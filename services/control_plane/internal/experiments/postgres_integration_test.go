package experiments

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var experimentEventTypes = []string{
	"mindclade.events.experiment.v1.ExperimentCreated",
	"mindclade.events.experiment.v1.ExperimentUpdated",
	"mindclade.events.experiment.v1.ExperimentStateChanged",
	"mindclade.events.experiment.v1.StudyCreated",
	"mindclade.events.experiment.v1.StudyStateChanged",
	"mindclade.events.experiment.v1.TrialCreated",
	"mindclade.events.experiment.v1.TrialStateChanged",
	"mindclade.events.experiment.v1.TrialCompleted",
}

func experimentIntegrationDB(t *testing.T) *sql.DB {
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

func TestPostgresExperimentVerticalRoundTripLifecycleIdempotencyAndEvents(t *testing.T) {
	db := experimentIntegrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "experiment-tenant-" + suffix, ProjectID: "project", Principal: "principal"}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("experiment-integration-key", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Pagination: codec, Events: GeneratedEventFactory{}}
	t.Cleanup(func() { cleanupExperimentTenant(t, db, identity.TenantID) })

	at := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	project := &commonv1.ResourceRef{ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, Name: projectParent(identity)}
	usePolicy := referenceFixture(identity, "use_policy", "policy", projectParent(identity)+"/usePolicies/policy", 3)
	subject := referenceFixture(identity, "dataset_release", "dataset-v1", projectParent(identity)+"/datasets/pdb/releases/v1", 7)
	create := &experimentv1.CreateExperimentCommand{
		Context: commandContext(identity, "experiment-create", "experiment-create-key"), Project: project,
		ExperimentId: "quality", DisplayName: "Quality study", Kind: experimentv1.ExperimentKind_EXPERIMENT_KIND_SCIENTIFIC,
		IntentManifest: artifactFixture("1"), Subjects: []*commonv1.ResourceRef{subject}, UsePolicy: usePolicy,
		PolicyClassification: "INTERNAL", Labels: map[string]string{"owner": "science"}, Annotations: map[string]string{"purpose": "non-clinical"},
	}
	createDigest := sealCommand(t, create, create.GetContext())
	experiment, replay, err := repository.CreateExperiment(ctx, identity, create, createDigest, at)
	if err != nil || replay {
		t.Fatalf("create experiment replay=%v err=%v", replay, err)
	}
	if experiment.GetState() != experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT || experiment.GetIntentManifest().GetDigest() != create.GetIntentManifest().GetDigest() || !proto.Equal(experiment.GetSubjects()[0], subject) || experiment.GetLabels()["owner"] != "science" {
		t.Fatalf("experiment protobuf round trip lost state: %v", experiment)
	}
	if _, replay, err = repository.CreateExperiment(ctx, identity, clone(create), createDigest, at.Add(time.Second)); err != nil || !replay {
		t.Fatalf("create replay=%v err=%v", replay, err)
	}
	conflict := clone(create)
	conflict.DisplayName = "different"
	conflict.Context.CanonicalRequestDigest = ""
	conflictDigest := sealCommand(t, conflict, conflict.GetContext())
	if _, _, err = repository.CreateExperiment(ctx, identity, conflict, conflictDigest, at.Add(2*time.Second)); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("idempotency conflict error=%v", err)
	}

	update := &experimentv1.UpdateExperimentCommand{
		Context:    commandContext(identity, "experiment-update", "experiment-update-key"),
		Experiment: clone(experiment), UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name", "labels", "annotations"}}, Etag: experiment.GetEtag(),
	}
	update.Experiment.DisplayName = "Quality campaign"
	update.Experiment.Labels = map[string]string{"owner": "platform", "tier": "candidate"}
	update.Experiment.Annotations = map[string]string{"purpose": "bounded-computational"}
	updateDigest := sealCommand(t, update, update.GetContext())
	experiment, _, err = repository.UpdateExperiment(ctx, identity, update, updateDigest, at.Add(3*time.Second))
	if err != nil || experiment.GetRevision() != 2 || experiment.GetDisplayName() != "Quality campaign" || len(experiment.GetLabels()) != 2 {
		t.Fatalf("updated experiment=%v err=%v", experiment, err)
	}
	stale := clone(update)
	stale.Context = commandContext(identity, "experiment-stale", "experiment-stale-key")
	staleDigest := sealCommand(t, stale, stale.GetContext())
	if _, _, err = repository.UpdateExperiment(ctx, identity, stale, staleDigest, at.Add(4*time.Second)); !errors.Is(err, ErrRevisionConflict) {
		t.Fatalf("stale update error=%v", err)
	}

	activate := &experimentv1.TransitionExperimentCommand{Context: commandContext(identity, "experiment-activate", "experiment-activate-key"), Experiment: resourceForExperiment(experiment), ExpectedState: experiment.GetState(), TargetState: experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE, Etag: experiment.GetEtag(), ReasonCode: "INTENT_APPROVED"}
	activateDigest := sealCommand(t, activate, activate.GetContext())
	experiment, _, err = repository.TransitionExperiment(ctx, identity, activate, activateDigest, at.Add(5*time.Second))
	if err != nil || experiment.GetState() != experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE {
		t.Fatalf("activated experiment=%v err=%v", experiment, err)
	}

	createStudy := &experimentv1.CreateStudyCommand{
		Context: commandContext(identity, "study-create", "study-create-key"), Experiment: resourceForExperiment(experiment), StudyId: "search",
		Type: experimentv1.StudyType_STUDY_TYPE_SCIENTIFIC, StudyManifest: artifactFixture("2"), BaseConfiguration: artifactFixture("3"), SearchSpace: artifactFixture("4"), ObjectiveSpecification: artifactFixture("5"),
		Budget: &experimentv1.StudyBudget{MaximumTrials: 4, MaximumParallelTrials: 2, MaximumDuration: durationpb.New(6 * time.Hour)},
	}
	studyDigest := sealCommand(t, createStudy, createStudy.GetContext())
	study, _, err := repository.CreateStudy(ctx, identity, createStudy, studyDigest, at.Add(6*time.Second))
	if err != nil || study.GetBudget().GetMaximumTrials() != 4 || study.GetSearchSpace().GetDigest() != createStudy.GetSearchSpace().GetDigest() {
		t.Fatalf("created study=%v err=%v", study, err)
	}
	startStudy := &experimentv1.TransitionStudyCommand{Context: commandContext(identity, "study-start", "study-start-key"), Study: resourceForStudy(study), ExpectedState: study.GetState(), TargetState: experimentv1.StudyState_STUDY_STATE_RUNNING, Etag: study.GetEtag(), ReasonCode: "ADMISSION_OPEN"}
	startStudyDigest := sealCommand(t, startStudy, startStudy.GetContext())
	study, _, err = repository.TransitionStudy(ctx, identity, startStudy, startStudyDigest, at.Add(7*time.Second))
	if err != nil || study.GetStartTime() == nil {
		t.Fatalf("started study=%v err=%v", study, err)
	}

	trial := createAndStartTrial(t, ctx, repository, identity, study, "trial-a", 1, at.Add(8*time.Second))
	result := artifactFixture("6")
	evidence := &artifactv1.EvidenceRef{Digest: digestFixture("7"), SubjectDigest: result.GetDigest(), EvidenceKind: "evaluation", PolicyDigest: digestFixture("8")}
	complete := &experimentv1.CompleteTrialCommand{Context: commandContext(identity, "trial-complete", "trial-complete-key"), Trial: resourceForTrial(trial), Outcome: experimentv1.TrialOutcome_TRIAL_OUTCOME_SUCCEEDED, ResultManifest: result, Evidence: []*artifactv1.EvidenceRef{evidence}, Etag: trial.GetEtag()}
	completeDigest := sealCommand(t, complete, complete.GetContext())
	trial, _, err = repository.CompleteTrial(ctx, identity, complete, completeDigest, at.Add(11*time.Second))
	if err != nil || trial.GetState() != experimentv1.TrialState_TRIAL_STATE_COMPLETED || !proto.Equal(trial.GetResultManifest(), result) || !proto.Equal(trial.GetEvidence()[0], evidence) || trial.GetElapsedTime() == nil {
		t.Fatalf("completed trial=%v err=%v", trial, err)
	}

	failed := createAndStartTrial(t, ctx, repository, identity, study, "trial-b", 2, at.Add(12*time.Second))
	failure := &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_FAILED_PRECONDITION, Message: "objective constraint failed", RetryClass: commonv1.RetryClass_RETRY_CLASS_NEVER, ErrorId: "failure-1", FieldViolations: []*commonv1.FieldViolation{{Field: "objective", Description: "outside bound"}}}
	fail := &experimentv1.CompleteTrialCommand{Context: commandContext(identity, "trial-fail", "trial-fail-key"), Trial: resourceForTrial(failed), Outcome: experimentv1.TrialOutcome_TRIAL_OUTCOME_FAILED, Error: failure, Etag: failed.GetEtag()}
	failDigest := sealCommand(t, fail, fail.GetContext())
	failed, _, err = repository.CompleteTrial(ctx, identity, fail, failDigest, at.Add(15*time.Second))
	if err != nil || failed.GetState() != experimentv1.TrialState_TRIAL_STATE_FAILED || !proto.Equal(failed.GetError(), failure) {
		t.Fatalf("failed trial=%v err=%v", failed, err)
	}

	study, err = repository.GetStudy(ctx, identity, study.GetName())
	if err != nil || study.GetAdmittedTrialCount() != 2 || study.GetCompletedTrialCount() != 2 {
		t.Fatalf("derived study counters=%v err=%v", study, err)
	}
	finishStudy := &experimentv1.TransitionStudyCommand{Context: commandContext(identity, "study-complete", "study-complete-key"), Study: resourceForStudy(study), ExpectedState: study.GetState(), TargetState: experimentv1.StudyState_STUDY_STATE_COMPLETED, Etag: study.GetEtag(), ReasonCode: "TRIALS_TERMINAL"}
	finishStudyDigest := sealCommand(t, finishStudy, finishStudy.GetContext())
	study, _, err = repository.TransitionStudy(ctx, identity, finishStudy, finishStudyDigest, at.Add(16*time.Second))
	if err != nil || study.GetCompleteTime() == nil {
		t.Fatalf("completed study=%v err=%v", study, err)
	}
	finishExperiment := &experimentv1.TransitionExperimentCommand{Context: commandContext(identity, "experiment-complete", "experiment-complete-key"), Experiment: resourceForExperiment(experiment), ExpectedState: experiment.GetState(), TargetState: experimentv1.ExperimentState_EXPERIMENT_STATE_COMPLETED, Etag: experiment.GetEtag(), ReasonCode: "STUDIES_TERMINAL"}
	finishExperimentDigest := sealCommand(t, finishExperiment, finishExperiment.GetContext())
	experiment, _, err = repository.TransitionExperiment(ctx, identity, finishExperiment, finishExperimentDigest, at.Add(17*time.Second))
	if err != nil || experiment.GetCompleteTime() == nil {
		t.Fatalf("completed experiment=%v err=%v", experiment, err)
	}

	experiment.DisplayName = "caller mutation"
	stored, err := repository.GetExperiment(ctx, identity, experiment.GetName())
	if err != nil || stored.GetDisplayName() == experiment.GetDisplayName() {
		t.Fatalf("repository leaked mutable protobuf alias: stored=%v err=%v", stored, err)
	}
	verifyExperimentEventsAndIsolation(t, ctx, db, identity)
}

func createAndStartTrial(t *testing.T, ctx context.Context, repository SQLRepository, identity Identity, study *experimentv1.Study, id string, number uint32, at time.Time) *experimentv1.Trial {
	t.Helper()
	create := &experimentv1.CreateTrialCommand{Context: commandContext(identity, id+"-create", id+"-create-key"), Study: resourceForStudy(study), TrialId: id, TrialNumber: number, ResolvedConfiguration: artifactFixture(strconv.FormatUint(uint64(number), 10)), Execution: referenceFixture(identity, "run", id+"-run", projectParent(identity)+"/runs/"+id, 1)}
	digest := sealCommand(t, create, create.GetContext())
	trial, _, err := repository.CreateTrial(ctx, identity, create, digest, at)
	if err != nil {
		t.Fatal(err)
	}
	admit := &experimentv1.TransitionTrialCommand{Context: commandContext(identity, id+"-admit", id+"-admit-key"), Trial: resourceForTrial(trial), ExpectedState: trial.GetState(), TargetState: experimentv1.TrialState_TRIAL_STATE_ADMITTED, Etag: trial.GetEtag(), ReasonCode: "CAPACITY_GRANTED"}
	digest = sealCommand(t, admit, admit.GetContext())
	trial, _, err = repository.TransitionTrial(ctx, identity, admit, digest, at.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	start := &experimentv1.TransitionTrialCommand{Context: commandContext(identity, id+"-start", id+"-start-key"), Trial: resourceForTrial(trial), ExpectedState: trial.GetState(), TargetState: experimentv1.TrialState_TRIAL_STATE_RUNNING, Etag: trial.GetEtag(), ReasonCode: "WORKER_STARTED"}
	digest = sealCommand(t, start, start.GetContext())
	trial, _, err = repository.TransitionTrial(ctx, identity, start, digest, at.Add(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	return trial
}

func verifyExperimentEventsAndIsolation(t *testing.T, ctx context.Context, db *sql.DB, identity Identity) {
	t.Helper()
	tx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	rows, err := tx.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 ORDER BY created_at,id`, identity.TenantID)
	if err != nil {
		t.Fatal(err)
	}
	seen := make(map[string]int)
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := queue.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		if _, decodeErr = queue.UnmarshalRegisteredPayload(envelope); decodeErr != nil {
			t.Fatalf("registered event %s: %v", envelope.GetEventType(), decodeErr)
		}
		seen[envelope.GetEventType()]++
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	for _, eventType := range experimentEventTypes {
		if seen[eventType] == 0 {
			t.Fatalf("missing typed event %s in %v", eventType, seen)
		}
	}
	var receipts, audits int
	if err = tx.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM experiment_command_receipts WHERE tenant_id=$1),(SELECT count(*) FROM audit_events WHERE tenant_id=$1)`, identity.TenantID).Scan(&receipts, &audits); err != nil {
		t.Fatal(err)
	}
	if receipts != 15 || audits != 15 {
		t.Fatalf("receipts=%d audits=%d", receipts, audits)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	assertExperimentRLS(t, ctx, db, identity)
	immutable, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = immutable.ExecContext(ctx, `UPDATE experiment_trial_evidence SET evidence_kind='rewritten' WHERE tenant_id=$1`, identity.TenantID); err == nil {
		t.Fatal("immutable trial evidence accepted an update")
	}
	_ = immutable.Rollback()
}

func assertExperimentRLS(t *testing.T, ctx context.Context, db *sql.DB, identity Identity) {
	t.Helper()
	var superuser, bypassRLS, createRole bool
	if err := db.QueryRowContext(ctx, `SELECT rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user`).Scan(&superuser, &bypassRLS, &createRole); err != nil {
		t.Fatal(err)
	}
	role := ""
	if superuser || bypassRLS {
		if !superuser && !createRole {
			t.Fatal("PostgreSQL integration identity bypasses RLS and cannot create a non-bypass qualification role")
		}
		role = fmt.Sprintf("mindclade_experiment_rls_%d", time.Now().UTC().UnixNano())
		if _, err := db.ExecContext(ctx, `CREATE ROLE `+role+` NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`); err != nil { // #nosec G202 -- suffix is generated solely from decimal Unix nanoseconds.
			t.Fatal(err)
		}
		cleanupContext := context.WithoutCancel(ctx)
		t.Cleanup(func() {
			if _, err := db.ExecContext(cleanupContext, `DROP OWNED BY `+role+`; DROP ROLE `+role); err != nil { // #nosec G202 -- role is generated solely from a fixed prefix and decimal Unix nanoseconds.
				t.Errorf("drop experiment RLS probe role: %v", err)
			}
		})
		if _, err := db.ExecContext(ctx, `GRANT USAGE ON SCHEMA public TO `+role); err != nil { // #nosec G202 -- closed test-only role identifier.
			t.Fatal(err)
		}
		if _, err := db.ExecContext(ctx, `GRANT SELECT ON experiments,experiment_labels,experiment_annotations,experiment_subjects,experiment_studies,experiment_trials,experiment_trial_evidence,experiment_command_receipts TO `+role); err != nil { // #nosec G202 -- tables are a closed repository-owned set.
			t.Fatal(err)
		}
	}
	var forced int
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname = ANY(ARRAY['experiments','experiment_labels','experiment_annotations','experiment_subjects','experiment_studies','experiment_trials','experiment_trial_evidence','experiment_command_receipts']) AND relrowsecurity AND relforcerowsecurity`).Scan(&forced); err != nil || forced != 8 {
		t.Fatalf("experiment FORCE RLS count=%d err=%v", forced, err)
	}
	tx, err := db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback() }()
	if role != "" {
		if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE `+role); err != nil { // #nosec G202 -- closed test-only role identifier.
			t.Fatal(err)
		}
	}
	var visible int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiments`).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("unbound experiment RLS visible=%d err=%v", visible, err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id',$1,true),set_config('row_security','on',true)`, identity.TenantID); err != nil {
		t.Fatal(err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiments WHERE project_id=$1`, identity.ProjectID).Scan(&visible); err != nil || visible != 1 {
		t.Fatalf("bound experiment RLS visible=%d want=1 err=%v", visible, err)
	}
	if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id',$1,true)`, identity.TenantID+"-other"); err != nil {
		t.Fatal(err)
	}
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM experiments WHERE project_id=$1`, identity.ProjectID).Scan(&visible); err != nil || visible != 0 {
		t.Fatalf("cross-tenant experiment RLS visible=%d err=%v", visible, err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
}

func cleanupExperimentTenant(t *testing.T, db *sql.DB, tenantID string) {
	t.Helper()
	ctx := context.Background()
	tx, err := platformdb.BeginTenantTx(ctx, db, tenantID, nil)
	if err != nil {
		t.Errorf("cleanup begin: %v", err)
		return
	}
	defer func() { _ = tx.Rollback() }()
	for _, table := range []string{"experiment_command_receipts", "outbox_messages", "audit_events", "experiment_trial_evidence", "experiment_trials", "experiment_studies", "experiment_subjects", "experiment_annotations", "experiment_labels", "experiments", "error_precondition_violations", "error_field_violations", "error_details", "resource_references", "artifact_references"} {
		if _, err = tx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); err != nil { //nolint:gosec
			t.Errorf("cleanup %s: %v", table, err)
		}
	}
	if err = tx.Commit(); err != nil {
		t.Errorf("cleanup commit: %v", err)
	}
}

func commandContext(identity Identity, requestID, key string) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: requestID, IdempotencyKey: key, TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, TraceId: "trace-" + requestID, CorrelationId: "correlation-experiment"}
}

func sealCommand(t *testing.T, command proto.Message, context *commonv1.CommandContext) string {
	t.Helper()
	digest, err := canonicalCommandDigest(command)
	if err != nil {
		t.Fatal(err)
	}
	context.CanonicalRequestDigest = digest
	return digest
}

func digestFixture(seed string) string {
	if seed == "" {
		seed = "0"
	}
	return "sha256:" + strings.Repeat(seed[:1], 64)
}

func artifactFixture(seed string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: digestFixture(seed), MediaType: "application/json", SizeBytes: 128, ArtifactKind: "manifest", SchemaId: "mindclade.fixture", IntegrityDigest: digestFixture(seed), Uri: "gs://internal-fixtures/" + seed, SchemaVersion: "v1"}
}

func referenceFixture(identity Identity, kind, id, name string, revision int64) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: revision, Name: name, Etag: resourceETag(name, revision)}
}

func resourceForExperiment(value *experimentv1.Experiment) *commonv1.ResourceRef {
	return experimentResource(value)
}
func resourceForStudy(value *experimentv1.Study) *commonv1.ResourceRef { return studyResource(value) }
func resourceForTrial(value *experimentv1.Trial) *commonv1.ResourceRef { return trialResource(value) }
