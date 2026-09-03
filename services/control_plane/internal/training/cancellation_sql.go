package training

import (
	"context"
	"database/sql"
	"errors"
	"time"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

// reconcileSchedulerCancellation applies cancellation intent monotonically to
// the Job and its single linked scheduler Run. Attempts have no cancelling
// state and retain their lease so the worker can checkpoint and acknowledge a
// terminal CANCELLED completion.
func reconcileSchedulerCancellation(ctx context.Context, tx *sql.Tx, identity Identity, row runRow, at time.Time) error {
	var jobState string
	var jobVersion int64
	err := tx.QueryRowContext(ctx, `SELECT desired_state,version FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, row.jobID).Scan(&jobState, &jobVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrInvalidTransition
	}
	if err != nil {
		return err
	}
	var runState string
	var runVersion int64
	err = tx.QueryRowContext(ctx, `SELECT status,version FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND job_id=$4 FOR UPDATE`, identity.TenantID, identity.ProjectID, row.schedulerRunID, row.jobID).Scan(&runState, &runVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrInvalidTransition
	}
	if err != nil {
		return err
	}
	if runState == "SUCCEEDED" || runState == "FAILED" || runState == "CANCELLED" || jobState == "SUCCEEDED" || jobState == "FAILED" || jobState == "CANCELLED" {
		return ErrInvalidTransition
	}
	if runState != "CANCELLING" {
		next := runVersion + 1
		result, updateErr := tx.ExecContext(ctx, `UPDATE runs SET status='CANCELLING',version=$5,etag=$6,updated_at=$7 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4`, identity.TenantID, identity.ProjectID, row.schedulerRunID, runVersion, next, resourceETag(row.schedulerRunID, next), at.UTC())
		if updateErr != nil {
			return updateErr
		}
		if updateErr = requireOne(result); updateErr != nil {
			return updateErr
		}
	}
	if jobState != "CANCELLING" {
		next := jobVersion + 1
		result, updateErr := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='CANCELLING',version=$5,etag=$6,updated_at=$7 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4`, identity.TenantID, identity.ProjectID, row.jobID, jobVersion, next, resourceETag(row.jobID, next), at.UTC())
		if updateErr != nil {
			return updateErr
		}
		if updateErr = requireOne(result); updateErr != nil {
			return updateErr
		}
	}
	return nil
}

func (r SQLRepository) CancelTrainingRun(ctx context.Context, identity Identity, command *trainingv1.CancelTrainingRunCommand, digest string, at time.Time) (*trainingv1.TrainingRun, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetTrainingRunName() == "" || command.GetEtag() == "" || !validReason(command.GetReason()) {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, command, command.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "training.cancel", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		run, _, loadErr := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(run), true, nil
	}
	run, row, err := getRunTx(ctx, tx, identity, command.GetTrainingRunName(), true)
	if err != nil {
		return nil, false, err
	}
	operationID := row.operationID
	if terminalRun(run.GetState()) {
		if err = insertAudit(ctx, tx, identity, "training.cancel.noop", run.GetName(), digest, at); err != nil {
			return nil, false, err
		}
		if err = recordIdempotency(ctx, tx, identity, "training.cancel", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(run), true, nil
	}
	if run.GetEtag() != command.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		if err = insertAudit(ctx, tx, identity, "training.cancel.noop", run.GetName(), digest, at); err != nil {
			return nil, false, err
		}
		if err = recordIdempotency(ctx, tx, identity, "training.cancel", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(run), true, nil
	}
	if err = reconcileSchedulerCancellation(ctx, tx, identity, row, at); err != nil {
		return nil, false, err
	}
	revision := run.GetRevision() + 1
	etag := resourceETag(run.GetName(), revision)
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$7 AND etag=$8`, identity.TenantID, identity.ProjectID, run.GetName(), revision, etag, int32(trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING), row.revision, command.GetEtag())
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, row.operationID, run, "CANCELLING", false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, false, err
	}
	operation, _, err := getOperationTx(ctx, tx, identity, row.operationID, false)
	if err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.CancellationRequested(identity, run, operation, command.GetReason(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "training.cancel", run.GetName(), digest, at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "training.cancel", command.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(run), false, nil
}

func (r SQLRepository) CancelOperation(ctx context.Context, identity Identity, request *internaljobv1.CancelOperationRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetName() == "" || request.GetEtag() == "" || !validReason(request.GetReason()) {
		return nil, false, ErrInvalidArgument
	}
	if err := validateRepositoryCommand(identity, request, request.GetContext(), digest, at); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, replay, err := checkIdempotency(ctx, tx, identity, "operations.cancel", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, _, loadErr := getOperationTx(ctx, tx, identity, request.GetName(), false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	// Discover the target without taking the operation lock. All training
	// mutations lock DomainRun before Operation; preserving that order avoids
	// a cancellation/completion deadlock.
	operation, _, err := getOperationTx(ctx, tx, identity, request.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	operationID := operation.GetOperationId()
	if operation.GetDone() {
		if err = insertAudit(ctx, tx, identity, "operations.cancel.noop", operation.GetOperationId(), digest, at); err != nil {
			return nil, false, err
		}
		if err = recordIdempotency(ctx, tx, identity, "operations.cancel", request.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	if operation.GetEtag() != request.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if operation.GetState() == jobv1.OperationState_OPERATION_STATE_CANCELLING {
		if err = insertAudit(ctx, tx, identity, "operations.cancel.noop", operation.GetOperationId(), digest, at); err != nil {
			return nil, false, err
		}
		if err = recordIdempotency(ctx, tx, identity, "operations.cancel", request.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(operation), true, nil
	}
	if operation.GetTarget() == nil || operation.GetTarget().GetResourceType() != "training_run" {
		return nil, false, ErrInvalidTransition
	}
	run, storedRunRow, err := getRunTx(ctx, tx, identity, operation.GetTarget().GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if terminalRun(run.GetState()) {
		return nil, false, ErrInvalidTransition
	}
	if err = reconcileSchedulerCancellation(ctx, tx, identity, storedRunRow, at); err != nil {
		return nil, false, err
	}
	lockedOperation, _, err := getOperationTx(ctx, tx, identity, request.GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if lockedOperation.GetDone() {
		if err = insertAudit(ctx, tx, identity, "operations.cancel.noop", lockedOperation.GetOperationId(), digest, at); err != nil {
			return nil, false, err
		}
		if err = recordIdempotency(ctx, tx, identity, "operations.cancel", request.GetContext().GetIdempotencyKey(), digest, lockedOperation.GetOperationId(), at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(lockedOperation), true, nil
	}
	if lockedOperation.GetEtag() != request.GetEtag() || lockedOperation.GetTarget() == nil || lockedOperation.GetTarget().GetName() != run.GetName() {
		return nil, false, ErrRevisionConflict
	}
	operation = lockedOperation
	runRevision := run.GetRevision() + 1
	result, err := tx.ExecContext(ctx, `UPDATE training_runs SET revision=$4,etag=$5,state=$6 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$7`, identity.TenantID, identity.ProjectID, run.GetName(), runRevision, resourceETag(run.GetName(), runRevision), int32(trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING), storedRunRow.revision)
	if err != nil {
		return nil, false, err
	}
	if err = requireOne(result); err != nil {
		return nil, false, err
	}
	run, _, err = getRunTx(ctx, tx, identity, run.GetName(), false)
	if err != nil {
		return nil, false, err
	}
	if err = updateOperationTarget(ctx, tx, identity, operation.GetOperationId(), run, "CANCELLING", false, at, sql.NullInt64{}, sql.NullInt64{}); err != nil {
		return nil, false, err
	}
	operation, _, err = getOperationTx(ctx, tx, identity, operation.GetOperationId(), false)
	if err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.CancellationRequested(identity, run, operation, request.GetReason(), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, "operations.cancel", operation.GetOperationId(), digest, at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = recordIdempotency(ctx, tx, identity, "operations.cancel", request.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}
