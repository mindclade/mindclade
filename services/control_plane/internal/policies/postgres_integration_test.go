package policies

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
	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
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

func integrationContext(identity Identity, requestID, key string) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: requestID, IdempotencyKey: key, TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, TraceId: "trace-" + requestID}
}

func TestPostgresPolicyLifecycleDecisionAndRLS(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "policy-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("policy-integration-page-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}, Evaluator: DenyAllEvaluator{ReasonCode: "DEFAULT_DENY"}}
	at := time.Now().UTC()
	create := &internalpolicyv1.CreateUsePolicyRequest{
		Parent: projectParent(identity), UsePolicyId: "safe",
		UsePolicy: &policyv1.UsePolicy{DisplayName: "Safe use", PolicyDocument: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/schema+json", SizeBytes: 42, SchemaId: "mindclade.use-policy", SchemaVersion: "1"}, PermittedPurposes: []string{"research"}, PermittedCapabilities: []string{"model.read"}, ProhibitedCapabilities: []string{"model.export"}, AcceptedClassifications: []string{"internal"}, ApprovalRequirements: []*policyv1.ApprovalRequirement{{Action: "model.export", RiskClass: policyv1.UseRiskClass_USE_RISK_CLASS_HIGH, MinimumIndependentApprovers: 2}}},
	}
	create.Context = integrationContext(identity, "create", "create-key")
	createDigest, err := canonicalCommandDigest(create)
	if err != nil {
		t.Fatal(err)
	}
	create.Context.CanonicalRequestDigest = createDigest
	operation, replay, err := repository.CreateUsePolicy(ctx, identity, create, createDigest, at)
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayed, replay, err := repository.CreateUsePolicy(ctx, identity, clone(create), createDigest, at.Add(time.Millisecond))
	if err != nil || !replay || replayed.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("replayed=%v replay=%v err=%v", replayed, replay, err)
	}
	name := projectParent(identity) + "/usePolicies/safe"
	created, err := repository.GetUsePolicy(ctx, identity, name)
	if err != nil {
		t.Fatal(err)
	}
	if created.GetPolicyDocument().GetSchemaId() != "mindclade.use-policy" || len(created.GetApprovalRequirements()) != 1 || created.GetPermittedPurposes()[0] != "research" {
		t.Fatalf("policy round trip lost fields: %v", created)
	}
	update := &internalpolicyv1.UpdateUsePolicyRequest{UsePolicy: &policyv1.UsePolicy{Name: name, Etag: created.GetEtag(), DisplayName: "Safe use v2"}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: created.GetEtag()}
	update.Context = integrationContext(identity, "update", "update-key")
	updateDigest, err := canonicalCommandDigest(update)
	if err != nil {
		t.Fatal(err)
	}
	update.Context.CanonicalRequestDigest = updateDigest
	if _, _, err = repository.UpdateUsePolicy(ctx, identity, update, updateDigest, at.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	updated, err := repository.GetUsePolicy(ctx, identity, name)
	if err != nil || updated.GetDisplayName() != "Safe use v2" || updated.GetRevision() != 2 {
		t.Fatalf("updated=%v err=%v", updated, err)
	}
	stale := clone(update)
	stale.Context = integrationContext(identity, "stale", "stale-key")
	staleDigest, err := canonicalCommandDigest(stale)
	if err != nil {
		t.Fatal(err)
	}
	stale.Context.CanonicalRequestDigest = staleDigest
	if _, _, err = repository.UpdateUsePolicy(ctx, identity, stale, staleDigest, at.Add(2*time.Second)); !errors.Is(err, ErrRevisionConflict) {
		t.Fatalf("stale update error=%v", err)
	}
	activate := &internalpolicyv1.ActivateUsePolicyRequest{Name: name, Etag: updated.GetEtag()}
	activate.Context = integrationContext(identity, "activate", "activate-key")
	activateDigest, err := canonicalCommandDigest(activate)
	if err != nil {
		t.Fatal(err)
	}
	activate.Context.CanonicalRequestDigest = activateDigest
	if _, _, err = repository.ActivateUsePolicy(ctx, identity, activate, activateDigest, at.Add(3*time.Second)); err != nil {
		t.Fatal(err)
	}
	active, err := repository.GetUsePolicy(ctx, identity, name)
	if err != nil || active.GetState() != policyv1.UsePolicyState_USE_POLICY_STATE_ACTIVE || active.GetActiveSnapshot() == nil {
		t.Fatalf("active=%v err=%v", active, err)
	}
	resolved, err := repository.ResolvePolicySnapshot(ctx, identity, name, at.Add(4*time.Second))
	if err != nil || resolved.GetDigest() != active.GetPolicyDocument().GetDigest() {
		t.Fatalf("resolved=%v err=%v", resolved, err)
	}
	evaluate := &internalpolicyv1.EvaluateAuthorizationRequest{TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalRef: identity.Principal, Action: "model.export", Resource: &commonv1.ResourceRef{ResourceType: "model", ResourceId: "m", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: projectParent(identity) + "/models/m"}, IntentDigest: "sha256:" + strings.Repeat("b", 64), PolicySnapshots: []*policyv1.PolicyReference{resolved}}
	evaluate.Context = integrationContext(identity, "evaluate", "evaluate-key")
	evaluateDigest, err := canonicalCommandDigest(evaluate)
	if err != nil {
		t.Fatal(err)
	}
	evaluate.Context.CanonicalRequestDigest = evaluateDigest
	decision, replay, err := repository.EvaluateAuthorization(ctx, identity, evaluate, evaluateDigest, at.Add(4*time.Second))
	if err != nil || replay || decision.GetOutcome() != policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY || decision.GetReasonCode() != "DEFAULT_DENY" || !validSHA256(decision.GetDecisionDigest()) {
		t.Fatalf("decision=%v replay=%v err=%v", decision, replay, err)
	}
	replayedDecision, replay, err := repository.EvaluateAuthorization(ctx, identity, clone(evaluate), evaluateDigest, at.Add(5*time.Second))
	if err != nil || !replay || replayedDecision.GetName() != decision.GetName() {
		t.Fatalf("replayed decision=%v replay=%v err=%v", replayedDecision, replay, err)
	}
	revoke := &internalpolicyv1.RevokeUsePolicyRequest{Name: name, Etag: active.GetEtag(), ReasonCode: "POLICY_WITHDRAWN"}
	revoke.Context = integrationContext(identity, "revoke", "revoke-key")
	revokeDigest, err := canonicalCommandDigest(revoke)
	if err != nil {
		t.Fatal(err)
	}
	revoke.Context.CanonicalRequestDigest = revokeDigest
	if _, _, err = repository.RevokeUsePolicy(ctx, identity, revoke, revokeDigest, at.Add(6*time.Second)); err != nil {
		t.Fatal(err)
	}
	revoked, err := repository.GetUsePolicy(ctx, identity, name)
	if err != nil || revoked.GetState() != policyv1.UsePolicyState_USE_POLICY_STATE_REVOKED || revoked.GetRevision() != 4 {
		t.Fatalf("revoked=%v err=%v", revoked, err)
	}
	listed, _, _, err := repository.ListUsePolicies(ctx, identity, PolicyPage{Limit: 10, Order: "create_time desc,name desc"})
	if err != nil || len(listed) != 1 || listed[0].GetName() != name {
		t.Fatalf("listed=%v err=%v", listed, err)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var policies, decisions, receipts, outbox, audits int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM use_policies WHERE tenant_id=$1),(SELECT count(*) FROM authorization_decisions WHERE tenant_id=$1),(SELECT count(*) FROM policy_admin_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM administrative_audit_records WHERE tenant_id=$1)`, identity.TenantID).Scan(&policies, &decisions, &receipts, &outbox, &audits); err != nil {
		t.Fatal(err)
	}
	if policies != 1 || decisions != 1 || receipts != 5 || outbox != 6 || audits != 5 {
		t.Fatalf("policies=%d decisions=%d receipts=%d outbox=%d audits=%d", policies, decisions, receipts, outbox, audits)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	var securityEvent *auditv1.SecurityEvent
	var securityEnvelope *commonv1.EventEnvelope
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		if value, ok := payload.(*auditv1.SecurityEvent); ok {
			if securityEvent != nil {
				t.Fatal("authorization denial produced more than one SecurityEvent")
			}
			securityEvent, securityEnvelope = value, envelope
		}
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	if securityEvent == nil || securityEvent.GetSeverity() != "high" || securityEvent.GetControl() != decision.GetReasonCode() ||
		securityEvent.GetEvidenceDigest() != decision.GetDecisionDigest() || securityEnvelope.GetClassification() != commonv1.DataClassification_DATA_CLASSIFICATION_RESTRICTED ||
		securityEnvelope.GetSubject().GetResourceType() != "security_event" || !strings.HasPrefix(securityEnvelope.GetSubject().GetName(), decision.GetName()+"/securityEvents/security-") ||
		securityEnvelope.GetSubject().GetResourceVersion() != 1 || securityEnvelope.GetSubject().GetEtag() != decision.GetDecisionDigest() {
		t.Fatalf("transactional policy denial SecurityEvent is incomplete: envelope=%v payload=%v decision=%v", securityEnvelope, securityEvent, decision)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
	other, err := platformdb.BeginTenantTx(ctx, db, "other-"+identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Rollback() }()
	if _, err = db.ExecContext(ctx, `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mindclade_policy_rls_probe') THEN CREATE ROLE mindclade_policy_rls_probe NOLOGIN; END IF; END $$; GRANT SELECT ON use_policies TO mindclade_policy_rls_probe`); err != nil {
		t.Fatal(err)
	}
	if _, err = other.ExecContext(ctx, `SET LOCAL ROLE mindclade_policy_rls_probe`); err != nil {
		t.Fatal(err)
	}
	var visible int
	if err = other.QueryRowContext(ctx, `SELECT count(*) FROM use_policies WHERE name=$1`, name).Scan(&visible); err != nil {
		t.Fatal(err)
	}
	if visible != 0 {
		t.Fatalf("RLS exposed %d policy rows across tenants", visible)
	}
}

func TestPostgresDeniedCommandsProduceDistinctTransactionalSecurityFacts(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "policy-security-" + suffix, ProjectID: "project", Principal: "principal"}
	subject := &commonv1.ResourceRef{
		ResourceType: "model", ResourceId: "model-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		ResourceVersion: 1, Name: projectParent(identity) + "/models/model-1",
	}
	decisionDigest := "sha256:" + strings.Repeat("a", 64)
	detailDigest := "sha256:" + strings.Repeat("b", 64)
	first := integrationContext(identity, "denied-request-1", "denied-key-1")
	second := integrationContext(identity, "denied-request-2", "denied-key-2")
	at := time.Now().UTC()

	tx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if err = insertPolicyAudit(ctx, tx, identity, "model.export", subject, 3, "DEFAULT_DENY", decisionDigest, "1", "1", detailDigest, first, at); err != nil {
		t.Fatal(err)
	}
	if err = insertPolicyAudit(ctx, tx, identity, "model.export", subject, 3, "DEFAULT_DENY", decisionDigest, "1", "1", detailDigest, second, at.Add(time.Nanosecond)); err != nil {
		t.Fatalf("second independent denial collided transactionally: %v", err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}

	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type='mindclade.events.audit.v1.SecurityEvent' ORDER BY created_at,id`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = platformdb.CloseRows(rows) }()
	eventIDs, subjectIDs, requestIDs := map[string]struct{}{}, map[string]struct{}{}, map[string]struct{}{}
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
		eventIDs[envelope.GetEventId()] = struct{}{}
		subjectIDs[envelope.GetSubject().GetResourceId()] = struct{}{}
		requestIDs[envelope.GetRequestId()] = struct{}{}
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	if len(eventIDs) != 2 || len(subjectIDs) != 2 || len(requestIDs) != 2 {
		t.Fatalf("distinct denials were not preserved: events=%v subjects=%v requests=%v", eventIDs, subjectIDs, requestIDs)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
}
