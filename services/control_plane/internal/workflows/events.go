package workflows

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type EventFactory interface {
	DefinitionCreated(Identity, *workflowv1.WorkflowDefinition, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	DefinitionUpdated(Identity, *workflowv1.WorkflowDefinition, int64, []string, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	RunStarted(Identity, *workflowv1.WorkflowRun, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	RunCancelled(Identity, *workflowv1.WorkflowRun, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Transitioned(Identity, *workflowv1.WorkflowRun, *workflowv1.WorkflowRun, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ApprovalRequested(Identity, *workflowv1.ApprovalRequest, time.Time) (*commonv1.EventEnvelope, error)
	ApprovalRecorded(Identity, *workflowv1.ApprovalRequest, *workflowv1.ApprovalReceipt, time.Time) (*commonv1.EventEnvelope, error)
	ApprovalConsumed(Identity, *workflowv1.ApprovalReceipt, string, uint64, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	JobRequested(Identity, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) DefinitionCreated(identity Identity, value *workflowv1.WorkflowDefinition, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.WorkflowDefinitionCreated{WorkflowDefinition: clone(value), Operation: operationResource(operation), CreatedAt: timestamppb.New(at)}
	return eventEnvelope(identity, workflowDefinitionResource(value), payload, uint64(value.GetRevision()), command, at, "workflow-control-plane") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) DefinitionUpdated(identity Identity, value *workflowv1.WorkflowDefinition, previous int64, paths []string, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.WorkflowDefinitionUpdated{WorkflowDefinition: clone(value), PreviousRevision: previous, UpdateMask: &fieldMask{Paths: append([]string(nil), paths...)}, Operation: operationResource(operation), UpdatedAt: timestamppb.New(at)}
	return eventEnvelope(identity, workflowDefinitionResource(value), payload, uint64(value.GetRevision()), command, at, "workflow-control-plane") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

// fieldMask is converted through the generated alias helper below to keep
// event construction explicit without accepting caller-owned mutable aliases.
type fieldMask = fieldmaskpb.FieldMask

func (GeneratedEventFactory) RunStarted(identity Identity, value *workflowv1.WorkflowRun, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.WorkflowRunStarted{WorkflowRun: clone(value), Operation: operationResource(operation), StartedAt: timestamppb.New(at)}
	return eventEnvelope(identity, workflowRunResource(value), payload, uint64(value.GetRevision()), command, at, "workflow-control-plane") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) RunCancelled(identity Identity, value *workflowv1.WorkflowRun, operation *jobv1.Operation, reason string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.WorkflowCancellationRequested{WorkflowRun: workflowRunResource(value), Reason: reason, Operation: operationResource(operation), RequestedAt: timestamppb.New(at)}
	return eventEnvelope(identity, workflowRunResource(value), payload, uint64(value.GetRevision()), command, at, "workflow-control-plane") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) Transitioned(identity Identity, before, after *workflowv1.WorkflowRun, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.WorkflowTransitioned{
		WorkflowRun: workflowRunResource(after), TransitionSequence: after.GetTransitionSequence(), FromState: before.GetState(), ToState: after.GetState(),
		FromNodeIds: append([]string(nil), before.GetActiveNodeIds()...), ToNodeIds: append([]string(nil), after.GetActiveNodeIds()...),
		TransitionReasonCode: "WORKER_COMMIT", AttemptId: after.GetAttemptId(), LeaseEpoch: after.GetLeaseEpoch(),
		Authorization: clone(after.GetAdmissionDecision()), TransitionEvidence: clone(after.GetDecisionLog()), TransitionedAt: timestamppb.New(at),
	}
	return eventEnvelope(identity, workflowRunResource(after), payload, after.GetTransitionSequence()+1, command, at, "workflow-worker")
}

func (GeneratedEventFactory) ApprovalRequested(identity Identity, value *workflowv1.ApprovalRequest, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.ApprovalRequested{ApprovalRequest: clone(value), RecordedAt: timestamppb.New(at)}
	return eventEnvelope(identity, approvalRequestResource(value), payload, uint64(value.GetRevision()), value.GetContext(), at, "approval-authority") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) ApprovalRecorded(identity Identity, request *workflowv1.ApprovalRequest, receipt *workflowv1.ApprovalReceipt, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.ApprovalRecorded{ApprovalRequest: approvalRequestResource(request), Receipt: clone(receipt), ResultingState: request.GetState(), RecordedAt: timestamppb.New(at)}
	return eventEnvelope(identity, approvalRequestResource(request), payload, uint64(request.GetRevision()), receipt.GetContext(), at, "approval-authority") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) ApprovalConsumed(identity Identity, receipt *workflowv1.ApprovalReceipt, callID string, sequence uint64, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &workflowv1.ApprovalConsumed{ApprovalReceipt: clone(receipt), CallId: callID, ConsumedAt: timestamppb.New(at)}
	return eventEnvelope(identity, approvalReceiptResource(identity, receipt), payload, sequence, command, at, "approval-authority")
}

func (GeneratedEventFactory) JobRequested(identity Identity, operation *jobv1.Operation, configurationDigest string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if operation == nil || !validSHA256(configurationDigest) {
		return nil, ErrInvalidArgument
	}
	payload := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	return eventEnvelope(identity, operationResource(operation), payload, 1, command, at, "workflow-scheduler")
}

func eventEnvelope(identity Identity, subject *commonv1.ResourceRef, payloadMessage proto.Message, sequence uint64, command *commonv1.CommandContext, at time.Time, producer string) (*commonv1.EventEnvelope, error) {
	if payloadMessage == nil || subject == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, ErrInvalidArgument
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventID, err := randomID("evt_")
	if err != nil {
		return nil, err
	}
	eventType := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	dedupSource := fmt.Sprintf("%s\x00%s\x00%d\x00%s", eventType, subject.GetName(), sequence, command.GetRequestId())
	dedupDigest := sha256.Sum256([]byte(dedupSource))
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: eventType, EventVersion: 1, OccurredAt: timestamppb.New(at.UTC()), TenantId: identity.TenantID,
		TraceId: command.GetTraceId(), Subject: clone(subject), PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		RecordedAt: timestamppb.New(at.UTC()), Producer: producer, ProjectId: identity.ProjectID, AggregateSequence: sequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: "sha256:" + hex.EncodeToString(dedupDigest[:]), PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func randomID(prefix string) (string, error) {
	value := make([]byte, 18)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return prefix + base64.RawURLEncoding.EncodeToString(value), nil
}

func operationResource(value *jobv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "mindclade.job.v1.Operation", ResourceId: value.GetOperationId(), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetResourceVersion(), Name: "tenants/" + value.GetTenantId() + "/projects/" + value.GetProjectId() + "/operations/" + value.GetOperationId(), Etag: value.GetEtag()}
}

func workflowDefinitionResource(value *workflowv1.WorkflowDefinition) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "mindclade.workflow.v1.WorkflowDefinition", ResourceId: value.GetUid(), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func workflowRunResource(value *workflowv1.WorkflowRun) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "mindclade.workflow.v1.WorkflowRun", ResourceId: value.GetUid(), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func approvalRequestResource(value *workflowv1.ApprovalRequest) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "mindclade.workflow.v1.ApprovalRequest", ResourceId: value.GetUid(), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func approvalReceiptResource(identity Identity, value *workflowv1.ApprovalReceipt) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "mindclade.workflow.v1.ApprovalReceipt", ResourceId: value.GetUid(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: value.GetName()}
}
