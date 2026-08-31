package operations

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

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

// CreateAtomicallySQL accepts a generated Operation while persisting normalized
// columns. Immutable outbox and audit envelopes are stored as protobuf bytes.
func (r SQLRepository) CreateAtomicallySQL(ctx context.Context, operation *jobv1.Operation, requestDigest, commandKey, actorID string) (*jobv1.Operation, bool, error) {
	if err := validateCreate(operation, requestDigest); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, operation.GetTenantId(), nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	var existingDigest, existingID string
	err = tx.QueryRowContext(ctx, `SELECT request_hash, operation_id FROM idempotency_records WHERE tenant_id = $1 AND command_key = $2 FOR UPDATE`, operation.GetTenantId(), commandKey).Scan(&existingDigest, &existingID)
	if err == nil {
		if existingDigest != requestDigest {
			return nil, false, ErrIdempotencyConflict
		}
		row, scanErr := scanOperationRow(tx.QueryRowContext(ctx, `SELECT id, tenant_id, project_id, job_id, status, version, done, etag, result_ref_id, error_detail_id, request_hash, created_at, updated_at FROM operations WHERE tenant_id = $1 AND id = $2`, operation.GetTenantId(), existingID))
		if scanErr != nil {
			return nil, false, scanErr
		}
		existing, scanErr := operationRowToProtoSQL(ctx, tx, row)
		if scanErr != nil {
			return nil, false, scanErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return existing, true, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	now := time.Now().UTC()
	row := operationToRow(operation, requestDigest)
	row.state = jobv1.OperationState_OPERATION_STATE_PENDING
	row.resourceVersion = 1
	row.done = false
	row.createdAt, row.updatedAt = now, now
	var configurationDigest string
	if err = tx.QueryRowContext(ctx, `SELECT configuration_digest FROM jobs WHERE tenant_id = $1 AND id = $2 FOR UPDATE`, row.tenantID, row.jobID).Scan(&configurationDigest); err != nil {
		return nil, false, err
	}
	envelope, err := newJobRequestedEnvelope(operationRowToProto(row), configurationDigest, now)
	if err != nil {
		return nil, false, err
	}
	auditEnvelope, err := newOperationAuditEnvelope(row, actorID, now)
	if err != nil {
		return nil, false, err
	}
	envelopeBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(envelope)
	if err != nil {
		return nil, false, fmt.Errorf("marshal outbox envelope: %w", err)
	}
	auditEnvelopeBytes, err := proto.MarshalOptions{Deterministic: true}.Marshal(auditEnvelope)
	if err != nil {
		return nil, false, fmt.Errorf("marshal audit envelope: %w", err)
	}
	resultRefID, err := platformdb.StoreArtifactRef(ctx, tx, row.tenantID, row.result)
	if err != nil {
		return nil, false, err
	}
	errorDetailID, err := platformdb.StoreErrorDetail(ctx, tx, row.tenantID, row.error)
	if err != nil {
		return nil, false, err
	}
	row.resultRefID, row.errorDetailID = resultRefID, errorDetailID
	if _, err = tx.ExecContext(ctx, `UPDATE jobs SET operation_id = $3, desired_state = 'QUEUED', version = version + 1, updated_at = $4 WHERE tenant_id = $1 AND id = $2 AND desired_state IN ('ACCEPTED','QUEUED')`, row.tenantID, row.jobID, row.operationID, now); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations (id, tenant_id, project_id, job_id, status, version, done, etag, result_ref_id, error_detail_id, request_hash, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$12)`, row.operationID, row.tenantID, row.projectID, row.jobID, operationStateDatabase(row.state), row.resourceVersion, row.done, row.etag, resultRefID, errorDetailID, requestDigest, now); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id, command_key, request_hash, operation_id, created_at) VALUES ($1, $2, $3, $4, $5)`, row.tenantID, commandKey, requestDigest, row.operationID, now); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id, tenant_id, actor_id, action, subject_id, occurred_at, details_digest, event_version, payload_digest, envelope_bytes) VALUES ($1, $2, $3, 'operations.create', $4, $5, $6, $7, $8, $9)`, auditEnvelope.GetEventId(), row.tenantID, actorID, row.operationID, now, requestDigest, auditEnvelope.GetEventVersion(), auditEnvelope.GetPayloadDigest(), auditEnvelopeBytes); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id, tenant_id, event_type, event_version, payload_digest, envelope_bytes, next_attempt_at, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)`, envelope.GetEventId(), row.tenantID, envelope.GetEventType(), envelope.GetEventVersion(), envelope.GetPayloadDigest(), envelopeBytes, now); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return operationRowToProto(row), false, nil
}

func (r SQLRepository) GetSQL(ctx context.Context, tenantID, operationID string) (*jobv1.Operation, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanOperationRow(tx.QueryRowContext(ctx, `SELECT id, tenant_id, project_id, job_id, status, version, done, etag, result_ref_id, error_detail_id, request_hash, created_at, updated_at FROM operations WHERE tenant_id = $1 AND id = $2`, tenantID, operationID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := operationRowToProtoSQL(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) AdvanceSQL(ctx context.Context, tenantID, operationID string, expectedVersion int64, state jobv1.OperationState) (*jobv1.Operation, error) {
	if !validAdvanceState(state) {
		return nil, ErrInvalidTransition
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	now := time.Now().UTC()
	done := terminalOperationState(state)
	result, err := tx.ExecContext(ctx, `UPDATE operations SET status = $4, version = version + 1, done = $5, updated_at = $6 WHERE tenant_id = $1 AND id = $2 AND version = $3 AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, tenantID, operationID, expectedVersion, operationStateDatabase(state), done, now)
	if err != nil {
		return nil, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}
	if count != 1 {
		var exists bool
		if scanErr := tx.QueryRowContext(ctx, `SELECT EXISTS (SELECT 1 FROM operations WHERE tenant_id = $1 AND id = $2)`, tenantID, operationID).Scan(&exists); scanErr != nil {
			return nil, scanErr
		}
		if !exists {
			return nil, ErrNotFound
		}
		return nil, ErrVersionConflict
	}
	row, err := scanOperationRow(tx.QueryRowContext(ctx, `SELECT id, tenant_id, project_id, job_id, status, version, done, etag, result_ref_id, error_detail_id, request_hash, created_at, updated_at FROM operations WHERE tenant_id = $1 AND id = $2`, tenantID, operationID))
	if err != nil {
		return nil, err
	}
	value, err := operationRowToProtoSQL(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

var (
	ErrNotFound            = errors.New("operation not found")
	ErrIdempotencyConflict = errors.New("idempotency key reused with a different request digest")
	ErrVersionConflict     = errors.New("operation version conflict")
	ErrTerminalTransition  = errors.New("operation terminal transition denied")
	ErrInvalidTransition   = errors.New("operation transition target is invalid")
)

// operationRow is a private relational adapter. The generated Operation and
// EventEnvelope messages own all service and delivery surfaces.
type operationRow struct {
	operationID, tenantID, projectID, jobID string
	state                                   jobv1.OperationState
	resourceVersion                         int64
	done                                    bool
	etag                                    string
	resultRefID, errorDetailID              sql.NullInt64
	result                                  *artifactv1.ArtifactRef
	error                                   *commonv1.ErrorDetail
	requestDigest                           string
	createdAt, updatedAt                    time.Time
}

type Repository struct {
	mu          sync.Mutex
	operations  map[string]operationRow
	idempotency map[string]operationRow
	audit       []*commonv1.EventEnvelope
	outbox      []*commonv1.EventEnvelope
}

func NewRepository() *Repository {
	return &Repository{operations: make(map[string]operationRow), idempotency: make(map[string]operationRow)}
}

// CreateAtomically records idempotency, operation, audit, and an immutable
// generated envelope under one lock.
func (r *Repository) CreateAtomically(operation *jobv1.Operation, requestDigest, configurationDigest, commandKey, actorID string) (*jobv1.Operation, bool, error) {
	if err := validateCreate(operation, requestDigest); err != nil {
		return nil, false, err
	}
	if err := validateDigest(configurationDigest, "configuration digest"); err != nil {
		return nil, false, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := operation.GetTenantId() + "\x00" + commandKey
	if previous, ok := r.idempotency[key]; ok {
		if previous.requestDigest != requestDigest {
			return nil, false, ErrIdempotencyConflict
		}
		return operationRowToProto(previous), true, nil
	}
	now := time.Now().UTC()
	row := operationToRow(operation, requestDigest)
	row.state = jobv1.OperationState_OPERATION_STATE_PENDING
	row.resourceVersion = 1
	row.done = false
	row.createdAt, row.updatedAt = now, now
	envelope, err := newJobRequestedEnvelope(operationRowToProto(row), configurationDigest, now)
	if err != nil {
		return nil, false, err
	}
	auditEnvelope, err := newOperationAuditEnvelope(row, actorID, now)
	if err != nil {
		return nil, false, err
	}
	r.operations[row.operationID], r.idempotency[key] = row, row
	r.audit = append(r.audit, auditEnvelope)
	r.outbox = append(r.outbox, envelope)
	return operationRowToProto(row), false, nil
}

func (r *Repository) Get(tenantID, operationID string) (*jobv1.Operation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	row, ok := r.operations[operationID]
	if !ok || tenants.RequireScope(tenantID, row.tenantID) != nil {
		return nil, ErrNotFound
	}
	return operationRowToProto(row), nil
}

func (r *Repository) Advance(tenantID, operationID string, expectedVersion int64, state jobv1.OperationState) (*jobv1.Operation, error) {
	if !validAdvanceState(state) {
		return nil, ErrInvalidTransition
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	row, ok := r.operations[operationID]
	if !ok || tenants.RequireScope(tenantID, row.tenantID) != nil {
		return nil, ErrNotFound
	}
	if row.resourceVersion != expectedVersion {
		return nil, ErrVersionConflict
	}
	if terminalOperationState(row.state) {
		return nil, ErrTerminalTransition
	}
	row.state = state
	row.resourceVersion++
	row.updatedAt = time.Now().UTC()
	row.done = terminalOperationState(state)
	r.operations[operationID] = row
	return operationRowToProto(row), nil
}

func (r *Repository) AuditCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.audit)
}

func (r *Repository) AuditEnvelopes() []*commonv1.EventEnvelope {
	r.mu.Lock()
	defer r.mu.Unlock()
	result := make([]*commonv1.EventEnvelope, len(r.audit))
	for index, envelope := range r.audit {
		result[index] = proto.Clone(envelope).(*commonv1.EventEnvelope)
	}
	return result
}

func (r *Repository) OutboxEnvelopes() []*commonv1.EventEnvelope {
	r.mu.Lock()
	defer r.mu.Unlock()
	result := make([]*commonv1.EventEnvelope, len(r.outbox))
	for index, envelope := range r.outbox {
		result[index] = proto.Clone(envelope).(*commonv1.EventEnvelope)
	}
	return result
}

func newJobRequestedEnvelope(operation *jobv1.Operation, configurationDigest string, at time.Time) (*commonv1.EventEnvelope, error) {
	if err := validateDigest(configurationDigest, "configuration digest"); err != nil {
		return nil, err
	}
	payloadMessage := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal JobRequested payload: %w", err)
	}
	digest := sha256.Sum256(payload)
	eventType := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	return &commonv1.EventEnvelope{
		EventId:            "job-requested:" + operation.GetOperationId(),
		EventType:          eventType,
		EventVersion:       1,
		OccurredAt:         timestamppb.New(at.UTC()),
		RecordedAt:         timestamppb.New(at.UTC()),
		TenantId:           operation.GetTenantId(),
		ProjectId:          operation.GetProjectId(),
		Subject:            &commonv1.ResourceRef{ResourceType: "operation", ResourceId: operation.GetOperationId(), TenantId: operation.GetTenantId(), ProjectId: operation.GetProjectId(), ResourceVersion: operation.GetResourceVersion()},
		PayloadDigest:      "sha256:" + hex.EncodeToString(digest[:]),
		Payload:            payload,
		Producer:           "services/control_plane",
		AggregateSequence:  1,
		JobId:              operation.GetJobId(),
		DeduplicationKey:   "job-requested:" + operation.GetOperationId(),
		PayloadContentType: "application/x-protobuf; deterministic=true",
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}, nil
}

func newOperationAuditEnvelope(row operationRow, actorID string, at time.Time) (*commonv1.EventEnvelope, error) {
	return foundationaudit.NewEvent(
		row.tenantID,
		actorID,
		CreateAction,
		row.operationID,
		"allowed",
		at.UTC(),
		nil,
	)
}

func validateCreate(operation *jobv1.Operation, requestDigest string) error {
	if operation == nil || operation.GetOperationId() == "" || operation.GetTenantId() == "" || operation.GetJobId() == "" {
		return ErrNotFound
	}
	return validateDigest(requestDigest, "request digest")
}

func validateDigest(value, field string) error {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return fmt.Errorf("%s must be sha256:<64 lowercase hex>", field)
	}
	if _, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:")); err != nil {
		return fmt.Errorf("invalid %s: %w", field, err)
	}
	return nil
}

func operationToRow(operation *jobv1.Operation, requestDigest string) operationRow {
	return operationRow{
		operationID: operation.GetOperationId(), tenantID: operation.GetTenantId(), projectID: operation.GetProjectId(), jobID: operation.GetJobId(),
		state: operation.GetState(), resourceVersion: operation.GetResourceVersion(), done: operation.GetDone(), etag: operation.GetEtag(),
		result: cloneOperationArtifact(operation.GetResult()), error: cloneOperationError(operation.GetError()),
		requestDigest: requestDigest, createdAt: protoTimestampTime(operation.GetCreatedAt()), updatedAt: protoTimestampTime(operation.GetUpdatedAt()),
	}
}

func operationRowToProto(row operationRow) *jobv1.Operation {
	return &jobv1.Operation{
		OperationId: row.operationID, TenantId: row.tenantID, ProjectId: row.projectID, JobId: row.jobID,
		State: row.state, ResourceVersion: row.resourceVersion, Done: row.done, Etag: row.etag,
		Result: cloneOperationArtifact(row.result), Error: cloneOperationError(row.error),
		CreatedAt: timeProtoTimestamp(row.createdAt), UpdatedAt: timeProtoTimestamp(row.updatedAt),
	}
}

type rowScanner interface {
	Scan(...any) error
}

func scanOperationRow(scanner rowScanner) (operationRow, error) {
	var row operationRow
	var state string
	if err := scanner.Scan(&row.operationID, &row.tenantID, &row.projectID, &row.jobID, &state, &row.resourceVersion, &row.done, &row.etag, &row.resultRefID, &row.errorDetailID, &row.requestDigest, &row.createdAt, &row.updatedAt); err != nil {
		return operationRow{}, err
	}
	parsed, err := operationStateFromDatabase(state)
	if err != nil {
		return operationRow{}, err
	}
	row.state = parsed
	if row.done != terminalOperationState(parsed) {
		return operationRow{}, errors.New("persisted operation done/state invariant is invalid")
	}
	return row, nil
}

func operationRowToProtoSQL(ctx context.Context, tx *sql.Tx, row operationRow) (*jobv1.Operation, error) {
	result, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.resultRefID)
	if err != nil {
		return nil, err
	}
	detail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenantID, row.errorDetailID)
	if err != nil {
		return nil, err
	}
	row.result, row.error = result, detail
	return operationRowToProto(row), nil
}

func operationStateDatabase(state jobv1.OperationState) string {
	return map[jobv1.OperationState]string{
		jobv1.OperationState_OPERATION_STATE_PENDING:    "PENDING",
		jobv1.OperationState_OPERATION_STATE_RUNNING:    "RUNNING",
		jobv1.OperationState_OPERATION_STATE_SUCCEEDED:  "SUCCEEDED",
		jobv1.OperationState_OPERATION_STATE_FAILED:     "FAILED",
		jobv1.OperationState_OPERATION_STATE_CANCELLING: "CANCELLING",
		jobv1.OperationState_OPERATION_STATE_CANCELLED:  "CANCELLED",
	}[state]
}

func operationStateFromDatabase(value string) (jobv1.OperationState, error) {
	states := map[string]jobv1.OperationState{
		"PENDING": jobv1.OperationState_OPERATION_STATE_PENDING, "RUNNING": jobv1.OperationState_OPERATION_STATE_RUNNING,
		"SUCCEEDED": jobv1.OperationState_OPERATION_STATE_SUCCEEDED, "FAILED": jobv1.OperationState_OPERATION_STATE_FAILED,
		"CANCELLING": jobv1.OperationState_OPERATION_STATE_CANCELLING, "CANCELLED": jobv1.OperationState_OPERATION_STATE_CANCELLED,
	}
	state, ok := states[value]
	if !ok {
		return jobv1.OperationState_OPERATION_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted operation state %q", value)
	}
	return state, nil
}

func terminalOperationState(state jobv1.OperationState) bool {
	return state == jobv1.OperationState_OPERATION_STATE_SUCCEEDED || state == jobv1.OperationState_OPERATION_STATE_FAILED || state == jobv1.OperationState_OPERATION_STATE_CANCELLED
}

func validAdvanceState(state jobv1.OperationState) bool {
	return state == jobv1.OperationState_OPERATION_STATE_RUNNING || state == jobv1.OperationState_OPERATION_STATE_SUCCEEDED || state == jobv1.OperationState_OPERATION_STATE_FAILED || state == jobv1.OperationState_OPERATION_STATE_CANCELLING || state == jobv1.OperationState_OPERATION_STATE_CANCELLED
}

func protoTimestampTime(value *timestamppb.Timestamp) time.Time {
	if value == nil {
		return time.Time{}
	}
	return value.AsTime().UTC()
}

func timeProtoTimestamp(value time.Time) *timestamppb.Timestamp {
	if value.IsZero() {
		return nil
	}
	return timestamppb.New(value.UTC())
}

func cloneOperationArtifact(value *artifactv1.ArtifactRef) *artifactv1.ArtifactRef {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*artifactv1.ArtifactRef)
}

func cloneOperationError(value *commonv1.ErrorDetail) *commonv1.ErrorDetail {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*commonv1.ErrorDetail)
}
