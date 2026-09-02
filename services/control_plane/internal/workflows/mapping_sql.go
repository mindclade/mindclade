package workflows

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

type scanner interface{ Scan(...any) error }

func advisoryLockKey(parts ...string) string {
	var result strings.Builder
	for _, part := range parts {
		_, _ = fmt.Fprintf(&result, "%d:", len(part))
		result.WriteString(part)
	}
	return result.String()
}

func nullableTime(value *timestamppb.Timestamp) (sql.NullTime, error) {
	if value == nil {
		return sql.NullTime{}, nil
	}
	if err := value.CheckValid(); err != nil {
		return sql.NullTime{}, err
	}
	result := value.AsTime().UTC()
	if result.Nanosecond()%int(time.Microsecond) != 0 {
		return sql.NullTime{}, fmt.Errorf("%w: timestamp exceeds PostgreSQL microsecond precision", ErrInvalidArgument)
	}
	return sql.NullTime{Time: result, Valid: true}, nil
}

func timestamp(value sql.NullTime) *timestamppb.Timestamp {
	if !value.Valid {
		return nil
	}
	return timestamppb.New(value.Time.UTC())
}

func requireTimestamp(value *timestamppb.Timestamp, label string) (time.Time, error) {
	if value == nil || value.CheckValid() != nil {
		return time.Time{}, fmt.Errorf("%w: %s timestamp is required", ErrInvalidArgument, label)
	}
	result := value.AsTime().UTC()
	if result.Nanosecond()%int(time.Microsecond) != 0 {
		return time.Time{}, fmt.Errorf("%w: %s timestamp exceeds PostgreSQL microsecond precision", ErrInvalidArgument, label)
	}
	return result, nil
}

func durationParts(value *durationpb.Duration, required bool) (int64, int32, error) {
	if value == nil {
		if required {
			return 0, 0, ErrInvalidArgument
		}
		return 0, 0, nil
	}
	if value.CheckValid() != nil || value.AsDuration() < 0 || required && value.AsDuration() == 0 {
		return 0, 0, ErrInvalidArgument
	}
	return value.GetSeconds(), value.GetNanos(), nil
}

// StorePolicySnapshot and LoadPolicySnapshot are exported for the agent
// persistence package, which depends on workflow/approval contracts. They
// preserve the exact generated value through normalized shared tables.
func StorePolicySnapshot(ctx context.Context, tx *sql.Tx, tenantID string, value *policyv1.PolicyReference) (int64, error) {
	if err := validatePolicy(value); err != nil {
		return 0, err
	}
	lockKey := advisoryLockKey(tenantID, "policy-snapshot", value.GetName(), strconv.FormatInt(value.GetResourceRevision(), 10), value.GetDigest())
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lockKey); err != nil {
		return 0, err
	}
	var id int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, tenantID, value.GetName(), value.GetResourceRevision(), value.GetDigest()).Scan(&id)
	if err == nil {
		persisted, loadErr := LoadPolicySnapshot(ctx, tx, tenantID, id)
		if loadErr != nil {
			return 0, loadErr
		}
		if !proto.Equal(persisted, value) {
			return 0, ErrIdempotencyConflict
		}
		return id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	documentID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetDocument())
	if err != nil {
		return 0, err
	}
	effective, err := requireTimestamp(value.GetEffectiveTime(), "policy effective")
	if err != nil {
		return 0, err
	}
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	err = tx.QueryRowContext(ctx, `INSERT INTO policy_snapshot_references(tenant_id,name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`, tenantID, value.GetName(), value.GetUid(), value.GetPolicyType(), value.GetVersion(), value.GetDigest(), documentID, value.GetResourceRevision(), effective, expiry, value.GetClassification()).Scan(&id)
	return id, err
}

func LoadPolicySnapshot(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.PolicyReference, error) {
	var value policyv1.PolicyReference
	var documentID int64
	var effective time.Time
	var expiry sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification FROM policy_snapshot_references WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&value.Name, &value.Uid, &value.PolicyType, &value.Version, &value.Digest, &documentID, &value.ResourceRevision, &effective, &expiry, &value.Classification)
	if err != nil {
		return nil, err
	}
	value.Document, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, sql.NullInt64{Int64: documentID, Valid: true})
	if err != nil {
		return nil, err
	}
	value.EffectiveTime, value.ExpireTime = timestamppb.New(effective.UTC()), timestamp(expiry)
	return &value, nil
}

func StoreAuthorizationDecision(ctx context.Context, tx *sql.Tx, identity Identity, value *policyv1.AuthorizationDecision) (int64, error) {
	if err := validateAuthorization(identity, value, true); err != nil {
		return 0, err
	}
	lockKey := advisoryLockKey(identity.TenantID, "authorization-decision", value.GetName())
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lockKey); err != nil {
		return 0, err
	}
	var id int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM authorization_decisions WHERE tenant_id=$1 AND name=$2`, identity.TenantID, value.GetName()).Scan(&id)
	if err == nil {
		persisted, loadErr := LoadAuthorizationDecision(ctx, tx, identity.TenantID, id)
		if loadErr != nil {
			return 0, loadErr
		}
		if !proto.Equal(persisted, value) {
			return 0, ErrIdempotencyConflict
		}
		return id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	evaluated, err := requireTimestamp(value.GetEvaluatedAt(), "authorization evaluated_at")
	if err != nil {
		return 0, err
	}
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetResource())
	if err != nil {
		return 0, err
	}
	err = tx.QueryRowContext(ctx, `INSERT INTO authorization_decisions(tenant_id,name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) RETURNING id`, identity.TenantID, value.GetName(), value.GetUid(), identity.ProjectID, value.GetPrincipalRef(), value.GetAction(), resourceID, value.GetIntentDigest(), int32(value.GetOutcome()), value.GetReasonCode(), value.GetSafeReason(), evaluated, expiry, value.GetContextDigest(), value.GetDecisionDigest()).Scan(&id)
	if err != nil {
		return 0, err
	}
	for ordinal, policy := range value.GetPolicies() {
		policyID, storeErr := StorePolicySnapshot(ctx, tx, identity.TenantID, policy)
		if storeErr != nil {
			return 0, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO authorization_decision_policies(tenant_id,decision_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4)`, identity.TenantID, id, ordinal, policyID); storeErr != nil {
			return 0, storeErr
		}
	}
	for ordinal, constraint := range value.GetConstraints() {
		if constraint == nil || constraint.GetKind() == "" || !validSHA256(constraint.GetDetailsDigest()) {
			return 0, ErrInvalidArgument
		}
		constraintExpiry, expiryErr := nullableTime(constraint.GetExpireTime())
		if expiryErr != nil {
			return 0, expiryErr
		}
		if _, storeErr := tx.ExecContext(ctx, `INSERT INTO authorization_decision_constraints(tenant_id,decision_id,ordinal,constraint_kind,details_digest,expire_time) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, id, ordinal, constraint.GetKind(), constraint.GetDetailsDigest(), constraintExpiry); storeErr != nil {
			return 0, storeErr
		}
	}
	return id, nil
}

func LoadAuthorizationDecision(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.AuthorizationDecision, error) {
	var value policyv1.AuthorizationDecision
	var resourceID int64
	var outcome int32
	var evaluated time.Time
	var expiry sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest FROM authorization_decisions WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&value.Name, &value.Uid, &value.ProjectId, &value.PrincipalRef, &value.Action, &resourceID, &value.IntentDigest, &outcome, &value.ReasonCode, &value.SafeReason, &evaluated, &expiry, &value.ContextDigest, &value.DecisionDigest)
	if err != nil {
		return nil, err
	}
	value.TenantId, value.Outcome, value.EvaluatedAt, value.ExpireTime = tenantID, policyv1.AuthorizationOutcome(outcome), timestamppb.New(evaluated.UTC()), timestamp(expiry)
	value.Resource, err = platformdb.LoadResourceRef(ctx, tx, tenantID, sql.NullInt64{Int64: resourceID, Valid: true})
	if err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM authorization_decision_policies WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, id) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var policyIDs []int64
	for rows.Next() {
		var policyID int64
		if err = rows.Scan(&policyID); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		policyIDs = append(policyIDs, policyID)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, policyID := range policyIDs {
		policy, loadErr := LoadPolicySnapshot(ctx, tx, tenantID, policyID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.Policies = append(value.Policies, policy)
	}
	rows, err = tx.QueryContext(ctx, `SELECT constraint_kind,details_digest,expire_time FROM authorization_decision_constraints WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, id) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var constraint policyv1.AuthorizationConstraint
		var constraintExpiry sql.NullTime
		if err = rows.Scan(&constraint.Kind, &constraint.DetailsDigest, &constraintExpiry); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		constraint.ExpireTime = timestamp(constraintExpiry)
		value.Constraints = append(value.Constraints, &constraint)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	return &value, rows.Err()
}

type definitionRow struct {
	tenant, project, name, uid, etag, displayName, semanticVersion, graphDigest string
	revision                                                                    int64
	state                                                                       int32
	definitionID                                                                int64
	maximumIterations, maximumFanOut, maximumParallel                           int64
	wallSeconds                                                                 int64
	wallNanos                                                                   int32
	inputSchemaID, outputSchemaID                                               sql.NullInt64
	created, updated                                                            time.Time
	deleted                                                                     sql.NullTime
}

const definitionColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,semantic_version,state,definition_ref_id,resolved_graph_digest,maximum_iterations,maximum_fan_out,maximum_parallel_nodes,maximum_wall_time_seconds,maximum_wall_time_nanos,input_schema_ref_id,output_schema_ref_id,create_time,update_time,delete_time`

func scanDefinition(row scanner) (definitionRow, error) {
	var value definitionRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.displayName, &value.semanticVersion, &value.state, &value.definitionID, &value.graphDigest, &value.maximumIterations, &value.maximumFanOut, &value.maximumParallel, &value.wallSeconds, &value.wallNanos, &value.inputSchemaID, &value.outputSchemaID, &value.created, &value.updated, &value.deleted)
	return value, err
}

func definitionProto(ctx context.Context, tx *sql.Tx, row definitionRow) (*workflowv1.WorkflowDefinition, error) {
	definition, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.definitionID, Valid: true})
	if err != nil {
		return nil, err
	}
	inputSchema, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.inputSchemaID)
	if err != nil {
		return nil, err
	}
	outputSchema, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.outputSchemaID)
	if err != nil {
		return nil, err
	}
	value := &workflowv1.WorkflowDefinition{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project,
		DisplayName: row.displayName, SemanticVersion: row.semanticVersion, State: workflowv1.WorkflowDefinitionState(row.state),
		Definition: definition, ResolvedGraphDigest: row.graphDigest,
		Limits:      &workflowv1.WorkflowLimits{MaximumIterations: uint32(row.maximumIterations), MaximumFanOut: uint32(row.maximumFanOut), MaximumParallelNodes: uint32(row.maximumParallel), MaximumWallTime: &durationpb.Duration{Seconds: row.wallSeconds, Nanos: row.wallNanos}}, //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
		InputSchema: inputSchema, OutputSchema: outputSchema, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()), DeleteTime: timestamp(row.deleted),
	}
	rows, err := tx.QueryContext(ctx, `SELECT resource_ref_id FROM workflow_definition_tools WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var toolIDs []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		toolIDs = append(toolIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range toolIDs {
		item, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.EligibleTools = append(value.EligibleTools, item)
	}
	rows, err = tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM workflow_definition_policies WHERE tenant_id=$1 AND project_id=$2 AND definition_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var policyIDs []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		policyIDs = append(policyIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range policyIDs {
		item, loadErr := LoadPolicySnapshot(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, item)
	}
	return value, nil
}

func storeDefinitionChildren(ctx context.Context, tx *sql.Tx, identity Identity, name string, value *workflowv1.WorkflowDefinition) error {
	for ordinal, tool := range value.GetEligibleTools() {
		id, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, tool)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_definition_tools(tenant_id,project_id,definition_name,ordinal,resource_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); err != nil {
			return err
		}
	}
	for ordinal, policy := range value.GetPolicySnapshots() {
		id, err := StorePolicySnapshot(ctx, tx, identity.TenantID, policy)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO workflow_definition_policies(tenant_id,project_id,definition_name,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); err != nil {
			return err
		}
	}
	return nil
}

type runRow struct {
	tenant, project, name, uid, etag, definitionDigest, attemptID, operationID, jobID, schedulerRunID string
	revision, completedNodes, iterations, transitionSequence, leaseEpoch                              int64
	state                                                                                             int32
	definitionID                                                                                      int64
	agentRunID, inputID, outputID, replayID, admissionID, decisionLogID, failureID                    sql.NullInt64
	created, updated                                                                                  time.Time
	ended                                                                                             sql.NullTime
}

const runColumns = `tenant_id,project_id,name,uid,revision,etag,definition_ref_id,definition_digest,agent_run_ref_id,state,completed_node_count,iteration_count,transition_sequence,attempt_id,lease_epoch,input_ref_id,output_ref_id,replay_state_ref_id,admission_decision_id,decision_log_ref_id,failure_detail_id,create_time,update_time,end_time,operation_id,job_id,scheduler_run_id`

func scanRun(row scanner) (runRow, error) {
	var value runRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.definitionID, &value.definitionDigest, &value.agentRunID, &value.state, &value.completedNodes, &value.iterations, &value.transitionSequence, &value.attemptID, &value.leaseEpoch, &value.inputID, &value.outputID, &value.replayID, &value.admissionID, &value.decisionLogID, &value.failureID, &value.created, &value.updated, &value.ended, &value.operationID, &value.jobID, &value.schedulerRunID)
	return value, err
}

func runProto(ctx context.Context, tx *sql.Tx, row runRow) (*workflowv1.WorkflowRun, error) {
	definition, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.definitionID, Valid: true})
	if err != nil {
		return nil, err
	}
	agentRun, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.agentRunID)
	if err != nil {
		return nil, err
	}
	loadArtifact := func(id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
		return platformdb.LoadArtifactRef(ctx, tx, row.tenant, id)
	}
	input, err := loadArtifact(row.inputID)
	if err != nil {
		return nil, err
	}
	output, err := loadArtifact(row.outputID)
	if err != nil {
		return nil, err
	}
	replay, err := loadArtifact(row.replayID)
	if err != nil {
		return nil, err
	}
	decisionLog, err := loadArtifact(row.decisionLogID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.failureID)
	if err != nil {
		return nil, err
	}
	var admission *policyv1.AuthorizationDecision
	if row.admissionID.Valid {
		admission, err = LoadAuthorizationDecision(ctx, tx, row.tenant, row.admissionID.Int64)
		if err != nil {
			return nil, err
		}
	}
	value := &workflowv1.WorkflowRun{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project, Definition: definition, DefinitionDigest: row.definitionDigest, AgentRun: agentRun, State: workflowv1.WorkflowRunState(row.state), CompletedNodeCount: uint32(row.completedNodes), IterationCount: uint32(row.iterations), TransitionSequence: uint64(row.transitionSequence), AttemptId: row.attemptID, LeaseEpoch: uint64(row.leaseEpoch), Input: input, Output: output, ReplayState: replay, AdmissionDecision: admission, DecisionLog: decisionLog, Failure: failure, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()), EndTime: timestamp(row.ended)} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	rows, err := tx.QueryContext(ctx, `SELECT node_id FROM workflow_run_active_nodes WHERE tenant_id=$1 AND project_id=$2 AND workflow_run_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
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
	return value, rows.Err()
}

func getRunTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*workflowv1.WorkflowRun, runRow, error) {
	canonical, err := canonicalScopedName(identity, name, "workflowRuns")
	if err != nil {
		return nil, runRow{}, err
	}
	query := `SELECT ` + runColumns + ` FROM workflow_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanRun(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, runRow{}, ErrNotFound
	}
	if err != nil {
		return nil, runRow{}, err
	}
	value, err := runProto(ctx, tx, row)
	return value, row, err
}

type contextRow struct {
	requestID, idempotencyKey, principalID, traceID, canonicalDigest, correlationID, causationID, cancellationTokenID string
	deadline                                                                                                          sql.NullTime
}

func contextProto(row contextRow, tenant, project string) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: row.requestID, IdempotencyKey: row.idempotencyKey, PrincipalId: row.principalID, TraceId: row.traceID, Deadline: timestamp(row.deadline), CanonicalRequestDigest: row.canonicalDigest, TenantId: tenant, ProjectId: project, CorrelationId: row.correlationID, CausationId: row.causationID, CancellationTokenId: row.cancellationTokenID}
}

func contextValues(value *commonv1.CommandContext) (contextRow, error) {
	if value == nil {
		return contextRow{}, ErrInvalidArgument
	}
	deadline, err := nullableTime(value.GetDeadline())
	if err != nil {
		return contextRow{}, err
	}
	return contextRow{requestID: value.GetRequestId(), idempotencyKey: value.GetIdempotencyKey(), principalID: value.GetPrincipalId(), traceID: value.GetTraceId(), deadline: deadline, canonicalDigest: value.GetCanonicalRequestDigest(), correlationID: value.GetCorrelationId(), causationID: value.GetCausationId(), cancellationTokenID: value.GetCancellationTokenId()}, nil
}

type approvalRow struct {
	tenant, project, name, uid, etag                                                               string
	revision                                                                                       int64
	context                                                                                        contextRow
	bindingAction, bindingIntentDigest, bindingParametersDigest, bindingAgentRun, bindingAgentStep string
	bindingToolID                                                                                  sql.NullInt64
	bindingToolVersion                                                                             string
	bindingPolicyID                                                                                int64
	bindingRiskClass, bindingDigest, requestedBy                                                   string
	minimumApprovers                                                                               int64
	reusePolicy, state                                                                             int32
	requestedAt, expireTime                                                                        time.Time
}

const approvalColumns = `tenant_id,project_id,name,uid,revision,etag,context_request_id,context_idempotency_key,context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,context_correlation_id,context_causation_id,context_cancellation_token_id,binding_action,binding_intent_digest,binding_parameters_digest,binding_agent_run_name,binding_agent_step_name,binding_tool_ref_id,binding_tool_version,binding_policy_snapshot_id,binding_risk_class,binding_digest,requested_by_principal_ref,minimum_independent_approvers,reuse_policy,state,requested_at,expire_time`

func scanApproval(row scanner) (approvalRow, error) {
	var value approvalRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.context.requestID, &value.context.idempotencyKey, &value.context.principalID, &value.context.traceID, &value.context.deadline, &value.context.canonicalDigest, &value.context.correlationID, &value.context.causationID, &value.context.cancellationTokenID, &value.bindingAction, &value.bindingIntentDigest, &value.bindingParametersDigest, &value.bindingAgentRun, &value.bindingAgentStep, &value.bindingToolID, &value.bindingToolVersion, &value.bindingPolicyID, &value.bindingRiskClass, &value.bindingDigest, &value.requestedBy, &value.minimumApprovers, &value.reusePolicy, &value.state, &value.requestedAt, &value.expireTime)
	return value, err
}

func approvalProto(ctx context.Context, tx *sql.Tx, row approvalRow) (*workflowv1.ApprovalRequest, error) {
	tool, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.bindingToolID)
	if err != nil {
		return nil, err
	}
	policy, err := LoadPolicySnapshot(ctx, tx, row.tenant, row.bindingPolicyID)
	if err != nil {
		return nil, err
	}
	binding := &workflowv1.ApprovalBinding{Action: row.bindingAction, IntentDigest: row.bindingIntentDigest, ParametersDigest: row.bindingParametersDigest, AgentRunName: row.bindingAgentRun, AgentStepName: row.bindingAgentStep, Tool: tool, ToolVersion: row.bindingToolVersion, PolicySnapshot: policy, RiskClass: row.bindingRiskClass, BindingDigest: row.bindingDigest}
	value := &workflowv1.ApprovalRequest{Context: contextProto(row.context, row.tenant, row.project), Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project, Binding: binding, RequestedByPrincipalRef: row.requestedBy, MinimumIndependentApprovers: uint32(row.minimumApprovers), ReusePolicy: workflowv1.ApprovalReusePolicy(row.reusePolicy), State: workflowv1.ApprovalState(row.state), RequestedAt: timestamppb.New(row.requestedAt.UTC()), ExpireTime: timestamppb.New(row.expireTime.UTC())} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	rows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM approval_request_input_artifacts WHERE tenant_id=$1 AND project_id=$2 AND approval_request_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)                                                                                                                                                                                                                                                                                                                                        //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var artifactIDs []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		artifactIDs = append(artifactIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range artifactIDs {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		binding.InputArtifacts = append(binding.InputArtifacts, item)
	}
	rows, err = tx.QueryContext(ctx, `SELECT authorization_decision_id FROM approval_request_policy_decisions WHERE tenant_id=$1 AND project_id=$2 AND approval_request_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var decisionIDs []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		decisionIDs = append(decisionIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range decisionIDs {
		item, loadErr := LoadAuthorizationDecision(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicyDecisions = append(value.PolicyDecisions, item)
	}
	return value, nil
}

func getApprovalTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*workflowv1.ApprovalRequest, approvalRow, error) {
	canonical, err := canonicalScopedName(identity, name, "approvalRequests")
	if err != nil {
		return nil, approvalRow{}, err
	}
	query := `SELECT ` + approvalColumns + ` FROM approval_requests WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanApproval(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, approvalRow{}, ErrNotFound
	}
	if err != nil {
		return nil, approvalRow{}, err
	}
	value, err := approvalProto(ctx, tx, row)
	return value, row, err
}

type receiptRow struct {
	tenant, project, name, uid                                                                     string
	context                                                                                        contextRow
	requestID                                                                                      int64
	bindingAction, bindingIntentDigest, bindingParametersDigest, bindingAgentRun, bindingAgentStep string
	bindingToolID                                                                                  sql.NullInt64
	bindingToolVersion                                                                             string
	bindingPolicyID                                                                                int64
	bindingRiskClass, bindingDigest                                                                string
	decision                                                                                       int32
	approver                                                                                       string
	authorityID                                                                                    int64
	reasonCode, safeReason                                                                         string
	reusePolicy                                                                                    int32
	decidedAt, expireTime                                                                          time.Time
	signer, receiptDigest                                                                          string
	consumedAt                                                                                     sql.NullTime
	consumedCallID                                                                                 sql.NullString
}

const receiptColumns = `r.tenant_id,r.project_id,r.name,r.uid,r.context_request_id,r.context_idempotency_key,r.context_principal_id,r.context_trace_id,r.context_deadline,r.context_canonical_request_digest,r.context_correlation_id,r.context_causation_id,r.context_cancellation_token_id,r.request_ref_id,r.binding_action,r.binding_intent_digest,r.binding_parameters_digest,r.binding_agent_run_name,r.binding_agent_step_name,r.binding_tool_ref_id,r.binding_tool_version,r.binding_policy_snapshot_id,r.binding_risk_class,r.binding_digest,r.decision,r.approver_principal_ref,r.approver_authority_ref_id,r.reason_code,r.safe_reason,r.reuse_policy,r.decided_at,r.expire_time,r.signer_identity,r.receipt_digest,c.consumed_at,c.consumed_by_call_id`

func scanReceipt(row scanner) (receiptRow, error) {
	var value receiptRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.context.requestID, &value.context.idempotencyKey, &value.context.principalID, &value.context.traceID, &value.context.deadline, &value.context.canonicalDigest, &value.context.correlationID, &value.context.causationID, &value.context.cancellationTokenID, &value.requestID, &value.bindingAction, &value.bindingIntentDigest, &value.bindingParametersDigest, &value.bindingAgentRun, &value.bindingAgentStep, &value.bindingToolID, &value.bindingToolVersion, &value.bindingPolicyID, &value.bindingRiskClass, &value.bindingDigest, &value.decision, &value.approver, &value.authorityID, &value.reasonCode, &value.safeReason, &value.reusePolicy, &value.decidedAt, &value.expireTime, &value.signer, &value.receiptDigest, &value.consumedAt, &value.consumedCallID)
	return value, err
}

func receiptProto(ctx context.Context, tx *sql.Tx, row receiptRow) (*workflowv1.ApprovalReceipt, error) {
	requestRef, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.requestID, Valid: true})
	if err != nil {
		return nil, err
	}
	tool, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.bindingToolID)
	if err != nil {
		return nil, err
	}
	policy, err := LoadPolicySnapshot(ctx, tx, row.tenant, row.bindingPolicyID)
	if err != nil {
		return nil, err
	}
	authority, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.authorityID, Valid: true})
	if err != nil {
		return nil, err
	}
	binding := &workflowv1.ApprovalBinding{Action: row.bindingAction, IntentDigest: row.bindingIntentDigest, ParametersDigest: row.bindingParametersDigest, AgentRunName: row.bindingAgentRun, AgentStepName: row.bindingAgentStep, Tool: tool, ToolVersion: row.bindingToolVersion, PolicySnapshot: policy, RiskClass: row.bindingRiskClass, BindingDigest: row.bindingDigest}
	value := &workflowv1.ApprovalReceipt{Context: contextProto(row.context, row.tenant, row.project), Name: row.name, Uid: row.uid, Request: requestRef, Binding: binding, Decision: workflowv1.ApprovalDecisionValue(row.decision), ApproverPrincipalRef: row.approver, ApproverAuthority: authority, ReasonCode: row.reasonCode, SafeReason: row.safeReason, ReusePolicy: workflowv1.ApprovalReusePolicy(row.reusePolicy), DecidedAt: timestamppb.New(row.decidedAt.UTC()), ExpireTime: timestamppb.New(row.expireTime.UTC()), ConsumedAt: timestamp(row.consumedAt), ConsumedByCallId: row.consumedCallID.String, SignerIdentity: row.signer, ReceiptDigest: row.receiptDigest}
	rows, err := tx.QueryContext(ctx, `SELECT artifact_ref_id FROM approval_receipt_input_artifacts WHERE tenant_id=$1 AND project_id=$2 AND approval_receipt_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
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
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range ids {
		item, loadErr := platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		binding.InputArtifacts = append(binding.InputArtifacts, item)
	}
	return value, nil
}

func LoadApprovalReceipt(ctx context.Context, tx *sql.Tx, tenantID, projectID, name string, lock bool) (*workflowv1.ApprovalReceipt, error) {
	query := `SELECT ` + receiptColumns + ` FROM approval_receipts r LEFT JOIN LATERAL (SELECT consumed_at,consumed_by_call_id FROM approval_receipt_consumptions WHERE tenant_id=r.tenant_id AND project_id=r.project_id AND approval_receipt_name=r.name ORDER BY consumed_at DESC,consumed_by_call_id DESC LIMIT 1) c ON true WHERE r.tenant_id=$1 AND r.project_id=$2 AND r.name=$3`
	if lock {
		query += ` FOR UPDATE OF r`
	}
	row, err := scanReceipt(tx.QueryRowContext(ctx, query, tenantID, projectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return receiptProto(ctx, tx, row)
}
