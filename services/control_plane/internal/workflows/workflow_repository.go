package workflows

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

func (repository SQLRepository) CreateDefinition(ctx context.Context, identity Identity, request *internalworkflowv1.CreateWorkflowDefinitionRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "workflow.definition.create", request.GetContext().GetIdempotencyKey()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	name := definitionName(identity, request.GetWorkflowDefinitionId())
	var exists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM workflow_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3)`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err != nil {
		return nil, false, err
	}
	if exists {
		return nil, false, ErrAlreadyExists
	}
	value := clone(request.GetWorkflowDefinition())
	uid, err := randomID("wfd_")
	if err != nil {
		return nil, false, err
	}
	value.Name, value.Uid, value.Revision, value.TenantId, value.ProjectId = name, uid, 1, identity.TenantID, identity.ProjectID
	value.Etag, value.CreateTime, value.UpdateTime = resourceETag(name, 1), timestamppb.New(at.UTC()), timestamppb.New(at.UTC())
	definitionID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetDefinition())
	if err != nil {
		return nil, false, err
	}
	inputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetInputSchema())
	if err != nil {
		return nil, false, err
	}
	outputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetOutputSchema())
	if err != nil {
		return nil, false, err
	}
	wallSeconds, wallNanos, err := durationParts(value.GetLimits().GetMaximumWallTime(), true)
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_definitions(tenant_id,project_id,name,uid,revision,etag,display_name,semantic_version,state,definition_ref_id,resolved_graph_digest,maximum_iterations,maximum_fan_out,maximum_parallel_nodes,maximum_wall_time_seconds,maximum_wall_time_nanos,input_schema_ref_id,output_schema_ref_id,create_time,update_time,delete_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$18,NULL)`, identity.TenantID, identity.ProjectID, name, uid, value.GetEtag(), value.GetDisplayName(), value.GetSemanticVersion(), int32(value.GetState()), definitionID, value.GetResolvedGraphDigest(), value.GetLimits().GetMaximumIterations(), value.GetLimits().GetMaximumFanOut(), value.GetLimits().GetMaximumParallelNodes(), wallSeconds, wallNanos, inputID, outputID, at.UTC()); err != nil {
		return nil, false, err
	}
	if err = storeDefinitionChildren(ctx, tx, identity, name, value); err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, workflowDefinitionResource(value), "workflow.definition.create", digest, at)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.DefinitionCreated(identity, value, operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, operation.GetOperationId(), name, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func validDefinitionTransition(from, to workflowv1.WorkflowDefinitionState) bool {
	if from == to {
		return true
	}
	switch from {
	case workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_DRAFT:
		return to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_ACTIVE || to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_REVOKED
	case workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_ACTIVE:
		return to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_DEPRECATED || to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_REVOKED
	case workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_DEPRECATED:
		return to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_REVOKED || to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_ARCHIVED
	case workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_REVOKED:
		return to == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_ARCHIVED
	default:
		return false
	}
}

func (repository SQLRepository) UpdateDefinition(ctx context.Context, identity Identity, request *internalworkflowv1.UpdateWorkflowDefinitionRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "workflow.definition.update", request.GetContext().GetIdempotencyKey()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	name := request.GetWorkflowDefinition().GetName()
	row, err := scanDefinition(tx.QueryRowContext(ctx, `SELECT `+definitionColumns+` FROM workflow_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	before, err := definitionProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	if request.GetEtag() != before.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	after := clone(before)
	for _, path := range request.GetUpdateMask().GetPaths() {
		switch path {
		case "display_name":
			if request.GetWorkflowDefinition().GetDisplayName() == "" {
				return nil, false, ErrInvalidArgument
			}
			after.DisplayName = request.GetWorkflowDefinition().GetDisplayName()
		case "state":
			if !validDefinitionTransition(before.GetState(), request.GetWorkflowDefinition().GetState()) {
				return nil, false, ErrInvalidTransition
			}
			after.State = request.GetWorkflowDefinition().GetState()
		}
	}
	after.Revision, after.Etag, after.UpdateTime = before.GetRevision()+1, resourceETag(name, before.GetRevision()+1), timestamppb.New(at.UTC())
	result, err := tx.ExecContext(ctx, `UPDATE workflow_definitions SET revision=$4,etag=$5,display_name=$6,state=$7,update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, name, after.GetRevision(), after.GetEtag(), after.GetDisplayName(), int32(after.GetState()), at.UTC(), before.GetRevision(), before.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, workflowDefinitionResource(after), "workflow.definition.update", digest, at)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.DefinitionUpdated(identity, after, before.GetRevision(), request.GetUpdateMask().GetPaths(), operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, operation.GetOperationId(), name, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetDefinition(ctx context.Context, identity Identity, name string) (*workflowv1.WorkflowDefinition, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	canonical, err := canonicalScopedName(identity, name, "workflowDefinitions")
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanDefinition(tx.QueryRowContext(ctx, `SELECT `+definitionColumns+` FROM workflow_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := definitionProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (repository SQLRepository) ListDefinitions(ctx context.Context, identity Identity, page DefinitionPage) ([]*workflowv1.WorkflowDefinition, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
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
	query := `SELECT ` + definitionColumns + ` FROM workflow_definitions WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_UNSPECIFIED {
		query += fmt.Sprintf(" AND state=$%d", next)
		args = append(args, int32(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (create_time,name)<($%d,$%d)", next, next+1)
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += fmt.Sprintf(" ORDER BY create_time DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []definitionRow
	for rows.Next() {
		item, scanErr := scanDefinition(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	if err = rows.Err(); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*workflowv1.WorkflowDefinition, 0, len(stored))
	for _, item := range stored {
		value, mapErr := definitionProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	token := ""
	if hasMore {
		last := stored[len(stored)-1]
		token, err = repository.Pagination.encode(pageToken{Kind: "workflow-definitions", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func (repository SQLRepository) StartRun(ctx context.Context, identity Identity, request *internalworkflowv1.StartWorkflowRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "workflow.run.start", request.GetContext().GetIdempotencyKey()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	name := runName(identity, request.GetWorkflowRunId())
	var exists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM workflow_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3)`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err != nil {
		return nil, false, err
	}
	if exists {
		return nil, false, ErrAlreadyExists
	}
	value := clone(request.GetWorkflowRun())
	uid, err := randomID("wfr_")
	if err != nil {
		return nil, false, err
	}
	value.Name, value.Uid, value.Revision, value.Etag, value.TenantId, value.ProjectId = name, uid, 1, resourceETag(name, 1), identity.TenantID, identity.ProjectID
	value.State, value.TransitionSequence = workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CREATED, 0
	value.CreateTime, value.UpdateTime = timestamppb.New(at.UTC()), timestamppb.New(at.UTC())
	definitionID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetDefinition())
	if err != nil {
		return nil, false, err
	}
	agentRunID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetAgentRun())
	if err != nil {
		return nil, false, err
	}
	inputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetInput())
	if err != nil {
		return nil, false, err
	}
	admissionID := sql.NullInt64{}
	if value.GetAdmissionDecision() != nil {
		id, storeErr := StoreAuthorizationDecision(ctx, tx, identity, value.GetAdmissionDecision())
		if storeErr != nil {
			return nil, false, storeErr
		}
		admissionID = sql.NullInt64{Int64: id, Valid: true}
	}
	operation, schedulerRunID, err := insertQueuedWork(ctx, tx, identity, workflowRunResource(value), "workflow.run", digest, value.GetDefinitionDigest(), inputID, sql.NullInt64{}, sql.NullInt64{}, at)
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_runs(tenant_id,project_id,name,uid,revision,etag,definition_ref_id,definition_digest,agent_run_ref_id,state,completed_node_count,iteration_count,transition_sequence,attempt_id,lease_epoch,input_ref_id,output_ref_id,replay_state_ref_id,admission_decision_id,decision_log_ref_id,failure_detail_id,create_time,update_time,end_time,operation_id,job_id,scheduler_run_id) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,0,0,0,'',0,$10,NULL,NULL,$11,NULL,NULL,$12,$12,NULL,$13,$14,$15)`, identity.TenantID, identity.ProjectID, name, uid, value.GetEtag(), definitionID, value.GetDefinitionDigest(), agentRunID, int32(value.GetState()), inputID, admissionID, at.UTC(), operation.GetOperationId(), operation.GetJobId(), schedulerRunID); err != nil {
		return nil, false, err
	}
	runEvent, err := repository.Events.RunStarted(identity, value, operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	jobEvent, err := repository.Events.JobRequested(identity, operation, value.GetDefinitionDigest(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, operation.GetOperationId(), name, []*commonv1.EventEnvelope{runEvent, jobEvent}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetRun(ctx context.Context, identity Identity, name string) (*workflowv1.WorkflowRun, error) {
	if err := repository.validate(); err != nil {
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

func (repository SQLRepository) ListRuns(ctx context.Context, identity Identity, page RunPage) ([]*workflowv1.WorkflowRun, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
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
	query := `SELECT ` + runColumns + ` FROM workflow_runs WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_UNSPECIFIED {
		query += fmt.Sprintf(" AND state=$%d", next)
		args = append(args, int32(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (create_time,name)<($%d,$%d)", next, next+1)
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += fmt.Sprintf(" ORDER BY create_time DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []runRow
	for rows.Next() {
		item, scanErr := scanRun(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	if err = rows.Err(); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*workflowv1.WorkflowRun, 0, len(stored))
	for _, item := range stored {
		value, mapErr := runProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	token := ""
	if hasMore {
		last := stored[len(stored)-1]
		token, err = repository.Pagination.encode(pageToken{Kind: "workflow-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func (repository SQLRepository) CancelRun(ctx context.Context, identity Identity, request *internalworkflowv1.CancelWorkflowRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "workflow.run.cancel", request.GetContext().GetIdempotencyKey()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	before, row, err := getRunTx(ctx, tx, identity, request.GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if before.GetEtag() != request.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if terminalRunState(before.GetState()) {
		return nil, false, ErrInvalidTransition
	}
	after := clone(before)
	after.Revision, after.Etag, after.State, after.UpdateTime = before.GetRevision()+1, resourceETag(before.GetName(), before.GetRevision()+1), workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLING, timestamppb.New(at.UTC())
	result, err := tx.ExecContext(ctx, `UPDATE workflow_runs SET revision=$4,etag=$5,state=$6,update_time=$7 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$8 AND etag=$9`, identity.TenantID, identity.ProjectID, before.GetName(), after.GetRevision(), after.GetEtag(), int32(after.GetState()), at.UTC(), before.GetRevision(), before.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	if err = advanceSchedulerRows(ctx, tx, identity, row.jobID, row.schedulerRunID, "CANCELLING", "CANCELLING", at); err != nil {
		return nil, false, err
	}
	if err = advanceOperation(ctx, tx, identity, row.operationID, workflowRunResource(after), jobv1.OperationState_OPERATION_STATE_CANCELLING, at); err != nil {
		return nil, false, err
	}
	cancelOperation, err := insertCompletedOperation(ctx, tx, identity, workflowRunResource(after), "workflow.run.cancel", digest, at)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.RunCancelled(identity, after, cancelOperation, request.GetReason(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, cancelOperation.GetOperationId(), after.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(cancelOperation), false, nil
}

func validRunTransition(from, to workflowv1.WorkflowRunState) bool {
	if terminalRunState(from) {
		return false
	}
	if from == to {
		return true
	}
	if to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_FAILED || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLED || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_EXPIRED {
		return true
	}
	switch from {
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CREATED:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_VALIDATING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_ADMITTED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_VALIDATING:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_ADMITTED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_ADMITTED:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_READY || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_READY, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_JOB, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_APPROVAL, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RECONCILING, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_PAUSED:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_JOB || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_APPROVAL || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RECONCILING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_PAUSED || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_JOB || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_WAITING_FOR_APPROVAL || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RECONCILING || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_PAUSED || to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLING:
		return to == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLED
	default:
		return false
	}
}

func verifyFenceTx(ctx context.Context, tx *sql.Tx, identity Identity, request *internalworkflowv1.CommitWorkflowTransitionRequest, row runRow, at time.Time) error {
	fence := request.GetFence()
	if fence.GetJobId() != row.jobID || fence.GetRunId() != row.schedulerRunID {
		return ErrStaleFence
	}
	var workerID, tokenDigest, statusValue, jobID, runID string
	var epoch int64
	var expires time.Time
	err := tx.QueryRowContext(ctx, `SELECT worker_id,lease_token_digest,lease_epoch,lease_expires_at,status,job_id,run_id FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, fence.GetAttemptId()).Scan(&workerID, &tokenDigest, &epoch, &expires, &statusValue, &jobID, &runID)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrStaleFence
	}
	if err != nil {
		return err
	}
	leaseEpoch, conversionErr := numconv.Int64ToUint64(epoch)
	if conversionErr != nil {
		return conversionErr
	}
	if workerID != identity.WorkerID || leaseEpoch != fence.GetLeaseEpoch() || jobID != fence.GetJobId() || runID != fence.GetRunId() || statusValue != "LEASED" && statusValue != "ACTIVE" {
		return ErrStaleFence
	}
	if !at.Before(expires.UTC()) {
		return ErrLeaseExpired
	}
	digest := sha256.Sum256([]byte(identity.LeaseToken))
	presented := "sha256:" + hex.EncodeToString(digest[:])
	if subtle.ConstantTimeCompare([]byte(presented), []byte(tokenDigest)) != 1 {
		return ErrLeaseToken
	}
	return nil
}

func validateTransitionPayload(before, proposed *workflowv1.WorkflowRun, request *internalworkflowv1.CommitWorkflowTransitionRequest) error {
	if proposed.GetName() != before.GetName() || proposed.GetUid() != before.GetUid() || proposed.GetTenantId() != "" && proposed.GetTenantId() != before.GetTenantId() || proposed.GetProjectId() != "" && proposed.GetProjectId() != before.GetProjectId() || request.GetExpectedTransitionSequence() != before.GetTransitionSequence() || proposed.GetTransitionSequence() != before.GetTransitionSequence()+1 || !validRunTransition(before.GetState(), proposed.GetState()) || proposed.GetCompletedNodeCount() < before.GetCompletedNodeCount() || proposed.GetIterationCount() < before.GetIterationCount() || len(proposed.GetActiveNodeIds()) > 4096 {
		return ErrInvalidTransition
	}
	if !proto.Equal(proposed.GetDefinition(), before.GetDefinition()) || proposed.GetDefinitionDigest() != before.GetDefinitionDigest() || !proto.Equal(proposed.GetAgentRun(), before.GetAgentRun()) || !proto.Equal(proposed.GetInput(), before.GetInput()) || !proto.Equal(proposed.GetAdmissionDecision(), before.GetAdmissionDecision()) {
		return ErrInvalidArgument
	}
	if !sort.StringsAreSorted(proposed.GetActiveNodeIds()) {
		return ErrInvalidArgument
	}
	for index, node := range proposed.GetActiveNodeIds() {
		if node == "" || index > 0 && node == proposed.GetActiveNodeIds()[index-1] {
			return ErrInvalidArgument
		}
	}
	if err := validateArtifact(proposed.GetOutput(), "workflow output", false); err != nil {
		return err
	}
	if err := validateArtifact(proposed.GetReplayState(), "workflow replay state", false); err != nil {
		return err
	}
	if err := validateArtifact(proposed.GetDecisionLog(), "workflow decision log", false); err != nil {
		return err
	}
	if proposed.GetState() == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED && proposed.GetOutput() == nil {
		return ErrInvalidTransition
	}
	return nil
}

func (repository SQLRepository) CommitTransition(ctx context.Context, identity Identity, request *internalworkflowv1.CommitWorkflowTransitionRequest, digest string, at time.Time) (*workflowv1.WorkflowRun, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "workflow.run.commit_transition", request.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := getTransitionTx(ctx, tx, identity, responseName, request.GetExpectedTransitionSequence()+1)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	before, row, err := getRunTx(ctx, tx, identity, request.GetWorkflowRun().GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if request.GetEtag() != before.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if err = verifyFenceTx(ctx, tx, identity, request, row, at); err != nil {
		return nil, false, err
	}
	proposed := clone(request.GetWorkflowRun())
	if err = validateTransitionPayload(before, proposed, request); err != nil {
		return nil, false, err
	}
	after := clone(before)
	after.Revision, after.Etag, after.State = before.GetRevision()+1, resourceETag(before.GetName(), before.GetRevision()+1), proposed.GetState()
	after.ActiveNodeIds, after.CompletedNodeCount, after.IterationCount, after.TransitionSequence = append([]string(nil), proposed.GetActiveNodeIds()...), proposed.GetCompletedNodeCount(), proposed.GetIterationCount(), proposed.GetTransitionSequence()
	after.AttemptId, after.LeaseEpoch = request.GetFence().GetAttemptId(), request.GetFence().GetLeaseEpoch()
	after.Output, after.ReplayState, after.DecisionLog, after.Failure = clone(proposed.GetOutput()), clone(proposed.GetReplayState()), clone(proposed.GetDecisionLog()), clone(proposed.GetFailure())
	after.UpdateTime = timestamppb.New(at.UTC())
	if terminalRunState(after.GetState()) {
		after.EndTime = timestamppb.New(at.UTC())
	} else {
		after.EndTime = nil
	}
	outputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, after.GetOutput())
	if err != nil {
		return nil, false, err
	}
	replayID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, after.GetReplayState())
	if err != nil {
		return nil, false, err
	}
	decisionLogID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, after.GetDecisionLog())
	if err != nil {
		return nil, false, err
	}
	failureID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, after.GetFailure())
	if err != nil {
		return nil, false, err
	}
	endTime, err := nullableTime(after.GetEndTime())
	if err != nil {
		return nil, false, err
	}
	result, err := tx.ExecContext(ctx, `UPDATE workflow_runs SET revision=$4,etag=$5,state=$6,completed_node_count=$7,iteration_count=$8,transition_sequence=$9,attempt_id=$10,lease_epoch=$11,output_ref_id=$12,replay_state_ref_id=$13,decision_log_ref_id=$14,failure_detail_id=$15,update_time=$16,end_time=$17 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$18 AND etag=$19 AND transition_sequence=$20`, identity.TenantID, identity.ProjectID, before.GetName(), after.GetRevision(), after.GetEtag(), int32(after.GetState()), after.GetCompletedNodeCount(), after.GetIterationCount(), after.GetTransitionSequence(), after.GetAttemptId(), after.GetLeaseEpoch(), outputID, replayID, decisionLogID, failureID, at.UTC(), endTime, before.GetRevision(), before.GetEtag(), before.GetTransitionSequence())
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM workflow_run_active_nodes WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3`, identity.TenantID, identity.ProjectID, after.GetName()); err != nil {
		return nil, false, err
	}
	for ordinal, node := range after.GetActiveNodeIds() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_run_active_nodes(tenant_id,project_id,workflow_run_name,ordinal,node_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, after.GetName(), ordinal, node); err != nil {
			return nil, false, err
		}
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_transition_revisions(tenant_id,project_id,workflow_run_name,transition_sequence,revision,etag,state,completed_node_count,iteration_count,attempt_id,lease_epoch,output_ref_id,replay_state_ref_id,decision_log_ref_id,failure_detail_id,update_time,end_time) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)`, identity.TenantID, identity.ProjectID, after.GetName(), after.GetTransitionSequence(), after.GetRevision(), after.GetEtag(), int32(after.GetState()), after.GetCompletedNodeCount(), after.GetIterationCount(), after.GetAttemptId(), after.GetLeaseEpoch(), outputID, replayID, decisionLogID, failureID, at.UTC(), endTime); err != nil {
		return nil, false, err
	}
	for ordinal, node := range after.GetActiveNodeIds() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_transition_active_nodes(tenant_id,project_id,workflow_run_name,transition_sequence,ordinal,node_id) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, identity.ProjectID, after.GetName(), after.GetTransitionSequence(), ordinal, node); err != nil {
			return nil, false, err
		}
	}
	jobState, schedulerState, operationState := "RUNNING", "EXECUTING", jobv1.OperationState_OPERATION_STATE_RUNNING
	switch after.GetState() {
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED:
		jobState, schedulerState, operationState = "SUCCEEDED", "SUCCEEDED", jobv1.OperationState_OPERATION_STATE_SUCCEEDED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_FAILED, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_EXPIRED:
		jobState, schedulerState, operationState = "FAILED", "FAILED", jobv1.OperationState_OPERATION_STATE_FAILED
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLING:
		jobState, schedulerState, operationState = "CANCELLING", "CANCELLING", jobv1.OperationState_OPERATION_STATE_CANCELLING
	case workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLED:
		jobState, schedulerState, operationState = "CANCELLED", "CANCELLED", jobv1.OperationState_OPERATION_STATE_CANCELLED
	}
	if err = advanceSchedulerRows(ctx, tx, identity, row.jobID, row.schedulerRunID, jobState, schedulerState, at); err != nil {
		return nil, false, err
	}
	if err = advanceOperation(ctx, tx, identity, row.operationID, workflowRunResource(after), operationState, at); err != nil {
		return nil, false, err
	}
	event, err := repository.Events.Transitioned(identity, before, after, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", after.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(after), false, nil
}

type transitionRow struct {
	sequence, revision, completedNodes, iterations, leaseEpoch int64
	etag, attemptID                                            string
	state                                                      int32
	outputID, replayID, decisionLogID, failureID               sql.NullInt64
	updated                                                    time.Time
	ended                                                      sql.NullTime
}

func applyTransitionRow(value *workflowv1.WorkflowRun, item transitionRow) error {
	completedNodes, err := numconv.Int64ToUint32(item.completedNodes)
	if err != nil {
		return err
	}
	iterations, err := numconv.Int64ToUint32(item.iterations)
	if err != nil {
		return err
	}
	sequence, err := numconv.Int64ToUint64(item.sequence)
	if err != nil {
		return err
	}
	leaseEpoch, err := numconv.Int64ToUint64(item.leaseEpoch)
	if err != nil {
		return err
	}
	value.Revision = item.revision
	value.Etag = item.etag
	value.State = workflowv1.WorkflowRunState(item.state)
	value.CompletedNodeCount = completedNodes
	value.IterationCount = iterations
	value.TransitionSequence = sequence
	value.AttemptId = item.attemptID
	value.LeaseEpoch = leaseEpoch
	return nil
}

func getTransitionTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, sequence uint64) (*workflowv1.WorkflowRun, error) {
	base, _, err := getRunTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	var item transitionRow
	err = tx.QueryRowContext(ctx, `SELECT transition_sequence,revision,etag,state,completed_node_count,iteration_count,attempt_id,lease_epoch,output_ref_id,replay_state_ref_id,decision_log_ref_id,failure_detail_id,update_time,end_time FROM workflow_transition_revisions WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3 AND transition_sequence=$4`, identity.TenantID, identity.ProjectID, base.GetName(), sequence).Scan(&item.sequence, &item.revision, &item.etag, &item.state, &item.completedNodes, &item.iterations, &item.attemptID, &item.leaseEpoch, &item.outputID, &item.replayID, &item.decisionLogID, &item.failureID, &item.updated, &item.ended)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value := clone(base)
	if err = applyTransitionRow(value, item); err != nil {
		return nil, err
	}
	value.Output, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.outputID)
	if err != nil {
		return nil, err
	}
	value.ReplayState, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.replayID)
	if err != nil {
		return nil, err
	}
	value.DecisionLog, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.decisionLogID)
	if err != nil {
		return nil, err
	}
	value.Failure, err = platformdb.LoadErrorDetail(ctx, tx, identity.TenantID, item.failureID)
	if err != nil {
		return nil, err
	}
	value.UpdateTime, value.EndTime, value.ActiveNodeIds = timestamppb.New(item.updated.UTC()), timestamp(item.ended), nil
	rows, err := tx.QueryContext(ctx, `SELECT node_id FROM workflow_transition_active_nodes WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3 AND transition_sequence=$4 ORDER BY ordinal`, identity.TenantID, identity.ProjectID, base.GetName(), item.sequence) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var node string
		if err = rows.Scan(&node); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.ActiveNodeIds = append(value.ActiveNodeIds, node)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	return value, nil
}

func (repository SQLRepository) ListTransitions(ctx context.Context, identity Identity, name string, after uint64, limit int) ([]*workflowv1.WorkflowRun, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 1000 {
		return nil, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	base, _, err := getRunTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT transition_sequence,revision,etag,state,completed_node_count,iteration_count,attempt_id,lease_epoch,output_ref_id,replay_state_ref_id,decision_log_ref_id,failure_detail_id,update_time,end_time FROM workflow_transition_revisions WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3 AND transition_sequence>$4 ORDER BY transition_sequence LIMIT $5`, identity.TenantID, identity.ProjectID, base.GetName(), after, limit) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var stored []transitionRow
	for rows.Next() {
		var item transitionRow
		if err = rows.Scan(&item.sequence, &item.revision, &item.etag, &item.state, &item.completedNodes, &item.iterations, &item.attemptID, &item.leaseEpoch, &item.outputID, &item.replayID, &item.decisionLogID, &item.failureID, &item.updated, &item.ended); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		stored = append(stored, item)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	values := make([]*workflowv1.WorkflowRun, 0, len(stored))
	for _, item := range stored {
		value := clone(base)
		if err = applyTransitionRow(value, item); err != nil {
			return nil, err
		}
		value.Output, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.outputID)
		if err != nil {
			return nil, err
		}
		value.ReplayState, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.replayID)
		if err != nil {
			return nil, err
		}
		value.DecisionLog, err = platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, item.decisionLogID)
		if err != nil {
			return nil, err
		}
		value.Failure, err = platformdb.LoadErrorDetail(ctx, tx, identity.TenantID, item.failureID)
		if err != nil {
			return nil, err
		}
		value.UpdateTime, value.EndTime, value.ActiveNodeIds = timestamppb.New(item.updated.UTC()), timestamp(item.ended), nil
		nodes, queryErr := tx.QueryContext(ctx, `SELECT node_id FROM workflow_transition_active_nodes WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3 AND transition_sequence=$4 ORDER BY ordinal`, identity.TenantID, identity.ProjectID, base.GetName(), item.sequence) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
		if queryErr != nil {
			return nil, queryErr
		}
		for nodes.Next() {
			var node string
			if queryErr = nodes.Scan(&node); queryErr != nil {
				_ = platformdb.CloseRows(nodes)
				return nil, queryErr
			}
			value.ActiveNodeIds = append(value.ActiveNodeIds, node)
		}
		if queryErr = platformdb.CloseRows(nodes); queryErr != nil {
			return nil, queryErr
		}
		if queryErr = nodes.Err(); queryErr != nil {
			return nil, queryErr
		}
		values = append(values, value)
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return cloneSlice(values), nil
}
