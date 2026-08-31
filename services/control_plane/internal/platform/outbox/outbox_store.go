package outbox

import (
	"context"
	"database/sql"
	"sync"
	"time"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
	"google.golang.org/protobuf/proto"
)

type SQLStore struct{ DB *sql.DB }

// ClaimSQL uses row locks and SKIP LOCKED so concurrent dispatchers cannot
// share a delivery epoch. The database stores immutable envelope bytes while
// delivery metadata stays in normalized columns.
func (s SQLStore) ClaimSQL(ctx context.Context, limit int) ([]DeliveryRecord, error) {
	rows, err := s.DB.QueryContext(ctx, `
WITH candidates AS (
  SELECT id FROM outbox_messages WHERE delivered_at IS NULL ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT $1
)
UPDATE outbox_messages AS message SET delivery_epoch = message.delivery_epoch + 1
FROM candidates WHERE message.id = candidates.id
RETURNING message.envelope_bytes, message.delivery_epoch`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var records []DeliveryRecord
	for rows.Next() {
		var encoded []byte
		var record DeliveryRecord
		if err := rows.Scan(&encoded, &record.DeliveryEpoch); err != nil {
			return nil, err
		}
		record.Envelope, err = queue.UnmarshalEnvelope(encoded)
		if err != nil {
			return nil, err
		}
		records = append(records, record)
	}
	return records, rows.Err()
}

// AcknowledgeSQL is a compare-and-swap on the claimed delivery epoch.
func (s SQLStore) AcknowledgeSQL(ctx context.Context, id string, epoch uint64) (bool, error) {
	result, err := s.DB.ExecContext(ctx, `UPDATE outbox_messages SET delivered_at = now() WHERE id = $1 AND delivery_epoch = $2 AND delivered_at IS NULL`, id, epoch)
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	return count == 1, err
}

// DeliveryRecord is adapter metadata around the generated envelope, not an
// independent wire contract.
type DeliveryRecord struct {
	Envelope      *commonv1.EventEnvelope
	DeliveryEpoch uint64
	DeliveredAt   *time.Time
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
	s.records[record.Envelope.GetEventId()] = cloneRecord(record)
	return nil
}

func (s *Store) Claim(id string) (DeliveryRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	record, ok := s.records[id]
	if !ok || record.DeliveredAt != nil {
		return DeliveryRecord{}, false
	}
	record.DeliveryEpoch++
	s.records[id] = record
	return cloneRecord(record), true
}

func (s *Store) MarkDelivered(id string, epoch uint64, at time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	record, ok := s.records[id]
	if !ok || record.DeliveryEpoch != epoch || record.DeliveredAt != nil {
		return false
	}
	at = at.UTC()
	record.DeliveredAt = &at
	s.records[id] = record
	return true
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
