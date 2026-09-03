package admin

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
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

func integrationContext(identity Identity, projectID, requestID, key string) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: requestID, IdempotencyKey: key, TenantId: identity.TenantID, ProjectId: projectID, PrincipalId: identity.Principal, TraceId: "trace-" + requestID}
}

func TestPostgresAdminLifecycleAuditExportAndRLS(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "admin-tenant-" + suffix, Principal: "admin"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("admin-integration-page-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	at := time.Now().UTC()
	tenantCanonical := "tenants/" + identity.TenantID
	seed, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	tenantETag := resourceETag(tenantCanonical, 1)
	if _, err = seed.ExecContext(ctx, `INSERT INTO administrative_tenants(tenant_id,name,uid,revision,etag,display_name,state,default_classification,create_time,update_time) VALUES($1,$2,$3,1,$4,'Tenant',$5,'internal',$6,$6)`, identity.TenantID, tenantCanonical, "tenant-uid-"+suffix, tenantETag, int32(adminv1.TenantState_TENANT_STATE_PROVISIONING), at.UTC()); err != nil {
		t.Fatal(err)
	}
	if err = seed.Commit(); err != nil {
		t.Fatal(err)
	}
	updateTenant := &internaladminv1.UpdateTenantRequest{Tenant: &adminv1.Tenant{Name: tenantCanonical, DisplayName: "Tenant Active", State: adminv1.TenantState_TENANT_STATE_ACTIVE, AllowedRegions: []string{"us-central1"}, Labels: map[string]string{"environment": "test"}}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name", "state", "allowed_regions", "labels"}}, Etag: tenantETag}
	updateTenant.Context = integrationContext(identity, "", "tenant-update", "tenant-update-key")
	tenantDigest, err := canonicalCommandDigest(updateTenant)
	if err != nil {
		t.Fatal(err)
	}
	updateTenant.Context.CanonicalRequestDigest = tenantDigest
	operation, replay, err := repository.UpdateTenant(ctx, identity, updateTenant, tenantDigest, at.Add(time.Second))
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("tenant operation=%v replay=%v err=%v", operation, replay, err)
	}
	tenant, err := repository.GetTenant(ctx, identity, tenantCanonical)
	if err != nil || tenant.GetRevision() != 2 || tenant.GetLabels()["environment"] != "test" || tenant.GetAllowedRegions()[0] != "us-central1" {
		t.Fatalf("tenant=%v err=%v", tenant, err)
	}
	projectID := "project"
	projectCanonical := tenantCanonical + "/projects/" + projectID
	tenantRef := &commonv1.ResourceRef{ResourceType: "tenant", ResourceId: identity.TenantID, TenantId: identity.TenantID, ResourceVersion: tenant.GetRevision(), Name: tenantCanonical, Etag: tenant.GetEtag()}
	createProject := &internaladminv1.CreateProjectRequest{Parent: tenantCanonical, ProjectId: projectID, Project: &adminv1.Project{Tenant: tenantRef, DisplayName: "Project", Purpose: "research", DefaultClassification: "internal", Quota: &adminv1.ProjectQuota{MaximumConcurrentJobs: 3, MaximumStorageBytes: 1024}, Labels: map[string]string{"team": "science"}, Annotations: map[string]string{"owner": "platform"}}}
	createProject.Context = integrationContext(identity, projectID, "project-create", "project-create-key")
	projectDigest, err := canonicalCommandDigest(createProject)
	if err != nil {
		t.Fatal(err)
	}
	createProject.Context.CanonicalRequestDigest = projectDigest
	operation, replay, err = repository.CreateProject(ctx, identity, createProject, projectDigest, at.Add(2*time.Second))
	if err != nil || replay || !operation.GetDone() {
		t.Fatalf("project operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayed, replay, err := repository.CreateProject(ctx, identity, clone(createProject), projectDigest, at.Add(3*time.Second))
	if err != nil || !replay || replayed.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("project replay=%v replay=%v err=%v", replayed, replay, err)
	}
	project, err := repository.GetProject(ctx, identity, projectCanonical)
	if err != nil || project.GetQuota().GetMaximumStorageBytes() != 1024 || project.GetLabels()["team"] != "science" || project.GetAnnotations()["owner"] != "platform" {
		t.Fatalf("project=%v err=%v", project, err)
	}
	updateProject := &internaladminv1.UpdateProjectRequest{Project: &adminv1.Project{Name: projectCanonical, DisplayName: "Project Active", State: adminv1.ProjectState_PROJECT_STATE_ACTIVE}, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name", "state"}}, Etag: project.GetEtag()}
	updateProject.Context = integrationContext(identity, projectID, "project-update", "project-update-key")
	updateDigest, err := canonicalCommandDigest(updateProject)
	if err != nil {
		t.Fatal(err)
	}
	updateProject.Context.CanonicalRequestDigest = updateDigest
	if _, _, err = repository.UpdateProject(ctx, identity, updateProject, updateDigest, at.Add(4*time.Second)); err != nil {
		t.Fatal(err)
	}
	updated, err := repository.GetProject(ctx, identity, projectCanonical)
	if err != nil || updated.GetDisplayName() != "Project Active" || updated.GetState() != adminv1.ProjectState_PROJECT_STATE_ACTIVE || updated.GetQuota().GetMaximumStorageBytes() != 1024 {
		t.Fatalf("updated project=%v err=%v", updated, err)
	}
	projects, _, _, err := repository.ListProjects(ctx, identity, ProjectPage{Limit: 10, Order: "create_time desc,name desc"})
	if err != nil || len(projects) != 1 || projects[0].GetName() != projectCanonical {
		t.Fatalf("projects=%v err=%v", projects, err)
	}
	query := &adminv1.AuditQuery{Parent: projectCanonical, StartTime: timestamppb.New(at.Add(-time.Minute)), EndTime: timestamppb.New(at.Add(time.Hour)), Page: &commonv1.PageRequest{PageSize: 50}}
	queryDigest, err := auditQueryDigest(query)
	if err != nil {
		t.Fatal(err)
	}
	records, _, err := repository.QueryAuditRecords(ctx, identity, query, AuditPage{Limit: 50, ProjectID: projectID, QueryDigest: queryDigest})
	if err != nil || len(records) != 2 {
		t.Fatalf("records=%v err=%v", records, err)
	}
	failExport := &internaladminv1.ExportAuditRecordsRequest{Query: clone(query)}
	failExport.Context = integrationContext(identity, projectID, "export-failed", "export-failed-key")
	failDigest, err := canonicalCommandDigest(failExport)
	if err != nil {
		t.Fatal(err)
	}
	failExport.Context.CanonicalRequestDigest = failDigest
	failedOperation, replay, err := repository.ExportAuditRecords(ctx, identity, failExport, failDigest, at.Add(5*time.Second))
	if err != nil || replay || !failedOperation.GetDone() || failedOperation.GetState() != jobv1.OperationState_OPERATION_STATE_FAILED || failedOperation.GetError().GetCode() != commonv1.ErrorCode_ERROR_CODE_UNAVAILABLE {
		t.Fatalf("failed operation=%v replay=%v err=%v", failedOperation, replay, err)
	}
	failedExport, err := repository.GetAuditExport(ctx, identity, failedOperation.GetTarget().GetName())
	if err != nil || failedExport.GetState() != adminv1.AuditExportState_AUDIT_EXPORT_STATE_FAILED || failedExport.GetFailureCode() != "EXPORTER_NOT_CONFIGURED" {
		t.Fatalf("failed export=%v err=%v", failedExport, err)
	}
	configured := repository
	configured.ExporterConfigured = true
	requestExport := &internaladminv1.ExportAuditRecordsRequest{Query: clone(query)}
	requestExport.Context = integrationContext(identity, projectID, "export-requested", "export-requested-key")
	requestDigest, err := canonicalCommandDigest(requestExport)
	if err != nil {
		t.Fatal(err)
	}
	requestExport.Context.CanonicalRequestDigest = requestDigest
	pendingOperation, replay, err := configured.ExportAuditRecords(ctx, identity, requestExport, requestDigest, at.Add(6*time.Second))
	if err != nil || replay || pendingOperation.GetDone() || pendingOperation.GetState() != jobv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("pending operation=%v replay=%v err=%v", pendingOperation, replay, err)
	}
	pendingExport, err := configured.GetAuditExport(ctx, identity, pendingOperation.GetTarget().GetName())
	if err != nil || pendingExport.GetState() != adminv1.AuditExportState_AUDIT_EXPORT_STATE_REQUESTED {
		t.Fatalf("pending export=%v err=%v", pendingExport, err)
	}
	exporterIdentity := identity
	exporterIdentity.ProjectID = projectID
	exporterIdentity.Principal = "audit-exporter"
	completed, err := configured.CompleteAuditExport(ctx, exporterIdentity, pendingExport.GetName(), pendingExport.GetEtag(), &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("c", 64), MediaType: "application/x-ndjson", SizeBytes: 2048, ArtifactKind: "audit-export", SchemaVersion: "1"}, at.Add(7*time.Second))
	if err != nil || completed.GetState() != adminv1.AuditExportState_AUDIT_EXPORT_STATE_SUCCEEDED || completed.GetArtifact().GetArtifactKind() != "audit-export" || completed.GetRevision() != 2 {
		t.Fatalf("completed=%v err=%v", completed, err)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var tenants, projectCount, exportCount, receipts, outbox, audits int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM administrative_tenants WHERE tenant_id=$1),(SELECT count(*) FROM administrative_projects WHERE tenant_id=$1),(SELECT count(*) FROM audit_exports WHERE tenant_id=$1),(SELECT count(*) FROM policy_admin_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM administrative_audit_records WHERE tenant_id=$1)`, identity.TenantID).Scan(&tenants, &projectCount, &exportCount, &receipts, &outbox, &audits); err != nil {
		t.Fatal(err)
	}
	if tenants != 1 || projectCount != 1 || exportCount != 2 || receipts != 5 || outbox != 6 || audits != 6 {
		t.Fatalf("tenants=%d projects=%d exports=%d receipts=%d outbox=%d audits=%d", tenants, projectCount, exportCount, receipts, outbox, audits)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	var tenantUpdates int
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
		if _, ok := payload.(*adminv1.TenantUpdated); ok {
			tenantUpdates++
			if envelope.GetAggregateSequence() != 1 || envelope.GetSubject().GetResourceVersion() != 2 {
				t.Fatalf("tenant update sequence=%d resource revision=%d", envelope.GetAggregateSequence(), envelope.GetSubject().GetResourceVersion())
			}
		}
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	if tenantUpdates != 1 {
		t.Fatalf("tenant update event count=%d", tenantUpdates)
	}
	var sequenceGaps int
	if err = verify.QueryRowContext(ctx, `
SELECT count(*)
FROM outbox_messages current
WHERE current.tenant_id=$1
  AND current.aggregate_sequence > 1
  AND NOT EXISTS (
    SELECT 1 FROM outbox_messages predecessor
    WHERE predecessor.tenant_id=current.tenant_id
      AND predecessor.aggregate_type=current.aggregate_type
      AND predecessor.aggregate_id=current.aggregate_id
      AND predecessor.aggregate_sequence=current.aggregate_sequence-1
  )`, identity.TenantID).Scan(&sequenceGaps); err != nil {
		t.Fatal(err)
	}
	if sequenceGaps != 0 {
		t.Fatalf("admin outbox contains %d undeliverable aggregate sequence gaps", sequenceGaps)
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
	if _, err = db.ExecContext(ctx, `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mindclade_admin_rls_probe') THEN CREATE ROLE mindclade_admin_rls_probe NOLOGIN; END IF; END $$; GRANT SELECT ON administrative_projects TO mindclade_admin_rls_probe`); err != nil {
		t.Fatal(err)
	}
	other, err := platformdb.BeginTenantTx(ctx, db, "other-"+identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Rollback() }()
	if _, err = other.ExecContext(ctx, `SET LOCAL ROLE mindclade_admin_rls_probe`); err != nil {
		t.Fatal(err)
	}
	var visible int
	if err = other.QueryRowContext(ctx, `SELECT count(*) FROM administrative_projects WHERE name=$1`, projectCanonical).Scan(&visible); err != nil {
		t.Fatal(err)
	}
	if visible != 0 {
		t.Fatalf("RLS exposed %d administrative project rows across tenants", visible)
	}
}
