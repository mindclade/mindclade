package operations

import (
	"context"
	"database/sql"
	"errors"
	"sync"
	"time"

	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

// CreateAtomicallySQL accepts one command in a PostgreSQL transaction. Delivery remains outside it via outbox.
func (r SQLRepository) CreateAtomicallySQL(ctx context.Context, operation Operation, commandKey, actorID string) (Operation, bool, error) {
	tx, err := r.DB.BeginTx(ctx, nil)
	if err != nil {
		return Operation{}, false, err
	}
	defer tx.Rollback()
	var existingHash, existingID string
	err = tx.QueryRowContext(ctx, `SELECT request_hash, operation_id FROM idempotency_records WHERE tenant_id = $1 AND command_key = $2 FOR UPDATE`, operation.TenantID, commandKey).Scan(&existingHash, &existingID)
	if err == nil {
		if existingHash != operation.RequestHash {
			return Operation{}, false, ErrIdempotencyConflict
		}
		var existing Operation
		err = tx.QueryRowContext(ctx, `SELECT id, tenant_id, job_id, status, version, request_hash, created_at, updated_at FROM operations WHERE tenant_id = $1 AND id = $2`, operation.TenantID, existingID).Scan(&existing.ID, &existing.TenantID, &existing.JobID, &existing.Status, &existing.Version, &existing.RequestHash, &existing.CreatedAt, &existing.UpdatedAt)
		if err != nil {
			return Operation{}, false, err
		}
		return existing, true, tx.Commit()
	}
	if err != sql.ErrNoRows {
		return Operation{}, false, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE jobs SET desired_state = 'QUEUED', version = version + 1, updated_at = now() WHERE tenant_id = $1 AND id = $2 AND desired_state IN ('ACCEPTED','QUEUED')`, operation.TenantID, operation.JobID); err != nil {
		return Operation{}, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations (id, tenant_id, job_id, status, version, request_hash, created_at, updated_at) VALUES ($1, $2, $3, 'PENDING', 1, $4, now(), now())`, operation.ID, operation.TenantID, operation.JobID, operation.RequestHash); err != nil {
		return Operation{}, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id, command_key, request_hash, operation_id, created_at) VALUES ($1, $2, $3, $4, now())`, operation.TenantID, commandKey, operation.RequestHash, operation.ID); err != nil {
		return Operation{}, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id, tenant_id, actor_id, action, subject_id, occurred_at, details_digest) VALUES ($1, $2, $3, 'operations.create', $4, now(), $5)`, "audit:"+operation.ID, operation.TenantID, actorID, operation.ID, operation.RequestHash); err != nil {
		return Operation{}, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id, tenant_id, event_type, payload_digest, created_at) VALUES ($1, $2, 'operation.created', $3, now())`, "operation-created:"+operation.ID, operation.TenantID, operation.RequestHash); err != nil {
		return Operation{}, false, err
	}
	operation.Status, operation.Version = "PENDING", 1
	if err = tx.QueryRowContext(ctx, `SELECT created_at, updated_at FROM operations WHERE tenant_id = $1 AND id = $2`, operation.TenantID, operation.ID).Scan(&operation.CreatedAt, &operation.UpdatedAt); err != nil {
		return Operation{}, false, err
	}
	return operation, false, tx.Commit()
}

var (
	ErrNotFound            = errors.New("operation not found")
	ErrIdempotencyConflict = errors.New("idempotency key reused with a different request hash")
	ErrVersionConflict     = errors.New("operation version conflict")
	ErrTerminalTransition  = errors.New("operation terminal transition denied")
)

type Operation struct {
	ID          string
	TenantID    string
	JobID       string
	Status      string
	Version     uint64
	RequestHash string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}
type AuditEvent struct {
	TenantID string
	ActorID  string
	Action   string
	Subject  string
}
type OutboxMessage struct {
	ID       string
	TenantID string
	Type     string
}

type Repository struct {
	mu          sync.Mutex
	operations  map[string]Operation
	idempotency map[string]Operation
	audit       []AuditEvent
	outbox      []OutboxMessage
}

func NewRepository() *Repository {
	return &Repository{operations: make(map[string]Operation), idempotency: make(map[string]Operation)}
}

// CreateAtomically records idempotency, operation, audit, and outbox state under one lock.
func (r *Repository) CreateAtomically(operation Operation, commandKey, actorID string) (Operation, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := operation.TenantID + "\x00" + commandKey
	if previous, ok := r.idempotency[key]; ok {
		if previous.RequestHash != operation.RequestHash {
			return Operation{}, false, ErrIdempotencyConflict
		}
		return previous, true, nil
	}
	if operation.ID == "" || operation.TenantID == "" || operation.JobID == "" || operation.RequestHash == "" {
		return Operation{}, false, ErrNotFound
	}
	now := time.Now().UTC()
	operation.Status, operation.Version, operation.CreatedAt, operation.UpdatedAt = "PENDING", 1, now, now
	r.operations[operation.ID], r.idempotency[key] = operation, operation
	r.audit = append(r.audit, AuditEvent{TenantID: operation.TenantID, ActorID: actorID, Action: "operations.create", Subject: operation.ID})
	r.outbox = append(r.outbox, OutboxMessage{ID: "operation-created:" + operation.ID, TenantID: operation.TenantID, Type: "operation.created"})
	return operation, false, nil
}

func (r *Repository) Get(tenantID, operationID string) (Operation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	operation, ok := r.operations[operationID]
	if !ok || tenants.RequireScope(tenantID, operation.TenantID) != nil {
		return Operation{}, ErrNotFound
	}
	return operation, nil
}

func (r *Repository) Advance(tenantID, operationID string, expectedVersion uint64, status string) (Operation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	operation, ok := r.operations[operationID]
	if !ok || tenants.RequireScope(tenantID, operation.TenantID) != nil {
		return Operation{}, ErrNotFound
	}
	if operation.Version != expectedVersion {
		return Operation{}, ErrVersionConflict
	}
	if operation.Status == "SUCCEEDED" || operation.Status == "FAILED" || operation.Status == "CANCELLED" {
		return Operation{}, ErrTerminalTransition
	}
	operation.Status, operation.Version, operation.UpdatedAt = status, operation.Version+1, time.Now().UTC()
	r.operations[operationID] = operation
	return operation, nil
}

func (r *Repository) AuditEvents() []AuditEvent {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]AuditEvent(nil), r.audit...)
}

func (r *Repository) OutboxMessages() []OutboxMessage {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]OutboxMessage(nil), r.outbox...)
}
