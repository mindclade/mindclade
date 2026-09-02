package training

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	operationsapp "github.com/mindclade/mindclade/services/control_plane/internal/operations"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

func integrationDB(t *testing.T) *sql.DB {
	t.Helper()
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
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestPostgresProjectScopedSchedulerIdentitiesAndOperationHistory(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	tenantID := "tenant-scope-history-" + suffix
	projects := []string{"project-a", "project-b"}
	jobID, runID, attemptID, operationID := "jobs/shared", "runs/shared", "attempts/shared", "operations/shared"
	requestDigest := "sha256:" + strings.Repeat("a", 64)
	commandDigest := "sha256:" + strings.Repeat("b", 64)
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("history-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	trainingRepository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	schedulerRepository := jobs.SQLRepository{DB: db}
	operationRepository := operationsapp.SQLRepository{DB: db}
	t.Cleanup(func() {
		cleanupTx, cleanupErr := platformdb.BeginTenantTx(ctx, db, tenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin project-scope cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = cleanupTx.Rollback() }()
		for _, table := range []string{
			"run_command_receipt_attempts", "run_command_receipts", "attempt_completion_history",
			"attempt_output_refs", "attempts", "run_output_refs", "runs", "idempotency_records",
			"outbox_messages", "audit_events", "operation_revisions", "operations", "jobs",
			"error_precondition_violations", "error_field_violations", "error_details", "artifact_references",
		} {
			if _, cleanupErr = cleanupTx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = cleanupTx.Commit(); cleanupErr != nil {
			t.Errorf("commit project-scope cleanup: %v", cleanupErr)
		}
	})

	for index, projectID := range projects {
		configuration := fixtureArtifact(string(rune('c' + index)))
		job, createErr := schedulerRepository.CreateJobSQL(ctx, &jobv1.Job{
			JobId: jobID, TenantId: tenantID, ProjectId: projectID, JobKind: "scope-test",
			Configuration: configuration, Etag: "job-etag-1",
		})
		if createErr != nil || job.GetProjectId() != projectID {
			t.Fatalf("create project %s job=%v err=%v", projectID, job, createErr)
		}
		operation, replay, createErr := operationRepository.CreateAtomicallySQL(ctx, &jobv1.Operation{
			OperationId: operationID, TenantId: tenantID, ProjectId: projectID, JobId: jobID, Etag: "operation-etag-1",
		}, requestDigest, "shared-command-key", "scope-test-principal")
		if createErr != nil || replay || operation.GetProjectId() != projectID {
			t.Fatalf("create project %s operation=%v replay=%v err=%v", projectID, operation, replay, createErr)
		}
		run, createErr := schedulerRepository.CreateRunSQL(ctx, &jobv1.Run{
			RunId: runID, JobId: jobID, TenantId: tenantID, ProjectId: projectID, Configuration: configuration, Etag: "run-etag-1",
		})
		if createErr != nil || run.GetProjectId() != projectID {
			t.Fatalf("create project %s run=%v err=%v", projectID, run, createErr)
		}
		leaseAt := time.Now().UTC()
		lease, createErr := schedulerRepository.AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{
			TenantID: tenantID, RunID: runID, AttemptID: attemptID, WorkerID: "worker-" + projectID,
			Token: strings.Repeat(string(rune('k'+index)), 40), TokenKeyID: "key-1", Duration: time.Minute, Now: leaseAt,
			Command: jobs.RunCommandMetadata{
				TenantID: tenantID, ProjectID: projectID, PrincipalID: "principal", WorkerID: "worker-" + projectID,
				Action: "run.acquire_lease", IdempotencyKey: "shared-acquire-key", RequestDigest: commandDigest, ObservedAt: leaseAt,
			},
		})
		if createErr != nil || lease.Attempt.GetProjectId() != projectID {
			t.Fatalf("acquire project %s lease=%v err=%v", projectID, lease, createErr)
		}
		if persisted, getErr := schedulerRepository.GetAttemptSQL(ctx, tenantID, projectID, attemptID); getErr != nil || persisted.GetProjectId() != projectID {
			t.Fatalf("read project %s attempt=%v err=%v", projectID, persisted, getErr)
		}
	}

	identity := Identity{TenantID: tenantID, ProjectID: projects[0], Principal: "principal"}
	operation, err := operationRepository.GetSQL(ctx, tenantID, projects[0], operationID)
	if err != nil {
		t.Fatal(err)
	}
	for _, state := range []jobv1.OperationState{
		jobv1.OperationState_OPERATION_STATE_RUNNING,
		jobv1.OperationState_OPERATION_STATE_CANCELLING,
		jobv1.OperationState_OPERATION_STATE_CANCELLED,
	} {
		operation, err = operationRepository.AdvanceSQL(ctx, tenantID, projects[0], operationID, operation.GetResourceVersion(), operation.GetEtag(), state)
		if err != nil {
			t.Fatalf("advance operation to %s: %v", state, err)
		}
	}
	history, terminal, err := trainingRepository.ReadOperationRevisions(ctx, identity, operationID, 0, operationWatchBatchLimit)
	if err != nil || !terminal || len(history) != 4 {
		t.Fatalf("history=%v terminal=%v err=%v", history, terminal, err)
	}
	for index, revision := range history {
		if revision.GetResourceVersion() != int64(index+1) {
			t.Fatalf("history revision %d = %d", index, revision.GetResourceVersion())
		}
	}
	resumed, terminal, err := trainingRepository.ReadOperationRevisions(ctx, identity, operationID, 4, operationWatchBatchLimit)
	if err != nil || !terminal || len(resumed) != 0 {
		t.Fatalf("terminal reconnect history=%v terminal=%v err=%v", resumed, terminal, err)
	}
	if _, _, err = trainingRepository.ReadOperationRevisions(ctx, identity, operationID, 5, operationWatchBatchLimit); !errors.Is(err, ErrCursorAhead) {
		t.Fatalf("ahead cursor err=%v", err)
	}
	mutationTx, err := platformdb.BeginTenantTx(ctx, db, tenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = mutationTx.ExecContext(ctx, `DELETE FROM operation_revisions WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision=1`, tenantID, projects[0], operationID); err == nil {
		_, err = mutationTx.ExecContext(ctx, `UPDATE operations SET history_floor_version=2 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, tenantID, projects[0], operationID)
	}
	if err != nil {
		_ = mutationTx.Rollback()
		t.Fatal(err)
	}
	if err = mutationTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if _, _, err = trainingRepository.ReadOperationRevisions(ctx, identity, operationID, 0, operationWatchBatchLimit); !errors.Is(err, ErrCursorExpired) {
		t.Fatalf("expired cursor err=%v", err)
	}
	mutationTx, err = platformdb.BeginTenantTx(ctx, db, tenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = mutationTx.ExecContext(ctx, `DELETE FROM operation_revisions WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision=3`, tenantID, projects[0], operationID); err != nil {
		_ = mutationTx.Rollback()
		t.Fatal(err)
	}
	if err = mutationTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if _, _, err = trainingRepository.ReadOperationRevisions(ctx, identity, operationID, 1, operationWatchBatchLimit); !errors.Is(err, ErrOperationHistoryGap) {
		t.Fatalf("history gap err=%v", err)
	}
}

func TestPostgresTrainingCreateReplayCancelAndMapping(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "tenant-training-" + suffix, ProjectID: "project-training", Principal: "principal-training"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("integration-pagination-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	at := time.Now().UTC()
	t.Cleanup(func() {
		cleanupTx, cleanupErr := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = cleanupTx.Rollback() }()
		for _, table := range []string{
			"training_run_labels", "training_checkpoints", "training_runs", "idempotency_records",
			"outbox_messages", "audit_events", "run_command_receipt_attempts", "run_command_receipts",
			"attempt_completion_history", "attempt_output_refs", "attempts", "run_output_refs",
			"operations", "runs", "jobs", "training_progress_snapshots",
			"error_precondition_violations", "error_field_violations", "error_details",
			"resource_references", "artifact_references",
		} {
			if _, cleanupErr = cleanupTx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", identity.TenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = cleanupTx.Commit(); cleanupErr != nil {
			t.Errorf("commit cleanup: %v", cleanupErr)
		}
	})
	command := &trainingv1.CreateTrainingRunCommand{Project: &commonv1.ResourceRef{ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID}, TrainingRunId: "integration-" + suffix, TrainingRecipe: fixtureArtifact("a"), DatasetRelease: &commonv1.ResourceRef{ResourceType: "dataset_release", ResourceId: "dataset-01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: "datasetReleases/dataset-01", ResourceVersion: 2, Etag: "dataset-etag"}, ModelRelease: &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: "model-01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: "modelReleases/model-01", ResourceVersion: 3, Etag: "model-etag"}, ExecutablePlan: fixtureArtifact("b"), Labels: map[string]string{"profile": "integration"}, PolicyClassification: "internal"}
	digest, err := canonicalCommandDigest(command)
	if err != nil {
		t.Fatal(err)
	}
	command.Context = &commonv1.CommandContext{RequestId: "request-create-" + suffix, IdempotencyKey: "create-" + suffix, PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID, CanonicalRequestDigest: digest}
	operation, replay, err := repository.CreateTrainingRun(ctx, identity, command, digest, at)
	if err != nil || replay {
		t.Fatalf("create operation=%v replay=%v err=%v", operation, replay, err)
	}
	if operation.GetTarget() == nil || operation.GetTarget().GetResourceVersion() != 1 {
		t.Fatalf("operation target=%v", operation.GetTarget())
	}
	var schedulerRunID, schedulerState, jobState string
	readSchedulerTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	if err = readSchedulerTx.QueryRowContext(ctx, `
SELECT training_runs.scheduler_run_id,runs.status,jobs.desired_state
FROM training_runs
JOIN runs ON runs.tenant_id=training_runs.tenant_id AND runs.project_id=training_runs.project_id AND runs.id=training_runs.scheduler_run_id
JOIN jobs ON jobs.tenant_id=training_runs.tenant_id AND jobs.project_id=training_runs.project_id AND jobs.id=training_runs.job_id
WHERE training_runs.tenant_id=$1 AND training_runs.project_id=$2 AND training_runs.name=$3`, identity.TenantID, identity.ProjectID, operation.GetTarget().GetName()).Scan(&schedulerRunID, &schedulerState, &jobState); err != nil {
		t.Fatalf("read linked scheduler lifecycle: %v", err)
	}
	if err = readSchedulerTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if schedulerRunID == "" || schedulerState != "READY" || jobState != "QUEUED" {
		t.Fatalf("linked scheduler lifecycle run=%q state=%q job=%q", schedulerRunID, schedulerState, jobState)
	}
	replayed, replay, err := repository.CreateTrainingRun(ctx, identity, command, digest, at)
	if err != nil || !replay || !proto.Equal(operation, replayed) {
		t.Fatalf("replay operation=%v replay=%v err=%v", replayed, replay, err)
	}
	// A command key and client-chosen run ID are scoped by project. The same
	// tenant can safely use both in a second project without replaying or
	// colliding with the first project aggregate.
	otherProject := identity
	otherProject.ProjectID = "project-training-other"
	otherCommand := proto.Clone(command).(*trainingv1.CreateTrainingRunCommand)
	otherCommand.Project = proto.Clone(command.GetProject()).(*commonv1.ResourceRef)
	otherCommand.Project.ResourceId = otherProject.ProjectID
	otherCommand.Project.ProjectId = otherProject.ProjectID
	otherCommand.Project.Name = "tenants/" + identity.TenantID + "/projects/" + otherProject.ProjectID
	otherCommand.DatasetRelease = proto.Clone(command.GetDatasetRelease()).(*commonv1.ResourceRef)
	otherCommand.DatasetRelease.ProjectId = otherProject.ProjectID
	otherCommand.ModelRelease = proto.Clone(command.GetModelRelease()).(*commonv1.ResourceRef)
	otherCommand.ModelRelease.ProjectId = otherProject.ProjectID
	otherCommand.Context = nil
	otherDigest, digestErr := canonicalCommandDigest(otherCommand)
	if digestErr != nil {
		t.Fatal(digestErr)
	}
	otherCommand.Context = &commonv1.CommandContext{
		RequestId: "request-create-other-" + suffix, IdempotencyKey: command.GetContext().GetIdempotencyKey(),
		PrincipalId: otherProject.Principal, TenantId: otherProject.TenantID, ProjectId: otherProject.ProjectID,
		CanonicalRequestDigest: otherDigest,
	}
	otherOperation, otherReplay, createErr := repository.CreateTrainingRun(ctx, otherProject, otherCommand, otherDigest, at)
	if createErr != nil || otherReplay || otherOperation.GetTarget().GetName() == operation.GetTarget().GetName() {
		t.Fatalf("cross-project create operation=%v replay=%v err=%v", otherOperation, otherReplay, createErr)
	}
	run, err := repository.GetTrainingRun(ctx, identity, operation.GetTarget().GetName())
	if err != nil {
		t.Fatal(err)
	}
	if run.GetLabels()["profile"] != "integration" || !proto.Equal(run.GetExecutablePlan(), command.GetExecutablePlan()) || run.GetDatasetRelease().GetEtag() != "dataset-etag" {
		t.Fatalf("run mapping lost fields: %v", run)
	}
	listed, next, readAt, err := repository.ListTrainingRuns(ctx, identity, RunPage{Limit: 1, Order: "create_time desc,name desc"})
	if err != nil || len(listed) != 1 || next != "" || readAt.IsZero() {
		t.Fatalf("list values=%d next=%q read=%v err=%v", len(listed), next, readAt, err)
	}
	worker := identity
	worker.WorkerID = "worker-training-" + suffix
	worker.LeaseToken = "training-integration-token-" + strings.Repeat("d", 32)
	leaseAt := at.Add(time.Second)
	schedulerRepository := jobs.SQLRepository{DB: db}
	acquireCommand := jobs.AcquireLeaseCommand{
		TenantID: identity.TenantID, RunID: schedulerRunID, AttemptID: "attempt-training-" + suffix,
		WorkerID: worker.WorkerID, Token: worker.LeaseToken, TokenKeyID: "integration-key",
		Duration: 5 * time.Minute, Now: leaseAt,
		Command: jobs.RunCommandMetadata{
			TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal, WorkerID: worker.WorkerID,
			Action: "run.acquire_lease", IdempotencyKey: "acquire-training-" + suffix,
			RequestDigest: "sha256:" + strings.Repeat("1", 64), ObservedAt: leaseAt,
		},
	}
	leaseResult, err := schedulerRepository.AcquireLeaseSQL(ctx, acquireCommand)
	if err != nil {
		t.Fatalf("acquire linked scheduler lease: %v", err)
	}
	replayedLease, err := schedulerRepository.AcquireLeaseSQL(ctx, acquireCommand)
	if err != nil || !replayedLease.Replay || !proto.Equal(replayedLease.Attempt, leaseResult.Attempt) || !proto.Equal(replayedLease.Fence, leaseResult.Fence) || replayedLease.TokenKeyID != leaseResult.TokenKeyID {
		t.Fatalf("durable acquire replay result=%v err=%v", replayedLease, err)
	}
	conflictingAcquire := acquireCommand
	conflictingAcquire.Command.RequestDigest = "sha256:" + strings.Repeat("f", 64)
	if _, conflictErr := schedulerRepository.AcquireLeaseSQL(ctx, conflictingAcquire); !errors.Is(conflictErr, jobs.ErrIdempotencyConflict) {
		t.Fatalf("acquire idempotency conflict err=%v", conflictErr)
	}
	startAt := at.Add(2 * time.Second)
	start := &trainingv1.StartTrainingAttemptCommand{
		TrainingRun: &commonv1.ResourceRef{
			ResourceType: "training_run", ResourceId: command.GetTrainingRunId(), TenantId: identity.TenantID,
			ProjectId: identity.ProjectID, ResourceVersion: run.GetRevision(), Name: run.GetName(), Etag: run.GetEtag(),
		},
		Fence: proto.Clone(leaseResult.Fence).(*jobv1.LeaseFence), Deadline: timestamppb.New(startAt.Add(time.Minute)),
		DelegatedCapability: &commonv1.ResourceRef{
			ResourceType: "delegated_capability", ResourceId: "capability-" + suffix, TenantId: identity.TenantID,
			ProjectId: identity.ProjectID, ResourceVersion: 1, Name: "delegatedCapabilities/capability-" + suffix, Etag: "capability-etag-1",
		},
	}
	startDigest, err := canonicalCommandDigest(start)
	if err != nil {
		t.Fatal(err)
	}
	start.Context = &commonv1.CommandContext{
		RequestId: "request-start-" + suffix, IdempotencyKey: "start-" + suffix, PrincipalId: identity.Principal,
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, CanonicalRequestDigest: startDigest,
	}
	run, replay, err = repository.StartTrainingAttempt(ctx, worker, start, startDigest, startAt)
	if err != nil || replay || run.GetState() != trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING {
		t.Fatalf("start linked training attempt run=%v replay=%v err=%v", run, replay, err)
	}
	// Renewal updates the scheduler's durable expiry/version. The training
	// aggregate intentionally accepts the later same-token/same-epoch fence.
	renewAt := at.Add(3 * time.Second)
	renewCommand := jobs.RenewLeaseCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: identity.TenantID, ProjectID: identity.ProjectID, AttemptID: leaseResult.Attempt.GetAttemptId(), WorkerID: worker.WorkerID,
			Token: worker.LeaseToken, Epoch: leaseResult.Attempt.GetLeaseEpoch(),
		},
		ExpectedResourceVersion: leaseResult.Attempt.GetResourceVersion(), Duration: 10 * time.Minute, Now: renewAt,
		Command: jobs.RunCommandMetadata{
			TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal, WorkerID: worker.WorkerID,
			Action: "run.renew_lease", IdempotencyKey: "renew-training-" + suffix,
			RequestDigest: "sha256:" + strings.Repeat("2", 64), ObservedAt: renewAt,
		},
	}
	renewed, err := schedulerRepository.RenewLeaseSQL(ctx, renewCommand)
	if err != nil || renewed.Fence.GetDeadline().AsTime().Before(leaseResult.Fence.GetDeadline().AsTime()) {
		t.Fatalf("renew linked scheduler lease result=%v err=%v", renewed, err)
	}
	replayedRenewal, err := schedulerRepository.RenewLeaseSQL(ctx, renewCommand)
	if err != nil || !replayedRenewal.Replay || !proto.Equal(replayedRenewal.Attempt, renewed.Attempt) || !proto.Equal(replayedRenewal.Fence, renewed.Fence) {
		t.Fatalf("durable renewal replay result=%v err=%v", replayedRenewal, err)
	}
	cancel := &trainingv1.CancelTrainingRunCommand{TrainingRunName: run.GetName(), Etag: run.GetEtag(), Reason: "integration cancellation"}
	cancelDigest, err := canonicalCommandDigest(cancel)
	if err != nil {
		t.Fatal(err)
	}
	cancel.Context = &commonv1.CommandContext{RequestId: "request-cancel-" + suffix, IdempotencyKey: "cancel-" + suffix, PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID, CanonicalRequestDigest: cancelDigest}
	cancelAt := at.Add(4 * time.Second)
	cancelled, replay, err := repository.CancelTrainingRun(ctx, worker, cancel, cancelDigest, cancelAt)
	if err != nil || replay || cancelled.GetState() != trainingv1.TrainingRunState_TRAINING_RUN_STATE_DRAINING {
		t.Fatalf("cancel run=%v replay=%v err=%v", cancelled, replay, err)
	}
	readSchedulerTx, err = platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	if err = readSchedulerTx.QueryRowContext(ctx, `SELECT runs.status,jobs.desired_state FROM runs JOIN jobs ON jobs.tenant_id=runs.tenant_id AND jobs.project_id=runs.project_id AND jobs.id=runs.job_id WHERE runs.tenant_id=$1 AND runs.project_id=$2 AND runs.id=$3`, identity.TenantID, identity.ProjectID, schedulerRunID).Scan(&schedulerState, &jobState); err != nil {
		t.Fatalf("read cancelled scheduler lifecycle: %v", err)
	}
	if err = readSchedulerTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if schedulerState != "CANCELLING" || jobState != "CANCELLING" {
		t.Fatalf("cancel did not reconcile scheduler lifecycle: run=%q job=%q", schedulerState, jobState)
	}
	failedCompletion := &trainingv1.CompleteTrainingRunCommand{
		TrainingRunName: run.GetName(), Fence: proto.Clone(renewed.Fence).(*jobv1.LeaseFence),
		Classification: trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_EXECUTION_FAILURE,
		Error:          &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_ABORTED, Message: "must not replace cancellation", ErrorId: "error-failed-" + suffix},
	}
	failedDigest, err := canonicalCommandDigest(failedCompletion)
	if err != nil {
		t.Fatal(err)
	}
	failedCompletion.Context = &commonv1.CommandContext{
		RequestId: "request-complete-failed-" + suffix, IdempotencyKey: "complete-failed-" + suffix,
		PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID, CanonicalRequestDigest: failedDigest,
	}
	if _, _, completionErr := repository.CompleteTrainingRun(ctx, worker, failedCompletion, failedDigest, at.Add(5*time.Second)); !errors.Is(completionErr, ErrInvalidTransition) {
		t.Fatalf("non-cancellation completion advanced a cancelling scheduler: %v", completionErr)
	}
	cancelledCompletion := &trainingv1.CompleteTrainingRunCommand{
		TrainingRunName: run.GetName(), Fence: proto.Clone(renewed.Fence).(*jobv1.LeaseFence),
		Classification: trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED,
		CompletedAt:    timestamppb.New(at.Add(5 * time.Second)),
	}
	completedDigest, err := canonicalCommandDigest(cancelledCompletion)
	if err != nil {
		t.Fatal(err)
	}
	cancelledCompletion.Context = &commonv1.CommandContext{
		RequestId: "request-complete-cancelled-" + suffix, IdempotencyKey: "complete-cancelled-" + suffix,
		PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID, CanonicalRequestDigest: completedDigest,
	}
	completed, replay, err := repository.CompleteTrainingRun(ctx, worker, cancelledCompletion, completedDigest, at.Add(5*time.Second))
	if err != nil || replay || completed.GetState() != trainingv1.TrainingRunState_TRAINING_RUN_STATE_CANCELLED {
		t.Fatalf("cancellation acknowledgement run=%v replay=%v err=%v", completed, replay, err)
	}
	readSchedulerTx, err = platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var attemptState, operationState string
	var operationDone bool
	if err = readSchedulerTx.QueryRowContext(ctx, `
SELECT runs.status,jobs.desired_state,attempts.status,operations.status,operations.done
FROM runs
JOIN jobs ON jobs.tenant_id=runs.tenant_id AND jobs.project_id=runs.project_id AND jobs.id=runs.job_id
JOIN attempts ON attempts.tenant_id=runs.tenant_id AND attempts.project_id=runs.project_id AND attempts.run_id=runs.id
JOIN operations ON operations.tenant_id=jobs.tenant_id AND operations.project_id=jobs.project_id AND operations.id=jobs.operation_id
WHERE runs.tenant_id=$1 AND runs.project_id=$2 AND runs.id=$3`, identity.TenantID, identity.ProjectID, schedulerRunID).Scan(&schedulerState, &jobState, &attemptState, &operationState, &operationDone); err != nil {
		t.Fatalf("read terminal scheduler lifecycle: %v", err)
	}
	if err = readSchedulerTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if schedulerState != "CANCELLED" || jobState != "CANCELLED" || attemptState != "CANCELLED" || operationState != "CANCELLED" || !operationDone {
		t.Fatalf("terminal cancellation did not reconcile: run=%q job=%q attempt=%q operation=%q done=%v", schedulerState, jobState, attemptState, operationState, operationDone)
	}
	typeCounts := map[string]int{}
	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	rows, err := readTx.QueryContext(ctx, `SELECT event_type FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var eventType string
		if err = rows.Scan(&eventType); err != nil {
			t.Fatal(err)
		}
		typeCounts[eventType]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	wantTypeCounts := map[string]int{
		"mindclade.events.job.v1.AttemptLeased":                      1,
		"mindclade.events.job.v1.JobRequested":                       2,
		"mindclade.events.training.v1.TrainingRunCreated":            2,
		"mindclade.events.training.v1.TrainingStarted":               1,
		"mindclade.events.training.v1.TrainingCancellationRequested": 1,
		"mindclade.events.training.v1.TrainingCompleted":             1,
	}
	if !reflect.DeepEqual(typeCounts, wantTypeCounts) {
		t.Fatalf("outbox event type counts=%v want=%v", typeCounts, wantTypeCounts)
	}
	var envelopeBytes []byte
	if err = readTx.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type='mindclade.events.training.v1.TrainingCancellationRequested'`, identity.TenantID).Scan(&envelopeBytes); err != nil {
		t.Fatal(err)
	}
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalEnvelope(envelopeBytes); err != nil {
		t.Fatalf("invalid durable event: %v", err)
	}
	var jobEnvelopeBytes []byte
	readJobTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	if err = readJobTx.QueryRowContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND event_type='mindclade.events.job.v1.JobRequested' AND aggregate_id=$2`, identity.TenantID, operation.GetOperationId()).Scan(&jobEnvelopeBytes); err != nil {
		_ = readJobTx.Rollback()
		t.Fatal(err)
	}
	if err = readJobTx.Commit(); err != nil {
		t.Fatal(err)
	}
	jobEnvelope, err := queue.UnmarshalEnvelope(jobEnvelopeBytes)
	if err != nil {
		t.Fatal(err)
	}
	jobPayload, err := queue.UnmarshalRegisteredPayload(jobEnvelope)
	if err != nil {
		t.Fatal(err)
	}
	requested, ok := jobPayload.(*jobv1.JobRequested)
	if !ok || requested.GetJobId() != operation.GetJobId() || requested.GetConfigurationDigest() != digest {
		t.Fatalf("training JobRequested payload=%T %v", jobPayload, jobPayload)
	}
	other := identity
	other.TenantID = "other-" + identity.TenantID
	if _, err = repository.GetTrainingRun(ctx, other, run.GetName()); !errors.Is(err, ErrNotFound) {
		t.Fatalf("cross-tenant read err=%v", err)
	}
}
