package datasets

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
)

type Server struct {
	internaldatasetv1.UnimplementedDatasetServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("dataset server requires repository, identity resolver, and pagination codec")
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
	internaldatasetv1.RegisterDatasetServiceServer(registrar, server)
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

func (s *Server) CreateDataset(ctx context.Context, request *internaldatasetv1.CreateDatasetRequest) (*internaldatasetv1.CreateDatasetResponse, error) {
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
	operation, _, err := s.repository.CreateDataset(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.CreateDatasetResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetDataset(ctx context.Context, request *internaldatasetv1.GetDatasetRequest) (*internaldatasetv1.GetDatasetResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetDataset(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.GetDatasetResponse{Dataset: clone(value)}, nil
}

func (s *Server) ListDatasets(ctx context.Context, request *internaldatasetv1.ListDatasetsRequest) (*internaldatasetv1.ListDatasetsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validProjectParent(identity, request.GetParent()) {
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
	state, err := parseFilter(request.GetFilter(), "DATASET_STATE_", datasetv1.DatasetState_value)
	if err != nil {
		return nil, rpcError(err)
	}
	page := DatasetPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: datasetv1.DatasetState(state)}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "datasets", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListDatasets(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.ListDatasetsResponse{Datasets: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) UpdateDataset(ctx context.Context, request *internaldatasetv1.UpdateDatasetRequest) (*internaldatasetv1.UpdateDatasetResponse, error) {
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
	operation, _, err := s.repository.UpdateDataset(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.UpdateDatasetResponse{Operation: clone(operation)}, nil
}

func (s *Server) PublishDatasetRelease(ctx context.Context, request *internaldatasetv1.PublishDatasetReleaseRequest) (*internaldatasetv1.PublishDatasetReleaseResponse, error) {
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
	operation, _, err := s.repository.PublishDatasetRelease(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.PublishDatasetReleaseResponse{Operation: clone(operation)}, nil
}

func (s *Server) RevokeDatasetRelease(ctx context.Context, request *internaldatasetv1.RevokeDatasetReleaseRequest) (*internaldatasetv1.RevokeDatasetReleaseResponse, error) {
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
	operation, _, err := s.repository.RevokeDatasetRelease(ctx, identity, command, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.RevokeDatasetReleaseResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetDatasetRelease(ctx context.Context, request *internaldatasetv1.GetDatasetReleaseRequest) (*internaldatasetv1.GetDatasetReleaseResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetDatasetRelease(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.GetDatasetReleaseResponse{DatasetRelease: clone(value)}, nil
}

func (s *Server) ListDatasetReleases(ctx context.Context, request *internaldatasetv1.ListDatasetReleasesRequest) (*internaldatasetv1.ListDatasetReleasesResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validDatasetParent(identity, request.GetParent()) {
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
	state, err := parseFilter(request.GetFilter(), "DATASET_RELEASE_STATE_", datasetv1.DatasetReleaseState_value)
	if err != nil {
		return nil, rpcError(err)
	}
	page := ReleasePage{Limit: limit, Parent: request.GetParent(), Filter: request.GetFilter(), Order: order, State: datasetv1.DatasetReleaseState(state)}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "dataset-releases", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListDatasetReleases(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaldatasetv1.ListDatasetReleasesResponse{DatasetReleases: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func orderBy(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" {
		return "", fmt.Errorf("%w: unsupported order_by", ErrInvalidArgument)
	}
	return value, nil
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
		return status.Error(codes.DeadlineExceeded, "dataset request deadline exceeded")
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "dataset request cancelled")
	default:
		return status.Error(codes.Internal, "internal dataset service error")
	}
}
