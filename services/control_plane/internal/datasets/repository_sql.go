package datasets

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Pagination == nil {
		return errors.New("dataset SQL repository requires database and pagination codec")
	}
	return nil
}

type datasetRow struct {
	tenant, project, name, uid, etag, display, classification, current string
	revision                                                           int64
	state                                                              int32
	created                                                            time.Time
	updated, deleted                                                   sql.NullTime
}

const datasetColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,state,policy_classification,create_time,update_time,delete_time,current_release_name`

type scanner interface{ Scan(...any) error }

func scanDataset(row scanner) (datasetRow, error) {
	var value datasetRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.display, &value.state, &value.classification, &value.created, &value.updated, &value.deleted, &value.current)
	return value, err
}

func datasetProto(ctx context.Context, tx *sql.Tx, row datasetRow) (*datasetv1.Dataset, error) {
	value := &datasetv1.Dataset{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantName: "tenants/" + row.tenant, ProjectName: "tenants/" + row.tenant + "/projects/" + row.project, DisplayName: row.display, State: datasetv1.DatasetState(row.state), PolicyClassification: row.classification, CreateTime: timestamppb.New(row.created.UTC()), CurrentReleaseName: row.current}
	if row.updated.Valid {
		value.UpdateTime = timestamppb.New(row.updated.Time.UTC())
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	value.Labels = map[string]string{}
	rows, err := tx.QueryContext(ctx, `SELECT label_key,label_value FROM dataset_labels WHERE tenant_id=$1 AND project_id=$2 AND dataset_name=$3 ORDER BY label_key`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var key, item string
		if err = rows.Scan(&key, &item); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.Labels[key] = item
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	value.Annotations = map[string]string{}
	rows, err = tx.QueryContext(ctx, `SELECT annotation_key,annotation_value FROM dataset_annotations WHERE tenant_id=$1 AND project_id=$2 AND dataset_name=$3 ORDER BY annotation_key`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var key, item string
		if err = rows.Scan(&key, &item); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.Annotations[key] = item
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	return value, nil
}

func (r SQLRepository) GetDataset(ctx context.Context, identity Identity, name string) (*datasetv1.Dataset, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := datasetProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) ListDatasets(ctx context.Context, identity Identity, page DatasetPage) ([]*datasetv1.Dataset, string, time.Time, error) {
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
	query := `SELECT ` + datasetColumns + ` FROM datasets WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != datasetv1.DatasetState_DATASET_STATE_UNSPECIFIED {
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
	var stored []datasetRow
	for rows.Next() {
		item, scanErr := scanDataset(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*datasetv1.Dataset, 0, len(stored))
	for _, item := range stored {
		value, mapErr := datasetProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(value))
	}
	token := ""
	if hasMore && len(stored) > 0 {
		last := stored[len(stored)-1]
		token, err = r.Pagination.encode(pageToken{Kind: "datasets", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, token, readAt.UTC(), nil
}

type releaseRow struct {
	tenant, project, name, uid, datasetName, releaseID, etag, classification, reason string
	revision                                                                         int64
	state                                                                            int32
	manifest, parent, policy                                                         sql.NullInt64
	created                                                                          time.Time
	published, revoked                                                               sql.NullTime
}

const releaseColumns = `tenant_id,project_id,name,uid,dataset_name,release_id,revision,etag,state,manifest_ref_id,parent_release_ref_id,use_policy_ref_id,policy_classification,create_time,publish_time,revoke_time,revocation_reason`

func scanRelease(row scanner) (releaseRow, error) {
	var v releaseRow
	err := row.Scan(&v.tenant, &v.project, &v.name, &v.uid, &v.datasetName, &v.releaseID, &v.revision, &v.etag, &v.state, &v.manifest, &v.parent, &v.policy, &v.classification, &v.created, &v.published, &v.revoked, &v.reason)
	return v, err
}

func releaseProto(ctx context.Context, tx *sql.Tx, row releaseRow) (*datasetv1.DatasetRelease, error) {
	manifest, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.manifest)
	if err != nil {
		return nil, err
	}
	parent, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.parent)
	if err != nil {
		return nil, err
	}
	policy, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.policy)
	if err != nil {
		return nil, err
	}
	value := &datasetv1.DatasetRelease{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantName: "tenants/" + row.tenant, ProjectName: "tenants/" + row.tenant + "/projects/" + row.project, DatasetName: row.datasetName, ReleaseId: row.releaseID, State: datasetv1.DatasetReleaseState(row.state), Manifest: manifest, ParentRelease: parent, UsePolicy: policy, PolicyClassification: row.classification, CreateTime: timestamppb.New(row.created.UTC()), RevocationReason: row.reason}
	if row.published.Valid {
		value.PublishTime = timestamppb.New(row.published.Time.UTC())
	}
	if row.revoked.Valid {
		value.RevokeTime = timestamppb.New(row.revoked.Time.UTC())
	}
	rows, err := tx.QueryContext(ctx, `SELECT digest,subject_digest,evidence_kind,policy_digest FROM dataset_release_qualification_evidence WHERE tenant_id=$1 AND project_id=$2 AND release_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	defer func() { _ = platformdb.CloseRows(rows) }()
	for rows.Next() {
		item := new(artifactv1.EvidenceRef)
		if err = rows.Scan(&item.Digest, &item.SubjectDigest, &item.EvidenceKind, &item.PolicyDigest); err != nil {
			return nil, err
		}
		value.QualificationEvidence = append(value.QualificationEvidence, item)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	return value, nil
}

func (r SQLRepository) GetDatasetRelease(ctx context.Context, identity Identity, name string) (*datasetv1.DatasetRelease, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
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

func (r SQLRepository) ListDatasetReleases(ctx context.Context, identity Identity, page ReleasePage) ([]*datasetv1.DatasetRelease, string, time.Time, error) {
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
	query := `SELECT ` + releaseColumns + ` FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND dataset_name=$3`
	args := []any{identity.TenantID, identity.ProjectID, page.Parent}
	next := 4
	if page.State != datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_UNSPECIFIED {
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
	var stored []releaseRow
	for rows.Next() {
		item, scanErr := scanRelease(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*datasetv1.DatasetRelease, 0, len(stored))
	for _, item := range stored {
		value, mapErr := releaseProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(value))
	}
	token := ""
	if hasMore && len(stored) > 0 {
		last := stored[len(stored)-1]
		token, err = r.Pagination.encode(pageToken{Kind: "dataset-releases", Tenant: identity.TenantID, Project: identity.ProjectID, Parent: page.Parent, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, token, readAt.UTC(), nil
}
