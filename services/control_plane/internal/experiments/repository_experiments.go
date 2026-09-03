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

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
)

func (repository SQLRepository) CreateExperiment(ctx context.Context, identity Identity, command *experimentv1.CreateExperimentCommand, digest string, at time.Time) (*experimentv1.Experiment, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if err := validateCreateExperiment(identity, command); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name, err := experimentName(identity, command.GetExperimentId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "experiment.create", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		if receipt.resourceType != "experiment" || receipt.resourceName != name {
			return nil, false, ErrIdempotencyConflict
		}
		value, loadErr := loadExperimentTx(ctx, tx, identity, name, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	var exists int
	if err = tx.QueryRowContext(ctx, `SELECT 1 FROM experiments WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists); err == nil {
		return nil, false, ErrAlreadyExists
	} else if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	intentID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetIntentManifest())
	if err != nil {
		return nil, false, err
	}
	policyID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetUsePolicy())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("exp_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO experiments(tenant_id,project_id,name,uid,revision,etag,display_name,kind,state,intent_manifest_ref_id,use_policy_ref_id,policy_classification,create_time,update_time,complete_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$12,NULL)`, identity.TenantID, identity.ProjectID, name, uid, etag, command.GetDisplayName(), int32(command.GetKind()), int32(experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT), intentID, policyID, command.GetPolicyClassification(), at.UTC()); err != nil {
		return nil, false, err
	}
	if err = storeMap(ctx, tx, "experiment_labels", "experiment_name", "label_key", "label_value", identity, name, command.GetLabels()); err != nil {
		return nil, false, err
	}
	if err = storeMap(ctx, tx, "experiment_annotations", "experiment_name", "annotation_key", "annotation_value", identity, name, command.GetAnnotations()); err != nil {
		return nil, false, err
	}
	for ordinal, subject := range command.GetSubjects() {
		id, storeErr := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, subject)
		if storeErr != nil {
			return nil, false, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO experiment_subjects(tenant_id,project_id,experiment_name,ordinal,subject_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, ordinal, id); storeErr != nil {
			return nil, false, storeErr
		}
	}
	value, err := loadExperimentTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.ExperimentCreated(identity, value, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "experiment.create", command.GetContext().GetIdempotencyKey(), digest, "experiment", name, value.GetRevision(), event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(value), false, nil
}

func (repository SQLRepository) GetExperiment(ctx context.Context, identity Identity, name string) (*experimentv1.Experiment, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, err := loadExperimentTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func loadExperimentTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*experimentv1.Experiment, error) {
	canonical, err := experimentName(identity, name)
	if err != nil || canonical != name {
		return nil, ErrNotFound
	}
	query := `SELECT ` + experimentColumns + ` FROM experiments WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanExperiment(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, mapNotFound(err)
	}
	return experimentProto(ctx, tx, row)
}

func (repository SQLRepository) ListExperiments(ctx context.Context, identity Identity, page Page) ([]*experimentv1.Experiment, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if page.Parent != projectParent(identity) || page.Limit < 1 || page.Limit > maximumPageSize {
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
	conditions := []string{"tenant_id=$1", "project_id=$2"}
	args := []any{identity.TenantID, identity.ProjectID}
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
	query := `SELECT ` + experimentColumns + ` FROM experiments WHERE ` + strings.Join(conditions, " AND ") + ` ORDER BY create_time ` + direction + `,name ` + direction + ` LIMIT $` + strconv.Itoa(len(args)) //nolint:gosec
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = rows.Close() }()
	rowValues := make([]experimentRow, 0, page.Limit+1)
	for rows.Next() {
		value, scanErr := scanExperiment(rows)
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
	values := make([]*experimentv1.Experiment, 0, len(rowValues))
	for _, row := range rowValues {
		value, mapErr := experimentProto(ctx, tx, row)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	next := ""
	if len(values) > page.Limit {
		last := values[page.Limit-1]
		next, err = repository.Pagination.encode(pageToken{Kind: "experiments", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order, AfterTime: last.GetCreateTime().AsTime().UTC().Format(time.RFC3339Nano), AfterName: last.GetName()})
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

func (repository SQLRepository) UpdateExperiment(ctx context.Context, identity Identity, command *experimentv1.UpdateExperimentCommand, digest string, at time.Time) (*experimentv1.Experiment, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	paths, err := normalizeMask(command)
	if err != nil {
		return nil, false, err
	}
	if err = validateMap(command.GetExperiment().GetLabels(), 256); err != nil {
		return nil, false, err
	}
	if err = validateMap(command.GetExperiment().GetAnnotations(), 4096); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name := command.GetExperiment().GetName()
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "experiment.update", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := loadExperimentTx(ctx, tx, identity, receipt.resourceName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	current, err := loadExperimentTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(current.GetEtag()), []byte(command.GetEtag())) != 1 || (command.GetExperiment().GetRevision() != 0 && command.GetExperiment().GetRevision() != current.GetRevision()) {
		return nil, false, ErrRevisionConflict
	}
	displayName, classification := current.GetDisplayName(), current.GetPolicyClassification()
	for _, path := range paths {
		switch path {
		case "display_name":
			displayName = command.GetExperiment().GetDisplayName()
			if displayName == "" || len(displayName) > 512 {
				return nil, false, ErrInvalidArgument
			}
		case "policy_classification":
			classification = command.GetExperiment().GetPolicyClassification()
			if classification == "" || len(classification) > 128 {
				return nil, false, ErrInvalidArgument
			}
		}
	}
	revision := current.GetRevision() + 1
	etag := resourceETag(name, revision)
	result, err := tx.ExecContext(ctx, `UPDATE experiments SET revision=$4,etag=$5,display_name=$6,policy_classification=$7,update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, name, revision, etag, displayName, classification, at.UTC(), current.GetRevision(), current.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		return nil, false, ErrRevisionConflict
	}
	for _, path := range paths {
		switch path {
		case "labels":
			if _, err = tx.ExecContext(ctx, `DELETE FROM experiment_labels WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3`, identity.TenantID, identity.ProjectID, name); err != nil {
				return nil, false, err
			}
			if err = storeMap(ctx, tx, "experiment_labels", "experiment_name", "label_key", "label_value", identity, name, command.GetExperiment().GetLabels()); err != nil {
				return nil, false, err
			}
		case "annotations":
			if _, err = tx.ExecContext(ctx, `DELETE FROM experiment_annotations WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3`, identity.TenantID, identity.ProjectID, name); err != nil {
				return nil, false, err
			}
			if err = storeMap(ctx, tx, "experiment_annotations", "experiment_name", "annotation_key", "annotation_value", identity, name, command.GetExperiment().GetAnnotations()); err != nil {
				return nil, false, err
			}
		}
	}
	updated, err := loadExperimentTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.ExperimentUpdated(identity, updated, paths, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "experiment.update", command.GetContext().GetIdempotencyKey(), digest, "experiment", name, revision, event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(updated), false, nil
}

func (repository SQLRepository) TransitionExperiment(ctx context.Context, identity Identity, command *experimentv1.TransitionExperimentCommand, digest string, at time.Time) (*experimentv1.Experiment, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	command = clone(command)
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || !validReasonCode(command.GetReasonCode()) || validateReference(identity, command.GetExperiment(), "experiment", true) != nil {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || compareDigest(canonical, digest) != nil {
		return nil, false, ErrInvalidArgument
	}
	name := command.GetExperiment().GetName()
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	receipt, replay, err := checkReceipt(ctx, tx, identity, "experiment.transition", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := loadExperimentTx(ctx, tx, identity, receipt.resourceName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	current, err := loadExperimentTx(ctx, tx, identity, name, true)
	if err != nil {
		return nil, false, err
	}
	if command.GetExpectedState() != current.GetState() || !experimentTransitionAllowed(current.GetState(), command.GetTargetState()) || command.GetExperiment().GetResourceVersion() != current.GetRevision() || subtle.ConstantTimeCompare([]byte(command.GetEtag()), []byte(current.GetEtag())) != 1 {
		return nil, false, ErrInvalidTransition
	}
	if command.GetTargetState() == experimentv1.ExperimentState_EXPERIMENT_STATE_COMPLETED {
		var unfinished int
		if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiment_studies WHERE tenant_id=$1 AND project_id=$2 AND experiment_name=$3 AND state NOT IN (4,5,6)`, identity.TenantID, identity.ProjectID, name).Scan(&unfinished); err != nil {
			return nil, false, err
		}
		if unfinished != 0 {
			return nil, false, ErrInvalidTransition
		}
	}
	revision := current.GetRevision() + 1
	etag := resourceETag(name, revision)
	completeTime := any(nil)
	if current.GetCompleteTime() != nil {
		completeTime = current.GetCompleteTime().AsTime().UTC()
	} else if command.GetTargetState() == experimentv1.ExperimentState_EXPERIMENT_STATE_COMPLETED || command.GetTargetState() == experimentv1.ExperimentState_EXPERIMENT_STATE_CANCELLED {
		completeTime = at.UTC()
	}
	result, err := tx.ExecContext(ctx, `UPDATE experiments SET revision=$4,etag=$5,state=$6,update_time=$7,complete_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, name, revision, etag, int32(command.GetTargetState()), at.UTC(), completeTime, current.GetRevision(), current.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		return nil, false, ErrRevisionConflict
	}
	updated, err := loadExperimentTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, false, err
	}
	event, err := repository.Events.ExperimentStateChanged(identity, updated, current.GetState(), command.GetReasonCode(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "experiment.transition", command.GetContext().GetIdempotencyKey(), digest, "experiment", name, revision, event, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(updated), false, nil
}

func pageRequest(page *commonv1.PageRequest) uint32 {
	if page == nil {
		return 0
	}
	return page.GetPageSize()
}
