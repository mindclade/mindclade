package admin

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var fixtureTime = time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)

type fixedResolver struct{ identity Identity }

func (r fixedResolver) Resolve(context.Context) (Identity, error) { return r.identity, nil }

type fixedClock struct{ at time.Time }

func (c fixedClock) Now() time.Time { return c.at }

type fakeRepository struct {
	tenant    *adminv1.Tenant
	project   *adminv1.Project
	export    *adminv1.AuditExport
	record    *adminv1.AuditRecord
	operation *jobv1.Operation
	request   proto.Message
}

func (r *fakeRepository) GetTenant(context.Context, Identity, string) (*adminv1.Tenant, error) {
	return clone(r.tenant), nil
}

func (r *fakeRepository) UpdateTenant(_ context.Context, _ Identity, request *internaladminv1.UpdateTenantRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) CreateProject(_ context.Context, _ Identity, request *internaladminv1.CreateProjectRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) GetProject(context.Context, Identity, string) (*adminv1.Project, error) {
	return clone(r.project), nil
}

func (r *fakeRepository) ListProjects(context.Context, Identity, ProjectPage) ([]*adminv1.Project, string, time.Time, error) {
	return []*adminv1.Project{clone(r.project)}, "", fixtureTime, nil
}

func (r *fakeRepository) UpdateProject(_ context.Context, _ Identity, request *internaladminv1.UpdateProjectRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) QueryAuditRecords(context.Context, Identity, *adminv1.AuditQuery, AuditPage) ([]*adminv1.AuditRecord, string, error) {
	return []*adminv1.AuditRecord{clone(r.record)}, "", nil
}

func (r *fakeRepository) ExportAuditRecords(_ context.Context, _ Identity, request *internaladminv1.ExportAuditRecordsRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) GetAuditExport(context.Context, Identity, string) (*adminv1.AuditExport, error) {
	return clone(r.export), nil
}

func identityFixture() Identity { return Identity{TenantID: "tenant-1", Principal: "admin-1"} }

func tenantFixture() *adminv1.Tenant {
	name := "tenants/tenant-1"
	return &adminv1.Tenant{Name: name, Uid: "tenant-uid", Revision: 2, Etag: resourceETag(name, 2), DisplayName: "Tenant", State: adminv1.TenantState_TENANT_STATE_ACTIVE, CreateTime: timestamppb.New(fixtureTime), UpdateTime: timestamppb.New(fixtureTime)}
}

func projectFixture() *adminv1.Project {
	name := "tenants/tenant-1/projects/project-1"
	return &adminv1.Project{Name: name, Uid: "project-uid", Revision: 1, Etag: resourceETag(name, 1), Tenant: &commonv1.ResourceRef{ResourceType: "tenant", ResourceId: "tenant-1", TenantId: "tenant-1", ResourceVersion: 2, Name: "tenants/tenant-1"}, DisplayName: "Project", Purpose: "research", State: adminv1.ProjectState_PROJECT_STATE_PROVISIONING, CreateTime: timestamppb.New(fixtureTime), UpdateTime: timestamppb.New(fixtureTime)}
}

func exportFixture() *adminv1.AuditExport {
	name := "tenants/tenant-1/projects/project-1/auditExports/export-1"
	return &adminv1.AuditExport{Name: name, Uid: "export-1", Revision: 1, Etag: resourceETag(name, 1), State: adminv1.AuditExportState_AUDIT_EXPORT_STATE_FAILED, FailureCode: "EXPORTER_NOT_CONFIGURED", QueryDigest: "sha256:" + strings.Repeat("a", 64), CreateTime: timestamppb.New(fixtureTime), UpdateTime: timestamppb.New(fixtureTime), ExpireTime: timestamppb.New(fixtureTime.Add(time.Hour))}
}

func adminContext(message proto.Message, projectID string) *commonv1.CommandContext {
	digest, err := canonicalCommandDigest(message)
	if err != nil {
		panic(err)
	}
	return &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "key-1", TenantId: "tenant-1", ProjectId: projectID, PrincipalId: "admin-1", TraceId: "trace-1", Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), CanonicalRequestDigest: digest}
}

func queryFixture() *adminv1.AuditQuery {
	return &adminv1.AuditQuery{Parent: "tenants/tenant-1/projects/project-1", StartTime: timestamppb.New(fixtureTime.Add(-time.Hour)), EndTime: timestamppb.New(fixtureTime.Add(time.Hour)), Page: &commonv1.PageRequest{PageSize: 10}}
}

func serverFixture(t *testing.T, repository Repository) *Server {
	t.Helper()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("a", 32)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, fixedResolver{identity: identityFixture()}, codec)
	if err != nil {
		t.Fatal(err)
	}
	return server.withClock(fixedClock{at: fixtureTime})
}

func TestAdminServerClonesAndBindsAuthenticatedCommand(t *testing.T) {
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: "tenant-1", ProjectId: "project-1", State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true}
	repository := &fakeRepository{operation: operation}
	server := serverFixture(t, repository)
	request := &internaladminv1.CreateProjectRequest{Parent: "tenants/tenant-1", ProjectId: "project-1", Project: projectFixture()}
	request.Context = adminContext(request, "project-1")
	response, err := server.CreateProject(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	request.Project.DisplayName = "mutated"
	stored := repository.request.(*internaladminv1.CreateProjectRequest)
	if stored.GetProject().GetDisplayName() != "Project" || response.GetOperation() == operation {
		t.Fatal("generated request or response alias escaped admin transport")
	}
}

func TestGeneratedAdminEventsAreRegisteredAndDecodable(t *testing.T) {
	identity := identityFixture()
	identity.ProjectID = "project-1"
	context := &commonv1.CommandContext{RequestId: "request-1", TraceId: "trace-1"}
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Etag: "etag"}
	events := GeneratedEventFactory{}
	created, err := events.ProjectCreated(identity, projectFixture(), operation, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := queue.UnmarshalRegisteredPayload(created)
	if err != nil {
		t.Fatal(err)
	}
	if typed, ok := payload.(*adminv1.ProjectCreated); !ok || typed.GetProject().GetName() != projectFixture().GetName() {
		t.Fatalf("payload=%T %v", payload, payload)
	}
	completedExport := exportFixture()
	completedExport.State = adminv1.AuditExportState_AUDIT_EXPORT_STATE_SUCCEEDED
	completedExport.Revision = 2
	completedExport.Artifact = &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("b", 64), MediaType: "application/x-ndjson", SizeBytes: 10}
	completed, err := events.AuditExportCompleted(identity, completedExport, operation, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalRegisteredPayload(completed); err != nil {
		t.Fatal(err)
	}
}

func TestTenantUpdateEventSeparatesSemanticSequenceFromResourceRevision(t *testing.T) {
	t.Parallel()
	identity := identityFixture()
	command := &commonv1.CommandContext{RequestId: "tenant-update-1", TraceId: "trace-1"}
	events := GeneratedEventFactory{}
	tenant := tenantFixture()
	first, err := events.TenantUpdated(identity, tenant, []string{"state"}, nil, command, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	if first.GetAggregateSequence() != 1 || first.GetSubject().GetResourceVersion() != 2 {
		t.Fatalf("first update sequence=%d resource revision=%d", first.GetAggregateSequence(), first.GetSubject().GetResourceVersion())
	}
	if _, err = queue.UnmarshalRegisteredPayload(first); err != nil {
		t.Fatal(err)
	}

	secondTenant := clone(tenant)
	secondTenant.Revision = 3
	secondTenant.Etag = resourceETag(secondTenant.GetName(), 3)
	secondCommand := clone(command)
	secondCommand.RequestId = "tenant-update-2"
	second, err := events.TenantUpdated(identity, secondTenant, []string{"display_name"}, nil, secondCommand, fixtureTime.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if second.GetAggregateSequence() != 2 || second.GetSubject().GetResourceVersion() != 3 {
		t.Fatalf("second update sequence=%d resource revision=%d", second.GetAggregateSequence(), second.GetSubject().GetResourceVersion())
	}

	preProvisioning := clone(tenant)
	preProvisioning.Revision = 1
	if _, err = events.TenantUpdated(identity, preProvisioning, nil, nil, command, fixtureTime); err == nil {
		t.Fatal("tenant revision one cannot produce an update event with semantic sequence zero")
	}
}

func TestAdminPageTokenIsTamperEvidentAndQueryBound(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "audit-records", Tenant: "t", Project: "p", QueryDigest: "sha256:" + strings.Repeat("a", 64)}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, QueryDigest: expected.QueryDigest, AfterTime: fixtureTime.Format(time.RFC3339Nano), AfterID: "event"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = codec.decode(encoded, expected); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(encoded, ".")
	if _, err = codec.decode("A"+parts[0][1:]+"."+parts[1], expected); err == nil {
		t.Fatal("tampered admin token accepted")
	}
	expected.QueryDigest = "sha256:" + strings.Repeat("b", 64)
	if _, err = codec.decode(encoded, expected); err == nil {
		t.Fatal("token replayed against another audit query")
	}
}

func TestAdminGeneratedNetworkGRPCService(t *testing.T) {
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: "tenant-1", ProjectId: "project-1", State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true}
	repository := &fakeRepository{tenant: tenantFixture(), project: projectFixture(), export: exportFixture(), record: &adminv1.AuditRecord{EventId: "event-1", TenantId: "tenant-1", ProjectId: "project-1", OccurredAt: timestamppb.New(fixtureTime)}, operation: operation}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	Register(grpcServer, serverFixture(t, repository))
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(grpcServer.Stop)
	connection, err := grpc.NewClient("passthrough:///admin-test", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internaladminv1.NewAdminServiceClient(connection)
	if _, err = client.GetTenant(context.Background(), &internaladminv1.GetTenantRequest{Name: "tenants/tenant-1"}); err != nil {
		t.Fatal(err)
	}
	updateTenant := &internaladminv1.UpdateTenantRequest{Tenant: tenantFixture(), UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: tenantFixture().GetEtag()}
	updateTenant.Context = adminContext(updateTenant, "")
	if _, err = client.UpdateTenant(context.Background(), updateTenant); err != nil {
		t.Fatal(err)
	}
	createProject := &internaladminv1.CreateProjectRequest{Parent: "tenants/tenant-1", ProjectId: "project-1", Project: projectFixture()}
	createProject.Context = adminContext(createProject, "project-1")
	if _, err = client.CreateProject(context.Background(), createProject); err != nil {
		t.Fatal(err)
	}
	if _, err = client.GetProject(context.Background(), &internaladminv1.GetProjectRequest{Name: projectFixture().GetName()}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.ListProjects(context.Background(), &internaladminv1.ListProjectsRequest{Parent: "tenants/tenant-1", Page: &commonv1.PageRequest{PageSize: 10}}); err != nil {
		t.Fatal(err)
	}
	updateProject := &internaladminv1.UpdateProjectRequest{Project: projectFixture(), UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: projectFixture().GetEtag()}
	updateProject.Context = adminContext(updateProject, "project-1")
	if _, err = client.UpdateProject(context.Background(), updateProject); err != nil {
		t.Fatal(err)
	}
	query := queryFixture()
	if _, err = client.QueryAuditRecords(context.Background(), &internaladminv1.QueryAuditRecordsRequest{Query: query}); err != nil {
		t.Fatal(err)
	}
	export := &internaladminv1.ExportAuditRecordsRequest{Query: queryFixture()}
	export.Context = adminContext(export, "project-1")
	if _, err = client.ExportAuditRecords(context.Background(), export); err != nil {
		t.Fatal(err)
	}
	if _, err = client.GetAuditExport(context.Background(), &internaladminv1.GetAuditExportRequest{Name: exportFixture().GetName()}); err != nil {
		t.Fatal(err)
	}
}
