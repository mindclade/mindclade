package artifacts

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"time"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	objectstorage "github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
)

const maxStagingReceiptLifetime = 7 * 24 * time.Hour

// SQLGCSStagingReceiptStore binds durable SQL verification evidence to bytes
// in immutable content-addressed object storage. It intentionally exposes no
// provider locator and performs no authentication of its own.
type SQLGCSStagingReceiptStore struct {
	DB      *sql.DB
	Objects objectstorage.ObjectStore
	Now     func() time.Time
}

var _ StagingReceiptStore = SQLGCSStagingReceiptStore{}

// RecordVerifiedObject is called by the transfer plane after ObjectStore.Put
// returns. It is deterministic and retry-safe for the same immutable provider
// generation. The receipt is an opaque digest, not a storage URI.
func (s SQLGCSStagingReceiptStore) RecordVerifiedObject(ctx context.Context, identity Identity, object objectstorage.Object, verifiedAt, expireAt time.Time) (string, error) {
	if s.DB == nil || s.Objects == nil || validateIdentity(identity) != nil || object.TenantID != identity.TenantID || !validDigest(object.Digest) || object.Size < 0 || object.Generation <= 0 || verifiedAt.IsZero() || !expireAt.After(verifiedAt) || expireAt.After(verifiedAt.Add(maxStagingReceiptLifetime)) {
		return "", ErrStagingUnverified
	}
	// Object is an ordinary value and is therefore not itself proof that Put
	// completed. Re-pin the provider generation and revalidate all bytes before
	// creating durable verification evidence.
	if err := s.Objects.Verify(ctx, object); err != nil {
		return "", ErrStagingUnverified
	}
	receipt := stagingReceiptDigest(identity, object, verifiedAt, expireAt)
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, identity.TenantID, nil)
	if err != nil {
		return "", err
	}
	defer func() { _ = tx.Rollback() }()
	if err = lockStagingReceipt(ctx, tx, identity, receipt); err != nil {
		return "", err
	}
	result, err := tx.ExecContext(ctx, `INSERT INTO artifact_staging_receipts (tenant_id,project_id,receipt_digest,artifact_digest,size_bytes,object_generation,state,verified_at,expire_time) VALUES ($1,$2,$3,$4,$5,$6,'VERIFIED',$7,$8) ON CONFLICT (tenant_id,project_id,receipt_digest) DO UPDATE SET verified_at=GREATEST(artifact_staging_receipts.verified_at,EXCLUDED.verified_at),expire_time=GREATEST(artifact_staging_receipts.expire_time,EXCLUDED.expire_time) WHERE artifact_staging_receipts.artifact_digest=EXCLUDED.artifact_digest AND artifact_staging_receipts.size_bytes=EXCLUDED.size_bytes AND artifact_staging_receipts.object_generation=EXCLUDED.object_generation AND artifact_staging_receipts.state='VERIFIED'`, identity.TenantID, identity.ProjectID, receipt, object.Digest, object.Size, object.Generation, verifiedAt.UTC(), expireAt.UTC())
	if err != nil {
		return "", err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		if rowsErr != nil {
			return "", rowsErr
		}
		return "", ErrStagingUnverified
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return receipt, nil
}

func stagingReceiptDigest(identity Identity, object objectstorage.Object, verifiedAt, expireAt time.Time) string {
	digestInput := fmt.Sprintf("v2\x00%d:%s\x00%d:%s\x00%s\x00%d\x00%d\x00%s\x00%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, object.Digest, object.Size, object.Generation, verifiedAt.UTC().Format(time.RFC3339Nano), expireAt.UTC().Format(time.RFC3339Nano))
	value := sha256.Sum256([]byte(digestInput))
	return "sha256:" + hex.EncodeToString(value[:])
}

func (s SQLGCSStagingReceiptStore) VerifyReceipt(ctx context.Context, identity Identity, receipt string, artifact *artifactv1.ArtifactRef) error {
	if s.DB == nil || s.Objects == nil || validateIdentity(identity) != nil || !validDigest(receipt) || validateArtifact(identity, artifact, true) != nil {
		return ErrStagingUnverified
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return ErrStagingUnverified
	}
	defer func() { _ = tx.Rollback() }()
	var digest, state string
	var size, generation int64
	var expireAt time.Time
	err = tx.QueryRowContext(ctx, `SELECT artifact_digest,size_bytes,object_generation,state,expire_time FROM artifact_staging_receipts WHERE tenant_id=$1 AND project_id=$2 AND receipt_digest=$3`, identity.TenantID, identity.ProjectID, receipt).Scan(&digest, &size, &generation, &state, &expireAt)
	now := time.Now().UTC()
	if s.Now != nil {
		now = s.Now().UTC()
	}
	if err != nil || state != "VERIFIED" || generation <= 0 || digest != artifact.GetDigest() || size != artifact.GetSizeBytes() || !expireAt.After(now) {
		return ErrStagingUnverified
	}
	if err = tx.Commit(); err != nil {
		return ErrStagingUnverified
	}
	if err = s.Objects.Verify(ctx, objectstorage.Object{TenantID: identity.TenantID, Digest: digest, Size: size, Generation: generation}); err != nil {
		return ErrStagingUnverified
	}
	return nil
}

func (s SQLGCSStagingReceiptStore) QuarantineReceipt(ctx context.Context, identity Identity, receipt, reason string, at time.Time) error {
	if s.DB == nil || validateIdentity(identity) != nil || !validDigest(receipt) || !reasonCodePattern.MatchString(reason) || at.IsZero() {
		return ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, s.DB, identity.TenantID, nil)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if err = lockStagingReceipt(ctx, tx, identity, receipt); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE artifact_staging_receipts AS receipt SET state='QUARANTINED',quarantine_time=$5,quarantine_reason=$4 WHERE tenant_id=$1 AND project_id=$2 AND receipt_digest=$3 AND state='VERIFIED' AND NOT EXISTS (SELECT 1 FROM artifact_catalog_entries AS artifact WHERE artifact.tenant_id=receipt.tenant_id AND artifact.project_id=receipt.project_id AND artifact.staging_receipt_digest=receipt.receipt_digest)`, identity.TenantID, identity.ProjectID, receipt, reason, at.UTC())
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count != 1 {
		return ErrInvalidTransition
	}
	return tx.Commit()
}
