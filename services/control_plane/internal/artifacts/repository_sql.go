package artifacts

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
	objectstorage "github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
)

const artifactEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) Committed(identity Identity, artifact *artifactv1.ArtifactRef, command *commonv1.CommandContext, sequence int64, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &artifactv1.ArtifactCommitted{Artifact: sanitizeArtifact(artifact)}
	return newArtifactEnvelope(identity, artifact, payload, command, sequence, at)
}

func (GeneratedEventFactory) Quarantined(identity Identity, artifact *artifactv1.ArtifactRef, reason string, evidence []*artifactv1.EvidenceRef, command *commonv1.CommandContext, sequence int64, at time.Time) (*commonv1.EventEnvelope, error) {
	evidenceDigest := ""
	if len(evidence) > 0 && evidence[0] != nil {
		evidenceDigest = evidence[0].GetDigest()
	}
	payload := &artifactv1.ArtifactQuarantined{SubjectDigest: artifact.GetDigest(), ReasonCode: reason, EvidenceDigest: evidenceDigest}
	return newArtifactEnvelope(identity, artifact, payload, command, sequence, at)
}

func (GeneratedEventFactory) StagingFinalized(identity Identity, uploadName string, artifact *artifactv1.ArtifactRef, receipt string, command *commonv1.CommandContext, sequence int64, verifiedAt, expireAt time.Time) (*commonv1.EventEnvelope, error) {
	payload := &artifactv1.ArtifactStagingFinalized{
		UploadName: uploadName, Artifact: sanitizeArtifact(artifact), StagingReceiptDigest: receipt,
		VerifiedAt: timestamppb.New(verifiedAt.UTC()), ExpireTime: timestamppb.New(expireAt.UTC()),
	}
	aggregateSequence, err := numconv.Int64ToUint64(sequence)
	if err != nil {
		return nil, err
	}
	if command == nil || sequence == 0 || !validDigest(receipt) || verifiedAt.IsZero() || !expireAt.After(verifiedAt) {
		return nil, ErrInvalidArgument
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	typeName := string(payload.ProtoReflect().Descriptor().FullName())
	eventIdentity := sha256.Sum256([]byte(identity.TenantID + "\x00" + identity.ProjectID + "\x00" + typeName + "\x00" + uploadName + "\x00" + strconv.FormatUint(aggregateSequence, 10) + "\x00" + command.GetRequestId()))
	identifier := "artifact-upload:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: identifier, EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(verifiedAt.UTC()), RecordedAt: timestamppb.New(verifiedAt.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(),
		Subject:       &commonv1.ResourceRef{ResourceType: "artifact_upload", ResourceId: uploadName, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: sequence, Name: uploadName, Etag: etag("artifact-upload", identity.TenantID, identity.ProjectID, uploadName, sequence)},
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		Producer: "services/control_plane/internal/artifacts", AggregateSequence: aggregateSequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: identifier, PayloadContentType: artifactEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func newArtifactEnvelope(identity Identity, artifact *artifactv1.ArtifactRef, payloadMessage proto.Message, command *commonv1.CommandContext, sequence int64, at time.Time) (*commonv1.EventEnvelope, error) {
	aggregateSequence, err := numconv.Int64ToUint64(sequence)
	if err != nil {
		return nil, err
	}
	if artifact == nil || payloadMessage == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, ErrInvalidArgument
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(payload)
	typeName := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	name := canonicalArtifactName(identity, artifact.GetDigest())
	eventIdentity := sha256.Sum256([]byte(identity.TenantID + "\x00" + identity.ProjectID + "\x00" + typeName + "\x00" + name + "\x00" + strconv.FormatUint(aggregateSequence, 10) + "\x00" + command.GetRequestId()))
	identifier := "artifact:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: identifier, EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(),
		Subject:       &commonv1.ResourceRef{ResourceType: "artifact", ResourceId: artifact.GetDigest(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: sequence, Name: name, Etag: etag("artifact", identity.TenantID, identity.ProjectID, artifact.GetDigest(), sequence)},
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/artifacts", AggregateSequence: aggregateSequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: identifier, PayloadContentType: artifactEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

type commandReceipt struct {
	kind string
	id   string
}

func lockAndCheckReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string) (commandReceipt, bool, error) {
	lockKey := fmt.Sprintf("%d:%s:%d:%s:artifact:%s:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, action, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return commandReceipt{}, false, err
	}
	var storedDigest string
	var result commandReceipt
	err := tx.QueryRowContext(ctx, `SELECT request_digest,response_kind,response_id FROM artifact_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND action=$3 AND idempotency_key=$4`, identity.TenantID, identity.ProjectID, action, key).Scan(&storedDigest, &result.kind, &result.id)
	if errors.Is(err, sql.ErrNoRows) {
		return commandReceipt{}, false, nil
	}
	if err != nil {
		return commandReceipt{}, false, err
	}
	if subtle.ConstantTimeCompare([]byte(storedDigest), []byte(digest)) != 1 {
		return commandReceipt{}, false, ErrIdempotencyConflict
	}
	return result, true, nil
}

func insertReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, kind, id string, at time.Time) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO artifact_command_receipts (tenant_id,project_id,action,idempotency_key,request_digest,response_kind,response_id,create_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, action, key, digest, kind, id, at.UTC())
	return err
}

func (r SQLRepository) replayReceipt(ctx context.Context, identity Identity, action, key, digest string) (commandReceipt, bool, error) {
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return commandReceipt{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	result, ok, err := lockAndCheckReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return commandReceipt{}, false, err
	}
	if err = tx.Commit(); err != nil {
		return commandReceipt{}, false, err
	}
	return result, ok, nil
}

type catalogRow struct {
	artifact         *artifactv1.ArtifactRef
	state            string
	revision         int64
	etag             string
	stagingReceipt   string
	quarantineReason string
	createTime       time.Time
	updateTime       time.Time
}

func scanCatalog(scanner interface{ Scan(...any) error }) (catalogRow, error) {
	row := catalogRow{artifact: new(artifactv1.ArtifactRef)}
	err := scanner.Scan(&row.artifact.Digest, &row.artifact.MediaType, &row.artifact.SizeBytes, &row.artifact.ArtifactKind, &row.artifact.SchemaId, &row.artifact.IntegrityDigest, &row.artifact.SchemaVersion, &row.state, &row.revision, &row.etag, &row.stagingReceipt, &row.quarantineReason, &row.createTime, &row.updateTime)
	return row, err
}

const catalogColumns = `digest,media_type,size_bytes,artifact_kind,schema_id,integrity_digest,schema_version,state,revision,etag,staging_receipt_digest,quarantine_reason,create_time,update_time`

func getCatalogTx(ctx context.Context, tx *sql.Tx, identity Identity, digest string, forUpdate bool) (catalogRow, error) {
	query := `SELECT ` + catalogColumns + ` FROM artifact_catalog_entries WHERE tenant_id=$1 AND project_id=$2 AND digest=$3`
	if forUpdate {
		query += ` FOR UPDATE`
	}
	row, err := scanCatalog(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, digest))
	if errors.Is(err, sql.ErrNoRows) {
		return catalogRow{}, ErrNotFound
	}
	return row, err
}

func (r SQLRepository) GetArtifact(ctx context.Context, identity Identity, digest string) (*artifactv1.ArtifactRef, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := getCatalogTx(ctx, tx, identity, digest, false)
	if err != nil {
		return nil, time.Time{}, err
	}
	if err = tx.Commit(); err != nil {
		return nil, time.Time{}, err
	}
	return sanitizeArtifact(row.artifact), row.updateTime.UTC(), nil
}

func (r SQLRepository) ListArtifacts(ctx context.Context, identity Identity, page ArtifactPage) ([]*artifactv1.ArtifactRef, *ArtifactCursor, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, nil, time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, nil, time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var after any
	if !page.AfterTime.IsZero() {
		after = page.AfterTime.UTC()
	}
	rows, err := tx.QueryContext(ctx, `SELECT `+catalogColumns+` FROM artifact_catalog_entries WHERE tenant_id=$1 AND project_id=$2 AND ($3='' OR state=$3) AND ($4::timestamptz IS NULL OR (create_time,digest)<($4,$5)) ORDER BY create_time DESC,digest DESC LIMIT $6`, identity.TenantID, identity.ProjectID, page.State, after, page.AfterDigest, page.Limit+1)
	if err != nil {
		return nil, nil, time.Time{}, err
	}
	defer func() { _ = rows.Close() }()
	values := make([]*artifactv1.ArtifactRef, 0, page.Limit)
	var cursor *ArtifactCursor
	var lastCreateTime time.Time
	var lastDigest string
	hasMore := false
	for rows.Next() {
		row, scanErr := scanCatalog(rows)
		if scanErr != nil {
			return nil, nil, time.Time{}, scanErr
		}
		if len(values) == page.Limit {
			hasMore = true
			break
		}
		values = append(values, sanitizeArtifact(row.artifact))
		lastCreateTime = row.createTime
		lastDigest = row.artifact.GetDigest()
	}
	if err = rows.Err(); err != nil {
		return nil, nil, time.Time{}, err
	}
	if hasMore {
		cursor = &ArtifactCursor{AfterTime: lastCreateTime, AfterDigest: lastDigest}
	}
	readAt := time.Now().UTC()
	if err = tx.QueryRowContext(ctx, `SELECT statement_timestamp()`).Scan(&readAt); err != nil {
		return nil, nil, time.Time{}, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, time.Time{}, err
	}
	return values, cursor, readAt, nil
}

func (r SQLRepository) ResolveArtifactAlias(ctx context.Context, identity Identity, alias string) (*artifactv1.ArtifactRef, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var digest string
	err = tx.QueryRowContext(ctx, `SELECT digest FROM artifact_aliases WHERE tenant_id=$1 AND project_id=$2 AND alias=$3`, identity.TenantID, identity.ProjectID, alias).Scan(&digest)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	row, err := getCatalogTx(ctx, tx, identity, digest, false)
	if err != nil {
		return nil, err
	}
	if row.state != "COMMITTED" {
		return nil, ErrInvalidTransition
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return sanitizeArtifact(row.artifact), nil
}

func (r SQLRepository) CommitArtifact(ctx context.Context, identity Identity, command *artifactv1.CommitArtifactCommand, requestDigest string, at time.Time) (*artifactv1.ArtifactRef, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetArtifact() == nil || command.GetContext().GetCanonicalRequestDigest() != requestDigest || !validDigest(requestDigest) {
		return nil, false, ErrInvalidArgument
	}
	action, key := "artifact.commit", command.GetContext().GetIdempotencyKey()
	if receipt, replay, err := r.replayReceipt(ctx, identity, action, key, requestDigest); err != nil {
		return nil, false, err
	} else if replay {
		if receipt.kind != "ARTIFACT" {
			return nil, false, ErrConflict
		}
		value, _, err := r.GetArtifact(ctx, identity, receipt.id)
		return value, true, err
	}
	if err := r.Staging.Verify(ctx, identity, command.GetStagingReceiptDigest(), sanitizeArtifact(command.GetArtifact())); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, receiptErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); receiptErr != nil {
		return nil, false, receiptErr
	} else if replay {
		row, loadErr := getCatalogTx(ctx, tx, identity, receipt.id, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return sanitizeArtifact(row.artifact), true, nil
	}
	artifact := sanitizeArtifact(command.GetArtifact())
	// The expensive provider read happens before the transaction. Re-lock and
	// recheck its durable receipt here so quarantine/expiry cannot race the
	// catalog mutation after the bytes were verified.
	if err = verifyStagingReceiptTx(ctx, tx, identity, command.GetStagingReceiptDigest(), artifact); err != nil {
		return nil, false, err
	}
	row, err := getCatalogTx(ctx, tx, identity, artifact.GetDigest(), true)
	if err == nil {
		if row.state != "COMMITTED" || !proto.Equal(row.artifact, artifact) {
			return nil, false, ErrConflict
		}
		if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "ARTIFACT", artifact.GetDigest(), at); err != nil {
			return nil, false, err
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return sanitizeArtifact(row.artifact), true, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return nil, false, err
	}
	revision := int64(1)
	artifactETag := etag("artifact", identity.TenantID, identity.ProjectID, artifact.GetDigest(), revision)
	_, err = tx.ExecContext(ctx, `INSERT INTO artifact_catalog_entries (tenant_id,project_id,digest,media_type,size_bytes,artifact_kind,schema_id,integrity_digest,schema_version,staging_receipt_digest,state,revision,etag,create_time,update_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'COMMITTED',$11,$12,$13,$13)`, identity.TenantID, identity.ProjectID, artifact.GetDigest(), artifact.GetMediaType(), artifact.GetSizeBytes(), artifact.GetArtifactKind(), artifact.GetSchemaId(), artifact.GetIntegrityDigest(), artifact.GetSchemaVersion(), command.GetStagingReceiptDigest(), revision, artifactETag, at.UTC())
	if err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.Committed(identity, artifact, command.GetContext(), revision, at)
	if err != nil {
		return nil, false, err
	}
	if err = insertArtifactOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "ARTIFACT", artifact.GetDigest(), at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return sanitizeArtifact(artifact), false, nil
}

func verifyStagingReceiptTx(ctx context.Context, tx *sql.Tx, identity Identity, receipt string, artifact *artifactv1.ArtifactRef) error {
	if err := lockStagingReceipt(ctx, tx, identity, receipt); err != nil {
		return err
	}
	var generation int64
	err := tx.QueryRowContext(ctx, `SELECT object_generation FROM artifact_staging_receipts WHERE tenant_id=$1 AND project_id=$2 AND receipt_digest=$3 AND artifact_digest=$4 AND size_bytes=$5 AND state='VERIFIED' AND expire_time>statement_timestamp() FOR SHARE`, identity.TenantID, identity.ProjectID, receipt, artifact.GetDigest(), artifact.GetSizeBytes()).Scan(&generation)
	if errors.Is(err, sql.ErrNoRows) {
		return ErrStagingUnverified
	}
	if err != nil {
		return err
	}
	if generation <= 0 {
		return ErrStagingUnverified
	}
	return nil
}

func lockStagingReceipt(ctx context.Context, tx *sql.Tx, identity Identity, receipt string) error {
	key := fmt.Sprintf("%d:%s:%d:%s:artifact-staging:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, receipt)
	_, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, key)
	return err
}

func (r SQLRepository) QuarantineArtifact(ctx context.Context, identity Identity, request *internalartifactv1.QuarantineArtifactRequest, requestDigest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	commandContext := request.GetContext()
	action, key := "artifact.quarantine", commandContext.GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, receiptErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); receiptErr != nil {
		return nil, false, receiptErr
	} else if replay {
		operation, loadErr := loadArtifactOperation(ctx, tx, identity, receipt.id)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return operation, true, nil
	}
	row, err := getCatalogTx(ctx, tx, identity, request.GetArtifact().GetDigest(), true)
	if err != nil {
		return nil, false, err
	}
	if row.state != "COMMITTED" {
		return nil, false, ErrInvalidTransition
	}
	if !proto.Equal(row.artifact, sanitizeArtifact(request.GetArtifact())) {
		return nil, false, ErrConflict
	}
	revision := row.revision + 1
	artifactETag := etag("artifact", identity.TenantID, identity.ProjectID, row.artifact.GetDigest(), revision)
	result, err := tx.ExecContext(ctx, `UPDATE artifact_catalog_entries SET state='QUARANTINED',revision=$4,etag=$5,quarantine_reason=$6,quarantine_time=$7,update_time=$7 WHERE tenant_id=$1 AND project_id=$2 AND digest=$3 AND state='COMMITTED' AND revision=$8`, identity.TenantID, identity.ProjectID, row.artifact.GetDigest(), revision, artifactETag, request.GetReasonCode(), at.UTC(), row.revision)
	if err != nil {
		return nil, false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	for index, evidence := range request.GetEvidence() {
		_, err = tx.ExecContext(ctx, `INSERT INTO artifact_quarantine_evidence (tenant_id,project_id,artifact_digest,ordinal,evidence_digest,subject_digest,evidence_kind,policy_digest) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, row.artifact.GetDigest(), index, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest())
		if err != nil {
			return nil, false, err
		}
	}
	opID := operationID(identity, key)
	operation := completedQuarantineOperation(identity, opID, row.artifact, at)
	operation.Target.ResourceVersion = revision
	operation.Target.Etag = artifactETag
	_, err = tx.ExecContext(ctx, `INSERT INTO artifact_operations (tenant_id,project_id,operation_id,target_digest,state,resource_version,done,etag,create_time,update_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)`, identity.TenantID, identity.ProjectID, opID, row.artifact.GetDigest(), int32(operation.GetState()), operation.GetResourceVersion(), operation.GetDone(), operation.GetEtag(), at.UTC())
	if err != nil {
		return nil, false, err
	}
	envelope, err := r.Events.Quarantined(identity, row.artifact, request.GetReasonCode(), request.GetEvidence(), commandContext, revision, at)
	if err != nil {
		return nil, false, err
	}
	if err = insertArtifactOutbox(ctx, tx, envelope, at); err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "OPERATION", opID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) AcquireArtifactLease(ctx context.Context, identity Identity, request *internalartifactv1.AcquireArtifactLeaseRequest, requestDigest string, at time.Time) (*commonv1.ResourceRef, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	action, key := "artifact.lease.acquire", request.GetContext().GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, receiptErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); receiptErr != nil {
		return nil, false, receiptErr
	} else if replay {
		lease, loadErr := loadArtifactLease(ctx, tx, identity, receipt.id)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return lease, true, nil
	}
	row, err := getCatalogTx(ctx, tx, identity, request.GetArtifact().GetDigest(), true)
	if err != nil {
		return nil, false, err
	}
	if row.state != "COMMITTED" {
		return nil, false, ErrInvalidTransition
	}
	if !proto.Equal(row.artifact, sanitizeArtifact(request.GetArtifact())) {
		return nil, false, ErrConflict
	}
	id := leaseID(identity, row.artifact.GetDigest())
	var state, storedETag string
	var revision int64
	var storedExpiry time.Time
	err = tx.QueryRowContext(ctx, `SELECT state,expire_time,revision,etag FROM artifact_leases WHERE tenant_id=$1 AND project_id=$2 AND lease_id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, id).Scan(&state, &storedExpiry, &revision, &storedETag)
	if errors.Is(err, sql.ErrNoRows) {
		revision = 1
		storedETag = etag("artifact-lease", identity.TenantID, identity.ProjectID, id, revision)
		_, err = tx.ExecContext(ctx, `INSERT INTO artifact_leases (tenant_id,project_id,lease_id,artifact_digest,principal_id,state,expire_time,revision,etag,create_time,update_time) VALUES ($1,$2,$3,$4,$5,'ACTIVE',$6,$7,$8,$9,$9)`, identity.TenantID, identity.ProjectID, id, row.artifact.GetDigest(), identity.Principal, request.GetExpireTime().AsTime().UTC(), revision, storedETag, at.UTC())
	} else if err == nil {
		requestedExpiry := request.GetExpireTime().AsTime().UTC()
		if state == "ACTIVE" && !requestedExpiry.After(storedExpiry) {
			lease := leaseResource(identity, id, revision, storedETag)
			if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "LEASE", id, at); err != nil {
				return nil, false, err
			}
			if err = tx.Commit(); err != nil {
				return nil, false, err
			}
			return lease, false, nil
		}
		revision++
		storedETag = etag("artifact-lease", identity.TenantID, identity.ProjectID, id, revision)
		_, err = tx.ExecContext(ctx, `UPDATE artifact_leases SET state='ACTIVE',expire_time=$4,revision=$5,etag=$6,update_time=$7,release_time=NULL WHERE tenant_id=$1 AND project_id=$2 AND lease_id=$3`, identity.TenantID, identity.ProjectID, id, requestedExpiry, revision, storedETag, at.UTC())
	}
	if err != nil {
		return nil, false, err
	}
	lease := leaseResource(identity, id, revision, storedETag)
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "LEASE", id, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return lease, false, nil
}

func (r SQLRepository) ReleaseArtifactLease(ctx context.Context, identity Identity, request *internalartifactv1.ReleaseArtifactLeaseRequest, requestDigest string, at time.Time) (bool, error) {
	if err := r.validate(); err != nil {
		return false, err
	}
	action, key := "artifact.lease.release", request.GetContext().GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	if _, replay, receiptErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); receiptErr != nil {
		return false, receiptErr
	} else if replay {
		if err = tx.Commit(); err != nil {
			return false, err
		}
		return true, nil
	}
	id := request.GetLease().GetResourceId()
	var state, storedETag string
	var revision int64
	err = tx.QueryRowContext(ctx, `SELECT state,revision,etag FROM artifact_leases WHERE tenant_id=$1 AND project_id=$2 AND lease_id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, id).Scan(&state, &revision, &storedETag)
	if errors.Is(err, sql.ErrNoRows) {
		return false, ErrNotFound
	}
	if err != nil {
		return false, err
	}
	if state != "ACTIVE" {
		return false, ErrInvalidTransition
	}
	if subtle.ConstantTimeCompare([]byte(storedETag), []byte(request.GetEtag())) != 1 {
		return false, ErrRevisionConflict
	}
	revision++
	newETag := etag("artifact-lease", identity.TenantID, identity.ProjectID, id, revision)
	result, err := tx.ExecContext(ctx, `UPDATE artifact_leases SET state='RELEASED',revision=$4,etag=$5,update_time=$6,release_time=$6 WHERE tenant_id=$1 AND project_id=$2 AND lease_id=$3 AND state='ACTIVE' AND etag=$7`, identity.TenantID, identity.ProjectID, id, revision, newETag, at.UTC(), storedETag)
	if err != nil {
		return false, err
	}
	if count, rowsErr := result.RowsAffected(); rowsErr != nil || count != 1 {
		if rowsErr != nil {
			return false, rowsErr
		}
		return false, ErrRevisionConflict
	}
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "EMPTY", id, at); err != nil {
		return false, err
	}
	if err = tx.Commit(); err != nil {
		return false, err
	}
	return false, nil
}

type uploadRow struct {
	uploadID              string
	artifact              *artifactv1.ArtifactRef
	state                 string
	committedOffset       int64
	nextChunkIndex        int64
	receipt               sql.NullString
	objectGeneration      sql.NullInt64
	finalizeKey           sql.NullString
	finalizeRequestDigest sql.NullString
	finalizeTime          sql.NullTime
	receiptExpireTime     sql.NullTime
	revision              int64
	etag                  string
	createTime            time.Time
	updateTime            time.Time
	expireTime            time.Time
	terminalReason        string
}

const uploadColumns = `upload_id,artifact_digest,media_type,size_bytes,artifact_kind,schema_id,integrity_digest,schema_version,state,committed_offset,next_chunk_index,staging_receipt_digest,object_generation,finalize_idempotency_key,finalize_request_digest,finalize_time,receipt_expire_time,revision,etag,create_time,update_time,expire_time,terminal_reason`

func scanUpload(scanner interface{ Scan(...any) error }) (uploadRow, error) {
	row := uploadRow{artifact: new(artifactv1.ArtifactRef)}
	err := scanner.Scan(&row.uploadID, &row.artifact.Digest, &row.artifact.MediaType, &row.artifact.SizeBytes, &row.artifact.ArtifactKind, &row.artifact.SchemaId, &row.artifact.IntegrityDigest, &row.artifact.SchemaVersion, &row.state, &row.committedOffset, &row.nextChunkIndex, &row.receipt, &row.objectGeneration, &row.finalizeKey, &row.finalizeRequestDigest, &row.finalizeTime, &row.receiptExpireTime, &row.revision, &row.etag, &row.createTime, &row.updateTime, &row.expireTime, &row.terminalReason)
	return row, err
}

func getUploadTx(ctx context.Context, tx *sql.Tx, identity Identity, uploadID string, forUpdate bool) (uploadRow, error) {
	query := `SELECT ` + uploadColumns + ` FROM artifact_upload_sessions WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3`
	if forUpdate {
		query += ` FOR UPDATE`
	}
	row, err := scanUpload(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, uploadID))
	if errors.Is(err, sql.ErrNoRows) {
		return uploadRow{}, ErrNotFound
	}
	return row, err
}

func expireUploadTx(ctx context.Context, tx *sql.Tx, identity Identity, row uploadRow, at time.Time) (uploadRow, error) {
	if (row.state != "OPEN" && row.state != "FINALIZING") || row.expireTime.After(at) {
		return row, nil
	}
	row.state, row.terminalReason = "EXPIRED", "SESSION_EXPIRED"
	row.revision++
	row.etag = etag("artifact-upload", identity.TenantID, identity.ProjectID, row.uploadID, row.revision)
	row.updateTime = at.UTC()
	result, err := tx.ExecContext(ctx, `UPDATE artifact_upload_sessions SET state='EXPIRED',terminal_reason='SESSION_EXPIRED',revision=$4,etag=$5,update_time=$6 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND revision=$7`, identity.TenantID, identity.ProjectID, row.uploadID, row.revision, row.etag, row.updateTime, row.revision-1)
	if err != nil {
		return uploadRow{}, err
	}
	if count, countErr := result.RowsAffected(); countErr != nil || count != 1 {
		if countErr != nil {
			return uploadRow{}, countErr
		}
		return uploadRow{}, ErrRevisionConflict
	}
	return row, nil
}

func uploadState(value string) internalartifactv1.ArtifactUploadState {
	switch value {
	case "OPEN":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN
	case "FINALIZING":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZING
	case "FINALIZED":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZED
	case "ABORTED":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_ABORTED
	case "QUARANTINED":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_QUARANTINED
	case "EXPIRED":
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_EXPIRED
	default:
		return internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_UNSPECIFIED
	}
}

func uploadMessage(identity Identity, row uploadRow) *internalartifactv1.ArtifactUploadSession {
	value := &internalartifactv1.ArtifactUploadSession{
		Name: canonicalUploadName(identity, row.uploadID), Artifact: sanitizeArtifact(row.artifact), State: uploadState(row.state),
		CommittedOffset: row.committedOffset, NextChunkIndex: row.nextChunkIndex,
		CreateTime: timestamppb.New(row.createTime.UTC()), UpdateTime: timestamppb.New(row.updateTime.UTC()), ExpireTime: timestamppb.New(row.expireTime.UTC()),
		Revision: row.revision, Etag: row.etag,
	}
	if row.state == "FINALIZED" && row.receipt.Valid && row.finalizeTime.Valid && row.receiptExpireTime.Valid {
		value.StagingReceipt = &internalartifactv1.ArtifactStagingReceipt{ReceiptDigest: row.receipt.String, Artifact: sanitizeArtifact(row.artifact), VerifiedAt: timestamppb.New(row.finalizeTime.Time.UTC()), ExpireTime: timestamppb.New(row.receiptExpireTime.Time.UTC())}
	}
	return value
}

func (r SQLRepository) BeginArtifactUpload(ctx context.Context, identity Identity, request *internalartifactv1.BeginArtifactUploadRequest, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, false, err
	}
	action, key := "artifact.upload.begin", request.GetContext().GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); checkErr != nil {
		return nil, false, checkErr
	} else if replay {
		row, loadErr := getUploadTx(ctx, tx, identity, receipt.id, true)
		if loadErr != nil {
			return nil, false, loadErr
		}
		row, loadErr = expireUploadTx(ctx, tx, identity, row, at)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, false, commitErr
		}
		return uploadMessage(identity, row), true, nil
	}
	if _, loadErr := getUploadTx(ctx, tx, identity, request.GetUploadId(), true); loadErr == nil {
		return nil, false, ErrConflict
	} else if !errors.Is(loadErr, ErrNotFound) {
		return nil, false, loadErr
	}
	artifact := sanitizeArtifact(request.GetArtifact())
	expireAt := request.GetExpireTime().AsTime().UTC()
	revision := int64(1)
	valueETag := etag("artifact-upload", identity.TenantID, identity.ProjectID, request.GetUploadId(), revision)
	_, err = tx.ExecContext(ctx, `INSERT INTO artifact_upload_sessions (tenant_id,project_id,upload_id,artifact_digest,media_type,size_bytes,artifact_kind,schema_id,integrity_digest,schema_version,state,revision,etag,create_time,update_time,expire_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'OPEN',$11,$12,$13,$13,$14)`, identity.TenantID, identity.ProjectID, request.GetUploadId(), artifact.GetDigest(), artifact.GetMediaType(), artifact.GetSizeBytes(), artifact.GetArtifactKind(), artifact.GetSchemaId(), artifact.GetIntegrityDigest(), artifact.GetSchemaVersion(), revision, valueETag, at.UTC(), expireAt)
	if err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "UPLOAD", request.GetUploadId(), at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	row := uploadRow{uploadID: request.GetUploadId(), artifact: artifact, state: "OPEN", revision: revision, etag: valueETag, createTime: at.UTC(), updateTime: at.UTC(), expireTime: expireAt}
	return uploadMessage(identity, row), false, nil
}

func (r SQLRepository) GetArtifactUpload(ctx context.Context, identity Identity, uploadID string, at time.Time) (*internalartifactv1.ArtifactUploadSession, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := getUploadTx(ctx, tx, identity, uploadID, true)
	if err != nil {
		return nil, err
	}
	row, err = expireUploadTx(ctx, tx, identity, row, at)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return uploadMessage(identity, row), nil
}

type storedChunkRow struct {
	chunk objectstorage.UploadChunk
	state string
}

func storageUploadID(identity Identity, uploadID string) string {
	value := sha256.Sum256([]byte(identity.ProjectID + "\x00" + uploadID))
	return hex.EncodeToString(value[:])
}

func scanStoredChunk(scanner interface{ Scan(...any) error }) (storedChunkRow, error) {
	var row storedChunkRow
	var generation sql.NullInt64
	err := scanner.Scan(&row.chunk.Index, &row.chunk.Offset, &row.chunk.Size, &row.chunk.Digest, &row.state, &generation)
	if generation.Valid {
		row.chunk.Generation = generation.Int64
	}
	return row, err
}

func getStoredChunkTx(ctx context.Context, tx *sql.Tx, identity Identity, uploadID string, index int64, forUpdate bool) (storedChunkRow, error) {
	query := `SELECT chunk_index,byte_offset,size_bytes,chunk_digest,state,object_generation FROM artifact_upload_chunks WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND chunk_index=$4`
	if forUpdate {
		query += ` FOR UPDATE`
	}
	row, err := scanStoredChunk(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, uploadID, index))
	if errors.Is(err, sql.ErrNoRows) {
		return storedChunkRow{}, ErrNotFound
	}
	return row, err
}

func (r SQLRepository) UploadArtifactChunk(ctx context.Context, identity Identity, request *internalartifactv1.UploadArtifactChunkRequest, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, false, err
	}
	uploadID, err := uploadIDFromName(identity, request.GetName())
	if err != nil {
		return nil, false, err
	}
	action, key := "artifact.upload.chunk", request.GetContext().GetIdempotencyKey()
	chunk := objectstorage.UploadChunk{Index: request.GetChunkIndex(), Offset: request.GetOffset(), Size: int64(len(request.GetData())), Digest: request.GetChunkDigest()}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); checkErr != nil {
		return nil, false, checkErr
	} else if replay {
		row, loadErr := getUploadTx(ctx, tx, identity, receipt.id, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, false, commitErr
		}
		return uploadMessage(identity, row), true, nil
	}
	row, err := getUploadTx(ctx, tx, identity, uploadID, true)
	if err != nil {
		return nil, false, err
	}
	row, err = expireUploadTx(ctx, tx, identity, row, at)
	if err != nil {
		return nil, false, err
	}
	if row.state == "EXPIRED" {
		return nil, false, ErrUploadExpired
	}
	if row.state != "OPEN" || subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetEtag())) != 1 || row.nextChunkIndex != chunk.Index || row.committedOffset != chunk.Offset || chunk.Offset+chunk.Size > row.artifact.GetSizeBytes() {
		return nil, false, ErrRevisionConflict
	}
	existing, chunkErr := getStoredChunkTx(ctx, tx, identity, uploadID, chunk.Index, true)
	switch {
	case chunkErr == nil:
		if existing.chunk.Offset != chunk.Offset || existing.chunk.Size != chunk.Size || subtle.ConstantTimeCompare([]byte(existing.chunk.Digest), []byte(chunk.Digest)) != 1 {
			return nil, false, ErrChunkConflict
		}
	case errors.Is(chunkErr, ErrNotFound):
		_, err = tx.ExecContext(ctx, `INSERT INTO artifact_upload_chunks (tenant_id,project_id,upload_id,chunk_index,byte_offset,size_bytes,chunk_digest,state,create_time) VALUES ($1,$2,$3,$4,$5,$6,$7,'WRITING',$8)`, identity.TenantID, identity.ProjectID, uploadID, chunk.Index, chunk.Offset, chunk.Size, chunk.Digest, at.UTC())
		if err != nil {
			return nil, false, err
		}
	default:
		return nil, false, chunkErr
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	stored, err := r.Objects.PutChunk(ctx, identity.TenantID, storageUploadID(identity, uploadID), chunk, append([]byte(nil), request.GetData()...))
	if err != nil {
		return nil, false, err
	}
	finish, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = finish.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, finish, identity, action, key, requestDigest); checkErr != nil {
		return nil, false, checkErr
	} else if replay {
		value, loadErr := getUploadTx(ctx, finish, identity, receipt.id, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if commitErr := finish.Commit(); commitErr != nil {
			return nil, false, commitErr
		}
		return uploadMessage(identity, value), true, nil
	}
	row, err = getUploadTx(ctx, finish, identity, uploadID, true)
	if err != nil {
		return nil, false, err
	}
	durable, err := getStoredChunkTx(ctx, finish, identity, uploadID, chunk.Index, true)
	if err != nil || durable.chunk.Offset != chunk.Offset || durable.chunk.Size != chunk.Size || subtle.ConstantTimeCompare([]byte(durable.chunk.Digest), []byte(chunk.Digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrChunkConflict
	}
	if durable.state == "WRITING" {
		if row.state != "OPEN" || row.nextChunkIndex != chunk.Index || row.committedOffset != chunk.Offset {
			return nil, false, ErrInvalidTransition
		}
		_, err = finish.ExecContext(ctx, `UPDATE artifact_upload_chunks SET state='STORED',object_generation=$5 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND chunk_index=$4 AND state='WRITING'`, identity.TenantID, identity.ProjectID, uploadID, chunk.Index, stored.Generation)
		if err != nil {
			return nil, false, err
		}
		row.committedOffset += chunk.Size
		row.nextChunkIndex++
		row.revision++
		row.updateTime = at.UTC()
		row.etag = etag("artifact-upload", identity.TenantID, identity.ProjectID, uploadID, row.revision)
		_, err = finish.ExecContext(ctx, `UPDATE artifact_upload_sessions SET committed_offset=$4,next_chunk_index=$5,revision=$6,etag=$7,update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND state='OPEN' AND revision=$9`, identity.TenantID, identity.ProjectID, uploadID, row.committedOffset, row.nextChunkIndex, row.revision, row.etag, row.updateTime, row.revision-1)
		if err != nil {
			return nil, false, err
		}
	}
	if err = insertReceipt(ctx, finish, identity, action, key, requestDigest, "UPLOAD", uploadID, at); err != nil {
		return nil, false, err
	}
	if err = finish.Commit(); err != nil {
		return nil, false, err
	}
	return uploadMessage(identity, row), false, nil
}

func listUploadChunksTx(ctx context.Context, tx *sql.Tx, identity Identity, uploadID string) ([]objectstorage.UploadChunk, error) {
	rows, err := tx.QueryContext(ctx, `SELECT chunk_index,byte_offset,size_bytes,chunk_digest,object_generation FROM artifact_upload_chunks WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND state='STORED' ORDER BY chunk_index`, identity.TenantID, identity.ProjectID, uploadID)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	chunks := make([]objectstorage.UploadChunk, 0)
	for rows.Next() {
		var chunk objectstorage.UploadChunk
		if err = rows.Scan(&chunk.Index, &chunk.Offset, &chunk.Size, &chunk.Digest, &chunk.Generation); err != nil {
			return nil, err
		}
		chunks = append(chunks, chunk)
	}
	return chunks, rows.Err()
}

func (r SQLRepository) FinalizeArtifactUpload(ctx context.Context, identity Identity, request *internalartifactv1.FinalizeArtifactUploadRequest, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, *internalartifactv1.ArtifactStagingReceipt, bool, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, nil, false, err
	}
	uploadID, err := uploadIDFromName(identity, request.GetName())
	if err != nil {
		return nil, nil, false, err
	}
	action, key := "artifact.upload.finalize", request.GetContext().GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); checkErr != nil {
		return nil, nil, false, checkErr
	} else if replay {
		row, loadErr := getUploadTx(ctx, tx, identity, receipt.id, false)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, nil, false, commitErr
		}
		value := uploadMessage(identity, row)
		return value, clone(value.GetStagingReceipt()), true, nil
	}
	row, err := getUploadTx(ctx, tx, identity, uploadID, true)
	if err != nil {
		return nil, nil, false, err
	}
	row, err = expireUploadTx(ctx, tx, identity, row, at)
	if err != nil {
		return nil, nil, false, err
	}
	if row.state == "EXPIRED" {
		return nil, nil, false, ErrUploadExpired
	}
	requestedExpire := request.GetReceiptExpireTime().AsTime().UTC()
	if row.state == "OPEN" {
		if subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetEtag())) != 1 || row.committedOffset != row.artifact.GetSizeBytes() || (row.nextChunkIndex == 0 && row.artifact.GetSizeBytes() != 0) {
			return nil, nil, false, ErrInvalidTransition
		}
		row.state = "FINALIZING"
		row.finalizeKey = sql.NullString{String: key, Valid: true}
		row.finalizeRequestDigest = sql.NullString{String: requestDigest, Valid: true}
		row.finalizeTime = sql.NullTime{Time: at.UTC(), Valid: true}
		row.receiptExpireTime = sql.NullTime{Time: requestedExpire, Valid: true}
		row.revision++
		row.updateTime = at.UTC()
		row.etag = etag("artifact-upload", identity.TenantID, identity.ProjectID, uploadID, row.revision)
		_, err = tx.ExecContext(ctx, `UPDATE artifact_upload_sessions SET state='FINALIZING',finalize_idempotency_key=$4,finalize_request_digest=$5,finalize_time=$6,receipt_expire_time=$7,revision=$8,etag=$9,update_time=$6 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND state='OPEN' AND revision=$10`, identity.TenantID, identity.ProjectID, uploadID, key, requestDigest, at.UTC(), requestedExpire, row.revision, row.etag, row.revision-1)
		if err != nil {
			return nil, nil, false, err
		}
	} else if row.state != "FINALIZING" || !row.finalizeKey.Valid || row.finalizeKey.String != key || !row.finalizeRequestDigest.Valid || subtle.ConstantTimeCompare([]byte(row.finalizeRequestDigest.String), []byte(requestDigest)) != 1 {
		return nil, nil, false, ErrInvalidTransition
	}
	chunks, err := listUploadChunksTx(ctx, tx, identity, uploadID)
	if err != nil {
		return nil, nil, false, err
	}
	if int64(len(chunks)) != row.nextChunkIndex || (len(chunks) == 0 && row.artifact.GetSizeBytes() != 0) {
		return nil, nil, false, ErrIntegrityFailure
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	object, err := r.Objects.Finalize(ctx, identity.TenantID, storageUploadID(identity, uploadID), chunks, row.artifact.GetDigest(), row.artifact.GetSizeBytes())
	if err != nil {
		return nil, nil, false, err
	}
	finish, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = finish.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, finish, identity, action, key, requestDigest); checkErr != nil {
		return nil, nil, false, checkErr
	} else if replay {
		value, loadErr := getUploadTx(ctx, finish, identity, receipt.id, false)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		if commitErr := finish.Commit(); commitErr != nil {
			return nil, nil, false, commitErr
		}
		message := uploadMessage(identity, value)
		return message, clone(message.GetStagingReceipt()), true, nil
	}
	row, err = getUploadTx(ctx, finish, identity, uploadID, true)
	if err != nil {
		return nil, nil, false, err
	}
	if row.state != "FINALIZING" || !row.finalizeRequestDigest.Valid || subtle.ConstantTimeCompare([]byte(row.finalizeRequestDigest.String), []byte(requestDigest)) != 1 || !row.finalizeTime.Valid || !row.receiptExpireTime.Valid {
		return nil, nil, false, ErrInvalidTransition
	}
	receiptDigest := stagingReceiptDigest(identity, object, row.finalizeTime.Time, row.receiptExpireTime.Time)
	result, err := finish.ExecContext(ctx, `INSERT INTO artifact_staging_receipts (tenant_id,project_id,receipt_digest,artifact_digest,size_bytes,object_generation,state,verified_at,expire_time) VALUES ($1,$2,$3,$4,$5,$6,'VERIFIED',$7,$8) ON CONFLICT (tenant_id,project_id,receipt_digest) DO NOTHING`, identity.TenantID, identity.ProjectID, receiptDigest, object.Digest, object.Size, object.Generation, row.finalizeTime.Time.UTC(), row.receiptExpireTime.Time.UTC())
	if err != nil {
		return nil, nil, false, err
	}
	if count, countErr := result.RowsAffected(); countErr != nil || count > 1 {
		if countErr != nil {
			return nil, nil, false, countErr
		}
		return nil, nil, false, ErrStagingUnverified
	} else if count == 0 {
		var storedDigest string
		var storedSize, storedGeneration int64
		var storedState string
		var storedVerified, storedExpire time.Time
		if queryErr := finish.QueryRowContext(ctx, `SELECT artifact_digest,size_bytes,object_generation,state,verified_at,expire_time FROM artifact_staging_receipts WHERE tenant_id=$1 AND project_id=$2 AND receipt_digest=$3 FOR SHARE`, identity.TenantID, identity.ProjectID, receiptDigest).Scan(&storedDigest, &storedSize, &storedGeneration, &storedState, &storedVerified, &storedExpire); queryErr != nil || storedDigest != object.Digest || storedSize != object.Size || storedGeneration != object.Generation || storedState != "VERIFIED" || !storedVerified.Equal(row.finalizeTime.Time.UTC().Truncate(time.Microsecond)) || !storedExpire.Equal(row.receiptExpireTime.Time.UTC().Truncate(time.Microsecond)) {
			return nil, nil, false, ErrStagingUnverified
		}
	}
	row.state = "FINALIZED"
	row.receipt = sql.NullString{String: receiptDigest, Valid: true}
	row.objectGeneration = sql.NullInt64{Int64: object.Generation, Valid: true}
	row.revision++
	row.updateTime = row.finalizeTime.Time.UTC()
	row.etag = etag("artifact-upload", identity.TenantID, identity.ProjectID, uploadID, row.revision)
	result, err = finish.ExecContext(ctx, `UPDATE artifact_upload_sessions SET state='FINALIZED',staging_receipt_digest=$4,object_generation=$5,revision=$6,etag=$7,update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND state='FINALIZING' AND revision=$9`, identity.TenantID, identity.ProjectID, uploadID, receiptDigest, object.Generation, row.revision, row.etag, row.updateTime, row.revision-1)
	if err != nil {
		return nil, nil, false, err
	}
	if count, countErr := result.RowsAffected(); countErr != nil || count != 1 {
		if countErr != nil {
			return nil, nil, false, countErr
		}
		return nil, nil, false, ErrRevisionConflict
	}
	envelope, err := r.Events.StagingFinalized(identity, canonicalUploadName(identity, uploadID), row.artifact, receiptDigest, request.GetContext(), row.revision, row.finalizeTime.Time, row.receiptExpireTime.Time)
	if err != nil {
		return nil, nil, false, err
	}
	if err = insertArtifactOutbox(ctx, finish, envelope, row.finalizeTime.Time); err != nil {
		return nil, nil, false, err
	}
	if err = insertReceipt(ctx, finish, identity, action, key, requestDigest, "UPLOAD", uploadID, row.finalizeTime.Time); err != nil {
		return nil, nil, false, err
	}
	if err = finish.Commit(); err != nil {
		return nil, nil, false, err
	}
	_ = r.Objects.DeleteChunks(context.WithoutCancel(ctx), identity.TenantID, storageUploadID(identity, uploadID), chunks)
	value := uploadMessage(identity, row)
	return value, clone(value.GetStagingReceipt()), false, nil
}

func (r SQLRepository) transitionArtifactUpload(ctx context.Context, identity Identity, command proto.Message, commandContext *commonv1.CommandContext, name, suppliedETag, reason, target, action, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	uploadID, err := uploadIDFromName(identity, name)
	if err != nil {
		return nil, false, err
	}
	key := commandContext.GetIdempotencyKey()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if receipt, replay, checkErr := lockAndCheckReceipt(ctx, tx, identity, action, key, requestDigest); checkErr != nil {
		return nil, false, checkErr
	} else if replay {
		row, loadErr := getUploadTx(ctx, tx, identity, receipt.id, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		chunks, loadErr := listUploadChunksTx(ctx, tx, identity, uploadID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, false, commitErr
		}
		if cleanupErr := r.Objects.DeleteChunks(ctx, identity.TenantID, storageUploadID(identity, uploadID), chunks); cleanupErr != nil {
			return nil, false, cleanupErr
		}
		return uploadMessage(identity, row), true, nil
	}
	_ = command
	row, err := getUploadTx(ctx, tx, identity, uploadID, true)
	if err != nil {
		return nil, false, err
	}
	row, err = expireUploadTx(ctx, tx, identity, row, at)
	if err != nil {
		return nil, false, err
	}
	if row.state != "OPEN" && row.state != "FINALIZING" {
		return nil, false, ErrInvalidTransition
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(suppliedETag)) != 1 {
		return nil, false, ErrRevisionConflict
	}
	row.state, row.terminalReason = target, reason
	row.revision++
	row.updateTime = at.UTC()
	row.etag = etag("artifact-upload", identity.TenantID, identity.ProjectID, uploadID, row.revision)
	result, err := tx.ExecContext(ctx, `UPDATE artifact_upload_sessions SET state=$4,terminal_reason=$5,revision=$6,etag=$7,update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND upload_id=$3 AND state IN ('OPEN','FINALIZING') AND revision=$9`, identity.TenantID, identity.ProjectID, uploadID, target, reason, row.revision, row.etag, row.updateTime, row.revision-1)
	if err != nil {
		return nil, false, err
	}
	if count, countErr := result.RowsAffected(); countErr != nil || count != 1 {
		if countErr != nil {
			return nil, false, countErr
		}
		return nil, false, ErrRevisionConflict
	}
	chunks, err := listUploadChunksTx(ctx, tx, identity, uploadID)
	if err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, action, key, requestDigest, "UPLOAD", uploadID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	if err = r.Objects.DeleteChunks(ctx, identity.TenantID, storageUploadID(identity, uploadID), chunks); err != nil {
		return nil, false, err
	}
	return uploadMessage(identity, row), false, nil
}

func (r SQLRepository) AbortArtifactUpload(ctx context.Context, identity Identity, request *internalartifactv1.AbortArtifactUploadRequest, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, false, err
	}
	return r.transitionArtifactUpload(ctx, identity, request, request.GetContext(), request.GetName(), request.GetEtag(), request.GetReasonCode(), "ABORTED", "artifact.upload.abort", requestDigest, at)
}

func (r SQLRepository) QuarantineArtifactUpload(ctx context.Context, identity Identity, request *internalartifactv1.QuarantineArtifactUploadRequest, requestDigest string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, false, err
	}
	return r.transitionArtifactUpload(ctx, identity, request, request.GetContext(), request.GetName(), request.GetEtag(), request.GetReasonCode(), "QUARANTINED", "artifact.upload.quarantine", requestDigest, at)
}

func (r SQLRepository) OpenArtifact(ctx context.Context, identity Identity, digest string, offset int64) (*artifactv1.ArtifactRef, io.ReadCloser, error) {
	if err := r.validateTransfer(); err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := getCatalogTx(ctx, tx, identity, digest, false)
	if err != nil {
		return nil, nil, err
	}
	if row.state != "COMMITTED" || offset < 0 || offset > row.artifact.GetSizeBytes() {
		return nil, nil, ErrInvalidTransition
	}
	var generation int64
	err = tx.QueryRowContext(ctx, `SELECT object_generation FROM artifact_staging_receipts WHERE tenant_id=$1 AND project_id=$2 AND receipt_digest=$3 AND artifact_digest=$4`, identity.TenantID, identity.ProjectID, row.stagingReceipt, digest).Scan(&generation)
	if err != nil || generation <= 0 {
		return nil, nil, ErrStagingUnverified
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	reader, err := r.Objects.OpenPinned(ctx, objectstorage.Object{TenantID: identity.TenantID, Digest: digest, Size: row.artifact.GetSizeBytes(), Generation: generation}, offset)
	if err != nil {
		return nil, nil, err
	}
	return sanitizeArtifact(row.artifact), reader, nil
}

func insertArtifactOutbox(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := queue.MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, envelope.GetEventId(), envelope.GetTenantId(), envelope.GetEventType(), envelope.GetEventVersion(), envelope.GetSubject().GetResourceType(), envelope.GetSubject().GetName(), envelope.GetAggregateSequence(), envelope.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func loadArtifactOperation(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*jobv1.Operation, error) {
	var operation jobv1.Operation
	var targetDigest string
	var state int32
	var createTime, updateTime time.Time
	err := tx.QueryRowContext(ctx, `SELECT operation_id,target_digest,state,resource_version,done,etag,create_time,update_time FROM artifact_operations WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3`, identity.TenantID, identity.ProjectID, id).Scan(&operation.OperationId, &targetDigest, &state, &operation.ResourceVersion, &operation.Done, &operation.Etag, &createTime, &updateTime)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	operation.TenantId, operation.ProjectId = identity.TenantID, identity.ProjectID
	operation.State = jobv1.OperationState(state)
	operation.CreatedAt, operation.UpdatedAt = timestamppb.New(createTime.UTC()), timestamppb.New(updateTime.UTC())
	row, err := getCatalogTx(ctx, tx, identity, targetDigest, false)
	if err != nil {
		return nil, err
	}
	operation.Target = &commonv1.ResourceRef{ResourceType: "artifact", ResourceId: targetDigest, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: row.revision, Name: canonicalArtifactName(identity, targetDigest), Etag: row.etag}
	return &operation, nil
}

func loadArtifactLease(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*commonv1.ResourceRef, error) {
	var revision int64
	var valueETag string
	err := tx.QueryRowContext(ctx, `SELECT revision,etag FROM artifact_leases WHERE tenant_id=$1 AND project_id=$2 AND lease_id=$3`, identity.TenantID, identity.ProjectID, id).Scan(&revision, &valueETag)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return leaseResource(identity, id, revision, valueETag), nil
}

func leaseResource(identity Identity, id string, revision int64, valueETag string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "artifact_lease", ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: revision, Name: canonicalParent(identity) + "/artifactLeases/" + id, Etag: valueETag}
}
