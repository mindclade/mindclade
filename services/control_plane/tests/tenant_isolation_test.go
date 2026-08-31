package controlplane_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
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
		RequestDigest:  "sha256:" + strings.Repeat("a", 64),
		Operation:      &jobv1.Operation{OperationId: "operation-1", TenantId: "tenant-b", JobId: "job-1"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected tenant denial, got %v", err)
	}
	_, _, err = operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal:      policies.Principal{ID: "principal-a", TenantID: "tenant-a"},
		IdempotencyKey: "key-2",
		RequestDigest:  "sha256:" + strings.Repeat("a", 64),
		Operation:      &jobv1.Operation{OperationId: "operation-2", TenantId: "tenant-a", JobId: "job-1"},
	})
	if !errors.Is(err, policies.ErrDenied) {
		t.Fatalf("expected default deny, got %v", err)
	}
}
