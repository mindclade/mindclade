package audit

import (
	"context"
	"strings"
	"testing"
	"time"
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
