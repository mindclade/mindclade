package controlplane_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func TestStaleCompletionIsRetainedButCannotAdvanceRun(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL lease-fencing branch: %v", err)
		}
	}
	repository := jobs.NewRepository()
	if err := repository.CreateJob(jobs.Job{ID: "job-1", TenantID: "tenant-a"}); err != nil {
		t.Fatal(err)
	}
	if err := repository.CreateRun(jobs.Run{ID: "run-1", TenantID: "tenant-a", JobID: "job-1"}); err != nil {
		t.Fatal(err)
	}
	first, err := repository.AcquireLease("tenant-a", "run-1", "attempt-1")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := repository.AcquireLease("tenant-a", "run-1", "attempt-2"); err != nil {
		t.Fatal(err)
	}
	if err := repository.CompleteAttempt("tenant-a", first.ID, first.LeaseEpoch, "SUCCEEDED", time.Now()); !errors.Is(err, jobs.ErrStaleCompletion) {
		t.Fatalf("expected stale completion, got %v", err)
	}
	run, err := repository.Run("tenant-a", "run-1")
	if err != nil || run.State != "EXECUTING" || len(repository.Completions()) != 1 || repository.Completions()[0].Accepted {
		t.Fatalf("stale completion advanced or disappeared: run=%#v err=%v", run, err)
	}
}
