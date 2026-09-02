package inbox

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	gcppubsub "cloud.google.com/go/pubsub/v2"
	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

type Store struct {
	mu   sync.Mutex
	seen map[string]struct{}
}

const DefaultMaxDeliveryAttempts uint32 = 10

var ErrInvalidConsumer = errors.New("inbox consumer identity is invalid")

// TransactionalHandler applies the business mutation inside the same
// tenant-scoped PostgreSQL transaction as the inbox receipt. Implementations
// must not perform external side effects; those belong in their own outbox.
type TransactionalHandler interface {
	HandleEvent(context.Context, *sql.Tx, *commonv1.EventEnvelope, proto.Message) error
}

type TransactionalHandlerFunc func(context.Context, *sql.Tx, *commonv1.EventEnvelope, proto.Message) error

func (f TransactionalHandlerFunc) HandleEvent(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, payload proto.Message) error {
	return f(ctx, tx, envelope, payload)
}

type DeliveryDisposition uint8

const (
	DeliveryNack DeliveryDisposition = iota
	DeliveryAck
)

// Processor validates one transport delivery, tracks attempts durably, and
// invokes a generated-payload handler with atomic inbox deduplication.
type Processor struct {
	DB                 *sql.DB
	Consumer           string
	Handler            TransactionalHandler
	AcceptedEvents     map[string]uint32
	MaxAttempts        uint32
	QuarantineTenantID string
}

// PubSubConsumer is the production pull subscriber. Callback processing is
// synchronous so Pub/Sub flow control and ack-deadline extension cover the
// entire PostgreSQL transaction.
type PubSubConsumer struct {
	subscriber *gcppubsub.Subscriber
	processor  Processor
	OnError    func(context.Context, error)
}

func NewPubSubConsumer(client *gcppubsub.Client, subscription string, processor Processor) (*PubSubConsumer, error) {
	if client == nil || subscription == "" || strings.TrimSpace(subscription) != subscription || strings.ContainsAny(subscription, "\x00\r\n") {
		return nil, errors.New("Pub/Sub client and bounded subscription identity are required")
	}
	if err := processor.validate(); err != nil {
		return nil, err
	}
	processor.AcceptedEvents = cloneAcceptedEvents(processor.AcceptedEvents)
	subscriber := client.Subscriber(subscription)
	subscriber.ReceiveSettings.MaxExtension = 10 * time.Minute
	subscriber.ReceiveSettings.MaxDurationPerAckExtension = 60 * time.Second
	subscriber.ReceiveSettings.MaxOutstandingMessages = 64
	subscriber.ReceiveSettings.MaxOutstandingBytes = 64 << 20
	subscriber.ReceiveSettings.EnablePerStreamFlowControl = true
	subscriber.ReceiveSettings.NumGoroutines = 1
	return &PubSubConsumer{subscriber: subscriber, processor: processor}, nil
}

func (s *PubSubConsumer) Receive(ctx context.Context) error {
	if s == nil || s.subscriber == nil {
		return errors.New("Pub/Sub consumer is not initialized")
	}
	return s.subscriber.Receive(ctx, func(deliveryContext context.Context, message *gcppubsub.Message) {
		disposition, err := s.processor.ProcessDelivery(deliveryContext, message.Data, message.Attributes, message.OrderingKey)
		if err != nil && s.OnError != nil {
			s.OnError(deliveryContext, err)
		}
		if disposition == DeliveryAck {
			message.Ack()
			return
		}
		message.Nack()
	})
}

func (p Processor) validate() error {
	if p.DB == nil || p.Handler == nil {
		return errors.New("inbox processor requires a database and transactional handler")
	}
	if !validConsumer(p.Consumer) {
		return ErrInvalidConsumer
	}
	if len(p.AcceptedEvents) == 0 {
		return errors.New("inbox processor requires an explicit registered event allowlist")
	}
	for fullName, version := range p.AcceptedEvents {
		registration, ok := queue.RegisteredEvent(fullName, version)
		if fullName == "" || version == 0 || !ok || registration.LifecycleState != "active" {
			return fmt.Errorf("inbox processor event allowlist contains inactive or unknown identity %s@%d", fullName, version)
		}
	}
	if p.MaxAttempts > 1000 {
		return errors.New("inbox maximum attempts must not exceed 1000")
	}
	if err := platformdb.ValidateTenantID(p.QuarantineTenantID); err != nil {
		return fmt.Errorf("inbox processor requires a trusted quarantine tenant: %w", err)
	}
	return nil
}

func (p Processor) maximumAttempts() uint32 {
	if p.MaxAttempts == 0 {
		return DefaultMaxDeliveryAttempts
	}
	return p.MaxAttempts
}

func (p Processor) ProcessDelivery(ctx context.Context, encoded []byte, attributes map[string]string, orderingKey string) (DeliveryDisposition, error) {
	if err := p.validate(); err != nil {
		return DeliveryNack, err
	}
	envelope, err := queue.UnmarshalEnvelope(encoded)
	if err != nil {
		if quarantineErr := quarantineInboxSQL(ctx, p.DB, p.Consumer, nil, p.QuarantineTenantID, encoded, 1, err); quarantineErr != nil {
			return DeliveryNack, errors.Join(err, quarantineErr)
		}
		return DeliveryAck, fmt.Errorf("quarantined unreadable Pub/Sub envelope: %w", err)
	}
	if err = queue.ValidateTransportAttributes(envelope, attributes, orderingKey); err != nil {
		if quarantineErr := quarantineInboxSQL(ctx, p.DB, p.Consumer, envelope, "", encoded, 1, err); quarantineErr != nil {
			return DeliveryNack, errors.Join(err, quarantineErr)
		}
		return DeliveryAck, fmt.Errorf("quarantined transport/envelope mismatch: %w", err)
	}
	acceptedVersion, allowlisted := p.AcceptedEvents[envelope.GetEventType()]
	if !allowlisted || acceptedVersion != envelope.GetEventVersion() {
		// Pub/Sub subscriptions should filter by the immutable event_type and
		// event_version attributes. This defense-in-depth acknowledgement keeps
		// a misconfigured subscription from poisoning a specialized consumer;
		// other subscriptions retain their independent delivery.
		return DeliveryAck, nil
	}
	payload, err := queue.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		if quarantineErr := quarantineInboxSQL(ctx, p.DB, p.Consumer, envelope, "", encoded, 1, err); quarantineErr != nil {
			return DeliveryNack, errors.Join(err, quarantineErr)
		}
		return DeliveryAck, fmt.Errorf("quarantined invalid registered payload: %w", err)
	}
	attempt, duplicate, err := registerAttemptSQL(ctx, p.DB, p.Consumer, envelope)
	if err != nil {
		return DeliveryNack, err
	}
	if duplicate {
		return DeliveryAck, nil
	}
	accepted, err := AcceptAndHandleSQL(ctx, p.DB, p.Consumer, envelope, payload, p.Handler)
	if err == nil {
		if !accepted {
			return DeliveryAck, nil
		}
		return DeliveryAck, nil
	}
	if detailErr := recordFailureDetailSQL(ctx, p.DB, p.Consumer, envelope, err); detailErr != nil {
		err = errors.Join(err, fmt.Errorf("record inbox failure detail: %w", detailErr))
	}
	if attempt < p.maximumAttempts() {
		return DeliveryNack, fmt.Errorf("process event %s attempt %d/%d: %w", envelope.GetEventId(), attempt, p.maximumAttempts(), err)
	}
	if quarantineErr := quarantineInboxSQL(ctx, p.DB, p.Consumer, envelope, "", encoded, attempt, err); quarantineErr != nil {
		return DeliveryNack, errors.Join(err, quarantineErr)
	}
	return DeliveryAck, fmt.Errorf("quarantined event %s after %d attempts: %w", envelope.GetEventId(), attempt, err)
}

// AcceptSQL validates the authoritative registry identity and atomically
// deduplicates an at-least-once event for one tenant-scoped consumer.
func AcceptSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope) (bool, error) {
	payload, err := queue.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		return false, err
	}
	return AcceptAndHandleSQL(ctx, db, consumer, envelope, payload, nil)
}

// AcceptAndHandleSQL commits the deduplication receipt and business mutation
// together. A handler error or process crash rolls both back, while a crash
// after commit is converted to a duplicate acknowledgement on redelivery.
func AcceptAndHandleSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope, payload proto.Message, handler TransactionalHandler) (bool, error) {
	if !validConsumer(consumer) {
		return false, ErrInvalidConsumer
	}
	authoritativePayload, err := queue.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		return false, err
	}
	if payload == nil || !proto.Equal(authoritativePayload, payload) {
		return false, queue.ErrInvalidEnvelope
	}
	tx, err := platformdb.BeginTenantTx(ctx, db, envelope.GetTenantId(), nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := tx.ExecContext(ctx, `INSERT INTO inbox_messages (consumer, event_id, tenant_id, event_type, event_version, received_at) VALUES ($1,$2,$3,$4,$5,now()) ON CONFLICT (tenant_id, consumer, event_id) DO NOTHING`, consumer, envelope.GetEventId(), envelope.GetTenantId(), envelope.GetEventType(), envelope.GetEventVersion())
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if count == 0 {
		if _, err = tx.ExecContext(ctx, `DELETE FROM inbox_delivery_failures WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, envelope.GetTenantId(), consumer, envelope.GetEventId()); err != nil {
			return false, err
		}
		if err = queue.CompleteInboxReplayTx(ctx, tx, envelope.GetTenantId(), consumer, envelope.GetEventId(), time.Now().UTC()); err != nil {
			return false, err
		}
		if err = tx.Commit(); err != nil {
			return false, err
		}
		return false, nil
	}
	if handler != nil {
		if err = handler.HandleEvent(ctx, tx, envelope, authoritativePayload); err != nil {
			return false, err
		}
	}
	if err = queue.CompleteInboxReplayTx(ctx, tx, envelope.GetTenantId(), consumer, envelope.GetEventId(), time.Now().UTC()); err != nil {
		return false, err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM inbox_delivery_failures WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, envelope.GetTenantId(), consumer, envelope.GetEventId()); err != nil {
		return false, err
	}
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return true, nil
}

func registerAttemptSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope) (uint32, bool, error) {
	tx, err := platformdb.BeginTenantTx(ctx, db, envelope.GetTenantId(), nil)
	if err != nil {
		return 0, false, err
	}
	defer func() { _ = tx.Rollback() }()
	var alreadyProcessed bool
	if err = tx.QueryRowContext(ctx, `
SELECT EXISTS (
  SELECT 1 FROM inbox_messages
  WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3
) OR EXISTS (
  SELECT 1 FROM dead_letter_messages
  WHERE tenant_id=$1 AND id=$4
    AND replay_state IN ('QUARANTINED','PENDING','REPLAYED')
)`, envelope.GetTenantId(), consumer, envelope.GetEventId(), queue.InboxDeadLetterID(envelope.GetTenantId(), consumer, envelope.GetEventId())).Scan(&alreadyProcessed); err != nil {
		return 0, false, err
	}
	if alreadyProcessed {
		if _, err = tx.ExecContext(ctx, `DELETE FROM inbox_delivery_failures WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, envelope.GetTenantId(), consumer, envelope.GetEventId()); err != nil {
			return 0, false, err
		}
		if err = tx.Commit(); err != nil {
			return 0, false, err
		}
		return 0, true, nil
	}
	var attempts uint32
	err = tx.QueryRowContext(ctx, `
INSERT INTO inbox_delivery_failures (tenant_id,consumer,event_id,event_type,event_version,attempts,last_error,updated_at)
VALUES ($1,$2,$3,$4,$5,1,'',now())
ON CONFLICT (tenant_id,consumer,event_id) DO UPDATE
SET attempts=inbox_delivery_failures.attempts+1, updated_at=EXCLUDED.updated_at
RETURNING attempts`, envelope.GetTenantId(), consumer, envelope.GetEventId(), envelope.GetEventType(), envelope.GetEventVersion()).Scan(&attempts)
	if err != nil {
		return 0, false, err
	}
	if err = tx.Commit(); err != nil {
		return 0, false, err
	}
	return attempts, false, nil
}

func recordFailureDetailSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope, cause error) error {
	detail := boundedReason(cause)
	tx, err := platformdb.BeginTenantTx(ctx, db, envelope.GetTenantId(), nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err = tx.ExecContext(ctx, `UPDATE inbox_delivery_failures SET last_error=$4,updated_at=now() WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, envelope.GetTenantId(), consumer, envelope.GetEventId(), detail); err != nil {
		return err
	}
	return tx.Commit()
}

func quarantineInboxSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope, quarantineTenantID string, encoded []byte, attempts uint32, cause error) error {
	if !validConsumer(consumer) || attempts == 0 || cause == nil {
		return errors.New("inbox quarantine requires consumer, attempts, and error")
	}
	contentDigest := sha256.Sum256(encoded)
	tenantID := quarantineTenantID
	eventID := "unreadable:" + hex.EncodeToString(contentDigest[:])
	eventType := "mindclade.invalid.UnreadableEnvelope"
	eventVersion := uint32(1)
	payloadDigest := "sha256:" + hex.EncodeToString(contentDigest[:])
	if envelope != nil {
		tenantID, eventID, eventType = envelope.GetTenantId(), envelope.GetEventId(), envelope.GetEventType()
		eventVersion, payloadDigest = envelope.GetEventVersion(), envelope.GetPayloadDigest()
	}
	if err := platformdb.ValidateTenantID(tenantID); err != nil {
		return fmt.Errorf("cannot quarantine delivery without a trusted tenant identity: %w", err)
	}
	tx, err := platformdb.BeginTenantTx(ctx, db, tenantID, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	_, err = tx.ExecContext(ctx, `
INSERT INTO dead_letter_messages (id,tenant_id,event_id,source,consumer,event_type,event_version,attempts,reason,payload_digest,envelope_bytes,created_at)
VALUES ($1,$2,$3,'INBOX',$4,$5,$6,$7,$8,$9,$10,now())
ON CONFLICT (tenant_id,id) DO UPDATE
SET attempts=GREATEST(dead_letter_messages.attempts,EXCLUDED.attempts),
    reason=EXCLUDED.reason,payload_digest=EXCLUDED.payload_digest,
    envelope_bytes=EXCLUDED.envelope_bytes,created_at=EXCLUDED.created_at,
    consumer=EXCLUDED.consumer,replay_state='QUARANTINED',
    replay_claim_expires_at=NULL,replay_next_attempt_at=NULL,
    replay_published_at=NULL,replayed_at=NULL,replay_last_error='',updated_at=now()`,
		queue.InboxDeadLetterID(tenantID, consumer, eventID), tenantID, eventID, consumer, eventType, eventVersion, attempts, boundedReason(cause), payloadDigest, encoded)
	if err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM inbox_delivery_failures WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, tenantID, consumer, eventID); err != nil {
		return err
	}
	return tx.Commit()
}

func boundedReason(cause error) string {
	detail := cause.Error()
	if len(detail) > 2048 {
		detail = detail[:2048]
	}
	return detail
}

func validConsumer(value string) bool {
	return value != "" && len(value) <= 255 && strings.TrimSpace(value) == value && !strings.ContainsRune(value, '\x00')
}

func cloneAcceptedEvents(source map[string]uint32) map[string]uint32 {
	result := make(map[string]uint32, len(source))
	for fullName, version := range source {
		result[fullName] = version
	}
	return result
}

func NewStore() *Store { return &Store{seen: make(map[string]struct{})} }

// Accept returns false for an invalid or already committed delivery.
func (s *Store) Accept(consumer string, envelope *commonv1.EventEnvelope) bool {
	if consumer == "" || queue.ValidateEnvelope(envelope) != nil {
		return false
	}
	key := consumer + "\x00" + envelope.GetTenantId() + "\x00" + envelope.GetEventId()
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.seen[key]; ok {
		return false
	}
	s.seen[key] = struct{}{}
	return true
}
