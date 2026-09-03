package training

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

type Server struct {
	internaltrainingv1.UnimplementedTrainingServiceServer
	internaljobv1.UnimplementedOperationServiceServer
	repository   Repository
	identities   IdentityResolver
	pages        *PageTokenCodec
	clock        Clock
	pollInterval time.Duration
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec, pollInterval time.Duration) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("training server requires repository, identity resolver, and pagination codec")
	}
	if pollInterval < 10*time.Millisecond || pollInterval > 5*time.Second {
		return nil, errors.New("training watch poll interval must be between 10ms and 5s")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}, pollInterval: pollInterval}, nil
}

func (s *Server) withClock(clock Clock) *Server {
	if clock != nil {
		s.clock = clock
	}
	return s
}

func Register(registrar grpc.ServiceRegistrar, server *Server) {
	internaltrainingv1.RegisterTrainingServiceServer(registrar, server)
	internaljobv1.RegisterOperationServiceServer(registrar, server)
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

func commandDigest(identity Identity, command proto.Message, context *commonv1.CommandContext, at time.Time) (string, error) {
	digest, err := validateContext(identity, command, context, at)
	if err != nil {
		return "", rpcError(err)
	}
	if context.GetCanonicalRequestDigest() == "" {
		context.CanonicalRequestDigest = digest
	}
	return digest, nil
}

func (s *Server) CreateTrainingRun(ctx context.Context, request *internaltrainingv1.CreateTrainingRunRequest) (*internaltrainingv1.CreateTrainingRunResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	operation, _, err := s.repository.CreateTrainingRun(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.CreateTrainingRunResponse{Operation: clone(operation)}, nil
}

func (s *Server) GetTrainingRun(ctx context.Context, request *internaltrainingv1.GetTrainingRunRequest) (*internaltrainingv1.GetTrainingRunResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetTrainingRun(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.GetTrainingRunResponse{TrainingRun: clone(value)}, nil
}

func (s *Server) ListTrainingRuns(ctx context.Context, request *internaltrainingv1.ListTrainingRunsRequest) (*internaltrainingv1.ListTrainingRunsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validParent(identity, request.GetParent()) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeOrder(request.GetOrderBy(), "create_time desc,name desc")
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseTrainingState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := RunPage{Limit: limit, State: state, Order: order, Filter: request.GetFilter()}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "training-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListTrainingRuns(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.ListTrainingRunsResponse{TrainingRuns: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) StartTrainingAttempt(ctx context.Context, request *internaltrainingv1.StartTrainingAttemptRequest) (*internaltrainingv1.StartTrainingAttemptResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	if err = validateCommandDeadline(command.GetDeadline(), at); err != nil {
		return nil, rpcError(err)
	}
	if err = validateScopedReference(identity, command.GetDelegatedCapability(), "delegated capability"); err != nil {
		return nil, rpcError(err)
	}
	value, _, err := s.repository.StartTrainingAttempt(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.StartTrainingAttemptResponse{TrainingRun: clone(value)}, nil
}

func (s *Server) ResumeTrainingAttempt(ctx context.Context, request *internaltrainingv1.ResumeTrainingAttemptRequest) (*internaltrainingv1.ResumeTrainingAttemptResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	if err = validateCommandDeadline(command.GetDeadline(), at); err != nil {
		return nil, rpcError(err)
	}
	if err = validateScopedReference(identity, command.GetDelegatedCapability(), "delegated capability"); err != nil {
		return nil, rpcError(err)
	}
	value, _, err := s.repository.ResumeTrainingAttempt(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.ResumeTrainingAttemptResponse{TrainingRun: clone(value)}, nil
}

func (s *Server) CommitTrainingProgress(ctx context.Context, request *internaltrainingv1.CommitTrainingProgressRequest) (*internaltrainingv1.CommitTrainingProgressResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	progress, run, _, err := s.repository.CommitTrainingProgress(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.CommitTrainingProgressResponse{Progress: clone(progress), TrainingRun: clone(run)}, nil
}

func (s *Server) PrepareCheckpoint(ctx context.Context, request *internaltrainingv1.PrepareCheckpointRequest) (*internaltrainingv1.PrepareCheckpointResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	value, _, err := s.repository.PrepareCheckpoint(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.PrepareCheckpointResponse{Checkpoint: clone(value)}, nil
}

func (s *Server) CommitCheckpoint(ctx context.Context, request *internaltrainingv1.CommitCheckpointRequest) (*internaltrainingv1.CommitCheckpointResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	checkpoint, run, _, err := s.repository.CommitCheckpoint(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.CommitCheckpointResponse{Checkpoint: clone(checkpoint), TrainingRun: clone(run)}, nil
}

func (s *Server) CompleteTrainingRun(ctx context.Context, request *internaltrainingv1.CompleteTrainingRunRequest) (*internaltrainingv1.CompleteTrainingRunResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	if err = validateFence(identity, command.GetFence(), at); err != nil {
		return nil, rpcError(err)
	}
	run, _, err := s.repository.CompleteTrainingRun(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.CompleteTrainingRunResponse{TrainingRun: clone(run)}, nil
}

func (s *Server) CancelTrainingRun(ctx context.Context, request *internaltrainingv1.CancelTrainingRunRequest) (*internaltrainingv1.CancelTrainingRunResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	command := clone(request.GetCommand())
	at := s.clock.Now()
	digest, err := commandDigest(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, err
	}
	run, _, err := s.repository.CancelTrainingRun(ctx, identity, command, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.CancelTrainingRunResponse{TrainingRun: clone(run)}, nil
}

func (s *Server) GetCheckpoint(ctx context.Context, request *internaltrainingv1.GetCheckpointRequest) (*internaltrainingv1.GetCheckpointResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetCheckpoint(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.GetCheckpointResponse{Checkpoint: clone(value)}, nil
}

func (s *Server) ListCheckpoints(ctx context.Context, request *internaltrainingv1.ListCheckpointsRequest) (*internaltrainingv1.ListCheckpointsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeOrder(request.GetOrderBy(), "snapshot_epoch desc,name desc")
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseCheckpointState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := CheckpointPage{Limit: limit, RunName: request.GetParent(), State: state, Order: order, Filter: request.GetFilter()}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "checkpoints", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.RunName, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterEpoch = decoded.AfterID
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListCheckpoints(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaltrainingv1.ListCheckpointsResponse{Checkpoints: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) GetOperation(ctx context.Context, request *internaljobv1.GetOperationRequest) (*internaljobv1.GetOperationResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := s.repository.GetOperation(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaljobv1.GetOperationResponse{Operation: clone(value)}, nil
}

func (s *Server) ListOperations(ctx context.Context, request *internaljobv1.ListOperationsRequest) (*internaljobv1.ListOperationsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validParent(identity, request.GetParent()) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeOrder(request.GetOrderBy(), "updated_at desc,id desc")
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseOperationState(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := OperationPage{Limit: limit, State: state, Order: order, Filter: request.GetFilter()}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := s.pages.decode(token, pageToken{Kind: "operations", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := s.repository.ListOperations(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaljobv1.ListOperationsResponse{Operations: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt)}, nil
}

func (s *Server) CancelOperation(ctx context.Context, request *internaljobv1.CancelOperationRequest) (*internaljobv1.CancelOperationResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	materialized := clone(request)
	at := s.clock.Now()
	digest, err := commandDigest(identity, materialized, materialized.GetContext(), at)
	if err != nil {
		return nil, err
	}
	value, _, err := s.repository.CancelOperation(ctx, identity, materialized, digest, at)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internaljobv1.CancelOperationResponse{Operation: clone(value)}, nil
}

func (s *Server) WatchTrainingRun(request *internaltrainingv1.WatchTrainingRunRequest, stream grpc.ServerStreamingServer[internaltrainingv1.WatchTrainingRunResponse]) error {
	if request == nil || request.GetName() == "" {
		return rpcError(ErrInvalidArgument)
	}
	identity, err := s.identity(stream.Context())
	if err != nil {
		return err
	}
	deadline, err := watchDeadline(stream.Context(), request.GetDeadline())
	if err != nil {
		return rpcError(err)
	}
	sequence := request.GetAfterSequence()
	ticker := time.NewTicker(s.pollInterval)
	defer ticker.Stop()
	for {
		value, err := s.repository.GetTrainingRun(stream.Context(), identity, request.GetName())
		if err != nil {
			return rpcError(err)
		}
		revision, conversionErr := numconv.Int64ToUint64(value.GetRevision())
		if conversionErr != nil {
			return rpcError(conversionErr)
		}
		if sequence > revision {
			return rpcError(fmt.Errorf("%w: watch sequence is ahead of the resource", ErrRevisionConflict))
		}
		if revision > sequence {
			sequence = revision
			if err = stream.Send(&internaltrainingv1.WatchTrainingRunResponse{TrainingRun: clone(value), Progress: clone(value.GetCommittedProgress()), Sequence: sequence, ObservedAt: timestamppb.New(s.clock.Now())}); err != nil {
				return err
			}
			if terminalRun(value.GetState()) {
				return nil
			}
		} else if terminalRun(value.GetState()) {
			return nil
		}
		wait := ticker.C
		if !deadline.IsZero() {
			remaining := time.Until(deadline)
			if remaining <= 0 {
				return status.Error(codes.DeadlineExceeded, "watch deadline reached")
			}
			timer := time.NewTimer(remaining)
			select {
			case <-stream.Context().Done():
				timer.Stop()
				return status.FromContextError(stream.Context().Err()).Err()
			case <-timer.C:
				return status.Error(codes.DeadlineExceeded, "watch deadline reached")
			case <-wait:
				timer.Stop()
			}
		} else {
			select {
			case <-stream.Context().Done():
				return status.FromContextError(stream.Context().Err()).Err()
			case <-wait:
			}
		}
	}
}

func (s *Server) WatchOperation(request *internaljobv1.WatchOperationRequest, stream grpc.ServerStreamingServer[internaljobv1.WatchOperationResponse]) error {
	if request == nil || request.GetName() == "" {
		return rpcError(ErrInvalidArgument)
	}
	identity, err := s.identity(stream.Context())
	if err != nil {
		return err
	}
	deadline, err := watchDeadline(stream.Context(), request.GetDeadline())
	if err != nil {
		return rpcError(err)
	}
	sequence := request.GetAfterSequence()
	ticker := time.NewTicker(s.pollInterval)
	defer ticker.Stop()
	for {
		values, terminal, err := s.repository.ReadOperationRevisions(stream.Context(), identity, request.GetName(), sequence, operationWatchBatchLimit)
		if err != nil {
			return rpcError(err)
		}
		for _, value := range values {
			revision, conversionErr := numconv.Int64ToUint64(value.GetResourceVersion())
			if conversionErr != nil {
				return rpcError(conversionErr)
			}
			if revision != sequence+1 {
				return rpcError(ErrOperationHistoryGap)
			}
			sequence = revision
			if err = stream.Send(&internaljobv1.WatchOperationResponse{Operation: clone(value), Sequence: sequence, ObservedAt: timestamppb.New(s.clock.Now())}); err != nil {
				return err
			}
			if value.GetDone() {
				return nil
			}
		}
		if terminal {
			return nil
		}
		if len(values) == operationWatchBatchLimit {
			continue
		}
		if deadline.IsZero() {
			select {
			case <-stream.Context().Done():
				return status.FromContextError(stream.Context().Err()).Err()
			case <-ticker.C:
			}
			continue
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return status.Error(codes.DeadlineExceeded, "watch deadline reached")
		}
		timer := time.NewTimer(remaining)
		select {
		case <-stream.Context().Done():
			timer.Stop()
			return status.FromContextError(stream.Context().Err()).Err()
		case <-timer.C:
			return status.Error(codes.DeadlineExceeded, "watch deadline reached")
		case <-ticker.C:
			timer.Stop()
		}
	}
}

func (s *Server) EncodeOperationCursor(name string, revision uint64) (string, error) {
	return s.pages.EncodeOperationCursor(name, revision)
}

func (s *Server) DecodeOperationCursor(cursor, expectedName string) (uint64, error) {
	revision, err := s.pages.DecodeOperationCursor(cursor, expectedName)
	return revision, rpcError(err)
}

func watchDeadline(ctx context.Context, requested *timestamppb.Timestamp) (time.Time, error) {
	deadline, _ := ctx.Deadline()
	if requested != nil {
		if err := requested.CheckValid(); err != nil {
			return time.Time{}, ErrInvalidArgument
		}
		value := requested.AsTime().UTC()
		if deadline.IsZero() || value.Before(deadline) {
			deadline = value
		}
	}
	return deadline, nil
}

func validParent(identity Identity, parent string) bool {
	return parent == "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID
}

func normalizeOrder(value, canonical string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return canonical, nil
	}
	if value != canonical {
		return "", fmt.Errorf("%w: unsupported order_by", ErrInvalidArgument)
	}
	return canonical, nil
}

func filterValue(filter string) (string, error) {
	if filter == "" {
		return "", nil
	}
	parts := strings.Split(filter, "=")
	if len(parts) != 2 || strings.TrimSpace(parts[0]) != "state" || strings.TrimSpace(parts[1]) == "" {
		return "", fmt.Errorf("%w: only state=<enum> filters are supported", ErrInvalidArgument)
	}
	return strings.ToUpper(strings.TrimSpace(parts[1])), nil
}

func parseTrainingState(filter string) (trainingv1.TrainingRunState, error) {
	value, err := filterValue(filter)
	if err != nil || value == "" {
		return 0, err
	}
	if !strings.HasPrefix(value, "TRAINING_RUN_STATE_") {
		value = "TRAINING_RUN_STATE_" + value
	}
	number, ok := trainingv1.TrainingRunState_value[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return trainingv1.TrainingRunState(number), nil
}

func parseCheckpointState(filter string) (trainingv1.CheckpointState, error) {
	value, err := filterValue(filter)
	if err != nil || value == "" {
		return 0, err
	}
	if !strings.HasPrefix(value, "CHECKPOINT_STATE_") {
		value = "CHECKPOINT_STATE_" + value
	}
	number, ok := trainingv1.CheckpointState_value[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return trainingv1.CheckpointState(number), nil
}

func parseOperationState(filter string) (operationv1.OperationState, error) {
	value, err := filterValue(filter)
	if err != nil || value == "" {
		return 0, err
	}
	if !strings.HasPrefix(value, "OPERATION_STATE_") {
		value = "OPERATION_STATE_" + value
	}
	number, ok := operationv1.OperationState_value[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return operationv1.OperationState(number), nil
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, "authenticated identity is required")
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, "resource is outside the authenticated scope")
	case errors.Is(err, ErrInvalidArgument):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrCursorMalformed):
		return status.Error(codes.InvalidArgument, ErrCursorMalformed.Error())
	case errors.Is(err, ErrCursorResource):
		return status.Error(codes.PermissionDenied, ErrCursorResource.Error())
	case errors.Is(err, ErrCursorAhead):
		return status.Error(codes.FailedPrecondition, ErrCursorAhead.Error())
	case errors.Is(err, ErrCursorExpired):
		return status.Error(codes.OutOfRange, ErrCursorExpired.Error())
	case errors.Is(err, ErrOperationHistoryGap):
		return status.Error(codes.DataLoss, ErrOperationHistoryGap.Error())
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, "resource not found")
	case errors.Is(err, ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, "resource already exists")
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrTerminal):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, ErrStaleFence), errors.Is(err, ErrLeaseExpired), errors.Is(err, ErrLeaseToken), errors.Is(err, ErrNonMonotonicProgress):
		return status.Error(codes.Aborted, err.Error())
	case errors.Is(err, ErrDeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, err.Error())
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "request cancelled")
	case errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "request deadline exceeded")
	default:
		return status.Error(codes.Internal, "internal training service error")
	}
}

func cloneSlice[T proto.Message](values []T) []T {
	result := make([]T, 0, len(values))
	for _, value := range values {
		result = append(result, clone(value))
	}
	return result
}
