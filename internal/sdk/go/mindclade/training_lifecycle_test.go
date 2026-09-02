package mindclade

import (
	"context"
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
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

type trainingLifecycleServer struct {
	internaltrainingv1.UnimplementedTrainingServiceServer
	mu       sync.Mutex
	requests []proto.Message
	leases   []string
	run      *trainingv1.TrainingRun
	progress *trainingv1.TrainingProgress
	point    *trainingv1.Checkpoint
}

func (server *trainingLifecycleServer) record(ctx context.Context, request proto.Message) {
	values, _ := metadata.FromIncomingContext(ctx)
	server.mu.Lock()
	defer server.mu.Unlock()
	server.requests = append(server.requests, proto.Clone(request))
	server.leases = append(server.leases, strings.Join(values.Get("x-mindclade-lease-token"), ""))
}

func (server *trainingLifecycleServer) GetTrainingRun(ctx context.Context, request *internaltrainingv1.GetTrainingRunRequest) (*internaltrainingv1.GetTrainingRunResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.GetTrainingRunResponse{TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) ListTrainingRuns(ctx context.Context, request *internaltrainingv1.ListTrainingRunsRequest) (*internaltrainingv1.ListTrainingRunsResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.ListTrainingRunsResponse{TrainingRuns: []*trainingv1.TrainingRun{cloneGenerated(server.run)}, Page: &commonv1.PageResponse{NextPageToken: "next"}}, nil
}

func (server *trainingLifecycleServer) StartTrainingAttempt(ctx context.Context, request *internaltrainingv1.StartTrainingAttemptRequest) (*internaltrainingv1.StartTrainingAttemptResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.StartTrainingAttemptResponse{TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) ResumeTrainingAttempt(ctx context.Context, request *internaltrainingv1.ResumeTrainingAttemptRequest) (*internaltrainingv1.ResumeTrainingAttemptResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.ResumeTrainingAttemptResponse{TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) CommitTrainingProgress(ctx context.Context, request *internaltrainingv1.CommitTrainingProgressRequest) (*internaltrainingv1.CommitTrainingProgressResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.CommitTrainingProgressResponse{Progress: cloneGenerated(server.progress), TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) PrepareCheckpoint(ctx context.Context, request *internaltrainingv1.PrepareCheckpointRequest) (*internaltrainingv1.PrepareCheckpointResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.PrepareCheckpointResponse{Checkpoint: cloneGenerated(server.point)}, nil
}

func (server *trainingLifecycleServer) CommitCheckpoint(ctx context.Context, request *internaltrainingv1.CommitCheckpointRequest) (*internaltrainingv1.CommitCheckpointResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.CommitCheckpointResponse{Checkpoint: cloneGenerated(server.point), TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) CompleteTrainingRun(ctx context.Context, request *internaltrainingv1.CompleteTrainingRunRequest) (*internaltrainingv1.CompleteTrainingRunResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.CompleteTrainingRunResponse{TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) CancelTrainingRun(ctx context.Context, request *internaltrainingv1.CancelTrainingRunRequest) (*internaltrainingv1.CancelTrainingRunResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.CancelTrainingRunResponse{TrainingRun: cloneGenerated(server.run)}, nil
}

func (server *trainingLifecycleServer) GetCheckpoint(ctx context.Context, request *internaltrainingv1.GetCheckpointRequest) (*internaltrainingv1.GetCheckpointResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.GetCheckpointResponse{Checkpoint: cloneGenerated(server.point)}, nil
}

func (server *trainingLifecycleServer) ListCheckpoints(ctx context.Context, request *internaltrainingv1.ListCheckpointsRequest) (*internaltrainingv1.ListCheckpointsResponse, error) {
	server.record(ctx, request)
	return &internaltrainingv1.ListCheckpointsResponse{Checkpoints: []*trainingv1.Checkpoint{cloneGenerated(server.point)}}, nil
}

func (server *trainingLifecycleServer) WatchTrainingRun(request *internaltrainingv1.WatchTrainingRunRequest, stream grpc.ServerStreamingServer[internaltrainingv1.WatchTrainingRunResponse]) error {
	server.record(stream.Context(), request)
	run := cloneGenerated(server.run)
	run.State = trainingv1.TrainingRunState_TRAINING_RUN_STATE_COMPLETED
	return stream.Send(&internaltrainingv1.WatchTrainingRunResponse{TrainingRun: run, Progress: cloneGenerated(server.progress), Sequence: request.GetAfterSequence() + 1, ObservedAt: timestamppb.Now()})
}

func newTrainingLifecycleService(t *testing.T) (*TrainingService, *trainingLifecycleServer, Config) {
	t.Helper()
	runName := "tenants/tenant-a/projects/project-a/trainingRuns/run-1"
	server := &trainingLifecycleServer{
		run:      &trainingv1.TrainingRun{Name: runName, Uid: "run-uid", State: trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING},
		progress: &trainingv1.TrainingProgress{TrainingRunName: runName, ProgressRevision: 1},
		point:    &trainingv1.Checkpoint{Name: runName + "/checkpoints/checkpoint-1", TrainingRunName: runName, SnapshotEpoch: 1},
	}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	internaltrainingv1.RegisterTrainingServiceServer(grpcServer, server)
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
		grpc.WithStreamInterceptor(streamInterceptor(config)),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := &Client{config: config}
	client.Operations = &OperationService{client: client}
	return &TrainingService{client: client, transport: internaltrainingv1.NewTrainingServiceClient(connection)}, server, config
}

func TestTrainingResourceLeafLaw(t *testing.T) {
	for _, value := range []string{"01", "A", "a.b_c~d-1"} {
		if !validTrainingResourceIDSDK(value) {
			t.Errorf("authoritative training resource leaf %q was rejected", value)
		}
	}
	for _, value := range []string{".leading", "~leading", "\x00control", strings.Repeat("a", 129)} {
		if validTrainingResourceIDSDK(value) {
			t.Errorf("invalid training resource leaf %q was accepted", value)
		}
	}
}

func TestTrainingLifecycleFacadeCoversGeneratedRPCs(t *testing.T) {
	service, server, config := newTrainingLifecycleService(t)
	ctx := context.Background()
	runName := server.run.GetName()
	checkpointName := server.point.GetName()
	fence := &jobv1.LeaseFence{JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(time.Minute)), LeaseTokenDigest: "sha256:" + strings.Repeat("a", 64)}
	ref := &commonv1.ResourceRef{Name: runName}
	checkpointRef := &commonv1.ResourceRef{Name: checkpointName}
	mutation := []RequestOption{WithIdempotencyKey("training-idempotency"), WithLeaseToken("opaque-lease")}

	if run, err := service.Get(ctx, runName); err != nil || run.GetName() != runName {
		t.Fatalf("get run=%v err=%v", run, err)
	}
	if page, err := service.ListRuns(ctx, &internaltrainingv1.ListTrainingRunsRequest{Page: &commonv1.PageRequest{PageSize: 20, PageToken: "opaque"}}); err != nil || page.GetPage().GetNextPageToken() != "next" {
		t.Fatalf("list=%v err=%v", page, err)
	}
	if run, err := service.StartAttempt(ctx, &trainingv1.StartTrainingAttemptCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRun: cloneGenerated(ref), Fence: cloneGenerated(fence), Deadline: timestamppb.New(time.Now().Add(time.Minute))}, mutation...); err != nil || run.GetName() != runName {
		t.Fatalf("start=%v err=%v", run, err)
	}
	if run, err := service.ResumeAttempt(ctx, &trainingv1.ResumeTrainingAttemptCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRun: cloneGenerated(ref), Checkpoint: cloneGenerated(checkpointRef), Fence: cloneGenerated(fence), Deadline: timestamppb.New(time.Now().Add(time.Minute))}, mutation...); err != nil || run.GetName() != runName {
		t.Fatalf("resume=%v err=%v", run, err)
	}
	if progress, run, err := service.CommitProgress(ctx, &trainingv1.CommitTrainingProgressCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRunName: runName, Fence: cloneGenerated(fence), Progress: cloneGenerated(server.progress)}, mutation...); err != nil || progress.GetProgressRevision() != 1 || run.GetName() != runName {
		t.Fatalf("progress=%v run=%v err=%v", progress, run, err)
	}
	artifact := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("b", 64)}
	if point, err := service.PrepareCheckpoint(ctx, &trainingv1.PrepareCheckpointCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRunName: runName, Fence: cloneGenerated(fence), SnapshotEpoch: 1, LogicalStateDescriptor: cloneGenerated(artifact), CommittedProgress: cloneGenerated(server.progress)}, mutation...); err != nil || point.GetName() != checkpointName {
		t.Fatalf("prepare=%v err=%v", point, err)
	}
	evidence := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("c", 64)}
	if point, run, err := service.CommitCheckpoint(ctx, &trainingv1.CommitCheckpointCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRunName: runName, Fence: cloneGenerated(fence), SnapshotEpoch: 1, CheckpointManifest: cloneGenerated(artifact), LogicalStateDescriptor: cloneGenerated(artifact), CommittedProgress: cloneGenerated(server.progress), VerificationEvidence: evidence, CommittedAt: timestamppb.Now()}, mutation...); err != nil || point.GetName() != checkpointName || run.GetName() != runName {
		t.Fatalf("commit=%v run=%v err=%v", point, run, err)
	}
	if run, err := service.Complete(ctx, &trainingv1.CompleteTrainingRunCommand{Context: &commonv1.CommandContext{IdempotencyKey: "training-idempotency"}, TrainingRunName: runName, Fence: cloneGenerated(fence), Classification: trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED, CompletedAt: timestamppb.Now()}, mutation...); err != nil || run.GetName() != runName {
		t.Fatalf("complete=%v err=%v", run, err)
	}
	if run, err := service.Cancel(ctx, &trainingv1.CancelTrainingRunCommand{Context: &commonv1.CommandContext{IdempotencyKey: "cancel-training"}, TrainingRunName: runName, Etag: "etag-1", Reason: "operator request"}, WithIdempotencyKey("cancel-training")); err != nil || run.GetName() != runName {
		t.Fatalf("cancel=%v err=%v", run, err)
	}
	if point, err := service.GetCheckpoint(ctx, checkpointName); err != nil || point.GetName() != checkpointName {
		t.Fatalf("get checkpoint=%v err=%v", point, err)
	}
	if page, err := service.ListCheckpoints(ctx, &internaltrainingv1.ListCheckpointsRequest{Parent: runName, Page: &commonv1.PageRequest{PageSize: 20}}); err != nil || len(page.GetCheckpoints()) != 1 {
		t.Fatalf("list checkpoints=%v err=%v", page, err)
	}
	watch, err := service.Watch(ctx, runName, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = watch.Close() }()
	if update, recvErr := watch.Recv(); recvErr != nil || update.GetSequence() != 1 {
		t.Fatalf("watch=%v err=%v", update, recvErr)
	}

	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.requests) != 12 {
		t.Fatalf("received %d training RPCs, want 12", len(server.requests))
	}
	for _, index := range []int{2, 3, 4, 5, 6, 7} {
		if server.leases[index] != "opaque-lease" {
			t.Fatalf("RPC %d omitted lease transport metadata", index)
		}
		message := server.requests[index].ProtoReflect().Get(server.requests[index].ProtoReflect().Descriptor().Fields().ByName("command")).Message()
		contextField := message.Descriptor().Fields().ByName("context")
		contextValue := message.Get(contextField).Message().Interface().(*commonv1.CommandContext)
		if contextValue.GetTenantId() != config.TenantID || contextValue.GetProjectId() != config.ProjectID || contextValue.GetPrincipalId() != config.PrincipalID || contextValue.GetCanonicalRequestDigest() == "" {
			t.Fatalf("RPC %d has invalid authoritative context: %v", index, contextValue)
		}
	}
}
