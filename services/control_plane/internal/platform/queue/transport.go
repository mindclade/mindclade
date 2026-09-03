package queue

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

var ErrInvalidEnvelope = errors.New("invalid event envelope")

// EventRegistration is generated from protocols/events/registry.yaml. Event
// type and version are a joint identity; consumers never accept an arbitrary
// non-zero version.
type EventRegistration struct {
	FullName            string
	Version             uint32
	ContentType         string
	Source              string
	Owner               string
	LifecycleState      string
	CompatibilityPolicy string
	Fixture             EventFixtureEvidence
	Producers           []EventEvidenceEndpoint
	Consumers           []EventEvidenceEndpoint
	ActivationGaps      []string
}

// EventEvidenceEndpoint binds registry claims to reviewed source and build
// evidence. Producer and consumer entries name behavior, not generic relays.
type EventEvidenceEndpoint struct {
	ID     string
	Source string
	Target string
	Mode   string
}

// EventFixtureEvidence records either a verified populated fixture or the
// explicit reason a candidate event cannot yet be activated.
type EventFixtureEvidence struct {
	Status string
	Source string
	Target string
	Mode   string
	Reason string
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
		if registration.FullName == "" || registration.Version == 0 || registration.ContentType == "" || registration.Source == "" || registration.Owner == "" || registration.CompatibilityPolicy != "exact-version" {
			panic("generated event registry contains an incomplete registration")
		}
		if registration.LifecycleState != "active" && registration.LifecycleState != "candidate" && registration.LifecycleState != "deprecated" && registration.LifecycleState != "retired" {
			panic("generated event registry contains an invalid lifecycle state")
		}
		if registration.LifecycleState == "active" && (registration.Fixture.Status != "verified" || len(registration.Producers) == 0 || len(registration.Consumers) == 0 || len(registration.ActivationGaps) != 0) {
			panic("generated active event registration lacks production evidence")
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
	registration.Producers = append([]EventEvidenceEndpoint(nil), registration.Producers...)
	registration.Consumers = append([]EventEvidenceEndpoint(nil), registration.Consumers...)
	registration.ActivationGaps = append([]string(nil), registration.ActivationGaps...)
	return registration, ok
}

// EventRegistryRatifiable reports whether every descriptor-visible event is
// production-active. Candidate metadata remains usable for exact decoding but
// cannot silently satisfy v1 ratification.
func EventRegistryRatifiable() bool {
	for _, registration := range authoritativeEventRegistry {
		if registration.LifecycleState != "active" {
			return false
		}
	}
	return true
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

// UnmarshalRegisteredPayload resolves the exact generated payload type named
// by the authoritative event registry. Consumers never decode into a generic
// map or accept unknown fields under an already registered event version.
func UnmarshalRegisteredPayload(envelope *commonv1.EventEnvelope) (proto.Message, error) {
	if err := ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	messageType, err := protoregistry.GlobalTypes.FindMessageByName(protoreflect.FullName(envelope.GetEventType()))
	if err != nil {
		return nil, fmt.Errorf("%w: generated payload type %s is not linked: %w", ErrInvalidEnvelope, envelope.GetEventType(), err)
	}
	payload := messageType.New().Interface()
	if err = (proto.UnmarshalOptions{DiscardUnknown: false, Resolver: protoregistry.GlobalTypes}).Unmarshal(envelope.GetPayload(), payload); err != nil {
		return nil, fmt.Errorf("%w: decode registered payload %s: %w", ErrInvalidEnvelope, envelope.GetEventType(), err)
	}
	if len(payload.ProtoReflect().GetUnknown()) != 0 {
		return nil, fmt.Errorf("%w: payload %s contains fields unknown to registered version %d", ErrInvalidEnvelope, envelope.GetEventType(), envelope.GetEventVersion())
	}
	canonical, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("%w: canonicalize registered payload %s: %w", ErrInvalidEnvelope, envelope.GetEventType(), err)
	}
	if !bytes.Equal(canonical, envelope.GetPayload()) {
		return nil, fmt.Errorf("%w: payload %s is not the canonical deterministic protobuf encoding", ErrInvalidEnvelope, envelope.GetEventType())
	}
	return payload, nil
}

// OrderingKey returns the stable, opaque Pub/Sub key for one aggregate. The
// clear-text tenant and resource identity remain only inside the protobuf
// envelope and authenticated attributes.
func OrderingKey(envelope *commonv1.EventEnvelope) (string, error) {
	aggregateType, aggregateID, err := AggregateIdentity(envelope)
	if err != nil {
		return "", err
	}
	source := envelope.GetTenantId() + "\x00" + aggregateType + "\x00" + aggregateID
	digest := sha256.Sum256([]byte(source))
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

// AggregateIdentity returns the canonical durable ordering identity. A fully
// qualified resource name is project-scoped and therefore takes precedence
// over a leaf resource ID; contracts without a name retain the resource_id
// compatibility fallback.
func AggregateIdentity(envelope *commonv1.EventEnvelope) (string, string, error) {
	if err := ValidateEnvelope(envelope); err != nil {
		return "", "", err
	}
	aggregateType, aggregateID := aggregateIdentity(envelope)
	return aggregateType, aggregateID, nil
}

// aggregateIdentity derives the ordering identity from an envelope a caller has
// already validated. ValidateEnvelope hashes the whole payload, so a caller
// that marshals and then derives would pay for that twice -- 5.9ms at the
// outbox size ceiling, inside the caller's open transaction. One definition of
// the identity, two entry points to it.
func aggregateIdentity(envelope *commonv1.EventEnvelope) (string, string) {
	aggregateID := envelope.GetSubject().GetName()
	if aggregateID == "" {
		aggregateID = envelope.GetSubject().GetResourceId()
	}
	return envelope.GetSubject().GetResourceType(), aggregateID
}

// TransportAttributes duplicates only routing and integrity metadata needed
// to quarantine an unreadable protobuf envelope. The envelope remains the
// semantic authority and consumers require exact equality when it is valid.
func TransportAttributes(envelope *commonv1.EventEnvelope) (map[string]string, error) {
	aggregateType, aggregateID, err := AggregateIdentity(envelope)
	if err != nil {
		return nil, err
	}
	return map[string]string{
		"event_id":             envelope.GetEventId(),
		"event_type":           envelope.GetEventType(),
		"event_version":        strconv.FormatUint(uint64(envelope.GetEventVersion()), 10),
		"tenant_id":            envelope.GetTenantId(),
		"project_id":           envelope.GetProjectId(),
		"aggregate_type":       aggregateType,
		"aggregate_id":         aggregateID,
		"aggregate_sequence":   strconv.FormatUint(envelope.GetAggregateSequence(), 10),
		"payload_digest":       envelope.GetPayloadDigest(),
		"payload_content_type": envelope.GetPayloadContentType(),
	}, nil
}

func ValidateTransportAttributes(envelope *commonv1.EventEnvelope, attributes map[string]string, orderingKey string) error {
	expected, err := TransportAttributes(envelope)
	if err != nil {
		return err
	}
	for name, value := range expected {
		if attributes[name] != value {
			return fmt.Errorf("%w: transport attribute %s does not match envelope", ErrInvalidEnvelope, name)
		}
	}
	expectedOrderingKey, err := OrderingKey(envelope)
	if err != nil {
		return err
	}
	if orderingKey != expectedOrderingKey {
		return fmt.Errorf("%w: transport ordering key does not match envelope aggregate", ErrInvalidEnvelope)
	}
	return nil
}

func ValidateEnvelope(envelope *commonv1.EventEnvelope) error {
	if envelope == nil {
		return fmt.Errorf("%w: message is required", ErrInvalidEnvelope)
	}
	if envelope.GetEventId() == "" || envelope.GetEventType() == "" || envelope.GetEventVersion() == 0 || envelope.GetTenantId() == "" {
		return fmt.Errorf("%w: identity, type, version, and tenant are required", ErrInvalidEnvelope)
	}
	if envelope.GetProducer() == "" || envelope.GetDeduplicationKey() == "" || envelope.GetAggregateSequence() == 0 {
		return fmt.Errorf("%w: producer, deduplication key, and aggregate sequence are required", ErrInvalidEnvelope)
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
	if envelope.GetSubject().GetTenantId() != envelope.GetTenantId() || envelope.GetSubject().GetProjectId() != envelope.GetProjectId() {
		return fmt.Errorf("%w: subject tenant/project scope must match the envelope", ErrInvalidEnvelope)
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
