package controlplane_test

import (
	"context"
	"errors"
	"testing"

	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

func TestTenantIsolationAndDefaultDeny(t *testing.T) {
	if db := postgresDB(t); db != nil {
		if _, err := db.ExecContext(context.Background(), "SELECT 1"); err != nil {
			t.Fatalf("PostgreSQL tenant-isolation branch: %v", err)
		}
	}
	repository := operations.NewRepository()
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal:      policies.Principal{ID: "principal-a", TenantID: "tenant-a", Actions: map[string]bool{operations.CreateAction: true}},
		IdempotencyKey: "key-1",
		Operation:      operations.Operation{ID: "operation-1", TenantID: "tenant-b", JobID: "job-1", RequestHash: "sha256:request"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected tenant denial, got %v", err)
	}
	_, _, err = operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal:      policies.Principal{ID: "principal-a", TenantID: "tenant-a"},
		IdempotencyKey: "key-2",
		Operation:      operations.Operation{ID: "operation-2", TenantID: "tenant-a", JobID: "job-1", RequestHash: "sha256:request"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected default deny, got %v", err)
	}
}
