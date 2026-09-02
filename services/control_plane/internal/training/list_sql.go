package training

import (
	"context"
	"database/sql"
	"strconv"
	"time"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

func (r SQLRepository) ListTrainingRuns(ctx context.Context, identity Identity, page RunPage) ([]*trainingv1.TrainingRun, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readTime time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readTime); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + runColumns + ` FROM training_runs WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != trainingv1.TrainingRunState_TRAINING_RUN_STATE_UNSPECIFIED {
		query += ` AND state=$` + itoa(next)
		args = append(args, int32(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += ` AND (create_time,name)<($` + itoa(next) + `,$` + itoa(next+1) + `)`
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += ` ORDER BY create_time DESC,name DESC LIMIT $` + itoa(next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var raw []runRow
	for rows.Next() {
		row, scanErr := scanRun(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		raw = append(raw, row)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(raw) > page.Limit
	if hasMore {
		raw = raw[:page.Limit]
	}
	values := make([]*trainingv1.TrainingRun, 0, len(raw))
	for _, row := range raw {
		value, loadErr := runRowProto(ctx, tx, row)
		if loadErr != nil {
			return nil, "", time.Time{}, loadErr
		}
		values = append(values, value)
	}
	nextToken := ""
	if hasMore && len(raw) > 0 {
		last := raw[len(raw)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "training-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.createTime.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, nextToken, readTime.UTC(), nil
}

func (r SQLRepository) ListCheckpoints(ctx context.Context, identity Identity, page CheckpointPage) ([]*trainingv1.Checkpoint, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readTime time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readTime); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + checkpointColumns + ` FROM training_checkpoints WHERE tenant_id=$1 AND project_id=$2 AND training_run_name=$3`
	args := []any{identity.TenantID, identity.ProjectID, page.RunName}
	next := 4
	if page.State != trainingv1.CheckpointState_CHECKPOINT_STATE_UNSPECIFIED {
		query += ` AND state=$` + itoa(next)
		args = append(args, int32(page.State))
		next++
	}
	if page.AfterEpoch != 0 {
		query += ` AND (snapshot_epoch,name)<($` + itoa(next) + `,$` + itoa(next+1) + `)`
		args = append(args, page.AfterEpoch, page.AfterName)
		next += 2
	}
	query += ` ORDER BY snapshot_epoch DESC,name DESC LIMIT $` + itoa(next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var raw []checkpointRow
	for rows.Next() {
		row, scanErr := scanCheckpoint(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		raw = append(raw, row)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(raw) > page.Limit
	if hasMore {
		raw = raw[:page.Limit]
	}
	values := make([]*trainingv1.Checkpoint, 0, len(raw))
	for _, row := range raw {
		value, loadErr := checkpointRowProto(ctx, tx, row)
		if loadErr != nil {
			return nil, "", time.Time{}, loadErr
		}
		values = append(values, value)
	}
	nextToken := ""
	if hasMore && len(raw) > 0 {
		last := raw[len(raw)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "checkpoints", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.RunName, Filter: page.Filter, Order: page.Order, AfterID: last.epoch, AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, nextToken, readTime.UTC(), nil
}

func (r SQLRepository) ListOperations(ctx context.Context, identity Identity, page OperationPage) ([]*jobv1.Operation, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readTime time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readTime); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + operationColumns + ` FROM operations WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != jobv1.OperationState_OPERATION_STATE_UNSPECIFIED {
		query += ` AND status=$` + itoa(next)
		args = append(args, operationStateDatabase(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += ` AND (updated_at,id)<($` + itoa(next) + `,$` + itoa(next+1) + `)`
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += ` ORDER BY updated_at DESC,id DESC LIMIT $` + itoa(next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var raw []operationRow
	for rows.Next() {
		row, scanErr := scanOperation(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		raw = append(raw, row)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(raw) > page.Limit
	if hasMore {
		raw = raw[:page.Limit]
	}
	values := make([]*jobv1.Operation, 0, len(raw))
	for _, row := range raw {
		value, loadErr := operationRowProto(ctx, tx, row)
		if loadErr != nil {
			return nil, "", time.Time{}, loadErr
		}
		values = append(values, value)
	}
	nextToken := ""
	if hasMore && len(raw) > 0 {
		last := raw[len(raw)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "operations", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.updatedAt.UTC().Format(time.RFC3339Nano), AfterName: last.id})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, nextToken, readTime.UTC(), nil
}

func operationStateDatabase(state jobv1.OperationState) string {
	switch state {
	case jobv1.OperationState_OPERATION_STATE_PENDING:
		return "PENDING"
	case jobv1.OperationState_OPERATION_STATE_RUNNING:
		return "RUNNING"
	case jobv1.OperationState_OPERATION_STATE_SUCCEEDED:
		return "SUCCEEDED"
	case jobv1.OperationState_OPERATION_STATE_FAILED:
		return "FAILED"
	case jobv1.OperationState_OPERATION_STATE_CANCELLING:
		return "CANCELLING"
	case jobv1.OperationState_OPERATION_STATE_CANCELLED:
		return "CANCELLED"
	default:
		return ""
	}
}

func itoa(value int) string {
	return strconv.Itoa(value)
}
