package controlplane_test

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

func TestTenantIsolationAndDefaultDeny(t *testing.T) {
	if db := postgresDB(t); db != nil {
		assertPostgresTenantIsolation(t, db)
	}
	repository := operations.NewRepository()
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal:      policies.Principal{ID: "principal-a", TenantID: "tenant-a", Actions: map[string]bool{operations.CreateAction: true}},
		IdempotencyKey: "key-1",
		RequestDigest:  "sha256:" + strings.Repeat("a", 64),
		Operation:      &operationv1.Operation{OperationId: "operation-1", TenantId: "tenant-b", ProjectId: "project-a", JobId: "job-1", Etag: "operation-etag-1"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected tenant denial, got %v", err)
	}
	_, _, err = operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal:      policies.Principal{ID: "principal-a", TenantID: "tenant-a"},
		IdempotencyKey: "key-2",
		RequestDigest:  "sha256:" + strings.Repeat("a", 64),
		Operation:      &operationv1.Operation{OperationId: "operation-2", TenantId: "tenant-a", ProjectId: "project-a", JobId: "job-1", Etag: "operation-etag-1"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected default deny, got %v", err)
	}
}

func assertPostgresTenantIsolation(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("150405.000000000"), ".", "")
	role := "mindclade_rls_test_" + suffix
	tenantA, tenantB := "tenant-rls-a-"+suffix, "tenant-rls-b-"+suffix
	jobA, jobB := "job-rls-a-"+suffix, "job-rls-b-"+suffix
	digestA := "sha256:" + strings.Repeat("a", 64)
	digestB := "sha256:" + strings.Repeat("b", 64)
	if _, err := db.ExecContext(ctx, fmt.Sprintf(`CREATE ROLE %s NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`, role)); err != nil {
		t.Fatalf("create non-bypass RLS test role: %v", err)
	}
	t.Cleanup(func() {
		if _, cleanupErr := db.ExecContext(ctx, `DELETE FROM jobs WHERE tenant_id IN ($1,$2)`, tenantA, tenantB); cleanupErr != nil {
			t.Errorf("clean tenant-isolation jobs: %v", cleanupErr)
		}
		if _, cleanupErr := db.ExecContext(ctx, `DELETE FROM artifact_references WHERE tenant_id IN ($1,$2)`, tenantA, tenantB); cleanupErr != nil {
			t.Errorf("clean tenant-isolation artifacts: %v", cleanupErr)
		}
		if _, cleanupErr := db.ExecContext(ctx, fmt.Sprintf(`DROP OWNED BY %s; DROP ROLE %s`, role, role)); cleanupErr != nil {
			t.Errorf("drop tenant-isolation role: %v", cleanupErr)
		}
	})
	var refA, refB int64
	if err := db.QueryRowContext(ctx, `INSERT INTO artifact_references (tenant_id,digest,media_type,size_bytes) VALUES ($1,$2,'application/json',1) RETURNING id`, tenantA, digestA).Scan(&refA); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRowContext(ctx, `INSERT INTO artifact_references (tenant_id,digest,media_type,size_bytes) VALUES ($1,$2,'application/json',1) RETURNING id`, tenantB, digestB).Scan(&refB); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, `INSERT INTO jobs (id,tenant_id,desired_state,version,configuration_ref_id,configuration_digest,created_at,updated_at) VALUES ($1,$2,'ACCEPTED',1,$3,$4,now(),now()),($5,$6,'ACCEPTED',1,$7,$8,now(),now())`, jobA, tenantA, refA, digestA, jobB, tenantB, refB, digestB); err != nil {
		t.Fatalf("seed tenant isolation rows: %v", err)
	}
	if _, err := db.ExecContext(ctx, `GRANT SELECT ON jobs TO `+role); err != nil { // #nosec G202 -- role is a fixed test-only identifier.
		t.Fatal(err)
	}
	var forced bool
	if err := db.QueryRowContext(ctx, `SELECT relforcerowsecurity FROM pg_class WHERE oid = 'jobs'::regclass`).Scan(&forced); err != nil || !forced {
		t.Fatalf("jobs must FORCE ROW LEVEL SECURITY: forced=%v err=%v", forced, err)
	}
	tx, err := db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE `+role); err != nil { // #nosec G202 -- role is a fixed test-only identifier.
		t.Fatal(err)
	}
	var count int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM jobs`).Scan(&count); err != nil || count != 0 {
		t.Fatalf("missing tenant scope must see no rows: count=%d err=%v", count, err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id',$1,true)`, tenantA); err != nil {
		t.Fatal(err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM jobs`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("bound tenant must see exactly its row: count=%d err=%v", count, err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM jobs WHERE tenant_id = $1`, tenantB).Scan(&count); err != nil || count != 0 {
		t.Fatalf("cross-tenant predicate must remain invisible: count=%d err=%v", count, err)
	}
}
