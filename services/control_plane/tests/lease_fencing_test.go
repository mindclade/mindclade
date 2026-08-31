package controlplane_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func TestStaleCompletionIsRetainedButCannotAdvanceRun(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL lease-fencing branch: %v", err)
		}
	}
	repository := jobs.NewRepository()
	if err := repository.CreateJob(&jobv1.Job{JobId: "job-1", TenantId: "tenant-a"}); err != nil {
		t.Fatal(err)
	}
	if err := repository.CreateRun(&jobv1.Run{RunId: "run-1", TenantId: "tenant-a", JobId: "job-1"}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	firstToken := "first-lease-token-" + strings.Repeat("a", 32)
	first, firstFence, err := repository.AcquireLease(jobs.AcquireLeaseCommand{
		TenantID: "tenant-a", RunID: "run-1", AttemptID: "attempt-1",
		WorkerID: "worker-1", Token: firstToken, Duration: jobs.MinimumLeaseDuration, Now: now,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !jobs.ValidLease(first, firstFence, "worker-1", firstToken, now.Add(time.Second)) {
		t.Fatal("fresh token-bound lease must validate")
	}
	secondToken := "second-lease-token-" + strings.Repeat("b", 32)
	if _, _, leaseErr := repository.AcquireLease(jobs.AcquireLeaseCommand{
		TenantID: "tenant-a", RunID: "run-1", AttemptID: "attempt-2",
		WorkerID: "worker-2", Token: secondToken, Duration: jobs.MinimumLeaseDuration,
		Now: now.Add(jobs.MinimumLeaseDuration + time.Second),
	}); leaseErr != nil {
		t.Fatal(leaseErr)
	}
	completion := proto.Clone(first).(*jobv1.Attempt)
	completion.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	credentials := jobs.LeaseCredentials{TenantID: "tenant-a", AttemptID: first.GetAttemptId(), WorkerID: "worker-1", Token: firstToken, Epoch: first.GetLeaseEpoch()}
	if completionErr := repository.CompleteAttempt(credentials, completion, first.GetResourceVersion(), now.Add(jobs.MinimumLeaseDuration+2*time.Second)); !errors.Is(completionErr, jobs.ErrStaleCompletion) {
		t.Fatalf("expected stale completion, got %v", completionErr)
	}
	run, err := repository.Run("tenant-a", "run-1")
	accepted, ok := repository.CompletionAccepted(0)
	if err != nil || run.GetState() != jobv1.RunState_RUN_STATE_EXECUTING || repository.CompletionCount() != 1 || !ok || accepted {
		t.Fatalf("stale completion advanced or disappeared: run=%#v err=%v", run, err)
	}
}
