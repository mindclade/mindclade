package outbox

import (
	"context"
	"database/sql"
	"sync"
	"time"
)

type SQLStore struct{ DB *sql.DB }

// ClaimSQL uses row locks and SKIP LOCKED so concurrent dispatchers cannot share a delivery epoch.
func (s SQLStore) ClaimSQL(ctx context.Context, limit int) ([]Message, error) {
	rows, err := s.DB.QueryContext(ctx, `
WITH candidates AS (
  SELECT id FROM outbox_messages WHERE delivered_at IS NULL ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT $1
)
UPDATE outbox_messages AS message SET delivery_epoch = message.delivery_epoch + 1
FROM candidates WHERE message.id = candidates.id
RETURNING message.id, message.tenant_id, message.event_type, message.payload_digest, message.delivery_epoch`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var messages []Message
	for rows.Next() {
		var message Message
		if err := rows.Scan(&message.ID, &message.TenantID, &message.EventType, &message.PayloadDigest, &message.DeliveryEpoch); err != nil {
			return nil, err
		}
		messages = append(messages, message)
	}
	return messages, rows.Err()
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

type Message struct {
	ID            string
	TenantID      string
	EventType     string
	PayloadDigest string
	DeliveryEpoch uint64
	DeliveredAt   *time.Time
}

type Store struct {
	mu       sync.Mutex
	messages map[string]Message
}

func NewStore() *Store { return &Store{messages: make(map[string]Message)} }

func (s *Store) Insert(message Message) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.messages[message.ID] = message
}

func (s *Store) Claim(id string) (Message, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	message, ok := s.messages[id]
	if !ok || message.DeliveredAt != nil {
		return Message{}, false
	}
	message.DeliveryEpoch++
	s.messages[id] = message
	return message, true
}

func (s *Store) MarkDelivered(id string, epoch uint64, at time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	message, ok := s.messages[id]
	if !ok || message.DeliveryEpoch != epoch || message.DeliveredAt != nil {
		return false
	}
	message.DeliveredAt = &at
	s.messages[id] = message
	return true
}

func (s *Store) Pending() []Message {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]Message, 0, len(s.messages))
	for _, message := range s.messages {
		if message.DeliveredAt == nil {
			result = append(result, message)
		}
	}
	return result
}
