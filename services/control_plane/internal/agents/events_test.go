package agents

import (
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/pubsubx"
	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

func TestAgentStepDispatchedIsPopulatedFencedRegisteredFact(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 14, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1", WorkerID: "worker-A", LeaseToken: strings.Repeat("lease-token-", 4)}
	step := &agentv1.AgentStep{
		Name: "tenants/tenant-1/projects/project-1/agentRuns/run-1/agentSteps/1", Uid: "step-1", Sequence: 1, Revision: 1,
		Etag: "step-etag", Kind: agentv1.AgentStepKind_AGENT_STEP_KIND_TOOL, State: agentv1.AgentStepState_AGENT_STEP_STATE_DISPATCHED,
		AttemptId: "attempts/attempt-1", LeaseEpoch: 7, CreateTime: timestamppb.New(at), UpdateTime: timestamppb.New(at),
	}
	fence := &jobv1.LeaseFence{
		JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: step.GetAttemptId(), LeaseEpoch: step.GetLeaseEpoch(),
		Deadline: timestamppb.New(at.Add(time.Minute)), TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		LeaseTokenDigest: "sha256:" + strings.Repeat("a", 64),
	}
	command := &commonv1.CommandContext{
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
		RequestId: "request-1", IdempotencyKey: "step-1", TraceId: "trace-1", CorrelationId: "correlation-1", CausationId: "causation-1",
	}
	first, err := (GeneratedEventFactory{}).AgentStepDispatched(identity, step, fence, command, at)
	if err != nil {
		t.Fatal(err)
	}
	second, err := (GeneratedEventFactory{}).AgentStepDispatched(identity, step, fence, command, at)
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(first, second) || first.GetEventType() != "mindclade.events.agent.v1.AgentStepDispatched" || first.GetAggregateSequence() != 1 {
		t.Fatalf("dispatch envelope is not deterministic and revision ordered: %v", first)
	}
	decoded, err := pubsubx.UnmarshalRegisteredPayload(first)
	if err != nil {
		t.Fatal(err)
	}
	dispatched, ok := decoded.(*agentv1.AgentStepDispatched)
	if !ok || !proto.Equal(dispatched.GetStep(), step) || dispatched.GetAttemptId() != fence.GetAttemptId() || dispatched.GetLeaseEpoch() != fence.GetLeaseEpoch() ||
		dispatched.GetWorkerProfile().GetResourceId() != identity.WorkerID || dispatched.GetWorkerProfile().GetName() != projectParent(identity)+"/workerProfiles/"+identity.WorkerID ||
		!proto.Equal(dispatched.GetDispatchDeadline(), fence.GetDeadline()) {
		t.Fatalf("dispatch event lost fenced execution authority: %T %v", decoded, decoded)
	}
	step.Uid = "caller-mutated"
	fence.Deadline = timestamppb.New(at.Add(2 * time.Minute))
	if dispatched.GetStep().GetUid() == "caller-mutated" || proto.Equal(dispatched.GetDispatchDeadline(), fence.GetDeadline()) {
		t.Fatal("dispatch event retained mutable caller aliases")
	}
}

func TestAgentStepDispatchedRejectsMismatchedFence(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, time.September, 2, 14, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1", WorkerID: "worker-1", LeaseToken: strings.Repeat("lease-token-", 4)}
	step := &agentv1.AgentStep{Name: "steps/1", Revision: 1, State: agentv1.AgentStepState_AGENT_STEP_STATE_DISPATCHED, AttemptId: "attempts/attempt-1", LeaseEpoch: 7}
	fence := &jobv1.LeaseFence{JobId: "jobs/job-1", RunId: "runs/run-1", AttemptId: "attempts/other", LeaseEpoch: 7, Deadline: timestamppb.New(at.Add(time.Minute)), TenantId: identity.TenantID, ProjectId: identity.ProjectID, LeaseTokenDigest: "sha256:" + strings.Repeat("a", 64)}
	if _, err := (GeneratedEventFactory{}).AgentStepDispatched(identity, step, fence, &commonv1.CommandContext{RequestId: "request-1"}, at); err == nil {
		t.Fatal("mismatched attempt fence produced a dispatch event")
	}
}
