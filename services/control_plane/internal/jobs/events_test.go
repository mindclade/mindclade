package jobs

import (
	"testing"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
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
	completedAttempt.ResourceVersion = 2
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
	if completed.GetEventType() != "mindclade.events.job.v1.AttemptCompleted" || completed.GetAggregateSequence() != 2 {
		t.Fatalf("completion envelope identity is not attempt-version ordered: %v", completed)
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
