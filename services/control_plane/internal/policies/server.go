package policies

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
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/validation"
)

type Server struct {
	internalpolicyv1.UnimplementedPolicyServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("policy server requires repository, identity resolver, and pagination codec")
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
	internalpolicyv1.RegisterPolicyServiceServer(registrar, server)
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

func (s *Server) digest(identity Identity, request proto.Message, command *commonv1.CommandContext) (string, error) {
	digest, err := validateContext(identity, request, command, s.clock.Now())
	if err != nil {
		return "", rpcError(err)
	}
	if command.GetCanonicalRequestDigest() == "" {
		command.CanonicalRequestDigest = digest
	}
	return digest, nil
}

func (s *Server) EvaluateAuthorization(ctx context.Context, request *internalpolicyv1.EvaluateAuthorizationRequest) (*internalpolicyv1.EvaluateAuthorizationResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	digest, err := s.digest(identity, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	decision, _, err := s.repository.EvaluateAuthorization(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.EvaluateAuthorizationResponse{Decision: clone(decision)}, nil
}

func (s *Server) CreateUsePolicy(ctx context.Context, request *internalpolicyv1.CreateUsePolicyRequest) (*internalpolicyv1.CreateUsePolicyResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	if crossFieldErr := validation.ValidateCrossField(request); crossFieldErr != nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest, err := s.digest(identity, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.CreateUsePolicy(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.CreateUsePolicyResponse{Operation: clone(operation)}, nil
}

func (s *Server) UpdateUsePolicy(ctx context.Context, request *internalpolicyv1.UpdateUsePolicyRequest) (*internalpolicyv1.UpdateUsePolicyResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	digest, err := s.digest(identity, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.UpdateUsePolicy(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.UpdateUsePolicyResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetUsePolicy(ctx context.Context, request *internalpolicyv1.GetUsePolicyRequest) (*internalpolicyv1.GetUsePolicyResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetUsePolicy(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.GetUsePolicyResponse{UsePolicy: clone(value)}, nil
}

func (s *Server) ListUsePolicies(ctx context.Context, request *internalpolicyv1.ListUsePoliciesRequest) (*internalpolicyv1.ListUsePoliciesResponse, error) {
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
	order, err := policyOrder(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := policyState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := PolicyPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "use-policies", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListUsePolicies(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.ListUsePoliciesResponse{UsePolicies: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) ActivateUsePolicy(ctx context.Context, request *internalpolicyv1.ActivateUsePolicyRequest) (*internalpolicyv1.ActivateUsePolicyResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	digest, err := s.digest(identity, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.ActivateUsePolicy(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.ActivateUsePolicyResponse{Operation: clone(operation)}, nil
}

func (s *Server) RevokeUsePolicy(ctx context.Context, request *internalpolicyv1.RevokeUsePolicyRequest) (*internalpolicyv1.RevokeUsePolicyResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	digest, err := s.digest(identity, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.RevokeUsePolicy(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.RevokeUsePolicyResponse{Operation: clone(operation)}, nil
}

func (s *Server) ResolvePolicySnapshot(ctx context.Context, request *internalpolicyv1.ResolvePolicySnapshotRequest) (*internalpolicyv1.ResolvePolicySnapshotResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" || request.GetEffectiveTime() == nil || request.GetEffectiveTime().CheckValid() != nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.ResolvePolicySnapshot(ctx, identity, request.GetName(), request.GetEffectiveTime().AsTime())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalpolicyv1.ResolvePolicySnapshotResponse{PolicySnapshot: clone(value)}, nil
}

func policyOrder(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" {
		return "", fmt.Errorf("%w: unsupported order_by", ErrInvalidArgument)
	}
	return value, nil
}

func policyState(filter string) (policyv1.UsePolicyState, error) {
	filter = strings.TrimSpace(filter)
	if filter == "" {
		return policyv1.UsePolicyState_USE_POLICY_STATE_UNSPECIFIED, nil
	}
	parts := strings.Fields(filter)
	if len(parts) != 3 || strings.ToLower(parts[0]) != "state" || parts[1] != "=" {
		return 0, ErrInvalidArgument
	}
	name := strings.ToUpper(strings.Trim(parts[2], `"'`))
	if !strings.HasPrefix(name, "USE_POLICY_STATE_") {
		name = "USE_POLICY_STATE_" + name
	}
	value, ok := policyv1.UsePolicyState_value[name]
	if !ok || value == 0 {
		return 0, ErrInvalidArgument
	}
	return policyv1.UsePolicyState(value), nil
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, ErrUnauthenticated.Error())
	case errors.Is(err, ErrPermissionDenied), errors.Is(err, ErrDenied):
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
		return status.Error(codes.DeadlineExceeded, "policy request deadline exceeded")
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "policy request cancelled")
	default:
		return status.Error(codes.Internal, "internal policy service error")
	}
}
