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
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
)

type experimentSDKServer struct {
	internalexperimentv1.UnimplementedExperimentServiceServer
	mu                 sync.Mutex
	requests           []proto.Message
	experiment         *experimentv1.Experiment
	study              *experimentv1.Study
	trial              *experimentv1.Trial
	canonicalRequestID bool
}

func (server *experimentSDKServer) record(ctx context.Context, request proto.Message) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.requests = append(server.requests, proto.Clone(request))
	requestMetadata, _ := metadata.FromIncomingContext(ctx)
	server.canonicalRequestID = server.canonicalRequestID ||
		len(requestMetadata.Get("x-request-id")) == 1 &&
			len(requestMetadata.Get("x-mindclade-request-id")) == 0
}

func (server *experimentSDKServer) CreateExperiment(ctx context.Context, request *internalexperimentv1.CreateExperimentRequest) (*internalexperimentv1.CreateExperimentResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.CreateExperimentResponse{Experiment: cloneGenerated(server.experiment)}, nil
}

func (server *experimentSDKServer) GetExperiment(ctx context.Context, request *internalexperimentv1.GetExperimentRequest) (*internalexperimentv1.GetExperimentResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.GetExperimentResponse{Experiment: cloneGenerated(server.experiment)}, nil
}

func (server *experimentSDKServer) ListExperiments(ctx context.Context, request *internalexperimentv1.ListExperimentsRequest) (*internalexperimentv1.ListExperimentsResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.ListExperimentsResponse{Experiments: []*experimentv1.Experiment{cloneGenerated(server.experiment)}, Page: &commonv1.PageResponse{NextPageToken: "experiment-next"}}, nil
}

func (server *experimentSDKServer) UpdateExperiment(ctx context.Context, request *internalexperimentv1.UpdateExperimentRequest) (*internalexperimentv1.UpdateExperimentResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.UpdateExperimentResponse{Experiment: cloneGenerated(server.experiment)}, nil
}

func (server *experimentSDKServer) TransitionExperiment(ctx context.Context, request *internalexperimentv1.TransitionExperimentRequest) (*internalexperimentv1.TransitionExperimentResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.TransitionExperimentResponse{Experiment: cloneGenerated(server.experiment)}, nil
}

func (server *experimentSDKServer) CreateStudy(ctx context.Context, request *internalexperimentv1.CreateStudyRequest) (*internalexperimentv1.CreateStudyResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.CreateStudyResponse{Study: cloneGenerated(server.study)}, nil
}

func (server *experimentSDKServer) GetStudy(ctx context.Context, request *internalexperimentv1.GetStudyRequest) (*internalexperimentv1.GetStudyResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.GetStudyResponse{Study: cloneGenerated(server.study)}, nil
}

func (server *experimentSDKServer) ListStudies(ctx context.Context, request *internalexperimentv1.ListStudiesRequest) (*internalexperimentv1.ListStudiesResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.ListStudiesResponse{Studies: []*experimentv1.Study{cloneGenerated(server.study)}, Page: &commonv1.PageResponse{NextPageToken: "study-next"}}, nil
}

func (server *experimentSDKServer) TransitionStudy(ctx context.Context, request *internalexperimentv1.TransitionStudyRequest) (*internalexperimentv1.TransitionStudyResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.TransitionStudyResponse{Study: cloneGenerated(server.study)}, nil
}

func (server *experimentSDKServer) CreateTrial(ctx context.Context, request *internalexperimentv1.CreateTrialRequest) (*internalexperimentv1.CreateTrialResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.CreateTrialResponse{Trial: cloneGenerated(server.trial)}, nil
}

func (server *experimentSDKServer) GetTrial(ctx context.Context, request *internalexperimentv1.GetTrialRequest) (*internalexperimentv1.GetTrialResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.GetTrialResponse{Trial: cloneGenerated(server.trial)}, nil
}

func (server *experimentSDKServer) ListTrials(ctx context.Context, request *internalexperimentv1.ListTrialsRequest) (*internalexperimentv1.ListTrialsResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.ListTrialsResponse{Trials: []*experimentv1.Trial{cloneGenerated(server.trial)}, Page: &commonv1.PageResponse{NextPageToken: "trial-next"}}, nil
}

func (server *experimentSDKServer) TransitionTrial(ctx context.Context, request *internalexperimentv1.TransitionTrialRequest) (*internalexperimentv1.TransitionTrialResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.TransitionTrialResponse{Trial: cloneGenerated(server.trial)}, nil
}

func (server *experimentSDKServer) CompleteTrial(ctx context.Context, request *internalexperimentv1.CompleteTrialRequest) (*internalexperimentv1.CompleteTrialResponse, error) {
	server.record(ctx, request)
	return &internalexperimentv1.CompleteTrialResponse{Trial: cloneGenerated(server.trial)}, nil
}

func experimentSDKFixture(t *testing.T) (*ExperimentService, *experimentSDKServer, Config) {
	t.Helper()
	config := defaultConfig()
	config.TenantID, config.ProjectID, config.PrincipalID = "tenant-a", "project-a", "principal-a"
	config.DefaultRPCTimeout = time.Second
	parent := projectName(config.TenantID, config.ProjectID)
	experimentName := parent + "/experiments/experiment-1"
	studyName := experimentName + "/studies/study-1"
	trialName := studyName + "/trials/trial-1"
	server := &experimentSDKServer{
		experiment: &experimentv1.Experiment{Name: experimentName, Uid: "exp-uid", Revision: 2, Etag: experimentSDKDigest("a"), TenantName: "tenants/tenant-a", ProjectName: parent, DisplayName: "candidate", State: experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE},
		study:      &experimentv1.Study{Name: studyName, Uid: "study-uid", Revision: 2, Etag: experimentSDKDigest("b"), TenantName: "tenants/tenant-a", ProjectName: parent, State: experimentv1.StudyState_STUDY_STATE_RUNNING},
		trial:      &experimentv1.Trial{Name: trialName, Uid: "trial-uid", Revision: 2, Etag: experimentSDKDigest("c"), TenantName: "tenants/tenant-a", ProjectName: parent, State: experimentv1.TrialState_TRIAL_STATE_RUNNING},
	}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	internalexperimentv1.RegisterExperimentServiceServer(grpcServer, server)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	connection, err := grpc.NewClient(
		"passthrough:///experiment-sdk",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(unaryInterceptor(config)),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := &Client{config: config}
	return &ExperimentService{client: client, transport: internalexperimentv1.NewExperimentServiceClient(connection)}, server, config
}

func experimentSDKDigest(character string) string { return "sha256:" + strings.Repeat(character, 64) }

func experimentSDKArtifact(character string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: experimentSDKDigest(character), MediaType: "application/json", SizeBytes: 42, ArtifactKind: "manifest"}
}

func experimentSDKRef(config Config, resourceType, name, etag string) *commonv1.ResourceRef {
	parts := strings.Split(name, "/")
	return &commonv1.ResourceRef{ResourceType: resourceType, ResourceId: parts[len(parts)-1], Name: name, TenantId: config.TenantID, ProjectId: config.ProjectID, ResourceVersion: 2, Etag: etag}
}

func TestExperimentFacadeRoutesAllDescriptorRPCsAndBindsCommandAuthority(t *testing.T) {
	service, server, config := experimentSDKFixture(t)
	ctx := context.Background()
	parent := projectName(config.TenantID, config.ProjectID)
	experimentName := parent + "/experiments/experiment-1"
	studyName := experimentName + "/studies/study-1"
	trialName := studyName + "/trials/trial-1"
	experimentRef := experimentSDKRef(config, "experiment", experimentName, experimentSDKDigest("a"))
	studyRef := experimentSDKRef(config, "study", studyName, experimentSDKDigest("b"))
	trialRef := experimentSDKRef(config, "trial", trialName, experimentSDKDigest("c"))
	usePolicy := experimentSDKRef(config, "use_policy", parent+"/usePolicies/policy-1", experimentSDKDigest("d"))
	subject := experimentSDKRef(config, "dataset_release", parent+"/datasets/data-1/releases/release-1", experimentSDKDigest("e"))

	create := &experimentv1.CreateExperimentCommand{Context: &commonv1.CommandContext{IdempotencyKey: "experiment-create", TenantId: "forged"}, ExperimentId: "experiment-1", DisplayName: "candidate", Kind: experimentv1.ExperimentKind_EXPERIMENT_KIND_SCIENTIFIC, IntentManifest: experimentSDKArtifact("1"), Subjects: []*commonv1.ResourceRef{subject}, UsePolicy: usePolicy, PolicyClassification: "INTERNAL", Labels: map[string]string{"owner": "science"}}
	if _, err := service.Create(ctx, create); err != nil {
		t.Fatal(err)
	}
	if _, err := service.Get(ctx, experimentName, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := service.ListPage(ctx, 20, " opaque-token== "); err != nil {
		t.Fatal(err)
	}
	update := &experimentv1.UpdateExperimentCommand{Context: &commonv1.CommandContext{IdempotencyKey: "experiment-update"}, Experiment: cloneGenerated(server.experiment), UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: server.experiment.GetEtag()}
	if _, err := service.Update(ctx, update); err != nil {
		t.Fatal(err)
	}
	if _, err := service.Transition(ctx, &experimentv1.TransitionExperimentCommand{Context: &commonv1.CommandContext{IdempotencyKey: "experiment-transition"}, Experiment: experimentRef, ExpectedState: experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT, TargetState: experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE, Etag: experimentRef.GetEtag(), ReasonCode: "INTENT_APPROVED"}); err != nil {
		t.Fatal(err)
	}
	study := &experimentv1.CreateStudyCommand{Context: &commonv1.CommandContext{IdempotencyKey: "study-create"}, Experiment: experimentRef, StudyId: "study-1", Type: experimentv1.StudyType_STUDY_TYPE_SCIENTIFIC, StudyManifest: experimentSDKArtifact("2"), BaseConfiguration: experimentSDKArtifact("3"), SearchSpace: experimentSDKArtifact("4"), ObjectiveSpecification: experimentSDKArtifact("5"), Budget: &experimentv1.StudyBudget{MaximumTrials: 10, MaximumParallelTrials: 2, MaximumDuration: durationpb.New(time.Hour)}}
	if _, err := service.CreateStudy(ctx, study); err != nil {
		t.Fatal(err)
	}
	if _, err := service.GetStudy(ctx, studyName, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := service.ListStudies(ctx, &internalexperimentv1.ListStudiesRequest{Parent: experimentName, Page: &commonv1.PageRequest{PageSize: 10}}); err != nil {
		t.Fatal(err)
	}
	if _, err := service.TransitionStudy(ctx, &experimentv1.TransitionStudyCommand{Context: &commonv1.CommandContext{IdempotencyKey: "study-transition"}, Study: studyRef, ExpectedState: experimentv1.StudyState_STUDY_STATE_CREATED, TargetState: experimentv1.StudyState_STUDY_STATE_RUNNING, Etag: studyRef.GetEtag(), ReasonCode: "ADMITTED"}); err != nil {
		t.Fatal(err)
	}
	trial := &experimentv1.CreateTrialCommand{Context: &commonv1.CommandContext{IdempotencyKey: "trial-create"}, Study: studyRef, TrialId: "trial-1", TrialNumber: 1, ResolvedConfiguration: experimentSDKArtifact("6")}
	if _, err := service.CreateTrial(ctx, trial); err != nil {
		t.Fatal(err)
	}
	if _, err := service.GetTrial(ctx, trialName, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := service.ListTrials(ctx, &internalexperimentv1.ListTrialsRequest{Parent: studyName, Page: &commonv1.PageRequest{PageSize: 10}}); err != nil {
		t.Fatal(err)
	}
	if _, err := service.TransitionTrial(ctx, &experimentv1.TransitionTrialCommand{Context: &commonv1.CommandContext{IdempotencyKey: "trial-transition"}, Trial: trialRef, ExpectedState: experimentv1.TrialState_TRIAL_STATE_CREATED, TargetState: experimentv1.TrialState_TRIAL_STATE_ADMITTED, Etag: trialRef.GetEtag(), ReasonCode: "CAPACITY_AVAILABLE"}); err != nil {
		t.Fatal(err)
	}
	if _, err := service.CompleteTrial(ctx, &experimentv1.CompleteTrialCommand{Context: &commonv1.CommandContext{IdempotencyKey: "trial-complete"}, Trial: trialRef, Outcome: experimentv1.TrialOutcome_TRIAL_OUTCOME_SUCCEEDED, ResultManifest: experimentSDKArtifact("7"), Evidence: []*artifactv1.EvidenceRef{{Digest: experimentSDKDigest("8"), SubjectDigest: experimentSDKDigest("9"), EvidenceKind: "trial-result"}}, Etag: trialRef.GetEtag()}); err != nil {
		t.Fatal(err)
	}

	server.mu.Lock()
	requests := append([]proto.Message(nil), server.requests...)
	canonicalRequestID := server.canonicalRequestID
	server.mu.Unlock()
	if len(requests) != 14 {
		t.Fatalf("received %d experiment RPCs, want all 14 descriptor methods", len(requests))
	}
	if !canonicalRequestID {
		t.Fatal("experiment facade omitted canonical x-request-id metadata or sent a legacy alias")
	}
	if create.GetContext().GetTenantId() != "forged" {
		t.Fatal("facade mutated caller-owned generated input")
	}
	capturedCreate := requests[0].(*internalexperimentv1.CreateExperimentRequest).GetCommand()
	if capturedCreate.GetContext().GetTenantId() != config.TenantID || capturedCreate.GetContext().GetProjectId() != config.ProjectID || capturedCreate.GetContext().GetPrincipalId() != config.PrincipalID || !validSHA256Digest(capturedCreate.GetContext().GetCanonicalRequestDigest()) {
		t.Fatalf("captured generated command context was not authoritative: %+v", capturedCreate.GetContext())
	}
	if token := requests[2].(*internalexperimentv1.ListExperimentsRequest).GetPage().GetPageToken(); token != " opaque-token== " {
		t.Fatalf("opaque page token was changed: %q", token)
	}
	for _, index := range []int{0, 3, 4, 5, 8, 9, 12, 13} {
		if !validateExperimentMutationRetry(requests[index], requestMetadata{idempotencyKey: experimentCommandContext(requests[index]).GetIdempotencyKey()}, config) {
			t.Fatalf("experiment mutation %T was not exact-digest retry safe", requests[index])
		}
	}
}

func experimentCommandContext(request proto.Message) *commonv1.CommandContext {
	reflected := request.ProtoReflect()
	commandField := reflected.Descriptor().Fields().ByName("command")
	if commandField == nil || !reflected.Has(commandField) {
		return nil
	}
	command := reflected.Get(commandField).Message()
	contextField := command.Descriptor().Fields().ByName("context")
	if contextField == nil || !command.Has(contextField) {
		return nil
	}
	value, _ := command.Get(contextField).Message().Interface().(*commonv1.CommandContext)
	return value
}

func TestExperimentFacadeRejectsScopeAndBoundsBeforeTransport(t *testing.T) {
	service, server, _ := experimentSDKFixture(t)
	if _, err := service.Get(context.Background(), "tenants/other/projects/other/experiments/x", ""); err == nil {
		t.Fatal("cross-tenant experiment read was accepted")
	}
	if _, err := service.List(context.Background(), &internalexperimentv1.ListExperimentsRequest{Page: &commonv1.PageRequest{PageSize: 201}}); err == nil {
		t.Fatal("unbounded experiment page was accepted")
	}
	if _, err := service.ListPage(context.Background(), -1, ""); err == nil {
		t.Fatal("negative experiment page was accepted at the signed-to-unsigned boundary")
	}
	if _, err := service.ListPage(context.Background(), 201, ""); err == nil {
		t.Fatal("oversized experiment page was accepted at the signed-to-unsigned boundary")
	}
	if _, err := service.Transition(context.Background(), &experimentv1.TransitionExperimentCommand{ReasonCode: "free form"}); err == nil {
		t.Fatal("invalid experiment transition was accepted")
	}
	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.requests) != 0 {
		t.Fatalf("invalid requests reached transport: %d", len(server.requests))
	}
}
