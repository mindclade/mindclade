package evaluations

import (
	"context"
	"crypto/subtle"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	jobsapp "github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	operationsapp "github.com/mindclade/mindclade/services/control_plane/internal/operations"
)

func (repository SQLRepository) CreateRun(ctx context.Context, identity Identity, request *internalevaluationv1.CreateEvaluationRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	request = clone(request)
	if err := validateCreateRun(identity, request); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	name := runName(identity, request.GetEvaluationRunId())
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "evaluation.run.create", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM evaluation_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	suiteID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetSuite())
	if err != nil {
		return nil, false, err
	}
	snapshotID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetSnapshot())
	if err != nil {
		return nil, false, err
	}
	modelID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, request.GetModelRelease())
	if err != nil {
		return nil, false, err
	}
	protocolID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetInferenceProtocol())
	if err != nil {
		return nil, false, err
	}
	executableID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetExecutablePlan())
	if err != nil {
		return nil, false, err
	}
	providerID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetProviderManifest())
	if err != nil {
		return nil, false, err
	}
	kernelID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetKernelQualification())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("eval_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	target := &commonv1.ResourceRef{ResourceType: "evaluation_run", ResourceId: request.GetEvaluationRunId(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: name, Etag: etag}
	operation, schedulerRunID, err := insertQueuedWork(ctx, tx, identity, target, "evaluation.run", digest, request.GetInferenceProtocol().GetDigest(), snapshotID, protocolID, executableID, at)
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO evaluation_runs(tenant_id,project_id,name,uid,revision,etag,suite_ref_id,snapshot_ref_id,model_release_ref_id,inference_protocol_ref_id,executable_plan_ref_id,provider_manifest_ref_id,kernel_qualification_ref_id,request_digest,operation_id,job_id,scheduler_run_id,attempt_id,lease_epoch,state,completed_samples,total_samples,failure_ref_id,create_time,update_time,end_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'',0,$17,0,NULL,NULL,$18,$18,NULL)`, identity.TenantID, identity.ProjectID, name, uid, etag, suiteID, snapshotID, modelID, protocolID, executableID, providerID, kernelID, digest, operation.GetOperationId(), operation.GetJobId(), schedulerRunID, int32(evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_QUEUED), at.UTC()); err != nil {
		return nil, false, err
	}
	for ordinal, dataset := range request.GetDatasets() {
		id, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, dataset)
		if storeErr != nil {
			return nil, false, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO evaluation_run_datasets(tenant_id,project_id,evaluation_run_name,ordinal,dataset_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); storeErr != nil {
			return nil, false, storeErr
		}
	}
	for ordinal, policy := range request.GetPolicySnapshots() {
		id, storeErr := storePolicySnapshot(ctx, tx, identity.TenantID, policy)
		if storeErr != nil {
			return nil, false, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO evaluation_run_policies(tenant_id,project_id,evaluation_run_name,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); storeErr != nil {
			return nil, false, storeErr
		}
	}
	run, row, err := getRunTx(ctx, tx, identity, name, false)
	_ = row
	if err != nil {
		return nil, false, err
	}
	created, err := repository.Events.RunCreated(identity, run, operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	requested, err := repository.Events.JobRequested(identity, operation, request.GetInferenceProtocol().GetDigest(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "evaluation.run.create", request.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{created, requested}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetRun(ctx context.Context, identity Identity, name string) (*evaluationv1.EvaluationRun, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
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

func (repository SQLRepository) ListRuns(ctx context.Context, identity Identity, page RunPage) ([]*evaluationv1.EvaluationRun, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, "", time.Time{}, err
	}
	if page.Limit < 1 || page.Limit > maximumPageSize {
		return nil, "", time.Time{}, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	conditions := []string{"tenant_id=$1", "project_id=$2"}
	arguments := []any{identity.TenantID, identity.ProjectID}
	if page.State != evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_UNSPECIFIED {
		arguments = append(arguments, int32(page.State))
		conditions = append(conditions, fmt.Sprintf("state=$%d", len(arguments)))
	}
	ascending := page.Order == "create_time asc,name asc"
	if !page.AfterTime.IsZero() {
		arguments = append(arguments, page.AfterTime.UTC(), page.AfterName)
		operator := "<"
		if ascending {
			operator = ">"
		}
		conditions = append(conditions, fmt.Sprintf("(create_time,name) %s ($%d,$%d)", operator, len(arguments)-1, len(arguments)))
	}
	arguments = append(arguments, page.Limit+1)
	direction := "DESC"
	if ascending {
		direction = "ASC"
	}
	query := `SELECT ` + runColumns + ` FROM evaluation_runs WHERE ` + strings.Join(conditions, " AND ") + ` ORDER BY create_time ` + direction + `,name ` + direction + ` LIMIT $` + strconv.Itoa(len(arguments)) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	rows, err := tx.QueryContext(ctx, query, arguments...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = rows.Close() }()
	rowValues := make([]runRow, 0, page.Limit+1)
	for rows.Next() {
		row, scanErr := scanRun(rows)
		if scanErr != nil {
			return nil, "", time.Time{}, scanErr
		}
		rowValues = append(rowValues, row)
	}
	if err = rows.Err(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err = rows.Close(); err != nil {
		return nil, "", time.Time{}, err
	}
	values := make([]*evaluationv1.EvaluationRun, 0, len(rowValues))
	for _, row := range rowValues {
		value, mapErr := runProto(ctx, tx, row)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	next := ""
	if len(values) > page.Limit {
		last := values[page.Limit-1]
		next, err = repository.Pagination.encode(pageToken{Kind: "evaluation-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.GetCreateTime().AsTime().UTC().Format(time.RFC3339Nano), AfterName: last.GetName()})
		if err != nil {
			return nil, "", time.Time{}, err
		}
		values = values[:page.Limit]
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), next, readAt.UTC(), nil
}

func (repository SQLRepository) CancelRun(ctx context.Context, identity Identity, request *internalevaluationv1.CancelEvaluationRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" || request.GetReason() == "" {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "evaluation.run.cancel", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	run, row, err := getRunTx(ctx, tx, identity, request.GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(run.GetEtag()), []byte(request.GetEtag())) != 1 {
		return nil, false, ErrRevisionConflict
	}
	switch run.GetState() {
	case evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_SUCCEEDED, evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_FAILED, evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLED, evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_EXPIRED:
		return nil, false, ErrInvalidTransition
	case evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLING:
		return nil, false, ErrInvalidTransition
	}
	nextRevision := run.GetRevision() + 1
	nextETag := resourceETag(run.GetName(), nextRevision)
	updatedRun, err := tx.ExecContext(ctx, `UPDATE evaluation_runs SET revision=$4,etag=$5,state=$6,update_time=$7 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$8 AND etag=$9`, identity.TenantID, identity.ProjectID, run.GetName(), nextRevision, nextETag, int32(evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLING), at.UTC(), run.GetRevision(), run.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := updatedRun.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	if err = advanceSchedulerRows(ctx, tx, identity, row.jobID, row.schedulerRunID, "CANCELLING", "CANCELLING", at); err != nil {
		return nil, false, err
	}
	current, err := loadOperationTx(ctx, tx, identity, row.operationID)
	if err != nil {
		return nil, false, err
	}
	updatedOperation, err := tx.ExecContext(ctx, `UPDATE operations SET target_resource_version=$4,target_etag=$5 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, row.operationID, nextRevision, nextETag)
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := updatedOperation.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrInvalidTransition
	}
	operation, err := operationsapp.AdvanceTxSQL(ctx, tx, identity.TenantID, identity.ProjectID, row.operationID, current.GetResourceVersion(), current.GetEtag(), jobv1.OperationState_OPERATION_STATE_CANCELLING, at)
	if err != nil {
		return nil, false, err
	}
	updated, _, err := getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.CancellationRequested(identity, updated, operation, request.GetReason(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "evaluation.run.cancel", request.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) CommitResult(ctx context.Context, identity Identity, request *internalevaluationv1.CommitEvaluationResultRequest, digest string, at time.Time) (*evaluationv1.EvaluationResult, *evaluationv1.EvaluationRun, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, nil, false, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" {
		return nil, nil, false, ErrInvalidArgument
	}
	if err := validateReference(identity, request.GetEvaluationRun(), "evaluation run"); err != nil {
		return nil, nil, false, err
	}
	if err := validateFence(identity, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	if err := validateResult(identity, request.GetResult()); err != nil {
		return nil, nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil {
		return nil, nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "evaluation.result.commit", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		result, loadErr := getResultTx(ctx, tx, identity, request.GetResult().GetName())
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		run, _, loadErr := getRunTx(ctx, tx, identity, request.GetEvaluationRun().GetName(), false)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, nil, false, commitErr
		}
		_ = operation
		return clone(result), clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, request.GetEvaluationRun().GetName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	if request.GetEvaluationRun().GetResourceVersion() != run.GetRevision() || subtle.ConstantTimeCompare([]byte(request.GetEtag()), []byte(run.GetEtag())) != 1 {
		return nil, nil, false, ErrRevisionConflict
	}
	if request.GetResult().GetRun().GetName() != run.GetName() {
		return nil, nil, false, ErrInvalidArgument
	}
	if run.GetState() == evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_SUCCEEDED || run.GetState() == evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_FAILED || run.GetState() == evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLED {
		return nil, nil, false, ErrInvalidTransition
	}
	if err = validateCurrentFence(ctx, tx, identity, row.schedulerRunID, row.jobID, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	result, reportID, err := storeResult(ctx, tx, identity, run.GetName(), request.GetResult())
	if err != nil {
		return nil, nil, false, err
	}
	nextRevision := run.GetRevision() + 1
	nextETag := resourceETag(run.GetName(), nextRevision)
	domainState, runState, jobState, attemptState, operationState := terminalStates(result.GetOutcome())
	completed := run.GetCompletedSamples()
	if run.TotalSamples != nil {
		completed = run.GetTotalSamples()
	}
	updatedRun, err := tx.ExecContext(ctx, `UPDATE evaluation_runs SET revision=$4,etag=$5,attempt_id=$6,lease_epoch=$7,state=$8,completed_samples=$9,update_time=$10,end_time=$10 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$11 AND etag=$12`, identity.TenantID, identity.ProjectID, run.GetName(), nextRevision, nextETag, request.GetFence().GetAttemptId(), request.GetFence().GetLeaseEpoch(), int32(domainState), completed, at.UTC(), run.GetRevision(), run.GetEtag())
	if err != nil {
		return nil, nil, false, err
	}
	if changed, rowsErr := updatedRun.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, nil, false, rowsErr
		}
		return nil, nil, false, ErrRevisionConflict
	}
	updatedAttempt, err := tx.ExecContext(ctx, `UPDATE attempts SET status=$5,version=version+1,completed_at=$6,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 AND lease_epoch=$7 AND worker_id=$8 AND status IN ('LEASED','ACTIVE')`, identity.TenantID, identity.ProjectID, request.GetFence().GetAttemptId(), row.schedulerRunID, attemptState, at.UTC(), request.GetFence().GetLeaseEpoch(), identity.WorkerID)
	if err != nil {
		return nil, nil, false, err
	}
	if changed, rowsErr := updatedAttempt.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, nil, false, rowsErr
		}
		return nil, nil, false, ErrStaleFence
	}
	if err = advanceSchedulerRows(ctx, tx, identity, row.jobID, row.schedulerRunID, jobState, runState, at); err != nil {
		return nil, nil, false, err
	}
	current, err := loadOperationTx(ctx, tx, identity, row.operationID)
	if err != nil {
		return nil, nil, false, err
	}
	updatedOperation, err := tx.ExecContext(ctx, `UPDATE operations SET target_resource_version=$4,target_etag=$5,result_ref_id=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, row.operationID, nextRevision, nextETag, reportID)
	if err != nil {
		return nil, nil, false, err
	}
	if changed, rowsErr := updatedOperation.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, nil, false, rowsErr
		}
		return nil, nil, false, ErrInvalidTransition
	}
	operation, err := operationsapp.AdvanceTxSQL(ctx, tx, identity.TenantID, identity.ProjectID, row.operationID, current.GetResourceVersion(), current.GetEtag(), operationState, at)
	if err != nil {
		return nil, nil, false, err
	}
	updated, _, err := getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, nil, false, err
	}
	event, err := repository.Events.ResultCommitted(identity, result, updated, operation, request.GetContext(), at)
	if err != nil {
		return nil, nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "evaluation.result.commit", request.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(result), clone(updated), false, nil
}

func (repository SQLRepository) GetResult(ctx context.Context, identity Identity, name string) (*evaluationv1.EvaluationResult, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getResultTx(ctx, tx, identity, name)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (repository SQLRepository) CreatePromotionDecision(ctx context.Context, identity Identity, request *internalevaluationv1.CreatePromotionDecisionRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil {
		return nil, false, ErrInvalidArgument
	}
	if err := validatePromotionDecision(identity, request.GetPromotionDecision()); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "evaluation.promotion.create", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	decision := clone(request.GetPromotionDecision())
	target := &commonv1.ResourceRef{ResourceType: "promotion_decision", ResourceId: resourceID(decision.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: decision.GetName(), Etag: decision.GetDecisionDigest()}
	operation, err := insertCompletedOperation(ctx, tx, identity, target, "evaluation.promotion", digest, at)
	if err != nil {
		return nil, false, err
	}
	if err = storePromotionDecision(ctx, tx, identity, decision, operation.GetOperationId()); err != nil {
		return nil, false, err
	}
	persisted, err := getDecisionTx(ctx, tx, identity, decision.GetName())
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.PromotionRecorded(identity, persisted, operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "evaluation.promotion.create", request.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetPromotionDecision(ctx context.Context, identity Identity, name string) (*evaluationv1.PromotionDecision, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getDecisionTx(ctx, tx, identity, name)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func validateCurrentFence(ctx context.Context, tx *sql.Tx, identity Identity, schedulerRunID, jobID string, fence *jobv1.LeaseFence, at time.Time) error {
	presented, err := jobsapp.LeaseTokenDigest(identity.LeaseToken)
	if err != nil {
		return ErrLeaseToken
	}
	if subtle.ConstantTimeCompare([]byte(presented), []byte(fence.GetLeaseTokenDigest())) != 1 {
		return ErrLeaseToken
	}
	if fence.GetRunId() != schedulerRunID || fence.GetJobId() != jobID {
		return ErrStaleFence
	}
	var worker, digest, status string
	var epoch, currentEpoch uint64
	var expiry time.Time
	err = tx.QueryRowContext(ctx, `SELECT a.worker_id,a.lease_token_digest,a.lease_epoch,a.lease_expires_at,a.status,r.lease_epoch FROM attempts a JOIN runs r ON r.tenant_id=a.tenant_id AND r.project_id=a.project_id AND r.id=a.run_id WHERE a.tenant_id=$1 AND a.project_id=$2 AND a.id=$3 AND a.run_id=$4 FOR UPDATE OF a,r`, identity.TenantID, identity.ProjectID, fence.GetAttemptId(), schedulerRunID).Scan(&worker, &digest, &epoch, &expiry, &status, &currentEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrStaleFence
	}
	if err != nil {
		return err
	}
	if worker != identity.WorkerID {
		return ErrPermissionDenied
	}
	if subtle.ConstantTimeCompare([]byte(digest), []byte(presented)) != 1 {
		return ErrLeaseToken
	}
	if epoch != fence.GetLeaseEpoch() || currentEpoch != fence.GetLeaseEpoch() {
		return ErrStaleFence
	}
	if status != "LEASED" && status != "ACTIVE" {
		return ErrStaleFence
	}
	if !at.UTC().Before(expiry.UTC()) || !fence.GetDeadline().AsTime().UTC().Equal(expiry.UTC()) {
		return ErrLeaseExpired
	}
	return nil
}

func terminalStates(outcome evaluationv1.EvaluationResultOutcome) (evaluationv1.EvaluationRunState, string, string, string, jobv1.OperationState) {
	switch outcome {
	case evaluationv1.EvaluationResultOutcome_EVALUATION_RESULT_OUTCOME_CANCELLED:
		return evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLED, "CANCELLED", "CANCELLED", "CANCELLED", jobv1.OperationState_OPERATION_STATE_CANCELLED
	case evaluationv1.EvaluationResultOutcome_EVALUATION_RESULT_OUTCOME_INVALID:
		return evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_FAILED, "FAILED", "FAILED", "FAILED", jobv1.OperationState_OPERATION_STATE_FAILED
	default:
		return evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_SUCCEEDED, "SUCCEEDED", "SUCCEEDED", "COMPLETED", jobv1.OperationState_OPERATION_STATE_SUCCEEDED
	}
}

func storeResult(ctx context.Context, tx *sql.Tx, identity Identity, runName string, value *evaluationv1.EvaluationResult) (*evaluationv1.EvaluationResult, sql.NullInt64, error) {
	value = clone(value)
	runRef, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetRun())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	report, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetReport())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	suite, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetSuite())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	snapshot, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetSnapshot())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	manifest, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetDatasetManifest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	protocol, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetInferenceProtocol())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	leakage, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetLeakageEvidence())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	safety, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetSafetyEvidence())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	statistical, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetStatisticalEvidence())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	performance, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetPerformanceEvidence())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	finalized, _ := requireTimestamp(value.GetFinalizedAt(), "result finalized")
	_, err = tx.ExecContext(ctx, `INSERT INTO evaluation_results(tenant_id,project_id,name,uid,evaluation_run_name,run_ref_id,run_digest,outcome,report_ref_id,suite_ref_id,snapshot_ref_id,dataset_manifest_ref_id,inference_protocol_ref_id,leakage_evidence_ref_id,safety_evidence_ref_id,statistical_evidence_ref_id,performance_evidence_ref_id,source_revision,finalized_at,result_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`, identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), runName, runRef, value.GetRunDigest(), int32(value.GetOutcome()), report, suite, snapshot, manifest, protocol, leakage, safety, statistical, performance, value.GetSourceRevision(), finalized, value.GetResultDigest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	for ordinal, metric := range value.GetMetrics() {
		var lower, upper sql.NullFloat64
		if metric.IntervalLower != nil {
			lower = sql.NullFloat64{Float64: metric.GetIntervalLower(), Valid: true}
			upper = sql.NullFloat64{Float64: metric.GetIntervalUpper(), Valid: true}
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO evaluation_result_metrics(tenant_id,project_id,result_name,ordinal,metric_id,metric_version,unit,direction,metric_value,interval_lower,interval_upper,valid_count,invalid_count,cohort_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, metric.GetMetricId(), metric.GetMetricVersion(), metric.GetUnit(), int32(metric.GetDirection()), metric.GetValue(), lower, upper, metric.GetValidCount(), metric.GetInvalidCount(), metric.GetCohortId()); err != nil {
			return nil, sql.NullInt64{}, err
		}
	}
	for ordinal, threshold := range value.GetThresholds() {
		evidence, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, threshold.GetEvidence())
		if storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO evaluation_result_thresholds(tenant_id,project_id,result_name,ordinal,rule_id,metric_id,threshold_result,reason_code,evidence_ref_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, threshold.GetRuleId(), threshold.GetMetricId(), int32(threshold.GetResult()), threshold.GetReasonCode(), evidence); storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
	}
	for ordinal, failure := range value.GetFailureCounts() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO evaluation_result_failure_counts(tenant_id,project_id,result_name,ordinal,failure_class,failure_count) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, failure.GetFailureClass(), failure.GetCount()); err != nil {
			return nil, sql.NullInt64{}, err
		}
	}
	persisted, err := getResultTx(ctx, tx, identity, value.GetName())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	if !proto.Equal(persisted, value) {
		return nil, sql.NullInt64{}, ErrInvalidArgument
	}
	return persisted, report, nil
}

func storePromotionDecision(ctx context.Context, tx *sql.Tx, identity Identity, value *evaluationv1.PromotionDecision, operationID string) error {
	candidate, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetCandidateRelease())
	if err != nil {
		return err
	}
	decided, _ := requireTimestamp(value.GetDecidedAt(), "promotion decided")
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO promotion_decisions(tenant_id,project_id,name,uid,candidate_release_ref_id,candidate_digest,target_profile,outcome,reason_code,safe_reason,decided_by_principal_ref,decided_at,expire_time,source_revision,decision_digest,operation_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)`, identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), candidate, value.GetCandidateDigest(), value.GetTargetProfile(), int32(value.GetOutcome()), value.GetReasonCode(), value.GetSafeReason(), value.GetDecidedByPrincipalRef(), decided, expiry, value.GetSourceRevision(), value.GetDecisionDigest(), operationID); err != nil {
		return err
	}
	for ordinal, result := range value.GetEvaluationResults() {
		id, storeErr := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, result)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO promotion_decision_results(tenant_id,project_id,decision_name,ordinal,evaluation_result_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	for ordinal, rule := range value.GetRules() {
		evidence, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, rule.GetEvidence())
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO promotion_decision_rules(tenant_id,project_id,decision_name,ordinal,rule_id,threshold_result,reason_code,evidence_ref_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, rule.GetRuleId(), int32(rule.GetResult()), rule.GetReasonCode(), evidence); storeErr != nil {
			return storeErr
		}
	}
	for ordinal, exception := range value.GetExceptions() {
		rationale, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, exception.GetRationale())
		if storeErr != nil {
			return storeErr
		}
		expiryTime, _ := requireTimestamp(exception.GetExpireTime(), "promotion exception expiry")
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO promotion_decision_exceptions(tenant_id,project_id,decision_name,ordinal,exception_id,rule_id,rationale_ref_id,expire_time) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, exception.GetExceptionId(), exception.GetRuleId(), rationale, expiryTime); storeErr != nil {
			return storeErr
		}
		for approvalOrdinal, approval := range exception.GetApprovalReceipts() {
			id, approvalErr := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, approval)
			if approvalErr != nil {
				return approvalErr
			}
			if _, approvalErr = tx.ExecContext(ctx, `INSERT INTO promotion_exception_approvals(tenant_id,project_id,decision_name,exception_ordinal,ordinal,approval_ref_id) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, approvalOrdinal, id); approvalErr != nil {
				return approvalErr
			}
		}
	}
	for ordinal, authorization := range value.GetPolicyDecisions() {
		id, storeErr := storeAuthorizationDecision(ctx, tx, identity, authorization)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO promotion_decision_authorizations(tenant_id,project_id,decision_name,ordinal,authorization_decision_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	persisted, err := getDecisionTx(ctx, tx, identity, value.GetName())
	if err != nil {
		return err
	}
	if !proto.Equal(persisted, value) {
		return ErrInvalidArgument
	}
	return nil
}
