package agents

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	workflowapp "github.com/mindclade/mindclade/services/control_plane/internal/workflows"
)

type scanner interface{ Scan(...any) error }

func workflowIdentity(identity Identity) workflowapp.Identity {
	return workflowapp.Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal, WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken, Roles: identity.Roles}
}

func durationParts(value *durationpb.Duration, required bool) (int64, int32, error) {
	if value == nil {
		if required {
			return 0, 0, ErrInvalidArgument
		}
		return 0, 0, nil
	}
	if err := value.CheckValid(); err != nil {
		return 0, 0, ErrInvalidArgument
	}
	return value.GetSeconds(), value.GetNanos(), nil
}

type definitionRow struct {
	tenant, project, name, uid, etag, displayName, semanticVersion, purpose string
	modelCapability, qualificationLevel                                     string
	revision                                                                int64
	state                                                                   int32
	definitionID, workflowID, inputID, outputID, evaluationID               sql.NullInt64
	maxModelTokens, maxIterations, maxToolCalls, maxBranches                int64
	maxStorageBytes, maxSpend                                               int64
	wallSeconds, acceleratorSeconds, cpuSeconds                             int64
	wallNanos, acceleratorNanos, cpuNanos                                   int32
	maxDepth, maxFanOut, maxObservations, maxArtifacts                      int64
	created, updated                                                        time.Time
	deleted                                                                 sql.NullTime
}

const definitionColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,semantic_version,state,purpose,definition_ref_id,workflow_definition_ref_id,input_schema_ref_id,output_schema_ref_id,model_capability,evaluation_suite_ref_id,budget_maximum_model_tokens,budget_maximum_iterations,budget_maximum_tool_calls,budget_maximum_concurrent_branches,budget_maximum_storage_bytes,budget_maximum_external_spend_micros,budget_maximum_wall_time_seconds,budget_maximum_wall_time_nanos,budget_maximum_accelerator_time_seconds,budget_maximum_accelerator_time_nanos,budget_maximum_cpu_time_seconds,budget_maximum_cpu_time_nanos,limit_maximum_depth,limit_maximum_fan_out,limit_maximum_observations_per_step,limit_maximum_artifact_references_per_call,qualification_level,create_time,update_time,delete_time`

func scanDefinition(row scanner) (definitionRow, error) {
	var value definitionRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.displayName, &value.semanticVersion, &value.state, &value.purpose, &value.definitionID, &value.workflowID, &value.inputID, &value.outputID, &value.modelCapability, &value.evaluationID, &value.maxModelTokens, &value.maxIterations, &value.maxToolCalls, &value.maxBranches, &value.maxStorageBytes, &value.maxSpend, &value.wallSeconds, &value.wallNanos, &value.acceleratorSeconds, &value.acceleratorNanos, &value.cpuSeconds, &value.cpuNanos, &value.maxDepth, &value.maxFanOut, &value.maxObservations, &value.maxArtifacts, &value.qualificationLevel, &value.created, &value.updated, &value.deleted)
	return value, err
}

func definitionProto(ctx context.Context, tx *sql.Tx, row definitionRow) (*agentv1.AgentDefinition, error) {
	definition, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.definitionID)
	if err != nil {
		return nil, err
	}
	workflow, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.workflowID)
	if err != nil {
		return nil, err
	}
	input, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.inputID)
	if err != nil {
		return nil, err
	}
	output, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.outputID)
	if err != nil {
		return nil, err
	}
	evaluation, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.evaluationID)
	if err != nil {
		return nil, err
	}
	value := &agentv1.AgentDefinition{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project,
		DisplayName: row.displayName, SemanticVersion: row.semanticVersion, State: agentv1.AgentDefinitionState(row.state), Purpose: row.purpose,
		Definition: definition, WorkflowDefinition: workflow, InputSchema: input, OutputSchema: output, ModelCapability: row.modelCapability, EvaluationSuite: evaluation,
		Budget:             &agentv1.AgentBudgetEnvelope{MaximumModelTokens: uint64(row.maxModelTokens), MaximumIterations: uint32(row.maxIterations), MaximumToolCalls: uint32(row.maxToolCalls), MaximumConcurrentBranches: uint32(row.maxBranches), MaximumStorageBytes: uint64(row.maxStorageBytes), MaximumExternalSpendMicros: uint64(row.maxSpend), MaximumWallTime: &durationpb.Duration{Seconds: row.wallSeconds, Nanos: row.wallNanos}, MaximumAcceleratorTime: &durationpb.Duration{Seconds: row.acceleratorSeconds, Nanos: row.acceleratorNanos}, MaximumCpuTime: &durationpb.Duration{Seconds: row.cpuSeconds, Nanos: row.cpuNanos}}, //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
		Limits:             &agentv1.AgentExecutionLimits{MaximumDepth: uint32(row.maxDepth), MaximumFanOut: uint32(row.maxFanOut), MaximumObservationsPerStep: uint32(row.maxObservations), MaximumArtifactReferencesPerCall: uint32(row.maxArtifacts)},                                                                                                                                                                                                                                                                                                                                                                                          //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
		QualificationLevel: row.qualificationLevel, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()),
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	rows, err := tx.QueryContext(ctx, `SELECT non_goal FROM agent_definition_non_goals WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var item string
		if err = rows.Scan(&item); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.NonGoals = append(value.NonGoals, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	toolRows, err := tx.QueryContext(ctx, `SELECT resource_ref_id FROM agent_definition_tools WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var toolIDs []int64
	for toolRows.Next() {
		var id int64
		if err = toolRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(toolRows)
			return nil, err
		}
		toolIDs = append(toolIDs, id)
	}
	if err = toolRows.Err(); err != nil {
		_ = platformdb.CloseRows(toolRows)
		return nil, err
	}
	if err = platformdb.CloseRows(toolRows); err != nil {
		return nil, err
	}
	for _, id := range toolIDs {
		item, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.EligibleTools = append(value.EligibleTools, item)
	}
	policyRows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM agent_definition_policies WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var policyIDs []int64
	for policyRows.Next() {
		var id int64
		if err = policyRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(policyRows)
			return nil, err
		}
		policyIDs = append(policyIDs, id)
	}
	if err = policyRows.Err(); err != nil {
		_ = platformdb.CloseRows(policyRows)
		return nil, err
	}
	if err = platformdb.CloseRows(policyRows); err != nil {
		return nil, err
	}
	for _, id := range policyIDs {
		item, loadErr := workflowapp.LoadPolicySnapshot(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, item)
	}
	return value, nil
}

func storeDefinitionChildren(ctx context.Context, tx *sql.Tx, identity Identity, name string, value *agentv1.AgentDefinition) error {
	for ordinal, item := range value.GetNonGoals() {
		if _, err := tx.ExecContext(ctx, `INSERT INTO agent_definition_non_goals(tenant_id,project_id,definition_name,ordinal,non_goal) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, item); err != nil {
			return err
		}
	}
	for ordinal, item := range value.GetEligibleTools() {
		id, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, item)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO agent_definition_tools(tenant_id,project_id,definition_name,ordinal,resource_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); err != nil {
			return err
		}
	}
	for ordinal, item := range value.GetPolicySnapshots() {
		id, err := workflowapp.StorePolicySnapshot(ctx, tx, identity.TenantID, item)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO agent_definition_policies(tenant_id,project_id,definition_name,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); err != nil {
			return err
		}
	}
	return nil
}

type runRow struct {
	tenant, project, name, uid, etag, definitionDigest, activeStep, attemptID string
	operationID, jobID, schedulerRunID                                        string
	revision, leaseEpoch                                                      int64
	definitionID, workflowRunID, inputID, providerID, budgetReservationID     sql.NullInt64
	runManifestID, outputID, failureID                                        sql.NullInt64
	modelTokens, iterations, toolCalls, storageBytes, spend                   int64
	acceleratorMillis, cpuMillis, nextSequence                                int64
	state                                                                     int32
	cancellation                                                              bool
	created, updated                                                          time.Time
	ended                                                                     sql.NullTime
}

const runColumns = `tenant_id,project_id,name,uid,revision,etag,definition_ref_id,definition_digest,workflow_run_ref_id,input_ref_id,model_provider_manifest_ref_id,budget_reservation_ref_id,usage_model_tokens,usage_iterations,usage_tool_calls,usage_storage_bytes,usage_external_spend_micros,usage_accelerator_milliseconds,usage_cpu_milliseconds,state,active_step_name,next_step_sequence,attempt_id,lease_epoch,cancellation_requested,run_manifest_ref_id,output_ref_id,failure_detail_id,create_time,update_time,end_time,operation_id,job_id,scheduler_run_id`

func scanRun(row scanner) (runRow, error) {
	var value runRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.definitionID, &value.definitionDigest, &value.workflowRunID, &value.inputID, &value.providerID, &value.budgetReservationID, &value.modelTokens, &value.iterations, &value.toolCalls, &value.storageBytes, &value.spend, &value.acceleratorMillis, &value.cpuMillis, &value.state, &value.activeStep, &value.nextSequence, &value.attemptID, &value.leaseEpoch, &value.cancellation, &value.runManifestID, &value.outputID, &value.failureID, &value.created, &value.updated, &value.ended, &value.operationID, &value.jobID, &value.schedulerRunID)
	return value, err
}

func runProto(ctx context.Context, tx *sql.Tx, row runRow) (*agentv1.AgentRun, error) {
	definition, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.definitionID)
	if err != nil {
		return nil, err
	}
	workflow, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.workflowRunID)
	if err != nil {
		return nil, err
	}
	input, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.inputID)
	if err != nil {
		return nil, err
	}
	provider, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.providerID)
	if err != nil {
		return nil, err
	}
	budget, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.budgetReservationID)
	if err != nil {
		return nil, err
	}
	manifest, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.runManifestID)
	if err != nil {
		return nil, err
	}
	output, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.outputID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.failureID)
	if err != nil {
		return nil, err
	}
	value := &agentv1.AgentRun{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project, Definition: definition, DefinitionDigest: row.definitionDigest, WorkflowRun: workflow, Input: input, ModelProviderManifest: provider, BudgetReservation: budget, BudgetUsage: &agentv1.AgentBudgetUsage{ModelTokens: uint64(row.modelTokens), Iterations: uint32(row.iterations), ToolCalls: uint32(row.toolCalls), StorageBytes: uint64(row.storageBytes), ExternalSpendMicros: uint64(row.spend), AcceleratorMilliseconds: uint64(row.acceleratorMillis), CpuMilliseconds: uint64(row.cpuMillis)}, State: agentv1.AgentRunState(row.state), ActiveStepName: row.activeStep, NextStepSequence: uint64(row.nextSequence), AttemptId: row.attemptID, LeaseEpoch: uint64(row.leaseEpoch), CancellationRequested: row.cancellation, RunManifest: manifest, Output: output, Failure: failure, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC())} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	if row.ended.Valid {
		value.EndTime = timestamppb.New(row.ended.Time.UTC())
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM agent_run_policies WHERE tenant_id=$1 AND project_id=$2 AND agent_run_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	for _, id := range ids {
		item, loadErr := workflowapp.LoadPolicySnapshot(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, item)
	}
	return value, nil
}

func storeRunPolicies(ctx context.Context, tx *sql.Tx, identity Identity, name string, values []*policyv1.PolicyReference) error {
	for ordinal, item := range values {
		id, err := workflowapp.StorePolicySnapshot(ctx, tx, identity.TenantID, item)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO agent_run_policies(tenant_id,project_id,agent_run_name,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); err != nil {
			return err
		}
	}
	return nil
}

type stepRow struct {
	tenant, project, name, uid, runName, etag, attemptID string
	runRefID, outputID, failureID                        sql.NullInt64
	sequence, revision, leaseEpoch                       int64
	kind, state                                          int32
	created, updated                                     time.Time
	ended                                                sql.NullTime
}

const stepColumns = `tenant_id,project_id,name,uid,agent_run_name,run_ref_id,sequence,revision,etag,kind,state,attempt_id,lease_epoch,output_ref_id,failure_detail_id,create_time,update_time,end_time`

func scanStep(row scanner) (stepRow, error) {
	var value stepRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.runName, &value.runRefID, &value.sequence, &value.revision, &value.etag, &value.kind, &value.state, &value.attemptID, &value.leaseEpoch, &value.outputID, &value.failureID, &value.created, &value.updated, &value.ended)
	return value, err
}

func stepProto(ctx context.Context, tx *sql.Tx, row stepRow) (*agentv1.AgentStep, error) {
	run, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.runRefID)
	if err != nil {
		return nil, err
	}
	output, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.outputID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.failureID)
	if err != nil {
		return nil, err
	}
	value := &agentv1.AgentStep{Name: row.name, Uid: row.uid, Run: run, Sequence: uint64(row.sequence), Revision: row.revision, Etag: row.etag, Kind: agentv1.AgentStepKind(row.kind), State: agentv1.AgentStepState(row.state), AttemptId: row.attemptID, LeaseEpoch: uint64(row.leaseEpoch), Output: output, Failure: failure, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC())} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	if row.ended.Valid {
		value.EndTime = timestamppb.New(row.ended.Time.UTC())
	}
	decisionRows, err := tx.QueryContext(ctx, `SELECT authorization_decision_id FROM agent_step_policy_decisions WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var decisionIDs []int64
	for decisionRows.Next() {
		var id int64
		if err = decisionRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(decisionRows)
			return nil, err
		}
		decisionIDs = append(decisionIDs, id)
	}
	if err = decisionRows.Err(); err != nil {
		_ = platformdb.CloseRows(decisionRows)
		return nil, err
	}
	if err = platformdb.CloseRows(decisionRows); err != nil {
		return nil, err
	}
	for _, id := range decisionIDs {
		item, loadErr := workflowapp.LoadAuthorizationDecision(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicyDecisions = append(value.PolicyDecisions, item)
	}
	observationRows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM agent_step_observations WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var observationIDs []int64
	for observationRows.Next() {
		var id int64
		if err = observationRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(observationRows)
			return nil, err
		}
		observationIDs = append(observationIDs, id)
	}
	if err = observationRows.Err(); err != nil {
		_ = platformdb.CloseRows(observationRows)
		return nil, err
	}
	if err = platformdb.CloseRows(observationRows); err != nil {
		return nil, err
	}
	for _, id := range observationIDs {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.Observations = append(value.Observations, item)
	}
	value.Decision, err = loadAgentDecision(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	return value, nil
}

func loadAgentDecision(ctx context.Context, tx *sql.Tx, row stepRow) (*agentv1.AgentDecision, error) {
	var id, kind, decisionType, rationale, waitCorrelation, replay string
	var domainID, approvalID, terminalID sql.NullInt64
	var waitSeconds sql.NullInt64
	var waitNanos sql.NullInt32
	err := tx.QueryRowContext(ctx, `SELECT decision_id,decision_type,rationale_summary,next_action_kind,domain_job_ref_id,approval_request_ref_id,wait_maximum_duration_seconds,wait_maximum_duration_nanos,wait_correlation_ref,terminal_result_ref_id,replay_digest FROM agent_step_decisions WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3`, row.tenant, row.project, row.name).Scan(&id, &decisionType, &rationale, &kind, &domainID, &approvalID, &waitSeconds, &waitNanos, &waitCorrelation, &terminalID, &replay)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	value := &agentv1.AgentDecision{DecisionId: id, DecisionType: decisionType, RationaleSummary: rationale, ReplayDigest: replay}
	switch kind {
	case "TOOL":
		call, loadErr := loadToolCall(ctx, tx, row)
		if loadErr != nil {
			return nil, loadErr
		}
		value.NextAction = &agentv1.AgentDecision_ToolCall{ToolCall: call}
	case "DOMAIN_JOB":
		item, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, domainID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.NextAction = &agentv1.AgentDecision_DomainJob{DomainJob: item}
	case "APPROVAL":
		item, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, approvalID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.NextAction = &agentv1.AgentDecision_ApprovalRequest{ApprovalRequest: item}
	case "WAIT":
		if !waitSeconds.Valid || !waitNanos.Valid {
			return nil, ErrInvalidTransition
		}
		value.NextAction = &agentv1.AgentDecision_Wait{Wait: &agentv1.AgentWait{MaximumDuration: &durationpb.Duration{Seconds: waitSeconds.Int64, Nanos: waitNanos.Int32}, CorrelationRef: waitCorrelation}}
	case "TERMINAL":
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, terminalID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.NextAction = &agentv1.AgentDecision_TerminalResult{TerminalResult: item}
	default:
		return nil, ErrInvalidTransition
	}
	rows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM agent_decision_evidence WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	for _, itemID := range ids {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: itemID, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.Evidence = append(value.Evidence, item)
	}
	return value, nil
}

func loadToolCall(ctx context.Context, tx *sql.Tx, row stepRow) (*agentv1.ToolCall, error) {
	value := new(agentv1.ToolCall)
	value.Context = new(commonv1.CommandContext)
	var toolID, authID, parametersID, budgetID, schemaID sql.NullInt64
	var deadline time.Time
	var contextDeadline sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT context_request_id,context_idempotency_key,context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,context_correlation_id,context_causation_id,context_cancellation_token_id,call_id,agent_run_name,declared_agent_step_name,tool_ref_id,tool_version,authorization_decision_id,input_digest,parameters_ref_id,deadline,budget_reservation_ref_id,expected_output_schema_ref_id,side_effect_class,output_classification FROM agent_tool_calls WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3`, row.tenant, row.project, row.name).Scan(&value.Context.RequestId, &value.Context.IdempotencyKey, &value.Context.PrincipalId, &value.Context.TraceId, &contextDeadline, &value.Context.CanonicalRequestDigest, &value.Context.CorrelationId, &value.Context.CausationId, &value.Context.CancellationTokenId, &value.CallId, &value.AgentRunName, &value.AgentStepName, &toolID, &value.ToolVersion, &authID, &value.InputDigest, &parametersID, &deadline, &budgetID, &schemaID, &value.SideEffectClass, &value.OutputClassification)
	if err != nil {
		return nil, err
	}
	value.Context.TenantId = row.tenant
	value.Context.ProjectId = row.project
	if contextDeadline.Valid {
		value.Context.Deadline = timestamppb.New(contextDeadline.Time.UTC())
	}
	value.Deadline = timestamppb.New(deadline.UTC())
	value.Tool, err = platformdb.LoadResourceRef(ctx, tx, row.tenant, toolID)
	if err != nil {
		return nil, err
	}
	value.Authorization, err = workflowapp.LoadAuthorizationDecision(ctx, tx, row.tenant, authID.Int64)
	if err != nil {
		return nil, err
	}
	value.Parameters, err = platformdb.LoadArtifactRef(ctx, tx, row.tenant, parametersID)
	if err != nil {
		return nil, err
	}
	value.BudgetReservation, err = platformdb.LoadResourceRef(ctx, tx, row.tenant, budgetID)
	if err != nil {
		return nil, err
	}
	value.ExpectedOutputSchema, err = platformdb.LoadArtifactRef(ctx, tx, row.tenant, schemaID)
	if err != nil {
		return nil, err
	}
	approvalRows, err := tx.QueryContext(ctx, `SELECT approval_receipt_name FROM agent_tool_call_approvals WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var names []string
	for approvalRows.Next() {
		var name string
		if err = approvalRows.Scan(&name); err != nil {
			_ = platformdb.CloseRows(approvalRows)
			return nil, err
		}
		names = append(names, name)
	}
	if err = approvalRows.Err(); err != nil {
		_ = platformdb.CloseRows(approvalRows)
		return nil, err
	}
	if err = platformdb.CloseRows(approvalRows); err != nil {
		return nil, err
	}
	for _, name := range names {
		item, loadErr := workflowapp.LoadApprovalReceipt(ctx, tx, row.tenant, row.project, name, false)
		if loadErr != nil {
			return nil, loadErr
		}
		value.Approvals = append(value.Approvals, item)
	}
	inputRows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM agent_tool_call_inputs WHERE tenant_id=$1 AND project_id=$2 AND agent_step_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for inputRows.Next() {
		var id int64
		if err = inputRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(inputRows)
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = inputRows.Err(); err != nil {
		_ = platformdb.CloseRows(inputRows)
		return nil, err
	}
	if err = platformdb.CloseRows(inputRows); err != nil {
		return nil, err
	}
	for _, id := range ids {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.InputArtifacts = append(value.InputArtifacts, item)
	}
	return value, nil
}

func storeStep(ctx context.Context, tx *sql.Tx, identity Identity, value *agentv1.AgentStep) error {
	runID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetRun())
	if err != nil {
		return err
	}
	outputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetOutput())
	if err != nil {
		return err
	}
	failureID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, value.GetFailure())
	if err != nil {
		return err
	}
	var end any
	if value.GetEndTime() != nil {
		end = value.GetEndTime().AsTime().UTC()
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO agent_steps(tenant_id,project_id,name,uid,agent_run_name,run_ref_id,sequence,revision,etag,kind,state,attempt_id,lease_epoch,output_ref_id,failure_detail_id,create_time,update_time,end_time) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)`, identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), value.GetRun().GetName(), runID, value.GetSequence(), value.GetRevision(), value.GetEtag(), int32(value.GetKind()), int32(value.GetState()), value.GetAttemptId(), value.GetLeaseEpoch(), outputID, failureID, value.GetCreateTime().AsTime().UTC(), value.GetUpdateTime().AsTime().UTC(), end); err != nil {
		return err
	}
	for ordinal, item := range value.GetPolicyDecisions() {
		id, storeErr := workflowapp.StoreAuthorizationDecision(ctx, tx, workflowIdentity(identity), item)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO agent_step_policy_decisions(tenant_id,project_id,agent_step_name,ordinal,authorization_decision_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	for ordinal, item := range value.GetObservations() {
		id, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, item)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO agent_step_observations(tenant_id,project_id,agent_step_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	return storeAgentDecision(ctx, tx, identity, value.GetName(), value.GetDecision())
}

func storeAgentDecision(ctx context.Context, tx *sql.Tx, identity Identity, step string, value *agentv1.AgentDecision) error {
	var kind string
	var domainID, approvalID, terminalID sql.NullInt64
	var waitSeconds sql.NullInt64
	var waitNanos sql.NullInt32
	var waitCorrelation string
	switch action := value.GetNextAction().(type) {
	case *agentv1.AgentDecision_ToolCall:
		kind = "TOOL"
	case *agentv1.AgentDecision_DomainJob:
		kind = "DOMAIN_JOB"
		id, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, action.DomainJob)
		if err != nil {
			return err
		}
		domainID = id
	case *agentv1.AgentDecision_ApprovalRequest:
		kind = "APPROVAL"
		id, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, action.ApprovalRequest)
		if err != nil {
			return err
		}
		approvalID = id
	case *agentv1.AgentDecision_Wait:
		kind = "WAIT"
		waitSeconds = sql.NullInt64{Int64: action.Wait.GetMaximumDuration().GetSeconds(), Valid: true}
		waitNanos = sql.NullInt32{Int32: action.Wait.GetMaximumDuration().GetNanos(), Valid: true}
		waitCorrelation = action.Wait.GetCorrelationRef()
	case *agentv1.AgentDecision_TerminalResult:
		kind = "TERMINAL"
		id, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, action.TerminalResult)
		if err != nil {
			return err
		}
		terminalID = id
	default:
		return ErrInvalidArgument
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO agent_step_decisions(tenant_id,project_id,agent_step_name,decision_id,decision_type,rationale_summary,next_action_kind,domain_job_ref_id,approval_request_ref_id,wait_maximum_duration_seconds,wait_maximum_duration_nanos,wait_correlation_ref,terminal_result_ref_id,replay_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, identity.TenantID, identity.ProjectID, step, value.GetDecisionId(), value.GetDecisionType(), value.GetRationaleSummary(), kind, domainID, approvalID, waitSeconds, waitNanos, waitCorrelation, terminalID, value.GetReplayDigest()); err != nil {
		return err
	}
	for ordinal, item := range value.GetEvidence() {
		id, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, item)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO agent_decision_evidence(tenant_id,project_id,agent_step_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, step, ordinal, id); err != nil {
			return err
		}
	}
	if call := value.GetToolCall(); call != nil {
		return storeToolCall(ctx, tx, identity, step, call)
	}
	return nil
}

func storeToolCall(ctx context.Context, tx *sql.Tx, identity Identity, step string, value *agentv1.ToolCall) error {
	toolID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetTool())
	if err != nil {
		return err
	}
	authID, err := workflowapp.StoreAuthorizationDecision(ctx, tx, workflowIdentity(identity), value.GetAuthorization())
	if err != nil {
		return err
	}
	parametersID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetParameters())
	if err != nil {
		return err
	}
	budgetID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetBudgetReservation())
	if err != nil {
		return err
	}
	schemaID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetExpectedOutputSchema())
	if err != nil {
		return err
	}
	var contextDeadline any
	if value.GetContext().GetDeadline() != nil {
		contextDeadline = value.GetContext().GetDeadline().AsTime().UTC()
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO agent_tool_calls(tenant_id,project_id,agent_step_name,context_request_id,context_idempotency_key,context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,context_correlation_id,context_causation_id,context_cancellation_token_id,call_id,agent_run_name,declared_agent_step_name,tool_ref_id,tool_version,authorization_decision_id,input_digest,parameters_ref_id,deadline,budget_reservation_ref_id,expected_output_schema_ref_id,side_effect_class,output_classification) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25)`, identity.TenantID, identity.ProjectID, step, value.GetContext().GetRequestId(), value.GetContext().GetIdempotencyKey(), value.GetContext().GetPrincipalId(), value.GetContext().GetTraceId(), contextDeadline, value.GetContext().GetCanonicalRequestDigest(), value.GetContext().GetCorrelationId(), value.GetContext().GetCausationId(), value.GetContext().GetCancellationTokenId(), value.GetCallId(), value.GetAgentRunName(), value.GetAgentStepName(), toolID, value.GetToolVersion(), authID, value.GetInputDigest(), parametersID, value.GetDeadline().AsTime().UTC(), budgetID, schemaID, value.GetSideEffectClass(), value.GetOutputClassification()); err != nil {
		return err
	}
	for ordinal, item := range value.GetApprovals() {
		stored, loadErr := workflowapp.LoadApprovalReceipt(ctx, tx, identity.TenantID, identity.ProjectID, item.GetName(), true)
		if loadErr != nil {
			return loadErr
		}
		if !proto.Equal(stored, item) {
			return ErrInvalidArgument
		}
		if _, loadErr = tx.ExecContext(ctx, `INSERT INTO agent_tool_call_approvals(tenant_id,project_id,agent_step_name,ordinal,approval_receipt_name) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, step, ordinal, item.GetName()); loadErr != nil {
			return loadErr
		}
	}
	for ordinal, item := range value.GetInputArtifacts() {
		id, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, item)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO agent_tool_call_inputs(tenant_id,project_id,agent_step_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, step, ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	return nil
}

type receiptRow struct {
	tenant, project, name, uid, callID, runName, stepName, toolVersion, attemptID, idempotencyKey, inputDigest, schemaDigest, outputDigest, executor, sourceRevision, receiptDigest string
	toolID, authID, reconciliationID, failureID                                                                                                                                     sql.NullInt64
	leaseEpoch                                                                                                                                                                      int64
	outcome, sideEffect                                                                                                                                                             int32
	inputBytes, outputBytes, cpuMillis, acceleratorMillis, spend                                                                                                                    int64
	started, completed                                                                                                                                                              time.Time
}

const receiptColumns = `tenant_id,project_id,name,uid,call_id,agent_run_name,agent_step_name,tool_ref_id,tool_version,attempt_id,lease_epoch,authorization_decision_id,idempotency_key,input_digest,expected_output_schema_digest,outcome,side_effect_state,output_digest,reconciliation_evidence_ref_id,failure_detail_id,usage_input_bytes,usage_output_bytes,usage_cpu_milliseconds,usage_accelerator_milliseconds,usage_external_spend_micros,started_at,completed_at,executor_identity,source_revision,receipt_digest`

func scanReceipt(row scanner) (receiptRow, error) {
	var value receiptRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.callID, &value.runName, &value.stepName, &value.toolID, &value.toolVersion, &value.attemptID, &value.leaseEpoch, &value.authID, &value.idempotencyKey, &value.inputDigest, &value.schemaDigest, &value.outcome, &value.sideEffect, &value.outputDigest, &value.reconciliationID, &value.failureID, &value.inputBytes, &value.outputBytes, &value.cpuMillis, &value.acceleratorMillis, &value.spend, &value.started, &value.completed, &value.executor, &value.sourceRevision, &value.receiptDigest)
	return value, err
}

func receiptProto(ctx context.Context, tx *sql.Tx, row receiptRow) (*agentv1.ToolReceipt, error) {
	tool, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.toolID)
	if err != nil {
		return nil, err
	}
	auth, err := workflowapp.LoadAuthorizationDecision(ctx, tx, row.tenant, row.authID.Int64)
	if err != nil {
		return nil, err
	}
	reconciliation, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.reconciliationID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.failureID)
	if err != nil {
		return nil, err
	}
	value := &agentv1.ToolReceipt{Name: row.name, Uid: row.uid, CallId: row.callID, AgentRunName: row.runName, AgentStepName: row.stepName, Tool: tool, ToolVersion: row.toolVersion, AttemptId: row.attemptID, LeaseEpoch: uint64(row.leaseEpoch), Authorization: auth, IdempotencyKey: row.idempotencyKey, InputDigest: row.inputDigest, ExpectedOutputSchemaDigest: row.schemaDigest, Outcome: agentv1.ToolExecutionOutcome(row.outcome), SideEffectState: agentv1.ToolSideEffectState(row.sideEffect), OutputDigest: row.outputDigest, ReconciliationEvidence: reconciliation, Failure: failure, Usage: &agentv1.ToolResourceUsage{InputBytes: uint64(row.inputBytes), OutputBytes: uint64(row.outputBytes), CpuMilliseconds: uint64(row.cpuMillis), AcceleratorMilliseconds: uint64(row.acceleratorMillis), ExternalSpendMicros: uint64(row.spend)}, StartedAt: timestamppb.New(row.started.UTC()), CompletedAt: timestamppb.New(row.completed.UTC()), ExecutorIdentity: row.executor, SourceRevision: row.sourceRevision, ReceiptDigest: row.receiptDigest} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	approvalRows, err := tx.QueryContext(ctx, `SELECT resource_ref_id FROM agent_tool_receipt_approvals WHERE tenant_id=$1 AND project_id=$2 AND tool_receipt_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var approvalIDs []int64
	for approvalRows.Next() {
		var id int64
		if err = approvalRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(approvalRows)
			return nil, err
		}
		approvalIDs = append(approvalIDs, id)
	}
	if err = approvalRows.Err(); err != nil {
		_ = platformdb.CloseRows(approvalRows)
		return nil, err
	}
	if err = platformdb.CloseRows(approvalRows); err != nil {
		return nil, err
	}
	for _, id := range approvalIDs {
		item, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.ApprovalReceipts = append(value.ApprovalReceipts, item)
	}
	outputRows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM agent_tool_receipt_outputs WHERE tenant_id=$1 AND project_id=$2 AND tool_receipt_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	var outputIDs []int64
	for outputRows.Next() {
		var id int64
		if err = outputRows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(outputRows)
			return nil, err
		}
		outputIDs = append(outputIDs, id)
	}
	if err = outputRows.Err(); err != nil {
		_ = platformdb.CloseRows(outputRows)
		return nil, err
	}
	if err = platformdb.CloseRows(outputRows); err != nil {
		return nil, err
	}
	for _, id := range outputIDs {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.Outputs = append(value.Outputs, item)
	}
	return value, nil
}

func storeToolReceipt(ctx context.Context, tx *sql.Tx, identity Identity, value *agentv1.ToolReceipt) error {
	toolID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetTool())
	if err != nil {
		return err
	}
	authID, err := workflowapp.StoreAuthorizationDecision(ctx, tx, workflowIdentity(identity), value.GetAuthorization())
	if err != nil {
		return err
	}
	reconciliationID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, value.GetReconciliationEvidence())
	if err != nil {
		return err
	}
	failureID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, value.GetFailure())
	if err != nil {
		return err
	}
	usage := value.GetUsage()
	if _, err = tx.ExecContext(ctx, `INSERT INTO agent_tool_receipts(tenant_id,project_id,name,uid,call_id,agent_run_name,agent_step_name,tool_ref_id,tool_version,attempt_id,lease_epoch,authorization_decision_id,idempotency_key,input_digest,expected_output_schema_digest,outcome,side_effect_state,output_digest,reconciliation_evidence_ref_id,failure_detail_id,usage_input_bytes,usage_output_bytes,usage_cpu_milliseconds,usage_accelerator_milliseconds,usage_external_spend_micros,started_at,completed_at,executor_identity,source_revision,receipt_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30)`, identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), value.GetCallId(), value.GetAgentRunName(), value.GetAgentStepName(), toolID, value.GetToolVersion(), value.GetAttemptId(), value.GetLeaseEpoch(), authID, value.GetIdempotencyKey(), value.GetInputDigest(), value.GetExpectedOutputSchemaDigest(), int32(value.GetOutcome()), int32(value.GetSideEffectState()), value.GetOutputDigest(), reconciliationID, failureID, usage.GetInputBytes(), usage.GetOutputBytes(), usage.GetCpuMilliseconds(), usage.GetAcceleratorMilliseconds(), usage.GetExternalSpendMicros(), value.GetStartedAt().AsTime().UTC(), value.GetCompletedAt().AsTime().UTC(), value.GetExecutorIdentity(), value.GetSourceRevision(), value.GetReceiptDigest()); err != nil {
		return err
	}
	for ordinal, item := range value.GetApprovalReceipts() {
		id, storeErr := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, item)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO agent_tool_receipt_approvals(tenant_id,project_id,tool_receipt_name,ordinal,resource_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	for ordinal, item := range value.GetOutputs() {
		id, storeErr := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, item)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO agent_tool_receipt_outputs(tenant_id,project_id,tool_receipt_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); storeErr != nil {
			return storeErr
		}
	}
	return nil
}
