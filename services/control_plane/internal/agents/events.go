package agents

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type EventFactory interface {
	DefinitionCreated(Identity, *agentv1.AgentDefinition, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	DefinitionUpdated(Identity, *agentv1.AgentDefinition, int64, []string, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	RunStarted(Identity, *agentv1.AgentRun, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	CancellationRequested(Identity, *agentv1.AgentRun, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	StepCommitted(Identity, *agentv1.AgentStep, *agentv1.AgentRun, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	RunCompleted(Identity, *agentv1.AgentRun, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ToolReceiptCommitted(Identity, *agentv1.ToolReceipt, uint64, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	JobRequested(Identity, *jobv1.Operation, string, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) DefinitionCreated(identity Identity, definition *agentv1.AgentDefinition, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentDefinitionCreated{AgentDefinition: clone(definition), Operation: operationResource(operation), CreatedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, definitionResource(definition), payload, uint64(definition.GetRevision()), command, at, "agent") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) DefinitionUpdated(identity Identity, definition *agentv1.AgentDefinition, previous int64, paths []string, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentDefinitionUpdated{AgentDefinition: clone(definition), PreviousRevision: previous, UpdateMask: &fieldmaskpb.FieldMask{Paths: append([]string(nil), paths...)}, Operation: operationResource(operation), UpdatedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, definitionResource(definition), payload, uint64(definition.GetRevision()), command, at, "agent") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) RunStarted(identity Identity, run *agentv1.AgentRun, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentRunStarted{AgentRun: clone(run), Operation: operationResource(operation), StartedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, runResource(run), payload, uint64(run.GetRevision()), command, at, "agent") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) CancellationRequested(identity Identity, run *agentv1.AgentRun, operation *jobv1.Operation, reason string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentCancellationRequested{AgentRun: runResource(run), Reason: reason, Operation: operationResource(operation), RequestedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, runResource(run), payload, uint64(run.GetRevision()), command, at, "agent") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) StepCommitted(identity Identity, step *agentv1.AgentStep, run *agentv1.AgentRun, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentStepCommitted{AgentStep: clone(step), AgentRun: runResource(run), CommittedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, stepResource(identity, step), payload, uint64(step.GetRevision()), command, at, "agent-worker") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) RunCompleted(identity Identity, run *agentv1.AgentRun, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.AgentRunCompleted{Run: clone(run), RunManifest: clone(run.GetRunManifest()), AttemptId: run.GetAttemptId(), LeaseEpoch: run.GetLeaseEpoch(), CompletedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, runResource(run), payload, uint64(run.GetRevision()), command, at, "agent-worker") //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
}

func (GeneratedEventFactory) ToolReceiptCommitted(identity Identity, receipt *agentv1.ToolReceipt, sequence uint64, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &agentv1.ToolReceiptCommitted{Receipt: clone(receipt), RunReceiptSequence: sequence, CommittedAt: timestamppb.New(at.UTC())}
	return eventEnvelope(identity, toolReceiptResource(identity, receipt), payload, 1, command, at, "agent-worker")
}

func (GeneratedEventFactory) JobRequested(identity Identity, operation *jobv1.Operation, configurationDigest string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if operation == nil || !validSHA256(configurationDigest) {
		return nil, ErrInvalidArgument
	}
	payload := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	return eventEnvelope(identity, operationResource(operation), payload, 1, command, at, "agent-scheduler")
}

func eventEnvelope(identity Identity, subject *commonv1.ResourceRef, payloadMessage proto.Message, sequence uint64, command *commonv1.CommandContext, at time.Time, producer string) (*commonv1.EventEnvelope, error) {
	if payloadMessage == nil || subject == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("event payload, subject, command, sequence, and time are required")
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal agent event: %w", err)
	}
	payloadDigest := sha256.Sum256(payload)
	eventType := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	eventIdentity := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	eventID := "agent:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: eventType, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(), Subject: clone(subject),
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/" + producer, AggregateSequence: sequence, JobId: eventJobID(payloadMessage, subject),
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: eventID, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func eventJobID(payload proto.Message, subject *commonv1.ResourceRef) string {
	if requested, ok := payload.(*jobv1.JobRequested); ok {
		return requested.GetJobId()
	}
	if subject.GetResourceType() == "operation" {
		return subject.GetResourceId()
	}
	return ""
}

func definitionResource(value *agentv1.AgentDefinition) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "agent_definition", ResourceId: resourceID(value.GetName()), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func runResource(value *agentv1.AgentRun) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "agent_run", ResourceId: resourceID(value.GetName()), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func stepResource(identity Identity, value *agentv1.AgentStep) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "agent_step", ResourceId: resourceID(value.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func toolReceiptResource(identity Identity, value *agentv1.ToolReceipt) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "tool_receipt", ResourceId: resourceID(value.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: value.GetName(), Etag: value.GetReceiptDigest()}
}

func operationResource(operation *jobv1.Operation) *commonv1.ResourceRef {
	if operation == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "operation", ResourceId: resourceID(operation.GetOperationId()), TenantId: operation.GetTenantId(), ProjectId: operation.GetProjectId(), ResourceVersion: operation.GetResourceVersion(), Name: operation.GetOperationId(), Etag: operation.GetEtag()}
}

func resourceID(name string) string {
	for index := len(name) - 1; index >= 0; index-- {
		if name[index] == '/' {
			return name[index+1:]
		}
	}
	return name
}
