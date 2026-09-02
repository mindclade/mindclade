package mindclade

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

// Code is a transport-neutral failure classification.
type Code string

const (
	CodeUnknown            Code = "unknown"
	CodeCanceled           Code = "canceled"
	CodeInvalidArgument    Code = "invalid_argument"
	CodeDeadlineExceeded   Code = "deadline_exceeded"
	CodeNotFound           Code = "not_found"
	CodeAlreadyExists      Code = "already_exists"
	CodePermissionDenied   Code = "permission_denied"
	CodeResourceExhausted  Code = "resource_exhausted"
	CodeFailedPrecondition Code = "failed_precondition"
	CodeAborted            Code = "aborted"
	CodeOutOfRange         Code = "out_of_range"
	CodeUnimplemented      Code = "unimplemented"
	CodeInternal           Code = "internal"
	CodeUnavailable        Code = "unavailable"
	CodeDataLoss           Code = "data_loss"
	CodeUnauthenticated    Code = "unauthenticated"
)

// Error preserves machine-actionable status and safe request metadata without
// exposing serialized request/response payloads.
type Error struct {
	Code       Code
	Message    string
	RequestID  string
	Retryable  bool
	RetryAfter time.Duration
	Cause      error
}

// OperationError represents a durable terminal failure. The generated
// operation remains available for its authoritative state, result, and error.
type OperationError struct {
	Operation *jobv1.Operation
}

func (err *OperationError) Error() string {
	if err == nil || err.Operation == nil {
		return "mindclade: operation failed"
	}
	return fmt.Sprintf("mindclade: operation %s reached terminal state %s", err.Operation.GetOperationId(), err.Operation.GetState())
}

func (err *Error) Error() string {
	if err == nil {
		return "<nil>"
	}
	if err.RequestID != "" {
		return fmt.Sprintf("mindclade: %s: %s (request_id=%s)", err.Code, err.Message, err.RequestID)
	}
	return fmt.Sprintf("mindclade: %s: %s", err.Code, err.Message)
}

func (err *Error) Unwrap() error { return err.Cause }

func normalizeError(err error) error {
	if err == nil {
		return nil
	}
	var existing *Error
	if errors.As(err, &existing) {
		return existing
	}
	if errors.Is(err, context.Canceled) {
		return &Error{Code: CodeCanceled, Message: "request canceled", Cause: err}
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return &Error{Code: CodeDeadlineExceeded, Message: "request deadline exceeded", Retryable: true, Cause: err}
	}
	grpcStatus, ok := status.FromError(err)
	if !ok {
		return &Error{Code: CodeUnknown, Message: "request failed"}
	}
	code := codeFromGRPC(grpcStatus.Code())
	return &Error{
		Code:      code,
		Message:   safeStatusMessage(grpcStatus.Code()),
		Retryable: retryableCode(grpcStatus.Code()),
	}
}

func safeStatusMessage(code codes.Code) string {
	switch code {
	case codes.Canceled:
		return "request canceled"
	case codes.InvalidArgument:
		return "request is invalid"
	case codes.DeadlineExceeded:
		return "request deadline exceeded"
	case codes.NotFound:
		return "resource was not found"
	case codes.AlreadyExists:
		return "resource already exists"
	case codes.PermissionDenied:
		return "permission denied"
	case codes.ResourceExhausted:
		return "remote service is resource constrained"
	case codes.FailedPrecondition:
		return "request precondition failed"
	case codes.Aborted:
		return "request conflicted with concurrent state"
	case codes.OutOfRange:
		return "request is outside the retained range"
	case codes.Unimplemented:
		return "operation is not implemented"
	case codes.Internal:
		return "remote service failed internally"
	case codes.Unavailable:
		return "remote service is unavailable"
	case codes.DataLoss:
		return "remote service reported data loss"
	case codes.Unauthenticated:
		return "authentication is required"
	default:
		return "request failed"
	}
}

func enrichError(err error, trailers metadata.MD) error {
	normalized := normalizeError(err)
	var sdkError *Error
	if !errors.As(normalized, &sdkError) {
		return normalized
	}
	clone := *sdkError
	clone.RequestID = firstMetadata(trailers, "x-request-id", "request-id")
	if value := firstMetadata(trailers, "retry-after-ms"); value != "" {
		if milliseconds, parseErr := strconv.ParseInt(value, 10, 64); parseErr == nil && milliseconds >= 0 && milliseconds <= int64(time.Hour/time.Millisecond) {
			clone.RetryAfter = time.Duration(milliseconds) * time.Millisecond
		}
	}
	return &clone
}

func firstMetadata(values metadata.MD, keys ...string) string {
	for _, key := range keys {
		items := values.Get(key)
		if len(items) > 0 {
			value := items[0]
			if len(value) <= 256 && isGraphicASCII(value) {
				return value
			}
		}
	}
	return ""
}

func codeFromGRPC(code codes.Code) Code {
	switch code {
	case codes.Canceled:
		return CodeCanceled
	case codes.InvalidArgument:
		return CodeInvalidArgument
	case codes.DeadlineExceeded:
		return CodeDeadlineExceeded
	case codes.NotFound:
		return CodeNotFound
	case codes.AlreadyExists:
		return CodeAlreadyExists
	case codes.PermissionDenied:
		return CodePermissionDenied
	case codes.ResourceExhausted:
		return CodeResourceExhausted
	case codes.FailedPrecondition:
		return CodeFailedPrecondition
	case codes.Aborted:
		return CodeAborted
	case codes.OutOfRange:
		return CodeOutOfRange
	case codes.Unimplemented:
		return CodeUnimplemented
	case codes.Internal:
		return CodeInternal
	case codes.Unavailable:
		return CodeUnavailable
	case codes.DataLoss:
		return CodeDataLoss
	case codes.Unauthenticated:
		return CodeUnauthenticated
	default:
		return CodeUnknown
	}
}

func retryableCode(code codes.Code) bool {
	return code == codes.Unavailable || code == codes.ResourceExhausted || code == codes.Aborted
}
