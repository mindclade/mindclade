package datasets

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
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) Created(identity Identity, dataset *datasetv1.Dataset, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &datasetv1.DatasetCreated{DatasetName: dataset.GetName(), DatasetUid: dataset.GetUid(), DatasetRevision: dataset.GetRevision(), DisplayName: dataset.GetDisplayName(), PolicyClassification: dataset.GetPolicyClassification(), Operation: operationResource(operation), CreatedAt: clone(dataset.GetCreateTime())}
	return newEvent(identity, datasetResource(dataset), payload, dataset.GetRevision(), command, at)
}

func (GeneratedEventFactory) Updated(identity Identity, dataset *datasetv1.Dataset, changedFields []string, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &datasetv1.DatasetUpdated{DatasetName: dataset.GetName(), DatasetRevision: dataset.GetRevision(), DatasetEtag: dataset.GetEtag(), ChangedFields: append([]string(nil), changedFields...), State: dataset.GetState(), Operation: operationResource(operation), UpdatedAt: clone(dataset.GetUpdateTime())}
	return newEvent(identity, datasetResource(dataset), payload, dataset.GetRevision(), command, at)
}

func (GeneratedEventFactory) Published(identity Identity, release *datasetv1.DatasetRelease, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &datasetv1.DatasetReleasePublished{DatasetReleaseName: release.GetName(), DatasetReleaseUid: release.GetUid(), DatasetReleaseRevision: release.GetRevision(), DatasetName: release.GetDatasetName(), ReleaseId: release.GetReleaseId(), Manifest: clone(release.GetManifest()), QualificationEvidence: cloneSlice(release.GetQualificationEvidence()), ParentRelease: clone(release.GetParentRelease()), UsePolicy: clone(release.GetUsePolicy()), Operation: operationResource(operation), PublishedAt: clone(release.GetPublishTime())}
	return newEvent(identity, releaseResource(release), payload, release.GetRevision(), command, at)
}

func (GeneratedEventFactory) Revoked(identity Identity, release *datasetv1.DatasetRelease, evidence []*artifactv1.EvidenceRef, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &datasetv1.DatasetReleaseRevoked{DatasetReleaseName: release.GetName(), DatasetReleaseRevision: release.GetRevision(), Reason: release.GetRevocationReason(), Evidence: cloneSlice(evidence), Operation: operationResource(operation), RevokedAt: clone(release.GetRevokeTime())}
	return newEvent(identity, releaseResource(release), payload, release.GetRevision(), command, at)
}

func newEvent(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, revision int64, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if subject == nil || payload == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("dataset event inputs are incomplete")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventType := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	id := "dataset:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{EventId: id, EventType: eventType, EventVersion: 1, OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(), Subject: clone(subject), PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded, Producer: "services/control_plane/internal/datasets", AggregateSequence: sequence, RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(), DeduplicationKey: id, PayloadContentType: protobufEventContentType, Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func datasetResource(value *datasetv1.Dataset) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "dataset", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func releaseResource(value *datasetv1.DatasetRelease) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "dataset_release", ResourceId: lastSegment(value.GetName()), TenantId: lastSegment(value.GetTenantName()), ProjectId: lastSegment(value.GetProjectName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func operationResource(value *jobv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "operation", ResourceId: lastSegment(value.GetOperationId()), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetResourceVersion(), Name: value.GetOperationId(), Etag: value.GetEtag()}
}

func lastSegment(value string) string {
	for index := len(value) - 1; index >= 0; index-- {
		if value[index] == '/' {
			return value[index+1:]
		}
	}
	return value
}
