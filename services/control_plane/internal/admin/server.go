package admin

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

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/validation"
)

type Server struct {
	internaladminv1.UnimplementedAdminServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("admin server requires repository, identity resolver, and pagination codec")
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
	internaladminv1.RegisterAdminServiceServer(registrar, server)
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

func (s *Server) digest(identity Identity, projectID string, request proto.Message, command *commonv1.CommandContext) (string, error) {
	digest, err := validateContext(identity, request, command, projectID, s.clock.Now())
	if err != nil {
		return "", rpcError(err)
	}
	if command.GetCanonicalRequestDigest() == "" {
		command.CanonicalRequestDigest = digest
	}
	return digest, nil
}

func (s *Server) GetTenant(ctx context.Context, request *internaladminv1.GetTenantRequest) (*internaladminv1.GetTenantResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetTenant(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.GetTenantResponse{Tenant: clone(value)}, nil
}

func (s *Server) UpdateTenant(ctx context.Context, request *internaladminv1.UpdateTenantRequest) (*internaladminv1.UpdateTenantResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	digest, err := s.digest(identity, "", request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.UpdateTenant(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.UpdateTenantResponse{Operation: clone(operation)}, nil
}

func (s *Server) CreateProject(ctx context.Context, request *internaladminv1.CreateProjectRequest) (*internaladminv1.CreateProjectResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || !validID(request.GetProjectId()) {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	if crossFieldErr := validation.ValidateCrossField(request); crossFieldErr != nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	digest, err := s.digest(identity, request.GetProjectId(), request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.CreateProject(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.CreateProjectResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetProject(ctx context.Context, request *internaladminv1.GetProjectRequest) (*internaladminv1.GetProjectResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetProject(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.GetProjectResponse{Project: clone(value)}, nil
}

func (s *Server) ListProjects(ctx context.Context, request *internaladminv1.ListProjectsRequest) (*internaladminv1.ListProjectsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != "tenants/"+identity.TenantID {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := projectOrder(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := projectState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := ProjectPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "projects", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterID
	}
	values, next, readAt, err := s.repository.ListProjects(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.ListProjectsResponse{Projects: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) UpdateProject(ctx context.Context, request *internaladminv1.UpdateProjectRequest) (*internaladminv1.UpdateProjectResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetProject() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	_, projectID, err := projectName(identity, request.GetProject().GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	digest, err := s.digest(identity, projectID, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.UpdateProject(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.UpdateProjectResponse{Operation: clone(operation)}, nil
}

func (s *Server) QueryAuditRecords(ctx context.Context, request *internaladminv1.QueryAuditRecordsRequest) (*internaladminv1.QueryAuditRecordsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetQuery() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	query := clone(request.GetQuery())
	projectID, err := validateAuditQuery(identity, query)
	if err != nil {
		return nil, rpcError(err)
	}
	digest, err := auditQueryDigest(query)
	if err != nil {
		return nil, rpcError(err)
	}
	limit, err := pageLimit(query.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	page := AuditPage{Limit: limit, QueryDigest: digest, ProjectID: projectID}
	if token := query.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "audit-records", Tenant: identity.TenantID, Project: projectID, QueryDigest: digest})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = pageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterID = decoded.AfterID
	}
	values, next, err := s.repository.QueryAuditRecords(ctx, identity, query, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.QueryAuditRecordsResponse{Result: &adminv1.AuditQueryPage{Records: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}}}, nil
}

func (s *Server) ExportAuditRecords(ctx context.Context, request *internaladminv1.ExportAuditRecordsRequest) (*internaladminv1.ExportAuditRecordsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetQuery() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	request = clone(request)
	projectID, err := validateAuditQuery(identity, request.GetQuery())
	if err != nil {
		return nil, rpcError(err)
	}
	digest, err := s.digest(identity, projectID, request, request.GetContext())
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.ExportAuditRecords(ctx, identity, request, digest, s.clock.Now())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.ExportAuditRecordsResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetAuditExport(ctx context.Context, request *internaladminv1.GetAuditExportRequest) (*internaladminv1.GetAuditExportResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetAuditExport(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaladminv1.GetAuditExportResponse{AuditExport: clone(value)}, nil
}

func projectOrder(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" {
		return "", fmt.Errorf("%w: unsupported order_by", ErrInvalidArgument)
	}
	return value, nil
}

func projectState(filter string) (adminv1.ProjectState, error) {
	filter = strings.TrimSpace(filter)
	if filter == "" {
		return adminv1.ProjectState_PROJECT_STATE_UNSPECIFIED, nil
	}
	parts := strings.Fields(filter)
	if len(parts) != 3 || strings.ToLower(parts[0]) != "state" || parts[1] != "=" {
		return 0, ErrInvalidArgument
	}
	name := strings.ToUpper(strings.Trim(parts[2], `"'`))
	if !strings.HasPrefix(name, "PROJECT_STATE_") {
		name = "PROJECT_STATE_" + name
	}
	value, ok := adminv1.ProjectState_value[name]
	if !ok || value == 0 {
		return 0, ErrInvalidArgument
	}
	return adminv1.ProjectState(value), nil
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
		return status.Error(codes.DeadlineExceeded, "administrative request deadline exceeded")
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "administrative request cancelled")
	default:
		return status.Error(codes.Internal, "internal administrative service error")
	}
}
