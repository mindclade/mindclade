package policies

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) DecisionRecorded(identity Identity, decision *policyv1.AuthorizationDecision, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &policyv1.AuthorizationDecisionRecorded{Decision: clone(decision)}
	subject := &commonv1.ResourceRef{ResourceType: "authorization_decision", ResourceId: decision.GetUid(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: decision.GetName(), Etag: decision.GetDecisionDigest()}
	return newEvent(identity, subject, payload, 1, command, at)
}

func (GeneratedEventFactory) PolicyCreated(identity Identity, value *policyv1.UsePolicy, operation *operationv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &policyv1.UsePolicyCreated{UsePolicy: clone(value), Operation: operationResource(operation), CreatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, usePolicyResource(identity, value), payload, value.GetRevision(), command, at)
}

func (GeneratedEventFactory) PolicyUpdated(identity Identity, value *policyv1.UsePolicy, changed []string, operation *operationv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &policyv1.UsePolicyUpdated{UsePolicy: clone(value), ChangedFields: append([]string(nil), changed...), Operation: operationResource(operation), UpdatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, usePolicyResource(identity, value), payload, value.GetRevision(), command, at)
}

func (GeneratedEventFactory) PolicyActivated(identity Identity, value *policyv1.UsePolicy, operation *operationv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &policyv1.UsePolicyActivated{UsePolicy: clone(value), ActiveSnapshot: clone(value.GetActiveSnapshot()), Operation: operationResource(operation), ActivatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, usePolicyResource(identity, value), payload, value.GetRevision(), command, at)
}

func (GeneratedEventFactory) PolicyRevoked(identity Identity, value *policyv1.UsePolicy, reason string, operation *operationv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &policyv1.UsePolicyRevoked{UsePolicy: clone(value), ReasonCode: reason, Operation: operationResource(operation), RevokedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, usePolicyResource(identity, value), payload, value.GetRevision(), command, at)
}

func newEvent(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, revision int64, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if subject == nil || payload == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("policy event inputs are incomplete")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventType := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	id := "policy:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{
		EventId: id, EventType: eventType, EventVersion: 1, OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(), Subject: clone(subject),
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		Producer: "services/control_plane/internal/policies", AggregateSequence: sequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: id, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}
