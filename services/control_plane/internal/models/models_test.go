package models

import (
	"context"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
)

var fixtureTime = time.Date(2026, 9, 1, 12, 0, 0, 0, time.UTC)

type fixedResolver struct {
	identity Identity
	err      error
}

func (r fixedResolver) Resolve(context.Context) (Identity, error) { return r.identity, r.err }

type fixedClock struct{ at time.Time }

func (c fixedClock) Now() time.Time { return c.at }

type fakeRepository struct {
	command   *modelv1.RegisterModelCommand
	operation *jobv1.Operation
	model     *modelv1.Model
	release   *modelv1.ModelRelease
}

func (r *fakeRepository) RegisterModel(_ context.Context, _ Identity, command *modelv1.RegisterModelCommand, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.command = clone(command)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) GetModel(context.Context, Identity, string) (*modelv1.Model, error) {
	if r.model == nil {
		return nil, ErrNotFound
	}
	return clone(r.model), nil
}

func (r *fakeRepository) ListModels(context.Context, Identity, ModelPage) ([]*modelv1.Model, string, time.Time, error) {
	return []*modelv1.Model{clone(r.model)}, "", fixtureTime, nil
}

func (*fakeRepository) RegisterModelRelease(context.Context, Identity, *modelv1.RegisterModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, missingEvent(RegisterReleaseEventContract)
}

func (r *fakeRepository) GetModelRelease(context.Context, Identity, string) (*modelv1.ModelRelease, error) {
	if r.release == nil {
		return nil, ErrNotFound
	}
	return clone(r.release), nil
}

func (r *fakeRepository) ListModelReleases(context.Context, Identity, ReleasePage) ([]*modelv1.ModelRelease, string, time.Time, error) {
	return []*modelv1.ModelRelease{clone(r.release)}, "", fixtureTime, nil
}

func (*fakeRepository) PromoteModelRelease(context.Context, Identity, *modelv1.PromoteModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) RevokeModelRelease(context.Context, Identity, *modelv1.RevokeModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func identityFixture() Identity {
	return Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
}

func contextFixture(message proto.Message) *commonv1.CommandContext {
	digest, err := canonicalCommandDigest(message)
	if err != nil {
		panic(err)
	}
	return &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "key-1", TenantId: "tenant-1", ProjectId: "project-1", PrincipalId: "principal-1", TraceId: "trace-1", Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), CanonicalRequestDigest: digest}
}

func artifactFixture(character string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(character, 64), MediaType: "application/json", SizeBytes: 42}
}

func evidenceFixture(character string) *artifactv1.EvidenceRef {
	return &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat(character, 64), SubjectDigest: "sha256:" + strings.Repeat("a", 64), EvidenceKind: "qualification", PolicyDigest: "sha256:" + strings.Repeat("b", 64)}
}

func serverFixture(t *testing.T, repository Repository) *Server {
	t.Helper()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, fixedResolver{identity: identityFixture()}, codec)
	if err != nil {
		t.Fatal(err)
	}
	return server.withClock(fixedClock{at: fixtureTime})
}

func TestRegisterModelUsesGeneratedCloneAndAuthenticatedContext(t *testing.T) {
	identity := identityFixture()
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true}
	repository := &fakeRepository{operation: operation}
	server := serverFixture(t, repository)
	command := &modelv1.RegisterModelCommand{Project: &commonv1.ResourceRef{ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: projectParent(identity)}, ModelId: "nova", DisplayName: "Nova", Family: "clade", DefinitionManifest: artifactFixture("a"), FeatureRequirementSet: artifactFixture("b"), ModelFeatureView: artifactFixture("c"), InputContract: artifactFixture("d"), OutputContract: artifactFixture("e")}
	command.Context = contextFixture(command)
	response, err := server.RegisterModel(context.Background(), &internalmodelv1.RegisterModelRequest{Command: command})
	if err != nil {
		t.Fatal(err)
	}
	command.DisplayName = "mutated"
	if repository.command.GetDisplayName() != "Nova" || response.GetOperation() == operation {
		t.Fatal("generated request/response alias escaped server boundary")
	}
	if repository.command.GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatal("server did not materialize authoritative command digest")
	}
}

func TestRegisterModelReleaseMapsMissingEventContract(t *testing.T) {
	server := serverFixture(t, &fakeRepository{})
	command := &modelv1.RegisterModelReleaseCommand{ReleaseId: "v1"}
	command.Context = contextFixture(command)
	_, err := server.RegisterModelRelease(context.Background(), &internalmodelv1.RegisterModelReleaseRequest{Command: command})
	if status.Code(err) != codes.FailedPrecondition || !strings.Contains(err.Error(), RegisterReleaseEventContract) {
		t.Fatalf("error=%v", err)
	}
}

func TestGeneratedModelEventsAreRegistryValidatedAndDecodable(t *testing.T) {
	identity := identityFixture()
	model := &modelv1.Model{Name: projectParent(identity) + "/models/nova", Uid: "mdl-1", Revision: 1, Etag: resourceETag("nova", 1), TenantName: "tenants/" + identity.TenantID, ProjectName: projectParent(identity), Family: "clade", DefinitionManifest: artifactFixture("a"), FeatureRequirementSet: artifactFixture("b"), ModelFeatureView: artifactFixture("c"), CreateTime: timestamppb.New(fixtureTime)}
	context := &commonv1.CommandContext{RequestId: "request-1", TraceId: "trace-1"}
	event, err := (GeneratedEventFactory{}).Registered(identity, model, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := pubsubx.UnmarshalRegisteredPayload(event)
	if err != nil {
		t.Fatal(err)
	}
	registered, ok := decoded.(*modelv1.ModelRegistered)
	if !ok || registered.GetModelName() != model.GetName() {
		t.Fatalf("decoded=%T %v", decoded, decoded)
	}
	release := &modelv1.ModelRelease{Name: projectParent(identity) + "/models/nova/releases/v1", Uid: "rel-1", Revision: 1, Etag: resourceETag("release", 1), TenantName: "tenants/" + identity.TenantID, ProjectName: projectParent(identity), Stage: modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL}
	release.ModelName = model.GetName()
	release.ReleaseId = "v1"
	release.BundleManifest = artifactFixture("a")
	release.ModelManifest = artifactFixture("b")
	release.Checkpoint = &commonv1.ResourceRef{ResourceType: "checkpoint", ResourceId: "checkpoint-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/checkpoints/checkpoint-1", Etag: "checkpoint-etag"}
	release.EvaluationEvidence = []*artifactv1.EvidenceRef{evidenceFixture("c")}
	release.FeatureRequirementSet = artifactFixture("d")
	release.ModelFeatureView = artifactFixture("e")
	release.ReleasePolicy = &commonv1.ResourceRef{ResourceType: "release_policy", ResourceId: "policy-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/releasePolicies/policy-1", Etag: "policy-etag"}
	release.CreateTime = timestamppb.New(fixtureTime)
	operation := &jobv1.Operation{OperationId: "operations/op-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Etag: resourceETag("operations/op-1", 1)}
	releaseRegistered, err := (GeneratedEventFactory{}).ReleaseRegistered(identity, release, operation, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err = pubsubx.UnmarshalRegisteredPayload(releaseRegistered)
	if err != nil {
		t.Fatal(err)
	}
	if value, ok := decoded.(*modelv1.ModelReleaseRegistered); !ok || value.GetModelReleaseName() != release.GetName() || value.GetOperation() == nil {
		t.Fatalf("release registered payload=%T %v", decoded, decoded)
	}
	release.Revision = 2
	release.Etag = resourceETag(release.GetName(), 2)
	release.Stage = modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED
	promoted, err := (GeneratedEventFactory{}).Promoted(identity, release, modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL, []*artifactv1.EvidenceRef{evidenceFixture("c")}, evidenceFixture("d"), context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pubsubx.UnmarshalRegisteredPayload(promoted); err != nil {
		t.Fatal(err)
	}
	release.Revision = 3
	release.Stage = modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_REVOKED
	release.RevocationReason = "invalid evidence"
	revoked, err := (GeneratedEventFactory{}).Revoked(identity, release, []*artifactv1.EvidenceRef{evidenceFixture("e")}, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = pubsubx.UnmarshalRegisteredPayload(revoked); err != nil {
		t.Fatal(err)
	}
}

func TestModelPageTokenIsTamperEvidentAndScoped(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "models", Tenant: "t", Project: "p", Order: "create_time desc,name desc"}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, Order: expected.Order, AfterTime: fixtureTime.Format(time.RFC3339Nano), AfterName: "last"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = codec.decode(encoded, expected); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(encoded, ".")
	if _, err = codec.decode("A"+parts[0][1:]+"."+parts[1], expected); err == nil {
		t.Fatal("tampered token accepted")
	}
	expected.Tenant = "other"
	if _, err = codec.decode(encoded, expected); err == nil {
		t.Fatal("cross-tenant token accepted")
	}
}

func TestModelGeneratedServiceRegistration(t *testing.T) {
	grpcServer := grpc.NewServer()
	Register(grpcServer, serverFixture(t, &fakeRepository{}))
	if _, ok := grpcServer.GetServiceInfo()["mindclade.internal.model.v1.ModelService"]; !ok {
		t.Fatal("generated ModelService was not registered")
	}
}
