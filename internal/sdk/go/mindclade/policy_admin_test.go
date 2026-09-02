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
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

type policySDKServer struct {
	internalpolicyv1.UnimplementedPolicyServiceServer
	mu       sync.Mutex
	requests []proto.Message
}

func (server *policySDKServer) record(value proto.Message) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.requests = append(server.requests, proto.Clone(value))
}

func (server *policySDKServer) EvaluateAuthorization(_ context.Context, request *internalpolicyv1.EvaluateAuthorizationRequest) (*internalpolicyv1.EvaluateAuthorizationResponse, error) {
	server.record(request)
	return &internalpolicyv1.EvaluateAuthorizationResponse{Decision: &policyv1.AuthorizationDecision{Name: "decisions/decision-a", Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY}}, nil
}

func (server *policySDKServer) CreateUsePolicy(_ context.Context, request *internalpolicyv1.CreateUsePolicyRequest) (*internalpolicyv1.CreateUsePolicyResponse, error) {
	server.record(request)
	return &internalpolicyv1.CreateUsePolicyResponse{Operation: sdkOperation("create-policy")}, nil
}

func (server *policySDKServer) UpdateUsePolicy(_ context.Context, request *internalpolicyv1.UpdateUsePolicyRequest) (*internalpolicyv1.UpdateUsePolicyResponse, error) {
	server.record(request)
	return &internalpolicyv1.UpdateUsePolicyResponse{Operation: sdkOperation("update-policy")}, nil
}

func (server *policySDKServer) GetUsePolicy(_ context.Context, request *internalpolicyv1.GetUsePolicyRequest) (*internalpolicyv1.GetUsePolicyResponse, error) {
	server.record(request)
	return &internalpolicyv1.GetUsePolicyResponse{UsePolicy: &policyv1.UsePolicy{Name: request.GetName(), Revision: 1, Etag: "etag-policy"}}, nil
}

func (server *policySDKServer) ListUsePolicies(_ context.Context, request *internalpolicyv1.ListUsePoliciesRequest) (*internalpolicyv1.ListUsePoliciesResponse, error) {
	server.record(request)
	return &internalpolicyv1.ListUsePoliciesResponse{UsePolicies: []*policyv1.UsePolicy{{Name: request.GetParent() + "/usePolicies/safe"}}}, nil
}

func (server *policySDKServer) ActivateUsePolicy(_ context.Context, request *internalpolicyv1.ActivateUsePolicyRequest) (*internalpolicyv1.ActivateUsePolicyResponse, error) {
	server.record(request)
	return &internalpolicyv1.ActivateUsePolicyResponse{Operation: sdkOperation("activate-policy")}, nil
}

func (server *policySDKServer) RevokeUsePolicy(_ context.Context, request *internalpolicyv1.RevokeUsePolicyRequest) (*internalpolicyv1.RevokeUsePolicyResponse, error) {
	server.record(request)
	return &internalpolicyv1.RevokeUsePolicyResponse{Operation: sdkOperation("revoke-policy")}, nil
}

func (server *policySDKServer) ResolvePolicySnapshot(_ context.Context, request *internalpolicyv1.ResolvePolicySnapshotRequest) (*internalpolicyv1.ResolvePolicySnapshotResponse, error) {
	server.record(request)
	return &internalpolicyv1.ResolvePolicySnapshotResponse{PolicySnapshot: &policyv1.PolicyReference{Name: request.GetName(), Digest: "sha256:" + strings.Repeat("a", 64)}}, nil
}

type adminSDKServer struct {
	internaladminv1.UnimplementedAdminServiceServer
	mu       sync.Mutex
	requests []proto.Message
}

func (server *adminSDKServer) record(value proto.Message) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.requests = append(server.requests, proto.Clone(value))
}

func (server *adminSDKServer) GetTenant(_ context.Context, request *internaladminv1.GetTenantRequest) (*internaladminv1.GetTenantResponse, error) {
	server.record(request)
	return &internaladminv1.GetTenantResponse{Tenant: &adminv1.Tenant{Name: request.GetName(), Revision: 1, Etag: "tenant-etag"}}, nil
}

func (server *adminSDKServer) UpdateTenant(_ context.Context, request *internaladminv1.UpdateTenantRequest) (*internaladminv1.UpdateTenantResponse, error) {
	server.record(request)
	return &internaladminv1.UpdateTenantResponse{Operation: sdkOperation("update-tenant")}, nil
}

func (server *adminSDKServer) CreateProject(_ context.Context, request *internaladminv1.CreateProjectRequest) (*internaladminv1.CreateProjectResponse, error) {
	server.record(request)
	return &internaladminv1.CreateProjectResponse{Operation: sdkOperation("create-project")}, nil
}

func (server *adminSDKServer) GetProject(_ context.Context, request *internaladminv1.GetProjectRequest) (*internaladminv1.GetProjectResponse, error) {
	server.record(request)
	return &internaladminv1.GetProjectResponse{Project: &adminv1.Project{Name: request.GetName(), Revision: 1, Etag: "project-etag"}}, nil
}

func (server *adminSDKServer) ListProjects(_ context.Context, request *internaladminv1.ListProjectsRequest) (*internaladminv1.ListProjectsResponse, error) {
	server.record(request)
	return &internaladminv1.ListProjectsResponse{Projects: []*adminv1.Project{{Name: "tenants/tenant-a/projects/project-a"}}}, nil
}

func (server *adminSDKServer) UpdateProject(_ context.Context, request *internaladminv1.UpdateProjectRequest) (*internaladminv1.UpdateProjectResponse, error) {
	server.record(request)
	return &internaladminv1.UpdateProjectResponse{Operation: sdkOperation("update-project")}, nil
}

func (server *adminSDKServer) QueryAuditRecords(_ context.Context, request *internaladminv1.QueryAuditRecordsRequest) (*internaladminv1.QueryAuditRecordsResponse, error) {
	server.record(request)
	return &internaladminv1.QueryAuditRecordsResponse{Result: &adminv1.AuditQueryPage{Records: []*adminv1.AuditRecord{{EventId: "event-a"}}}}, nil
}

func (server *adminSDKServer) ExportAuditRecords(_ context.Context, request *internaladminv1.ExportAuditRecordsRequest) (*internaladminv1.ExportAuditRecordsResponse, error) {
	server.record(request)
	return &internaladminv1.ExportAuditRecordsResponse{Operation: sdkOperation("export-audit")}, nil
}

func (server *adminSDKServer) GetAuditExport(_ context.Context, request *internaladminv1.GetAuditExportRequest) (*internaladminv1.GetAuditExportResponse, error) {
	server.record(request)
	return &internaladminv1.GetAuditExportResponse{AuditExport: &adminv1.AuditExport{Name: request.GetName(), State: adminv1.AuditExportState_AUDIT_EXPORT_STATE_SUCCEEDED}}, nil
}

func sdkOperation(id string) *jobv1.Operation {
	return &jobv1.Operation{OperationId: "operations/" + id, State: jobv1.OperationState_OPERATION_STATE_PENDING}
}

func policyAdminSDKClient(t *testing.T) (*Client, *policySDKServer, *adminSDKServer) {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	policyServer, adminServer := &policySDKServer{}, &adminSDKServer{}
	internalpolicyv1.RegisterPolicyServiceServer(grpcServer, policyServer)
	internaladminv1.RegisterAdminServiceServer(grpcServer, adminServer)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(grpcServer.Stop)
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client, err := NewWithTransportForTesting(newTransportClients(connection), WithTenantProject("tenant-a", "project-a"), WithPrincipal("principal-a"))
	if err != nil {
		t.Fatal(err)
	}
	return client, policyServer, adminServer
}

func TestPolicyFacadeCoversGeneratedServiceAndAuthoritativeContext(t *testing.T) {
	client, server, _ := policyAdminSDKClient(t)
	ctx := context.Background()
	parent, name := "tenants/tenant-a/projects/project-a", "tenants/tenant-a/projects/project-a/usePolicies/safe"
	created, err := client.Policies.Create(ctx, &internalpolicyv1.CreateUsePolicyRequest{UsePolicyId: "safe", UsePolicy: &policyv1.UsePolicy{DisplayName: "Safe"}, Context: &commonv1.CommandContext{TenantId: "attacker", IdempotencyKey: "caller-key"}})
	if err != nil || created.GetOperationId() == "" {
		t.Fatalf("create policy: operation=%v err=%v", created, err)
	}
	if _, err = client.Policies.Update(ctx, &internalpolicyv1.UpdateUsePolicyRequest{UsePolicy: &policyv1.UsePolicy{Name: name}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: "etag-policy"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Policies.Get(ctx, name, ""); err != nil {
		t.Fatal(err)
	}
	if page, listErr := client.Policies.List(ctx, nil); listErr != nil || len(page.GetUsePolicies()) != 1 {
		t.Fatalf("list policies: page=%v err=%v", page, listErr)
	}
	if _, err = client.Policies.Activate(ctx, name, "etag-policy"); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Policies.Revoke(ctx, name, "etag-policy-2", "WITHDRAWN"); err != nil {
		t.Fatal(err)
	}
	now := timestamppb.Now()
	if _, err = client.Policies.ResolveSnapshot(ctx, name, now); err != nil {
		t.Fatal(err)
	}
	decision, err := client.Policies.Evaluate(ctx, &internalpolicyv1.EvaluateAuthorizationRequest{Action: "model.read", IntentDigest: "sha256:" + strings.Repeat("b", 64), Resource: &commonv1.ResourceRef{Name: parent + "/models/model-a"}})
	if err != nil || decision.GetOutcome() != policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY {
		t.Fatalf("evaluate: decision=%v err=%v", decision, err)
	}
	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.requests) != 8 {
		t.Fatalf("received %d policy RPCs, want 8", len(server.requests))
	}
	createRequest := server.requests[0].(*internalpolicyv1.CreateUsePolicyRequest)
	if createRequest.GetParent() != parent || createRequest.GetContext().GetTenantId() != "tenant-a" || createRequest.GetContext().GetProjectId() != "project-a" || createRequest.GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatalf("authoritative create request = %v", createRequest)
	}
	createContext := createRequest.GetContext()
	if !retryPermitted("/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy", createRequest, requestMetadata{idempotencyKey: createContext.GetIdempotencyKey()}, client.config) {
		t.Fatal("fully bound policy mutation was not retry-safe")
	}
}

func TestAdminFacadeCoversGeneratedServiceAndScopesCommands(t *testing.T) {
	client, _, server := policyAdminSDKClient(t)
	ctx := context.Background()
	tenant, project := "tenants/tenant-a", "tenants/tenant-a/projects/project-a"
	if _, err := client.Admin.GetTenant(ctx, tenant, ""); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Admin.UpdateTenant(ctx, &internaladminv1.UpdateTenantRequest{Tenant: &adminv1.Tenant{Name: tenant}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: "tenant-etag"}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Admin.CreateProject(ctx, &internaladminv1.CreateProjectRequest{Project: &adminv1.Project{DisplayName: "Project", Purpose: "research"}}); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Admin.GetProject(ctx, project, ""); err != nil {
		t.Fatal(err)
	}
	if page, err := client.Admin.ListProjects(ctx, nil); err != nil || len(page.GetProjects()) != 1 {
		t.Fatalf("list projects: page=%v err=%v", page, err)
	}
	if _, err := client.Admin.UpdateProject(ctx, &internaladminv1.UpdateProjectRequest{Project: &adminv1.Project{Name: project}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: "project-etag"}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	query := &adminv1.AuditQuery{Parent: project, StartTime: timestamppb.New(now.Add(-time.Hour)), EndTime: timestamppb.New(now)}
	if page, err := client.Admin.QueryAudit(ctx, query); err != nil || len(page.GetRecords()) != 1 {
		t.Fatalf("query audit: page=%v err=%v", page, err)
	}
	if _, err := client.Admin.ExportAudit(ctx, query, WithIdempotencyKey("audit-export-key")); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Admin.GetAuditExport(ctx, project+"/auditExports/export-a"); err != nil {
		t.Fatal(err)
	}
	server.mu.Lock()
	defer server.mu.Unlock()
	if len(server.requests) != 9 {
		t.Fatalf("received %d admin RPCs, want 9", len(server.requests))
	}
	tenantUpdate := server.requests[1].(*internaladminv1.UpdateTenantRequest)
	projectCreate := server.requests[2].(*internaladminv1.CreateProjectRequest)
	if tenantUpdate.GetContext().GetProjectId() != "" || tenantUpdate.GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatalf("tenant update context = %v", tenantUpdate.GetContext())
	}
	if !retryPermitted("/mindclade.internal.admin.v1.AdminService/UpdateTenant", tenantUpdate, requestMetadata{idempotencyKey: tenantUpdate.GetContext().GetIdempotencyKey()}, client.config) {
		t.Fatal("tenant-scoped administrative mutation was not retry-safe")
	}
	if projectCreate.GetParent() != tenant || projectCreate.GetProjectId() != "project-a" || projectCreate.GetContext().GetProjectId() != "project-a" {
		t.Fatalf("project create request = %v", projectCreate)
	}
}
