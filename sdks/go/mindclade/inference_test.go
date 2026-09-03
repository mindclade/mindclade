package mindclade

import (
	"context"
	"errors"
	"io"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

type inferenceSDKServer struct {
	internalinferencev1.UnimplementedInferenceServiceServer
	mu      sync.Mutex
	submit  *internalinferencev1.SubmitInferenceRequest
	commit  *internalinferencev1.CommitInferenceResultRequest
	request *inferencev1.InferenceRequest
	result  *inferencev1.InferenceResult
	op      *operationv1.Operation
}

func (server *inferenceSDKServer) SubmitInference(_ context.Context, request *internalinferencev1.SubmitInferenceRequest) (*internalinferencev1.SubmitInferenceResponse, error) {
	server.mu.Lock()
	server.submit = cloneGenerated(request)
	server.request = cloneGenerated(request.GetInferenceRequest())
	server.mu.Unlock()
	return &internalinferencev1.SubmitInferenceResponse{Operation: cloneGenerated(server.op)}, nil
}

func (server *inferenceSDKServer) GetInferenceRequest(context.Context, *internalinferencev1.GetInferenceRequestRequest) (*internalinferencev1.GetInferenceRequestResponse, error) {
	return &internalinferencev1.GetInferenceRequestResponse{InferenceRequest: cloneGenerated(server.request)}, nil
}

func (server *inferenceSDKServer) GetInferenceResult(context.Context, *internalinferencev1.GetInferenceResultRequest) (*internalinferencev1.GetInferenceResultResponse, error) {
	return &internalinferencev1.GetInferenceResultResponse{Result: cloneGenerated(server.result), Operation: cloneGenerated(server.op)}, nil
}

func (server *inferenceSDKServer) CommitInferenceResult(_ context.Context, request *internalinferencev1.CommitInferenceResultRequest) (*internalinferencev1.CommitInferenceResultResponse, error) {
	server.mu.Lock()
	server.commit = cloneGenerated(request)
	server.mu.Unlock()
	return &internalinferencev1.CommitInferenceResultResponse{Result: cloneGenerated(server.result), Operation: cloneGenerated(server.op)}, nil
}

func (server *inferenceSDKServer) WatchInference(request *internalinferencev1.WatchInferenceRequest, stream grpc.ServerStreamingServer[internalinferencev1.WatchInferenceResponse]) error {
	requestName := server.request.GetName()
	after := uint64(0)
	if request.GetCursor() != nil {
		after = request.GetCursor().GetAfterSequence()
	}
	if after == 0 {
		if err := stream.Send(&internalinferencev1.WatchInferenceResponse{Message: &inferencev1.InferenceStreamMessage{
			RequestName: requestName, Sequence: 1, ResumeToken: "cursor-1", EmittedAt: timestamppb.Now(),
			Update: &inferencev1.InferenceStreamMessage_Progress{Progress: &inferencev1.InferenceProgress{LifecycleState: "RUNNING"}},
		}}); err != nil {
			return err
		}
		after = 1
	}
	if after == 1 {
		if err := stream.Send(&internalinferencev1.WatchInferenceResponse{Message: &inferencev1.InferenceStreamMessage{
			RequestName: requestName, Sequence: 1, ResumeToken: "cursor-1", EmittedAt: timestamppb.Now(),
			Update: &inferencev1.InferenceStreamMessage_Heartbeat{Heartbeat: &inferencev1.InferenceHeartbeat{ObservedAt: timestamppb.Now()}},
		}}); err != nil {
			return err
		}
		return stream.Send(&internalinferencev1.WatchInferenceResponse{Message: &inferencev1.InferenceStreamMessage{
			RequestName: requestName, Sequence: 2, ResumeToken: "cursor-2", EmittedAt: timestamppb.Now(),
			Update: &inferencev1.InferenceStreamMessage_FinalResult{FinalResult: &inferencev1.InferenceFinalUpdate{Result: cloneGenerated(server.result.GetRequest()), Outcome: server.result.GetOutcome(), ResultManifest: cloneGenerated(server.result.GetResultManifest()), ResultDigest: server.result.GetResultDigest()}},
		}})
	}
	return nil
}

func inferenceSDKClient(t *testing.T) (*Client, *InferenceService, *inferenceSDKServer) {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	request := &inferencev1.InferenceRequest{Name: "tenants/tenant-a/projects/project-a/inferenceRequests/request-1", TenantId: "tenant-a", ProjectId: "project-a"}
	op := &operationv1.Operation{OperationId: "operations/op-1", TenantId: "tenant-a", ProjectId: "project-a", JobId: "jobs/job-1", State: operationv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 2, Done: true}
	result := &inferencev1.InferenceResult{Name: "tenants/tenant-a/projects/project-a/inferenceResults/result-1", Request: &commonv1.ResourceRef{ResourceType: "inference_request", ResourceId: "request-1", TenantId: "tenant-a", ProjectId: "project-a", Name: request.GetName()}, Outcome: inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_SUCCEEDED, ResultManifest: fixtureArtifact(), ResultDigest: "sha256:" + strings.Repeat("a", 64)}
	server := &inferenceSDKServer{request: request, result: result, op: op}
	internalinferencev1.RegisterInferenceServiceServer(grpcServer, server)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client, err := NewWithTransportForTesting(newTransportClients(connection), WithTenantProject("tenant-a", "project-a"), WithPrincipal("principal-a"), WithOperationTimeout(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	service := &InferenceService{client: client, transport: client.transport.Inference}
	return client, service, server
}

func TestInferenceFacadeUsesGeneratedTypesAndResumableWatch(t *testing.T) {
	_, service, server := inferenceSDKClient(t)
	request := &inferencev1.InferenceRequest{
		Context: &commonv1.CommandContext{IdempotencyKey: "submit-inference"},
		Name:    "tenants/tenant-a/projects/project-a/inferenceRequests/request-1",
	}
	original := cloneGenerated(request)
	operation, err := service.Submit(context.Background(), request)
	if err != nil || operation.GetOperationId() != "operations/op-1" || !proto.Equal(request, original) {
		t.Fatalf("submit operation=%v request=%v err=%v", operation, request, err)
	}
	server.mu.Lock()
	captured := cloneGenerated(server.submit)
	server.mu.Unlock()
	if captured.GetInferenceRequest().GetContext().GetCanonicalRequestDigest() == "" || captured.GetInferenceRequest().GetContext().GetPrincipalId() != "principal-a" || captured.GetInferenceRequest().GetTenantId() != "tenant-a" {
		t.Fatalf("materialized submit=%v", captured)
	}
	read, err := service.GetRequest(context.Background(), request.GetName())
	if err != nil || read.GetName() != request.GetName() {
		t.Fatalf("read=%v err=%v", read, err)
	}
	commit := &internalinferencev1.CommitInferenceResultRequest{
		Context:          &commonv1.CommandContext{IdempotencyKey: "commit-inference"},
		InferenceRequest: cloneGenerated(server.result.GetRequest()), Fence: &jobv1.LeaseFence{JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1},
		Result: cloneGenerated(server.result), RequestDigest: "sha256:" + strings.Repeat("b", 64),
	}
	if _, _, err = service.CommitResult(context.Background(), commit); err != nil {
		t.Fatal(err)
	}
	server.mu.Lock()
	capturedCommit := cloneGenerated(server.commit)
	server.mu.Unlock()
	if capturedCommit.GetContext().GetCanonicalRequestDigest() == "" || capturedCommit.GetContext().GetPrincipalId() != "principal-a" {
		t.Fatalf("materialized commit=%v", capturedCommit)
	}
	watcher, err := service.Watch(context.Background(), operation.GetOperationId(), nil)
	if err != nil {
		t.Fatal(err)
	}
	progress, err := watcher.Recv()
	if err != nil || progress.GetProgress() == nil || watcher.Cursor().GetAfterSequence() != 1 {
		t.Fatalf("progress=%v cursor=%v err=%v", progress, watcher.Cursor(), err)
	}
	heartbeat, err := watcher.Recv()
	if err != nil || heartbeat.GetHeartbeat() == nil || watcher.Cursor().GetAfterSequence() != 1 {
		t.Fatalf("heartbeat=%v cursor=%v err=%v", heartbeat, watcher.Cursor(), err)
	}
	terminal, err := watcher.Recv()
	if err != nil || terminal.GetFinalResult() == nil || watcher.Cursor().GetAfterSequence() != 2 {
		t.Fatalf("terminal=%v cursor=%v err=%v", terminal, watcher.Cursor(), err)
	}
	if _, err = watcher.Recv(); !errors.Is(err, io.EOF) {
		t.Fatalf("terminal recv err=%v", err)
	}
	if err = watcher.Close(); err != nil {
		t.Fatal(err)
	}
	result, terminalOperation, err := service.Wait(context.Background(), operation.GetOperationId(), &inferencev1.InferenceStreamCursor{RequestName: request.GetName(), AfterSequence: 1, ResumeToken: "cursor-1"})
	if err != nil || result.GetName() != server.result.GetName() || terminalOperation.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("wait result=%v operation=%v err=%v", result, terminalOperation, err)
	}
}
