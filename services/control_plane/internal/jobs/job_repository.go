package jobs

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"time"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type SQLRepository struct{ DB *sql.DB }

// CompleteAttemptSQL locks relational rows before applying a generated enum
// transition. Protobuf represents the service boundary; normalized columns
// remain the durable state authority.
func (r SQLRepository) CompleteAttemptSQL(ctx context.Context, tenantID, attemptID string, epoch uint64, outcome jobv1.AttemptState) error {
	attemptOutcome, runOutcome, err := terminalOutcome(outcome)
	if err != nil {
		return err
	}
	tx, err := r.DB.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var runID string
	var attemptEpoch, currentEpoch uint64
	var runStatus string
	err = tx.QueryRowContext(ctx, `SELECT attempt.run_id, attempt.lease_epoch, run.lease_epoch, run.status FROM attempts AS attempt JOIN runs AS run ON run.tenant_id = attempt.tenant_id AND run.id = attempt.run_id WHERE attempt.tenant_id = $1 AND attempt.id = $2 FOR UPDATE OF run, attempt`, tenantID, attemptID).Scan(&runID, &attemptEpoch, &currentEpoch, &runStatus)
	if err != nil {
		return err
	}
	runState, err := runStateFromDatabase(runStatus)
	if err != nil {
		return err
	}
	accepted := attemptEpoch == epoch && currentEpoch == epoch && runState == jobv1.RunState_RUN_STATE_EXECUTING
	if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_completion_history (tenant_id, attempt_id, lease_epoch, accepted, outcome, recorded_at) VALUES ($1, $2, $3, $4, $5, now())`, tenantID, attemptID, epoch, accepted, attemptOutcome); err != nil {
		return err
	}
	if !accepted {
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'FENCED' WHERE tenant_id = $1 AND id = $2 AND status NOT IN ('COMPLETED','FAILED','CANCELLED')`, tenantID, attemptID); err != nil {
			return err
		}
		if err = tx.Commit(); err != nil {
			return err
		}
		return ErrStaleCompletion
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = $3 WHERE tenant_id = $1 AND id = $2 AND lease_epoch = $4`, tenantID, attemptID, attemptOutcome, epoch); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = $3, version = version + 1 WHERE tenant_id = $1 AND id = $2 AND lease_epoch = $4`, tenantID, runID, runOutcome, epoch); err != nil {
		return err
	}
	return tx.Commit()
}

var (
	ErrNotFound         = errors.New("job resource not found")
	ErrStaleCompletion  = errors.New("stale attempt completion retained")
	ErrTerminalMutation = errors.New("terminal resource cannot advance")
	ErrInvalidOutcome   = errors.New("attempt completion requires a terminal outcome")
)

// These row types are intentionally private: they model normalized relational
// columns and cannot compete with the generated lifecycle messages.
type jobRow struct {
	jobID, operationID, tenantID, projectID string
	state                                   jobv1.JobState
	resourceVersion                         int64
	policyDigest, jobKind                   string
	input, configuration                    *artifactv1.ArtifactRef
	createdAt, updatedAt                    time.Time
	etag                                    string
}

type runRow struct {
	runID, jobID, tenantID, projectID string
	input, configuration, plan        *artifactv1.ArtifactRef
	state                             jobv1.RunState
	resourceVersion                   int64
	leaseEpoch                        uint64
	createdAt, startedAt, completedAt time.Time
	outputs                           []*artifactv1.ArtifactRef
	error                             *commonv1.ErrorDetail
	etag                              string
}

type attemptRow struct {
	attemptID, runID, tenantID, projectID, jobID, workerID string
	leaseEpoch                                             uint64
	state                                                  jobv1.AttemptState
	leaseExpiresAt, leasedAt, startedAt, completedAt       time.Time
	outputs                                                []*artifactv1.ArtifactRef
	error                                                  *commonv1.ErrorDetail
	resourceVersion                                        int64
}

type completionRow struct {
	attemptID string
	epoch     uint64
	outcome   jobv1.AttemptState
	accepted  bool
	at        time.Time
}

type Repository struct {
	mu          sync.Mutex
	jobs        map[string]jobRow
	runs        map[string]runRow
	attempts    map[string]attemptRow
	completions []completionRow
}

func NewRepository() *Repository {
	return &Repository{
		jobs:     make(map[string]jobRow),
		runs:     make(map[string]runRow),
		attempts: make(map[string]attemptRow),
	}
}

func (r *Repository) CreateJob(job *jobv1.Job) error {
	if job == nil || job.GetJobId() == "" || job.GetTenantId() == "" {
		return ErrNotFound
	}
	now := time.Now().UTC()
	row := jobToRow(job)
	row.state = jobv1.JobState_JOB_STATE_ACCEPTED
	row.resourceVersion = 1
	if row.createdAt.IsZero() {
		row.createdAt = now
	}
	row.updatedAt = now
	r.mu.Lock()
	defer r.mu.Unlock()
	r.jobs[row.jobID] = row
	return nil
}

func (r *Repository) CreateRun(run *jobv1.Run) error {
	if run == nil || run.GetRunId() == "" || run.GetJobId() == "" || run.GetTenantId() == "" {
		return ErrNotFound
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	job, ok := r.jobs[run.GetJobId()]
	if !ok || tenants.RequireScope(run.GetTenantId(), job.tenantID) != nil {
		return ErrNotFound
	}
	row := runToRow(run)
	row.state = jobv1.RunState_RUN_STATE_READY
	row.resourceVersion = 1
	if row.projectID == "" {
		row.projectID = job.projectID
	}
	if row.createdAt.IsZero() {
		row.createdAt = time.Now().UTC()
	}
	r.runs[row.runID] = row
	return nil
}

func (r *Repository) AcquireLease(tenantID, runID, attemptID string) (*jobv1.Attempt, error) {
	if attemptID == "" {
		return nil, ErrNotFound
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	run, ok := r.runs[runID]
	if !ok || tenants.RequireScope(tenantID, run.tenantID) != nil {
		return nil, ErrNotFound
	}
	if terminalRunState(run.state) {
		return nil, ErrTerminalMutation
	}
	now := time.Now().UTC()
	for id, prior := range r.attempts {
		if prior.runID != runID || terminalAttemptState(prior.state) {
			continue
		}
		prior.state = jobv1.AttemptState_ATTEMPT_STATE_FENCED
		prior.completedAt = now
		prior.resourceVersion++
		r.attempts[id] = prior
	}
	epoch := run.leaseEpoch + 1
	attempt := attemptRow{
		attemptID:       attemptID,
		tenantID:        tenantID,
		projectID:       run.projectID,
		jobID:           run.jobID,
		runID:           runID,
		leaseEpoch:      epoch,
		state:           jobv1.AttemptState_ATTEMPT_STATE_LEASED,
		leasedAt:        now,
		resourceVersion: 1,
	}
	r.attempts[attemptID] = attempt
	run.state = jobv1.RunState_RUN_STATE_EXECUTING
	run.resourceVersion++
	run.leaseEpoch = epoch
	if run.startedAt.IsZero() {
		run.startedAt = now
	}
	r.runs[runID] = run
	return attemptRowToProto(attempt), nil
}

func (r *Repository) CompleteAttempt(tenantID, attemptID string, epoch uint64, outcome jobv1.AttemptState, at time.Time) error {
	if _, _, err := terminalOutcome(outcome); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	attempt, ok := r.attempts[attemptID]
	if !ok || tenants.RequireScope(tenantID, attempt.tenantID) != nil {
		return ErrNotFound
	}
	run := r.runs[attempt.runID]
	accepted := attempt.leaseEpoch == epoch && run.leaseEpoch == epoch && run.state == jobv1.RunState_RUN_STATE_EXECUTING
	r.completions = append(r.completions, completionRow{attemptID: attemptID, epoch: epoch, outcome: outcome, accepted: accepted, at: at.UTC()})
	if !accepted {
		attempt.state = jobv1.AttemptState_ATTEMPT_STATE_FENCED
		attempt.completedAt = at.UTC()
		attempt.resourceVersion++
		r.attempts[attemptID] = attempt
		return ErrStaleCompletion
	}
	attempt.state = outcome
	attempt.completedAt = at.UTC()
	attempt.resourceVersion++
	switch outcome {
	case jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED:
		run.state = jobv1.RunState_RUN_STATE_SUCCEEDED
	case jobv1.AttemptState_ATTEMPT_STATE_CANCELLED:
		run.state = jobv1.RunState_RUN_STATE_CANCELLED
	default:
		run.state = jobv1.RunState_RUN_STATE_FAILED
	}
	run.completedAt = at.UTC()
	run.resourceVersion++
	r.attempts[attemptID] = attempt
	r.runs[run.runID] = run
	return nil
}

func (r *Repository) Run(tenantID, runID string) (*jobv1.Run, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	run, ok := r.runs[runID]
	if !ok || tenants.RequireScope(tenantID, run.tenantID) != nil {
		return nil, ErrNotFound
	}
	return runRowToProto(run), nil
}

func (r *Repository) CompletionCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.completions)
}

func (r *Repository) CompletionAccepted(index int) (bool, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if index < 0 || index >= len(r.completions) {
		return false, false
	}
	return r.completions[index].accepted, true
}

func terminalOutcome(outcome jobv1.AttemptState) (attemptStatus, runStatus string, err error) {
	switch outcome {
	case jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED:
		return "COMPLETED", "COMPLETED", nil
	case jobv1.AttemptState_ATTEMPT_STATE_FAILED, jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT:
		return "FAILED", "FAILED", nil
	case jobv1.AttemptState_ATTEMPT_STATE_CANCELLED:
		return "CANCELLED", "CANCELLED", nil
	default:
		return "", "", ErrInvalidOutcome
	}
}

func terminalRunState(state jobv1.RunState) bool {
	return state == jobv1.RunState_RUN_STATE_SUCCEEDED || state == jobv1.RunState_RUN_STATE_FAILED || state == jobv1.RunState_RUN_STATE_CANCELLED
}

func terminalAttemptState(state jobv1.AttemptState) bool {
	switch state {
	case jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED,
		jobv1.AttemptState_ATTEMPT_STATE_FAILED,
		jobv1.AttemptState_ATTEMPT_STATE_CANCELLED,
		jobv1.AttemptState_ATTEMPT_STATE_FENCED,
		jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT:
		return true
	default:
		return false
	}
}

func runStateFromDatabase(value string) (jobv1.RunState, error) {
	switch value {
	case "CREATED", "READY":
		return jobv1.RunState_RUN_STATE_READY, nil
	case "EXECUTING":
		return jobv1.RunState_RUN_STATE_EXECUTING, nil
	case "COMPLETED":
		return jobv1.RunState_RUN_STATE_SUCCEEDED, nil
	case "FAILED":
		return jobv1.RunState_RUN_STATE_FAILED, nil
	case "CANCELLED":
		return jobv1.RunState_RUN_STATE_CANCELLED, nil
	default:
		return jobv1.RunState_RUN_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted run state %q", value)
	}
}

func jobToRow(value *jobv1.Job) jobRow {
	return jobRow{
		jobID: value.GetJobId(), operationID: value.GetOperationId(), tenantID: value.GetTenantId(), projectID: value.GetProjectId(),
		state: value.GetState(), resourceVersion: value.GetResourceVersion(), policyDigest: value.GetPolicyDigest(), jobKind: value.GetJobKind(),
		input: cloneArtifact(value.GetInput()), configuration: cloneArtifact(value.GetConfiguration()), createdAt: timestampTime(value.GetCreatedAt()),
		updatedAt: timestampTime(value.GetUpdatedAt()), etag: value.GetEtag(),
	}
}

func runToRow(value *jobv1.Run) runRow {
	return runRow{
		runID: value.GetRunId(), jobID: value.GetJobId(), tenantID: value.GetTenantId(), projectID: value.GetProjectId(),
		input: cloneArtifact(value.GetInput()), configuration: cloneArtifact(value.GetConfiguration()), plan: cloneArtifact(value.GetPlan()),
		state: value.GetState(), resourceVersion: value.GetResourceVersion(), leaseEpoch: value.GetLeaseEpoch(), createdAt: timestampTime(value.GetCreatedAt()),
		startedAt: timestampTime(value.GetStartedAt()), completedAt: timestampTime(value.GetCompletedAt()), outputs: cloneArtifacts(value.GetOutputs()),
		error: cloneError(value.GetError()), etag: value.GetEtag(),
	}
}

func runRowToProto(row runRow) *jobv1.Run {
	return &jobv1.Run{
		RunId: row.runID, JobId: row.jobID, TenantId: row.tenantID, ProjectId: row.projectID,
		Input: cloneArtifact(row.input), Configuration: cloneArtifact(row.configuration), Plan: cloneArtifact(row.plan),
		State: row.state, ResourceVersion: row.resourceVersion, LeaseEpoch: row.leaseEpoch,
		CreatedAt: timeTimestamp(row.createdAt), StartedAt: timeTimestamp(row.startedAt), CompletedAt: timeTimestamp(row.completedAt),
		Outputs: cloneArtifacts(row.outputs), Error: cloneError(row.error), Etag: row.etag,
	}
}

func attemptRowToProto(row attemptRow) *jobv1.Attempt {
	return &jobv1.Attempt{
		AttemptId: row.attemptID, RunId: row.runID, LeaseEpoch: row.leaseEpoch, State: row.state,
		LeaseExpiresAt: timeTimestamp(row.leaseExpiresAt), TenantId: row.tenantID, ProjectId: row.projectID,
		JobId: row.jobID, WorkerId: row.workerID, LeasedAt: timeTimestamp(row.leasedAt), StartedAt: timeTimestamp(row.startedAt),
		CompletedAt: timeTimestamp(row.completedAt), Outputs: cloneArtifacts(row.outputs), Error: cloneError(row.error), ResourceVersion: row.resourceVersion,
	}
}

func cloneArtifact(value *artifactv1.ArtifactRef) *artifactv1.ArtifactRef {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*artifactv1.ArtifactRef)
}

func cloneArtifacts(values []*artifactv1.ArtifactRef) []*artifactv1.ArtifactRef {
	result := make([]*artifactv1.ArtifactRef, len(values))
	for index, value := range values {
		result[index] = cloneArtifact(value)
	}
	return result
}

func cloneError(value *commonv1.ErrorDetail) *commonv1.ErrorDetail {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*commonv1.ErrorDetail)
}

func timestampTime(value *timestamppb.Timestamp) time.Time {
	if value == nil {
		return time.Time{}
	}
	return value.AsTime().UTC()
}

func timeTimestamp(value time.Time) *timestamppb.Timestamp {
	if value.IsZero() {
		return nil
	}
	return timestamppb.New(value.UTC())
}
