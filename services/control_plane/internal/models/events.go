package models

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
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) Registered(identity Identity, model *modelv1.Model, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &modelv1.ModelRegistered{ModelName: model.GetName(), ModelUid: model.GetUid(), ModelRevision: model.GetRevision(), Family: model.GetFamily(), DefinitionManifest: clone(model.GetDefinitionManifest()), FeatureRequirementSet: clone(model.GetFeatureRequirementSet()), ModelFeatureView: clone(model.GetModelFeatureView()), RegisteredAt: clone(model.GetCreateTime())}
	return newEvent(identity, modelResource(model), payload, model.GetRevision(), context, at)
}

func (GeneratedEventFactory) ReleaseRegistered(identity Identity, release *modelv1.ModelRelease, operation *operationv1.Operation, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &modelv1.ModelReleaseRegistered{
		ModelReleaseName:      release.GetName(),
		ModelReleaseUid:       release.GetUid(),
		ModelReleaseRevision:  release.GetRevision(),
		ModelName:             release.GetModelName(),
		ReleaseId:             release.GetReleaseId(),
		Stage:                 release.GetStage(),
		BundleManifest:        clone(release.GetBundleManifest()),
		ModelManifest:         clone(release.GetModelManifest()),
		Checkpoint:            clone(release.GetCheckpoint()),
		EvaluationEvidence:    cloneSlice(release.GetEvaluationEvidence()),
		FeatureRequirementSet: clone(release.GetFeatureRequirementSet()),
		ModelFeatureView:      clone(release.GetModelFeatureView()),
		ReleasePolicy:         clone(release.GetReleasePolicy()),
		Operation:             operationResource(operation),
		RegisteredAt:          clone(release.GetCreateTime()),
	}
	return newEvent(identity, releaseResource(release), payload, release.GetRevision(), context, at)
}

func (GeneratedEventFactory) Promoted(identity Identity, release *modelv1.ModelRelease, prior modelv1.ModelReleaseStage, evidence []*artifactv1.EvidenceRef, decision *artifactv1.EvidenceRef, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &modelv1.ModelPromoted{ModelReleaseName: release.GetName(), ModelReleaseRevision: release.GetRevision(), PriorStage: prior, PromotedStage: release.GetStage(), Evidence: cloneSlice(evidence), PromotionDecision: clone(decision), PromotedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, releaseResource(release), payload, release.GetRevision(), context, at)
}

func (GeneratedEventFactory) Revoked(identity Identity, release *modelv1.ModelRelease, evidence []*artifactv1.EvidenceRef, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &modelv1.ModelRevoked{ModelReleaseName: release.GetName(), ModelReleaseRevision: release.GetRevision(), Reason: release.GetRevocationReason(), Evidence: cloneSlice(evidence), RevokedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, releaseResource(release), payload, release.GetRevision(), context, at)
}

func newEvent(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, revision int64, context *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if subject == nil || payload == nil || context == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("model event inputs are incomplete")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventType := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + context.GetRequestId()))
	id := "model:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{EventId: id, EventType: eventType, EventVersion: 1, OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: context.GetTraceId(), Subject: clone(subject), PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded, Producer: "services/control_plane/internal/models", AggregateSequence: sequence, RequestId: context.GetRequestId(), CorrelationId: context.GetCorrelationId(), CausationId: context.GetCausationId(), DeduplicationKey: id, PayloadContentType: protobufEventContentType, Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func modelResource(value *modelv1.Model) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "model", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func releaseResource(value *modelv1.ModelRelease) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func operationResource(value *operationv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{
		ResourceType:    "operation",
		ResourceId:      lastSegment(value.GetOperationId()),
		TenantId:        value.GetTenantId(),
		ProjectId:       value.GetProjectId(),
		ResourceVersion: value.GetResourceVersion(),
		Name:            value.GetOperationId(),
		Etag:            value.GetEtag(),
	}
}

func lastSegment(value string) string {
	for i := len(value) - 1; i >= 0; i-- {
		if value[i] == '/' {
			return value[i+1:]
		}
	}
	return value
}
