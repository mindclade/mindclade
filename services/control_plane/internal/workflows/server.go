package workflows

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

type Server struct {
	internalworkflowv1.UnimplementedWorkflowServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

type ApprovalServer struct {
	internalworkflowv1.UnimplementedApprovalServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, *ApprovalServer, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, nil, errors.New("workflow servers require repository, identity resolver, and pagination codec")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}}, &ApprovalServer{repository: repository, identities: identities, pages: pages, clock: realClock{}}, nil
}

func Register(registrar grpc.ServiceRegistrar, workflow *Server, approval *ApprovalServer) error {
	if registrar == nil || workflow == nil || approval == nil {
		return errors.New("workflow registrar and both servers are required")
	}
	internalworkflowv1.RegisterWorkflowServiceServer(registrar, workflow)
	internalworkflowv1.RegisterApprovalServiceServer(registrar, approval)
	return nil
}

func (server *Server) identity(ctx context.Context, roles ...string) (Identity, error) {
	identity, err := server.identities.Resolve(ctx)
	if err != nil || validateIdentity(identity) != nil {
		return Identity{}, rpcError(ErrUnauthenticated)
	}
	if err = requireRole(identity, roles...); err != nil {
		return Identity{}, rpcError(err)
	}
	return identity, nil
}

func (server *ApprovalServer) identity(ctx context.Context, roles ...string) (Identity, error) {
	identity, err := server.identities.Resolve(ctx)
	if err != nil || validateIdentity(identity) != nil {
		return Identity{}, rpcError(ErrUnauthenticated)
	}
	if err = requireRole(identity, roles...); err != nil {
		return Identity{}, rpcError(err)
	}
	return identity, nil
}

var readRoles = []string{"platform-admin", "automation-operator", "automation-viewer", "automation-worker", "approver", "auditor"}

func (server *Server) CreateWorkflowDefinition(ctx context.Context, request *internalworkflowv1.CreateWorkflowDefinitionRequest) (*internalworkflowv1.CreateWorkflowDefinitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetWorkflowDefinitionId()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateWorkflowDefinition(identity, request.GetWorkflowDefinition(), true); err != nil {
		return nil, rpcError(err)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.CreateDefinition(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.CreateWorkflowDefinitionResponse{Operation: clone(operation)}, nil
}

func (server *Server) UpdateWorkflowDefinition(ctx context.Context, request *internalworkflowv1.UpdateWorkflowDefinitionRequest) (*internalworkflowv1.UpdateWorkflowDefinitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetWorkflowDefinition() == nil || request.GetEtag() == "" || request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = canonicalScopedName(identity, request.GetWorkflowDefinition().GetName(), "workflowDefinitions"); err != nil {
		return nil, rpcError(err)
	}
	allowed := map[string]bool{"display_name": true, "state": true}
	seen := map[string]bool{}
	for _, path := range request.GetUpdateMask().GetPaths() {
		if !allowed[path] || seen[path] {
			return nil, rpcError(ErrInvalidArgument)
		}
		seen[path] = true
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.UpdateDefinition(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.UpdateWorkflowDefinitionResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetWorkflowDefinition(ctx context.Context, request *internalworkflowv1.GetWorkflowDefinitionRequest) (*internalworkflowv1.GetWorkflowDefinitionResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetDefinition(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	if request.GetIfNoneMatch() != "" && request.GetIfNoneMatch() == value.GetEtag() {
		return nil, status.Error(codes.Aborted, "workflow definition has not changed")
	}
	return &internalworkflowv1.GetWorkflowDefinitionResponse{WorkflowDefinition: clone(value)}, nil
}

func (server *Server) ListWorkflowDefinitions(ctx context.Context, request *internalworkflowv1.ListWorkflowDefinitionsRequest) (*internalworkflowv1.ListWorkflowDefinitionsResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	page, err := definitionPage(identity, request, server.pages)
	if err != nil {
		return nil, rpcError(err)
	}
	values, next, readAt, err := server.repository.ListDefinitions(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.ListWorkflowDefinitionsResponse{WorkflowDefinitions: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (server *Server) StartWorkflowRun(ctx context.Context, request *internalworkflowv1.StartWorkflowRunRequest) (*internalworkflowv1.StartWorkflowRunResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	now := server.clock.Now()
	if err = validateStartRun(identity, request, now); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.StartRun(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.StartWorkflowRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetWorkflowRun(ctx context.Context, request *internalworkflowv1.GetWorkflowRunRequest) (*internalworkflowv1.GetWorkflowRunResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetRun(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	if request.GetIfNoneMatch() != "" && request.GetIfNoneMatch() == value.GetEtag() {
		return nil, status.Error(codes.Aborted, "workflow run has not changed")
	}
	return &internalworkflowv1.GetWorkflowRunResponse{WorkflowRun: clone(value)}, nil
}

func (server *Server) ListWorkflowRuns(ctx context.Context, request *internalworkflowv1.ListWorkflowRunsRequest) (*internalworkflowv1.ListWorkflowRunsResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	page, err := runPage(identity, request, server.pages)
	if err != nil {
		return nil, rpcError(err)
	}
	values, next, readAt, err := server.repository.ListRuns(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.ListWorkflowRunsResponse{WorkflowRuns: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (server *Server) CancelWorkflowRun(ctx context.Context, request *internalworkflowv1.CancelWorkflowRunRequest) (*internalworkflowv1.CancelWorkflowRunResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetName() == "" || request.GetEtag() == "" || request.GetReason() == "" || len(request.GetReason()) > 1024 {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.CancelRun(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.CancelWorkflowRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) CommitWorkflowTransition(ctx context.Context, request *internalworkflowv1.CommitWorkflowTransitionRequest) (*internalworkflowv1.CommitWorkflowTransitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-worker")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	now := server.clock.Now()
	if request == nil || request.GetContext() == nil || request.GetWorkflowRun() == nil || request.GetEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateFence(identity, request.GetFence(), now); err != nil {
		return nil, rpcError(err)
	}
	if _, err = canonicalScopedName(identity, request.GetWorkflowRun().GetName(), "workflowRuns"); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	value, _, err := server.repository.CommitTransition(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.CommitWorkflowTransitionResponse{WorkflowRun: clone(value)}, nil
}

func (server *Server) WatchWorkflowRun(request *internalworkflowv1.WatchWorkflowRunRequest, stream grpc.ServerStreamingServer[internalworkflowv1.WatchWorkflowRunResponse]) error {
	identity, err := server.identity(stream.Context(), readRoles...)
	if err != nil {
		return err
	}
	if request == nil {
		return rpcError(ErrInvalidArgument)
	}
	if _, err = canonicalScopedName(identity, request.GetName(), "workflowRuns"); err != nil {
		return rpcError(err)
	}
	after := request.GetAfterTransitionSequence()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		values, listErr := server.repository.ListTransitions(stream.Context(), identity, request.GetName(), after, 100)
		if listErr != nil {
			return rpcError(listErr)
		}
		for _, value := range values {
			if value.GetTransitionSequence() <= after {
				return status.Error(codes.Internal, "workflow repository returned a non-monotonic transition")
			}
			if err = stream.Send(&internalworkflowv1.WatchWorkflowRunResponse{WorkflowRun: clone(value)}); err != nil {
				return err
			}
			after = value.GetTransitionSequence()
			if terminalRunState(value.GetState()) {
				return nil
			}
		}
		select {
		case <-stream.Context().Done():
			return status.FromContextError(stream.Context().Err()).Err()
		case <-ticker.C:
		}
	}
}

func (server *ApprovalServer) RequestApproval(ctx context.Context, request *internalworkflowv1.RequestApprovalRequest) (*internalworkflowv1.RequestApprovalResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator", "automation-worker")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	value := request.GetApprovalRequest()
	if err = validateApproval(identity, value, true); err != nil {
		return nil, rpcError(err)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, value, value.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	created, _, err := server.repository.RequestApproval(ctx, identity, value, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.RequestApprovalResponse{ApprovalRequest: clone(created)}, nil
}

func (server *ApprovalServer) GetApprovalRequest(ctx context.Context, request *internalworkflowv1.GetApprovalRequestRequest) (*internalworkflowv1.GetApprovalRequestResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetApproval(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.GetApprovalRequestResponse{ApprovalRequest: clone(value)}, nil
}

func (server *ApprovalServer) ListApprovalRequests(ctx context.Context, request *internalworkflowv1.ListApprovalRequestsRequest) (*internalworkflowv1.ListApprovalRequestsResponse, error) {
	identity, err := server.identity(ctx, readRoles...)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	page, err := approvalPage(identity, request, server.pages)
	if err != nil {
		return nil, rpcError(err)
	}
	values, next, readAt, err := server.repository.ListApprovals(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.ListApprovalRequestsResponse{ApprovalRequests: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (server *ApprovalServer) DecideApproval(ctx context.Context, request *internalworkflowv1.DecideApprovalRequest) (*internalworkflowv1.DecideApprovalResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "approver")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetName() == "" || request.GetEtag() == "" || request.GetDecision() == workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_UNSPECIFIED || request.GetReasonCode() == "" || len(request.GetSafeReason()) > 2048 {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	receipt, _, err := server.repository.DecideApproval(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.DecideApprovalResponse{ApprovalReceipt: clone(receipt)}, nil
}

func (server *ApprovalServer) ConsumeApproval(ctx context.Context, request *internalworkflowv1.ConsumeApprovalRequest) (*internalworkflowv1.ConsumeApprovalResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "automation-operator", "automation-worker")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetReceiptName() == "" || !validSHA256(request.GetBindingDigest()) || request.GetCallId() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	receipt, _, err := server.repository.ConsumeApproval(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalworkflowv1.ConsumeApprovalResponse{ApprovalReceipt: clone(receipt)}, nil
}

func terminalRunState(value workflowv1.WorkflowRunState) bool {
	return value == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_SUCCEEDED || value == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_FAILED || value == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_CANCELLED || value == workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_EXPIRED
}

func normalizedOrder(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" {
		return "", ErrInvalidArgument
	}
	return value, nil
}

func parseEnumFilter(value, prefix string, values map[string]int32) (int32, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0, nil
	}
	parts := strings.Fields(value)
	if len(parts) != 3 || strings.ToLower(parts[0]) != "state" || parts[1] != "=" {
		return 0, ErrInvalidArgument
	}
	name := strings.ToUpper(parts[2])
	if !strings.HasPrefix(name, prefix) {
		name = prefix + name
	}
	result, ok := values[name]
	if !ok || result == 0 {
		return 0, ErrInvalidArgument
	}
	return result, nil
}

func definitionPage(identity Identity, request *internalworkflowv1.ListWorkflowDefinitionsRequest, codec *PageTokenCodec) (DefinitionPage, error) {
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return DefinitionPage{}, err
	}
	order, err := normalizedOrder(request.GetOrderBy())
	if err != nil {
		return DefinitionPage{}, err
	}
	state, err := parseEnumFilter(request.GetFilter(), "WORKFLOW_DEFINITION_STATE_", workflowv1.WorkflowDefinitionState_value)
	if err != nil {
		return DefinitionPage{}, err
	}
	page := DefinitionPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: workflowv1.WorkflowDefinitionState(state)}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := codec.decode(token, pageToken{Kind: "workflow-definitions", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return DefinitionPage{}, decodeErr
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		page.AfterName = decoded.AfterName
	}
	return page, err
}

func runPage(identity Identity, request *internalworkflowv1.ListWorkflowRunsRequest, codec *PageTokenCodec) (RunPage, error) {
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return RunPage{}, err
	}
	order, err := normalizedOrder(request.GetOrderBy())
	if err != nil {
		return RunPage{}, err
	}
	state, err := parseEnumFilter(request.GetFilter(), "WORKFLOW_RUN_STATE_", workflowv1.WorkflowRunState_value)
	if err != nil {
		return RunPage{}, err
	}
	page := RunPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: workflowv1.WorkflowRunState(state)}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := codec.decode(token, pageToken{Kind: "workflow-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return RunPage{}, decodeErr
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		page.AfterName = decoded.AfterName
	}
	return page, err
}

func approvalPage(identity Identity, request *internalworkflowv1.ListApprovalRequestsRequest, codec *PageTokenCodec) (ApprovalPage, error) {
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return ApprovalPage{}, err
	}
	order, err := normalizedOrder(request.GetOrderBy())
	if err != nil {
		return ApprovalPage{}, err
	}
	state, err := parseEnumFilter(request.GetFilter(), "APPROVAL_STATE_", workflowv1.ApprovalState_value)
	if err != nil {
		return ApprovalPage{}, err
	}
	page := ApprovalPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: workflowv1.ApprovalState(state)}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := codec.decode(token, pageToken{Kind: "approval-requests", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return ApprovalPage{}, decodeErr
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		page.AfterName = decoded.AfterName
	}
	return page, err
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, err.Error())
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, err.Error())
	case errors.Is(err, ErrInvalidArgument):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, err.Error())
	case errors.Is(err, ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrStaleFence), errors.Is(err, ErrApprovalConsumed):
		return status.Error(codes.Aborted, err.Error())
	case errors.Is(err, ErrDeadlineExceeded), errors.Is(err, ErrLeaseExpired), errors.Is(err, ErrApprovalExpired):
		return status.Error(codes.DeadlineExceeded, err.Error())
	case errors.Is(err, ErrLeaseToken):
		return status.Error(codes.PermissionDenied, err.Error())
	default:
		return status.Error(codes.Internal, fmt.Sprintf("workflow service failure: %v", err))
	}
}

var (
	_ internalworkflowv1.WorkflowServiceServer = (*Server)(nil)
	_ internalworkflowv1.ApprovalServiceServer = (*ApprovalServer)(nil)
)
