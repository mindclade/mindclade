package controlplane_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
)

func TestIdempotencyReturnsReplayAndRejectsHashChange(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL idempotency branch: %v", err)
		}
	}
	repository := operations.NewRepository()
	first := &jobv1.Operation{OperationId: "operation-1", TenantId: "tenant-a", JobId: "job-1"}
	firstDigest := "sha256:" + strings.Repeat("1", 64)
	if _, replay, err := repository.CreateAtomically(first, firstDigest, "key-1", "principal-1"); err != nil || replay {
		t.Fatalf("first delivery failed: replay=%v err=%v", replay, err)
	}
	if _, replay, err := repository.CreateAtomically(first, firstDigest, "key-1", "principal-1"); err != nil || !replay {
		t.Fatalf("identical replay failed: replay=%v err=%v", replay, err)
	}
	changedDigest := "sha256:" + strings.Repeat("2", 64)
	if _, _, err := repository.CreateAtomically(first, changedDigest, "key-1", "principal-1"); !errors.Is(err, operations.ErrIdempotencyConflict) {
		t.Fatalf("expected hash conflict, got %v", err)
	}
}
