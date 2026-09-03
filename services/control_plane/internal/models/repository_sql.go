package models

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Pagination == nil || r.Events == nil {
		return errors.New("model SQL repository requires database, pagination codec, and event factory")
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
	var stored, id string
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id FROM data_model_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&stored, &id)
	if errors.Is(err, sql.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(digest)) != 1 {
		return "", false, ErrIdempotencyConflict
	}
	return id, true, nil
}

func replayOperation(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*jobv1.Operation, bool, error) {
	operation, err := getOperationTx(ctx, tx, identity, id)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), true, nil
}

func insertAudit(ctx context.Context, tx *sql.Tx, identity Identity, action, subject, digest string, at time.Time) error {
	event, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, subject, "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	encoded, err := queue.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, event.GetEventId(), identity.TenantID, identity.Principal, action, subject, at.UTC(), digest, event.GetEventVersion(), event.GetPayloadDigest(), encoded)
	return err
}

func insertCompletedOperation(ctx context.Context, tx *sql.Tx, identity Identity, digest string, target *commonv1.ResourceRef, at time.Time) (*jobv1.Operation, error) {
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, err
	}
	operationID, err := randomID("operations/")
	if err != nil {
		return nil, err
	}
	jobETag := resourceETag(jobID, 1)
	operationETag := resourceETag(operationID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'SUCCEEDED',1,'','model.lifecycle',NULL,NULL,$5,$6,$7,$7)`, jobID, identity.TenantID, operationID, identity.ProjectID, digest, jobETag, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$2,$3,$7,$8,$9,'SUCCEEDED',1,true,$10,NULL,NULL,$11,$12,$12)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, digest, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operation_revisions(operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at) VALUES($1,$2,$3,1,$4,true,$5,$6,$2,$3,$7,$8,$9,'SUCCEEDED',true,$10,NULL,NULL,$11,$11,$11)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, at.UTC()); err != nil {
		return nil, err
	}
	return &jobv1.Operation{OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID, State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 1, Done: true, Etag: operationETag, Target: clone(target), CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC())}, nil
}

func recordMutation(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string, operation *jobv1.Operation, events []*commonv1.EventEnvelope, at time.Time) error {
	if operation == nil || operation.GetTarget() == nil || len(events) == 0 {
		return ErrInvalidArgument
	}
	if err := insertAudit(ctx, tx, identity, action, operation.GetTarget().GetName(), digest, at); err != nil {
		return err
	}
	for _, event := range events {
		if err := queue.InsertOutboxMessage(ctx, tx, event, at); err != nil {
			return err
		}
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO data_model_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, operation.GetOperationId(), at.UTC())
	return err
}

func finishMutation(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string, target *commonv1.ResourceRef, event *commonv1.EventEnvelope, at time.Time) (*jobv1.Operation, error) {
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, target, at)
	if err != nil {
		return nil, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, err
	}
	return operation, nil
}

func (r SQLRepository) RegisterModel(ctx context.Context, identity Identity, command *modelv1.RegisterModelCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || !validID(command.GetModelId()) || command.GetDisplayName() == "" || command.GetFamily() == "" {
		return nil, false, ErrInvalidArgument
	}
	command = clone(command)
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	if err = validateReference(identity, command.GetProject(), "project", "project"); err != nil {
		return nil, false, err
	}
	if command.GetProject().GetResourceId() != identity.ProjectID || command.GetProject().GetName() != projectParent(identity) {
		return nil, false, ErrPermissionDenied
	}
	// Validate separately to keep each authoritative field's diagnostic stable.
	if err = validateArtifact(command.GetDefinitionManifest(), "definition manifest"); err != nil {
		return nil, false, err
	}
	if err = validateArtifact(command.GetFeatureRequirementSet(), "feature requirement set"); err != nil {
		return nil, false, err
	}
	if err = validateArtifact(command.GetModelFeatureView(), "model feature view"); err != nil {
		return nil, false, err
	}
	if err = validateArtifact(command.GetInputContract(), "input contract"); err != nil {
		return nil, false, err
	}
	if err = validateArtifact(command.GetOutputContract(), "output contract"); err != nil {
		return nil, false, err
	}
	name, err := modelName(identity, command.GetModelId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "model.register", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM models WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	definition, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetDefinitionManifest())
	if err != nil {
		return nil, false, err
	}
	requirements, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetFeatureRequirementSet())
	if err != nil {
		return nil, false, err
	}
	view, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetModelFeatureView())
	if err != nil {
		return nil, false, err
	}
	input, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetInputContract())
	if err != nil {
		return nil, false, err
	}
	output, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetOutputContract())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("mdl_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO models(tenant_id,project_id,name,uid,revision,etag,display_name,family,state,definition_manifest_ref_id,feature_requirement_set_ref_id,model_feature_view_ref_id,input_contract_ref_id,output_contract_ref_id,policy_classification,create_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`, identity.TenantID, identity.ProjectID, name, uid, etag, command.GetDisplayName(), command.GetFamily(), int32(modelv1.ModelState_MODEL_STATE_ACTIVE), definition, requirements, view, input, output, command.GetPolicyClassification(), at.UTC()); err != nil {
		return nil, false, err
	}
	for key, value := range command.GetLabels() {
		if key == "" || len(key) > 128 || len(value) > 256 {
			return nil, false, ErrInvalidArgument
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO model_labels(tenant_id,project_id,model_name,label_key,label_value) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, key, value); err != nil {
			return nil, false, err
		}
	}
	row, err := scanModel(tx.QueryRowContext(ctx, `SELECT `+modelColumns+` FROM models WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, false, err
	}
	model, err := modelProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	event, err := r.Events.Registered(identity, model, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	operation, err := finishMutation(ctx, tx, identity, "model.register", command.GetContext().GetIdempotencyKey(), digest, modelResource(model), event, at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) RegisterModelRelease(ctx context.Context, identity Identity, command *modelv1.RegisterModelReleaseCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	factory, available := r.Events.(ModelReleaseEventFactory)
	if !available {
		return nil, false, missingEvent(RegisterReleaseEventContract)
	}
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || !validID(command.GetReleaseId()) || len(command.GetEvaluationEvidence()) == 0 {
		return nil, false, ErrInvalidArgument
	}
	command = clone(command)
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	if err = validateReference(identity, command.GetModel(), "model", "model"); err != nil {
		return nil, false, err
	}
	if err = validateReference(identity, command.GetCheckpoint(), "checkpoint", "checkpoint"); err != nil {
		return nil, false, err
	}
	if err = validateReference(identity, command.GetReleasePolicy(), "release_policy", "release policy"); err != nil {
		return nil, false, err
	}
	for _, field := range []struct {
		label string
		value *artifactv1.ArtifactRef
	}{
		{label: "bundle manifest", value: command.GetBundleManifest()},
		{label: "model manifest", value: command.GetModelManifest()},
		{label: "feature requirement set", value: command.GetFeatureRequirementSet()},
		{label: "model feature view", value: command.GetModelFeatureView()},
	} {
		if err = validateArtifact(field.value, field.label); err != nil {
			return nil, false, err
		}
	}
	for _, evidence := range command.GetEvaluationEvidence() {
		if err = validateEvidence(evidence, "evaluation evidence"); err != nil {
			return nil, false, err
		}
		if subtle.ConstantTimeCompare([]byte(evidence.GetSubjectDigest()), []byte(command.GetBundleManifest().GetDigest())) != 1 {
			return nil, false, fmt.Errorf("%w: evaluation evidence does not bind the bundle manifest", ErrInvalidArgument)
		}
	}
	modelName, err := modelName(identity, command.GetModel().GetName())
	if err != nil {
		return nil, false, err
	}
	if modelName != command.GetModel().GetName() {
		return nil, false, ErrInvalidArgument
	}
	name := modelName + "/releases/" + command.GetReleaseId()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "model.release.register", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	var modelRevision int64
	var modelETag string
	err = tx.QueryRowContext(ctx, `SELECT revision,etag FROM models WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, modelName).Scan(&modelRevision, &modelETag)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if command.GetModel().GetResourceVersion() > 0 && command.GetModel().GetResourceVersion() != modelRevision {
		return nil, false, ErrRevisionConflict
	}
	if command.GetModel().GetEtag() != "" && command.GetModel().GetEtag() != modelETag {
		return nil, false, ErrRevisionConflict
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	bundleID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetBundleManifest())
	if err != nil {
		return nil, false, err
	}
	manifestID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetModelManifest())
	if err != nil {
		return nil, false, err
	}
	checkpointID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetCheckpoint())
	if err != nil {
		return nil, false, err
	}
	requirementsID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetFeatureRequirementSet())
	if err != nil {
		return nil, false, err
	}
	viewID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetModelFeatureView())
	if err != nil {
		return nil, false, err
	}
	policyID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetReleasePolicy())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("mlr_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	_, err = tx.ExecContext(ctx, `INSERT INTO model_releases(tenant_id,project_id,name,uid,model_name,release_id,revision,etag,stage,bundle_manifest_ref_id,model_manifest_ref_id,checkpoint_ref_id,feature_requirement_set_ref_id,model_feature_view_ref_id,release_policy_ref_id,policy_classification,create_time) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)`, identity.TenantID, identity.ProjectID, name, uid, modelName, command.GetReleaseId(), etag, int32(modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL), bundleID, manifestID, checkpointID, requirementsID, viewID, policyID, command.GetPolicyClassification(), at.UTC())
	if err != nil {
		return nil, false, err
	}
	for ordinal, evidence := range command.GetEvaluationEvidence() {
		_, err = tx.ExecContext(ctx, `INSERT INTO model_release_evaluation_evidence(tenant_id,project_id,release_name,ordinal,digest,subject_digest,evidence_kind,policy_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, name, ordinal, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest())
		if err != nil {
			return nil, false, err
		}
	}
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, false, err
	}
	release, err := releaseProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, releaseResource(release), at)
	if err != nil {
		return nil, false, err
	}
	event, err := factory.ReleaseRegistered(identity, release, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "model.release.register", command.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func validPromotion(from, to modelv1.ModelReleaseStage) bool {
	return (from == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_EXPERIMENTAL && to == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED) || (from == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED && to == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_RELEASE_CANDIDATE) || (from == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_RELEASE_CANDIDATE && to == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_RELEASED) || (from == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_RELEASED && to == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_DEPRECATED)
}

func storeTransitionEvidence(ctx context.Context, tx *sql.Tx, identity Identity, name string, revision int64, kind string, values []*artifactv1.EvidenceRef, at time.Time) error {
	for ordinal, value := range values {
		if err := validateEvidence(value, "transition evidence"); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO model_release_transition_evidence(tenant_id,project_id,release_name,release_revision,transition_kind,ordinal,digest,subject_digest,evidence_kind,policy_digest,occurred_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, identity.TenantID, identity.ProjectID, name, revision, kind, ordinal, value.GetDigest(), value.GetSubjectDigest(), value.GetEvidenceKind(), value.GetPolicyDigest(), at.UTC()); err != nil {
			return err
		}
	}
	return nil
}

func (r SQLRepository) PromoteModelRelease(ctx context.Context, identity Identity, command *modelv1.PromoteModelReleaseCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || len(command.GetEvidence()) == 0 || command.GetPromotionDecision() == nil {
		return nil, false, ErrInvalidArgument
	}
	command = clone(command)
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	if err = validateReference(identity, command.GetModelRelease(), "model_release", "model release"); err != nil {
		return nil, false, err
	}
	for _, value := range command.GetEvidence() {
		if err = validateEvidence(value, "promotion evidence"); err != nil {
			return nil, false, err
		}
	}
	if err = validateEvidence(command.GetPromotionDecision(), "promotion decision"); err != nil {
		return nil, false, err
	}
	if !validPromotion(command.GetExpectedStage(), command.GetTargetStage()) {
		return nil, false, ErrInvalidTransition
	}
	name, err := releaseName(identity, command.GetModelRelease().GetName())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "model.release.promote", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if row.etag != command.GetEtag() || row.stage != int32(command.GetExpectedStage()) {
		return nil, false, ErrRevisionConflict
	}
	revision := row.revision + 1
	etag := resourceETag(row.name, revision)
	result, err := tx.ExecContext(ctx, `UPDATE model_releases SET revision=$4,etag=$5,stage=$6::integer,qualify_time=CASE WHEN $6::integer=$7::integer THEN COALESCE(qualify_time,$8::timestamptz) ELSE qualify_time END,release_time=CASE WHEN $6::integer=$9::integer THEN COALESCE(release_time,$8::timestamptz) ELSE release_time END WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$10 AND etag=$11`, identity.TenantID, identity.ProjectID, row.name, revision, etag, int32(command.GetTargetStage()), int32(modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_QUALIFIED), at.UTC(), int32(modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_RELEASED), row.revision, row.etag)
	if err != nil {
		return nil, false, err
	}
	if count, _ := result.RowsAffected(); count != 1 {
		return nil, false, ErrRevisionConflict
	}
	if err = storeTransitionEvidence(ctx, tx, identity, row.name, revision, "PROMOTION", command.GetEvidence(), at); err != nil {
		return nil, false, err
	}
	if err = storeTransitionEvidence(ctx, tx, identity, row.name, revision, "PROMOTION_DECISION", []*artifactv1.EvidenceRef{command.GetPromotionDecision()}, at); err != nil {
		return nil, false, err
	}
	updated, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, row.name))
	if err != nil {
		return nil, false, err
	}
	release, err := releaseProto(ctx, tx, updated)
	if err != nil {
		return nil, false, err
	}
	event, err := r.Events.Promoted(identity, release, modelv1.ModelReleaseStage(row.stage), command.GetEvidence(), command.GetPromotionDecision(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	operation, err := finishMutation(ctx, tx, identity, "model.release.promote", command.GetContext().GetIdempotencyKey(), digest, releaseResource(release), event, at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) RevokeModelRelease(ctx context.Context, identity Identity, command *modelv1.RevokeModelReleaseCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || command.GetReason() == "" || len(command.GetReason()) > 1024 || len(command.GetEvidence()) == 0 {
		return nil, false, ErrInvalidArgument
	}
	command = clone(command)
	canonical, err := validateContext(identity, command, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return nil, false, ErrInvalidArgument
	}
	if err = validateReference(identity, command.GetModelRelease(), "model_release", "model release"); err != nil {
		return nil, false, err
	}
	for _, value := range command.GetEvidence() {
		if err = validateEvidence(value, "revocation evidence"); err != nil {
			return nil, false, err
		}
	}
	name, err := releaseName(identity, command.GetModelRelease().GetName())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "model.release.revoke", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if row.etag != command.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if modelv1.ModelReleaseStage(row.stage) == modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_REVOKED {
		return nil, false, ErrInvalidTransition
	}
	revision := row.revision + 1
	etag := resourceETag(row.name, revision)
	result, err := tx.ExecContext(ctx, `UPDATE model_releases SET revision=$4,etag=$5,stage=$6,revoke_time=$7,revocation_reason=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, row.name, revision, etag, int32(modelv1.ModelReleaseStage_MODEL_RELEASE_STAGE_REVOKED), at.UTC(), command.GetReason(), row.revision, row.etag)
	if err != nil {
		return nil, false, err
	}
	if count, _ := result.RowsAffected(); count != 1 {
		return nil, false, ErrRevisionConflict
	}
	if err = storeTransitionEvidence(ctx, tx, identity, row.name, revision, "REVOCATION", command.GetEvidence(), at); err != nil {
		return nil, false, err
	}
	updated, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM model_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, row.name))
	if err != nil {
		return nil, false, err
	}
	release, err := releaseProto(ctx, tx, updated)
	if err != nil {
		return nil, false, err
	}
	event, err := r.Events.Revoked(identity, release, command.GetEvidence(), command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	operation, err := finishMutation(ctx, tx, identity, "model.release.revoke", command.GetContext().GetIdempotencyKey(), digest, releaseResource(release), event, at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}
