package training

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Pagination == nil || r.Events == nil {
		return errors.New("training SQL repository requires database, pagination codec, and event factory")
	}
	return nil
}

func randomID(prefix string) (string, error) {
	value := make([]byte, 18)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return prefix + base64.RawURLEncoding.EncodeToString(value), nil
}

func commandKey(action, key string) string { return action + ":" + key }

func checkIdempotency(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string) (string, bool, error) {
	key = commandKey(action, key)
	// PostgreSQL text values cannot contain NUL. Length-prefixing preserves an
	// unambiguous tenant/command boundary without sending forbidden bytes.
	lockKey := fmt.Sprintf("%d:%s:%d:%s:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return "", false, err
	}
	var storedDigest, operationID string
	err := tx.QueryRowContext(ctx, `SELECT request_hash, operation_id FROM idempotency_records WHERE tenant_id=$1 AND project_id=$2 AND command_key=$3`, identity.TenantID, identity.ProjectID, key).Scan(&storedDigest, &operationID)
	if errors.Is(err, sql.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(storedDigest), []byte(digest)) != 1 {
		return "", false, ErrIdempotencyConflict
	}
	return operationID, true, nil
}

func recordIdempotency(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, operationID string, at time.Time) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id, project_id, command_key, request_hash, operation_id, created_at) VALUES ($1,$2,$3,$4,$5,$6)`, identity.TenantID, identity.ProjectID, commandKey(action, key), digest, operationID, at.UTC())
	return err
}

func requireOne(result sql.Result) error {
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count != 1 {
		return ErrRevisionConflict
	}
	return nil
}

func insertAudit(ctx context.Context, tx *sql.Tx, identity Identity, action, subject, digest string, at time.Time) error {
	envelope, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, subject, "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id, tenant_id, actor_id, action, subject_id, occurred_at, details_digest, event_version, payload_digest, envelope_bytes) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		envelope.GetEventId(), identity.TenantID, identity.Principal, action, subject, at.UTC(), digest, envelope.GetEventVersion(), envelope.GetPayloadDigest(), encoded)
	return err
}

func insertOutbox(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	aggregateID := envelope.GetSubject().GetName()
	if aggregateID == "" {
		aggregateID = envelope.GetSubject().GetResourceId()
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id, tenant_id, event_type, event_version, aggregate_type, aggregate_id, aggregate_sequence, payload_digest, envelope_bytes, next_attempt_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`,
		envelope.GetEventId(), envelope.GetTenantId(), envelope.GetEventType(), envelope.GetEventVersion(), envelope.GetSubject().GetResourceType(), aggregateID, envelope.GetAggregateSequence(), envelope.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func (r SQLRepository) CreateTrainingRun(ctx context.Context, identity Identity, command *trainingv1.CreateTrainingRunCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetTrainingRunId() == "" || command.GetTrainingRecipe() == nil || command.GetDatasetRelease() == nil || command.GetModelRelease() == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	if err := validateArtifactReference(command.GetTrainingRecipe(), "training recipe", true); err != nil {
		return nil, false, err
	}
	if err := validateArtifactReference(command.GetExecutablePlan(), "executable plan", false); err != nil {
		return nil, false, err
	}
	if err := validateArtifactReference(command.GetHardwareTopology(), "hardware topology", false); err != nil {
		return nil, false, err
	}
	if !validResourceID(command.GetTrainingRunId()) {
		return nil, false, fmt.Errorf("%w: invalid training_run_id", ErrInvalidArgument)
	}
	if command.GetProject().GetResourceId() != identity.ProjectID || (command.GetProject().GetTenantId() != "" && command.GetProject().GetTenantId() != identity.TenantID) {
		return nil, false, ErrPermissionDenied
	}
	if command.GetProject().GetResourceType() != "project" || command.GetProject().GetName() != "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID {
		return nil, false, ErrInvalidArgument
	}
	if err := validateScopedReference(identity, command.GetDatasetRelease(), "dataset release"); err != nil {
		return nil, false, err
	}
	if err := validateScopedReference(identity, command.GetModelRelease(), "model release"); err != nil {
		return nil, false, err
	}
	if command.GetDatasetRelease().GetResourceType() != "dataset_release" || command.GetModelRelease().GetResourceType() != "model_release" {
		return nil, false, fmt.Errorf("%w: unexpected dataset or model resource type", ErrInvalidArgument)
	}
	if command.GetUsePolicy() != nil {
		if err := validateScopedReference(identity, command.GetUsePolicy(), "use policy"); err != nil {
			return nil, false, err
		}
		if command.GetUsePolicy().GetResourceType() != "use_policy" {
			return nil, false, fmt.Errorf("%w: unexpected use policy resource type", ErrInvalidArgument)
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkIdempotency(ctx, tx, identity, "training.create", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, _, loadErr := getOperationTx(ctx, tx, identity, operationID, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return value, true, nil
	}
	runName, err := canonicalTrainingRunName(identity, command.GetTrainingRunId())
	if err != nil {
		return nil, false, err
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM training_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, runName).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, false, err
	}
	operationID, err = randomID("operations/")
	if err != nil {
		return nil, false, err
	}
	schedulerRunID, err := randomID("run_")
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("trn_")
	if err != nil {
		return nil, false, err
	}
	recipeID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetTrainingRecipe())
	if err != nil {
		return nil, false, err
	}
	datasetID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetDatasetRelease())
	if err != nil {
		return nil, false, err
	}
	modelID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetModelRelease())
	if err != nil {
		return nil, false, err
	}
	planID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetExecutablePlan())
	if err != nil {
		return nil, false, err
	}
	topologyID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetHardwareTopology())
	if err != nil {
		return nil, false, err
	}
	policyID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetUsePolicy())
	if err != nil {
		return nil, false, err
	}
	runETag := resourceETag(runName, 1)
	operationETag := resourceETag(operationID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs (id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES ($1,$2,'',$3,'ACCEPTED',1,'','training',NULL,$4,$5,$6,$7,$7)`, jobID, identity.TenantID, identity.ProjectID, recipeID, digest, resourceETag(jobID, 1), at.UTC()); err != nil {
		return nil, false, err
	}
	target := &commonv1.ResourceRef{ResourceType: "training_run", ResourceId: command.GetTrainingRunId(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: runName, Etag: runETag}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations (id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES ($1,$2,$3,$4,true,$5,$6,$2,$3,1,$7,$8,'PENDING',1,false,$9,NULL,NULL,$10,$11,$11)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), runName, runETag, operationETag, digest, at.UTC()); err != nil {
		return nil, false, err
	}
	createdOperation, createdOperationRow, err := getOperationTx(ctx, tx, identity, operationID, false)
	if err != nil {
		return nil, false, err
	}
	if err = recordOperationRevisionTx(ctx, tx, createdOperationRow, at); err != nil {
		return nil, false, err
	}
	jobUpdate, err := tx.ExecContext(ctx, `UPDATE jobs SET operation_id=$4,desired_state='QUEUED',version=2,etag=$5,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, jobID, operationID, resourceETag(jobID, 2), at.UTC())
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(jobUpdate); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO runs (id,tenant_id,project_id,job_id,input_ref_id,configuration_ref_id,plan_ref_id,status,version,lease_epoch,error_detail_id,etag,created_at,updated_at) VALUES ($1,$2,$3,$4,NULL,$5,$6,'READY',1,0,NULL,$7,$8,$8)`, schedulerRunID, identity.TenantID, identity.ProjectID, jobID, recipeID, planID, resourceETag(schedulerRunID, 1), at.UTC()); err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO training_runs (name,tenant_id,project_id,uid,revision,etag,state,operation_id,job_id,scheduler_run_id,training_recipe_ref_id,dataset_release_ref_id,model_release_ref_id,executable_plan_ref_id,hardware_topology_ref_id,use_policy_ref_id,policy_classification,create_time) VALUES ($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)`, runName, identity.TenantID, identity.ProjectID, uid, runETag, int32(trainingv1.TrainingRunState_TRAINING_RUN_STATE_CREATED), operationID, jobID, schedulerRunID, recipeID, datasetID, modelID, planID, topologyID, policyID, command.GetPolicyClassification(), at.UTC()); err != nil {
		return nil, false, err
	}
	for key, value := range command.GetLabels() {
		if key == "" || len(key) > 128 || len(value) > 256 {
			return nil, false, ErrInvalidArgument
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO training_run_labels (tenant_id,project_id,training_run_name,label_key,label_value) VALUES ($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, runName, key, value); err != nil {
			return nil, false, err
		}
	}
	run, _, err := getRunTx(ctx, tx, identity, runName, false)
	if err != nil {
		return nil, false, err
	}
	operation := createdOperation
	createdEvent, err := r.Events.Created(identity, run, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	jobEvent, err := r.Events.JobRequested(identity, operation, digest, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.create", runName, digest, at); err != nil {
		return nil, false, err
	}
	for _, event := range []*commonv1.EventEnvelope{createdEvent, jobEvent} {
		if err = insertOutbox(ctx, tx, event, at); err != nil {
			return nil, false, err
		}
	}
	if err = recordIdempotency(ctx, tx, identity, "training.create", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) GetTrainingRun(ctx context.Context, identity Identity, name string) (*trainingv1.TrainingRun, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, _, err := getRunTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) GetCheckpoint(ctx context.Context, identity Identity, name string) (*trainingv1.Checkpoint, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, _, err := getCheckpointTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) GetOperation(ctx context.Context, identity Identity, name string) (*jobv1.Operation, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, _, err := getOperationTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

// ReadOperationRevisions returns a bounded, contiguous page strictly after
// afterRevision. It classifies cursor expiry and future cursors before reading
// history so callers never mistake a lossy resume for an idle stream.
func (r SQLRepository) ReadOperationRevisions(ctx context.Context, identity Identity, name string, afterRevision uint64, requestedLimit int) ([]*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	limit := requestedLimit
	if limit <= 0 || limit > operationWatchBatchLimit {
		limit = operationWatchBatchLimit
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	var current, floor int64
	var done bool
	err = tx.QueryRowContext(ctx, `SELECT version,history_floor_version,done FROM operations
WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, name).Scan(&current, &floor, &done)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	currentRevision, conversionErr := numconv.Int64ToUint64(current)
	if conversionErr != nil {
		return nil, false, conversionErr
	}
	floorRevision, conversionErr := numconv.Int64ToUint64(floor)
	if conversionErr != nil {
		return nil, false, conversionErr
	}
	if afterRevision > currentRevision {
		return nil, false, ErrCursorAhead
	}
	if afterRevision+1 < floorRevision {
		return nil, false, ErrCursorExpired
	}
	rows, err := tx.QueryContext(ctx, `SELECT `+operationRevisionColumns+` FROM operation_revisions
WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision>$4
ORDER BY revision LIMIT $5`, identity.TenantID, identity.ProjectID, name, afterRevision, limit)
	if err != nil {
		return nil, false, err
	}
	stored := make([]operationRow, 0, limit)
	expected := afterRevision + 1
	for rows.Next() {
		row, scanErr := scanOperation(rows)
		if scanErr != nil {
			return nil, false, scanErr
		}
		rowVersion, conversionErr := numconv.Int64ToUint64(row.version)
		if conversionErr != nil {
			return nil, false, conversionErr
		}
		if rowVersion != expected {
			return nil, false, ErrOperationHistoryGap
		}
		stored = append(stored, row)
		expected++
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, false, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, false, err
	}
	values := make([]*jobv1.Operation, 0, len(stored))
	for _, row := range stored {
		value, mapErr := operationRowProto(ctx, tx, row)
		if mapErr != nil {
			return nil, false, mapErr
		}
		values = append(values, clone(value))
	}
	if len(values) == 0 && afterRevision < currentRevision {
		return nil, false, ErrOperationHistoryGap
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return values, done && (len(values) == 0 || values[len(values)-1].GetResourceVersion() == current), nil
}

type schedulerLeaseState struct {
	jobVersion, runVersion, attemptVersion int64
	jobID, runID, attemptID                string
	jobStatus, runStatus                   string
}

// verifyAttemptFence locks scheduler state in its canonical Job -> Run ->
// Attempt order. A renewed fence is accepted only when its deadline exactly
// matches the current durable lease; an older same-epoch receipt therefore
// cannot extend authority beyond the deadline it actually represents.
func verifyAttemptFence(ctx context.Context, tx *sql.Tx, identity Identity, expectedJobID, expectedRunID string, fence *jobv1.LeaseFence, at time.Time, allowCancelling bool) (schedulerLeaseState, error) {
	if err := validateFence(identity, fence, at); err != nil {
		return schedulerLeaseState{}, err
	}
	if fence.GetJobId() != expectedJobID || fence.GetRunId() != expectedRunID {
		return schedulerLeaseState{}, ErrStaleFence
	}
	state := schedulerLeaseState{jobID: expectedJobID, runID: expectedRunID, attemptID: fence.GetAttemptId()}
	var projectID string
	var runEpoch uint64
	err := tx.QueryRowContext(ctx, `SELECT desired_state,version FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, expectedJobID).Scan(&state.jobStatus, &state.jobVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return schedulerLeaseState{}, ErrStaleFence
	}
	if err != nil {
		return schedulerLeaseState{}, err
	}
	err = tx.QueryRowContext(ctx, `SELECT project_id,lease_epoch,status,version FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND job_id=$4 FOR UPDATE`, identity.TenantID, identity.ProjectID, expectedRunID, expectedJobID).Scan(&projectID, &runEpoch, &state.runStatus, &state.runVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return schedulerLeaseState{}, ErrStaleFence
	}
	if err != nil {
		return schedulerLeaseState{}, err
	}
	if projectID != identity.ProjectID || runEpoch != fence.GetLeaseEpoch() ||
		(state.runStatus != "EXECUTING" && (!allowCancelling || state.runStatus != "CANCELLING")) {
		return schedulerLeaseState{}, ErrStaleFence
	}
	var jobID, runID, workerID, digest, status string
	var epoch uint64
	var expiry time.Time
	err = tx.QueryRowContext(ctx, `SELECT job_id,run_id,worker_id,lease_token_digest,lease_epoch,lease_expires_at,status,version FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 FOR UPDATE`, identity.TenantID, identity.ProjectID, fence.GetAttemptId(), expectedRunID).Scan(&jobID, &runID, &workerID, &digest, &epoch, &expiry, &status, &state.attemptVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return schedulerLeaseState{}, ErrStaleFence
	}
	if err != nil {
		return schedulerLeaseState{}, err
	}
	if jobID != expectedJobID || runID != expectedRunID || workerID != identity.WorkerID || epoch != fence.GetLeaseEpoch() || !at.Before(expiry.UTC()) || !expiry.UTC().Equal(fence.GetDeadline().AsTime().UTC()) || (status != "LEASED" && status != "ACTIVE") {
		return schedulerLeaseState{}, ErrStaleFence
	}
	if subtle.ConstantTimeCompare([]byte(digest), []byte(fence.GetLeaseTokenDigest())) != 1 {
		return schedulerLeaseState{}, ErrLeaseToken
	}
	return state, nil
}

func storedFenceMatches(run *trainingv1.TrainingRun, fence *jobv1.LeaseFence) bool {
	active := run.GetActiveFence()
	if active == nil || fence == nil || active.GetDeadline() == nil || fence.GetDeadline() == nil {
		return false
	}
	return active.GetJobId() == fence.GetJobId() && active.GetRunId() == fence.GetRunId() &&
		active.GetAttemptId() == fence.GetAttemptId() && active.GetLeaseEpoch() == fence.GetLeaseEpoch() &&
		active.GetTenantId() == fence.GetTenantId() && active.GetProjectId() == fence.GetProjectId() &&
		subtle.ConstantTimeCompare([]byte(active.GetLeaseTokenDigest()), []byte(fence.GetLeaseTokenDigest())) == 1 &&
		!fence.GetDeadline().AsTime().Before(active.GetDeadline().AsTime())
}

func updateOperationTarget(ctx context.Context, tx *sql.Tx, identity Identity, operationID string, run *trainingv1.TrainingRun, state string, done bool, at time.Time, result sql.NullInt64, errorID sql.NullInt64) error {
	resultSet, err := tx.ExecContext(ctx, `UPDATE operations SET status=$4,version=version+1,done=$5,etag=$6,target_resource_version=$7,target_etag=$8,result_ref_id=$9,error_detail_id=$10,updated_at=$11 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, operationID, state, done, resourceETag(operationID, run.GetRevision()), run.GetRevision(), run.GetEtag(), result, errorID, at.UTC())
	if err != nil {
		return err
	}
	if err = requireOne(resultSet); err != nil {
		return err
	}
	_, row, err := getOperationTx(ctx, tx, identity, operationID, false)
	if err != nil {
		return err
	}
	return recordOperationRevisionTx(ctx, tx, row, at)
}

func (r SQLRepository) startOrResume(ctx context.Context, identity Identity, runRef *commonv1.ResourceRef, checkpointRef *commonv1.ResourceRef, fence *jobv1.LeaseFence, commandContext *commonv1.CommandContext, digest, action string, at time.Time) (*trainingv1.TrainingRun, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if runRef == nil || runRef.GetName() == "" {
		return nil, false, ErrInvalidArgument
	}
	if err := validateScopedReference(identity, runRef, "training run"); err != nil {
		return nil, false, err
	}
	if runRef.GetResourceType() != "training_run" {
		return nil, false, fmt.Errorf("%w: unexpected training run resource type", ErrInvalidArgument)
	}
	if checkpointRef != nil {
		if err := validateScopedReference(identity, checkpointRef, "checkpoint"); err != nil {
			return nil, false, err
		}
		if checkpointRef.GetResourceType() != "checkpoint" {
			return nil, false, fmt.Errorf("%w: unexpected checkpoint resource type", ErrInvalidArgument)
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, action, commandContext.GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		run, _, loadErr := getRunTx(ctx, tx, identity, runRef.GetName(), false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, runRef.GetName(), true)
	if err != nil {
		return nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		return nil, false, ErrTerminal
	}
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		return nil, false, ErrInvalidTransition
	}
	if fence.GetJobId() != row.jobID || fence.GetRunId() != row.schedulerRunID {
		return nil, false, ErrStaleFence
	}
	if runRef.GetResourceVersion() != 0 && runRef.GetResourceVersion() != run.GetRevision() {
		return nil, false, ErrRevisionConflict
	}
	if runRef.GetEtag() != "" && runRef.GetEtag() != run.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	scheduler, err := verifyAttemptFence(ctx, tx, identity, row.jobID, row.schedulerRunID, fence, at, false)
	if err != nil {
		return nil, false, err
	}
	if scheduler.jobStatus != "RUNNING" {
		if scheduler.jobStatus != "QUEUED" && scheduler.jobStatus != "ACCEPTED" {
			return nil, false, ErrInvalidTransition
		}
		jobRevision := scheduler.jobVersion + 1
		result, updateErr := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='RUNNING',version=$5,etag=$6,updated_at=$7 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4`, identity.TenantID, identity.ProjectID, row.jobID, scheduler.jobVersion, jobRevision, resourceETag(row.jobID, jobRevision), at.UTC())
		if updateErr != nil {
			return nil, false, updateErr
		}
		if updateErr = requireOne(result); updateErr != nil {
			return nil, false, updateErr
		}
	}
	if active := run.GetActiveFence(); active != nil && !proto.Equal(active, fence) {
		if active.GetJobId() != fence.GetJobId() || active.GetRunId() != fence.GetRunId() || fence.GetLeaseEpoch() <= active.GetLeaseEpoch() {
			return nil, false, ErrStaleFence
		}
	}
	if checkpointRef != nil {
		checkpoint, _, loadErr := getCheckpointTx(ctx, tx, identity, checkpointRef.GetName(), false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if checkpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_COMMITTED || checkpoint.GetTrainingRunName() != run.GetName() {
			return nil, false, ErrInvalidTransition
		}
		if (checkpointRef.GetResourceVersion() != 0 && checkpointRef.GetResourceVersion() != checkpoint.GetRevision()) || (checkpointRef.GetEtag() != "" && checkpointRef.GetEtag() != checkpoint.GetEtag()) {
			return nil, false, ErrRevisionConflict
		}
	}
	state := trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING
	if checkpointRef != nil {
		state = trainingv1.TrainingRunState_TRAINING_RUN_STATE_RECOVERING
	}
	revision := run.GetRevision() + 1
	etag := resourceETag(run.GetName(), revision)
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6,active_fence_present=true,fence_job_id=$7,fence_run_id=$8,fence_attempt_id=$9,fence_lease_epoch=$10,fence_deadline=$11,fence_tenant_id=$1,fence_project_id=$2,fence_token_digest=$12,start_time=COALESCE(start_time,$13) WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$14`, identity.TenantID, identity.ProjectID, run.GetName(), revision, etag, int32(state), fence.GetJobId(), fence.GetRunId(), fence.GetAttemptId(), fence.GetLeaseEpoch(), fence.GetDeadline().AsTime().UTC(), fence.GetLeaseTokenDigest(), at.UTC(), row.revision)
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, "RUNNING", false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.Started(identity, run, fence, commandContext, at)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, action, run.GetName(), digest, at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, action, commandContext.GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(run), false, nil
}

func (r SQLRepository) StartTrainingAttempt(ctx context.Context, identity Identity, command *trainingv1.StartTrainingAttemptCommand, digest string, at time.Time) (*trainingv1.TrainingRun, bool, error) {
	if command == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	if err := validateCommandDeadline(command.GetDeadline(), at); err != nil {
		return nil, false, err
	}
	if err := validateScopedReference(identity, command.GetDelegatedCapability(), "delegated capability"); err != nil {
		return nil, false, err
	}
	return r.startOrResume(ctx, identity, command.GetTrainingRun(), nil, command.GetFence(), command.GetContext(), digest, "training.start", at)
}

func (r SQLRepository) ResumeTrainingAttempt(ctx context.Context, identity Identity, command *trainingv1.ResumeTrainingAttemptCommand, digest string, at time.Time) (*trainingv1.TrainingRun, bool, error) {
	if command == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	if err := validateCommandDeadline(command.GetDeadline(), at); err != nil {
		return nil, false, err
	}
	if err := validateScopedReference(identity, command.GetDelegatedCapability(), "delegated capability"); err != nil {
		return nil, false, err
	}
	return r.startOrResume(ctx, identity, command.GetTrainingRun(), command.GetCheckpoint(), command.GetFence(), command.GetContext(), digest, "training.resume", at)
}

func (r SQLRepository) CommitTrainingProgress(ctx context.Context, identity Identity, command *trainingv1.CommitTrainingProgressCommand, digest string, at time.Time) (*trainingv1.TrainingProgress, *trainingv1.TrainingRun, bool, error) {
	if err := r.validate(); err != nil {
		return nil, nil, false, err
	}
	if command == nil || command.GetProgress() == nil {
		return nil, nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, nil, false, err
	}
	if data := command.GetProgress().GetLatestDataRange(); data != nil {
		if err := validateScopedReference(identity, data.GetDatasetRelease(), "progress dataset release"); err != nil {
			return nil, nil, false, err
		}
		if data.GetDatasetRelease().GetResourceType() != "dataset_release" {
			return nil, nil, false, fmt.Errorf("%w: unexpected progress dataset resource type", ErrInvalidArgument)
		}
	}
	if err := validateProgressArtifacts(command.GetProgress()); err != nil {
		return nil, nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "training.progress", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		run, _, loadErr := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), false)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, nil, false, err
		}
		return clone(run.GetCommittedProgress()), clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		return nil, nil, false, ErrTerminal
	}
	if !storedFenceMatches(run, command.GetFence()) {
		return nil, nil, false, ErrStaleFence
	}
	if _, err = verifyAttemptFence(ctx, tx, identity, row.jobID, row.schedulerRunID, command.GetFence(), at, false); err != nil {
		return nil, nil, false, err
	}
	progressName, err := canonicalTrainingRunName(identity, command.GetProgress().GetTrainingRunName())
	if err != nil || progressName != run.GetName() || command.GetProgress().GetCommittedAt() == nil {
		return nil, nil, false, ErrInvalidArgument
	}
	if err = command.GetProgress().GetCommittedAt().CheckValid(); err != nil {
		return nil, nil, false, ErrInvalidArgument
	}
	progressTime := command.GetProgress().GetCommittedAt().AsTime().UTC()
	if progressTime.After(at.Add(5*time.Minute)) || (run.GetStartTime() != nil && progressTime.Before(run.GetStartTime().AsTime())) {
		return nil, nil, false, ErrInvalidArgument
	}
	progress := clone(command.GetProgress())
	progress.TrainingRunName = run.GetName()
	if err = monotonicProgress(run.GetCommittedProgress(), progress); err != nil {
		return nil, nil, false, err
	}
	progressID, err := storeProgress(ctx, tx, identity.TenantID, progress)
	if err != nil {
		return nil, nil, false, err
	}
	revision := run.GetRevision() + 1
	etag := resourceETag(run.GetName(), revision)
	runState, operationState := trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING, "RUNNING"
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		runState, operationState = trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING, "CANCELLING"
	}
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6,committed_progress_id=$7,fence_deadline=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9`, identity.TenantID, identity.ProjectID, run.GetName(), revision, etag, int32(runState), progressID, command.GetFence().GetDeadline().AsTime().UTC(), row.revision)
	if err != nil {
		return nil, nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, operationState, false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, nil, false, err
	}
	envelope, err := r.Events.Progress(identity, run, progress, command.GetFence(), command.GetContext(), at)
	if err != nil {
		return nil, nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.progress", run.GetName(), digest, at); err != nil {
		return nil, nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "training.progress", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(progress), clone(run), false, nil
}

func checkpointName(identity Identity, runName string, epoch uint64) (string, error) {
	canonical, err := canonicalTrainingRunName(identity, runName)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s/checkpoints/%d", canonical, epoch), nil
}

func checkpointReference(identity Identity, checkpoint *trainingv1.Checkpoint) *commonv1.ResourceRef {
	if checkpoint == nil {
		return nil
	}
	return &commonv1.ResourceRef{
		ResourceType: "checkpoint", ResourceId: resourceID(checkpoint.GetName()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		ResourceVersion: checkpoint.GetRevision(), Name: checkpoint.GetName(), Etag: checkpoint.GetEtag(),
	}
}

func (r SQLRepository) PrepareCheckpoint(ctx context.Context, identity Identity, command *trainingv1.PrepareCheckpointCommand, digest string, at time.Time) (*trainingv1.Checkpoint, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetSnapshotEpoch() == 0 || command.GetSnapshotEpoch() > maxPostgresBigint || command.GetLogicalStateDescriptor() == nil || command.GetCommittedProgress() == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	if err := validateArtifactReference(command.GetLogicalStateDescriptor(), "logical state descriptor", true); err != nil {
		return nil, false, err
	}
	if err := validateProgressArtifacts(command.GetCommittedProgress()); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "training.checkpoint.prepare", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	name, err := checkpointName(identity, command.GetTrainingRunName(), command.GetSnapshotEpoch())
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, _, loadErr := getCheckpointTx(ctx, tx, identity, name, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), true)
	if err != nil {
		return nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		return nil, false, ErrTerminal
	}
	if !storedFenceMatches(run, command.GetFence()) {
		return nil, false, ErrStaleFence
	}
	if _, err = verifyAttemptFence(ctx, tx, identity, row.jobID, row.schedulerRunID, command.GetFence(), at, false); err != nil {
		return nil, false, err
	}
	progress := clone(command.GetCommittedProgress())
	progress.TrainingRunName = run.GetName()
	if !proto.Equal(run.GetCommittedProgress(), progress) {
		return nil, false, ErrRevisionConflict
	}
	logicalID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetLogicalStateDescriptor())
	if err != nil {
		return nil, false, err
	}
	progressID, err := storeProgress(ctx, tx, identity.TenantID, progress)
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("chk_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	_, err = tx.ExecContext(ctx, `INSERT INTO training_checkpoints (name,tenant_id,project_id,uid,revision,etag,training_run_name,snapshot_epoch,state,logical_state_ref_id,committed_progress_id,prepare_time) VALUES ($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11)`, name, identity.TenantID, identity.ProjectID, uid, etag, run.GetName(), command.GetSnapshotEpoch(), int32(trainingv1.CheckpointState_CHECKPOINT_STATE_PREPARING), logicalID, progressID, at.UTC())
	if err != nil {
		return nil, false, err
	}
	revision := run.GetRevision() + 1
	runState, operationState := trainingv1.TrainingRunState_TRAINING_RUN_STATE_CHECKPOINTING, "RUNNING"
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		runState, operationState = trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING, "CANCELLING"
	}
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6,fence_deadline=$7 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$8`, identity.TenantID, identity.ProjectID, run.GetName(), revision, resourceETag(run.GetName(), revision), int32(runState), command.GetFence().GetDeadline().AsTime().UTC(), row.revision)
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	checkpoint, _, err := getCheckpointTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, operationState, false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.checkpoint.prepare", name, digest, at); err != nil {
		return nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "training.checkpoint.prepare", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(checkpoint), false, nil
}

func (r SQLRepository) CommitCheckpoint(ctx context.Context, identity Identity, command *trainingv1.CommitCheckpointCommand, digest string, at time.Time) (*trainingv1.Checkpoint, *trainingv1.TrainingRun, bool, error) {
	if err := r.validate(); err != nil {
		return nil, nil, false, err
	}
	if command == nil || command.GetSnapshotEpoch() == 0 || command.GetSnapshotEpoch() > maxPostgresBigint || command.GetCheckpointManifest() == nil || command.GetLogicalStateDescriptor() == nil || command.GetCommittedProgress() == nil || command.GetVerificationEvidence() == nil {
		return nil, nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, nil, false, err
	}
	if err := validateVerificationEvidence(command.GetVerificationEvidence(), command.GetCheckpointManifest().GetDigest()); err != nil {
		return nil, nil, false, err
	}
	if err := validateArtifactReference(command.GetCheckpointManifest(), "checkpoint manifest", true); err != nil {
		return nil, nil, false, err
	}
	if err := validateArtifactReference(command.GetLogicalStateDescriptor(), "logical state descriptor", true); err != nil {
		return nil, nil, false, err
	}
	if err := validateArtifactReference(command.GetTopologyEnvelope(), "topology envelope", false); err != nil {
		return nil, nil, false, err
	}
	if err := validateProgressArtifacts(command.GetCommittedProgress()); err != nil {
		return nil, nil, false, err
	}
	if command.GetParentCheckpoint() != nil {
		if err := validateScopedReference(identity, command.GetParentCheckpoint(), "parent checkpoint"); err != nil {
			return nil, nil, false, err
		}
		if command.GetParentCheckpoint().GetResourceType() != "checkpoint" {
			return nil, nil, false, fmt.Errorf("%w: unexpected parent checkpoint resource type", ErrInvalidArgument)
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "training.checkpoint.commit", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, nil, false, err
	}
	name, err := checkpointName(identity, command.GetTrainingRunName(), command.GetSnapshotEpoch())
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		checkpoint, _, checkpointErr := getCheckpointTx(ctx, tx, identity, name, false)
		if checkpointErr != nil {
			return nil, nil, false, checkpointErr
		}
		run, _, runErr := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), false)
		if runErr != nil {
			return nil, nil, false, runErr
		}
		if err = tx.Commit(); err != nil {
			return nil, nil, false, err
		}
		return clone(checkpoint), clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		return nil, nil, false, ErrTerminal
	}
	if !storedFenceMatches(run, command.GetFence()) {
		return nil, nil, false, ErrStaleFence
	}
	if _, err = verifyAttemptFence(ctx, tx, identity, row.jobID, row.schedulerRunID, command.GetFence(), at, false); err != nil {
		return nil, nil, false, err
	}
	checkpoint, checkpointRow, err := getCheckpointTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, nil, false, err
	}
	if checkpoint.GetState() == trainingv1.CheckpointState_CHECKPOINT_STATE_COMMITTED {
		return nil, nil, false, ErrAlreadyExists
	}
	if checkpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_PREPARING && checkpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_WRITING && checkpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_VERIFYING {
		return nil, nil, false, ErrInvalidTransition
	}
	progress := clone(command.GetCommittedProgress())
	progress.TrainingRunName = run.GetName()
	if !proto.Equal(checkpoint.GetLogicalStateDescriptor(), command.GetLogicalStateDescriptor()) || !proto.Equal(run.GetCommittedProgress(), progress) {
		return nil, nil, false, ErrRevisionConflict
	}
	var parentRef *commonv1.ResourceRef
	if parent := command.GetParentCheckpoint(); parent != nil {
		parentCheckpoint, _, parentErr := getCheckpointTx(ctx, tx, identity, parent.GetName(), false)
		if parentErr != nil {
			return nil, nil, false, parentErr
		}
		if parentCheckpoint.GetTrainingRunName() != run.GetName() || parentCheckpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_COMMITTED || parentCheckpoint.GetSnapshotEpoch() >= command.GetSnapshotEpoch() {
			return nil, nil, false, ErrInvalidTransition
		}
		if (parent.GetResourceVersion() != 0 && parent.GetResourceVersion() != parentCheckpoint.GetRevision()) || (parent.GetEtag() != "" && parent.GetEtag() != parentCheckpoint.GetEtag()) {
			return nil, nil, false, ErrRevisionConflict
		}
		parentRef = checkpointReference(identity, parentCheckpoint)
	}
	manifestID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetCheckpointManifest())
	if err != nil {
		return nil, nil, false, err
	}
	logicalID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetLogicalStateDescriptor())
	if err != nil {
		return nil, nil, false, err
	}
	progressID, err := storeProgress(ctx, tx, identity.TenantID, progress)
	if err != nil {
		return nil, nil, false, err
	}
	parentID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, parentRef)
	if err != nil {
		return nil, nil, false, err
	}
	topologyID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetTopologyEnvelope())
	if err != nil {
		return nil, nil, false, err
	}
	committedAt := at.UTC()
	if command.GetCommittedAt() != nil {
		if err = command.GetCommittedAt().CheckValid(); err != nil {
			return nil, nil, false, ErrInvalidArgument
		}
		committedAt = command.GetCommittedAt().AsTime().UTC()
	}
	if checkpoint.GetPrepareTime() != nil && committedAt.Before(checkpoint.GetPrepareTime().AsTime()) {
		return nil, nil, false, ErrInvalidArgument
	}
	if committedAt.After(at.Add(5 * time.Minute)) {
		return nil, nil, false, ErrInvalidArgument
	}
	evidence := command.GetVerificationEvidence()
	revision := checkpoint.GetRevision() + 1
	result, err := tx.ExecContext(ctx, `UPDATE training_checkpoints SET revision=$4,etag=$5,state=$6,checkpoint_manifest_ref_id=$7,logical_state_ref_id=$8,committed_progress_id=$9,parent_checkpoint_ref_id=$10,topology_envelope_ref_id=$11,evidence_digest=$12,evidence_subject_digest=$13,evidence_kind=$14,evidence_policy_digest=$15,verify_time=$16,commit_time=$16 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$17`, identity.TenantID, identity.ProjectID, name, revision, resourceETag(name, revision), int32(trainingv1.CheckpointState_CHECKPOINT_STATE_COMMITTED), manifestID, logicalID, progressID, parentID, topologyID, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest(), committedAt, checkpointRow.revision)
	if err != nil {
		return nil, nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, nil, false, err
	}
	checkpointRef := &commonv1.ResourceRef{ResourceType: "checkpoint", ResourceId: resourceID(name), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: revision, Name: name, Etag: resourceETag(name, revision)}
	checkpointRefID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, checkpointRef)
	if err != nil {
		return nil, nil, false, err
	}
	runRevision := run.GetRevision() + 1
	runState, operationState := trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING, "RUNNING"
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		runState, operationState = trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING, "CANCELLING"
	}
	result, err = tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6,committed_progress_id=$7,latest_checkpoint_ref_id=$8,fence_deadline=$9 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$10`, identity.TenantID, identity.ProjectID, run.GetName(), runRevision, resourceETag(run.GetName(), runRevision), int32(runState), progressID, checkpointRefID, command.GetFence().GetDeadline().AsTime().UTC(), row.revision)
	if err != nil {
		return nil, nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, nil, false, err
	}
	checkpoint, _, err = getCheckpointTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, operationState, false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, nil, false, err
	}
	envelope, err := r.Events.Checkpoint(identity, run, checkpoint, command.GetFence(), command.GetContext(), committedAt)
	if err != nil {
		return nil, nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.checkpoint.commit", name, digest, at); err != nil {
		return nil, nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "training.checkpoint.commit", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(checkpoint), clone(run), false, nil
}

func terminalState(classification trainingv1.TrainingTerminalClassification) (trainingv1.TrainingRunState, string, error) {
	switch classification {
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED:
		return trainingv1.TrainingRunState_TRAINING_RUN_STATE_COMPLETED, "SUCCEEDED", nil
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED:
		return trainingv1.TrainingRunState_TRAINING_RUN_STATE_CANCELLED, "CANCELLED", nil
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED:
		return 0, "", ErrInvalidArgument
	default:
		return trainingv1.TrainingRunState_TRAINING_RUN_STATE_FAILED, "FAILED", nil
	}
}

func schedulerTerminalState(classification trainingv1.TrainingTerminalClassification) (attempt, run, job string, err error) {
	switch classification {
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED:
		return "COMPLETED", "SUCCEEDED", "SUCCEEDED", nil
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED:
		return "CANCELLED", "CANCELLED", "CANCELLED", nil
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED:
		return "", "", "", ErrInvalidArgument
	default:
		return "FAILED", "FAILED", "FAILED", nil
	}
}

func reconcileSchedulerTerminal(ctx context.Context, tx *sql.Tx, identity Identity, state schedulerLeaseState, classification trainingv1.TrainingTerminalClassification, resultID, errorID sql.NullInt64, completedAt time.Time) error {
	attemptStatus, runStatus, jobStatus, err := schedulerTerminalState(classification)
	if err != nil {
		return err
	}
	if state.runStatus == "CANCELLING" && classification != trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED {
		return ErrInvalidTransition
	}
	result, err := tx.ExecContext(ctx, `UPDATE attempts SET status=$5,version=$6,error_detail_id=$7,completed_at=$8,updated_at=$8 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4 AND status IN ('LEASED','ACTIVE')`, identity.TenantID, identity.ProjectID, state.attemptID, state.attemptVersion, attemptStatus, state.attemptVersion+1, errorID, completedAt.UTC())
	if err != nil {
		return err
	}
	if err = requireOne(result); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM attempt_output_refs WHERE tenant_id=$1 AND attempt_id=$2`, identity.TenantID, state.attemptID); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM run_output_refs WHERE tenant_id=$1 AND run_id=$2`, identity.TenantID, state.runID); err != nil {
		return err
	}
	if resultID.Valid {
		if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_output_refs (tenant_id,project_id,attempt_id,ordinal,artifact_ref_id) VALUES ($1,$2,$3,0,$4)`, identity.TenantID, identity.ProjectID, state.attemptID, resultID.Int64); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs (tenant_id,project_id,run_id,ordinal,artifact_ref_id) VALUES ($1,$2,$3,0,$4)`, identity.TenantID, identity.ProjectID, state.runID, resultID.Int64); err != nil {
			return err
		}
	}
	runVersion := state.runVersion + 1
	result, err = tx.ExecContext(ctx, `UPDATE runs SET status=$5,version=$6,etag=$7,error_detail_id=$8,completed_at=$9,updated_at=$9 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4 AND status=$10`, identity.TenantID, identity.ProjectID, state.runID, state.runVersion, runStatus, runVersion, resourceETag(state.runID, runVersion), errorID, completedAt.UTC(), state.runStatus)
	if err != nil {
		return err
	}
	if err = requireOne(result); err != nil {
		return err
	}
	jobVersion := state.jobVersion + 1
	result, err = tx.ExecContext(ctx, `UPDATE jobs SET desired_state=$5,version=$6,etag=$7,updated_at=$8 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4 AND desired_state IN ('ACCEPTED','QUEUED','RUNNING','CANCELLING')`, identity.TenantID, identity.ProjectID, state.jobID, state.jobVersion, jobStatus, jobVersion, resourceETag(state.jobID, jobVersion), completedAt.UTC())
	if err != nil {
		return err
	}
	return requireOne(result)
}

func (r SQLRepository) CompleteTrainingRun(ctx context.Context, identity Identity, command *trainingv1.CompleteTrainingRunCommand, digest string, at time.Time) (*trainingv1.TrainingRun, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	if err := validateTerminalCommand(command); err != nil {
		return nil, false, err
	}
	if err := validateDurableError(identity, command.GetError()); err != nil {
		return nil, false, err
	}
	if err := validateArtifactReference(command.GetResultManifest(), "result manifest", command.GetClassification() == trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED); err != nil {
		return nil, false, err
	}
	if command.GetFinalCheckpoint() != nil {
		if err := validateScopedReference(identity, command.GetFinalCheckpoint(), "final checkpoint"); err != nil {
			return nil, false, err
		}
		if command.GetFinalCheckpoint().GetResourceType() != "checkpoint" {
			return nil, false, fmt.Errorf("%w: unexpected final checkpoint resource type", ErrInvalidArgument)
		}
	}
	state, operationState, err := terminalState(command.GetClassification())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "training.complete", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		run, _, loadErr := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), true)
	if err != nil {
		return nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		return nil, false, ErrTerminal
	}
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING && command.GetClassification() != trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED {
		return nil, false, ErrInvalidTransition
	}
	if !storedFenceMatches(run, command.GetFence()) {
		return nil, false, ErrStaleFence
	}
	allowCancelling := command.GetClassification() == trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED
	scheduler, err := verifyAttemptFence(ctx, tx, identity, row.jobID, row.schedulerRunID, command.GetFence(), at, allowCancelling)
	if err != nil {
		return nil, false, err
	}
	completedAt := at.UTC()
	if command.GetCompletedAt() != nil {
		if err = command.GetCompletedAt().CheckValid(); err != nil {
			return nil, false, ErrInvalidArgument
		}
		completedAt = command.GetCompletedAt().AsTime().UTC()
	}
	if run.GetStartTime() != nil && completedAt.Before(run.GetStartTime().AsTime()) {
		return nil, false, ErrInvalidArgument
	}
	if completedAt.After(at.Add(5 * time.Minute)) {
		return nil, false, ErrInvalidArgument
	}
	var finalCheckpointRef *commonv1.ResourceRef
	if command.GetFinalCheckpoint() != nil && command.GetFinalCheckpoint().GetName() != "" {
		checkpoint, _, checkpointErr := getCheckpointTx(ctx, tx, identity, command.GetFinalCheckpoint().GetName(), false)
		if checkpointErr != nil {
			return nil, false, checkpointErr
		}
		if checkpoint.GetTrainingRunName() != run.GetName() || checkpoint.GetState() != trainingv1.CheckpointState_CHECKPOINT_STATE_COMMITTED {
			return nil, false, ErrInvalidTransition
		}
		if (command.GetFinalCheckpoint().GetResourceVersion() != 0 && command.GetFinalCheckpoint().GetResourceVersion() != checkpoint.GetRevision()) || (command.GetFinalCheckpoint().GetEtag() != "" && command.GetFinalCheckpoint().GetEtag() != checkpoint.GetEtag()) {
			return nil, false, ErrRevisionConflict
		}
		finalCheckpointRef = checkpointReference(identity, checkpoint)
	}
	resultID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetResultManifest())
	if err != nil {
		return nil, false, err
	}
	checkpointID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, finalCheckpointRef)
	if err != nil {
		return nil, false, err
	}
	errorID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, command.GetError())
	if err != nil {
		return nil, false, err
	}
	if err = reconcileSchedulerTerminal(ctx, tx, identity, scheduler, command.GetClassification(), resultID, errorID, completedAt); err != nil {
		return nil, false, err
	}
	revision := run.GetRevision() + 1
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6,active_fence_present=false,fence_job_id='',fence_run_id='',fence_attempt_id='',fence_lease_epoch=0,fence_deadline=NULL,fence_tenant_id='',fence_project_id='',fence_token_digest='',latest_checkpoint_ref_id=$7,result_manifest_ref_id=$8,terminal_classification=$9,error_detail_id=$10,complete_time=$11 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$12`, identity.TenantID, identity.ProjectID, run.GetName(), revision, resourceETag(run.GetName(), revision), int32(state), checkpointID, resultID, int32(command.GetClassification()), errorID, completedAt, row.revision)
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, operationState, true, at, resultID, errorID); err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.Completed(identity, run, command.GetFence(), command.GetContext(), completedAt)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.complete", run.GetName(), digest, at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "training.complete", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(run), false, nil
}

// CancelTrainingRun is completed in cancellation_sql.go so the typed
// TrainingCancellationRequested event can be compiled from its generated
// binding without weakening this repository's transactional boundary.
