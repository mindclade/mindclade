package inference

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	jobsapp "github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	operationsapp "github.com/mindclade/mindclade/services/control_plane/internal/operations"
)

const (
	actionSubmit = "inference.request.submit"
	actionCommit = "inference.result.commit"
)

func (repository SQLRepository) validate() error {
	if repository.DB == nil || repository.Events == nil {
		return errors.New("inference SQL repository requires database and generated event factory")
	}
	return nil
}

func randomID(prefix string) (string, error) {
	value := make([]byte, 18)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return prefix + base64.RawURLEncoding.EncodeToString(value), nil
}

func checkReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string) (string, bool, error) {
	lock := fmt.Sprintf("%d:%s:%d:%s:%d:%s:%s:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, len(identity.Principal), identity.Principal, action, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lock); err != nil {
		return "", false, err
	}
	var storedDigest, operationID string
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id FROM evaluation_inference_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&storedDigest, &operationID)
	if errors.Is(err, sql.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(storedDigest), []byte(digest)) != 1 {
		return "", false, ErrIdempotencyConflict
	}
	return operationID, true, nil
}

func recordReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, operationID string, at time.Time) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO evaluation_inference_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, operationID, at.UTC())
	return err
}

func insertOperationRevision(ctx context.Context, tx *sql.Tx, operation *jobv1.Operation, at time.Time) error {
	target := operation.GetTarget()
	if target == nil {
		return ErrInvalidArgument
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO operation_revisions(
operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,
target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,
target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at
) VALUES($1,$2,$3,$4,$5,true,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NULL,NULL,$16,$17,$18)`,
		operation.GetOperationId(), operation.GetTenantId(), operation.GetProjectId(), operation.GetResourceVersion(),
		operation.GetJobId(), target.GetResourceType(), target.GetResourceId(), target.GetTenantId(), target.GetProjectId(),
		target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationStateSQL(operation.GetState()),
		operation.GetDone(), operation.GetEtag(), operation.GetCreatedAt().AsTime().UTC(), operation.GetUpdatedAt().AsTime().UTC(), at.UTC())
	return err
}

func operationStateSQL(state jobv1.OperationState) string {
	switch state {
	case jobv1.OperationState_OPERATION_STATE_PENDING:
		return "PENDING"
	case jobv1.OperationState_OPERATION_STATE_RUNNING:
		return "RUNNING"
	case jobv1.OperationState_OPERATION_STATE_SUCCEEDED:
		return "SUCCEEDED"
	case jobv1.OperationState_OPERATION_STATE_FAILED:
		return "FAILED"
	case jobv1.OperationState_OPERATION_STATE_CANCELLING:
		return "CANCELLING"
	case jobv1.OperationState_OPERATION_STATE_CANCELLED:
		return "CANCELLED"
	default:
		return ""
	}
}

func materializeContext(identity Identity, request *inferencev1.InferenceRequest, digest string) {
	request.TenantId, request.ProjectId = identity.TenantID, identity.ProjectID
	request.Context.TenantId, request.Context.ProjectId = identity.TenantID, identity.ProjectID
	request.Context.PrincipalId = identity.Principal
	request.Context.CanonicalRequestDigest = digest
}

func storeRequest(ctx context.Context, tx *sql.Tx, identity Identity, request *inferencev1.InferenceRequest, digest, operationID, jobID, runID string) error {
	modelID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, request.GetModel())
	if err != nil {
		return err
	}
	modelBundleID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetResolvedModelBundle())
	if err != nil {
		return err
	}
	featurePolicyID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetFeaturePolicy())
	if err != nil {
		return err
	}
	samplingPolicyID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetSamplingPolicy().GetPolicy())
	if err != nil {
		return err
	}
	confidencePolicyID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetConfidencePolicy())
	if err != nil {
		return err
	}
	var inputKind, inlineMedia, inlineSchema, inlineDigest string
	var inputArtifactID sql.NullInt64
	var inlinePayload []byte
	switch input := request.GetInput().(type) {
	case *inferencev1.InferenceRequest_InputArtifact:
		inputKind = "ARTIFACT"
		inputArtifactID, err = platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, input.InputArtifact)
	case *inferencev1.InferenceRequest_InlineInput:
		inputKind = "INLINE"
		inlineMedia, inlineSchema, inlineDigest = input.InlineInput.GetMediaType(), input.InlineInput.GetSchemaId(), input.InlineInput.GetContentDigest()
		inlinePayload = append([]byte(nil), input.InlineInput.GetPayload()...)
	default:
		return ErrInvalidArgument
	}
	if err != nil {
		return err
	}
	contextDeadline, err := nullableTime(request.GetContext().GetDeadline())
	if err != nil {
		return err
	}
	var temperature, guidance sql.NullFloat64
	if request.GetSamplingPolicy().Temperature != nil {
		temperature = sql.NullFloat64{Float64: request.GetSamplingPolicy().GetTemperature(), Valid: true}
	}
	if request.GetSamplingPolicy().GuidanceScale != nil {
		guidance = sql.NullFloat64{Float64: request.GetSamplingPolicy().GetGuidanceScale(), Valid: true}
	}
	contextValue := request.GetContext()
	policy := request.GetSamplingPolicy()
	options := request.GetOutputOptions()
	_, err = tx.ExecContext(ctx, `INSERT INTO inference_requests(
tenant_id,project_id,name,uid,request_digest,context_request_id,context_idempotency_key,
context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,
context_tenant_id,context_project_id,context_correlation_id,context_causation_id,
context_cancellation_token_id,capability,mode,model_ref_id,resolved_model_bundle_ref_id,
input_kind,input_artifact_ref_id,inline_media_type,inline_schema_id,inline_payload,
inline_content_digest,feature_policy_ref_id,sampling_algorithm,sampling_algorithm_version,
sampling_candidate_count,sampling_maximum_steps,sampling_temperature,sampling_guidance_scale,
sampling_random_key,sampling_maximum_compute_seconds,sampling_maximum_compute_nanos,
sampling_policy_ref_id,confidence_policy_ref_id,result_schema_id,
include_bounded_candidate_summaries,retain_diagnostics,resource_class,reproducibility,
data_classification,deadline,create_time,operation_id,job_id,scheduler_run_id
) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,$37,$38,$39,$40,$41,$42,$43,$44,$45,$46,$47,$48,$49)`,
		identity.TenantID, identity.ProjectID, request.GetName(), request.GetUid(), digest,
		contextValue.GetRequestId(), contextValue.GetIdempotencyKey(), contextValue.GetPrincipalId(),
		contextValue.GetTraceId(), contextDeadline, contextValue.GetCanonicalRequestDigest(),
		contextValue.GetTenantId(), contextValue.GetProjectId(), contextValue.GetCorrelationId(),
		contextValue.GetCausationId(), contextValue.GetCancellationTokenId(), request.GetCapability(),
		int32(request.GetMode()), modelID, modelBundleID, inputKind, inputArtifactID, inlineMedia,
		inlineSchema, inlinePayload, inlineDigest, featurePolicyID, policy.GetAlgorithm(),
		policy.GetAlgorithmVersion(), policy.GetCandidateCount(), policy.GetMaximumSteps(), temperature,
		guidance, policy.GetRandomKey(), policy.GetMaximumComputeTime().GetSeconds(),
		policy.GetMaximumComputeTime().GetNanos(), samplingPolicyID, confidencePolicyID,
		options.GetResultSchemaId(), options.GetIncludeBoundedCandidateSummaries(), options.GetRetainDiagnostics(),
		request.GetResourceClass(), int32(request.GetReproducibility()), request.GetDataClassification(),
		request.GetDeadline().AsTime().UTC(), request.GetCreateTime().AsTime().UTC(), operationID, jobID, runID)
	if err != nil {
		return err
	}
	for ordinal, kind := range options.GetRequestedArtifactKinds() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO inference_request_output_kinds(tenant_id,project_id,request_name,ordinal,artifact_kind) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, request.GetName(), ordinal, kind); err != nil {
			return err
		}
	}
	for ordinal, snapshot := range request.GetPolicySnapshots() {
		policyID, storeErr := storePolicy(ctx, tx, identity.TenantID, snapshot)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO inference_request_policies(tenant_id,project_id,request_name,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, request.GetName(), ordinal, policyID); storeErr != nil {
			return storeErr
		}
	}
	persisted, _, err := getRequestTx(ctx, tx, identity, request.GetName(), false)
	if err != nil {
		return err
	}
	if !proto.Equal(persisted, request) {
		return fmt.Errorf("%w: inference request SQL mapping parity", ErrInvalidArgument)
	}
	return nil
}

func (repository SQLRepository) Submit(ctx context.Context, identity Identity, request *inferencev1.InferenceRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	request = clone(request)
	if err := validateInferenceRequest(identity, request, at); err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	materializeContext(identity, request, digest)
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, actionSubmit, request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, false, commitErr
		}
		return clone(operation), true, nil
	}
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, false, err
	}
	operationID, err = randomID("operations/")
	if err != nil {
		return nil, false, err
	}
	runID, err := randomID("runs/")
	if err != nil {
		return nil, false, err
	}
	inputID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetInputArtifact())
	if err != nil {
		return nil, false, err
	}
	configurationID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetSamplingPolicy().GetPolicy())
	if err != nil {
		return nil, false, err
	}
	planID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, request.GetFeaturePolicy())
	if err != nil {
		return nil, false, err
	}
	policyDigest := request.GetPolicySnapshots()[0].GetDigest()
	jobETag := resourceETag(jobID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'QUEUED',1,$5,'inference.request',$6,$7,$8,$9,$10,$10)`, jobID, identity.TenantID, operationID, identity.ProjectID, policyDigest, inputID, configurationID, digest, jobETag, at.UTC()); err != nil {
		return nil, false, mapUnique(err)
	}
	target := requestResource(identity, request, digest)
	operation := &jobv1.Operation{OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID, State: jobv1.OperationState_OPERATION_STATE_PENDING, ResourceVersion: 1, Etag: operationsapp.ResourceETag(identity.TenantID, identity.ProjectID, operationID, 1), Target: target, CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC())}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$7,$8,$9,$10,$11,'PENDING',1,false,$12,NULL,NULL,$13,$14,$14)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetTenantId(), target.GetProjectId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operation.GetEtag(), digest, at.UTC()); err != nil {
		return nil, false, mapUnique(err)
	}
	if err = insertOperationRevision(ctx, tx, operation, at); err != nil {
		return nil, false, err
	}
	runETag := resourceETag(runID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO runs(id,tenant_id,project_id,job_id,input_ref_id,configuration_ref_id,plan_ref_id,status,version,lease_epoch,error_detail_id,etag,created_at,started_at,completed_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,'READY',1,0,NULL,$8,$9,NULL,NULL,$9)`, runID, identity.TenantID, identity.ProjectID, jobID, inputID, configurationID, planID, runETag, at.UTC()); err != nil {
		return nil, false, err
	}
	if err = storeRequest(ctx, tx, identity, request, digest, operationID, jobID, runID); err != nil {
		return nil, false, err
	}
	requestedEvent, err := repository.Events.Requested(identity, request, operation, digest, at)
	if err != nil {
		return nil, false, err
	}
	jobEvent, err := repository.Events.JobRequested(identity, operation, digest, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, actionSubmit, request.GetName(), digest, at); err != nil {
		return nil, false, err
	}
	for _, event := range []*commonv1.EventEnvelope{requestedEvent, jobEvent} {
		if err = insertOutbox(ctx, tx, event, at); err != nil {
			return nil, false, err
		}
	}
	if err = recordReceipt(ctx, tx, identity, actionSubmit, request.GetContext().GetIdempotencyKey(), digest, operationID, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (repository SQLRepository) GetRequest(ctx context.Context, identity Identity, name string) (*inferencev1.InferenceRequest, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	request, _, err := getRequestTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(request), nil
}

func validateCurrentFence(ctx context.Context, tx *sql.Tx, identity Identity, requestRow requestRow, fence *jobv1.LeaseFence, outcome inferencev1.InferenceResultOutcome, at time.Time) (int64, error) {
	presentedDigest, err := jobsapp.LeaseTokenDigest(identity.LeaseToken)
	if err != nil {
		return 0, ErrLeaseToken
	}
	if subtle.ConstantTimeCompare([]byte(presentedDigest), []byte(fence.GetLeaseTokenDigest())) != 1 {
		return 0, ErrLeaseToken
	}
	if fence.GetRunId() != requestRow.schedulerRunID || fence.GetJobId() != requestRow.jobID {
		return 0, ErrStaleFence
	}
	var workerID, tokenDigest, attemptState, runState string
	var attemptEpoch, runEpoch uint64
	var runVersion int64
	var expiry time.Time
	err = tx.QueryRowContext(ctx, `SELECT a.worker_id,a.lease_token_digest,a.lease_epoch,a.lease_expires_at,a.status,r.status,r.lease_epoch,r.version FROM attempts a JOIN runs r ON r.tenant_id=a.tenant_id AND r.project_id=a.project_id AND r.id=a.run_id WHERE a.tenant_id=$1 AND a.project_id=$2 AND a.id=$3 AND a.run_id=$4 FOR UPDATE OF a,r`, identity.TenantID, identity.ProjectID, fence.GetAttemptId(), requestRow.schedulerRunID).Scan(&workerID, &tokenDigest, &attemptEpoch, &expiry, &attemptState, &runState, &runEpoch, &runVersion)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, ErrStaleFence
	}
	if err != nil {
		return 0, err
	}
	if workerID != identity.WorkerID {
		return 0, ErrPermissionDenied
	}
	if subtle.ConstantTimeCompare([]byte(tokenDigest), []byte(presentedDigest)) != 1 {
		return 0, ErrLeaseToken
	}
	if attemptEpoch != fence.GetLeaseEpoch() || runEpoch != fence.GetLeaseEpoch() {
		return 0, ErrStaleFence
	}
	if attemptState != "LEASED" && attemptState != "ACTIVE" {
		return 0, ErrStaleFence
	}
	if runState != "EXECUTING" && (runState != "CANCELLING" || outcome != inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_CANCELLED) {
		return 0, ErrInvalidTransition
	}
	if !at.UTC().Before(expiry.UTC()) || !fence.GetDeadline().AsTime().UTC().Equal(expiry.UTC()) {
		return 0, ErrLeaseExpired
	}
	return runVersion, nil
}

func requireOneMutation(result sql.Result, err error) error {
	if err != nil {
		return err
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if rows != 1 {
		return ErrInvalidTransition
	}
	return nil
}

func schedulerTerminalStates(outcome inferencev1.InferenceResultOutcome) (run, job, attempt string) {
	switch outcome {
	case inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_CANCELLED:
		return "CANCELLED", "CANCELLED", "CANCELLED"
	case inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_EXPIRED:
		return "FAILED", "FAILED", "TIMED_OUT"
	case inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_FAILED,
		inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_POLICY_DENIED:
		return "FAILED", "FAILED", "FAILED"
	default:
		return "SUCCEEDED", "SUCCEEDED", "COMPLETED"
	}
}

func (repository SQLRepository) CommitResult(ctx context.Context, identity Identity, command *internalinferencev1.CommitInferenceResultRequest, digest string, at time.Time) (*inferencev1.InferenceResult, *jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, nil, false, err
	}
	command = clone(command)
	if command == nil || command.GetContext() == nil || command.GetInferenceRequest() == nil {
		return nil, nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, actionCommit, command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, nil, false, err
	}
	if replay {
		operation, loadErr := loadOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		var requestName string
		if loadErr = tx.QueryRowContext(ctx, `SELECT name FROM inference_requests WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3`, identity.TenantID, identity.ProjectID, operationID).Scan(&requestName); loadErr != nil {
			return nil, nil, false, loadErr
		}
		result, loadErr := getResultByRequestTx(ctx, tx, identity, requestName)
		if loadErr != nil {
			return nil, nil, false, loadErr
		}
		if commitErr := tx.Commit(); commitErr != nil {
			return nil, nil, false, commitErr
		}
		return clone(result), clone(operation), true, nil
	}
	request, requestRow, err := getRequestTx(ctx, tx, identity, command.GetInferenceRequest().GetName(), true)
	if err != nil {
		return nil, nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(requestRow.requestDigest), []byte(command.GetRequestDigest())) != 1 {
		return nil, nil, false, ErrInvalidArgument
	}
	if err = validateCommit(identity, command, request, at); err != nil {
		return nil, nil, false, err
	}
	operation, err := loadOperationTx(ctx, tx, identity, requestRow.operationID)
	if err != nil {
		return nil, nil, false, err
	}
	if operation.GetDone() || command.GetResult().GetOperation().GetName() != operation.GetOperationId() || command.GetResult().GetOperation().GetTenantId() != identity.TenantID || command.GetResult().GetOperation().GetProjectId() != identity.ProjectID {
		return nil, nil, false, ErrInvalidTransition
	}
	runVersion, err := validateCurrentFence(ctx, tx, identity, requestRow, command.GetFence(), command.GetResult().GetOutcome(), at)
	if err != nil {
		return nil, nil, false, err
	}
	var jobVersion int64
	if err = tx.QueryRowContext(ctx, `SELECT version FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, requestRow.jobID).Scan(&jobVersion); errors.Is(err, sql.ErrNoRows) {
		return nil, nil, false, ErrInvalidTransition
	} else if err != nil {
		return nil, nil, false, err
	}
	result, manifestID, err := storeResult(ctx, tx, identity, request.GetName(), command.GetResult())
	if err != nil {
		return nil, nil, false, mapUnique(err)
	}
	runState, jobState, attemptState := schedulerTerminalStates(result.GetOutcome())
	if err = requireOneMutation(tx.ExecContext(ctx, `UPDATE attempts SET status=$5,version=version+1,completed_at=$6,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND run_id=$4 AND status IN ('LEASED','ACTIVE')`, identity.TenantID, identity.ProjectID, command.GetFence().GetAttemptId(), requestRow.schedulerRunID, attemptState, at.UTC())); err != nil {
		return nil, nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO attempt_output_refs(tenant_id,project_id,attempt_id,ordinal,artifact_ref_id) VALUES($1,$2,$3,0,$4)`, identity.TenantID, identity.ProjectID, command.GetFence().GetAttemptId(), manifestID); err != nil {
		return nil, nil, false, err
	}
	if err = requireOneMutation(tx.ExecContext(ctx, `UPDATE runs SET status=$4,version=version+1,completed_at=$5,updated_at=$5,etag=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, requestRow.schedulerRunID, runState, at.UTC(), resourceETag(requestRow.schedulerRunID, runVersion+1))); err != nil {
		return nil, nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO run_output_refs(tenant_id,project_id,run_id,ordinal,artifact_ref_id) VALUES($1,$2,$3,0,$4)`, identity.TenantID, identity.ProjectID, requestRow.schedulerRunID, manifestID); err != nil {
		return nil, nil, false, err
	}
	if err = requireOneMutation(tx.ExecContext(ctx, `UPDATE jobs SET desired_state=$4,version=version+1,updated_at=$5,etag=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, requestRow.jobID, jobState, at.UTC(), resourceETag(requestRow.jobID, jobVersion+1))); err != nil {
		return nil, nil, false, err
	}
	if err = requireOneMutation(tx.ExecContext(ctx, `UPDATE operations SET result_ref_id=$4 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, requestRow.operationID, manifestID)); err != nil {
		return nil, nil, false, err
	}
	operation, err = operationsapp.AdvanceTxSQL(ctx, tx, identity.TenantID, identity.ProjectID, requestRow.operationID, operation.GetResourceVersion(), operation.GetEtag(), terminalOperationState(result.GetOutcome()), at)
	if err != nil {
		return nil, nil, false, err
	}
	event, err := repository.Events.ResultCommitted(identity, request, result, operation, command.GetContext(), at)
	if err != nil {
		return nil, nil, false, err
	}
	if err = insertAudit(ctx, tx, identity, actionCommit, result.GetName(), digest, at); err != nil {
		return nil, nil, false, err
	}
	if err = insertOutbox(ctx, tx, event, at); err != nil {
		return nil, nil, false, err
	}
	if err = recordReceipt(ctx, tx, identity, actionCommit, command.GetContext().GetIdempotencyKey(), digest, operation.GetOperationId(), at); err != nil {
		return nil, nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, false, err
	}
	return clone(result), clone(operation), false, nil
}

func (repository SQLRepository) GetResult(ctx context.Context, identity Identity, operationName string) (*inferencev1.InferenceResult, *jobv1.Operation, error) {
	if err := repository.validate(); err != nil {
		return nil, nil, err
	}
	operationName, err := operationID(operationName)
	if err != nil {
		return nil, nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, nil, err
	}
	defer func() { _ = tx.Rollback() }()
	operation, err := loadOperationTx(ctx, tx, identity, operationName)
	if err != nil {
		return nil, nil, err
	}
	var requestName string
	if err = tx.QueryRowContext(ctx, `SELECT name FROM inference_requests WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3`, identity.TenantID, identity.ProjectID, operationName).Scan(&requestName); errors.Is(err, sql.ErrNoRows) {
		return nil, nil, ErrNotFound
	} else if err != nil {
		return nil, nil, err
	}
	result, err := getResultByRequestTx(ctx, tx, identity, requestName)
	if err != nil {
		return nil, nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, nil, err
	}
	return clone(result), clone(operation), nil
}

func (repository SQLRepository) GetResultByRequest(ctx context.Context, identity Identity, requestName string) (*inferencev1.InferenceResult, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	result, err := getResultByRequestTx(ctx, tx, identity, requestName)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(result), nil
}

const operationRevisionColumns = `operation_id,tenant_id,project_id,job_id,status,revision,done,etag,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,result_ref_id,error_detail_id,created_at,updated_at`

func (repository SQLRepository) ReadOperationRevisions(ctx context.Context, identity Identity, operationName string, after uint64, limit int) (string, []*jobv1.Operation, bool, error) {
	if err := repository.validate(); err != nil {
		return "", nil, false, err
	}
	operationName, err := operationID(operationName)
	if err != nil || limit <= 0 || limit > operationWatchBatchSize {
		return "", nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return "", nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	var requestName string
	if err = tx.QueryRowContext(ctx, `SELECT name FROM inference_requests WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3`, identity.TenantID, identity.ProjectID, operationName).Scan(&requestName); errors.Is(err, sql.ErrNoRows) {
		return "", nil, false, ErrNotFound
	} else if err != nil {
		return "", nil, false, err
	}
	var current, floor uint64
	var done bool
	if err = tx.QueryRowContext(ctx, `SELECT version,history_floor_version,done FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, operationName).Scan(&current, &floor, &done); err != nil {
		return "", nil, false, err
	}
	if after > current {
		return "", nil, false, ErrCursorAhead
	}
	if after+1 < floor {
		return "", nil, false, ErrCursorExpired
	}
	rows, err := tx.QueryContext(ctx, `SELECT `+operationRevisionColumns+` FROM operation_revisions WHERE tenant_id=$1 AND project_id=$2 AND operation_id=$3 AND revision>$4 ORDER BY revision LIMIT $5`, identity.TenantID, identity.ProjectID, operationName, after, limit+1) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return "", nil, false, err
	}
	stored := make([]operationRow, 0, limit+1)
	for rows.Next() {
		value, scanErr := scanOperation(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return "", nil, false, scanErr
		}
		stored = append(stored, value)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return "", nil, false, err
	}
	if err = rows.Err(); err != nil {
		return "", nil, false, err
	}
	hasMore := len(stored) > limit
	if hasMore {
		stored = stored[:limit]
	}
	expected := after + 1
	revisions := make([]*jobv1.Operation, 0, len(stored))
	for _, row := range stored {
		rowVersion, conversionErr := numconv.Int64ToUint64(row.version)
		if conversionErr != nil {
			return "", nil, false, conversionErr
		}
		if rowVersion != expected {
			return "", nil, false, ErrHistoryGap
		}
		revision, mapErr := operationProto(ctx, tx, row)
		if mapErr != nil {
			return "", nil, false, mapErr
		}
		revisions = append(revisions, revision)
		expected++
	}
	if len(revisions) == 0 && after < current {
		return "", nil, false, ErrHistoryGap
	}
	lastRevision := uint64(0)
	if len(revisions) > 0 {
		lastRevision, err = numconv.Int64ToUint64(revisions[len(revisions)-1].GetResourceVersion())
		if err != nil {
			return "", nil, false, err
		}
	}
	terminal := done && !hasMore && (len(revisions) > 0 && lastRevision == current || len(revisions) == 0 && after == current)
	if err = tx.Commit(); err != nil {
		return "", nil, false, err
	}
	return requestName, cloneSlice(revisions), terminal, nil
}

type sqlStateCarrier interface{ SQLState() string }

func mapUnique(err error) error {
	var state sqlStateCarrier
	if errors.As(err, &state) && state.SQLState() == "23505" {
		return ErrAlreadyExists
	}
	return err
}
