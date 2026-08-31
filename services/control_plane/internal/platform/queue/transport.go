package queue

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

var ErrInvalidEnvelope = errors.New("invalid event envelope")

// EventRegistration is generated from protocols/events/registry.yaml. Event
// type and version are a joint identity; consumers never accept an arbitrary
// non-zero version.
type EventRegistration struct {
	FullName    string
	Version     uint32
	ContentType string
	Source      string
}

type eventIdentity struct {
	fullName string
	version  uint32
}

var authoritativeEventRegistry = buildEventRegistry(authoritativeEventRegistrations)

func buildEventRegistry(registrations []EventRegistration) map[eventIdentity]EventRegistration {
	registry := make(map[eventIdentity]EventRegistration, len(registrations))
	for _, registration := range registrations {
		identity := eventIdentity{fullName: registration.FullName, version: registration.Version}
		if registration.FullName == "" || registration.Version == 0 || registration.ContentType == "" {
			panic("generated event registry contains an incomplete registration")
		}
		if _, exists := registry[identity]; exists {
			panic("generated event registry contains a duplicate identity")
		}
		registry[identity] = registration
	}
	return registry
}

// RegisteredEvent returns a value copy so callers cannot mutate registry
// authority shared by producers and consumers.
func RegisteredEvent(fullName string, version uint32) (EventRegistration, bool) {
	registration, ok := authoritativeEventRegistry[eventIdentity{fullName: fullName, version: version}]
	return registration, ok
}

// Transport is an at-least-once envelope transport. It deliberately exposes no database capability.
type Transport interface {
	Publish(context.Context, *commonv1.EventEnvelope) error
}

// MarshalEnvelope validates and deterministically serializes the authoritative
// generated envelope for a queue, outbox, audit, or dead-letter boundary.
func MarshalEnvelope(envelope *commonv1.EventEnvelope) ([]byte, error) {
	if err := ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("marshal event envelope: %w", err)
	}
	return encoded, nil
}

// UnmarshalEnvelope rejects corrupt or semantically incomplete durable bytes.
func UnmarshalEnvelope(encoded []byte) (*commonv1.EventEnvelope, error) {
	envelope := new(commonv1.EventEnvelope)
	if err := proto.Unmarshal(encoded, envelope); err != nil {
		return nil, fmt.Errorf("unmarshal event envelope: %w", err)
	}
	if err := ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func ValidateEnvelope(envelope *commonv1.EventEnvelope) error {
	if envelope == nil {
		return fmt.Errorf("%w: message is required", ErrInvalidEnvelope)
	}
	if envelope.GetEventId() == "" || envelope.GetEventType() == "" || envelope.GetEventVersion() == 0 || envelope.GetTenantId() == "" {
		return fmt.Errorf("%w: identity, type, version, and tenant are required", ErrInvalidEnvelope)
	}
	registration, ok := RegisteredEvent(envelope.GetEventType(), envelope.GetEventVersion())
	if !ok {
		return fmt.Errorf(
			"%w: unregistered event identity %s@%d",
			ErrInvalidEnvelope,
			envelope.GetEventType(),
			envelope.GetEventVersion(),
		)
	}
	if envelope.GetOccurredAt() == nil || envelope.GetRecordedAt() == nil {
		return fmt.Errorf("%w: occurred_at and recorded_at are required", ErrInvalidEnvelope)
	}
	if err := envelope.GetOccurredAt().CheckValid(); err != nil {
		return fmt.Errorf("%w: occurred_at: %w", ErrInvalidEnvelope, err)
	}
	if err := envelope.GetRecordedAt().CheckValid(); err != nil {
		return fmt.Errorf("%w: recorded_at: %w", ErrInvalidEnvelope, err)
	}
	if envelope.GetSubject() == nil || envelope.GetSubject().GetResourceId() == "" || envelope.GetSubject().GetResourceType() == "" {
		return fmt.Errorf("%w: subject is required", ErrInvalidEnvelope)
	}
	if len(envelope.GetPayload()) == 0 || envelope.GetPayloadContentType() == "" {
		return fmt.Errorf("%w: payload bytes and content type are required", ErrInvalidEnvelope)
	}
	if envelope.GetPayloadContentType() != registration.ContentType {
		return fmt.Errorf(
			"%w: content type for %s@%d must be %q",
			ErrInvalidEnvelope,
			envelope.GetEventType(),
			envelope.GetEventVersion(),
			registration.ContentType,
		)
	}
	payloadDigest := sha256.Sum256(envelope.GetPayload())
	expected := "sha256:" + hex.EncodeToString(payloadDigest[:])
	if envelope.GetPayloadDigest() != expected {
		return fmt.Errorf("%w: payload digest mismatch", ErrInvalidEnvelope)
	}
	if envelope.GetClassification() == commonv1.DataClassification_DATA_CLASSIFICATION_UNSPECIFIED {
		return fmt.Errorf("%w: data classification is required", ErrInvalidEnvelope)
	}
	return nil
}
