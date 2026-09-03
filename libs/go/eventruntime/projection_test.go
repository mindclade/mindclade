package eventruntime

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/inbox"
	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

// These contracts originally had no populated fixture evidence. Naming the
// set here makes the registry claim reviewable, while the descriptor-driven
// test below populates and exact-version round-trips each complete message.
var projectionOwnedFixtureEvents = map[string]struct{}{
	"mindclade.events.admin.v1.AuditExportRequested":             {},
	"mindclade.events.admin.v1.ProjectUpdated":                   {},
	"mindclade.events.admin.v1.TenantUpdated":                    {},
	"mindclade.events.artifact.v1.ArtifactStagingFinalized":      {},
	"mindclade.events.audit.v1.AuditEvent":                       {},
	"mindclade.events.policy.v1.UsePolicyActivated":              {},
	"mindclade.events.policy.v1.UsePolicyRevoked":                {},
	"mindclade.events.policy.v1.UsePolicyUpdated":                {},
	"mindclade.events.workflow.v1.WorkflowCancellationRequested": {},
	"mindclade.events.workflow.v1.WorkflowDefinitionCreated":     {},
	"mindclade.events.workflow.v1.WorkflowDefinitionUpdated":     {},
	"mindclade.events.workflow.v1.WorkflowRunStarted":            {},
	"mindclade.events.workflow.v1.WorkflowTransitioned":          {},
}

func TestPopulatedEventFixturesCoverRegistry(t *testing.T) {
	descriptorEvents := make(map[string]struct{})
	protoregistry.GlobalTypes.RangeMessages(func(messageType protoreflect.MessageType) bool {
		fullName := string(messageType.Descriptor().FullName())
		if strings.HasPrefix(fullName, "mindclade.events.") {
			descriptorEvents[fullName] = struct{}{}
		}
		return true
	})
	if len(semanticDefinitions) != len(descriptorEvents) {
		t.Fatalf("semantic event coverage=%d, descriptor event coverage=%d", len(semanticDefinitions), len(descriptorEvents))
	}
	for fullName := range descriptorEvents {
		if _, ok := semanticDefinitions[fullName]; !ok {
			t.Fatalf("descriptor event has no semantic definition: %s", fullName)
		}
	}
	for fullName := range semanticDefinitions {
		t.Run(fullName, func(t *testing.T) {
			registration, ok := pubsubx.RegisteredEvent(fullName, 1)
			if !ok || registration.CompatibilityPolicy != "exact-version" {
				t.Fatalf("missing exact-version registry entry for %s", fullName)
			}
			messageType, err := protoregistry.GlobalTypes.FindMessageByName(protoreflect.FullName(fullName))
			if err != nil {
				t.Fatalf("generated payload type is not linked: %v", err)
			}
			payload := messageType.New().Interface()
			populateMessage(payload.ProtoReflect(), 0)
			if proto.Size(payload) == 0 {
				t.Fatal("populated fixture encoded to an empty payload")
			}
			envelope := fixtureEnvelope(t, fullName, payload, "tenant-fixture", "project-fixture", "fixture-aggregate", "fixture-event", 1)
			decoded, err := pubsubx.UnmarshalRegisteredPayload(envelope)
			if err != nil {
				t.Fatalf("exact-version fixture decode: %v", err)
			}
			if !proto.Equal(payload, decoded) {
				t.Fatal("populated fixture did not survive deterministic round trip")
			}
			fact := deriveFact(envelope, decoded, semanticDefinitions[fullName])
			if err = validateSemanticFact(fact); err != nil {
				t.Fatalf("populated fixture did not yield a bounded semantic fact: %v", err)
			}
			if fact.action == "" || fact.actor == "" || fact.outcome == "" {
				t.Fatalf("semantic fixture is incomplete: %#v", fact)
			}
		})
	}
	for fullName := range projectionOwnedFixtureEvents {
		registration, ok := pubsubx.RegisteredEvent(fullName, 1)
		if !ok {
			t.Fatalf("projection-owned populated fixture is not registered: %s", fullName)
		}
		if registration.Fixture.Source != "libs/go/eventruntime/projection_test.go" ||
			registration.Fixture.Mode != "populated-protobuf-roundtrip" {
			t.Fatalf("projection-owned fixture evidence drift for %s: %#v", fullName, registration.Fixture)
		}
	}
}

func TestAcceptedEventsFollowActiveRegistryLifecycle(t *testing.T) {
	accepted, err := AcceptedEvents()
	if err != nil {
		t.Fatal(err)
	}
	for fullName := range semanticDefinitions {
		registration, ok := pubsubx.RegisteredEvent(fullName, 1)
		if !ok {
			t.Fatalf("semantic event %s is not registered", fullName)
		}
		_, subscribed := accepted[fullName]
		if subscribed != (registration.LifecycleState == "active") {
			t.Fatalf("subscription lifecycle mismatch for %s: active=%t subscribed=%t", fullName, registration.LifecycleState == "active", subscribed)
		}
	}
}

func TestEventProjectionAtomicityOrderingAndExactVersion(t *testing.T) {
	db := eventProjectionDB(t)
	if db == nil {
		t.Skip("PostgreSQL event projection integration requires MINDCLADE_TEST_POSTGRES_DSN")
	}
	ctx := context.Background()
	now := time.Date(2026, 9, 2, 15, 0, 0, 0, time.UTC)
	unique := strconv.FormatInt(time.Now().UTC().UnixNano(), 10)
	tenantID := "tenant-event-projection-" + unique
	projectID := "project-event-projection"
	processor := inbox.Processor{
		DB: db, Consumer: ConsumerName, Handler: Handler{Now: func() time.Time { return now.Add(time.Minute) }},
		AcceptedEvents: map[string]uint32{"mindclade.events.job.v1.JobRequested": 1},
		MaxAttempts:    3, QuarantineTenantID: tenantID,
	}

	t.Run("duplicate delivery is atomically deduplicated and queryable", func(t *testing.T) {
		envelope := jobEnvelope(t, tenantID, projectID, "duplicate", "event-duplicate", 1, now)
		processOK(t, ctx, processor, envelope)
		processOK(t, ctx, processor, envelope)
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", envelope.GetEventId(), 1)
		assertTenantCount(t, ctx, db, tenantID, "administrative_audit_records", "event_id", envelope.GetEventId(), 1)
		assertTenantCount(t, ctx, db, tenantID, "inbox_messages", "event_id", envelope.GetEventId(), 1)
		var action, detailDigest string
		withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
			if err := tx.QueryRowContext(ctx, `SELECT action,detail_digest FROM administrative_audit_records WHERE tenant_id=$1 AND event_id=$2`, tenantID, envelope.GetEventId()).Scan(&action, &detailDigest); err != nil {
				t.Fatal(err)
			}
		})
		if action != envelope.GetEventType() || detailDigest != envelope.GetPayloadDigest() {
			t.Fatalf("admin audit query projection action=%q detail=%q", action, detailDigest)
		}
		// The Admin audit query narrows administrative_audit_records by tenant,
		// project, action, and occurrence window. This library cannot import the
		// control plane's private admin package to run that query, so it asserts
		// the same predicate directly: a fact the projection writes must satisfy
		// every clause the Admin query applies, or the projection has written a
		// row the service can never return.
		var visible int
		withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
			if err := tx.QueryRowContext(
				ctx,
				`SELECT count(*) FROM administrative_audit_records
				 WHERE tenant_id=$1 AND project_id=$2 AND action=$3
				   AND occurred_at BETWEEN $4 AND $5 AND event_id=$6`,
				tenantID,
				projectID,
				envelope.GetEventType(),
				now.Add(-time.Minute),
				now.Add(time.Minute),
				envelope.GetEventId(),
			).Scan(&visible); err != nil {
				t.Fatal(err)
			}
		})
		if visible != 1 {
			t.Fatalf("Admin audit query predicate did not match the projected event fact: %d rows", visible)
		}
	})

	t.Run("handler failure rolls inbox and projection back", func(t *testing.T) {
		envelope := jobEnvelope(t, tenantID, projectID, "rollback", "event-rollback", 1, now)
		payload, err := pubsubx.UnmarshalRegisteredPayload(envelope)
		if err != nil {
			t.Fatal(err)
		}
		rollback := errors.New("synthetic failure after semantic projection")
		handler := inbox.TransactionalHandlerFunc(func(handlerContext context.Context, tx *sql.Tx, value *commonv1.EventEnvelope, decoded proto.Message) error {
			if handleErr := (Handler{Now: func() time.Time { return now.Add(time.Minute) }}).HandleEvent(handlerContext, tx, value, decoded); handleErr != nil {
				return handleErr
			}
			return rollback
		})
		if accepted, acceptErr := inbox.AcceptAndHandleSQL(ctx, db, ConsumerName, envelope, payload, handler); accepted || !errors.Is(acceptErr, rollback) {
			t.Fatalf("rollback delivery accepted=%t err=%v", accepted, acceptErr)
		}
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", envelope.GetEventId(), 0)
		assertTenantCount(t, ctx, db, tenantID, "inbox_messages", "event_id", envelope.GetEventId(), 0)
		processOK(t, ctx, processor, envelope)
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", envelope.GetEventId(), 1)
	})

	t.Run("receiver clock skew does not poison a valid ordered event", func(t *testing.T) {
		envelope := jobEnvelope(t, tenantID, projectID, "clock-skew", "event-clock-skew", 1, now)
		skewedProcessor := processor
		skewedProcessor.Handler = Handler{Now: func() time.Time { return now.Add(-30 * time.Second) }}
		processOK(t, ctx, skewedProcessor, envelope)
		withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
			var receivedAt, recordedAt time.Time
			if err := tx.QueryRowContext(ctx, `
SELECT received_at,recorded_at FROM event_audit_projection
WHERE tenant_id=$1 AND event_id=$2`, tenantID, envelope.GetEventId()).Scan(&receivedAt, &recordedAt); err != nil {
				t.Fatal(err)
			}
			if !receivedAt.Before(recordedAt) {
				t.Fatalf("test did not retain observed clock skew: received=%s recorded=%s", receivedAt, recordedAt)
			}
		})
	})

	t.Run("aggregate sequence remains authoritative across producer clock skew", func(t *testing.T) {
		first := jobEnvelope(t, tenantID, projectID, "producer-clock-skew", "event-producer-clock-skew-1", 1, now)
		second := jobEnvelope(t, tenantID, projectID, "producer-clock-skew", "event-producer-clock-skew-2", 2, now.Add(-30*time.Second))
		processOK(t, ctx, processor, first)
		skewedProcessor := processor
		skewedProcessor.Handler = Handler{Now: func() time.Time { return now.Add(-time.Minute) }}
		processOK(t, ctx, skewedProcessor, second)
		withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
			var sequence uint64
			var occurredAt time.Time
			if err := tx.QueryRowContext(ctx, `
SELECT last_sequence,last_occurred_at FROM event_audit_projection_heads
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3`, tenantID, second.GetSubject().GetResourceType(), second.GetSubject().GetName()).Scan(&sequence, &occurredAt); err != nil {
				t.Fatal(err)
			}
			if sequence != 2 || !occurredAt.Equal(second.GetOccurredAt().AsTime()) {
				t.Fatalf("sequence head=%d occurrence=%s", sequence, occurredAt)
			}
		})
	})

	t.Run("row-level security hides another tenant projection", func(t *testing.T) {
		otherTenantID := tenantID + "-other"
		withTenantReadRoleTx(t, ctx, db, otherTenantID, func(tx *sql.Tx) {
			var count int
			if err := tx.QueryRowContext(ctx, `SELECT count(*) FROM event_audit_projection WHERE tenant_id=$1`, tenantID).Scan(&count); err != nil {
				t.Fatal(err)
			}
			if count != 0 {
				t.Fatalf("cross-tenant projection rows visible=%d", count)
			}
		})
	})

	t.Run("gaps wait for predecessors and stale sequences fail closed", func(t *testing.T) {
		first := jobEnvelope(t, tenantID, projectID, "ordered", "event-ordered-1", 1, now)
		second := jobEnvelope(t, tenantID, projectID, "ordered", "event-ordered-2", 2, now.Add(time.Second))
		third := jobEnvelope(t, tenantID, projectID, "ordered", "event-ordered-3", 3, now.Add(2*time.Second))
		processOK(t, ctx, processor, first)
		disposition, processErr := process(ctx, processor, third)
		if disposition != inbox.DeliveryNack || !errors.Is(processErr, ErrSequenceGap) {
			t.Fatalf("gap disposition=%v err=%v", disposition, processErr)
		}
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", third.GetEventId(), 0)
		assertTenantCount(t, ctx, db, tenantID, "inbox_messages", "event_id", third.GetEventId(), 0)
		processOK(t, ctx, processor, second)
		processOK(t, ctx, processor, third)

		stale := jobEnvelope(t, tenantID, projectID, "ordered", "event-ordered-stale", 2, now.Add(3*time.Second))
		disposition, processErr = process(ctx, processor, stale)
		if disposition != inbox.DeliveryNack || !errors.Is(processErr, ErrStaleSequence) {
			t.Fatalf("stale disposition=%v err=%v", disposition, processErr)
		}
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", stale.GetEventId(), 0)
	})

	t.Run("concurrent first events serialize baseline selection", func(t *testing.T) {
		events := []*commonv1.EventEnvelope{
			jobEnvelope(t, tenantID, projectID, "concurrent-baseline", "event-concurrent-a", 1, now),
			jobEnvelope(t, tenantID, projectID, "concurrent-baseline", "event-concurrent-b", 1, now),
		}
		type result struct {
			disposition inbox.DeliveryDisposition
			err         error
		}
		results := make(chan result, len(events))
		start := make(chan struct{})
		var workers sync.WaitGroup
		for _, envelope := range events {
			workers.Add(1)
			go func(value *commonv1.EventEnvelope) {
				defer workers.Done()
				<-start
				disposition, err := process(ctx, processor, value)
				results <- result{disposition: disposition, err: err}
			}(envelope)
		}
		close(start)
		workers.Wait()
		close(results)
		acknowledged, stale := 0, 0
		for value := range results {
			switch {
			case value.disposition == inbox.DeliveryAck && value.err == nil:
				acknowledged++
			case value.disposition == inbox.DeliveryNack && errors.Is(value.err, ErrStaleSequence):
				stale++
			default:
				t.Fatalf("concurrent baseline disposition=%v err=%v", value.disposition, value.err)
			}
		}
		if acknowledged != 1 || stale != 1 {
			t.Fatalf("concurrent baseline acknowledged=%d stale=%d", acknowledged, stale)
		}
		projected := 0
		for _, envelope := range events {
			withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
				var count int
				if err := tx.QueryRowContext(ctx, `SELECT count(*) FROM event_audit_projection WHERE tenant_id=$1 AND event_id=$2`, tenantID, envelope.GetEventId()).Scan(&count); err != nil {
					t.Fatal(err)
				}
				projected += count
			})
		}
		if projected != 1 {
			t.Fatalf("concurrent baseline projected rows=%d, want 1", projected)
		}
	})

	t.Run("aggregate sequence heads are immutable and bound to the projected event", func(t *testing.T) {
		tx, err := platformdb.BeginTenantTx(ctx, db, tenantID, nil)
		if err != nil {
			t.Fatal(err)
		}
		_, deleteErr := tx.ExecContext(ctx, `
DELETE FROM event_audit_projection_heads
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3`, tenantID, "fixture", "tenants/"+tenantID+"/projects/"+projectID+"/fixtures/ordered")
		if deleteErr == nil || !strings.Contains(deleteErr.Error(), "aggregate heads cannot be deleted") {
			_ = tx.Rollback()
			t.Fatalf("sequence head deletion was not rejected: %v", deleteErr)
		}
		if err = tx.Rollback(); err != nil {
			t.Fatal(err)
		}

		wrongTarget := jobEnvelope(t, tenantID, projectID, "wrong-head", "event-wrong-head", 4, now.Add(4*time.Second))
		processOK(t, ctx, processor, wrongTarget)
		tx, err = platformdb.BeginTenantTx(ctx, db, tenantID, nil)
		if err != nil {
			t.Fatal(err)
		}
		_, updateErr := tx.ExecContext(ctx, `
UPDATE event_audit_projection_heads
SET last_sequence=4,last_event_id=$4,last_occurred_at=$5,updated_at=$5
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3`, tenantID, "fixture", "tenants/"+tenantID+"/projects/"+projectID+"/fixtures/ordered", wrongTarget.GetEventId(), wrongTarget.GetOccurredAt().AsTime())
		if updateErr == nil {
			_ = tx.Rollback()
			t.Fatal("sequence head accepted an event from another aggregate")
		}
		if err = tx.Rollback(); err != nil {
			t.Fatal(err)
		}
		withTenantTx(t, ctx, db, tenantID, func(readTx *sql.Tx) {
			var sequence uint64
			if err = readTx.QueryRowContext(ctx, `
SELECT last_sequence FROM event_audit_projection_heads
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3`, tenantID, "fixture", "tenants/"+tenantID+"/projects/"+projectID+"/fixtures/ordered").Scan(&sequence); err != nil {
				t.Fatal(err)
			}
			if sequence != 3 {
				t.Fatalf("sequence head changed after rejected deletion: %d", sequence)
			}
		})
	})

	t.Run("unknown versions are rejected before durable mutation", func(t *testing.T) {
		envelope := jobEnvelope(t, tenantID, projectID, "unknown-version", "event-unknown-version", 1, now)
		payload := &jobv1.JobRequested{JobId: "job-unknown-version", ConfigurationDigest: fixtureDigest("unknown")}
		envelope.EventVersion = 2
		accepted, err := inbox.AcceptAndHandleSQL(ctx, db, ConsumerName, envelope, payload, Handler{})
		if accepted || !errors.Is(err, pubsubx.ErrInvalidEnvelope) {
			t.Fatalf("unknown version accepted=%t err=%v", accepted, err)
		}
		assertTenantCount(t, ctx, db, tenantID, "event_audit_projection", "event_id", envelope.GetEventId(), 0)
		assertTenantCount(t, ctx, db, tenantID, "inbox_messages", "event_id", envelope.GetEventId(), 0)
	})

	t.Run("down migration refuses immutable projection evidence and restores force RLS", func(t *testing.T) {
		downSQL := readEventProjectionMigration(t, "down")
		if err := executeDownMigration(ctx, db, downSQL, ""); err == nil || !strings.Contains(err.Error(), "requires app.allow_local_empty_down_migration=true") {
			t.Fatalf("unauthorized down migration was not rejected: %v", err)
		}
		if err := executeDownMigration(ctx, db, downSQL, "true"); err == nil || !strings.Contains(err.Error(), "cannot remove event audit projection while immutable evidence exists") {
			t.Fatalf("down migration did not reject retained evidence: %v", err)
		}
		var forced int
		if err := db.QueryRowContext(ctx, `
SELECT count(*) FROM pg_class
WHERE relnamespace='public'::regnamespace
  AND relname=ANY(ARRAY['event_audit_projection','event_audit_projection_heads'])
  AND relrowsecurity AND relforcerowsecurity`).Scan(&forced); err != nil {
			t.Fatal(err)
		}
		if forced != 2 {
			t.Fatalf("failed down migration restored FORCE RLS on %d/2 tables", forced)
		}
	})

	t.Run("empty projection migration rehearses down and up safely", func(t *testing.T) {
		rehearseEmptyProjectionMigration(t, ctx, db)
	})

	t.Run("ordinary non-owner cannot disable projection RLS", func(t *testing.T) {
		var superuser bool
		if err := db.QueryRowContext(ctx, `SELECT rolsuper FROM pg_roles WHERE rolname=current_user`).Scan(&superuser); err != nil {
			t.Fatal(err)
		}
		if !superuser {
			if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
				t.Fatal("required PostgreSQL qualification role must be able to assume the built-in non-owner role")
			}
			t.Skip("connected integration role cannot assume the built-in non-owner role")
		}
		tx, err := db.BeginTx(ctx, nil)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = tx.Rollback() }()
		if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE pg_monitor`); err != nil {
			t.Fatal(err)
		}
		if _, err = tx.ExecContext(ctx, `ALTER TABLE event_audit_projection NO FORCE ROW LEVEL SECURITY`); err == nil {
			t.Fatal("ordinary non-owner unexpectedly altered projection RLS")
		}
		_ = tx.Rollback()
		var forced bool
		if err = db.QueryRowContext(ctx, `
SELECT relrowsecurity AND relforcerowsecurity FROM pg_class
WHERE oid='public.event_audit_projection'::regclass`).Scan(&forced); err != nil {
			t.Fatal(err)
		}
		if !forced {
			t.Fatal("failed non-owner migration attempt changed FORCE RLS")
		}
	})
}

func readEventProjectionMigration(t *testing.T, direction string) string {
	t.Helper()
	if direction != "up" && direction != "down" {
		t.Fatalf("invalid event projection migration direction %q", direction)
	}
	name := "000009_event_audit_projection." + direction + ".sql"
	candidates := []string{
		"services/control_plane/migrations/" + name,
		"../../../migrations/" + name,
	}
	if runfiles, workspace := os.Getenv("TEST_SRCDIR"), os.Getenv("TEST_WORKSPACE"); runfiles != "" && workspace != "" {
		candidates = append(candidates, filepath.Join(runfiles, workspace, "services/control_plane/migrations", name))
	}
	for _, candidate := range candidates {
		value, err := os.ReadFile(candidate) //nolint:gosec // Candidates are fixed repository/runfiles locations built from a closed direction enum.
		if err == nil {
			return string(value)
		}
	}
	t.Fatalf("event projection down migration is absent from test runfiles: %v", candidates)
	return ""
}

func rehearseEmptyProjectionMigration(t *testing.T, ctx context.Context, db *sql.DB) {
	t.Helper()
	// The suffix is decimal-only and the fixed prefix makes these unquoted SQL
	// identifiers safe. A dedicated connection preserves search_path across the
	// migration's own BEGIN/COMMIT statements.
	schema := fmt.Sprintf("event_projection_migration_test_%d", time.Now().UTC().UnixNano())
	conn, err := db.Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if _, err = conn.ExecContext(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = conn.ExecContext(ctx, "ROLLBACK")
		_, _ = conn.ExecContext(ctx, `SELECT set_config('app.allow_local_empty_down_migration','',false)`)
		_, _ = conn.ExecContext(ctx, "SET search_path TO public; DROP SCHEMA "+schema+" CASCADE")
	}()
	if _, err = conn.ExecContext(ctx, "SET search_path TO "+schema); err != nil {
		t.Fatal(err)
	}
	if _, err = conn.ExecContext(ctx, `SELECT set_config('app.allow_local_empty_down_migration','true',false)`); err != nil {
		t.Fatal(err)
	}
	if _, err = conn.ExecContext(ctx, `
CREATE TABLE inbox_messages (
  tenant_id text NOT NULL,
  consumer text NOT NULL,
  event_id text NOT NULL,
  PRIMARY KEY (tenant_id,consumer,event_id)
);
CREATE TABLE resource_references (
  tenant_id text NOT NULL,
  id bigint NOT NULL,
  UNIQUE (tenant_id,id)
)`); err != nil {
		t.Fatal(err)
	}
	upSQL, downSQL := readEventProjectionMigration(t, "up"), readEventProjectionMigration(t, "down")
	if _, err = conn.ExecContext(ctx, upSQL); err != nil {
		t.Fatalf("initial event projection up migration: %v", err)
	}
	if _, err = conn.ExecContext(ctx, downSQL); err != nil {
		t.Fatalf("empty event projection down migration: %v", err)
	}
	if _, err = conn.ExecContext(ctx, upSQL); err != nil {
		t.Fatalf("event projection re-apply after empty down: %v", err)
	}
	var forced int
	if err = conn.QueryRowContext(ctx, `
SELECT count(*) FROM pg_class
WHERE relnamespace=current_schema()::regnamespace
  AND relname=ANY(ARRAY['event_audit_projection','event_audit_projection_heads'])
  AND relrowsecurity AND relforcerowsecurity`).Scan(&forced); err != nil {
		t.Fatal(err)
	}
	if forced != 2 {
		t.Fatalf("re-applied empty migration forced RLS on %d/2 tables", forced)
	}
}

func executeDownMigration(ctx context.Context, db *sql.DB, migration, authorization string) error {
	conn, err := db.Conn(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close() }()
	if _, err = conn.ExecContext(ctx, `SELECT set_config('app.allow_local_empty_down_migration',$1,false)`, authorization); err != nil {
		return err
	}
	defer func() {
		_, _ = conn.ExecContext(ctx, "ROLLBACK")
		_, _ = conn.ExecContext(ctx, `SELECT set_config('app.allow_local_empty_down_migration','',false)`)
	}()
	_, err = conn.ExecContext(ctx, migration)
	return err
}

func eventProjectionDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		return nil
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err = db.PingContext(context.Background()); err != nil {
		t.Fatal(err)
	}
	return db
}

func processOK(t *testing.T, ctx context.Context, processor inbox.Processor, envelope *commonv1.EventEnvelope) {
	t.Helper()
	disposition, err := process(ctx, processor, envelope)
	if err != nil || disposition != inbox.DeliveryAck {
		t.Fatalf("process event %s disposition=%v err=%v", envelope.GetEventId(), disposition, err)
	}
}

func process(ctx context.Context, processor inbox.Processor, envelope *commonv1.EventEnvelope) (inbox.DeliveryDisposition, error) {
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		return inbox.DeliveryNack, err
	}
	attributes, err := pubsubx.TransportAttributes(envelope)
	if err != nil {
		return inbox.DeliveryNack, err
	}
	orderingKey, err := pubsubx.OrderingKey(envelope)
	if err != nil {
		return inbox.DeliveryNack, err
	}
	return processor.ProcessDelivery(ctx, encoded, attributes, orderingKey)
}

func jobEnvelope(t *testing.T, tenantID, projectID, aggregateID, eventID string, sequence uint64, at time.Time) *commonv1.EventEnvelope {
	t.Helper()
	payload := &jobv1.JobRequested{JobId: "job-" + eventID, ConfigurationDigest: fixtureDigest(eventID)}
	return fixtureEnvelope(t, "mindclade.events.job.v1.JobRequested", payload, tenantID, projectID, aggregateID, eventID, sequence, at)
}

func fixtureEnvelope(t *testing.T, eventType string, payload proto.Message, tenantID, projectID, aggregateID, eventID string, sequence uint64, occurrence ...time.Time) *commonv1.EventEnvelope {
	t.Helper()
	resourceVersion, err := numconv.Uint64ToInt64(sequence)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(encoded)
	at := time.Date(2026, 9, 2, 15, 0, 0, 0, time.UTC)
	if len(occurrence) != 0 {
		at = occurrence[0].UTC()
	}
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: eventType, EventVersion: 1,
		OccurredAt: timestamppb.New(at), RecordedAt: timestamppb.New(at), TenantId: tenantID, ProjectId: projectID,
		Subject:       &commonv1.ResourceRef{ResourceType: "fixture", ResourceId: aggregateID, TenantId: tenantID, ProjectId: projectID, ResourceVersion: resourceVersion, Name: "tenants/" + tenantID + "/projects/" + projectID + "/fixtures/" + aggregateID},
		PayloadDigest: "sha256:" + hex.EncodeToString(digest[:]), Payload: encoded, Producer: "services/control_plane/tests/eventprojection",
		AggregateSequence: sequence, RequestId: "request-" + eventID, CorrelationId: "correlation-" + aggregateID,
		DeduplicationKey: eventID, PayloadContentType: "application/x-protobuf; deterministic=true",
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		t.Fatalf("fixture envelope: %v", err)
	}
	return envelope
}

func populateMessage(message protoreflect.Message, depth int) {
	if depth > 6 {
		return
	}
	fields := message.Descriptor().Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if field.IsMap() {
			value := fixtureValue(field.MapValue(), message.NewField(field).Map().NewValue(), depth+1)
			message.Mutable(field).Map().Set(fixtureMapKey(field.MapKey()), value)
			continue
		}
		if field.IsList() {
			list := message.Mutable(field).List()
			list.Append(fixtureValue(field, list.NewElement(), depth+1))
			continue
		}
		value := fixtureValue(field, message.NewField(field), depth+1)
		message.Set(field, value)
	}
}

func fixtureValue(field protoreflect.FieldDescriptor, value protoreflect.Value, depth int) protoreflect.Value {
	switch field.Kind() {
	case protoreflect.BoolKind:
		return protoreflect.ValueOfBool(true)
	case protoreflect.EnumKind:
		values := field.Enum().Values()
		if values.Len() > 1 {
			return protoreflect.ValueOfEnum(values.Get(1).Number())
		}
		return protoreflect.ValueOfEnum(values.Get(0).Number())
	case protoreflect.Int32Kind, protoreflect.Sint32Kind, protoreflect.Sfixed32Kind:
		return protoreflect.ValueOfInt32(1)
	case protoreflect.Int64Kind, protoreflect.Sint64Kind, protoreflect.Sfixed64Kind:
		return protoreflect.ValueOfInt64(1)
	case protoreflect.Uint32Kind, protoreflect.Fixed32Kind:
		return protoreflect.ValueOfUint32(1)
	case protoreflect.Uint64Kind, protoreflect.Fixed64Kind:
		return protoreflect.ValueOfUint64(1)
	case protoreflect.FloatKind:
		return protoreflect.ValueOfFloat32(1)
	case protoreflect.DoubleKind:
		return protoreflect.ValueOfFloat64(1)
	case protoreflect.StringKind:
		name := string(field.Name())
		if strings.Contains(name, "digest") || name == "etag" {
			return protoreflect.ValueOfString(fixtureDigest(name))
		}
		return protoreflect.ValueOfString("fixture-" + name)
	case protoreflect.BytesKind:
		return protoreflect.ValueOfBytes([]byte("fixture"))
	case protoreflect.MessageKind, protoreflect.GroupKind:
		populateMessage(value.Message(), depth)
		return value
	default:
		return value
	}
}

func fixtureMapKey(field protoreflect.FieldDescriptor) protoreflect.MapKey {
	switch field.Kind() {
	case protoreflect.StringKind:
		return protoreflect.ValueOfString("fixture-key").MapKey()
	case protoreflect.BoolKind:
		return protoreflect.ValueOfBool(true).MapKey()
	case protoreflect.Int32Kind, protoreflect.Sint32Kind, protoreflect.Sfixed32Kind:
		return protoreflect.ValueOfInt32(1).MapKey()
	case protoreflect.Int64Kind, protoreflect.Sint64Kind, protoreflect.Sfixed64Kind:
		return protoreflect.ValueOfInt64(1).MapKey()
	case protoreflect.Uint32Kind, protoreflect.Fixed32Kind:
		return protoreflect.ValueOfUint32(1).MapKey()
	case protoreflect.Uint64Kind, protoreflect.Fixed64Kind:
		return protoreflect.ValueOfUint64(1).MapKey()
	default:
		panic("unsupported protobuf map key kind")
	}
}

func fixtureDigest(value string) string {
	digest := sha256.Sum256([]byte(value))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func withTenantTx(t *testing.T, ctx context.Context, db *sql.DB, tenantID string, fn func(*sql.Tx)) {
	t.Helper()
	tx, err := platformdb.BeginTenantTx(ctx, db, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	fn(tx)
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
}

func withTenantReadRoleTx(t *testing.T, ctx context.Context, db *sql.DB, tenantID string, fn func(*sql.Tx)) {
	t.Helper()
	var superuser bool
	if err := db.QueryRowContext(ctx, `SELECT rolsuper FROM pg_roles WHERE rolname=current_user`).Scan(&superuser); err != nil {
		t.Fatal(err)
	}
	if !superuser {
		withTenantTx(t, ctx, db, tenantID, fn)
		return
	}
	tx, err := db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id', $1, true)`, tenantID); err != nil {
		t.Fatal(err)
	}
	// pg_read_all_data can read every table but, unlike a superuser, does not
	// bypass RLS. Assuming it here exercises the production policy even when
	// the migration-managed integration database is owned by a superuser.
	if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE pg_read_all_data`); err != nil {
		t.Fatal(err)
	}
	fn(tx)
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
}

func assertTenantCount(t *testing.T, ctx context.Context, db *sql.DB, tenantID, table, column, value string, expected int) {
	t.Helper()
	allowed := map[string]bool{
		"event_audit_projection/event_id":       true,
		"administrative_audit_records/event_id": true,
		"inbox_messages/event_id":               true,
	}
	if !allowed[table+"/"+column] {
		t.Fatal("test attempted an unreviewed dynamic SQL identifier")
	}
	withTenantTx(t, ctx, db, tenantID, func(tx *sql.Tx) {
		var count int
		query := "SELECT count(*) FROM " + table + " WHERE tenant_id=$1 AND " + column + "=$2"
		if err := tx.QueryRowContext(ctx, query, tenantID, value).Scan(&count); err != nil {
			t.Fatal(err)
		}
		if count != expected {
			t.Fatalf("%s count=%d, want %d", table, count, expected)
		}
	})
}
