package mindclade

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"

	"google.golang.org/grpc"
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

// InferenceWatcher resumes generated streaming updates from the last durable
// server-issued cursor. Recv is serialized; Close is idempotent.
type InferenceWatcher struct {
	service       *InferenceService
	ctx           context.Context //nolint:containedctx // A stream watcher owns its cancellable lifecycle context.
	cancel        context.CancelFunc
	operationName string
	cursor        *inferencev1.InferenceStreamCursor
	stream        grpc.ServerStreamingClient[internalinferencev1.WatchInferenceResponse]
	terminal      bool
	mu            sync.Mutex
}

func (service *InferenceService) Watch(ctx context.Context, operationName string, cursor *inferencev1.InferenceStreamCursor) (*InferenceWatcher, error) {
	if service == nil || service.client == nil || service.transport == nil || ctx == nil || !validResourceIdentifier(operationName) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "context and valid inference operation name are required"}
	}
	watchContext, cancel, err := service.longRunningContext(ctx)
	if err != nil {
		return nil, err
	}
	watcher := &InferenceWatcher{service: service, ctx: watchContext, cancel: cancel, operationName: operationName, cursor: cloneGenerated(cursor)}
	if err = watcher.connect(); err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

func (service *InferenceService) longRunningContext(ctx context.Context) (context.Context, context.CancelFunc, error) {
	if ctx == nil {
		return nil, nil, &Error{Code: CodeInvalidArgument, Message: "context is required"}
	}
	if _, ok := ctx.Deadline(); ok {
		return longRunningStreamContext(ctx), func() {}, nil
	}
	bounded, cancel := context.WithTimeout(ctx, service.client.config.DefaultOperationTimeout)
	return longRunningStreamContext(bounded), cancel, nil
}

func (watcher *InferenceWatcher) connect() error {
	request := &internalinferencev1.WatchInferenceRequest{OperationName: watcher.operationName, Cursor: cloneGenerated(watcher.cursor)}
	if deadline, ok := watcher.ctx.Deadline(); ok {
		request.Deadline = timestamppb.New(deadline)
	}
	stream, err := watcher.service.transport.WatchInference(watcher.ctx, request)
	if err != nil {
		return normalizeError(err)
	}
	watcher.stream = stream
	return nil
}

func (watcher *InferenceWatcher) Recv() (*inferencev1.InferenceStreamMessage, error) {
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	if watcher.terminal {
		return nil, io.EOF
	}
	failures := 0
	for {
		response, err := watcher.stream.Recv()
		if err == nil {
			message := response.GetMessage()
			if message == nil || message.GetRequestName() == "" || message.GetResumeToken() == "" || message.GetSequence() == 0 {
				return nil, &Error{Code: CodeDataLoss, Message: "inference watch returned an incomplete message"}
			}
			if message.GetHeartbeat() != nil {
				if watcher.cursor == nil || message.GetRequestName() != watcher.cursor.GetRequestName() || message.GetSequence() != watcher.cursor.GetAfterSequence() || message.GetResumeToken() != watcher.cursor.GetResumeToken() {
					return nil, &Error{Code: CodeDataLoss, Message: "inference heartbeat was not bound to the last durable cursor"}
				}
				return cloneGenerated(message), nil
			}
			after := uint64(0)
			if watcher.cursor != nil {
				after = watcher.cursor.GetAfterSequence()
				if watcher.cursor.GetRequestName() != message.GetRequestName() {
					return nil, &Error{Code: CodeDataLoss, Message: "inference watch changed request identity"}
				}
			}
			if message.GetSequence() != after+1 {
				return nil, &Error{Code: CodeDataLoss, Message: "inference watch sequence is not contiguous"}
			}
			watcher.cursor = &inferencev1.InferenceStreamCursor{RequestName: message.GetRequestName(), AfterSequence: message.GetSequence(), ResumeToken: message.GetResumeToken()}
			watcher.terminal = message.GetFinalResult() != nil || message.GetFailure() != nil
			return cloneGenerated(message), nil
		}
		if errors.Is(err, io.EOF) && watcher.terminal {
			return nil, io.EOF
		}
		if watcher.ctx.Err() != nil {
			return nil, normalizeError(watcher.ctx.Err())
		}
		if !errors.Is(err, io.EOF) && !isRetryable(err) {
			return nil, normalizeError(err)
		}
		failures++
		if failures >= watcher.service.client.config.MaxAttempts {
			return nil, normalizeError(err)
		}
		if waitErr := waitContext(watcher.ctx, retryDelay(watcher.service.client.config, failures)); waitErr != nil {
			return nil, normalizeError(waitErr)
		}
		if connectErr := watcher.connect(); connectErr != nil {
			return nil, connectErr
		}
	}
}

func (watcher *InferenceWatcher) Cursor() *inferencev1.InferenceStreamCursor {
	if watcher == nil {
		return nil
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	return cloneGenerated(watcher.cursor)
}

func (watcher *InferenceWatcher) Close() error {
	if watcher != nil && watcher.cancel != nil {
		watcher.cancel()
	}
	return nil
}

// Wait consumes resumable typed updates until terminal truth is durable, then
// returns the authoritative generated result and operation.
func (service *InferenceService) Wait(ctx context.Context, operationName string, cursor *inferencev1.InferenceStreamCursor) (*inferencev1.InferenceResult, *operationv1.Operation, error) {
	watcher, err := service.Watch(ctx, operationName, cursor)
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
			return service.GetResult(ctx, operationName)
		}
	}
}
