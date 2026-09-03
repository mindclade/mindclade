package mindclade

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

type OperationService struct {
	client    *Client
	transport internaljobv1.OperationServiceClient
}

const maximumOperationPageSize = 200

// OperationPage is one bounded list response plus cursor-scheme traversal.
// The embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type OperationPage struct {
	*internaljobv1.ListOperationsResponse
	pageBase[*operationv1.Operation, *OperationPage]
}

// Items returns this page's operations without traversing any further page.
func (page *OperationPage) Items() []*operationv1.Operation { return page.GetOperations() }

// List returns one detached, bounded project-scoped page while preserving the
// server's opaque pagination cursor. The returned page iterates the whole
// collection through All and walks it a page at a time through NextPage.
func (service *OperationService) List(ctx context.Context, request *internaljobv1.ListOperationsRequest, options ...RequestOption) (*OperationPage, error) {
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
	detached := cloneGenerated(response)
	page := &OperationPage{ListOperationsResponse: detached}
	page.pageBase = newPage[*operationv1.Operation](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*OperationPage, error) {
		successor := cloneGenerated(value)
		successor.Page = pageRequestWithToken(value.GetPage(), token)
		return service.List(ctx, successor, options...)
	})
	return page, nil
}

func validListedOperation(config Config, operation *operationv1.Operation) bool {
	if operation == nil || strings.TrimSpace(operation.GetOperationId()) == "" || operation.GetTenantId() != config.TenantID || operation.GetProjectId() != config.ProjectID || operation.GetState() == operationv1.OperationState_OPERATION_STATE_UNSPECIFIED {
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

func (service *OperationService) Get(ctx context.Context, name string, options ...RequestOption) (*operationv1.Operation, error) {
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
// A failed/cancelled operation is returned together with OperationError. Wait
// is one of the uniform long-running verbs — Get, Wait, Watch, Cancel,
// ResumeWatch — and like every other one it accepts per-request options, which
// it applies once so every poll shares the caller's request identity.
func (service *OperationService) Wait(
	ctx context.Context,
	name string,
	options WaitOptions,
	requestOptions ...RequestOption,
) (*operationv1.Operation, error) {
	if service == nil || service.client == nil {
		return nil, &Error{Code: CodeFailedPrecondition, Message: "operation service is not configured"}
	}
	operationContext, cancel, err := service.client.longRunningContext(ctx, requestOptions...)
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
) (*operationv1.Operation, error) {
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

// watchPolicy supplies the per-domain rules the shared watcher must not share:
// how a stream is opened at a cursor, how one decoded message is validated and
// folded into the next cursor, and how a terminal message projects onto a
// domain error. Everything else — reconnect, backoff, deadline arithmetic,
// detachment, and the Next/Current/Err surface — belongs to StreamWatcher.
type watchPolicy[Message proto.Message, Cursor any] struct {
	// open establishes (or re-establishes) the stream at cursor and returns the
	// receive function the watcher will drive. Implementations normalize their
	// own transport failures.
	open func(ctx context.Context, cursor Cursor) (func() (Message, error), error)
	// accept validates one detached message against the current cursor and
	// returns the next cursor together with whether the stream reached terminal
	// truth. A non-nil error ends the watch and is never retried: it reports a
	// protocol violation, not a transport fault.
	accept func(cursor Cursor, message Message) (Cursor, bool, error)
	// terminal projects a terminal message onto a domain error. A nil result
	// means the stream ended successfully.
	terminal func(message Message) error
	// snapshot detaches a cursor before it is handed to a caller or to open.
	// The identity function is used when a cursor is a scalar.
	snapshot func(cursor Cursor) Cursor
}

// StreamWatcher is the SDK's single resumable server-streaming reader. Every
// domain watcher is an alias of it, so reconnect policy, cursor discipline, and
// deadline arithmetic exist exactly once.
//
// It reconnects only inside the caller's remaining deadline and always resumes
// from the last acknowledged cursor, so no message is replayed or skipped
// across a reconnect. Next, Recv, and Close are serialized; Next and Recv must
// not be called concurrently, and Close is idempotent.
type StreamWatcher[Message proto.Message, Cursor any] struct {
	ctx      context.Context //nolint:containedctx // A stream watcher owns its cancellable lifecycle context.
	cancel   context.CancelFunc
	config   Config
	policy   watchPolicy[Message, Cursor]
	receive  func() (Message, error)
	cursor   Cursor
	current  Message
	err      error
	terminal bool
	ended    bool
	mu       sync.Mutex
}

// Watcher is the operations spelling of the shared resumable watcher. It
// yields the generated watch response, whose sequence is the resume cursor.
type Watcher = StreamWatcher[*internaljobv1.WatchOperationResponse, uint64]

// newStreamWatcher binds one watch policy to the shared reader and performs the
// initial connect. The first connect is retried under the same budget as a
// reconnect: a control plane that is briefly unavailable when a watch starts is
// no different from one that becomes unavailable while it runs.
func newStreamWatcher[Message proto.Message, Cursor any](
	ctx context.Context,
	cancel context.CancelFunc,
	config Config,
	cursor Cursor,
	policy watchPolicy[Message, Cursor],
) (*StreamWatcher[Message, Cursor], error) {
	if ctx == nil || policy.open == nil || policy.accept == nil {
		return nil, invalidArgument("a watch requires a context, an open rule, and an accept rule")
	}
	if policy.snapshot == nil {
		policy.snapshot = func(value Cursor) Cursor { return value }
	}
	watcher := &StreamWatcher[Message, Cursor]{ctx: ctx, cancel: cancel, config: config, policy: policy, cursor: cursor}
	failures := 0
	for {
		err := watcher.open()
		if err == nil {
			return watcher, nil
		}
		failures++
		if !retryableStatus(err) || failures >= config.MaxAttempts {
			return nil, err
		}
		delay := retryDelay(config, failures)
		if deadlineErr := watcher.withinRemainingDeadline(delay); deadlineErr != nil {
			return nil, deadlineErr
		}
		if waitErr := waitContext(ctx, delay); waitErr != nil {
			return nil, normalizeError(waitErr)
		}
	}
}

// Recv returns the next detached message. It returns io.EOF once the stream has
// delivered terminal truth, and returns a message together with an error when a
// domain reports terminal failure through both.
func (watcher *StreamWatcher[Message, Cursor]) Recv() (Message, error) {
	var zero Message
	if watcher == nil {
		return zero, io.EOF
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	return watcher.receiveLocked()
}

// Next advances the watcher and reports whether a message is available through
// Current. It returns false at a clean end of stream and on failure; Err
// distinguishes the two. A terminal failure message is still exposed through
// Current, so a caller reading with Next sees the same state Recv would return.
func (watcher *StreamWatcher[Message, Cursor]) Next() bool {
	if watcher == nil {
		return false
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	if watcher.ended {
		return false
	}
	message, err := watcher.receiveLocked()
	if !nilGenerated(message) {
		watcher.current = message
	}
	switch {
	case err == nil:
		return true
	case errors.Is(err, io.EOF):
		watcher.ended, watcher.err = true, nil
		return false
	default:
		watcher.ended, watcher.err = true, err
		return false
	}
}

// Current returns the message the last successful Next decoded.
func (watcher *StreamWatcher[Message, Cursor]) Current() Message {
	var zero Message
	if watcher == nil {
		return zero
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	return watcher.current
}

// Err returns the terminal error that ended a Next loop. It is nil at a clean
// end of stream, so io.EOF is never surfaced as a failure.
func (watcher *StreamWatcher[Message, Cursor]) Err() error {
	if watcher == nil {
		return nil
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	return watcher.err
}

// Cursor returns a detached copy of the last acknowledged resume position. It
// is exactly what ResumeWatch and the domain resume verbs accept.
func (watcher *StreamWatcher[Message, Cursor]) Cursor() Cursor {
	var zero Cursor
	if watcher == nil {
		return zero
	}
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	return watcher.policy.snapshot(watcher.cursor)
}

// Close cancels the watch and is safe to call repeatedly.
func (watcher *StreamWatcher[Message, Cursor]) Close() error {
	if watcher != nil && watcher.cancel != nil {
		watcher.cancel()
	}
	return nil
}

func (watcher *StreamWatcher[Message, Cursor]) receiveLocked() (Message, error) {
	var zero Message
	if watcher.terminal {
		return zero, io.EOF
	}
	if watcher.receive == nil {
		return zero, invalidArgument("watch stream is not connected")
	}
	failures := 0
	for {
		message, err := watcher.receive()
		if err == nil {
			detached := cloneGenerated(message)
			next, terminal, acceptErr := watcher.policy.accept(watcher.cursor, detached)
			if acceptErr != nil {
				return zero, acceptErr
			}
			watcher.cursor, watcher.terminal = next, terminal
			if terminal && watcher.policy.terminal != nil {
				if terminalErr := watcher.policy.terminal(detached); terminalErr != nil {
					return detached, terminalErr
				}
			}
			return detached, nil
		}
		if errors.Is(err, io.EOF) && watcher.terminal {
			return zero, io.EOF
		}
		if contextErr := watcher.ctx.Err(); contextErr != nil {
			return zero, normalizeError(contextErr)
		}
		if !errors.Is(err, io.EOF) && !retryableStatus(err) {
			return zero, normalizeError(err)
		}
		failures++
		if reconnectErr := watcher.reconnect(&failures, err); reconnectErr != nil {
			return zero, reconnectErr
		}
	}
}

// reconnect waits out one backoff and re-opens the stream from the last
// acknowledged cursor, retrying the open itself against the same attempt
// budget. It reconnects only inside the caller's remaining deadline: when the
// next wait would outlive that deadline it reports the deadline immediately
// rather than sleeping past it.
func (watcher *StreamWatcher[Message, Cursor]) reconnect(failures *int, cause error) error {
	for {
		if *failures >= watcher.config.MaxAttempts {
			return normalizeError(cause)
		}
		delay := retryDelay(watcher.config, *failures)
		if deadlineErr := watcher.withinRemainingDeadline(delay); deadlineErr != nil {
			return deadlineErr
		}
		if waitErr := waitContext(watcher.ctx, delay); waitErr != nil {
			return normalizeError(waitErr)
		}
		openErr := watcher.open()
		if openErr == nil {
			return nil
		}
		if !retryableStatus(openErr) {
			return openErr
		}
		cause = openErr
		*failures++
	}
}

func (watcher *StreamWatcher[Message, Cursor]) open() error {
	receive, err := watcher.policy.open(watcher.ctx, watcher.policy.snapshot(watcher.cursor))
	if err != nil {
		return err
	}
	if receive == nil {
		return protocolDataLoss("watch stream was not established")
	}
	watcher.receive = receive
	return nil
}

// withinRemainingDeadline reports the caller's deadline when the next backoff
// would consume all of it. A watcher never sleeps past the budget it was given.
func (watcher *StreamWatcher[Message, Cursor]) withinRemainingDeadline(delay time.Duration) error {
	deadline, ok := watcher.ctx.Deadline()
	if !ok {
		return nil
	}
	if time.Until(deadline) <= delay {
		return normalizeError(context.DeadlineExceeded)
	}
	return nil
}

// Watch streams durable operation revisions from afterSequence, reconnecting
// within the caller's deadline and resuming from the last acknowledged
// sequence.
func (service *OperationService) Watch(ctx context.Context, name string, afterSequence uint64, options ...RequestOption) (*Watcher, error) {
	if service == nil || service.client == nil || service.transport == nil || ctx == nil || strings.TrimSpace(name) == "" {
		return nil, &Error{Code: CodeInvalidArgument, Message: "context and operation name are required"}
	}
	watchContext, cancel, err := service.client.longRunningContext(ctx, options...)
	if err != nil {
		return nil, err
	}
	watcher, err := newStreamWatcher(watchContext, cancel, service.client.config, afterSequence, service.watchPolicy(name))
	if err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

// ResumeWatch continues a watch from an explicitly named resume cursor, which
// is what a caller holds after a process restart. It is the resume verb of the
// uniform long-running surface; Watch is the same call from the beginning.
func (service *OperationService) ResumeWatch(ctx context.Context, name string, cursor uint64, options ...RequestOption) (*Watcher, error) {
	return service.Watch(ctx, name, cursor, options...)
}

// watchPolicy keeps every operation-specific rule the previous hand-written
// watcher enforced: a strictly increasing sequence, stable operation identity,
// a consistent done/state pair, and OperationError on terminal failure.
func (service *OperationService) watchPolicy(name string) watchPolicy[*internaljobv1.WatchOperationResponse, uint64] {
	return watchPolicy[*internaljobv1.WatchOperationResponse, uint64]{
		open: func(ctx context.Context, cursor uint64) (func() (*internaljobv1.WatchOperationResponse, error), error) {
			request := &internaljobv1.WatchOperationRequest{Name: name, AfterSequence: cursor}
			if deadline, ok := ctx.Deadline(); ok {
				request.Deadline = timestamppb.New(deadline)
			}
			stream, err := service.transport.WatchOperation(ctx, request)
			if err != nil {
				return nil, normalizeError(err)
			}
			return stream.Recv, nil
		},
		accept: func(cursor uint64, response *internaljobv1.WatchOperationResponse) (uint64, bool, error) {
			if response.GetSequence() <= cursor {
				return cursor, false, &Error{Code: CodeDataLoss, Message: "operation watch sequence did not advance"}
			}
			operation := response.GetOperation()
			if operation == nil || operation.GetOperationId() != name {
				return cursor, false, &Error{Code: CodeDataLoss, Message: "operation watch returned a different or missing operation"}
			}
			if operation.GetDone() != terminalOperationState(operation.GetState()) {
				return cursor, false, &Error{Code: CodeDataLoss, Message: "operation terminal state is inconsistent"}
			}
			return response.GetSequence(), operation.GetDone(), nil
		},
		terminal: func(response *internaljobv1.WatchOperationResponse) error {
			operation := response.GetOperation()
			if operationFailed(operation) {
				return &OperationError{Operation: cloneGenerated(operation)}
			}
			return nil
		},
	}
}

func terminalOperationState(state operationv1.OperationState) bool {
	return state == operationv1.OperationState_OPERATION_STATE_SUCCEEDED ||
		state == operationv1.OperationState_OPERATION_STATE_FAILED ||
		state == operationv1.OperationState_OPERATION_STATE_CANCELLED
}

func operationFailed(operation *operationv1.Operation) bool {
	return operation.GetState() == operationv1.OperationState_OPERATION_STATE_FAILED ||
		operation.GetState() == operationv1.OperationState_OPERATION_STATE_CANCELLED ||
		operation.GetError() != nil
}

func validateTerminalOperation(operation *operationv1.Operation) error {
	if operation == nil || strings.TrimSpace(operation.GetOperationId()) == "" {
		return &Error{Code: CodeDataLoss, Message: "operation service returned an invalid operation"}
	}
	if operation.GetDone() != terminalOperationState(operation.GetState()) {
		return &Error{Code: CodeDataLoss, Message: "operation terminal state is inconsistent"}
	}
	return nil
}
