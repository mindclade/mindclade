package mindclade

import (
	"context"
	"path"
	"strings"

	"google.golang.org/protobuf/proto"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

// AdminService is the private generated-type-only tenant, project, and audit
// facade. Its scope is fixed by authenticated client configuration.
type AdminService struct {
	client    *Client
	transport internaladminv1.AdminServiceClient
}

func (service *AdminService) GetTenant(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*adminv1.Tenant, error) {
	if name != configuredTenantName(service.client.config) {
		return nil, invalidArgument("tenant name must match the configured tenant")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetTenant(callContext, &internaladminv1.GetTenantRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetTenant() == nil {
		return nil, protocolDataLoss("GetTenant response omitted its tenant")
	}
	return cloneGenerated(response.GetTenant()), nil
}

func (service *AdminService) UpdateTenant(ctx context.Context, request *internaladminv1.UpdateTenantRequest, options ...RequestOption) (*jobv1.Operation, error) {
	materialized := cloneGenerated(request)
	if materialized == nil || materialized.GetTenant() == nil || materialized.GetTenant().GetName() != configuredTenantName(service.client.config) || materialized.GetUpdateMask() == nil || strings.TrimSpace(materialized.GetEtag()) == "" {
		return nil, invalidArgument("tenant update requires the configured tenant, field mask, and etag")
	}
	callContext, cancel, err := service.prepareMutation(ctx, materialized, materialized.GetContext(), func(value *commonv1.CommandContext) { materialized.Context = value }, "", options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.UpdateTenant(callContext, materialized)
	return operationResponse(response.GetOperation(), rpcErr, "UpdateTenant")
}

func (service *AdminService) CreateProject(ctx context.Context, request *internaladminv1.CreateProjectRequest, options ...RequestOption) (*jobv1.Operation, error) {
	materialized := cloneGenerated(request)
	projectID := configuredProjectID(service.client.config)
	if materialized == nil || materialized.GetProject() == nil || (materialized.GetProjectId() != "" && materialized.GetProjectId() != projectID) {
		return nil, invalidArgument("project create requires the configured project")
	}
	tenant := configuredTenantName(service.client.config)
	if materialized.GetParent() != "" && materialized.GetParent() != tenant {
		return nil, invalidArgument("project parent must match the configured tenant")
	}
	materialized.Parent = tenant
	materialized.ProjectId = projectID
	if materialized.Project.GetTenant() == nil {
		materialized.Project.Tenant = &commonv1.ResourceRef{ResourceType: "tenant", ResourceId: path.Base(tenant), TenantId: service.client.config.TenantID, Name: tenant}
	} else if !normalizeTenantReference(service.client.config, materialized.Project.Tenant) {
		return nil, invalidArgument("project tenant reference must match the configured tenant")
	}
	callContext, cancel, err := service.prepareMutation(ctx, materialized, materialized.GetContext(), func(value *commonv1.CommandContext) { materialized.Context = value }, service.client.config.ProjectID, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.CreateProject(callContext, materialized)
	return operationResponse(response.GetOperation(), rpcErr, "CreateProject")
}

func (service *AdminService) GetProject(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*adminv1.Project, error) {
	if name != projectName(service.client.config.TenantID, service.client.config.ProjectID) {
		return nil, invalidArgument("project name must match the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetProject(callContext, &internaladminv1.GetProjectRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetProject() == nil {
		return nil, protocolDataLoss("GetProject response omitted its project")
	}
	return cloneGenerated(response.GetProject()), nil
}

func (service *AdminService) ListProjects(ctx context.Context, request *internaladminv1.ListProjectsRequest, options ...RequestOption) (*internaladminv1.ListProjectsResponse, error) {
	materialized := cloneGenerated(request)
	if materialized == nil {
		materialized = &internaladminv1.ListProjectsRequest{}
	}
	parent := configuredTenantName(service.client.config)
	if materialized.GetParent() != "" && materialized.GetParent() != parent {
		return nil, invalidArgument("project list parent must match the configured tenant")
	}
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("project page size cannot exceed 1000")
	}
	materialized.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListProjects(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

func (service *AdminService) UpdateProject(ctx context.Context, request *internaladminv1.UpdateProjectRequest, options ...RequestOption) (*jobv1.Operation, error) {
	materialized := cloneGenerated(request)
	if materialized == nil || materialized.GetProject() == nil || materialized.GetProject().GetName() != projectName(service.client.config.TenantID, service.client.config.ProjectID) || materialized.GetUpdateMask() == nil || strings.TrimSpace(materialized.GetEtag()) == "" {
		return nil, invalidArgument("project update requires the configured project, field mask, and etag")
	}
	callContext, cancel, err := service.prepareMutation(ctx, materialized, materialized.GetContext(), func(value *commonv1.CommandContext) { materialized.Context = value }, service.client.config.ProjectID, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.UpdateProject(callContext, materialized)
	return operationResponse(response.GetOperation(), rpcErr, "UpdateProject")
}

func (service *AdminService) QueryAudit(ctx context.Context, query *adminv1.AuditQuery, options ...RequestOption) (*adminv1.AuditQueryPage, error) {
	materialized := cloneGenerated(query)
	if !validateAuditQueryScope(service.client.config, materialized) {
		return nil, invalidArgument("audit query must be bounded to the configured tenant or project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.QueryAuditRecords(callContext, &internaladminv1.QueryAuditRecordsRequest{Query: materialized})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetResult() == nil {
		return nil, protocolDataLoss("QueryAuditRecords response omitted its result page")
	}
	return cloneGenerated(response.GetResult()), nil
}

func (service *AdminService) ExportAudit(ctx context.Context, query *adminv1.AuditQuery, options ...RequestOption) (*jobv1.Operation, error) {
	materializedQuery := cloneGenerated(query)
	if !validateAuditQueryScope(service.client.config, materializedQuery) {
		return nil, invalidArgument("audit export query must be bounded to the configured tenant or project")
	}
	request := &internaladminv1.ExportAuditRecordsRequest{Query: materializedQuery}
	callContext, cancel, err := service.prepareMutation(ctx, request, request.GetContext(), func(value *commonv1.CommandContext) { request.Context = value }, auditProjectScope(service.client.config, materializedQuery.GetParent()), options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.ExportAuditRecords(callContext, request)
	return operationResponse(response.GetOperation(), rpcErr, "ExportAuditRecords")
}

func (service *AdminService) GetAuditExport(ctx context.Context, name string, options ...RequestOption) (*adminv1.AuditExport, error) {
	if !scopedResourceName(service.client.config, name, "auditExports") {
		return nil, invalidArgument("audit export name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetAuditExport(callContext, &internaladminv1.GetAuditExportRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetAuditExport() == nil {
		return nil, protocolDataLoss("GetAuditExport response omitted its export")
	}
	return cloneGenerated(response.GetAuditExport()), nil
}

func (service *AdminService) prepareMutation(ctx context.Context, request proto.Message, existing *commonv1.CommandContext, assign func(*commonv1.CommandContext), projectID string, options ...RequestOption) (context.Context, context.CancelFunc, error) {
	key := existing.GetIdempotencyKey()
	assign(nil)
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, nil, err
	}
	digest, err := deterministicDigest(request)
	if err != nil {
		cancel()
		return nil, nil, err
	}
	command := commandContext(service.client.config, callContext, metadata, digest)
	command.ProjectId = projectID
	assign(command)
	return callContext, cancel, nil
}

func configuredTenantName(config Config) string {
	if strings.HasPrefix(config.TenantID, "tenants/") {
		return config.TenantID
	}
	return "tenants/" + config.TenantID
}

func configuredProjectID(config Config) string {
	return path.Base(projectName(config.TenantID, config.ProjectID))
}

func normalizeTenantReference(config Config, reference *commonv1.ResourceRef) bool {
	name := configuredTenantName(config)
	if reference == nil || reference.GetName() != name || (reference.GetResourceType() != "" && reference.GetResourceType() != "tenant") || (reference.GetTenantId() != "" && reference.GetTenantId() != config.TenantID) || (reference.GetResourceId() != "" && reference.GetResourceId() != path.Base(name)) {
		return false
	}
	reference.ResourceType = "tenant"
	reference.ResourceId = path.Base(name)
	reference.TenantId = config.TenantID
	reference.ProjectId = ""
	return true
}

func validateAuditQueryScope(config Config, query *adminv1.AuditQuery) bool {
	if query == nil || query.GetStartTime() == nil || query.GetStartTime().CheckValid() != nil || query.GetEndTime() == nil || query.GetEndTime().CheckValid() != nil || !query.GetEndTime().AsTime().After(query.GetStartTime().AsTime()) || query.GetPage().GetPageSize() > 1000 {
		return false
	}
	tenant, project := configuredTenantName(config), projectName(config.TenantID, config.ProjectID)
	if query.GetParent() != tenant && query.GetParent() != project {
		return false
	}
	for _, resource := range query.GetResources() {
		if !normalizePolicyResource(config, resource) {
			return false
		}
	}
	return true
}

func auditProjectScope(config Config, parent string) string {
	if parent == configuredTenantName(config) {
		return ""
	}
	return config.ProjectID
}
