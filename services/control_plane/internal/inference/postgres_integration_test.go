package inference

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

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
)

func inferenceIntegrationDB(t *testing.T) *sql.DB {
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

func TestPostgresInferenceJourneyIsNormalizedFencedResumableAndEventBacked(t *testing.T) {
	db := inferenceIntegrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	at := time.Now().UTC().Truncate(time.Microsecond)
	identity := Identity{TenantID: "inference-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	repository := SQLRepository{DB: db, Events: GeneratedEventFactory{}}

	request := inferenceRequestFixture(identity, at)
	request.Name = projectParent(identity) + "/inferenceRequests/qualification"
	request.Uid = "inference-request-" + suffix
	request.Context = &commonv1.CommandContext{
		RequestId: "submit-" + suffix, IdempotencyKey: "submit-key-" + suffix,
		PrincipalId: identity.Principal, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		TraceId: "trace-" + suffix, CorrelationId: "correlation-" + suffix,
		CausationId: "causation-" + suffix, CancellationTokenId: "cancel-" + suffix,
		Deadline: timestamppb.New(at.Add(time.Minute)),
	}
	request.PolicySnapshots[0].ExpireTime = timestamppb.New(at.Add(time.Hour))
	request.CreateTime = timestamppb.New(at)
	request.Deadline = timestamppb.New(at.Add(time.Hour))
	digest, err := canonicalDigest(request)
	if err != nil {
		t.Fatal(err)
	}
	request.Context.CanonicalRequestDigest = digest

	operation, replay, err := repository.Submit(ctx, identity, request, digest, at)
	if err != nil || replay {
		t.Fatalf("submit operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayedOperation, replay, err := repository.Submit(ctx, identity, clone(request), digest, at.Add(time.Second))
	if err != nil || !replay || !proto.Equal(operation, replayedOperation) {
		t.Fatalf("submit replay operation=%v replay=%v err=%v", replayedOperation, replay, err)
	}
	conflict := clone(request)
	conflict.Capability = "different-capability"
	conflictingDigest, err := canonicalDigest(conflict)
	if err != nil {
		t.Fatal(err)
	}
	conflict.Context.CanonicalRequestDigest = conflictingDigest
	if _, _, err = repository.Submit(ctx, identity, conflict, conflictingDigest, at.Add(time.Second)); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("idempotency conflict err=%v", err)
	}
	persistedRequest, err := repository.GetRequest(ctx, identity, request.GetName())
	if err != nil || !proto.Equal(persistedRequest, request) {
		t.Fatalf("request SQL roundtrip=%v err=%v", persistedRequest, err)
	}
	persistedRequest.Context.PrincipalId = "mutated"
	persistedAgain, err := repository.GetRequest(ctx, identity, request.GetName())
	if err != nil || persistedAgain.GetContext().GetPrincipalId() != identity.Principal {
		t.Fatalf("request clone boundary=%v err=%v", persistedAgain, err)
	}

	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var schedulerRunID string
	if err = readTx.QueryRowContext(ctx, `SELECT scheduler_run_id FROM inference_requests WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, request.GetName()).Scan(&schedulerRunID); err != nil {
		_ = readTx.Rollback()
		t.Fatal(err)
	}
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}

	leaseToken := strings.Repeat("inference-lease-token-", 2)
	leaseAt := at.Add(2 * time.Second)
	lease, err := (jobs.SQLRepository{DB: db}).AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{
		TenantID: identity.TenantID, RunID: schedulerRunID, AttemptID: "attempts/inference-1",
		WorkerID: "worker-1", Token: leaseToken, TokenKeyID: "key-1", Duration: time.Minute, Now: leaseAt,
		Command: jobs.RunCommandMetadata{
			TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal,
			WorkerID: "worker-1", Action: "run.acquire_lease", IdempotencyKey: "acquire-" + suffix,
			RequestDigest: digestFixture("5"), ObservedAt: leaseAt,
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	commitAt := at.Add(3 * time.Second)
	confidence := 0.93
	requestRef := requestResource(identity, request, digest)
	decision := &policyv1.AuthorizationDecision{
		Name: projectParent(identity) + "/authorizationDecisions/inference-safety", Uid: "authorization-" + suffix,
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalRef: identity.Principal,
		Action: "inference.result.commit", Resource: clone(requestRef), IntentDigest: digestFixture("6"),
		Policies: cloneSlice(request.GetPolicySnapshots()), Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW,
		ReasonCode: "policy-allow", SafeReason: "bounded inference result accepted",
		Constraints: []*policyv1.AuthorizationConstraint{{Kind: "classification", DetailsDigest: digestFixture("7"), ExpireTime: timestamppb.New(commitAt.Add(time.Hour))}},
		EvaluatedAt: timestamppb.New(commitAt), ExpireTime: timestamppb.New(commitAt.Add(time.Hour)),
		ContextDigest: digestFixture("8"), DecisionDigest: digestFixture("9"),
	}
	result := &inferencev1.InferenceResult{
		Name: projectParent(identity) + "/inferenceResults/qualification", Uid: "inference-result-" + suffix,
		Request: requestRef, RequestDigest: digest, Operation: operationResource(operation),
		JobId: operation.GetJobId(), RunId: schedulerRunID, AttemptId: lease.Attempt.GetAttemptId(),
		LeaseEpoch: lease.Fence.GetLeaseEpoch(), Outcome: inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_SUCCEEDED,
		ResultManifest: artifactFixture("a"), InputArtifact: artifactFixture("b"), ModelBundle: clone(request.GetResolvedModelBundle()),
		FeatureBundle: artifactFixture("c"), ExecutablePlan: artifactFixture("d"), ProviderManifest: artifactFixture("e"),
		KernelQualification: artifactFixture("f"), ConfidenceReport: artifactFixture("1"), RankingReport: artifactFixture("2"),
		FailureDiagnostics: artifactFixture("3"),
		Candidates: []*inferencev1.InferenceCandidateResult{
			{CandidateId: "candidate-0", SampleIndex: 0, Output: artifactFixture("4"), Confidence: &confidence, Selected: true, Diagnostics: artifactFixture("5")},
			{CandidateId: "candidate-1", SampleIndex: 1, Output: artifactFixture("6")},
		},
		SelectedCandidateId: "candidate-0", SafetyDecisions: []*policyv1.AuthorizationDecision{decision},
		SourceRevision: "git:qualification", CompletedAt: timestamppb.New(commitAt), ResultDigest: digestFixture("7"),
	}
	commit := &internalinferencev1.CommitInferenceResultRequest{
		Context: &commonv1.CommandContext{
			RequestId: "commit-" + suffix, IdempotencyKey: "commit-key-" + suffix,
			TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
			TraceId: "commit-trace-" + suffix, CorrelationId: request.GetContext().GetRequestId(),
			CausationId: request.GetContext().GetRequestId(), CancellationTokenId: "commit-cancel-" + suffix,
			Deadline: timestamppb.New(commitAt.Add(time.Minute)),
		},
		InferenceRequest: requestRef, Fence: clone(lease.Fence), Result: result, RequestDigest: digest,
	}
	commitDigest, err := canonicalDigest(commit)
	if err != nil {
		t.Fatal(err)
	}
	commit.Context.CanonicalRequestDigest = commitDigest
	worker := Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal, WorkerID: "worker-1", LeaseToken: "wrong-" + leaseToken}
	if _, _, _, err = repository.CommitResult(ctx, worker, commit, commitDigest, commitAt); !errors.Is(err, ErrLeaseToken) {
		t.Fatalf("wrong lease token err=%v", err)
	}
	worker.LeaseToken = leaseToken
	storedResult, completedOperation, replayedResult, err := repository.CommitResult(ctx, worker, commit, commitDigest, commitAt)
	if err != nil || replayedResult || !proto.Equal(storedResult, result) || !completedOperation.GetDone() || completedOperation.GetResourceVersion() != 3 {
		t.Fatalf("commit result=%v operation=%v replay=%v err=%v", storedResult, completedOperation, replayedResult, err)
	}
	storedReplay, operationReplay, replayedResult, err := repository.CommitResult(ctx, worker, clone(commit), commitDigest, commitAt.Add(time.Second))
	if err != nil || !replayedResult || !proto.Equal(storedReplay, result) || !proto.Equal(operationReplay, completedOperation) {
		t.Fatalf("commit replay result=%v operation=%v replay=%v err=%v", storedReplay, operationReplay, replayedResult, err)
	}
	readResult, readOperation, err := repository.GetResult(ctx, identity, operation.GetOperationId())
	if err != nil || !proto.Equal(readResult, result) || !proto.Equal(readOperation, completedOperation) {
		t.Fatalf("result SQL roundtrip=%v operation=%v err=%v", readResult, readOperation, err)
	}
	requestName, history, terminal, err := repository.ReadOperationRevisions(ctx, identity, operation.GetOperationId(), 0, operationWatchBatchSize)
	if err != nil || requestName != request.GetName() || !terminal || len(history) != 3 ||
		history[0].GetResourceVersion() != 1 || history[0].GetState() != jobv1.OperationState_OPERATION_STATE_PENDING ||
		history[1].GetResourceVersion() != 2 || history[1].GetState() != jobv1.OperationState_OPERATION_STATE_RUNNING ||
		history[2].GetResourceVersion() != 3 || history[2].GetState() != jobv1.OperationState_OPERATION_STATE_SUCCEEDED {
		t.Fatalf("history request=%q revisions=%v terminal=%v err=%v", requestName, history, terminal, err)
	}
	_, resumed, terminal, err := repository.ReadOperationRevisions(ctx, identity, operation.GetOperationId(), 3, operationWatchBatchSize)
	if err != nil || !terminal || len(resumed) != 0 {
		t.Fatalf("terminal resume revisions=%v terminal=%v err=%v", resumed, terminal, err)
	}
	if _, _, _, err = repository.ReadOperationRevisions(ctx, identity, operation.GetOperationId(), 4, operationWatchBatchSize); !errors.Is(err, ErrCursorAhead) {
		t.Fatalf("ahead cursor err=%v", err)
	}
	otherProject := identity
	otherProject.ProjectID = "other-project"
	if _, err = repository.GetRequest(ctx, otherProject, request.GetName()); !errors.Is(err, ErrPermissionDenied) {
		t.Fatalf("cross-project request err=%v", err)
	}

	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = verify.Rollback() }()
	var events, audits, receipts, operationRevisions int
	if err = verify.QueryRowContext(ctx, `SELECT
(SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),
(SELECT count(*) FROM audit_events WHERE tenant_id=$1),
(SELECT count(*) FROM evaluation_inference_command_receipts WHERE tenant_id=$1),
(SELECT count(*) FROM operation_revisions WHERE tenant_id=$1)`, identity.TenantID).Scan(&events, &audits, &receipts, &operationRevisions); err != nil {
		t.Fatal(err)
	}
	if events != 4 || audits != 2 || receipts != 2 || operationRevisions != 3 {
		t.Fatalf("events=%d audits=%d receipts=%d revisions=%d", events, audits, receipts, operationRevisions)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,event_type`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	types := make(map[string]int)
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			_ = platformdb.CloseRows(rows)
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			_ = platformdb.CloseRows(rows)
			t.Fatal(decodeErr)
		}
		payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
			_ = platformdb.CloseRows(rows)
			t.Fatal(decodeErr)
		}
		types[string(payload.ProtoReflect().Descriptor().FullName())]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		t.Fatal(err)
	}
	for _, eventType := range []string{"mindclade.events.inference.v1.InferenceRequested", "mindclade.events.inference.v1.InferenceResultCommitted", "mindclade.events.job.v1.JobRequested", "mindclade.events.job.v1.AttemptLeased"} {
		if types[eventType] != 1 {
			t.Fatalf("event type %s count=%d all=%v", eventType, types[eventType], types)
		}
	}
	var attemptState, runState, jobState string
	var runVersion, jobVersion int64
	if err = verify.QueryRowContext(ctx, `SELECT a.status,r.status,r.version,j.desired_state,j.version
FROM attempts a JOIN runs r ON r.tenant_id=a.tenant_id AND r.project_id=a.project_id AND r.id=a.run_id
JOIN jobs j ON j.tenant_id=r.tenant_id AND j.project_id=r.project_id AND j.id=r.job_id
WHERE a.tenant_id=$1 AND a.project_id=$2 AND a.id=$3`, identity.TenantID, identity.ProjectID, lease.Attempt.GetAttemptId()).Scan(&attemptState, &runState, &runVersion, &jobState, &jobVersion); err != nil {
		t.Fatal(err)
	}
	if attemptState != "COMPLETED" || runState != "SUCCEEDED" || jobState != "SUCCEEDED" || runVersion != 3 || jobVersion != 3 {
		t.Fatalf("attempt=%s run=%s/v%d job=%s/v%d", attemptState, runState, runVersion, jobState, jobVersion)
	}
	if _, err = verify.ExecContext(ctx, `UPDATE inference_results SET source_revision='tampered' WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, result.GetName()); err == nil {
		t.Fatal("immutable inference result update unexpectedly succeeded")
	}
}
