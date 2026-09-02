package inference

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	"github.com/mindclade/mindclade/libs/go/numconv"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) Requested(identity Identity, request *inferencev1.InferenceRequest, operation *jobv1.Operation, digest string, at time.Time) (*commonv1.EventEnvelope, error) {
	if request == nil || operation == nil || !validSHA256(digest) {
		return nil, ErrInvalidArgument
	}
	inlineDigest := ""
	if inline := request.GetInlineInput(); inline != nil {
		inlineDigest = inline.GetContentDigest()
	}
	payload := &inferencev1.InferenceRequested{
		InferenceRequestName: request.GetName(), RequestDigest: digest, Mode: request.GetMode(),
		Model: clone(request.GetModel()), InputArtifact: clone(request.GetInputArtifact()),
		InlineInputDigest: inlineDigest, Operation: operationResource(operation), RequestedAt: timestamppb.New(at.UTC()),
	}
	return eventEnvelope(identity, requestResource(identity, request, digest), payload, 1, request.GetContext(), at, "inference")
}

func (GeneratedEventFactory) ResultCommitted(identity Identity, request *inferencev1.InferenceRequest, result *inferencev1.InferenceResult, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if request == nil || result == nil || operation == nil {
		return nil, ErrInvalidArgument
	}
	payload := &inferencev1.InferenceResultCommitted{
		InferenceResultName: result.GetName(), InferenceRequestName: request.GetName(), Outcome: result.GetOutcome(),
		ResultManifest: clone(result.GetResultManifest()), ResultDigest: result.GetResultDigest(),
		Operation: operationResource(operation), CommittedAt: timestamppb.New(at.UTC()),
	}
	return eventEnvelope(identity, requestResource(identity, request, result.GetRequestDigest()), payload, operation.GetResourceVersion(), command, at, "inference")
}

func (GeneratedEventFactory) JobRequested(identity Identity, operation *jobv1.Operation, configurationDigest string, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if operation == nil || !validSHA256(configurationDigest) {
		return nil, ErrInvalidArgument
	}
	payload := &jobv1.JobRequested{JobId: operation.GetJobId(), ConfigurationDigest: configurationDigest}
	return eventEnvelope(identity, operationResource(operation), payload, 1, command, at, "inference-scheduler")
}

func eventEnvelope(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, revision int64, command *commonv1.CommandContext, at time.Time, producer string) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if subject == nil || payload == nil || command == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("inference event subject, payload, command, sequence, and time are required")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshal inference event: %w", err)
	}
	payloadDigest := sha256.Sum256(encoded)
	typeName := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(typeName + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + command.GetRequestId()))
	eventID := "inference:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{
		EventId: eventID, EventType: typeName, EventVersion: 1,
		OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: command.GetTraceId(),
		Subject: clone(subject), PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		Producer: "services/control_plane/internal/" + producer, AggregateSequence: sequence,
		RequestId: command.GetRequestId(), CorrelationId: command.GetCorrelationId(), CausationId: command.GetCausationId(),
		DeduplicationKey: eventID, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_INTERNAL,
	}
	if requested, ok := payload.(*jobv1.JobRequested); ok {
		envelope.JobId = requested.GetJobId()
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}

func insertOutbox(ctx context.Context, tx sqlExecutor, event *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := queue.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	aggregateType, aggregateID, err := queue.AggregateIdentity(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages(
id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,
payload_digest,envelope_bytes,next_attempt_at,created_at
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, event.GetEventId(), event.GetTenantId(), event.GetEventType(), event.GetEventVersion(), aggregateType, aggregateID, event.GetAggregateSequence(), event.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func insertAudit(ctx context.Context, tx sqlExecutor, identity Identity, action, subject, digest string, at time.Time) error {
	event, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, subject, "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	encoded, err := queue.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO audit_events(
id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, event.GetEventId(), identity.TenantID, identity.Principal, action, subject, at.UTC(), digest, event.GetEventVersion(), event.GetPayloadDigest(), encoded)
	return err
}

type sqlExecutor interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
}
