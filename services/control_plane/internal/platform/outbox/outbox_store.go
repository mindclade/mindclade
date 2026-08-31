package outbox

import (
	"context"
	"database/sql"
	"errors"
	"sort"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

type SQLStore struct{ DB *sql.DB }

// ClaimSQL uses row locks, SKIP LOCKED, and an expiring claim so concurrent or
// crashed dispatchers cannot share a delivery epoch indefinitely.
func (s SQLStore) ClaimSQL(ctx context.Context, tenantID string, limit int, now time.Time, claimTTL time.Duration) ([]DeliveryRecord, error) {
	if limit < 1 || limit > 1000 || now.IsZero() || claimTTL < time.Second || claimTTL > 15*time.Minute {
		return nil, errors.New("outbox claim requires a bounded limit, server time, and claim TTL")
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	rows, err := tx.QueryContext(ctx, `
WITH candidates AS (
  SELECT id
  FROM outbox_messages
  WHERE tenant_id = $1
    AND delivered_at IS NULL
    AND next_attempt_at <= $2
    AND (claim_expires_at IS NULL OR claim_expires_at <= $2)
  ORDER BY next_attempt_at, created_at, id
  FOR UPDATE SKIP LOCKED
  LIMIT $3
)
UPDATE outbox_messages AS message
SET delivery_epoch = message.delivery_epoch + 1,
    publish_attempts = message.publish_attempts + 1,
    claim_expires_at = $4,
    last_error = ''
FROM candidates
WHERE message.tenant_id = $1 AND message.id = candidates.id
RETURNING message.id, message.envelope_bytes, message.delivery_epoch,
          message.publish_attempts, message.claim_expires_at`,
		tenantID, now.UTC(), limit, now.UTC().Add(claimTTL))
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var records []DeliveryRecord
	for rows.Next() {
		var encoded []byte
		var record DeliveryRecord
		if scanErr := rows.Scan(&record.ID, &encoded, &record.DeliveryEpoch, &record.PublishAttempts, &record.ClaimExpiresAt); scanErr != nil {
			return nil, scanErr
		}
		record.Envelope, err = queue.UnmarshalEnvelope(encoded)
		if err != nil {
			return nil, err
		}
		if record.Envelope.GetTenantId() != tenantID || record.Envelope.GetEventId() != record.ID {
			return nil, errors.New("outbox normalized identity does not match immutable envelope")
		}
		record.TenantID = tenantID
		records = append(records, record)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return records, nil
}

// AcknowledgeSQL is a compare-and-swap on the claimed delivery epoch.
func (s SQLStore) AcknowledgeSQL(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := tx.ExecContext(ctx, `UPDATE outbox_messages SET delivered_at = $4, claim_expires_at = NULL, last_error = '' WHERE tenant_id = $1 AND id = $2 AND delivery_epoch = $3 AND delivered_at IS NULL`, tenantID, id, epoch, at.UTC())
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

func (s SQLStore) RetrySQL(ctx context.Context, tenantID, id string, epoch uint64, nextAttempt time.Time, publishErr error) (bool, error) {
	if publishErr == nil || nextAttempt.IsZero() {
		return false, errors.New("outbox retry requires an error and next attempt time")
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, tenantID, nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	detail := publishErr.Error()
	if len(detail) > 2048 {
		detail = detail[:2048]
	}
	result, err := tx.ExecContext(ctx, `UPDATE outbox_messages SET claim_expires_at = NULL, next_attempt_at = $4, last_error = $5 WHERE tenant_id = $1 AND id = $2 AND delivery_epoch = $3 AND delivered_at IS NULL`, tenantID, id, epoch, nextAttempt.UTC(), detail)
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

func (s SQLStore) Claim(ctx context.Context, tenantID string, limit int, now time.Time, claimTTL time.Duration) ([]DeliveryRecord, error) {
	return s.ClaimSQL(ctx, tenantID, limit, now, claimTTL)
}

func (s SQLStore) Acknowledge(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	return s.AcknowledgeSQL(ctx, tenantID, id, epoch, at)
}

func (s SQLStore) Retry(ctx context.Context, tenantID, id string, epoch uint64, nextAttempt time.Time, publishErr error) (bool, error) {
	return s.RetrySQL(ctx, tenantID, id, epoch, nextAttempt, publishErr)
}

// DeliveryRecord is adapter metadata around the generated envelope, not an
// independent wire contract.
type DeliveryRecord struct {
	ID              string
	TenantID        string
	Envelope        *commonv1.EventEnvelope
	DeliveryEpoch   uint64
	PublishAttempts uint32
	ClaimExpiresAt  time.Time
	NextAttemptAt   time.Time
	DeliveredAt     *time.Time
}

type Store struct {
	mu      sync.Mutex
	records map[string]DeliveryRecord
}

func NewStore() *Store { return &Store{records: make(map[string]DeliveryRecord)} }

func (s *Store) Insert(record DeliveryRecord) error {
	if err := queue.ValidateEnvelope(record.Envelope); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	record.ID = record.Envelope.GetEventId()
	record.TenantID = record.Envelope.GetTenantId()
	if record.NextAttemptAt.IsZero() {
		record.NextAttemptAt = time.Now().UTC()
	}
	s.records[record.TenantID+"\x00"+record.ID] = cloneRecord(record)
	return nil
}

func (s *Store) Pending() []DeliveryRecord {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]DeliveryRecord, 0, len(s.records))
	for _, record := range s.records {
		if record.DeliveredAt == nil {
			result = append(result, cloneRecord(record))
		}
	}
	return result
}

func (s *Store) Claim(_ context.Context, tenantID string, limit int, now time.Time, claimTTL time.Duration) ([]DeliveryRecord, error) {
	if tenantID == "" || limit < 1 || now.IsZero() || claimTTL < time.Second {
		return nil, errors.New("invalid in-memory outbox claim")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	keys := make([]string, 0, len(s.records))
	for key := range s.records {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	result := make([]DeliveryRecord, 0, limit)
	for _, key := range keys {
		if len(result) == limit {
			break
		}
		record := s.records[key]
		if record.TenantID != tenantID || record.DeliveredAt != nil || now.UTC().Before(record.NextAttemptAt) || (!record.ClaimExpiresAt.IsZero() && now.UTC().Before(record.ClaimExpiresAt)) {
			continue
		}
		record.DeliveryEpoch++
		record.PublishAttempts++
		record.ClaimExpiresAt = now.UTC().Add(claimTTL)
		s.records[key] = record
		result = append(result, cloneRecord(record))
	}
	return result, nil
}

func (s *Store) Acknowledge(_ context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := tenantID + "\x00" + id
	record, ok := s.records[key]
	if !ok || record.DeliveredAt != nil || record.DeliveryEpoch != epoch {
		return false, nil
	}
	value := at.UTC()
	record.DeliveredAt = &value
	record.ClaimExpiresAt = time.Time{}
	s.records[key] = record
	return true, nil
}

func (s *Store) Retry(_ context.Context, tenantID, id string, epoch uint64, nextAttempt time.Time, publishErr error) (bool, error) {
	if publishErr == nil {
		return false, errors.New("retry error is required")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	key := tenantID + "\x00" + id
	record, ok := s.records[key]
	if !ok || record.DeliveredAt != nil || record.DeliveryEpoch != epoch {
		return false, nil
	}
	record.ClaimExpiresAt = time.Time{}
	record.NextAttemptAt = nextAttempt.UTC()
	s.records[key] = record
	return true, nil
}

func cloneRecord(record DeliveryRecord) DeliveryRecord {
	result := record
	if record.Envelope != nil {
		result.Envelope = proto.Clone(record.Envelope).(*commonv1.EventEnvelope)
	}
	if record.DeliveredAt != nil {
		at := *record.DeliveredAt
		result.DeliveredAt = &at
	}
	return result
}
