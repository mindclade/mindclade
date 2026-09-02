package admin

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const protobufEventContentType = "application/x-protobuf; deterministic=true"

type GeneratedEventFactory struct{}

func (GeneratedEventFactory) TenantUpdated(identity Identity, value *adminv1.Tenant, changed []string, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	if value == nil || value.GetRevision() < 2 {
		return nil, errors.New("tenant update requires an authoritative post-provisioning revision")
	}
	payload := &adminv1.TenantUpdated{Tenant: clone(value), ChangedFields: append([]string(nil), changed...), Operation: operationResource(operation), UpdatedAt: timestamppb.New(at.UTC())}
	// Tenant provisioning is an external administrative boundary and has no
	// TenantCreated delivery in this contract. The update stream therefore
	// starts at semantic event ordinal one for resource revision two. Keep the
	// real revision on Subject while avoiding a nonexistent outbox predecessor.
	return newEvent(identity, tenantResource(identity, value), payload, value.GetRevision()-1, command, operation, at)
}

func (GeneratedEventFactory) ProjectCreated(identity Identity, value *adminv1.Project, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &adminv1.ProjectCreated{Project: clone(value), Operation: operationResource(operation), CreatedAt: timestamppb.New(at.UTC())}
	eventIdentity := identity
	eventIdentity.ProjectID = lastSegment(value.GetName())
	return newEvent(eventIdentity, projectResource(eventIdentity, value), payload, value.GetRevision(), command, operation, at)
}

func (GeneratedEventFactory) ProjectUpdated(identity Identity, value *adminv1.Project, changed []string, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &adminv1.ProjectUpdated{Project: clone(value), ChangedFields: append([]string(nil), changed...), Operation: operationResource(operation), UpdatedAt: timestamppb.New(at.UTC())}
	eventIdentity := identity
	eventIdentity.ProjectID = lastSegment(value.GetName())
	return newEvent(eventIdentity, projectResource(eventIdentity, value), payload, value.GetRevision(), command, operation, at)
}

func (GeneratedEventFactory) AuditExportRequested(identity Identity, value *adminv1.AuditExport, query *adminv1.AuditQuery, operation *jobv1.Operation, command *commonv1.CommandContext, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &adminv1.AuditExportRequested{AuditExport: clone(value), Query: clone(query), Operation: operationResource(operation), RequestedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, exportResource(identity, value), payload, value.GetRevision(), command, operation, at)
}

func (GeneratedEventFactory) AuditExportCompleted(identity Identity, value *adminv1.AuditExport, operation *jobv1.Operation, at time.Time) (*commonv1.EventEnvelope, error) {
	payload := &adminv1.AuditExportCompleted{AuditExport: clone(value), Operation: operationResource(operation), CompletedAt: timestamppb.New(at.UTC())}
	return newEvent(identity, exportResource(identity, value), payload, value.GetRevision(), nil, operation, at)
}

func newEvent(identity Identity, subject *commonv1.ResourceRef, payload proto.Message, revision int64, command *commonv1.CommandContext, operation *jobv1.Operation, at time.Time) (*commonv1.EventEnvelope, error) {
	sequence, err := numconv.Int64ToUint64(revision)
	if err != nil {
		return nil, err
	}
	if subject == nil || payload == nil || sequence == 0 || at.IsZero() {
		return nil, errors.New("admin event inputs are incomplete")
	}
	requestID, traceID, correlationID, causationID := "", "", "", ""
	if command != nil {
		requestID, traceID = command.GetRequestId(), command.GetTraceId()
		correlationID, causationID = command.GetCorrelationId(), command.GetCausationId()
	} else if operation != nil {
		requestID = operation.GetOperationId()
	}
	if requestID == "" {
		return nil, errors.New("admin event request identity is required")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(payload)
	if err != nil {
		return nil, err
	}
	payloadDigest := sha256.Sum256(encoded)
	eventType := string(payload.ProtoReflect().Descriptor().FullName())
	identityDigest := sha256.Sum256([]byte(eventType + "\x00" + subject.GetName() + "\x00" + strconv.FormatUint(sequence, 10) + "\x00" + requestID))
	id := "admin:" + hex.EncodeToString(identityDigest[:])
	envelope := &commonv1.EventEnvelope{
		EventId: id, EventType: eventType, EventVersion: 1, OccurredAt: timestamppb.New(at.UTC()), RecordedAt: timestamppb.New(at.UTC()),
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, TraceId: traceID, Subject: clone(subject),
		PayloadDigest: "sha256:" + hex.EncodeToString(payloadDigest[:]), Payload: encoded,
		Producer: "services/control_plane/internal/admin", AggregateSequence: sequence,
		RequestId: requestID, CorrelationId: correlationID, CausationId: causationID,
		DeduplicationKey: id, PayloadContentType: protobufEventContentType,
		Classification: commonv1.DataClassification_DATA_CLASSIFICATION_RESTRICTED,
	}
	if err = queue.ValidateEnvelope(envelope); err != nil {
		return nil, err
	}
	return envelope, nil
}
