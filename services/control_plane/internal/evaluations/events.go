package evaluations

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
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) RunCreated(identity Identity, run *evaluationv1.EvaluationRun, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &evaluationv1.EvaluationRunCreated{
		EvaluationRunName: run.GetName(), EvaluationRunRevision: run.GetRevision(),
		Suite: clone(run.GetSuite()), Datasets: cloneSlice(run.GetDatasets()), Snapshot: clone(run.GetSnapshot()),
		ModelRelease: clone(run.GetModelRelease()), Operation: operationResource(operation), CreatedAt: clone(run.GetCreateTime()),
	}
	return eventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at, "evaluation")
}

func (GeneratedEventFactory) CancellationRequested(identity Identity, run *evaluationv1.EvaluationRun, operation *jobv1.Operation, reason string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &evaluationv1.EvaluationCancellationRequested{
		EvaluationRunName: run.GetName(), EvaluationRunRevision: run.GetRevision(), Reason: reason,
		Operation: operationResource(operation), RequestedAt: timestamppb.New(at.UTC()),
	}
	return eventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at, "evaluation")
}

func (GeneratedEventFactory) ResultCommitted(identity Identity, result *evaluationv1.EvaluationResult, run *evaluationv1.EvaluationRun, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &evaluationv1.EvaluationResultCommitted{
		EvaluationResultName: result.GetName(), EvaluationRunName: run.GetName(), EvaluationRunRevision: run.GetRevision(),
		Outcome: result.GetOutcome(), Report: clone(result.GetReport()), ResultDigest: result.GetResultDigest(),
		Operation: operationResource(operation), CommittedAt: timestamppb.New(at.UTC()),
	}
	return eventEnvelope(identity, runResource(run), payload, run.GetRevision(), command, at, "evaluation")
}

func (GeneratedEventFactory) PromotionRecorded(identity Identity, decision *evaluationv1.PromotionDecision, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &evaluationv1.PromotionDecisionRecorded{
		PromotionDecisionName: decision.GetName(), PromotionDecisionUid: decision.GetUid(), CandidateRelease: clone(decision.GetCandidateRelease()),
		CandidateDigest: decision.GetCandidateDigest(), Outcome: decision.GetOutcome(), DecisionDigest: decision.GetDecisionDigest(),
		Operation: operationResource(operation), RecordedAt: timestamppb.New(at.UTC()),
	}
	return eventEnvelope(identity, decisionResource(identity, decision), payload, 1, command, at, "evaluation")
}

func (GeneratedEventFactory) JobRequested(identity Identity, operation *jobv1.Operation, configurationDigest string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if operation == nil || !validSHA256(configurationDigest) {
		return nil, ErrInvalidArgument
	}
	payload := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	return eventEnvelope(identity, operationResource(operation), payload, 1, command, at, "evaluation-scheduler")
}

func eventEnvelope(identity Identity, subject *commonv1.ResourceRef, payloadMessage proto.Message, revision int64, command *commonv1.CommandContext, at time.Time, producer string) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if payloadMessage == nil || subject == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("event payload, subject, command, sequence, and time are required")
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal evaluation event: %w", err)
	}
	payloadDigest := sha256.Sum256(payload)
	eventType := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	eventIdentity := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	eventID := "evaluation:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: eventType, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(), Subject: clone(subject),
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/" + producer, AggregateSequence: sequence, JobId: jobID(payloadMessage, subject),
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: eventID, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func jobID(payload proto.Message, subject *commonv1.ResourceRef) string {
	if requested, ok := payload.(*jobv1.JobRequested); ok {
		return requested.GetJobId()
	}
	if subject.GetResourceType() == "operation" {
		return subject.GetResourceId()
	}
	return ""
}

func runResource(run *evaluationv1.EvaluationRun) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "evaluation_run", ResourceId: resourceID(run.GetName()), TenantId: run.GetTenantId(), ProjectId: run.GetProjectId(), ResourceVersion: run.GetRevision(), Name: run.GetName(), Etag: run.GetEtag()}
}

func decisionResource(identity Identity, decision *evaluationv1.PromotionDecision) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "promotion_decision", ResourceId: resourceID(decision.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: decision.GetName(), Etag: decision.GetDecisionDigest()}
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
