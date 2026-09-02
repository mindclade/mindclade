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

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type workflowSDKServer struct {
	internalworkflowv1.UnimplementedWorkflowServiceServer
	mu             sync.Mutex
	contexts       []*commonv1.CommandContext
	lease          string
	name           string
	definitionName string
}

func (server *workflowSDKServer) capture(ctx context.Context, command *commonv1.CommandContext) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.contexts = append(server.contexts, cloneGenerated(command))
	values, _ := metadata.FromIncomingContext(ctx)
	server.lease = strings.Join(values.Get("x-mindclade-lease-token"), "")
}

func workflowOperation(id string) *jobv1.Operation { return &jobv1.Operation{OperationId: id} }

func (server *workflowSDKServer) CreateWorkflowDefinition(ctx context.Context, request *internalworkflowv1.CreateWorkflowDefinitionRequest) (*internalworkflowv1.CreateWorkflowDefinitionResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalworkflowv1.CreateWorkflowDefinitionResponse{Operation: workflowOperation("operations/create-definition")}, nil
}

func (server *workflowSDKServer) UpdateWorkflowDefinition(ctx context.Context, request *internalworkflowv1.UpdateWorkflowDefinitionRequest) (*internalworkflowv1.UpdateWorkflowDefinitionResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalworkflowv1.UpdateWorkflowDefinitionResponse{Operation: workflowOperation("operations/update-definition")}, nil
}

func (server *workflowSDKServer) GetWorkflowDefinition(context.Context, *internalworkflowv1.GetWorkflowDefinitionRequest) (*internalworkflowv1.GetWorkflowDefinitionResponse, error) {
	return &internalworkflowv1.GetWorkflowDefinitionResponse{WorkflowDefinition: &workflowv1.WorkflowDefinition{Name: server.definitionName}}, nil
}

func (*workflowSDKServer) ListWorkflowDefinitions(_ context.Context, request *internalworkflowv1.ListWorkflowDefinitionsRequest) (*internalworkflowv1.ListWorkflowDefinitionsResponse, error) {
	return &internalworkflowv1.ListWorkflowDefinitionsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-definition"}}, nil
}

func (server *workflowSDKServer) StartWorkflowRun(ctx context.Context, request *internalworkflowv1.StartWorkflowRunRequest) (*internalworkflowv1.StartWorkflowRunResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalworkflowv1.StartWorkflowRunResponse{Operation: workflowOperation("operations/start-run")}, nil
}

func (server *workflowSDKServer) GetWorkflowRun(context.Context, *internalworkflowv1.GetWorkflowRunRequest) (*internalworkflowv1.GetWorkflowRunResponse, error) {
	return &internalworkflowv1.GetWorkflowRunResponse{WorkflowRun: &workflowv1.WorkflowRun{Name: server.name, State: workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING, TransitionSequence: 1}}, nil
}

func (*workflowSDKServer) ListWorkflowRuns(_ context.Context, request *internalworkflowv1.ListWorkflowRunsRequest) (*internalworkflowv1.ListWorkflowRunsResponse, error) {
	return &internalworkflowv1.ListWorkflowRunsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-run"}}, nil
}

func (server *workflowSDKServer) CancelWorkflowRun(ctx context.Context, request *internalworkflowv1.CancelWorkflowRunRequest) (*internalworkflowv1.CancelWorkflowRunResponse, error) {
	server.capture(ctx, request.GetContext())
	return &internalworkflowv1.CancelWorkflowRunResponse{Operation: workflowOperation("operations/cancel-run")}, nil
}

func (server *workflowSDKServer) CommitWorkflowTransition(ctx context.Context, request *internalworkflowv1.CommitWorkflowTransitionRequest) (*internalworkflowv1.CommitWorkflowTransitionResponse, error) {
	server.capture(ctx, request.GetContext())
	run := cloneGenerated(request.GetWorkflowRun())
	run.TransitionSequence = request.GetExpectedTransitionSequence() + 1
	return &internalworkflowv1.CommitWorkflowTransitionResponse{WorkflowRun: run}, nil
}

func (server *workflowSDKServer) WatchWorkflowRun(request *internalworkflowv1.WatchWorkflowRunRequest, stream grpc.ServerStreamingServer[internalworkflowv1.WatchWorkflowRunResponse]) error {
	if request.GetAfterTransitionSequence() == 0 {
		if err := stream.Send(&internalworkflowv1.WatchWorkflowRunResponse{WorkflowRun: &workflowv1.WorkflowRun{Name: server.name, State: workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING, TransitionSequence: 1}}); err != nil {
			return err
		}
		return status.Error(codes.Unavailable, "force resumable reconnect")
	}
	return stream.Send(&internalworkflowv1.WatchWorkflowRunResponse{WorkflowRun: &workflowv1.WorkflowRun{Name: server.name, State: workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED, TransitionSequence: request.GetAfterTransitionSequence() + 1}})
}

type approvalSDKServer struct {
	internalworkflowv1.UnimplementedApprovalServiceServer
	mu       sync.Mutex
	contexts []*commonv1.CommandContext
	request  *workflowv1.ApprovalRequest
	receipt  *workflowv1.ApprovalReceipt
}

func (server *approvalSDKServer) capture(command *commonv1.CommandContext) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.contexts = append(server.contexts, cloneGenerated(command))
}

func (server *approvalSDKServer) RequestApproval(_ context.Context, request *internalworkflowv1.RequestApprovalRequest) (*internalworkflowv1.RequestApprovalResponse, error) {
	server.capture(request.GetApprovalRequest().GetContext())
	created := cloneGenerated(request.GetApprovalRequest())
	created.Name = server.request.GetName()
	server.request = cloneGenerated(created)
	return &internalworkflowv1.RequestApprovalResponse{ApprovalRequest: created}, nil
}

func (server *approvalSDKServer) GetApprovalRequest(context.Context, *internalworkflowv1.GetApprovalRequestRequest) (*internalworkflowv1.GetApprovalRequestResponse, error) {
	return &internalworkflowv1.GetApprovalRequestResponse{ApprovalRequest: cloneGenerated(server.request)}, nil
}

func (*approvalSDKServer) ListApprovalRequests(_ context.Context, request *internalworkflowv1.ListApprovalRequestsRequest) (*internalworkflowv1.ListApprovalRequestsResponse, error) {
	return &internalworkflowv1.ListApprovalRequestsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-approval"}}, nil
}

func (server *approvalSDKServer) DecideApproval(_ context.Context, request *internalworkflowv1.DecideApprovalRequest) (*internalworkflowv1.DecideApprovalResponse, error) {
	server.capture(request.GetContext())
	receipt := cloneGenerated(server.receipt)
	receipt.Decision, receipt.ReasonCode, receipt.SafeReason = request.GetDecision(), request.GetReasonCode(), request.GetSafeReason()
	return &internalworkflowv1.DecideApprovalResponse{ApprovalReceipt: receipt}, nil
}

func (server *approvalSDKServer) ConsumeApproval(_ context.Context, request *internalworkflowv1.ConsumeApprovalRequest) (*internalworkflowv1.ConsumeApprovalResponse, error) {
	server.capture(request.GetContext())
	receipt := cloneGenerated(server.receipt)
	receipt.ConsumedAt, receipt.ConsumedByCallId = timestamppb.Now(), request.GetCallId()
	return &internalworkflowv1.ConsumeApprovalResponse{ApprovalReceipt: receipt}, nil
}

func workflowSDKFixture(t *testing.T) (*Client, *workflowSDKServer, *approvalSDKServer) {
	t.Helper()
	parent := "tenants/tenant-a/projects/project-a"
	runName, approvalName, receiptName := parent+"/workflowRuns/run-1", parent+"/approvalRequests/approval-1", parent+"/approvalReceipts/receipt-1"
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	workflows := &workflowSDKServer{name: runName, definitionName: parent + "/workflowDefinitions/definition-1"}
	approvals := &approvalSDKServer{
		request: &workflowv1.ApprovalRequest{Name: approvalName},
		receipt: &workflowv1.ApprovalReceipt{
			Name: receiptName, Request: &commonv1.ResourceRef{ResourceType: "approval_request", ResourceId: "approval-1", TenantId: "tenant-a", ProjectId: "project-a", Name: approvalName},
			Binding: &workflowv1.ApprovalBinding{BindingDigest: testSHA256("binding")}, DecidedAt: timestamppb.Now(), ReceiptDigest: testSHA256("receipt"),
		},
	}
	internalworkflowv1.RegisterWorkflowServiceServer(grpcServer, workflows)
	internalworkflowv1.RegisterApprovalServiceServer(grpcServer, approvals)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	config := defaultConfig()
	config.TenantID, config.ProjectID, config.PrincipalID = "tenant-a", "project-a", "principal-a"
	config.DefaultRPCTimeout, config.DefaultOperationTimeout = time.Second, 3*time.Second
	config.RetryBaseDelay, config.RetryMaxDelay = time.Millisecond, 2*time.Millisecond
	connection, err := grpc.NewClient("passthrough:///bufnet",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(unaryInterceptor(config)), grpc.WithStreamInterceptor(streamInterceptor(config)))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := &Client{config: config}
	client.Workflows = &WorkflowService{client: client, transport: internalworkflowv1.NewWorkflowServiceClient(connection)}
	client.Approvals = &ApprovalService{client: client, transport: internalworkflowv1.NewApprovalServiceClient(connection)}
	return client, workflows, approvals
}

func testSHA256(value string) string {
	digest := sha256.Sum256([]byte(value))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func approvalBinding(t *testing.T) *workflowv1.ApprovalBinding {
	t.Helper()
	value := &workflowv1.ApprovalBinding{Action: "workflow.execute", IntentDigest: testSHA256("intent"), ParametersDigest: testSHA256("parameters"), RiskClass: "bounded"}
	digest, err := deterministicDigest(value)
	if err != nil {
		t.Fatal(err)
	}
	value.BindingDigest = digest
	return value
}

func TestWorkflowAndApprovalFacadesCoverGeneratedRPCs(t *testing.T) {
	client, workflows, approvals := workflowSDKFixture(t)
	parent := "tenants/tenant-a/projects/project-a"
	definitionName, runName := parent+"/workflowDefinitions/definition-1", parent+"/workflowRuns/run-1"
	contextValue := &commonv1.CommandContext{IdempotencyKey: "caller-key", PrincipalId: "forged"}
	create := &internalworkflowv1.CreateWorkflowDefinitionRequest{Context: contextValue, WorkflowDefinitionId: "definition-1", WorkflowDefinition: &workflowv1.WorkflowDefinition{}}
	original := cloneGenerated(create)
	if _, err := client.Workflows.CreateDefinition(context.Background(), create); err != nil || !proto.Equal(create, original) {
		t.Fatalf("create request mutated or failed: %v", err)
	}
	if _, err := client.Workflows.UpdateDefinition(context.Background(), &internalworkflowv1.UpdateWorkflowDefinitionRequest{WorkflowDefinition: &workflowv1.WorkflowDefinition{Name: definitionName}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: "etag"}); err != nil {
		t.Fatal(err)
	}
	if value, err := client.Workflows.GetDefinition(context.Background(), definitionName, "etag"); err != nil || value.GetName() != definitionName {
		t.Fatalf("definition=%v err=%v", value, err)
	}
	if page, err := client.Workflows.ListDefinitions(context.Background(), &internalworkflowv1.ListWorkflowDefinitionsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "opaque-definition" {
		t.Fatalf("definition page=%v err=%v", page, err)
	}
	if _, err := client.Workflows.StartRun(context.Background(), &internalworkflowv1.StartWorkflowRunRequest{WorkflowRunId: "run-1", WorkflowRun: &workflowv1.WorkflowRun{Definition: &commonv1.ResourceRef{Name: definitionName}}}); err != nil {
		t.Fatal(err)
	}
	if value, err := client.Workflows.GetRun(context.Background(), runName, ""); err != nil || value.GetName() != runName {
		t.Fatalf("run=%v err=%v", value, err)
	}
	if page, err := client.Workflows.ListRuns(context.Background(), &internalworkflowv1.ListWorkflowRunsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "opaque-run" {
		t.Fatalf("run page=%v err=%v", page, err)
	}
	if _, err := client.Workflows.CancelRun(context.Background(), &internalworkflowv1.CancelWorkflowRunRequest{Name: runName, Etag: "etag", Reason: "operator request"}); err != nil {
		t.Fatal(err)
	}
	leaseToken := "scheduler-issued-token"
	commit := &internalworkflowv1.CommitWorkflowTransitionRequest{WorkflowRun: &workflowv1.WorkflowRun{Name: runName}, ExpectedTransitionSequence: 1, Etag: "etag", Fence: &jobv1.LeaseFence{JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(time.Minute)), LeaseTokenDigest: testSHA256(leaseToken)}}
	if value, err := client.Workflows.CommitTransition(context.Background(), commit, WithLeaseToken(leaseToken)); err != nil || value.GetTransitionSequence() != 2 {
		t.Fatalf("transition=%v err=%v", value, err)
	}
	workflows.mu.Lock()
	if len(workflows.contexts) != 5 || workflows.contexts[0].GetPrincipalId() != "principal-a" || workflows.contexts[0].GetCanonicalRequestDigest() == "" || workflows.lease != leaseToken {
		t.Fatalf("workflow contexts=%v lease=%q", workflows.contexts, workflows.lease)
	}
	workflows.mu.Unlock()
	watcher, err := client.Workflows.Watch(context.Background(), runName, 0)
	if err != nil {
		t.Fatal(err)
	}
	first, err := watcher.Recv()
	if err != nil || first.GetTransitionSequence() != 1 || watcher.Cursor() != 1 {
		t.Fatalf("first=%v cursor=%d err=%v", first, watcher.Cursor(), err)
	}
	terminal, err := watcher.Recv()
	if err != nil || terminal.GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED || watcher.Cursor() != 2 {
		t.Fatalf("terminal=%v cursor=%d err=%v", terminal, watcher.Cursor(), err)
	}
	_ = watcher.Close()
	if run, err := client.Workflows.Wait(context.Background(), runName, 1); err != nil || run.GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED {
		t.Fatalf("wait run=%v err=%v", run, err)
	}

	binding := approvalBinding(t)
	approval, err := client.Approvals.Request(context.Background(), &workflowv1.ApprovalRequest{Context: &commonv1.CommandContext{IdempotencyKey: "approval-key", PrincipalId: "forged"}, Binding: binding})
	if err != nil || approval.GetName() != parent+"/approvalRequests/approval-1" || approval.GetRequestedByPrincipalRef() != "principal-a" {
		t.Fatalf("approval=%v err=%v", approval, err)
	}
	if value, getErr := client.Approvals.Get(context.Background(), approval.GetName()); getErr != nil || value.GetName() != approval.GetName() {
		t.Fatalf("approval read=%v err=%v", value, getErr)
	}
	if page, listErr := client.Approvals.List(context.Background(), &internalworkflowv1.ListApprovalRequestsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}}); listErr != nil || page.GetPage().GetNextPageToken() != "opaque-approval" {
		t.Fatalf("approval page=%v err=%v", page, listErr)
	}
	approvals.receipt.Binding = cloneGenerated(binding)
	decision := &internalworkflowv1.DecideApprovalRequest{Name: approval.GetName(), Etag: "etag", Decision: workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_APPROVE, ReasonCode: "approved", SafeReason: "reviewed"}
	receipt, err := client.Approvals.Decide(context.Background(), decision)
	if err != nil || receipt.GetDecision() != decision.GetDecision() {
		t.Fatalf("receipt=%v err=%v", receipt, err)
	}
	consumed, err := client.Approvals.Consume(context.Background(), &internalworkflowv1.ConsumeApprovalRequest{ReceiptName: receipt.GetName(), BindingDigest: binding.GetBindingDigest(), CallId: "call-1"})
	if err != nil || consumed.GetConsumedByCallId() != "call-1" {
		t.Fatalf("consumed=%v err=%v", consumed, err)
	}
	approvals.mu.Lock()
	if len(approvals.contexts) != 3 || approvals.contexts[0].GetPrincipalId() != "principal-a" || approvals.contexts[0].GetCanonicalRequestDigest() == "" {
		t.Fatalf("approval contexts=%v", approvals.contexts)
	}
	approvals.mu.Unlock()
}

func TestWorkflowWaitReturnsTypedGeneratedFailure(t *testing.T) {
	run := &workflowv1.WorkflowRun{Name: "tenants/t/projects/p/workflowRuns/r", State: workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_FAILED}
	err := &WorkflowRunError{Run: run}
	if err.Run != run || strings.Contains(err.Error(), "secret failure detail") {
		t.Fatalf("typed workflow error=%v", err)
	}
}
