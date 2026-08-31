package telemetry

import (
	"fmt"

	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"google.golang.org/protobuf/proto"
)

type AuditSink interface {
	EmitAudit(*commonv1.EventEnvelope) error
}

// DecodeAuditPayload gives telemetry implementations the generated payload
// and rejects other envelope types. No parallel telemetry event model exists.
func DecodeAuditPayload(envelope *commonv1.EventEnvelope) (*auditv1.AuditEvent, error) {
	if envelope == nil {
		return nil, fmt.Errorf("audit envelope is required")
	}
	payload := new(auditv1.AuditEvent)
	expectedType := string(payload.ProtoReflect().Descriptor().FullName())
	if envelope.GetEventType() != expectedType {
		return nil, fmt.Errorf("unexpected audit event type %q", envelope.GetEventType())
	}
	if err := proto.Unmarshal(envelope.GetPayload(), payload); err != nil {
		return nil, fmt.Errorf("unmarshal audit payload: %w", err)
	}
	return payload, nil
}
