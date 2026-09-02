package jobs

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

func TestPostgresDomainCompletionIsFencedTypedAndTransactional(t *testing.T) {
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		t.Skip("PostgreSQL integration DSN is not configured")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	tenantID, projectID := "domain-completion-tenant-"+suffix, "project-1"
	t.Cleanup(func() {
		cleanupContext, cleanupCancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cleanupCancel()
		tx, cleanupErr := platformdb.BeginTenantTx(cleanupContext, db, tenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = tx.Rollback() }()
		for _, table := range []string{
			"run_command_receipt_attempts", "run_command_receipts", "attempt_completion_history", "attempt_output_refs", "attempts",
			"run_output_refs", "runs", "outbox_messages", "jobs", "error_precondition_violations", "error_field_violations",
			"error_details", "artifact_references", "artifacts",
		} {
			if _, cleanupErr = tx.ExecContext(cleanupContext, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); cleanupErr != nil { //nolint:gosec // closed table list; tenant remains a bound value.
				t.Errorf("clean %s: %v", table, cleanupErr)
				return
			}
		}
		if cleanupErr = tx.Commit(); cleanupErr != nil {
			t.Errorf("commit cleanup: %v", cleanupErr)
		}
	})

	repository := SQLRepository{DB: db}
	base := time.Now().UTC().Truncate(time.Microsecond)
	for index, fixture := range []struct {
		jobKind   string
		eventType string
	}{
		{jobKind: FeatureMaterializationJobKind, eventType: "mindclade.events.feature.v1.FeatureMaterializationCompleted"},
		{jobKind: TransformExecutionJobKind, eventType: "mindclade.events.transform.v1.TransformExecutionCompleted"},
	} {
		jobID := "jobs/domain-" + strings.ReplaceAll(fixture.jobKind, ".", "-")
		runID := "runs/domain-" + strings.ReplaceAll(fixture.jobKind, ".", "-")
		attemptID := "attempts/domain-" + strings.ReplaceAll(fixture.jobKind, ".", "-")
		configuration := domainCompletionArtifact(byte('1'+index), "application/json")
		if _, err = repository.CreateJobSQL(ctx, &jobv1.Job{JobId: jobID, TenantId: tenantID, ProjectId: projectID, JobKind: fixture.jobKind, Configuration: configuration, Etag: "job-etag-1"}); err != nil {
			t.Fatalf("create %s job: %v", fixture.jobKind, err)
		}
		if _, err = repository.CreateRunSQL(ctx, &jobv1.Run{RunId: runID, JobId: jobID, TenantId: tenantID, ProjectId: projectID, Configuration: configuration, Etag: "run-etag-1"}); err != nil {
			t.Fatalf("create %s run: %v", fixture.jobKind, err)
		}
		leaseAt := base.Add(time.Duration(index) * time.Second)
		workerID := "worker-" + strings.ReplaceAll(fixture.jobKind, ".", "-")
		token := strings.Repeat("domain-completion-token-", 3) + fixture.jobKind
		acquireMetadata := domainRunMetadata(tenantID, projectID, workerID, actionAcquireLease, "acquire-"+fixture.jobKind, leaseAt)
		lease, leaseErr := repository.AcquireLeaseSQL(ctx, AcquireLeaseCommand{
			TenantID: tenantID, RunID: runID, AttemptID: attemptID, WorkerID: workerID, Token: token,
			Duration: time.Minute, Now: leaseAt, Command: acquireMetadata, TokenKeyID: "test-key",
		})
		if leaseErr != nil {
			t.Fatalf("acquire %s lease: %v", fixture.jobKind, leaseErr)
		}
		completedAt := leaseAt.Add(time.Second)
		output := domainCompletionArtifact(byte('3'+index), "application/octet-stream")
		receipt := domainCompletionArtifact(byte('5'+index), "application/vnd.mindclade.receipt+json")
		lineage := domainCompletionArtifact(byte('7'+index), "application/vnd.mindclade.lineage+json")
		metadata := domainRunMetadata(tenantID, projectID, workerID, actionCommitAttempt, "complete-"+fixture.jobKind, completedAt)
		commandContext := domainCommandContext(metadata)
		attempt := proto.Clone(lease.Attempt).(*jobv1.Attempt)
		attempt.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
		attempt.Outputs = []*artifactv1.ArtifactRef{output}
		completion := CompleteAttemptCommand{
			Credentials: LeaseCredentials{TenantID: tenantID, ProjectID: projectID, AttemptID: attemptID, WorkerID: workerID, Token: token, Epoch: lease.Fence.GetLeaseEpoch()},
			Attempt:     attempt, Fence: proto.Clone(lease.Fence).(*jobv1.LeaseFence), UpdateMask: []string{"state", "outputs"},
			ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Now: completedAt, Command: metadata,
		}
		if fixture.jobKind == FeatureMaterializationJobKind {
			completion.FeatureMaterialization = &featurev1.CommitFeatureMaterializationCommand{
				Context: commandContext, MaterializationName: "tenants/" + tenantID + "/projects/" + projectID + "/featureMaterializations/a.b_c~d-1",
				Fence: proto.Clone(lease.Fence).(*jobv1.LeaseFence), Classification: featurev1.FeatureMaterializationTerminalClassification_FEATURE_MATERIALIZATION_TERMINAL_CLASSIFICATION_SUCCEEDED,
				Receipt: receipt, OutputRefs: []*artifactv1.ArtifactRef{output}, CompletedAt: timestamppb.New(completedAt),
			}
			wrong := completion
			wrong.FeatureMaterialization = nil
			wrong.TransformExecution = &transformv1.CommitTransformExecutionCommand{
				Context: commandContext, ExecutionName: "tenants/" + tenantID + "/projects/" + projectID + "/transformExecutions/wrong-kind",
				Fence: proto.Clone(lease.Fence).(*jobv1.LeaseFence), Classification: transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SUCCEEDED,
				Receipt: receipt, OutputRefs: []*artifactv1.ArtifactRef{output}, LineageMap: lineage, CompletedAt: timestamppb.New(completedAt),
			}
			wrong.Command.IdempotencyKey, wrong.Command.RequestID = "wrong-kind", "wrong-kind"
			wrong.TransformExecution.Context = domainCommandContext(wrong.Command)
			if _, wrongErr := repository.CompleteAttemptSQL(ctx, wrong); !errors.Is(wrongErr, ErrInvalidOutcome) {
				t.Fatalf("wrong completion kind was not rejected atomically: %v", wrongErr)
			}
			persisted, loadErr := repository.GetAttemptSQL(ctx, tenantID, projectID, attemptID)
			if loadErr != nil || persisted.GetState() != jobv1.AttemptState_ATTEMPT_STATE_LEASED || persisted.GetResourceVersion() != lease.Attempt.GetResourceVersion() {
				t.Fatalf("rejected kind mutated attempt: attempt=%v err=%v", persisted, loadErr)
			}
		} else {
			completion.TransformExecution = &transformv1.CommitTransformExecutionCommand{
				Context: commandContext, ExecutionName: "tenants/" + tenantID + "/projects/" + projectID + "/transformExecutions/01",
				Fence: proto.Clone(lease.Fence).(*jobv1.LeaseFence), Classification: transformv1.TransformExecutionTerminalClassification_TRANSFORM_EXECUTION_TERMINAL_CLASSIFICATION_SUCCEEDED,
				Receipt: receipt, OutputRefs: []*artifactv1.ArtifactRef{output}, LineageMap: lineage, CompletedAt: timestamppb.New(completedAt),
			}
		}
		result, completeErr := repository.CompleteAttemptSQL(ctx, completion)
		if completeErr != nil || result.Replay || result.Attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED || result.Run.GetState() != jobv1.RunState_RUN_STATE_SUCCEEDED {
			t.Fatalf("complete %s: result=%v err=%v", fixture.jobKind, result, completeErr)
		}
		replayed, replayErr := repository.CompleteAttemptSQL(ctx, completion)
		if replayErr != nil || !replayed.Replay || !proto.Equal(replayed.Attempt, result.Attempt) || !proto.Equal(replayed.Run, result.Run) {
			t.Fatalf("replay %s: result=%v err=%v", fixture.jobKind, replayed, replayErr)
		}
		var encoded []byte
		if err = db.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type=$2`, tenantID, fixture.eventType).Scan(&encoded); err != nil {
			t.Fatalf("read %s transactional outbox event: %v", fixture.eventType, err)
		}
		envelope, decodeErr := queue.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payload, decodeErr := queue.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		switch value := payload.(type) {
		case *featurev1.FeatureMaterializationCompleted:
			if completion.FeatureMaterialization == nil || value.GetMaterializationName() != completion.FeatureMaterialization.GetMaterializationName() || !proto.Equal(value.GetFence(), lease.Fence) || !proto.Equal(value.GetOutputRefs()[0], output) {
				t.Fatalf("feature outbox payload incomplete: %v", value)
			}
		case *transformv1.TransformExecutionCompleted:
			if completion.TransformExecution == nil || value.GetExecutionName() != completion.TransformExecution.GetExecutionName() || !proto.Equal(value.GetFence(), lease.Fence) || !proto.Equal(value.GetLineageMap(), lineage) || !proto.Equal(value.GetOutputRefs()[0], output) {
				t.Fatalf("transform outbox payload incomplete: %v", value)
			}
		default:
			t.Fatalf("unexpected registered domain completion payload: %T", payload)
		}
		var count int
		if err = db.QueryRowContext(ctx, `SELECT count(*) FROM outbox_messages WHERE tenant_id=$1 AND event_type=$2`, tenantID, fixture.eventType).Scan(&count); err != nil || count != 1 {
			t.Fatalf("idempotent %s outbox count=%d err=%v", fixture.eventType, count, err)
		}
	}
}

func domainCompletionArtifact(fill byte, mediaType string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(string(fill), 64), MediaType: mediaType, SizeBytes: 42, SchemaId: "mindclade.test", SchemaVersion: "1"}
}

func domainRunMetadata(tenantID, projectID, workerID, action, key string, at time.Time) RunCommandMetadata {
	return RunCommandMetadata{
		TenantID: tenantID, ProjectID: projectID, PrincipalID: "principal-1", WorkerID: workerID, Action: action,
		IdempotencyKey: key, RequestDigest: "sha256:" + strings.Repeat("a", 64), RequestID: "request-" + key,
		TraceID: "trace-" + key, CorrelationID: "correlation-" + key, CausationID: "causation-" + key, ObservedAt: at,
	}
}

func domainCommandContext(value RunCommandMetadata) *commonv1.CommandContext {
	return &commonv1.CommandContext{
		TenantId: value.TenantID, ProjectId: value.ProjectID, PrincipalId: value.PrincipalID, RequestId: value.RequestID,
		IdempotencyKey: value.IdempotencyKey, TraceId: value.TraceID, CorrelationId: value.CorrelationID, CausationId: value.CausationID,
	}
}
