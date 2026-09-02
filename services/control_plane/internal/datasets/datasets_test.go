package datasets

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

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var testTime = time.Date(2026, 9, 1, 12, 0, 0, 0, time.UTC)

type fixedResolver struct {
	identity Identity
	err      error
}

func (r fixedResolver) Resolve(context.Context) (Identity, error) { return r.identity, r.err }

type fixedClock struct{ at time.Time }

func (c fixedClock) Now() time.Time { return c.at }

type fakeRepository struct {
	dataset *datasetv1.Dataset
	release *datasetv1.DatasetRelease
}

func (*fakeRepository) CreateDataset(context.Context, Identity, *datasetv1.CreateDatasetCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, missingEvent(CreateEventContract)
}

func (r *fakeRepository) GetDataset(context.Context, Identity, string) (*datasetv1.Dataset, error) {
	if r.dataset == nil {
		return nil, ErrNotFound
	}
	return clone(r.dataset), nil
}

func (r *fakeRepository) ListDatasets(context.Context, Identity, DatasetPage) ([]*datasetv1.Dataset, string, time.Time, error) {
	return []*datasetv1.Dataset{clone(r.dataset)}, "", testTime, nil
}

func (*fakeRepository) UpdateDataset(context.Context, Identity, *datasetv1.UpdateDatasetCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, missingEvent(UpdateEventContract)
}

func (*fakeRepository) PublishDatasetRelease(context.Context, Identity, *datasetv1.PublishDatasetReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, missingEvent(PublishEventContract)
}

func (*fakeRepository) RevokeDatasetRelease(context.Context, Identity, *datasetv1.RevokeDatasetReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, missingEvent(RevokeEventContract)
}

func (r *fakeRepository) GetDatasetRelease(context.Context, Identity, string) (*datasetv1.DatasetRelease, error) {
	if r.release == nil {
		return nil, ErrNotFound
	}
	return clone(r.release), nil
}

func (r *fakeRepository) ListDatasetReleases(context.Context, Identity, ReleasePage) ([]*datasetv1.DatasetRelease, string, time.Time, error) {
	return []*datasetv1.DatasetRelease{clone(r.release)}, "", testTime, nil
}

func testIdentity() Identity {
	return Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
}

func commandContext(message proto.Message) *commonv1.CommandContext {
	digest, err := canonicalCommandDigest(message)
	if err != nil {
		panic(err)
	}
	return &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "key-1", TenantId: "tenant-1", ProjectId: "project-1", PrincipalId: "principal-1", Deadline: timestamppb.New(testTime.Add(time.Minute)), CanonicalRequestDigest: digest}
}

func testServer(t *testing.T, repository Repository) *Server {
	t.Helper()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, fixedResolver{identity: testIdentity()}, codec)
	if err != nil {
		t.Fatal(err)
	}
	return server.withClock(fixedClock{at: testTime})
}

func TestDatasetMutationsFailClosedWithoutAuthoritativeEvents(t *testing.T) {
	server := testServer(t, &fakeRepository{})
	create := &datasetv1.CreateDatasetCommand{DatasetId: "data"}
	create.Context = commandContext(create)
	update := &datasetv1.UpdateDatasetCommand{Dataset: &datasetv1.Dataset{Name: "data"}, Etag: "etag"}
	update.Context = commandContext(update)
	publish := &datasetv1.PublishDatasetReleaseCommand{ReleaseId: "v1"}
	publish.Context = commandContext(publish)
	revoke := &datasetv1.RevokeDatasetReleaseCommand{Reason: "unsafe"}
	revoke.Context = commandContext(revoke)
	cases := []struct {
		name, contract string
		call           func() error
	}{{"create", CreateEventContract, func() error {
		_, err := server.CreateDataset(context.Background(), &internaldatasetv1.CreateDatasetRequest{Command: create})
		return err
	}}, {"update", UpdateEventContract, func() error {
		_, err := server.UpdateDataset(context.Background(), &internaldatasetv1.UpdateDatasetRequest{Command: update})
		return err
	}}, {"publish", PublishEventContract, func() error {
		_, err := server.PublishDatasetRelease(context.Background(), &internaldatasetv1.PublishDatasetReleaseRequest{Command: publish})
		return err
	}}, {"revoke", RevokeEventContract, func() error {
		_, err := server.RevokeDatasetRelease(context.Background(), &internaldatasetv1.RevokeDatasetReleaseRequest{Command: revoke})
		return err
	}}}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.call()
			if status.Code(err) != codes.FailedPrecondition || !strings.Contains(err.Error(), tc.contract) {
				t.Fatalf("error=%v", err)
			}
		})
	}
}

func TestDatasetResponsesAreCloned(t *testing.T) {
	stored := &datasetv1.Dataset{Name: "tenants/tenant-1/projects/project-1/datasets/data", DisplayName: "original", Labels: map[string]string{"env": "test"}}
	repository := &fakeRepository{dataset: stored}
	server := testServer(t, repository)
	response, err := server.GetDataset(context.Background(), &internaldatasetv1.GetDatasetRequest{Name: stored.GetName()})
	if err != nil {
		t.Fatal(err)
	}
	response.Dataset.DisplayName = "mutated"
	response.Dataset.Labels["env"] = "mutated"
	if repository.dataset.GetDisplayName() != "original" || repository.dataset.GetLabels()["env"] != "test" {
		t.Fatal("server leaked mutable protobuf alias")
	}
}

func TestGeneratedDatasetEventsAreRegistryValidatedAndDecodable(t *testing.T) {
	identity := testIdentity()
	parent := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
	dataset := &datasetv1.Dataset{
		Name:                 parent + "/datasets/pdb",
		Uid:                  "dataset-uid",
		Revision:             1,
		Etag:                 resourceETag(parent+"/datasets/pdb", 1),
		TenantName:           "tenants/" + identity.TenantID,
		ProjectName:          parent,
		DisplayName:          "PDB",
		State:                datasetv1.DatasetState_DATASET_STATE_DRAFT,
		PolicyClassification: "internal",
		CreateTime:           timestamppb.New(testTime),
	}
	operation := &jobv1.Operation{OperationId: "operations/op-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Etag: resourceETag("operations/op-1", 1)}
	command := &commonv1.CommandContext{RequestId: "request-1", TraceId: "trace-1"}
	factory := GeneratedEventFactory{}
	created, err := factory.Created(identity, dataset, operation, command, testTime)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := queue.UnmarshalRegisteredPayload(created)
	if err != nil {
		t.Fatal(err)
	}
	if value, ok := payload.(*datasetv1.DatasetCreated); !ok || value.GetDatasetName() != dataset.GetName() || value.GetOperation() == nil {
		t.Fatalf("created payload=%T %v", payload, payload)
	}

	dataset.Revision = 2
	dataset.Etag = resourceETag(dataset.GetName(), 2)
	dataset.State = datasetv1.DatasetState_DATASET_STATE_ACTIVE
	dataset.UpdateTime = timestamppb.New(testTime.Add(time.Second))
	updated, err := factory.Updated(identity, dataset, []string{"state"}, operation, command, testTime.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalRegisteredPayload(updated); err != nil {
		t.Fatal(err)
	}

	manifestDigest := "sha256:" + strings.Repeat("a", 64)
	release := &datasetv1.DatasetRelease{
		Name:                  dataset.GetName() + "/releases/v1",
		Uid:                   "release-uid",
		Revision:              1,
		Etag:                  resourceETag(dataset.GetName()+"/releases/v1", 1),
		TenantName:            dataset.GetTenantName(),
		ProjectName:           dataset.GetProjectName(),
		DatasetName:           dataset.GetName(),
		ReleaseId:             "v1",
		State:                 datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_PUBLISHED,
		Manifest:              &artifactv1.ArtifactRef{Digest: manifestDigest, MediaType: "application/json", SizeBytes: 1},
		QualificationEvidence: []*artifactv1.EvidenceRef{{Digest: "sha256:" + strings.Repeat("b", 64), SubjectDigest: manifestDigest, EvidenceKind: "qualification"}},
		CreateTime:            timestamppb.New(testTime),
		PublishTime:           timestamppb.New(testTime),
	}
	published, err := factory.Published(identity, release, operation, command, testTime)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalRegisteredPayload(published); err != nil {
		t.Fatal(err)
	}
	release.Revision = 2
	release.Etag = resourceETag(release.GetName(), 2)
	release.State = datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_REVOKED
	release.RevocationReason = "qualification withdrawn"
	release.RevokeTime = timestamppb.New(testTime.Add(2 * time.Second))
	revoked, err := factory.Revoked(identity, release, release.GetQualificationEvidence(), operation, command, testTime.Add(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalRegisteredPayload(revoked); err != nil {
		t.Fatal(err)
	}
}

func TestDatasetPageTokenIsTamperEvidentAndQueryBound(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "datasets", Tenant: "t", Project: "p", Filter: "state=ACTIVE", Order: "create_time desc,name desc"}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, Filter: expected.Filter, Order: expected.Order, AfterTime: testTime.Format(time.RFC3339Nano), AfterName: "last"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = codec.decode(encoded, expected); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(encoded, ".")
	tampered := "A" + parts[0][1:] + "." + parts[1]
	if _, err = codec.decode(tampered, expected); err == nil {
		t.Fatal("tampered token accepted")
	}
	expected.Project = "other"
	if _, err = codec.decode(encoded, expected); err == nil {
		t.Fatal("cross-project token accepted")
	}
}

func TestDatasetGeneratedServiceRegistration(t *testing.T) {
	server := testServer(t, &fakeRepository{})
	grpcServer := grpc.NewServer()
	Register(grpcServer, server)
	if _, ok := grpcServer.GetServiceInfo()["mindclade.internal.dataset.v1.DatasetService"]; !ok {
		t.Fatal("generated DatasetService was not registered")
	}
}
