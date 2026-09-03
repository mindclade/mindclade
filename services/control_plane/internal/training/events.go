package training

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type EventFactory interface {
	Created(Identity, *trainingv1.TrainingRun, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	JobRequested(Identity, *operationv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Started(Identity, *trainingv1.TrainingRun, *jobv1.LeaseFence, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Progress(Identity, *trainingv1.TrainingRun, *trainingv1.TrainingProgress, *jobv1.LeaseFence, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Checkpoint(Identity, *trainingv1.TrainingRun, *trainingv1.Checkpoint, *jobv1.LeaseFence, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Completed(Identity, *trainingv1.TrainingRun, *jobv1.LeaseFence, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	CancellationRequested(Identity, *trainingv1.TrainingRun, *operationv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) Created(identity Identity, run *trainingv1.TrainingRun, operation *operationv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.TrainingRunCreated{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(),
		TrainingRecipe: clone(run.GetTrainingRecipe()), DatasetRelease: clone(run.GetDatasetRelease()),
		ModelRelease: clone(run.GetModelRelease()), HardwareTopology: clone(run.GetHardwareTopology()),
		Operation: operationResource(operation), CreatedAt: clone(run.GetCreateTime()),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func (GeneratedEventFactory) JobRequested(identity Identity, operation *operationv1.Operation, configurationDigest string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if operation == nil || !validSHA256Digest(configurationDigest) {
		return nil, ErrInvalidArgument
	}
	payload := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	return newEventEnvelope(identity, operationResource(operation), payload, 1, command, at)
}

func (GeneratedEventFactory) Started(identity Identity, run *trainingv1.TrainingRun, fence *jobv1.LeaseFence, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.TrainingStarted{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(),
		Fence: clone(fence), TrainingRecipe: clone(run.GetTrainingRecipe()),
		DatasetRelease: clone(run.GetDatasetRelease()), ModelRelease: clone(run.GetModelRelease()),
		ExecutablePlan: clone(run.GetExecutablePlan()), StartedAt: timestamppb.New(at),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func (GeneratedEventFactory) Progress(identity Identity, run *trainingv1.TrainingRun, progress *trainingv1.TrainingProgress, fence *jobv1.LeaseFence, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.ProgressCommitted{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(),
		Fence: clone(fence), Progress: clone(progress),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func (GeneratedEventFactory) Checkpoint(identity Identity, run *trainingv1.TrainingRun, checkpoint *trainingv1.Checkpoint, fence *jobv1.LeaseFence, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.CheckpointCommitted{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(), Fence: clone(fence),
		CheckpointName: checkpoint.GetName(), SnapshotEpoch: checkpoint.GetSnapshotEpoch(),
		CheckpointManifest:   clone(checkpoint.GetCheckpointManifest()),
		CommittedProgress:    clone(checkpoint.GetCommittedProgress()),
		VerificationEvidence: clone(checkpoint.GetVerificationEvidence()), CommittedAt: timestamppb.New(at),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func (GeneratedEventFactory) Completed(identity Identity, run *trainingv1.TrainingRun, fence *jobv1.LeaseFence, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.TrainingCompleted{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(), Fence: clone(fence),
		Classification: run.GetTerminalClassification(), ResultManifest: clone(run.GetResultManifest()),
		FinalCheckpoint: clone(run.GetLatestCheckpoint()), Error: clone(run.GetError()),
		CompletedAt: clone(run.GetCompleteTime()),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func (GeneratedEventFactory) CancellationRequested(identity Identity, run *trainingv1.TrainingRun, operation *operationv1.Operation, reason string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &trainingv1.TrainingCancellationRequested{
		TrainingRunName: run.GetName(), TrainingRunRevision: run.GetRevision(),
		Operation: operationResource(operation), Reason: reason, RequestedAt: timestamppb.New(at.UTC()),
	}
	return newEventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at)
}

func newEventEnvelope(identity Identity, subject *commonv1.ResourceRef, payloadMessage proto.Message, revision int64, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if payloadMessage == nil || subject == nil || command == nil || at.IsZero() || sequence == 0 {
		return nil, errors.New("event payload, subject, command context, sequence, and time are required")
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal training event: %w", err)
	}
	payloadDigest := sha256.Sum256(payload)
	typeName := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	eventIdentity := sha256.Sum256([]byte(typeName + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	envelope := &commonv1.EventEnvelope{
		EventId: "training:" + hex.EncodeToString(eventIdentity[:]), EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(),
		Subject: clone(subject), PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/training", AggregateSequence: sequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey:   "training:" + hex.EncodeToString(eventIdentity[:]),
		PayloadContentType: protobufEventContentType,
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if requested, ok := payloadMessage.(*jobv1.JobRequested); ok {
		envelope.JobId = requested.GetJobId()
	}
	if err := pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func runResource(run *trainingv1.TrainingRun) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{
		ResourceType: "training_run", ResourceId: resourceID(run.GetName()), TenantId: tenantIDFromName(run.GetTenantName()),
		ProjectId: projectIDFromName(run.GetProjectName()), ResourceVersion: run.GetRevision(), Name: run.GetName(), Etag: run.GetEtag(),
	}
}

func operationResource(operation *operationv1.Operation) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{
		ResourceType: "operation", ResourceId: resourceID(operation.GetOperationId()), TenantId: operation.GetTenantId(),
		ProjectId: operation.GetProjectId(), ResourceVersion: operation.GetResourceVersion(),
		Name: operation.GetOperationId(), Etag: operation.GetEtag(),
	}
}

func resourceID(name string) string {
	for index := len(name) - 1; index >= 0; index-- {
		if name[index] == '/' {
			return name[index+1:]
		}
	}
	return name
}

func tenantIDFromName(name string) string  { return resourceID(name) }
func projectIDFromName(name string) string { return resourceID(name) }

func clone[T proto.Message](value T) T {
	if any(value) == nil {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}
