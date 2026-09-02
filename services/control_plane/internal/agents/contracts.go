package agents

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/proto"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("agent resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid agent request")
	ErrNotFound            = errors.New("agent resource not found")
	ErrAlreadyExists       = errors.New("agent resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different agent intent")
	ErrRevisionConflict    = errors.New("agent revision or etag conflict")
	ErrInvalidTransition   = errors.New("invalid agent lifecycle transition")
	ErrDeadlineExceeded    = errors.New("agent command deadline has elapsed")
	ErrStaleFence          = errors.New("agent mutation was submitted by a stale attempt")
	ErrLeaseExpired        = errors.New("agent attempt lease has expired")
	ErrLeaseToken          = errors.New("agent attempt lease token is invalid")
)

// Identity is transport authority. CommandContext identity values are only
// correlation evidence and never authorize a request.
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
	State                    agentv1.AgentDefinitionState
}

type RunPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    agentv1.AgentRunState
}

type StepPage struct {
	Limit         int
	Parent        string
	AfterSequence uint64
	Filter, Order string
}

// Repository uses generated protobuf resources at its boundary and clones all
// incoming and outgoing messages. SQL row representations remain private.
type Repository interface {
	CreateDefinition(context.Context, Identity, *internalagentv1.CreateAgentDefinitionRequest, string, time.Time) (*jobv1.Operation, bool, error)
	UpdateDefinition(context.Context, Identity, *internalagentv1.UpdateAgentDefinitionRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetDefinition(context.Context, Identity, string) (*agentv1.AgentDefinition, error)
	ListDefinitions(context.Context, Identity, DefinitionPage) ([]*agentv1.AgentDefinition, string, time.Time, error)
	StartRun(context.Context, Identity, *internalagentv1.StartAgentRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetRun(context.Context, Identity, string) (*agentv1.AgentRun, error)
	ListRuns(context.Context, Identity, RunPage) ([]*agentv1.AgentRun, string, time.Time, error)
	CancelRun(context.Context, Identity, *internalagentv1.CancelAgentRunRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetStep(context.Context, Identity, string) (*agentv1.AgentStep, error)
	ListSteps(context.Context, Identity, StepPage) ([]*agentv1.AgentStep, string, time.Time, error)
	CommitStep(context.Context, Identity, *internalagentv1.CommitAgentStepRequest, string, time.Time) (*agentv1.AgentStep, *agentv1.AgentRun, bool, error)
	CommitToolReceipt(context.Context, Identity, *internalagentv1.CommitToolReceiptRequest, string, time.Time) (*agentv1.ToolReceipt, *agentv1.AgentRun, bool, error)
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
