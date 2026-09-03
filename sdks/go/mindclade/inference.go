package mindclade

import (
	"context"
	"strings"

	"google.golang.org/protobuf/types/known/timestamppb"

	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

// InferenceService is a thin ergonomic façade over the generated internal
// InferenceService client. Every accepted and returned domain value remains an
// authoritative generated protobuf message.
type InferenceService struct {
	client    *Client
	transport internalinferencev1.InferenceServiceClient
}

// Submit freezes authenticated command context and submits generated inference
// intent. The caller retains ownership of request; the SDK clones before
// materializing transport identity and the canonical request digest.
func (service *InferenceService) Submit(ctx context.Context, request *inferencev1.InferenceRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if request == nil || !validResourceIdentifier(request.GetName()) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "generated inference request with a valid name is required"}
	}
	if service == nil || service.client == nil || service.transport == nil {
		return nil, &Error{Code: CodeFailedPrecondition, Message: "inference service is not configured"}
	}
	value := cloneGenerated(request)
	commandKey := ""
	if value.GetContext() != nil {
		commandKey = value.GetContext().GetIdempotencyKey()
	}
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, commandKey, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	value.TenantId = service.client.config.TenantID
	value.ProjectId = service.client.config.ProjectID
	value.Context = nil
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.SubmitInference(callContext, &internalinferencev1.SubmitInferenceRequest{InferenceRequest: value})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetOperation() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "inference service returned no durable operation"}
	}
	return cloneGenerated(response.GetOperation()), nil
}

// GetRequest returns the immutable generated execution intent.
func (service *InferenceService) GetRequest(ctx context.Context, name string, options ...RequestOption) (*inferencev1.InferenceRequest, error) {
	if !validResourceIdentifier(name) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "valid inference request name is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetInferenceRequest(callContext, &internalinferencev1.GetInferenceRequestRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetInferenceRequest() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "inference service returned no request"}
	}
	return cloneGenerated(response.GetInferenceRequest()), nil
}

// GetResult returns immutable terminal truth and the durable generated
// operation used to authorize that read.
func (service *InferenceService) GetResult(ctx context.Context, operationName string, options ...RequestOption) (*inferencev1.InferenceResult, *operationv1.Operation, error) {
	if !validResourceIdentifier(operationName) {
		return nil, nil, &Error{Code: CodeInvalidArgument, Message: "valid inference operation name is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	response, err := service.transport.GetInferenceResult(callContext, &internalinferencev1.GetInferenceResultRequest{OperationName: operationName})
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetResult() == nil || response.GetOperation() == nil {
		return nil, nil, &Error{Code: CodeDataLoss, Message: "inference result response omitted result or operation"}
	}
	return cloneGenerated(response.GetResult()), cloneGenerated(response.GetOperation()), nil
}

// CommitResult sends a generated fenced terminal command. Authenticated
// identity and the canonical command digest are always rematerialized.
func (service *InferenceService) CommitResult(ctx context.Context, command *internalinferencev1.CommitInferenceResultRequest, options ...RequestOption) (*inferencev1.InferenceResult, *operationv1.Operation, error) {
	if command == nil || command.GetInferenceRequest() == nil || command.GetFence() == nil || command.GetResult() == nil || strings.TrimSpace(command.GetRequestDigest()) == "" {
		return nil, nil, &Error{Code: CodeInvalidArgument, Message: "complete generated inference result command is required"}
	}
	value := cloneGenerated(command)
	commandKey := ""
	if value.GetContext() != nil {
		commandKey = value.GetContext().GetIdempotencyKey()
	}
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, commandKey, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	value.Context = nil
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.CommitInferenceResult(callContext, value)
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetResult() == nil || response.GetOperation() == nil {
		return nil, nil, &Error{Code: CodeDataLoss, Message: "inference commit response omitted result or operation"}
	}
	return cloneGenerated(response.GetResult()), cloneGenerated(response.GetOperation()), nil
}

// InferenceWatcher is the inference spelling of the shared resumable watcher.
// It yields the generated stream message; its resume cursor is the generated
// InferenceStreamCursor the server issued with the last accepted message.
type InferenceWatcher = StreamWatcher[*inferencev1.InferenceStreamMessage, *inferencev1.InferenceStreamCursor]

// Watch streams generated inference updates, resuming from cursor. Passing the
// cursor a previous watcher reported through Cursor resumes exactly where that
// watcher stopped.
func (service *InferenceService) Watch(ctx context.Context, operationName string, cursor *inferencev1.InferenceStreamCursor, options ...RequestOption) (*InferenceWatcher, error) {
	if service == nil || service.client == nil || service.transport == nil || ctx == nil || !validResourceIdentifier(operationName) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "context and valid inference operation name are required"}
	}
	watchContext, cancel, err := service.client.longRunningContext(ctx, options...)
	if err != nil {
		return nil, err
	}
	watcher, err := newStreamWatcher(watchContext, cancel, service.client.config, cloneGenerated(cursor), service.watchPolicy(operationName))
	if err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

// ResumeWatch continues a stream from a cursor a previous process persisted.
func (service *InferenceService) ResumeWatch(ctx context.Context, operationName string, cursor *inferencev1.InferenceStreamCursor, options ...RequestOption) (*InferenceWatcher, error) {
	return service.Watch(ctx, operationName, cursor, options...)
}

// watchPolicy keeps every inference-specific rule the previous hand-written
// watcher enforced: a complete message, a heartbeat bound to the last durable
// cursor, stable request identity, and a strictly contiguous sequence.
func (service *InferenceService) watchPolicy(operationName string) watchPolicy[*inferencev1.InferenceStreamMessage, *inferencev1.InferenceStreamCursor] {
	return watchPolicy[*inferencev1.InferenceStreamMessage, *inferencev1.InferenceStreamCursor]{
		open: func(ctx context.Context, cursor *inferencev1.InferenceStreamCursor) (func() (*inferencev1.InferenceStreamMessage, error), error) {
			request := &internalinferencev1.WatchInferenceRequest{OperationName: operationName, Cursor: cloneGenerated(cursor)}
			if deadline, ok := ctx.Deadline(); ok {
				request.Deadline = timestamppb.New(deadline)
			}
			stream, err := service.transport.WatchInference(ctx, request)
			if err != nil {
				return nil, normalizeError(err)
			}
			return func() (*inferencev1.InferenceStreamMessage, error) {
				response, receiveErr := stream.Recv()
				if receiveErr != nil {
					return nil, receiveErr
				}
				return response.GetMessage(), nil
			}, nil
		},
		accept: func(cursor *inferencev1.InferenceStreamCursor, message *inferencev1.InferenceStreamMessage) (*inferencev1.InferenceStreamCursor, bool, error) {
			if message == nil || message.GetRequestName() == "" || message.GetResumeToken() == "" || message.GetSequence() == 0 {
				return cursor, false, &Error{Code: CodeDataLoss, Message: "inference watch returned an incomplete message"}
			}
			if message.GetHeartbeat() != nil {
				if cursor == nil || message.GetRequestName() != cursor.GetRequestName() || message.GetSequence() != cursor.GetAfterSequence() || message.GetResumeToken() != cursor.GetResumeToken() {
					return cursor, false, &Error{Code: CodeDataLoss, Message: "inference heartbeat was not bound to the last durable cursor"}
				}
				return cursor, false, nil
			}
			after := uint64(0)
			if cursor != nil {
				after = cursor.GetAfterSequence()
				if cursor.GetRequestName() != message.GetRequestName() {
					return cursor, false, &Error{Code: CodeDataLoss, Message: "inference watch changed request identity"}
				}
			}
			if message.GetSequence() != after+1 {
				return cursor, false, &Error{Code: CodeDataLoss, Message: "inference watch sequence is not contiguous"}
			}
			next := &inferencev1.InferenceStreamCursor{RequestName: message.GetRequestName(), AfterSequence: message.GetSequence(), ResumeToken: message.GetResumeToken()}
			return next, message.GetFinalResult() != nil || message.GetFailure() != nil, nil
		},
		snapshot: cloneGenerated[*inferencev1.InferenceStreamCursor],
	}
}

// Wait consumes resumable typed updates until terminal truth is durable, then
// returns the authoritative generated result and operation.
func (service *InferenceService) Wait(ctx context.Context, operationName string, cursor *inferencev1.InferenceStreamCursor, options ...RequestOption) (*inferencev1.InferenceResult, *operationv1.Operation, error) {
	watcher, err := service.Watch(ctx, operationName, cursor, options...)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = watcher.Close() }()
	for {
		message, receiveErr := watcher.Recv()
		if receiveErr != nil {
			return nil, nil, receiveErr
		}
		if message.GetFailure() != nil {
			return nil, nil, &Error{Code: CodeFailedPrecondition, Message: "inference watch reported durable failure"}
		}
		if message.GetFinalResult() != nil {
			return service.GetResult(ctx, operationName, options...)
		}
	}
}
