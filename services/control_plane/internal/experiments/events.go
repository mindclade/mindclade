package experiments

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
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) ExperimentCreated(identity Identity, value *experimentv1.Experiment, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.ExperimentCreated{Experiment: clone(value), CreatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, experimentResource(value), payload, context, at)
}

func (GeneratedEventFactory) ExperimentUpdated(identity Identity, value *experimentv1.Experiment, fields []string, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.ExperimentUpdated{Experiment: clone(value), ChangedFields: append([]string(nil), fields...), UpdatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, experimentResource(value), payload, context, at)
}

func (GeneratedEventFactory) ExperimentStateChanged(identity Identity, value *experimentv1.Experiment, prior experimentv1.ExperimentState, reasonCode string, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.ExperimentStateChanged{Experiment: clone(value), PriorState: prior, ReasonCode: reasonCode, ChangedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, experimentResource(value), payload, context, at)
}

func (GeneratedEventFactory) StudyCreated(identity Identity, value *experimentv1.Study, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.StudyCreated{Study: clone(value), CreatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, studyResource(value), payload, context, at)
}

func (GeneratedEventFactory) StudyStateChanged(identity Identity, value *experimentv1.Study, prior experimentv1.StudyState, reasonCode string, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.StudyStateChanged{Study: clone(value), PriorState: prior, ReasonCode: reasonCode, ChangedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, studyResource(value), payload, context, at)
}

func (GeneratedEventFactory) TrialCreated(identity Identity, value *experimentv1.Trial, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.TrialCreated{Trial: clone(value), CreatedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, trialResource(value), payload, context, at)
}

func (GeneratedEventFactory) TrialStateChanged(identity Identity, value *experimentv1.Trial, prior experimentv1.TrialState, reasonCode string, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.TrialStateChanged{Trial: clone(value), PriorState: prior, ReasonCode: reasonCode, ChangedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, trialResource(value), payload, context, at)
}

func (GeneratedEventFactory) TrialCompleted(identity Identity, value *experimentv1.Trial, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &experimentv1.TrialCompleted{Trial: clone(value), CompletedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, trialResource(value), payload, context, at)
}

func newEvent(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if subject == nil || payload == nil || context == nil || subject.GetResourceVersion() < 1 || at.IsZero() {
		return nil, errors.New("experiment event inputs are incomplete")
	}
	sequence, err := numconv.Int64ToUint64(subject.GetResourceVersion())
	if err != nil {
		return nil, err
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventType := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + context.GetRequestId()))
	id := "experiment:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{
		EventId: id, EventType: eventType, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: context.GetTraceId(), Subject: clone(subject),
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		Producer: "services/control_plane/internal/experiments", AggregateSequence: sequence,
		RequestId: context.GetRequestId(), CorrelationId: context.GetCorrelationId(), CausationId: context.GetCausationId(),
		DeduplicationKey: id, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func experimentResource(value *experimentv1.Experiment) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "experiment", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func studyResource(value *experimentv1.Study) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "study", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func trialResource(value *experimentv1.Trial) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "trial", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}
