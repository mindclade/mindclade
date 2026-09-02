package mindclade

import (
	"context"
	cryptorand "crypto/rand"
	"math/big"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func unaryInterceptor(config Config) grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		request, response any,
		connection *grpc.ClientConn,
		invoke grpc.UnaryInvoker,
		options ...grpc.CallOption,
	) error {
		if _, ok := ctx.Deadline(); !ok {
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, config.DefaultRPCTimeout)
			defer cancel()
		}
		var requestValue requestMetadata
		ctx, requestValue, _ = withRequestOptions(ctx)
		ctx = attachRequestMetadata(ctx, config, method)
		attempts := 1
		if retryPermitted(method, request, requestValue, config) {
			attempts = config.MaxAttempts
		}
		var trailers metadata.MD
		callOptions := append([]grpc.CallOption(nil), options...)
		callOptions = append(callOptions, grpc.Trailer(&trailers))
		for attempt := 1; attempt <= attempts; attempt++ {
			started := time.Now()
			observeStarted(config.Observer, method, attempt)
			err := invoke(ctx, method, request, response, connection, callOptions...)
			observeFinished(config.Observer, method, attempt, time.Since(started), errorCode(err))
			if err == nil {
				return nil
			}
			code := status.Code(err)
			if attempt == attempts || !retryableCode(code) {
				return enrichError(err, trailers)
			}
			delay := retryDelay(config, attempt)
			if err := waitContext(ctx, delay); err != nil {
				return normalizeError(err)
			}
		}
		return &Error{Code: CodeInternal, Message: "retry loop exited unexpectedly"}
	}
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
		ctx, _, _ = withRequestOptions(ctx)
		ctx = attachRequestMetadata(ctx, config, method)
		started := time.Now()
		observeStarted(config.Observer, method, 1)
		stream, err := streamer(ctx, description, connection, method, options...)
		observeFinished(config.Observer, method, 1, time.Since(started), errorCode(err))
		if err != nil {
			return nil, normalizeError(err)
		}
		return stream, nil
	}
}

func observeStarted(observer Observer, method string, attempt int) {
	defer func() { _ = recover() }()
	observer.RPCStarted(method, attempt)
}

func observeFinished(observer Observer, method string, attempt int, elapsed time.Duration, code Code) {
	defer func() { _ = recover() }()
	observer.RPCFinished(method, attempt, elapsed, code)
}

func errorCode(err error) Code {
	if err == nil {
		return "ok"
	}
	return codeFromGRPC(status.Code(err))
}

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
	upperBound := new(big.Int).Add(big.NewInt(int64(delay)), big.NewInt(1))
	value, err := cryptorand.Int(cryptorand.Reader, upperBound)
	if err != nil {
		return delay / 2
	}
	return time.Duration(value.Int64())
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

func isRetryable(err error) bool {
	code := status.Code(err)
	return code == codes.Unavailable || code == codes.ResourceExhausted || code == codes.Aborted
}
