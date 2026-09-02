// Package eventprojection builds a tenant-isolated, payload-minimized audit
// projection from exact-version protobuf events. It performs no external side
// effects; inbox deduplication and projection updates commit in one SQL
// transaction.
package eventprojection

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	_ "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"    // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1" // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"    // link registered event payloads
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	_ "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"    // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1" // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1" // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"    // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"  // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/job/v1"        // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/model/v1"      // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"     // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/training/v1"   // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"  // link registered event payloads
	_ "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"   // link registered event payloads
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const ConsumerName = "control-plane-event-audit-projection-v1"

var (
	ErrSequenceGap     = errors.New("event projection sequence gap")
	ErrStaleSequence   = errors.New("event projection stale sequence")
	ErrUnsupportedType = errors.New("event projection unsupported event type")
)

type semanticKind uint8

const (
	semanticFact semanticKind = iota + 1
	semanticCancellation
	semanticFailure
	semanticDecision
)

// Every descriptor-visible event is named here deliberately. Besides making
// semantic coverage reviewable, this source is the registry's consumer
// evidence. Candidate events remain understood but are not subscribed until
// producer and fixture evidence allow their registry lifecycle to become
// active.
var semanticDefinitions = map[string]semanticKind{
	"mindclade.events.admin.v1.AuditExportCompleted":                 semanticFact,
	"mindclade.events.admin.v1.AuditExportRequested":                 semanticFact,
	"mindclade.events.admin.v1.ProjectCreated":                       semanticFact,
	"mindclade.events.admin.v1.ProjectUpdated":                       semanticFact,
	"mindclade.events.admin.v1.TenantUpdated":                        semanticFact,
	"mindclade.events.agent.v1.AgentCancellationRequested":           semanticCancellation,
	"mindclade.events.agent.v1.AgentDefinitionCreated":               semanticFact,
	"mindclade.events.agent.v1.AgentDefinitionUpdated":               semanticFact,
	"mindclade.events.agent.v1.AgentRunCompleted":                    semanticDecision,
	"mindclade.events.agent.v1.AgentRunStarted":                      semanticFact,
	"mindclade.events.agent.v1.AgentStepCommitted":                   semanticFact,
	"mindclade.events.agent.v1.AgentStepDispatched":                  semanticFact,
	"mindclade.events.agent.v1.ToolReceiptCommitted":                 semanticFact,
	"mindclade.events.artifact.v1.ArtifactCommitted":                 semanticFact,
	"mindclade.events.artifact.v1.ArtifactQuarantined":               semanticFailure,
	"mindclade.events.artifact.v1.ArtifactStagingFinalized":          semanticFact,
	"mindclade.events.audit.v1.AuditEvent":                           semanticDecision,
	"mindclade.events.audit.v1.SecurityEvent":                        semanticFailure,
	"mindclade.events.dataset.v1.DatasetCreated":                     semanticFact,
	"mindclade.events.dataset.v1.DatasetReleasePublished":            semanticFact,
	"mindclade.events.dataset.v1.DatasetReleaseRevoked":              semanticDecision,
	"mindclade.events.dataset.v1.DatasetUpdated":                     semanticFact,
	"mindclade.events.evaluation.v1.EvaluationCancellationRequested": semanticCancellation,
	"mindclade.events.evaluation.v1.EvaluationResultCommitted":       semanticDecision,
	"mindclade.events.evaluation.v1.EvaluationRunCreated":            semanticFact,
	"mindclade.events.evaluation.v1.PromotionDecisionRecorded":       semanticDecision,
	"mindclade.events.experiment.v1.ExperimentCreated":               semanticFact,
	"mindclade.events.experiment.v1.ExperimentStateChanged":          semanticDecision,
	"mindclade.events.experiment.v1.ExperimentUpdated":               semanticFact,
	"mindclade.events.experiment.v1.StudyCreated":                    semanticFact,
	"mindclade.events.experiment.v1.StudyStateChanged":               semanticDecision,
	"mindclade.events.experiment.v1.TrialCompleted":                  semanticDecision,
	"mindclade.events.experiment.v1.TrialCreated":                    semanticFact,
	"mindclade.events.experiment.v1.TrialStateChanged":               semanticDecision,
	"mindclade.events.feature.v1.FeatureMaterializationCompleted":    semanticDecision,
	"mindclade.events.inference.v1.InferenceRequested":               semanticFact,
	"mindclade.events.inference.v1.InferenceResultCommitted":         semanticDecision,
	"mindclade.events.job.v1.AttemptCompleted":                       semanticDecision,
	"mindclade.events.job.v1.AttemptLeased":                          semanticFact,
	"mindclade.events.job.v1.JobRequested":                           semanticFact,
	"mindclade.events.model.v1.ModelPromoted":                        semanticFact,
	"mindclade.events.model.v1.ModelRegistered":                      semanticFact,
	"mindclade.events.model.v1.ModelReleaseRegistered":               semanticFact,
	"mindclade.events.model.v1.ModelRevoked":                         semanticDecision,
	"mindclade.events.policy.v1.AuthorizationDecisionRecorded":       semanticDecision,
	"mindclade.events.policy.v1.UsePolicyActivated":                  semanticFact,
	"mindclade.events.policy.v1.UsePolicyCreated":                    semanticFact,
	"mindclade.events.policy.v1.UsePolicyRevoked":                    semanticDecision,
	"mindclade.events.policy.v1.UsePolicyUpdated":                    semanticFact,
	"mindclade.events.training.v1.CheckpointCommitted":               semanticFact,
	"mindclade.events.training.v1.ProgressCommitted":                 semanticFact,
	"mindclade.events.training.v1.TrainingCancellationRequested":     semanticCancellation,
	"mindclade.events.training.v1.TrainingCompleted":                 semanticDecision,
	"mindclade.events.training.v1.TrainingRunCreated":                semanticFact,
	"mindclade.events.training.v1.TrainingStarted":                   semanticFact,
	"mindclade.events.transform.v1.TransformExecutionCompleted":      semanticDecision,
	"mindclade.events.workflow.v1.ApprovalConsumed":                  semanticFact,
	"mindclade.events.workflow.v1.ApprovalRecorded":                  semanticDecision,
	"mindclade.events.workflow.v1.ApprovalRequested":                 semanticFact,
	"mindclade.events.workflow.v1.WorkflowCancellationRequested":     semanticCancellation,
	"mindclade.events.workflow.v1.WorkflowDefinitionCreated":         semanticFact,
	"mindclade.events.workflow.v1.WorkflowDefinitionUpdated":         semanticFact,
	"mindclade.events.workflow.v1.WorkflowRunStarted":                semanticFact,
	"mindclade.events.workflow.v1.WorkflowTransitioned":              semanticDecision,
}

// AcceptedEvents returns a defensive copy of the exact-version allowlist for
// events whose registry lifecycle is active. An understood candidate is not a
// production subscription authorization.
func AcceptedEvents() (map[string]uint32, error) {
	accepted := make(map[string]uint32, len(semanticDefinitions))
	for fullName := range semanticDefinitions {
		registration, ok := queue.RegisteredEvent(fullName, 1)
		if !ok {
			return nil, fmt.Errorf("%w: %s@1 is absent from the authoritative registry", ErrUnsupportedType, fullName)
		}
		if registration.LifecycleState == "active" {
			accepted[fullName] = registration.Version
		}
	}
	if len(accepted) == 0 {
		return nil, errors.New("event projection has no active registered events")
	}
	return accepted, nil
}

// Handler implements inbox.TransactionalHandler without importing the inbox
// package. The interface is satisfied structurally and avoids a platform-layer
// dependency cycle.
type Handler struct {
	Now func() time.Time
}

func (h Handler) HandleEvent(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, payload proto.Message) error {
	if tx == nil || envelope == nil || payload == nil {
		return errors.New("event projection requires transaction, envelope, and payload")
	}
	authoritative, err := queue.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		return err
	}
	if !proto.Equal(authoritative, payload) || string(payload.ProtoReflect().Descriptor().FullName()) != envelope.GetEventType() {
		return fmt.Errorf("%w: handler payload does not match the authoritative envelope", queue.ErrInvalidEnvelope)
	}
	kind, ok := semanticDefinitions[envelope.GetEventType()]
	if !ok {
		return fmt.Errorf("%w: %s", ErrUnsupportedType, envelope.GetEventType())
	}
	registration, registered := queue.RegisteredEvent(envelope.GetEventType(), envelope.GetEventVersion())
	if !registered || registration.LifecycleState != "active" {
		return fmt.Errorf("%w: %s@%d is not active", ErrUnsupportedType, envelope.GetEventType(), envelope.GetEventVersion())
	}
	if err = validateProjectionEnvelope(envelope); err != nil {
		return err
	}
	aggregateType, aggregateID, err := projectionAggregateIdentity(envelope)
	if err != nil {
		return err
	}
	if err = validateSequence(ctx, tx, envelope, aggregateType, aggregateID); err != nil {
		return err
	}

	var resourceID sql.NullInt64
	if envelope.GetSubject().GetName() != "" {
		resourceID, err = platformdb.StoreResourceRef(ctx, tx, envelope.GetTenantId(), envelope.GetSubject())
		if err != nil {
			return err
		}
	}
	fact := deriveFact(envelope, authoritative, kind)
	if err = validateSemanticFact(fact); err != nil {
		return err
	}
	// received_at is the consumer's observed wall clock. It may precede the
	// producer's recorded_at under bounded cross-host skew and is never used for
	// ordering; aggregate_sequence is the sole ordering authority.
	receivedAt := time.Now().UTC()
	if h.Now != nil {
		receivedAt = h.Now().UTC()
	}
	if receivedAt.IsZero() {
		return errors.New("event projection received time is required")
	}
	result, err := tx.ExecContext(ctx, `
INSERT INTO event_audit_projection (
  tenant_id,consumer,event_id,project_id,event_type,event_version,occurred_at,recorded_at,received_at,
  producer,subject_resource_type,subject_resource_id,subject_name,resource_ref_id,aggregate_type,aggregate_id,
  aggregate_sequence,semantic_action,semantic_outcome,audit_result,actor_principal_ref,reason_code,
  request_id,trace_id,correlation_id,causation_id,job_id,run_id,payload_digest,payload_content_type,classification
) VALUES (
  $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31
)`, envelope.GetTenantId(), ConsumerName, envelope.GetEventId(), envelope.GetProjectId(), envelope.GetEventType(), envelope.GetEventVersion(),
		envelope.GetOccurredAt().AsTime().UTC(), envelope.GetRecordedAt().AsTime().UTC(), receivedAt, envelope.GetProducer(),
		envelope.GetSubject().GetResourceType(), envelope.GetSubject().GetResourceId(), envelope.GetSubject().GetName(), resourceID, aggregateType, aggregateID,
		envelope.GetAggregateSequence(), fact.action, fact.outcome, int32(fact.result), fact.actor, fact.reason,
		envelope.GetRequestId(), envelope.GetTraceId(), envelope.GetCorrelationId(), envelope.GetCausationId(), envelope.GetJobId(), envelope.GetRunId(),
		envelope.GetPayloadDigest(), envelope.GetPayloadContentType(), int32(envelope.GetClassification()))
	if err != nil {
		return fmt.Errorf("insert event audit projection: %w", err)
	}
	if count, countErr := result.RowsAffected(); countErr != nil || count != 1 {
		if countErr != nil {
			return countErr
		}
		return errors.New("event audit projection insert did not affect exactly one row")
	}

	if err = advanceSequence(ctx, tx, envelope, aggregateType, aggregateID, receivedAt); err != nil {
		return err
	}
	beforeRevision, afterRevision := projectedRevisions(envelope)
	_, err = tx.ExecContext(ctx, `
INSERT INTO administrative_audit_records (
  tenant_id,event_id,project_id,occurred_at,actor_principal_ref,action,resource_ref_id,
  before_revision,after_revision,policy_reason_code,result,failure_class,request_id,trace_id,detail_digest
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
ON CONFLICT (tenant_id,event_id) DO NOTHING`, envelope.GetTenantId(), envelope.GetEventId(), envelope.GetProjectId(),
		envelope.GetOccurredAt().AsTime().UTC(), fact.actor, fact.action, resourceID, beforeRevision, afterRevision,
		fact.reason, int32(fact.result), fact.failureClass, envelope.GetRequestId(), envelope.GetTraceId(), envelope.GetPayloadDigest())
	if err != nil {
		return fmt.Errorf("insert administrative event audit record: %w", err)
	}
	return nil
}

func validateProjectionEnvelope(envelope *commonv1.EventEnvelope) error {
	if envelope.GetAggregateSequence() > uint64(1<<63-1) {
		return fmt.Errorf("%w: aggregate sequence exceeds PostgreSQL bigint", queue.ErrInvalidEnvelope)
	}
	if envelope.GetRecordedAt().AsTime().Before(envelope.GetOccurredAt().AsTime()) {
		return fmt.Errorf("%w: recorded time precedes occurrence time", queue.ErrInvalidEnvelope)
	}
	limits := []struct {
		name  string
		value string
		limit int
	}{
		{"event_id", envelope.GetEventId(), 512},
		{"event_type", envelope.GetEventType(), 255},
		{"project_id", envelope.GetProjectId(), 255},
		{"producer", envelope.GetProducer(), 255},
		{"subject_resource_type", envelope.GetSubject().GetResourceType(), 255},
		{"subject_resource_id", envelope.GetSubject().GetResourceId(), 1024},
		{"subject_name", envelope.GetSubject().GetName(), 2048},
		{"request_id", envelope.GetRequestId(), 512},
		{"trace_id", envelope.GetTraceId(), 512},
		{"correlation_id", envelope.GetCorrelationId(), 512},
		{"causation_id", envelope.GetCausationId(), 512},
		{"job_id", envelope.GetJobId(), 512},
		{"run_id", envelope.GetRunId(), 512},
	}
	for _, item := range limits {
		if len(item.value) > item.limit || strings.ContainsRune(item.value, '\x00') {
			return fmt.Errorf("%w: %s exceeds its storage boundary", queue.ErrInvalidEnvelope, item.name)
		}
	}
	if classification := envelope.GetClassification(); classification < commonv1.DataClassification_DATA_CLASSIFICATION_PUBLIC || classification > commonv1.DataClassification_DATA_CLASSIFICATION_RESTRICTED {
		return fmt.Errorf("%w: classification is outside the registered storage domain", queue.ErrInvalidEnvelope)
	}
	return nil
}

func validateSemanticFact(fact semanticFactValue) error {
	values := []struct {
		name     string
		value    string
		limit    int
		required bool
	}{
		{name: "semantic_action", value: fact.action, limit: 512, required: true},
		{name: "semantic_outcome", value: fact.outcome, limit: 255, required: true},
		{name: "actor_principal_ref", value: fact.actor, limit: 512, required: true},
		{name: "reason_code", value: fact.reason, limit: 255},
		{name: "failure_class", value: fact.failureClass, limit: 255},
	}
	for _, value := range values {
		if (value.required && value.value == "") || len(value.value) > value.limit || strings.ContainsRune(value.value, '\x00') {
			return fmt.Errorf("%w: %s is outside its storage boundary", queue.ErrInvalidEnvelope, value.name)
		}
	}
	return nil
}

func validateSequence(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, aggregateType, aggregateID string) error {
	// Pub/Sub ordering keys serialize normal delivery, but replay, redelivery,
	// and operator tooling can still race the first retained event for an
	// aggregate. Lock the logical identity before observing or creating its
	// head so two transactions cannot independently choose a baseline. The
	// length-prefixed material is unambiguous and PostgreSQL keeps the advisory
	// lock transaction-scoped, including error rollback.
	lockIdentity := fmt.Sprintf("%d:%s:%d:%s:%d:%s", len(envelope.GetTenantId()), envelope.GetTenantId(), len(aggregateType), aggregateType, len(aggregateID), aggregateID)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lockIdentity); err != nil {
		return fmt.Errorf("lock event projection aggregate identity: %w", err)
	}
	var lastSequence uint64
	err := tx.QueryRowContext(ctx, `
SELECT last_sequence
FROM event_audit_projection_heads
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3
FOR UPDATE`, envelope.GetTenantId(), aggregateType, aggregateID).Scan(&lastSequence)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("lock event projection aggregate head: %w", err)
	}
	if envelope.GetAggregateSequence() <= lastSequence {
		return fmt.Errorf("%w: aggregate %s/%s received %d after %d", ErrStaleSequence, aggregateType, aggregateID, envelope.GetAggregateSequence(), lastSequence)
	}
	if envelope.GetAggregateSequence() != lastSequence+1 {
		return fmt.Errorf("%w: aggregate %s/%s expected %d, received %d", ErrSequenceGap, aggregateType, aggregateID, lastSequence+1, envelope.GetAggregateSequence())
	}
	return nil
}

func advanceSequence(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, aggregateType, aggregateID string, at time.Time) error {
	result, err := tx.ExecContext(ctx, `
UPDATE event_audit_projection_heads
SET last_sequence=$4,last_event_id=$5,last_occurred_at=$6,updated_at=$7
WHERE tenant_id=$1 AND aggregate_type=$2 AND aggregate_id=$3`, envelope.GetTenantId(), aggregateType, aggregateID,
		envelope.GetAggregateSequence(), envelope.GetEventId(), envelope.GetOccurredAt().AsTime().UTC(), at)
	if err != nil {
		return fmt.Errorf("advance event projection aggregate head: %w", err)
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count == 1 {
		return nil
	}
	if count != 0 {
		return errors.New("event projection aggregate head update affected an invalid row count")
	}
	_, err = tx.ExecContext(ctx, `
INSERT INTO event_audit_projection_heads (
  tenant_id,aggregate_type,aggregate_id,baseline_sequence,last_sequence,last_event_id,last_occurred_at,updated_at
) VALUES ($1,$2,$3,$4,$4,$5,$6,$7)`, envelope.GetTenantId(), aggregateType, aggregateID,
		envelope.GetAggregateSequence(), envelope.GetEventId(), envelope.GetOccurredAt().AsTime().UTC(), at)
	if err != nil {
		return fmt.Errorf("create event projection aggregate head: %w", err)
	}
	return nil
}

func projectionAggregateIdentity(envelope *commonv1.EventEnvelope) (string, string, error) {
	aggregateType, aggregateID, err := queue.AggregateIdentity(envelope)
	if err != nil {
		return "", "", err
	}
	// Foundation audit records are independently immutable facts rather than
	// revisions of the resource they mention; their envelope sequence is one by
	// construction. Give each audit fact its own projection aggregate so two
	// actions concerning the same subject cannot collide.
	if strings.HasPrefix(envelope.GetEventType(), "mindclade.events.audit.v1.") {
		return envelope.GetEventType(), envelope.GetEventId(), nil
	}
	return aggregateType, aggregateID, nil
}

type semanticFactValue struct {
	action       string
	outcome      string
	actor        string
	reason       string
	failureClass string
	result       adminv1.AuditActionResult
}

func deriveFact(envelope *commonv1.EventEnvelope, payload proto.Message, kind semanticKind) semanticFactValue {
	action := envelope.GetEventType()
	actor := firstString(
		payload.ProtoReflect(), 0,
		"actor_principal_id", "approver_principal_ref", "requested_by_principal_ref",
		"decided_by_principal_ref", "principal_ref", "principal_id",
	)
	reason := firstString(payload.ProtoReflect(), 0, "reason_code", "transition_reason_code")
	outcome := firstEnum(payload.ProtoReflect(), 0, "outcome", "resulting_state", "decision", "state", "classification")
	if event := payload.ProtoReflect(); event.Descriptor().FullName() == "mindclade.events.audit.v1.AuditEvent" {
		if value := firstString(event, 0, "action"); value != "" {
			action = value
		}
		if value := firstString(event, 0, "decision"); value != "" {
			outcome = strings.ToUpper(value)
		}
	}
	if actor == "" {
		actor = "service://" + envelope.GetProducer()
	}
	if outcome == "" {
		switch kind {
		case semanticCancellation:
			outcome = "CANCELLATION_REQUESTED"
		case semanticFailure:
			outcome = "FAILED"
		case semanticDecision:
			outcome = "RECORDED"
		default:
			outcome = "SUCCEEDED"
		}
	}
	result := adminv1.AuditActionResult_AUDIT_ACTION_RESULT_SUCCEEDED
	upperOutcome := strings.ToUpper(outcome)
	switch {
	case strings.Contains(upperOutcome, "CANCEL"):
		result = adminv1.AuditActionResult_AUDIT_ACTION_RESULT_CANCELLED
	case strings.Contains(upperOutcome, "DENY"), strings.Contains(upperOutcome, "REJECT"), strings.Contains(upperOutcome, "REVOK"):
		result = adminv1.AuditActionResult_AUDIT_ACTION_RESULT_DENIED
	case kind == semanticFailure,
		strings.Contains(upperOutcome, "FAIL"), strings.Contains(upperOutcome, "ERROR"),
		strings.Contains(upperOutcome, "QUARANTIN"), strings.Contains(upperOutcome, "TIMED_OUT"),
		strings.Contains(upperOutcome, "STALE_FENCE"):
		result = adminv1.AuditActionResult_AUDIT_ACTION_RESULT_FAILED
	}
	failureClass := ""
	if result == adminv1.AuditActionResult_AUDIT_ACTION_RESULT_FAILED {
		failureClass = outcome
	}
	return semanticFactValue{action: action, outcome: outcome, actor: actor, reason: reason, failureClass: failureClass, result: result}
}

func firstString(message protoreflect.Message, depth int, names ...protoreflect.Name) string {
	if depth > 4 || !message.IsValid() {
		return ""
	}
	for _, name := range names {
		if field := message.Descriptor().Fields().ByName(name); field != nil && field.Kind() == protoreflect.StringKind && message.Has(field) {
			if value := message.Get(field).String(); value != "" {
				return value
			}
		}
	}
	fields := message.Descriptor().Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if field.IsList() || field.IsMap() || field.Kind() != protoreflect.MessageKind || !message.Has(field) {
			continue
		}
		if value := firstString(message.Get(field).Message(), depth+1, names...); value != "" {
			return value
		}
	}
	return ""
}

func firstEnum(message protoreflect.Message, depth int, names ...protoreflect.Name) string {
	if depth > 4 || !message.IsValid() {
		return ""
	}
	for _, name := range names {
		if field := message.Descriptor().Fields().ByName(name); field != nil && field.Kind() == protoreflect.EnumKind && message.Has(field) {
			if value := field.Enum().Values().ByNumber(message.Get(field).Enum()); value != nil && value.Number() != 0 {
				return string(value.Name())
			}
		}
	}
	fields := message.Descriptor().Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if field.IsList() || field.IsMap() || field.Kind() != protoreflect.MessageKind || !message.Has(field) {
			continue
		}
		if value := firstEnum(message.Get(field).Message(), depth+1, names...); value != "" {
			return value
		}
	}
	return ""
}

func projectedRevisions(envelope *commonv1.EventEnvelope) (string, string) {
	after := envelope.GetSubject().GetResourceVersion()
	if after <= 0 {
		return "", strconv.FormatUint(envelope.GetAggregateSequence(), 10)
	}
	before := ""
	if after > 1 {
		before = strconv.FormatInt(after-1, 10)
	}
	return before, strconv.FormatInt(after, 10)
}
