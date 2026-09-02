package mindclade

import (
	"context"
	"errors"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

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
