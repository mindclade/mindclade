package experiments

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("experiment resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid experiment request")
	ErrNotFound            = errors.New("experiment resource not found")
	ErrAlreadyExists       = errors.New("experiment resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different experiment intent")
	ErrRevisionConflict    = errors.New("experiment revision or etag conflict")
	ErrInvalidTransition   = errors.New("invalid experiment lifecycle transition")
	ErrDeadlineExceeded    = errors.New("experiment command deadline has elapsed")
)

// Identity is derived from authenticated transport metadata, never request fields.
type Identity struct{ TenantID, ProjectID, Principal string }

type IdentityResolver interface {
	Resolve(context.Context) (Identity, error)
}

type Clock interface{ Now() time.Time }

type realClock struct{}

func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

type Page struct {
	Limit                    int
	Parent                   string
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    int32
}

// Repository accepts and returns generated protobuf values and clones at boundaries.
type Repository interface {
	CreateExperiment(context.Context, Identity, *experimentv1.CreateExperimentCommand, string, time.Time) (*experimentv1.Experiment, bool, error)
	GetExperiment(context.Context, Identity, string) (*experimentv1.Experiment, error)
	ListExperiments(context.Context, Identity, Page) ([]*experimentv1.Experiment, string, time.Time, error)
	UpdateExperiment(context.Context, Identity, *experimentv1.UpdateExperimentCommand, string, time.Time) (*experimentv1.Experiment, bool, error)
	TransitionExperiment(context.Context, Identity, *experimentv1.TransitionExperimentCommand, string, time.Time) (*experimentv1.Experiment, bool, error)
	CreateStudy(context.Context, Identity, *experimentv1.CreateStudyCommand, string, time.Time) (*experimentv1.Study, bool, error)
	GetStudy(context.Context, Identity, string) (*experimentv1.Study, error)
	ListStudies(context.Context, Identity, Page) ([]*experimentv1.Study, string, time.Time, error)
	TransitionStudy(context.Context, Identity, *experimentv1.TransitionStudyCommand, string, time.Time) (*experimentv1.Study, bool, error)
	CreateTrial(context.Context, Identity, *experimentv1.CreateTrialCommand, string, time.Time) (*experimentv1.Trial, bool, error)
	GetTrial(context.Context, Identity, string) (*experimentv1.Trial, error)
	ListTrials(context.Context, Identity, Page) ([]*experimentv1.Trial, string, time.Time, error)
	TransitionTrial(context.Context, Identity, *experimentv1.TransitionTrialCommand, string, time.Time) (*experimentv1.Trial, bool, error)
	CompleteTrial(context.Context, Identity, *experimentv1.CompleteTrialCommand, string, time.Time) (*experimentv1.Trial, bool, error)
}

type EventFactory interface {
	ExperimentCreated(Identity, *experimentv1.Experiment, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ExperimentUpdated(Identity, *experimentv1.Experiment, []string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ExperimentStateChanged(Identity, *experimentv1.Experiment, experimentv1.ExperimentState, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	StudyCreated(Identity, *experimentv1.Study, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	StudyStateChanged(Identity, *experimentv1.Study, experimentv1.StudyState, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	TrialCreated(Identity, *experimentv1.Trial, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	TrialStateChanged(Identity, *experimentv1.Trial, experimentv1.TrialState, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	TrialCompleted(Identity, *experimentv1.Trial, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
}

var _ internalexperimentv1.ExperimentServiceServer = (*Server)(nil)

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
