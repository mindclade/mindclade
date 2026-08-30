package jobs

import (
	"context"
	"database/sql"
	"errors"
	"sync"
	"time"

	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

// CompleteAttemptSQL locks the run before recording the completion so the current lease epoch is authoritative.
func (r SQLRepository) CompleteAttemptSQL(ctx context.Context, tenantID, attemptID string, epoch uint64, outcome string) error {
	tx, err := r.DB.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var runID string
	var attemptEpoch, currentEpoch uint64
	var runState string
	err = tx.QueryRowContext(ctx, `SELECT attempt.run_id, attempt.lease_epoch, run.lease_epoch, run.status FROM attempts AS attempt JOIN runs AS run ON run.tenant_id = attempt.tenant_id AND run.id = attempt.run_id WHERE attempt.tenant_id = $1 AND attempt.id = $2 FOR UPDATE OF run, attempt`, tenantID, attemptID).Scan(&runID, &attemptEpoch, &currentEpoch, &runState)
	if err != nil {
		return err
	}
	accepted := attemptEpoch == epoch && currentEpoch == epoch && runState == "EXECUTING"
	if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_completion_history (tenant_id, attempt_id, lease_epoch, accepted, outcome, recorded_at) VALUES ($1, $2, $3, $4, $5, now())`, tenantID, attemptID, epoch, accepted, outcome); err != nil {
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
	runOutcome, attemptOutcome := "FAILED", "FAILED"
	if outcome == "SUCCEEDED" {
		runOutcome, attemptOutcome = "COMPLETED", "COMPLETED"
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
)

type Job struct {
	ID       string
	TenantID string
	State    string
	Version  uint64
}
type Run struct {
	ID         string
	TenantID   string
	JobID      string
	State      string
	Version    uint64
	LeaseEpoch uint64
}
type Attempt struct {
	ID         string
	TenantID   string
	RunID      string
	LeaseEpoch uint64
	State      string
}
type Completion struct {
	AttemptID string
	Epoch     uint64
	Outcome   string
	Accepted  bool
	At        time.Time
}

type Repository struct {
	mu          sync.Mutex
	jobs        map[string]Job
	runs        map[string]Run
	attempts    map[string]Attempt
	completions []Completion
}

func NewRepository() *Repository {
	return &Repository{jobs: make(map[string]Job), runs: make(map[string]Run), attempts: make(map[string]Attempt)}
}

func (r *Repository) CreateJob(job Job) error {
	if job.ID == "" || job.TenantID == "" {
		return ErrNotFound
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	job.State, job.Version = "ACCEPTED", 1
	r.jobs[job.ID] = job
	return nil
}

func (r *Repository) CreateRun(run Run) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	job, ok := r.jobs[run.JobID]
	if !ok || tenants.RequireScope(run.TenantID, job.TenantID) != nil {
		return ErrNotFound
	}
	run.State, run.Version = "READY", 1
	r.runs[run.ID] = run
	return nil
}

func (r *Repository) AcquireLease(tenantID, runID, attemptID string) (Attempt, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	run, ok := r.runs[runID]
	if !ok || tenants.RequireScope(tenantID, run.TenantID) != nil {
		return Attempt{}, ErrNotFound
	}
	if run.State == "COMPLETED" || run.State == "FAILED" || run.State == "CANCELLED" {
		return Attempt{}, ErrTerminalMutation
	}
	for id, prior := range r.attempts {
		if prior.RunID != runID {
			continue
		}
		switch prior.State {
		case "COMPLETED", "FAILED", "CANCELLED", "FENCED":
			continue
		default:
			prior.State = "FENCED"
			r.attempts[id] = prior
		}
	}
	epoch := run.LeaseEpoch + 1
	attempt := Attempt{ID: attemptID, TenantID: tenantID, RunID: runID, LeaseEpoch: epoch, State: "LEASED"}
	r.attempts[attemptID] = attempt
	run.State, run.Version, run.LeaseEpoch = "EXECUTING", run.Version+1, epoch
	r.runs[runID] = run
	return attempt, nil
}

func (r *Repository) CompleteAttempt(tenantID, attemptID string, epoch uint64, outcome string, at time.Time) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	attempt, ok := r.attempts[attemptID]
	if !ok || tenants.RequireScope(tenantID, attempt.TenantID) != nil {
		return ErrNotFound
	}
	run := r.runs[attempt.RunID]
	accepted := attempt.LeaseEpoch == epoch && run.LeaseEpoch == epoch && run.State == "EXECUTING"
	r.completions = append(r.completions, Completion{AttemptID: attemptID, Epoch: epoch, Outcome: outcome, Accepted: accepted, At: at.UTC()})
	if !accepted {
		attempt.State = "FENCED"
		r.attempts[attemptID] = attempt
		return ErrStaleCompletion
	}
	if outcome == "SUCCEEDED" {
		attempt.State, run.State = "COMPLETED", "COMPLETED"
	} else {
		attempt.State, run.State = "FAILED", "FAILED"
	}
	run.Version++
	r.attempts[attemptID], r.runs[run.ID] = attempt, run
	return nil
}

func (r *Repository) Run(tenantID, runID string) (Run, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	run, ok := r.runs[runID]
	if !ok || tenants.RequireScope(tenantID, run.TenantID) != nil {
		return Run{}, ErrNotFound
	}
	return run, nil
}

func (r *Repository) Completions() []Completion {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]Completion(nil), r.completions...)
}
