package evaluations

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

type scanner interface{ Scan(...any) error }

func advisoryLockKey(parts ...string) string {
	var result strings.Builder
	for _, part := range parts {
		_, _ = fmt.Fprintf(&result, "%d:", len(part))
		result.WriteString(part)
	}
	return result.String()
}

func nullableTime(value *timestamppb.Timestamp) (sql.NullTime, error) {
	if value == nil {
		return sql.NullTime{}, nil
	}
	if err := value.CheckValid(); err != nil {
		return sql.NullTime{}, err
	}
	result := value.AsTime().UTC()
	if result.Nanosecond()%int(time.Microsecond) != 0 {
		return sql.NullTime{}, fmt.Errorf("%w: timestamp exceeds PostgreSQL microsecond precision", ErrInvalidArgument)
	}
	return sql.NullTime{Time: result, Valid: true}, nil
}

func timestamp(value sql.NullTime) *timestamppb.Timestamp {
	if !value.Valid {
		return nil
	}
	return timestamppb.New(value.Time.UTC())
}

func requireTimestamp(value *timestamppb.Timestamp, label string) (time.Time, error) {
	if value == nil || value.CheckValid() != nil {
		return time.Time{}, fmt.Errorf("%w: %s timestamp is required", ErrInvalidArgument, label)
	}
	result := value.AsTime().UTC()
	if result.Nanosecond()%int(time.Microsecond) != 0 {
		return time.Time{}, fmt.Errorf("%w: %s timestamp exceeds PostgreSQL microsecond precision", ErrInvalidArgument, label)
	}
	return result, nil
}

func storePolicySnapshot(ctx context.Context, tx *sql.Tx, tenantID string, value *policyv1.PolicyReference) (int64, error) {
	if err := validatePolicy(value); err != nil {
		return 0, err
	}
	lockKey := advisoryLockKey(tenantID, "policy-snapshot", value.GetName(), strconv.FormatInt(value.GetResourceRevision(), 10), value.GetDigest())
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return 0, err
	}
	var id int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, tenantID, value.GetName(), value.GetResourceRevision(), value.GetDigest()).Scan(&id)
	if err == nil {
		persisted, loadErr := loadPolicySnapshot(ctx, tx, tenantID, id)
		if loadErr != nil {
			return 0, loadErr
		}
		if !proto.Equal(persisted, value) {
			return 0, ErrIdempotencyConflict
		}
		return id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	documentID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetDocument())
	if err != nil {
		return 0, err
	}
	effective, _ := requireTimestamp(value.GetEffectiveTime(), "policy effective")
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	err = tx.QueryRowContext(ctx, `INSERT INTO policy_snapshot_references(tenant_id,name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`, tenantID, value.GetName(), value.GetUid(), value.GetPolicyType(), value.GetVersion(), value.GetDigest(), documentID, value.GetResourceRevision(), effective, expiry, value.GetClassification()).Scan(&id)
	if err != nil {
		return 0, err
	}
	persisted, err := loadPolicySnapshot(ctx, tx, tenantID, id)
	if err != nil {
		return 0, err
	}
	if !proto.Equal(persisted, value) {
		return 0, ErrIdempotencyConflict
	}
	return id, nil
}

func loadPolicySnapshot(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.PolicyReference, error) {
	var value policyv1.PolicyReference
	var documentID int64
	var effective time.Time
	var expiry sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification FROM policy_snapshot_references WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&value.Name, &value.Uid, &value.PolicyType, &value.Version, &value.Digest, &documentID, &value.ResourceRevision, &effective, &expiry, &value.Classification)
	if err != nil {
		return nil, err
	}
	value.Document, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, sql.NullInt64{Int64: documentID, Valid: true})
	if err != nil {
		return nil, err
	}
	value.EffectiveTime, value.ExpireTime = timestamppb.New(effective.UTC()), timestamp(expiry)
	return &value, nil
}

func storeAuthorizationDecision(ctx context.Context, tx *sql.Tx, identity Identity, value *policyv1.AuthorizationDecision) (int64, error) {
	if value == nil || value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetName() == "" || value.GetUid() == "" || value.GetPrincipalRef() == "" || value.GetAction() == "" || value.GetOutcome() == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_UNSPECIFIED || value.GetReasonCode() == "" || !validSHA256(value.GetIntentDigest()) || !validSHA256(value.GetContextDigest()) || !validSHA256(value.GetDecisionDigest()) || len(value.GetPolicies()) == 0 || len(value.GetPolicies()) > 64 || len(value.GetConstraints()) > 64 {
		return 0, ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetResource(), "authorization resource"); err != nil {
		return 0, err
	}
	lockKey := advisoryLockKey(identity.TenantID, "authorization-decision", value.GetName())
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, lockKey); err != nil {
		return 0, err
	}
	var id int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM authorization_decisions WHERE tenant_id=$1 AND name=$2`, identity.TenantID, value.GetName()).Scan(&id)
	if err == nil {
		persisted, loadErr := loadAuthorizationDecision(ctx, tx, identity.TenantID, id)
		if loadErr != nil {
			return 0, loadErr
		}
		if !proto.Equal(persisted, value) {
			return 0, ErrIdempotencyConflict
		}
		return id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return 0, err
	}
	evaluated, err := requireTimestamp(value.GetEvaluatedAt(), "authorization evaluated_at")
	if err != nil {
		return 0, err
	}
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetResource())
	if err != nil {
		return 0, err
	}
	err = tx.QueryRowContext(ctx, `INSERT INTO authorization_decisions(tenant_id,name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) RETURNING id`, identity.TenantID, value.GetName(), value.GetUid(), identity.ProjectID, value.GetPrincipalRef(), value.GetAction(), resourceID, value.GetIntentDigest(), int32(value.GetOutcome()), value.GetReasonCode(), value.GetSafeReason(), evaluated, expiry, value.GetContextDigest(), value.GetDecisionDigest()).Scan(&id)
	if err != nil {
		return 0, err
	}
	for ordinal, policy := range value.GetPolicies() {
		policyID, storeErr := storePolicySnapshot(ctx, tx, identity.TenantID, policy)
		if storeErr != nil {
			return 0, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO authorization_decision_policies(tenant_id,decision_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4)`, identity.TenantID, id, ordinal, policyID); storeErr != nil {
			return 0, storeErr
		}
	}
	for ordinal, constraint := range value.GetConstraints() {
		if constraint == nil || constraint.GetKind() == "" || !validSHA256(constraint.GetDetailsDigest()) {
			return 0, ErrInvalidArgument
		}
		constraintExpiry, expiryErr := nullableTime(constraint.GetExpireTime())
		if expiryErr != nil {
			return 0, expiryErr
		}
		if _, storeErr := tx.ExecContext(ctx, `INSERT INTO authorization_decision_constraints(tenant_id,decision_id,ordinal,constraint_kind,details_digest,expire_time) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, id, ordinal, constraint.GetKind(), constraint.GetDetailsDigest(), constraintExpiry); storeErr != nil {
			return 0, storeErr
		}
	}
	persisted, err := loadAuthorizationDecision(ctx, tx, identity.TenantID, id)
	if err != nil {
		return 0, err
	}
	if !proto.Equal(persisted, value) {
		return 0, ErrIdempotencyConflict
	}
	return id, nil
}

func loadAuthorizationDecision(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.AuthorizationDecision, error) {
	var value policyv1.AuthorizationDecision
	var resourceID int64
	var outcome int32
	var evaluated time.Time
	var expiry sql.NullTime
	err := tx.QueryRowContext(ctx, `SELECT name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest FROM authorization_decisions WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&value.Name, &value.Uid, &value.ProjectId, &value.PrincipalRef, &value.Action, &resourceID, &value.IntentDigest, &outcome, &value.ReasonCode, &value.SafeReason, &evaluated, &expiry, &value.ContextDigest, &value.DecisionDigest)
	if err != nil {
		return nil, err
	}
	value.TenantId, value.Outcome, value.EvaluatedAt, value.ExpireTime = tenantID, policyv1.AuthorizationOutcome(outcome), timestamppb.New(evaluated.UTC()), timestamp(expiry)
	value.Resource, err = platformdb.LoadResourceRef(ctx, tx, tenantID, sql.NullInt64{Int64: resourceID, Valid: true})
	if err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM authorization_decision_policies WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, id) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	policyIDs := make([]int64, 0)
	for rows.Next() {
		var policyID int64
		if err = rows.Scan(&policyID); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		policyIDs = append(policyIDs, policyID)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, policyID := range policyIDs {
		policy, loadErr := loadPolicySnapshot(ctx, tx, tenantID, policyID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.Policies = append(value.Policies, policy)
	}
	rows, err = tx.QueryContext(ctx, `SELECT constraint_kind,details_digest,expire_time FROM authorization_decision_constraints WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, id) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var constraint policyv1.AuthorizationConstraint
		var constraintExpiry sql.NullTime
		if err = rows.Scan(&constraint.Kind, &constraint.DetailsDigest, &constraintExpiry); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		constraint.ExpireTime = timestamp(constraintExpiry)
		value.Constraints = append(value.Constraints, &constraint)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	return &value, rows.Err()
}

type runRow struct {
	tenant, project, name, uid, etag, requestDigest, operationID, jobID, schedulerRunID, attemptID string
	revision, leaseEpoch, completedSamples                                                         int64
	totalSamples                                                                                   sql.NullInt64
	state                                                                                          int32
	suiteID, snapshotID, modelID, inferenceProtocolID                                              int64
	executableID, providerID, kernelID, failureID                                                  sql.NullInt64
	created, updated                                                                               time.Time
	ended                                                                                          sql.NullTime
}

const runColumns = `tenant_id,project_id,name,uid,revision,etag,suite_ref_id,snapshot_ref_id,model_release_ref_id,inference_protocol_ref_id,executable_plan_ref_id,provider_manifest_ref_id,kernel_qualification_ref_id,request_digest,operation_id,job_id,scheduler_run_id,attempt_id,lease_epoch,state,completed_samples,total_samples,failure_ref_id,create_time,update_time,end_time`

func scanRun(row scanner) (runRow, error) {
	var value runRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.suiteID, &value.snapshotID, &value.modelID, &value.inferenceProtocolID, &value.executableID, &value.providerID, &value.kernelID, &value.requestDigest, &value.operationID, &value.jobID, &value.schedulerRunID, &value.attemptID, &value.leaseEpoch, &value.state, &value.completedSamples, &value.totalSamples, &value.failureID, &value.created, &value.updated, &value.ended)
	return value, err
}

func runProto(ctx context.Context, tx *sql.Tx, row runRow) (*evaluationv1.EvaluationRun, error) {
	loadArtifact := func(id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
		return platformdb.LoadArtifactRef(ctx, tx, row.tenant, id)
	}
	suite, err := loadArtifact(sql.NullInt64{Int64: row.suiteID, Valid: true})
	if err != nil {
		return nil, err
	}
	snapshot, err := loadArtifact(sql.NullInt64{Int64: row.snapshotID, Valid: true})
	if err != nil {
		return nil, err
	}
	model, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.modelID, Valid: true})
	if err != nil {
		return nil, err
	}
	inferenceProtocol, err := loadArtifact(sql.NullInt64{Int64: row.inferenceProtocolID, Valid: true})
	if err != nil {
		return nil, err
	}
	executable, err := loadArtifact(row.executableID)
	if err != nil {
		return nil, err
	}
	provider, err := loadArtifact(row.providerID)
	if err != nil {
		return nil, err
	}
	kernel, err := loadArtifact(row.kernelID)
	if err != nil {
		return nil, err
	}
	failure, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.failureID)
	if err != nil {
		return nil, err
	}
	value := &evaluationv1.EvaluationRun{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantId: row.tenant, ProjectId: row.project, Suite: suite, Snapshot: snapshot, ModelRelease: model, InferenceProtocol: inferenceProtocol, ExecutablePlan: executable, ProviderManifest: provider, KernelQualification: kernel, RequestDigest: row.requestDigest, JobId: row.jobID, AttemptId: row.attemptID, LeaseEpoch: uint64(row.leaseEpoch), State: evaluationv1.EvaluationRunState(row.state), CompletedSamples: uint64(row.completedSamples), Failure: failure, CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()), EndTime: timestamp(row.ended)} //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
	if row.totalSamples.Valid {
		total := uint64(row.totalSamples.Int64) //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
		value.TotalSamples = &total
	}
	rows, err := tx.QueryContext(ctx, `SELECT dataset_ref_id FROM evaluation_run_datasets WHERE tenant_id=$1 AND project_id=$2 AND evaluation_run_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	datasetIDs := make([]int64, 0)
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		datasetIDs = append(datasetIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range datasetIDs {
		artifact, loadErr := loadArtifact(sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.Datasets = append(value.Datasets, artifact)
	}
	rows, err = tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM evaluation_run_policies WHERE tenant_id=$1 AND project_id=$2 AND evaluation_run_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	policyIDs := make([]int64, 0)
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		policyIDs = append(policyIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range policyIDs {
		policy, loadErr := loadPolicySnapshot(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, policy)
	}
	return value, nil
}

func getRunTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*evaluationv1.EvaluationRun, runRow, error) {
	canonical, err := canonicalScopedName(identity, name, "evaluationRuns")
	if err != nil {
		return nil, runRow{}, err
	}
	query := `SELECT ` + runColumns + ` FROM evaluation_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanRun(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, runRow{}, ErrNotFound
	}
	if err != nil {
		return nil, runRow{}, err
	}
	value, err := runProto(ctx, tx, row)
	return value, row, err
}

type resultRow struct {
	tenant, project, name, uid, runName, runDigest, sourceRevision, resultDigest string
	runRef, report, suite, snapshot, datasetManifest, inferenceProtocol          int64
	leakage, safety, statistical, performance                                    sql.NullInt64
	outcome                                                                      int32
	finalized                                                                    time.Time
}

const resultColumns = `tenant_id,project_id,name,uid,evaluation_run_name,run_ref_id,run_digest,outcome,report_ref_id,suite_ref_id,snapshot_ref_id,dataset_manifest_ref_id,inference_protocol_ref_id,leakage_evidence_ref_id,safety_evidence_ref_id,statistical_evidence_ref_id,performance_evidence_ref_id,source_revision,finalized_at,result_digest`

func scanResult(row scanner) (resultRow, error) {
	var v resultRow
	err := row.Scan(&v.tenant, &v.project, &v.name, &v.uid, &v.runName, &v.runRef, &v.runDigest, &v.outcome, &v.report, &v.suite, &v.snapshot, &v.datasetManifest, &v.inferenceProtocol, &v.leakage, &v.safety, &v.statistical, &v.performance, &v.sourceRevision, &v.finalized, &v.resultDigest)
	return v, err
}

func resultProto(ctx context.Context, tx *sql.Tx, row resultRow) (*evaluationv1.EvaluationResult, error) {
	load := func(id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
		return platformdb.LoadArtifactRef(ctx, tx, row.tenant, id)
	}
	run, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.runRef, Valid: true})
	if err != nil {
		return nil, err
	}
	report, err := load(sql.NullInt64{Int64: row.report, Valid: true})
	if err != nil {
		return nil, err
	}
	suite, err := load(sql.NullInt64{Int64: row.suite, Valid: true})
	if err != nil {
		return nil, err
	}
	snapshot, err := load(sql.NullInt64{Int64: row.snapshot, Valid: true})
	if err != nil {
		return nil, err
	}
	manifest, err := load(sql.NullInt64{Int64: row.datasetManifest, Valid: true})
	if err != nil {
		return nil, err
	}
	protocol, err := load(sql.NullInt64{Int64: row.inferenceProtocol, Valid: true})
	if err != nil {
		return nil, err
	}
	leakage, err := load(row.leakage)
	if err != nil {
		return nil, err
	}
	safety, err := load(row.safety)
	if err != nil {
		return nil, err
	}
	statistical, err := load(row.statistical)
	if err != nil {
		return nil, err
	}
	performance, err := load(row.performance)
	if err != nil {
		return nil, err
	}
	value := &evaluationv1.EvaluationResult{Name: row.name, Uid: row.uid, Run: run, RunDigest: row.runDigest, Outcome: evaluationv1.EvaluationResultOutcome(row.outcome), Report: report, Suite: suite, Snapshot: snapshot, DatasetManifest: manifest, InferenceProtocol: protocol, LeakageEvidence: leakage, SafetyEvidence: safety, StatisticalEvidence: statistical, PerformanceEvidence: performance, SourceRevision: row.sourceRevision, FinalizedAt: timestamppb.New(row.finalized.UTC()), ResultDigest: row.resultDigest}
	rows, err := tx.QueryContext(ctx, `SELECT metric_id,metric_version,unit,direction,metric_value,interval_lower,interval_upper,valid_count,invalid_count,cohort_id FROM evaluation_result_metrics WHERE tenant_id=$1 AND project_id=$2 AND result_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var metric evaluationv1.MetricSummary
		var direction int32
		var lower, upper sql.NullFloat64
		if err = rows.Scan(&metric.MetricId, &metric.MetricVersion, &metric.Unit, &direction, &metric.Value, &lower, &upper, &metric.ValidCount, &metric.InvalidCount, &metric.CohortId); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		metric.Direction = evaluationv1.MetricDirection(direction)
		if lower.Valid {
			metric.IntervalLower = &lower.Float64
			metric.IntervalUpper = &upper.Float64
		}
		value.Metrics = append(value.Metrics, &metric)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	rows, err = tx.QueryContext(ctx, `SELECT rule_id,metric_id,threshold_result,reason_code,evidence_ref_id FROM evaluation_result_thresholds WHERE tenant_id=$1 AND project_id=$2 AND result_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	type thresholdRow struct {
		value      *evaluationv1.ThresholdOutcome
		evidenceID int64
	}
	thresholds := make([]thresholdRow, 0)
	for rows.Next() {
		var threshold evaluationv1.ThresholdOutcome
		var result int32
		var evidenceID int64
		if err = rows.Scan(&threshold.RuleId, &threshold.MetricId, &result, &threshold.ReasonCode, &evidenceID); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		threshold.Result = evaluationv1.ThresholdResult(result)
		thresholds = append(thresholds, thresholdRow{value: &threshold, evidenceID: evidenceID})
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, item := range thresholds {
		item.value.Evidence, err = load(sql.NullInt64{Int64: item.evidenceID, Valid: true})
		if err != nil {
			return nil, err
		}
		value.Thresholds = append(value.Thresholds, item.value)
	}
	rows, err = tx.QueryContext(ctx, `SELECT failure_class,failure_count FROM evaluation_result_failure_counts WHERE tenant_id=$1 AND project_id=$2 AND result_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		failure := new(evaluationv1.EvaluationFailureCount)
		if err = rows.Scan(&failure.FailureClass, &failure.Count); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.FailureCounts = append(value.FailureCounts, failure)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	return value, rows.Err()
}

func getResultTx(ctx context.Context, tx *sql.Tx, identity Identity, name string) (*evaluationv1.EvaluationResult, error) {
	canonical, err := canonicalScopedName(identity, name, "evaluationResults")
	if err != nil {
		return nil, err
	}
	row, err := scanResult(tx.QueryRowContext(ctx, `SELECT `+resultColumns+` FROM evaluation_results WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return resultProto(ctx, tx, row)
}

type decisionRow struct {
	tenant, project, name, uid, candidateDigest, targetProfile, reasonCode, safeReason, principal, sourceRevision, decisionDigest, operationID string
	candidateID                                                                                                                                int64
	outcome                                                                                                                                    int32
	decided                                                                                                                                    time.Time
	expiry                                                                                                                                     sql.NullTime
}

const decisionColumns = `tenant_id,project_id,name,uid,candidate_release_ref_id,candidate_digest,target_profile,outcome,reason_code,safe_reason,decided_by_principal_ref,decided_at,expire_time,source_revision,decision_digest,operation_id`

func scanDecision(row scanner) (decisionRow, error) {
	var v decisionRow
	err := row.Scan(&v.tenant, &v.project, &v.name, &v.uid, &v.candidateID, &v.candidateDigest, &v.targetProfile, &v.outcome, &v.reasonCode, &v.safeReason, &v.principal, &v.decided, &v.expiry, &v.sourceRevision, &v.decisionDigest, &v.operationID)
	return v, err
}

func decisionProto(ctx context.Context, tx *sql.Tx, row decisionRow) (*evaluationv1.PromotionDecision, error) {
	candidate, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.candidateID, Valid: true})
	if err != nil {
		return nil, err
	}
	value := &evaluationv1.PromotionDecision{Name: row.name, Uid: row.uid, CandidateRelease: candidate, CandidateDigest: row.candidateDigest, TargetProfile: row.targetProfile, Outcome: evaluationv1.PromotionOutcome(row.outcome), ReasonCode: row.reasonCode, SafeReason: row.safeReason, DecidedByPrincipalRef: row.principal, DecidedAt: timestamppb.New(row.decided.UTC()), ExpireTime: timestamp(row.expiry), SourceRevision: row.sourceRevision, DecisionDigest: row.decisionDigest}
	rows, err := tx.QueryContext(ctx, `SELECT evaluation_result_ref_id FROM promotion_decision_results WHERE tenant_id=$1 AND project_id=$2 AND decision_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	resultIDs := make([]int64, 0)
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		resultIDs = append(resultIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range resultIDs {
		ref, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.EvaluationResults = append(value.EvaluationResults, ref)
	}
	rows, err = tx.QueryContext(ctx, `SELECT rule_id,threshold_result,reason_code,evidence_ref_id FROM promotion_decision_rules WHERE tenant_id=$1 AND project_id=$2 AND decision_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	type ruleRow struct {
		value      *evaluationv1.PromotionRuleDecision
		evidenceID int64
	}
	rules := make([]ruleRow, 0)
	for rows.Next() {
		rule := new(evaluationv1.PromotionRuleDecision)
		var result int32
		var evidenceID int64
		if err = rows.Scan(&rule.RuleId, &result, &rule.ReasonCode, &evidenceID); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		rule.Result = evaluationv1.ThresholdResult(result)
		rules = append(rules, ruleRow{value: rule, evidenceID: evidenceID})
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, item := range rules {
		item.value.Evidence, err = platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: item.evidenceID, Valid: true})
		if err != nil {
			return nil, err
		}
		value.Rules = append(value.Rules, item.value)
	}
	rows, err = tx.QueryContext(ctx, `SELECT ordinal,exception_id,rule_id,rationale_ref_id,expire_time FROM promotion_decision_exceptions WHERE tenant_id=$1 AND project_id=$2 AND decision_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	type exceptionRow struct {
		ordinal, rationaleID int64
		value                *evaluationv1.PromotionException
	}
	exceptions := make([]exceptionRow, 0)
	for rows.Next() {
		exception := new(evaluationv1.PromotionException)
		var ordinal, rationaleID int64
		var expiry time.Time
		if err = rows.Scan(&ordinal, &exception.ExceptionId, &exception.RuleId, &rationaleID, &expiry); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		exception.ExpireTime = timestamppb.New(expiry.UTC())
		exceptions = append(exceptions, exceptionRow{ordinal: ordinal, rationaleID: rationaleID, value: exception})
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, item := range exceptions {
		item.value.Rationale, err = platformdb.LoadArtifactRef(ctx, tx, row.tenant, sql.NullInt64{Int64: item.rationaleID, Valid: true})
		if err != nil {
			return nil, err
		}
		approvalRows, queryErr := tx.QueryContext(ctx, `SELECT approval_ref_id FROM promotion_exception_approvals WHERE tenant_id=$1 AND project_id=$2 AND decision_name=$3 AND exception_ordinal=$4 ORDER BY ordinal`, row.tenant, row.project, row.name, item.ordinal) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
		if queryErr != nil {
			return nil, queryErr
		}
		approvalIDs := make([]int64, 0)
		for approvalRows.Next() {
			var id int64
			if queryErr = approvalRows.Scan(&id); queryErr != nil {
				_ = platformdb.CloseRows(approvalRows)
				return nil, queryErr
			}
			approvalIDs = append(approvalIDs, id)
		}
		if queryErr = platformdb.CloseRows(approvalRows); queryErr != nil {
			return nil, queryErr
		}
		if queryErr = approvalRows.Err(); queryErr != nil {
			return nil, queryErr
		}
		for _, id := range approvalIDs {
			ref, loadErr := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
			if loadErr != nil {
				return nil, loadErr
			}
			item.value.ApprovalReceipts = append(item.value.ApprovalReceipts, ref)
		}
		value.Exceptions = append(value.Exceptions, item.value)
	}
	rows, err = tx.QueryContext(ctx, `SELECT authorization_decision_id FROM promotion_decision_authorizations WHERE tenant_id=$1 AND project_id=$2 AND decision_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	authorizationIDs := make([]int64, 0)
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		authorizationIDs = append(authorizationIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range authorizationIDs {
		decision, loadErr := loadAuthorizationDecision(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicyDecisions = append(value.PolicyDecisions, decision)
	}
	return value, nil
}

func getDecisionTx(ctx context.Context, tx *sql.Tx, identity Identity, name string) (*evaluationv1.PromotionDecision, error) {
	canonical, err := canonicalScopedName(identity, name, "promotionDecisions")
	if err != nil {
		return nil, err
	}
	row, err := scanDecision(tx.QueryRowContext(ctx, `SELECT `+decisionColumns+` FROM promotion_decisions WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return decisionProto(ctx, tx, row)
}
