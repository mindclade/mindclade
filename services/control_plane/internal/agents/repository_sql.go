package agents

import (
	"context"
	"crypto/subtle"
	"database/sql"
	"errors"
	"fmt"
	"math"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	jobsapp "github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func (repository SQLRepository) CreateDefinition(ctx context.Context, identity Identity, request *internalagentv1.CreateAgentDefinitionRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetParent() != projectParent(identity) || !validID(request.GetAgentDefinitionId()) {
		return nil, false, ErrInvalidArgument
	}
	if err := validateDefinition(identity, request.GetAgentDefinition(), true); err != nil {
		return nil, false, err
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.definition.create", request.GetContext().GetIdempotencyKey()
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
	name := definitionName(identity, request.GetAgentDefinitionId())
	var exists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM agent_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3)`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err != nil {
		return nil, false, err
	}
	if exists {
		return nil, false, ErrAlreadyExists
	}
	value := clone(request.GetAgentDefinition())
	uid, err := randomID("agd_")
	if err != nil {
		return nil, false, err
	}
	value.Name, value.Uid, value.Revision, value.Etag, value.TenantId, value.ProjectId = name, uid, 1, resourceETag(name, 1), identity.TenantID, identity.ProjectID
	value.CreateTime, value.UpdateTime = timestamppb.New(at.UTC()), timestamppb.New(at.UTC())
	definitionID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetDefinition())
	if err != nil {
		return nil, false, err
	}
	workflowID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetWorkflowDefinition())
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
	evaluationID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetEvaluationSuite())
	if err != nil {
		return nil, false, err
	}
	wallSeconds, wallNanos, err := durationParts(value.GetBudget().GetMaximumWallTime(), true)
	if err != nil {
		return nil, false, err
	}
	acceleratorSeconds, acceleratorNanos, err := durationParts(value.GetBudget().GetMaximumAcceleratorTime(), false)
	if err != nil {
		return nil, false, err
	}
	cpuSeconds, cpuNanos, err := durationParts(value.GetBudget().GetMaximumCpuTime(), false)
	if err != nil {
		return nil, false, err
	}
	budget, limits := value.GetBudget(), value.GetLimits()
	_, err = tx.ExecContext(ctx, `INSERT INTO agent_definitions(tenant_id,project_id,name,uid,revision,etag,display_name,semantic_version,state,purpose,definition_ref_id,workflow_definition_ref_id,input_schema_ref_id,output_schema_ref_id,model_capability,evaluation_suite_ref_id,budget_maximum_model_tokens,budget_maximum_iterations,budget_maximum_tool_calls,budget_maximum_concurrent_branches,budget_maximum_storage_bytes,budget_maximum_external_spend_micros,budget_maximum_wall_time_seconds,budget_maximum_wall_time_nanos,budget_maximum_accelerator_time_seconds,budget_maximum_accelerator_time_nanos,budget_maximum_cpu_time_seconds,budget_maximum_cpu_time_nanos,limit_maximum_depth,limit_maximum_fan_out,limit_maximum_observations_per_step,limit_maximum_artifact_references_per_call,qualification_level,create_time,update_time,delete_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$33,NULL)`, identity.TenantID, identity.ProjectID, name, uid, value.GetEtag(), value.GetDisplayName(), value.GetSemanticVersion(), int32(value.GetState()), value.GetPurpose(), definitionID, workflowID, inputID, outputID, value.GetModelCapability(), evaluationID, budget.GetMaximumModelTokens(), budget.GetMaximumIterations(), budget.GetMaximumToolCalls(), budget.GetMaximumConcurrentBranches(), budget.GetMaximumStorageBytes(), budget.GetMaximumExternalSpendMicros(), wallSeconds, wallNanos, acceleratorSeconds, acceleratorNanos, cpuSeconds, cpuNanos, limits.GetMaximumDepth(), limits.GetMaximumFanOut(), limits.GetMaximumObservationsPerStep(), limits.GetMaximumArtifactReferencesPerCall(), value.GetQualificationLevel(), at.UTC())
	if err != nil {
		return nil, false, err
	}
	if err = storeDefinitionChildren(ctx, tx, identity, name, value); err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, definitionResource(value), action, digest, at)
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

func validDefinitionTransition(from, to agentv1.AgentDefinitionState) bool {
	if from == to {
		return true
	}
	switch from {
	case agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DRAFT:
		return to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ACTIVE || to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_REVOKED
	case agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ACTIVE:
		return to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DEPRECATED || to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_REVOKED
	case agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DEPRECATED:
		return to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_REVOKED || to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ARCHIVED
	case agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_REVOKED:
		return to == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ARCHIVED
	default:
		return false
	}
}

func (repository SQLRepository) UpdateDefinition(ctx context.Context, identity Identity, request *internalagentv1.UpdateAgentDefinitionRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetAgentDefinition() == nil || request.GetEtag() == "" || request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.definition.update", request.GetContext().GetIdempotencyKey()
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
	name := request.GetAgentDefinition().GetName()
	row, err := scanDefinition(tx.QueryRowContext(ctx, `SELECT `+definitionColumns+` FROM agent_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
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
	childrenChanged := false
	for _, path := range request.GetUpdateMask().GetPaths() {
		switch path {
		case "display_name":
			after.DisplayName = request.GetAgentDefinition().GetDisplayName()
		case "state":
			if !validDefinitionTransition(before.GetState(), request.GetAgentDefinition().GetState()) {
				return nil, false, ErrInvalidTransition
			}
			after.State = request.GetAgentDefinition().GetState()
		case "purpose":
			after.Purpose = request.GetAgentDefinition().GetPurpose()
		case "non_goals":
			after.NonGoals = append([]string(nil), request.GetAgentDefinition().GetNonGoals()...)
			childrenChanged = true
		case "eligible_tools":
			after.EligibleTools = cloneSlice(request.GetAgentDefinition().GetEligibleTools())
			childrenChanged = true
		case "policy_snapshots":
			after.PolicySnapshots = cloneSlice(request.GetAgentDefinition().GetPolicySnapshots())
			childrenChanged = true
		case "budget":
			after.Budget = clone(request.GetAgentDefinition().GetBudget())
		case "limits":
			after.Limits = clone(request.GetAgentDefinition().GetLimits())
		case "qualification_level":
			after.QualificationLevel = request.GetAgentDefinition().GetQualificationLevel()
		default:
			return nil, false, ErrInvalidArgument
		}
	}
	if err = validateDefinition(identity, after, false); err != nil {
		return nil, false, err
	}
	after.Revision = before.GetRevision() + 1
	after.Etag = resourceETag(name, after.GetRevision())
	after.UpdateTime = timestamppb.New(at.UTC())
	if after.GetState() == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ARCHIVED && after.GetDeleteTime() == nil {
		after.DeleteTime = timestamppb.New(at.UTC())
	}
	wallSeconds, wallNanos, err := durationParts(after.GetBudget().GetMaximumWallTime(), true)
	if err != nil {
		return nil, false, err
	}
	acceleratorSeconds, acceleratorNanos, err := durationParts(after.GetBudget().GetMaximumAcceleratorTime(), false)
	if err != nil {
		return nil, false, err
	}
	cpuSeconds, cpuNanos, err := durationParts(after.GetBudget().GetMaximumCpuTime(), false)
	if err != nil {
		return nil, false, err
	}
	budget, limits := after.GetBudget(), after.GetLimits()
	var deleted any
	if after.GetDeleteTime() != nil {
		deleted = after.GetDeleteTime().AsTime().UTC()
	}
	result, err := tx.ExecContext(ctx, `UPDATE agent_definitions SET revision=$4,etag=$5,display_name=$6,state=$7,purpose=$8,budget_maximum_model_tokens=$9,budget_maximum_iterations=$10,budget_maximum_tool_calls=$11,budget_maximum_concurrent_branches=$12,budget_maximum_storage_bytes=$13,budget_maximum_external_spend_micros=$14,budget_maximum_wall_time_seconds=$15,budget_maximum_wall_time_nanos=$16,budget_maximum_accelerator_time_seconds=$17,budget_maximum_accelerator_time_nanos=$18,budget_maximum_cpu_time_seconds=$19,budget_maximum_cpu_time_nanos=$20,limit_maximum_depth=$21,limit_maximum_fan_out=$22,limit_maximum_observations_per_step=$23,limit_maximum_artifact_references_per_call=$24,qualification_level=$25,update_time=$26,delete_time=$27 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$28 AND etag=$29`, identity.TenantID, identity.ProjectID, name, after.GetRevision(), after.GetEtag(), after.GetDisplayName(), int32(after.GetState()), after.GetPurpose(), budget.GetMaximumModelTokens(), budget.GetMaximumIterations(), budget.GetMaximumToolCalls(), budget.GetMaximumConcurrentBranches(), budget.GetMaximumStorageBytes(), budget.GetMaximumExternalSpendMicros(), wallSeconds, wallNanos, acceleratorSeconds, acceleratorNanos, cpuSeconds, cpuNanos, limits.GetMaximumDepth(), limits.GetMaximumFanOut(), limits.GetMaximumObservationsPerStep(), limits.GetMaximumArtifactReferencesPerCall(), after.GetQualificationLevel(), at.UTC(), deleted, before.GetRevision(), before.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	if childrenChanged {
		for _, table := range []string{"agent_definition_non_goals", "agent_definition_tools", "agent_definition_policies"} {
			if _, err = tx.ExecContext(ctx, `DELETE FROM `+table+` WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3`, identity.TenantID, identity.ProjectID, name); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				return nil, false, err
			}
		}
		if err = storeDefinitionChildren(ctx, tx, identity, name, after); err != nil {
			return nil, false, err
		}
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, definitionResource(after), action, digest, at)
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

func (repository SQLRepository) GetDefinition(ctx context.Context, identity Identity, name string) (*agentv1.AgentDefinition, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, err
	}
	canonical, err := canonicalScopedName(identity, name, "agentDefinitions")
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanDefinition(tx.QueryRowContext(ctx, `SELECT `+definitionColumns+` FROM agent_definitions WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
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

func (repository SQLRepository) ListDefinitions(ctx context.Context, identity Identity, page DefinitionPage) ([]*agentv1.AgentDefinition, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err := validateIdentity(identity); err != nil || page.Limit <= 0 || page.Limit > maximumPageSize {
		if err != nil {
			return nil, "", time.Time{}, err
		}
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
	query := `SELECT ` + definitionColumns + ` FROM agent_definitions WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_UNSPECIFIED {
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
	rows, err := tx.QueryContext(ctx, query, args...)
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
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*agentv1.AgentDefinition, 0, len(stored))
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
		token, err = repository.Pagination.encode(pageToken{Kind: "agent-definitions", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func (repository SQLRepository) StartRun(ctx context.Context, identity Identity, request *internalagentv1.StartAgentRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	if err := validateStartRun(identity, request); err != nil {
		return nil, false, err
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.run.start", request.GetContext().GetIdempotencyKey()
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
	name := runName(identity, request.GetAgentRunId())
	var exists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM agent_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3)`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err != nil {
		return nil, false, err
	}
	if exists {
		return nil, false, ErrAlreadyExists
	}
	if err = verifyDefinitionForRun(ctx, tx, identity, request.GetAgentRun().GetDefinition(), request.GetAgentRun().GetDefinitionDigest()); err != nil {
		return nil, false, err
	}
	value := clone(request.GetAgentRun())
	uid, err := randomID("agr_")
	if err != nil {
		return nil, false, err
	}
	value.Name, value.Uid, value.Revision, value.Etag, value.TenantId, value.ProjectId = name, uid, 1, resourceETag(name, 1), identity.TenantID, identity.ProjectID
	value.State = agentv1.AgentRunState_AGENT_RUN_STATE_CREATED
	value.NextStepSequence = 1
	value.BudgetUsage = &agentv1.AgentBudgetUsage{}
	value.CreateTime, value.UpdateTime = timestamppb.New(at.UTC()), timestamppb.New(at.UTC())
	definitionID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetDefinition())
	if err != nil {
		return nil, false, err
	}
	workflowID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetWorkflowRun())
	if err != nil {
		return nil, false, err
	}
	inputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetInput())
	if err != nil {
		return nil, false, err
	}
	providerID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetModelProviderManifest())
	if err != nil {
		return nil, false, err
	}
	budgetID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetBudgetReservation())
	if err != nil {
		return nil, false, err
	}
	operation, schedulerRunID, err := insertQueuedWork(ctx, tx, identity, runResource(value), "agent.run", digest, value.GetDefinitionDigest(), inputID, at)
	if err != nil {
		return nil, false, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO agent_runs(tenant_id,project_id,name,uid,revision,etag,definition_ref_id,definition_digest,workflow_run_ref_id,input_ref_id,model_provider_manifest_ref_id,budget_reservation_ref_id,usage_model_tokens,usage_iterations,usage_tool_calls,usage_storage_bytes,usage_external_spend_micros,usage_accelerator_milliseconds,usage_cpu_milliseconds,state,active_step_name,next_step_sequence,attempt_id,lease_epoch,cancellation_requested,run_manifest_ref_id,output_ref_id,failure_detail_id,create_time,update_time,end_time,operation_id,job_id,scheduler_run_id) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,0,0,0,0,0,0,0,$12,'',1,'',0,false,NULL,NULL,NULL,$13,$13,NULL,$14,$15,$16)`, identity.TenantID, identity.ProjectID, name, uid, value.GetEtag(), definitionID, value.GetDefinitionDigest(), workflowID, inputID, providerID, budgetID, int32(value.GetState()), at.UTC(), operation.GetOperationId(), operation.GetJobId(), schedulerRunID)
	if err != nil {
		return nil, false, err
	}
	if err = storeRunPolicies(ctx, tx, identity, name, value.GetPolicySnapshots()); err != nil {
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

func (repository SQLRepository) GetRun(ctx context.Context, identity Identity, name string) (*agentv1.AgentRun, error) {
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

func (repository SQLRepository) ListRuns(ctx context.Context, identity Identity, page RunPage) ([]*agentv1.AgentRun, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err := validateIdentity(identity); err != nil || page.Limit <= 0 || page.Limit > maximumPageSize {
		if err != nil {
			return nil, "", time.Time{}, err
		}
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
	query := `SELECT ` + runColumns + ` FROM agent_runs WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != agentv1.AgentRunState_AGENT_RUN_STATE_UNSPECIFIED {
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
	rows, err := tx.QueryContext(ctx, query, args...)
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
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*agentv1.AgentRun, 0, len(stored))
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
		token, err = repository.Pagination.encode(pageToken{Kind: "agent-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func (repository SQLRepository) CancelRun(ctx context.Context, identity Identity, request *internalagentv1.CancelAgentRunRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetName() == "" || request.GetEtag() == "" || request.GetReason() == "" {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.run.cancel", request.GetContext().GetIdempotencyKey()
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
	if request.GetEtag() != before.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if terminalRunState(before.GetState()) {
		return nil, false, ErrInvalidTransition
	}
	after := clone(before)
	after.Revision++
	after.Etag = resourceETag(after.GetName(), after.GetRevision())
	after.CancellationRequested = true
	after.State = agentv1.AgentRunState_AGENT_RUN_STATE_CANCELLING
	after.UpdateTime = timestamppb.New(at.UTC())
	result, err := tx.ExecContext(ctx, `UPDATE agent_runs SET revision=$4,etag=$5,state=$6,cancellation_requested=true,update_time=$7 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$8 AND etag=$9`, identity.TenantID, identity.ProjectID, after.GetName(), after.GetRevision(), after.GetEtag(), int32(after.GetState()), at.UTC(), before.GetRevision(), before.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	if err = advanceSchedulerCancellation(ctx, tx, identity, row.jobID, row.schedulerRunID, at); err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, after, "CANCELLING", false, at); err != nil {
		return nil, false, err
	}
	operation, err := loadOperationTx(ctx, tx, identity, row.operationID)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.CancellationRequested(identity, after, operation, request.GetReason(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, operation.GetOperationId(), after.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetStep(ctx context.Context, identity Identity, name string) (*agentv1.AgentStep, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	if err := validateIdentity(identity); err != nil {
		return nil, err
	}
	canonical, err := canonicalStepName(identity, name)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanStep(tx.QueryRowContext(ctx, `SELECT `+stepColumns+` FROM agent_steps WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := stepProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (repository SQLRepository) ListSteps(ctx context.Context, identity Identity, page StepPage) ([]*agentv1.AgentStep, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err := validateIdentity(identity); err != nil || page.Limit <= 0 || page.Limit > maximumPageSize {
		if err != nil {
			return nil, "", time.Time{}, err
		}
		return nil, "", time.Time{}, ErrInvalidArgument
	}
	parent, err := canonicalScopedName(identity, page.Parent, "agentRuns")
	if err != nil {
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
	rows, err := tx.QueryContext(ctx, `SELECT `+stepColumns+` FROM agent_steps WHERE tenant_id=$1 AND project_id=$2 AND agent_run_name=$3 AND sequence>$4 ORDER BY sequence LIMIT $5`, identity.TenantID, identity.ProjectID, parent, page.AfterSequence, page.Limit+1)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []stepRow
	for rows.Next() {
		item, scanErr := scanStep(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*agentv1.AgentStep, 0, len(stored))
	for _, item := range stored {
		value, mapErr := stepProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	token := ""
	if hasMore {
		last := stored[len(stored)-1]
		afterSequence, conversionErr := numconv.Int64ToUint64(last.sequence)
		if conversionErr != nil {
			return nil, "", time.Time{}, conversionErr
		}
		token, err = repository.Pagination.encode(pageToken{Kind: "agent-steps", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: parent, Filter: page.Filter, Order: page.Order, AfterSequence: afterSequence})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func (repository SQLRepository) CommitStep(ctx context.Context, identity Identity, request *internalagentv1.CommitAgentStepRequest, digest string, at time.Time) (*agentv1.AgentStep, *agentv1.AgentRun, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, nil, false, err
	}
	if request == nil || request.GetRunEtag() == "" || request.GetExpectedNextStepSequence() == 0 {
		return nil, nil, false, ErrInvalidArgument
	}
	if err := validateStep(identity, request.GetAgentStep()); err != nil {
		return nil, nil, false, err
	}
	if err := validateFence(identity, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, nil, false, err
	}
	if call := request.GetAgentStep().GetDecision().GetToolCall(); call != nil {
		if !at.Before(call.GetDeadline().AsTime()) {
			return nil, nil, false, ErrDeadlineExceeded
		}
		if err := validateAuthorizationAt(call.GetAuthorization(), at); err != nil {
			return nil, nil, false, err
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.step.commit", request.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		step, rowErr := getStepTx(ctx, tx, identity, responseName, false)
		if rowErr != nil {
			return nil, nil, false, rowErr
		}
		run, _, runErr := getRunTx(ctx, tx, identity, step.GetRun().GetName(), false)
		if runErr != nil {
			return nil, nil, false, runErr
		}
		if err = tx.Commit(); err != nil {
			return nil, nil, false, err
		}
		return clone(step), clone(run), true, nil
	}
	runNameValue := request.GetAgentStep().GetRun().GetName()
	before, row, err := getRunTx(ctx, tx, identity, runNameValue, true)
	if err != nil {
		return nil, nil, false, err
	}
	if request.GetRunEtag() != before.GetEtag() || request.GetExpectedNextStepSequence() != before.GetNextStepSequence() || request.GetAgentStep().GetSequence() != before.GetNextStepSequence() {
		return nil, nil, false, ErrRevisionConflict
	}
	if terminalRunState(before.GetState()) || before.GetCancellationRequested() {
		return nil, nil, false, ErrInvalidTransition
	}
	if err = verifyCurrentFence(ctx, tx, identity, row, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	if before.GetAttemptId() != "" && (before.GetAttemptId() != request.GetFence().GetAttemptId() || before.GetLeaseEpoch() != request.GetFence().GetLeaseEpoch()) {
		return nil, nil, false, ErrStaleFence
	}
	step := clone(request.GetAgentStep())
	uid, err := randomID("ags_")
	if err != nil {
		return nil, nil, false, err
	}
	step.Name = stepName(before.GetName(), step.GetSequence())
	step.Uid = uid
	step.Revision = 1
	step.Etag = resourceETag(step.GetName(), 1)
	step.AttemptId = request.GetFence().GetAttemptId()
	step.LeaseEpoch = request.GetFence().GetLeaseEpoch()
	step.CreateTime = timestamppb.New(at.UTC())
	step.UpdateTime = timestamppb.New(at.UTC())
	if call := step.GetDecision().GetToolCall(); call != nil {
		if call.GetAgentRunName() != before.GetName() || call.GetAgentStepName() != step.GetName() {
			return nil, nil, false, ErrInvalidArgument
		}
	}
	after := clone(before)
	after.Revision++
	after.Etag = resourceETag(after.GetName(), after.GetRevision())
	after.ActiveStepName = step.GetName()
	after.NextStepSequence++
	after.AttemptId = step.GetAttemptId()
	after.LeaseEpoch = step.GetLeaseEpoch()
	after.UpdateTime = timestamppb.New(at.UTC())
	after.BudgetUsage.Iterations++
	after.State = stateAfterStep(step)
	terminal := terminalRunState(after.GetState())
	if terminal {
		after.EndTime = timestamppb.New(at.UTC())
		if step.GetFailure() != nil {
			after.Failure = clone(step.GetFailure())
		}
		if result := step.GetDecision().GetTerminalResult(); result != nil {
			// For a successful terminal step, step.output is the verified
			// AgentRunManifest and terminal_result is the domain output.
			after.RunManifest = clone(step.GetOutput())
			after.Output = clone(result)
		}
	}
	manifestID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, after.GetRunManifest())
	if err != nil {
		return nil, nil, false, err
	}
	outputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, after.GetOutput())
	if err != nil {
		return nil, nil, false, err
	}
	failureID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, after.GetFailure())
	if err != nil {
		return nil, nil, false, err
	}
	var end any
	if after.GetEndTime() != nil {
		end = after.GetEndTime().AsTime().UTC()
	}
	result, err := tx.ExecContext(ctx, `UPDATE agent_runs SET revision=$4,etag=$5,usage_iterations=$6,state=$7,active_step_name=$8,next_step_sequence=$9,attempt_id=$10,lease_epoch=$11,run_manifest_ref_id=$12,output_ref_id=$13,failure_detail_id=$14,update_time=$15,end_time=$16 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$17 AND etag=$18 AND next_step_sequence=$19`, identity.TenantID, identity.ProjectID, after.GetName(), after.GetRevision(), after.GetEtag(), after.GetBudgetUsage().GetIterations(), int32(after.GetState()), after.GetActiveStepName(), after.GetNextStepSequence(), after.GetAttemptId(), after.GetLeaseEpoch(), manifestID, outputID, failureID, at.UTC(), end, before.GetRevision(), before.GetEtag(), before.GetNextStepSequence())
	if err != nil {
		return nil, nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, nil, false, err
	}
	if err = storeStep(ctx, tx, identity, step); err != nil {
		return nil, nil, false, err
	}
	events := make([]*commonv1.EventEnvelope, 0, 2)
	var stepEvent *commonv1.EventEnvelope
	if step.GetState() == agentv1.AgentStepState_AGENT_STEP_STATE_DISPATCHED {
		stepEvent, err = repository.Events.AgentStepDispatched(identity, step, request.GetFence(), request.GetContext(), at)
	} else {
		stepEvent, err = repository.Events.StepCommitted(identity, step, after, request.GetContext(), at)
	}
	if err != nil {
		return nil, nil, false, err
	}
	events = append(events, stepEvent)
	if terminal {
		if after.GetState() == agentv1.AgentRunState_AGENT_RUN_STATE_SUCCEEDED && after.GetRunManifest() == nil {
			return nil, nil, false, ErrInvalidArgument
		}
		runEvent, eventErr := repository.Events.RunCompleted(identity, after, request.GetContext(), at)
		if eventErr != nil {
			return nil, nil, false, eventErr
		}
		events = append(events, runEvent)
		if err = finishScheduler(ctx, tx, identity, row, request.GetFence(), after, at); err != nil {
			return nil, nil, false, err
		}
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", step.GetName(), events, at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(step), clone(after), false, nil
}

func (repository SQLRepository) CommitToolReceipt(ctx context.Context, identity Identity, request *internalagentv1.CommitToolReceiptRequest, digest string, at time.Time) (*agentv1.ToolReceipt, *agentv1.AgentRun, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, nil, false, err
	}
	if request == nil || request.GetRunEtag() == "" {
		return nil, nil, false, ErrInvalidArgument
	}
	if err := validateToolReceipt(identity, request.GetToolReceipt()); err != nil {
		return nil, nil, false, err
	}
	if err := validateFence(identity, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), at, digest); err != nil {
		return nil, nil, false, err
	}
	if err := validateAuthorizationAt(request.GetToolReceipt().GetAuthorization(), at); err != nil {
		return nil, nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "agent.tool_receipt.commit", request.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		receipt, loadErr := getReceiptTx(ctx, tx, identity, responseName)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		run, _, runErr := getRunTx(ctx, tx, identity, receipt.GetAgentRunName(), false)
		if runErr != nil {
			return nil, nil, false, runErr
		}
		if err = tx.Commit(); err != nil {
			return nil, nil, false, err
		}
		return clone(receipt), clone(run), true, nil
	}
	receipt := clone(request.GetToolReceipt())
	before, row, err := getRunTx(ctx, tx, identity, receipt.GetAgentRunName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	if request.GetRunEtag() != before.GetEtag() {
		return nil, nil, false, ErrRevisionConflict
	}
	if terminalRunState(before.GetState()) {
		return nil, nil, false, ErrInvalidTransition
	}
	if err = verifyCurrentFence(ctx, tx, identity, row, request.GetFence(), at); err != nil {
		return nil, nil, false, err
	}
	if receipt.GetAttemptId() != request.GetFence().GetAttemptId() || receipt.GetLeaseEpoch() != request.GetFence().GetLeaseEpoch() || receipt.GetExecutorIdentity() != identity.WorkerID || receipt.GetIdempotencyKey() != key {
		return nil, nil, false, ErrPermissionDenied
	}
	step, err := getStepTx(ctx, tx, identity, receipt.GetAgentStepName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	call := step.GetDecision().GetToolCall()
	if call == nil || call.GetCallId() != receipt.GetCallId() || call.GetAgentRunName() != receipt.GetAgentRunName() || call.GetAgentStepName() != receipt.GetAgentStepName() || call.GetToolVersion() != receipt.GetToolVersion() || call.GetInputDigest() != receipt.GetInputDigest() || call.GetExpectedOutputSchema().GetDigest() != receipt.GetExpectedOutputSchemaDigest() || !proto.Equal(call.GetTool(), receipt.GetTool()) || call.GetAuthorization().GetDecisionDigest() != receipt.GetAuthorization().GetDecisionDigest() {
		return nil, nil, false, ErrInvalidArgument
	}
	var receiptExists bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM agent_tool_receipts WHERE tenant_id=$1 AND project_id=$2 AND (name=$3 OR call_id=$4 OR receipt_digest=$5 OR idempotency_key=$6))`, identity.TenantID, identity.ProjectID, receipt.GetName(), receipt.GetCallId(), receipt.GetReceiptDigest(), receipt.GetIdempotencyKey()).Scan(&receiptExists); err != nil {
		return nil, nil, false, err
	}
	if receiptExists {
		return nil, nil, false, ErrAlreadyExists
	}
	if err = storeToolReceipt(ctx, tx, identity, receipt); err != nil {
		return nil, nil, false, err
	}
	after := clone(before)
	after.Revision++
	after.Etag = resourceETag(after.GetName(), after.GetRevision())
	after.UpdateTime = timestamppb.New(at.UTC())
	usage := after.GetBudgetUsage()
	deltaStorage := receipt.GetUsage().GetInputBytes() + receipt.GetUsage().GetOutputBytes()
	if usage.GetToolCalls() == ^uint32(0) || usage.GetStorageBytes() > math.MaxInt64-deltaStorage || usage.GetExternalSpendMicros() > math.MaxInt64-receipt.GetUsage().GetExternalSpendMicros() || usage.GetAcceleratorMilliseconds() > math.MaxInt64-receipt.GetUsage().GetAcceleratorMilliseconds() || usage.GetCpuMilliseconds() > math.MaxInt64-receipt.GetUsage().GetCpuMilliseconds() {
		return nil, nil, false, ErrInvalidArgument
	}
	usage.ToolCalls++
	usage.StorageBytes += deltaStorage
	usage.ExternalSpendMicros += receipt.GetUsage().GetExternalSpendMicros()
	usage.AcceleratorMilliseconds += receipt.GetUsage().GetAcceleratorMilliseconds()
	usage.CpuMilliseconds += receipt.GetUsage().GetCpuMilliseconds()
	after.State = agentv1.AgentRunState_AGENT_RUN_STATE_RUNNING
	result, err := tx.ExecContext(ctx, `UPDATE agent_runs SET revision=$4,etag=$5,usage_tool_calls=$6,usage_storage_bytes=$7,usage_external_spend_micros=$8,usage_accelerator_milliseconds=$9,usage_cpu_milliseconds=$10,state=$11,update_time=$12 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$13 AND etag=$14`, identity.TenantID, identity.ProjectID, after.GetName(), after.GetRevision(), after.GetEtag(), usage.GetToolCalls(), usage.GetStorageBytes(), usage.GetExternalSpendMicros(), usage.GetAcceleratorMilliseconds(), usage.GetCpuMilliseconds(), int32(after.GetState()), at.UTC(), before.GetRevision(), before.GetEtag())
	if err != nil {
		return nil, nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, nil, false, err
	}
	event, err := repository.Events.ToolReceiptCommitted(identity, receipt, uint64(after.GetBudgetUsage().GetToolCalls()), request.GetContext(), at)
	if err != nil {
		return nil, nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", receipt.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(receipt), clone(after), false, nil
}

func getStepTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*agentv1.AgentStep, error) {
	canonical, err := canonicalStepName(identity, name)
	if err != nil {
		return nil, err
	}
	query := `SELECT ` + stepColumns + ` FROM agent_steps WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += " FOR UPDATE"
	}
	row, err := scanStep(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return stepProto(ctx, tx, row)
}

func getReceiptTx(ctx context.Context, tx *sql.Tx, identity Identity, name string) (*agentv1.ToolReceipt, error) {
	row, err := scanReceipt(tx.QueryRowContext(ctx, `SELECT `+receiptColumns+` FROM agent_tool_receipts WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return receiptProto(ctx, tx, row)
}

func validateRepositoryCommand(identity Identity, command proto.Message, commandContext *commonv1.CommandContext, at time.Time, expectedDigest string) error {
	digest, err := validateContext(identity, command, commandContext, at)
	if err != nil {
		return err
	}
	if !validSHA256(expectedDigest) || subtle.ConstantTimeCompare([]byte(digest), []byte(expectedDigest)) != 1 {
		return ErrInvalidArgument
	}
	return nil
}

func verifyDefinitionForRun(ctx context.Context, tx *sql.Tx, identity Identity, reference *commonv1.ResourceRef, digest string) error {
	if reference == nil || reference.GetResourceType() != "agent_definition" {
		return ErrInvalidArgument
	}
	var revision int64
	var etag, storedDigest string
	var state int32
	err := tx.QueryRowContext(ctx, `SELECT d.revision,d.etag,d.state,a.digest FROM agent_definitions d JOIN artifact_references a ON a.tenant_id=d.tenant_id AND a.id=d.definition_ref_id WHERE d.tenant_id=$1 AND d.project_id=$2 AND d.name=$3 FOR SHARE OF d,a`, identity.TenantID, identity.ProjectID, reference.GetName()).Scan(&revision, &etag, &state, &storedDigest)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrNotFound
	}
	if err != nil {
		return err
	}
	if revision != reference.GetResourceVersion() || subtle.ConstantTimeCompare([]byte(etag), []byte(reference.GetEtag())) != 1 || agentv1.AgentDefinitionState(state) != agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ACTIVE || subtle.ConstantTimeCompare([]byte(storedDigest), []byte(digest)) != 1 {
		return ErrRevisionConflict
	}
	return nil
}

func verifyCurrentFence(ctx context.Context, tx *sql.Tx, identity Identity, row runRow, fence *jobv1.LeaseFence, at time.Time) error {
	if err := validateFence(identity, fence, at); err != nil {
		return err
	}
	presented, err := jobsapp.LeaseTokenDigest(identity.LeaseToken)
	if err != nil {
		return ErrLeaseToken
	}
	if subtle.ConstantTimeCompare([]byte(presented), []byte(fence.GetLeaseTokenDigest())) != 1 {
		return ErrLeaseToken
	}
	if fence.GetJobId() != row.jobID || fence.GetRunId() != row.schedulerRunID {
		return ErrStaleFence
	}
	var jobState string
	if err = tx.QueryRowContext(ctx, `SELECT desired_state FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, row.jobID).Scan(&jobState); errors.Is(err, sql.ErrNoRows) {
		return ErrStaleFence
	} else if err != nil {
		return err
	}
	var runState string
	var currentEpoch uint64
	if err = tx.QueryRowContext(ctx, `SELECT status,lease_epoch FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND job_id=$4 FOR UPDATE`, identity.TenantID, identity.ProjectID, row.schedulerRunID, row.jobID).Scan(&runState, &currentEpoch); errors.Is(err, sql.ErrNoRows) {
		return ErrStaleFence
	} else if err != nil {
		return err
	}
	var worker, digest, status string
	var epoch uint64
	var expiry time.Time
	if err = tx.QueryRowContext(ctx, `SELECT worker_id,lease_token_digest,lease_epoch,lease_expires_at,status FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 AND job_id=$5 FOR UPDATE`, identity.TenantID, identity.ProjectID, fence.GetAttemptId(), row.schedulerRunID, row.jobID).Scan(&worker, &digest, &epoch, &expiry, &status); errors.Is(err, sql.ErrNoRows) {
		return ErrStaleFence
	} else if err != nil {
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
	if status != "LEASED" && status != "ACTIVE" || runState != "EXECUTING" || jobState == "CANCELLED" || jobState == "SUCCEEDED" || jobState == "FAILED" {
		return ErrStaleFence
	}
	if !at.Before(expiry.UTC()) || !expiry.UTC().Equal(fence.GetDeadline().AsTime().UTC()) {
		return ErrLeaseExpired
	}
	return nil
}

func stateAfterStep(step *agentv1.AgentStep) agentv1.AgentRunState {
	switch step.GetState() {
	case agentv1.AgentStepState_AGENT_STEP_STATE_FAILED:
		return agentv1.AgentRunState_AGENT_RUN_STATE_FAILED
	case agentv1.AgentStepState_AGENT_STEP_STATE_CANCELLED:
		return agentv1.AgentRunState_AGENT_RUN_STATE_CANCELLED
	case agentv1.AgentStepState_AGENT_STEP_STATE_EXPIRED:
		return agentv1.AgentRunState_AGENT_RUN_STATE_EXPIRED
	}
	if step.GetDecision().GetTerminalResult() != nil && step.GetState() == agentv1.AgentStepState_AGENT_STEP_STATE_SUCCEEDED {
		return agentv1.AgentRunState_AGENT_RUN_STATE_SUCCEEDED
	}
	if step.GetDecision().GetToolCall() != nil {
		return agentv1.AgentRunState_AGENT_RUN_STATE_WAITING_FOR_TOOL
	}
	if step.GetDecision().GetDomainJob() != nil {
		return agentv1.AgentRunState_AGENT_RUN_STATE_WAITING_FOR_JOB
	}
	if step.GetDecision().GetApprovalRequest() != nil {
		return agentv1.AgentRunState_AGENT_RUN_STATE_WAITING_FOR_APPROVAL
	}
	if step.GetDecision().GetWait() != nil {
		return agentv1.AgentRunState_AGENT_RUN_STATE_PAUSED
	}
	return agentv1.AgentRunState_AGENT_RUN_STATE_RUNNING
}

func terminalRunState(state agentv1.AgentRunState) bool {
	return state == agentv1.AgentRunState_AGENT_RUN_STATE_SUCCEEDED || state == agentv1.AgentRunState_AGENT_RUN_STATE_FAILED || state == agentv1.AgentRunState_AGENT_RUN_STATE_CANCELLED || state == agentv1.AgentRunState_AGENT_RUN_STATE_EXPIRED
}

func finishScheduler(ctx context.Context, tx *sql.Tx, identity Identity, row runRow, fence *jobv1.LeaseFence, run *agentv1.AgentRun, at time.Time) error {
	jobStatus, runStatus, attemptStatus, operationStatus := "SUCCEEDED", "SUCCEEDED", "COMPLETED", "SUCCEEDED"
	switch run.GetState() {
	case agentv1.AgentRunState_AGENT_RUN_STATE_CANCELLED:
		jobStatus, runStatus, attemptStatus, operationStatus = "CANCELLED", "CANCELLED", "CANCELLED", "CANCELLED"
	case agentv1.AgentRunState_AGENT_RUN_STATE_FAILED, agentv1.AgentRunState_AGENT_RUN_STATE_EXPIRED:
		jobStatus, runStatus, attemptStatus, operationStatus = "FAILED", "FAILED", "FAILED", "FAILED"
	}
	attemptResult, err := tx.ExecContext(ctx, `UPDATE attempts SET status=$6,version=version+1,completed_at=$7,updated_at=$7 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 AND lease_epoch=$5 AND status IN ('LEASED','ACTIVE')`, identity.TenantID, identity.ProjectID, fence.GetAttemptId(), row.schedulerRunID, fence.GetLeaseEpoch(), attemptStatus, at.UTC())
	if err != nil {
		return err
	}
	if err = requireOne(attemptResult); err != nil {
		return ErrStaleFence
	}
	runResult, err := tx.ExecContext(ctx, `UPDATE runs SET status=$4,version=version+1,completed_at=$5,updated_at=$5 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND status='EXECUTING'`, identity.TenantID, identity.ProjectID, row.schedulerRunID, runStatus, at.UTC())
	if err != nil {
		return err
	}
	if err = requireOne(runResult); err != nil {
		return err
	}
	jobResult, err := tx.ExecContext(ctx, `UPDATE jobs SET desired_state=$4,version=version+1,updated_at=$5 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND desired_state NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, identity.TenantID, identity.ProjectID, row.jobID, jobStatus, at.UTC())
	if err != nil {
		return err
	}
	if err = requireOne(jobResult); err != nil {
		return err
	}
	return updateOperationTarget(ctx, tx, identity, row.operationID, run, operationStatus, true, at)
}
