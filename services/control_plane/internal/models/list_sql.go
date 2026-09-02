package models

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

func (r SQLRepository) GetModel(ctx context.Context, identity Identity, name string) (*modelv1.Model, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanModel(tx.QueryRowContext(ctx, `SELECT `+modelColumns+` FROM models WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := modelProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) ListModels(ctx context.Context, identity Identity, page ModelPage) ([]*modelv1.Model, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + modelColumns + ` FROM models WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != modelv1.ModelState_MODEL_STATE_UNSPECIFIED {
		query += fmt.Sprintf(" AND state=$%d", next)
		args = append(args, int32(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (create_time,name)<($%d,$%d)", next, next+1)
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += fmt.Sprintf(" ORDER BY create_time DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []modelRow
	for rows.Next() {
		v, scanErr := scanModel(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, v)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	more := len(stored) > page.Limit
	if more {
		stored = stored[:page.Limit]
	}
	values := make([]*modelv1.Model, 0, len(stored))
	for _, v := range stored {
		item, mapErr := modelProto(ctx, tx, v)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(item))
	}
	token := ""
	if more && len(stored) > 0 {
		last := stored[len(stored)-1]
		token, err = r.Pagination.encode(pageToken{Kind: "models", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, token, readAt.UTC(), nil
}

func (r SQLRepository) GetModelRelease(ctx context.Context, identity Identity, name string) (*modelv1.ModelRelease, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := releaseProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) ListModelReleases(ctx context.Context, identity Identity, page ReleasePage) ([]*modelv1.ModelRelease, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + releaseColumns + ` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND model_name=$3`
	args := []any{identity.TenantID, identity.ProjectID, page.Parent}
	next := 4
	if page.Stage != modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_UNSPECIFIED {
		query += fmt.Sprintf(" AND stage=$%d", next)
		args = append(args, int32(page.Stage))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (create_time,name)<($%d,$%d)", next, next+1)
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += fmt.Sprintf(" ORDER BY create_time DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []releaseRow
	for rows.Next() {
		v, scanErr := scanRelease(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, v)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	more := len(stored) > page.Limit
	if more {
		stored = stored[:page.Limit]
	}
	values := make([]*modelv1.ModelRelease, 0, len(stored))
	for _, v := range stored {
		item, mapErr := releaseProto(ctx, tx, v)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(item))
	}
	token := ""
	if more && len(stored) > 0 {
		last := stored[len(stored)-1]
		token, err = r.Pagination.encode(pageToken{Kind: "model-releases", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, token, readAt.UTC(), nil
}
