package training

import (
	"context"
	"database/sql"
	"errors"
	"time"

	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

var (
	ErrUnauthenticated      = errors.New("authenticated identity is required")
	ErrPermissionDenied     = errors.New("authenticated identity does not own the requested resource")
	ErrInvalidArgument      = errors.New("invalid training request")
	ErrNotFound             = errors.New("training resource not found")
	ErrAlreadyExists        = errors.New("training resource already exists")
	ErrIdempotencyConflict  = errors.New("idempotency key was reused with different command content")
	ErrRevisionConflict     = errors.New("resource revision or etag conflict")
	ErrStaleFence           = errors.New("training attempt fence is stale")
	ErrLeaseExpired         = errors.New("training attempt lease is expired")
	ErrLeaseToken           = errors.New("training attempt lease token is invalid")
	ErrDeadlineExceeded     = errors.New("training command deadline has elapsed")
	ErrNonMonotonicProgress = errors.New("training progress must advance monotonically")
	ErrInvalidTransition    = errors.New("invalid training state transition")
	ErrTerminal             = errors.New("training run is already terminal")
	ErrCursorMalformed      = errors.New("operation resume cursor is malformed")
	ErrCursorResource       = errors.New("operation resume cursor belongs to another resource")
	ErrCursorAhead          = errors.New("operation resume cursor is ahead of durable state")
	ErrCursorExpired        = errors.New("operation resume cursor predates retained history")
	ErrOperationHistoryGap  = errors.New("operation revision history is not contiguous")
)

// Identity is resolved from authenticated transport state. CommandContext
// identity fields are correlation evidence only and never grant authority.
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

type Clock interface {
	Now() time.Time
}

type realClock struct{}

// PostgreSQL timestamptz resolves to microseconds. Truncating here keeps an
// accepted command and its idempotent replay byte-identical: without it a
// response built in memory keeps nanosecond digits the database drops.
func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

// Repository accepts and returns authoritative generated resources. Every
// implementation must clone at its boundary so mutable protobuf aliases never
// escape persistence.
type Repository interface {
	CreateTrainingRun(context.Context, Identity, *trainingv1.CreateTrainingRunCommand, string, time.Time) (*jobv1.Operation, bool, error)
	GetTrainingRun(context.Context, Identity, string) (*trainingv1.TrainingRun, error)
	ListTrainingRuns(context.Context, Identity, RunPage) ([]*trainingv1.TrainingRun, string, time.Time, error)
	StartTrainingAttempt(context.Context, Identity, *trainingv1.StartTrainingAttemptCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error)
	ResumeTrainingAttempt(context.Context, Identity, *trainingv1.ResumeTrainingAttemptCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error)
	CommitTrainingProgress(context.Context, Identity, *trainingv1.CommitTrainingProgressCommand, string, time.Time) (*trainingv1.TrainingProgress, *trainingv1.TrainingRun, bool, error)
	PrepareCheckpoint(context.Context, Identity, *trainingv1.PrepareCheckpointCommand, string, time.Time) (*trainingv1.Checkpoint, bool, error)
	CommitCheckpoint(context.Context, Identity, *trainingv1.CommitCheckpointCommand, string, time.Time) (*trainingv1.Checkpoint, *trainingv1.TrainingRun, bool, error)
	CompleteTrainingRun(context.Context, Identity, *trainingv1.CompleteTrainingRunCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error)
	CancelTrainingRun(context.Context, Identity, *trainingv1.CancelTrainingRunCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error)
	GetCheckpoint(context.Context, Identity, string) (*trainingv1.Checkpoint, error)
	ListCheckpoints(context.Context, Identity, CheckpointPage) ([]*trainingv1.Checkpoint, string, time.Time, error)
	GetOperation(context.Context, Identity, string) (*jobv1.Operation, error)
	ReadOperationRevisions(context.Context, Identity, string, uint64, int) ([]*jobv1.Operation, bool, error)
	ListOperations(context.Context, Identity, OperationPage) ([]*jobv1.Operation, string, time.Time, error)
	CancelOperation(context.Context, Identity, *internaljobv1.CancelOperationRequest, string, time.Time) (*jobv1.Operation, bool, error)
}

type RunPage struct {
	Limit     int
	AfterTime time.Time
	AfterName string
	State     trainingv1.TrainingRunState
	Order     string
	Filter    string
}

type CheckpointPage struct {
	Limit      int
	RunName    string
	AfterEpoch uint64
	AfterName  string
	Order      string
	Filter     string
	State      trainingv1.CheckpointState
}

type OperationPage struct {
	Limit     int
	AfterTime time.Time
	AfterName string
	Order     string
	Filter    string
	State     jobv1.OperationState
}

// SQLRepository performs all aggregate writes in tenant-scoped transactions.
type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
}

var (
	_ internaltrainingv1.TrainingServiceServer = (*Server)(nil)
	_ internaljobv1.OperationServiceServer     = (*Server)(nil)
)
