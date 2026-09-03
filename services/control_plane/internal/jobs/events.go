package jobs

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
)

const jobEventContentType = "application/x-protobuf; deterministic=true"

func newAttemptLeasedEvent(
	attempt *jobv1.Attempt,
	fence *jobv1.LeaseFence,
	command RunCommandMetadata,
	at time.Time,
) (*commonv1.EventEnvelope, error) {
	if attempt == nil || fence == nil || attempt.GetLeasedAt() == nil || attempt.GetLeaseExpiresAt() == nil {
		return nil, errors.New("leased attempt, fence, and lease timestamps are required")
	}
	payload := &jobv1.AttemptLeased{
		Attempt:        proto.Clone(attempt).(*jobv1.Attempt),
		Fence:          proto.Clone(fence).(*jobv1.LeaseFence),
		LeasedAt:       cloneTimestamp(attempt.GetLeasedAt()),
		LeaseExpiresAt: cloneTimestamp(attempt.GetLeaseExpiresAt()),
	}
	return newAttemptEvent(attempt, payload, command, at)
}

func newAttemptCompletedEvent(
	attempt *jobv1.Attempt,
	run *jobv1.Run,
	fence *jobv1.LeaseFence,
	command RunCommandMetadata,
	at time.Time,
) (*commonv1.EventEnvelope, error) {
	if attempt == nil || run == nil || fence == nil || attempt.GetCompletedAt() == nil {
		return nil, errors.New("completed attempt, run, fence, and completion timestamp are required")
	}
	payload := &jobv1.AttemptCompleted{
		Attempt:     proto.Clone(attempt).(*jobv1.Attempt),
		Run:         proto.Clone(run).(*jobv1.Run),
		Fence:       proto.Clone(fence).(*jobv1.LeaseFence),
		CompletedAt: cloneTimestamp(attempt.GetCompletedAt()),
	}
	return newAttemptEvent(attempt, payload, command, at)
}

func newFeatureMaterializationCompletedEvent(
	command *featurev1.CommitFeatureMaterializationCommand,
	run *jobv1.Run,
	fence *jobv1.LeaseFence,
	metadata RunCommandMetadata,
	recordedAt time.Time,
) (*commonv1.EventEnvelope, error) {
	if command == nil || run == nil || fence == nil || command.GetCompletedAt() == nil {
		return nil, errors.New("feature completion command, run, fence, and timestamp are required")
	}
	payload := &featurev1.FeatureMaterializationCompleted{
		MaterializationName:     command.GetMaterializationName(),
		MaterializationRevision: 1,
		Fence:                   proto.Clone(fence).(*jobv1.LeaseFence),
		Classification:          command.GetClassification(),
		Receipt:                 cloneArtifact(command.GetReceipt()),
		OutputRefs:              cloneArtifacts(command.GetOutputRefs()),
		Error:                   cloneError(command.GetError()),
		CompletedAt:             cloneTimestamp(command.GetCompletedAt()),
	}
	return newDomainCompletionEvent(run, "feature_materialization", command.GetMaterializationName(), payload, command.GetCompletedAt().AsTime(), metadata, recordedAt)
}

func newTransformExecutionCompletedEvent(
	command *transformv1.CommitTransformExecutionCommand,
	run *jobv1.Run,
	fence *jobv1.LeaseFence,
	metadata RunCommandMetadata,
	recordedAt time.Time,
) (*commonv1.EventEnvelope, error) {
	if command == nil || run == nil || fence == nil || command.GetCompletedAt() == nil {
		return nil, errors.New("transform completion command, run, fence, and timestamp are required")
	}
	payload := &transformv1.TransformExecutionCompleted{
		ExecutionName:     command.GetExecutionName(),
		ExecutionRevision: 1,
		Fence:             proto.Clone(fence).(*jobv1.LeaseFence),
		Classification:    command.GetClassification(),
		Receipt:           cloneArtifact(command.GetReceipt()),
		OutputRefs:        cloneArtifacts(command.GetOutputRefs()),
		LineageMap:        cloneArtifact(command.GetLineageMap()),
		Error:             cloneError(command.GetError()),
		CompletedAt:       cloneTimestamp(command.GetCompletedAt()),
	}
	return newDomainCompletionEvent(run, "transform_execution", command.GetExecutionName(), payload, command.GetCompletedAt().AsTime(), metadata, recordedAt)
}

func newDomainCompletionEvent(
	run *jobv1.Run,
	resourceType string,
	resourceName string,
	payloadMessage proto.Message,
	occurredAt time.Time,
	command RunCommandMetadata,
	recordedAt time.Time,
) (*commonv1.EventEnvelope, error) {
	if run == nil || payloadMessage == nil || resourceType == "" || resourceName == "" || occurredAt.IsZero() || recordedAt.IsZero() {
		return nil, errors.New("domain completion event identity, payload, and timestamps are required")
	}
	// The typed terminal fact creates this domain aggregate. Its first durable
	// revision and outbox sequence must therefore be one; using the backing Run
	// revision would strand the event behind nonexistent domain predecessors.
	const sequence uint64 = 1
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal domain completion event: %w", err)
	}
	typeName := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	requestID := command.RequestID
	if requestID == "" {
		requestID = command.IdempotencyKey
	}
	eventIdentity := sha256.Sum256([]byte(typeName + "\x00" + resourceName + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + requestID))
	payloadDigest := sha256.Sum256(payload)
	eventID := "domain-completion:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(occurredAt.UTC()), RecordedAt: timestamppb.New(recordedAt.UTC()),
		TenantId: run.GetTenantId(), ProjectId: run.GetProjectId(), TraceId: command.TraceID,
		Subject: &commonv1.ResourceRef{
			ResourceType: resourceType, ResourceId: resourceTail(resourceName), TenantId: run.GetTenantId(),
			ProjectId: run.GetProjectId(), ResourceVersion: 1, Name: resourceName,
		},
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/jobs", AggregateSequence: sequence,
		RequestId: requestID, CorrelationId: command.CorrelationID, CausationId: command.CausationID,
		JobId: run.GetJobId(), RunId: run.GetRunId(), DeduplicationKey: eventID,
		PayloadContentType: jobEventContentType,
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func newAttemptEvent(
	attempt *jobv1.Attempt,
	payloadMessage proto.Message,
	command RunCommandMetadata,
	at time.Time,
) (*commonv1.EventEnvelope, error) {
	if attempt == nil || payloadMessage == nil || at.IsZero() {
		return nil, errors.New("attempt event value, payload, and time are required")
	}
	if attempt.GetResourceVersion() <= 0 {
		return nil, errors.New("attempt event resource version must be positive")
	}
	// Attempt resource revisions also advance for lease renewal and heartbeat
	// writes. Those control-plane mutations are deliberately not immutable
	// domain events, so using resource_version as the outbox sequence creates
	// gaps (leased=1, completed=3+) and permanently blocks completion delivery.
	// Sequence the closed semantic attempt stream instead while retaining the
	// exact resource revision on Subject for optimistic-concurrency evidence.
	var sequence uint64
	switch payloadMessage.(type) {
	case *jobv1.AttemptLeased:
		sequence = 1
	case *jobv1.AttemptCompleted:
		sequence = 2
	default:
		return nil, fmt.Errorf("unsupported attempt event payload %T", payloadMessage)
	}
	payload, err := proto.MarshalOptions{Deterministic: true}.Marshal(payloadMessage)
	if err != nil {
		return nil, fmt.Errorf("marshal attempt event: %w", err)
	}
	typeName := string(payloadMessage.ProtoReflect().Descriptor().FullName())
	requestID := command.RequestID
	if requestID == "" {
		requestID = command.IdempotencyKey
	}
	subjectName := attemptResourceName(attempt)
	eventIdentity := sha256.Sum256([]byte(typeName + "\x00" + subjectName + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + requestID))
	payloadDigest := sha256.Sum256(payload)
	eventID := "attempt:" + hex.EncodeToString(eventIdentity[:])
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: attempt.GetTenantId(), ProjectId: attempt.GetProjectId(), TraceId: command.TraceID,
		Subject: &commonv1.ResourceRef{
			ResourceType: "attempt", ResourceId: attempt.GetAttemptId(), TenantId: attempt.GetTenantId(),
			ProjectId: attempt.GetProjectId(), ResourceVersion: attempt.GetResourceVersion(), Name: subjectName,
		},
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: payload,
		Producer: "services/control_plane/internal/jobs", AggregateSequence: sequence,
		RequestId: requestID, CorrelationId: command.CorrelationID, CausationId: command.CausationID,
		JobId: attempt.GetJobId(), RunId: attempt.GetRunId(), DeduplicationKey: eventID,
		PayloadContentType: jobEventContentType,
		Classification:     commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if err = pubsubx.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func insertAttemptOutbox(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	aggregateType, aggregateID, err := pubsubx.AggregateIdentity(envelope)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`,
		envelope.GetEventId(), envelope.GetTenantId(), envelope.GetEventType(), envelope.GetEventVersion(),
		aggregateType, aggregateID, envelope.GetAggregateSequence(), envelope.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func attemptResourceName(attempt *jobv1.Attempt) string {
	return "tenants/" + attempt.GetTenantId() + "/projects/" + attempt.GetProjectId() + "/jobs/" + resourceTail(attempt.GetJobId()) +
		"/runs/" + resourceTail(attempt.GetRunId()) + "/attempts/" + resourceTail(attempt.GetAttemptId())
}

func resourceTail(value string) string {
	parts := strings.Split(strings.Trim(value, "/"), "/")
	if len(parts) == 0 {
		return ""
	}
	return parts[len(parts)-1]
}
