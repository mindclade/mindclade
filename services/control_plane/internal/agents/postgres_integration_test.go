package agents

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func integrationDB(t *testing.T) *sql.DB {
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
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	return db
}

func integrationArtifact(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(seed, 64), MediaType: "application/vnd.mindclade.integration+json", SizeBytes: 128, ArtifactKind: "integration", SchemaId: "mindclade.integration.v1", IntegrityDigest: "sha256:" + strings.Repeat(seed, 64), SchemaVersion: "1"}
}

// This test is intentionally a full vertical journey: authoritative generated
// values cross SQL, the scheduler lease is acquired through RunService state,
// worker writes are fenced, and every mutation produces registered protobuf
// events, audit evidence, and replayable command receipts.
func TestPostgresAgentJourneyIsNormalizedFencedIdempotentAndEventBacked(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "agent-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("agent-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	at := time.Now().UTC().Truncate(time.Microsecond)
	project := projectParent(identity)
	policy := &policyv1.PolicyReference{Name: project + "/policies/agent", Uid: "policy-agent", PolicyType: "agent", Version: "1.0.0", Digest: "sha256:" + strings.Repeat("1", 64), Document: integrationArtifact("1"), ResourceRevision: 3, EffectiveTime: timestamppb.New(at.Add(-time.Hour)), Classification: "internal"}
	definitionInput := &agentv1.AgentDefinition{DisplayName: "Qualified bounded agent", SemanticVersion: "1.0.0", State: agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DRAFT, Purpose: "perform bounded analysis", NonGoals: []string{"unbounded autonomous action", "secret handling"}, Definition: integrationArtifact("2"), WorkflowDefinition: &commonv1.ResourceRef{ResourceType: "workflow_definition", ResourceId: "workflow-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 2, Name: project + "/workflowDefinitions/workflow-1", Etag: "sha256:" + strings.Repeat("e", 64)}, EligibleTools: []*commonv1.ResourceRef{{ResourceType: "tool", ResourceId: "search", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 4, Name: project + "/tools/search", Etag: "sha256:" + strings.Repeat("d", 64)}}, PolicySnapshots: []*policyv1.PolicyReference{policy}, InputSchema: integrationArtifact("3"), OutputSchema: integrationArtifact("4"), ModelCapability: "reasoning", EvaluationSuite: &commonv1.ResourceRef{ResourceType: "evaluation_suite", ResourceId: "suite-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: project + "/evaluationSuites/suite-1", Etag: "sha256:" + strings.Repeat("c", 64)}, Budget: &agentv1.AgentBudgetEnvelope{MaximumModelTokens: 100000, MaximumIterations: 12, MaximumToolCalls: 8, MaximumConcurrentBranches: 2, MaximumStorageBytes: 1 << 30, MaximumExternalSpendMicros: 1000, MaximumWallTime: durationpb.New(10 * time.Minute), MaximumAcceleratorTime: durationpb.New(time.Minute), MaximumCpuTime: durationpb.New(5 * time.Minute)}, Limits: &agentv1.AgentExecutionLimits{MaximumDepth: 6, MaximumFanOut: 3, MaximumObservationsPerStep: 32, MaximumArtifactReferencesPerCall: 64}, QualificationLevel: "staging"}
	create := &internalagentv1.CreateAgentDefinitionRequest{Context: &commonv1.CommandContext{RequestId: "definition-create", IdempotencyKey: "definition-create-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(at.Add(time.Minute))}, Parent: project, AgentDefinitionId: "analyst", AgentDefinition: definitionInput}
	createDigest, err := canonicalDigest(create)
	if err != nil {
		t.Fatal(err)
	}
	create.Context.CanonicalRequestDigest = createDigest
	operation, replay, err := repository.CreateDefinition(ctx, identity, create, createDigest, at)
	if err != nil || replay {
		t.Fatalf("create operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayed, replay, err := repository.CreateDefinition(ctx, identity, clone(create), createDigest, at.Add(time.Second))
	if err != nil || !replay || replayed.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("create replay=%v replay=%v err=%v", replayed, replay, err)
	}
	definition, err := repository.GetDefinition(ctx, identity, definitionName(identity, "analyst"))
	if err != nil {
		t.Fatal(err)
	}
	expectedDefinition := clone(definitionInput)
	expectedDefinition.Name = definition.GetName()
	expectedDefinition.Uid = definition.GetUid()
	expectedDefinition.Revision = 1
	expectedDefinition.Etag = definition.GetEtag()
	expectedDefinition.TenantId = identity.TenantID
	expectedDefinition.ProjectId = identity.ProjectID
	expectedDefinition.CreateTime = timestamppb.New(at)
	expectedDefinition.UpdateTime = timestamppb.New(at)
	if !proto.Equal(definition, expectedDefinition) {
		t.Fatalf("definition roundtrip lost fields\n got=%v\nwant=%v", definition, expectedDefinition)
	}
	updateAt := at.Add(time.Second)
	update := &internalagentv1.UpdateAgentDefinitionRequest{Context: &commonv1.CommandContext{RequestId: "definition-update", IdempotencyKey: "definition-update-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(updateAt.Add(time.Minute))}, AgentDefinition: &agentv1.AgentDefinition{Name: definition.GetName(), DisplayName: "Qualified bounded agent v2", State: agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ACTIVE}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name", "state"}}, Etag: definition.GetEtag()}
	updateDigest, err := canonicalDigest(update)
	if err != nil {
		t.Fatal(err)
	}
	update.Context.CanonicalRequestDigest = updateDigest
	if _, replay, err = repository.UpdateDefinition(ctx, identity, update, updateDigest, updateAt); err != nil || replay {
		t.Fatalf("update replay=%v err=%v", replay, err)
	}
	definition, err = repository.GetDefinition(ctx, identity, definition.GetName())
	if err != nil || definition.GetState() != agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ACTIVE || definition.GetDisplayName() != "Qualified bounded agent v2" || definition.GetRevision() != 2 {
		t.Fatalf("updated definition=%v err=%v", definition, err)
	}
	listedDefinitions, next, _, err := repository.ListDefinitions(ctx, identity, DefinitionPage{Limit: 1, Order: "create_time desc, name desc"})
	if err != nil || len(listedDefinitions) != 1 || next != "" {
		t.Fatalf("definitions=%v next=%q err=%v", listedDefinitions, next, err)
	}
	runInput := &agentv1.AgentRun{Definition: &commonv1.ResourceRef{ResourceType: "agent_definition", ResourceId: "analyst", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: definition.GetRevision(), Name: definition.GetName(), Etag: definition.GetEtag()}, DefinitionDigest: definition.GetDefinition().GetDigest(), PolicySnapshots: []*policyv1.PolicyReference{policy}, Input: integrationArtifact("5"), ModelProviderManifest: integrationArtifact("6"), BudgetReservation: &commonv1.ResourceRef{ResourceType: "budget_reservation", ResourceId: "budget-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: project + "/budgetReservations/budget-1", Etag: "sha256:" + strings.Repeat("b", 64)}}
	startAt := at.Add(2 * time.Second)
	start := &internalagentv1.StartAgentRunRequest{Context: &commonv1.CommandContext{RequestId: "run-start", IdempotencyKey: "run-start-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(startAt.Add(time.Minute))}, Parent: project, AgentRunId: "run-1", AgentRun: runInput}
	startDigest, err := canonicalDigest(start)
	if err != nil {
		t.Fatal(err)
	}
	start.Context.CanonicalRequestDigest = startDigest
	runOperation, replay, err := repository.StartRun(ctx, identity, start, startDigest, startAt)
	if err != nil || replay {
		t.Fatalf("start operation=%v replay=%v err=%v", runOperation, replay, err)
	}
	run, err := repository.GetRun(ctx, identity, runName(identity, "run-1"))
	if err != nil {
		t.Fatal(err)
	}
	if run.GetDefinitionDigest() != runInput.GetDefinitionDigest() || !proto.Equal(run.GetPolicySnapshots()[0], policy) || run.GetNextStepSequence() != 1 || run.GetState() != agentv1.AgentRunState_AGENT_RUN_STATE_CREATED {
		t.Fatalf("run roundtrip=%v", run)
	}
	var schedulerRunID string
	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	if err = readTx.QueryRowContext(ctx, `SELECT scheduler_run_id FROM agent_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, run.GetName()).Scan(&schedulerRunID); err != nil {
		t.Fatal(err)
	}
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}
	token := strings.Repeat("agent-lease-token-", 4)
	leaseAt := at.Add(3 * time.Second)
	lease, err := (jobs.SQLRepository{DB: db}).AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{TenantID: identity.TenantID, RunID: schedulerRunID, AttemptID: "attempts/agent-1", WorkerID: "worker-1", Token: token, TokenKeyID: "key-1", Duration: time.Minute, Now: leaseAt, Command: jobs.RunCommandMetadata{TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal, WorkerID: "worker-1", Action: "run.acquire_lease", IdempotencyKey: "acquire-agent-1", RequestDigest: "sha256:" + strings.Repeat("7", 64), ObservedAt: leaseAt}})
	if err != nil {
		t.Fatal(err)
	}
	authorization := &policyv1.AuthorizationDecision{Name: project + "/authorizationDecisions/tool-1", Uid: "authorization-tool-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalRef: identity.Principal, Action: "tool.execute", Resource: clone(definition.GetEligibleTools()[0]), IntentDigest: "sha256:" + strings.Repeat("8", 64), Policies: []*policyv1.PolicyReference{policy}, Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW, ReasonCode: "allowed", SafeReason: "bounded tool allowed", EvaluatedAt: timestamppb.New(at.Add(4 * time.Second)), ExpireTime: timestamppb.New(at.Add(time.Minute)), ContextDigest: "sha256:" + strings.Repeat("9", 64), DecisionDigest: "sha256:" + strings.Repeat("a", 64)}
	stepAt := at.Add(4 * time.Second)
	stepNameValue := stepName(run.GetName(), 1)
	toolCall := &agentv1.ToolCall{Context: &commonv1.CommandContext{RequestId: "tool-call-1", IdempotencyKey: "tool-call-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(stepAt.Add(30 * time.Second)), CanonicalRequestDigest: "sha256:" + strings.Repeat("1", 64)}, CallId: "call-1", AgentRunName: run.GetName(), AgentStepName: stepNameValue, Tool: clone(definition.GetEligibleTools()[0]), ToolVersion: "4", Authorization: authorization, InputDigest: "sha256:" + strings.Repeat("2", 64), Parameters: integrationArtifact("7"), InputArtifacts: []*artifactv1.ArtifactRef{integrationArtifact("8")}, Deadline: timestamppb.New(stepAt.Add(30 * time.Second)), BudgetReservation: clone(run.GetBudgetReservation()), ExpectedOutputSchema: integrationArtifact("9"), SideEffectClass: "read-only", OutputClassification: "internal"}
	stepInput := &agentv1.AgentStep{Run: &commonv1.ResourceRef{ResourceType: "agent_run", ResourceId: "run-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: run.GetRevision(), Name: run.GetName(), Etag: run.GetEtag()}, Sequence: 1, Kind: agentv1.AgentStepKind_AGENT_STEP_KIND_TOOL, State: agentv1.AgentStepState_AGENT_STEP_STATE_DISPATCHED, PolicyDecisions: []*policyv1.AuthorizationDecision{authorization}, Observations: []*artifactv1.ArtifactRef{integrationArtifact("a")}, Decision: &agentv1.AgentDecision{DecisionId: "decision-1", DecisionType: "tool", RationaleSummary: "bounded tool call", Evidence: []*artifactv1.ArtifactRef{integrationArtifact("b")}, NextAction: &agentv1.AgentDecision_ToolCall{ToolCall: toolCall}, ReplayDigest: "sha256:" + strings.Repeat("c", 64)}}
	stepRequest := &internalagentv1.CommitAgentStepRequest{Context: &commonv1.CommandContext{RequestId: "step-commit", IdempotencyKey: "step-commit-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(stepAt.Add(time.Minute))}, AgentStep: stepInput, Fence: clone(lease.Fence), RunEtag: run.GetEtag(), ExpectedNextStepSequence: 1}
	stepDigest, err := canonicalDigest(stepRequest)
	if err != nil {
		t.Fatal(err)
	}
	stepRequest.Context.CanonicalRequestDigest = stepDigest
	worker := Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal, WorkerID: "worker-1", LeaseToken: "wrong-" + token}
	if _, _, _, err = repository.CommitStep(ctx, worker, stepRequest, stepDigest, stepAt); !errors.Is(err, ErrLeaseToken) {
		t.Fatalf("wrong token err=%v", err)
	}
	worker.LeaseToken = token
	storedStep, afterStep, replayedStep, err := repository.CommitStep(ctx, worker, stepRequest, stepDigest, stepAt)
	if err != nil || replayedStep {
		t.Fatalf("step=%v run=%v replay=%v err=%v", storedStep, afterStep, replayedStep, err)
	}
	expectedStep := clone(stepInput)
	expectedStep.Name = stepNameValue
	expectedStep.Uid = storedStep.GetUid()
	expectedStep.Revision = 1
	expectedStep.Etag = storedStep.GetEtag()
	expectedStep.AttemptId = lease.Attempt.GetAttemptId()
	expectedStep.LeaseEpoch = lease.Attempt.GetLeaseEpoch()
	expectedStep.CreateTime = timestamppb.New(stepAt)
	expectedStep.UpdateTime = timestamppb.New(stepAt)
	if !proto.Equal(storedStep, expectedStep) || afterStep.GetState() != agentv1.AgentRunState_AGENT_RUN_STATE_WAITING_FOR_TOOL {
		t.Fatalf("step roundtrip=%v run=%v", storedStep, afterStep)
	}
	storedAgain, runAgain, replayedStep, err := repository.CommitStep(ctx, worker, clone(stepRequest), stepDigest, stepAt.Add(time.Second))
	if err != nil || !replayedStep || !proto.Equal(storedAgain, storedStep) || runAgain.GetRevision() != afterStep.GetRevision() {
		t.Fatalf("step replay=%v run=%v replay=%v err=%v", storedAgain, runAgain, replayedStep, err)
	}
	receiptAt := at.Add(5 * time.Second)
	receipt := &agentv1.ToolReceipt{Name: project + "/toolReceipts/receipt-1", Uid: "receipt-1", CallId: toolCall.GetCallId(), AgentRunName: run.GetName(), AgentStepName: storedStep.GetName(), Tool: clone(toolCall.GetTool()), ToolVersion: toolCall.GetToolVersion(), AttemptId: lease.Attempt.GetAttemptId(), LeaseEpoch: lease.Attempt.GetLeaseEpoch(), Authorization: clone(authorization), IdempotencyKey: "tool-receipt-key", InputDigest: toolCall.GetInputDigest(), ExpectedOutputSchemaDigest: toolCall.GetExpectedOutputSchema().GetDigest(), Outcome: agentv1.ToolExecutionOutcome_TOOL_EXECUTION_OUTCOME_SUCCEEDED, SideEffectState: agentv1.ToolSideEffectState_TOOL_SIDE_EFFECT_STATE_NONE, Outputs: []*artifactv1.ArtifactRef{integrationArtifact("d")}, OutputDigest: "sha256:" + strings.Repeat("e", 64), Usage: &agentv1.ToolResourceUsage{InputBytes: 10, OutputBytes: 20, CpuMilliseconds: 30, AcceleratorMilliseconds: 40, ExternalSpendMicros: 50}, StartedAt: timestamppb.New(receiptAt.Add(-time.Second)), CompletedAt: timestamppb.New(receiptAt), ExecutorIdentity: "worker-1", SourceRevision: "git:abc123", ReceiptDigest: "sha256:" + strings.Repeat("f", 64)}
	receiptRequest := &internalagentv1.CommitToolReceiptRequest{Context: &commonv1.CommandContext{RequestId: "receipt-commit", IdempotencyKey: receipt.GetIdempotencyKey(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(receiptAt.Add(time.Minute))}, ToolReceipt: receipt, RunEtag: afterStep.GetEtag(), Fence: clone(lease.Fence)}
	receiptDigest, err := canonicalDigest(receiptRequest)
	if err != nil {
		t.Fatal(err)
	}
	receiptRequest.Context.CanonicalRequestDigest = receiptDigest
	storedReceipt, afterReceipt, replayedReceipt, err := repository.CommitToolReceipt(ctx, worker, receiptRequest, receiptDigest, receiptAt)
	if err != nil || replayedReceipt || !proto.Equal(storedReceipt, receipt) {
		t.Fatalf("receipt=%v run=%v replay=%v err=%v", storedReceipt, afterReceipt, replayedReceipt, err)
	}
	if afterReceipt.GetBudgetUsage().GetToolCalls() != 1 || afterReceipt.GetBudgetUsage().GetStorageBytes() != 30 {
		t.Fatalf("usage=%v", afterReceipt.GetBudgetUsage())
	}
	storedReceiptAgain, afterReceiptAgain, replayedReceipt, err := repository.CommitToolReceipt(ctx, worker, clone(receiptRequest), receiptDigest, receiptAt.Add(time.Second))
	if err != nil || !replayedReceipt || !proto.Equal(storedReceiptAgain, receipt) || afterReceiptAgain.GetRevision() != afterReceipt.GetRevision() {
		t.Fatalf("receipt replay=%v run=%v replay=%v err=%v", storedReceiptAgain, afterReceiptAgain, replayedReceipt, err)
	}
	terminalAt := at.Add(6 * time.Second)
	terminalResult := integrationArtifact("f")
	terminalInput := &agentv1.AgentStep{Run: &commonv1.ResourceRef{ResourceType: "agent_run", ResourceId: "run-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: afterReceipt.GetRevision(), Name: run.GetName(), Etag: afterReceipt.GetEtag()}, Sequence: 2, Kind: agentv1.AgentStepKind_AGENT_STEP_KIND_TERMINAL, State: agentv1.AgentStepState_AGENT_STEP_STATE_SUCCEEDED, Decision: &agentv1.AgentDecision{DecisionId: "decision-2", DecisionType: "terminal", RationaleSummary: "bounded work complete", NextAction: &agentv1.AgentDecision_TerminalResult{TerminalResult: terminalResult}, ReplayDigest: "sha256:" + strings.Repeat("1", 64)}, Output: integrationArtifact("2")}
	terminalRequest := &internalagentv1.CommitAgentStepRequest{Context: &commonv1.CommandContext{RequestId: "terminal-commit", IdempotencyKey: "terminal-commit-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(terminalAt.Add(time.Minute))}, AgentStep: terminalInput, Fence: clone(lease.Fence), RunEtag: afterReceipt.GetEtag(), ExpectedNextStepSequence: 2}
	terminalDigest, err := canonicalDigest(terminalRequest)
	if err != nil {
		t.Fatal(err)
	}
	terminalRequest.Context.CanonicalRequestDigest = terminalDigest
	terminalStep, completed, replayedTerminal, err := repository.CommitStep(ctx, worker, terminalRequest, terminalDigest, terminalAt)
	if err != nil || replayedTerminal {
		t.Fatalf("terminal step=%v run=%v replay=%v err=%v", terminalStep, completed, replayedTerminal, err)
	}
	if completed.GetState() != agentv1.AgentRunState_AGENT_RUN_STATE_SUCCEEDED || !proto.Equal(completed.GetRunManifest(), terminalInput.GetOutput()) || !proto.Equal(completed.GetOutput(), terminalResult) || completed.GetEndTime() == nil {
		t.Fatalf("completed run=%v", completed)
	}
	steps, next, _, err := repository.ListSteps(ctx, identity, StepPage{Limit: 2, Parent: run.GetName()})
	if err != nil || len(steps) != 2 || next != "" || !proto.Equal(steps[0], storedStep) || !proto.Equal(steps[1], terminalStep) {
		t.Fatalf("steps=%v next=%q err=%v", steps, next, err)
	}
	cancelStartAt := at.Add(7 * time.Second)
	cancelStart := &internalagentv1.StartAgentRunRequest{Context: &commonv1.CommandContext{RequestId: "cancel-run-start", IdempotencyKey: "cancel-run-start-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(cancelStartAt.Add(time.Minute))}, Parent: project, AgentRunId: "run-cancel", AgentRun: clone(runInput)}
	cancelStartDigest, err := canonicalDigest(cancelStart)
	if err != nil {
		t.Fatal(err)
	}
	cancelStart.Context.CanonicalRequestDigest = cancelStartDigest
	if _, replay, err = repository.StartRun(ctx, identity, cancelStart, cancelStartDigest, cancelStartAt); err != nil || replay {
		t.Fatalf("cancel target start replay=%v err=%v", replay, err)
	}
	cancelTarget, err := repository.GetRun(ctx, identity, runName(identity, "run-cancel"))
	if err != nil {
		t.Fatal(err)
	}
	cancelAt := at.Add(8 * time.Second)
	cancelRequest := &internalagentv1.CancelAgentRunRequest{Context: &commonv1.CommandContext{RequestId: "run-cancel", IdempotencyKey: "run-cancel-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(cancelAt.Add(time.Minute))}, Name: cancelTarget.GetName(), Etag: cancelTarget.GetEtag(), Reason: "bounded operator cancellation"}
	cancelDigest, err := canonicalDigest(cancelRequest)
	if err != nil {
		t.Fatal(err)
	}
	cancelRequest.Context.CanonicalRequestDigest = cancelDigest
	cancelOperation, replayedCancel, err := repository.CancelRun(ctx, identity, cancelRequest, cancelDigest, cancelAt)
	if err != nil || replayedCancel || cancelOperation.GetState() != operationv1.OperationState_OPERATION_STATE_CANCELLING {
		t.Fatalf("cancel operation=%v replay=%v err=%v", cancelOperation, replayedCancel, err)
	}
	cancelReplay, replayedCancel, err := repository.CancelRun(ctx, identity, clone(cancelRequest), cancelDigest, cancelAt.Add(time.Second))
	if err != nil || !replayedCancel || cancelReplay.GetOperationId() != cancelOperation.GetOperationId() {
		t.Fatalf("cancel replay operation=%v replay=%v err=%v", cancelReplay, replayedCancel, err)
	}
	cancelling, err := repository.GetRun(ctx, identity, cancelTarget.GetName())
	if err != nil || cancelling.GetState() != agentv1.AgentRunState_AGENT_RUN_STATE_CANCELLING || !cancelling.GetCancellationRequested() || cancelling.GetRevision() != cancelTarget.GetRevision()+1 {
		t.Fatalf("cancelling run=%v err=%v", cancelling, err)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	var events, audits, receipts int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1),(SELECT count(*) FROM workflow_agent_command_receipts WHERE tenant_id=$1 AND action LIKE 'agent.%')`, identity.TenantID).Scan(&events, &audits, &receipts); err != nil {
		t.Fatal(err)
	}
	if events != 12 || audits != 8 || receipts != 8 {
		t.Fatalf("events=%d audits=%d receipts=%d", events, audits, receipts)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,event_type`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	types := map[string]int{}
	var dispatched *agentv1.AgentStepDispatched
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
		types[string(payload.ProtoReflect().Descriptor().FullName())]++
		if value, ok := payload.(*agentv1.AgentStepDispatched); ok {
			dispatched = value
		}
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		t.Fatal(err)
	}
	for eventType, count := range map[string]int{"mindclade.events.agent.v1.AgentDefinitionCreated": 1, "mindclade.events.agent.v1.AgentDefinitionUpdated": 1, "mindclade.events.agent.v1.AgentRunStarted": 2, "mindclade.events.agent.v1.AgentCancellationRequested": 1, "mindclade.events.agent.v1.AgentStepDispatched": 1, "mindclade.events.agent.v1.AgentStepCommitted": 1, "mindclade.events.agent.v1.ToolReceiptCommitted": 1, "mindclade.events.agent.v1.AgentRunCompleted": 1, "mindclade.events.job.v1.JobRequested": 2, "mindclade.events.job.v1.AttemptLeased": 1} {
		if types[eventType] != count {
			t.Fatalf("event %s count=%d want=%d all=%v", eventType, types[eventType], count, types)
		}
	}
	if dispatched == nil || !proto.Equal(dispatched.GetStep(), storedStep) || dispatched.GetAttemptId() != lease.Fence.GetAttemptId() ||
		dispatched.GetLeaseEpoch() != lease.Fence.GetLeaseEpoch() || dispatched.GetWorkerProfile().GetResourceId() != worker.WorkerID ||
		dispatched.GetWorkerProfile().GetName() != project+"/workerProfiles/"+worker.WorkerID || !proto.Equal(dispatched.GetDispatchDeadline(), lease.Fence.GetDeadline()) {
		t.Fatalf("AgentStepDispatched payload is not populated from the accepted fenced step: %v", dispatched)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
	assertAgentRLS(t, ctx, db, suffix, identity, 2)
	tamper, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tamper.ExecContext(ctx, `UPDATE agent_steps SET uid='tampered' WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, storedStep.GetName()); err == nil {
		t.Fatal("immutable agent step update succeeded")
	}
	_ = tamper.Rollback()
}

func assertAgentRLS(t *testing.T, ctx context.Context, db *sql.DB, suffix string, identity Identity, runCount int) {
	t.Helper()
	var superuser, bypassRLS, createRole bool
	if err := db.QueryRowContext(ctx, `SELECT rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user`).Scan(&superuser, &bypassRLS, &createRole); err != nil {
		t.Fatal(err)
	}
	role := ""
	if superuser || bypassRLS {
		if !createRole {
			t.Fatal("integration identity bypasses RLS and cannot create qualification role")
		}
		role = "mindclade_agent_rls_" + suffix
		if _, err := db.ExecContext(ctx, fmt.Sprintf(`CREATE ROLE %s NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`, role)); err != nil {
			t.Fatal(err)
		}
		cleanupContext := context.WithoutCancel(ctx)
		t.Cleanup(func() {
			if _, cleanupErr := db.ExecContext(cleanupContext, `DROP OWNED BY `+role+`; DROP ROLE `+role); cleanupErr != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
				t.Errorf("drop agent RLS role: %v", cleanupErr)
			}
		})
		if _, err := db.ExecContext(ctx, `GRANT SELECT ON agent_definitions,agent_runs,agent_steps,agent_tool_receipts TO `+role); err != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
			t.Fatal(err)
		}
	}
	var forced int
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(ARRAY['agent_definitions','agent_definition_non_goals','agent_definition_tools','agent_definition_policies','agent_runs','agent_run_policies','agent_steps','agent_step_policy_decisions','agent_step_observations','agent_step_decisions','agent_decision_evidence','agent_tool_calls','agent_tool_call_approvals','agent_tool_call_inputs','agent_tool_receipts','agent_tool_receipt_approvals','agent_tool_receipt_outputs','workflow_agent_command_receipts']) AND relrowsecurity AND relforcerowsecurity`).Scan(&forced); err != nil || forced != 18 {
		t.Fatalf("agent FORCE RLS count=%d err=%v", forced, err)
	}
	tx, err := db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if role != "" {
		if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE `+role); err != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
			t.Fatal(err)
		}
	}
	var visible int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM agent_runs`).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("unbound visible=%d err=%v", visible, err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id',$1,true),set_config('row_security','on',true)`, identity.TenantID); err != nil {
		t.Fatal(err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM agent_runs WHERE project_id=$1`, identity.ProjectID).Scan(&visible); err != nil || visible != runCount {
		t.Fatalf("bound runs visible=%d want=%d err=%v", visible, runCount, err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM agent_runs WHERE tenant_id='different-tenant'`).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("cross-tenant rows=%d err=%v", visible, err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
}
