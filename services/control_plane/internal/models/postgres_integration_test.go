package models

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
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
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestPostgresModelRegistrationIsAtomicIdempotentAndEventBacked(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "model-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("integration-page-key-", 2)))
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
		for _, table := range []string{"data_model_command_receipts", "outbox_messages", "audit_events", "operation_revisions", "operations", "jobs", "model_annotations", "model_labels", "model_release_transition_evidence", "model_release_evaluation_evidence", "model_releases", "models", "resource_references", "artifact_references"} {
			if _, cleanupErr = tx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", identity.TenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = tx.Commit(); cleanupErr != nil {
			t.Errorf("cleanup commit: %v", cleanupErr)
		}
	})
	at := time.Now().UTC()
	command := &modelv1.RegisterModelCommand{Project: &commonv1.ResourceRef{ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: projectParent(identity)}, ModelId: "nova", DisplayName: "Nova", Family: "clade", DefinitionManifest: artifactFixture("1"), FeatureRequirementSet: artifactFixture("2"), ModelFeatureView: artifactFixture("3"), InputContract: artifactFixture("4"), OutputContract: artifactFixture("5"), Labels: map[string]string{"environment": "integration"}}
	command.Context = &commonv1.CommandContext{RequestId: "register-request", IdempotencyKey: "register-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal}
	digest, err := canonicalCommandDigest(command)
	if err != nil {
		t.Fatal(err)
	}
	command.Context.CanonicalRequestDigest = digest
	operation, replay, err := repository.RegisterModel(ctx, identity, command, digest, at)
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayed, replay, err := repository.RegisterModel(ctx, identity, clone(command), digest, at.Add(time.Second))
	if err != nil || !replay || replayed.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("replayed=%v replay=%v err=%v", replayed, replay, err)
	}
	stored, err := repository.GetModel(ctx, identity, projectParent(identity)+"/models/nova")
	if err != nil {
		t.Fatal(err)
	}
	if stored.GetDefinitionManifest().GetDigest() != command.GetDefinitionManifest().GetDigest() || stored.GetLabels()["environment"] != "integration" {
		t.Fatalf("protobuf SQL round trip lost state: %v", stored)
	}
	tx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	var models, receipts, events, audits int
	if err = tx.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM models WHERE tenant_id=$1),(SELECT count(*) FROM data_model_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1)`, identity.TenantID).Scan(&models, &receipts, &events, &audits); err != nil {
		t.Fatal(err)
	}
	if models != 1 || receipts != 1 || events != 1 || audits != 1 {
		t.Fatalf("models=%d receipts=%d events=%d audits=%d", models, receipts, events, audits)
	}
	var encoded []byte
	if err = tx.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1`, identity.TenantID).Scan(&encoded); err != nil {
		t.Fatal(err)
	}
	envelope, err := queue.UnmarshalEnvelope(encoded)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := queue.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		t.Fatal(err)
	}
	registered, ok := payload.(*modelv1.ModelRegistered)
	if !ok || registered.GetModelName() != stored.GetName() {
		t.Fatalf("payload=%T %v", payload, payload)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	conflicting := clone(command)
	conflicting.DisplayName = "Different"
	conflicting.Context.CanonicalRequestDigest = ""
	conflictDigest, err := canonicalCommandDigest(conflicting)
	if err != nil {
		t.Fatal(err)
	}
	conflicting.Context.CanonicalRequestDigest = conflictDigest
	if _, _, err = repository.RegisterModel(ctx, identity, conflicting, conflictDigest, at.Add(2*time.Second)); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("conflicting replay error=%v", err)
	}
	if proto.Equal(command, conflicting) {
		t.Fatal("fixture corruption")
	}

	releaseName := projectParent(identity) + "/models/nova/releases/v1"
	bundle := artifactFixture("6")
	evaluationEvidence := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("f", 64), SubjectDigest: bundle.GetDigest(), EvidenceKind: "evaluation", PolicyDigest: "sha256:" + strings.Repeat("e", 64)}
	releaseCommand := &modelv1.RegisterModelReleaseCommand{
		Model:                 &commonv1.ResourceRef{ResourceType: "model", ResourceId: "nova", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: stored.GetRevision(), Name: stored.GetName(), Etag: stored.GetEtag()},
		ReleaseId:             "v1",
		BundleManifest:        bundle,
		ModelManifest:         artifactFixture("7"),
		Checkpoint:            &commonv1.ResourceRef{ResourceType: "checkpoint", ResourceId: "checkpoint-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/checkpoints/checkpoint-1", Etag: "checkpoint-etag"},
		EvaluationEvidence:    []*artifactv1.EvidenceRef{evaluationEvidence},
		FeatureRequirementSet: artifactFixture("8"),
		ModelFeatureView:      artifactFixture("9"),
		ReleasePolicy:         &commonv1.ResourceRef{ResourceType: "release_policy", ResourceId: "policy-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/releasePolicies/policy-1", Etag: "policy-etag"},
		PolicyClassification:  "internal",
		Context:               &commonv1.CommandContext{RequestId: "release-register-request", IdempotencyKey: "release-register-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal},
	}
	releaseDigest, err := canonicalCommandDigest(releaseCommand)
	if err != nil {
		t.Fatal(err)
	}
	releaseCommand.Context.CanonicalRequestDigest = releaseDigest
	if operation, replay, err = repository.RegisterModelRelease(ctx, identity, releaseCommand, releaseDigest, at.Add(3*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("release registration operation=%v replay=%v err=%v", operation, replay, err)
	}
	releaseOperationID := operation.GetOperationId()
	if operation, replay, err = repository.RegisterModelRelease(ctx, identity, clone(releaseCommand), releaseDigest, at.Add(3500*time.Millisecond)); err != nil || !replay || operation.GetOperationId() != releaseOperationID {
		t.Fatalf("release registration replay operation=%v replay=%v err=%v", operation, replay, err)
	}
	registeredRelease, err := repository.GetModelRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	if registeredRelease.GetRevision() != 1 || registeredRelease.GetStage() != modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL || registeredRelease.GetBundleManifest().GetDigest() != bundle.GetDigest() || len(registeredRelease.GetEvaluationEvidence()) != 1 {
		t.Fatalf("registered release=%v", registeredRelease)
	}
	releaseRef := &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: "v1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: registeredRelease.GetRevision(), Name: releaseName, Etag: registeredRelease.GetEtag()}
	promote := &modelv1.PromoteModelReleaseCommand{ModelRelease: releaseRef, Etag: registeredRelease.GetEtag(), ExpectedStage: modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL, TargetStage: modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED, Evidence: []*artifactv1.EvidenceRef{evidenceFixture("a")}, PromotionDecision: evidenceFixture("b")}
	promote.Context = &commonv1.CommandContext{RequestId: "promote-request", IdempotencyKey: "promote-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal}
	promoteDigest, err := canonicalCommandDigest(promote)
	if err != nil {
		t.Fatal(err)
	}
	promote.Context.CanonicalRequestDigest = promoteDigest
	if operation, replay, err = repository.PromoteModelRelease(ctx, identity, promote, promoteDigest, at.Add(4*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("promote operation=%v replay=%v err=%v", operation, replay, err)
	}
	promoteOperationID := operation.GetOperationId()
	if operation, replay, err = repository.PromoteModelRelease(ctx, identity, clone(promote), promoteDigest, at.Add(4500*time.Millisecond)); err != nil || !replay || operation.GetOperationId() != promoteOperationID {
		t.Fatalf("promote replay operation=%v replay=%v err=%v", operation, replay, err)
	}
	promoted, err := repository.GetModelRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	if promoted.GetRevision() != 2 || promoted.GetStage() != modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED || promoted.GetQualifyTime() == nil {
		t.Fatalf("promoted release=%v", promoted)
	}
	revoke := &modelv1.RevokeModelReleaseCommand{ModelRelease: &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: "v1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: promoted.GetRevision(), Name: releaseName, Etag: promoted.GetEtag()}, Etag: promoted.GetEtag(), Reason: "qualification withdrawn", Evidence: []*artifactv1.EvidenceRef{evidenceFixture("c")}}
	revoke.Context = &commonv1.CommandContext{RequestId: "revoke-request", IdempotencyKey: "revoke-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal}
	revokeDigest, err := canonicalCommandDigest(revoke)
	if err != nil {
		t.Fatal(err)
	}
	revoke.Context.CanonicalRequestDigest = revokeDigest
	if operation, replay, err = repository.RevokeModelRelease(ctx, identity, revoke, revokeDigest, at.Add(5*time.Second)); err != nil || replay || !operation.GetDone() {
		t.Fatalf("revoke operation=%v replay=%v err=%v", operation, replay, err)
	}
	revokeOperationID := operation.GetOperationId()
	if operation, replay, err = repository.RevokeModelRelease(ctx, identity, clone(revoke), revokeDigest, at.Add(5500*time.Millisecond)); err != nil || !replay || operation.GetOperationId() != revokeOperationID {
		t.Fatalf("revoke replay operation=%v replay=%v err=%v", operation, replay, err)
	}
	revoked, err := repository.GetModelRelease(ctx, identity, releaseName)
	if err != nil {
		t.Fatal(err)
	}
	if revoked.GetRevision() != 3 || revoked.GetStage() != modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_REVOKED || revoked.GetRevokeTime() == nil || revoked.GetRevocationReason() == "" {
		t.Fatalf("revoked release=%v", revoked)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var evaluation int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM data_model_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1),(SELECT count(*) FROM model_release_transition_evidence WHERE tenant_id=$1),(SELECT count(*) FROM model_release_evaluation_evidence WHERE tenant_id=$1)`, identity.TenantID).Scan(&receipts, &events, &audits, &models, &evaluation); err != nil {
		t.Fatal(err)
	}
	if receipts != 4 || events != 4 || audits != 4 || models != 3 || evaluation != 1 {
		t.Fatalf("receipts=%d events=%d audits=%d transition_evidence=%d evaluation_evidence=%d", receipts, events, audits, models, evaluation)
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
		envelope, decodeErr := queue.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		if _, decodeErr = queue.UnmarshalRegisteredPayload(envelope); decodeErr != nil {
			t.Fatal(decodeErr)
		}
		seen[envelope.GetEventType()]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	for _, eventType := range []string{
		"mindclade.events.model.v1.ModelRegistered",
		"mindclade.events.model.v1.ModelReleaseRegistered",
		"mindclade.events.model.v1.ModelPromoted",
		"mindclade.events.model.v1.ModelRevoked",
	} {
		if seen[eventType] != 1 {
			t.Fatalf("typed event distribution=%v", seen)
		}
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
	immutable, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = immutable.ExecContext(ctx, `UPDATE model_release_transition_evidence SET evidence_kind='rewritten' WHERE tenant_id=$1`, identity.TenantID); err == nil {
		t.Fatal("immutable transition evidence accepted an update")
	}
	_ = immutable.Rollback()
}
