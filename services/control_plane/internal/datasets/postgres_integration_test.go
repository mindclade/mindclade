package datasets

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"google.golang.org/protobuf/types/known/fieldmaskpb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
)

func integrationDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		t.Skip("PostgreSQL integration DSN is not configured")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func TestPostgresDatasetNormalizedRoundTripAndForcedRLS(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "dataset-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	other := Identity{TenantID: "dataset-other-" + suffix, ProjectID: identity.ProjectID, Principal: identity.Principal}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("dataset-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec}
	t.Cleanup(func() {
		for _, tenant := range []string{identity.TenantID, other.TenantID} {
			tx, cleanupErr := platformdb.BeginTenantTx(ctx, db, tenant, nil)
			if cleanupErr != nil {
				t.Errorf("cleanup begin: %v", cleanupErr)
				continue
			}
			for _, table := range []string{"dataset_release_revocation_evidence", "dataset_release_qualification_evidence", "dataset_releases", "dataset_annotations", "dataset_labels", "datasets", "resource_references", "artifact_references"} {
				if _, cleanupErr = tx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", tenant); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
					t.Errorf("cleanup %s: %v", table, cleanupErr)
				}
			}
			if cleanupErr = tx.Commit(); cleanupErr != nil {
				t.Errorf("cleanup commit: %v", cleanupErr)
			}
		}
	})
	at := time.Now().UTC()
	name := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID + "/datasets/pdb"
	releaseName := name + "/releases/v1"
	tx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	manifestID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/vnd.mindclade.dataset-manifest+json", SizeBytes: 42, SchemaId: "mindclade.dataset-manifest/v1", SchemaVersion: "1"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO datasets(tenant_id,project_id,name,uid,revision,etag,display_name,state,policy_classification,create_time,current_release_name) VALUES($1,$2,$3,'dataset-uid',1,$4,'PDB',2,'internal',$5,$6)`, identity.TenantID, identity.ProjectID, name, "sha256:"+strings.Repeat("b", 64), at, releaseName); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_labels(tenant_id,project_id,dataset_name,label_key,label_value) VALUES($1,$2,$3,'source','pdb')`, identity.TenantID, identity.ProjectID, name); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_annotations(tenant_id,project_id,dataset_name,annotation_key,annotation_value) VALUES($1,$2,$3,'cutoff','2026-08-01')`, identity.TenantID, identity.ProjectID, name); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_releases(tenant_id,project_id,name,uid,dataset_name,release_id,revision,etag,state,manifest_ref_id,policy_classification,create_time,publish_time) VALUES($1,$2,$3,'release-uid',$4,'v1',1,$5,3,$6,'internal',$7,$7)`, identity.TenantID, identity.ProjectID, releaseName, name, "sha256:"+strings.Repeat("c", 64), manifestID, at); err != nil {
		t.Fatal(err)
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_release_qualification_evidence(tenant_id,project_id,release_name,ordinal,digest,subject_digest,evidence_kind,policy_digest) VALUES($1,$2,$3,0,$4,$5,'dataset_qualification',$6)`, identity.TenantID, identity.ProjectID, releaseName, "sha256:"+strings.Repeat("d", 64), "sha256:"+strings.Repeat("a", 64), "sha256:"+strings.Repeat("e", 64)); err != nil {
		t.Fatal(err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	value, err := repository.GetDataset(ctx, identity, name)
	if err != nil {
		t.Fatal(err)
	}
	if value.GetLabels()["source"] != "pdb" || value.GetAnnotations()["cutoff"] == "" || value.GetCurrentReleaseName() != releaseName {
		t.Fatalf("dataset round trip=%v", value)
	}
	release, err := repository.GetDatasetRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	if release.GetManifest().GetDigest() == "" || len(release.GetQualificationEvidence()) != 1 || release.GetState() != datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_PUBLISHED {
		t.Fatalf("release round trip=%v", release)
	}
	if _, err = repository.GetDataset(ctx, other, name); !errors.Is(err, ErrNotFound) {
		t.Fatalf("cross-tenant read error=%v", err)
	}
	var forced int
	if err = db.QueryRowContext(ctx, `SELECT count(*) FROM pg_class WHERE relname = ANY($1) AND relrowsecurity AND relforcerowsecurity`, []string{"datasets", "dataset_labels", "dataset_annotations", "dataset_releases", "dataset_release_qualification_evidence", "dataset_release_revocation_evidence", "models", "model_labels", "model_annotations", "model_releases", "model_release_evaluation_evidence", "model_release_transition_evidence", "data_model_command_receipts"}).Scan(&forced); err != nil {
		t.Fatal(err)
	}
	if forced != 13 {
		t.Fatalf("only %d/13 data-model tables force row-level security", forced)
	}
}

func TestPostgresDatasetLifecycleIsAtomicIdempotentAndEventBacked(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "dataset-lifecycle-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("dataset-lifecycle-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	t.Cleanup(func() {
		tx, cleanupErr := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
		if cleanupErr != nil {
			t.Errorf("cleanup begin: %v", cleanupErr)
			return
		}
		defer func() { _ = tx.Rollback() }()
		for _, table := range []string{
			"data_model_command_receipts", "outbox_messages", "audit_events", "operation_revisions", "operations", "jobs",
			"dataset_release_revocation_evidence", "dataset_release_qualification_evidence", "dataset_releases",
			"dataset_annotations", "dataset_labels", "datasets", "resource_references", "artifact_references",
		} {
			if _, cleanupErr = tx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", identity.TenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = tx.Commit(); cleanupErr != nil {
			t.Errorf("cleanup commit: %v", cleanupErr)
		}
	})

	parent := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
	at := time.Now().UTC()
	create := &datasetv1.CreateDatasetCommand{
		Project:              &commonv1.ResourceRef{ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: parent},
		DatasetId:            "pdb",
		DisplayName:          "PDB",
		Labels:               map[string]string{"source": "pdb"},
		Annotations:          map[string]string{"cutoff": "2026-08-01"},
		PolicyClassification: "internal",
		Context:              &commonv1.CommandContext{RequestId: "dataset-create", IdempotencyKey: "dataset-create", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal},
	}
	createDigest, err := canonicalCommandDigest(create)
	if err != nil {
		t.Fatal(err)
	}
	create.Context.CanonicalRequestDigest = createDigest
	operation, replay, err := repository.CreateDataset(ctx, identity, create, createDigest, at)
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("create operation=%v replay=%v err=%v", operation, replay, err)
	}
	createdOperationID := operation.GetOperationId()
	operation, replay, err = repository.CreateDataset(ctx, identity, clone(create), createDigest, at.Add(time.Second))
	if err != nil || !replay || operation.GetOperationId() != createdOperationID {
		t.Fatalf("create replay operation=%v replay=%v err=%v", operation, replay, err)
	}
	conflicting := clone(create)
	conflicting.DisplayName = "Different"
	conflicting.Context.CanonicalRequestDigest = ""
	conflictDigest, err := canonicalCommandDigest(conflicting)
	if err != nil {
		t.Fatal(err)
	}
	conflicting.Context.CanonicalRequestDigest = conflictDigest
	if _, _, err = repository.CreateDataset(ctx, identity, conflicting, conflictDigest, at.Add(2*time.Second)); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("conflicting replay error=%v", err)
	}

	datasetName := parent + "/datasets/pdb"
	created, err := repository.GetDataset(ctx, identity, datasetName)
	if err != nil {
		t.Fatal(err)
	}
	update := &datasetv1.UpdateDatasetCommand{
		Dataset: &datasetv1.Dataset{
			Name:                 datasetName,
			DisplayName:          "Protein Data Bank",
			Labels:               map[string]string{"source": "pdb", "qualified": "true"},
			Annotations:          map[string]string{"cutoff": "2026-08-31"},
			PolicyClassification: "restricted-internal",
		},
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name", "labels", "annotations", "policy_classification"}},
		Etag:       created.GetEtag(),
		Context:    &commonv1.CommandContext{RequestId: "dataset-update", IdempotencyKey: "dataset-update", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal},
	}
	updateDigest, err := canonicalCommandDigest(update)
	if err != nil {
		t.Fatal(err)
	}
	update.Context.CanonicalRequestDigest = updateDigest
	if operation, replay, err = repository.UpdateDataset(ctx, identity, update, updateDigest, at.Add(3*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("update operation=%v replay=%v err=%v", operation, replay, err)
	}
	updated, err := repository.GetDataset(ctx, identity, datasetName)
	if err != nil {
		t.Fatal(err)
	}
	if updated.GetRevision() != 2 || updated.GetLabels()["qualified"] != "true" || updated.GetAnnotations()["cutoff"] != "2026-08-31" {
		t.Fatalf("updated dataset=%v", updated)
	}

	manifestDigest := "sha256:" + strings.Repeat("a", 64)
	manifest := &artifactv1.ArtifactRef{Digest: manifestDigest, MediaType: "application/vnd.mindclade.dataset-manifest+json", SizeBytes: 42, SchemaId: "mindclade.dataset-manifest/v1", SchemaVersion: "1"}
	qualification := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("b", 64), SubjectDigest: manifestDigest, EvidenceKind: "dataset_qualification", PolicyDigest: "sha256:" + strings.Repeat("c", 64)}
	publish := &datasetv1.PublishDatasetReleaseCommand{
		Dataset:               &commonv1.ResourceRef{ResourceType: "dataset", ResourceId: "pdb", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: updated.GetRevision(), Name: datasetName, Etag: updated.GetEtag()},
		ReleaseId:             "v1",
		Manifest:              manifest,
		QualificationEvidence: []*artifactv1.EvidenceRef{qualification},
		PolicyClassification:  "restricted-internal",
		Context:               &commonv1.CommandContext{RequestId: "dataset-publish", IdempotencyKey: "dataset-publish", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal},
	}
	publishDigest, err := canonicalCommandDigest(publish)
	if err != nil {
		t.Fatal(err)
	}
	publish.Context.CanonicalRequestDigest = publishDigest
	if operation, replay, err = repository.PublishDatasetRelease(ctx, identity, publish, publishDigest, at.Add(4*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("publish operation=%v replay=%v err=%v", operation, replay, err)
	}
	releaseName := datasetName + "/releases/v1"
	release, err := repository.GetDatasetRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	afterPublish, err := repository.GetDataset(ctx, identity, datasetName)
	if err != nil {
		t.Fatal(err)
	}
	if release.GetState() != datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_PUBLISHED || release.GetManifest().GetDigest() != manifestDigest || len(release.GetQualificationEvidence()) != 1 || afterPublish.GetState() != datasetv1.DatasetState_DATASET_STATE_ACTIVE || afterPublish.GetCurrentReleaseName() != releaseName {
		t.Fatalf("published release=%v dataset=%v", release, afterPublish)
	}

	revocation := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("d", 64), SubjectDigest: manifestDigest, EvidenceKind: "dataset_revocation", PolicyDigest: "sha256:" + strings.Repeat("e", 64)}
	revoke := &datasetv1.RevokeDatasetReleaseCommand{
		DatasetRelease: &commonv1.ResourceRef{ResourceType: "dataset_release", ResourceId: "v1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: release.GetRevision(), Name: releaseName, Etag: release.GetEtag()},
		Etag:           release.GetEtag(),
		Reason:         "qualification withdrawn",
		Evidence:       []*artifactv1.EvidenceRef{revocation},
		Context:        &commonv1.CommandContext{RequestId: "dataset-revoke", IdempotencyKey: "dataset-revoke", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal},
	}
	revokeDigest, err := canonicalCommandDigest(revoke)
	if err != nil {
		t.Fatal(err)
	}
	revoke.Context.CanonicalRequestDigest = revokeDigest
	if operation, replay, err = repository.RevokeDatasetRelease(ctx, identity, revoke, revokeDigest, at.Add(5*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("revoke operation=%v replay=%v err=%v", operation, replay, err)
	}
	revoked, err := repository.GetDatasetRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	afterRevoke, err := repository.GetDataset(ctx, identity, datasetName)
	if err != nil {
		t.Fatal(err)
	}
	if revoked.GetRevision() != 2 || revoked.GetState() != datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_REVOKED || revoked.GetRevocationReason() == "" || afterRevoke.GetCurrentReleaseName() != "" {
		t.Fatalf("revoked release=%v dataset=%v", revoked, afterRevoke)
	}

	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var receipts, events, audits, jobs, operations, evidence int
	if err = verify.QueryRowContext(ctx, `SELECT
		(SELECT count(*) FROM data_model_command_receipts WHERE tenant_id=$1),
		(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),
		(SELECT count(*) FROM audit_events WHERE tenant_id=$1),
		(SELECT count(*) FROM jobs WHERE tenant_id=$1),
		(SELECT count(*) FROM operations WHERE tenant_id=$1),
		(SELECT count(*) FROM dataset_release_revocation_evidence WHERE tenant_id=$1)`, identity.TenantID).Scan(&receipts, &events, &audits, &jobs, &operations, &evidence); err != nil {
		t.Fatal(err)
	}
	if receipts != 4 || events != 6 || audits != 4 || jobs != 4 || operations != 4 || evidence != 1 {
		t.Fatalf("receipts=%d events=%d audits=%d jobs=%d operations=%d revocation_evidence=%d", receipts, events, audits, jobs, operations, evidence)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,id`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]int{}
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		if _, decodeErr = pubsubx.UnmarshalRegisteredPayload(envelope); decodeErr != nil {
			t.Fatal(decodeErr)
		}
		seen[envelope.GetEventType()]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	if seen["mindclade.events.dataset.v1.DatasetCreated"] != 1 || seen["mindclade.events.dataset.v1.DatasetUpdated"] != 3 || seen["mindclade.events.dataset.v1.DatasetReleasePublished"] != 1 || seen["mindclade.events.dataset.v1.DatasetReleaseRevoked"] != 1 {
		t.Fatalf("typed event distribution=%v", seen)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}

	immutable, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = immutable.ExecContext(ctx, `UPDATE dataset_release_revocation_evidence SET evidence_kind='rewritten' WHERE tenant_id=$1`, identity.TenantID); err == nil {
		t.Fatal("immutable dataset revocation evidence accepted an update")
	}
	_ = immutable.Rollback()
}
