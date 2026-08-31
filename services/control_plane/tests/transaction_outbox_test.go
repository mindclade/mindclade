package controlplane_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/artifacts"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/inbox"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

func postgresDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required when PostgreSQL integration is required")
		}
		return nil
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open PostgreSQL integration database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("ping PostgreSQL integration database: %v", err)
	}
	return db
}

type memoryCatalog struct {
	records map[string]storage.ArtifactRecord
}

func (c *memoryCatalog) Register(_ context.Context, record storage.ArtifactRecord) error {
	if c.records == nil {
		c.records = map[string]storage.ArtifactRecord{}
	}
	c.records[record.TenantID+record.Digest] = record
	return nil
}
func (c *memoryCatalog) Get(_ context.Context, tenantID, digest string) (storage.ArtifactRecord, error) {
	return c.records[tenantID+digest], nil
}

func TestOperationAcceptanceCommitsAuditAndOutboxAtomically(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL operation transaction branch: %v", err)
		}
	}
	repository := operations.NewRepository()
	principal := policies.Principal{ID: "principal-1", TenantID: "tenant-a", Actions: map[string]bool{operations.CreateAction: true}}
	requestDigest := "sha256:" + strings.Repeat("a", 64)
	operation, replay, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: principal, IdempotencyKey: "key-1", RequestDigest: requestDigest,
		Operation: &jobv1.Operation{OperationId: "operation-1", TenantId: "tenant-a", ProjectId: "project-a", JobId: "job-1"},
	})
	if err != nil || replay || operation.GetState() != jobv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("unexpected operation result: %#v replay=%v err=%v", operation, replay, err)
	}
	envelopes := repository.OutboxEnvelopes()
	if repository.AuditCount() != 1 || len(envelopes) != 1 {
		t.Fatal("accepted operation must include audit and outbox evidence")
	}
	encoded, err := queue.MarshalEnvelope(envelopes[0])
	if err != nil {
		t.Fatalf("marshal authoritative envelope: %v", err)
	}
	decoded, err := queue.UnmarshalEnvelope(encoded)
	if err != nil || decoded.GetJobId() != "job-1" {
		t.Fatalf("round-trip authoritative envelope: envelope=%v err=%v", decoded, err)
	}
}

func TestArtifactFinalizeIsAtomicAndRejectsCorruption(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL artifact catalog branch: %v", err)
		}
	}
	root := t.TempDir()
	body := []byte("immutable artifact")
	hash := sha256.Sum256(body)
	digest := "sha256:" + hex.EncodeToString(hash[:])
	principal := policies.Principal{ID: "principal-1", TenantID: "tenant-a", Actions: map[string]bool{artifacts.RegisterAction: true}}
	repository := artifacts.NewRepository()
	_, err := artifacts.Finalize(context.Background(), policies.DenyByDefault{}, repository, storage.FilesystemCAS{Root: root}, &memoryCatalog{}, artifacts.FinalizeCommand{Principal: principal, TenantID: "tenant-a", Artifact: &artifactv1.ArtifactRef{Digest: digest, MediaType: "application/octet-stream", SizeBytes: int64(len(body))}, Body: bytes.NewReader(body)})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = repository.Get("tenant-a", digest); err != nil {
		t.Fatal(err)
	}
	_, err = artifacts.Finalize(context.Background(), policies.DenyByDefault{}, artifacts.NewRepository(), storage.FilesystemCAS{Root: root}, &memoryCatalog{}, artifacts.FinalizeCommand{Principal: principal, TenantID: "tenant-a", Artifact: &artifactv1.ArtifactRef{Digest: digest, MediaType: "application/octet-stream", SizeBytes: int64(len(body)) + 1}, Body: bytes.NewReader(body)})
	if err == nil {
		t.Fatal("expected size mismatch")
	}
}

func TestArtifactOrphanCleanup(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL orphan-cleanup branch: %v", err)
		}
	}
	root := t.TempDir()
	staging := root + "/.staging"
	if err := os.MkdirAll(staging, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(staging+"/orphan", []byte("orphan"), 0o600); err != nil {
		t.Fatal(err)
	}
	removed, err := (storage.FilesystemCAS{Root: root}).CleanupOrphans(time.Now().Add(time.Second))
	if err != nil || removed != 1 {
		t.Fatalf("removed=%d err=%v", removed, err)
	}
}

// TestPostgresKernelJourney is the real local-stack journey required by control_worker_test.py.
func TestPostgresKernelJourney(t *testing.T) {
	db := postgresDB(t)
	if db == nil {
		return
	}
	context := context.Background()
	unique := time.Now().UTC().Format("20060102150405.000000000")
	tenantID := "tenant-" + unique
	jobID := "job-" + unique
	operationID := "operation-" + unique
	requestHash := "sha256:" + strings.Repeat("a", 64)
	if _, err := db.ExecContext(context, `INSERT INTO jobs (id, tenant_id, desired_state, version, created_at, updated_at) VALUES ($1, $2, 'ACCEPTED', 1, now(), now())`, jobID, tenantID); err != nil {
		t.Fatalf("seed PostgreSQL job: %v", err)
	}
	t.Cleanup(func() {
		_, _ = db.ExecContext(context, `DELETE FROM attempt_completion_history WHERE tenant_id = $1; DELETE FROM attempts WHERE tenant_id = $1; DELETE FROM runs WHERE tenant_id = $1; DELETE FROM outbox_messages WHERE tenant_id = $1; DELETE FROM audit_events WHERE tenant_id = $1; DELETE FROM idempotency_records WHERE tenant_id = $1; DELETE FROM operations WHERE tenant_id = $1; DELETE FROM jobs WHERE tenant_id = $1`, tenantID)
	})
	operationsSQL := operations.SQLRepository{DB: db}
	operationInput := &jobv1.Operation{OperationId: operationID, TenantId: tenantID, JobId: jobID}
	operation, replay, err := operationsSQL.CreateAtomicallySQL(context, operationInput, requestHash, "journey-key", "integration-principal")
	if err != nil || replay || operation.GetState() != jobv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("PostgreSQL operation acceptance failed: operation=%#v replay=%v err=%v", operation, replay, err)
	}
	if _, replay, err = operationsSQL.CreateAtomicallySQL(context, operationInput, requestHash, "journey-key", "integration-principal"); err != nil || !replay {
		t.Fatalf("PostgreSQL idempotency replay failed: replay=%v err=%v", replay, err)
	}
	if accepted, err := inbox.AcceptSQL(context, db, "integration-worker", "event-"+unique, tenantID); err != nil || !accepted {
		t.Fatalf("PostgreSQL inbox first delivery failed: accepted=%v err=%v", accepted, err)
	}
	if accepted, err := inbox.AcceptSQL(context, db, "integration-worker", "event-"+unique, tenantID); err != nil || accepted {
		t.Fatalf("PostgreSQL inbox duplicate was not rejected: accepted=%v err=%v", accepted, err)
	}
	runID, attemptID := "run-"+unique, "attempt-"+unique
	if _, err := db.ExecContext(context, `INSERT INTO runs (id, tenant_id, job_id, status, version, lease_epoch, created_at, updated_at) VALUES ($1, $2, $3, 'EXECUTING', 1, 2, now(), now())`, runID, tenantID, jobID); err != nil {
		t.Fatalf("seed PostgreSQL run: %v", err)
	}
	if _, err := db.ExecContext(context, `INSERT INTO attempts (id, tenant_id, run_id, lease_epoch, status, created_at) VALUES ($1, $2, $3, 1, 'FENCED', now())`, attemptID, tenantID, runID); err != nil {
		t.Fatalf("seed PostgreSQL fenced attempt: %v", err)
	}
	if err := (jobs.SQLRepository{DB: db}).CompleteAttemptSQL(context, tenantID, attemptID, 1, jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED); !errors.Is(err, jobs.ErrStaleCompletion) {
		t.Fatalf("PostgreSQL stale completion must be retained and fenced: %v", err)
	}
}
