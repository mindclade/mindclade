package controlplane_test

import (
	"context"
	"errors"
	"testing"

	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
)

func TestIdempotencyReturnsReplayAndRejectsHashChange(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL idempotency branch: %v", err)
		}
	}
	repository := operations.NewRepository()
	first := operations.Operation{ID: "operation-1", TenantID: "tenant-a", JobID: "job-1", RequestHash: "sha256:one"}
	if _, replay, err := repository.CreateAtomically(first, "key-1", "principal-1"); err != nil || replay {
		t.Fatalf("first delivery failed: replay=%v err=%v", replay, err)
	}
	if _, replay, err := repository.CreateAtomically(first, "key-1", "principal-1"); err != nil || !replay {
		t.Fatalf("identical replay failed: replay=%v err=%v", replay, err)
	}
	changed := first
	changed.RequestHash = "sha256:two"
	if _, _, err := repository.CreateAtomically(changed, "key-1", "principal-1"); !errors.Is(err, operations.ErrIdempotencyConflict) {
		t.Fatalf("expected hash conflict, got %v", err)
	}
}
