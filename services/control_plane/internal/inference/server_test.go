package inference

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

type staticIdentityResolver struct{ identity Identity }

func (resolver staticIdentityResolver) Resolve(context.Context) (Identity, error) {
	return resolver.identity, nil
}

type fixedClock struct{ now time.Time }

func (clock fixedClock) Now() time.Time { return clock.now }

type fakeRepository struct {
	submit      func(context.Context, Identity, *inferencev1.InferenceRequest, string, time.Time) (*jobv1.Operation, bool, error)
	request     *inferencev1.InferenceRequest
	result      *inferencev1.InferenceResult
	operation   *jobv1.Operation
	revisions   []*jobv1.Operation
	requestName string
}

func (repository *fakeRepository) Submit(ctx context.Context, identity Identity, request *inferencev1.InferenceRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if repository.submit != nil {
		return repository.submit(ctx, identity, request, digest, at)
	}
	return clone(repository.operation), false, nil
}

func (repository *fakeRepository) GetRequest(context.Context, Identity, string) (*inferencev1.InferenceRequest, error) {
	if repository.request == nil {
		return nil, ErrNotFound
	}
	return clone(repository.request), nil
}

func (repository *fakeRepository) GetResult(context.Context, Identity, string) (*inferencev1.InferenceResult, *jobv1.Operation, error) {
	if repository.result == nil || repository.operation == nil {
		return nil, nil, ErrNotFound
	}
	return clone(repository.result), clone(repository.operation), nil
}

func (repository *fakeRepository) CommitResult(_ context.Context, _ Identity, _ *internalinferencev1.CommitInferenceResultRequest, _ string, _ time.Time) (*inferencev1.InferenceResult, *jobv1.Operation, bool, error) {
	return clone(repository.result), clone(repository.operation), false, nil
}

func (repository *fakeRepository) ReadOperationRevisions(_ context.Context, _ Identity, _ string, after uint64, limit int) (string, []*jobv1.Operation, bool, error) {
	var values []*jobv1.Operation
	for _, revision := range repository.revisions {
		sequence, err := numconv.Int64ToUint64(revision.GetResourceVersion())
		if err != nil {
			return "", nil, false, err
		}
		if sequence > after {
			values = append(values, clone(revision))
		}
	}
	if len(values) > limit {
		values = values[:limit]
	}
	current, err := numconv.Int64ToUint64(repository.operation.GetResourceVersion())
	if err != nil {
		return "", nil, false, err
	}
	terminal := len(values) == 0 && after == current || len(values) > 0 && values[len(values)-1].GetDone()
	return repository.requestName, values, terminal, nil
}

func (repository *fakeRepository) GetResultByRequest(context.Context, Identity, string) (*inferencev1.InferenceResult, error) {
	if repository.result == nil {
		return nil, ErrNotFound
	}
	return clone(repository.result), nil
}

func digestFixture(seed string) string { return "sha256:" + strings.Repeat(seed, 64) }

func artifactFixture(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: digestFixture(seed), MediaType: "application/vnd.mindclade.test+json", SizeBytes: 64, ArtifactKind: "test", SchemaId: "mindclade.test.v1", SchemaVersion: "1.0.0"}
}

func referenceFixture(identity Identity, kind, id string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/" + kind + "s/" + id, Etag: digestFixture("e")}
}

func policyFixture(identity Identity, now time.Time) *policyv1.PolicyReference {
	return &policyv1.PolicyReference{Name: projectParent(identity) + "/policies/safety", Uid: "policy-1", PolicyType: "safety", Version: "1.0.0", Digest: digestFixture("a"), Document: artifactFixture("b"), ResourceRevision: 1, EffectiveTime: timestamppb.New(now.Add(-time.Hour)), Classification: "internal"}
}

func inferenceRequestFixture(identity Identity, now time.Time) *inferencev1.InferenceRequest {
	payload := []byte("bounded inference input")
	inputDigest, _ := canonicalBytesDigest(payload)
	return &inferencev1.InferenceRequest{
		Context: &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "idempotency-1", PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Deadline: timestamppb.New(now.Add(2 * time.Minute)), TraceId: "trace-1"},
		Name:    projectParent(identity) + "/inferenceRequests/request-1", Uid: "inference-request-uid-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		Capability: "structure_prediction", Mode: inferencev1.InferenceMode_INFERENCE_MODE_ASYNCHRONOUS,
		Model: referenceFixture(identity, "model", "model-1"), ResolvedModelBundle: artifactFixture("c"),
		Input:         &inferencev1.InferenceRequest_InlineInput{InlineInput: &inferencev1.BoundedInlineInput{MediaType: "application/json", SchemaId: "mindclade.input.v1", Payload: payload, ContentDigest: inputDigest}},
		FeaturePolicy: artifactFixture("d"), SamplingPolicy: &inferencev1.SamplingPolicy{Algorithm: "deterministic", AlgorithmVersion: "1", CandidateCount: 2, MaximumSteps: 20, Temperature: pointer(0.0), GuidanceScale: pointer(1.0), RandomKey: "seed-reference-1", MaximumComputeTime: durationpb.New(time.Minute), Policy: artifactFixture("f")},
		ConfidencePolicy: artifactFixture("1"), OutputOptions: &inferencev1.InferenceOutputOptions{ResultSchemaId: "mindclade.result.v1", RequestedArtifactKinds: []string{"result_manifest", "candidate"}, IncludeBoundedCandidateSummaries: true},
		ResourceClass: "cpu-test", Reproducibility: inferencev1.ReproducibilityIntent_REPRODUCIBILITY_INTENT_BITWISE,
		PolicySnapshots: []*policyv1.PolicyReference{policyFixture(identity, now)}, DataClassification: "internal", Deadline: timestamppb.New(now.Add(time.Hour)), CreateTime: timestamppb.New(now),
	}
}

func canonicalBytesDigest(value []byte) (string, error) {
	message := &inferencev1.BoundedInlineInput{Payload: value}
	digest, err := canonicalDigest(message)
	if err != nil {
		return "", err
	}
	// canonicalDigest includes protobuf framing; inline content uses raw bytes.
	_ = digest
	return rawDigest(value), nil
}

func rawDigest(value []byte) string {
	sum := sha256.Sum256(value)
	return "sha256:" + hex.EncodeToString(sum[:])
}

func pointer(value float64) *float64 { return &value }

func operationFixture(identity Identity, request *inferencev1.InferenceRequest, revision int64, state jobv1.OperationState, done bool, now time.Time) *jobv1.Operation {
	return &jobv1.Operation{OperationId: "operations/op-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: "jobs/job-1", State: state, ResourceVersion: revision, Done: done, Etag: resourceETag("operations/op-1", revision), Target: requestResource(identity, request, request.GetContext().GetCanonicalRequestDigest()), CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now.Add(time.Duration(revision) * time.Second))}
}

func resultFixture(identity Identity, request *inferencev1.InferenceRequest, operation *jobv1.Operation, now time.Time) *inferencev1.InferenceResult {
	return &inferencev1.InferenceResult{Name: projectParent(identity) + "/inferenceResults/result-1", Uid: "result-uid-1", Request: requestResource(identity, request, request.GetContext().GetCanonicalRequestDigest()), RequestDigest: request.GetContext().GetCanonicalRequestDigest(), Operation: operationResource(operation), JobId: operation.GetJobId(), RunId: "runs/run-1", AttemptId: "attempts/attempt-1", LeaseEpoch: 1, Outcome: inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_SUCCEEDED, ResultManifest: artifactFixture("2"), ModelBundle: clone(request.GetResolvedModelBundle()), Candidates: []*inferencev1.InferenceCandidateResult{{CandidateId: "candidate-1", SampleIndex: 0, Output: artifactFixture("3"), Confidence: pointer(0.9), Selected: true}}, SelectedCandidateId: "candidate-1", SourceRevision: "revision-1", CompletedAt: timestamppb.New(now.Add(time.Minute)), ResultDigest: digestFixture("4")}
}

func networkClient(t *testing.T, server *Server) internalinferencev1.InferenceServiceClient {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	if err := Register(grpcServer, server); err != nil {
		t.Fatal(err)
	}
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() { grpcServer.Stop(); _ = listener.Close() })
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	return internalinferencev1.NewInferenceServiceClient(connection)
}

func TestNetworkInferenceGeneratedServiceAndResumableTerminalWatch(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1", WorkerID: "worker-1", LeaseToken: strings.Repeat("token", 8)}
	request := inferenceRequestFixture(identity, now)
	digest, err := canonicalDigest(request)
	if err != nil {
		t.Fatal(err)
	}
	materializeContext(identity, request, digest)
	pending := operationFixture(identity, request, 1, jobv1.OperationState_OPERATION_STATE_PENDING, false, now)
	terminal := operationFixture(identity, request, 2, jobv1.OperationState_OPERATION_STATE_SUCCEEDED, true, now)
	result := resultFixture(identity, request, terminal, now)
	called := false
	repository := &fakeRepository{request: request, result: result, operation: terminal, revisions: []*jobv1.Operation{pending, terminal}, requestName: request.GetName()}
	repository.submit = func(_ context.Context, got Identity, value *inferencev1.InferenceRequest, supplied string, at time.Time) (*jobv1.Operation, bool, error) {
		called = true
		if got != identity || supplied != digest || !at.Equal(now) || value.GetContext().GetPrincipalId() != identity.Principal {
			t.Fatalf("submit identity=%+v digest=%q at=%s value=%v", got, supplied, at, value)
		}
		value.Name = "mutated-by-repository"
		return pending, false, nil
	}
	codec, err := NewCursorCodec([]byte(strings.Repeat("cursor-key-", 4)), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, staticIdentityResolver{identity}, codec, 10*time.Millisecond, 20*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{now})
	client := networkClient(t, server)
	original := clone(request)
	response, err := client.SubmitInference(context.Background(), &internalinferencev1.SubmitInferenceRequest{InferenceRequest: request})
	if err != nil || !called || response.GetOperation().GetOperationId() != pending.GetOperationId() {
		t.Fatalf("submit response=%v called=%v err=%v", response, called, err)
	}
	if !proto.Equal(request, original) {
		t.Fatal("server leaked mutable request alias")
	}
	stream, err := client.WatchInference(context.Background(), &internalinferencev1.WatchInferenceRequest{OperationName: terminal.GetOperationId(), Deadline: timestamppb.New(now.Add(time.Minute))})
	if err != nil {
		t.Fatal(err)
	}
	first, err := stream.Recv()
	if err != nil || first.GetMessage().GetProgress() == nil || first.GetMessage().GetSequence() != 1 || first.GetMessage().GetResumeToken() == "" {
		t.Fatalf("first=%v err=%v", first, err)
	}
	last, err := stream.Recv()
	if err != nil || last.GetMessage().GetFinalResult().GetResultDigest() != result.GetResultDigest() || last.GetMessage().GetSequence() != 2 {
		t.Fatalf("last=%v err=%v", last, err)
	}
	if _, err = stream.Recv(); !errors.Is(err, io.EOF) {
		t.Fatalf("terminal stream err=%v", err)
	}
	resume := &inferencev1.InferenceStreamCursor{RequestName: request.GetName(), AfterSequence: 2, ResumeToken: last.GetMessage().GetResumeToken()}
	resumed, err := client.WatchInference(context.Background(), &internalinferencev1.WatchInferenceRequest{OperationName: terminal.GetOperationId(), Cursor: resume, Deadline: timestamppb.New(now.Add(time.Minute))})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = resumed.Recv(); !errors.Is(err, io.EOF) {
		t.Fatalf("terminal reconnect err=%v", err)
	}
	read, err := client.GetInferenceRequest(context.Background(), &internalinferencev1.GetInferenceRequestRequest{Name: request.GetName()})
	if err != nil || !proto.Equal(read.GetInferenceRequest(), request) {
		t.Fatalf("read=%v err=%v", read, err)
	}
	resultRead, err := client.GetInferenceResult(context.Background(), &internalinferencev1.GetInferenceResultRequest{OperationName: terminal.GetOperationId()})
	if err != nil || !proto.Equal(resultRead.GetResult(), result) {
		t.Fatalf("result=%v err=%v", resultRead, err)
	}
}

func TestCursorBindingTamperExpiryAndCrossResource(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
	codec, err := NewCursorCodec([]byte(strings.Repeat("cursor-key-", 4)), time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	token, err := codec.Encode(identity, "operations/op-1", projectParent(identity)+"/inferenceRequests/request-1", 7, now)
	if err != nil {
		t.Fatal(err)
	}
	if sequence, decodeErr := codec.Decode(token, identity, "operations/op-1", projectParent(identity)+"/inferenceRequests/request-1", now); decodeErr != nil || sequence != 7 {
		t.Fatalf("sequence=%d err=%v", sequence, decodeErr)
	}
	if _, decodeErr := codec.Decode(token+"x", identity, "operations/op-1", projectParent(identity)+"/inferenceRequests/request-1", now); !errors.Is(decodeErr, ErrCursorMalformed) {
		t.Fatalf("tamper err=%v", decodeErr)
	}
	if _, decodeErr := codec.Decode(token, identity, "operations/other", projectParent(identity)+"/inferenceRequests/request-1", now); !errors.Is(decodeErr, ErrCursorResource) {
		t.Fatalf("resource err=%v", decodeErr)
	}
	if _, decodeErr := codec.Decode(token, identity, "operations/op-1", projectParent(identity)+"/inferenceRequests/request-1", now.Add(time.Minute)); !errors.Is(decodeErr, ErrCursorExpired) {
		t.Fatalf("expiry err=%v", decodeErr)
	}
}

func TestSubmitRejectsCallerSelectedScope(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
	codec, _ := NewCursorCodec([]byte(strings.Repeat("cursor-key-", 4)), time.Hour)
	repository := &fakeRepository{submit: func(context.Context, Identity, *inferencev1.InferenceRequest, string, time.Time) (*jobv1.Operation, bool, error) {
		t.Fatal("repository must not be called")
		return nil, false, nil
	}}
	server, _ := NewServer(repository, staticIdentityResolver{identity}, codec, 10*time.Millisecond, 20*time.Millisecond)
	server.withClock(fixedClock{now})
	request := inferenceRequestFixture(identity, now)
	request.ProjectId = "other-project"
	_, err := server.SubmitInference(context.Background(), &internalinferencev1.SubmitInferenceRequest{InferenceRequest: request})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("code=%s err=%v", status.Code(err), err)
	}
}
