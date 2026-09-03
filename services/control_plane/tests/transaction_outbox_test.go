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
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	"github.com/mindclade/mindclade/libs/go/inbox"
	"github.com/mindclade/mindclade/libs/go/outbox"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	"github.com/mindclade/mindclade/libs/go/storage"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/artifacts"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

type standardContext = context.Context

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

type recordingPublisher struct {
	failures  int
	published []*commonv1.EventEnvelope
}

type acknowledgeFailingStore struct {
	*outbox.Store
	failures int
}

func (s *acknowledgeFailingStore) Acknowledge(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	if s.failures > 0 {
		s.failures--
		return false, errors.New("synthetic crash before durable acknowledgement")
	}
	return s.Store.Acknowledge(ctx, tenantID, id, epoch, at)
}

func (p *recordingPublisher) Publish(_ context.Context, envelope *commonv1.EventEnvelope) error {
	if p.failures > 0 {
		p.failures--
		return errors.New("synthetic transport failure")
	}
	p.published = append(p.published, proto.Clone(envelope).(*commonv1.EventEnvelope))
	return nil
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
		ConfigurationDigest: "sha256:" + strings.Repeat("c", 64),
		Operation:           &operationv1.Operation{OperationId: "operation-1", TenantId: "tenant-a", ProjectId: "project-a", JobId: "job-1", Etag: "operation-etag-1"},
	})
	if err != nil || replay || operation.GetState() != operationv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("unexpected operation result: %#v replay=%v err=%v", operation, replay, err)
	}
	envelopes := repository.OutboxEnvelopes()
	if repository.AuditCount() != 1 || len(envelopes) != 1 {
		t.Fatal("accepted operation must include audit and outbox evidence")
	}
	auditEnvelopes := repository.AuditEnvelopes()
	if len(auditEnvelopes) != 1 {
		t.Fatal("accepted operation must include one generated audit envelope")
	}
	auditPayload, err := foundationaudit.ValidateEvent(auditEnvelopes[0])
	if err != nil || auditPayload.GetAction() != operations.CreateAction {
		t.Fatalf("validate authoritative audit envelope: payload=%v err=%v", auditPayload, err)
	}
	encoded, err := pubsubx.MarshalEnvelope(envelopes[0])
	if err != nil {
		t.Fatalf("marshal authoritative envelope: %v", err)
	}
	decoded, err := pubsubx.UnmarshalEnvelope(encoded)
	if err != nil || decoded.GetJobId() != "job-1" {
		t.Fatalf("round-trip authoritative envelope: envelope=%v err=%v", decoded, err)
	}
}

func TestOutboxDispatcherRetriesThenAcknowledgesRegisteredEvent(t *testing.T) {
	repository := operations.NewRepository()
	principal := policies.Principal{ID: "principal-1", TenantID: "tenant-a", Actions: map[string]bool{operations.CreateAction: true}}
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: principal, IdempotencyKey: "key-dispatch", RequestDigest: "sha256:" + strings.Repeat("a", 64),
		ConfigurationDigest: "sha256:" + strings.Repeat("c", 64),
		Operation:           &operationv1.Operation{OperationId: "operation-dispatch", TenantId: "tenant-a", ProjectId: "project-a", JobId: "job-dispatch", Etag: "operation-etag-1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	envelope := repository.OutboxEnvelopes()[0]
	store := outbox.NewStore()
	now := time.Now().UTC()
	if err = store.Insert(outbox.DeliveryRecord{Envelope: envelope, NextAttemptAt: now}); err != nil {
		t.Fatalf("insert authoritative outbox envelope: %v", err)
	}
	publisher := &recordingPublisher{failures: 1}
	dispatcher := outbox.Dispatcher{
		Store: store, Publisher: publisher, Now: func() time.Time { return now },
		ClaimTTL: time.Minute, RetryDelay: func(uint32) time.Duration { return 0 },
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-a", 10); delivered != 0 || dispatchErr == nil {
		t.Fatalf("failed publish must be retried: delivered=%d err=%v", delivered, dispatchErr)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-a", 10); delivered != 1 || dispatchErr != nil {
		t.Fatalf("retried publish must be acknowledged: delivered=%d err=%v", delivered, dispatchErr)
	}
	if len(publisher.published) != 1 || len(store.Pending()) != 0 || !proto.Equal(publisher.published[0], envelope) {
		t.Fatal("dispatcher must publish and acknowledge the immutable registered envelope exactly once")
	}
	unknownVersion := proto.Clone(envelope).(*commonv1.EventEnvelope)
	unknownVersion.EventVersion++
	if validationErr := pubsubx.ValidateEnvelope(unknownVersion); !errors.Is(validationErr, pubsubx.ErrInvalidEnvelope) {
		t.Fatalf("consumer must reject an unregistered event version: %v", validationErr)
	}
	payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
	if decodeErr != nil {
		t.Fatalf("decode exact generated event payload: %v", decodeErr)
	}
	if _, ok := payload.(*jobv1.JobRequested); !ok {
		t.Fatalf("registered payload type = %T, want *jobv1.JobRequested", payload)
	}
}

func TestOutboxDispatcherRepublishesStableEventAfterPublishBeforeAckCrash(t *testing.T) {
	repository := operations.NewRepository()
	principal := policies.Principal{ID: "principal-crash", TenantID: "tenant-crash", Actions: map[string]bool{operations.CreateAction: true}}
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: principal, IdempotencyKey: "key-crash", RequestDigest: "sha256:" + strings.Repeat("a", 64),
		ConfigurationDigest: "sha256:" + strings.Repeat("c", 64),
		Operation:           &operationv1.Operation{OperationId: "operation-crash", TenantId: "tenant-crash", ProjectId: "project-crash", JobId: "job-crash", Etag: "operation-etag-1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	envelope := repository.OutboxEnvelopes()[0]
	store := &acknowledgeFailingStore{Store: outbox.NewStore(), failures: 1}
	now := time.Now().UTC()
	if err = store.Insert(outbox.DeliveryRecord{Envelope: envelope, NextAttemptAt: now}); err != nil {
		t.Fatal(err)
	}
	publisher := &recordingPublisher{}
	dispatchTime := now
	dispatcher := outbox.Dispatcher{
		Store: store, Publisher: publisher, Now: func() time.Time { return dispatchTime }, ClaimTTL: time.Second,
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-crash", 1); delivered != 0 || dispatchErr == nil {
		t.Fatalf("publish-before-ack crash must leave delivery pending: delivered=%d err=%v", delivered, dispatchErr)
	}
	if len(publisher.published) != 1 || len(store.Pending()) != 1 {
		t.Fatalf("published=%d pending=%d after acknowledgement crash", len(publisher.published), len(store.Pending()))
	}
	dispatchTime = now.Add(2 * time.Second)
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-crash", 1); delivered != 1 || dispatchErr != nil {
		t.Fatalf("expired claim must republish and acknowledge: delivered=%d err=%v", delivered, dispatchErr)
	}
	if len(publisher.published) != 2 || len(store.Pending()) != 0 {
		t.Fatalf("published=%d pending=%d after recovery", len(publisher.published), len(store.Pending()))
	}
	if first, second := publisher.published[0], publisher.published[1]; first.GetEventId() != envelope.GetEventId() || second.GetEventId() != envelope.GetEventId() || !proto.Equal(first, second) {
		t.Fatalf("republish changed immutable event identity: first=%q second=%q want=%q", first.GetEventId(), second.GetEventId(), envelope.GetEventId())
	}
}

func TestOutboxDoesNotClaimAnAggregateSuccessorBeforeItsPredecessor(t *testing.T) {
	repository := operations.NewRepository()
	principal := policies.Principal{ID: "principal-order", TenantID: "tenant-order", Actions: map[string]bool{operations.CreateAction: true}}
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: principal, IdempotencyKey: "key-order", RequestDigest: "sha256:" + strings.Repeat("a", 64),
		ConfigurationDigest: "sha256:" + strings.Repeat("c", 64),
		Operation:           &operationv1.Operation{OperationId: "operation-order", TenantId: "tenant-order", ProjectId: "project-order", JobId: "job-order", Etag: "operation-etag-1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	first := repository.OutboxEnvelopes()[0]
	first.EventId = "z-predecessor"
	first.DeduplicationKey = first.EventId
	second := proto.Clone(first).(*commonv1.EventEnvelope)
	second.EventId = "a-successor"
	second.DeduplicationKey = second.EventId
	second.AggregateSequence = 2
	store := outbox.NewStore()
	now := time.Now().UTC()
	// Insert in reverse sequence and make the successor sort first by ID. The
	// aggregate sequence, not insertion or lexical order, controls eligibility.
	if err = store.Insert(outbox.DeliveryRecord{Envelope: second, NextAttemptAt: now}); err != nil {
		t.Fatal(err)
	}
	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{Store: store, Publisher: publisher, Now: func() time.Time { return now }, ClaimTTL: time.Minute}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-order", 10); dispatchErr != nil || delivered != 0 {
		t.Fatalf("aggregate sequence gap must remain blocked: delivered=%d err=%v", delivered, dispatchErr)
	}
	if err = store.Insert(outbox.DeliveryRecord{Envelope: first, NextAttemptAt: now}); err != nil {
		t.Fatal(err)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-order", 10); dispatchErr != nil || delivered != 1 {
		t.Fatalf("first aggregate dispatch: delivered=%d err=%v", delivered, dispatchErr)
	}
	if len(publisher.published) != 1 || publisher.published[0].GetAggregateSequence() != 1 {
		t.Fatalf("published sequences after first claim = %v", publisher.published)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-order", 10); dispatchErr != nil || delivered != 1 {
		t.Fatalf("second aggregate dispatch: delivered=%d err=%v", delivered, dispatchErr)
	}
	if len(publisher.published) != 2 || publisher.published[1].GetAggregateSequence() != 2 {
		t.Fatalf("published sequences after second claim = %v", publisher.published)
	}
}

func TestOutboxQuarantinesAfterBoundedPublishAttempts(t *testing.T) {
	repository := operations.NewRepository()
	principal := policies.Principal{ID: "principal-dlq", TenantID: "tenant-dlq", Actions: map[string]bool{operations.CreateAction: true}}
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: principal, IdempotencyKey: "key-dlq", RequestDigest: "sha256:" + strings.Repeat("a", 64),
		ConfigurationDigest: "sha256:" + strings.Repeat("c", 64),
		Operation:           &operationv1.Operation{OperationId: "operation-dlq", TenantId: "tenant-dlq", ProjectId: "project-dlq", JobId: "job-dlq", Etag: "operation-etag-1"},
	})
	if err != nil {
		t.Fatal(err)
	}
	store := outbox.NewStore()
	now := time.Now().UTC()
	if err = store.Insert(outbox.DeliveryRecord{Envelope: repository.OutboxEnvelopes()[0], NextAttemptAt: now}); err != nil {
		t.Fatal(err)
	}
	dispatcher := outbox.Dispatcher{
		Store: store, Publisher: &recordingPublisher{failures: 3}, Now: func() time.Time { return now },
		ClaimTTL: time.Minute, RetryDelay: func(uint32) time.Duration { return 0 }, MaxAttempts: 2,
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-dlq", 1); delivered != 0 || dispatchErr == nil || len(store.Pending()) != 1 {
		t.Fatalf("first failure must remain retryable: delivered=%d pending=%d err=%v", delivered, len(store.Pending()), dispatchErr)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(context.Background(), "tenant-dlq", 1); delivered != 0 || dispatchErr == nil || len(store.Pending()) != 0 || len(store.Quarantined()) != 1 {
		t.Fatalf("second failure must quarantine: delivered=%d pending=%d quarantined=%d err=%v", delivered, len(store.Pending()), len(store.Quarantined()), dispatchErr)
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

	manifest := []byte(`{"schema_version":"mindclade.artifact-manifest/v1","kind":"ArtifactManifest","metadata":{"uid":"artifact-1","created_at":"2026-08-30T00:00:00Z","owner":"data-platform"},"spec":{"artifact":{"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","media_type":"application/json","size_bytes":1,"kind":"fixture"}},"lineage":[],"integrity":{"payload_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","signatures":[]}}`)
	manifestHash := sha256.Sum256(manifest)
	manifestDigest := "sha256:" + hex.EncodeToString(manifestHash[:])
	manifestRef := &artifactv1.ArtifactRef{
		Digest: manifestDigest, IntegrityDigest: manifestDigest, MediaType: "application/json",
		SizeBytes: int64(len(manifest)), ArtifactKind: "manifest", SchemaId: "artifact_manifest",
		SchemaVersion: "mindclade.artifact-manifest/v1",
	}
	manifestRepository := artifacts.NewRepository()
	if _, err = artifacts.Finalize(context.Background(), policies.DenyByDefault{}, manifestRepository, storage.FilesystemCAS{Root: t.TempDir()}, &memoryCatalog{}, artifacts.FinalizeCommand{
		Principal: principal, TenantID: "tenant-a", Artifact: manifestRef, Body: bytes.NewReader(manifest),
	}); err != nil {
		t.Fatalf("generated schema binding rejected valid artifact manifest: %v", err)
	}
	invalidManifest := []byte(`{"schema_version":"mindclade.artifact-manifest/v1","kind":"ArtifactManifest"}`)
	invalidHash := sha256.Sum256(invalidManifest)
	invalidDigest := "sha256:" + hex.EncodeToString(invalidHash[:])
	if _, err = artifacts.Finalize(context.Background(), policies.DenyByDefault{}, artifacts.NewRepository(), storage.FilesystemCAS{Root: t.TempDir()}, &memoryCatalog{}, artifacts.FinalizeCommand{
		Principal: principal, TenantID: "tenant-a",
		Artifact: &artifactv1.ArtifactRef{
			Digest: invalidDigest, IntegrityDigest: invalidDigest, MediaType: "application/json",
			SizeBytes: int64(len(invalidManifest)), ArtifactKind: "manifest", SchemaId: "artifact_manifest",
			SchemaVersion: "mindclade.artifact-manifest/v1",
		},
		Body: bytes.NewReader(invalidManifest),
	}); err == nil {
		t.Fatal("generated schema binding accepted an invalid artifact manifest")
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
	testContext := context.Background()
	unique := time.Now().UTC().Format("20060102150405.000000000")
	tenantID := "tenant-" + unique
	jobID := "job-" + unique
	operationID := "operation-" + unique
	requestHash := "sha256:" + strings.Repeat("a", 64)
	configurationDigest := "sha256:" + strings.Repeat("c", 64)
	richError := &commonv1.ErrorDetail{
		Code: commonv1.ErrorCode_ERROR_CODE_FAILED_PRECONDITION, Message: "fixture failure",
		RetryClass:             commonv1.RetryClass_RETRY_CLASS_AFTER_RECONCILIATION,
		Subject:                &commonv1.ResourceRef{ResourceType: "job", ResourceId: jobID, TenantId: tenantID, ProjectId: "project-integration", ResourceVersion: 7, Name: "jobs/" + jobID, Etag: "job-subject-etag-7"},
		FieldViolations:        []*commonv1.FieldViolation{{Field: "configuration.digest", Description: "fixture violation"}},
		PreconditionViolations: []*commonv1.PreconditionViolation{{Type: "CONFIGURATION", Subject: jobID, Description: "fixture precondition"}},
		RetryAfter:             durationpb.New(3*time.Second + 17*time.Nanosecond), ErrorId: "error-" + unique,
	}
	t.Cleanup(func() {
		for _, table := range []string{
			"run_command_receipt_attempts", "run_command_receipts",
			"attempt_completion_history", "attempt_output_refs", "attempts",
			"run_output_refs", "runs", "dead_letter_messages", "inbox_delivery_failures",
			"inbox_messages", "outbox_messages",
			"audit_events", "idempotency_records", "operations", "jobs",
			"error_precondition_violations", "error_field_violations",
			"error_details", "artifact_references", "artifacts",
		} {
			if _, cleanupErr := db.ExecContext(testContext, "DELETE FROM "+table+" WHERE tenant_id = $1", tenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("clean PostgreSQL integration table %s: %v", table, cleanupErr)
			}
		}
	})
	jobsSQL := jobs.SQLRepository{DB: db}
	configuration := &artifactv1.ArtifactRef{Digest: configurationDigest, MediaType: "application/json", SizeBytes: 128, ArtifactKind: "configuration", SchemaId: "mindclade.configuration", IntegrityDigest: configurationDigest, Uri: "gs://internal/configuration", SchemaVersion: "1"}
	createdJob, err := jobsSQL.CreateJobSQL(testContext, &jobv1.Job{
		JobId: jobID, TenantId: tenantID, ProjectId: "project-integration", JobKind: "training",
		PolicyDigest: "sha256:" + strings.Repeat("b", 64), Configuration: configuration, Etag: "job-etag-1",
	})
	if err != nil || createdJob.GetConfiguration().GetDigest() != configurationDigest {
		t.Fatalf("create PostgreSQL generated job: job=%v err=%v", createdJob, err)
	}
	operationsSQL := operations.SQLRepository{DB: db}
	operationTarget := &commonv1.ResourceRef{ResourceType: "training_run", ResourceId: "training-" + unique, TenantId: tenantID, ProjectId: "project-integration", ResourceVersion: 3, Name: "trainingRuns/training-" + unique, Etag: "training-etag-3"}
	operationInput := &operationv1.Operation{OperationId: operationID, TenantId: tenantID, ProjectId: "project-integration", JobId: jobID, Etag: "operation-etag-1", Result: configuration, Error: richError, Target: operationTarget}
	operation, replay, err := operationsSQL.CreateAtomicallySQL(testContext, operationInput, requestHash, "journey-key", "integration-principal")
	if err != nil || replay || operation.GetState() != operationv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("PostgreSQL operation acceptance failed: operation=%#v replay=%v err=%v", operation, replay, err)
	}
	var auditEnvelopeBytes []byte
	if queryErr := db.QueryRowContext(testContext, `SELECT envelope_bytes FROM audit_events WHERE tenant_id = $1 AND subject_id = $2`, tenantID, operationID).Scan(&auditEnvelopeBytes); queryErr != nil {
		t.Fatalf("read PostgreSQL generated audit envelope: %v", queryErr)
	}
	auditEnvelope, err := pubsubx.UnmarshalEnvelope(auditEnvelopeBytes)
	if err != nil {
		t.Fatalf("decode PostgreSQL generated audit envelope: %v", err)
	}
	if auditPayload, validationErr := foundationaudit.ValidateEvent(auditEnvelope); validationErr != nil || auditPayload.GetAction() != operations.CreateAction {
		t.Fatalf("validate PostgreSQL generated audit payload: payload=%v err=%v", auditPayload, validationErr)
	}
	replayed, replay, err := operationsSQL.CreateAtomicallySQL(testContext, operationInput, requestHash, "journey-key", "integration-principal")
	if err != nil || !replay || replayed.GetProjectId() != operationInput.GetProjectId() || replayed.GetEtag() != operationInput.GetEtag() || !proto.Equal(replayed.GetResult(), configuration) || !proto.Equal(replayed.GetError(), richError) || !proto.Equal(replayed.GetTarget(), operationTarget) {
		t.Fatalf("PostgreSQL idempotency replay failed: replay=%v err=%v", replay, err)
	}
	advanced, err := operationsSQL.AdvanceSQL(testContext, tenantID, "project-integration", operationID, operation.GetResourceVersion(), operation.GetEtag(), operationv1.OperationState_OPERATION_STATE_RUNNING)
	if err != nil || advanced.GetResourceVersion() != 2 || advanced.GetEtag() == operation.GetEtag() || !proto.Equal(advanced.GetTarget(), operationTarget) {
		t.Fatalf("PostgreSQL conditional operation advance failed: operation=%v err=%v", advanced, err)
	}
	if _, err = operationsSQL.AdvanceSQL(testContext, tenantID, "project-integration", operationID, operation.GetResourceVersion(), operation.GetEtag(), operationv1.OperationState_OPERATION_STATE_SUCCEEDED); !errors.Is(err, operations.ErrVersionConflict) {
		t.Fatalf("PostgreSQL stale operation advance error=%v", err)
	}
	persistedJob, err := jobsSQL.GetJobSQL(testContext, tenantID, "project-integration", jobID)
	if err != nil || persistedJob.GetOperationId() != operationID || persistedJob.GetProjectId() != createdJob.GetProjectId() || persistedJob.GetPolicyDigest() != createdJob.GetPolicyDigest() || persistedJob.GetJobKind() != createdJob.GetJobKind() || persistedJob.GetEtag() != createdJob.GetEtag() || !proto.Equal(persistedJob.GetConfiguration(), configuration) {
		t.Fatalf("PostgreSQL generated job round trip failed: job=%v err=%v", persistedJob, err)
	}
	var outboxEnvelopeBytes []byte
	if queryErr := db.QueryRowContext(testContext, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id = $1 AND aggregate_type = 'operation' AND aggregate_id = $2`, tenantID, "tenants/"+tenantID+"/projects/project-integration/operations/"+operationID).Scan(&outboxEnvelopeBytes); queryErr != nil {
		t.Fatalf("read PostgreSQL outbox envelope: %v", queryErr)
	}
	outboxEnvelope, err := pubsubx.UnmarshalEnvelope(outboxEnvelopeBytes)
	if err != nil {
		t.Fatalf("decode PostgreSQL outbox envelope: %v", err)
	}
	jobRequested := new(jobv1.JobRequested)
	if err = proto.Unmarshal(outboxEnvelope.GetPayload(), jobRequested); err != nil || jobRequested.GetConfigurationDigest() != configurationDigest {
		t.Fatalf("JobRequested configuration digest: payload=%v err=%v", jobRequested, err)
	}
	if accepted, acceptErr := inbox.AcceptSQL(testContext, db, "integration-worker", outboxEnvelope); acceptErr != nil || !accepted {
		t.Fatalf("PostgreSQL inbox first delivery failed: accepted=%v err=%v", accepted, acceptErr)
	}
	if accepted, acceptErr := inbox.AcceptSQL(testContext, db, "integration-worker", outboxEnvelope); acceptErr != nil || accepted {
		t.Fatalf("PostgreSQL inbox duplicate was not rejected: accepted=%v err=%v", accepted, acceptErr)
	}
	registeredPayload, err := pubsubx.UnmarshalRegisteredPayload(outboxEnvelope)
	if err != nil {
		t.Fatalf("decode registered PostgreSQL payload: %v", err)
	}
	if accepted, consumeErr := inbox.AcceptAndHandleSQL(testContext, db, "scheduler-worker", outboxEnvelope, registeredPayload, jobs.JobRequestedHandler{}); consumeErr != nil || !accepted {
		t.Fatalf("JobRequested handler did not atomically reconcile the durable job: accepted=%v err=%v", accepted, consumeErr)
	}
	queuedJob, consumeErr := jobsSQL.GetJobSQL(testContext, tenantID, "project-integration", jobID)
	if consumeErr != nil || queuedJob.GetState() != jobv1.JobState_JOB_STATE_QUEUED || queuedJob.GetResourceVersion() != 2 {
		t.Fatalf("JobRequested handler state=%v version=%d err=%v", queuedJob.GetState(), queuedJob.GetResourceVersion(), consumeErr)
	}
	if accepted, consumeErr := inbox.AcceptAndHandleSQL(testContext, db, "scheduler-worker", outboxEnvelope, registeredPayload, jobs.JobRequestedHandler{}); consumeErr != nil || accepted {
		t.Fatalf("duplicate JobRequested must be acknowledged without another transition: accepted=%v err=%v", accepted, consumeErr)
	}
	atomicConsumer := "atomic-worker"
	mutationDigest := "sha256:" + strings.Repeat("d", 64)
	handlerCalls := 0
	failMutation := true
	handler := inbox.TransactionalHandlerFunc(func(ctx standardContext, tx *sql.Tx, _ *commonv1.EventEnvelope, payload proto.Message) error {
		handlerCalls++
		if _, ok := payload.(*jobv1.JobRequested); !ok {
			return errors.New("unexpected generated payload type")
		}
		if _, mutationErr := tx.ExecContext(ctx, `INSERT INTO artifacts (digest,tenant_id,media_type,byte_size,created_at) VALUES ($1,$2,'application/octet-stream',1,now())`, mutationDigest, tenantID); mutationErr != nil {
			return mutationErr
		}
		if failMutation {
			return errors.New("synthetic business mutation failure")
		}
		return nil
	})
	if accepted, mutationErr := inbox.AcceptAndHandleSQL(testContext, db, atomicConsumer, outboxEnvelope, registeredPayload, handler); mutationErr == nil || accepted {
		t.Fatalf("failed business mutation must roll back receipt: accepted=%v err=%v", accepted, mutationErr)
	}
	var receiptCount, mutationCount int
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM inbox_messages WHERE tenant_id=$1 AND consumer=$2 AND event_id=$3`, tenantID, atomicConsumer, outboxEnvelope.GetEventId()).Scan(&receiptCount); queryErr != nil {
		t.Fatal(queryErr)
	}
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM artifacts WHERE tenant_id=$1 AND digest=$2`, tenantID, mutationDigest).Scan(&mutationCount); queryErr != nil {
		t.Fatal(queryErr)
	}
	if receiptCount != 0 || mutationCount != 0 {
		t.Fatalf("handler rollback leaked receipt=%d mutation=%d", receiptCount, mutationCount)
	}
	failMutation = false
	if accepted, mutationErr := inbox.AcceptAndHandleSQL(testContext, db, atomicConsumer, outboxEnvelope, registeredPayload, handler); mutationErr != nil || !accepted {
		t.Fatalf("successful business mutation did not commit atomically: accepted=%v err=%v", accepted, mutationErr)
	}
	if accepted, mutationErr := inbox.AcceptAndHandleSQL(testContext, db, atomicConsumer, outboxEnvelope, registeredPayload, handler); mutationErr != nil || accepted || handlerCalls != 2 {
		t.Fatalf("duplicate must acknowledge without rerunning handler: accepted=%v calls=%d err=%v", accepted, handlerCalls, mutationErr)
	}

	poison := proto.Clone(outboxEnvelope).(*commonv1.EventEnvelope)
	poison.EventId = "poison:" + unique
	poison.DeduplicationKey = poison.EventId
	poison.Subject.ResourceId = "poison-" + operationID
	poisonBytes, err := pubsubx.MarshalEnvelope(poison)
	if err != nil {
		t.Fatal(err)
	}
	poisonAttributes, err := pubsubx.TransportAttributes(poison)
	if err != nil {
		t.Fatal(err)
	}
	poisonOrderingKey, err := pubsubx.OrderingKey(poison)
	if err != nil {
		t.Fatal(err)
	}
	poisonCalls := 0
	processor := inbox.Processor{DB: db, Consumer: "bounded-worker", AcceptedEvents: map[string]uint32{"mindclade.events.job.v1.JobRequested": 1}, MaxAttempts: 2, QuarantineTenantID: tenantID, Handler: inbox.TransactionalHandlerFunc(func(standardContext, *sql.Tx, *commonv1.EventEnvelope, proto.Message) error {
		poisonCalls++
		return errors.New("synthetic permanent worker failure")
	})}
	misrouted, err := foundationaudit.NewEvent(tenantID, "integration-principal", "reliability.misroute", "jobs/"+jobID, "allowed", time.Now().UTC(), nil)
	if err != nil {
		t.Fatal(err)
	}
	misroutedBytes, err := pubsubx.MarshalEnvelope(misrouted)
	if err != nil {
		t.Fatal(err)
	}
	misroutedAttributes, err := pubsubx.TransportAttributes(misrouted)
	if err != nil {
		t.Fatal(err)
	}
	misroutedOrderingKey, err := pubsubx.OrderingKey(misrouted)
	if err != nil {
		t.Fatal(err)
	}
	if disposition, processErr := processor.ProcessDelivery(testContext, misroutedBytes, misroutedAttributes, misroutedOrderingKey); disposition != inbox.DeliveryAck || processErr != nil || poisonCalls != 0 {
		t.Fatalf("specialized consumer must acknowledge an unrelated registered delivery without invoking its handler: disposition=%v calls=%d err=%v", disposition, poisonCalls, processErr)
	}
	if disposition, processErr := processor.ProcessDelivery(testContext, poisonBytes, poisonAttributes, poisonOrderingKey); disposition != inbox.DeliveryNack || processErr == nil {
		t.Fatalf("first worker failure must nack: disposition=%v err=%v", disposition, processErr)
	}
	if disposition, processErr := processor.ProcessDelivery(testContext, poisonBytes, poisonAttributes, poisonOrderingKey); disposition != inbox.DeliveryAck || processErr == nil {
		t.Fatalf("bounded worker failure must quarantine and ack: disposition=%v err=%v", disposition, processErr)
	}
	if disposition, processErr := processor.ProcessDelivery(testContext, poisonBytes, poisonAttributes, poisonOrderingKey); disposition != inbox.DeliveryAck || processErr != nil || poisonCalls != 2 {
		t.Fatalf("redelivery after durable quarantine must ack without rerunning: disposition=%v calls=%d err=%v", disposition, poisonCalls, processErr)
	}
	var poisonDLQCount int
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM dead_letter_messages WHERE tenant_id=$1 AND source='INBOX' AND event_id=$2 AND attempts=2`, tenantID, poison.GetEventId()).Scan(&poisonDLQCount); queryErr != nil || poisonDLQCount != 1 {
		t.Fatalf("inbox DLQ record count=%d err=%v", poisonDLQCount, queryErr)
	}
	dispatchTime := time.Now().UTC()
	transport := &recordingPublisher{failures: 1}
	dispatcher := outbox.Dispatcher{
		Store: outbox.SQLStore{DB: db}, Publisher: transport,
		Now: func() time.Time { return dispatchTime }, ClaimTTL: time.Minute,
		RetryDelay: func(uint32) time.Duration { return 0 },
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 0 || dispatchErr == nil {
		t.Fatalf("PostgreSQL outbox transport failure must schedule retry: delivered=%d err=%v", delivered, dispatchErr)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 1 || dispatchErr != nil {
		t.Fatalf("PostgreSQL outbox retry must publish and acknowledge: delivered=%d err=%v", delivered, dispatchErr)
	}
	var outboxDelivered bool
	if queryErr := db.QueryRowContext(testContext, `SELECT delivered_at IS NOT NULL FROM outbox_messages WHERE tenant_id = $1 AND id = $2`, tenantID, outboxEnvelope.GetEventId()).Scan(&outboxDelivered); queryErr != nil || !outboxDelivered || len(transport.published) != 1 {
		t.Fatalf("PostgreSQL outbox acknowledgement was not durable: delivered=%v published=%d err=%v", outboxDelivered, len(transport.published), queryErr)
	}
	validAfterCorrupt := proto.Clone(outboxEnvelope).(*commonv1.EventEnvelope)
	validAfterCorrupt.EventId = "z-valid-after-corrupt:" + unique
	validAfterCorrupt.DeduplicationKey = validAfterCorrupt.EventId
	validAfterCorrupt.Subject.ResourceId = "valid-after-corrupt-" + operationID
	validAfterCorrupt.Subject.Name = "tenants/" + tenantID + "/projects/project-integration/operations/valid-after-corrupt-" + operationID
	validAfterCorrupt.AggregateSequence = 1
	validBytes, err := pubsubx.MarshalEnvelope(validAfterCorrupt)
	if err != nil {
		t.Fatal(err)
	}
	isolationTime := time.Now().UTC()
	if _, insertErr := db.ExecContext(testContext, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, validAfterCorrupt.GetEventId(), tenantID, validAfterCorrupt.GetEventType(), validAfterCorrupt.GetEventVersion(), validAfterCorrupt.GetSubject().GetResourceType(), validAfterCorrupt.GetSubject().GetName(), validAfterCorrupt.GetAggregateSequence(), validAfterCorrupt.GetPayloadDigest(), validBytes, isolationTime); insertErr != nil {
		t.Fatalf("insert valid isolation fixture: %v", insertErr)
	}
	corruptID := "a-corrupt:" + unique
	if _, insertErr := db.ExecContext(testContext, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,1,$7,$8,$9,$9)`, corruptID, tenantID, outboxEnvelope.GetEventType(), outboxEnvelope.GetEventVersion(), "operation", "corrupt-"+operationID, outboxEnvelope.GetPayloadDigest(), []byte{0xff}, isolationTime); insertErr != nil {
		t.Fatalf("insert corrupt isolation fixture: %v", insertErr)
	}
	isolationPublisher := &recordingPublisher{}
	isolationDispatcher := outbox.Dispatcher{Store: outbox.SQLStore{DB: db}, Publisher: isolationPublisher, Now: func() time.Time { return isolationTime }, ClaimTTL: time.Minute}
	if delivered, dispatchErr := isolationDispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 1 || dispatchErr == nil {
		t.Fatalf("corrupt record must be isolated while valid aggregate proceeds: delivered=%d err=%v", delivered, dispatchErr)
	}
	var corruptQuarantined, validDelivered bool
	if queryErr := db.QueryRowContext(testContext, `SELECT quarantined_at IS NOT NULL FROM outbox_messages WHERE tenant_id=$1 AND id=$2`, tenantID, corruptID).Scan(&corruptQuarantined); queryErr != nil {
		t.Fatal(queryErr)
	}
	if queryErr := db.QueryRowContext(testContext, `SELECT delivered_at IS NOT NULL FROM outbox_messages WHERE tenant_id=$1 AND id=$2`, tenantID, validAfterCorrupt.GetEventId()).Scan(&validDelivered); queryErr != nil {
		t.Fatal(queryErr)
	}
	var corruptDLQCount int
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM dead_letter_messages WHERE tenant_id=$1 AND source='OUTBOX' AND event_id=$2 AND attempts=1`, tenantID, corruptID).Scan(&corruptDLQCount); queryErr != nil || !corruptQuarantined || !validDelivered || corruptDLQCount != 1 || len(isolationPublisher.published) != 1 {
		t.Fatalf("corrupt isolation state: quarantined=%v valid_delivered=%v dlq=%d published=%d err=%v", corruptQuarantined, validDelivered, corruptDLQCount, len(isolationPublisher.published), queryErr)
	}
	gapFirst := proto.Clone(outboxEnvelope).(*commonv1.EventEnvelope)
	gapFirst.EventId = "gap-first:" + unique
	gapFirst.DeduplicationKey = gapFirst.EventId
	gapFirst.Subject.ResourceId = "gap-" + operationID
	gapFirst.Subject.Name = "tenants/" + tenantID + "/projects/project-integration/operations/gap-" + operationID
	gapFirst.AggregateSequence = 1
	gapSecond := proto.Clone(gapFirst).(*commonv1.EventEnvelope)
	gapSecond.EventId = "gap-second:" + unique
	gapSecond.DeduplicationKey = gapSecond.EventId
	gapSecond.AggregateSequence = 2
	insertGapEnvelope := func(envelope *commonv1.EventEnvelope) {
		t.Helper()
		encoded, encodeErr := pubsubx.MarshalEnvelope(envelope)
		if encodeErr != nil {
			t.Fatal(encodeErr)
		}
		if _, insertErr := db.ExecContext(testContext, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, envelope.GetEventId(), tenantID, envelope.GetEventType(), envelope.GetEventVersion(), envelope.GetSubject().GetResourceType(), envelope.GetSubject().GetName(), envelope.GetAggregateSequence(), envelope.GetPayloadDigest(), encoded, isolationTime); insertErr != nil {
			t.Fatalf("insert aggregate-gap fixture %q: %v", envelope.GetEventId(), insertErr)
		}
	}
	insertGapEnvelope(gapSecond)
	gapPublisher := &recordingPublisher{}
	gapDispatcher := outbox.Dispatcher{Store: outbox.SQLStore{DB: db}, Publisher: gapPublisher, Now: func() time.Time { return isolationTime }, ClaimTTL: time.Minute}
	if delivered, dispatchErr := gapDispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 0 || dispatchErr != nil {
		t.Fatalf("PostgreSQL aggregate gap must remain blocked: delivered=%d err=%v", delivered, dispatchErr)
	}
	insertGapEnvelope(gapFirst)
	if delivered, dispatchErr := gapDispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 1 || dispatchErr != nil || len(gapPublisher.published) != 1 || gapPublisher.published[0].GetAggregateSequence() != 1 {
		t.Fatalf("PostgreSQL predecessor dispatch: delivered=%d published=%v err=%v", delivered, gapPublisher.published, dispatchErr)
	}
	if delivered, dispatchErr := gapDispatcher.DeliverBatch(testContext, tenantID, 10); delivered != 1 || dispatchErr != nil || len(gapPublisher.published) != 2 || gapPublisher.published[1].GetAggregateSequence() != 2 {
		t.Fatalf("PostgreSQL successor dispatch: delivered=%d published=%v err=%v", delivered, gapPublisher.published, dispatchErr)
	}
	runID := "run-" + unique
	createdRun, err := jobsSQL.CreateRunSQL(testContext, &jobv1.Run{RunId: runID, TenantId: tenantID, ProjectId: "project-integration", JobId: jobID, Input: configuration, Configuration: configuration, Plan: configuration, Outputs: []*artifactv1.ArtifactRef{configuration}, Error: richError, Etag: "run-etag-1"})
	if err != nil || createdRun.GetConfiguration().GetDigest() != configurationDigest || !proto.Equal(createdRun.GetInput(), configuration) || !proto.Equal(createdRun.GetPlan(), configuration) || len(createdRun.GetOutputs()) != 1 || !proto.Equal(createdRun.GetOutputs()[0], configuration) || !proto.Equal(createdRun.GetError(), richError) || createdRun.GetEtag() != "run-etag-1" {
		t.Fatalf("create PostgreSQL generated run: run=%v err=%v", createdRun, err)
	}
	leaseTime := time.Now().UTC()
	firstToken := "postgres-first-token-" + strings.Repeat("d", 32)
	firstLease, err := jobsSQL.AcquireLeaseSQL(testContext, jobs.AcquireLeaseCommand{
		TenantID: tenantID, RunID: runID, AttemptID: "attempt-first-" + unique, WorkerID: "worker-first",
		Token: firstToken, TokenKeyID: "integration-key", Duration: jobs.MinimumLeaseDuration, Now: leaseTime,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: "worker-first",
			Action: "run.acquire_lease", IdempotencyKey: "acquire-first-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("1", 64), ObservedAt: leaseTime,
		},
	})
	if err != nil {
		t.Fatalf("acquire first PostgreSQL lease: %v", err)
	}
	first := firstLease.Attempt
	secondToken := "postgres-second-token-" + strings.Repeat("e", 32)
	secondObservedAt := leaseTime.Add(jobs.MinimumLeaseDuration + time.Second)
	secondLease, err := jobsSQL.AcquireLeaseSQL(testContext, jobs.AcquireLeaseCommand{
		TenantID: tenantID, RunID: runID, AttemptID: "attempt-second-" + unique, WorkerID: "worker-second",
		Token: secondToken, TokenKeyID: "integration-key", Duration: jobs.MinimumLeaseDuration, Now: secondObservedAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: "worker-second",
			Action: "run.acquire_lease", IdempotencyKey: "acquire-second-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("2", 64), ObservedAt: secondObservedAt,
		},
	})
	if err != nil {
		t.Fatalf("acquire replacement PostgreSQL lease: %v", err)
	}
	second := secondLease.Attempt
	firstAttemptName := "tenants/" + tenantID + "/projects/project-integration/jobs/" + jobID + "/runs/" + runID + "/attempts/" + first.GetAttemptId()
	var timedOutEnvelopeBytes []byte
	if queryErr := db.QueryRowContext(testContext, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND aggregate_type='attempt' AND aggregate_id=$2 AND aggregate_sequence=2 AND event_type='mindclade.events.job.v1.AttemptCompleted'`, tenantID, firstAttemptName).Scan(&timedOutEnvelopeBytes); queryErr != nil {
		t.Fatalf("replacement lease did not atomically record the expired attempt: %v", queryErr)
	}
	timedOutEnvelope, decodeErr := pubsubx.UnmarshalEnvelope(timedOutEnvelopeBytes)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	timedOutPayload, decodeErr := pubsubx.UnmarshalRegisteredPayload(timedOutEnvelope)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	timedOutFact, ok := timedOutPayload.(*jobv1.AttemptCompleted)
	if !ok || timedOutFact.GetAttempt().GetState() != jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT ||
		timedOutFact.GetRun().GetLeaseEpoch() != first.GetLeaseEpoch() || timedOutFact.GetFence().GetLeaseEpoch() != first.GetLeaseEpoch() {
		t.Fatalf("invalid generated replacement-timeout fact: %T %v", timedOutPayload, timedOutPayload)
	}
	completion := proto.Clone(first).(*jobv1.Attempt)
	completion.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	credentials := jobs.LeaseCredentials{TenantID: tenantID, ProjectID: "project-integration", AttemptID: first.GetAttemptId(), WorkerID: first.GetWorkerId(), Token: firstToken, Epoch: first.GetLeaseEpoch()}
	completionAt := leaseTime.Add(jobs.MinimumLeaseDuration + 2*time.Second)
	if _, completionErr := jobsSQL.CompleteAttemptSQL(testContext, jobs.CompleteAttemptCommand{
		Credentials: credentials, Attempt: completion, UpdateMask: []string{"state"}, ExpectedResourceVersion: first.GetResourceVersion(), Now: completionAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: first.GetWorkerId(),
			Action: "run.commit_attempt", IdempotencyKey: "complete-first-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("3", 64), ObservedAt: completionAt,
		},
	}); !errors.Is(completionErr, jobs.ErrStaleCompletion) {
		t.Fatalf("PostgreSQL stale completion must be retained and fenced: %v", completionErr)
	}
	acceptedCompletion := proto.Clone(second).(*jobv1.Attempt)
	acceptedCompletion.State = jobv1.AttemptState_ATTEMPT_STATE_FAILED
	acceptedCompletion.Outputs = []*artifactv1.ArtifactRef{configuration}
	completionError := proto.Clone(richError).(*commonv1.ErrorDetail)
	completionError.Message = "attempt terminal failure"
	completionError.ErrorId = "completion-error-" + unique
	acceptedCompletion.Error = completionError
	acceptedCredentials := jobs.LeaseCredentials{TenantID: tenantID, ProjectID: "project-integration", AttemptID: second.GetAttemptId(), WorkerID: second.GetWorkerId(), Token: secondToken, Epoch: second.GetLeaseEpoch()}
	acceptedResult, completionErr := jobsSQL.CompleteAttemptSQL(testContext, jobs.CompleteAttemptCommand{
		Credentials: acceptedCredentials, Attempt: acceptedCompletion, UpdateMask: []string{"state", "outputs", "error"},
		ExpectedResourceVersion: second.GetResourceVersion(), Now: completionAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: second.GetWorkerId(),
			Action: "run.commit_attempt", IdempotencyKey: "complete-second-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("4", 64), ObservedAt: completionAt,
		},
	})
	var acceptedAttempt *jobv1.Attempt
	var acceptedRun *jobv1.Run
	if acceptedResult != nil {
		acceptedAttempt, acceptedRun = acceptedResult.Attempt, acceptedResult.Run
	}
	if completionErr != nil || acceptedAttempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_FAILED || acceptedRun.GetState() != jobv1.RunState_RUN_STATE_FAILED || len(acceptedAttempt.GetOutputs()) != 1 || len(acceptedRun.GetOutputs()) != 1 || !proto.Equal(acceptedAttempt.GetOutputs()[0], configuration) || !proto.Equal(acceptedRun.GetOutputs()[0], configuration) || !proto.Equal(acceptedAttempt.GetError(), completionError) || !proto.Equal(acceptedRun.GetError(), completionError) {
		t.Fatalf("PostgreSQL generated attempt/run completion round trip: attempt=%v run=%v err=%v", acceptedAttempt, acceptedRun, completionErr)
	}
	failedOperation, operationErr := operationsSQL.GetSQL(testContext, tenantID, "project-integration", operationID)
	if operationErr != nil || failedOperation.GetState() != operationv1.OperationState_OPERATION_STATE_FAILED || !failedOperation.GetDone() || failedOperation.GetResult() != nil || !proto.Equal(failedOperation.GetError(), completionError) {
		t.Fatalf("PostgreSQL terminal attempt error was not propagated to the operation: operation=%v err=%v", failedOperation, operationErr)
	}

	leaseReplay, replayErr := jobsSQL.AcquireLeaseSQL(testContext, jobs.AcquireLeaseCommand{
		TenantID: tenantID, RunID: runID, AttemptID: second.GetAttemptId(), WorkerID: second.GetWorkerId(),
		Token: secondToken, TokenKeyID: "integration-key", Duration: jobs.MinimumLeaseDuration, Now: secondObservedAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: second.GetWorkerId(),
			Action: "run.acquire_lease", IdempotencyKey: "acquire-second-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("2", 64), ObservedAt: secondObservedAt,
		},
	})
	if replayErr != nil || !leaseReplay.Replay {
		t.Fatalf("lease replay must return its durable receipt: replay=%v err=%v", leaseReplay, replayErr)
	}
	completionReplay, replayErr := jobsSQL.CompleteAttemptSQL(testContext, jobs.CompleteAttemptCommand{
		Credentials: acceptedCredentials, Attempt: acceptedCompletion, UpdateMask: []string{"state", "outputs", "error"},
		ExpectedResourceVersion: second.GetResourceVersion(), Now: completionAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: "project-integration", PrincipalID: "integration-principal", WorkerID: second.GetWorkerId(),
			Action: "run.commit_attempt", IdempotencyKey: "complete-second-" + unique,
			RequestDigest: "sha256:" + strings.Repeat("4", 64), ObservedAt: completionAt,
		},
	})
	if replayErr != nil || !completionReplay.Replay || !proto.Equal(completionReplay.Attempt, acceptedAttempt) || !proto.Equal(completionReplay.Run, acceptedRun) {
		t.Fatalf("completion replay must return the accepted generated state: replay=%v err=%v", completionReplay, replayErr)
	}

	secondAttemptName := "tenants/" + tenantID + "/projects/project-integration/jobs/" + jobID + "/runs/" + runID + "/attempts/" + second.GetAttemptId()
	var leasedCount, completedCount int
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM outbox_messages WHERE tenant_id=$1 AND aggregate_type='attempt' AND aggregate_id=$2 AND event_type='mindclade.events.job.v1.AttemptLeased'`, tenantID, secondAttemptName).Scan(&leasedCount); queryErr != nil {
		t.Fatal(queryErr)
	}
	if queryErr := db.QueryRowContext(testContext, `SELECT count(*) FROM outbox_messages WHERE tenant_id=$1 AND aggregate_type='attempt' AND aggregate_id=$2 AND event_type='mindclade.events.job.v1.AttemptCompleted'`, tenantID, secondAttemptName).Scan(&completedCount); queryErr != nil {
		t.Fatal(queryErr)
	}
	if leasedCount != 1 || completedCount != 1 {
		t.Fatalf("lease and completion replay must not duplicate outbox facts: leased=%d completed=%d", leasedCount, completedCount)
	}
	var leasedEnvelopeBytes, completedEnvelopeBytes []byte
	if queryErr := db.QueryRowContext(testContext, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND aggregate_id=$2 AND event_type='mindclade.events.job.v1.AttemptLeased'`, tenantID, secondAttemptName).Scan(&leasedEnvelopeBytes); queryErr != nil {
		t.Fatal(queryErr)
	}
	if queryErr := db.QueryRowContext(testContext, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND aggregate_id=$2 AND event_type='mindclade.events.job.v1.AttemptCompleted'`, tenantID, secondAttemptName).Scan(&completedEnvelopeBytes); queryErr != nil {
		t.Fatal(queryErr)
	}
	leasedEnvelope, decodeErr := pubsubx.UnmarshalEnvelope(leasedEnvelopeBytes)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	leasedPayload, decodeErr := pubsubx.UnmarshalRegisteredPayload(leasedEnvelope)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	leasedFact, ok := leasedPayload.(*jobv1.AttemptLeased)
	if !ok || !proto.Equal(leasedFact.GetAttempt(), second) || leasedFact.GetFence().GetLeaseTokenDigest() == "" || leasedFact.GetLeaseExpiresAt() == nil {
		t.Fatalf("invalid generated AttemptLeased outbox fact: %T %v", leasedPayload, leasedPayload)
	}
	completedEnvelope, decodeErr := pubsubx.UnmarshalEnvelope(completedEnvelopeBytes)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	completedPayload, decodeErr := pubsubx.UnmarshalRegisteredPayload(completedEnvelope)
	if decodeErr != nil {
		t.Fatal(decodeErr)
	}
	completedFact, ok := completedPayload.(*jobv1.AttemptCompleted)
	if !ok || !proto.Equal(completedFact.GetAttempt(), acceptedAttempt) || !proto.Equal(completedFact.GetRun(), acceptedRun) || completedFact.GetFence().GetLeaseTokenDigest() == "" || completedFact.GetCompletedAt() == nil {
		t.Fatalf("invalid generated AttemptCompleted outbox fact: %T %v", completedPayload, completedPayload)
	}
}

func TestPostgresGenericJobSchedulerLifecycle(t *testing.T) {
	db := postgresDB(t)
	if db == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	tenantID, projectID := "generic-scheduler-tenant-"+suffix, "project-1"
	jobID, operationID := "jobs/generic-"+suffix, "operations/generic-"+suffix
	t.Cleanup(func() {
		cleanupContext, cleanupCancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cleanupCancel()
		for _, table := range []string{
			"run_command_receipt_attempts", "run_command_receipts", "attempt_completion_history",
			"attempt_output_refs", "attempts", "run_output_refs", "runs", "inbox_delivery_failures",
			"inbox_messages", "dead_letter_messages", "outbox_messages", "audit_events",
			"idempotency_records", "operations", "jobs", "error_precondition_violations",
			"error_field_violations", "error_details", "artifact_references", "artifacts",
		} {
			if _, cleanupErr := db.ExecContext(cleanupContext, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); cleanupErr != nil { //nolint:gosec // closed table list; tenant remains bound.
				t.Errorf("clean generic scheduler table %s: %v", table, cleanupErr)
				return
			}
		}
	})

	at := time.Now().UTC().Truncate(time.Microsecond)
	configuration := &artifactv1.ArtifactRef{
		Digest: "sha256:" + strings.Repeat("8", 64), IntegrityDigest: "sha256:" + strings.Repeat("8", 64),
		MediaType: "application/json", SizeBytes: 1, ArtifactKind: "configuration", SchemaId: "scheduler-test", SchemaVersion: "1",
	}
	input := &artifactv1.ArtifactRef{
		Digest: "sha256:" + strings.Repeat("9", 64), IntegrityDigest: "sha256:" + strings.Repeat("9", 64),
		MediaType: "application/octet-stream", SizeBytes: 1, ArtifactKind: "input", SchemaId: "scheduler-test", SchemaVersion: "1",
	}
	repository := jobs.SQLRepository{DB: db}
	requested, err := repository.RequestJobSQL(ctx, &jobv1.Job{
		JobId: jobID, TenantId: tenantID, ProjectId: projectID, JobKind: "generic.test",
		Input: input, Configuration: configuration, Etag: "job-etag-1",
	}, &operationv1.Operation{
		OperationId: operationID, TenantId: tenantID, ProjectId: projectID, JobId: jobID, Etag: "operation-etag-1",
	}, jobs.JobCommandMetadata{
		TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal",
		IdempotencyKey: "request-generic", RequestDigest: "sha256:" + strings.Repeat("a", 64), ObservedAt: at,
	})
	if err != nil || requested.Replay {
		t.Fatalf("request generic job: result=%v err=%v", requested, err)
	}

	var encoded []byte
	if err = db.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type='mindclade.events.job.v1.JobRequested'`, tenantID).Scan(&encoded); err != nil {
		t.Fatal(err)
	}
	envelope, err := pubsubx.UnmarshalEnvelope(encoded)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := pubsubx.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		t.Fatal(err)
	}
	for _, consumer := range []string{"generic-scheduler-a", "generic-scheduler-b"} {
		accepted, consumeErr := inbox.AcceptAndHandleSQL(ctx, db, consumer, envelope, payload, jobs.JobRequestedHandler{})
		if consumeErr != nil || !accepted {
			t.Fatalf("consume JobRequested as %s: accepted=%v err=%v", consumer, accepted, consumeErr)
		}
	}
	var runID, runState string
	var runCount int
	if err = db.QueryRowContext(ctx, `SELECT count(*),min(id),min(status) FROM runs WHERE tenant_id=$1 AND project_id=$2 AND job_id=$3`, tenantID, projectID, jobID).Scan(&runCount, &runID, &runState); err != nil {
		t.Fatal(err)
	}
	if runCount != 1 || !strings.HasPrefix(runID, "runs/") || runState != "READY" {
		t.Fatalf("JobRequested scheduler projection: count=%d run=%q state=%q", runCount, runID, runState)
	}
	createdRun, err := repository.GetRunSQL(ctx, tenantID, projectID, runID)
	if err != nil || !proto.Equal(createdRun.GetInput(), input) || !proto.Equal(createdRun.GetConfiguration(), configuration) {
		t.Fatalf("generic scheduler Run lost frozen inputs: run=%v err=%v", createdRun, err)
	}
	queuedJob, err := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	if err != nil || queuedJob.GetState() != jobv1.JobState_JOB_STATE_QUEUED {
		t.Fatalf("generic scheduler Job not queued: job=%v err=%v", queuedJob, err)
	}
	queuedOperation, err := (operations.SQLRepository{DB: db}).GetSQL(ctx, tenantID, projectID, operationID)
	if err != nil || queuedOperation.GetState() != operationv1.OperationState_OPERATION_STATE_PENDING {
		t.Fatalf("generic scheduler Operation advanced before acquisition: operation=%v err=%v", queuedOperation, err)
	}

	leaseAt := at.Add(time.Second)
	token := "generic-scheduler-token-" + strings.Repeat("x", 32)
	acquire := jobs.AcquireLeaseCommand{
		TenantID: tenantID, RunID: runID, AttemptID: "attempts/generic-" + suffix, WorkerID: "worker-1",
		Token: token, TokenKeyID: "scheduler-key-1", Duration: time.Minute, Now: leaseAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal", WorkerID: "worker-1",
			Action: "run.acquire_lease", IdempotencyKey: "acquire-generic", RequestDigest: "sha256:" + strings.Repeat("b", 64), ObservedAt: leaseAt,
		},
	}
	lease, err := repository.AcquireLeaseSQL(ctx, acquire)
	if err != nil || lease.Replay {
		t.Fatalf("acquire generic scheduler Run: result=%v err=%v", lease, err)
	}
	runningJob, err := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	if err != nil || runningJob.GetState() != jobv1.JobState_JOB_STATE_RUNNING {
		t.Fatalf("lease did not advance Job: job=%v err=%v", runningJob, err)
	}
	runningOperation, err := (operations.SQLRepository{DB: db}).GetSQL(ctx, tenantID, projectID, operationID)
	if err != nil || runningOperation.GetState() != operationv1.OperationState_OPERATION_STATE_RUNNING || runningOperation.GetDone() {
		t.Fatalf("lease did not advance Operation: operation=%v err=%v", runningOperation, err)
	}
	if replay, replayErr := repository.AcquireLeaseSQL(ctx, acquire); replayErr != nil || !replay.Replay {
		t.Fatalf("acquire replay: result=%v err=%v", replay, replayErr)
	}

	completedAt := leaseAt.Add(time.Second)
	completedAttempt := proto.Clone(lease.Attempt).(*jobv1.Attempt)
	completedAttempt.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	completedAttempt.Outputs = []*artifactv1.ArtifactRef{configuration}
	completion := jobs.CompleteAttemptCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: tenantID, ProjectID: projectID, AttemptID: lease.Attempt.GetAttemptId(), WorkerID: lease.Attempt.GetWorkerId(),
			Token: token, Epoch: lease.Attempt.GetLeaseEpoch(),
		},
		Attempt: completedAttempt, UpdateMask: []string{"state", "outputs"}, ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Now: completedAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal", WorkerID: "worker-1",
			Action: "run.commit_attempt", IdempotencyKey: "complete-generic", RequestDigest: "sha256:" + strings.Repeat("c", 64), ObservedAt: completedAt,
		},
	}
	completed, err := repository.CompleteAttemptSQL(ctx, completion)
	if err != nil || completed.Replay || completed.Run.GetState() != jobv1.RunState_RUN_STATE_SUCCEEDED {
		t.Fatalf("complete generic scheduler Run: result=%v err=%v", completed, err)
	}
	terminalJob, err := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	if err != nil || terminalJob.GetState() != jobv1.JobState_JOB_STATE_SUCCEEDED {
		t.Fatalf("completion did not terminally advance Job: job=%v err=%v", terminalJob, err)
	}
	terminalOperation, err := (operations.SQLRepository{DB: db}).GetSQL(ctx, tenantID, projectID, operationID)
	if err != nil || terminalOperation.GetState() != operationv1.OperationState_OPERATION_STATE_SUCCEEDED || !terminalOperation.GetDone() ||
		!proto.Equal(terminalOperation.GetResult(), configuration) || terminalOperation.GetError() != nil ||
		terminalOperation.GetTarget().GetResourceType() != "run" || terminalOperation.GetTarget().GetResourceId() != strings.TrimPrefix(runID, "runs/") ||
		terminalOperation.GetTarget().GetResourceVersion() != completed.Run.GetResourceVersion() || terminalOperation.GetTarget().GetEtag() != completed.Run.GetEtag() {
		t.Fatalf("completion did not terminally advance Operation: operation=%v err=%v", terminalOperation, err)
	}
	if replay, replayErr := repository.CompleteAttemptSQL(ctx, completion); replayErr != nil || !replay.Replay {
		t.Fatalf("completion replay: result=%v err=%v", replay, replayErr)
	}
	unchangedJob, _ := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	unchangedOperation, _ := (operations.SQLRepository{DB: db}).GetSQL(ctx, tenantID, projectID, operationID)
	if unchangedJob.GetResourceVersion() != terminalJob.GetResourceVersion() || unchangedOperation.GetResourceVersion() != terminalOperation.GetResourceVersion() {
		t.Fatalf("idempotent replay created lifecycle revisions: job=%d/%d operation=%d/%d", unchangedJob.GetResourceVersion(), terminalJob.GetResourceVersion(), unchangedOperation.GetResourceVersion(), terminalOperation.GetResourceVersion())
	}
}

func TestPostgresCancellationExpiryFinalizesSchedulerLifecycle(t *testing.T) {
	db := postgresDB(t)
	if db == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	tenantID, projectID := "expiry-cancel-tenant-"+suffix, "project-1"
	jobID, operationID := "jobs/expiry-cancel-"+suffix, "operations/expiry-cancel-"+suffix
	t.Cleanup(func() {
		cleanupContext, cleanupCancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cleanupCancel()
		for _, table := range []string{
			"run_command_receipt_attempts", "run_command_receipts", "attempt_completion_history",
			"attempt_output_refs", "attempts", "run_output_refs", "runs", "inbox_delivery_failures",
			"inbox_messages", "dead_letter_messages", "outbox_messages", "audit_events",
			"idempotency_records", "operations", "jobs", "error_precondition_violations",
			"error_field_violations", "error_details", "artifact_references", "artifacts",
		} {
			if _, cleanupErr := db.ExecContext(cleanupContext, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); cleanupErr != nil { //nolint:gosec // closed table list; tenant remains bound.
				t.Errorf("clean cancellation expiry table %s: %v", table, cleanupErr)
				return
			}
		}
	})

	at := time.Now().UTC().Truncate(time.Microsecond)
	digest := "sha256:" + strings.Repeat("d", 64)
	configuration := &artifactv1.ArtifactRef{
		Digest: digest, IntegrityDigest: digest, MediaType: "application/json", SizeBytes: 1,
		ArtifactKind: "configuration", SchemaId: "scheduler-test", SchemaVersion: "1",
	}
	repository := jobs.SQLRepository{DB: db}
	requested, err := repository.RequestJobSQL(ctx, &jobv1.Job{
		JobId: jobID, TenantId: tenantID, ProjectId: projectID, JobKind: "generic.test",
		Configuration: configuration, Etag: "job-etag-1",
	}, &operationv1.Operation{
		OperationId: operationID, TenantId: tenantID, ProjectId: projectID, JobId: jobID, Etag: "operation-etag-1",
	}, jobs.JobCommandMetadata{
		TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal",
		IdempotencyKey: "request-expiry-cancel", RequestDigest: "sha256:" + strings.Repeat("e", 64), ObservedAt: at,
	})
	if err != nil || requested.Replay {
		t.Fatalf("request cancellation-expiry job: result=%v err=%v", requested, err)
	}
	var encoded []byte
	if err = db.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type='mindclade.events.job.v1.JobRequested'`, tenantID).Scan(&encoded); err != nil {
		t.Fatal(err)
	}
	envelope, err := pubsubx.UnmarshalEnvelope(encoded)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := pubsubx.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if accepted, consumeErr := inbox.AcceptAndHandleSQL(ctx, db, "expiry-cancel-scheduler", envelope, payload, jobs.JobRequestedHandler{}); consumeErr != nil || !accepted {
		t.Fatalf("consume cancellation-expiry JobRequested: accepted=%v err=%v", accepted, consumeErr)
	}
	var runID string
	if err = db.QueryRowContext(ctx, `SELECT id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND job_id=$3`, tenantID, projectID, jobID).Scan(&runID); err != nil {
		t.Fatal(err)
	}

	leaseAt := at.Add(time.Second)
	token := "expiry-cancellation-token-" + strings.Repeat("y", 32)
	lease, err := repository.AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{
		TenantID: tenantID, RunID: runID, AttemptID: "attempts/expiry-cancel-" + suffix, WorkerID: "worker-1",
		Token: token, TokenKeyID: "scheduler-key-1", Duration: jobs.MinimumLeaseDuration, Now: leaseAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal", WorkerID: "worker-1",
			Action: "run.acquire_lease", IdempotencyKey: "acquire-expiry-cancel", RequestDigest: "sha256:" + strings.Repeat("f", 64), ObservedAt: leaseAt,
		},
	})
	if err != nil {
		t.Fatalf("acquire cancellation-expiry lease: %v", err)
	}
	runningJob, err := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	if err != nil {
		t.Fatal(err)
	}
	cancelled, err := repository.CancelJobSQL(ctx, jobID, runningJob.GetEtag(), "operator cancellation", jobs.JobCommandMetadata{
		TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal",
		IdempotencyKey: "cancel-expiry-job", RequestDigest: "sha256:" + strings.Repeat("1", 64), ObservedAt: leaseAt.Add(time.Second),
	})
	if err != nil || cancelled.Job.GetState() != jobv1.JobState_JOB_STATE_CANCELLING || cancelled.Operation.GetState() != operationv1.OperationState_OPERATION_STATE_CANCELLING {
		t.Fatalf("request cancellation before expiry: result=%v err=%v", cancelled, err)
	}
	renewAt := leaseAt.Add(2 * time.Second)
	if _, renewErr := repository.RenewLeaseSQL(ctx, jobs.RenewLeaseCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: tenantID, ProjectID: projectID, AttemptID: lease.Attempt.GetAttemptId(), WorkerID: lease.Attempt.GetWorkerId(),
			Token: token, Epoch: lease.Attempt.GetLeaseEpoch(),
		},
		ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Duration: time.Minute, Now: renewAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal", WorkerID: "worker-1",
			Action: "run.renew_lease", IdempotencyKey: "renew-after-cancel", RequestDigest: "sha256:" + strings.Repeat("3", 64), ObservedAt: renewAt,
		},
	}); !errors.Is(renewErr, jobs.ErrTerminalMutation) {
		t.Fatalf("renew after cancellation error=%v, want terminal mutation", renewErr)
	}
	unrenewed, err := repository.GetAttemptSQL(ctx, tenantID, projectID, lease.Attempt.GetAttemptId())
	if err != nil || unrenewed.GetResourceVersion() != lease.Attempt.GetResourceVersion() || !proto.Equal(unrenewed.GetLeaseExpiresAt(), lease.Attempt.GetLeaseExpiresAt()) {
		t.Fatalf("rejected renewal mutated lease: attempt=%v err=%v", unrenewed, err)
	}

	expiredAt := lease.Attempt.GetLeaseExpiresAt().AsTime().Add(time.Nanosecond)
	expire := jobs.ExpireLeasesCommand{
		TenantID: tenantID, Limit: 10, Now: expiredAt,
		Command: jobs.RunCommandMetadata{
			TenantID: tenantID, ProjectID: projectID, PrincipalID: "scheduler-test-principal", WorkerID: "scheduler-1",
			Action: "run.expire_leases", IdempotencyKey: "expire-cancelled-lease", RequestDigest: "sha256:" + strings.Repeat("2", 64), ObservedAt: expiredAt,
		},
	}
	expired, err := repository.ExpireLeasesSQL(ctx, expire)
	if err != nil || expired.Replay || len(expired.Attempts) != 1 || expired.Attempts[0].GetState() != jobv1.AttemptState_ATTEMPT_STATE_CANCELLED {
		t.Fatalf("expire cancelling lease: result=%v err=%v", expired, err)
	}
	terminalRun, err := repository.GetRunSQL(ctx, tenantID, projectID, runID)
	if err != nil || terminalRun.GetState() != jobv1.RunState_RUN_STATE_CANCELLED || terminalRun.GetError().GetCode() != commonv1.ErrorCode_ERROR_CODE_CANCELLED {
		t.Fatalf("expiry did not cancel Run: run=%v err=%v", terminalRun, err)
	}
	terminalJob, err := repository.GetJobSQL(ctx, tenantID, projectID, jobID)
	if err != nil || terminalJob.GetState() != jobv1.JobState_JOB_STATE_CANCELLED {
		t.Fatalf("expiry did not cancel Job: job=%v err=%v", terminalJob, err)
	}
	terminalOperation, err := (operations.SQLRepository{DB: db}).GetSQL(ctx, tenantID, projectID, operationID)
	if err != nil || terminalOperation.GetState() != operationv1.OperationState_OPERATION_STATE_CANCELLED || !terminalOperation.GetDone() ||
		!proto.Equal(terminalOperation.GetError(), terminalRun.GetError()) || terminalOperation.GetTarget().GetResourceType() != "run" ||
		terminalOperation.GetTarget().GetResourceVersion() != terminalRun.GetResourceVersion() || terminalOperation.GetTarget().GetEtag() != terminalRun.GetEtag() {
		t.Fatalf("expiry did not cancel Operation: operation=%v err=%v", terminalOperation, err)
	}
	if replay, replayErr := repository.ExpireLeasesSQL(ctx, expire); replayErr != nil || !replay.Replay || len(replay.Attempts) != 1 || !proto.Equal(replay.Attempts[0], expired.Attempts[0]) {
		t.Fatalf("cancellation expiry replay changed result: result=%v err=%v", replay, replayErr)
	}
}
