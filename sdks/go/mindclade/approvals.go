package mindclade

import (
	"context"
	"crypto/subtle"
	"strings"

	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

// ApprovalService is the private generated-type-only facade for exact-intent
// approval requests and immutable receipt decisions/consumption.
type ApprovalService struct {
	client    *Client
	transport internalworkflowv1.ApprovalServiceClient
}

// Request records exact approval intent after replacing caller identity and
// verifying the canonical binding digest locally.
func (service *ApprovalService) Request(ctx context.Context, request *workflowv1.ApprovalRequest, options ...RequestOption) (*workflowv1.ApprovalRequest, error) {
	if !service.configured() || request == nil || request.GetBinding() == nil {
		return nil, invalidArgument("a generated approval request and binding are required")
	}
	value := cloneGenerated(request)
	key := value.GetContext().GetIdempotencyKey()
	value.Context = nil
	value.RequestedByPrincipalRef = service.client.config.PrincipalID
	if value.GetBinding().GetTool() != nil && !normalizeReferenceScope(service.client.config, value.GetBinding().GetTool()) {
		return nil, invalidArgument("approval tool must be in the configured scope")
	}
	for _, decision := range value.GetPolicyDecisions() {
		if decision.GetResource() != nil && !normalizeReferenceScope(service.client.config, decision.GetResource()) {
			return nil, invalidArgument("approval policy decision resource must be in the configured scope")
		}
	}
	if err := verifyApprovalBinding(value.GetBinding()); err != nil {
		return nil, err
	}
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, key, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.RequestApproval(callContext, &internalworkflowv1.RequestApprovalRequest{ApprovalRequest: value})
	if err != nil {
		return nil, normalizeError(err)
	}
	created := response.GetApprovalRequest()
	if created == nil || !scopedResourceName(service.client.config, created.GetName(), "approvalRequests") || created.GetBinding() == nil || subtle.ConstantTimeCompare([]byte(created.GetBinding().GetBindingDigest()), []byte(value.GetBinding().GetBindingDigest())) != 1 {
		return nil, protocolDataLoss("RequestApproval returned inconsistent durable intent")
	}
	return cloneGenerated(created), nil
}

// Get reads one generated approval request.
func (service *ApprovalService) Get(ctx context.Context, name string, options ...RequestOption) (*workflowv1.ApprovalRequest, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "approvalRequests") {
		return nil, invalidArgument("approval request name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetApprovalRequest(callContext, &internalworkflowv1.GetApprovalRequestRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetApprovalRequest() == nil {
		return nil, protocolDataLoss("GetApprovalRequest response omitted its approval request")
	}
	return cloneGenerated(response.GetApprovalRequest()), nil
}

// List returns one bounded generated page while preserving its opaque token.
func (service *ApprovalService) List(ctx context.Context, request *internalworkflowv1.ListApprovalRequestsRequest, options ...RequestOption) (*internalworkflowv1.ListApprovalRequestsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("approval service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalworkflowv1.ListApprovalRequestsRequest{}
	}
	expected := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() == "" {
		value.Parent = expected
	} else if value.GetParent() != expected {
		return nil, invalidArgument("approval list parent must match the configured project")
	}
	if value.GetPage().GetPageSize() > workflowMaximumPageSize {
		return nil, invalidArgument("approval page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListApprovalRequests(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

// Decide records one independently authenticated decision under an ETag and
// verifies the immutable receipt returned by the authority.
func (service *ApprovalService) Decide(ctx context.Context, request *internalworkflowv1.DecideApprovalRequest, options ...RequestOption) (*workflowv1.ApprovalReceipt, error) {
	if !service.configured() || request == nil || !scopedResourceName(service.client.config, request.GetName(), "approvalRequests") || strings.TrimSpace(request.GetEtag()) == "" || request.GetDecision() == workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_UNSPECIFIED || strings.TrimSpace(request.GetReasonCode()) == "" || len(request.GetSafeReason()) > 2048 {
		return nil, invalidArgument("approval decision requires a scoped request, ETag, decision, and bounded reason")
	}
	value := cloneGenerated(request)
	key := value.GetContext().GetIdempotencyKey()
	value.Context = nil
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, key, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.DecideApproval(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	receipt := response.GetApprovalReceipt()
	if err = validateDecisionReceipt(service.client.config, value, receipt); err != nil {
		return nil, err
	}
	return cloneGenerated(receipt), nil
}

// Consume atomically binds a receipt to one call and verifies the returned
// generated receipt against that exact binding and call identity.
func (service *ApprovalService) Consume(ctx context.Context, request *internalworkflowv1.ConsumeApprovalRequest, options ...RequestOption) (*workflowv1.ApprovalReceipt, error) {
	if !service.configured() || request == nil || !scopedResourceName(service.client.config, request.GetReceiptName(), "approvalReceipts") || !validSHA256Digest(request.GetBindingDigest()) || strings.TrimSpace(request.GetCallId()) == "" {
		return nil, invalidArgument("approval consumption requires a scoped receipt, binding digest, and call ID")
	}
	value := cloneGenerated(request)
	key := value.GetContext().GetIdempotencyKey()
	value.Context = nil
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, key, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.ConsumeApproval(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	receipt := response.GetApprovalReceipt()
	if receipt == nil || receipt.GetName() != value.GetReceiptName() || receipt.GetConsumedAt() == nil || receipt.GetConsumedAt().CheckValid() != nil || receipt.GetConsumedByCallId() != value.GetCallId() || receipt.GetBinding() == nil || subtle.ConstantTimeCompare([]byte(receipt.GetBinding().GetBindingDigest()), []byte(value.GetBindingDigest())) != 1 || !validSHA256Digest(receipt.GetReceiptDigest()) {
		return nil, protocolDataLoss("ConsumeApproval returned an inconsistent receipt")
	}
	return cloneGenerated(receipt), nil
}

func (service *ApprovalService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func verifyApprovalBinding(binding *workflowv1.ApprovalBinding) error {
	if binding == nil || !validSHA256Digest(binding.GetIntentDigest()) || !validSHA256Digest(binding.GetParametersDigest()) || !validSHA256Digest(binding.GetBindingDigest()) {
		return invalidArgument("approval binding requires canonical SHA-256 digests")
	}
	copyBinding := cloneGenerated(binding)
	supplied := copyBinding.GetBindingDigest()
	copyBinding.BindingDigest = ""
	computed, err := deterministicDigest(copyBinding)
	if err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(supplied), []byte(computed)) != 1 {
		return invalidArgument("approval binding digest does not match its generated payload")
	}
	return nil
}

func validateDecisionReceipt(config Config, request *internalworkflowv1.DecideApprovalRequest, receipt *workflowv1.ApprovalReceipt) error {
	if receipt == nil || !scopedResourceName(config, receipt.GetName(), "approvalReceipts") || receipt.GetRequest() == nil || receipt.GetRequest().GetName() != request.GetName() || receipt.GetBinding() == nil || receipt.GetDecision() != request.GetDecision() || receipt.GetReasonCode() != request.GetReasonCode() || receipt.GetSafeReason() != request.GetSafeReason() || receipt.GetDecidedAt() == nil || receipt.GetDecidedAt().CheckValid() != nil || !validSHA256Digest(receipt.GetReceiptDigest()) {
		return protocolDataLoss("DecideApproval returned an inconsistent receipt")
	}
	if !normalizeReferenceScope(config, receipt.Request) {
		return protocolDataLoss("DecideApproval receipt escaped the configured scope")
	}
	return nil
}
