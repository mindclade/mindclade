package mindclade

import (
	"context"
	"fmt"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

const workflowMaximumPageSize = 200

// WorkflowService is the private, generated-type-only facade for durable
// workflow definitions, runs, transitions, and watches. It never accesses
// persistence, Pub/Sub, or artifact storage directly.
type WorkflowService struct {
	client    *Client
	transport internalworkflowv1.WorkflowServiceClient
}

// WorkflowRunError carries authoritative generated terminal state without
// exposing server failure text through Error().
type WorkflowRunError struct {
	Run *workflowv1.WorkflowRun
}

func (err *WorkflowRunError) Error() string {
	if err == nil || err.Run == nil {
		return "mindclade: workflow run failed"
	}
	return fmt.Sprintf("mindclade: workflow run %s reached terminal state %s", err.Run.GetName(), err.Run.GetState())
}

// CreateDefinition validates scope, replaces caller identity, and returns the
// generated durable Operation.
func (service *WorkflowService) CreateDefinition(ctx context.Context, request *internalworkflowv1.CreateWorkflowDefinitionRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetWorkflowDefinition() == nil || !validResourceIdentifier(request.GetWorkflowDefinitionId()) {
		return nil, invalidArgument("a configured service and generated workflow definition request are required")
	}
	value := cloneGenerated(request)
	if err := service.projectParent(&value.Parent, "workflow definition"); err != nil {
		return nil, err
	}
	for _, reference := range value.GetWorkflowDefinition().GetEligibleTools() {
		if !normalizeReferenceScope(service.client.config, reference) {
			return nil, invalidArgument("workflow eligible tools must be in the configured scope")
		}
	}
	return service.operationMutation(ctx, value.GetContext(), value, "CreateWorkflowDefinition", options...)
}

// UpdateDefinition applies a generated field mask under an explicit ETag.
func (service *WorkflowService) UpdateDefinition(ctx context.Context, request *internalworkflowv1.UpdateWorkflowDefinitionRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetWorkflowDefinition() == nil || !scopedResourceName(service.client.config, request.GetWorkflowDefinition().GetName(), "workflowDefinitions") || strings.TrimSpace(request.GetEtag()) == "" || request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 {
		return nil, invalidArgument("workflow update requires a scoped definition, field mask, and ETag")
	}
	value := cloneGenerated(request)
	if !normalizeMessageScope(service.client.config, &value.WorkflowDefinition.TenantId, &value.WorkflowDefinition.ProjectId) {
		return nil, invalidArgument("workflow definition must be in the configured project")
	}
	for _, reference := range value.GetWorkflowDefinition().GetEligibleTools() {
		if !normalizeReferenceScope(service.client.config, reference) {
			return nil, invalidArgument("workflow eligible tools must be in the configured scope")
		}
	}
	return service.operationMutation(ctx, value.GetContext(), value, "UpdateWorkflowDefinition", options...)
}

// GetDefinition reads one generated workflow definition.
func (service *WorkflowService) GetDefinition(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*workflowv1.WorkflowDefinition, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "workflowDefinitions") {
		return nil, invalidArgument("workflow definition name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetWorkflowDefinition(callContext, &internalworkflowv1.GetWorkflowDefinitionRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetWorkflowDefinition() == nil {
		return nil, protocolDataLoss("GetWorkflowDefinition response omitted its definition")
	}
	return cloneGenerated(response.GetWorkflowDefinition()), nil
}

// WorkflowDefinitionPage is one bounded list response plus cursor-scheme traversal. The
// embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type WorkflowDefinitionPage struct {
	*internalworkflowv1.ListWorkflowDefinitionsResponse
	pageBase[*workflowv1.WorkflowDefinition, *WorkflowDefinitionPage]
}

// Items returns this page's workflow definitions without traversing any further page.
func (page *WorkflowDefinitionPage) Items() []*workflowv1.WorkflowDefinition {
	return page.GetWorkflowDefinitions()
}

// ListDefinitions returns one bounded page and preserves the opaque token.
func (service *WorkflowService) ListDefinitions(ctx context.Context, request *internalworkflowv1.ListWorkflowDefinitionsRequest, options ...RequestOption) (*WorkflowDefinitionPage, error) {
	if !service.configured() {
		return nil, invalidArgument("workflow service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalworkflowv1.ListWorkflowDefinitionsRequest{}
	}
	if err := service.projectParent(&value.Parent, "workflow definition list"); err != nil {
		return nil, err
	}
	if value.GetPage().GetPageSize() > workflowMaximumPageSize {
		return nil, invalidArgument("workflow definition page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListWorkflowDefinitions(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	detached := cloneGenerated(response)
	page := &WorkflowDefinitionPage{ListWorkflowDefinitionsResponse: detached}
	page.pageBase = newPage[*workflowv1.WorkflowDefinition](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*WorkflowDefinitionPage, error) {
		successor := cloneGenerated(value)
		successor.Page = pageRequestWithToken(value.GetPage(), token)
		return service.ListDefinitions(ctx, successor, options...)
	})
	return page, nil
}

// StartRun freezes generated workflow intent and returns a durable Operation.
func (service *WorkflowService) StartRun(ctx context.Context, request *internalworkflowv1.StartWorkflowRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || request.GetWorkflowRun() == nil || !validResourceIdentifier(request.GetWorkflowRunId()) {
		return nil, invalidArgument("a generated workflow start request and valid run ID are required")
	}
	value := cloneGenerated(request)
	if err := service.projectParent(&value.Parent, "workflow run"); err != nil {
		return nil, err
	}
	if !normalizeScopedReference(service.client.config, value.GetWorkflowRun().GetDefinition(), "workflow_definition", "workflowDefinitions") {
		return nil, invalidArgument("workflow run definition must be in the configured project")
	}
	if value.GetWorkflowRun().GetAgentRun() != nil && !normalizeScopedReference(service.client.config, value.GetWorkflowRun().GetAgentRun(), "agent_run", "agentRuns") {
		return nil, invalidArgument("workflow agent run must be in the configured project")
	}
	return service.operationMutation(ctx, value.GetContext(), value, "StartWorkflowRun", options...)
}

// GetRun reads one generated durable workflow run.
func (service *WorkflowService) GetRun(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*workflowv1.WorkflowRun, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "workflowRuns") {
		return nil, invalidArgument("workflow run name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetWorkflowRun(callContext, &internalworkflowv1.GetWorkflowRunRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetWorkflowRun() == nil {
		return nil, protocolDataLoss("GetWorkflowRun response omitted its run")
	}
	return cloneGenerated(response.GetWorkflowRun()), nil
}

// WorkflowRunPage is one bounded list response plus cursor-scheme traversal. The
// embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type WorkflowRunPage struct {
	*internalworkflowv1.ListWorkflowRunsResponse
	pageBase[*workflowv1.WorkflowRun, *WorkflowRunPage]
}

// Items returns this page's workflow runs without traversing any further page.
func (page *WorkflowRunPage) Items() []*workflowv1.WorkflowRun { return page.GetWorkflowRuns() }

// ListRuns returns one bounded page and preserves the opaque token.
func (service *WorkflowService) ListRuns(ctx context.Context, request *internalworkflowv1.ListWorkflowRunsRequest, options ...RequestOption) (*WorkflowRunPage, error) {
	if !service.configured() {
		return nil, invalidArgument("workflow service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalworkflowv1.ListWorkflowRunsRequest{}
	}
	if err := service.projectParent(&value.Parent, "workflow run list"); err != nil {
		return nil, err
	}
	if value.GetPage().GetPageSize() > workflowMaximumPageSize {
		return nil, invalidArgument("workflow run page size cannot exceed 200")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListWorkflowRuns(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	detached := cloneGenerated(response)
	page := &WorkflowRunPage{ListWorkflowRunsResponse: detached}
	page.pageBase = newPage[*workflowv1.WorkflowRun](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*WorkflowRunPage, error) {
		successor := cloneGenerated(value)
		successor.Page = pageRequestWithToken(value.GetPage(), token)
		return service.ListRuns(ctx, successor, options...)
	})
	return page, nil
}

// CancelRun records monotonic cancellation under an explicit ETag.
func (service *WorkflowService) CancelRun(ctx context.Context, request *internalworkflowv1.CancelWorkflowRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil || !scopedResourceName(service.client.config, request.GetName(), "workflowRuns") || strings.TrimSpace(request.GetEtag()) == "" || strings.TrimSpace(request.GetReason()) == "" || len(request.GetReason()) > 1024 {
		return nil, invalidArgument("workflow cancellation requires a scoped name, ETag, and bounded reason")
	}
	value := cloneGenerated(request)
	return service.operationMutation(ctx, value.GetContext(), value, "CancelWorkflowRun", options...)
}

// CommitTransition appends one generated transition under an ETag and current
// generated fence. The raw lease credential is carried only as transport
// metadata via WithLeaseToken and is never serialized into this request.
func (service *WorkflowService) CommitTransition(ctx context.Context, request *internalworkflowv1.CommitWorkflowTransitionRequest, options ...RequestOption) (*workflowv1.WorkflowRun, error) {
	if !service.configured() || request == nil || request.GetWorkflowRun() == nil || request.GetFence() == nil || strings.TrimSpace(request.GetEtag()) == "" {
		return nil, invalidArgument("workflow transition requires a generated run, fence, and ETag")
	}
	value := cloneGenerated(request)
	if !scopedResourceName(service.client.config, value.GetWorkflowRun().GetName(), "workflowRuns") || !normalizeMessageScope(service.client.config, &value.WorkflowRun.TenantId, &value.WorkflowRun.ProjectId) {
		return nil, invalidArgument("workflow transition run must be in the configured project")
	}
	if err := normalizeFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, err
	}
	callContext, metadata, cancel, err := service.client.workflowMutationContext(ctx, value.GetContext().GetIdempotencyKey(), true, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	value.Context = nil
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.CommitWorkflowTransition(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetWorkflowRun() == nil || response.GetWorkflowRun().GetName() != value.GetWorkflowRun().GetName() || response.GetWorkflowRun().GetTransitionSequence() != value.GetExpectedTransitionSequence()+1 {
		return nil, protocolDataLoss("CommitWorkflowTransition returned inconsistent durable state")
	}
	return cloneGenerated(response.GetWorkflowRun()), nil
}

func (service *WorkflowService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func (service *WorkflowService) projectParent(parent *string, label string) error {
	expected := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if strings.TrimSpace(*parent) == "" {
		*parent = expected
	} else if *parent != expected {
		return invalidArgument(label + " parent must match the configured project")
	}
	return nil
}

func (service *WorkflowService) operationMutation(ctx context.Context, supplied *commonv1.CommandContext, request proto.Message, method string, options ...RequestOption) (*operationv1.Operation, error) {
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
	case *internalworkflowv1.CreateWorkflowDefinitionRequest:
		response, callErr := service.transport.CreateWorkflowDefinition(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalworkflowv1.UpdateWorkflowDefinitionRequest:
		response, callErr := service.transport.UpdateWorkflowDefinition(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalworkflowv1.StartWorkflowRunRequest:
		response, callErr := service.transport.StartWorkflowRun(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	case *internalworkflowv1.CancelWorkflowRunRequest:
		response, callErr := service.transport.CancelWorkflowRun(callContext, value)
		if callErr != nil {
			return nil, normalizeError(callErr)
		}
		operation = response.GetOperation()
	default:
		return nil, invalidArgument("unsupported workflow mutation")
	}
	return operationResponse(operation, nil, method)
}

func clearCommandContext(message proto.Message) {
	reflected := message.ProtoReflect()
	field := reflected.Descriptor().Fields().ByName("context")
	if field != nil {
		reflected.Clear(field)
	}
}

func setCommandContext(message proto.Message, command *commonv1.CommandContext) {
	reflected := message.ProtoReflect()
	field := reflected.Descriptor().Fields().ByName("context")
	if field != nil {
		reflected.Set(field, protoreflect.ValueOfMessage(command.ProtoReflect()))
	}
}

func normalizeMessageScope(config Config, tenantID, projectID *string) bool {
	if (*tenantID != "" && *tenantID != config.TenantID) || (*projectID != "" && *projectID != config.ProjectID) {
		return false
	}
	*tenantID, *projectID = config.TenantID, config.ProjectID
	return true
}

func normalizeReferenceScope(config Config, reference *commonv1.ResourceRef) bool {
	if reference == nil || strings.TrimSpace(reference.GetResourceType()) == "" || strings.TrimSpace(reference.GetResourceId()) == "" || !validResourceIdentifier(reference.GetName()) || !normalizeMessageScope(config, &reference.TenantId, &reference.ProjectId) {
		return false
	}
	return true
}

func normalizeFence(config Config, fence *jobv1.LeaseFence, now time.Time) error {
	if fence == nil || strings.TrimSpace(fence.GetJobId()) == "" || strings.TrimSpace(fence.GetRunId()) == "" || strings.TrimSpace(fence.GetAttemptId()) == "" || fence.GetLeaseEpoch() == 0 || fence.GetDeadline() == nil || fence.GetDeadline().CheckValid() != nil || !now.Before(fence.GetDeadline().AsTime()) || !validSHA256Digest(fence.GetLeaseTokenDigest()) {
		return invalidArgument("workflow transition fence is incomplete, expired, or missing its token digest")
	}
	if !normalizeMessageScope(config, &fence.TenantId, &fence.ProjectId) {
		return invalidArgument("workflow transition fence must match the configured project")
	}
	return nil
}

func terminalWorkflowRun(state workflowv1.WorkflowRunState) bool {
	return state == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED || state == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_FAILED || state == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLED || state == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_EXPIRED
}

// WorkflowWatcher is the workflow spelling of the shared resumable watcher. It
// yields the generated run revision; the transition sequence is its cursor.
type WorkflowWatcher = StreamWatcher[*workflowv1.WorkflowRun, uint64]

// Watch starts a cancellation-aware, total-deadline-bounded durable watch. It
// reconnects only inside the caller's remaining deadline, resuming from the
// last accepted transition sequence.
func (service *WorkflowService) Watch(ctx context.Context, name string, afterTransitionSequence uint64, options ...RequestOption) (*WorkflowWatcher, error) {
	if !service.configured() || ctx == nil || !scopedResourceName(service.client.config, name, "workflowRuns") {
		return nil, invalidArgument("context and a scoped workflow run name are required")
	}
	watchContext, cancel, err := service.client.longRunningContext(ctx, options...)
	if err != nil {
		return nil, err
	}
	watcher, err := newStreamWatcher(watchContext, cancel, service.client.config, afterTransitionSequence, service.watchPolicy(name))
	if err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

// ResumeWatch continues a workflow watch from a transition sequence a previous
// process persisted.
func (service *WorkflowService) ResumeWatch(ctx context.Context, name string, afterTransitionSequence uint64, options ...RequestOption) (*WorkflowWatcher, error) {
	return service.Watch(ctx, name, afterTransitionSequence, options...)
}

// watchPolicy keeps every workflow-specific rule the previous hand-written
// watcher enforced: stable run identity and a strictly contiguous transition
// sequence.
//
// WatchWorkflowRunRequest carries no deadline field, so the caller's budget is
// propagated by the watch context alone rather than restated in the request.
func (service *WorkflowService) watchPolicy(name string) watchPolicy[*workflowv1.WorkflowRun, uint64] {
	return watchPolicy[*workflowv1.WorkflowRun, uint64]{
		open: func(ctx context.Context, cursor uint64) (func() (*workflowv1.WorkflowRun, error), error) {
			stream, err := service.transport.WatchWorkflowRun(ctx, &internalworkflowv1.WatchWorkflowRunRequest{Name: name, AfterTransitionSequence: cursor})
			if err != nil {
				return nil, normalizeError(err)
			}
			return func() (*workflowv1.WorkflowRun, error) {
				response, receiveErr := stream.Recv()
				if receiveErr != nil {
					return nil, receiveErr
				}
				return response.GetWorkflowRun(), nil
			}, nil
		},
		accept: func(cursor uint64, run *workflowv1.WorkflowRun) (uint64, bool, error) {
			if run == nil || run.GetName() != name || run.GetTransitionSequence() != cursor+1 {
				return cursor, false, protocolDataLoss("workflow watch returned an invalid identity or non-contiguous sequence")
			}
			return run.GetTransitionSequence(), terminalWorkflowRun(run.GetState()), nil
		},
	}
}

// Wait consumes a durable watch through terminal truth. Failed, cancelled, and
// expired runs return WorkflowRunError carrying the generated run.
func (service *WorkflowService) Wait(ctx context.Context, name string, afterTransitionSequence uint64, options ...RequestOption) (*workflowv1.WorkflowRun, error) {
	watcher, err := service.Watch(ctx, name, afterTransitionSequence, options...)
	if err != nil {
		return nil, err
	}
	defer func() { _ = watcher.Close() }()
	for {
		run, receiveErr := watcher.Recv()
		if receiveErr != nil {
			return nil, receiveErr
		}
		if !terminalWorkflowRun(run.GetState()) {
			continue
		}
		if run.GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED {
			return nil, &WorkflowRunError{Run: cloneGenerated(run)}
		}
		return run, nil
	}
}
