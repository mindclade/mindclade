package jobs

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

const (
	MinimumLeaseDuration = 5 * time.Second
	MaximumLeaseDuration = 15 * time.Minute
)

// LeaseCredentials are authenticated behavior inputs, not a competing wire
// model. The raw token is carried in transport metadata and is never persisted.
type LeaseCredentials struct {
	TenantID  string
	AttemptID string
	WorkerID  string
	Token     string
	Epoch     uint64
}

type AcquireLeaseCommand struct {
	TenantID  string
	RunID     string
	AttemptID string
	WorkerID  string
	Token     string
	Duration  time.Duration
	Now       time.Time
}

type RenewLeaseCommand struct {
	Credentials             LeaseCredentials
	ExpectedResourceVersion int64
	Duration                time.Duration
	Now                     time.Time
}

func NewLeaseToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("generate lease token: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

func LeaseTokenDigest(token string) (string, error) {
	if len(token) < 32 || strings.TrimSpace(token) != token {
		return "", ErrInvalidLeaseToken
	}
	digest := sha256.Sum256([]byte(token))
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func equalLeaseTokenDigest(persisted, presented string) bool {
	return len(persisted) == len(presented) && subtle.ConstantTimeCompare([]byte(persisted), []byte(presented)) == 1
}

func validateLeaseDuration(value time.Duration) error {
	if value < MinimumLeaseDuration || value > MaximumLeaseDuration {
		return fmt.Errorf("%w: duration must be between %s and %s", ErrInvalidLease, MinimumLeaseDuration, MaximumLeaseDuration)
	}
	return nil
}

// CompleteAttemptSQL locks the attempt and run, records every completion
// observation, and advances state only for the current unexpired token-bound
// lease. The generated Attempt remains the authoritative update value.
func (r SQLRepository) CompleteAttemptSQL(
	ctx context.Context,
	credentials LeaseCredentials,
	attempt *jobv1.Attempt,
	expectedVersion int64,
	at time.Time,
) (*jobv1.Attempt, *jobv1.Run, error) {
	if attempt == nil || credentials.TenantID == "" || credentials.AttemptID == "" || credentials.WorkerID == "" || at.IsZero() {
		return nil, nil, ErrInvalidLease
	}
	if attempt.GetAttemptId() != credentials.AttemptID || attempt.GetTenantId() != credentials.TenantID || attempt.GetLeaseEpoch() != credentials.Epoch {
		return nil, nil, ErrInvalidLease
	}
	attemptOutcome, runOutcome, err := terminalOutcome(attempt.GetState())
	if err != nil {
		return nil, nil, err
	}
	presentedDigest, err := LeaseTokenDigest(credentials.Token)
	if err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, credentials.TenantID, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var (
		runID, storedWorkerID, storedTokenDigest, attemptStatus, runStatus string
		attemptEpoch, currentEpoch                                         uint64
		storedVersion                                                      int64
		leaseExpiresAt                                                     time.Time
	)
	err = tx.QueryRowContext(ctx, `
SELECT attempt.run_id, attempt.worker_id, attempt.lease_token_digest,
       attempt.lease_epoch, attempt.version, attempt.lease_expires_at,
       attempt.status, run.lease_epoch, run.status
FROM attempts AS attempt
JOIN runs AS run ON run.tenant_id = attempt.tenant_id AND run.id = attempt.run_id
WHERE attempt.tenant_id = $1 AND attempt.id = $2
FOR UPDATE OF run, attempt`, credentials.TenantID, credentials.AttemptID).Scan(
		&runID, &storedWorkerID, &storedTokenDigest, &attemptEpoch, &storedVersion,
		&leaseExpiresAt, &attemptStatus, &currentEpoch, &runStatus,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	runState, err := runStateFromDatabase(runStatus)
	if err != nil {
		return nil, nil, err
	}
	tokenMatches := equalLeaseTokenDigest(storedTokenDigest, presentedDigest)
	ownerMatches := storedWorkerID == credentials.WorkerID
	epochMatches := attemptEpoch == credentials.Epoch && currentEpoch == credentials.Epoch
	versionMatches := storedVersion == expectedVersion
	unexpired := at.UTC().Before(leaseExpiresAt.UTC())
	active := attemptStatus == "LEASED" || attemptStatus == "ACTIVE"
	accepted := tokenMatches && ownerMatches && epochMatches && versionMatches && unexpired && active && runState == jobv1.RunState_RUN_STATE_EXECUTING
	if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_completion_history (tenant_id, attempt_id, worker_id, lease_epoch, lease_token_digest, accepted, outcome, recorded_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, credentials.TenantID, credentials.AttemptID, credentials.WorkerID, credentials.Epoch, presentedDigest, accepted, attemptOutcome, at.UTC()); err != nil {
		return nil, nil, err
	}
	if !accepted {
		rejection := ErrStaleCompletion
		switch {
		case !tokenMatches:
			rejection = ErrInvalidLeaseToken
		case !ownerMatches:
			rejection = ErrLeaseOwner
		case !epochMatches:
			rejection = ErrStaleCompletion
		case !versionMatches:
			rejection = ErrVersionConflict
		case !unexpired:
			rejection = ErrLeaseExpired
		}
		if tokenMatches && ownerMatches && (!epochMatches || !unexpired) && active {
			if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'FENCED', version = version + 1, completed_at = $3, updated_at = $3 WHERE tenant_id = $1 AND id = $2`, credentials.TenantID, credentials.AttemptID, at.UTC()); err != nil {
				return nil, nil, err
			}
		}
		if err = tx.Commit(); err != nil {
			return nil, nil, err
		}
		return nil, nil, rejection
	}
	errorID, err := platformdb.StoreErrorDetail(ctx, tx, credentials.TenantID, attempt.GetError())
	if err != nil {
		return nil, nil, err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM attempt_output_refs WHERE tenant_id = $1 AND attempt_id = $2`, credentials.TenantID, credentials.AttemptID); err != nil {
		return nil, nil, err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM run_output_refs WHERE tenant_id = $1 AND run_id = $2`, credentials.TenantID, runID); err != nil {
		return nil, nil, err
	}
	for ordinal, output := range attempt.GetOutputs() {
		refID, storeErr := platformdb.StoreArtifactRef(ctx, tx, credentials.TenantID, output)
		if storeErr != nil {
			return nil, nil, storeErr
		}
		if !refID.Valid {
			return nil, nil, errors.New("attempt output cannot be nil")
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_output_refs (tenant_id, attempt_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4)`, credentials.TenantID, credentials.AttemptID, ordinal, refID.Int64); err != nil {
			return nil, nil, err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs (tenant_id, run_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4)`, credentials.TenantID, runID, ordinal, refID.Int64); err != nil {
			return nil, nil, err
		}
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = $3, version = version + 1, error_detail_id = $4, completed_at = $5, updated_at = $5 WHERE tenant_id = $1 AND id = $2`, credentials.TenantID, credentials.AttemptID, attemptOutcome, errorID, at.UTC()); err != nil {
		return nil, nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = $3, version = version + 1, error_detail_id = $4, completed_at = $5, updated_at = $5 WHERE tenant_id = $1 AND id = $2 AND lease_epoch = $6`, credentials.TenantID, runID, runOutcome, errorID, at.UTC(), credentials.Epoch); err != nil {
		return nil, nil, err
	}
	acceptedAttempt, err := getAttemptTx(ctx, tx, credentials.TenantID, credentials.AttemptID)
	if err != nil {
		return nil, nil, err
	}
	acceptedRun, err := getRunTx(ctx, tx, credentials.TenantID, runID)
	if err != nil {
		return nil, nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return acceptedAttempt, acceptedRun, nil
}

func (r SQLRepository) CreateJobSQL(ctx context.Context, job *jobv1.Job) (*jobv1.Job, error) {
	if job == nil || job.GetJobId() == "" || job.GetTenantId() == "" || job.GetConfiguration() == nil {
		return nil, ErrNotFound
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, job.GetTenantId(), nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	inputRefID, err := platformdb.StoreArtifactRef(ctx, tx, job.GetTenantId(), job.GetInput())
	if err != nil {
		return nil, err
	}
	configurationRefID, err := platformdb.StoreArtifactRef(ctx, tx, job.GetTenantId(), job.GetConfiguration())
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	createdAt := timestampTime(job.GetCreatedAt())
	if createdAt.IsZero() {
		createdAt = now
	}
	if _, err = tx.ExecContext(ctx, `
INSERT INTO jobs (
  id, tenant_id, operation_id, project_id, desired_state, version,
  policy_digest, job_kind, input_ref_id, configuration_ref_id,
  configuration_digest, etag, created_at, updated_at
) VALUES ($1,$2,$3,$4,'ACCEPTED',1,$5,$6,$7,$8,$9,$10,$11,$12)`,
		job.GetJobId(), job.GetTenantId(), job.GetOperationId(), job.GetProjectId(),
		job.GetPolicyDigest(), job.GetJobKind(), inputRefID, configurationRefID,
		job.GetConfiguration().GetDigest(), job.GetEtag(), createdAt, now); err != nil {
		return nil, err
	}
	created, err := getJobTx(ctx, tx, job.GetTenantId(), job.GetJobId())
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return created, nil
}

func (r SQLRepository) GetJobSQL(ctx context.Context, tenantID, jobID string) (*jobv1.Job, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getJobTx(ctx, tx, tenantID, jobID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) CreateRunSQL(ctx context.Context, run *jobv1.Run) (*jobv1.Run, error) {
	if run == nil || run.GetRunId() == "" || run.GetJobId() == "" || run.GetTenantId() == "" {
		return nil, ErrNotFound
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, run.GetTenantId(), nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	job, err := getJobTx(ctx, tx, run.GetTenantId(), run.GetJobId())
	if err != nil {
		return nil, err
	}
	inputRefID, err := platformdb.StoreArtifactRef(ctx, tx, run.GetTenantId(), run.GetInput())
	if err != nil {
		return nil, err
	}
	configurationRefID, err := platformdb.StoreArtifactRef(ctx, tx, run.GetTenantId(), run.GetConfiguration())
	if err != nil {
		return nil, err
	}
	planRefID, err := platformdb.StoreArtifactRef(ctx, tx, run.GetTenantId(), run.GetPlan())
	if err != nil {
		return nil, err
	}
	errorDetailID, err := platformdb.StoreErrorDetail(ctx, tx, run.GetTenantId(), run.GetError())
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	createdAt := timestampTime(run.GetCreatedAt())
	if createdAt.IsZero() {
		createdAt = now
	}
	projectID := run.GetProjectId()
	if projectID == "" {
		projectID = job.GetProjectId()
	}
	if _, err = tx.ExecContext(ctx, `
INSERT INTO runs (
  id, tenant_id, project_id, job_id, input_ref_id, configuration_ref_id,
  plan_ref_id, status, version, lease_epoch, error_detail_id, etag,
  created_at, started_at, completed_at, updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,'READY',1,0,$8,$9,$10,$11,$12,$13)`,
		run.GetRunId(), run.GetTenantId(), projectID, run.GetJobId(), inputRefID,
		configurationRefID, planRefID, errorDetailID, run.GetEtag(), createdAt,
		nullTime(timestampTime(run.GetStartedAt())), nullTime(timestampTime(run.GetCompletedAt())), now); err != nil {
		return nil, err
	}
	for ordinal, output := range run.GetOutputs() {
		refID, storeErr := platformdb.StoreArtifactRef(ctx, tx, run.GetTenantId(), output)
		if storeErr != nil {
			return nil, storeErr
		}
		if !refID.Valid {
			return nil, errors.New("run output cannot be nil")
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs (tenant_id, run_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4)`, run.GetTenantId(), run.GetRunId(), ordinal, refID.Int64); err != nil {
			return nil, err
		}
	}
	created, err := getRunTx(ctx, tx, run.GetTenantId(), run.GetRunId())
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return created, nil
}

func (r SQLRepository) GetRunSQL(ctx context.Context, tenantID, runID string) (*jobv1.Run, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getRunTx(ctx, tx, tenantID, runID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) GetAttemptSQL(ctx context.Context, tenantID, attemptID string) (*jobv1.Attempt, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getAttemptTx(ctx, tx, tenantID, attemptID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) AcquireLeaseSQL(ctx context.Context, command AcquireLeaseCommand) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	if command.TenantID == "" || command.RunID == "" || command.AttemptID == "" || command.WorkerID == "" || command.Now.IsZero() {
		return nil, nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, nil, err
	}
	tokenDigest, err := LeaseTokenDigest(command.Token)
	if err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, command.TenantID, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var (
		jobID, projectID, status string
		currentEpoch             uint64
	)
	err = tx.QueryRowContext(ctx, `SELECT job_id, project_id, status, lease_epoch FROM runs WHERE tenant_id = $1 AND id = $2 FOR UPDATE`, command.TenantID, command.RunID).Scan(&jobID, &projectID, &status, &currentEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	runState, err := runStateFromDatabase(status)
	if err != nil {
		return nil, nil, err
	}
	if terminalRunState(runState) || runState == jobv1.RunState_RUN_STATE_CANCELLING {
		return nil, nil, ErrTerminalMutation
	}
	var activeAttemptID string
	var activeExpiry time.Time
	activeErr := tx.QueryRowContext(ctx, `SELECT id, lease_expires_at FROM attempts WHERE tenant_id = $1 AND run_id = $2 AND status IN ('LEASED','ACTIVE') ORDER BY lease_epoch DESC LIMIT 1 FOR UPDATE`, command.TenantID, command.RunID).Scan(&activeAttemptID, &activeExpiry)
	if activeErr == nil && command.Now.UTC().Before(activeExpiry.UTC()) {
		return nil, nil, ErrLeaseHeld
	}
	if activeErr != nil && !errors.Is(activeErr, sql.ErrNoRows) {
		return nil, nil, activeErr
	}
	if activeAttemptID != "" {
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'TIMED_OUT', version = version + 1, completed_at = $3, updated_at = $3 WHERE tenant_id = $1 AND id = $2 AND status IN ('LEASED','ACTIVE')`, command.TenantID, activeAttemptID, command.Now.UTC()); err != nil {
			return nil, nil, err
		}
	}
	epoch := currentEpoch + 1
	deadline := command.Now.UTC().Add(command.Duration)
	if _, err = tx.ExecContext(ctx, `
INSERT INTO attempts (
  id, tenant_id, project_id, job_id, run_id, worker_id, lease_epoch,
  lease_token_digest, lease_expires_at, last_heartbeat_at, status,
  version, created_at, leased_at, updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'LEASED',1,$10,$10,$10)`,
		command.AttemptID, command.TenantID, projectID, jobID, command.RunID,
		command.WorkerID, epoch, tokenDigest, deadline, command.Now.UTC()); err != nil {
		return nil, nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'EXECUTING', lease_epoch = $3, version = version + 1, started_at = COALESCE(started_at, $4), updated_at = $4 WHERE tenant_id = $1 AND id = $2`, command.TenantID, command.RunID, epoch, command.Now.UTC()); err != nil {
		return nil, nil, err
	}
	attempt, err := getAttemptTx(ctx, tx, command.TenantID, command.AttemptID)
	if err != nil {
		return nil, nil, err
	}
	fence := leaseFence(attempt, tokenDigest)
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return attempt, fence, nil
}

func (r SQLRepository) RenewLeaseSQL(ctx context.Context, command RenewLeaseCommand) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	return r.renewLeaseSQL(ctx, command, false)
}

func (r SQLRepository) HeartbeatLeaseSQL(ctx context.Context, command RenewLeaseCommand) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	return r.renewLeaseSQL(ctx, command, true)
}

func (r SQLRepository) renewLeaseSQL(ctx context.Context, command RenewLeaseCommand, heartbeat bool) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	if command.Now.IsZero() || command.Credentials.TenantID == "" || command.Credentials.AttemptID == "" || command.Credentials.WorkerID == "" {
		return nil, nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, nil, err
	}
	presentedDigest, err := LeaseTokenDigest(command.Credentials.Token)
	if err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, command.Credentials.TenantID, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var storedWorker, storedDigest, status string
	var attemptEpoch, currentEpoch uint64
	var version int64
	var expiresAt time.Time
	err = tx.QueryRowContext(ctx, `SELECT attempt.worker_id, attempt.lease_token_digest, attempt.lease_epoch, attempt.version, attempt.lease_expires_at, attempt.status, run.lease_epoch FROM attempts AS attempt JOIN runs AS run ON run.tenant_id = attempt.tenant_id AND run.id = attempt.run_id WHERE attempt.tenant_id = $1 AND attempt.id = $2 FOR UPDATE OF attempt, run`, command.Credentials.TenantID, command.Credentials.AttemptID).Scan(&storedWorker, &storedDigest, &attemptEpoch, &version, &expiresAt, &status, &currentEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	switch {
	case storedWorker != command.Credentials.WorkerID:
		return nil, nil, ErrLeaseOwner
	case !equalLeaseTokenDigest(storedDigest, presentedDigest):
		return nil, nil, ErrInvalidLeaseToken
	case attemptEpoch != command.Credentials.Epoch || currentEpoch != command.Credentials.Epoch:
		return nil, nil, ErrStaleCompletion
	case version != command.ExpectedResourceVersion:
		return nil, nil, ErrVersionConflict
	case !command.Now.UTC().Before(expiresAt.UTC()):
		return nil, nil, ErrLeaseExpired
	case status != "LEASED" && status != "ACTIVE":
		return nil, nil, ErrTerminalMutation
	}
	deadline := command.Now.UTC().Add(command.Duration)
	newStatus := status
	if heartbeat {
		newStatus = "ACTIVE"
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET lease_expires_at = $3, last_heartbeat_at = $4, status = $5, started_at = CASE WHEN $6 THEN COALESCE(started_at, $4) ELSE started_at END, version = version + 1, updated_at = $4 WHERE tenant_id = $1 AND id = $2`, command.Credentials.TenantID, command.Credentials.AttemptID, deadline, command.Now.UTC(), newStatus, heartbeat); err != nil {
		return nil, nil, err
	}
	attempt, err := getAttemptTx(ctx, tx, command.Credentials.TenantID, command.Credentials.AttemptID)
	if err != nil {
		return nil, nil, err
	}
	fence := leaseFence(attempt, storedDigest)
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return attempt, fence, nil
}

func (r SQLRepository) CancelAttemptSQL(ctx context.Context, credentials LeaseCredentials, expectedVersion int64, at time.Time) (*jobv1.Attempt, *jobv1.Run, error) {
	if at.IsZero() {
		return nil, nil, ErrInvalidLease
	}
	command := RenewLeaseCommand{Credentials: credentials, ExpectedResourceVersion: expectedVersion, Duration: MinimumLeaseDuration, Now: at}
	// Validate ownership, token, epoch, version, and expiry under the same lock
	// as cancellation; renewal itself is not committed.
	presentedDigest, err := LeaseTokenDigest(command.Credentials.Token)
	if err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, credentials.TenantID, nil)
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var runID, workerID, tokenDigest, status string
	var epoch, currentEpoch uint64
	var version int64
	var expiresAt time.Time
	err = tx.QueryRowContext(ctx, `SELECT attempt.run_id, attempt.worker_id, attempt.lease_token_digest, attempt.lease_epoch, attempt.version, attempt.lease_expires_at, attempt.status, run.lease_epoch FROM attempts AS attempt JOIN runs AS run ON run.tenant_id = attempt.tenant_id AND run.id = attempt.run_id WHERE attempt.tenant_id = $1 AND attempt.id = $2 FOR UPDATE OF attempt, run`, credentials.TenantID, credentials.AttemptID).Scan(&runID, &workerID, &tokenDigest, &epoch, &version, &expiresAt, &status, &currentEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil, ErrNotFound
	}
	if err != nil {
		return nil, nil, err
	}
	switch {
	case workerID != credentials.WorkerID:
		return nil, nil, ErrLeaseOwner
	case !equalLeaseTokenDigest(tokenDigest, presentedDigest):
		return nil, nil, ErrInvalidLeaseToken
	case epoch != credentials.Epoch || currentEpoch != credentials.Epoch:
		return nil, nil, ErrStaleCompletion
	case version != expectedVersion:
		return nil, nil, ErrVersionConflict
	case !at.UTC().Before(expiresAt.UTC()):
		return nil, nil, ErrLeaseExpired
	case status != "LEASED" && status != "ACTIVE":
		return nil, nil, ErrTerminalMutation
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'CANCELLED', version = version + 1, completed_at = $3, updated_at = $3 WHERE tenant_id = $1 AND id = $2`, credentials.TenantID, credentials.AttemptID, at.UTC()); err != nil {
		return nil, nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'CANCELLED', version = version + 1, completed_at = $3, updated_at = $3 WHERE tenant_id = $1 AND id = $2 AND lease_epoch = $4`, credentials.TenantID, runID, at.UTC(), credentials.Epoch); err != nil {
		return nil, nil, err
	}
	attempt, err := getAttemptTx(ctx, tx, credentials.TenantID, credentials.AttemptID)
	if err != nil {
		return nil, nil, err
	}
	run, err := getRunTx(ctx, tx, credentials.TenantID, runID)
	if err != nil {
		return nil, nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return attempt, run, nil
}

func (r SQLRepository) ExpireLeasesSQL(ctx context.Context, tenantID string, at time.Time, limit int) ([]*jobv1.Attempt, error) {
	if at.IsZero() || limit < 1 || limit > 1000 {
		return nil, ErrInvalidLease
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	rows, err := tx.QueryContext(ctx, `SELECT id, run_id, lease_epoch FROM attempts WHERE tenant_id = $1 AND status IN ('LEASED','ACTIVE') AND lease_expires_at <= $2 ORDER BY lease_expires_at, id FOR UPDATE SKIP LOCKED LIMIT $3`, tenantID, at.UTC(), limit)
	if err != nil {
		return nil, err
	}
	type expired struct {
		attemptID, runID string
		epoch            uint64
	}
	var due []expired
	for rows.Next() {
		var value expired
		if err = rows.Scan(&value.attemptID, &value.runID, &value.epoch); err != nil {
			_ = rows.Close()
			return nil, err
		}
		due = append(due, value)
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err = rows.Close(); err != nil {
		return nil, err
	}
	result := make([]*jobv1.Attempt, 0, len(due))
	for _, value := range due {
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'TIMED_OUT', version = version + 1, completed_at = $3, updated_at = $3 WHERE tenant_id = $1 AND id = $2`, tenantID, value.attemptID, at.UTC()); err != nil {
			return nil, err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'READY', version = version + 1, updated_at = $4 WHERE tenant_id = $1 AND id = $2 AND lease_epoch = $3 AND status = 'EXECUTING'`, tenantID, value.runID, value.epoch, at.UTC()); err != nil {
			return nil, err
		}
		attempt, loadErr := getAttemptTx(ctx, tx, tenantID, value.attemptID)
		if loadErr != nil {
			return nil, loadErr
		}
		result = append(result, attempt)
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return result, nil
}

var (
	ErrNotFound          = errors.New("job resource not found")
	ErrStaleCompletion   = errors.New("stale attempt completion retained")
	ErrTerminalMutation  = errors.New("terminal resource cannot advance")
	ErrInvalidOutcome    = errors.New("attempt completion requires a terminal outcome")
	ErrInvalidLease      = errors.New("invalid attempt lease")
	ErrInvalidLeaseToken = errors.New("invalid attempt lease token")
	ErrLeaseHeld         = errors.New("run already has an unexpired lease")
	ErrLeaseExpired      = errors.New("attempt lease expired")
	ErrLeaseOwner        = errors.New("attempt lease belongs to another worker")
	ErrVersionConflict   = errors.New("attempt resource version conflict")
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
	leaseTokenDigest                                       string
	leaseEpoch                                             uint64
	state                                                  jobv1.AttemptState
	leaseExpiresAt, lastHeartbeatAt                        time.Time
	leasedAt, startedAt, completedAt                       time.Time
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

type sqlRowScanner interface{ Scan(...any) error }

type jobSQLRow struct {
	row                     jobRow
	inputRefID, configRefID sql.NullInt64
}

type runSQLRow struct {
	row                                runRow
	inputRefID, configRefID, planRefID sql.NullInt64
	errorDetailID                      sql.NullInt64
	startedAt, completedAt             sql.NullTime
}

type attemptSQLRow struct {
	row           attemptRow
	errorDetailID sql.NullInt64
	startedAt     sql.NullTime
	completedAt   sql.NullTime
}

func scanJobSQL(scanner sqlRowScanner) (jobSQLRow, error) {
	var value jobSQLRow
	var state string
	err := scanner.Scan(
		&value.row.jobID, &value.row.operationID, &value.row.tenantID,
		&value.row.projectID, &state, &value.row.resourceVersion,
		&value.row.policyDigest, &value.row.jobKind, &value.inputRefID,
		&value.configRefID, &value.row.createdAt, &value.row.updatedAt,
		&value.row.etag,
	)
	if err != nil {
		return jobSQLRow{}, err
	}
	value.row.state, err = jobStateFromDatabase(state)
	return value, err
}

func scanRunSQL(scanner sqlRowScanner) (runSQLRow, error) {
	var value runSQLRow
	var state string
	err := scanner.Scan(
		&value.row.runID, &value.row.jobID, &value.row.tenantID,
		&value.row.projectID, &value.inputRefID, &value.configRefID,
		&value.planRefID, &state, &value.row.resourceVersion,
		&value.row.leaseEpoch, &value.errorDetailID, &value.row.etag,
		&value.row.createdAt, &value.startedAt, &value.completedAt,
	)
	if err != nil {
		return runSQLRow{}, err
	}
	value.row.state, err = runStateFromDatabase(state)
	if value.startedAt.Valid {
		value.row.startedAt = value.startedAt.Time.UTC()
	}
	if value.completedAt.Valid {
		value.row.completedAt = value.completedAt.Time.UTC()
	}
	return value, err
}

func scanAttemptSQL(scanner sqlRowScanner) (attemptSQLRow, error) {
	var value attemptSQLRow
	var state string
	err := scanner.Scan(
		&value.row.attemptID, &value.row.runID, &value.row.tenantID,
		&value.row.projectID, &value.row.jobID, &value.row.workerID,
		&value.row.leaseEpoch, &value.row.leaseTokenDigest,
		&value.row.leaseExpiresAt, &value.row.lastHeartbeatAt, &state,
		&value.row.resourceVersion, &value.errorDetailID, &value.row.leasedAt,
		&value.startedAt, &value.completedAt,
	)
	if err != nil {
		return attemptSQLRow{}, err
	}
	value.row.state, err = attemptStateFromDatabase(state)
	if value.startedAt.Valid {
		value.row.startedAt = value.startedAt.Time.UTC()
	}
	if value.completedAt.Valid {
		value.row.completedAt = value.completedAt.Time.UTC()
	}
	return value, err
}

func getJobTx(ctx context.Context, tx *sql.Tx, tenantID, jobID string) (*jobv1.Job, error) {
	value, err := scanJobSQL(tx.QueryRowContext(ctx, `SELECT id, operation_id, tenant_id, project_id, desired_state, version, policy_digest, job_kind, input_ref_id, configuration_ref_id, created_at, updated_at, etag FROM jobs WHERE tenant_id = $1 AND id = $2`, tenantID, jobID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value.row.input, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, value.inputRefID)
	if err != nil {
		return nil, err
	}
	value.row.configuration, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, value.configRefID)
	if err != nil {
		return nil, err
	}
	return jobRowToProto(value.row), nil
}

func getRunTx(ctx context.Context, tx *sql.Tx, tenantID, runID string) (*jobv1.Run, error) {
	value, err := scanRunSQL(tx.QueryRowContext(ctx, `SELECT id, job_id, tenant_id, project_id, input_ref_id, configuration_ref_id, plan_ref_id, status, version, lease_epoch, error_detail_id, etag, created_at, started_at, completed_at FROM runs WHERE tenant_id = $1 AND id = $2`, tenantID, runID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value.row.input, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, value.inputRefID)
	if err != nil {
		return nil, err
	}
	value.row.configuration, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, value.configRefID)
	if err != nil {
		return nil, err
	}
	value.row.plan, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, value.planRefID)
	if err != nil {
		return nil, err
	}
	value.row.error, err = platformdb.LoadErrorDetail(ctx, tx, tenantID, value.errorDetailID)
	if err != nil {
		return nil, err
	}
	value.row.outputs, err = loadOutputRefs(ctx, tx, tenantID, "run_output_refs", "run_id", runID)
	if err != nil {
		return nil, err
	}
	return runRowToProto(value.row), nil
}

func getAttemptTx(ctx context.Context, tx *sql.Tx, tenantID, attemptID string) (*jobv1.Attempt, error) {
	value, err := scanAttemptSQL(tx.QueryRowContext(ctx, `SELECT id, run_id, tenant_id, project_id, job_id, worker_id, lease_epoch, lease_token_digest, lease_expires_at, last_heartbeat_at, status, version, error_detail_id, leased_at, started_at, completed_at FROM attempts WHERE tenant_id = $1 AND id = $2`, tenantID, attemptID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value.row.error, err = platformdb.LoadErrorDetail(ctx, tx, tenantID, value.errorDetailID)
	if err != nil {
		return nil, err
	}
	value.row.outputs, err = loadOutputRefs(ctx, tx, tenantID, "attempt_output_refs", "attempt_id", attemptID)
	if err != nil {
		return nil, err
	}
	return attemptRowToProto(value.row), nil
}

func loadOutputRefs(ctx context.Context, tx *sql.Tx, tenantID, table, ownerColumn, ownerID string) ([]*artifactv1.ArtifactRef, error) {
	query := ""
	switch {
	case table == "run_output_refs" && ownerColumn == "run_id":
		query = `SELECT artifact_ref_id FROM run_output_refs WHERE tenant_id = $1 AND run_id = $2 ORDER BY ordinal`
	case table == "attempt_output_refs" && ownerColumn == "attempt_id":
		query = `SELECT artifact_ref_id FROM attempt_output_refs WHERE tenant_id = $1 AND attempt_id = $2 ORDER BY ordinal`
	default:
		return nil, errors.New("unsupported output reference owner")
	}
	rows, err := tx.QueryContext(ctx, query, tenantID, ownerID)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = rows.Close()
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err = rows.Close(); err != nil {
		return nil, err
	}
	result := make([]*artifactv1.ArtifactRef, 0, len(ids))
	for _, id := range ids {
		ref, loadErr := platformdb.LoadArtifactRef(ctx, tx, tenantID, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		result = append(result, ref)
	}
	return result, nil
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

func (r *Repository) AcquireLease(command AcquireLeaseCommand) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	if command.TenantID == "" || command.RunID == "" || command.AttemptID == "" || command.WorkerID == "" || command.Now.IsZero() {
		return nil, nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, nil, err
	}
	tokenDigest, err := LeaseTokenDigest(command.Token)
	if err != nil {
		return nil, nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	run, ok := r.runs[command.RunID]
	if !ok || tenants.RequireScope(command.TenantID, run.tenantID) != nil {
		return nil, nil, ErrNotFound
	}
	if terminalRunState(run.state) || run.state == jobv1.RunState_RUN_STATE_CANCELLING {
		return nil, nil, ErrTerminalMutation
	}
	now := command.Now.UTC()
	for id, prior := range r.attempts {
		if prior.runID != command.RunID || terminalAttemptState(prior.state) {
			continue
		}
		if now.Before(prior.leaseExpiresAt) {
			return nil, nil, ErrLeaseHeld
		}
		prior.state = jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT
		prior.completedAt = now
		prior.resourceVersion++
		r.attempts[id] = prior
	}
	epoch := run.leaseEpoch + 1
	attempt := attemptRow{
		attemptID:        command.AttemptID,
		tenantID:         command.TenantID,
		projectID:        run.projectID,
		jobID:            run.jobID,
		runID:            command.RunID,
		workerID:         command.WorkerID,
		leaseTokenDigest: tokenDigest,
		leaseEpoch:       epoch,
		state:            jobv1.AttemptState_ATTEMPT_STATE_LEASED,
		leaseExpiresAt:   now.Add(command.Duration),
		lastHeartbeatAt:  now,
		leasedAt:         now,
		resourceVersion:  1,
	}
	r.attempts[command.AttemptID] = attempt
	run.state = jobv1.RunState_RUN_STATE_EXECUTING
	run.resourceVersion++
	run.leaseEpoch = epoch
	if run.startedAt.IsZero() {
		run.startedAt = now
	}
	r.runs[command.RunID] = run
	value := attemptRowToProto(attempt)
	return value, leaseFence(value, tokenDigest), nil
}

func (r *Repository) RenewLease(command RenewLeaseCommand, heartbeat bool) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	if command.Now.IsZero() {
		return nil, nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, nil, err
	}
	presentedDigest, err := LeaseTokenDigest(command.Credentials.Token)
	if err != nil {
		return nil, nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	attempt, ok := r.attempts[command.Credentials.AttemptID]
	if !ok || tenants.RequireScope(command.Credentials.TenantID, attempt.tenantID) != nil {
		return nil, nil, ErrNotFound
	}
	run := r.runs[attempt.runID]
	switch {
	case attempt.workerID != command.Credentials.WorkerID:
		return nil, nil, ErrLeaseOwner
	case !equalLeaseTokenDigest(attempt.leaseTokenDigest, presentedDigest):
		return nil, nil, ErrInvalidLeaseToken
	case attempt.leaseEpoch != command.Credentials.Epoch || run.leaseEpoch != command.Credentials.Epoch:
		return nil, nil, ErrStaleCompletion
	case attempt.resourceVersion != command.ExpectedResourceVersion:
		return nil, nil, ErrVersionConflict
	case !command.Now.UTC().Before(attempt.leaseExpiresAt):
		return nil, nil, ErrLeaseExpired
	case terminalAttemptState(attempt.state):
		return nil, nil, ErrTerminalMutation
	}
	attempt.leaseExpiresAt = command.Now.UTC().Add(command.Duration)
	attempt.lastHeartbeatAt = command.Now.UTC()
	attempt.resourceVersion++
	if heartbeat {
		attempt.state = jobv1.AttemptState_ATTEMPT_STATE_RUNNING
		if attempt.startedAt.IsZero() {
			attempt.startedAt = command.Now.UTC()
		}
	}
	r.attempts[attempt.attemptID] = attempt
	value := attemptRowToProto(attempt)
	return value, leaseFence(value, attempt.leaseTokenDigest), nil
}

func (r *Repository) CompleteAttempt(credentials LeaseCredentials, value *jobv1.Attempt, expectedVersion int64, at time.Time) error {
	if value == nil || value.GetAttemptId() != credentials.AttemptID || value.GetTenantId() != credentials.TenantID || value.GetLeaseEpoch() != credentials.Epoch || at.IsZero() {
		return ErrInvalidLease
	}
	if _, _, err := terminalOutcome(value.GetState()); err != nil {
		return err
	}
	presentedDigest, err := LeaseTokenDigest(credentials.Token)
	if err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	attempt, ok := r.attempts[credentials.AttemptID]
	if !ok || tenants.RequireScope(credentials.TenantID, attempt.tenantID) != nil {
		return ErrNotFound
	}
	run := r.runs[attempt.runID]
	tokenMatches := equalLeaseTokenDigest(attempt.leaseTokenDigest, presentedDigest)
	ownerMatches := attempt.workerID == credentials.WorkerID
	epochMatches := attempt.leaseEpoch == credentials.Epoch && run.leaseEpoch == credentials.Epoch
	versionMatches := attempt.resourceVersion == expectedVersion
	unexpired := at.UTC().Before(attempt.leaseExpiresAt)
	accepted := tokenMatches && ownerMatches && epochMatches && versionMatches && unexpired && !terminalAttemptState(attempt.state) && run.state == jobv1.RunState_RUN_STATE_EXECUTING
	r.completions = append(r.completions, completionRow{attemptID: credentials.AttemptID, epoch: credentials.Epoch, outcome: value.GetState(), accepted: accepted, at: at.UTC()})
	if !accepted {
		switch {
		case !tokenMatches:
			return ErrInvalidLeaseToken
		case !ownerMatches:
			return ErrLeaseOwner
		case !epochMatches:
			attempt.state = jobv1.AttemptState_ATTEMPT_STATE_FENCED
			attempt.completedAt = at.UTC()
			attempt.resourceVersion++
			r.attempts[attempt.attemptID] = attempt
			return ErrStaleCompletion
		case !versionMatches:
			return ErrVersionConflict
		case !unexpired:
			return ErrLeaseExpired
		default:
			attempt.state = jobv1.AttemptState_ATTEMPT_STATE_FENCED
			attempt.completedAt = at.UTC()
			attempt.resourceVersion++
			r.attempts[attempt.attemptID] = attempt
			return ErrStaleCompletion
		}
	}
	attempt.state = value.GetState()
	attempt.outputs = cloneArtifacts(value.GetOutputs())
	attempt.error = cloneError(value.GetError())
	attempt.completedAt = at.UTC()
	attempt.resourceVersion++
	switch value.GetState() {
	case jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED:
		run.state = jobv1.RunState_RUN_STATE_SUCCEEDED
	case jobv1.AttemptState_ATTEMPT_STATE_CANCELLED:
		run.state = jobv1.RunState_RUN_STATE_CANCELLED
	default:
		run.state = jobv1.RunState_RUN_STATE_FAILED
	}
	run.completedAt = at.UTC()
	run.outputs = cloneArtifacts(value.GetOutputs())
	run.error = cloneError(value.GetError())
	run.resourceVersion++
	r.attempts[attempt.attemptID] = attempt
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
	case jobv1.AttemptState_ATTEMPT_STATE_FAILED:
		return "FAILED", "FAILED", nil
	case jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT:
		return "TIMED_OUT", "FAILED", nil
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
	case "READY":
		return jobv1.RunState_RUN_STATE_READY, nil
	case "EXECUTING":
		return jobv1.RunState_RUN_STATE_EXECUTING, nil
	case "COMPLETED", "SUCCEEDED":
		return jobv1.RunState_RUN_STATE_SUCCEEDED, nil
	case "FAILED":
		return jobv1.RunState_RUN_STATE_FAILED, nil
	case "CANCELLING":
		return jobv1.RunState_RUN_STATE_CANCELLING, nil
	case "CANCELLED":
		return jobv1.RunState_RUN_STATE_CANCELLED, nil
	default:
		return jobv1.RunState_RUN_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted run state %q", value)
	}
}

func jobStateFromDatabase(value string) (jobv1.JobState, error) {
	states := map[string]jobv1.JobState{
		"ACCEPTED":   jobv1.JobState_JOB_STATE_ACCEPTED,
		"QUEUED":     jobv1.JobState_JOB_STATE_QUEUED,
		"RUNNING":    jobv1.JobState_JOB_STATE_RUNNING,
		"SUCCEEDED":  jobv1.JobState_JOB_STATE_SUCCEEDED,
		"FAILED":     jobv1.JobState_JOB_STATE_FAILED,
		"CANCELLING": jobv1.JobState_JOB_STATE_CANCELLING,
		"CANCELLED":  jobv1.JobState_JOB_STATE_CANCELLED,
	}
	state, ok := states[value]
	if !ok {
		return jobv1.JobState_JOB_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted job state %q", value)
	}
	return state, nil
}

func attemptStateFromDatabase(value string) (jobv1.AttemptState, error) {
	states := map[string]jobv1.AttemptState{
		"LEASED":    jobv1.AttemptState_ATTEMPT_STATE_LEASED,
		"ACTIVE":    jobv1.AttemptState_ATTEMPT_STATE_RUNNING,
		"COMPLETED": jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED,
		"FAILED":    jobv1.AttemptState_ATTEMPT_STATE_FAILED,
		"CANCELLED": jobv1.AttemptState_ATTEMPT_STATE_CANCELLED,
		"FENCED":    jobv1.AttemptState_ATTEMPT_STATE_FENCED,
		"TIMED_OUT": jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT,
	}
	state, ok := states[value]
	if !ok {
		return jobv1.AttemptState_ATTEMPT_STATE_UNSPECIFIED, fmt.Errorf("unknown persisted attempt state %q", value)
	}
	return state, nil
}

func jobToRow(value *jobv1.Job) jobRow {
	return jobRow{
		jobID: value.GetJobId(), operationID: value.GetOperationId(), tenantID: value.GetTenantId(), projectID: value.GetProjectId(),
		state: value.GetState(), resourceVersion: value.GetResourceVersion(), policyDigest: value.GetPolicyDigest(), jobKind: value.GetJobKind(),
		input: cloneArtifact(value.GetInput()), configuration: cloneArtifact(value.GetConfiguration()), createdAt: timestampTime(value.GetCreatedAt()),
		updatedAt: timestampTime(value.GetUpdatedAt()), etag: value.GetEtag(),
	}
}

func jobRowToProto(row jobRow) *jobv1.Job {
	return &jobv1.Job{
		JobId: row.jobID, OperationId: row.operationID, TenantId: row.tenantID,
		ProjectId: row.projectID, State: row.state, ResourceVersion: row.resourceVersion,
		PolicyDigest: row.policyDigest, JobKind: row.jobKind, Input: cloneArtifact(row.input),
		Configuration: cloneArtifact(row.configuration), CreatedAt: timeTimestamp(row.createdAt),
		UpdatedAt: timeTimestamp(row.updatedAt), Etag: row.etag,
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

func leaseFence(attempt *jobv1.Attempt, tokenDigest string) *jobv1.LeaseFence {
	if attempt == nil {
		return nil
	}
	return &jobv1.LeaseFence{
		JobId: attempt.GetJobId(), RunId: attempt.GetRunId(), AttemptId: attempt.GetAttemptId(),
		LeaseEpoch: attempt.GetLeaseEpoch(), Deadline: cloneTimestamp(attempt.GetLeaseExpiresAt()),
		TenantId: attempt.GetTenantId(), ProjectId: attempt.GetProjectId(), LeaseTokenDigest: tokenDigest,
	}
}

func cloneTimestamp(value *timestamppb.Timestamp) *timestamppb.Timestamp {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*timestamppb.Timestamp)
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

func nullTime(value time.Time) sql.NullTime {
	if value.IsZero() {
		return sql.NullTime{}
	}
	return sql.NullTime{Time: value.UTC(), Valid: true}
}
