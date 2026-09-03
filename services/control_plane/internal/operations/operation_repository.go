package operations

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
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
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

const operationSelectColumns = `id, tenant_id, project_id, job_id,
target_present, target_resource_type, target_resource_id, target_tenant_id,
target_project_id, target_resource_version, target_name, target_etag,
status, version, done, etag, result_ref_id, error_detail_id, request_hash,
created_at, updated_at`

const operationHistoryRetention = int64(256)

// CreateAtomicallySQL accepts a generated Operation while persisting normalized
// columns. Immutable outbox and audit envelopes are stored as protobuf bytes.
func (r SQLRepository) CreateAtomicallySQL(ctx context.Context, operation *operationv1.Operation, requestDigest, commandKey, actorID string) (*operationv1.Operation, bool, error) {
	if err := validateCreate(operation, requestDigest); err != nil {
		return nil, false, err
	}
	if err := validateCommandIdentity(commandKey, actorID); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, operation.GetTenantId(), nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	var existingDigest, existingID string
	err = tx.QueryRowContext(ctx, `SELECT request_hash, operation_id FROM idempotency_records WHERE tenant_id = $1 AND project_id = $2 AND command_key = $3 FOR UPDATE`, operation.GetTenantId(), operation.GetProjectId(), commandKey).Scan(&existingDigest, &existingID)
	if err == nil {
		if existingDigest != requestDigest {
			return nil, false, ErrIdempotencyConflict
		}
		row, scanErr := scanOperationRow(tx.QueryRowContext(ctx, `SELECT `+operationSelectColumns+` FROM operations WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, operation.GetTenantId(), operation.GetProjectId(), existingID))
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
	row.state = operationv1.OperationState_OPERATION_STATE_PENDING
	row.resourceVersion = 1
	row.done = false
	row.createdAt, row.updatedAt = now, now
	var configurationDigest string
	if err = tx.QueryRowContext(ctx, `SELECT configuration_digest FROM jobs WHERE tenant_id = $1 AND project_id = $2 AND id = $3 FOR UPDATE`, row.tenantID, row.projectID, row.jobID).Scan(&configurationDigest); err != nil {
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
	auditEnvelopeBytes, err := pubsubx.MarshalEnvelope(auditEnvelope)
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
	jobResult, err := tx.ExecContext(ctx, `UPDATE jobs SET operation_id = $4, desired_state = 'QUEUED', version = version + 1, updated_at = $5 WHERE tenant_id = $1 AND project_id = $2 AND id = $3 AND desired_state IN ('ACCEPTED','QUEUED') AND (operation_id = '' OR operation_id = $4)`, row.tenantID, row.projectID, row.jobID, row.operationID, now)
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := jobResult.RowsAffected(); rowsErr != nil {
		return nil, false, rowsErr
	} else if changed != 1 {
		return nil, false, ErrInvalidTransition
	}
	targetPresent, targetType, targetID, targetTenant, targetProject, targetVersion, targetName, targetETag := operationTargetColumns(row.target)
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations (
id, tenant_id, project_id, job_id, target_present, target_resource_type,
target_resource_id, target_tenant_id, target_project_id, target_resource_version,
target_name, target_etag, status, version, done, etag, result_ref_id,
error_detail_id, request_hash, created_at, updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$20)`,
		row.operationID, row.tenantID, row.projectID, row.jobID,
		targetPresent, targetType, targetID, targetTenant, targetProject, targetVersion, targetName, targetETag,
		operationStateDatabase(row.state), row.resourceVersion, row.done, row.etag,
		resultRefID, errorDetailID, requestDigest, now,
	); err != nil {
		return nil, false, err
	}
	if err = recordOperationRevisionSQL(ctx, tx, row, now); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id, project_id, command_key, request_hash, operation_id, created_at) VALUES ($1, $2, $3, $4, $5, $6)`, row.tenantID, row.projectID, commandKey, requestDigest, row.operationID, now); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id, tenant_id, actor_id, action, subject_id, occurred_at, details_digest, event_version, payload_digest, envelope_bytes) VALUES ($1, $2, $3, 'operations.create', $4, $5, $6, $7, $8, $9)`, auditEnvelope.GetEventId(), row.tenantID, actorID, row.operationID, now, requestDigest, auditEnvelope.GetEventVersion(), auditEnvelope.GetPayloadDigest(), auditEnvelopeBytes); err != nil {
		return nil, false, err
	}
	if err = pubsubx.InsertOutboxMessage(ctx, tx, envelope, now); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return operationRowToProto(row), false, nil
}

// CreateJobAndOperationSQL is the generated JobService acceptance transaction.
// It creates the normalized job, operation, first immutable operation revision,
// idempotency receipt, audit evidence, and JobRequested outbox delivery as one
// tenant-scoped commit. Replays return the original operation without writes.
func (r SQLRepository) CreateJobAndOperationSQL(ctx context.Context, job *jobv1.Job, operation *operationv1.Operation, requestDigest, commandKey, actorID string, at time.Time) (*operationv1.Operation, bool, error) {
	if job == nil || job.GetJobId() == "" || job.GetTenantId() == "" || job.GetProjectId() == "" ||
		job.GetConfiguration() == nil || job.GetConfiguration().GetDigest() == "" || job.GetEtag() == "" ||
		operation == nil || operation.GetJobId() != job.GetJobId() || operation.GetTenantId() != job.GetTenantId() ||
		operation.GetProjectId() != job.GetProjectId() || at.IsZero() {
		return nil, false, ErrNotFound
	}
	if err := validateCreate(operation, requestDigest); err != nil {
		return nil, false, err
	}
	if err := validateDigest(job.GetConfiguration().GetDigest(), "configuration digest"); err != nil {
		return nil, false, err
	}
	if err := validateCommandIdentity(commandKey, actorID); err != nil {
		return nil, false, err
	}
	at = at.UTC()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, job.GetTenantId(), nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	lockKey := fmt.Sprintf("%d:%s:%d:%s:%s", len(job.GetTenantId()), job.GetTenantId(), len(job.GetProjectId()), job.GetProjectId(), commandKey)
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return nil, false, err
	}
	var existingDigest, existingID string
	err = tx.QueryRowContext(ctx, `SELECT request_hash, operation_id FROM idempotency_records WHERE tenant_id=$1 AND project_id=$2 AND command_key=$3`, job.GetTenantId(), job.GetProjectId(), commandKey).Scan(&existingDigest, &existingID)
	if err == nil {
		if subtle.ConstantTimeCompare([]byte(existingDigest), []byte(requestDigest)) != 1 {
			return nil, false, ErrIdempotencyConflict
		}
		row, scanErr := scanOperationRow(tx.QueryRowContext(ctx, `SELECT `+operationSelectColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, job.GetTenantId(), job.GetProjectId(), existingID))
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
	inputRefID, err := platformdb.StoreArtifactRef(ctx, tx, job.GetTenantId(), job.GetInput())
	if err != nil {
		return nil, false, err
	}
	configurationRefID, err := platformdb.StoreArtifactRef(ctx, tx, job.GetTenantId(), job.GetConfiguration())
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs (
id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,
input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at
) VALUES ($1,$2,'',$3,'ACCEPTED',1,$4,$5,$6,$7,$8,$9,$10,$10)`,
		job.GetJobId(), job.GetTenantId(), job.GetProjectId(), job.GetPolicyDigest(), job.GetJobKind(),
		inputRefID, configurationRefID, job.GetConfiguration().GetDigest(), job.GetEtag(), at); err != nil {
		if sqlState(err) == "23505" {
			return nil, false, ErrAlreadyExists
		}
		return nil, false, err
	}
	row := operationToRow(operation, requestDigest)
	row.state = operationv1.OperationState_OPERATION_STATE_PENDING
	row.resourceVersion = 1
	row.done = false
	row.createdAt, row.updatedAt = at, at
	envelope, err := newJobRequestedEnvelope(operationRowToProto(row), job.GetConfiguration().GetDigest(), at)
	if err != nil {
		return nil, false, err
	}
	auditEnvelope, err := newOperationAuditEnvelope(row, actorID, at)
	if err != nil {
		return nil, false, err
	}
	auditEnvelopeBytes, err := pubsubx.MarshalEnvelope(auditEnvelope)
	if err != nil {
		return nil, false, fmt.Errorf("marshal audit envelope: %w", err)
	}
	jobResult, err := tx.ExecContext(ctx, `UPDATE jobs SET operation_id=$4,desired_state='QUEUED',version=2,etag=$5,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND desired_state='ACCEPTED' AND version=1`, row.tenantID, row.projectID, row.jobID, row.operationID, ResourceETag(row.tenantID, row.projectID, row.jobID, 2), at)
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := jobResult.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrInvalidTransition
	}
	targetPresent, targetType, targetID, targetTenant, targetProject, targetVersion, targetName, targetETag := operationTargetColumns(row.target)
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations (
id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,
target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,
version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,1,false,$14,NULL,NULL,$15,$16,$16)`,
		row.operationID, row.tenantID, row.projectID, row.jobID, targetPresent, targetType, targetID,
		targetTenant, targetProject, targetVersion, targetName, targetETag, operationStateDatabase(row.state), row.etag,
		requestDigest, at); err != nil {
		if sqlState(err) == "23505" {
			return nil, false, ErrAlreadyExists
		}
		return nil, false, err
	}
	if err = recordOperationRevisionSQL(ctx, tx, row, at); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id,project_id,command_key,request_hash,operation_id,created_at) VALUES ($1,$2,$3,$4,$5,$6)`, row.tenantID, row.projectID, commandKey, requestDigest, row.operationID, at); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES ($1,$2,$3,'operations.create',$4,$5,$6,$7,$8,$9)`, auditEnvelope.GetEventId(), row.tenantID, actorID, row.operationID, at, requestDigest, auditEnvelope.GetEventVersion(), auditEnvelope.GetPayloadDigest(), auditEnvelopeBytes); err != nil {
		return nil, false, err
	}
	if err = pubsubx.InsertOutboxMessage(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return operationRowToProto(row), false, nil
}

func (r SQLRepository) GetSQL(ctx context.Context, tenantID, projectID, operationID string) (*operationv1.Operation, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanOperationRow(tx.QueryRowContext(ctx, `SELECT `+operationSelectColumns+` FROM operations WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, operationID))
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

func recordOperationRevisionSQL(ctx context.Context, tx *sql.Tx, row operationRow, recordedAt time.Time) error {
	targetPresent, targetType, targetID, targetTenant, targetProject, targetVersion, targetName, targetETag := operationTargetColumns(row.target)
	if _, err := tx.ExecContext(ctx, `INSERT INTO operation_revisions (
operation_id,tenant_id,project_id,revision,job_id,target_present,
target_resource_type,target_resource_id,target_tenant_id,target_project_id,
target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,
error_detail_id,created_at,updated_at,recorded_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)`,
		row.operationID, row.tenantID, row.projectID, row.resourceVersion, row.jobID,
		targetPresent, targetType, targetID, targetTenant, targetProject, targetVersion,
		targetName, targetETag, operationStateDatabase(row.state), row.done, row.etag,
		row.resultRefID, row.errorDetailID, row.createdAt.UTC(), row.updatedAt.UTC(), recordedAt.UTC()); err != nil {
		return err
	}
	floor := row.resourceVersion - operationHistoryRetention + 1
	if floor < 1 {
		floor = 1
	}
	if _, err := tx.ExecContext(ctx, `DELETE FROM operation_revisions
WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision<$4`,
		row.tenantID, row.projectID, row.operationID, floor); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE operations SET history_floor_version=$4
WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$5`,
		row.tenantID, row.projectID, row.operationID, floor, row.resourceVersion)
	if err != nil {
		return err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if changed != 1 {
		return ErrVersionConflict
	}
	return nil
}

func (r SQLRepository) AdvanceSQL(ctx context.Context, tenantID, projectID, operationID string, expectedVersion int64, expectedETag string, state operationv1.OperationState) (*operationv1.Operation, error) {
	if !validAdvanceState(state) {
		return nil, ErrInvalidTransition
	}
	if tenantID == "" || projectID == "" || operationID == "" || expectedVersion < 1 || expectedETag == "" {
		return nil, ErrVersionConflict
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	now := time.Now().UTC()
	done := terminalOperationState(state)
	nextVersion := expectedVersion + 1
	nextETag := operationETag(tenantID, projectID, operationID, nextVersion)
	result, err := tx.ExecContext(ctx, `UPDATE operations SET status = $6, version = $4, done = $7, etag = $5, updated_at = $8 WHERE tenant_id = $1 AND project_id = $2 AND id = $3 AND version = $9 AND etag = $10 AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, tenantID, projectID, operationID, nextVersion, nextETag, operationStateDatabase(state), done, now, expectedVersion, expectedETag)
	if err != nil {
		return nil, err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}
	if count != 1 {
		var persistedVersion int64
		var persistedETag, persistedState string
		scanErr := tx.QueryRowContext(ctx, `SELECT version, etag, status FROM operations WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, operationID).Scan(&persistedVersion, &persistedETag, &persistedState)
		if errors.Is(scanErr, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		if scanErr != nil {
			return nil, scanErr
		}
		if persistedState == "SUCCEEDED" || persistedState == "FAILED" || persistedState == "CANCELLED" {
			return nil, ErrTerminalTransition
		}
		_ = persistedVersion
		_ = persistedETag
		return nil, ErrVersionConflict
	}
	row, err := scanOperationRow(tx.QueryRowContext(ctx, `SELECT `+operationSelectColumns+` FROM operations WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, operationID))
	if err != nil {
		return nil, err
	}
	value, err := operationRowToProtoSQL(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = recordOperationRevisionSQL(ctx, tx, row, now); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

// AdvanceTxSQL applies an Operation transition inside a caller-owned tenant
// transaction and appends its immutable revision before returning. Callers use
// this to reconcile a domain aggregate and its client-visible Operation as one
// commit.
func AdvanceTxSQL(ctx context.Context, tx *sql.Tx, tenantID, projectID, operationID string, expectedVersion int64, expectedETag string, state operationv1.OperationState, at time.Time) (*operationv1.Operation, error) {
	if tx == nil || !validAdvanceState(state) || tenantID == "" || projectID == "" || operationID == "" || expectedVersion < 1 || expectedETag == "" || at.IsZero() {
		return nil, ErrVersionConflict
	}
	at = at.UTC()
	nextVersion := expectedVersion + 1
	nextETag := operationETag(tenantID, projectID, operationID, nextVersion)
	result, err := tx.ExecContext(ctx, `UPDATE operations SET status=$6,version=$4,done=$7,etag=$5,updated_at=$8 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$9 AND etag=$10 AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, tenantID, projectID, operationID, nextVersion, nextETag, operationStateDatabase(state), terminalOperationState(state), at, expectedVersion, expectedETag)
	if err != nil {
		return nil, err
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return nil, err
	}
	if changed != 1 {
		var persistedState string
		scanErr := tx.QueryRowContext(ctx, `SELECT status FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, tenantID, projectID, operationID).Scan(&persistedState)
		if errors.Is(scanErr, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		if scanErr != nil {
			return nil, scanErr
		}
		if persistedState == "SUCCEEDED" || persistedState == "FAILED" || persistedState == "CANCELLED" {
			return nil, ErrTerminalTransition
		}
		return nil, ErrVersionConflict
	}
	row, err := scanOperationRow(tx.QueryRowContext(ctx, `SELECT `+operationSelectColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, tenantID, projectID, operationID))
	if err != nil {
		return nil, err
	}
	value, err := operationRowToProtoSQL(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = recordOperationRevisionSQL(ctx, tx, row, at); err != nil {
		return nil, err
	}
	return value, nil
}

var (
	ErrNotFound            = errors.New("operation not found")
	ErrAlreadyExists       = errors.New("operation already exists")
	ErrIdempotencyConflict = errors.New("idempotency key reused with a different request digest")
	ErrVersionConflict     = errors.New("operation version conflict")
	ErrTerminalTransition  = errors.New("operation terminal transition denied")
	ErrInvalidTransition   = errors.New("operation transition target is invalid")
)

// operationRow is a private relational adapter. The generated Operation and
// EventEnvelope messages own all service and delivery surfaces.
type operationRow struct {
	operationID, tenantID, projectID, jobID string
	state                                   operationv1.OperationState
	resourceVersion                         int64
	done                                    bool
	etag                                    string
	resultRefID, errorDetailID              sql.NullInt64
	result                                  *artifactv1.ArtifactRef
	error                                   *commonv1.ErrorDetail
	target                                  *commonv1.ResourceRef
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
func (r *Repository) CreateAtomically(operation *operationv1.Operation, requestDigest, configurationDigest, commandKey, actorID string) (*operationv1.Operation, bool, error) {
	if err := validateCreate(operation, requestDigest); err != nil {
		return nil, false, err
	}
	if err := validateDigest(configurationDigest, "configuration digest"); err != nil {
		return nil, false, err
	}
	if err := validateCommandIdentity(commandKey, actorID); err != nil {
		return nil, false, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := operationScopeKey(operation.GetTenantId(), operation.GetProjectId(), commandKey)
	if previous, ok := r.idempotency[key]; ok {
		if previous.requestDigest != requestDigest {
			return nil, false, ErrIdempotencyConflict
		}
		return operationRowToProto(previous), true, nil
	}
	now := time.Now().UTC()
	row := operationToRow(operation, requestDigest)
	row.state = operationv1.OperationState_OPERATION_STATE_PENDING
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
	operationKey := operationScopeKey(row.tenantID, row.projectID, row.operationID)
	if _, exists := r.operations[operationKey]; exists {
		return nil, false, ErrAlreadyExists
	}
	r.operations[operationKey], r.idempotency[key] = row, row
	r.audit = append(r.audit, auditEnvelope)
	r.outbox = append(r.outbox, envelope)
	return operationRowToProto(row), false, nil
}

func (r *Repository) Get(tenantID, projectID, operationID string) (*operationv1.Operation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	row, ok := r.operations[operationScopeKey(tenantID, projectID, operationID)]
	if !ok || tenants.RequireScope(tenantID, row.tenantID) != nil || row.projectID != projectID {
		return nil, ErrNotFound
	}
	return operationRowToProto(row), nil
}

func (r *Repository) Advance(tenantID, projectID, operationID string, expectedVersion int64, expectedETag string, state operationv1.OperationState) (*operationv1.Operation, error) {
	if !validAdvanceState(state) {
		return nil, ErrInvalidTransition
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := operationScopeKey(tenantID, projectID, operationID)
	row, ok := r.operations[key]
	if !ok || tenants.RequireScope(tenantID, row.tenantID) != nil || row.projectID != projectID {
		return nil, ErrNotFound
	}
	if row.resourceVersion != expectedVersion || row.etag != expectedETag {
		return nil, ErrVersionConflict
	}
	if terminalOperationState(row.state) {
		return nil, ErrTerminalTransition
	}
	row.state = state
	row.resourceVersion++
	row.etag = operationETag(row.tenantID, row.projectID, row.operationID, row.resourceVersion)
	row.updatedAt = time.Now().UTC()
	row.done = terminalOperationState(state)
	r.operations[key] = row
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

func newJobRequestedEnvelope(operation *operationv1.Operation, configurationDigest string, at time.Time) (*commonv1.EventEnvelope, error) {
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
	resourceName, resourceID := operationEventResourceIdentity(operation)
	eventIdentity := sha256.Sum256([]byte(eventType + "\x00" + resourceName))
	eventID := "job-requested:" + hex.EncodeToString(eventIdentity[:])
	return &commonv1.EventEnvelope{
		EventId:            eventID,
		EventType:          eventType,
		EventVersion:       1,
		OccurredAt:         timestamppb.New(at.UTC()),
		RecordedAt:         timestamppb.New(at.UTC()),
		TenantId:           operation.GetTenantId(),
		ProjectId:          operation.GetProjectId(),
		Subject:            &commonv1.ResourceRef{ResourceType: "operation", ResourceId: resourceID, TenantId: operation.GetTenantId(), ProjectId: operation.GetProjectId(), ResourceVersion: operation.GetResourceVersion(), Name: resourceName},
		PayloadDigest:      "sha256:" + hex.EncodeToString(digest[:]),
		Payload:            payload,
		Producer:           "services/control_plane",
		AggregateSequence:  1,
		JobId:              operation.GetJobId(),
		DeduplicationKey:   eventID,
		PayloadContentType: "application/x-protobuf; deterministic=true",
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}, nil
}

func operationEventResourceIdentity(operation *operationv1.Operation) (string, string) {
	operationID := strings.TrimPrefix(operation.GetOperationId(), "/")
	resourceID := operationID
	if separator := strings.LastIndexByte(resourceID, '/'); separator >= 0 {
		resourceID = resourceID[separator+1:]
	}
	scope := "tenants/" + operation.GetTenantId() + "/projects/" + operation.GetProjectId() + "/"
	canonicalPrefix := scope + "operations/"
	switch {
	case strings.HasPrefix(operationID, canonicalPrefix):
		return operationID, resourceID
	case strings.HasPrefix(operationID, "operations/"):
		return scope + operationID, resourceID
	default:
		return canonicalPrefix + operationID, resourceID
	}
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

func validateCreate(operation *operationv1.Operation, requestDigest string) error {
	if operation == nil || operation.GetOperationId() == "" || operation.GetTenantId() == "" || operation.GetProjectId() == "" || operation.GetJobId() == "" {
		return ErrNotFound
	}
	if operation.GetEtag() == "" {
		return ErrVersionConflict
	}
	return validateDigest(requestDigest, "request digest")
}

func validateCommandIdentity(commandKey, actorID string) error {
	if commandKey == "" || len(commandKey) > 512 || strings.ContainsAny(commandKey, "\x00\r\n") {
		return errors.New("idempotency key is required and must be bounded")
	}
	if actorID == "" || len(actorID) > 512 || strings.ContainsAny(actorID, "\x00\r\n") {
		return errors.New("actor identity is required and must be bounded")
	}
	return nil
}

func operationScopeKey(tenantID, projectID, value string) string {
	return tenantID + "\x00" + projectID + "\x00" + value
}

func operationETag(tenantID, projectID, operationID string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s\x00%d", tenantID, projectID, operationID, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

// ResourceETag returns the deterministic optimistic-concurrency token shared
// by normalized Job and Operation aggregates.
func ResourceETag(tenantID, projectID, resourceID string, revision int64) string {
	return operationETag(tenantID, projectID, resourceID, revision)
}

type sqlStateCarrier interface{ SQLState() string }

func sqlState(err error) string {
	var value sqlStateCarrier
	if errors.As(err, &value) {
		return value.SQLState()
	}
	return ""
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

func operationToRow(operation *operationv1.Operation, requestDigest string) operationRow {
	return operationRow{
		operationID: operation.GetOperationId(), tenantID: operation.GetTenantId(), projectID: operation.GetProjectId(), jobID: operation.GetJobId(),
		state: operation.GetState(), resourceVersion: operation.GetResourceVersion(), done: operation.GetDone(), etag: operation.GetEtag(),
		result: cloneOperationArtifact(operation.GetResult()), error: cloneOperationError(operation.GetError()),
		target:        cloneOperationResource(operation.GetTarget()),
		requestDigest: requestDigest, createdAt: protoTimestampTime(operation.GetCreatedAt()), updatedAt: protoTimestampTime(operation.GetUpdatedAt()),
	}
}

func operationRowToProto(row operationRow) *operationv1.Operation {
	return &operationv1.Operation{
		OperationId: row.operationID, TenantId: row.tenantID, ProjectId: row.projectID, JobId: row.jobID,
		State: row.state, ResourceVersion: row.resourceVersion, Done: row.done, Etag: row.etag,
		Result: cloneOperationArtifact(row.result), Error: cloneOperationError(row.error),
		Target:    cloneOperationResource(row.target),
		CreatedAt: timeProtoTimestamp(row.createdAt), UpdatedAt: timeProtoTimestamp(row.updatedAt),
	}
}

type rowScanner interface {
	Scan(...any) error
}

func scanOperationRow(scanner rowScanner) (operationRow, error) {
	var row operationRow
	var state string
	var targetPresent bool
	var target commonv1.ResourceRef
	if err := scanner.Scan(
		&row.operationID, &row.tenantID, &row.projectID, &row.jobID,
		&targetPresent, &target.ResourceType, &target.ResourceId, &target.TenantId,
		&target.ProjectId, &target.ResourceVersion, &target.Name, &target.Etag,
		&state, &row.resourceVersion, &row.done, &row.etag, &row.resultRefID,
		&row.errorDetailID, &row.requestDigest, &row.createdAt, &row.updatedAt,
	); err != nil {
		return operationRow{}, err
	}
	if targetPresent {
		row.target = &target
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

func operationRowToProtoSQL(ctx context.Context, tx *sql.Tx, row operationRow) (*operationv1.Operation, error) {
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

func operationStateDatabase(state operationv1.OperationState) string {
	return map[operationv1.OperationState]string{
		operationv1.OperationState_OPERATION_STATE_PENDING:    "PENDING",
		operationv1.OperationState_OPERATION_STATE_RUNNING:    "RUNNING",
		operationv1.OperationState_OPERATION_STATE_SUCCEEDED:  "SUCCEEDED",
		operationv1.OperationState_OPERATION_STATE_FAILED:     "FAILED",
		operationv1.OperationState_OPERATION_STATE_CANCELLING: "CANCELLING",
		operationv1.OperationState_OPERATION_STATE_CANCELLED:  "CANCELLED",
	}[state]
}

func operationStateFromDatabase(value string) (operationv1.OperationState, error) {
	states := map[string]operationv1.OperationState{
		"PENDING": operationv1.OperationState_OPERATION_STATE_PENDING, "RUNNING": operationv1.OperationState_OPERATION_STATE_RUNNING,
		"SUCCEEDED": operationv1.OperationState_OPERATION_STATE_SUCCEEDED, "FAILED": operationv1.OperationState_OPERATION_STATE_FAILED,
		"CANCELLING": operationv1.OperationState_OPERATION_STATE_CANCELLING, "CANCELLED": operationv1.OperationState_OPERATION_STATE_CANCELLED,
	}
	state, ok := states[value]
	if !ok {
		return operationv1.OperationState_OPERATION_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted operation state %q", value)
	}
	return state, nil
}

func terminalOperationState(state operationv1.OperationState) bool {
	return state == operationv1.OperationState_OPERATION_STATE_SUCCEEDED || state == operationv1.OperationState_OPERATION_STATE_FAILED || state == operationv1.OperationState_OPERATION_STATE_CANCELLED
}

func validAdvanceState(state operationv1.OperationState) bool {
	return state == operationv1.OperationState_OPERATION_STATE_RUNNING || state == operationv1.OperationState_OPERATION_STATE_SUCCEEDED || state == operationv1.OperationState_OPERATION_STATE_FAILED || state == operationv1.OperationState_OPERATION_STATE_CANCELLING || state == operationv1.OperationState_OPERATION_STATE_CANCELLED
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

func cloneOperationResource(value *commonv1.ResourceRef) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*commonv1.ResourceRef)
}

func operationTargetColumns(value *commonv1.ResourceRef) (bool, string, string, string, string, int64, string, string) {
	if value == nil {
		return false, "", "", "", "", 0, "", ""
	}
	return true, value.GetResourceType(), value.GetResourceId(), value.GetTenantId(),
		value.GetProjectId(), value.GetResourceVersion(), value.GetName(), value.GetEtag()
}
