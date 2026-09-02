package audit

import (
	"context"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

func TestWriterUsesGeneratedAuditEnvelope(t *testing.T) {
	event, err := NewEvent(
		"tenant-a",
		"principal-a",
		"artifacts.read",
		"artifact_0123456789",
		"allowed",
		time.Now().UTC(),
		map[string]string{"policy_digest": "sha256:" + strings.Repeat("a", 64)},
	)
	if err != nil {
		t.Fatal(err)
	}
	writer := new(MemoryWriter)
	if err = writer.Append(context.Background(), event); err != nil {
		t.Fatal(err)
	}
	events, err := writer.Events()
	if err != nil || len(events) != 1 {
		t.Fatalf("events=%d err=%v", len(events), err)
	}
	payload, err := ValidateEvent(events[0])
	if err != nil || payload.GetActorPrincipalId() != "principal-a" {
		t.Fatalf("payload=%v err=%v", payload, err)
	}
}

func TestWriterUsesGeneratedSecurityEnvelope(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 14, 0, 0, 0, time.UTC)
	subject := &commonv1.ResourceRef{
		ResourceType: "authorization_decision", ResourceId: "decision-1", TenantId: "tenant-a", ProjectId: "project-a",
		ResourceVersion: 1, Name: "tenants/tenant-a/projects/project-a/authorizationDecisions/decision-1",
	}
	command := &commonv1.CommandContext{
		TenantId: "tenant-a", ProjectId: "project-a", PrincipalId: "principal-a", RequestId: "request-a", IdempotencyKey: "denial-a",
		TraceId: "trace-a", CorrelationId: "correlation-a", CausationId: "causation-a",
	}
	digest := "sha256:" + strings.Repeat("a", 64)
	first, err := NewSecurityEvent("tenant-a", "project-a", "high", "DEFAULT_DENY", digest, subject, command, at)
	if err != nil {
		t.Fatal(err)
	}
	second, err := NewSecurityEvent("tenant-a", "project-a", "high", "DEFAULT_DENY", digest, subject, command, at)
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(first, second) || first.GetEventType() != "mindclade.events.audit.v1.SecurityEvent" ||
		first.GetClassification() != commonv1.DataClassification_DATA_CLASSIFICATION_RESTRICTED || first.GetAggregateSequence() != 1 {
		t.Fatalf("security fact is not deterministic and restricted: %v", first)
	}
	distinctCommand := proto.Clone(command).(*commonv1.CommandContext)
	distinctCommand.RequestId = "request-b"
	distinctCommand.IdempotencyKey = "denial-b"
	distinct, err := NewSecurityEvent("tenant-a", "project-a", "high", "DEFAULT_DENY", digest, subject, distinctCommand, at)
	if err != nil {
		t.Fatal(err)
	}
	if distinct.GetEventId() == first.GetEventId() {
		t.Fatal("distinct denied command collapsed to the same immutable security event")
	}
	writer := new(MemoryWriter)
	if err = writer.Append(context.Background(), first); err != nil {
		t.Fatal(err)
	}
	events, err := writer.Events()
	if err != nil || len(events) != 1 {
		t.Fatalf("events=%d err=%v", len(events), err)
	}
	payload, err := ValidateSecurityEvent(events[0])
	if err != nil || payload.GetSeverity() != "high" || payload.GetControl() != "DEFAULT_DENY" || payload.GetEvidenceDigest() != digest {
		t.Fatalf("security payload=%v err=%v", payload, err)
	}
	subject.Name = "caller-mutated"
	command.RequestId = "caller-mutated"
	if events[0].GetSubject().GetName() == "caller-mutated" || events[0].GetRequestId() == "caller-mutated" {
		t.Fatal("security factory retained a mutable alias")
	}
	tampered := proto.Clone(events[0]).(*commonv1.EventEnvelope)
	tampered.Payload[0] ^= 0xff
	if _, err = ValidateSecurityEvent(tampered); err == nil {
		t.Fatal("tampered security event passed digest validation")
	}
}
