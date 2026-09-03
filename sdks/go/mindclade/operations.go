package mindclade

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type OperationService struct {
	client    *Client
	transport internaljobv1.OperationServiceClient
}

const maximumOperationPageSize = 200

// List returns one detached, bounded project-scoped page while preserving the
// server's opaque pagination cursor.
func (service *OperationService) List(ctx context.Context, request *internaljobv1.ListOperationsRequest, options ...RequestOption) (*internaljobv1.ListOperationsResponse, error) {
	value := cloneGenerated(request)
	if value == nil {
		value = &internaljobv1.ListOperationsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() != "" && value.GetParent() != parent {
		return nil, invalidArgument("operation list parent must match the configured project")
	}
	if value.GetPage().GetPageSize() > maximumOperationPageSize {
		return nil, invalidArgument("operation page size cannot exceed 200")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListOperations(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListOperations returned no response")
	}
	for _, operation := range response.GetOperations() {
		if !validListedOperation(service.client.config, operation) {
			return nil, protocolDataLoss("ListOperations returned an invalid or cross-project operation")
		}
	}
	return cloneGenerated(response), nil
}

func validListedOperation(config Config, operation *jobv1.Operation) bool {
	if operation == nil || strings.TrimSpace(operation.GetOperationId()) == "" || operation.GetTenantId() != config.TenantID || operation.GetProjectId() != config.ProjectID || operation.GetState() == jobv1.OperationState_OPERATION_STATE_UNSPECIFIED {
		return false
	}
	if operation.GetDone() != terminalOperationState(operation.GetState()) {
		return false
	}
	if target := operation.GetTarget(); target != nil && !operationTargetInProject(config, target) {
		return false
	}
	return true
}

func operationTargetInProject(config Config, target *commonv1.ResourceRef) bool {
	return target.GetTenantId() == config.TenantID && target.GetProjectId() == config.ProjectID && strings.HasPrefix(target.GetName(), projectName(config.TenantID, config.ProjectID)+"/")
}

func (service *OperationService) Get(ctx context.Context, name string, options ...RequestOption) (*jobv1.Operation, error) {
	if strings.TrimSpace(name) == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "operation name is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetOperation(callContext, &internaljobv1.GetOperationRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetOperation() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "operation service returned no operation"}
	}
	return cloneGenerated(response.GetOperation()), nil
}

type WaitOptions struct {
	PollInterval time.Duration
}

// Wait polls durable operation state until terminal or context cancellation.
// A failed/cancelled operation is returned together with OperationError.
func (service *OperationService) Wait(ctx context.Context, name string, options WaitOptions) (*jobv1.Operation, error) {
	operationContext, cancel, err := service.longRunningContext(ctx)
	if err != nil {
		return nil, err
	}
	defer cancel()
	interval := options.PollInterval
	if interval == 0 {
		interval = service.client.config.PollInterval
	}
	if interval <= 0 {
		return nil, &Error{Code: CodeInvalidArgument, Message: "poll interval must be positive"}
	}
	for {
		operation, err := service.Get(operationContext, name)
		if err != nil {
			return nil, err
		}
		if operation.GetDone() || terminalOperationState(operation.GetState()) {
			if err := validateTerminalOperation(operation); err != nil {
				return operation, err
			}
			if operationFailed(operation) {
				return operation, &OperationError{Operation: operation}
			}
			return operation, nil
		}
		if err := waitContext(operationContext, interval); err != nil {
			return operation, normalizeError(err)
		}
	}
}

func (service *OperationService) Cancel(
	ctx context.Context,
	name, etag, reason string,
	options ...RequestOption,
) (*jobv1.Operation, error) {
	reason = strings.TrimSpace(reason)
	if strings.TrimSpace(name) == "" || strings.TrimSpace(etag) == "" || len(reason) == 0 || len(reason) > 1024 || strings.ContainsAny(reason, "\x00\r\n") {
		return nil, &Error{Code: CodeInvalidArgument, Message: "operation name, etag, and bounded cancellation reason are required"}
	}
	options = append(options, WithIdempotencyKey("cancel:"+name+":"+etag))
	callContext, request, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	command := &internaljobv1.CancelOperationRequest{
		Name:   name,
		Etag:   etag,
		Reason: reason,
	}
	digest, err := deterministicDigest(command)
	if err != nil {
		return nil, err
	}
	command.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.CancelOperation(callContext, command)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetOperation() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "operation service returned no operation"}
	}
	return cloneGenerated(response.GetOperation()), nil
}

// Watcher automatically resumes a generated gRPC stream from its last durable
// sequence after retryable transport failures. Recv must not be called
// concurrently. Close is idempotent.
type Watcher struct {
	service  *OperationService
	ctx      context.Context //nolint:containedctx // A stream watcher owns its cancellable lifecycle context.
	cancel   context.CancelFunc
	name     string
	after    uint64
	stream   grpc.ServerStreamingClient[internaljobv1.WatchOperationResponse]
	terminal bool
	mu       sync.Mutex
}

func (service *OperationService) Watch(ctx context.Context, name string, afterSequence uint64) (*Watcher, error) {
	if ctx == nil || strings.TrimSpace(name) == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "context and operation name are required"}
	}
	watchContext, cancel, err := service.longRunningContext(ctx)
	if err != nil {
		return nil, err
	}
	watcher := &Watcher{service: service, ctx: watchContext, cancel: cancel, name: name, after: afterSequence}
	if err := watcher.connect(); err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

func (watcher *Watcher) connect() error {
	deadline, hasDeadline := watcher.ctx.Deadline()
	request := &internaljobv1.WatchOperationRequest{Name: watcher.name, AfterSequence: watcher.after}
	if hasDeadline {
		request.Deadline = timestamppb.New(deadline)
	}
	stream, err := watcher.service.transport.WatchOperation(watcher.ctx, request)
	if err != nil {
		return normalizeError(err)
	}
	watcher.stream = stream
	return nil
}

func (watcher *Watcher) Recv() (*internaljobv1.WatchOperationResponse, error) {
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	if watcher.terminal {
		return nil, io.EOF
	}
	failures := 0
	for {
		response, err := watcher.stream.Recv()
		if err == nil {
			if response.GetSequence() <= watcher.after {
				return nil, &Error{Code: CodeDataLoss, Message: "operation watch sequence did not advance"}
			}
			detached := cloneGenerated(response)
			operation := detached.GetOperation()
			if operation == nil || operation.GetOperationId() != watcher.name {
				return nil, &Error{Code: CodeDataLoss, Message: "operation watch returned a different or missing operation"}
			}
			if operation.GetDone() != terminalOperationState(operation.GetState()) {
				return nil, &Error{Code: CodeDataLoss, Message: "operation terminal state is inconsistent"}
			}
			watcher.after = response.GetSequence()
			watcher.terminal = operation.GetDone()
			if watcher.terminal && operationFailed(operation) {
				return detached, &OperationError{Operation: cloneGenerated(operation)}
			}
			return detached, nil
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
		for {
			connectErr := watcher.connect()
			if connectErr == nil {
				break
			}
			var sdkError *Error
			if !errors.As(connectErr, &sdkError) || !sdkError.Retryable {
				return nil, connectErr
			}
			failures++
			if failures >= watcher.service.client.config.MaxAttempts {
				return nil, connectErr
			}
			if waitErr := waitContext(watcher.ctx, retryDelay(watcher.service.client.config, failures)); waitErr != nil {
				return nil, normalizeError(waitErr)
			}
		}
	}
}

func (watcher *Watcher) Close() error {
	if watcher == nil {
		return nil
	}
	watcher.cancel()
	return nil
}

func terminalOperationState(state jobv1.OperationState) bool {
	return state == jobv1.OperationState_OPERATION_STATE_SUCCEEDED ||
		state == jobv1.OperationState_OPERATION_STATE_FAILED ||
		state == jobv1.OperationState_OPERATION_STATE_CANCELLED
}

func operationFailed(operation *jobv1.Operation) bool {
	return operation.GetState() == jobv1.OperationState_OPERATION_STATE_FAILED ||
		operation.GetState() == jobv1.OperationState_OPERATION_STATE_CANCELLED ||
		operation.GetError() != nil
}

func validateTerminalOperation(operation *jobv1.Operation) error {
	if operation == nil || strings.TrimSpace(operation.GetOperationId()) == "" {
		return &Error{Code: CodeDataLoss, Message: "operation service returned an invalid operation"}
	}
	if operation.GetDone() != terminalOperationState(operation.GetState()) {
		return &Error{Code: CodeDataLoss, Message: "operation terminal state is inconsistent"}
	}
	return nil
}

func (service *OperationService) longRunningContext(ctx context.Context) (context.Context, context.CancelFunc, error) {
	if ctx == nil {
		return nil, nil, &Error{Code: CodeInvalidArgument, Message: "context is required"}
	}
	if _, ok := ctx.Deadline(); ok {
		return longRunningStreamContext(ctx), func() {}, nil
	}
	bounded, cancel := context.WithTimeout(ctx, service.client.config.DefaultOperationTimeout)
	return longRunningStreamContext(bounded), cancel, nil
}
