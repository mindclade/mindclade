package training

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

type scanner interface{ Scan(...any) error }

type runRow struct {
	name, tenantID, projectID, uid, etag, operationID, jobID, schedulerRunID, policy string
	revision                                                                         int64
	state                                                                            int32
	trainingRecipe, datasetRelease, modelRelease                                     sql.NullInt64
	executablePlan, hardwareTopology, usePolicy                                      sql.NullInt64
	fencePresent                                                                     bool
	fenceJob, fenceRun, fenceAttempt, fenceTenant, fenceProject, fenceDigest         string
	fenceEpoch                                                                       uint64
	fenceDeadline                                                                    sql.NullTime
	progress, latestCheckpoint, resultManifest, errorDetail                          sql.NullInt64
	terminal                                                                         int32
	createTime                                                                       time.Time
	startTime, completeTime                                                          sql.NullTime
}

const runColumns = `name, tenant_id, project_id, uid, revision, etag, state,
operation_id, job_id, scheduler_run_id, training_recipe_ref_id, dataset_release_ref_id,
model_release_ref_id, executable_plan_ref_id, hardware_topology_ref_id,
use_policy_ref_id, active_fence_present, fence_job_id, fence_run_id,
fence_attempt_id, fence_lease_epoch, fence_deadline, fence_tenant_id,
fence_project_id, fence_token_digest, committed_progress_id,
latest_checkpoint_ref_id, result_manifest_ref_id, terminal_classification,
error_detail_id, policy_classification, create_time, start_time, complete_time`

func scanRun(row scanner) (runRow, error) {
	var value runRow
	err := row.Scan(
		&value.name, &value.tenantID, &value.projectID, &value.uid, &value.revision, &value.etag, &value.state,
		&value.operationID, &value.jobID, &value.schedulerRunID, &value.trainingRecipe, &value.datasetRelease, &value.modelRelease,
		&value.executablePlan, &value.hardwareTopology, &value.usePolicy, &value.fencePresent,
		&value.fenceJob, &value.fenceRun, &value.fenceAttempt, &value.fenceEpoch, &value.fenceDeadline,
		&value.fenceTenant, &value.fenceProject, &value.fenceDigest, &value.progress,
		&value.latestCheckpoint, &value.resultManifest, &value.terminal, &value.errorDetail,
		&value.policy, &value.createTime, &value.startTime, &value.completeTime,
	)
	return value, err
}

func getRunTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*trainingv1.TrainingRun, runRow, error) {
	canonicalName, err := canonicalTrainingRunName(identity, name)
	if err != nil {
		return nil, runRow{}, err
	}
	query := `SELECT ` + runColumns + ` FROM training_runs WHERE tenant_id = $1 AND project_id = $2 AND name = $3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanRun(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonicalName))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, runRow{}, ErrNotFound
	}
	if err != nil {
		return nil, runRow{}, err
	}
	value, err := runRowProto(ctx, tx, row)
	return value, row, err
}

func runRowProto(ctx context.Context, tx *sql.Tx, row runRow) (*trainingv1.TrainingRun, error) {
	trainingRecipe, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.trainingRecipe)
	if err != nil {
		return nil, err
	}
	datasetRelease, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.datasetRelease)
	if err != nil {
		return nil, err
	}
	modelRelease, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.modelRelease)
	if err != nil {
		return nil, err
	}
	executablePlan, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.executablePlan)
	if err != nil {
		return nil, err
	}
	hardwareTopology, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.hardwareTopology)
	if err != nil {
		return nil, err
	}
	usePolicy, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.usePolicy)
	if err != nil {
		return nil, err
	}
	progress, err := loadProgress(ctx, tx, row.tenantID, row.progress)
	if err != nil {
		return nil, err
	}
	latestCheckpoint, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.latestCheckpoint)
	if err != nil {
		return nil, err
	}
	resultManifest, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.resultManifest)
	if err != nil {
		return nil, err
	}
	errorDetail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenantID, row.errorDetail)
	if err != nil {
		return nil, err
	}
	labels, err := loadLabels(ctx, tx, row.tenantID, row.projectID, row.name)
	if err != nil {
		return nil, err
	}
	value := &trainingv1.TrainingRun{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantName: "tenants/" + row.tenantID, ProjectName: "tenants/" + row.tenantID + "/projects/" + row.projectID,
		State: trainingv1.TrainingRunState(row.state), TrainingRecipe: trainingRecipe,
		DatasetRelease: datasetRelease, ModelRelease: modelRelease, ExecutablePlan: executablePlan,
		HardwareTopology: hardwareTopology, UsePolicy: usePolicy, CommittedProgress: progress,
		LatestCheckpoint: latestCheckpoint, ResultManifest: resultManifest,
		TerminalClassification: trainingv1.TrainingTerminalClassification(row.terminal), Error: errorDetail,
		Labels: labels, PolicyClassification: row.policy, CreateTime: timestamppb.New(row.createTime.UTC()),
		StartTime: nullTimestamp(row.startTime), CompleteTime: nullTimestamp(row.completeTime),
	}
	if row.fencePresent {
		value.ActiveFence = &jobv1.LeaseFence{
			JobId: row.fenceJob, RunId: row.fenceRun, AttemptId: row.fenceAttempt,
			LeaseEpoch: row.fenceEpoch, Deadline: nullTimestamp(row.fenceDeadline),
			TenantId: row.fenceTenant, ProjectId: row.fenceProject, LeaseTokenDigest: row.fenceDigest,
		}
	}
	return value, nil
}

func loadLabels(ctx context.Context, tx *sql.Tx, tenantID, projectID, runName string) (map[string]string, error) {
	rows, err := tx.QueryContext(ctx, `SELECT label_key, label_value FROM training_run_labels WHERE tenant_id=$1 AND project_id=$2 AND training_run_name=$3 ORDER BY label_key`, tenantID, projectID, runName)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	values := make(map[string]string)
	for rows.Next() {
		var key, value string
		if err := rows.Scan(&key, &value); err != nil {
			return nil, err
		}
		values[key] = value
	}
	return values, rows.Err()
}

func storeProgress(ctx context.Context, tx *sql.Tx, tenantID string, value *trainingv1.TrainingProgress) (sql.NullInt64, error) {
	if value == nil {
		return sql.NullInt64{}, nil
	}
	if err := validateProgressStorage(value); err != nil {
		return sql.NullInt64{}, err
	}
	var updatePresent, dataPresent bool
	var updateValue, split, partition string
	var updateSequence, start, end uint64
	if update := value.GetLatestCommittedUpdate(); update != nil {
		updatePresent = true
		updateValue = update.GetValue()
		updateSequence = update.GetSequence()
	}
	var datasetID, batchID sql.NullInt64
	if data := value.GetLatestDataRange(); data != nil {
		dataPresent = true
		split, partition = data.GetSplitName(), data.GetPartitionId()
		start, end = data.GetStartOrdinal(), data.GetEndOrdinalExclusive()
		var err error
		datasetID, err = platformdb.StoreResourceRef(ctx, tx, tenantID, data.GetDatasetRelease())
		if err != nil {
			return sql.NullInt64{}, err
		}
		batchID, err = platformdb.StoreArtifactRef(ctx, tx, tenantID, data.GetBatchReceipt())
		if err != nil {
			return sql.NullInt64{}, err
		}
	}
	ledgerID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetProgressLedger())
	if err != nil {
		return sql.NullInt64{}, err
	}
	metricID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetMetricSnapshot())
	if err != nil {
		return sql.NullInt64{}, err
	}
	var committedAt sql.NullTime
	if value.GetCommittedAt() != nil {
		if timestampErr := value.GetCommittedAt().CheckValid(); timestampErr != nil {
			return sql.NullInt64{}, timestampErr
		}
		committedAt = sql.NullTime{Time: value.GetCommittedAt().AsTime().UTC(), Valid: true}
	}
	var id int64
	err = tx.QueryRowContext(ctx, `INSERT INTO training_progress_snapshots (
tenant_id, training_run_name, progress_revision, latest_update_present,
latest_update_value, latest_update_sequence, committed_update_count,
committed_sample_count, committed_token_count, effective_work_units,
effective_work_unit_name, data_range_present, data_range_dataset_ref_id,
data_range_split_name, data_range_partition_id, data_range_start_ordinal,
data_range_end_ordinal, data_range_batch_ref_id, progress_ledger_ref_id,
metric_snapshot_ref_id, committed_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21) RETURNING id`,
		tenantID, value.GetTrainingRunName(), value.GetProgressRevision(), updatePresent, updateValue, updateSequence,
		value.GetCommittedUpdateCount(), value.GetCommittedSampleCount(), value.GetCommittedTokenCount(),
		value.GetEffectiveWorkUnits(), value.GetEffectiveWorkUnitName(), dataPresent, datasetID, split, partition,
		start, end, batchID, ledgerID, metricID, committedAt).Scan(&id)
	if err != nil {
		return sql.NullInt64{}, fmt.Errorf("store training progress: %w", err)
	}
	return sql.NullInt64{Int64: id, Valid: true}, nil
}

func loadProgress(ctx context.Context, tx *sql.Tx, tenantID string, id sql.NullInt64) (*trainingv1.TrainingProgress, error) {
	if !id.Valid {
		return nil, nil
	}
	var value trainingv1.TrainingProgress
	var updatePresent, dataPresent bool
	var updateValue, split, partition string
	var updateSequence, start, end uint64
	var datasetID, batchID, ledgerID, metricID sql.NullInt64
	var committedAt sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT training_run_name, progress_revision,
latest_update_present, latest_update_value, latest_update_sequence,
committed_update_count, committed_sample_count, committed_token_count,
effective_work_units, effective_work_unit_name, data_range_present,
data_range_dataset_ref_id, data_range_split_name, data_range_partition_id,
data_range_start_ordinal, data_range_end_ordinal, data_range_batch_ref_id,
progress_ledger_ref_id, metric_snapshot_ref_id, committed_at
FROM training_progress_snapshots WHERE tenant_id=$1 AND id=$2`, tenantID, id.Int64).Scan(
		&value.TrainingRunName, &value.ProgressRevision, &updatePresent, &updateValue, &updateSequence,
		&value.CommittedUpdateCount, &value.CommittedSampleCount, &value.CommittedTokenCount,
		&value.EffectiveWorkUnits, &value.EffectiveWorkUnitName, &dataPresent, &datasetID,
		&split, &partition, &start, &end, &batchID, &ledgerID, &metricID, &committedAt)
	if err != nil {
		return nil, err
	}
	if updatePresent {
		value.LatestCommittedUpdate = &trainingv1.UpdateId{Value: updateValue, Sequence: updateSequence}
	}
	if dataPresent {
		dataset, datasetErr := platformdb.LoadResourceRef(ctx, tx, tenantID, datasetID)
		if datasetErr != nil {
			return nil, datasetErr
		}
		batch, batchErr := platformdb.LoadArtifactRef(ctx, tx, tenantID, batchID)
		if batchErr != nil {
			return nil, batchErr
		}
		value.LatestDataRange = &trainingv1.DataProgressRange{DatasetRelease: dataset, SplitName: split, PartitionId: partition, StartOrdinal: start, EndOrdinalExclusive: end, BatchReceipt: batch}
	}
	value.ProgressLedger, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, ledgerID)
	if err != nil {
		return nil, err
	}
	value.MetricSnapshot, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, metricID)
	if err != nil {
		return nil, err
	}
	value.CommittedAt = nullTimestamp(committedAt)
	return &value, nil
}

type checkpointRow struct {
	name, tenantID, projectID, uid, etag, runName                   string
	revision                                                        int64
	epoch                                                           uint64
	state                                                           int32
	manifest, logicalState, progress, parent, topology, errorDetail sql.NullInt64
	evidenceDigest, evidenceSubject, evidenceKind, evidencePolicy   string
	prepareTime                                                     time.Time
	verifyTime, commitTime, revokeTime                              sql.NullTime
}

const checkpointColumns = `name, tenant_id, project_id, uid, revision, etag,
training_run_name, snapshot_epoch, state, checkpoint_manifest_ref_id,
logical_state_ref_id, committed_progress_id, parent_checkpoint_ref_id,
topology_envelope_ref_id, evidence_digest, evidence_subject_digest,
evidence_kind, evidence_policy_digest, error_detail_id, prepare_time,
verify_time, commit_time, revoke_time`

func scanCheckpoint(row scanner) (checkpointRow, error) {
	var value checkpointRow
	err := row.Scan(&value.name, &value.tenantID, &value.projectID, &value.uid, &value.revision, &value.etag,
		&value.runName, &value.epoch, &value.state, &value.manifest, &value.logicalState, &value.progress,
		&value.parent, &value.topology, &value.evidenceDigest, &value.evidenceSubject,
		&value.evidenceKind, &value.evidencePolicy, &value.errorDetail, &value.prepareTime,
		&value.verifyTime, &value.commitTime, &value.revokeTime)
	return value, err
}

func getCheckpointTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*trainingv1.Checkpoint, checkpointRow, error) {
	query := `SELECT ` + checkpointColumns + ` FROM training_checkpoints WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanCheckpoint(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, checkpointRow{}, ErrNotFound
	}
	if err != nil {
		return nil, checkpointRow{}, err
	}
	value, err := checkpointRowProto(ctx, tx, row)
	return value, row, err
}

func checkpointRowProto(ctx context.Context, tx *sql.Tx, row checkpointRow) (*trainingv1.Checkpoint, error) {
	manifest, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.manifest)
	if err != nil {
		return nil, err
	}
	logicalState, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.logicalState)
	if err != nil {
		return nil, err
	}
	progress, err := loadProgress(ctx, tx, row.tenantID, row.progress)
	if err != nil {
		return nil, err
	}
	parent, err := platformdb.LoadResourceRef(ctx, tx, row.tenantID, row.parent)
	if err != nil {
		return nil, err
	}
	topology, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.topology)
	if err != nil {
		return nil, err
	}
	errorDetail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenantID, row.errorDetail)
	if err != nil {
		return nil, err
	}
	value := &trainingv1.Checkpoint{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantName: "tenants/" + row.tenantID, ProjectName: "tenants/" + row.tenantID + "/projects/" + row.projectID,
		TrainingRunName: row.runName, SnapshotEpoch: row.epoch, State: trainingv1.CheckpointState(row.state),
		CheckpointManifest: manifest, LogicalStateDescriptor: logicalState, CommittedProgress: progress,
		ParentCheckpoint: parent, TopologyEnvelope: topology, Error: errorDetail,
		PrepareTime: timestamppb.New(row.prepareTime.UTC()), VerifyTime: nullTimestamp(row.verifyTime),
		CommitTime: nullTimestamp(row.commitTime), RevokeTime: nullTimestamp(row.revokeTime),
	}
	if row.evidenceDigest != "" {
		value.VerificationEvidence = &artifactv1.EvidenceRef{Digest: row.evidenceDigest, SubjectDigest: row.evidenceSubject, EvidenceKind: row.evidenceKind, PolicyDigest: row.evidencePolicy}
	}
	return value, nil
}

type operationRow struct {
	id, tenantID, projectID, jobID, etag, requestHash, status                 string
	version                                                                   int64
	done                                                                      bool
	targetPresent                                                             bool
	targetType, targetID, targetTenant, targetProject, targetName, targetETag string
	targetVersion                                                             int64
	result, errorDetail                                                       sql.NullInt64
	createdAt, updatedAt                                                      time.Time
}

const operationColumns = `id, tenant_id, project_id, job_id, target_present,
target_resource_type, target_resource_id, target_tenant_id, target_project_id,
target_resource_version, target_name, target_etag, status, version, done, etag,
result_ref_id, error_detail_id, request_hash, created_at, updated_at`

const operationRevisionColumns = `operation_id, tenant_id, project_id, job_id, target_present,
target_resource_type, target_resource_id, target_tenant_id, target_project_id,
target_resource_version, target_name, target_etag, status, revision, done, etag,
result_ref_id, error_detail_id, ''::text AS request_hash, created_at, updated_at`

const (
	operationHistoryRetention = int64(256)
	operationWatchBatchLimit  = 64
)

func scanOperation(row scanner) (operationRow, error) {
	var value operationRow
	err := row.Scan(&value.id, &value.tenantID, &value.projectID, &value.jobID, &value.targetPresent,
		&value.targetType, &value.targetID, &value.targetTenant, &value.targetProject, &value.targetVersion,
		&value.targetName, &value.targetETag, &value.status, &value.version, &value.done, &value.etag,
		&value.result, &value.errorDetail, &value.requestHash, &value.createdAt, &value.updatedAt)
	return value, err
}

func getOperationTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*operationv1.Operation, operationRow, error) {
	query := `SELECT ` + operationColumns + ` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanOperation(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, operationRow{}, ErrNotFound
	}
	if err != nil {
		return nil, operationRow{}, err
	}
	value, err := operationRowProto(ctx, tx, row)
	return value, row, err
}

func operationRowProto(ctx context.Context, tx *sql.Tx, row operationRow) (*operationv1.Operation, error) {
	result, err := platformdb.LoadArtifactRef(ctx, tx, row.tenantID, row.result)
	if err != nil {
		return nil, err
	}
	errorDetail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenantID, row.errorDetail)
	if err != nil {
		return nil, err
	}
	state, err := operationState(row.status)
	if err != nil {
		return nil, err
	}
	value := &operationv1.Operation{
		OperationId: row.id, TenantId: row.tenantID, ProjectId: row.projectID, JobId: row.jobID,
		State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag, Result: result, Error: errorDetail,
		CreatedAt: timestamppb.New(row.createdAt.UTC()), UpdatedAt: timestamppb.New(row.updatedAt.UTC()),
	}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant, ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag}
	}
	return value, nil
}

// recordOperationRevisionTx appends the exact post-mutation state and then
// advances the explicit bounded-retention floor in the same transaction.
// A cursor for revision N remains valid while N+1 is retained.
func recordOperationRevisionTx(ctx context.Context, tx *sql.Tx, row operationRow, recordedAt time.Time) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO operation_revisions (
operation_id,tenant_id,project_id,revision,job_id,target_present,
target_resource_type,target_resource_id,target_tenant_id,target_project_id,
target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,
error_detail_id,created_at,updated_at,recorded_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)`,
		row.id, row.tenantID, row.projectID, row.version, row.jobID, row.targetPresent,
		row.targetType, row.targetID, row.targetTenant, row.targetProject, row.targetVersion,
		row.targetName, row.targetETag, row.status, row.done, row.etag, row.result,
		row.errorDetail, row.createdAt.UTC(), row.updatedAt.UTC(), recordedAt.UTC())
	if err != nil {
		return err
	}
	floor := row.version - operationHistoryRetention + 1
	if floor < 1 {
		floor = 1
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM operation_revisions
WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision < $4`,
		row.tenantID, row.projectID, row.id, floor); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE operations SET history_floor_version=$4
WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$5`,
		row.tenantID, row.projectID, row.id, floor, row.version)
	if err != nil {
		return err
	}
	return requireOne(result)
}

func operationState(value string) (operationv1.OperationState, error) {
	switch value {
	case "PENDING":
		return operationv1.OperationState_OPERATION_STATE_PENDING, nil
	case "RUNNING":
		return operationv1.OperationState_OPERATION_STATE_RUNNING, nil
	case "SUCCEEDED":
		return operationv1.OperationState_OPERATION_STATE_SUCCEEDED, nil
	case "FAILED":
		return operationv1.OperationState_OPERATION_STATE_FAILED, nil
	case "CANCELLING":
		return operationv1.OperationState_OPERATION_STATE_CANCELLING, nil
	case "CANCELLED":
		return operationv1.OperationState_OPERATION_STATE_CANCELLED, nil
	default:
		return 0, fmt.Errorf("unknown operation state %q", value)
	}
}

func nullTimestamp(value sql.NullTime) *timestamppb.Timestamp {
	if !value.Valid {
		return nil
	}
	return timestamppb.New(value.Time.UTC())
}
