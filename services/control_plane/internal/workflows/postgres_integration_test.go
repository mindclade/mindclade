package workflows

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func workflowIntegrationDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		t.Skip("PostgreSQL integration DSN is not configured")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err = db.PingContext(context.Background()); err != nil {
		t.Fatal(err)
	}
	return db
}

func workflowArtifact(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(seed, 64), MediaType: "application/vnd.mindclade.workflow+json", SizeBytes: 64, ArtifactKind: "workflow-test", SchemaId: "mindclade.workflow.test", SchemaVersion: "1", IntegrityDigest: "sha256:" + strings.Repeat(seed, 64)}
}

func workflowContext(identity Identity, requestID, key string, at time.Time) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: requestID, IdempotencyKey: key, TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, TraceId: "trace-" + requestID, Deadline: timestamppb.New(at.Add(time.Minute))}
}

func workflowPolicy(identity Identity, fixtureID string, at time.Time) *policyv1.PolicyReference {
	return &policyv1.PolicyReference{Name: projectParent(identity) + "/usePolicies/approval-" + fixtureID + "/snapshots/1", Uid: "approval-policy-" + fixtureID, PolicyType: "approval", Version: "1.0.0", Digest: "sha256:" + strings.Repeat("a", 64), Document: workflowArtifact("a"), ResourceRevision: 1, EffectiveTime: timestamppb.New(at.Add(-time.Hour)), ExpireTime: timestamppb.New(at.Add(24 * time.Hour)), Classification: "internal"}
}

func workflowAuthorization(identity Identity, fixtureID string, policy *policyv1.PolicyReference, at time.Time) *policyv1.AuthorizationDecision {
	return &policyv1.AuthorizationDecision{Name: projectParent(identity) + "/authorizationDecisions/approval-" + fixtureID, Uid: "approval-authorization-" + fixtureID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalRef: identity.Principal, Action: "agent.tool.execute", Resource: &commonv1.ResourceRef{ResourceType: "mindclade.agent.v1.Tool", ResourceId: "tool", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/tools/tool", Etag: "sha256:" + strings.Repeat("b", 64)}, IntentDigest: "sha256:" + strings.Repeat("c", 64), Policies: []*policyv1.PolicyReference{clone(policy)}, Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW, ReasonCode: "POLICY_ALLOW", SafeReason: "bounded integration fixture", EvaluatedAt: timestamppb.New(at), ExpireTime: timestamppb.New(at.Add(time.Hour)), ContextDigest: "sha256:" + strings.Repeat("d", 64), DecisionDigest: "sha256:" + strings.Repeat("e", 64)}
}

func TestPostgresUint32StorageBoundsAreValidated(t *testing.T) {
	db := workflowIntegrationDB(t)
	rows, err := db.QueryContext(context.Background(), `
SELECT conname, convalidated, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname IN (
  'chk_workflow_def_max_iterations_u32',
  'chk_workflow_def_max_fan_out_u32',
  'chk_workflow_def_max_parallel_nodes_u32',
  'chk_workflow_run_completed_nodes_u32',
  'chk_workflow_run_iterations_u32',
  'chk_workflow_rev_completed_nodes_u32',
  'chk_workflow_rev_iterations_u32',
  'chk_approval_request_min_approvers_u32',
  'chk_agent_def_budget_iterations_u32',
  'chk_agent_def_budget_tool_calls_u32',
  'chk_agent_def_budget_branches_u32',
  'chk_agent_def_limit_depth_u32',
  'chk_agent_def_limit_fan_out_u32',
  'chk_agent_def_limit_observations_u32',
  'chk_agent_def_limit_artifacts_u32',
  'chk_agent_run_usage_iterations_u32',
  'chk_agent_run_usage_tool_calls_u32'
)`)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = rows.Close() }()

	seen := make(map[string]struct{}, 17)
	for rows.Next() {
		var name, definition string
		var validated bool
		if err = rows.Scan(&name, &validated, &definition); err != nil {
			t.Fatal(err)
		}
		if !validated || !strings.Contains(definition, "4294967295") {
			t.Fatalf("constraint %s is not a validated uint32 bound: validated=%t definition=%q", name, validated, definition)
		}
		seen[name] = struct{}{}
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 17 {
		t.Fatalf("found %d of 17 validated uint32 storage constraints: %v", len(seen), seen)
	}
}

func approvalFixture(t *testing.T, identity Identity, reuse workflowv1.ApprovalReusePolicy, requestID, key string, at time.Time) *workflowv1.ApprovalRequest {
	t.Helper()
	policy := workflowPolicy(identity, requestID, at)
	binding := &workflowv1.ApprovalBinding{Action: "agent.tool.execute", IntentDigest: "sha256:" + strings.Repeat("1", 64), ParametersDigest: "sha256:" + strings.Repeat("2", 64), InputArtifacts: []*artifactv1.ArtifactRef{workflowArtifact("3")}, AgentRunName: projectParent(identity) + "/agentRuns/run", AgentStepName: projectParent(identity) + "/agentRuns/run/steps/1", PolicySnapshot: policy, RiskClass: "HIGH"}
	var err error
	binding.BindingDigest, err = canonicalBindingDigest(binding)
	if err != nil {
		t.Fatal(err)
	}
	value := &workflowv1.ApprovalRequest{Context: workflowContext(identity, requestID, key, at), Binding: binding, RequestedByPrincipalRef: identity.Principal, MinimumIndependentApprovers: 1, ReusePolicy: reuse, PolicyDecisions: []*policyv1.AuthorizationDecision{workflowAuthorization(identity, requestID, policy, at)}, ExpireTime: timestamppb.New(at.Add(time.Hour))}
	digest, err := canonicalDigest(value)
	if err != nil {
		t.Fatal(err)
	}
	value.Context.CanonicalRequestDigest = digest
	return value
}

func TestPostgresApprovalAuthorityIsNormalizedIndependentIdempotentAndReusable(t *testing.T) {
	db := workflowIntegrationDB(t)
	ctx := context.Background()
	at := time.Now().UTC().Truncate(time.Microsecond)
	suffix := strings.ReplaceAll(at.Format("20060102150405.000000"), ".", "")
	requester := Identity{TenantID: "workflow-tenant-" + suffix, ProjectID: "project", Principal: "requester", Roles: map[string]struct{}{"automation-operator": {}}}
	approver := Identity{TenantID: requester.TenantID, ProjectID: requester.ProjectID, Principal: "approver", Roles: map[string]struct{}{"approver": {}}}
	worker := Identity{TenantID: requester.TenantID, ProjectID: requester.ProjectID, Principal: "worker", Roles: map[string]struct{}{"automation-worker": {}}}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("workflow-approval-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}

	requested := approvalFixture(t, requester, workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_SINGLE_USE, "request-single", "key-single", at)
	digest := requested.GetContext().GetCanonicalRequestDigest()
	created, replay, err := repository.RequestApproval(ctx, requester, requested, digest, at)
	if err != nil || replay || created.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_PENDING {
		t.Fatalf("create=%v replay=%v err=%v", created, replay, err)
	}
	replayed, replay, err := repository.RequestApproval(ctx, requester, clone(requested), digest, at.Add(time.Second))
	if err != nil || !replay || !proto.Equal(replayed, created) {
		t.Fatalf("request replay=%v replay=%v err=%v", replayed, replay, err)
	}
	listed, next, _, err := repository.ListApprovals(ctx, requester, ApprovalPage{Limit: 10, Order: "create_time desc,name desc"})
	if err != nil || len(listed) != 1 || next != "" || !proto.Equal(listed[0], created) {
		t.Fatalf("list=%v next=%q err=%v", listed, next, err)
	}

	decideAt := at.Add(2 * time.Second)
	decide := &internalworkflowv1.DecideApprovalRequest{Context: workflowContext(approver, "decide-single", "decide-key-single", decideAt), Name: created.GetName(), Etag: created.GetEtag(), Decision: workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_APPROVE, ReasonCode: "HUMAN_VERIFIED", SafeReason: "intent and evidence match"}
	decideDigest, err := canonicalDigest(decide)
	if err != nil {
		t.Fatal(err)
	}
	decide.Context.CanonicalRequestDigest = decideDigest
	receipt, replay, err := repository.DecideApproval(ctx, approver, decide, decideDigest, decideAt)
	if err != nil || replay || !validSHA256(receipt.GetReceiptDigest()) || receipt.GetApproverPrincipalRef() != approver.Principal {
		t.Fatalf("receipt=%v replay=%v err=%v", receipt, replay, err)
	}
	receiptReplay, replay, err := repository.DecideApproval(ctx, approver, clone(decide), decideDigest, decideAt.Add(time.Second))
	if err != nil || !replay || !proto.Equal(receiptReplay, receipt) {
		t.Fatalf("decision replay=%v replay=%v err=%v", receiptReplay, replay, err)
	}
	approved, err := repository.GetApproval(ctx, requester, created.GetName())
	if err != nil || approved.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_APPROVED || approved.GetRevision() != 2 {
		t.Fatalf("approved=%v err=%v", approved, err)
	}

	consumeAt := at.Add(4 * time.Second)
	consume := &internalworkflowv1.ConsumeApprovalRequest{Context: workflowContext(worker, "consume-single", "consume-key-single", consumeAt), ReceiptName: receipt.GetName(), BindingDigest: receipt.GetBinding().GetBindingDigest(), CallId: "call-single"}
	consumeDigest, err := canonicalDigest(consume)
	if err != nil {
		t.Fatal(err)
	}
	consume.Context.CanonicalRequestDigest = consumeDigest
	consumed, replay, err := repository.ConsumeApproval(ctx, worker, consume, consumeDigest, consumeAt)
	if err != nil || replay || consumed.GetConsumedByCallId() != consume.GetCallId() {
		t.Fatalf("consumed=%v replay=%v err=%v", consumed, replay, err)
	}
	consumedReplay, replay, err := repository.ConsumeApproval(ctx, worker, clone(consume), consumeDigest, consumeAt.Add(time.Second))
	if err != nil || !replay || !proto.Equal(consumedReplay, consumed) {
		t.Fatalf("consume replay=%v replay=%v err=%v", consumedReplay, replay, err)
	}
	reuseSingle := clone(consume)
	reuseSingle.Context = workflowContext(worker, "consume-single-again", "consume-key-single-again", consumeAt.Add(2*time.Second))
	reuseSingle.CallId = "call-single-again"
	reuseDigest, err := canonicalDigest(reuseSingle)
	if err != nil {
		t.Fatal(err)
	}
	reuseSingle.Context.CanonicalRequestDigest = reuseDigest
	if _, _, err = repository.ConsumeApproval(ctx, worker, reuseSingle, reuseDigest, consumeAt.Add(2*time.Second)); !errors.Is(err, ErrApprovalConsumed) {
		t.Fatalf("single-use reuse error=%v", err)
	}
	consumedRequest, err := repository.GetApproval(ctx, requester, created.GetName())
	if err != nil || consumedRequest.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_CONSUMED || consumedRequest.GetRevision() != 3 {
		t.Fatalf("consumed request=%v err=%v", consumedRequest, err)
	}

	same := approvalFixture(t, requester, workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_SAME_INTENT_UNTIL_EXPIRY, "request-same", "key-same", at.Add(10*time.Second))
	sameDigest := same.GetContext().GetCanonicalRequestDigest()
	sameCreated, _, err := repository.RequestApproval(ctx, requester, same, sameDigest, at.Add(10*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	sameDecideAt := at.Add(11 * time.Second)
	sameDecide := &internalworkflowv1.DecideApprovalRequest{Context: workflowContext(approver, "decide-same", "decide-key-same", sameDecideAt), Name: sameCreated.GetName(), Etag: sameCreated.GetEtag(), Decision: workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_APPROVE, ReasonCode: "HUMAN_VERIFIED"}
	sameDecideDigest, err := canonicalDigest(sameDecide)
	if err != nil {
		t.Fatal(err)
	}
	sameDecide.Context.CanonicalRequestDigest = sameDecideDigest
	sameReceipt, _, err := repository.DecideApproval(ctx, approver, sameDecide, sameDecideDigest, sameDecideAt)
	if err != nil {
		t.Fatal(err)
	}
	for index := 1; index <= 2; index++ {
		useAt := at.Add(time.Duration(11+index) * time.Second)
		use := &internalworkflowv1.ConsumeApprovalRequest{Context: workflowContext(worker, "consume-same-"+string(rune('0'+index)), "consume-key-same-"+string(rune('0'+index)), useAt), ReceiptName: sameReceipt.GetName(), BindingDigest: sameReceipt.GetBinding().GetBindingDigest(), CallId: "call-same-" + string(rune('0'+index))}
		useDigest, digestErr := canonicalDigest(use)
		if digestErr != nil {
			t.Fatal(digestErr)
		}
		use.Context.CanonicalRequestDigest = useDigest
		used, wasReplay, useErr := repository.ConsumeApproval(ctx, worker, use, useDigest, useAt)
		if useErr != nil || wasReplay || used.GetConsumedByCallId() != use.GetCallId() {
			t.Fatalf("same-intent use %d receipt=%v replay=%v err=%v", index, used, wasReplay, useErr)
		}
	}

	verify, err := platformdb.BeginTenantTx(ctx, db, requester.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var approvals, receipts, consumptions, commands, outbox, audits int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM approval_requests WHERE tenant_id=$1),(SELECT count(*) FROM approval_receipts WHERE tenant_id=$1),(SELECT count(*) FROM approval_receipt_consumptions WHERE tenant_id=$1),(SELECT count(*) FROM workflow_agent_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1)`, requester.TenantID).Scan(&approvals, &receipts, &consumptions, &commands, &outbox, &audits); err != nil {
		t.Fatal(err)
	}
	if approvals != 2 || receipts != 2 || consumptions != 3 || commands != 7 || outbox != 7 || audits != 7 {
		t.Fatalf("approvals=%d receipts=%d consumptions=%d commands=%d outbox=%d audits=%d", approvals, receipts, consumptions, commands, outbox, audits)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,event_type`, requester.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	eventTypes := map[string]int{}
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		eventTypes[string(payload.ProtoReflect().Descriptor().FullName())]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]int{"mindclade.events.workflow.v1.ApprovalRequested": 2, "mindclade.events.workflow.v1.ApprovalRecorded": 2, "mindclade.events.workflow.v1.ApprovalConsumed": 3} {
		if eventTypes[name] != want {
			t.Fatalf("event %s count=%d want=%d all=%v", name, eventTypes[name], want, eventTypes)
		}
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
}

func TestPostgresWorkflowRunIsNormalizedFencedResumableAndEventBacked(t *testing.T) {
	db := workflowIntegrationDB(t)
	ctx := context.Background()
	at := time.Now().UTC().Truncate(time.Microsecond)
	suffix := strings.ReplaceAll(at.Format("20060102150405.000000"), ".", "")
	identity := Identity{TenantID: "workflow-run-tenant-" + suffix, ProjectID: "project", Principal: "operator", Roles: map[string]struct{}{"automation-operator": {}}}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("workflow-run-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	policy := workflowPolicy(identity, "run", at)
	definition := &workflowv1.WorkflowDefinition{DisplayName: "Integration workflow", SemanticVersion: "1.0.0", State: workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_ACTIVE, Definition: workflowArtifact("4"), ResolvedGraphDigest: "sha256:" + strings.Repeat("5", 64), Limits: &workflowv1.WorkflowLimits{MaximumIterations: 8, MaximumFanOut: 4, MaximumParallelNodes: 2, MaximumWallTime: durationpb.New(10 * time.Minute)}, EligibleTools: []*commonv1.ResourceRef{{ResourceType: "mindclade.agent.v1.Tool", ResourceId: "tool", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/tools/tool", Etag: "sha256:" + strings.Repeat("6", 64)}}, PolicySnapshots: []*policyv1.PolicyReference{policy}, InputSchema: workflowArtifact("7"), OutputSchema: workflowArtifact("8")}
	create := &internalworkflowv1.CreateWorkflowDefinitionRequest{Context: workflowContext(identity, "definition-create", "definition-create-key", at), Parent: projectParent(identity), WorkflowDefinitionId: "integration", WorkflowDefinition: definition}
	createDigest, err := canonicalDigest(create)
	if err != nil {
		t.Fatal(err)
	}
	create.Context.CanonicalRequestDigest = createDigest
	operation, replay, err := repository.CreateDefinition(ctx, identity, create, createDigest, at)
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("definition operation=%v replay=%v err=%v", operation, replay, err)
	}
	definitionName := projectParent(identity) + "/workflowDefinitions/integration"
	persistedDefinition, err := repository.GetDefinition(ctx, identity, definitionName)
	if err != nil || persistedDefinition.GetResolvedGraphDigest() != definition.GetResolvedGraphDigest() || len(persistedDefinition.GetEligibleTools()) != 1 || !proto.Equal(persistedDefinition.GetPolicySnapshots()[0], policy) {
		t.Fatalf("definition=%v err=%v", persistedDefinition, err)
	}

	definitionRef := &commonv1.ResourceRef{ResourceType: "mindclade.workflow.v1.WorkflowDefinition", ResourceId: persistedDefinition.GetUid(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: persistedDefinition.GetRevision(), Name: persistedDefinition.GetName(), Etag: persistedDefinition.GetEtag()}
	admission := workflowAuthorization(identity, "run-admission", policy, at.Add(time.Second))
	startAt := at.Add(time.Second)
	start := &internalworkflowv1.StartWorkflowRunRequest{Context: workflowContext(identity, "run-start", "run-start-key", startAt), Parent: projectParent(identity), WorkflowRunId: "integration", WorkflowRun: &workflowv1.WorkflowRun{Definition: definitionRef, DefinitionDigest: definition.GetResolvedGraphDigest(), Input: workflowArtifact("9"), AdmissionDecision: admission}}
	startDigest, err := canonicalDigest(start)
	if err != nil {
		t.Fatal(err)
	}
	start.Context.CanonicalRequestDigest = startDigest
	runOperation, replay, err := repository.StartRun(ctx, identity, start, startDigest, startAt)
	if err != nil || replay || runOperation.GetDone() || runOperation.GetState() != 1 {
		t.Fatalf("run operation=%v replay=%v err=%v", runOperation, replay, err)
	}
	run, err := repository.GetRun(ctx, identity, projectParent(identity)+"/workflowRuns/integration")
	if err != nil || run.GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CREATED || !proto.Equal(run.GetAdmissionDecision(), admission) {
		t.Fatalf("run=%v err=%v", run, err)
	}
	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var schedulerRunID string
	if err = readTx.QueryRowContext(ctx, `SELECT scheduler_run_id FROM workflow_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, run.GetName()).Scan(&schedulerRunID); err != nil {
		t.Fatal(err)
	}
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}
	leaseToken := strings.Repeat("workflow-lease-token-", 3)
	leaseAt := at.Add(2 * time.Second)
	lease, err := (jobs.SQLRepository{DB: db}).AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{TenantID: identity.TenantID, RunID: schedulerRunID, AttemptID: "attempts/workflow-integration", WorkerID: "worker-1", Token: leaseToken, TokenKeyID: "workflow-key-1", Duration: time.Minute, Now: leaseAt, Command: jobs.RunCommandMetadata{TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal, WorkerID: "worker-1", Action: "run.acquire_lease", IdempotencyKey: "workflow-acquire", RequestDigest: "sha256:" + strings.Repeat("a", 64), ObservedAt: leaseAt}})
	if err != nil {
		t.Fatal(err)
	}
	worker := Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: "workflow-worker", WorkerID: "worker-1", LeaseToken: "wrong-" + leaseToken, Roles: map[string]struct{}{"automation-worker": {}}}
	states := []workflowv1.WorkflowRunState{workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_ADMITTED, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING, workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED}
	replaySeeds := []string{"b", "c", "d"}
	decisionSeeds := []string{"e", "f", "0"}
	var firstCommit *internalworkflowv1.CommitWorkflowTransitionRequest
	var firstCommitted *workflowv1.WorkflowRun
	var firstCommitDigest string
	for index, state := range states {
		transitionAt := at.Add(time.Duration(3+index) * time.Second)
		proposed := clone(run)
		proposed.State = state
		proposed.TransitionSequence = run.GetTransitionSequence() + 1
		proposed.ActiveNodeIds = []string{"node-a"}
		proposed.CompletedNodeCount = uint32(index)
		proposed.IterationCount = uint32(index + 1)
		proposed.ReplayState = workflowArtifact(replaySeeds[index])
		proposed.DecisionLog = workflowArtifact(decisionSeeds[index])
		if state == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED {
			proposed.ActiveNodeIds = nil
			proposed.CompletedNodeCount = 3
			proposed.Output = workflowArtifact("f")
		}
		commit := &internalworkflowv1.CommitWorkflowTransitionRequest{Context: workflowContext(worker, "transition-"+string(rune('1'+index)), "transition-key-"+string(rune('1'+index)), transitionAt), WorkflowRun: proposed, ExpectedTransitionSequence: run.GetTransitionSequence(), Fence: clone(lease.Fence), Etag: run.GetEtag()}
		commitDigest, digestErr := canonicalDigest(commit)
		if digestErr != nil {
			t.Fatal(digestErr)
		}
		commit.Context.CanonicalRequestDigest = commitDigest
		if index == 0 {
			if _, _, commitErr := repository.CommitTransition(ctx, worker, commit, commitDigest, transitionAt); !errors.Is(commitErr, ErrLeaseToken) {
				t.Fatalf("wrong lease token error=%v", commitErr)
			}
			worker.LeaseToken = leaseToken
		}
		committed, wasReplay, commitErr := repository.CommitTransition(ctx, worker, commit, commitDigest, transitionAt)
		if commitErr != nil || wasReplay || committed.GetState() != state || committed.GetTransitionSequence() != uint64(index+1) || committed.GetAttemptId() != lease.Attempt.GetAttemptId() {
			t.Fatalf("transition %d run=%v replay=%v err=%v", index, committed, wasReplay, commitErr)
		}
		if index == 0 {
			replayedTransition, wasReplay, replayErr := repository.CommitTransition(ctx, worker, clone(commit), commitDigest, transitionAt.Add(time.Millisecond))
			if replayErr != nil || !wasReplay || !proto.Equal(replayedTransition, committed) {
				t.Fatalf("transition replay=%v replay=%v err=%v", replayedTransition, wasReplay, replayErr)
			}
			firstCommit, firstCommitted, firstCommitDigest = clone(commit), clone(committed), commitDigest
		}
		run = committed
	}
	lateReplay, wasReplay, err := repository.CommitTransition(ctx, worker, firstCommit, firstCommitDigest, at.Add(30*time.Second))
	if err != nil || !wasReplay || !proto.Equal(lateReplay, firstCommitted) {
		t.Fatalf("late transition replay=%v replay=%v err=%v", lateReplay, wasReplay, err)
	}
	transitions, err := repository.ListTransitions(ctx, identity, run.GetName(), 0, 10)
	if err != nil || len(transitions) != 3 || transitions[0].GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_ADMITTED || transitions[2].GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED || transitions[2].GetOutput().GetDigest() != workflowArtifact("f").GetDigest() {
		t.Fatalf("transitions=%v err=%v", transitions, err)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var storedToken string
	if err = verify.QueryRowContext(ctx, `SELECT lease_token_digest FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, lease.Attempt.GetAttemptId()).Scan(&storedToken); err != nil {
		t.Fatal(err)
	}
	if storedToken == leaseToken || !validSHA256(storedToken) {
		t.Fatalf("raw lease token was persisted: %q", storedToken)
	}
	var definitions, runs, revisions, events int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM workflow_definitions WHERE tenant_id=$1),(SELECT count(*) FROM workflow_runs WHERE tenant_id=$1),(SELECT count(*) FROM workflow_transition_revisions WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1)`, identity.TenantID).Scan(&definitions, &runs, &revisions, &events); err != nil {
		t.Fatal(err)
	}
	if definitions != 1 || runs != 1 || revisions != 3 || events != 7 {
		t.Fatalf("definitions=%d runs=%d revisions=%d events=%d", definitions, runs, revisions, events)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
}
