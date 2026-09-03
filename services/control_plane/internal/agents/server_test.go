package agents

import (
	"context"
	"errors"
	"net"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

type staticIdentityResolver struct{ identity Identity }

func (resolver staticIdentityResolver) Resolve(context.Context) (Identity, error) {
	return resolver.identity, nil
}

type fixedClock struct{ now time.Time }

func (clock fixedClock) Now() time.Time { return clock.now }

type fakeRepository struct {
	createDefinition func(context.Context, Identity, *internalagentv1.CreateAgentDefinitionRequest, string, time.Time) (*operationv1.Operation, bool, error)
	commitStep       func(context.Context, Identity, *internalagentv1.CommitAgentStepRequest, string, time.Time) (*agentv1.AgentStep, *agentv1.AgentRun, bool, error)
}

func (repository fakeRepository) CreateDefinition(ctx context.Context, i Identity, r *internalagentv1.CreateAgentDefinitionRequest, d string, t time.Time) (*operationv1.Operation, bool, error) {
	return repository.createDefinition(ctx, i, r, d, t)
}

func (fakeRepository) UpdateDefinition(context.Context, Identity, *internalagentv1.UpdateAgentDefinitionRequest, string, time.Time) (*operationv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (fakeRepository) GetDefinition(context.Context, Identity, string) (*agentv1.AgentDefinition, error) {
	return nil, ErrNotFound
}

func (fakeRepository) ListDefinitions(context.Context, Identity, DefinitionPage) ([]*agentv1.AgentDefinition, string, time.Time, error) {
	return nil, "", time.Unix(1, 0).UTC(), nil
}

func (fakeRepository) StartRun(context.Context, Identity, *internalagentv1.StartAgentRunRequest, string, time.Time) (*operationv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (fakeRepository) GetRun(context.Context, Identity, string) (*agentv1.AgentRun, error) {
	return nil, ErrNotFound
}

func (fakeRepository) ListRuns(context.Context, Identity, RunPage) ([]*agentv1.AgentRun, string, time.Time, error) {
	return nil, "", time.Unix(1, 0).UTC(), nil
}

func (fakeRepository) CancelRun(context.Context, Identity, *internalagentv1.CancelAgentRunRequest, string, time.Time) (*operationv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (fakeRepository) GetStep(context.Context, Identity, string) (*agentv1.AgentStep, error) {
	return nil, ErrNotFound
}

func (fakeRepository) ListSteps(context.Context, Identity, StepPage) ([]*agentv1.AgentStep, string, time.Time, error) {
	return nil, "", time.Unix(1, 0).UTC(), nil
}

func (repository fakeRepository) CommitStep(ctx context.Context, i Identity, r *internalagentv1.CommitAgentStepRequest, d string, t time.Time) (*agentv1.AgentStep, *agentv1.AgentRun, bool, error) {
	return repository.commitStep(ctx, i, r, d, t)
}

func (fakeRepository) CommitToolReceipt(context.Context, Identity, *internalagentv1.CommitToolReceiptRequest, string, time.Time) (*agentv1.ToolReceipt, *agentv1.AgentRun, bool, error) {
	return nil, nil, false, ErrNotFound
}

func strings64(value string) string { return strings.Repeat(value, 64)[:64] }
func testArtifact(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings64(seed), MediaType: "application/vnd.mindclade.test+json", SizeBytes: 12, ArtifactKind: "test", SchemaId: "mindclade.test.v1"}
}

func testReference(identity Identity, kind, id string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/" + kind + "s/" + id, Etag: "sha256:" + strings64("e")}
}

func testPolicy(identity Identity, now time.Time) *policyv1.PolicyReference {
	return &policyv1.PolicyReference{Name: projectParent(identity) + "/policies/safety", Uid: "policy-1", PolicyType: "safety", Version: "1.0.0", Digest: "sha256:" + strings64("1"), Document: testArtifact("a"), ResourceRevision: 1, EffectiveTime: timestamppb.New(now.Add(-time.Hour))}
}

func validDefinition(identity Identity, now time.Time) *agentv1.AgentDefinition {
	return &agentv1.AgentDefinition{DisplayName: "Bounded analyst", SemanticVersion: "1.0.0", State: agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DRAFT, Purpose: "bounded analysis", NonGoals: []string{"unbounded execution"}, Definition: testArtifact("b"), WorkflowDefinition: testReference(identity, "workflow_definition", "workflow-1"), EligibleTools: []*commonv1.ResourceRef{testReference(identity, "tool", "search")}, PolicySnapshots: []*policyv1.PolicyReference{testPolicy(identity, now)}, InputSchema: testArtifact("c"), OutputSchema: testArtifact("d"), ModelCapability: "reasoning", EvaluationSuite: testReference(identity, "evaluation_suite", "suite-1"), Budget: &agentv1.AgentBudgetEnvelope{MaximumModelTokens: 1000, MaximumIterations: 8, MaximumToolCalls: 4, MaximumConcurrentBranches: 1, MaximumStorageBytes: 1 << 20, MaximumWallTime: durationpb.New(time.Minute), MaximumAcceleratorTime: durationpb.New(time.Second), MaximumCpuTime: durationpb.New(time.Minute)}, Limits: &agentv1.AgentExecutionLimits{MaximumDepth: 4, MaximumFanOut: 2, MaximumObservationsPerStep: 16, MaximumArtifactReferencesPerCall: 16}, QualificationLevel: "dev"}
}

func TestNetworkCreateAgentDefinitionUsesGeneratedServiceAndClones(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1", Roles: map[string]struct{}{"agent-admin": {}}}
	called := false
	repository := fakeRepository{createDefinition: func(_ context.Context, got Identity, request *internalagentv1.CreateAgentDefinitionRequest, digest string, at time.Time) (*operationv1.Operation, bool, error) {
		called = true
		if got.TenantID != identity.TenantID || got.ProjectID != identity.ProjectID || got.Principal != identity.Principal {
			t.Fatalf("identity=%+v", got)
		}
		if !validSHA256(digest) {
			t.Fatalf("digest=%q", digest)
		}
		if !at.Equal(now) {
			t.Fatalf("at=%s", at)
		}
		request.AgentDefinitionId = "mutated"
		return &operationv1.Operation{OperationId: "operations/op-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: "jobs/job-1", State: operationv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 1, Done: true, Etag: "sha256:" + strings64("9"), CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now)}, false, nil
	}}
	codec, err := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, staticIdentityResolver{identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{now})
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	if err = Register(grpcServer, server); err != nil {
		t.Fatal(err)
	}
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalagentv1.NewAgentServiceClient(connection)
	request := &internalagentv1.CreateAgentDefinitionRequest{Context: &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "idem-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(now.Add(time.Minute))}, Parent: projectParent(identity), AgentDefinitionId: "agent-1", AgentDefinition: validDefinition(identity, now)}
	response, err := client.CreateAgentDefinition(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if !called || response.GetOperation().GetOperationId() != "operations/op-1" {
		t.Fatalf("response=%v called=%v", response, called)
	}
	if request.GetAgentDefinitionId() != "agent-1" {
		t.Fatal("server leaked mutable request alias")
	}
}

func TestCreateAgentDefinitionRejectsIdentityOverrideAndMissingRole(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1", Roles: map[string]struct{}{"agent-admin": {}}}
	codec, _ := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	repository := fakeRepository{createDefinition: func(context.Context, Identity, *internalagentv1.CreateAgentDefinitionRequest, string, time.Time) (*operationv1.Operation, bool, error) {
		t.Fatal("repository called")
		return nil, false, nil
	}}
	server, _ := NewServer(repository, staticIdentityResolver{identity}, codec)
	server.withClock(fixedClock{now})
	request := &internalagentv1.CreateAgentDefinitionRequest{Context: &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "idem-1", TenantId: "other", ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(now.Add(time.Minute))}, Parent: projectParent(identity), AgentDefinitionId: "agent-1", AgentDefinition: validDefinition(identity, now)}
	_, err := server.CreateAgentDefinition(context.Background(), request)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("code=%s err=%v", status.Code(err), err)
	}
	identity.Roles = nil
	server.identities = staticIdentityResolver{identity}
	request.Context.TenantId = identity.TenantID
	_, err = server.CreateAgentDefinition(context.Background(), request)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("missing role code=%s err=%v", status.Code(err), err)
	}
}

func TestAgentPageTokensAreSignedAndQueryBound(t *testing.T) {
	t.Parallel()
	codec, err := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "agent-steps", Tenant: "tenant-1", Project: "project-1", Parent: "tenants/tenant-1/projects/project-1/agentRuns/run-1", Order: "sequence"}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, Parent: expected.Parent, Order: expected.Order, AfterSequence: 7})
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := codec.decode(encoded, expected)
	if err != nil || decoded.AfterSequence != 7 {
		t.Fatalf("decoded=%+v err=%v", decoded, err)
	}
	tampered := []byte(encoded)
	if tampered[len(tampered)-1] == 'A' {
		tampered[len(tampered)-1] = 'B'
	} else {
		tampered[len(tampered)-1] = 'A'
	}
	if _, err = codec.decode(string(tampered), expected); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("tampered err=%v", err)
	}
	expected.Parent += "-other"
	if _, err = codec.decode(encoded, expected); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("rebound err=%v", err)
	}
}

func TestCommitAgentStepRequiresWorkerTransportAuthority(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "worker-principal", WorkerID: "worker-1", LeaseToken: "lease-token", Roles: map[string]struct{}{"agent-worker": {}}}
	codec, _ := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	called := false
	repository := fakeRepository{createDefinition: func(context.Context, Identity, *internalagentv1.CreateAgentDefinitionRequest, string, time.Time) (*operationv1.Operation, bool, error) {
		return nil, false, ErrNotFound
	}, commitStep: func(_ context.Context, got Identity, request *internalagentv1.CommitAgentStepRequest, digest string, at time.Time) (*agentv1.AgentStep, *agentv1.AgentRun, bool, error) {
		called = true
		if got.WorkerID != "worker-1" || !validSHA256(digest) || !at.Equal(now) {
			t.Fatalf("identity=%+v digest=%s at=%s", got, digest, at)
		}
		step := clone(request.GetAgentStep())
		step.Name = stepName(step.GetRun().GetName(), 1)
		step.Uid = "step-1"
		step.Revision = 1
		step.Etag = "sha256:" + strings64("e")
		step.AttemptId = request.GetFence().GetAttemptId()
		step.LeaseEpoch = 1
		step.CreateTime = timestamppb.New(now)
		step.UpdateTime = timestamppb.New(now)
		return step, &agentv1.AgentRun{Name: step.GetRun().GetName(), Revision: 2, Etag: "sha256:" + strings64("f")}, false, nil
	}}
	server, _ := NewServer(repository, staticIdentityResolver{identity}, codec)
	server.withClock(fixedClock{now})
	runRef := testReference(identity, "agent_run", "run-1")
	runRef.Name = runName(identity, "run-1")
	decision := &agentv1.AgentDecision{DecisionId: "decision-1", DecisionType: "wait", RationaleSummary: "bounded wait", NextAction: &agentv1.AgentDecision_Wait{Wait: &agentv1.AgentWait{MaximumDuration: durationpb.New(time.Second), CorrelationRef: "event-1"}}, ReplayDigest: "sha256:" + strings64("a")}
	request := &internalagentv1.CommitAgentStepRequest{Context: &commonv1.CommandContext{RequestId: "step-request", IdempotencyKey: "step-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(now.Add(time.Minute))}, AgentStep: &agentv1.AgentStep{Run: runRef, Sequence: 1, Kind: agentv1.AgentStepKind_AGENT_STEP_KIND_WAIT, State: agentv1.AgentStepState_AGENT_STEP_STATE_WAITING, Decision: decision}, Fence: &jobv1.LeaseFence{JobId: "jobs/1", RunId: "runs/1", AttemptId: "attempts/1", LeaseEpoch: 1, Deadline: timestamppb.New(now.Add(time.Minute)), TenantId: identity.TenantID, ProjectId: identity.ProjectID, LeaseTokenDigest: "sha256:" + strings64("b")}, RunEtag: "sha256:" + strings64("c"), ExpectedNextStepSequence: 1}
	response, err := server.CommitAgentStep(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if !called || response.GetAgentStep().GetName() == "" {
		t.Fatalf("response=%v called=%v", response, called)
	}
	identity.WorkerID = ""
	server.identities = staticIdentityResolver{identity}
	_, err = server.CommitAgentStep(context.Background(), request)
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("worker identity code=%s err=%v", status.Code(err), err)
	}
}
