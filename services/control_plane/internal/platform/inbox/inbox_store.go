package inbox

import (
	"context"
	"database/sql"
	"sync"
)

type Store struct {
	mu   sync.Mutex
	seen map[string]struct{}
}

// AcceptSQL atomically deduplicates an at-least-once event for one tenant-scoped consumer.
func AcceptSQL(ctx context.Context, db *sql.DB, consumer, eventID, tenantID string) (bool, error) {
	result, err := db.ExecContext(ctx, `INSERT INTO inbox_messages (consumer, event_id, tenant_id, received_at) VALUES ($1, $2, $3, now()) ON CONFLICT (consumer, event_id) DO NOTHING`, consumer, eventID, tenantID)
	if err != nil {
		return false, err
	}
	count, err := result.RowsAffected()
	return count == 1, err
}

func NewStore() *Store { return &Store{seen: make(map[string]struct{})} }

// Accept returns false for an at-least-once redelivery already committed by this consumer.
func (s *Store) Accept(consumer, eventID, tenantID string) bool {
	if consumer == "" || eventID == "" || tenantID == "" {
		return false
	}
	key := consumer + "\x00" + tenantID + "\x00" + eventID
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.seen[key]; ok {
		return false
	}
	s.seen[key] = struct{}{}
	return true
}
