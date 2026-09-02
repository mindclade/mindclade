package inference

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("inference resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid inference request")
	ErrNotFound            = errors.New("inference resource not found")
	ErrAlreadyExists       = errors.New("inference resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different inference intent")
	ErrInvalidTransition   = errors.New("invalid inference lifecycle transition")
	ErrDeadlineExceeded    = errors.New("inference deadline has elapsed")
	ErrStaleFence          = errors.New("inference result was submitted by a stale attempt")
	ErrLeaseExpired        = errors.New("inference result lease has expired")
	ErrLeaseToken          = errors.New("inference result lease token is invalid")
	ErrCursorMalformed     = errors.New("inference resume cursor is malformed")
	ErrCursorResource      = errors.New("inference resume cursor belongs to another resource")
	ErrCursorAhead         = errors.New("inference resume cursor is ahead of durable state")
	ErrCursorExpired       = errors.New("inference resume cursor predates retained history")
	ErrHistoryGap          = errors.New("inference operation history is not contiguous")
)

// Identity is resolved from authenticated transport metadata. Identity fields
// in CommandContext are correlation evidence and never grant authority.
type Identity struct {
	TenantID   string
	ProjectID  string
	Principal  string
	WorkerID   string
	LeaseToken string
}

type IdentityResolver interface {
	Resolve(context.Context) (Identity, error)
}

type Clock interface{ Now() time.Time }

type realClock struct{}

// PostgreSQL timestamptz resolves to microseconds. Truncating here keeps an
// accepted command and its idempotent replay byte-identical: without it a
// response built in memory keeps nanosecond digits the database drops.
func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

// Repository accepts and returns generated protobuf values only. Implementors
// clone every input and output so mutable aliases cannot cross the boundary.
type Repository interface {
	Submit(context.Context, Identity, *inferencev1.InferenceRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetRequest(context.Context, Identity, string) (*inferencev1.InferenceRequest, error)
	GetResult(context.Context, Identity, string) (*inferencev1.InferenceResult, *jobv1.Operation, error)
	CommitResult(context.Context, Identity, *internalinferencev1.CommitInferenceResultRequest, string, time.Time) (*inferencev1.InferenceResult, *jobv1.Operation, bool, error)
	ReadOperationRevisions(context.Context, Identity, string, uint64, int) (string, []*jobv1.Operation, bool, error)
	GetResultByRequest(context.Context, Identity, string) (*inferencev1.InferenceResult, error)
}

type EventFactory interface {
	Requested(Identity, *inferencev1.InferenceRequest, *jobv1.Operation, string, time.Time) (*commonv1.EventEnvelope, error)
	ResultCommitted(Identity, *inferencev1.InferenceRequest, *inferencev1.InferenceResult, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	JobRequested(Identity, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB     *sql.DB
	Events EventFactory
}

func clone[T proto.Message](value T) T {
	if any(value) == nil {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}

func cloneSlice[T proto.Message](values []T) []T {
	result := make([]T, 0, len(values))
	for _, value := range values {
		result = append(result, clone(value))
	}
	return result
}

var _ internalinferencev1.InferenceServiceServer = (*Server)(nil)
