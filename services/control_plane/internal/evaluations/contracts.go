package evaluations

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("evaluation resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid evaluation request")
	ErrNotFound            = errors.New("evaluation resource not found")
	ErrAlreadyExists       = errors.New("evaluation resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different evaluation intent")
	ErrRevisionConflict    = errors.New("evaluation revision or etag conflict")
	ErrInvalidTransition   = errors.New("invalid evaluation lifecycle transition")
	ErrDeadlineExceeded    = errors.New("evaluation command deadline has elapsed")
	ErrStaleFence          = errors.New("evaluation result was submitted by a stale attempt")
	ErrLeaseExpired        = errors.New("evaluation result lease has expired")
	ErrLeaseToken          = errors.New("evaluation result lease token is invalid")
)

// Identity is derived exclusively from authenticated transport metadata.
// CommandContext identity fields are correlation evidence and never authority.
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

type (
	Clock     interface{ Now() time.Time }
	realClock struct{}
)

func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

type RunPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    evaluationv1.EvaluationRunState
}

// Repository boundaries accept and return generated protobuf values only.
// Implementations clone at every boundary so mutable aliases never escape.
type Repository interface {
	CreateRun(context.Context, Identity, *internalevaluationv1.CreateEvaluationRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetRun(context.Context, Identity, string) (*evaluationv1.EvaluationRun, error)
	ListRuns(context.Context, Identity, RunPage) ([]*evaluationv1.EvaluationRun, string, time.Time, error)
	CancelRun(context.Context, Identity, *internalevaluationv1.CancelEvaluationRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	CommitResult(context.Context, Identity, *internalevaluationv1.CommitEvaluationResultRequest, string, time.Time) (*evaluationv1.EvaluationResult, *evaluationv1.EvaluationRun, bool, error)
	GetResult(context.Context, Identity, string) (*evaluationv1.EvaluationResult, error)
	CreatePromotionDecision(context.Context, Identity, *internalevaluationv1.CreatePromotionDecisionRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetPromotionDecision(context.Context, Identity, string) (*evaluationv1.PromotionDecision, error)
}

type EventFactory interface {
	RunCreated(Identity, *evaluationv1.EvaluationRun, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	CancellationRequested(Identity, *evaluationv1.EvaluationRun, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ResultCommitted(Identity, *evaluationv1.EvaluationResult, *evaluationv1.EvaluationRun, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	PromotionRecorded(Identity, *evaluationv1.PromotionDecision, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	JobRequested(Identity, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
}

var _ internalevaluationv1.EvaluationServiceServer = (*Server)(nil)

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
