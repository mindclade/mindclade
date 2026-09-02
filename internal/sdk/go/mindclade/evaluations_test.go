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
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type evaluationSDKServer struct {
	internalevaluationv1.UnimplementedEvaluationServiceServer
	mu       sync.Mutex
	requests []proto.Message
	leases   []string
	run      *evaluationv1.EvaluationRun
	result   *evaluationv1.EvaluationResult
	decision *evaluationv1.PromotionDecision
}

func (server *evaluationSDKServer) record(ctx context.Context, request proto.Message) {
	values, _ := metadata.FromIncomingContext(ctx)
	server.mu.Lock()
	defer server.mu.Unlock()
	server.requests = append(server.requests, proto.Clone(request))
	server.leases = append(server.leases, strings.Join(values.Get("x-mindclade-lease-token"), ""))
}

func (server *evaluationSDKServer) CreateEvaluationRun(ctx context.Context, request *internalevaluationv1.CreateEvaluationRunRequest) (*internalevaluationv1.CreateEvaluationRunResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.CreateEvaluationRunResponse{Operation: sdkOperation("evaluation-create")}, nil
}

func (server *evaluationSDKServer) GetEvaluationRun(ctx context.Context, request *internalevaluationv1.GetEvaluationRunRequest) (*internalevaluationv1.GetEvaluationRunResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.GetEvaluationRunResponse{EvaluationRun: cloneGenerated(server.run)}, nil
}

func (server *evaluationSDKServer) ListEvaluationRuns(ctx context.Context, request *internalevaluationv1.ListEvaluationRunsRequest) (*internalevaluationv1.ListEvaluationRunsResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.ListEvaluationRunsResponse{EvaluationRuns: []*evaluationv1.EvaluationRun{cloneGenerated(server.run)}, Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-next"}}, nil
}

func (server *evaluationSDKServer) CancelEvaluationRun(ctx context.Context, request *internalevaluationv1.CancelEvaluationRunRequest) (*internalevaluationv1.CancelEvaluationRunResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.CancelEvaluationRunResponse{Operation: sdkOperation("evaluation-cancel")}, nil
}

func (server *evaluationSDKServer) CommitEvaluationResult(ctx context.Context, request *internalevaluationv1.CommitEvaluationResultRequest) (*internalevaluationv1.CommitEvaluationResultResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.CommitEvaluationResultResponse{Result: cloneGenerated(server.result), EvaluationRun: cloneGenerated(server.run)}, nil
}

func (server *evaluationSDKServer) GetEvaluationResult(ctx context.Context, request *internalevaluationv1.GetEvaluationResultRequest) (*internalevaluationv1.GetEvaluationResultResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.GetEvaluationResultResponse{Result: cloneGenerated(server.result)}, nil
}

func (server *evaluationSDKServer) CreatePromotionDecision(ctx context.Context, request *internalevaluationv1.CreatePromotionDecisionRequest) (*internalevaluationv1.CreatePromotionDecisionResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.CreatePromotionDecisionResponse{Operation: sdkOperation("promotion-decision")}, nil
}

func (server *evaluationSDKServer) GetPromotionDecision(ctx context.Context, request *internalevaluationv1.GetPromotionDecisionRequest) (*internalevaluationv1.GetPromotionDecisionResponse, error) {
	server.record(ctx, request)
	return &internalevaluationv1.GetPromotionDecisionResponse{PromotionDecision: cloneGenerated(server.decision)}, nil
}

func evaluationSDKArtifact(kind string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), IntegrityDigest: "sha256:" + strings.Repeat("b", 64), MediaType: "application/json", SizeBytes: 42, ArtifactKind: kind}
}

func evaluationSDKClient(t *testing.T) (*EvaluationService, *evaluationSDKServer, Config) {
	t.Helper()
	parent := "tenants/tenant-a/projects/project-a"
	runName := parent + "/evaluationRuns/evaluation-1"
	resultName := parent + "/evaluationResults/result-1"
	decisionName := parent + "/promotionDecisions/decision-1"
	runRef := &commonv1.ResourceRef{ResourceType: "evaluation_run", ResourceId: "evaluation-1", TenantId: "tenant-a", ProjectId: "project-a", Name: runName}
	server := &evaluationSDKServer{
		run:      &evaluationv1.EvaluationRun{Name: runName, Uid: "run-uid", Revision: 2, Etag: "etag-run", TenantId: "tenant-a", ProjectId: "project-a", State: evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_SUCCEEDED},
		result:   &evaluationv1.EvaluationResult{Name: resultName, Uid: "result-uid", Run: cloneGenerated(runRef), RunDigest: "sha256:" + strings.Repeat("c", 64), ResultDigest: "sha256:" + strings.Repeat("d", 64), Outcome: evaluationv1.EvaluationResultOutcome_EVALUATION_RESULT_OUTCOME_PASSED},
		decision: &evaluationv1.PromotionDecision{Name: decisionName, Uid: "decision-uid", DecisionDigest: "sha256:" + strings.Repeat("e", 64)},
	}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	internalevaluationv1.RegisterEvaluationServiceServer(grpcServer, server)
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
	return &EvaluationService{client: client, transport: internalevaluationv1.NewEvaluationServiceClient(connection)}, server, config
}

func TestEvaluationFacadeCoversAllGeneratedRPCsAndBindsAuthority(t *testing.T) {
	service, server, config := evaluationSDKClient(t)
	ctx := context.Background()
	parent := "tenants/tenant-a/projects/project-a"
	runName := parent + "/evaluationRuns/evaluation-1"
	resultName := parent + "/evaluationResults/result-1"
	decisionName := parent + "/promotionDecisions/decision-1"
	modelRelease := &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: "v1", Name: parent + "/models/model-1/releases/v1"}
	create := &internalevaluationv1.CreateEvaluationRunRequest{
		Context: &commonv1.CommandContext{IdempotencyKey: "create-evaluation", TenantId: "forged"}, EvaluationRunId: "evaluation-1",
		Suite: evaluationSDKArtifact("evaluation-suite"), Datasets: []*artifactv1.ArtifactRef{evaluationSDKArtifact("dataset-manifest")}, Snapshot: evaluationSDKArtifact("model-snapshot"), ModelRelease: modelRelease, InferenceProtocol: evaluationSDKArtifact("inference-protocol"),
	}
	createOriginal := cloneGenerated(create)
	if operation, err := service.CreateRun(ctx, create); err != nil || operation.GetOperationId() == "" || !proto.Equal(create, createOriginal) {
		t.Fatalf("create operation=%v unchanged=%v err=%v", operation, proto.Equal(create, createOriginal), err)
	}
	if run, err := service.GetRun(ctx, runName, "etag-run"); err != nil || run.GetName() != runName {
		t.Fatalf("get run=%v err=%v", run, err)
	}
	page, err := service.ListRuns(ctx, &internalevaluationv1.ListEvaluationRunsRequest{Page: &commonv1.PageRequest{PageSize: 20, PageToken: "page-cursor"}})
	if err != nil || page.GetPage().GetNextPageToken() != "page-cursor-next" {
		t.Fatalf("list page=%v err=%v", page, err)
	}
	if _, err = service.CancelRun(ctx, &internalevaluationv1.CancelEvaluationRunRequest{Name: runName, Etag: "etag-run", Reason: "operator request"}, WithIdempotencyKey("cancel-evaluation")); err != nil {
		t.Fatal(err)
	}
	commit := &internalevaluationv1.CommitEvaluationResultRequest{
		Context:       &commonv1.CommandContext{IdempotencyKey: "commit-evaluation", PrincipalId: "forged"},
		EvaluationRun: &commonv1.ResourceRef{ResourceType: "evaluation_run", ResourceId: "evaluation-1", Name: runName},
		Fence:         &jobv1.LeaseFence{JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(time.Minute)), LeaseTokenDigest: "sha256:" + strings.Repeat("f", 64)},
		Result:        cloneGenerated(server.result), Etag: "etag-run",
	}
	if _, _, err = service.CommitResult(ctx, commit); err == nil {
		t.Fatal("fenced result commit accepted without a transport lease capability")
	}
	result, completed, err := service.CommitResult(ctx, commit, WithLeaseToken("opaque-lease-capability"))
	if err != nil || result.GetName() != resultName || completed.GetName() != runName {
		t.Fatalf("commit result=%v run=%v err=%v", result, completed, err)
	}
	if read, readErr := service.GetResult(ctx, resultName); readErr != nil || read.GetName() != resultName {
		t.Fatalf("get result=%v err=%v", read, readErr)
	}
	decision := &evaluationv1.PromotionDecision{
		Name: decisionName, Uid: "decision-uid", CandidateRelease: cloneGenerated(modelRelease), CandidateDigest: "sha256:" + strings.Repeat("1", 64), TargetProfile: "staging",
		EvaluationResults: []*commonv1.ResourceRef{{ResourceType: "evaluation_result", ResourceId: "result-1", Name: resultName}}, Outcome: evaluationv1.PromotionOutcome_PROMOTION_OUTCOME_APPROVE,
		ReasonCode: "QUALIFIED", DecidedByPrincipalRef: "forged", DecidedAt: timestamppb.Now(), SourceRevision: "revision-1", DecisionDigest: "sha256:" + strings.Repeat("2", 64),
	}
	decisionRequest := &internalevaluationv1.CreatePromotionDecisionRequest{Context: &commonv1.CommandContext{IdempotencyKey: "promotion-decision"}, PromotionDecision: decision}
	if operation, createErr := service.CreatePromotionDecision(ctx, decisionRequest); createErr != nil || operation.GetOperationId() == "" {
		t.Fatalf("create decision operation=%v err=%v", operation, createErr)
	}
	if read, readErr := service.GetPromotionDecision(ctx, decisionName); readErr != nil || read.GetName() != decisionName {
		t.Fatalf("get decision=%v err=%v", read, readErr)
	}

	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.requests) != 8 {
		t.Fatalf("received %d evaluation RPCs, want all 8", len(server.requests))
	}
	capturedCreate := server.requests[0].(*internalevaluationv1.CreateEvaluationRunRequest)
	if capturedCreate.GetParent() != parent || capturedCreate.GetContext().GetTenantId() != config.TenantID || capturedCreate.GetContext().GetProjectId() != config.ProjectID || capturedCreate.GetContext().GetPrincipalId() != config.PrincipalID || capturedCreate.GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatalf("authoritative create context=%v parent=%q", capturedCreate.GetContext(), capturedCreate.GetParent())
	}
	capturedCommit := server.requests[4].(*internalevaluationv1.CommitEvaluationResultRequest)
	if server.leases[4] != "opaque-lease-capability" || capturedCommit.GetContext().GetCanonicalRequestDigest() == "" || capturedCommit.GetFence().GetTenantId() != config.TenantID || capturedCommit.GetFence().GetProjectId() != config.ProjectID {
		t.Fatalf("fenced commit context=%v fence=%v lease-present=%v", capturedCommit.GetContext(), capturedCommit.GetFence(), server.leases[4] != "")
	}
	capturedDecision := server.requests[6].(*internalevaluationv1.CreatePromotionDecisionRequest)
	if capturedDecision.GetPromotionDecision().GetDecidedByPrincipalRef() != config.PrincipalID {
		t.Fatalf("promotion principal=%q", capturedDecision.GetPromotionDecision().GetDecidedByPrincipalRef())
	}
	for _, index := range []int{0, 3, 4, 6} {
		request := server.requests[index]
		command := request.ProtoReflect().Get(request.ProtoReflect().Descriptor().Fields().ByName("context")).Message().Interface().(*commonv1.CommandContext)
		if !validateEvaluationMutationRetry(request, requestMetadata{idempotencyKey: command.GetIdempotencyKey()}, config) {
			t.Fatalf("evaluation mutation %T was not exact-digest retry safe", request)
		}
	}
}
