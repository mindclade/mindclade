package database

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	"google.golang.org/protobuf/types/known/durationpb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

var ErrTenantScopeRequired = errors.New("database tenant scope is required")

// Transaction is intentionally opaque: repositories expose no transaction object to workers.
type Transaction interface {
	AfterCommit(func(context.Context) error)
}

type Runner interface {
	WithinTransaction(context.Context, func(Transaction) error) error
}

// NoExternalEffects documents the kernel rule: callbacks schedule delivery after commit only.
type NoExternalEffects struct{}

func (NoExternalEffects) AfterCommit(func(context.Context) error) {}

// BeginTenantTx opens a transaction and binds its PostgreSQL RLS scope before
// any application query can execute. set_config(..., true) is transaction-local,
// so a pooled connection cannot leak one tenant's scope into the next request.
func BeginTenantTx(ctx context.Context, db *sql.DB, tenantID string, options *sql.TxOptions) (*sql.Tx, error) {
	if db == nil {
		return nil, errors.New("database handle is required")
	}
	if err := ValidateTenantID(tenantID); err != nil {
		return nil, err
	}
	tx, err := db.BeginTx(ctx, options)
	if err != nil {
		return nil, fmt.Errorf("begin tenant transaction: %w", err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id', $1, true), set_config('row_security', 'on', true)`, tenantID); err != nil {
		_ = tx.Rollback()
		return nil, fmt.Errorf("bind tenant transaction scope: %w", err)
	}
	return tx, nil
}

// ValidateTenantID rejects values that cannot be a durable tenant identity.
// The value is always passed as a SQL parameter; this additionally bounds the
// session-setting value and rejects invisible separators in logs and evidence.
func ValidateTenantID(tenantID string) error {
	if tenantID == "" || len(tenantID) > 255 || strings.TrimSpace(tenantID) != tenantID || strings.ContainsRune(tenantID, '\x00') {
		return ErrTenantScopeRequired
	}
	return nil
}

// StoreArtifactRef inserts one normalized, tenant-scoped protobuf submessage.
// A NULL foreign key represents absent protobuf message presence.
func StoreArtifactRef(ctx context.Context, tx *sql.Tx, tenantID string, value *artifactv1.ArtifactRef) (sql.NullInt64, error) {
	if value == nil {
		return sql.NullInt64{}, nil
	}
	if value.GetDigest() == "" || value.GetMediaType() == "" || value.GetSizeBytes() < 0 {
		return sql.NullInt64{}, errors.New("artifact reference requires digest, media type, and non-negative size")
	}
	var id int64
	err := tx.QueryRowContext(ctx, `
INSERT INTO artifact_references (
  tenant_id, digest, media_type, size_bytes, artifact_kind, schema_id,
  integrity_digest, uri, schema_version
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
RETURNING id`, tenantID, value.GetDigest(), value.GetMediaType(), value.GetSizeBytes(),
		value.GetArtifactKind(), value.GetSchemaId(), value.GetIntegrityDigest(), value.GetUri(),
		value.GetSchemaVersion()).Scan(&id)
	if err != nil {
		return sql.NullInt64{}, fmt.Errorf("store artifact reference: %w", err)
	}
	return sql.NullInt64{Int64: id, Valid: true}, nil
}

// LoadArtifactRef reconstructs every field and preserves absent-message
// presence when the owning foreign key is NULL.
func LoadArtifactRef(ctx context.Context, tx *sql.Tx, tenantID string, id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
	if !id.Valid {
		return nil, nil
	}
	value := new(artifactv1.ArtifactRef)
	err := tx.QueryRowContext(ctx, `
SELECT digest, media_type, size_bytes, artifact_kind, schema_id,
       integrity_digest, uri, schema_version
FROM artifact_references WHERE tenant_id = $1 AND id = $2`, tenantID, id.Int64).Scan(
		&value.Digest, &value.MediaType, &value.SizeBytes, &value.ArtifactKind,
		&value.SchemaId, &value.IntegrityDigest, &value.Uri, &value.SchemaVersion,
	)
	if err != nil {
		return nil, fmt.Errorf("load artifact reference: %w", err)
	}
	return value, nil
}

// StoreErrorDetail normalizes the generated error and its ordered violations.
func StoreErrorDetail(ctx context.Context, tx *sql.Tx, tenantID string, value *commonv1.ErrorDetail) (sql.NullInt64, error) {
	if value == nil {
		return sql.NullInt64{}, nil
	}
	if value.GetCode() == commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED {
		return sql.NullInt64{}, errors.New("error detail requires a typed error code")
	}
	var (
		subjectPresent                                        bool
		subjectType, subjectID, subjectTenant, subjectProject string
		subjectVersion                                        int64
		retrySeconds                                          sql.NullInt64
		retryNanos                                            sql.NullInt32
	)
	if subject := value.GetSubject(); subject != nil {
		subjectPresent = true
		subjectType, subjectID = subject.GetResourceType(), subject.GetResourceId()
		subjectTenant, subjectProject = subject.GetTenantId(), subject.GetProjectId()
		subjectVersion = subject.GetResourceVersion()
	}
	if retryAfter := value.GetRetryAfter(); retryAfter != nil {
		if err := retryAfter.CheckValid(); err != nil {
			return sql.NullInt64{}, fmt.Errorf("error retry_after: %w", err)
		}
		retrySeconds = sql.NullInt64{Int64: retryAfter.GetSeconds(), Valid: true}
		retryNanos = sql.NullInt32{Int32: retryAfter.GetNanos(), Valid: true}
	}
	var id int64
	err := tx.QueryRowContext(ctx, `
INSERT INTO error_details (
  tenant_id, code, message, retry_class, subject_present,
  subject_resource_type, subject_resource_id, subject_tenant_id,
  subject_project_id, subject_resource_version, retry_after_seconds,
  retry_after_nanos, error_id
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
RETURNING id`, tenantID, int32(value.GetCode()), value.GetMessage(), int32(value.GetRetryClass()),
		subjectPresent, subjectType, subjectID, subjectTenant, subjectProject, subjectVersion,
		retrySeconds, retryNanos, value.GetErrorId()).Scan(&id)
	if err != nil {
		return sql.NullInt64{}, fmt.Errorf("store error detail: %w", err)
	}
	for ordinal, violation := range value.GetFieldViolations() {
		if violation == nil {
			return sql.NullInt64{}, errors.New("error field violation cannot be nil")
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO error_field_violations (tenant_id, error_detail_id, ordinal, field_path, description) VALUES ($1,$2,$3,$4,$5)`, tenantID, id, ordinal, violation.GetField(), violation.GetDescription()); err != nil {
			return sql.NullInt64{}, fmt.Errorf("store error field violation: %w", err)
		}
	}
	for ordinal, violation := range value.GetPreconditionViolations() {
		if violation == nil {
			return sql.NullInt64{}, errors.New("error precondition violation cannot be nil")
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO error_precondition_violations (tenant_id, error_detail_id, ordinal, violation_type, subject, description) VALUES ($1,$2,$3,$4,$5,$6)`, tenantID, id, ordinal, violation.GetType(), violation.GetSubject(), violation.GetDescription()); err != nil {
			return sql.NullInt64{}, fmt.Errorf("store error precondition violation: %w", err)
		}
	}
	return sql.NullInt64{Int64: id, Valid: true}, nil
}

// LoadErrorDetail reconstructs scalar presence and both repeated violation
// lists in ordinal order.
func LoadErrorDetail(ctx context.Context, tx *sql.Tx, tenantID string, id sql.NullInt64) (*commonv1.ErrorDetail, error) {
	if !id.Valid {
		return nil, nil
	}
	var (
		code, retryClass                                      int32
		subjectPresent                                        bool
		subjectType, subjectID, subjectTenant, subjectProject string
		subjectVersion                                        int64
		retrySeconds                                          sql.NullInt64
		retryNanos                                            sql.NullInt32
	)
	value := new(commonv1.ErrorDetail)
	err := tx.QueryRowContext(ctx, `
SELECT code, message, retry_class, subject_present, subject_resource_type,
       subject_resource_id, subject_tenant_id, subject_project_id,
       subject_resource_version, retry_after_seconds, retry_after_nanos, error_id
FROM error_details WHERE tenant_id = $1 AND id = $2`, tenantID, id.Int64).Scan(
		&code, &value.Message, &retryClass, &subjectPresent, &subjectType, &subjectID,
		&subjectTenant, &subjectProject, &subjectVersion, &retrySeconds, &retryNanos,
		&value.ErrorId,
	)
	if err != nil {
		return nil, fmt.Errorf("load error detail: %w", err)
	}
	value.Code = commonv1.ErrorCode(code)
	value.RetryClass = commonv1.RetryClass(retryClass)
	if subjectPresent {
		value.Subject = &commonv1.ResourceRef{
			ResourceType: subjectType, ResourceId: subjectID, TenantId: subjectTenant,
			ProjectId: subjectProject, ResourceVersion: subjectVersion,
		}
	}
	if retrySeconds.Valid != retryNanos.Valid {
		return nil, errors.New("persisted error retry_after presence is inconsistent")
	}
	if retrySeconds.Valid {
		value.RetryAfter = &durationpb.Duration{Seconds: retrySeconds.Int64, Nanos: retryNanos.Int32}
		if err := value.RetryAfter.CheckValid(); err != nil {
			return nil, fmt.Errorf("persisted error retry_after: %w", err)
		}
	}
	fieldRows, err := tx.QueryContext(ctx, `SELECT field_path, description FROM error_field_violations WHERE tenant_id = $1 AND error_detail_id = $2 ORDER BY ordinal`, tenantID, id.Int64)
	if err != nil {
		return nil, fmt.Errorf("load error field violations: %w", err)
	}
	for fieldRows.Next() {
		violation := new(commonv1.FieldViolation)
		if err = fieldRows.Scan(&violation.Field, &violation.Description); err != nil {
			_ = fieldRows.Close()
			return nil, err
		}
		value.FieldViolations = append(value.FieldViolations, violation)
	}
	if err = fieldRows.Err(); err != nil {
		_ = fieldRows.Close()
		return nil, err
	}
	if err = fieldRows.Close(); err != nil {
		return nil, err
	}
	preconditionRows, err := tx.QueryContext(ctx, `SELECT violation_type, subject, description FROM error_precondition_violations WHERE tenant_id = $1 AND error_detail_id = $2 ORDER BY ordinal`, tenantID, id.Int64)
	if err != nil {
		return nil, fmt.Errorf("load error precondition violations: %w", err)
	}
	defer func() { _ = preconditionRows.Close() }()
	for preconditionRows.Next() {
		violation := new(commonv1.PreconditionViolation)
		if err = preconditionRows.Scan(&violation.Type, &violation.Subject, &violation.Description); err != nil {
			return nil, err
		}
		value.PreconditionViolations = append(value.PreconditionViolations, violation)
	}
	if err = preconditionRows.Err(); err != nil {
		return nil, err
	}
	return value, nil
}
