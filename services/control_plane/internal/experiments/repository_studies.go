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

func (repository SQLRepository) CreateStudy(ctx context.Context, identity Identity, command *experimentv1.CreateStudyCommand, digest string, at time.Time) (*experimentv1.Study, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if err := validateCreateStudy(identity, command); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name, err := studyName(identity, command.GetExperiment().GetName(), command.GetStudyId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "study.create", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		if receipt.resourceType != "study" || receipt.resourceName != name {
			return nil, false, ErrIdempotencyConflict
		}
		value, loadErr := loadStudyTx(ctx, tx, identity, name, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	parent, err := loadExperimentTx(ctx, tx, identity, command.GetExperiment().GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if parent.GetState() != experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE || parent.GetRevision() != command.GetExperiment().GetResourceVersion() || subtle.ConstantTimeCompare([]byte(parent.GetEtag()), []byte(command.GetExperiment().GetEtag())) != 1 {
		return nil, false, ErrRevisionConflict
	}
	var exists int
	if err = tx.QueryRowContext(ctx, `SELECT 1 FROM experiment_studies WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err == nil {
		return nil, false, ErrAlreadyExists
	} else if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	experimentID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetExperiment())
	if err != nil {
		return nil, false, err
	}
	ids := make([]sql.NullInt64, 4)
	ids[0], err = platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetStudyManifest())
	if err == nil {
		ids[1], err = platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetBaseConfiguration())
	}
	if err == nil {
		ids[2], err = platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetSearchSpace())
	}
	if err == nil {
		ids[3], err = platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetObjectiveSpecification())
	}
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("study_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	duration := command.GetBudget().GetMaximumDuration()
	if _, err = tx.ExecContext(ctx, `INSERT INTO experiment_studies(tenant_id,project_id,name,uid,experiment_name,experiment_ref_id,revision,etag,study_type,state,study_manifest_ref_id,base_configuration_ref_id,search_space_ref_id,objective_specification_ref_id,maximum_trials,maximum_parallel_trials,maximum_duration_seconds,maximum_duration_nanos,create_time,start_time,complete_time) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,NULL,NULL)`, identity.TenantID, identity.ProjectID, name, uid, parent.GetName(), experimentID, etag, int32(command.GetType()), int32(experimentv1.StudyState_STUDY_STATE_CREATED), ids[0], ids[1], ids[2], ids[3], int64(command.GetBudget().GetMaximumTrials()), int64(command.GetBudget().GetMaximumParallelTrials()), duration.GetSeconds(), duration.GetNanos(), at.UTC()); err != nil {
		return nil, false, err
	}
	value, err := loadStudyTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.StudyCreated(identity, value, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "study.create", command.GetContext().GetIdempotencyKey(), digest, "study", name, value.GetRevision(), event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(value), false, nil
}

func (repository SQLRepository) GetStudy(ctx context.Context, identity Identity, name string) (*experimentv1.Study, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := loadStudyTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func loadStudyTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*experimentv1.Study, error) {
	if !validStudyParent(identity, name) {
		return nil, ErrNotFound
	}
	query := `SELECT ` + studyColumns + ` FROM experiment_studies WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanStudy(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, mapNotFound(err)
	}
	return studyProto(ctx, tx, row)
}

func (repository SQLRepository) ListStudies(ctx context.Context, identity Identity, page Page) ([]*experimentv1.Study, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if !validExperimentParent(identity, page.Parent) || page.Limit < 1 || page.Limit > maximumPageSize {
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
	conditions := []string{"tenant_id=$1", "project_id=$2", "experiment_name=$3"}
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
	query := `SELECT ` + studyColumns + ` FROM experiment_studies WHERE ` + strings.Join(conditions, " AND ") + ` ORDER BY create_time ` + direction + `,name ` + direction + ` LIMIT $` + strconv.Itoa(len(args)) //nolint:gosec
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = rows.Close() }()
	rowValues := make([]studyRow, 0, page.Limit+1)
	for rows.Next() {
		value, scanErr := scanStudy(rows)
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
	values := make([]*experimentv1.Study, 0, len(rowValues))
	for _, row := range rowValues {
		value, mapErr := studyProto(ctx, tx, row)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	next := ""
	if len(values) > page.Limit {
		last := values[page.Limit-1]
		next, err = repository.Pagination.encode(pageToken{Kind: "studies", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order, AfterTime: last.GetCreateTime().AsTime().UTC().Format(time.RFC3339Nano), AfterName: last.GetName()})
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

func (repository SQLRepository) TransitionStudy(ctx context.Context, identity Identity, command *experimentv1.TransitionStudyCommand, digest string, at time.Time) (*experimentv1.Study, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || !validReasonCode(command.GetReasonCode()) || validateReference(identity, command.GetStudy(), "study", true) != nil {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name := command.GetStudy().GetName()
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "study.transition", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := loadStudyTx(ctx, tx, identity, receipt.resourceName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	current, err := loadStudyTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, false, err
	}
	if command.GetExpectedState() != current.GetState() || !studyTransitionAllowed(current.GetState(), command.GetTargetState()) || command.GetStudy().GetResourceVersion() != current.GetRevision() || subtle.ConstantTimeCompare([]byte(command.GetEtag()), []byte(current.GetEtag())) != 1 {
		return nil, false, ErrInvalidTransition
	}
	if command.GetTargetState() == experimentv1.StudyState_STUDY_STATE_COMPLETED {
		var total, unfinished int
		if err = tx.QueryRowContext(ctx, `SELECT count(*),count(*) FILTER (WHERE state NOT IN (4,5,6,7)) FROM experiment_trials WHERE tenant_id=$1 AND project_id=$2 AND study_name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&total, &unfinished); err != nil {
			return nil, false, err
		}
		if total == 0 || unfinished != 0 {
			return nil, false, ErrInvalidTransition
		}
	}
	revision := current.GetRevision() + 1
	etag := resourceETag(name, revision)
	startTime := any(nil)
	if current.GetStartTime() != nil {
		startTime = current.GetStartTime().AsTime().UTC()
	} else if command.GetTargetState() == experimentv1.StudyState_STUDY_STATE_RUNNING {
		startTime = at.UTC()
	}
	completeTime := any(nil)
	if command.GetTargetState() == experimentv1.StudyState_STUDY_STATE_COMPLETED || command.GetTargetState() == experimentv1.StudyState_STUDY_STATE_CANCELLED || command.GetTargetState() == experimentv1.StudyState_STUDY_STATE_FAILED {
		completeTime = at.UTC()
	}
	result, err := tx.ExecContext(ctx, `UPDATE experiment_studies SET revision=$4,etag=$5,state=$6,start_time=$7,complete_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, name, revision, etag, int32(command.GetTargetState()), startTime, completeTime, current.GetRevision(), current.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		return nil, false, ErrRevisionConflict
	}
	updated, err := loadStudyTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.StudyStateChanged(identity, updated, current.GetState(), command.GetReasonCode(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "study.transition", command.GetContext().GetIdempotencyKey(), digest, "study", name, revision, event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(updated), false, nil
}
