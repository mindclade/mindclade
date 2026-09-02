package mindclade

import (
	"context"
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

// PolicyService is the private generated-type-only policy lifecycle and
// authorization facade. Authenticated SDK configuration, never caller-owned
// request fields, is authoritative for tenant, project, and principal scope.
type PolicyService struct {
	client    *Client
	transport internalpolicyv1.PolicyServiceClient
}

func (service *PolicyService) Evaluate(ctx context.Context, request *internalpolicyv1.EvaluateAuthorizationRequest, options ...RequestOption) (*policyv1.AuthorizationDecision, error) {
	materialized := cloneGenerated(request)
	if materialized == nil || strings.TrimSpace(materialized.GetAction()) == "" || materialized.GetResource() == nil || !validSHA256Digest(materialized.GetIntentDigest()) {
		return nil, invalidArgument("authorization evaluation requires an action, resource, and sha256 intent digest")
	}
	if !normalizePolicyResource(service.client.config, materialized.Resource) {
		return nil, invalidArgument("authorization resource must be in the configured project")
	}
	materialized.TenantId = service.client.config.TenantID
	materialized.ProjectId = service.client.config.ProjectID
	materialized.PrincipalRef = service.client.config.PrincipalID
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	deadline, _ := callContext.Deadline()
	materialized.Deadline = timestamppb.New(deadline)
	digest, err := deterministicDigest(materialized)
	if err != nil {
		return nil, err
	}
	materialized.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.EvaluateAuthorization(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetDecision() == nil {
		return nil, protocolDataLoss("EvaluateAuthorization response omitted its decision")
	}
	return cloneGenerated(response.GetDecision()), nil
}

func (service *PolicyService) Create(ctx context.Context, request *internalpolicyv1.CreateUsePolicyRequest, options ...RequestOption) (*jobv1.Operation, error) {
	materialized := cloneGenerated(request)
	if materialized == nil || materialized.GetUsePolicy() == nil || !validResourceIdentifier(materialized.GetUsePolicyId()) {
		return nil, invalidArgument("policy create requires a generated policy and valid policy ID")
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if materialized.GetParent() != "" && materialized.GetParent() != parent {
		return nil, invalidArgument("policy parent must match the configured project")
	}
	materialized.Parent = parent
	callContext, cancel, err := service.prepareMutation(ctx, materialized, materialized.GetContext(), func(value *commonv1.CommandContext) { materialized.Context = value }, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.CreateUsePolicy(callContext, materialized)
	return operationResponse(response.GetOperation(), rpcErr, "CreateUsePolicy")
}

func (service *PolicyService) Update(ctx context.Context, request *internalpolicyv1.UpdateUsePolicyRequest, options ...RequestOption) (*jobv1.Operation, error) {
	materialized := cloneGenerated(request)
	if materialized == nil || materialized.GetUsePolicy() == nil || !scopedResourceName(service.client.config, materialized.GetUsePolicy().GetName(), "usePolicies") || materialized.GetUpdateMask() == nil || strings.TrimSpace(materialized.GetEtag()) == "" {
		return nil, invalidArgument("policy update requires a scoped policy, field mask, and etag")
	}
	callContext, cancel, err := service.prepareMutation(ctx, materialized, materialized.GetContext(), func(value *commonv1.CommandContext) { materialized.Context = value }, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.UpdateUsePolicy(callContext, materialized)
	return operationResponse(response.GetOperation(), rpcErr, "UpdateUsePolicy")
}

func (service *PolicyService) Get(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*policyv1.UsePolicy, error) {
	if !scopedResourceName(service.client.config, name, "usePolicies") {
		return nil, invalidArgument("policy name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetUsePolicy(callContext, &internalpolicyv1.GetUsePolicyRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetUsePolicy() == nil {
		return nil, protocolDataLoss("GetUsePolicy response omitted its policy")
	}
	return cloneGenerated(response.GetUsePolicy()), nil
}

// UsePolicyPage is one bounded list response plus cursor-scheme traversal. The
// embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type UsePolicyPage struct {
	*internalpolicyv1.ListUsePoliciesResponse
	pageBase[*policyv1.UsePolicy, *UsePolicyPage]
}

// Items returns this page's use policies without traversing any further page.
func (page *UsePolicyPage) Items() []*policyv1.UsePolicy { return page.GetUsePolicies() }

func (service *PolicyService) List(ctx context.Context, request *internalpolicyv1.ListUsePoliciesRequest, options ...RequestOption) (*UsePolicyPage, error) {
	materialized := cloneGenerated(request)
	if materialized == nil {
		materialized = &internalpolicyv1.ListUsePoliciesRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if materialized.GetParent() != "" && materialized.GetParent() != parent {
		return nil, invalidArgument("policy list parent must match the configured project")
	}
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("policy page size cannot exceed 1000")
	}
	materialized.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListUsePolicies(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	detached := cloneGenerated(response)
	page := &UsePolicyPage{ListUsePoliciesResponse: detached}
	page.pageBase = newPage[*policyv1.UsePolicy](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*UsePolicyPage, error) {
		successor := cloneGenerated(materialized)
		successor.Page = pageRequestWithToken(materialized.GetPage(), token)
		return service.List(ctx, successor, options...)
	})
	return page, nil
}

func (service *PolicyService) Activate(ctx context.Context, name, etag string, options ...RequestOption) (*jobv1.Operation, error) {
	if !scopedResourceName(service.client.config, name, "usePolicies") || strings.TrimSpace(etag) == "" {
		return nil, invalidArgument("policy activation requires a scoped name and etag")
	}
	request := &internalpolicyv1.ActivateUsePolicyRequest{Name: name, Etag: strings.TrimSpace(etag)}
	callContext, cancel, err := service.prepareMutation(ctx, request, request.GetContext(), func(value *commonv1.CommandContext) { request.Context = value }, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.ActivateUsePolicy(callContext, request)
	return operationResponse(response.GetOperation(), rpcErr, "ActivateUsePolicy")
}

func (service *PolicyService) Revoke(ctx context.Context, name, etag, reasonCode string, options ...RequestOption) (*jobv1.Operation, error) {
	if !scopedResourceName(service.client.config, name, "usePolicies") || strings.TrimSpace(etag) == "" || strings.TrimSpace(reasonCode) == "" {
		return nil, invalidArgument("policy revocation requires a scoped name, etag, and reason code")
	}
	request := &internalpolicyv1.RevokeUsePolicyRequest{Name: name, Etag: strings.TrimSpace(etag), ReasonCode: strings.TrimSpace(reasonCode)}
	callContext, cancel, err := service.prepareMutation(ctx, request, request.GetContext(), func(value *commonv1.CommandContext) { request.Context = value }, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.RevokeUsePolicy(callContext, request)
	return operationResponse(response.GetOperation(), rpcErr, "RevokeUsePolicy")
}

func (service *PolicyService) ResolveSnapshot(ctx context.Context, name string, effectiveTime *timestamppb.Timestamp, options ...RequestOption) (*policyv1.PolicyReference, error) {
	if !scopedResourceName(service.client.config, name, "usePolicies") || effectiveTime == nil || effectiveTime.CheckValid() != nil {
		return nil, invalidArgument("snapshot resolution requires a scoped policy and valid effective time")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ResolvePolicySnapshot(callContext, &internalpolicyv1.ResolvePolicySnapshotRequest{Name: name, EffectiveTime: cloneGenerated(effectiveTime)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetPolicySnapshot() == nil {
		return nil, protocolDataLoss("ResolvePolicySnapshot response omitted its snapshot")
	}
	return cloneGenerated(response.GetPolicySnapshot()), nil
}

func (service *PolicyService) prepareMutation(ctx context.Context, request proto.Message, existing *commonv1.CommandContext, assign func(*commonv1.CommandContext), options ...RequestOption) (context.Context, context.CancelFunc, error) {
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
	assign(commandContext(service.client.config, callContext, metadata, digest))
	return callContext, cancel, nil
}

func normalizePolicyResource(config Config, resource *commonv1.ResourceRef) bool {
	if resource == nil || (resource.GetTenantId() != "" && resource.GetTenantId() != config.TenantID) || (resource.GetProjectId() != "" && resource.GetProjectId() != config.ProjectID) {
		return false
	}
	parent := projectName(config.TenantID, config.ProjectID)
	if resource.GetName() != parent && !strings.HasPrefix(resource.GetName(), parent+"/") {
		return false
	}
	resource.TenantId = config.TenantID
	resource.ProjectId = config.ProjectID
	return true
}

func validSHA256Digest(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") {
		return false
	}
	for _, character := range value[7:] {
		if (character < '0' || character > '9') && (character < 'a' || character > 'f') {
			return false
		}
	}
	return true
}
