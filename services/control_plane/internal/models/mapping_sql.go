package models

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

type (
	scanner  interface{ Scan(...any) error }
	modelRow struct {
		tenant, project, name, uid, etag, display, family, classification, current string
		revision                                                                   int64
		state                                                                      int32
		definition, requirements, view, input, output                              sql.NullInt64
		created                                                                    time.Time
		updated, deleted                                                           sql.NullTime
	}
)

const modelColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,family,state,definition_manifest_ref_id,feature_requirement_set_ref_id,model_feature_view_ref_id,input_contract_ref_id,output_contract_ref_id,policy_classification,create_time,update_time,delete_time,current_release_name`

func scanModel(row scanner) (modelRow, error) {
	var v modelRow
	err := row.Scan(&v.tenant, &v.project, &v.name, &v.uid, &v.revision, &v.etag, &v.display, &v.family, &v.state, &v.definition, &v.requirements, &v.view, &v.input, &v.output, &v.classification, &v.created, &v.updated, &v.deleted, &v.current)
	return v, err
}

func modelProto(ctx context.Context, tx *sql.Tx, row modelRow) (*modelv1.Model, error) {
	definition, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.definition)
	if err != nil {
		return nil, err
	}
	requirements, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.requirements)
	if err != nil {
		return nil, err
	}
	view, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.view)
	if err != nil {
		return nil, err
	}
	input, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.input)
	if err != nil {
		return nil, err
	}
	output, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.output)
	if err != nil {
		return nil, err
	}
	value := &modelv1.Model{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantName: "tenants/" + row.tenant, ProjectName: "tenants/" + row.tenant + "/projects/" + row.project, DisplayName: row.display, Family: row.family, State: modelv1.ModelState(row.state), DefinitionManifest: definition, FeatureRequirementSet: requirements, ModelFeatureView: view, InputContract: input, OutputContract: output, PolicyClassification: row.classification, CreateTime: timestamppb.New(row.created.UTC()), CurrentReleaseName: row.current}
	if row.updated.Valid {
		value.UpdateTime = timestamppb.New(row.updated.Time.UTC())
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	if value.Labels, err = platformdb.LoadStringMap(ctx, tx, `SELECT label_key,label_value FROM model_labels WHERE tenant_id=$1 AND project_id=$2 AND model_name=$3 ORDER BY label_key`, row.tenant, row.project, row.name); err != nil {
		return nil, err
	}
	if value.Annotations, err = platformdb.LoadStringMap(ctx, tx, `SELECT annotation_key,annotation_value FROM model_annotations WHERE tenant_id=$1 AND project_id=$2 AND model_name=$3 ORDER BY annotation_key`, row.tenant, row.project, row.name); err != nil {
		return nil, err
	}
	return value, nil
}

type releaseRow struct {
	tenant, project, name, uid, modelName, releaseID, etag, classification, reason string
	revision                                                                       int64
	stage                                                                          int32
	bundle, manifest, checkpoint, requirements, view, policy                       sql.NullInt64
	created                                                                        time.Time
	qualified, released, revoked                                                   sql.NullTime
}

const releaseColumns = `tenant_id,project_id,name,uid,model_name,release_id,revision,etag,stage,bundle_manifest_ref_id,model_manifest_ref_id,checkpoint_ref_id,feature_requirement_set_ref_id,model_feature_view_ref_id,release_policy_ref_id,policy_classification,create_time,qualify_time,release_time,revoke_time,revocation_reason`

func scanRelease(row scanner) (releaseRow, error) {
	var v releaseRow
	err := row.Scan(&v.tenant, &v.project, &v.name, &v.uid, &v.modelName, &v.releaseID, &v.revision, &v.etag, &v.stage, &v.bundle, &v.manifest, &v.checkpoint, &v.requirements, &v.view, &v.policy, &v.classification, &v.created, &v.qualified, &v.released, &v.revoked, &v.reason)
	return v, err
}

func releaseProto(ctx context.Context, tx *sql.Tx, row releaseRow) (*modelv1.ModelRelease, error) {
	bundle, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.bundle)
	if err != nil {
		return nil, err
	}
	manifest, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.manifest)
	if err != nil {
		return nil, err
	}
	checkpoint, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.checkpoint)
	if err != nil {
		return nil, err
	}
	requirements, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.requirements)
	if err != nil {
		return nil, err
	}
	view, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.view)
	if err != nil {
		return nil, err
	}
	policy, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.policy)
	if err != nil {
		return nil, err
	}
	value := &modelv1.ModelRelease{Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, TenantName: "tenants/" + row.tenant, ProjectName: "tenants/" + row.tenant + "/projects/" + row.project, ModelName: row.modelName, ReleaseId: row.releaseID, Stage: modelv1.ModelReleaseStage(row.stage), BundleManifest: bundle, ModelManifest: manifest, Checkpoint: checkpoint, FeatureRequirementSet: requirements, ModelFeatureView: view, ReleasePolicy: policy, PolicyClassification: row.classification, CreateTime: timestamppb.New(row.created.UTC()), RevocationReason: row.reason}
	if row.qualified.Valid {
		value.QualifyTime = timestamppb.New(row.qualified.Time.UTC())
	}
	if row.released.Valid {
		value.ReleaseTime = timestamppb.New(row.released.Time.UTC())
	}
	if row.revoked.Valid {
		value.RevokeTime = timestamppb.New(row.revoked.Time.UTC())
	}
	rows, err := tx.QueryContext(ctx, `SELECT digest,subject_digest,evidence_kind,policy_digest FROM model_release_evaluation_evidence WHERE tenant_id=$1 AND project_id=$2 AND release_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		item := new(artifactv1.EvidenceRef)
		if err = rows.Scan(&item.Digest, &item.SubjectDigest, &item.EvidenceKind, &item.PolicyDigest); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.EvaluationEvidence = append(value.EvaluationEvidence, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	return value, nil
}

type operationRow struct {
	id, tenant, project, job, status, etag, targetType, targetID, targetTenant, targetProject, targetName, targetETag string
	version, targetVersion                                                                                            int64
	done, targetPresent                                                                                               bool
	result, errorDetail                                                                                               sql.NullInt64
	created, updated                                                                                                  time.Time
}

const operationColumns = `id,tenant_id,project_id,job_id,status,version,done,etag,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,result_ref_id,error_detail_id,created_at,updated_at`

func scanOperation(row scanner) (operationRow, error) {
	var v operationRow
	err := row.Scan(&v.id, &v.tenant, &v.project, &v.job, &v.status, &v.version, &v.done, &v.etag, &v.targetPresent, &v.targetType, &v.targetID, &v.targetTenant, &v.targetProject, &v.targetVersion, &v.targetName, &v.targetETag, &v.result, &v.errorDetail, &v.created, &v.updated)
	return v, err
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
	var state operationv1.OperationState
	switch row.status {
	case "PENDING":
		state = operationv1.OperationState_OPERATION_STATE_PENDING
	case "RUNNING":
		state = operationv1.OperationState_OPERATION_STATE_RUNNING
	case "SUCCEEDED":
		state = operationv1.OperationState_OPERATION_STATE_SUCCEEDED
	case "FAILED":
		state = operationv1.OperationState_OPERATION_STATE_FAILED
	case "CANCELLING":
		state = operationv1.OperationState_OPERATION_STATE_CANCELLING
	case "CANCELLED":
		state = operationv1.OperationState_OPERATION_STATE_CANCELLED
	default:
		return nil, ErrInvalidArgument
	}
	value := &operationv1.Operation{OperationId: row.id, TenantId: row.tenant, ProjectId: row.project, JobId: row.job, State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag, Result: result, Error: detail, CreatedAt: timestamppb.New(row.created.UTC()), UpdatedAt: timestamppb.New(row.updated.UTC())}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant, ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag}
	}
	return value, nil
}

func getOperationTx(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*operationv1.Operation, error) {
	row, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return operationProto(ctx, tx, row)
}
