package inference

import (
	"context"
	"errors"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type Server struct {
	internalinferencev1.UnimplementedInferenceServiceServer
	repository        Repository
	identities        IdentityResolver
	cursors           *CursorCodec
	clock             Clock
	pollInterval      time.Duration
	heartbeatInterval time.Duration
}

func NewServer(repository Repository, identities IdentityResolver, cursors *CursorCodec, pollInterval, heartbeatInterval time.Duration) (*Server, error) {
	if repository == nil || identities == nil || cursors == nil {
		return nil, errors.New("inference server requires repository, identity resolver, and cursor codec")
	}
	if pollInterval < 10*time.Millisecond || pollInterval > 5*time.Second {
		return nil, errors.New("inference watch poll interval must be between 10ms and 5s")
	}
	if heartbeatInterval < pollInterval || heartbeatInterval > time.Minute {
		return nil, errors.New("inference heartbeat interval must be between poll interval and one minute")
	}
	return &Server{repository: repository, identities: identities, cursors: cursors, clock: realClock{}, pollInterval: pollInterval, heartbeatInterval: heartbeatInterval}, nil
}

func (server *Server) withClock(clock Clock) *Server {
	if clock != nil {
		server.clock = clock
	}
	return server
}

func Register(registrar grpc.ServiceRegistrar, server *Server) error {
	if registrar == nil || server == nil {
		return errors.New("inference registrar and server are required")
	}
	internalinferencev1.RegisterInferenceServiceServer(registrar, server)
	return nil
}

func (server *Server) identity(ctx context.Context) (Identity, error) {
	identity, err := server.identities.Resolve(ctx)
	if err != nil || validateIdentity(identity) != nil {
		return Identity{}, rpcError(ErrUnauthenticated)
	}
	return identity, nil
}

func (server *Server) SubmitInference(ctx context.Context, request *internalinferencev1.SubmitInferenceRequest) (*internalinferencev1.SubmitInferenceResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetInferenceRequest() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	value := request.GetInferenceRequest()
	if err = validateInferenceRequest(identity, value, now); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, value, value.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	materializeContext(identity, value, digest)
	operation, _, err := server.repository.Submit(ctx, identity, value, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalinferencev1.SubmitInferenceResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetInferenceRequest(ctx context.Context, request *internalinferencev1.GetInferenceRequestRequest) (*internalinferencev1.GetInferenceRequestResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetRequest(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalinferencev1.GetInferenceRequestResponse{InferenceRequest: clone(value)}, nil
}

func (server *Server) GetInferenceResult(ctx context.Context, request *internalinferencev1.GetInferenceResultRequest) (*internalinferencev1.GetInferenceResultResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetOperationName() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	result, operation, err := server.repository.GetResult(ctx, identity, request.GetOperationName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalinferencev1.GetInferenceResultResponse{Result: clone(result), Operation: clone(operation)}, nil
}

func (server *Server) CommitInferenceResult(ctx context.Context, request *internalinferencev1.CommitInferenceResultRequest) (*internalinferencev1.CommitInferenceResultResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	if err = validateFenceShape(identity, request.GetFence(), now); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	request.Context.TenantId, request.Context.ProjectId, request.Context.PrincipalId = identity.TenantID, identity.ProjectID, identity.Principal
	request.Context.CanonicalRequestDigest = digest
	result, operation, _, err := server.repository.CommitResult(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalinferencev1.CommitInferenceResultResponse{Result: clone(result), Operation: clone(operation)}, nil
}

func (server *Server) WatchInference(request *internalinferencev1.WatchInferenceRequest, stream grpc.ServerStreamingServer[internalinferencev1.WatchInferenceResponse]) error {
	identity, err := server.identity(stream.Context())
	if err != nil {
		return err
	}
	request = clone(request)
	if request == nil || request.GetOperationName() == "" {
		return rpcError(ErrInvalidArgument)
	}
	if _, err = operationID(request.GetOperationName()); err != nil {
		return rpcError(err)
	}
	now := server.clock.Now()
	deadline, err := watchDeadline(stream.Context(), request.GetDeadline(), now)
	if err != nil {
		return rpcError(err)
	}
	var after uint64
	expectedRequest := ""
	if cursor := request.GetCursor(); cursor != nil {
		if cursor.GetRequestName() == "" || cursor.GetAfterSequence() == 0 || cursor.GetResumeToken() == "" {
			return rpcError(ErrCursorMalformed)
		}
		expectedRequest = cursor.GetRequestName()
		after, err = server.cursors.Decode(cursor.GetResumeToken(), identity, request.GetOperationName(), expectedRequest, now)
		if err != nil {
			return rpcError(err)
		}
		if after != cursor.GetAfterSequence() {
			return rpcError(ErrCursorMalformed)
		}
	}
	ticker := time.NewTicker(server.pollInterval)
	defer ticker.Stop()
	lastHeartbeat := now
	for {
		requestName, revisions, terminal, readErr := server.repository.ReadOperationRevisions(stream.Context(), identity, request.GetOperationName(), after, operationWatchBatchSize)
		if readErr != nil {
			return rpcError(readErr)
		}
		if expectedRequest != "" && requestName != expectedRequest {
			return rpcError(ErrCursorResource)
		}
		expectedRequest = requestName
		for _, revision := range revisions {
			message, mapErr := server.streamMessage(stream.Context(), identity, requestName, revision)
			if mapErr != nil {
				return rpcError(mapErr)
			}
			message.ResumeToken, mapErr = server.cursors.Encode(identity, request.GetOperationName(), requestName, uint64(revision.GetResourceVersion()), server.clock.Now()) //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
			if mapErr != nil {
				return rpcError(mapErr)
			}
			if sendErr := stream.Send(&internalinferencev1.WatchInferenceResponse{Message: message}); sendErr != nil {
				return sendErr
			}
			after = uint64(revision.GetResourceVersion()) //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
			lastHeartbeat = server.clock.Now()
		}
		if terminal {
			return nil
		}
		now = server.clock.Now()
		if !now.Before(deadline) {
			return rpcError(ErrDeadlineExceeded)
		}
		if len(revisions) == 0 && after > 0 && now.Sub(lastHeartbeat) >= server.heartbeatInterval {
			token, tokenErr := server.cursors.Encode(identity, request.GetOperationName(), requestName, after, now)
			if tokenErr != nil {
				return rpcError(tokenErr)
			}
			heartbeat := &inferencev1.InferenceStreamMessage{RequestName: requestName, Sequence: after, EmittedAt: timestamppb.New(now.UTC()), ResumeToken: token, Update: &inferencev1.InferenceStreamMessage_Heartbeat{Heartbeat: &inferencev1.InferenceHeartbeat{ObservedAt: timestamppb.New(now.UTC())}}}
			if sendErr := stream.Send(&internalinferencev1.WatchInferenceResponse{Message: heartbeat}); sendErr != nil {
				return sendErr
			}
			lastHeartbeat = now
		}
		select {
		case <-stream.Context().Done():
			return status.FromContextError(stream.Context().Err()).Err()
		case <-ticker.C:
		}
	}
}

func watchDeadline(ctx context.Context, requested *timestamppb.Timestamp, now time.Time) (time.Time, error) {
	deadline := now.UTC().Add(5 * time.Minute)
	if requested != nil {
		if requested.CheckValid() != nil || !now.UTC().Before(requested.AsTime().UTC()) || requested.AsTime().UTC().After(now.UTC().Add(24*time.Hour)) {
			return time.Time{}, ErrInvalidArgument
		}
		deadline = requested.AsTime().UTC()
	}
	if contextDeadline, ok := ctx.Deadline(); ok && contextDeadline.Before(deadline) {
		deadline = contextDeadline.UTC()
	}
	return deadline, nil
}

func (server *Server) streamMessage(ctx context.Context, identity Identity, requestName string, operation *jobv1.Operation) (*inferencev1.InferenceStreamMessage, error) {
	if operation == nil || operation.GetResourceVersion() <= 0 || operation.GetUpdatedAt() == nil {
		return nil, ErrHistoryGap
	}
	message := &inferencev1.InferenceStreamMessage{RequestName: requestName, Sequence: uint64(operation.GetResourceVersion()), EmittedAt: clone(operation.GetUpdatedAt())} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	if operation.GetDone() {
		result, err := server.repository.GetResultByRequest(ctx, identity, requestName)
		if err != nil {
			return nil, err
		}
		message.Update = &inferencev1.InferenceStreamMessage_FinalResult{FinalResult: &inferencev1.InferenceFinalUpdate{Result: resultResource(identity, result), Outcome: result.GetOutcome(), ResultManifest: clone(result.GetResultManifest()), ResultDigest: result.GetResultDigest()}}
		return message, nil
	}
	progress := &inferencev1.InferenceProgress{LifecycleState: operation.GetState().String(), StatusCode: operation.GetState().String()}
	switch operation.GetState() {
	case jobv1.OperationState_OPERATION_STATE_RUNNING:
		progress.CompletionBasisPoints = 5000
	case jobv1.OperationState_OPERATION_STATE_CANCELLING:
		progress.CompletionBasisPoints = 9000
	}
	message.Update = &inferencev1.InferenceStreamMessage_Progress{Progress: progress}
	return message, nil
}

func rpcError(err error) error {
	switch {
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, err.Error())
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, err.Error())
	case errors.Is(err, ErrInvalidArgument), errors.Is(err, ErrCursorMalformed), errors.Is(err, ErrCursorResource), errors.Is(err, ErrCursorAhead):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, err.Error())
	case errors.Is(err, ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrStaleFence), errors.Is(err, ErrLeaseExpired), errors.Is(err, ErrLeaseToken), errors.Is(err, ErrCursorExpired), errors.Is(err, ErrHistoryGap):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, ErrDeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, err.Error())
	default:
		return status.Error(codes.Internal, fmt.Sprintf("inference service failure: %v", err))
	}
}
