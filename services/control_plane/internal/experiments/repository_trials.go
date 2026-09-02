package experiments

import (
	"context"
	"crypto/subtle"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

func (repository SQLRepository) CreateTrial(ctx context.Context, identity Identity, command *experimentv1.CreateTrialCommand, digest string, at time.Time) (*experimentv1.Trial, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if err := validateCreateTrial(identity, command); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name, err := trialName(identity, command.GetStudy().GetName(), command.GetTrialId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "trial.create", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		if receipt.resourceType != "trial" || receipt.resourceName != name {
			return nil, false, ErrIdempotencyConflict
		}
		value, loadErr := loadTrialTx(ctx, tx, identity, name, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	study, err := loadStudyTx(ctx, tx, identity, command.GetStudy().GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if study.GetState() != experimentv1.StudyState_STUDY_STATE_CREATED && study.GetState() != experimentv1.StudyState_STUDY_STATE_RUNNING {
		return nil, false, ErrInvalidTransition
	}
	if study.GetRevision() != command.GetStudy().GetResourceVersion() || subtle.ConstantTimeCompare([]byte(study.GetEtag()), []byte(command.GetStudy().GetEtag())) != 1 {
		return nil, false, ErrRevisionConflict
	}
	var count int64
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND study_name=$3`, identity.TenantID, identity.ProjectID, study.GetName()).Scan(&count); err != nil {
		return nil, false, err
	}
	if count >= int64(study.GetBudget().GetMaximumTrials()) {
		return nil, false, ErrInvalidTransition
	}
	var exists int
	if err = tx.QueryRowContext(ctx, `SELECT 1 FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND (name=$3 OR (study_name=$4 AND trial_number=$5))`, identity.TenantID, identity.ProjectID, name, study.GetName(), int64(command.GetTrialNumber())).Scan(&exists); err == nil {
		return nil, false, ErrAlreadyExists
	} else if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	studyID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetStudy())
	if err != nil {
		return nil, false, err
	}
	configurationID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetResolvedConfiguration())
	if err != nil {
		return nil, false, err
	}
	executionID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetExecution())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("trial_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO experiment_trials(tenant_id,project_id,name,uid,study_name,study_ref_id,revision,etag,trial_number,state,outcome,resolved_configuration_ref_id,execution_ref_id,result_manifest_ref_id,error_detail_id,create_time,start_time,complete_time,elapsed_seconds,elapsed_nanos) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,$9,0,$10,$11,NULL,NULL,$12,NULL,NULL,NULL,NULL)`, identity.TenantID, identity.ProjectID, name, uid, study.GetName(), studyID, etag, int64(command.GetTrialNumber()), int32(experimentv1.TrialState_TRIAL_STATE_CREATED), configurationID, executionID, at.UTC()); err != nil {
		return nil, false, err
	}
	value, err := loadTrialTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.TrialCreated(identity, value, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "trial.create", command.GetContext().GetIdempotencyKey(), digest, "trial", name, value.GetRevision(), event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(value), false, nil
}

func (repository SQLRepository) GetTrial(ctx context.Context, identity Identity, name string) (*experimentv1.Trial, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := loadTrialTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func loadTrialTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*experimentv1.Trial, error) {
	if !strings.HasPrefix(name, projectParent(identity)+"/experiments/") || parentStudy(name) == "" || !validStudyParent(identity, parentStudy(name)) || !validID(lastSegment(name)) {
		return nil, ErrNotFound
	}
	query := `SELECT ` + trialColumns + ` FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanTrial(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, mapNotFound(err)
	}
	return trialProto(ctx, tx, row)
}

func (repository SQLRepository) ListTrials(ctx context.Context, identity Identity, page Page) ([]*experimentv1.Trial, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if !validStudyParent(identity, page.Parent) || page.Limit < 1 || page.Limit > maximumPageSize {
		return nil, "", time.Time{}, ErrPermissionDenied
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	conditions := []string{"tenant_id=$1", "project_id=$2", "study_name=$3"}
	args := []any{identity.TenantID, identity.ProjectID, page.Parent}
	if page.State != 0 {
		args = append(args, page.State)
		conditions = append(conditions, fmt.Sprintf("state=$%d", len(args)))
	}
	ascending := page.Order == "create_time asc,name asc"
	if !page.AfterTime.IsZero() {
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		operator := "<"
		if ascending {
			operator = ">"
		}
		conditions = append(conditions, fmt.Sprintf("(create_time,name) %s ($%d,$%d)", operator, len(args)-1, len(args)))
	}
	args = append(args, page.Limit+1)
	direction := "DESC"
	if ascending {
		direction = "ASC"
	}
	query := `SELECT ` + trialColumns + ` FROM experiment_trials WHERE ` + strings.Join(conditions, " AND ") + ` ORDER BY create_time ` + direction + `,name ` + direction + ` LIMIT $` + strconv.Itoa(len(args)) //nolint:gosec
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = rows.Close() }()
	rowValues := make([]trialRow, 0, page.Limit+1)
	for rows.Next() {
		value, scanErr := scanTrial(rows)
		if scanErr != nil {
			return nil, "", time.Time{}, scanErr
		}
		rowValues = append(rowValues, value)
	}
	if err = rows.Err(); err != nil {
		return nil, "", time.Time{}, err
	}
	if err = rows.Close(); err != nil {
		return nil, "", time.Time{}, err
	}
	values := make([]*experimentv1.Trial, 0, len(rowValues))
	for _, row := range rowValues {
		value, mapErr := trialProto(ctx, tx, row)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	next := ""
	if len(values) > page.Limit {
		last := values[page.Limit-1]
		next, err = repository.Pagination.encode(pageToken{Kind: "trials", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order, AfterTime: last.GetCreateTime().AsTime().UTC().Format(time.RFC3339Nano), AfterName: last.GetName()})
		values = values[:page.Limit]
	}
	if err != nil {
		return nil, "", time.Time{}, err
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), next, readAt.UTC(), nil
}

func (repository SQLRepository) TransitionTrial(ctx context.Context, identity Identity, command *experimentv1.TransitionTrialCommand, digest string, at time.Time) (*experimentv1.Trial, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || !validReasonCode(command.GetReasonCode()) || validateReference(identity, command.GetTrial(), "trial", true) != nil {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name := command.GetTrial().GetName()
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "trial.transition", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := loadTrialTx(ctx, tx, identity, receipt.resourceName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	current, err := loadTrialTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, false, err
	}
	if command.GetExpectedState() != current.GetState() || !trialTransitionAllowed(current.GetState(), command.GetTargetState()) || command.GetTrial().GetResourceVersion() != current.GetRevision() || subtle.ConstantTimeCompare([]byte(command.GetEtag()), []byte(current.GetEtag())) != 1 {
		return nil, false, ErrInvalidTransition
	}
	study, err := loadStudyTx(ctx, tx, identity, parentStudy(name), true)
	if err != nil {
		return nil, false, err
	}
	if (command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_ADMITTED || command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_RUNNING) && study.GetState() != experimentv1.StudyState_STUDY_STATE_RUNNING {
		return nil, false, ErrInvalidTransition
	}
	if command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_ADMITTED {
		var active int64
		if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND study_name=$3 AND state IN (2,3)`, identity.TenantID, identity.ProjectID, study.GetName()).Scan(&active); err != nil {
			return nil, false, err
		}
		if active >= int64(study.GetBudget().GetMaximumParallelTrials()) {
			return nil, false, ErrInvalidTransition
		}
	}
	revision := current.GetRevision() + 1
	etag := resourceETag(name, revision)
	startTime := any(nil)
	if current.GetStartTime() != nil {
		startTime = current.GetStartTime().AsTime().UTC()
	} else if command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_RUNNING {
		startTime = at.UTC()
	}
	completeTime, elapsedSeconds, elapsedNanos := any(nil), any(nil), any(nil)
	outcome := experimentv1.TrialOutcome_TRIAL_OUTCOME_UNSPECIFIED
	if command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_CANCELLED || command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_INVALID {
		completeTime = at.UTC()
		if current.GetStartTime() != nil {
			elapsed := at.Sub(current.GetStartTime().AsTime())
			if elapsed < 0 {
				return nil, false, ErrInvalidArgument
			}
			elapsedSeconds, elapsedNanos = int64(elapsed/time.Second), int32(elapsed%time.Second)
		}
		if command.GetTargetState() == experimentv1.TrialState_TRIAL_STATE_CANCELLED {
			outcome = experimentv1.TrialOutcome_TRIAL_OUTCOME_CANCELLED
		} else {
			outcome = experimentv1.TrialOutcome_TRIAL_OUTCOME_INFEASIBLE
		}
	}
	result, err := tx.ExecContext(ctx, `UPDATE experiment_trials SET revision=$4,etag=$5,state=$6,outcome=$7,start_time=$8,complete_time=$9,elapsed_seconds=$10,elapsed_nanos=$11 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$12 AND etag=$13`, identity.TenantID, identity.ProjectID, name, revision, etag, int32(command.GetTargetState()), int32(outcome), startTime, completeTime, elapsedSeconds, elapsedNanos, current.GetRevision(), current.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		return nil, false, ErrRevisionConflict
	}
	updated, err := loadTrialTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.TrialStateChanged(identity, updated, current.GetState(), command.GetReasonCode(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "trial.transition", command.GetContext().GetIdempotencyKey(), digest, "trial", name, revision, event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(updated), false, nil
}

func (repository SQLRepository) CompleteTrial(ctx context.Context, identity Identity, command *experimentv1.CompleteTrialCommand, digest string, at time.Time) (*experimentv1.Trial, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if err := validateCompleteTrial(command); err != nil {
		return nil, false, err
	}
	if err := validateReference(identity, command.GetTrial(), "trial", true); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name := command.GetTrial().GetName()
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "trial.complete", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := loadTrialTx(ctx, tx, identity, receipt.resourceName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	current, err := loadTrialTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, false, err
	}
	if current.GetState() != experimentv1.TrialState_TRIAL_STATE_RUNNING || command.GetTrial().GetResourceVersion() != current.GetRevision() || subtle.ConstantTimeCompare([]byte(command.GetEtag()), []byte(current.GetEtag())) != 1 || current.GetStartTime() == nil {
		return nil, false, ErrInvalidTransition
	}
	study, err := loadStudyTx(ctx, tx, identity, parentStudy(name), true)
	if err != nil || study.GetState() != experimentv1.StudyState_STUDY_STATE_RUNNING {
		return nil, false, ErrInvalidTransition
	}
	resultID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetResultManifest())
	if err != nil {
		return nil, false, err
	}
	errorID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, command.GetError())
	if err != nil {
		return nil, false, err
	}
	state := experimentv1.TrialState_TRIAL_STATE_COMPLETED
	if command.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_FAILED {
		state = experimentv1.TrialState_TRIAL_STATE_FAILED
	}
	elapsed := at.Sub(current.GetStartTime().AsTime())
	if elapsed < 0 {
		return nil, false, ErrInvalidArgument
	}
	revision := current.GetRevision() + 1
	etag := resourceETag(name, revision)
	result, err := tx.ExecContext(ctx, `UPDATE experiment_trials SET revision=$4,etag=$5,state=$6,outcome=$7,result_manifest_ref_id=$8,error_detail_id=$9,complete_time=$10,elapsed_seconds=$11,elapsed_nanos=$12 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$13 AND etag=$14`, identity.TenantID, identity.ProjectID, name, revision, etag, int32(state), int32(command.GetOutcome()), resultID, errorID, at.UTC(), int64(elapsed/time.Second), int32(elapsed%time.Second), current.GetRevision(), current.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		return nil, false, ErrRevisionConflict
	}
	for ordinal, evidence := range command.GetEvidence() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO experiment_trial_evidence(tenant_id,project_id,trial_name,ordinal,digest,subject_digest,evidence_kind,policy_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, name, ordinal, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest()); err != nil {
			return nil, false, err
		}
	}
	updated, err := loadTrialTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.TrialCompleted(identity, updated, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "trial.complete", command.GetContext().GetIdempotencyKey(), digest, "trial", name, revision, event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(updated), false, nil
}
