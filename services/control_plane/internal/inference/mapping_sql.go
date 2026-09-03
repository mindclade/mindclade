package inference

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

type scanner interface{ Scan(...any) error }

func nullableTime(value *timestamppb.Timestamp) (sql.NullTime, error) {
	if value == nil {
		return sql.NullTime{}, nil
	}
	if err := value.CheckValid(); err != nil {
		return sql.NullTime{}, err
	}
	return sql.NullTime{Time: value.AsTime().UTC(), Valid: true}, nil
}

func protoTimestamp(value sql.NullTime) *timestamppb.Timestamp {
	if !value.Valid {
		return nil
	}
	return timestamppb.New(value.Time.UTC())
}

func storePolicy(ctx context.Context, tx *sql.Tx, tenantID string, value *policyv1.PolicyReference) (int64, error) {
	if err := validatePolicy(value); err != nil {
		return 0, err
	}
	documentID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetDocument())
	if err != nil {
		return 0, err
	}
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	var id int64
	err = tx.QueryRowContext(ctx, `INSERT INTO policy_snapshot_references(
tenant_id,name,uid,policy_type,semantic_version,digest,document_ref_id,
resource_revision,effective_time,expire_time,classification
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
ON CONFLICT (tenant_id,name,resource_revision,digest) DO NOTHING RETURNING id`,
		tenantID, value.GetName(), value.GetUid(), value.GetPolicyType(), value.GetVersion(), value.GetDigest(),
		documentID, value.GetResourceRevision(), value.GetEffectiveTime().AsTime().UTC(), expiry, value.GetClassification()).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, tenantID, value.GetName(), value.GetResourceRevision(), value.GetDigest()).Scan(&id)
	}
	if err != nil {
		return 0, err
	}
	persisted, err := loadPolicy(ctx, tx, tenantID, id)
	if err != nil {
		return 0, err
	}
	if !proto.Equal(persisted, value) {
		return 0, ErrIdempotencyConflict
	}
	return id, nil
}

func loadPolicy(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.PolicyReference, error) {
	value := new(policyv1.PolicyReference)
	var documentID int64
	var effective time.Time
	var expiry sql.NullTime
	if err := tx.QueryRowContext(ctx, `SELECT name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification FROM policy_snapshot_references WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(
		&value.Name, &value.Uid, &value.PolicyType, &value.Version, &value.Digest, &documentID,
		&value.ResourceRevision, &effective, &expiry, &value.Classification,
	); err != nil {
		return nil, err
	}
	var err error
	value.Document, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, sql.NullInt64{Int64: documentID, Valid: true})
	if err != nil {
		return nil, err
	}
	value.EffectiveTime, value.ExpireTime = timestamppb.New(effective.UTC()), protoTimestamp(expiry)
	return value, nil
}

func storeAuthorization(ctx context.Context, tx *sql.Tx, identity Identity, value *policyv1.AuthorizationDecision) (int64, error) {
	if err := validateAuthorization(identity, value); err != nil {
		return 0, err
	}
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetResource())
	if err != nil {
		return 0, err
	}
	expiry, err := nullableTime(value.GetExpireTime())
	if err != nil {
		return 0, err
	}
	var id int64
	err = tx.QueryRowContext(ctx, `INSERT INTO authorization_decisions(
tenant_id,name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,
outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
ON CONFLICT (tenant_id,name) DO NOTHING RETURNING id`,
		identity.TenantID, value.GetName(), value.GetUid(), identity.ProjectID, value.GetPrincipalRef(),
		value.GetAction(), resourceID, value.GetIntentDigest(), int32(value.GetOutcome()), value.GetReasonCode(),
		value.GetSafeReason(), value.GetEvaluatedAt().AsTime().UTC(), expiry, value.GetContextDigest(), value.GetDecisionDigest()).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		err = tx.QueryRowContext(ctx, `SELECT id FROM authorization_decisions WHERE tenant_id=$1 AND name=$2`, identity.TenantID, value.GetName()).Scan(&id)
	}
	if err != nil {
		return 0, err
	}
	var children int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM authorization_decision_policies WHERE tenant_id=$1 AND decision_id=$2`, identity.TenantID, id).Scan(&children); err != nil {
		return 0, err
	}
	if children == 0 {
		for ordinal, snapshot := range value.GetPolicies() {
			policyID, storeErr := storePolicy(ctx, tx, identity.TenantID, snapshot)
			if storeErr != nil {
				return 0, storeErr
			}
			if _, storeErr = tx.ExecContext(ctx, `INSERT INTO authorization_decision_policies(tenant_id,decision_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4)`, identity.TenantID, id, ordinal, policyID); storeErr != nil {
				return 0, storeErr
			}
		}
		for ordinal, constraint := range value.GetConstraints() {
			constraintExpiry, expiryErr := nullableTime(constraint.GetExpireTime())
			if expiryErr != nil {
				return 0, expiryErr
			}
			if _, storeErr := tx.ExecContext(ctx, `INSERT INTO authorization_decision_constraints(tenant_id,decision_id,ordinal,constraint_kind,details_digest,expire_time) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, id, ordinal, constraint.GetKind(), constraint.GetDetailsDigest(), constraintExpiry); storeErr != nil {
				return 0, storeErr
			}
		}
	}
	persisted, err := loadAuthorization(ctx, tx, identity.TenantID, id)
	if err != nil {
		return 0, err
	}
	if !proto.Equal(persisted, value) {
		return 0, ErrIdempotencyConflict
	}
	return id, nil
}

func loadAuthorization(ctx context.Context, tx *sql.Tx, tenantID string, id int64) (*policyv1.AuthorizationDecision, error) {
	value := new(policyv1.AuthorizationDecision)
	var resourceID int64
	var outcome int32
	var evaluated time.Time
	var expiry sql.NullTime
	if err := tx.QueryRowContext(ctx, `SELECT name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest FROM authorization_decisions WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(
		&value.Name, &value.Uid, &value.ProjectId, &value.PrincipalRef, &value.Action, &resourceID,
		&value.IntentDigest, &outcome, &value.ReasonCode, &value.SafeReason, &evaluated, &expiry,
		&value.ContextDigest, &value.DecisionDigest,
	); err != nil {
		return nil, err
	}
	value.TenantId, value.Outcome = tenantID, policyv1.AuthorizationOutcome(outcome)
	value.EvaluatedAt, value.ExpireTime = timestamppb.New(evaluated.UTC()), protoTimestamp(expiry)
	var err error
	value.Resource, err = platformdb.LoadResourceRef(ctx, tx, tenantID, sql.NullInt64{Int64: resourceID, Valid: true})
	if err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM authorization_decision_policies WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, id) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var policyIDs []int64
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
		policy, loadErr := loadPolicy(ctx, tx, tenantID, policyID)
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
		constraint := new(policyv1.AuthorizationConstraint)
		var constraintExpiry sql.NullTime
		if err = rows.Scan(&constraint.Kind, &constraint.DetailsDigest, &constraintExpiry); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		constraint.ExpireTime = protoTimestamp(constraintExpiry)
		value.Constraints = append(value.Constraints, constraint)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	return value, rows.Err()
}

type requestRow struct {
	tenant, project, name, uid, requestDigest                                     string
	contextRequestID, contextIdempotencyKey, contextPrincipalID, contextTraceID   string
	contextCanonical, contextTenant, contextProject                               string
	contextCorrelation, contextCausation, contextCancellation                     string
	contextDeadline                                                               sql.NullTime
	capability, inputKind                                                         string
	mode, reproducibility                                                         int32
	modelID, modelBundleID, featurePolicyID, samplingPolicyID, confidencePolicyID int64
	inputArtifactID                                                               sql.NullInt64
	inlineMedia, inlineSchema, inlineDigest                                       string
	inlinePayload                                                                 []byte
	samplingAlgorithm, samplingVersion, samplingRandomKey                         string
	samplingCandidateCount, samplingMaximumSteps                                  uint32
	temperature, guidance                                                         sql.NullFloat64
	computeSeconds                                                                int64
	computeNanos                                                                  int32
	resultSchema                                                                  string
	includeSummaries, retainDiagnostics                                           bool
	resourceClass, classification                                                 string
	deadline, createTime                                                          time.Time
	operationID, jobID, schedulerRunID                                            string
}

const requestColumns = `tenant_id,project_id,name,uid,request_digest,
context_request_id,context_idempotency_key,context_principal_id,context_trace_id,
context_deadline,context_canonical_request_digest,context_tenant_id,context_project_id,
context_correlation_id,context_causation_id,context_cancellation_token_id,
capability,mode,model_ref_id,resolved_model_bundle_ref_id,input_kind,input_artifact_ref_id,
inline_media_type,inline_schema_id,inline_payload,inline_content_digest,feature_policy_ref_id,
sampling_algorithm,sampling_algorithm_version,sampling_candidate_count,sampling_maximum_steps,
sampling_temperature,sampling_guidance_scale,sampling_random_key,sampling_maximum_compute_seconds,
sampling_maximum_compute_nanos,sampling_policy_ref_id,confidence_policy_ref_id,result_schema_id,
include_bounded_candidate_summaries,retain_diagnostics,resource_class,reproducibility,
data_classification,deadline,create_time,operation_id,job_id,scheduler_run_id`

func scanRequest(row scanner) (requestRow, error) {
	var value requestRow
	err := row.Scan(
		&value.tenant, &value.project, &value.name, &value.uid, &value.requestDigest,
		&value.contextRequestID, &value.contextIdempotencyKey, &value.contextPrincipalID, &value.contextTraceID,
		&value.contextDeadline, &value.contextCanonical, &value.contextTenant, &value.contextProject,
		&value.contextCorrelation, &value.contextCausation, &value.contextCancellation,
		&value.capability, &value.mode, &value.modelID, &value.modelBundleID, &value.inputKind, &value.inputArtifactID,
		&value.inlineMedia, &value.inlineSchema, &value.inlinePayload, &value.inlineDigest, &value.featurePolicyID,
		&value.samplingAlgorithm, &value.samplingVersion, &value.samplingCandidateCount, &value.samplingMaximumSteps,
		&value.temperature, &value.guidance, &value.samplingRandomKey, &value.computeSeconds, &value.computeNanos,
		&value.samplingPolicyID, &value.confidencePolicyID, &value.resultSchema, &value.includeSummaries,
		&value.retainDiagnostics, &value.resourceClass, &value.reproducibility, &value.classification,
		&value.deadline, &value.createTime, &value.operationID, &value.jobID, &value.schedulerRunID,
	)
	return value, err
}

func requestProto(ctx context.Context, tx *sql.Tx, row requestRow) (*inferencev1.InferenceRequest, error) {
	model, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.modelID, Valid: true})
	if err != nil {
		return nil, err
	}
	loadArtifact := func(id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
		return platformdb.LoadArtifactRef(ctx, tx, row.tenant, id)
	}
	modelBundle, err := loadArtifact(sql.NullInt64{Int64: row.modelBundleID, Valid: true})
	if err != nil {
		return nil, err
	}
	featurePolicy, err := loadArtifact(sql.NullInt64{Int64: row.featurePolicyID, Valid: true})
	if err != nil {
		return nil, err
	}
	samplingPolicy, err := loadArtifact(sql.NullInt64{Int64: row.samplingPolicyID, Valid: true})
	if err != nil {
		return nil, err
	}
	confidencePolicy, err := loadArtifact(sql.NullInt64{Int64: row.confidencePolicyID, Valid: true})
	if err != nil {
		return nil, err
	}
	value := &inferencev1.InferenceRequest{
		Context: &commonv1.CommandContext{
			RequestId: row.contextRequestID, IdempotencyKey: row.contextIdempotencyKey,
			PrincipalId: row.contextPrincipalID, TraceId: row.contextTraceID,
			Deadline: protoTimestamp(row.contextDeadline), CanonicalRequestDigest: row.contextCanonical,
			TenantId: row.contextTenant, ProjectId: row.contextProject,
			CorrelationId: row.contextCorrelation, CausationId: row.contextCausation,
			CancellationTokenId: row.contextCancellation,
		},
		Name: row.name, Uid: row.uid, TenantId: row.tenant, ProjectId: row.project,
		Capability: row.capability, Mode: inferencev1.InferenceMode(row.mode), Model: model,
		ResolvedModelBundle: modelBundle, FeaturePolicy: featurePolicy,
		SamplingPolicy: &inferencev1.SamplingPolicy{
			Algorithm: row.samplingAlgorithm, AlgorithmVersion: row.samplingVersion,
			CandidateCount: row.samplingCandidateCount, MaximumSteps: row.samplingMaximumSteps,
			RandomKey: row.samplingRandomKey, MaximumComputeTime: &durationpb.Duration{Seconds: row.computeSeconds, Nanos: row.computeNanos},
			Policy: samplingPolicy,
		},
		ConfidencePolicy: confidencePolicy,
		OutputOptions:    &inferencev1.InferenceOutputOptions{ResultSchemaId: row.resultSchema, IncludeBoundedCandidateSummaries: row.includeSummaries, RetainDiagnostics: row.retainDiagnostics},
		ResourceClass:    row.resourceClass, Reproducibility: inferencev1.ReproducibilityIntent(row.reproducibility),
		DataClassification: row.classification, Deadline: timestamppb.New(row.deadline.UTC()), CreateTime: timestamppb.New(row.createTime.UTC()),
	}
	if row.temperature.Valid {
		value.SamplingPolicy.Temperature = &row.temperature.Float64
	}
	if row.guidance.Valid {
		value.SamplingPolicy.GuidanceScale = &row.guidance.Float64
	}
	switch row.inputKind {
	case "ARTIFACT":
		input, loadErr := loadArtifact(row.inputArtifactID)
		if loadErr != nil {
			return nil, loadErr
		}
		value.Input = &inferencev1.InferenceRequest_InputArtifact{InputArtifact: input}
	case "INLINE":
		value.Input = &inferencev1.InferenceRequest_InlineInput{InlineInput: &inferencev1.BoundedInlineInput{MediaType: row.inlineMedia, SchemaId: row.inlineSchema, Payload: append([]byte(nil), row.inlinePayload...), ContentDigest: row.inlineDigest}}
	default:
		return nil, ErrInvalidArgument
	}
	rows, err := tx.QueryContext(ctx, `SELECT artifact_kind FROM inference_request_output_kinds WHERE tenant_id=$1 AND project_id=$2 AND request_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var kind string
		if err = rows.Scan(&kind); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.OutputOptions.RequestedArtifactKinds = append(value.OutputOptions.RequestedArtifactKinds, kind)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	rows, err = tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM inference_request_policies WHERE tenant_id=$1 AND project_id=$2 AND request_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var policyIDs []int64
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
		policy, loadErr := loadPolicy(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, policy)
	}
	return value, nil
}

func getRequestTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*inferencev1.InferenceRequest, requestRow, error) {
	canonical, err := canonicalName(identity, name, "inferenceRequests")
	if err != nil {
		return nil, requestRow{}, err
	}
	query := `SELECT ` + requestColumns + ` FROM inference_requests WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += ` FOR UPDATE`
	}
	row, err := scanRequest(tx.QueryRowContext(ctx, query, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, requestRow{}, ErrNotFound
	}
	if err != nil {
		return nil, requestRow{}, err
	}
	value, err := requestProto(ctx, tx, row)
	return value, row, err
}

type resultRow struct {
	tenant, project, name, uid, requestName, requestDigest, jobID, runID, attemptID  string
	requestRefID, operationRefID                                                     int64
	leaseEpoch                                                                       uint64
	outcome                                                                          int32
	resultManifestID, modelBundleID                                                  int64
	inputArtifactID, featureBundleID, executablePlanID, providerManifestID           sql.NullInt64
	kernelQualificationID, confidenceReportID, rankingReportID, failureDiagnosticsID sql.NullInt64
	selectedCandidateID, sourceRevision, resultDigest                                string
	completedAt                                                                      time.Time
}

const resultColumns = `tenant_id,project_id,name,uid,inference_request_name,request_ref_id,request_digest,operation_ref_id,job_id,scheduler_run_id,attempt_id,lease_epoch,outcome,result_manifest_ref_id,input_artifact_ref_id,model_bundle_ref_id,feature_bundle_ref_id,executable_plan_ref_id,provider_manifest_ref_id,kernel_qualification_ref_id,selected_candidate_id,confidence_report_ref_id,ranking_report_ref_id,failure_diagnostics_ref_id,source_revision,completed_at,result_digest`

func scanResult(row scanner) (resultRow, error) {
	var value resultRow
	err := row.Scan(&value.tenant, &value.project, &value.name, &value.uid, &value.requestName,
		&value.requestRefID, &value.requestDigest, &value.operationRefID, &value.jobID, &value.runID,
		&value.attemptID, &value.leaseEpoch, &value.outcome, &value.resultManifestID,
		&value.inputArtifactID, &value.modelBundleID, &value.featureBundleID, &value.executablePlanID,
		&value.providerManifestID, &value.kernelQualificationID, &value.selectedCandidateID,
		&value.confidenceReportID, &value.rankingReportID, &value.failureDiagnosticsID,
		&value.sourceRevision, &value.completedAt, &value.resultDigest)
	return value, err
}

func resultProto(ctx context.Context, tx *sql.Tx, row resultRow) (*inferencev1.InferenceResult, error) {
	loadArtifact := func(id sql.NullInt64) (*artifactv1.ArtifactRef, error) {
		return platformdb.LoadArtifactRef(ctx, tx, row.tenant, id)
	}
	requestRef, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.requestRefID, Valid: true})
	if err != nil {
		return nil, err
	}
	operationRef, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, sql.NullInt64{Int64: row.operationRefID, Valid: true})
	if err != nil {
		return nil, err
	}
	manifest, err := loadArtifact(sql.NullInt64{Int64: row.resultManifestID, Valid: true})
	if err != nil {
		return nil, err
	}
	modelBundle, err := loadArtifact(sql.NullInt64{Int64: row.modelBundleID, Valid: true})
	if err != nil {
		return nil, err
	}
	value := &inferencev1.InferenceResult{
		Name: row.name, Uid: row.uid, Request: requestRef, RequestDigest: row.requestDigest,
		Operation: operationRef, JobId: row.jobID, RunId: row.runID, AttemptId: row.attemptID,
		LeaseEpoch: row.leaseEpoch, Outcome: inferencev1.InferenceResultOutcome(row.outcome),
		ResultManifest: manifest, ModelBundle: modelBundle, SelectedCandidateId: row.selectedCandidateID,
		SourceRevision: row.sourceRevision, CompletedAt: timestamppb.New(row.completedAt.UTC()), ResultDigest: row.resultDigest,
	}
	for destination, id := range map[**artifactv1.ArtifactRef]sql.NullInt64{
		&value.InputArtifact: row.inputArtifactID, &value.FeatureBundle: row.featureBundleID,
		&value.ExecutablePlan: row.executablePlanID, &value.ProviderManifest: row.providerManifestID,
		&value.KernelQualification: row.kernelQualificationID, &value.ConfidenceReport: row.confidenceReportID,
		&value.RankingReport: row.rankingReportID, &value.FailureDiagnostics: row.failureDiagnosticsID,
	} {
		*destination, err = loadArtifact(id)
		if err != nil {
			return nil, err
		}
	}
	rows, err := tx.QueryContext(ctx, `SELECT candidate_id,sample_index,output_ref_id,confidence,selected,diagnostics_ref_id FROM inference_result_candidates WHERE tenant_id=$1 AND project_id=$2 AND result_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	type candidateRow struct {
		value         *inferencev1.InferenceCandidateResult
		outputID      int64
		diagnosticsID sql.NullInt64
		confidence    sql.NullFloat64
	}
	var candidates []candidateRow
	for rows.Next() {
		item := candidateRow{value: new(inferencev1.InferenceCandidateResult)}
		if err = rows.Scan(&item.value.CandidateId, &item.value.SampleIndex, &item.outputID, &item.confidence, &item.value.Selected, &item.diagnosticsID); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		candidates = append(candidates, item)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, item := range candidates {
		item.value.Output, err = loadArtifact(sql.NullInt64{Int64: item.outputID, Valid: true})
		if err != nil {
			return nil, err
		}
		item.value.Diagnostics, err = loadArtifact(item.diagnosticsID)
		if err != nil {
			return nil, err
		}
		if item.confidence.Valid {
			item.value.Confidence = &item.confidence.Float64
		}
		value.Candidates = append(value.Candidates, item.value)
	}
	rows, err = tx.QueryContext(ctx, `SELECT authorization_decision_id FROM inference_result_authorizations WHERE tenant_id=$1 AND project_id=$2 AND result_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, err
	}
	var decisionIDs []int64
	for rows.Next() {
		var id int64
		if err = rows.Scan(&id); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		decisionIDs = append(decisionIDs, id)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, err
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for _, id := range decisionIDs {
		decision, loadErr := loadAuthorization(ctx, tx, row.tenant, id)
		if loadErr != nil {
			return nil, loadErr
		}
		value.SafetyDecisions = append(value.SafetyDecisions, decision)
	}
	return value, nil
}

func getResultByNameTx(ctx context.Context, tx *sql.Tx, identity Identity, name string) (*inferencev1.InferenceResult, error) {
	canonical, err := canonicalName(identity, name, "inferenceResults")
	if err != nil {
		return nil, err
	}
	row, err := scanResult(tx.QueryRowContext(ctx, `SELECT `+resultColumns+` FROM inference_results WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return resultProto(ctx, tx, row)
}

func getResultByRequestTx(ctx context.Context, tx *sql.Tx, identity Identity, requestName string) (*inferencev1.InferenceResult, error) {
	canonical, err := canonicalName(identity, requestName, "inferenceRequests")
	if err != nil {
		return nil, err
	}
	row, err := scanResult(tx.QueryRowContext(ctx, `SELECT `+resultColumns+` FROM inference_results WHERE tenant_id=$1 AND project_id=$2 AND inference_request_name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return resultProto(ctx, tx, row)
}

func storeResult(ctx context.Context, tx *sql.Tx, identity Identity, requestName string, value *inferencev1.InferenceResult) (*inferencev1.InferenceResult, sql.NullInt64, error) {
	value = clone(value)
	requestRef, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetRequest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	operationRef, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetOperation())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	storeArtifact := func(item *artifactv1.ArtifactRef) (sql.NullInt64, error) {
		return platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, item)
	}
	manifest, err := storeArtifact(value.GetResultManifest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	input, err := storeArtifact(value.GetInputArtifact())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	model, err := storeArtifact(value.GetModelBundle())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	feature, err := storeArtifact(value.GetFeatureBundle())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	executable, err := storeArtifact(value.GetExecutablePlan())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	provider, err := storeArtifact(value.GetProviderManifest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	kernel, err := storeArtifact(value.GetKernelQualification())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	confidence, err := storeArtifact(value.GetConfidenceReport())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	ranking, err := storeArtifact(value.GetRankingReport())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	failure, err := storeArtifact(value.GetFailureDiagnostics())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO inference_results(
tenant_id,project_id,name,uid,inference_request_name,request_ref_id,request_digest,
operation_ref_id,job_id,scheduler_run_id,attempt_id,lease_epoch,outcome,
result_manifest_ref_id,input_artifact_ref_id,model_bundle_ref_id,feature_bundle_ref_id,
executable_plan_ref_id,provider_manifest_ref_id,kernel_qualification_ref_id,
selected_candidate_id,confidence_report_ref_id,ranking_report_ref_id,
failure_diagnostics_ref_id,source_revision,completed_at,result_digest
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27)`,
		identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), requestName,
		requestRef, value.GetRequestDigest(), operationRef, value.GetJobId(), value.GetRunId(),
		value.GetAttemptId(), value.GetLeaseEpoch(), int32(value.GetOutcome()), manifest, input, model,
		feature, executable, provider, kernel, value.GetSelectedCandidateId(), confidence, ranking,
		failure, value.GetSourceRevision(), value.GetCompletedAt().AsTime().UTC(), value.GetResultDigest())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	for ordinal, candidate := range value.GetCandidates() {
		output, storeErr := storeArtifact(candidate.GetOutput())
		if storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
		diagnostics, storeErr := storeArtifact(candidate.GetDiagnostics())
		if storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
		var confidenceValue sql.NullFloat64
		if candidate.Confidence != nil {
			confidenceValue = sql.NullFloat64{Float64: candidate.GetConfidence(), Valid: true}
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO inference_result_candidates(tenant_id,project_id,result_name,ordinal,candidate_id,sample_index,output_ref_id,confidence,selected,diagnostics_ref_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, candidate.GetCandidateId(), candidate.GetSampleIndex(), output, confidenceValue, candidate.GetSelected(), diagnostics); storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
	}
	for ordinal, decision := range value.GetSafetyDecisions() {
		decisionID, storeErr := storeAuthorization(ctx, tx, identity, decision)
		if storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO inference_result_authorizations(tenant_id,project_id,result_name,ordinal,authorization_decision_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, decisionID); storeErr != nil {
			return nil, sql.NullInt64{}, storeErr
		}
	}
	persisted, err := getResultByNameTx(ctx, tx, identity, value.GetName())
	if err != nil {
		return nil, sql.NullInt64{}, err
	}
	if !proto.Equal(persisted, value) {
		return nil, sql.NullInt64{}, fmt.Errorf("%w: inference result SQL mapping parity", ErrInvalidArgument)
	}
	return persisted, manifest, nil
}

type operationRow struct {
	id, tenant, project, job, status, etag                                    string
	targetPresent                                                             bool
	targetType, targetID, targetTenant, targetProject, targetName, targetETag string
	targetVersion, version                                                    int64
	done                                                                      bool
	result, errorDetail                                                       sql.NullInt64
	created, updated                                                          time.Time
}

const operationColumns = `id,tenant_id,project_id,job_id,status,version,done,etag,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,result_ref_id,error_detail_id,created_at,updated_at`

func scanOperation(row scanner) (operationRow, error) {
	var value operationRow
	err := row.Scan(&value.id, &value.tenant, &value.project, &value.job, &value.status,
		&value.version, &value.done, &value.etag, &value.targetPresent, &value.targetType,
		&value.targetID, &value.targetTenant, &value.targetProject, &value.targetVersion,
		&value.targetName, &value.targetETag, &value.result, &value.errorDetail,
		&value.created, &value.updated)
	return value, err
}

func operationProto(ctx context.Context, tx *sql.Tx, row operationRow) (*operationv1.Operation, error) {
	result, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.result)
	if err != nil {
		return nil, err
	}
	detail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.errorDetail)
	if err != nil {
		return nil, err
	}
	states := map[string]operationv1.OperationState{"PENDING": operationv1.OperationState_OPERATION_STATE_PENDING, "RUNNING": operationv1.OperationState_OPERATION_STATE_RUNNING, "SUCCEEDED": operationv1.OperationState_OPERATION_STATE_SUCCEEDED, "FAILED": operationv1.OperationState_OPERATION_STATE_FAILED, "CANCELLING": operationv1.OperationState_OPERATION_STATE_CANCELLING, "CANCELLED": operationv1.OperationState_OPERATION_STATE_CANCELLED}
	state, ok := states[row.status]
	if !ok {
		return nil, ErrInvalidTransition
	}
	value := &operationv1.Operation{OperationId: row.id, TenantId: row.tenant, ProjectId: row.project, JobId: row.job, State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag, Result: result, Error: detail, CreatedAt: timestamppb.New(row.created.UTC()), UpdatedAt: timestamppb.New(row.updated.UTC())}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant, ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag}
	}
	return value, nil
}

func loadOperationTx(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*operationv1.Operation, error) {
	row, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return operationProto(ctx, tx, row)
}
