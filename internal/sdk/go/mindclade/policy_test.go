package mindclade

import (
	"context"
	"errors"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

func TestPlaintextAuthorityRequiresExactLoopback(t *testing.T) {
	for _, endpoint := range []string{
		"bufnet-attacker.example:443",
		"localhost.example:443",
		"192.0.2.1:9443",
	} {
		_, err := New(
			WithEnvironment(Local),
			WithEndpoint(endpoint),
			WithTenantProject("tenant-a", "project-a"),
			WithPrincipal("principal-a"),
			WithInsecureTransportForTesting(),
		)
		if err == nil || err.Error() != "mindclade: insecure transport is restricted to Local loopback" {
			t.Fatalf("endpoint %q was not rejected as non-loopback: %v", endpoint, err)
		}
	}
	if !isLoopbackEndpoint("127.1.2.3:9443") || !isLoopbackEndpoint("[::1]:9443") || !isLoopbackEndpoint("bufnet:1") {
		t.Fatal("an explicit loopback/test authority was rejected")
	}
}

func TestWorkloadIdentityAudienceUsesCanonicalHTTPSOrigin(t *testing.T) {
	for _, test := range []struct {
		endpoint string
		want     string
	}{
		{endpoint: "CONTROL-PLANE.EXAMPLE:443", want: "https://control-plane.example"},
		{endpoint: "control-plane.example:8443", want: "https://control-plane.example:8443"},
		{endpoint: "[2001:db8::1]:443", want: "https://[2001:db8::1]"},
	} {
		config := defaultConfig()
		config.Endpoint = test.endpoint
		config.TenantID = "tenant-a"
		config.ProjectID = "project-a"
		config.PrincipalID = "principal-a"
		config.workloadIdentity = true
		if err := config.finalize(); err != nil {
			t.Fatalf("finalize %q: %v", test.endpoint, err)
		}
		if config.Audience != test.want {
			t.Fatalf("audience for %q = %q, want %q", test.endpoint, config.Audience, test.want)
		}
	}

	config := defaultConfig()
	config.Endpoint = "control-plane.example:443"
	config.Audience = "https://verifier.example/custom-audience"
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.workloadIdentity = true
	if err := config.finalize(); err != nil {
		t.Fatal(err)
	}
	if config.Audience != "https://verifier.example/custom-audience" {
		t.Fatalf("explicit audience was changed: %q", config.Audience)
	}
}

func TestRawMutationMetadataCannotPromoteRetrySafety(t *testing.T) {
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.MaxAttempts = 3
	config.RetryBaseDelay = time.Nanosecond
	config.RetryMaxDelay = time.Nanosecond
	interceptor := unaryInterceptor(config)
	ctx, _, err := withRequestOptions(context.Background(), WithIdempotencyKey("key-a"))
	if err != nil {
		t.Fatal(err)
	}
	attempts := 0
	err = interceptor(ctx, "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun", nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			attempts++
			return status.Error(codes.Unavailable, "retryable transport failure")
		},
	)
	if err == nil || attempts != 1 {
		t.Fatalf("unknown mutation was retried: attempts=%d err=%v", attempts, err)
	}
}

func TestKnownMutationRequiresMatchingGeneratedCommandContext(t *testing.T) {
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	metadata := requestMetadata{idempotencyKey: "key-a", requestID: "request-a", traceID: "trace-a"}
	command := &trainingv1.CreateTrainingRunCommand{TrainingRunId: "run-a"}
	digest, err := deterministicDigest(command)
	if err != nil {
		t.Fatal(err)
	}
	command.Context = commandContext(config, contextWithDeadline(t), metadata, digest)
	request := &internaltrainingv1.CreateTrainingRunRequest{Command: command}
	if !retryPermitted("/mindclade.internal.training.v1.TrainingService/CreateTrainingRun", request, metadata, config) {
		t.Fatal("matching generated idempotent command was not retryable")
	}
	metadata.idempotencyKey = "different-key"
	if retryPermitted("/mindclade.internal.training.v1.TrainingService/CreateTrainingRun", request, metadata, config) {
		t.Fatal("mismatched metadata promoted mutation retry safety")
	}
}

func TestLongRunningDefaultsAndTerminalFailuresAreBounded(t *testing.T) {
	client := &Client{config: defaultConfig()}
	service := &OperationService{client: client}
	ctx, cancel, err := service.longRunningContext(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer cancel()
	deadline, ok := ctx.Deadline()
	if !ok || time.Until(deadline) > defaultOperationTimeout || time.Until(deadline) < defaultOperationTimeout-time.Second {
		t.Fatalf("unexpected operation deadline: %v, %v", deadline, ok)
	}
	operation := &jobv1.Operation{
		OperationId: "operations/failed-a",
		State:       jobv1.OperationState_OPERATION_STATE_FAILED,
		Done:        true,
	}
	if err := validateTerminalOperation(operation); err != nil {
		t.Fatalf("valid terminal operation rejected: %v", err)
	}
	operationError := &OperationError{Operation: operation}
	var typed *OperationError
	if !errors.As(operationError, &typed) || typed.Operation != operation {
		t.Fatal("typed operation failure did not preserve the generated operation")
	}
	if delay := retryDelay(defaultConfig(), 1<<30); delay < 0 || delay > defaultRetryMaxDelay {
		t.Fatalf("retry backoff was not saturated: %v", delay)
	}
}

func contextWithDeadline(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	t.Cleanup(cancel)
	return ctx
}

func TestExpireAttemptLeasesIsNeverRetried(t *testing.T) {
	const method = "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases"
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.MaxAttempts = 4
	config.jitter = func(int64) int64 { return 0 }
	request := &internaljobv1.ExpireAttemptLeasesRequest{}

	for name, options := range map[string][]RequestOption{
		"default policy":  nil,
		"caller override": {WithUnsafeRetryOfNonIdempotentRPC(), WithMaxAttempts(8)},
	} {
		ctx, requestValue, err := withRequestOptions(context.Background(), options...)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if retryPermitted(method, request, requestValue, config) {
			t.Fatalf("%s: denylisted method was classified retryable", name)
		}
		if retryEligible(config, requestValue, method, request) {
			t.Fatalf("%s: denylisted method was eligible for retry", name)
		}
		attempts := 0
		_ = unaryInterceptor(config)(ctx, method, request, nil, nil,
			func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, callOptions ...grpc.CallOption) error {
				attempts++
				for _, option := range callOptions {
					if trailer, ok := option.(grpc.TrailerCallOption); ok && trailer.TrailerAddr != nil {
						*trailer.TrailerAddr = metadata.Pairs("x-mindclade-should-retry", "true")
					}
				}
				return status.Error(codes.Unavailable, "reconciler transport failure")
			},
		)
		if attempts != 1 {
			t.Fatalf("%s: lease expiry was retried %d times", name, attempts)
		}
	}
}

func TestPerRequestAttemptsAndTimeoutOnlyNarrow(t *testing.T) {
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.MaxAttempts = 4
	config.RetryBaseDelay = time.Millisecond
	config.RetryMaxDelay = time.Millisecond
	config.jitter = func(int64) int64 { return 0 }

	countAttempts := func(ctx context.Context, method string, request any) int {
		t.Helper()
		attempts := 0
		_ = unaryInterceptor(config)(ctx, method, request, nil, nil,
			func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
				attempts++
				return status.Error(codes.Unavailable, "transport failure")
			},
		)
		return attempts
	}

	unbounded, _, err := withRequestOptions(context.Background(), WithMaxAttempts(8))
	if err != nil {
		t.Fatal(err)
	}
	if attempts := countAttempts(unbounded, "/mindclade.internal.job.v1.RunService/CommitAttempt", &internaljobv1.CommitAttemptRequest{}); attempts != 1 {
		t.Fatalf("a per-request maximum promoted an ineligible mutation: attempts=%d", attempts)
	}
	if attempts := countAttempts(unbounded, "/mindclade.internal.job.v1.OperationService/GetOperation", nil); attempts != config.MaxAttempts {
		t.Fatalf("a per-request maximum widened the configured policy: attempts=%d, want %d", attempts, config.MaxAttempts)
	}
	narrowed, _, err := withRequestOptions(context.Background(), WithMaxAttempts(2))
	if err != nil {
		t.Fatal(err)
	}
	if attempts := countAttempts(narrowed, "/mindclade.internal.job.v1.OperationService/GetOperation", nil); attempts != 2 {
		t.Fatalf("a per-request maximum did not narrow the policy: attempts=%d", attempts)
	}

	callerDeadline, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	extended, _, err := withRequestOptions(callerDeadline, WithTimeout(4*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	err = unaryInterceptor(config)(extended, "/mindclade.internal.job.v1.OperationService/GetOperation", nil, nil, nil,
		func(callContext context.Context, _ string, _, _ any, _ *grpc.ClientConn, _ ...grpc.CallOption) error {
			deadline, ok := callContext.Deadline()
			if !ok || time.Until(deadline) > time.Second {
				t.Fatalf("per-request timeout extended a caller deadline: %v", deadline)
			}
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	for name, option := range map[string]RequestOption{
		"timeout above the policy ceiling":  WithTimeout(6 * time.Minute),
		"negative timeout":                  WithTimeout(-time.Second),
		"attempts above the policy ceiling": WithMaxAttempts(9),
	} {
		if _, _, err := withRequestOptions(context.Background(), option); err == nil {
			t.Fatalf("%s was accepted", name)
		}
	}
}

func TestUnsafeRetryOverrideIsExplicitAndBounded(t *testing.T) {
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.MaxAttempts = 3
	config.RetryBaseDelay = time.Millisecond
	config.RetryMaxDelay = time.Millisecond
	config.jitter = func(int64) int64 { return 0 }
	const method = "/mindclade.internal.job.v1.RunService/CommitAttempt"
	request := &internaljobv1.CommitAttemptRequest{}

	attemptsWith := func(options ...RequestOption) int {
		t.Helper()
		ctx, _, err := withRequestOptions(context.Background(), options...)
		if err != nil {
			t.Fatal(err)
		}
		attempts := 0
		_ = unaryInterceptor(config)(ctx, method, request, nil, nil,
			func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
				attempts++
				return status.Error(codes.Unavailable, "transport failure")
			},
		)
		return attempts
	}
	if attempts := attemptsWith(); attempts != 1 {
		t.Fatalf("a mutation without a validated command context was retried: attempts=%d", attempts)
	}
	if attempts := attemptsWith(WithUnsafeRetryOfNonIdempotentRPC()); attempts != config.MaxAttempts {
		t.Fatalf("the explicit unsafe override did not take effect: attempts=%d, want %d", attempts, config.MaxAttempts)
	}
	if attempts := attemptsWith(WithUnsafeRetryOfNonIdempotentRPC(), WithMaxAttempts(2)); attempts != 2 {
		t.Fatalf("the unsafe override escaped the per-request bound: attempts=%d", attempts)
	}
}

func TestOneRetryablePredicateGovernsEveryCallSite(t *testing.T) {
	for code, want := range map[codes.Code]bool{
		codes.Unavailable:        true,
		codes.ResourceExhausted:  true,
		codes.Aborted:            true,
		codes.DeadlineExceeded:   true,
		codes.NotFound:           false,
		codes.InvalidArgument:    false,
		codes.PermissionDenied:   false,
		codes.FailedPrecondition: false,
		codes.Canceled:           false,
	} {
		failure := status.Error(code, "scripted failure")
		if got := retryableStatus(failure); got != want {
			t.Fatalf("retryableStatus(%s) = %t, want %t", code, got, want)
		}
		if got := isRetryable(failure); got != want {
			t.Fatalf("isRetryable(%s) = %t, want %t; the stream path diverged from the unary path", code, got, want)
		}
		if got := retryableStatus(normalizeError(failure)); got != want {
			t.Fatalf("retryableStatus of the normalized %s = %t, want %t", code, got, want)
		}
	}
	if !retryableStatus(context.DeadlineExceeded) || retryableStatus(context.Canceled) || retryableStatus(nil) {
		t.Fatal("context failures were not classified consistently")
	}
}
