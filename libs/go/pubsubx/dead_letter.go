package pubsubx

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type DeadLetterSource string

const (
	DeadLetterSourceInbox  DeadLetterSource = "INBOX"
	DeadLetterSourceOutbox DeadLetterSource = "OUTBOX"
)

type ReplayState string

const (
	ReplayStateQuarantined ReplayState = "QUARANTINED"
	ReplayStatePending     ReplayState = "PENDING"
	ReplayStateClaimed     ReplayState = "CLAIMED"
	ReplayStatePublished   ReplayState = "PUBLISHED"
	ReplayStateReplayed    ReplayState = "REPLAYED"
)

var (
	ErrDeadLetterNotFound = errors.New("dead-letter message not found")
	ErrReplayConflict     = errors.New("dead-letter replay idempotency conflict")
	ErrReplayInProgress   = errors.New("dead-letter replay is already in progress")
	ErrAlreadyReplayed    = errors.New("dead-letter message was already replayed")
	ErrNotReplayable      = errors.New("dead-letter message cannot be safely replayed")
	ErrReplayClaimLost    = errors.New("dead-letter replay claim lost")
)

// DeadLetter is private delivery metadata around the immutable generated
// envelope. It is never a replacement wire model.
type DeadLetter struct {
	ID                    string
	TenantID              string
	EventID               string
	Source                DeadLetterSource
	Consumer              string
	EventType             string
	EventVersion          uint32
	Attempts              uint32
	Reason                string
	PayloadDigest         string
	EnvelopeBytes         []byte
	Envelope              *commonv1.EventEnvelope
	CreatedAt             time.Time
	ReplayState           ReplayState
	ReplayGeneration      uint64
	ReplayDeliveryEpoch   uint64
	ReplayPublishAttempts uint32
	ReplayClaimExpiresAt  *time.Time
	ReplayNextAttemptAt   *time.Time
	ReplayRequestedAt     *time.Time
	ReplayPublishedAt     *time.Time
	ReplayedAt            *time.Time
	ReplayLastError       string
	DecodeError           error
}

type DeadLetterSink interface {
	Quarantine(DeadLetter) error
}

// ReplayCommand is authenticated behavior metadata. The immutable protobuf
// envelope remains the replay payload authority.
type ReplayCommand struct {
	TenantID       string
	DeadLetterID   string
	IdempotencyKey string
	RequestDigest  string
	RequestedBy    string
	RequestedAt    time.Time
}

type ReplayRequestResult struct {
	DeadLetter       *DeadLetter
	ReplayGeneration uint64
	IdempotentReplay bool
}

// DeadLetterSQLStore owns tenant-scoped replay state. Publishing remains an
// external effect performed by ReplayDispatcher after this transaction commits.
type DeadLetterSQLStore struct{ DB *sql.DB }

func (s DeadLetterSQLStore) RequestReplay(ctx context.Context, command ReplayCommand) (*ReplayRequestResult, error) {
	if err := validateReplayCommand(command); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, command.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	lockKey := "dead-letter-replay:" + command.TenantID + ":" + command.IdempotencyKey
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return nil, err
	}
	var existingID, existingDigest, existingActor string
	var existingGeneration uint64
	err = tx.QueryRowContext(ctx, `SELECT dead_letter_id,request_digest,requested_by,replay_generation FROM dead_letter_replay_receipts WHERE tenant_id=$1 AND idempotency_key=$2`, command.TenantID, command.IdempotencyKey).Scan(&existingID, &existingDigest, &existingActor, &existingGeneration)
	if err == nil {
		if existingID != command.DeadLetterID || existingActor != command.RequestedBy || subtle.ConstantTimeCompare([]byte(existingDigest), []byte(command.RequestDigest)) != 1 {
			return nil, ErrReplayConflict
		}
		value, loadErr := loadDeadLetterTx(ctx, tx, command.TenantID, command.DeadLetterID, false)
		if loadErr != nil {
			return nil, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, err
		}
		return &ReplayRequestResult{DeadLetter: value, ReplayGeneration: existingGeneration, IdempotentReplay: true}, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	value, err := loadDeadLetterTx(ctx, tx, command.TenantID, command.DeadLetterID, true)
	if err != nil {
		return nil, err
	}
	switch value.ReplayState {
	case ReplayStateQuarantined:
	case ReplayStateReplayed:
		return nil, ErrAlreadyReplayed
	default:
		return nil, ErrReplayInProgress
	}
	if err = validateReplayEnvelope(value); err != nil {
		return nil, err
	}
	if value.Source == DeadLetterSourceInbox && !validConsumerIdentity(value.Consumer) {
		return nil, fmt.Errorf("%w: inbox consumer identity was not retained", ErrNotReplayable)
	}
	if value.Source == DeadLetterSourceOutbox {
		result, updateErr := tx.ExecContext(ctx, `
UPDATE outbox_messages
SET quarantined_at=NULL, quarantine_reason='', claim_expires_at=NULL,
    publish_attempts=0, next_attempt_at=$3, last_error=''
WHERE tenant_id=$1 AND id=$2 AND delivered_at IS NULL AND quarantined_at IS NOT NULL
  AND event_type=$4 AND event_version=$5 AND payload_digest=$6 AND envelope_bytes=$7`,
			command.TenantID, value.EventID, command.RequestedAt.UTC(), value.EventType,
			value.EventVersion, value.PayloadDigest, value.EnvelopeBytes)
		if updateErr != nil {
			return nil, updateErr
		}
		updated, rowsErr := result.RowsAffected()
		if rowsErr != nil {
			return nil, rowsErr
		}
		if updated != 1 {
			return nil, fmt.Errorf("%w: quarantined outbox source is unavailable", ErrNotReplayable)
		}
	}
	var generation uint64
	if err = tx.QueryRowContext(ctx, `
UPDATE dead_letter_messages
SET replay_state='PENDING', replay_generation=replay_generation+1,
    replay_publish_attempts=0,
    replay_claim_expires_at=NULL, replay_next_attempt_at=$3,
    replay_requested_at=$3, replay_published_at=NULL, replayed_at=NULL,
    replay_last_error='', updated_at=$3
WHERE tenant_id=$1 AND id=$2 AND replay_state='QUARANTINED'
RETURNING replay_generation`, command.TenantID, command.DeadLetterID, command.RequestedAt.UTC()).Scan(&generation); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrReplayInProgress
		}
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `
INSERT INTO dead_letter_replay_receipts (
  tenant_id,idempotency_key,request_digest,dead_letter_id,replay_generation,
  requested_by,requested_at
) VALUES ($1,$2,$3,$4,$5,$6,$7)`, command.TenantID, command.IdempotencyKey, command.RequestDigest, command.DeadLetterID, generation, command.RequestedBy, command.RequestedAt.UTC()); err != nil {
		return nil, err
	}
	value, err = loadDeadLetterTx(ctx, tx, command.TenantID, command.DeadLetterID, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &ReplayRequestResult{DeadLetter: value, ReplayGeneration: generation}, nil
}

func (s DeadLetterSQLStore) ClaimInboxReplays(ctx context.Context, tenantID string, limit int, now time.Time, claimTTL time.Duration) ([]DeadLetter, error) {
	if limit < 1 || limit > 1000 || now.IsZero() || claimTTL < time.Second || claimTTL > 15*time.Minute {
		return nil, errors.New("dead-letter claim requires a bounded limit, server time, and claim TTL")
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	rows, err := tx.QueryContext(ctx, `
WITH candidates AS (
  SELECT message.id
  FROM dead_letter_messages AS message
  WHERE message.tenant_id=$1 AND message.source='INBOX'
    AND (
      (message.replay_state='PENDING' AND message.replay_next_attempt_at <= $2)
      OR
      (message.replay_state='CLAIMED' AND message.replay_claim_expires_at <= $2)
    )
  ORDER BY message.replay_next_attempt_at,message.created_at,message.id
  FOR UPDATE OF message SKIP LOCKED
  LIMIT $3
)
UPDATE dead_letter_messages AS message
SET replay_state='CLAIMED', replay_delivery_epoch=message.replay_delivery_epoch+1,
    replay_publish_attempts=message.replay_publish_attempts+1,
    replay_claim_expires_at=$4, replay_last_error='', updated_at=$2
FROM candidates
WHERE message.tenant_id=$1 AND message.id=candidates.id
RETURNING message.id,message.event_id,message.source,message.consumer,message.event_type,
          message.event_version,message.attempts,message.reason,message.payload_digest,
          message.envelope_bytes,message.created_at,message.replay_state,
          message.replay_generation,message.replay_delivery_epoch,
          message.replay_publish_attempts,message.replay_claim_expires_at,
          message.replay_next_attempt_at,message.replay_requested_at,
          message.replay_published_at,message.replayed_at,message.replay_last_error`, tenantID, now.UTC(), limit, now.UTC().Add(claimTTL))
	if err != nil {
		return nil, err
	}
	defer func() { _ = platformdb.CloseRows(rows) }()
	var result []DeadLetter
	for rows.Next() {
		value, scanErr := scanDeadLetter(rows, tenantID)
		if scanErr != nil {
			return nil, scanErr
		}
		decodeDeadLetter(value)
		result = append(result, *value)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return result, nil
}

func (s DeadLetterSQLStore) AcknowledgeInboxPublished(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	if id == "" || epoch == 0 || at.IsZero() {
		return false, errors.New("dead-letter publish acknowledgement requires identity, epoch, and time")
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := tx.ExecContext(ctx, `
UPDATE dead_letter_messages
SET replay_state='PUBLISHED', replay_claim_expires_at=NULL,
    replay_next_attempt_at=NULL, replay_published_at=$4,
    replay_last_error='', updated_at=$4
WHERE tenant_id=$1 AND id=$2 AND replay_delivery_epoch=$3
  AND source='INBOX' AND replay_state='CLAIMED'`, tenantID, id, epoch, at.UTC())
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if count == 0 {
		var state ReplayState
		var persistedEpoch uint64
		queryErr := tx.QueryRowContext(ctx, `SELECT replay_state,replay_delivery_epoch FROM dead_letter_messages WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&state, &persistedEpoch)
		if queryErr != nil && !errors.Is(queryErr, sql.ErrNoRows) {
			return false, queryErr
		}
		if queryErr == nil && persistedEpoch == epoch && state == ReplayStateReplayed {
			count = 1
		}
	}
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return count == 1, nil
}

func (s DeadLetterSQLStore) RetryInboxReplay(ctx context.Context, tenantID, id string, epoch uint64, nextAttempt time.Time, cause error) (bool, error) {
	if id == "" || epoch == 0 || nextAttempt.IsZero() || cause == nil {
		return false, errors.New("dead-letter retry requires identity, epoch, next attempt, and error")
	}
	return s.updateClaim(ctx, tenantID, id, epoch, `
UPDATE dead_letter_messages
SET replay_state='PENDING',replay_claim_expires_at=NULL,replay_next_attempt_at=$4,
    replay_last_error=$5,updated_at=clock_timestamp()
WHERE tenant_id=$1 AND id=$2 AND replay_delivery_epoch=$3
  AND source='INBOX' AND replay_state='CLAIMED'`, nextAttempt.UTC(), boundedDeliveryReason(cause))
}

func (s DeadLetterSQLStore) QuarantineInboxReplay(ctx context.Context, tenantID, id string, epoch uint64, at time.Time, cause error) (bool, error) {
	if id == "" || epoch == 0 || at.IsZero() || cause == nil {
		return false, errors.New("dead-letter requarantine requires identity, epoch, time, and error")
	}
	detail := boundedDeliveryReason(cause)
	return s.updateClaim(ctx, tenantID, id, epoch, `
UPDATE dead_letter_messages
SET replay_state='QUARANTINED',replay_claim_expires_at=NULL,replay_next_attempt_at=NULL,
    replay_published_at=NULL,replayed_at=NULL,replay_last_error=$5,reason=$5,updated_at=$4
WHERE tenant_id=$1 AND id=$2 AND replay_delivery_epoch=$3
  AND source='INBOX' AND replay_state='CLAIMED'`, at.UTC(), detail)
}

func (s DeadLetterSQLStore) updateClaim(ctx context.Context, tenantID, id string, epoch uint64, statement string, values ...any) (bool, error) {
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	arguments := []any{tenantID, id, epoch}
	arguments = append(arguments, values...)
	result, err := tx.ExecContext(ctx, statement, arguments...)
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return count == 1, nil
}

type DeadLetterReplayStore interface {
	ClaimInboxReplays(context.Context, string, int, time.Time, time.Duration) ([]DeadLetter, error)
	AcknowledgeInboxPublished(context.Context, string, string, uint64, time.Time) (bool, error)
	RetryInboxReplay(context.Context, string, string, uint64, time.Time, error) (bool, error)
	QuarantineInboxReplay(context.Context, string, string, uint64, time.Time, error) (bool, error)
}

type ReplayDispatcher struct {
	Store       DeadLetterReplayStore
	Publisher   Transport
	Now         func() time.Time
	ClaimTTL    time.Duration
	RetryDelay  func(uint32) time.Duration
	MaxAttempts uint32
}

func (d ReplayDispatcher) DeliverBatch(ctx context.Context, tenantID string, limit int) (int, error) {
	if d.Store == nil || d.Publisher == nil {
		return 0, errors.New("dead-letter replay dispatcher requires a store and publisher")
	}
	nowFn := d.Now
	if nowFn == nil {
		nowFn = time.Now
	}
	claimTTL := d.ClaimTTL
	if claimTTL == 0 {
		claimTTL = 30 * time.Second
	}
	maxAttempts := d.MaxAttempts
	if maxAttempts == 0 {
		maxAttempts = 10
	}
	if maxAttempts > 1000 {
		return 0, errors.New("dead-letter maximum replay attempts must not exceed 1000")
	}
	records, err := d.Store.ClaimInboxReplays(ctx, tenantID, limit, nowFn().UTC(), claimTTL)
	if err != nil {
		return 0, err
	}
	published := 0
	var failures []error
	for index := range records {
		record := &records[index]
		if record.DecodeError != nil || record.Envelope == nil {
			cause := record.DecodeError
			if cause == nil {
				cause = ErrInvalidEnvelope
			}
			updated, updateErr := d.Store.QuarantineInboxReplay(ctx, record.TenantID, record.ID, record.ReplayDeliveryEpoch, nowFn().UTC(), cause)
			failures = appendReplayUpdateError(failures, cause, updated, updateErr, record)
			continue
		}
		if publishErr := d.Publisher.Publish(ctx, record.Envelope); publishErr != nil {
			if record.ReplayPublishAttempts >= maxAttempts {
				updated, updateErr := d.Store.QuarantineInboxReplay(ctx, record.TenantID, record.ID, record.ReplayDeliveryEpoch, nowFn().UTC(), publishErr)
				failures = appendReplayUpdateError(failures, publishErr, updated, updateErr, record)
				continue
			}
			delay := defaultReplayRetryDelay(record.ReplayPublishAttempts)
			if d.RetryDelay != nil {
				delay = d.RetryDelay(record.ReplayPublishAttempts)
			}
			if delay < 0 || delay > 24*time.Hour {
				failures = append(failures, fmt.Errorf("dead-letter %s has invalid retry delay", record.ID))
				continue
			}
			updated, updateErr := d.Store.RetryInboxReplay(ctx, record.TenantID, record.ID, record.ReplayDeliveryEpoch, nowFn().UTC().Add(delay), publishErr)
			failures = appendReplayUpdateError(failures, publishErr, updated, updateErr, record)
			continue
		}
		acknowledged, ackErr := d.Store.AcknowledgeInboxPublished(ctx, record.TenantID, record.ID, record.ReplayDeliveryEpoch, nowFn().UTC())
		switch {
		case ackErr != nil:
			failures = append(failures, ackErr)
		case !acknowledged:
			failures = append(failures, fmt.Errorf("%w: publish %s@%d", ErrReplayClaimLost, record.ID, record.ReplayDeliveryEpoch))
		default:
			published++
		}
	}
	return published, errors.Join(failures...)
}

func appendReplayUpdateError(failures []error, cause error, updated bool, updateErr error, record *DeadLetter) []error {
	switch {
	case updateErr != nil:
		return append(failures, errors.Join(cause, updateErr))
	case !updated:
		return append(failures, fmt.Errorf("%w: update %s@%d", ErrReplayClaimLost, record.ID, record.ReplayDeliveryEpoch))
	default:
		return append(failures, cause)
	}
}

// CompleteInboxReplayTx marks the replay terminal in the same transaction as
// the inbox receipt and business mutation.
func CompleteInboxReplayTx(ctx context.Context, tx *sql.Tx, tenantID, consumer, eventID string, at time.Time) error {
	if tx == nil || !validConsumerIdentity(consumer) || eventID == "" || at.IsZero() {
		return errors.New("complete inbox replay requires transaction, identity, and time")
	}
	_, err := tx.ExecContext(ctx, `
UPDATE dead_letter_messages
SET replay_state='REPLAYED',replay_claim_expires_at=NULL,replay_next_attempt_at=NULL,
    replayed_at=$4,replay_last_error='',updated_at=$4
WHERE tenant_id=$1 AND id=$2 AND event_id=$3 AND source='INBOX'
  AND consumer=$5 AND replay_state IN ('CLAIMED','PUBLISHED')`, tenantID, InboxDeadLetterID(tenantID, consumer, eventID), eventID, at.UTC(), consumer)
	return err
}

// CompleteOutboxReplayTx marks replay evidence terminal atomically with the
// authoritative outbox delivery acknowledgement.
func CompleteOutboxReplayTx(ctx context.Context, tx *sql.Tx, tenantID, eventID string, at time.Time) error {
	if tx == nil || eventID == "" || at.IsZero() {
		return errors.New("complete outbox replay requires transaction, identity, and time")
	}
	_, err := tx.ExecContext(ctx, `
UPDATE dead_letter_messages
SET replay_state='REPLAYED',replay_claim_expires_at=NULL,replay_next_attempt_at=NULL,
    replayed_at=$3,replay_last_error='',updated_at=$3
WHERE tenant_id=$1 AND id='outbox:' || $2 AND event_id=$2 AND source='OUTBOX'
  AND replay_state='PENDING'`, tenantID, eventID, at.UTC())
	return err
}

func InboxDeadLetterID(tenantID, consumer, eventID string) string {
	digest := sha256.Sum256([]byte(tenantID + "\x00" + consumer + "\x00" + eventID))
	return "inbox:" + hex.EncodeToString(digest[:])
}

func validateReplayCommand(command ReplayCommand) error {
	if err := platformdb.ValidateTenantID(command.TenantID); err != nil {
		return err
	}
	if command.DeadLetterID == "" || len(command.DeadLetterID) > 512 || command.IdempotencyKey == "" || len(command.IdempotencyKey) > 255 ||
		command.RequestedBy == "" || len(command.RequestedBy) > 255 || command.RequestedAt.IsZero() ||
		strings.TrimSpace(command.DeadLetterID) != command.DeadLetterID || strings.TrimSpace(command.IdempotencyKey) != command.IdempotencyKey ||
		strings.TrimSpace(command.RequestedBy) != command.RequestedBy || strings.ContainsAny(command.DeadLetterID+command.IdempotencyKey+command.RequestedBy, "\x00\r\n") ||
		len(command.RequestDigest) != 71 || !strings.HasPrefix(command.RequestDigest, "sha256:") || command.RequestDigest != strings.ToLower(command.RequestDigest) {
		return ErrNotReplayable
	}
	if _, err := hex.DecodeString(strings.TrimPrefix(command.RequestDigest, "sha256:")); err != nil {
		return ErrNotReplayable
	}
	return nil
}

func loadDeadLetterTx(ctx context.Context, tx *sql.Tx, tenantID, id string, lock bool) (*DeadLetter, error) {
	statement := `
SELECT id,event_id,source,COALESCE(consumer,''),event_type,event_version,attempts,
       reason,payload_digest,envelope_bytes,created_at,replay_state,
       replay_generation,replay_delivery_epoch,replay_publish_attempts,
       replay_claim_expires_at,replay_next_attempt_at,replay_requested_at,
       replay_published_at,replayed_at,replay_last_error
FROM dead_letter_messages WHERE tenant_id=$1 AND id=$2`
	if lock {
		statement += " FOR UPDATE"
	}
	value, err := scanDeadLetter(tx.QueryRowContext(ctx, statement, tenantID, id), tenantID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrDeadLetterNotFound
	}
	if err != nil {
		return nil, err
	}
	decodeDeadLetter(value)
	return value, nil
}

type rowScanner interface {
	Scan(...any) error
}

func scanDeadLetter(row rowScanner, tenantID string) (*DeadLetter, error) {
	value := &DeadLetter{TenantID: tenantID}
	var claimExpiresAt, nextAttemptAt, requestedAt, publishedAt, replayedAt sql.NullTime
	if err := row.Scan(
		&value.ID, &value.EventID, &value.Source, &value.Consumer, &value.EventType,
		&value.EventVersion, &value.Attempts, &value.Reason, &value.PayloadDigest,
		&value.EnvelopeBytes, &value.CreatedAt, &value.ReplayState,
		&value.ReplayGeneration, &value.ReplayDeliveryEpoch, &value.ReplayPublishAttempts,
		&claimExpiresAt, &nextAttemptAt, &requestedAt, &publishedAt, &replayedAt,
		&value.ReplayLastError,
	); err != nil {
		return nil, err
	}
	value.ReplayClaimExpiresAt = nullableTime(claimExpiresAt)
	value.ReplayNextAttemptAt = nullableTime(nextAttemptAt)
	value.ReplayRequestedAt = nullableTime(requestedAt)
	value.ReplayPublishedAt = nullableTime(publishedAt)
	value.ReplayedAt = nullableTime(replayedAt)
	return value, nil
}

func decodeDeadLetter(value *DeadLetter) {
	value.Envelope, value.DecodeError = UnmarshalEnvelope(value.EnvelopeBytes)
	if value.DecodeError == nil {
		value.DecodeError = validateReplayEnvelope(value)
	}
}

func validateReplayEnvelope(value *DeadLetter) error {
	if value == nil || value.Envelope == nil {
		return fmt.Errorf("%w: immutable envelope is invalid", ErrNotReplayable)
	}
	envelope := value.Envelope
	if envelope.GetTenantId() != value.TenantID || envelope.GetEventId() != value.EventID || envelope.GetEventType() != value.EventType ||
		envelope.GetEventVersion() != value.EventVersion || envelope.GetPayloadDigest() != value.PayloadDigest {
		return fmt.Errorf("%w: normalized dead-letter identity differs from its envelope", ErrNotReplayable)
	}
	if value.Source != DeadLetterSourceInbox && value.Source != DeadLetterSourceOutbox {
		return fmt.Errorf("%w: unknown dead-letter source", ErrNotReplayable)
	}
	return nil
}

func nullableTime(value sql.NullTime) *time.Time {
	if !value.Valid {
		return nil
	}
	at := value.Time.UTC()
	return &at
}

func boundedDeliveryReason(cause error) string {
	detail := cause.Error()
	if len(detail) > 2048 {
		detail = detail[:2048]
	}
	return detail
}

func defaultReplayRetryDelay(attempt uint32) time.Duration {
	if attempt == 0 {
		attempt = 1
	}
	shift := attempt - 1
	if shift > 8 {
		shift = 8
	}
	return time.Second * (1 << shift)
}

func validConsumerIdentity(value string) bool {
	return value != "" && len(value) <= 255 && strings.TrimSpace(value) == value && !strings.ContainsRune(value, '\x00')
}
