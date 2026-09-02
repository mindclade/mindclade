package jobs

import (
	"errors"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

func TestAttemptEventsAreRegisteredDeterministicGeneratedFacts(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 12, 30, 0, 0, time.UTC)
	attempt := &jobv1.Attempt{
		AttemptId: "attempts/attempt-1", RunId: "runs/run-1", JobId: "jobs/job-1",
		TenantId: "tenant-1", ProjectId: "project-1", WorkerId: "worker-1",
		LeaseEpoch: 7, State: jobv1.AttemptState_ATTEMPT_STATE_LEASED, ResourceVersion: 1,
		LeasedAt: timestamppb.New(at), LeaseExpiresAt: timestamppb.New(at.Add(time.Minute)),
	}
	fence := leaseFence(attempt, "sha256:lease-token-digest")
	command := RunCommandMetadata{
		TenantID: "tenant-1", ProjectID: "project-1", PrincipalID: "principal-1", WorkerID: "worker-1",
		Action: actionAcquireLease, IdempotencyKey: "acquire-1", RequestDigest: "sha256:request",
		RequestID: "request-1", TraceID: "trace-1", CorrelationID: "correlation-1", CausationID: "causation-1",
		ObservedAt: at,
	}

	first, err := newAttemptLeasedEvent(attempt, fence, command, at)
	if err != nil {
		t.Fatal(err)
	}
	second, err := newAttemptLeasedEvent(attempt, fence, command, at)
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(first, second) || first.GetEventId() != second.GetEventId() {
		t.Fatal("same authoritative lease fact must produce byte-equivalent deterministic envelopes")
	}
	if first.GetEventType() != "mindclade.events.job.v1.AttemptLeased" || first.GetAggregateSequence() != 1 ||
		first.GetRequestId() != command.RequestID || first.GetTraceId() != command.TraceID ||
		first.GetCorrelationId() != command.CorrelationID || first.GetCausationId() != command.CausationID ||
		first.GetJobId() != attempt.GetJobId() || first.GetRunId() != attempt.GetRunId() {
		t.Fatalf("lease envelope lost authoritative metadata: %v", first)
	}
	decoded, err := queue.UnmarshalRegisteredPayload(first)
	if err != nil {
		t.Fatal(err)
	}
	leased, ok := decoded.(*jobv1.AttemptLeased)
	if !ok || !proto.Equal(leased.GetAttempt(), attempt) || !proto.Equal(leased.GetFence(), fence) {
		t.Fatalf("lease payload did not round-trip through the exact registry type: %T %v", decoded, decoded)
	}

	completedAttempt := proto.Clone(attempt).(*jobv1.Attempt)
	completedAttempt.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	// Renewal and heartbeat writes advance the resource revision without
	// creating immutable facts. Completion must still be semantic sequence 2.
	completedAttempt.ResourceVersion = 4
	completedAttempt.CompletedAt = timestamppb.New(at.Add(30 * time.Second))
	run := &jobv1.Run{
		RunId: attempt.GetRunId(), JobId: attempt.GetJobId(), TenantId: attempt.GetTenantId(), ProjectId: attempt.GetProjectId(),
		State: jobv1.RunState_RUN_STATE_SUCCEEDED, ResourceVersion: 3, LeaseEpoch: attempt.GetLeaseEpoch(),
		CompletedAt: cloneTimestamp(completedAttempt.GetCompletedAt()), Etag: "sha256:run-etag",
	}
	completed, err := newAttemptCompletedEvent(completedAttempt, run, leaseFence(completedAttempt, fence.GetLeaseTokenDigest()), command, at.Add(30*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if completed.GetEventType() != "mindclade.events.job.v1.AttemptCompleted" || completed.GetAggregateSequence() != 2 ||
		completed.GetSubject().GetResourceVersion() != 4 {
		t.Fatalf("completion envelope lost semantic ordering or authoritative revision: %v", completed)
	}
	decoded, err = queue.UnmarshalRegisteredPayload(completed)
	if err != nil {
		t.Fatal(err)
	}
	completion, ok := decoded.(*jobv1.AttemptCompleted)
	if !ok || !proto.Equal(completion.GetAttempt(), completedAttempt) || !proto.Equal(completion.GetRun(), run) {
		t.Fatalf("completion payload did not round-trip through the exact registry type: %T %v", decoded, decoded)
	}

	completedAttempt.WorkerId = "mutated-after-factory"
	if completion.GetAttempt().GetWorkerId() != "worker-1" {
		t.Fatal("event factory retained a mutable alias to the caller's generated message")
	}
}

func TestDomainCompletionEventsUseTypedCommandsAndExactJobKinds(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 12, 30, 0, 0, time.UTC)
	context := &commonv1.CommandContext{
		TenantId: "tenant-1", ProjectId: "project-1", PrincipalId: "principal-1", RequestId: "request-1",
		IdempotencyKey: "commit-1", TraceId: "trace-1", CorrelationId: "correlation-1", CausationId: "causation-1",
	}
	metadata := RunCommandMetadata{
		TenantID: context.GetTenantId(), ProjectID: context.GetProjectId(), PrincipalID: context.GetPrincipalId(), WorkerID: "worker-1",
		Action: actionCommitAttempt, IdempotencyKey: context.GetIdempotencyKey(), RequestDigest: "sha256:" + strings.Repeat("1", 64),
		RequestID: context.GetRequestId(), TraceID: context.GetTraceId(), CorrelationID: context.GetCorrelationId(), CausationID: context.GetCausationId(), ObservedAt: at,
	}
	output := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("2", 64), MediaType: "application/octet-stream"}
	receipt := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("3", 64), MediaType: "application/vnd.mindclade.receipt+json"}
	lineage := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("4", 64), MediaType: "application/vnd.mindclade.lineage+json"}
	attempt := &jobv1.Attempt{
		AttemptId: "attempts/attempt-1", RunId: "runs/run-1", JobId: "jobs/job-1", TenantId: context.GetTenantId(), ProjectId: context.GetProjectId(), WorkerId: metadata.WorkerID,
		LeaseEpoch: 7, State: jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED, ResourceVersion: 2, LeasedAt: timestamppb.New(at.Add(-time.Minute)), CompletedAt: timestamppb.New(at), Outputs: []*artifactv1.ArtifactRef{output},
	}
	fence := &jobv1.LeaseFence{JobId: attempt.GetJobId(), RunId: attempt.GetRunId(), AttemptId: attempt.GetAttemptId(), LeaseEpoch: attempt.GetLeaseEpoch(), Deadline: timestamppb.New(at.Add(time.Minute)), TenantId: context.GetTenantId(), ProjectId: context.GetProjectId(), LeaseTokenDigest: "sha256:" + strings.Repeat("5", 64)}
	run := &jobv1.Run{RunId: attempt.GetRunId(), JobId: attempt.GetJobId(), TenantId: context.GetTenantId(), ProjectId: context.GetProjectId(), State: jobv1.RunState_RUN_STATE_SUCCEEDED, ResourceVersion: 3, LeaseEpoch: attempt.GetLeaseEpoch(), Outputs: []*artifactv1.ArtifactRef{output}, CompletedAt: timestamppb.New(at)}
	featureCommand := &featurev1.CommitFeatureMaterializationCommand{
		Context: context, MaterializationName: "tenants/tenant-1/projects/project-1/featureMaterializations/a.b_c~d-1", Fence: fence,
		Classification: featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_SUCCEEDED,
		Receipt:        receipt, OutputRefs: []*artifactv1.ArtifactRef{output}, CompletedAt: timestamppb.New(at),
	}
	featureMutation := CompleteAttemptCommand{Credentials: LeaseCredentials{TenantID: context.GetTenantId(), ProjectID: context.GetProjectId()}, Attempt: attempt, Fence: fence, FeatureMaterialization: featureCommand, Now: at, Command: metadata}
	if err := validateDomainCompletion(featureMutation, FeatureMaterializationJobKind, attempt); err != nil {
		t.Fatalf("valid feature completion: %v", err)
	}
	if err := validateDomainCompletion(featureMutation, TransformExecutionJobKind, attempt); !errors.Is(err, ErrInvalidOutcome) {
		t.Fatalf("feature completion crossed exact job-kind boundary: %v", err)
	}
	featureCommand.Classification = featurev1.FeatureMaterializationTerminalClassification(999)
	if err := validateDomainCompletion(featureMutation, FeatureMaterializationJobKind, attempt); !errors.Is(err, ErrInvalidOutcome) {
		t.Fatalf("unknown feature classification entered the closed terminal state machine: %v", err)
	}
	featureCommand.Classification = featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_SUCCEEDED
	featureEnvelope, err := newFeatureMaterializationCompletedEvent(featureCommand, run, fence, metadata, at)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := queue.UnmarshalRegisteredPayload(featureEnvelope)
	if err != nil {
		t.Fatal(err)
	}
	featureCompleted, ok := decoded.(*featurev1.FeatureMaterializationCompleted)
	if !ok || featureCompleted.GetMaterializationName() != featureCommand.GetMaterializationName() || featureCompleted.GetMaterializationRevision() != 1 || featureEnvelope.GetAggregateSequence() != 1 ||
		!proto.Equal(featureCompleted.GetFence(), fence) || !proto.Equal(featureCompleted.GetReceipt(), receipt) || !proto.Equal(featureCompleted.GetOutputRefs()[0], output) {
		t.Fatalf("feature completion did not preserve its exact populated generated payload: %T %v", decoded, decoded)
	}

	transformCommand := &transformv1.CommitTransformExecutionCommand{
		Context: context, ExecutionName: "tenants/tenant-1/projects/project-1/transformExecutions/01", Fence: fence,
		Classification: transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SUCCEEDED,
		Receipt:        receipt, OutputRefs: []*artifactv1.ArtifactRef{output}, LineageMap: lineage, CompletedAt: timestamppb.New(at),
	}
	transformMutation := CompleteAttemptCommand{Credentials: LeaseCredentials{TenantID: context.GetTenantId(), ProjectID: context.GetProjectId()}, Attempt: attempt, Fence: fence, TransformExecution: transformCommand, Now: at, Command: metadata}
	if err = validateDomainCompletion(transformMutation, TransformExecutionJobKind, attempt); err != nil {
		t.Fatalf("valid transform completion: %v", err)
	}
	transformEnvelope, err := newTransformExecutionCompletedEvent(transformCommand, run, fence, metadata, at)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err = queue.UnmarshalRegisteredPayload(transformEnvelope)
	if err != nil {
		t.Fatal(err)
	}
	transformCompleted, ok := decoded.(*transformv1.TransformExecutionCompleted)
	if !ok || transformCompleted.GetExecutionName() != transformCommand.GetExecutionName() || transformCompleted.GetExecutionRevision() != 1 || transformEnvelope.GetAggregateSequence() != 1 ||
		!proto.Equal(transformCompleted.GetFence(), fence) || !proto.Equal(transformCompleted.GetLineageMap(), lineage) || !proto.Equal(transformCompleted.GetOutputRefs()[0], output) {
		t.Fatalf("transform completion did not preserve its exact populated generated payload: %T %v", decoded, decoded)
	}
	featureCommand.MaterializationName = "mutated"
	transformCommand.LineageMap.Digest = "mutated"
	if featureCompleted.GetMaterializationName() == "mutated" || transformCompleted.GetLineageMap().GetDigest() == "mutated" {
		t.Fatal("domain completion factory retained mutable aliases")
	}
}

func TestDomainCompletionResourceLeafLaw(t *testing.T) {
	t.Parallel()
	for _, leaf := range []string{"01", "A", "a.b_c~d-1"} {
		if !validDomainResourceName("tenant", "project", "featureMaterializations", "tenants/tenant/projects/project/featureMaterializations/"+leaf) {
			t.Fatalf("valid authoritative resource leaf rejected: %q", leaf)
		}
	}
	for _, leaf := range []string{"-leading", "_leading", ".leading", "~leading", "contains/control\n", strings.Repeat("a", 129)} {
		if validDomainResourceName("tenant", "project", "featureMaterializations", "tenants/tenant/projects/project/featureMaterializations/"+leaf) {
			t.Fatalf("invalid authoritative resource leaf accepted: %q", leaf)
		}
	}
}

func TestAttemptEventRejectsNonPositiveResourceVersion(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 12, 30, 0, 0, time.UTC)
	attempt := &jobv1.Attempt{
		AttemptId: "attempts/attempt-1", RunId: "runs/run-1", JobId: "jobs/job-1",
		TenantId: "tenant-1", ProjectId: "project-1", WorkerId: "worker-1",
		LeaseEpoch: 1, State: jobv1.AttemptState_ATTEMPT_STATE_LEASED,
		LeasedAt: timestamppb.New(at), LeaseExpiresAt: timestamppb.New(at.Add(time.Minute)),
	}
	if _, err := newAttemptLeasedEvent(attempt, leaseFence(attempt, "sha256:digest"), RunCommandMetadata{IdempotencyKey: "acquire-1"}, at); err == nil {
		t.Fatal("zero attempt resource version must not enter the ordered event stream")
	}
}

func TestJobCancellationAuditUsesStandaloneSemanticAggregate(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 13, 0, 0, 0, time.UTC)
	job := &jobv1.Job{
		JobId: "jobs/job-1", TenantId: "tenant-1", ProjectId: "project-1",
		ResourceVersion: 4, Etag: "sha256:" + strings.Repeat("a", 64),
	}
	envelope, err := newJobCancellationAuditEnvelope(job, "principal-1", at)
	if err != nil {
		t.Fatal(err)
	}
	if envelope.GetAggregateSequence() != 1 || envelope.GetSubject().GetResourceVersion() != 4 ||
		envelope.GetSubject().GetResourceType() != "job_cancellation_audit" ||
		!strings.Contains(envelope.GetSubject().GetName(), "/auditEvents/") ||
		envelope.GetSubject().GetEtag() != job.GetEtag() {
		t.Fatalf("cancellation audit conflated event sequence with job revision: %v", envelope)
	}
	if _, err = queue.UnmarshalRegisteredPayload(envelope); err != nil {
		t.Fatal(err)
	}
	if _, _, err = queue.AggregateIdentity(envelope); err != nil {
		t.Fatal(err)
	}
	if _, err = newJobCancellationAuditEnvelope(&jobv1.Job{}, "principal-1", at); !errors.Is(err, ErrInvalidJobCommand) {
		t.Fatalf("non-positive job revision error=%v", err)
	}
}
