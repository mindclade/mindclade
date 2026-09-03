package mindclade

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type agentSDKServer struct {
	internalagentv1.UnimplementedAgentServiceServer
	mu       sync.Mutex
	contexts []*commonv1.CommandContext
	leases   []string
	parent   string
}

func (server *agentSDKServer) capture(ctx context.Context, command *commonv1.CommandContext) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.contexts = append(server.contexts, cloneGenerated(command))
	values, _ := metadata.FromIncomingContext(ctx)
	server.leases = append(server.leases, strings.Join(values.Get("x-mindclade-lease-token"), ""))
}

func agentOperation(id string) *jobv1.Operation { return &jobv1.Operation{OperationId: id} }

func (server *agentSDKServer) CreateAgentDefinition(ctx context.Context, request *internalagentv1.CreateAgentDefinitionRequest) (*internalagentv1.CreateAgentDefinitionResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalagentv1.CreateAgentDefinitionResponse{Operation: agentOperation("operations/create-agent-definition")}, nil
}

func (server *agentSDKServer) UpdateAgentDefinition(ctx context.Context, request *internalagentv1.UpdateAgentDefinitionRequest) (*internalagentv1.UpdateAgentDefinitionResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalagentv1.UpdateAgentDefinitionResponse{Operation: agentOperation("operations/update-agent-definition")}, nil
}

func (server *agentSDKServer) GetAgentDefinition(_ context.Context, request *internalagentv1.GetAgentDefinitionRequest) (*internalagentv1.GetAgentDefinitionResponse, error) {
	return &internalagentv1.GetAgentDefinitionResponse{AgentDefinition: &agentv1.AgentDefinition{Name: request.GetName()}}, nil
}

func (*agentSDKServer) ListAgentDefinitions(_ context.Context, request *internalagentv1.ListAgentDefinitionsRequest) (*internalagentv1.ListAgentDefinitionsResponse, error) {
	return &internalagentv1.ListAgentDefinitionsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-definition"}}, nil
}

func (server *agentSDKServer) StartAgentRun(ctx context.Context, request *internalagentv1.StartAgentRunRequest) (*internalagentv1.StartAgentRunResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalagentv1.StartAgentRunResponse{Operation: agentOperation("operations/start-agent-run")}, nil
}

func (server *agentSDKServer) GetAgentRun(_ context.Context, request *internalagentv1.GetAgentRunRequest) (*internalagentv1.GetAgentRunResponse, error) {
	return &internalagentv1.GetAgentRunResponse{AgentRun: &agentv1.AgentRun{Name: request.GetName(), NextStepSequence: 2}}, nil
}

func (*agentSDKServer) ListAgentRuns(_ context.Context, request *internalagentv1.ListAgentRunsRequest) (*internalagentv1.ListAgentRunsResponse, error) {
	return &internalagentv1.ListAgentRunsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-run"}}, nil
}

func (server *agentSDKServer) CancelAgentRun(ctx context.Context, request *internalagentv1.CancelAgentRunRequest) (*internalagentv1.CancelAgentRunResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalagentv1.CancelAgentRunResponse{Operation: agentOperation("operations/cancel-agent-run")}, nil
}

func (*agentSDKServer) GetAgentStep(_ context.Context, request *internalagentv1.GetAgentStepRequest) (*internalagentv1.GetAgentStepResponse, error) {
	return &internalagentv1.GetAgentStepResponse{AgentStep: &agentv1.AgentStep{Name: request.GetName(), Sequence: 1}}, nil
}

func (*agentSDKServer) ListAgentSteps(_ context.Context, request *internalagentv1.ListAgentStepsRequest) (*internalagentv1.ListAgentStepsResponse, error) {
	return &internalagentv1.ListAgentStepsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-step"}}, nil
}

func (server *agentSDKServer) CommitAgentStep(ctx context.Context, request *internalagentv1.CommitAgentStepRequest) (*internalagentv1.CommitAgentStepResponse, error) {
	server.capture(ctx, request.GetContext())
	step := cloneGenerated(request.GetAgentStep())
	step.Name = step.GetRun().GetName() + "/agentSteps/" + "1"
	run := &agentv1.AgentRun{Name: step.GetRun().GetName(), NextStepSequence: step.GetSequence() + 1}
	return &internalagentv1.CommitAgentStepResponse{AgentStep: step, AgentRun: run}, nil
}

func (server *agentSDKServer) CommitToolReceipt(ctx context.Context, request *internalagentv1.CommitToolReceiptRequest) (*internalagentv1.CommitToolReceiptResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalagentv1.CommitToolReceiptResponse{ToolReceipt: cloneGenerated(request.GetToolReceipt()), AgentRun: &agentv1.AgentRun{Name: request.GetToolReceipt().GetAgentRunName()}}, nil
}

func agentSDKFixture(t *testing.T) (*AgentService, *agentSDKServer) {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	server := &agentSDKServer{parent: "tenants/tenant-a/projects/project-a"}
	internalagentv1.RegisterAgentServiceServer(grpcServer, server)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	config := defaultConfig()
	config.TenantID, config.ProjectID, config.PrincipalID = "tenant-a", "project-a", "principal-a"
	config.DefaultRPCTimeout = time.Second
	connection, err := grpc.NewClient(
		"passthrough:///bufnet",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(unaryInterceptor(config)),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := &Client{config: config}
	return &AgentService{client: client, transport: internalagentv1.NewAgentServiceClient(connection)}, server
}

func agentSDKRef(parent, kind, collection, id string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, Name: parent + "/" + collection + "/" + id}
}

func agentSDKDigest(value string) string {
	digest := sha256.Sum256([]byte(value))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func TestAgentFacadeCoversAllGeneratedRPCsAndPreservesInputs(t *testing.T) {
	service, server := agentSDKFixture(t)
	parent := server.parent
	definitionName := parent + "/agentDefinitions/definition-1"
	runName := parent + "/agentRuns/run-1"
	stepName := runName + "/agentSteps/1"
	receiptName := parent + "/toolReceipts/receipt-1"
	definition := &agentv1.AgentDefinition{
		WorkflowDefinition: agentSDKRef(parent, "workflow_definition", "workflowDefinitions", "workflow-1"),
		EvaluationSuite:    agentSDKRef(parent, "evaluation_suite", "evaluationSuites", "evaluation-1"),
		EligibleTools:      []*commonv1.ResourceRef{agentSDKRef(parent, "tool", "tools", "tool-1")},
	}
	create := &internalagentv1.CreateAgentDefinitionRequest{Context: &commonv1.CommandContext{IdempotencyKey: "create-key", PrincipalId: "forged"}, AgentDefinitionId: "definition-1", AgentDefinition: definition}
	originalCreate := cloneGenerated(create)
	if operation, err := service.CreateDefinition(context.Background(), create); err != nil || operation.GetOperationId() == "" || !proto.Equal(create, originalCreate) {
		t.Fatalf("create operation=%v unchanged=%v err=%v", operation, proto.Equal(create, originalCreate), err)
	}
	update := &internalagentv1.UpdateAgentDefinitionRequest{AgentDefinition: &agentv1.AgentDefinition{Name: definitionName, WorkflowDefinition: cloneGenerated(definition.WorkflowDefinition), EvaluationSuite: cloneGenerated(definition.EvaluationSuite), EligibleTools: cloneGeneratedSlice(definition.EligibleTools)}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"purpose"}}, Etag: "etag-1"}
	if _, err := service.UpdateDefinition(context.Background(), update); err != nil {
		t.Fatal(err)
	}
	if value, err := service.GetDefinition(context.Background(), definitionName, "etag-1"); err != nil || value.GetName() != definitionName {
		t.Fatalf("definition=%v err=%v", value, err)
	}
	if page, err := service.ListDefinitions(context.Background(), &internalagentv1.ListAgentDefinitionsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "opaque-definition" {
		t.Fatalf("definition page=%v err=%v", page, err)
	}
	run := &agentv1.AgentRun{Definition: agentSDKRef(parent, "agent_definition", "agentDefinitions", "definition-1"), BudgetReservation: agentSDKRef(parent, "budget_reservation", "budgetReservations", "budget-1")}
	start := &internalagentv1.StartAgentRunRequest{Context: &commonv1.CommandContext{IdempotencyKey: "run-key", PrincipalId: "forged"}, AgentRunId: "run-1", AgentRun: run}
	originalStart := cloneGenerated(start)
	if _, err := service.StartRun(context.Background(), start); err != nil || !proto.Equal(start, originalStart) {
		t.Fatalf("start unchanged=%v err=%v", proto.Equal(start, originalStart), err)
	}
	if value, err := service.GetRun(context.Background(), runName, ""); err != nil || value.GetName() != runName {
		t.Fatalf("run=%v err=%v", value, err)
	}
	if page, err := service.ListRuns(context.Background(), &internalagentv1.ListAgentRunsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "opaque-run" {
		t.Fatalf("run page=%v err=%v", page, err)
	}
	if _, err := service.CancelRun(context.Background(), &internalagentv1.CancelAgentRunRequest{Name: runName, Etag: "etag-2", Reason: "operator request"}); err != nil {
		t.Fatal(err)
	}
	if value, err := service.GetStep(context.Background(), stepName); err != nil || value.GetName() != stepName {
		t.Fatalf("step=%v err=%v", value, err)
	}
	if page, err := service.ListSteps(context.Background(), &internalagentv1.ListAgentStepsRequest{Parent: runName, Page: &commonv1.PageRequest{PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "opaque-step" {
		t.Fatalf("step page=%v err=%v", page, err)
	}

	leaseToken := "scheduler-issued-agent-token"
	fence := &jobv1.LeaseFence{TenantId: "tenant-a", ProjectId: "project-a", JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(time.Minute)), LeaseTokenDigest: agentSDKDigest(leaseToken)}
	step := &agentv1.AgentStep{Run: agentSDKRef(parent, "agent_run", "agentRuns", "run-1"), Sequence: 1}
	commitStep := &internalagentv1.CommitAgentStepRequest{Context: &commonv1.CommandContext{IdempotencyKey: "step-key", PrincipalId: "forged"}, AgentStep: step, Fence: fence, RunEtag: "etag-3", ExpectedNextStepSequence: 1}
	originalStep := cloneGenerated(commitStep)
	accepted, reconciled, err := service.CommitStep(context.Background(), commitStep, WithLeaseToken(leaseToken))
	if err != nil || accepted.GetName() != stepName || reconciled.GetName() != runName || !proto.Equal(commitStep, originalStep) {
		t.Fatalf("accepted=%v run=%v unchanged=%v err=%v", accepted, reconciled, proto.Equal(commitStep, originalStep), err)
	}
	receipt := &agentv1.ToolReceipt{Name: receiptName, CallId: "call-1", AgentRunName: runName, AgentStepName: stepName, Tool: agentSDKRef(parent, "tool", "tools", "tool-1")}
	commitReceipt := &internalagentv1.CommitToolReceiptRequest{Context: &commonv1.CommandContext{IdempotencyKey: "receipt-key", PrincipalId: "forged"}, ToolReceipt: receipt, RunEtag: "etag-4", Fence: cloneGenerated(fence)}
	originalReceipt := cloneGenerated(commitReceipt)
	acceptedReceipt, receiptRun, err := service.CommitToolReceipt(context.Background(), commitReceipt, WithLeaseToken(leaseToken))
	if err != nil || acceptedReceipt.GetName() != receiptName || receiptRun.GetName() != runName || !proto.Equal(commitReceipt, originalReceipt) {
		t.Fatalf("receipt=%v run=%v unchanged=%v err=%v", acceptedReceipt, receiptRun, proto.Equal(commitReceipt, originalReceipt), err)
	}

	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.contexts) != 6 {
		t.Fatalf("captured mutation contexts=%d", len(server.contexts))
	}
	for index, command := range server.contexts {
		if command.GetPrincipalId() != "principal-a" || command.GetTenantId() != "tenant-a" || command.GetProjectId() != "project-a" || command.GetCanonicalRequestDigest() == "" {
			t.Fatalf("context[%d]=%v", index, command)
		}
	}
	if server.leases[4] != leaseToken || server.leases[5] != leaseToken {
		t.Fatalf("fenced lease metadata=%q", server.leases)
	}
	for _, value := range server.leases[:4] {
		if value != "" {
			t.Fatalf("lease leaked to non-fenced mutation: %q", server.leases)
		}
	}
}

func TestAgentFacadeRejectsMissingLeaseAndInvalidPagination(t *testing.T) {
	service, _ := agentSDKFixture(t)
	parent := "tenants/tenant-a/projects/project-a"
	runName := parent + "/agentRuns/run-1"
	fence := &jobv1.LeaseFence{TenantId: "tenant-a", ProjectId: "project-a", JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(time.Minute)), LeaseTokenDigest: agentSDKDigest("token")}
	_, _, err := service.CommitStep(context.Background(), &internalagentv1.CommitAgentStepRequest{AgentStep: &agentv1.AgentStep{Run: agentSDKRef(parent, "agent_run", "agentRuns", "run-1"), Sequence: 1}, Fence: fence, RunEtag: "etag", ExpectedNextStepSequence: 1})
	if err == nil {
		t.Fatal("CommitStep accepted a missing raw lease token")
	}
	_, err = service.ListSteps(context.Background(), &internalagentv1.ListAgentStepsRequest{Parent: runName, Page: &commonv1.PageRequest{PageSize: agentMaximumPageSize + 1}})
	if err == nil {
		t.Fatal("ListSteps accepted an oversized page")
	}
}

func TestClientRegistersAgentFacade(t *testing.T) {
	client, _, _ := testClient(t)
	if client.Agents == nil || client.Agents.transport == nil {
		t.Fatal("client did not register the generated AgentService facade")
	}
}

func TestAgentMutationRetryRegistryIsCompleteAndFailClosed(t *testing.T) {
	config := defaultConfig()
	config.TenantID, config.ProjectID, config.PrincipalID = "tenant-a", "project-a", "principal-a"
	metadata := requestMetadata{
		idempotencyKey: "agent-retry-key",
		requestID:      "agent-request-id",
		traceID:        "agent-trace-id",
	}
	tests := []struct {
		method  string
		request proto.Message
	}{
		{"/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition", &internalagentv1.CreateAgentDefinitionRequest{}},
		{"/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition", &internalagentv1.UpdateAgentDefinitionRequest{}},
		{"/mindclade.internal.agent.v1.AgentService/StartAgentRun", &internalagentv1.StartAgentRunRequest{}},
		{"/mindclade.internal.agent.v1.AgentService/CancelAgentRun", &internalagentv1.CancelAgentRunRequest{}},
		{"/mindclade.internal.agent.v1.AgentService/CommitAgentStep", &internalagentv1.CommitAgentStepRequest{}},
		{"/mindclade.internal.agent.v1.AgentService/CommitToolReceipt", &internalagentv1.CommitToolReceiptRequest{}},
	}
	ctx := contextWithDeadline(t)
	for _, test := range tests {
		t.Run(test.method, func(t *testing.T) {
			digest, err := deterministicDigest(test.request)
			if err != nil {
				t.Fatal(err)
			}
			setCommandContext(test.request, commandContext(config, ctx, metadata, digest))
			if !retryPermitted(test.method, test.request, metadata, config) {
				t.Fatal("fully bound agent mutation was not retry-safe")
			}
			mismatched := metadata
			mismatched.idempotencyKey = "different-key"
			if retryPermitted(test.method, test.request, mismatched, config) {
				t.Fatal("mismatched metadata promoted agent mutation retry safety")
			}
		})
	}
}

func cloneGeneratedSlice[T proto.Message](values []T) []T {
	result := make([]T, len(values))
	for index, value := range values {
		result[index] = cloneGenerated(value)
	}
	return result
}
