package controlplane_test

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

// recordingExecutor stands in for the caller's *sql.Tx. Recording the
// statement and its arguments is what lets these tests assert that every
// column is derived from the envelope, and that a rejected envelope reaches
// the database not at all rather than partially.
type recordingExecutor struct {
	statements []string
	arguments  [][]any
	err        error
}

func (e *recordingExecutor) ExecContext(_ context.Context, statement string, arguments ...any) (sql.Result, error) {
	e.statements = append(e.statements, statement)
	e.arguments = append(e.arguments, arguments)
	if e.err != nil {
		return nil, e.err
	}
	return driverResult{}, nil
}

type driverResult struct{}

func (driverResult) LastInsertId() (int64, error) { return 0, errors.New("not supported") }
func (driverResult) RowsAffected() (int64, error) { return 1, nil }

func producerEnvelope(t *testing.T) *commonv1.EventEnvelope {
	t.Helper()
	envelope, err := foundationaudit.NewEvent(
		"tenant_producer", "producer-principal", "producer.enqueue",
		"jobs_producer-subject", "allowed", time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC), nil,
	)
	if err != nil {
		t.Fatalf("build producer envelope: %v", err)
	}
	return envelope
}

// TestInsertOutboxMessageDerivesEveryColumnFromTheEnvelope pins the contract
// the fourteen hand-copied variants disagreed on: the row is a projection of
// the envelope, so no caller-held tenant or aggregate value can shadow it.
func TestInsertOutboxMessageDerivesEveryColumnFromTheEnvelope(t *testing.T) {
	envelope := producerEnvelope(t)
	encoded, err := queue.MarshalEnvelope(envelope)
	if err != nil {
		t.Fatalf("marshal envelope: %v", err)
	}
	aggregateType, aggregateID, err := queue.AggregateIdentity(envelope)
	if err != nil {
		t.Fatalf("resolve aggregate identity: %v", err)
	}
	executor := new(recordingExecutor)
	at := time.Date(2026, 9, 2, 12, 30, 0, 0, time.FixedZone("UTC+2", 2*60*60))
	if err = queue.InsertOutboxMessage(context.Background(), executor, envelope, at); err != nil {
		t.Fatalf("insert outbox message: %v", err)
	}
	if len(executor.statements) != 1 {
		t.Fatalf("expected exactly one statement, got %d", len(executor.statements))
	}
	if !strings.Contains(executor.statements[0], "INSERT INTO outbox_messages") {
		t.Fatalf("unexpected statement: %s", executor.statements[0])
	}
	expected := []any{
		envelope.GetEventId(),
		envelope.GetTenantId(),
		envelope.GetEventType(),
		envelope.GetEventVersion(),
		aggregateType,
		aggregateID,
		envelope.GetAggregateSequence(),
		envelope.GetPayloadDigest(),
	}
	arguments := executor.arguments[0]
	if len(arguments) != len(expected)+2 {
		t.Fatalf("expected %d bound arguments, got %d", len(expected)+2, len(arguments))
	}
	for index, want := range expected {
		if arguments[index] != want {
			t.Fatalf("argument %d = %v, want %v", index+1, arguments[index], want)
		}
	}
	envelopeBytes, ok := arguments[len(expected)].([]byte)
	if !ok || string(envelopeBytes) != string(encoded) {
		t.Fatal("envelope_bytes must be the deterministic marshalling of the envelope")
	}
	recordedAt, ok := arguments[len(expected)+1].(time.Time)
	if !ok || recordedAt.Location() != time.UTC || !recordedAt.Equal(at) {
		t.Fatalf("next_attempt_at must be the same instant normalized to UTC, got %v", arguments[len(expected)+1])
	}
}

// TestInsertOutboxMessageRejectsAnInvalidEnvelopeBeforeWriting is the gate two
// of the replaced variants skipped by deriving aggregate identity inline.
func TestInsertOutboxMessageRejectsAnInvalidEnvelopeBeforeWriting(t *testing.T) {
	for name, mutate := range map[string]func(*commonv1.EventEnvelope){
		"nil envelope":       nil,
		"missing tenant":     func(e *commonv1.EventEnvelope) { e.TenantId = "" },
		"missing producer":   func(e *commonv1.EventEnvelope) { e.Producer = "" },
		"zero sequence":      func(e *commonv1.EventEnvelope) { e.AggregateSequence = 0 },
		"digest mismatch":    func(e *commonv1.EventEnvelope) { e.PayloadDigest = "sha256:" + strings.Repeat("0", 64) },
		"unregistered event": func(e *commonv1.EventEnvelope) { e.EventVersion = 99 },
	} {
		t.Run(name, func(t *testing.T) {
			var envelope *commonv1.EventEnvelope
			if mutate != nil {
				envelope = producerEnvelope(t)
				mutate(envelope)
			}
			executor := new(recordingExecutor)
			err := queue.InsertOutboxMessage(context.Background(), executor, envelope, time.Now().UTC())
			if !errors.Is(err, queue.ErrInvalidEnvelope) {
				t.Fatalf("expected ErrInvalidEnvelope, got %v", err)
			}
			if len(executor.statements) != 0 {
				t.Fatal("a rejected envelope must not reach the database")
			}
		})
	}
}

// TestInsertOutboxMessageRejectsAnOversizedEnvelope keeps the failure attached
// to the code that produced the event. Without the bound the row commits and
// the relay discovers the problem asynchronously, by which point the operator
// sees a dead letter rather than the producing call site.
func TestInsertOutboxMessageRejectsAnOversizedEnvelope(t *testing.T) {
	envelope := producerEnvelope(t)
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(&auditv1.AuditEvent{
		ActorPrincipalId: "producer-principal",
		Action:           strings.Repeat("o", queue.MaxOutboxEnvelopeBytes+1),
		Decision:         "allowed",
	})
	if err != nil {
		t.Fatalf("marshal oversized payload: %v", err)
	}
	digest := sha256.Sum256(payload)
	envelope.Payload = payload
	envelope.PayloadDigest = "sha256:" + hex.EncodeToString(digest[:])
	executor := new(recordingExecutor)
	err = queue.InsertOutboxMessage(context.Background(), executor, envelope, time.Now().UTC())
	if !errors.Is(err, queue.ErrInvalidEnvelope) {
		t.Fatalf("expected ErrInvalidEnvelope, got %v", err)
	}
	if !strings.Contains(err.Error(), "outbox limit") {
		t.Fatalf("error must name the limit it violated, got %v", err)
	}
	if len(executor.statements) != 0 {
		t.Fatal("an oversized envelope must not reach the database")
	}
}

// TestInsertOutboxMessageSurfacesTheDatabaseError confirms the producer adds no
// retry or swallowing of its own: the caller's transaction owns the outcome.
func TestInsertOutboxMessageSurfacesTheDatabaseError(t *testing.T) {
	failure := errors.New("duplicate key value violates unique constraint")
	executor := &recordingExecutor{err: failure}
	err := queue.InsertOutboxMessage(context.Background(), executor, producerEnvelope(t), time.Now().UTC())
	if !errors.Is(err, failure) {
		t.Fatalf("expected the database error to surface unchanged, got %v", err)
	}
	if len(executor.statements) != 1 {
		t.Fatalf("expected exactly one attempt, got %d", len(executor.statements))
	}
}
