package mindclade

import (
	"context"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

const agentMaximumPageSize = 200

// AgentService is the generated-type-only private facade for bounded agent
// definitions, durable runs, append-only steps, and immutable tool receipts.
// It does not access PostgreSQL, Pub/Sub, artifacts, or model providers.
type AgentService struct {
	client    *Client
	transport internalagentv1.AgentServiceClient
}

// CreateDefinition admits a generated definition and returns its durable
// operation. Server-managed fields remain unset and caller identity is always
// replaced by authenticated SDK configuration in CommandContext.
func (service *AgentService) CreateDefinition(ctx context.Context, request *internalagentv1.CreateAgentDefinitionRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetAgentDefinition() == nil || !validResourceIdentifier(request.GetAgentDefinitionId()) {
		return nil, invalidArgument("a configured service, generated agent definition, and valid definition ID are required")
	}
	value := cloneGenerated(request)
	if err := service.projectParent(&value.Parent, "agent definition"); err != nil {
		return nil, err
	}
	if err := service.normalizeDefinition(value.GetAgentDefinition(), true); err != nil {
		return nil, err
	}
	return service.operationMutation(ctx, value.GetContext(), value, "CreateAgentDefinition", options...)
}

// UpdateDefinition applies a generated field mask under an explicit ETag.
func (service *AgentService) UpdateDefinition(ctx context.Context, request *internalagentv1.UpdateAgentDefinitionRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetAgentDefinition() == nil || !scopedResourceName(service.client.config, request.GetAgentDefinition().GetName(), "agentDefinitions") || strings.TrimSpace(request.GetEtag()) == "" || request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 || len(request.GetUpdateMask().GetPaths()) > 32 {
		return nil, invalidArgument("agent definition update requires a scoped definition, bounded field mask, and ETag")
	}
	value := cloneGenerated(request)
	if err := service.normalizeDefinition(value.GetAgentDefinition(), false); err != nil {
		return nil, err
	}
	return service.operationMutation(ctx, value.GetContext(), value, "UpdateAgentDefinition", options...)
}

// GetDefinition reads one generated definition revision.
func (service *AgentService) GetDefinition(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*agentv1.AgentDefinition, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "agentDefinitions") {
		return nil, invalidArgument("agent definition name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetAgentDefinition(callContext, &internalagentv1.GetAgentDefinitionRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetAgentDefinition() == nil || response.GetAgentDefinition().GetName() != name {
		return nil, protocolDataLoss("GetAgentDefinition returned an invalid definition identity")
	}
	return cloneGenerated(response.GetAgentDefinition()), nil
}

// ListDefinitions returns one bounded server-issued page. Opaque page tokens
// are forwarded without inspection or modification.
func (service *AgentService) ListDefinitions(ctx context.Context, request *internalagentv1.ListAgentDefinitionsRequest, options ...RequestOption) (*internalagentv1.ListAgentDefinitionsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("agent service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalagentv1.ListAgentDefinitionsRequest{}
	}
	if err := service.projectParent(&value.Parent, "agent definition list"); err != nil {
		return nil, err
	}
	if value.GetPage().GetPageSize() > agentMaximumPageSize {
		return nil, invalidArgument("agent definition page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListAgentDefinitions(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

// StartRun admits immutable generated run intent and returns the durable
// operation that owns asynchronous control state.
func (service *AgentService) StartRun(ctx context.Context, request *internalagentv1.StartAgentRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetAgentRun() == nil || !validResourceIdentifier(request.GetAgentRunId()) {
		return nil, invalidArgument("a configured service, generated agent run, and valid run ID are required")
	}
	value := cloneGenerated(request)
	if err := service.projectParent(&value.Parent, "agent run"); err != nil {
		return nil, err
	}
	if !normalizeScopedReference(service.client.config, value.GetAgentRun().GetDefinition(), "agent_definition", "agentDefinitions") {
		return nil, invalidArgument("agent run definition must be in the configured project")
	}
	if run := value.GetAgentRun().GetWorkflowRun(); run != nil && !normalizeScopedReference(service.client.config, run, "workflow_run", "workflowRuns") {
		return nil, invalidArgument("agent workflow run must be in the configured project")
	}
	if reservation := value.GetAgentRun().GetBudgetReservation(); reservation != nil && !normalizeReferenceScope(service.client.config, reservation) {
		return nil, invalidArgument("agent budget reservation must be a scoped generated reference")
	}
	return service.operationMutation(ctx, value.GetContext(), value, "StartAgentRun", options...)
}

// GetRun reads one durable generated agent run.
func (service *AgentService) GetRun(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*agentv1.AgentRun, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "agentRuns") {
		return nil, invalidArgument("agent run name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetAgentRun(callContext, &internalagentv1.GetAgentRunRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetAgentRun() == nil || response.GetAgentRun().GetName() != name {
		return nil, protocolDataLoss("GetAgentRun returned an invalid run identity")
	}
	return cloneGenerated(response.GetAgentRun()), nil
}

// ListRuns returns one bounded server-issued page.
func (service *AgentService) ListRuns(ctx context.Context, request *internalagentv1.ListAgentRunsRequest, options ...RequestOption) (*internalagentv1.ListAgentRunsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("agent service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalagentv1.ListAgentRunsRequest{}
	}
	if err := service.projectParent(&value.Parent, "agent run list"); err != nil {
		return nil, err
	}
	if value.GetPage().GetPageSize() > agentMaximumPageSize {
		return nil, invalidArgument("agent run page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListAgentRuns(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

// CancelRun records monotonic cancellation under an explicit ETag.
func (service *AgentService) CancelRun(ctx context.Context, request *internalagentv1.CancelAgentRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || !scopedResourceName(service.client.config, request.GetName(), "agentRuns") || strings.TrimSpace(request.GetEtag()) == "" || strings.TrimSpace(request.GetReason()) == "" || len(request.GetReason()) > 1024 {
		return nil, invalidArgument("agent cancellation requires a scoped run name, ETag, and bounded reason")
	}
	value := cloneGenerated(request)
	return service.operationMutation(ctx, value.GetContext(), value, "CancelAgentRun", options...)
}

// GetStep reads one immutable generated step.
func (service *AgentService) GetStep(ctx context.Context, name string, options ...RequestOption) (*agentv1.AgentStep, error) {
	if !service.configured() || !scopedAgentStepName(service.client.config, name) {
		return nil, invalidArgument("agent step name must be in a configured-project run")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetAgentStep(callContext, &internalagentv1.GetAgentStepRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetAgentStep() == nil || response.GetAgentStep().GetName() != name {
		return nil, protocolDataLoss("GetAgentStep returned an invalid step identity")
	}
	return cloneGenerated(response.GetAgentStep()), nil
}

// ListSteps returns append-only history after an optional durable sequence.
func (service *AgentService) ListSteps(ctx context.Context, request *internalagentv1.ListAgentStepsRequest, options ...RequestOption) (*internalagentv1.ListAgentStepsResponse, error) {
	if !service.configured() || request == nil || !scopedResourceName(service.client.config, request.GetParent(), "agentRuns") {
		return nil, invalidArgument("agent step parent must be a run in the configured project")
	}
	value := cloneGenerated(request)
	if value.GetPage().GetPageSize() > agentMaximumPageSize {
		return nil, invalidArgument("agent step page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListAgentSteps(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

// CommitStep appends one generated step under the current worker lease. The
// raw lease credential must be supplied with WithLeaseToken and is metadata
// only; it never enters protobuf state or the canonical request digest.
func (service *AgentService) CommitStep(ctx context.Context, request *internalagentv1.CommitAgentStepRequest, options ...RequestOption) (*agentv1.AgentStep, *agentv1.AgentRun, error) {
	if !service.configured() || request == nil || request.GetAgentStep() == nil || request.GetFence() == nil || strings.TrimSpace(request.GetRunEtag()) == "" || request.GetExpectedNextStepSequence() == 0 {
		return nil, nil, invalidArgument("agent step commit requires a generated step, current fence, run ETag, and next sequence")
	}
	value := cloneGenerated(request)
	if value.GetAgentStep().GetSequence() != value.GetExpectedNextStepSequence() || !normalizeScopedReference(service.client.config, value.GetAgentStep().GetRun(), "agent_run", "agentRuns") {
		return nil, nil, invalidArgument("agent step sequence and run reference are inconsistent")
	}
	if err := normalizeAgentFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, nil, err
	}
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, value.GetContext().GetIdempotencyKey(), true, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	value.Context = nil
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.CommitAgentStep(callContext, value)
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	step, run := response.GetAgentStep(), response.GetAgentRun()
	if step == nil || run == nil || step.GetSequence() != value.GetExpectedNextStepSequence() || step.GetRun().GetName() != value.GetAgentStep().GetRun().GetName() || run.GetName() != value.GetAgentStep().GetRun().GetName() {
		return nil, nil, protocolDataLoss("CommitAgentStep returned inconsistent durable state")
	}
	return cloneGenerated(step), cloneGenerated(run), nil
}

// CommitToolReceipt appends immutable execution evidence under the current
// worker lease. The raw lease credential is transport metadata only.
func (service *AgentService) CommitToolReceipt(ctx context.Context, request *internalagentv1.CommitToolReceiptRequest, options ...RequestOption) (*agentv1.ToolReceipt, *agentv1.AgentRun, error) {
	if !service.configured() || request == nil || request.GetToolReceipt() == nil || request.GetFence() == nil || strings.TrimSpace(request.GetRunEtag()) == "" || !scopedResourceName(service.client.config, request.GetToolReceipt().GetAgentRunName(), "agentRuns") || !scopedResourceName(service.client.config, request.GetToolReceipt().GetName(), "toolReceipts") {
		return nil, nil, invalidArgument("tool receipt commit requires scoped generated evidence, current fence, and run ETag")
	}
	value := cloneGenerated(request)
	if !scopedAgentStepName(service.client.config, value.GetToolReceipt().GetAgentStepName()) || !normalizeReferenceScope(service.client.config, value.GetToolReceipt().GetTool()) {
		return nil, nil, invalidArgument("tool receipt step and tool must be in the configured project")
	}
	if err := normalizeAgentFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, nil, err
	}
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, value.GetContext().GetIdempotencyKey(), true, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	value.Context = nil
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.CommitToolReceipt(callContext, value)
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	receipt, run := response.GetToolReceipt(), response.GetAgentRun()
	if receipt == nil || run == nil || receipt.GetName() != value.GetToolReceipt().GetName() || receipt.GetCallId() != value.GetToolReceipt().GetCallId() || run.GetName() != value.GetToolReceipt().GetAgentRunName() {
		return nil, nil, protocolDataLoss("CommitToolReceipt returned inconsistent durable state")
	}
	return cloneGenerated(receipt), cloneGenerated(run), nil
}

func (service *AgentService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func (service *AgentService) projectParent(parent *string, label string) error {
	expected := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if strings.TrimSpace(*parent) == "" {
		*parent = expected
	} else if *parent != expected {
		return invalidArgument(label + " parent must match the configured project")
	}
	return nil
}

func (service *AgentService) normalizeDefinition(value *agentv1.AgentDefinition, creating bool) error {
	if value == nil {
		return invalidArgument("agent definition is required")
	}
	if creating && (value.GetName() != "" || value.GetUid() != "" || value.GetRevision() != 0 || value.GetEtag() != "" || value.GetTenantId() != "" || value.GetProjectId() != "" || value.GetCreateTime() != nil || value.GetUpdateTime() != nil || value.GetDeleteTime() != nil) {
		return invalidArgument("server-managed agent definition fields must be unset when creating")
	}
	if !creating && !normalizeMessageScope(service.client.config, &value.TenantId, &value.ProjectId) {
		return invalidArgument("agent definition must be in the configured project")
	}
	if !normalizeScopedReference(service.client.config, value.GetWorkflowDefinition(), "workflow_definition", "workflowDefinitions") {
		return invalidArgument("agent workflow definition must be in the configured project")
	}
	if !normalizeReferenceScope(service.client.config, value.GetEvaluationSuite()) {
		return invalidArgument("agent evaluation suite must be a scoped generated reference")
	}
	if len(value.GetEligibleTools()) == 0 {
		return invalidArgument("agent definition requires at least one allowlisted tool")
	}
	for _, tool := range value.GetEligibleTools() {
		if !normalizeReferenceScope(service.client.config, tool) {
			return invalidArgument("agent eligible tools must be scoped generated references")
		}
	}
	return nil
}

func (service *AgentService) operationMutation(ctx context.Context, supplied *commonv1.CommandContext, request proto.Message, method string, options ...RequestOption) (*operationv1.Operation, error) {
	key := supplied.GetIdempotencyKey()
	clearCommandContext(request)
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, key, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(request)
	if err != nil {
		return nil, err
	}
	setCommandContext(request, commandContext(service.client.config, callContext, metadata, digest))
	var operation *operationv1.Operation
	switch value := request.(type) {
	case *internalagentv1.CreateAgentDefinitionRequest:
		response, callErr := service.transport.CreateAgentDefinition(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalagentv1.UpdateAgentDefinitionRequest:
		response, callErr := service.transport.UpdateAgentDefinition(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalagentv1.StartAgentRunRequest:
		response, callErr := service.transport.StartAgentRun(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalagentv1.CancelAgentRunRequest:
		response, callErr := service.transport.CancelAgentRun(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	default:
		return nil, invalidArgument("unsupported agent mutation")
	}
	return operationResponse(operation, nil, method)
}

func normalizeAgentFence(config Config, fence *jobv1.LeaseFence, now time.Time) error {
	if fence == nil || strings.TrimSpace(fence.GetJobId()) == "" || strings.TrimSpace(fence.GetRunId()) == "" || strings.TrimSpace(fence.GetAttemptId()) == "" || fence.GetLeaseEpoch() == 0 || fence.GetDeadline() == nil || fence.GetDeadline().CheckValid() != nil || !now.Before(fence.GetDeadline().AsTime()) || !validSHA256Digest(fence.GetLeaseTokenDigest()) {
		return invalidArgument("agent worker fence is incomplete, expired, or missing its token digest")
	}
	if !normalizeMessageScope(config, &fence.TenantId, &fence.ProjectId) {
		return invalidArgument("agent worker fence must match the configured project")
	}
	return nil
}

func scopedAgentStepName(config Config, name string) bool {
	prefix := projectName(config.TenantID, config.ProjectID) + "/agentRuns/"
	remainder := strings.TrimPrefix(strings.TrimSpace(name), prefix)
	parts := strings.Split(remainder, "/agentSteps/")
	return strings.HasPrefix(strings.TrimSpace(name), prefix) && len(parts) == 2 && validResourceIdentifier(parts[0]) && validResourceIdentifier(parts[1]) && !strings.Contains(parts[0], "/") && !strings.Contains(parts[1], "/")
}
