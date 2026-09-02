package experiments

import (
	"context"
	"errors"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
)

type Server struct {
	internalexperimentv1.UnimplementedExperimentServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("experiment server requires repository, identity resolver, and pagination codec")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}}, nil
}

func Register(registrar grpc.ServiceRegistrar, server *Server) error {
	if registrar == nil || server == nil {
		return errors.New("experiment registrar and server are required")
	}
	internalexperimentv1.RegisterExperimentServiceServer(registrar, server)
	return nil
}

func (server *Server) identity(ctx context.Context) (Identity, error) {
	identity, err := server.identities.Resolve(ctx)
	if err != nil || validateIdentity(identity) != nil {
		return Identity{}, rpcError(ErrUnauthenticated)
	}
	return identity, nil
}

func (server *Server) digest(identity Identity, command proto.Message, commandContext *commonv1.CommandContext) (string, error) {
	digest, err := validateContext(identity, command, commandContext, server.clock.Now())
	if err != nil {
		return "", rpcError(err)
	}
	if commandContext.GetCanonicalRequestDigest() == "" {
		commandContext.CanonicalRequestDigest = digest
	}
	return digest, nil
}

func (server *Server) CreateExperiment(ctx context.Context, request *internalexperimentv1.CreateExperimentRequest) (*internalexperimentv1.CreateExperimentResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.CreateExperiment(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.CreateExperimentResponse{Experiment: clone(value)}, nil
}

func (server *Server) GetExperiment(ctx context.Context, request *internalexperimentv1.GetExperimentRequest) (*internalexperimentv1.GetExperimentResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetExperiment(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.GetExperimentResponse{Experiment: clone(value)}, nil
}

func (server *Server) ListExperiments(ctx context.Context, request *internalexperimentv1.ListExperimentsRequest) (*internalexperimentv1.ListExperimentsResponse, error) {
	identity, page, err := server.experimentPage(ctx, "experiments", request.GetParent(), request.GetPage(), request.GetFilter(), request.GetOrderBy(), false)
	if err != nil {
		return nil, err
	}
	values, next, at, err := server.repository.ListExperiments(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.ListExperimentsResponse{Experiments: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(at)}, nil
}

func (server *Server) UpdateExperiment(ctx context.Context, request *internalexperimentv1.UpdateExperimentRequest) (*internalexperimentv1.UpdateExperimentResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.UpdateExperiment(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.UpdateExperimentResponse{Experiment: clone(value)}, nil
}

func (server *Server) TransitionExperiment(ctx context.Context, request *internalexperimentv1.TransitionExperimentRequest) (*internalexperimentv1.TransitionExperimentResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.TransitionExperiment(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.TransitionExperimentResponse{Experiment: clone(value)}, nil
}

func (server *Server) CreateStudy(ctx context.Context, request *internalexperimentv1.CreateStudyRequest) (*internalexperimentv1.CreateStudyResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.CreateStudy(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.CreateStudyResponse{Study: clone(value)}, nil
}

func (server *Server) GetStudy(ctx context.Context, request *internalexperimentv1.GetStudyRequest) (*internalexperimentv1.GetStudyResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetStudy(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.GetStudyResponse{Study: clone(value)}, nil
}

func (server *Server) ListStudies(ctx context.Context, request *internalexperimentv1.ListStudiesRequest) (*internalexperimentv1.ListStudiesResponse, error) {
	identity, page, err := server.experimentPage(ctx, "studies", request.GetParent(), request.GetPage(), request.GetFilter(), request.GetOrderBy(), true)
	if err != nil {
		return nil, err
	}
	values, next, at, err := server.repository.ListStudies(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.ListStudiesResponse{Studies: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(at)}, nil
}

func (server *Server) TransitionStudy(ctx context.Context, request *internalexperimentv1.TransitionStudyRequest) (*internalexperimentv1.TransitionStudyResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.TransitionStudy(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.TransitionStudyResponse{Study: clone(value)}, nil
}

func (server *Server) CreateTrial(ctx context.Context, request *internalexperimentv1.CreateTrialRequest) (*internalexperimentv1.CreateTrialResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.CreateTrial(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.CreateTrialResponse{Trial: clone(value)}, nil
}

func (server *Server) GetTrial(ctx context.Context, request *internalexperimentv1.GetTrialRequest) (*internalexperimentv1.GetTrialResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetTrial(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.GetTrialResponse{Trial: clone(value)}, nil
}

func (server *Server) ListTrials(ctx context.Context, request *internalexperimentv1.ListTrialsRequest) (*internalexperimentv1.ListTrialsResponse, error) {
	identity, page, err := server.experimentPage(ctx, "trials", request.GetParent(), request.GetPage(), request.GetFilter(), request.GetOrderBy(), true)
	if err != nil {
		return nil, err
	}
	values, next, at, err := server.repository.ListTrials(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.ListTrialsResponse{Trials: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(at)}, nil
}

func (server *Server) TransitionTrial(ctx context.Context, request *internalexperimentv1.TransitionTrialRequest) (*internalexperimentv1.TransitionTrialResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.TransitionTrial(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.TransitionTrialResponse{Trial: clone(value)}, nil
}

func (server *Server) CompleteTrial(ctx context.Context, request *internalexperimentv1.CompleteTrialRequest) (*internalexperimentv1.CompleteTrialResponse, error) {
	identity, command, digest, err := commandInput(ctx, server, request.GetCommand())
	if err != nil {
		return nil, err
	}
	value, _, err := server.repository.CompleteTrial(ctx, identity, command, digest, server.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalexperimentv1.CompleteTrialResponse{Trial: clone(value)}, nil
}

func commandInput[T proto.Message](ctx context.Context, server *Server, input T) (Identity, T, string, error) {
	var zero T
	identity, err := server.identity(ctx)
	if err != nil {
		return Identity{}, zero, "", err
	}
	if any(input) == nil {
		return Identity{}, zero, "", rpcError(ErrInvalidArgument)
	}
	command := clone(input)
	message := command.ProtoReflect()
	field := message.Descriptor().Fields().ByName("context")
	if field == nil || !message.Has(field) {
		return Identity{}, zero, "", rpcError(ErrInvalidArgument)
	}
	commandContext, ok := message.Get(field).Message().Interface().(*commonv1.CommandContext)
	if !ok || commandContext == nil {
		return Identity{}, zero, "", rpcError(ErrInvalidArgument)
	}
	digest, err := server.digest(identity, command, commandContext)
	if err != nil {
		return Identity{}, zero, "", err
	}
	return identity, command, digest, nil
}

func (server *Server) experimentPage(ctx context.Context, kind, parent string, request *commonv1.PageRequest, filter, orderBy string, nested bool) (Identity, Page, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return Identity{}, Page{}, err
	}
	if parent == "" || (!nested && parent != projectParent(identity)) {
		return Identity{}, Page{}, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(pageRequest(request))
	if err != nil {
		return Identity{}, Page{}, rpcError(err)
	}
	order, err := normalizeOrder(orderBy)
	if err != nil {
		return Identity{}, Page{}, rpcError(err)
	}
	var state int32
	switch kind {
	case "experiments":
		state, err = filterState(filter, experimentv1.ExperimentState_value, "EXPERIMENT_STATE_")
	case "studies":
		state, err = filterState(filter, experimentv1.StudyState_value, "STUDY_STATE_")
	case "trials":
		state, err = filterState(filter, experimentv1.TrialState_value, "TRIAL_STATE_")
	default:
		err = ErrInvalidArgument
	}
	if err != nil {
		return Identity{}, Page{}, rpcError(err)
	}
	page := Page{Limit: limit, Parent: parent, Filter: filter, Order: order, State: state}
	if request != nil && request.GetPageToken() != "" {
		decoded, decodeErr := server.pages.decode(request.GetPageToken(), pageToken{Kind: kind, Tenant: identity.TenantID, Project: identity.ProjectID, Parent: parent, Filter: filter, Order: order})
		if decodeErr != nil {
			return Identity{}, Page{}, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return Identity{}, Page{}, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	return identity, page, nil
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
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, ErrDeadlineExceeded), errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "experiment request deadline exceeded")
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "experiment request cancelled")
	default:
		return status.Error(codes.Internal, "internal experiment service error")
	}
}
