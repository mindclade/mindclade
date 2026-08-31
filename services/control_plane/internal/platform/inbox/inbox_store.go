package inbox

import (
	"context"
	"database/sql"
	"sync"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

type Store struct {
	mu   sync.Mutex
	seen map[string]struct{}
}

// AcceptSQL validates the authoritative registry identity and atomically
// deduplicates an at-least-once event for one tenant-scoped consumer.
func AcceptSQL(ctx context.Context, db *sql.DB, consumer string, envelope *commonv1.EventEnvelope) (bool, error) {
	if consumer == "" {
		return false, queue.ErrInvalidEnvelope
	}
	if err := queue.ValidateEnvelope(envelope); err != nil {
		return false, err
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
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return count == 1, nil
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
