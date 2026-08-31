package controlplane_test

import (
	"context"
	"errors"
	"testing"
	"time"

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
	first, err := repository.AcquireLease("tenant-a", "run-1", "attempt-1")
	if err != nil {
		t.Fatal(err)
	}
	if _, leaseErr := repository.AcquireLease("tenant-a", "run-1", "attempt-2"); leaseErr != nil {
		t.Fatal(leaseErr)
	}
	if completionErr := repository.CompleteAttempt("tenant-a", first.GetAttemptId(), first.GetLeaseEpoch(), jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED, time.Now()); !errors.Is(completionErr, jobs.ErrStaleCompletion) {
		t.Fatalf("expected stale completion, got %v", completionErr)
	}
	run, err := repository.Run("tenant-a", "run-1")
	accepted, ok := repository.CompletionAccepted(0)
	if err != nil || run.GetState() != jobv1.RunState_RUN_STATE_EXECUTING || repository.CompletionCount() != 1 || !ok || accepted {
		t.Fatalf("stale completion advanced or disappeared: run=%#v err=%v", run, err)
	}
}
