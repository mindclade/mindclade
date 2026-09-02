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

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
	operationsapp "github.com/mindclade/mindclade/services/control_plane/internal/operations"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

type SQLRepository struct{ DB *sql.DB }

type JobCommandMetadata struct {
	TenantID, ProjectID, PrincipalID string
	IdempotencyKey, RequestDigest    string
	ObservedAt                       time.Time
}

type JobMutationResult struct {
	Job       *jobv1.Job
	Operation *jobv1.Operation
	Replay    bool
}

const (
	MinimumLeaseDuration = 5 * time.Second
	MaximumLeaseDuration = 15 * time.Minute
	// FeatureMaterializationJobKind and TransformExecutionJobKind are the
	// closed scheduler discriminators for the corresponding typed completion
	// commands. Exact matching prevents one domain payload from being attached
	// to another job kind.
	FeatureMaterializationJobKind = "feature.materialization"
	TransformExecutionJobKind     = "transform.execution"
	actionAcquireLease            = "run.acquire_lease"
	actionRenewLease              = "run.renew_lease"
	actionHeartbeat               = "run.heartbeat"
	actionCancelAttempt           = "run.cancel_attempt"
	actionExpireLeases            = "run.expire_leases"
	actionCommitAttempt           = "run.commit_attempt"
)

// LeaseCredentials are authenticated behavior inputs, not a competing wire
// model. The raw token is carried in transport metadata and is never persisted.
type LeaseCredentials struct {
	TenantID  string
	ProjectID string
	AttemptID string
	WorkerID  string
	Token     string
	Epoch     uint64
}

type AcquireLeaseCommand struct {
	TenantID   string
	RunID      string
	AttemptID  string
	WorkerID   string
	Token      string
	Duration   time.Duration
	Now        time.Time
	Command    RunCommandMetadata
	TokenKeyID string
}

type RenewLeaseCommand struct {
	Credentials             LeaseCredentials
	ExpectedResourceVersion int64
	Duration                time.Duration
	Now                     time.Time
	Command                 RunCommandMetadata
}

// RunCommandMetadata is authenticated behavior state used to serialize and
// replay successful RunService mutations. It is deliberately not a wire
// model; the authoritative command remains the generated protobuf request.
type RunCommandMetadata struct {
	TenantID, ProjectID, PrincipalID, WorkerID string
	Action, IdempotencyKey, RequestDigest      string
	RequestID, TraceID                         string
	CorrelationID, CausationID                 string
	ObservedAt                                 time.Time
}

type CancelAttemptCommand struct {
	Credentials             LeaseCredentials
	ExpectedResourceVersion int64
	Now                     time.Time
	Command                 RunCommandMetadata
}

type ExpireLeasesCommand struct {
	TenantID string
	Limit    int
	Now      time.Time
	Command  RunCommandMetadata
}

type CompleteAttemptCommand struct {
	Credentials             LeaseCredentials
	Attempt                 *jobv1.Attempt
	Fence                   *jobv1.LeaseFence
	FeatureMaterialization  *featurev1.CommitFeatureMaterializationCommand
	TransformExecution      *transformv1.CommitTransformExecutionCommand
	UpdateMask              []string
	ExpectedResourceVersion int64
	Now                     time.Time
	Command                 RunCommandMetadata
}

func validateDomainCompletionContext(value *commonv1.CommandContext, command RunCommandMetadata) bool {
	return value != nil && value.GetTenantId() == command.TenantID && value.GetProjectId() == command.ProjectID &&
		value.GetPrincipalId() == command.PrincipalID && value.GetRequestId() == command.RequestID &&
		value.GetIdempotencyKey() == command.IdempotencyKey && value.GetTraceId() == command.TraceID &&
		value.GetCorrelationId() == command.CorrelationID && value.GetCausationId() == command.CausationID
}

func validDomainResourceName(tenantID, projectID, collection, value string) bool {
	prefix := "tenants/" + tenantID + "/projects/" + projectID + "/" + collection + "/"
	if !strings.HasPrefix(value, prefix) {
		return false
	}
	leaf := strings.TrimPrefix(value, prefix)
	if len(leaf) == 0 || len(leaf) > 128 || !asciiAlphaNumeric(leaf[0]) {
		return false
	}
	for index := 1; index < len(leaf); index++ {
		if !asciiAlphaNumeric(leaf[index]) && !strings.ContainsRune("._~-", rune(leaf[index])) {
			return false
		}
	}
	return true
}

func asciiAlphaNumeric(value byte) bool {
	return value >= '0' && value <= '9' || value >= 'A' && value <= 'Z' || value >= 'a' && value <= 'z'
}

func validCompletionTimestamp(value *timestamppb.Timestamp, attempt *jobv1.Attempt, recordedAt time.Time) bool {
	if value == nil || value.CheckValid() != nil || attempt == nil || attempt.GetLeasedAt() == nil {
		return false
	}
	completedAt := value.AsTime().UTC()
	return !completedAt.Before(attempt.GetLeasedAt().AsTime().UTC()) && !completedAt.After(recordedAt.UTC())
}

func equalArtifacts(left, right []*artifactv1.ArtifactRef) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if !proto.Equal(left[index], right[index]) {
			return false
		}
	}
	return true
}

func validCompletionArtifacts(receipt *artifactv1.ArtifactRef, outputs []*artifactv1.ArtifactRef, failure *commonv1.ErrorDetail, attempt *jobv1.Attempt) bool {
	if attempt == nil || !validArtifactReference(receipt, true) || len(outputs) > 256 || !equalArtifacts(outputs, attempt.GetOutputs()) || !proto.Equal(failure, attempt.GetError()) {
		return false
	}
	if attempt.GetState() == jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED && len(outputs) == 0 {
		return false
	}
	for _, output := range outputs {
		if !validArtifactReference(output, true) {
			return false
		}
	}
	return failure == nil || failure.GetCode() != commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED
}

func featureClassificationMatches(state jobv1.AttemptState, classification featurev1.FeatureMaterializationTerminalClassification) bool {
	switch classification {
	case featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_SUCCEEDED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	case featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_CANCELLED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_CANCELLED
	case featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_DEADLINE_EXCEEDED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT
	case featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_INVALID_PLAN,
		featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_POLICY_DENIED,
		featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_DETERMINISM_VIOLATION,
		featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_EXECUTION_FAILED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_FAILED
	case featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_UNSPECIFIED,
		featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_STALE_FENCE:
		return false
	default:
		return false
	}
}

func transformClassificationMatches(state jobv1.AttemptState, classification transformv1.TransformExecutionTerminalClassification) bool {
	switch classification {
	case transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SUCCEEDED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	case transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_CANCELLED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_CANCELLED
	case transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_DEADLINE_EXCEEDED:
		return state == jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT
	case transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_INVALID_INPUT,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SCHEMA_MISMATCH,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SEMANTIC_VALIDATION_FAILED,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_POLICY_DENIED,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_RESOURCE_EXHAUSTED,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_TRANSIENT_IO,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_IMPLEMENTATION_FAILURE,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_DETERMINISM_VIOLATION,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_CARDINALITY_VIOLATION,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_ORDERING_VIOLATION,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_LINEAGE_VIOLATION:
		return state == jobv1.AttemptState_ATTEMPT_STATE_FAILED
	case transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_UNSPECIFIED,
		transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_STALE_FENCE:
		return false
	default:
		return false
	}
}

func validateDomainCompletion(command CompleteAttemptCommand, jobKind string, attempt *jobv1.Attempt) error {
	feature, transform := command.FeatureMaterialization, command.TransformExecution
	if feature != nil && transform != nil {
		return ErrInvalidOutcome
	}
	switch jobKind {
	case FeatureMaterializationJobKind:
		if feature == nil || transform != nil || !validateDomainCompletionContext(feature.GetContext(), command.Command) ||
			!proto.Equal(feature.GetFence(), command.Fence) || !validDomainResourceName(command.Credentials.TenantID, command.Credentials.ProjectID, "featureMaterializations", feature.GetMaterializationName()) ||
			!validCompletionTimestamp(feature.GetCompletedAt(), attempt, command.Now) || !featureClassificationMatches(attempt.GetState(), feature.GetClassification()) ||
			!validCompletionArtifacts(feature.GetReceipt(), feature.GetOutputRefs(), feature.GetError(), attempt) {
			return ErrInvalidOutcome
		}
	case TransformExecutionJobKind:
		if transform == nil || feature != nil || !validateDomainCompletionContext(transform.GetContext(), command.Command) ||
			!proto.Equal(transform.GetFence(), command.Fence) || !validDomainResourceName(command.Credentials.TenantID, command.Credentials.ProjectID, "transformExecutions", transform.GetExecutionName()) ||
			!validCompletionTimestamp(transform.GetCompletedAt(), attempt, command.Now) || !transformClassificationMatches(attempt.GetState(), transform.GetClassification()) ||
			!validCompletionArtifacts(transform.GetReceipt(), transform.GetOutputRefs(), transform.GetError(), attempt) || !validArtifactReference(transform.GetLineageMap(), true) {
			return ErrInvalidOutcome
		}
	default:
		if feature != nil || transform != nil {
			return ErrInvalidOutcome
		}
	}
	return nil
}

type runCommandReceipt struct {
	commandKey, requestDigest, action, projectID, principalID, workerID string
	runID, attemptID, tokenKeyID                                        sql.NullString
	observedAt                                                          time.Time
}

type LeaseMutationResult struct {
	Attempt    *jobv1.Attempt
	Fence      *jobv1.LeaseFence
	TokenKeyID string
	Replay     bool
}

type AttemptMutationResult struct {
	Attempt *jobv1.Attempt
	Run     *jobv1.Run
	Replay  bool
}

type ExpireLeasesResult struct {
	Attempts   []*jobv1.Attempt
	ObservedAt time.Time
	Replay     bool
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

func renewedLeaseDeadline(now time.Time, duration time.Duration, current time.Time) time.Time {
	candidate := now.UTC().Add(duration)
	if candidate.Before(current.UTC()) {
		return current.UTC()
	}
	return candidate
}

func validateRunCommandMetadata(value RunCommandMetadata, tenantID, action string) error {
	if value.TenantID != tenantID || value.ProjectID == "" || value.PrincipalID == "" || value.WorkerID == "" ||
		value.Action != action || value.IdempotencyKey == "" || value.ObservedAt.IsZero() ||
		len(value.IdempotencyKey) > 255 || strings.TrimSpace(value.IdempotencyKey) != value.IdempotencyKey ||
		strings.ContainsAny(value.IdempotencyKey, "\x00\r\n") || len(value.RequestDigest) != 71 ||
		!strings.HasPrefix(value.RequestDigest, "sha256:") {
		return ErrInvalidLease
	}
	if _, err := hex.DecodeString(strings.TrimPrefix(value.RequestDigest, "sha256:")); err != nil {
		return ErrInvalidLease
	}
	return nil
}

func runCommandKey(action, key string) string { return action + ":" + key }

func checkRunCommand(ctx context.Context, tx *sql.Tx, command RunCommandMetadata) (runCommandReceipt, bool, error) {
	key := runCommandKey(command.Action, command.IdempotencyKey)
	lockKey := fmt.Sprintf("%d:%s:%d:%s:%s", len(command.TenantID), command.TenantID, len(command.ProjectID), command.ProjectID, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return runCommandReceipt{}, false, err
	}
	var receipt runCommandReceipt
	err := tx.QueryRowContext(ctx, `SELECT command_key,request_hash,action,project_id,principal_id,worker_id,run_id,attempt_id,token_key_id,observed_at FROM run_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND command_key=$3`, command.TenantID, command.ProjectID, key).Scan(
		&receipt.commandKey, &receipt.requestDigest, &receipt.action, &receipt.projectID,
		&receipt.principalID, &receipt.workerID, &receipt.runID, &receipt.attemptID,
		&receipt.tokenKeyID, &receipt.observedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return runCommandReceipt{}, false, nil
	}
	if err != nil {
		return runCommandReceipt{}, false, err
	}
	if subtle.ConstantTimeCompare([]byte(receipt.requestDigest), []byte(command.RequestDigest)) != 1 ||
		receipt.action != command.Action || receipt.projectID != command.ProjectID ||
		receipt.principalID != command.PrincipalID || receipt.workerID != command.WorkerID {
		return runCommandReceipt{}, false, ErrIdempotencyConflict
	}
	return receipt, true, nil
}

func recordRunCommand(ctx context.Context, tx *sql.Tx, command RunCommandMetadata, runID, attemptID, tokenKeyID string) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO run_command_receipts (tenant_id,command_key,request_hash,action,project_id,principal_id,worker_id,run_id,attempt_id,token_key_id,observed_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,NULLIF($8,''),NULLIF($9,''),$10,$11,$11)`,
		command.TenantID, runCommandKey(command.Action, command.IdempotencyKey), command.RequestDigest,
		command.Action, command.ProjectID, command.PrincipalID, command.WorkerID,
		runID, attemptID, tokenKeyID, command.ObservedAt.UTC())
	return err
}

func getAttemptFenceTx(ctx context.Context, tx *sql.Tx, tenantID, projectID, attemptID string) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	attempt, err := getAttemptTx(ctx, tx, tenantID, projectID, attemptID)
	if err != nil {
		return nil, nil, err
	}
	var digest string
	if err = tx.QueryRowContext(ctx, `SELECT lease_token_digest FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, tenantID, projectID, attemptID).Scan(&digest); err != nil {
		return nil, nil, err
	}
	return attempt, leaseFence(attempt, digest), nil
}

func loadReceiptAttempts(ctx context.Context, tx *sql.Tx, tenantID, projectID, commandKey string) ([]*jobv1.Attempt, error) {
	rows, err := tx.QueryContext(ctx, `SELECT attempt_id FROM run_command_receipt_attempts WHERE tenant_id=$1 AND project_id=$2 AND command_key=$3 ORDER BY ordinal`, tenantID, projectID, commandKey)
	if err != nil {
		return nil, err
	}
	defer func() { _ = platformdb.CloseRows(rows) }()
	var ids []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	result := make([]*jobv1.Attempt, 0, len(ids))
	for _, id := range ids {
		attempt, loadErr := getAttemptTx(ctx, tx, tenantID, projectID, id)
		if loadErr != nil {
			return nil, loadErr
		}
		result = append(result, attempt)
	}
	return result, nil
}

func applyAttemptCompletionMask(stored, requested *jobv1.Attempt, paths []string, expectedVersion int64) (*jobv1.Attempt, error) {
	if stored == nil || requested == nil || len(paths) == 0 || expectedVersion < 1 ||
		requested.GetAttemptId() != stored.GetAttemptId() || requested.GetRunId() != stored.GetRunId() ||
		requested.GetJobId() != stored.GetJobId() || requested.GetTenantId() != stored.GetTenantId() ||
		requested.GetProjectId() != stored.GetProjectId() || requested.GetWorkerId() != stored.GetWorkerId() ||
		requested.GetLeaseEpoch() != stored.GetLeaseEpoch() || requested.GetResourceVersion() != expectedVersion {
		return nil, ErrInvalidOutcome
	}
	result := proto.Clone(stored).(*jobv1.Attempt)
	seen := make(map[string]struct{}, len(paths))
	for _, path := range paths {
		if _, exists := seen[path]; exists {
			return nil, ErrInvalidOutcome
		}
		seen[path] = struct{}{}
		switch path {
		case "state":
			result.State = requested.GetState()
		case "outputs":
			result.Outputs = cloneArtifacts(requested.GetOutputs())
		case "error":
			result.Error = cloneError(requested.GetError())
		default:
			return nil, ErrInvalidOutcome
		}
	}
	if _, ok := seen["state"]; !ok {
		return nil, ErrInvalidOutcome
	}
	if _, _, err := terminalOutcome(result.GetState()); err != nil {
		return nil, err
	}
	if result.GetState() == jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED && result.GetError() != nil {
		return nil, ErrInvalidOutcome
	}
	return result, nil
}

// CompleteAttemptSQL locks the attempt and run, records every completion
// observation, and advances state only for the current unexpired token-bound
// lease. The generated Attempt remains the authoritative update value.
func (r SQLRepository) CompleteAttemptSQL(
	ctx context.Context,
	command CompleteAttemptCommand,
) (*AttemptMutationResult, error) {
	credentials, requested, expectedVersion, at := command.Credentials, command.Attempt, command.ExpectedResourceVersion, command.Now
	if requested == nil || credentials.TenantID == "" || credentials.ProjectID == "" || credentials.AttemptID == "" || credentials.WorkerID == "" || at.IsZero() {
		return nil, ErrInvalidLease
	}
	if requested.GetAttemptId() != credentials.AttemptID || requested.GetTenantId() != credentials.TenantID || requested.GetProjectId() != credentials.ProjectID || requested.GetLeaseEpoch() != credentials.Epoch ||
		validateRunCommandMetadata(command.Command, credentials.TenantID, actionCommitAttempt) != nil || command.Command.ProjectID != credentials.ProjectID || command.Command.WorkerID != credentials.WorkerID {
		return nil, ErrInvalidLease
	}
	presentedDigest, err := LeaseTokenDigest(credentials.Token)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, credentials.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkRunCommand(ctx, tx, command.Command)
	if err != nil {
		return nil, err
	}
	if replay {
		if !receipt.attemptID.Valid || receipt.attemptID.String != credentials.AttemptID || !receipt.runID.Valid {
			return nil, ErrIdempotencyConflict
		}
		attempt, loadErr := getAttemptTx(ctx, tx, credentials.TenantID, credentials.ProjectID, receipt.attemptID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		run, loadErr := getRunTx(ctx, tx, credentials.TenantID, credentials.ProjectID, receipt.runID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, commitErr
		}
		return &AttemptMutationResult{Attempt: attempt, Run: run, Replay: true}, nil
	}
	var runID string
	if err = tx.QueryRowContext(ctx, `SELECT run_id FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID).Scan(&runID); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	var (
		storedWorkerID, storedTokenDigest, attemptStatus, runStatus string
		attemptEpoch, currentEpoch                                  uint64
		storedVersion                                               int64
		leaseExpiresAt                                              time.Time
	)
	var projectID string
	err = tx.QueryRowContext(ctx, `SELECT lease_epoch,status,project_id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, credentials.TenantID, credentials.ProjectID, runID).Scan(&currentEpoch, &runStatus, &projectID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if projectID != command.Command.ProjectID {
		return nil, ErrNotFound
	}
	err = tx.QueryRowContext(ctx, `SELECT worker_id,lease_token_digest,lease_epoch,version,lease_expires_at,status FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 FOR UPDATE`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, runID).Scan(&storedWorkerID, &storedTokenDigest, &attemptEpoch, &storedVersion, &leaseExpiresAt, &attemptStatus)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	storedAttempt, err := getAttemptTx(ctx, tx, credentials.TenantID, credentials.ProjectID, credentials.AttemptID)
	if err != nil {
		return nil, err
	}
	attempt, err := applyAttemptCompletionMask(storedAttempt, requested, command.UpdateMask, expectedVersion)
	if err != nil {
		return nil, err
	}
	var jobKind string
	if err = tx.QueryRowContext(ctx, `SELECT job_kind FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR SHARE`, credentials.TenantID, credentials.ProjectID, attempt.GetJobId()).Scan(&jobKind); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	if err = validateDomainCompletion(command, jobKind, attempt); err != nil {
		return nil, err
	}
	attemptOutcome, runOutcome, err := terminalOutcome(attempt.GetState())
	if err != nil {
		return nil, err
	}
	runState, err := runStateFromDatabase(runStatus)
	if err != nil {
		return nil, err
	}
	tokenMatches := equalLeaseTokenDigest(storedTokenDigest, presentedDigest)
	ownerMatches := storedWorkerID == credentials.WorkerID
	epochMatches := attemptEpoch == credentials.Epoch && currentEpoch == credentials.Epoch
	versionMatches := storedVersion == expectedVersion
	unexpired := at.UTC().Before(leaseExpiresAt.UTC())
	active := attemptStatus == "LEASED" || attemptStatus == "ACTIVE"
	runAccepts := runState == jobv1.RunState_RUN_STATE_EXECUTING || (runState == jobv1.RunState_RUN_STATE_CANCELLING && attempt.GetState() == jobv1.AttemptState_ATTEMPT_STATE_CANCELLED)
	accepted := tokenMatches && ownerMatches && epochMatches && versionMatches && unexpired && active && runAccepts
	if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_completion_history (tenant_id, project_id, attempt_id, worker_id, lease_epoch, lease_token_digest, accepted, outcome, recorded_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, credentials.WorkerID, credentials.Epoch, presentedDigest, accepted, attemptOutcome, at.UTC()); err != nil {
		return nil, err
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
			if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'FENCED', version = version + 1, completed_at = $4, updated_at = $4 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, at.UTC()); err != nil {
				return nil, err
			}
		}
		if err = tx.Commit(); err != nil {
			return nil, err
		}
		return nil, rejection
	}
	errorID, err := platformdb.StoreErrorDetail(ctx, tx, credentials.TenantID, attempt.GetError())
	if err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM attempt_output_refs WHERE tenant_id = $1 AND project_id=$2 AND attempt_id = $3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM run_output_refs WHERE tenant_id = $1 AND project_id=$2 AND run_id = $3`, credentials.TenantID, credentials.ProjectID, runID); err != nil {
		return nil, err
	}
	for ordinal, output := range attempt.GetOutputs() {
		refID, storeErr := platformdb.StoreArtifactRef(ctx, tx, credentials.TenantID, output)
		if storeErr != nil {
			return nil, storeErr
		}
		if !refID.Valid {
			return nil, errors.New("attempt output cannot be nil")
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_output_refs (tenant_id, project_id, attempt_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4,$5)`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, ordinal, refID.Int64); err != nil {
			return nil, err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs (tenant_id, project_id, run_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4,$5)`, credentials.TenantID, credentials.ProjectID, runID, ordinal, refID.Int64); err != nil {
			return nil, err
		}
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = $4, version = version + 1, error_detail_id = $5, completed_at = $6, updated_at = $6 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, attemptOutcome, errorID, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = $4, version = version + 1, error_detail_id = $5, completed_at = $6, updated_at = $6 WHERE tenant_id = $1 AND project_id=$2 AND id = $3 AND lease_epoch = $7`, credentials.TenantID, credentials.ProjectID, runID, runOutcome, errorID, at.UTC(), credentials.Epoch); err != nil {
		return nil, err
	}
	acceptedAttempt, err := getAttemptTx(ctx, tx, credentials.TenantID, credentials.ProjectID, credentials.AttemptID)
	if err != nil {
		return nil, err
	}
	acceptedRun, err := getRunTx(ctx, tx, credentials.TenantID, credentials.ProjectID, runID)
	if err != nil {
		return nil, err
	}
	completionFence := leaseFence(acceptedAttempt, presentedDigest)
	completionEvent, err := newAttemptCompletedEvent(acceptedAttempt, acceptedRun, completionFence, command.Command, at)
	if err != nil {
		return nil, err
	}
	if err = insertAttemptOutbox(ctx, tx, completionEvent, at); err != nil {
		return nil, err
	}
	var domainEvent *commonv1.EventEnvelope
	switch jobKind {
	case FeatureMaterializationJobKind:
		domainEvent, err = newFeatureMaterializationCompletedEvent(command.FeatureMaterialization, acceptedRun, completionFence, command.Command, at)
	case TransformExecutionJobKind:
		domainEvent, err = newTransformExecutionCompletedEvent(command.TransformExecution, acceptedRun, completionFence, command.Command, at)
	}
	if err != nil {
		return nil, err
	}
	if domainEvent != nil {
		if err = insertAttemptOutbox(ctx, tx, domainEvent, at); err != nil {
			return nil, err
		}
	}
	if err = recordRunCommand(ctx, tx, command.Command, runID, credentials.AttemptID, ""); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &AttemptMutationResult{Attempt: acceptedAttempt, Run: acceptedRun}, nil
}

func validateJobCommand(value JobCommandMetadata) error {
	if value.TenantID == "" || value.ProjectID == "" || value.PrincipalID == "" || value.IdempotencyKey == "" ||
		value.ObservedAt.IsZero() || len(value.IdempotencyKey) > 512 || strings.TrimSpace(value.IdempotencyKey) != value.IdempotencyKey ||
		strings.ContainsAny(value.IdempotencyKey, "\x00\r\n") || len(value.RequestDigest) != 71 ||
		!strings.HasPrefix(value.RequestDigest, "sha256:") {
		return ErrInvalidJobCommand
	}
	if _, err := hex.DecodeString(strings.TrimPrefix(value.RequestDigest, "sha256:")); err != nil {
		return ErrInvalidJobCommand
	}
	return nil
}

// RequestJobSQL commits Job, Operation, idempotency, audit, history, and
// JobRequested outbox state through the shared Operation acceptance boundary.
func (r SQLRepository) RequestJobSQL(ctx context.Context, job *jobv1.Job, operation *jobv1.Operation, command JobCommandMetadata) (*JobMutationResult, error) {
	if r.DB == nil || job == nil || operation == nil || validateJobCommand(command) != nil ||
		job.GetTenantId() != command.TenantID || job.GetProjectId() != command.ProjectID ||
		operation.GetTenantId() != command.TenantID || operation.GetProjectId() != command.ProjectID || operation.GetJobId() != job.GetJobId() {
		return nil, ErrInvalidJobCommand
	}
	accepted, replay, err := (operationsapp.SQLRepository{DB: r.DB}).CreateJobAndOperationSQL(
		ctx, cloneJob(job), proto.Clone(operation).(*jobv1.Operation), command.RequestDigest,
		command.IdempotencyKey, command.PrincipalID, command.ObservedAt.UTC(),
	)
	if err != nil {
		return nil, mapOperationError(err)
	}
	persisted, err := r.GetJobSQL(ctx, command.TenantID, command.ProjectID, accepted.GetJobId())
	if err != nil {
		return nil, err
	}
	return &JobMutationResult{Job: cloneJob(persisted), Operation: proto.Clone(accepted).(*jobv1.Operation), Replay: replay}, nil
}

// ListJobsSQL returns a stable keyset page from one repeatable-read snapshot.
func (r SQLRepository) ListJobsSQL(ctx context.Context, tenantID, projectID, after string, limit int) ([]*jobv1.Job, bool, time.Time, error) {
	if r.DB == nil || tenantID == "" || projectID == "" || limit < 1 || limit > 200 {
		return nil, false, time.Time{}, ErrInvalidJobCommand
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, false, time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, false, time.Time{}, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT id FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id>$3 ORDER BY id LIMIT $4`, tenantID, projectID, after, limit+1)
	if err != nil {
		return nil, false, time.Time{}, err
	}
	ids := make([]string, 0, limit+1)
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, false, time.Time{}, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, false, time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, false, time.Time{}, err
	}
	more := len(ids) > limit
	if more {
		ids = ids[:limit]
	}
	values := make([]*jobv1.Job, 0, len(ids))
	for _, id := range ids {
		value, loadErr := getJobTx(ctx, tx, tenantID, projectID, id)
		if loadErr != nil {
			return nil, false, time.Time{}, loadErr
		}
		values = append(values, cloneJob(value))
	}
	if err = tx.Commit(); err != nil {
		return nil, false, time.Time{}, err
	}
	return values, more, readAt.UTC(), nil
}

// CancelJobSQL records monotonic cancellation plus its Operation revision,
// idempotency receipt, audit evidence, and immutable audit event delivery.
func (r SQLRepository) CancelJobSQL(ctx context.Context, jobID, expectedETag, reason string, command JobCommandMetadata) (*JobMutationResult, error) {
	if r.DB == nil || jobID == "" || expectedETag == "" || len(reason) > 4096 || validateJobCommand(command) != nil {
		return nil, ErrInvalidJobCommand
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, command.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	lockKey := fmt.Sprintf("jobs.cancel:%d:%s:%d:%s:%s", len(command.TenantID), command.TenantID, len(command.ProjectID), command.ProjectID, command.IdempotencyKey)
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return nil, err
	}
	var existingDigest, existingOperationID string
	err = tx.QueryRowContext(ctx, `SELECT request_hash,operation_id FROM idempotency_records WHERE tenant_id=$1 AND project_id=$2 AND command_key=$3`, command.TenantID, command.ProjectID, command.IdempotencyKey).Scan(&existingDigest, &existingOperationID)
	if err == nil {
		if subtle.ConstantTimeCompare([]byte(existingDigest), []byte(command.RequestDigest)) != 1 {
			return nil, ErrIdempotencyConflict
		}
		if err = tx.Commit(); err != nil {
			return nil, err
		}
		operation, loadErr := (operationsapp.SQLRepository{DB: r.DB}).GetSQL(ctx, command.TenantID, command.ProjectID, existingOperationID)
		if loadErr != nil {
			return nil, mapOperationError(loadErr)
		}
		job, loadErr := r.GetJobSQL(ctx, command.TenantID, command.ProjectID, operation.GetJobId())
		if loadErr != nil {
			return nil, loadErr
		}
		return &JobMutationResult{Job: cloneJob(job), Operation: proto.Clone(operation).(*jobv1.Operation), Replay: true}, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	var operationID, state, persistedETag string
	var version int64
	err = tx.QueryRowContext(ctx, `SELECT operation_id,desired_state,version,etag FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, command.TenantID, command.ProjectID, jobID).Scan(&operationID, &state, &version, &persistedETag)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if subtle.ConstantTimeCompare([]byte(persistedETag), []byte(expectedETag)) != 1 {
		return nil, ErrVersionConflict
	}
	if state != "ACCEPTED" && state != "QUEUED" && state != "RUNNING" {
		return nil, ErrTerminalMutation
	}
	if operationID == "" {
		return nil, ErrInvalidJobCommand
	}
	var operationVersion int64
	var operationETag string
	if err = tx.QueryRowContext(ctx, `SELECT version,etag FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, command.TenantID, command.ProjectID, operationID).Scan(&operationVersion, &operationETag); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	nextVersion := version + 1
	nextETag := operationsapp.ResourceETag(command.TenantID, command.ProjectID, jobID, nextVersion)
	result, err := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='CANCELLING',version=$4,etag=$5,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$7 AND etag=$8`, command.TenantID, command.ProjectID, jobID, nextVersion, nextETag, command.ObservedAt.UTC(), version, persistedETag)
	if err != nil {
		return nil, err
	}
	if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, rowsErr
		}
		return nil, ErrVersionConflict
	}
	operation, err := operationsapp.AdvanceTxSQL(ctx, tx, command.TenantID, command.ProjectID, operationID, operationVersion, operationETag, jobv1.OperationState_OPERATION_STATE_CANCELLING, command.ObservedAt.UTC())
	if err != nil {
		return nil, mapOperationError(err)
	}
	job, err := getJobTx(ctx, tx, command.TenantID, command.ProjectID, jobID)
	if err != nil {
		return nil, err
	}
	auditEnvelope, err := newJobCancellationAuditEnvelope(job, command.PrincipalID, command.ObservedAt.UTC())
	if err != nil {
		return nil, err
	}
	envelopeBytes, err := queue.MarshalEnvelope(auditEnvelope)
	if err != nil {
		return nil, err
	}
	aggregateType, aggregateID, err := queue.AggregateIdentity(auditEnvelope)
	if err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO idempotency_records (tenant_id,project_id,command_key,request_hash,operation_id,created_at) VALUES ($1,$2,$3,$4,$5,$6)`, command.TenantID, command.ProjectID, command.IdempotencyKey, command.RequestDigest, operationID, command.ObservedAt.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events (id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES ($1,$2,$3,'jobs.cancel',$4,$5,$6,$7,$8,$9)`, auditEnvelope.GetEventId(), command.TenantID, command.PrincipalID, jobID, command.ObservedAt.UTC(), command.RequestDigest, auditEnvelope.GetEventVersion(), auditEnvelope.GetPayloadDigest(), envelopeBytes); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, auditEnvelope.GetEventId(), command.TenantID, auditEnvelope.GetEventType(), auditEnvelope.GetEventVersion(), aggregateType, aggregateID, auditEnvelope.GetAggregateSequence(), auditEnvelope.GetPayloadDigest(), envelopeBytes, command.ObservedAt.UTC()); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &JobMutationResult{Job: cloneJob(job), Operation: proto.Clone(operation).(*jobv1.Operation)}, nil
}

func newJobCancellationAuditEnvelope(job *jobv1.Job, principalID string, at time.Time) (*commonv1.EventEnvelope, error) {
	if job == nil || job.GetResourceVersion() < 1 {
		return nil, ErrInvalidJobCommand
	}
	envelope, err := foundationaudit.NewEvent(job.GetTenantId(), principalID, "jobs.cancel", job.GetJobId(), "allowed", at.UTC(), nil)
	if err != nil {
		return nil, err
	}
	envelope.ProjectId = job.GetProjectId()
	envelope.JobId = job.GetJobId()
	envelope.Producer = "services/control_plane"
	// JobRequested is ordered on its Operation aggregate, and there is no
	// sequence-one event on the Job aggregate. Model this immutable audit fact
	// as its own semantic aggregate at ordinal one; preserve the authoritative
	// Job revision on Subject instead of manufacturing a missing predecessor.
	envelope.AggregateSequence = 1
	envelope.Subject.ResourceType = "job_cancellation_audit"
	envelope.Subject.ResourceId = strings.TrimPrefix(envelope.GetEventId(), "audit:")
	envelope.Subject.ProjectId = job.GetProjectId()
	envelope.Subject.ResourceVersion = job.GetResourceVersion()
	envelope.Subject.Name = "tenants/" + job.GetTenantId() + "/projects/" + job.GetProjectId() + "/" + strings.TrimPrefix(job.GetJobId(), "/") + "/auditEvents/" + envelope.Subject.GetResourceId()
	envelope.Subject.Etag = job.GetEtag()
	return envelope, queue.ValidateEnvelope(envelope)
}

func mapOperationError(err error) error {
	switch {
	case errors.Is(err, operationsapp.ErrNotFound):
		return ErrNotFound
	case errors.Is(err, operationsapp.ErrAlreadyExists):
		return ErrAlreadyExists
	case errors.Is(err, operationsapp.ErrIdempotencyConflict):
		return ErrIdempotencyConflict
	case errors.Is(err, operationsapp.ErrVersionConflict):
		return ErrVersionConflict
	case errors.Is(err, operationsapp.ErrTerminalTransition), errors.Is(err, operationsapp.ErrInvalidTransition):
		return ErrTerminalMutation
	default:
		return err
	}
}

func (r SQLRepository) CreateJobSQL(ctx context.Context, job *jobv1.Job) (*jobv1.Job, error) {
	if job == nil || job.GetJobId() == "" || job.GetTenantId() == "" || job.GetProjectId() == "" || job.GetConfiguration() == nil {
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
	created, err := getJobTx(ctx, tx, job.GetTenantId(), job.GetProjectId(), job.GetJobId())
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return created, nil
}

func (r SQLRepository) GetJobSQL(ctx context.Context, tenantID, projectID, jobID string) (*jobv1.Job, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getJobTx(ctx, tx, tenantID, projectID, jobID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) CreateRunSQL(ctx context.Context, run *jobv1.Run) (*jobv1.Run, error) {
	if run == nil || run.GetRunId() == "" || run.GetJobId() == "" || run.GetTenantId() == "" || run.GetProjectId() == "" {
		return nil, ErrNotFound
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, run.GetTenantId(), nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	job, err := getJobTx(ctx, tx, run.GetTenantId(), run.GetProjectId(), run.GetJobId())
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
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs (tenant_id, project_id, run_id, ordinal, artifact_ref_id) VALUES ($1,$2,$3,$4,$5)`, run.GetTenantId(), projectID, run.GetRunId(), ordinal, refID.Int64); err != nil {
			return nil, err
		}
	}
	created, err := getRunTx(ctx, tx, run.GetTenantId(), projectID, run.GetRunId())
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return created, nil
}

func (r SQLRepository) GetRunSQL(ctx context.Context, tenantID, projectID, runID string) (*jobv1.Run, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getRunTx(ctx, tx, tenantID, projectID, runID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

// ListRunsSQL returns a stable keyset page ordered by immutable run identity.
// The caller signs and scope-binds the last identity before exposing it as a
// page token.
func (r SQLRepository) ListRunsSQL(ctx context.Context, tenantID, projectID, jobID, after string, limit int) ([]*jobv1.Run, bool, time.Time, error) {
	if tenantID == "" || projectID == "" || jobID == "" || limit < 1 || limit > 200 {
		return nil, false, time.Time{}, ErrNotFound
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, false, time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	readAt := time.Now().UTC()
	rows, err := tx.QueryContext(ctx, `SELECT id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND job_id=$3 AND id>$4 ORDER BY id LIMIT $5`, tenantID, projectID, jobID, after, limit+1)
	if err != nil {
		return nil, false, time.Time{}, err
	}
	ids := make([]string, 0, limit+1)
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, false, time.Time{}, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, false, time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, false, time.Time{}, err
	}
	more := len(ids) > limit
	if more {
		ids = ids[:limit]
	}
	values := make([]*jobv1.Run, 0, len(ids))
	for _, id := range ids {
		value, loadErr := getRunTx(ctx, tx, tenantID, projectID, id)
		if loadErr != nil {
			return nil, false, time.Time{}, loadErr
		}
		values = append(values, value)
	}
	if err = tx.Commit(); err != nil {
		return nil, false, time.Time{}, err
	}
	return values, more, readAt, nil
}

func (r SQLRepository) GetAttemptSQL(ctx context.Context, tenantID, projectID, attemptID string) (*jobv1.Attempt, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := getAttemptTx(ctx, tx, tenantID, projectID, attemptID)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return value, nil
}

// ListAttemptsSQL returns a stable keyset page ordered by immutable attempt
// identity under one run.
func (r SQLRepository) ListAttemptsSQL(ctx context.Context, tenantID, projectID, runID, after string, limit int) ([]*jobv1.Attempt, bool, time.Time, error) {
	if tenantID == "" || projectID == "" || runID == "" || limit < 1 || limit > 200 {
		return nil, false, time.Time{}, ErrNotFound
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, false, time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	readAt := time.Now().UTC()
	rows, err := tx.QueryContext(ctx, `SELECT id FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND run_id=$3 AND id>$4 ORDER BY id LIMIT $5`, tenantID, projectID, runID, after, limit+1)
	if err != nil {
		return nil, false, time.Time{}, err
	}
	ids := make([]string, 0, limit+1)
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, false, time.Time{}, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, false, time.Time{}, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, false, time.Time{}, err
	}
	more := len(ids) > limit
	if more {
		ids = ids[:limit]
	}
	values := make([]*jobv1.Attempt, 0, len(ids))
	for _, id := range ids {
		value, loadErr := getAttemptTx(ctx, tx, tenantID, projectID, id)
		if loadErr != nil {
			return nil, false, time.Time{}, loadErr
		}
		values = append(values, value)
	}
	if err = tx.Commit(); err != nil {
		return nil, false, time.Time{}, err
	}
	return values, more, readAt, nil
}

func (r SQLRepository) AcquireLeaseSQL(ctx context.Context, command AcquireLeaseCommand) (*LeaseMutationResult, error) {
	if command.TenantID == "" || command.RunID == "" || command.AttemptID == "" || command.WorkerID == "" || command.Now.IsZero() {
		return nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, err
	}
	if command.TokenKeyID == "" || validateRunCommandMetadata(command.Command, command.TenantID, actionAcquireLease) != nil || command.Command.WorkerID != command.WorkerID {
		return nil, ErrInvalidLease
	}
	tokenDigest, err := LeaseTokenDigest(command.Token)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, command.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkRunCommand(ctx, tx, command.Command)
	if err != nil {
		return nil, err
	}
	if replay {
		if !receipt.runID.Valid || !receipt.attemptID.Valid || !receipt.tokenKeyID.Valid || receipt.runID.String != command.RunID || receipt.attemptID.String != command.AttemptID {
			return nil, ErrIdempotencyConflict
		}
		attempt, fence, loadErr := getAttemptFenceTx(ctx, tx, command.TenantID, command.Command.ProjectID, receipt.attemptID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, commitErr
		}
		return &LeaseMutationResult{Attempt: attempt, Fence: fence, TokenKeyID: receipt.tokenKeyID.String, Replay: true}, nil
	}
	var (
		jobID, projectID, status string
		currentEpoch             uint64
	)
	err = tx.QueryRowContext(ctx, `SELECT job_id, project_id, status, lease_epoch FROM runs WHERE tenant_id = $1 AND project_id=$2 AND id = $3 FOR UPDATE`, command.TenantID, command.Command.ProjectID, command.RunID).Scan(&jobID, &projectID, &status, &currentEpoch)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if projectID != command.Command.ProjectID {
		return nil, ErrNotFound
	}
	runState, err := runStateFromDatabase(status)
	if err != nil {
		return nil, err
	}
	if terminalRunState(runState) || runState == jobv1.RunState_RUN_STATE_CANCELLING {
		return nil, ErrTerminalMutation
	}
	var activeAttemptID string
	var activeExpiry time.Time
	activeErr := tx.QueryRowContext(ctx, `SELECT id, lease_expires_at FROM attempts WHERE tenant_id = $1 AND project_id=$2 AND run_id = $3 AND status IN ('LEASED','ACTIVE') ORDER BY lease_epoch DESC LIMIT 1 FOR UPDATE`, command.TenantID, command.Command.ProjectID, command.RunID).Scan(&activeAttemptID, &activeExpiry)
	if activeErr == nil && command.Now.UTC().Before(activeExpiry.UTC()) {
		return nil, ErrLeaseHeld
	}
	if activeErr != nil && !errors.Is(activeErr, sql.ErrNoRows) {
		return nil, activeErr
	}
	if activeAttemptID != "" {
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'TIMED_OUT', version = version + 1, completed_at = $4, updated_at = $4 WHERE tenant_id = $1 AND project_id=$2 AND id = $3 AND status IN ('LEASED','ACTIVE')`, command.TenantID, command.Command.ProjectID, activeAttemptID, command.Now.UTC()); err != nil {
			return nil, err
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
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'EXECUTING', lease_epoch = $4, version = version + 1, started_at = COALESCE(started_at, $5), updated_at = $5 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, command.TenantID, command.Command.ProjectID, command.RunID, epoch, command.Now.UTC()); err != nil {
		return nil, err
	}
	attempt, err := getAttemptTx(ctx, tx, command.TenantID, command.Command.ProjectID, command.AttemptID)
	if err != nil {
		return nil, err
	}
	fence := leaseFence(attempt, tokenDigest)
	leasedEvent, err := newAttemptLeasedEvent(attempt, fence, command.Command, command.Now)
	if err != nil {
		return nil, err
	}
	if err = insertAttemptOutbox(ctx, tx, leasedEvent, command.Now); err != nil {
		return nil, err
	}
	if err = recordRunCommand(ctx, tx, command.Command, command.RunID, command.AttemptID, command.TokenKeyID); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &LeaseMutationResult{Attempt: attempt, Fence: fence, TokenKeyID: command.TokenKeyID}, nil
}

func (r SQLRepository) RenewLeaseSQL(ctx context.Context, command RenewLeaseCommand) (*LeaseMutationResult, error) {
	return r.renewLeaseSQL(ctx, command, false)
}

func (r SQLRepository) HeartbeatLeaseSQL(ctx context.Context, command RenewLeaseCommand) (*LeaseMutationResult, error) {
	return r.renewLeaseSQL(ctx, command, true)
}

func (r SQLRepository) renewLeaseSQL(ctx context.Context, command RenewLeaseCommand, heartbeat bool) (*LeaseMutationResult, error) {
	if command.Now.IsZero() || command.Credentials.TenantID == "" || command.Credentials.ProjectID == "" || command.Credentials.AttemptID == "" || command.Credentials.WorkerID == "" {
		return nil, ErrInvalidLease
	}
	if err := validateLeaseDuration(command.Duration); err != nil {
		return nil, err
	}
	action := actionRenewLease
	if heartbeat {
		action = actionHeartbeat
	}
	if validateRunCommandMetadata(command.Command, command.Credentials.TenantID, action) != nil || command.Command.ProjectID != command.Credentials.ProjectID || command.Command.WorkerID != command.Credentials.WorkerID {
		return nil, ErrInvalidLease
	}
	presentedDigest, err := LeaseTokenDigest(command.Credentials.Token)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, command.Credentials.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkRunCommand(ctx, tx, command.Command)
	if err != nil {
		return nil, err
	}
	if replay {
		if !receipt.attemptID.Valid || receipt.attemptID.String != command.Credentials.AttemptID {
			return nil, ErrIdempotencyConflict
		}
		attempt, fence, loadErr := getAttemptFenceTx(ctx, tx, command.Credentials.TenantID, command.Credentials.ProjectID, receipt.attemptID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, commitErr
		}
		return &LeaseMutationResult{Attempt: attempt, Fence: fence, Replay: true}, nil
	}
	var runID string
	if err = tx.QueryRowContext(ctx, `SELECT run_id FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, command.Credentials.TenantID, command.Credentials.ProjectID, command.Credentials.AttemptID).Scan(&runID); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	var currentEpoch uint64
	var runStatus, projectID string
	if err = tx.QueryRowContext(ctx, `SELECT lease_epoch,status,project_id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, command.Credentials.TenantID, command.Credentials.ProjectID, runID).Scan(&currentEpoch, &runStatus, &projectID); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	if projectID != command.Command.ProjectID || (runStatus != "EXECUTING" && runStatus != "CANCELLING") {
		return nil, ErrTerminalMutation
	}
	var storedWorker, storedDigest, status string
	var attemptEpoch uint64
	var version int64
	var expiresAt time.Time
	err = tx.QueryRowContext(ctx, `SELECT worker_id,lease_token_digest,lease_epoch,version,lease_expires_at,status FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 FOR UPDATE`, command.Credentials.TenantID, command.Credentials.ProjectID, command.Credentials.AttemptID, runID).Scan(&storedWorker, &storedDigest, &attemptEpoch, &version, &expiresAt, &status)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	switch {
	case storedWorker != command.Credentials.WorkerID:
		return nil, ErrLeaseOwner
	case !equalLeaseTokenDigest(storedDigest, presentedDigest):
		return nil, ErrInvalidLeaseToken
	case attemptEpoch != command.Credentials.Epoch || currentEpoch != command.Credentials.Epoch:
		return nil, ErrStaleCompletion
	case version != command.ExpectedResourceVersion:
		return nil, ErrVersionConflict
	case !command.Now.UTC().Before(expiresAt.UTC()):
		return nil, ErrLeaseExpired
	case status != "LEASED" && status != "ACTIVE":
		return nil, ErrTerminalMutation
	}
	deadline := renewedLeaseDeadline(command.Now, command.Duration, expiresAt)
	newStatus := status
	if heartbeat {
		newStatus = "ACTIVE"
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET lease_expires_at = $4, last_heartbeat_at = $5, status = $6, started_at = CASE WHEN $7 THEN COALESCE(started_at, $5) ELSE started_at END, version = version + 1, updated_at = $5 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, command.Credentials.TenantID, command.Credentials.ProjectID, command.Credentials.AttemptID, deadline, command.Now.UTC(), newStatus, heartbeat); err != nil {
		return nil, err
	}
	attempt, fence, err := getAttemptFenceTx(ctx, tx, command.Credentials.TenantID, command.Credentials.ProjectID, command.Credentials.AttemptID)
	if err != nil {
		return nil, err
	}
	if err = recordRunCommand(ctx, tx, command.Command, runID, command.Credentials.AttemptID, ""); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &LeaseMutationResult{Attempt: attempt, Fence: fence}, nil
}

func (r SQLRepository) CancelAttemptSQL(ctx context.Context, command CancelAttemptCommand) (*AttemptMutationResult, error) {
	credentials, expectedVersion, at := command.Credentials, command.ExpectedResourceVersion, command.Now
	if at.IsZero() || credentials.ProjectID == "" || validateRunCommandMetadata(command.Command, credentials.TenantID, actionCancelAttempt) != nil || command.Command.ProjectID != credentials.ProjectID || command.Command.WorkerID != credentials.WorkerID {
		return nil, ErrInvalidLease
	}
	// Validate ownership, token, epoch, version, and expiry under the same lock
	// as cancellation; renewal itself is not committed.
	presentedDigest, err := LeaseTokenDigest(credentials.Token)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, credentials.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkRunCommand(ctx, tx, command.Command)
	if err != nil {
		return nil, err
	}
	if replay {
		if !receipt.attemptID.Valid || receipt.attemptID.String != credentials.AttemptID || !receipt.runID.Valid {
			return nil, ErrIdempotencyConflict
		}
		attempt, loadErr := getAttemptTx(ctx, tx, credentials.TenantID, credentials.ProjectID, receipt.attemptID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		run, loadErr := getRunTx(ctx, tx, credentials.TenantID, credentials.ProjectID, receipt.runID.String)
		if loadErr != nil {
			return nil, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, commitErr
		}
		return &AttemptMutationResult{Attempt: attempt, Run: run, Replay: true}, nil
	}
	var runID string
	if err = tx.QueryRowContext(ctx, `SELECT run_id FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID).Scan(&runID); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	var currentEpoch uint64
	var runStatus, projectID string
	if err = tx.QueryRowContext(ctx, `SELECT lease_epoch,status,project_id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, credentials.TenantID, credentials.ProjectID, runID).Scan(&currentEpoch, &runStatus, &projectID); errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	} else if err != nil {
		return nil, err
	}
	if projectID != command.Command.ProjectID || (runStatus != "EXECUTING" && runStatus != "CANCELLING") {
		return nil, ErrTerminalMutation
	}
	var workerID, tokenDigest, status string
	var epoch uint64
	var version int64
	var expiresAt time.Time
	err = tx.QueryRowContext(ctx, `SELECT worker_id,lease_token_digest,lease_epoch,version,lease_expires_at,status FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 FOR UPDATE`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, runID).Scan(&workerID, &tokenDigest, &epoch, &version, &expiresAt, &status)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	switch {
	case workerID != credentials.WorkerID:
		return nil, ErrLeaseOwner
	case !equalLeaseTokenDigest(tokenDigest, presentedDigest):
		return nil, ErrInvalidLeaseToken
	case epoch != credentials.Epoch || currentEpoch != credentials.Epoch:
		return nil, ErrStaleCompletion
	case version != expectedVersion:
		return nil, ErrVersionConflict
	case !at.UTC().Before(expiresAt.UTC()):
		return nil, ErrLeaseExpired
	case status != "LEASED" && status != "ACTIVE":
		return nil, ErrTerminalMutation
	}
	if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'CANCELLED', version = version + 1, completed_at = $4, updated_at = $4 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, credentials.TenantID, credentials.ProjectID, credentials.AttemptID, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'CANCELLED', version = version + 1, completed_at = $4, updated_at = $4 WHERE tenant_id = $1 AND project_id=$2 AND id = $3 AND lease_epoch = $5`, credentials.TenantID, credentials.ProjectID, runID, at.UTC(), credentials.Epoch); err != nil {
		return nil, err
	}
	attempt, err := getAttemptTx(ctx, tx, credentials.TenantID, credentials.ProjectID, credentials.AttemptID)
	if err != nil {
		return nil, err
	}
	run, err := getRunTx(ctx, tx, credentials.TenantID, credentials.ProjectID, runID)
	if err != nil {
		return nil, err
	}
	if err = recordRunCommand(ctx, tx, command.Command, runID, credentials.AttemptID, ""); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &AttemptMutationResult{Attempt: attempt, Run: run}, nil
}

func (r SQLRepository) ExpireLeasesSQL(ctx context.Context, command ExpireLeasesCommand) (*ExpireLeasesResult, error) {
	tenantID, at, limit := command.TenantID, command.Now, command.Limit
	if at.IsZero() || limit < 1 || limit > 1000 || validateRunCommandMetadata(command.Command, tenantID, actionExpireLeases) != nil {
		return nil, ErrInvalidLease
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, tenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkRunCommand(ctx, tx, command.Command)
	if err != nil {
		return nil, err
	}
	if replay {
		attempts, loadErr := loadReceiptAttempts(ctx, tx, tenantID, command.Command.ProjectID, receipt.commandKey)
		if loadErr != nil {
			return nil, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, commitErr
		}
		return &ExpireLeasesResult{Attempts: attempts, ObservedAt: receipt.observedAt, Replay: true}, nil
	}
	rows, err := tx.QueryContext(ctx, `SELECT id,run_id,lease_epoch FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND status IN ('LEASED','ACTIVE') AND lease_expires_at <= $3 ORDER BY lease_expires_at,id LIMIT $4`, tenantID, command.Command.ProjectID, at.UTC(), limit)
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
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		due = append(due, value)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	result := make([]*jobv1.Attempt, 0, len(due))
	for _, value := range due {
		var currentEpoch uint64
		var runStatus string
		runErr := tx.QueryRowContext(ctx, `SELECT lease_epoch,status FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE SKIP LOCKED`, tenantID, command.Command.ProjectID, value.runID).Scan(&currentEpoch, &runStatus)
		if errors.Is(runErr, sql.ErrNoRows) {
			continue
		}
		if runErr != nil {
			return nil, runErr
		}
		var attemptEpoch uint64
		var attemptStatus string
		var expiresAt time.Time
		attemptErr := tx.QueryRowContext(ctx, `SELECT lease_epoch,status,lease_expires_at FROM attempts WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 FOR UPDATE SKIP LOCKED`, tenantID, command.Command.ProjectID, value.attemptID, value.runID).Scan(&attemptEpoch, &attemptStatus, &expiresAt)
		if errors.Is(attemptErr, sql.ErrNoRows) {
			continue
		}
		if attemptErr != nil {
			return nil, attemptErr
		}
		if attemptEpoch != value.epoch || currentEpoch != value.epoch || (attemptStatus != "LEASED" && attemptStatus != "ACTIVE") || at.UTC().Before(expiresAt.UTC()) {
			continue
		}
		if _, err = tx.ExecContext(ctx, `UPDATE attempts SET status = 'TIMED_OUT', version = version + 1, completed_at = $4, updated_at = $4 WHERE tenant_id = $1 AND project_id=$2 AND id = $3`, tenantID, command.Command.ProjectID, value.attemptID, at.UTC()); err != nil {
			return nil, err
		}
		if runStatus == "EXECUTING" {
			if _, err = tx.ExecContext(ctx, `UPDATE runs SET status = 'READY', version = version + 1, updated_at = $5 WHERE tenant_id = $1 AND project_id=$2 AND id = $3 AND lease_epoch = $4 AND status = 'EXECUTING'`, tenantID, command.Command.ProjectID, value.runID, value.epoch, at.UTC()); err != nil {
				return nil, err
			}
		}
		attempt, loadErr := getAttemptTx(ctx, tx, tenantID, command.Command.ProjectID, value.attemptID)
		if loadErr != nil {
			return nil, loadErr
		}
		result = append(result, attempt)
	}
	if err = recordRunCommand(ctx, tx, command.Command, "", "", ""); err != nil {
		return nil, err
	}
	key := runCommandKey(command.Command.Action, command.Command.IdempotencyKey)
	for ordinal, attempt := range result {
		if _, err = tx.ExecContext(ctx, `INSERT INTO run_command_receipt_attempts (tenant_id,project_id,command_key,ordinal,attempt_id) VALUES ($1,$2,$3,$4,$5)`, tenantID, command.Command.ProjectID, key, ordinal, attempt.GetAttemptId()); err != nil {
			return nil, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return &ExpireLeasesResult{Attempts: result, ObservedAt: at.UTC()}, nil
}

var (
	ErrAlreadyExists       = errors.New("job resource already exists")
	ErrInvalidJobCommand   = errors.New("invalid job command")
	ErrNotFound            = errors.New("job resource not found")
	ErrStaleCompletion     = errors.New("stale attempt completion retained")
	ErrTerminalMutation    = errors.New("terminal resource cannot advance")
	ErrInvalidOutcome      = errors.New("attempt completion requires a terminal outcome")
	ErrInvalidLease        = errors.New("invalid attempt lease")
	ErrInvalidLeaseToken   = errors.New("invalid attempt lease token")
	ErrLeaseHeld           = errors.New("run already has an unexpired lease")
	ErrLeaseExpired        = errors.New("attempt lease expired")
	ErrLeaseOwner          = errors.New("attempt lease belongs to another worker")
	ErrVersionConflict     = errors.New("attempt resource version conflict")
	ErrIdempotencyConflict = errors.New("run command idempotency key conflict")
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

func getJobTx(ctx context.Context, tx *sql.Tx, tenantID, projectID, jobID string) (*jobv1.Job, error) {
	value, err := scanJobSQL(tx.QueryRowContext(ctx, `SELECT id, operation_id, tenant_id, project_id, desired_state, version, policy_digest, job_kind, input_ref_id, configuration_ref_id, created_at, updated_at, etag FROM jobs WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, jobID))
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

func getRunTx(ctx context.Context, tx *sql.Tx, tenantID, projectID, runID string) (*jobv1.Run, error) {
	value, err := scanRunSQL(tx.QueryRowContext(ctx, `SELECT id, job_id, tenant_id, project_id, input_ref_id, configuration_ref_id, plan_ref_id, status, version, lease_epoch, error_detail_id, etag, created_at, started_at, completed_at FROM runs WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, runID))
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
	value.row.outputs, err = loadOutputRefs(ctx, tx, tenantID, projectID, "run_output_refs", "run_id", runID)
	if err != nil {
		return nil, err
	}
	return runRowToProto(value.row), nil
}

func getAttemptTx(ctx context.Context, tx *sql.Tx, tenantID, projectID, attemptID string) (*jobv1.Attempt, error) {
	value, err := scanAttemptSQL(tx.QueryRowContext(ctx, `SELECT id, run_id, tenant_id, project_id, job_id, worker_id, lease_epoch, lease_token_digest, lease_expires_at, last_heartbeat_at, status, version, error_detail_id, leased_at, started_at, completed_at FROM attempts WHERE tenant_id = $1 AND project_id = $2 AND id = $3`, tenantID, projectID, attemptID))
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
	value.row.outputs, err = loadOutputRefs(ctx, tx, tenantID, projectID, "attempt_output_refs", "attempt_id", attemptID)
	if err != nil {
		return nil, err
	}
	return attemptRowToProto(value.row), nil
}

func loadOutputRefs(ctx context.Context, tx *sql.Tx, tenantID, projectID, table, ownerColumn, ownerID string) ([]*artifactv1.ArtifactRef, error) {
	var query string
	switch {
	case table == "run_output_refs" && ownerColumn == "run_id":
		query = `SELECT artifact_ref_id FROM run_output_refs WHERE tenant_id = $1 AND project_id = $2 AND run_id = $3 ORDER BY ordinal`
	case table == "attempt_output_refs" && ownerColumn == "attempt_id":
		query = `SELECT artifact_ref_id FROM attempt_output_refs WHERE tenant_id = $1 AND project_id = $2 AND attempt_id = $3 ORDER BY ordinal`
	default:
		return nil, errors.New("unsupported output reference owner")
	}
	rows, err := tx.QueryContext(ctx, query, tenantID, projectID, ownerID)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	if err = platformdb.CloseRows(rows); err != nil {
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
		return "COMPLETED", "SUCCEEDED", nil
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
