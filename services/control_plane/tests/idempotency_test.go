package controlplane_test

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/mindclade/mindclade/libs/go/pubsubx"
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
	first := &jobv1.Operation{OperationId: "operation-1", TenantId: "tenant-a", ProjectId: "project-a", JobId: "job-1", Etag: "operation-etag-1"}
	firstDigest := "sha256:" + strings.Repeat("1", 64)
	configurationDigest := "sha256:" + strings.Repeat("c", 64)
	if _, replay, err := repository.CreateAtomically(first, firstDigest, configurationDigest, "key-1", "principal-1"); err != nil || replay {
		t.Fatalf("first delivery failed: replay=%v err=%v", replay, err)
	}
	if _, replay, err := repository.CreateAtomically(first, firstDigest, configurationDigest, "key-1", "principal-1"); err != nil || !replay {
		t.Fatalf("identical replay failed: replay=%v err=%v", replay, err)
	}
	changedDigest := "sha256:" + strings.Repeat("2", 64)
	if _, _, err := repository.CreateAtomically(first, changedDigest, configurationDigest, "key-1", "principal-1"); !errors.Is(err, operations.ErrIdempotencyConflict) {
		t.Fatalf("expected hash conflict, got %v", err)
	}
}

func TestOperationRepositoryScopesAliasesAndConditionalAdvances(t *testing.T) {
	repository := operations.NewRepository()
	digest := "sha256:" + strings.Repeat("1", 64)
	configurationDigest := "sha256:" + strings.Repeat("c", 64)
	first := &jobv1.Operation{
		OperationId: "operation-shared", TenantId: "tenant-a", ProjectId: "project-a",
		JobId: "job-a", Etag: "operation-etag-a-1",
	}
	second := &jobv1.Operation{
		OperationId: "operation-shared", TenantId: "tenant-a", ProjectId: "project-b",
		JobId: "job-b", Etag: "operation-etag-b-1",
	}
	createdA, replay, err := repository.CreateAtomically(first, digest, configurationDigest, "same-client-key", "principal-a")
	if err != nil || replay {
		t.Fatalf("create project A: replay=%v err=%v", replay, err)
	}
	createdB, replay, err := repository.CreateAtomically(second, digest, configurationDigest, "same-client-key", "principal-b")
	if err != nil || replay {
		t.Fatalf("create project B: replay=%v err=%v", replay, err)
	}
	events := repository.OutboxEnvelopes()
	if len(events) != 2 || events[0].GetEventId() == events[1].GetEventId() || events[0].GetDeduplicationKey() == events[1].GetDeduplicationKey() {
		t.Fatalf("project-scoped operations produced colliding event identities: %v", events)
	}
	if events[0].GetSubject().GetName() != "tenants/tenant-a/projects/project-a/operations/operation-shared" || events[1].GetSubject().GetName() != "tenants/tenant-a/projects/project-b/operations/operation-shared" {
		t.Fatalf("event subjects are not canonical project-scoped names: %v", events)
	}
	firstOrderingKey, err := pubsubx.OrderingKey(events[0])
	if err != nil {
		t.Fatal(err)
	}
	secondOrderingKey, err := pubsubx.OrderingKey(events[1])
	if err != nil {
		t.Fatal(err)
	}
	if firstOrderingKey == secondOrderingKey {
		t.Fatal("project-scoped aggregates produced the same Pub/Sub ordering key")
	}
	deterministicRepository := operations.NewRepository()
	if _, _, err = deterministicRepository.CreateAtomically(first, digest, configurationDigest, "same-client-key", "principal-a"); err != nil {
		t.Fatal(err)
	}
	if deterministicRepository.OutboxEnvelopes()[0].GetEventId() != events[0].GetEventId() {
		t.Fatal("deterministic replay produced a different event identity")
	}
	createdA.JobId = "mutated-by-caller"
	persistedA, err := repository.Get("tenant-a", "project-a", "operation-shared")
	if err != nil || persistedA.GetJobId() != "job-a" {
		t.Fatalf("repository leaked mutable alias: operation=%v err=%v", persistedA, err)
	}
	advanced, err := repository.Advance(
		"tenant-a", "project-a", "operation-shared",
		persistedA.GetResourceVersion(), persistedA.GetEtag(),
		jobv1.OperationState_OPERATION_STATE_RUNNING,
	)
	if err != nil || advanced.GetResourceVersion() != 2 || advanced.GetEtag() == persistedA.GetEtag() {
		t.Fatalf("conditional advance: operation=%v err=%v", advanced, err)
	}
	if _, err = repository.Advance(
		"tenant-a", "project-a", "operation-shared",
		persistedA.GetResourceVersion(), persistedA.GetEtag(),
		jobv1.OperationState_OPERATION_STATE_SUCCEEDED,
	); !errors.Is(err, operations.ErrVersionConflict) {
		t.Fatalf("stale advance error=%v", err)
	}
	persistedB, err := repository.Get("tenant-a", "project-b", "operation-shared")
	if err != nil || persistedB.GetJobId() != createdB.GetJobId() || persistedB.GetResourceVersion() != 1 {
		t.Fatalf("project B was not isolated: operation=%v err=%v", persistedB, err)
	}
}
