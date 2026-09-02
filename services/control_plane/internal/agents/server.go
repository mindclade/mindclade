package agents

import (
	"context"
	"errors"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
)

type Server struct {
	internalagentv1.UnimplementedAgentServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("agent server requires repository, identity resolver, and pagination codec")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}}, nil
}

func (server *Server) withClock(clock Clock) *Server {
	if clock != nil {
		server.clock = clock
	}
	return server
}

func Register(registrar grpc.ServiceRegistrar, server *Server) error {
	if registrar == nil || server == nil {
		return errors.New("agent registrar and server are required")
	}
	internalagentv1.RegisterAgentServiceServer(registrar, server)
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

func (server *Server) CreateAgentDefinition(ctx context.Context, request *internalagentv1.CreateAgentDefinitionRequest) (*internalagentv1.CreateAgentDefinitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "agent-admin")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetAgentDefinitionId()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateDefinition(identity, request.GetAgentDefinition(), true); err != nil {
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
	return &internalagentv1.CreateAgentDefinitionResponse{Operation: clone(operation)}, nil
}

func (server *Server) UpdateAgentDefinition(ctx context.Context, request *internalagentv1.UpdateAgentDefinitionRequest) (*internalagentv1.UpdateAgentDefinitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "agent-admin")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetAgentDefinition() == nil || request.GetEtag() == "" || request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 || len(request.GetUpdateMask().GetPaths()) > 32 {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = canonicalScopedName(identity, request.GetAgentDefinition().GetName(), "agentDefinitions"); err != nil {
		return nil, rpcError(err)
	}
	seen := map[string]struct{}{}
	for _, path := range request.GetUpdateMask().GetPaths() {
		if _, ok := seen[path]; ok {
			return nil, rpcError(ErrInvalidArgument)
		}
		seen[path] = struct{}{}
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
	return &internalagentv1.UpdateAgentDefinitionResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetAgentDefinition(ctx context.Context, request *internalagentv1.GetAgentDefinitionRequest) (*internalagentv1.GetAgentDefinitionResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
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
		return nil, status.Error(codes.Aborted, "agent definition has not changed")
	}
	return &internalagentv1.GetAgentDefinitionResponse{AgentDefinition: clone(value)}, nil
}

func (server *Server) ListAgentDefinitions(ctx context.Context, request *internalagentv1.ListAgentDefinitionsRequest) (*internalagentv1.ListAgentDefinitionsResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeDefinitionOrder(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseDefinitionFilter(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := DefinitionPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := server.pages.decode(token, pageToken{Kind: "agent-definitions", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := server.repository.ListDefinitions(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.ListAgentDefinitionsResponse{AgentDefinitions: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt.UTC())}, nil
}

func (server *Server) StartAgentRun(ctx context.Context, request *internalagentv1.StartAgentRunRequest) (*internalagentv1.StartAgentRunResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if err = validateStartRun(identity, request); err != nil {
		return nil, rpcError(err)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.StartRun(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.StartAgentRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetAgentRun(ctx context.Context, request *internalagentv1.GetAgentRunRequest) (*internalagentv1.GetAgentRunResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
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
		return nil, status.Error(codes.Aborted, "agent run has not changed")
	}
	return &internalagentv1.GetAgentRunResponse{AgentRun: clone(value)}, nil
}

func (server *Server) ListAgentRuns(ctx context.Context, request *internalagentv1.ListAgentRunsRequest) (*internalagentv1.ListAgentRunsResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeRunOrder(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseRunFilter(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := RunPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := server.pages.decode(token, pageToken{Kind: "agent-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := server.repository.ListRuns(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.ListAgentRunsResponse{AgentRuns: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt.UTC())}, nil
}

func (server *Server) CancelAgentRun(ctx context.Context, request *internalagentv1.CancelAgentRunRequest) (*internalagentv1.CancelAgentRunResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetName() == "" || request.GetEtag() == "" || request.GetReason() == "" || len(request.GetReason()) > 1024 {
		return nil, rpcError(ErrInvalidArgument)
	}
	if _, err = canonicalScopedName(identity, request.GetName(), "agentRuns"); err != nil {
		return nil, rpcError(err)
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
	return &internalagentv1.CancelAgentRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetAgentStep(ctx context.Context, request *internalagentv1.GetAgentStepRequest) (*internalagentv1.GetAgentStepResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetStep(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.GetAgentStepResponse{AgentStep: clone(value)}, nil
}

func (server *Server) ListAgentSteps(ctx context.Context, request *internalagentv1.ListAgentStepsRequest) (*internalagentv1.ListAgentStepsResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "platform-operator", "agent-admin", "agent-user", "agent-worker", "auditor")
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	parent, err := canonicalScopedName(identity, request.GetParent(), "agentRuns")
	if err != nil {
		return nil, rpcError(err)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	page := StepPage{Limit: limit, Parent: parent, AfterSequence: request.GetAfterSequence(), Order: "sequence"}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := server.pages.decode(token, pageToken{Kind: "agent-steps", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: parent, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		if page.AfterSequence != 0 && page.AfterSequence != decoded.AfterSequence {
			return nil, rpcError(ErrInvalidArgument)
		}
		page.AfterSequence = decoded.AfterSequence
	}
	values, next, readAt, err := server.repository.ListSteps(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.ListAgentStepsResponse{AgentSteps: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt.UTC())}, nil
}

func (server *Server) CommitAgentStep(ctx context.Context, request *internalagentv1.CommitAgentStepRequest) (*internalagentv1.CommitAgentStepResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "agent-worker")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	now := server.clock.Now()
	if request == nil || request.GetContext() == nil || request.GetRunEtag() == "" || request.GetExpectedNextStepSequence() == 0 {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateStep(identity, request.GetAgentStep()); err != nil {
		return nil, rpcError(err)
	}
	if err = validateFence(identity, request.GetFence(), now); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	step, run, _, err := server.repository.CommitStep(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.CommitAgentStepResponse{AgentStep: clone(step), AgentRun: clone(run)}, nil
}

func (server *Server) CommitToolReceipt(ctx context.Context, request *internalagentv1.CommitToolReceiptRequest) (*internalagentv1.CommitToolReceiptResponse, error) {
	identity, err := server.identity(ctx, "platform-admin", "agent-worker")
	if err != nil {
		return nil, err
	}
	request = clone(request)
	now := server.clock.Now()
	if request == nil || request.GetContext() == nil || request.GetRunEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateToolReceipt(identity, request.GetToolReceipt()); err != nil {
		return nil, rpcError(err)
	}
	if err = validateFence(identity, request.GetFence(), now); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	receipt, run, _, err := server.repository.CommitToolReceipt(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalagentv1.CommitToolReceiptResponse{ToolReceipt: clone(receipt), AgentRun: clone(run)}, nil
}

func rpcError(err error) error {
	if err == nil {
		return nil
	}
	switch {
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
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrStaleFence), errors.Is(err, ErrLeaseExpired), errors.Is(err, ErrLeaseToken):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, ErrDeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, err.Error())
	default:
		return status.Error(codes.Internal, "agent service failure")
	}
}
