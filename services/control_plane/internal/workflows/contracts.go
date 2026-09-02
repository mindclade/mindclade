package workflows

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"

	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("workflow resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid workflow request")
	ErrNotFound            = errors.New("workflow resource not found")
	ErrAlreadyExists       = errors.New("workflow resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different workflow intent")
	ErrRevisionConflict    = errors.New("workflow revision or etag conflict")
	ErrInvalidTransition   = errors.New("invalid workflow lifecycle transition")
	ErrDeadlineExceeded    = errors.New("workflow command deadline has elapsed")
	ErrStaleFence          = errors.New("workflow transition was submitted by a stale attempt")
	ErrLeaseExpired        = errors.New("workflow attempt lease has expired")
	ErrLeaseToken          = errors.New("workflow attempt lease token is invalid")
	ErrApprovalConsumed    = errors.New("approval receipt is already consumed")
	ErrApprovalExpired     = errors.New("approval receipt has expired")
)

// Identity is derived only from authenticated transport metadata. CommandContext
// identity fields are correlation evidence and never grant authority.
type Identity struct {
	TenantID   string
	ProjectID  string
	Principal  string
	WorkerID   string
	LeaseToken string
	Roles      map[string]struct{}
}

func (identity Identity) HasAnyRole(roles ...string) bool {
	for _, role := range roles {
		if _, ok := identity.Roles[role]; ok {
			return true
		}
	}
	return false
}

type IdentityResolver interface {
	Resolve(context.Context) (Identity, error)
}
type (
	Clock     interface{ Now() time.Time }
	realClock struct{}
)

func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

type DefinitionPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    workflowv1.WorkflowDefinitionState
}

type RunPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    workflowv1.WorkflowRunState
}

type ApprovalPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    workflowv1.ApprovalState
}

// Repository boundaries use generated protobuf values and clone at both sides.
// Private SQL row types never leave this package.
type Repository interface {
	CreateDefinition(context.Context, Identity, *internalworkflowv1.CreateWorkflowDefinitionRequest, string, time.Time) (*jobv1.Operation, bool, error)
	UpdateDefinition(context.Context, Identity, *internalworkflowv1.UpdateWorkflowDefinitionRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetDefinition(context.Context, Identity, string) (*workflowv1.WorkflowDefinition, error)
	ListDefinitions(context.Context, Identity, DefinitionPage) ([]*workflowv1.WorkflowDefinition, string, time.Time, error)
	StartRun(context.Context, Identity, *internalworkflowv1.StartWorkflowRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetRun(context.Context, Identity, string) (*workflowv1.WorkflowRun, error)
	ListRuns(context.Context, Identity, RunPage) ([]*workflowv1.WorkflowRun, string, time.Time, error)
	CancelRun(context.Context, Identity, *internalworkflowv1.CancelWorkflowRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	CommitTransition(context.Context, Identity, *internalworkflowv1.CommitWorkflowTransitionRequest, string, time.Time) (*workflowv1.WorkflowRun, bool, error)
	ListTransitions(context.Context, Identity, string, uint64, int) ([]*workflowv1.WorkflowRun, error)
	RequestApproval(context.Context, Identity, *workflowv1.ApprovalRequest, string, time.Time) (*workflowv1.ApprovalRequest, bool, error)
	GetApproval(context.Context, Identity, string) (*workflowv1.ApprovalRequest, error)
	ListApprovals(context.Context, Identity, ApprovalPage) ([]*workflowv1.ApprovalRequest, string, time.Time, error)
	DecideApproval(context.Context, Identity, *internalworkflowv1.DecideApprovalRequest, string, time.Time) (*workflowv1.ApprovalReceipt, bool, error)
	ConsumeApproval(context.Context, Identity, *internalworkflowv1.ConsumeApprovalRequest, string, time.Time) (*workflowv1.ApprovalReceipt, bool, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
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
