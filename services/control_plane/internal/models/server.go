package models

import (
	"context"
	"errors"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
)

type Server struct {
	internalmodelv1.UnimplementedModelServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("model server requires repository, identity resolver, and pagination codec")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}}, nil
}

func (s *Server) withClock(clock Clock) *Server {
	if clock != nil {
		s.clock = clock
	}
	return s
}

func Register(registrar grpc.ServiceRegistrar, server *Server) {
	internalmodelv1.RegisterModelServiceServer(registrar, server)
}

func (s *Server) identity(ctx context.Context) (Identity, error) {
	identity, err := s.identities.Resolve(ctx)
	if err != nil {
		return Identity{}, rpcError(err)
	}
	if err = validateIdentity(identity); err != nil {
		return Identity{}, rpcError(err)
	}
	return identity, nil
}

func (s *Server) digest(identity Identity, command proto.Message, context *commonv1.CommandContext) (string, error) {
	digest, err := validateContext(identity, command, context, s.clock.Now())
	if err != nil {
		return "", rpcError(err)
	}
	if context.GetCanonicalRequestDigest() == "" {
		context.CanonicalRequestDigest = digest
	}
	return digest, nil
}

func (s *Server) RegisterModel(ctx context.Context, request *internalmodelv1.RegisterModelRequest) (*internalmodelv1.RegisterModelResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	digest, err := s.digest(identity, command, command.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.RegisterModel(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.RegisterModelResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetModel(ctx context.Context, request *internalmodelv1.GetModelRequest) (*internalmodelv1.GetModelResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetModel(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.GetModelResponse{Model: clone(value)}, nil
}

func (s *Server) ListModels(ctx context.Context, request *internalmodelv1.ListModelsRequest) (*internalmodelv1.ListModelsResponse, error) {
	identity, err := s.identity(ctx)
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
	order, err := orderBy(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := modelState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := ModelPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "models", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, at, err := s.repository.ListModels(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.ListModelsResponse{Models: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(at)}, nil
}

func (s *Server) RegisterModelRelease(ctx context.Context, request *internalmodelv1.RegisterModelReleaseRequest) (*internalmodelv1.RegisterModelReleaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	digest, err := s.digest(identity, command, command.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.RegisterModelRelease(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.RegisterModelReleaseResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetModelRelease(ctx context.Context, request *internalmodelv1.GetModelReleaseRequest) (*internalmodelv1.GetModelReleaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetModelRelease(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.GetModelReleaseResponse{ModelRelease: clone(value)}, nil
}

func (s *Server) ListModelReleases(ctx context.Context, request *internalmodelv1.ListModelReleasesRequest) (*internalmodelv1.ListModelReleasesResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validModelParent(identity, request.GetParent()) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := orderBy(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	stage, err := releaseStage(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := ReleasePage{Limit: limit, Parent: request.GetParent(), Filter: request.GetFilter(), Order: order, Stage: stage}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "model-releases", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, at, err := s.repository.ListModelReleases(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.ListModelReleasesResponse{ModelReleases: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(at)}, nil
}

func (s *Server) PromoteModelRelease(ctx context.Context, request *internalmodelv1.PromoteModelReleaseRequest) (*internalmodelv1.PromoteModelReleaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	digest, err := s.digest(identity, command, command.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.PromoteModelRelease(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.PromoteModelReleaseResponse{Operation: clone(operation)}, nil
}

func (s *Server) RevokeModelRelease(ctx context.Context, request *internalmodelv1.RevokeModelReleaseRequest) (*internalmodelv1.RevokeModelReleaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	digest, err := s.digest(identity, command, command.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.RevokeModelRelease(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalmodelv1.RevokeModelReleaseResponse{Operation: clone(operation)}, nil
}

func validModelParent(identity Identity, parent string) bool {
	prefix := projectParent(identity) + "/models/"
	return strings.HasPrefix(parent, prefix) && validID(strings.TrimPrefix(parent, prefix))
}

func orderBy(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" {
		return "", ErrInvalidArgument
	}
	return value, nil
}

func filterValue(filter string) (string, error) {
	if filter == "" {
		return "", nil
	}
	parts := strings.Split(filter, "=")
	if len(parts) != 2 || strings.TrimSpace(parts[0]) != "state" || strings.TrimSpace(parts[1]) == "" {
		return "", ErrInvalidArgument
	}
	return strings.ToUpper(strings.TrimSpace(parts[1])), nil
}

func modelState(filter string) (modelv1.ModelState, error) {
	value, err := filterValue(filter)
	if err != nil || value == "" {
		return 0, err
	}
	if !strings.HasPrefix(value, "MODEL_STATE_") {
		value = "MODEL_STATE_" + value
	}
	number, ok := modelv1.ModelState_value[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return modelv1.ModelState(number), nil
}

func releaseStage(filter string) (modelv1.ModelReleaseStage, error) {
	value, err := filterValue(filter)
	if err != nil || value == "" {
		return 0, err
	}
	if !strings.HasPrefix(value, "MODEL_RELEASE_STAGE_") {
		value = "MODEL_RELEASE_STAGE_" + value
	}
	number, ok := modelv1.ModelReleaseStage_value[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return modelv1.ModelReleaseStage(number), nil
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, ErrUnauthenticated.Error())
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, ErrPermissionDenied.Error())
	case errors.Is(err, ErrInvalidArgument):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, ErrNotFound.Error())
	case errors.Is(err, ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, ErrAlreadyExists.Error())
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrEventContractUnavailable):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, ErrDeadlineExceeded), errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "model request deadline exceeded")
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "model request cancelled")
	default:
		return status.Error(codes.Internal, "internal model service error")
	}
}
