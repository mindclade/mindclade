package mindclade

import (
	"context"
	cryptorand "crypto/rand"
	"errors"
	"io"
	"math/big"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type longRunningStreamContextKey struct{}

func longRunningStreamContext(ctx context.Context) context.Context {
	return context.WithValue(ctx, longRunningStreamContextKey{}, struct{}{})
}

// unaryInterceptor applies the SDK transport policy to one logical call. The
// timeout it establishes is a TOTAL budget: every attempt, every backoff wait,
// and the per-RPC credential acquisition gRPC performs beneath this
// interceptor all draw from the same deadline, so a retried call can never
// outlive the budget the caller asked for.
func unaryInterceptor(config Config) grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		request, response any,
		connection *grpc.ClientConn,
		invoke grpc.UnaryInvoker,
		options ...grpc.CallOption,
	) error {
		// Per-request options are resolved before the deadline is bound so a
		// caller-supplied WithTimeout governs the budget instead of being
		// clamped by the configured default it was meant to replace.
		ctx, requestValue, err := withRequestOptions(ctx)
		if err != nil {
			return normalizeError(err)
		}
		budget := effectiveTimeout(config, requestValue)
		if deadline, ok := ctx.Deadline(); !ok || time.Until(deadline) > budget {
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, budget)
			defer cancel()
		}
		ctx = attachRequestMetadata(ctx, config, method)
		attempts := attemptBudget(config, requestValue, method, request)
		var cumulativeDelay time.Duration
		for attempt := 1; ; attempt++ {
			attemptCtx := attachAttemptMetadata(ctx, attempt-1)
			var headers, trailers metadata.MD
			callOptions := append([]grpc.CallOption(nil), options...)
			callOptions = append(callOptions, grpc.Header(&headers), grpc.Trailer(&trailers))
			started := time.Now()
			observeStarted(config.Observer, method, attempt)
			invokeErr := invoke(attemptCtx, method, request, response, connection, callOptions...)
			elapsed := time.Since(started)
			var normalized error
			if invokeErr != nil {
				normalized = enrichError(invokeErr, trailers)
			}
			observeFinished(config.Observer, attemptEvent(requestValue, method, attempt, elapsed, invokeErr, normalized, headers, trailers))
			if invokeErr == nil {
				// A successful call surfaces its request id only here: there is
				// no error to carry it, so the raw-response capture is the one
				// path by which a caller can correlate a success with a server
				// log line.
				captureResponseMetadata(requestValue, headers, trailers, "ok", "ok")
				return nil
			}
			if attempt >= attempts || !shouldRetry(normalized) {
				captureResponseMetadata(requestValue, headers, trailers, errorCode(invokeErr), safeStatusMessage(status.Code(invokeErr)))
				return withRetryOutcome(normalized, attempt, cumulativeDelay)
			}
			delay := retryDelayForError(config, attempt, normalized)
			if waitErr := waitContext(ctx, delay); waitErr != nil {
				captureResponseMetadata(requestValue, headers, trailers, errorCode(waitErr), safeStatusMessage(status.Code(waitErr)))
				return withRetryOutcome(normalizeError(waitErr), attempt, cumulativeDelay)
			}
			cumulativeDelay += delay
		}
	}
}

// effectiveTimeout resolves the total budget for one logical call. A
// per-request timeout replaces the configured per-RPC default outright; it can
// still only narrow a deadline the caller's own context already imposes.
func effectiveTimeout(config Config, request requestMetadata) time.Duration {
	if request.timeout > 0 {
		return request.timeout
	}
	return config.DefaultRPCTimeout
}

// attemptBudget resolves how many transport attempts one call may issue. A
// method the policy does not classify as safe or idempotent gets exactly one
// attempt, and a per-request maximum can only narrow the configured policy —
// never promote an ineligible method.
func attemptBudget(config Config, request requestMetadata, method string, rpcRequest any) int {
	if !retryEligible(config, request, method, rpcRequest) {
		return 1
	}
	attempts := config.MaxAttempts
	if request.maxAttempts > 0 && request.maxAttempts < attempts {
		attempts = request.maxAttempts
	}
	if attempts < 1 {
		return 1
	}
	return attempts
}

// retryEligible answers whether implicit retry of this RPC is permitted at all.
// The never-retry denylist is consulted first and overrides every other input,
// including an explicit caller override.
func retryEligible(config Config, request requestMetadata, method string, rpcRequest any) bool {
	if neverRetryMethods[method] {
		return false
	}
	if retryPermitted(method, rpcRequest, request, config) {
		return true
	}
	return request.unsafeRetry
}

// shouldRetry decides whether an eligible call should repeat after one
// failure. The server's x-mindclade-should-retry trailer wins in both
// directions: "false" stops a retry the status would have allowed, and "true"
// permits one the default status set would not. It is consulted only after
// eligibility, so it can never promote a non-idempotent or denylisted RPC.
func shouldRetry(err error) bool {
	var sdkError *Error
	if errors.As(err, &sdkError) && sdkError.serverRetryOverride != nil {
		return *sdkError.serverRetryOverride
	}
	return retryableStatus(err)
}

// retryDelayForError resolves one backoff wait. A server retry-after-ms
// trailer is authoritative and is clamped to max_backoff rather than jittered,
// so an honoured server hint stays exactly the interval the server asked for.
// Every other wait is the full-jitter backoff.
func retryDelayForError(config Config, attempt int, err error) time.Duration {
	var sdkError *Error
	if errors.As(err, &sdkError) && (sdkError.retryAfterSet || sdkError.RetryAfter > 0) {
		return min(sdkError.RetryAfter, config.RetryMaxDelay)
	}
	return retryDelay(config, attempt)
}

func streamInterceptor(config Config) grpc.StreamClientInterceptor {
	return func(
		ctx context.Context,
		description *grpc.StreamDesc,
		connection *grpc.ClientConn,
		method string,
		streamer grpc.Streamer,
		options ...grpc.CallOption,
	) (grpc.ClientStream, error) {
		cancel := func() {}
		ctx, requestValue, optionErr := withRequestOptions(ctx)
		if optionErr != nil {
			return nil, normalizeError(optionErr)
		}
		budget := effectiveTimeout(config, requestValue)
		_, longRunning := ctx.Value(longRunningStreamContextKey{}).(struct{})
		if deadline, ok := ctx.Deadline(); !longRunning && (!ok || time.Until(deadline) > budget) {
			ctx, cancel = context.WithTimeout(ctx, budget)
		}
		ctx = attachRequestMetadata(ctx, config, method)
		ctx = attachAttemptMetadata(ctx, 0)
		started := time.Now()
		observeStarted(config.Observer, method, 1)
		stream, err := streamer(ctx, description, connection, method, options...)
		observeFinished(config.Observer, attemptEvent(requestValue, method, 1, time.Since(started), err, nil, nil, nil))
		if err != nil {
			cancel()
			// A stream that never opened has no headers or trailers to read, so
			// the capture carries the status and the identity the SDK sent.
			captureResponseMetadata(requestValue, nil, nil, errorCode(err), safeStatusMessage(status.Code(err)))
			return nil, normalizeError(err)
		}
		return &boundedClientStream{ClientStream: stream, cancel: cancel, request: requestValue}, nil
	}
}

// boundedClientStream releases an SDK-created deadline timer when the stream
// reaches EOF or another terminal receive error. Caller cancellation remains
// authoritative when a consumer abandons a stream before reading it to end.
type boundedClientStream struct {
	grpc.ClientStream
	cancel   context.CancelFunc
	request  requestMetadata
	once     sync.Once
	captured sync.Once
}

func (stream *boundedClientStream) RecvMsg(message any) error {
	err := stream.ClientStream.RecvMsg(message)
	// Headers are readable only once a receive has resolved, so capturing here
	// never blocks a caller waiting on a server that has sent nothing. The
	// first message publishes the request id early; the terminal receive
	// overwrites it with the complete headers, trailers, and final status.
	if err == nil {
		stream.captured.Do(stream.captureHeaders)
		return nil
	}
	stream.once.Do(stream.cancel)
	// A clean end of stream is a success, not the UNKNOWN status a bare io.EOF
	// would otherwise be classified as.
	if errors.Is(err, io.EOF) {
		stream.capture("ok", "ok")
		return err
	}
	stream.capture(errorCode(err), safeStatusMessage(status.Code(err)))
	return err
}

// captureHeaders publishes the request id as soon as a first message proves the
// server has replied. Trailers are deliberately NOT read here: gRPC permits
// ClientStream.Trailer only once a receive has returned a non-nil error, and
// reading it mid-stream is an unsynchronized read of state the transport's own
// reader goroutine is still writing. Nothing is lost by waiting — a live stream
// has no trailers yet — and the terminal receive overwrites this capture with
// the complete headers, trailers, and final status.
func (stream *boundedClientStream) captureHeaders() {
	if stream.request.responseTarget == nil && stream.request.responseSink == nil {
		return
	}
	headers, _ := stream.Header()
	captureResponseMetadata(stream.request, headers, nil, "ok", "ok")
}

// capture records the stream's terminal allowlisted response metadata. It runs
// only after a receive has resolved with an error — a clean io.EOF included —
// which is the one point at which reading Trailer is defined. Header and
// trailer reads are best effort: a stream torn down before the server replied
// still yields the status and the identity the SDK itself sent.
func (stream *boundedClientStream) capture(code Code, statusMessage string) {
	if stream.request.responseTarget == nil && stream.request.responseSink == nil {
		return
	}
	headers, _ := stream.Header()
	captureResponseMetadata(stream.request, headers, stream.Trailer(), code, statusMessage)
}

func observeStarted(observer Observer, method string, attempt int) {
	defer func() { _ = recover() }()
	observer.RPCStarted(method, attempt)
}

// observeFinished reports one completed attempt. An Observer that also
// implements RequestObserver additionally receives the complete bounded event;
// both callbacks share one panic guard, so a hostile or broken observer still
// cannot change an RPC outcome.
func observeFinished(observer Observer, event RPCEvent) {
	defer func() { _ = recover() }()
	observer.RPCFinished(event.Method, event.Attempt, event.Elapsed, event.Status)
	if rich, ok := observer.(RequestObserver); ok {
		rich.RPCAttempt(event)
	}
}

// attemptEvent assembles the bounded telemetry for one attempt. It reads
// metadata KEY NAMES only and takes request identity from the SDK's own record
// rather than from server-controlled values, so nothing a server sends can
// enlarge or poison what an observer receives.
func attemptEvent(
	request requestMetadata,
	method string,
	attempt int,
	elapsed time.Duration,
	invokeErr, normalized error,
	headers, trailers metadata.MD,
) RPCEvent {
	event := RPCEvent{
		Method:       method,
		Attempt:      attempt,
		Elapsed:      elapsed,
		Status:       errorCode(invokeErr),
		RequestID:    request.requestID,
		TraceID:      request.traceID,
		MetadataKeys: metadataKeyNames(headers, trailers),
	}
	var sdkError *Error
	if errors.As(normalized, &sdkError) {
		event.RetryAfter = sdkError.RetryAfter
	}
	return event
}

func errorCode(err error) Code {
	if err == nil {
		return "ok"
	}
	return codeFromGRPC(status.Code(err))
}

// retryDelay computes one full-jitter backoff wait: the nominal interval
// doubles from RetryBaseDelay and saturates at RetryMaxDelay, and the actual
// wait is drawn uniformly from [0, that interval]. The attempt counter is
// 1-based and saturates safely, so an absurd attempt number cannot overflow
// into a negative or unbounded wait.
func retryDelay(config Config, attempt int) time.Duration {
	delay := config.RetryBaseDelay
	for step := 1; step < attempt && delay < config.RetryMaxDelay; step++ {
		if delay > config.RetryMaxDelay/2 {
			delay = config.RetryMaxDelay
			break
		}
		delay *= 2
	}
	if delay <= 0 {
		return 0
	}
	return time.Duration(resolveJitter(config)(int64(delay)))
}

// jitterSource returns a uniform value in [0, bound]. Full jitter draws every
// wait from the whole interval rather than a band around it, so retries from
// many clients decorrelate instead of arriving as a herd.
type jitterSource func(bound int64) int64

// resolveJitter selects the configured randomness, defaulting to the
// cryptographically seeded reader. An injectable source exists so tests can
// script backoff deterministically; production configuration never sets one.
func resolveJitter(config Config) jitterSource {
	if config.jitter != nil {
		return config.jitter
	}
	return cryptographicJitter
}

// cryptographicJitter draws uniformly from [0, bound] using crypto/rand. A
// reader failure degrades to half the interval rather than to zero, so a
// degraded entropy source cannot collapse backoff into a tight retry loop.
func cryptographicJitter(bound int64) int64 {
	if bound <= 0 {
		return 0
	}
	upperBound := new(big.Int).Add(big.NewInt(bound), big.NewInt(1))
	value, err := cryptorand.Int(cryptorand.Reader, upperBound)
	if err != nil {
		return bound / 2
	}
	return value.Int64()
}

func waitContext(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
