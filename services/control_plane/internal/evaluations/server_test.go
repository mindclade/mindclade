package evaluations

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
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
	create func(context.Context, Identity, *internalevaluationv1.CreateEvaluationRunRequest, string, time.Time) (*operationv1.Operation, bool, error)
}

func (repository fakeRepository) CreateRun(ctx context.Context, identity Identity, request *internalevaluationv1.CreateEvaluationRunRequest, digest string, at time.Time) (*operationv1.Operation, bool, error) {
	return repository.create(ctx, identity, request, digest, at)
}

func (fakeRepository) GetRun(context.Context, Identity, string) (*evaluationv1.EvaluationRun, error) {
	return nil, ErrNotFound
}

func (fakeRepository) ListRuns(context.Context, Identity, RunPage) ([]*evaluationv1.EvaluationRun, string, time.Time, error) {
	return nil, "", time.Unix(1, 0).UTC(), nil
}

func (fakeRepository) CancelRun(context.Context, Identity, *internalevaluationv1.CancelEvaluationRunRequest, string, time.Time) (*operationv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (fakeRepository) CommitResult(context.Context, Identity, *internalevaluationv1.CommitEvaluationResultRequest, string, time.Time) (*evaluationv1.EvaluationResult, *evaluationv1.EvaluationRun, bool, error) {
	return nil, nil, false, ErrNotFound
}

func (fakeRepository) GetResult(context.Context, Identity, string) (*evaluationv1.EvaluationResult, error) {
	return nil, ErrNotFound
}

func (fakeRepository) CreatePromotionDecision(context.Context, Identity, *internalevaluationv1.CreatePromotionDecisionRequest, string, time.Time) (*operationv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (fakeRepository) GetPromotionDecision(context.Context, Identity, string) (*evaluationv1.PromotionDecision, error) {
	return nil, ErrNotFound
}

func testArtifact(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + seed, MediaType: "application/vnd.mindclade.test+json", SizeBytes: 12, ArtifactKind: "test", SchemaId: "mindclade.test.v1"}
}

func testReference(identity Identity, kind, id string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/" + kind + "s/" + id, Etag: "sha256:" + strings64("e")}
}

func strings64(value string) string {
	result := ""
	for len(result) < 64 {
		result += value
	}
	return result[:64]
}

func validCreateRequest(identity Identity, now time.Time) *internalevaluationv1.CreateEvaluationRunRequest {
	policyDocument := testArtifact(strings64("a"))
	return &internalevaluationv1.CreateEvaluationRunRequest{
		Context: &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "idem-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(now.Add(time.Minute))},
		Parent:  projectParent(identity), EvaluationRunId: "eval-1", Suite: testArtifact(strings64("b")), Datasets: []*artifactv1.ArtifactRef{testArtifact(strings64("c"))}, Snapshot: testArtifact(strings64("d")), ModelRelease: testReference(identity, "model_release", "release-1"), InferenceProtocol: testArtifact(strings64("f")),
		PolicySnapshots: []*policyv1.PolicyReference{{Name: projectParent(identity) + "/policies/safety", Uid: "policy-1", PolicyType: "safety", Version: "1.0.0", Digest: "sha256:" + strings64("1"), Document: policyDocument, ResourceRevision: 1, EffectiveTime: timestamppb.New(now.Add(-time.Hour))}},
	}
}

func TestNetworkCreateEvaluationRunUsesGeneratedServiceAndAuthoritativeDigest(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
	called := false
	repository := fakeRepository{create: func(_ context.Context, got Identity, request *internalevaluationv1.CreateEvaluationRunRequest, digest string, at time.Time) (*operationv1.Operation, bool, error) {
		called = true
		if got != identity {
			t.Fatalf("identity=%+v", got)
		}
		if !validSHA256(digest) {
			t.Fatalf("digest=%q", digest)
		}
		if !at.Equal(now) {
			t.Fatalf("at=%s", at)
		}
		request.EvaluationRunId = "mutated"
		return &operationv1.Operation{OperationId: "operations/op-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: "jobs/job-1", State: operationv1.OperationState_OPERATION_STATE_PENDING, ResourceVersion: 1, Etag: "sha256:" + strings64("9"), CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now)}, false, nil
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
	client := internalevaluationv1.NewEvaluationServiceClient(connection)
	request := validCreateRequest(identity, now)
	response, err := client.CreateEvaluationRun(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if !called || response.GetOperation().GetOperationId() != "operations/op-1" {
		t.Fatalf("response=%v called=%v", response, called)
	}
	if request.GetEvaluationRunId() != "eval-1" {
		t.Fatal("server leaked mutable request alias")
	}
}

func TestCreateEvaluationRunRejectsCallerSuppliedCrossTenantContext(t *testing.T) {
	now := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
	codec, _ := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	repository := fakeRepository{create: func(context.Context, Identity, *internalevaluationv1.CreateEvaluationRunRequest, string, time.Time) (*operationv1.Operation, bool, error) {
		t.Fatal("repository must not be called")
		return nil, false, nil
	}}
	server, _ := NewServer(repository, staticIdentityResolver{identity}, codec)
	server.withClock(fixedClock{now})
	request := validCreateRequest(identity, now)
	request.Context.TenantId = "other-tenant"
	_, err := server.CreateEvaluationRun(context.Background(), request)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("code=%s err=%v", status.Code(err), err)
	}
}

func TestPageTokensAreSignedAndBoundToAuthenticatedQuery(t *testing.T) {
	t.Parallel()
	codec, err := NewPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "evaluation-runs", Tenant: "tenant-1", Project: "project-1", Filter: "state=EVALUATION_RUN_STATE_RUNNING", Order: "create_time desc,name desc"}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, Filter: expected.Filter, Order: expected.Order, AfterTime: time.Unix(10, 0).UTC().Format(time.RFC3339Nano), AfterName: "evaluationRuns/run-1"})
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := codec.decode(encoded, expected)
	if err != nil || decoded.AfterName != "evaluationRuns/run-1" {
		t.Fatalf("decoded=%+v err=%v", decoded, err)
	}
	tampered := []byte(encoded)
	if tampered[len(tampered)-1] == 'A' {
		tampered[len(tampered)-1] = 'B'
	} else {
		tampered[len(tampered)-1] = 'A'
	}
	if _, err = codec.decode(string(tampered), expected); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("tampered token err=%v", err)
	}
	mismatched := expected
	mismatched.Project = "project-2"
	if _, err = codec.decode(encoded, mismatched); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("cross-project token err=%v", err)
	}
}

func TestPersistenceTimestampPrecisionIsExplicit(t *testing.T) {
	t.Parallel()
	precise := timestamppb.New(time.Unix(10, 123_456_000).UTC())
	if _, err := requireTimestamp(precise, "precise"); err != nil {
		t.Fatalf("microsecond timestamp rejected: %v", err)
	}
	overPrecise := timestamppb.New(time.Unix(10, 123_456_789).UTC())
	if _, err := requireTimestamp(overPrecise, "over-precise"); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("nanosecond timestamp err=%v", err)
	}
}
