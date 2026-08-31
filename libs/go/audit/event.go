package audit

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

const auditPayloadContentType = "application/x-protobuf; deterministic=true"

// NewEvent returns the generated immutable delivery envelope containing a
// generated AuditEvent payload. Arbitrary fields are deliberately rejected so
// secrets cannot be smuggled into durable audit evidence; policy_digest is the
// only supported legacy extension.
func NewEvent(tenantID, principalID, action, resourceID, decision string, at time.Time, fields map[string]string) (*commonv1.EventEnvelope, error) {
	if tenantID == "" || principalID == "" || action == "" || resourceID == "" || at.Location() != time.UTC {
		return nil, errors.New("invalid audit identity or UTC timestamp")
	}
	decision = strings.ToLower(decision)
	if decision != "allowed" && decision != "denied" {
		return nil, errors.New("audit decision must be allowed or denied")
	}
	policyDigest := ""
	for key, value := range fields {
		if key != "policy_digest" {
			return nil, fmt.Errorf("unsupported audit field %q", key)
		}
		policyDigest = value
	}
	if policyDigest != "" && !validSHA256Digest(policyDigest) {
		return nil, errors.New("policy_digest must be sha256:<64 lowercase hex>")
	}
	payloadMessage := &auditv1.AuditEvent{
		ActorPrincipalId: principalID,
		Action:           action,
		Decision:         decision,
		PolicyDigest:     policyDigest,
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal audit payload: %w", err)
	}
	payloadHash := sha256.Sum256(payload)
	eventHash := sha256.Sum256([]byte(tenantID + "\x00" + resourceID + "\x00" + at.Format(time.RFC3339Nano) + "\x00" + hex.EncodeToString(payloadHash[:])))
	eventType := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	envelope := &commonv1.EventEnvelope{
		EventId:            "audit:" + hex.EncodeToString(eventHash[:]),
		EventType:          eventType,
		EventVersion:       1,
		OccurredAt:         timestamppb.New(at),
		RecordedAt:         timestamppb.New(at),
		TenantId:           tenantID,
		Subject:            &commonv1.ResourceRef{ResourceType: resourceType(resourceID), ResourceId: resourceID, TenantId: tenantID},
		PayloadDigest:      "sha256:" + hex.EncodeToString(payloadHash[:]),
		Payload:            payload,
		Producer:           "libs/go/audit",
		AggregateSequence:  1,
		DeduplicationKey:   "audit:" + hex.EncodeToString(eventHash[:]),
		PayloadContentType: auditPayloadContentType,
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if _, err := ValidateEvent(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

// ValidateEvent verifies the envelope digest and decodes the authoritative
// generated audit payload without exposing a second event model.
func ValidateEvent(envelope *commonv1.EventEnvelope) (*auditv1.AuditEvent, error) {
	if envelope == nil || envelope.GetEventId() == "" || envelope.GetTenantId() == "" || envelope.GetEventVersion() != 1 {
		return nil, errors.New("invalid audit envelope identity")
	}
	if envelope.GetOccurredAt() == nil || envelope.GetRecordedAt() == nil {
		return nil, errors.New("audit timestamps are required")
	}
	if err := envelope.GetOccurredAt().CheckValid(); err != nil {
		return nil, fmt.Errorf("invalid occurred_at: %w", err)
	}
	if err := envelope.GetRecordedAt().CheckValid(); err != nil {
		return nil, fmt.Errorf("invalid recorded_at: %w", err)
	}
	if envelope.GetSubject() == nil || envelope.GetSubject().GetResourceId() == "" || envelope.GetPayloadContentType() != auditPayloadContentType {
		return nil, errors.New("audit subject and protobuf content type are required")
	}
	payload := new(auditv1.AuditEvent)
	expectedType := string(payload.ProtoReflect().Descriptor().FullName())
	if envelope.GetEventType() != expectedType {
		return nil, fmt.Errorf("unexpected audit event type %q", envelope.GetEventType())
	}
	payloadHash := sha256.Sum256(envelope.GetPayload())
	if envelope.GetPayloadDigest() != "sha256:"+hex.EncodeToString(payloadHash[:]) {
		return nil, errors.New("audit payload digest mismatch")
	}
	if err := proto.Unmarshal(envelope.GetPayload(), payload); err != nil {
		return nil, fmt.Errorf("unmarshal audit payload: %w", err)
	}
	if payload.GetActorPrincipalId() == "" || payload.GetAction() == "" || (payload.GetDecision() != "allowed" && payload.GetDecision() != "denied") {
		return nil, errors.New("invalid audit payload")
	}
	if payload.GetPolicyDigest() != "" && !validSHA256Digest(payload.GetPolicyDigest()) {
		return nil, errors.New("invalid audit policy digest")
	}
	return payload, nil
}

func resourceType(resourceID string) string {
	if separator := strings.IndexByte(resourceID, '_'); separator > 0 {
		return resourceID[:separator]
	}
	return "resource"
}

func validSHA256Digest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}
