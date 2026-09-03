package evaluations

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
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

func integrationArtifact(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(seed, 64), MediaType: "application/vnd.mindclade.integration+json", SizeBytes: 128, ArtifactKind: "integration", SchemaId: "mindclade.integration.v1", IntegrityDigest: "sha256:" + strings.Repeat(seed, 64), SchemaVersion: "1"}
}

func TestPostgresEvaluationJourneyIsNormalizedFencedIdempotentAndEventBacked(t *testing.T) {
	db := integrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "eval-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("evaluation-integration-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	at := time.Now().UTC().Truncate(time.Microsecond)
	project := projectParent(identity)
	request := &internalevaluationv1.CreateEvaluationRunRequest{Context: &commonv1.CommandContext{RequestId: "eval-create-request", IdempotencyKey: "eval-create-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(at.Add(time.Minute))}, Parent: project, EvaluationRunId: "qualification", Suite: integrationArtifact("a"), Datasets: []*artifactv1.ArtifactRef{integrationArtifact("b"), integrationArtifact("c")}, Snapshot: integrationArtifact("d"), ModelRelease: &commonv1.ResourceRef{ResourceType: "model_release", ResourceId: "release-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 3, Name: project + "/modelReleases/release-1", Etag: "sha256:" + strings.Repeat("e", 64)}, InferenceProtocol: integrationArtifact("f"), ExecutablePlan: integrationArtifact("1"), ProviderManifest: integrationArtifact("2"), KernelQualification: integrationArtifact("3"), PolicySnapshots: []*policyv1.PolicyReference{{Name: project + "/policies/evaluation", Uid: "policy-1", PolicyType: "evaluation", Version: "1.0.0", Digest: "sha256:" + strings.Repeat("4", 64), Document: integrationArtifact("4"), ResourceRevision: 7, EffectiveTime: timestamppb.New(at.Add(-time.Hour)), Classification: "internal"}}}
	digest, err := canonicalDigest(request)
	if err != nil {
		t.Fatal(err)
	}
	request.Context.CanonicalRequestDigest = digest
	operation, replay, err := repository.CreateRun(ctx, identity, request, digest, at)
	if err != nil || replay {
		t.Fatalf("create operation=%v replay=%v err=%v", operation, replay, err)
	}
	replayed, replay, err := repository.CreateRun(ctx, identity, clone(request), digest, at.Add(time.Second))
	if err != nil || !replay || replayed.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("replay operation=%v replay=%v err=%v", replayed, replay, err)
	}
	run, err := repository.GetRun(ctx, identity, project+"/evaluationRuns/qualification")
	if err != nil {
		t.Fatal(err)
	}
	if run.GetRequestDigest() != digest || len(run.GetDatasets()) != 2 || !proto.Equal(run.GetPolicySnapshots()[0], request.GetPolicySnapshots()[0]) || run.GetExecutablePlan().GetDigest() != request.GetExecutablePlan().GetDigest() {
		t.Fatalf("normalized run round trip lost state: %v", run)
	}
	listed, next, _, err := repository.ListRuns(ctx, identity, RunPage{Limit: 1, Order: "create_time desc,name desc"})
	if err != nil || len(listed) != 1 || next != "" {
		t.Fatalf("list=%v next=%q err=%v", listed, next, err)
	}
	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var schedulerRunID string
	if err = readTx.QueryRowContext(ctx, `SELECT scheduler_run_id FROM evaluation_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, run.GetName()).Scan(&schedulerRunID); err != nil {
		t.Fatal(err)
	}
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}
	token := strings.Repeat("lease-token-", 4)
	leaseAt := at.Add(2 * time.Second)
	lease, err := (jobs.SQLRepository{DB: db}).AcquireLeaseSQL(ctx, jobs.AcquireLeaseCommand{TenantID: identity.TenantID, RunID: schedulerRunID, AttemptID: "attempts/eval-1", WorkerID: "worker-1", Token: token, TokenKeyID: "key-1", Duration: time.Minute, Now: leaseAt, Command: jobs.RunCommandMetadata{TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal, WorkerID: "worker-1", Action: "run.acquire_lease", IdempotencyKey: "acquire-eval-1", RequestDigest: "sha256:" + strings.Repeat("5", 64), ObservedAt: leaseAt}})
	if err != nil {
		t.Fatal(err)
	}
	lower, upper := 0.80, 0.95
	result := &evaluationv1.EvaluationResult{Name: resultName(identity, "result-1"), Uid: "eval-result-1", Run: &commonv1.ResourceRef{ResourceType: "evaluation_run", ResourceId: "qualification", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: run.GetRevision(), Name: run.GetName(), Etag: run.GetEtag()}, RunDigest: "sha256:" + strings.Repeat("6", 64), Outcome: evaluationv1.EvaluationResultOutcome_EVALUATION_RESULT_OUTCOME_PASSED, Report: integrationArtifact("7"), Suite: clone(request.GetSuite()), Snapshot: clone(request.GetSnapshot()), DatasetManifest: integrationArtifact("8"), InferenceProtocol: clone(request.GetInferenceProtocol()), Metrics: []*evaluationv1.MetricSummary{{MetricId: "accuracy", MetricVersion: "1", Unit: "ratio", Direction: evaluationv1.MetricDirection_METRIC_DIRECTION_HIGHER_IS_BETTER, Value: 0.9, IntervalLower: &lower, IntervalUpper: &upper, ValidCount: 200, InvalidCount: 2, CohortId: "all"}}, Thresholds: []*evaluationv1.ThresholdOutcome{{RuleId: "accuracy-min", MetricId: "accuracy", Result: evaluationv1.ThresholdResult_THRESHOLD_RESULT_PASS, ReasonCode: "met", Evidence: integrationArtifact("9")}}, FailureCounts: []*evaluationv1.EvaluationFailureCount{{FailureClass: "invalid-input", Count: 2}}, LeakageEvidence: integrationArtifact("a"), SafetyEvidence: integrationArtifact("b"), StatisticalEvidence: integrationArtifact("c"), PerformanceEvidence: integrationArtifact("d"), SourceRevision: "git:abc123", FinalizedAt: timestamppb.New(at.Add(3 * time.Second)), ResultDigest: "sha256:" + strings.Repeat("e", 64)}
	commit := &internalevaluationv1.CommitEvaluationResultRequest{Context: &commonv1.CommandContext{RequestId: "eval-commit-request", IdempotencyKey: "eval-commit-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(at.Add(30 * time.Second))}, EvaluationRun: clone(result.GetRun()), Fence: clone(lease.Fence), Result: result, Etag: run.GetEtag()}
	commitDigest, err := canonicalDigest(commit)
	if err != nil {
		t.Fatal(err)
	}
	commit.Context.CanonicalRequestDigest = commitDigest
	workerIdentity := Identity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal, WorkerID: "worker-1", LeaseToken: "wrong-" + token}
	if _, _, _, err = repository.CommitResult(ctx, workerIdentity, commit, commitDigest, at.Add(3*time.Second)); !errors.Is(err, ErrLeaseToken) {
		t.Fatalf("wrong token err=%v", err)
	}
	workerIdentity.LeaseToken = token
	storedResult, completed, replayedResult, err := repository.CommitResult(ctx, workerIdentity, commit, commitDigest, at.Add(3*time.Second))
	if err != nil || replayedResult {
		t.Fatalf("commit result=%v run=%v replay=%v err=%v", storedResult, completed, replayedResult, err)
	}
	if !proto.Equal(storedResult, result) || completed.GetState() != evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_SUCCEEDED || completed.GetAttemptId() != lease.Attempt.GetAttemptId() {
		t.Fatalf("terminal roundtrip result=%v run=%v", storedResult, completed)
	}
	storedResult2, completed2, replayedResult, err := repository.CommitResult(ctx, workerIdentity, clone(commit), commitDigest, at.Add(4*time.Second))
	if err != nil || !replayedResult || !proto.Equal(storedResult2, result) || completed2.GetRevision() != completed.GetRevision() {
		t.Fatalf("terminal replay result=%v run=%v replay=%v err=%v", storedResult2, completed2, replayedResult, err)
	}
	promotionAt := at.Add(5 * time.Second)
	candidate := clone(request.GetModelRelease())
	evaluationResultRef := &commonv1.ResourceRef{ResourceType: "evaluation_result", ResourceId: "result-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: result.GetName(), Etag: result.GetResultDigest()}
	authorization := &policyv1.AuthorizationDecision{
		Name: project + "/authorizationDecisions/promotion-1", Uid: "authorization-promotion-1",
		TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalRef: identity.Principal,
		Action: "model.release.promote", Resource: clone(candidate), IntentDigest: "sha256:" + strings.Repeat("1", 64),
		Policies: cloneSlice(request.GetPolicySnapshots()), Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW,
		ReasonCode: "policy-allow", SafeReason: "all promotion policies passed",
		Constraints: []*policyv1.AuthorizationConstraint{{Kind: "target-profile", DetailsDigest: "sha256:" + strings.Repeat("2", 64), ExpireTime: timestamppb.New(promotionAt.Add(time.Hour))}},
		EvaluatedAt: timestamppb.New(promotionAt), ExpireTime: timestamppb.New(promotionAt.Add(time.Hour)),
		ContextDigest: "sha256:" + strings.Repeat("3", 64), DecisionDigest: "sha256:" + strings.Repeat("4", 64),
	}
	decision := &evaluationv1.PromotionDecision{
		Name: decisionName(identity, "promotion-1"), Uid: "promotion-1", CandidateRelease: candidate,
		CandidateDigest: "sha256:" + strings.Repeat("5", 64), TargetProfile: "staging",
		EvaluationResults: []*commonv1.ResourceRef{evaluationResultRef},
		Rules:             []*evaluationv1.PromotionRuleDecision{{RuleId: "accuracy-min", Result: evaluationv1.ThresholdResult_THRESHOLD_RESULT_PASS, ReasonCode: "met", Evidence: integrationArtifact("6")}},
		Exceptions:        []*evaluationv1.PromotionException{{ExceptionId: "exception-1", RuleId: "latency-advisory", Rationale: integrationArtifact("7"), ApprovalReceipts: []*commonv1.ResourceRef{{ResourceType: "approval", ResourceId: "approval-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: project + "/approvals/approval-1", Etag: "sha256:" + strings.Repeat("8", 64)}}, ExpireTime: timestamppb.New(promotionAt.Add(30 * time.Minute))}},
		PolicyDecisions:   []*policyv1.AuthorizationDecision{authorization}, Outcome: evaluationv1.PromotionOutcome_PROMOTION_OUTCOME_APPROVE,
		ReasonCode: "qualification-passed", SafeReason: "qualification evidence passed", DecidedByPrincipalRef: identity.Principal,
		DecidedAt: timestamppb.New(promotionAt), ExpireTime: timestamppb.New(promotionAt.Add(time.Hour)), SourceRevision: "git:def456", DecisionDigest: "sha256:" + strings.Repeat("9", 64),
	}
	promotion := &internalevaluationv1.CreatePromotionDecisionRequest{Context: &commonv1.CommandContext{RequestId: "promotion-create-request", IdempotencyKey: "promotion-create-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(promotionAt.Add(time.Minute))}, PromotionDecision: decision}
	promotionDigest, err := canonicalDigest(promotion)
	if err != nil {
		t.Fatal(err)
	}
	promotion.Context.CanonicalRequestDigest = promotionDigest
	promotionOperation, replayedPromotion, err := repository.CreatePromotionDecision(ctx, identity, promotion, promotionDigest, promotionAt)
	if err != nil || replayedPromotion || !promotionOperation.GetDone() {
		t.Fatalf("promotion operation=%v replay=%v err=%v", promotionOperation, replayedPromotion, err)
	}
	promotionReplay, replayedPromotion, err := repository.CreatePromotionDecision(ctx, identity, clone(promotion), promotionDigest, promotionAt.Add(time.Second))
	if err != nil || !replayedPromotion || promotionReplay.GetOperationId() != promotionOperation.GetOperationId() {
		t.Fatalf("promotion replay operation=%v replay=%v err=%v", promotionReplay, replayedPromotion, err)
	}
	persistedDecision, err := repository.GetPromotionDecision(ctx, identity, decision.GetName())
	if err != nil || !proto.Equal(persistedDecision, decision) {
		t.Fatalf("promotion roundtrip=%v err=%v", persistedDecision, err)
	}
	cancelCreateAt := promotionAt.Add(2 * time.Second)
	cancelCreate := clone(request)
	cancelCreate.Context = &commonv1.CommandContext{RequestId: "cancel-run-create-request", IdempotencyKey: "cancel-run-create-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(cancelCreateAt.Add(time.Minute))}
	cancelCreate.EvaluationRunId = "cancelled-qualification"
	cancelCreateDigest, err := canonicalDigest(cancelCreate)
	if err != nil {
		t.Fatal(err)
	}
	cancelCreate.Context.CanonicalRequestDigest = cancelCreateDigest
	if _, replayedCancelCreate, createErr := repository.CreateRun(ctx, identity, cancelCreate, cancelCreateDigest, cancelCreateAt); createErr != nil || replayedCancelCreate {
		t.Fatalf("cancel-target create replay=%v err=%v", replayedCancelCreate, createErr)
	}
	cancelTarget, err := repository.GetRun(ctx, identity, runName(identity, cancelCreate.GetEvaluationRunId()))
	if err != nil {
		t.Fatal(err)
	}
	cancelAt := cancelCreateAt.Add(time.Second)
	cancelRequest := &internalevaluationv1.CancelEvaluationRunRequest{Context: &commonv1.CommandContext{RequestId: "cancel-run-request", IdempotencyKey: "cancel-run-key", TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, Deadline: timestamppb.New(cancelAt.Add(time.Minute))}, Name: cancelTarget.GetName(), Etag: cancelTarget.GetEtag(), Reason: "operator requested bounded cancellation"}
	cancelDigest, err := canonicalDigest(cancelRequest)
	if err != nil {
		t.Fatal(err)
	}
	cancelRequest.Context.CanonicalRequestDigest = cancelDigest
	cancelOperation, replayedCancel, err := repository.CancelRun(ctx, identity, cancelRequest, cancelDigest, cancelAt)
	if err != nil || replayedCancel || cancelOperation.GetState() != jobv1.OperationState_OPERATION_STATE_CANCELLING {
		t.Fatalf("cancel operation=%v replay=%v err=%v", cancelOperation, replayedCancel, err)
	}
	cancelReplay, replayedCancel, err := repository.CancelRun(ctx, identity, clone(cancelRequest), cancelDigest, cancelAt.Add(time.Second))
	if err != nil || !replayedCancel || cancelReplay.GetOperationId() != cancelOperation.GetOperationId() {
		t.Fatalf("cancel replay operation=%v replay=%v err=%v", cancelReplay, replayedCancel, err)
	}
	cancellingRun, err := repository.GetRun(ctx, identity, cancelTarget.GetName())
	if err != nil || cancellingRun.GetState() != evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_CANCELLING || cancellingRun.GetRevision() != cancelTarget.GetRevision()+1 {
		t.Fatalf("cancelling run=%v err=%v", cancellingRun, err)
	}
	verify, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	var events, audits, receipts int
	if err = verify.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM outbox_messages WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1),(SELECT count(*) FROM evaluation_inference_command_receipts WHERE tenant_id=$1)`, identity.TenantID).Scan(&events, &audits, &receipts); err != nil {
		t.Fatal(err)
	}
	if events != 8 || audits != 5 || receipts != 5 {
		t.Fatalf("events=%d audits=%d receipts=%d", events, audits, receipts)
	}
	rows, err := verify.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,event_type`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	types := map[string]int{}
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
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
	for eventType, count := range map[string]int{"mindclade.events.evaluation.v1.EvaluationRunCreated": 2, "mindclade.events.evaluation.v1.EvaluationCancellationRequested": 1, "mindclade.events.evaluation.v1.EvaluationResultCommitted": 1, "mindclade.events.evaluation.v1.PromotionDecisionRecorded": 1, "mindclade.events.job.v1.JobRequested": 2, "mindclade.events.job.v1.AttemptLeased": 1} {
		if types[eventType] != count {
			t.Fatalf("event type %s count=%d want=%d all=%v", eventType, types[eventType], count, types)
		}
	}
	if err = verify.Commit(); err != nil {
		t.Fatal(err)
	}
	assertEvaluationRLS(t, ctx, db, suffix, identity, 2, 1)
	tamper, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tamper.ExecContext(ctx, `UPDATE evaluation_results SET source_revision='tampered' WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, result.GetName()); err == nil {
		t.Fatal("immutable evaluation result update unexpectedly succeeded")
	}
	_ = tamper.Rollback()
}

func assertEvaluationRLS(t *testing.T, ctx context.Context, db *sql.DB, suffix string, identity Identity, runCount, decisionCount int) {
	t.Helper()
	var superuser, bypassRLS, createRole bool
	if err := db.QueryRowContext(ctx, `SELECT rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user`).Scan(&superuser, &bypassRLS, &createRole); err != nil {
		t.Fatal(err)
	}
	role := ""
	if superuser || bypassRLS {
		if !createRole {
			t.Fatal("PostgreSQL integration identity bypasses RLS and cannot create a non-bypass qualification role")
		}
		role = "mindclade_eval_rls_" + suffix
		if _, err := db.ExecContext(ctx, fmt.Sprintf(`CREATE ROLE %s NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`, role)); err != nil {
			t.Fatal(err)
		}
		cleanupContext := context.WithoutCancel(ctx)
		t.Cleanup(func() {
			if _, cleanupErr := db.ExecContext(cleanupContext, `DROP OWNED BY `+role+`; DROP ROLE `+role); cleanupErr != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
				t.Errorf("drop evaluation RLS role: %v", cleanupErr)
			}
		})
		if _, err := db.ExecContext(ctx, `GRANT SELECT ON evaluation_runs,promotion_decisions TO `+role); err != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
			t.Fatal(err)
		}
	}
	var forced int
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(ARRAY['policy_snapshot_references','authorization_decisions','authorization_decision_policies','authorization_decision_constraints','evaluation_runs','evaluation_run_datasets','evaluation_run_policies','evaluation_results','evaluation_result_metrics','evaluation_result_thresholds','evaluation_result_failure_counts','promotion_decisions','promotion_decision_results','promotion_decision_rules','promotion_decision_exceptions','promotion_exception_approvals','promotion_decision_authorizations','inference_requests','inference_request_output_kinds','inference_request_policies','inference_results','inference_result_candidates','inference_result_authorizations','evaluation_inference_command_receipts']) AND relrowsecurity AND relforcerowsecurity`).Scan(&forced); err != nil || forced != 24 {
		t.Fatalf("evaluation/inference FORCE RLS count=%d err=%v", forced, err)
	}
	tx, err := db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if role != "" {
		if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE `+role); err != nil { // #nosec G202 -- role is constructed solely from a fixed prefix and decimal timestamp digits.
			t.Fatal(err)
		}
	}
	var visible int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM evaluation_runs`).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("unbound RLS scope visible=%d err=%v", visible, err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id',$1,true),set_config('row_security','on',true)`, identity.TenantID); err != nil {
		t.Fatal(err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM evaluation_runs WHERE project_id=$1`, identity.ProjectID).Scan(&visible); err != nil || visible != runCount {
		t.Fatalf("bound evaluation runs visible=%d want=%d err=%v", visible, runCount, err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM promotion_decisions WHERE project_id=$1`, identity.ProjectID).Scan(&visible); err != nil || visible != decisionCount {
		t.Fatalf("bound promotion decisions visible=%d want=%d err=%v", visible, decisionCount, err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM evaluation_runs WHERE tenant_id='different-tenant'`).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("cross-tenant evaluation rows visible=%d err=%v", visible, err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
}
