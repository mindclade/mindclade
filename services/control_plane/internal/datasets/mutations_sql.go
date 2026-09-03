package datasets

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"sort"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

func (r SQLRepository) validateMutation() error {
	if err := r.validate(); err != nil {
		return err
	}
	if r.Events == nil {
		return errors.New("dataset SQL repository requires a generated event factory for mutations")
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
	var stored, operationID string
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id FROM data_model_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&stored, &operationID)
	if errors.Is(err, sql.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(digest)) != 1 {
		return "", false, ErrIdempotencyConflict
	}
	return operationID, true, nil
}

type operationRow struct {
	id, tenant, project, job, status, etag            string
	targetType, targetID, targetTenant, targetProject string
	targetName, targetETag                            string
	version, targetVersion                            int64
	done, targetPresent                               bool
	result, errorDetail                               sql.NullInt64
	created, updated                                  time.Time
}

const operationColumns = `id,tenant_id,project_id,job_id,status,version,done,etag,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,result_ref_id,error_detail_id,created_at,updated_at`

func scanOperation(row scanner) (operationRow, error) {
	var value operationRow
	err := row.Scan(&value.id, &value.tenant, &value.project, &value.job, &value.status, &value.version, &value.done, &value.etag, &value.targetPresent, &value.targetType, &value.targetID, &value.targetTenant, &value.targetProject, &value.targetVersion, &value.targetName, &value.targetETag, &value.result, &value.errorDetail, &value.created, &value.updated)
	return value, err
}

func operationProto(ctx context.Context, tx *sql.Tx, row operationRow) (*jobv1.Operation, error) {
	result, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.result)
	if err != nil {
		return nil, err
	}
	detail, err := platformdb.LoadErrorDetail(ctx, tx, row.tenant, row.errorDetail)
	if err != nil {
		return nil, err
	}
	var state jobv1.OperationState
	switch row.status {
	case "PENDING":
		state = jobv1.OperationState_OPERATION_STATE_PENDING
	case "RUNNING":
		state = jobv1.OperationState_OPERATION_STATE_RUNNING
	case "SUCCEEDED":
		state = jobv1.OperationState_OPERATION_STATE_SUCCEEDED
	case "FAILED":
		state = jobv1.OperationState_OPERATION_STATE_FAILED
	case "CANCELLING":
		state = jobv1.OperationState_OPERATION_STATE_CANCELLING
	case "CANCELLED":
		state = jobv1.OperationState_OPERATION_STATE_CANCELLED
	default:
		return nil, ErrInvalidArgument
	}
	value := &jobv1.Operation{OperationId: row.id, TenantId: row.tenant, ProjectId: row.project, JobId: row.job, State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag, Result: result, Error: detail, CreatedAt: timestamppb.New(row.created.UTC()), UpdatedAt: timestamppb.New(row.updated.UTC())}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant, ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag}
	}
	return value, nil
}

func replayOperation(ctx context.Context, tx *sql.Tx, identity Identity, operationID string) (*jobv1.Operation, bool, error) {
	row, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, operationID))
	if err != nil {
		return nil, false, err
	}
	operation, err := operationProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), true, nil
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
	jobETag, operationETag := resourceETag(jobID, 1), resourceETag(operationID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'SUCCEEDED',1,'','dataset.lifecycle',NULL,NULL,$5,$6,$7,$7)`, jobID, identity.TenantID, operationID, identity.ProjectID, digest, jobETag, at.UTC()); err != nil {
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
	audit, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, operation.GetTarget().GetName(), "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	encodedAudit, err := pubsubx.MarshalEnvelope(audit)
	if err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, audit.GetEventId(), identity.TenantID, identity.Principal, action, operation.GetTarget().GetName(), at.UTC(), digest, audit.GetEventVersion(), audit.GetPayloadDigest(), encodedAudit); err != nil {
		return err
	}
	for _, event := range events {
		encoded, marshalErr := pubsubx.MarshalEnvelope(event)
		if marshalErr != nil {
			return marshalErr
		}
		kind, id, identityErr := pubsubx.AggregateIdentity(event)
		if identityErr != nil {
			return identityErr
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages(id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, event.GetEventId(), event.GetTenantId(), event.GetEventType(), event.GetEventVersion(), kind, id, event.GetAggregateSequence(), event.GetPayloadDigest(), encoded, at.UTC()); err != nil {
			return err
		}
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO data_model_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, operation.GetOperationId(), at.UTC())
	return err
}

func validateMap(values map[string]string, maximumValue int) error {
	for key, value := range values {
		if key == "" || len(key) > 128 || len(value) > maximumValue {
			return ErrInvalidArgument
		}
	}
	return nil
}

func (r SQLRepository) CreateDataset(ctx context.Context, identity Identity, command *datasetv1.CreateDatasetCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validateMutation(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || !validID(command.GetDatasetId()) || command.GetDisplayName() == "" {
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
	if command.GetProject().GetResourceId() != identity.ProjectID || command.GetProject().GetName() != "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID {
		return nil, false, ErrPermissionDenied
	}
	if err = validateMap(command.GetLabels(), 256); err != nil {
		return nil, false, err
	}
	if err = validateMap(command.GetAnnotations(), 4096); err != nil {
		return nil, false, err
	}
	name, err := canonicalDatasetName(identity, command.GetDatasetId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "dataset.create", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	uid, err := randomID("dst_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO datasets(tenant_id,project_id,name,uid,revision,etag,display_name,state,policy_classification,create_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9)`, identity.TenantID, identity.ProjectID, name, uid, etag, command.GetDisplayName(), int32(datasetv1.DatasetState_DATASET_STATE_DRAFT), command.GetPolicyClassification(), at.UTC()); err != nil {
		return nil, false, err
	}
	if err = storeDatasetMaps(ctx, tx, identity, name, command.GetLabels(), command.GetAnnotations()); err != nil {
		return nil, false, err
	}
	row, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, false, err
	}
	dataset, err := datasetProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, datasetResource(dataset), at)
	if err != nil {
		return nil, false, err
	}
	event, err := r.Events.Created(identity, dataset, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "dataset.create", command.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func storeDatasetMaps(ctx context.Context, tx *sql.Tx, identity Identity, name string, labels, annotations map[string]string) error {
	for key, value := range labels {
		if _, err := tx.ExecContext(ctx, `INSERT INTO dataset_labels(tenant_id,project_id,dataset_name,label_key,label_value) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, key, value); err != nil {
			return err
		}
	}
	for key, value := range annotations {
		if _, err := tx.ExecContext(ctx, `INSERT INTO dataset_annotations(tenant_id,project_id,dataset_name,annotation_key,annotation_value) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, key, value); err != nil {
			return err
		}
	}
	return nil
}

func validDatasetTransition(from, to datasetv1.DatasetState) bool {
	return (from == datasetv1.DatasetState_DATASET_STATE_DRAFT && to == datasetv1.DatasetState_DATASET_STATE_ACTIVE) || (from == datasetv1.DatasetState_DATASET_STATE_ACTIVE && to == datasetv1.DatasetState_DATASET_STATE_DEPRECATED) || ((from == datasetv1.DatasetState_DATASET_STATE_ACTIVE || from == datasetv1.DatasetState_DATASET_STATE_DEPRECATED) && to == datasetv1.DatasetState_DATASET_STATE_REVOKED)
}

func (r SQLRepository) UpdateDataset(ctx context.Context, identity Identity, command *datasetv1.UpdateDatasetCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validateMutation(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || command.GetDataset() == nil || command.GetUpdateMask() == nil || len(command.GetUpdateMask().GetPaths()) == 0 || command.GetEtag() == "" {
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
	name, err := canonicalDatasetName(identity, command.GetDataset().GetName())
	if err != nil || name != command.GetDataset().GetName() {
		return nil, false, ErrInvalidArgument
	}
	allowed := map[string]bool{"display_name": true, "labels": true, "annotations": true, "state": true, "policy_classification": true}
	seen := map[string]bool{}
	paths := make([]string, 0, len(command.GetUpdateMask().GetPaths()))
	for _, path := range command.GetUpdateMask().GetPaths() {
		if !allowed[path] || seen[path] {
			return nil, false, ErrInvalidArgument
		}
		seen[path] = true
		paths = append(paths, path)
	}
	sort.Strings(paths)
	if seen["display_name"] && command.GetDataset().GetDisplayName() == "" {
		return nil, false, ErrInvalidArgument
	}
	if seen["labels"] {
		if err = validateMap(command.GetDataset().GetLabels(), 256); err != nil {
			return nil, false, err
		}
	}
	if seen["annotations"] {
		if err = validateMap(command.GetDataset().GetAnnotations(), 4096); err != nil {
			return nil, false, err
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "dataset.update", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	row, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if row.etag != command.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	next, err := datasetProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	input := command.GetDataset()
	if seen["display_name"] {
		next.DisplayName = input.GetDisplayName()
	}
	if seen["labels"] {
		next.Labels = cloneMap(input.GetLabels())
	}
	if seen["annotations"] {
		next.Annotations = cloneMap(input.GetAnnotations())
	}
	if seen["state"] {
		if !validDatasetTransition(next.GetState(), input.GetState()) {
			return nil, false, ErrInvalidTransition
		}
		next.State = input.GetState()
	}
	if seen["policy_classification"] {
		next.PolicyClassification = input.GetPolicyClassification()
	}
	next.Revision = row.revision + 1
	next.Etag = resourceETag(name, next.Revision)
	next.UpdateTime = timestamppb.New(at.UTC())
	result, err := tx.ExecContext(ctx, `UPDATE datasets SET revision=$4,etag=$5,display_name=$6,state=$7,policy_classification=$8,update_time=$9 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$10 AND etag=$11`, identity.TenantID, identity.ProjectID, name, next.GetRevision(), next.GetEtag(), next.GetDisplayName(), int32(next.GetState()), next.GetPolicyClassification(), at.UTC(), row.revision, row.etag)
	if err != nil {
		return nil, false, err
	}
	if count, _ := result.RowsAffected(); count != 1 {
		return nil, false, ErrRevisionConflict
	}
	if seen["labels"] {
		if _, err = tx.ExecContext(ctx, `DELETE FROM dataset_labels WHERE tenant_id=$1 AND project_id=$2 AND dataset_name=$3`, identity.TenantID, identity.ProjectID, name); err != nil {
			return nil, false, err
		}
		for key, value := range next.GetLabels() {
			if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_labels(tenant_id,project_id,dataset_name,label_key,label_value) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, key, value); err != nil {
				return nil, false, err
			}
		}
	}
	if seen["annotations"] {
		if _, err = tx.ExecContext(ctx, `DELETE FROM dataset_annotations WHERE tenant_id=$1 AND project_id=$2 AND dataset_name=$3`, identity.TenantID, identity.ProjectID, name); err != nil {
			return nil, false, err
		}
		for key, value := range next.GetAnnotations() {
			if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_annotations(tenant_id,project_id,dataset_name,annotation_key,annotation_value) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, name, key, value); err != nil {
				return nil, false, err
			}
		}
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, datasetResource(next), at)
	if err != nil {
		return nil, false, err
	}
	event, err := r.Events.Updated(identity, next, paths, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "dataset.update", command.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func cloneMap(values map[string]string) map[string]string {
	result := make(map[string]string, len(values))
	for key, value := range values {
		result[key] = value
	}
	return result
}

func (r SQLRepository) PublishDatasetRelease(ctx context.Context, identity Identity, command *datasetv1.PublishDatasetReleaseCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validateMutation(); err != nil {
		return nil, false, err
	}
	if command == nil || command.GetContext() == nil || !validID(command.GetReleaseId()) || len(command.GetQualificationEvidence()) == 0 {
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
	if err = validateReference(identity, command.GetDataset(), "dataset", "dataset"); err != nil {
		return nil, false, err
	}
	if err = validateArtifact(command.GetManifest(), "dataset manifest"); err != nil {
		return nil, false, err
	}
	if command.GetParentRelease() != nil {
		if err = validateReference(identity, command.GetParentRelease(), "dataset_release", "parent release"); err != nil {
			return nil, false, err
		}
	}
	if command.GetUsePolicy() != nil {
		if err = validateReference(identity, command.GetUsePolicy(), "use_policy", "use policy"); err != nil {
			return nil, false, err
		}
	}
	for _, evidence := range command.GetQualificationEvidence() {
		if err = validateEvidence(evidence, "qualification evidence"); err != nil {
			return nil, false, err
		}
		if subtle.ConstantTimeCompare([]byte(evidence.GetSubjectDigest()), []byte(command.GetManifest().GetDigest())) != 1 {
			return nil, false, fmt.Errorf("%w: qualification evidence does not bind the manifest", ErrInvalidArgument)
		}
	}
	datasetName, err := canonicalDatasetName(identity, command.GetDataset().GetName())
	if err != nil || datasetName != command.GetDataset().GetName() {
		return nil, false, ErrInvalidArgument
	}
	releaseName := datasetName + "/releases/" + command.GetReleaseId()
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "dataset.release.publish", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	row, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, datasetName))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if command.GetDataset().GetResourceVersion() > 0 && command.GetDataset().GetResourceVersion() != row.revision {
		return nil, false, ErrRevisionConflict
	}
	if command.GetDataset().GetEtag() != "" && command.GetDataset().GetEtag() != row.etag {
		return nil, false, ErrRevisionConflict
	}
	if datasetv1.DatasetState(row.state) == datasetv1.DatasetState_DATASET_STATE_DEPRECATED || datasetv1.DatasetState(row.state) == datasetv1.DatasetState_DATASET_STATE_REVOKED {
		return nil, false, ErrInvalidTransition
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, releaseName).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	manifestID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, command.GetManifest())
	if err != nil {
		return nil, false, err
	}
	parentID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetParentRelease())
	if err != nil {
		return nil, false, err
	}
	policyID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, command.GetUsePolicy())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("dsr_")
	if err != nil {
		return nil, false, err
	}
	releaseETag := resourceETag(releaseName, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_releases(tenant_id,project_id,name,uid,dataset_name,release_id,revision,etag,state,manifest_ref_id,parent_release_ref_id,use_policy_ref_id,policy_classification,create_time,publish_time) VALUES($1,$2,$3,$4,$5,$6,1,$7,$8,$9,$10,$11,$12,$13,$13)`, identity.TenantID, identity.ProjectID, releaseName, uid, datasetName, command.GetReleaseId(), releaseETag, int32(datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_PUBLISHED), manifestID, parentID, policyID, command.GetPolicyClassification(), at.UTC()); err != nil {
		return nil, false, err
	}
	for ordinal, evidence := range command.GetQualificationEvidence() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_release_qualification_evidence(tenant_id,project_id,release_name,ordinal,digest,subject_digest,evidence_kind,policy_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, identity.ProjectID, releaseName, ordinal, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest()); err != nil {
			return nil, false, err
		}
	}
	nextRevision := row.revision + 1
	nextETag := resourceETag(datasetName, nextRevision)
	nextState := datasetv1.DatasetState(row.state)
	if nextState == datasetv1.DatasetState_DATASET_STATE_DRAFT {
		nextState = datasetv1.DatasetState_DATASET_STATE_ACTIVE
	}
	result, err := tx.ExecContext(ctx, `UPDATE datasets SET revision=$4,etag=$5,state=$6,update_time=$7,current_release_name=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, datasetName, nextRevision, nextETag, int32(nextState), at.UTC(), releaseName, row.revision, row.etag)
	if err != nil {
		return nil, false, err
	}
	if count, _ := result.RowsAffected(); count != 1 {
		return nil, false, ErrRevisionConflict
	}
	releaseRow, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, releaseName))
	if err != nil {
		return nil, false, err
	}
	release, err := releaseProto(ctx, tx, releaseRow)
	if err != nil {
		return nil, false, err
	}
	datasetRow, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, datasetName))
	if err != nil {
		return nil, false, err
	}
	dataset, err := datasetProto(ctx, tx, datasetRow)
	if err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, releaseResource(release), at)
	if err != nil {
		return nil, false, err
	}
	published, err := r.Events.Published(identity, release, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	changedFields := []string{"current_release_name"}
	if datasetv1.DatasetState(row.state) != nextState {
		changedFields = append(changedFields, "state")
	}
	updated, err := r.Events.Updated(identity, dataset, changedFields, operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, "dataset.release.publish", command.GetContext().GetIdempotencyKey(), digest, operation, []*commonv1.EventEnvelope{published, updated}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) RevokeDatasetRelease(ctx context.Context, identity Identity, command *datasetv1.RevokeDatasetReleaseCommand, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validateMutation(); err != nil {
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
	if err = validateReference(identity, command.GetDatasetRelease(), "dataset_release", "dataset release"); err != nil {
		return nil, false, err
	}
	for _, evidence := range command.GetEvidence() {
		if err = validateEvidence(evidence, "revocation evidence"); err != nil {
			return nil, false, err
		}
	}
	name, err := canonicalReleaseName(identity, command.GetDatasetRelease().GetName())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "dataset.release.revoke", command.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		return replayOperation(ctx, tx, identity, operationID)
	}
	row, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if row.etag != command.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if datasetv1.DatasetReleaseState(row.state) == datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_REVOKED {
		return nil, false, ErrInvalidTransition
	}
	manifest, err := platformdb.LoadArtifactRef(ctx, tx, identity.TenantID, row.manifest)
	if err != nil {
		return nil, false, err
	}
	for _, evidence := range command.GetEvidence() {
		if subtle.ConstantTimeCompare([]byte(evidence.GetSubjectDigest()), []byte(manifest.GetDigest())) != 1 {
			return nil, false, fmt.Errorf("%w: revocation evidence does not bind the manifest", ErrInvalidArgument)
		}
	}
	revision := row.revision + 1
	etag := resourceETag(name, revision)
	result, err := tx.ExecContext(ctx, `UPDATE dataset_releases SET revision=$4,etag=$5,state=$6,revoke_time=$7,revocation_reason=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$9 AND etag=$10`, identity.TenantID, identity.ProjectID, name, revision, etag, int32(datasetv1.DatasetReleaseState_DATASET_RELEASE_STATE_REVOKED), at.UTC(), command.GetReason(), row.revision, row.etag)
	if err != nil {
		return nil, false, err
	}
	if count, _ := result.RowsAffected(); count != 1 {
		return nil, false, ErrRevisionConflict
	}
	for ordinal, evidence := range command.GetEvidence() {
		if _, err = tx.ExecContext(ctx, `INSERT INTO dataset_release_revocation_evidence(tenant_id,project_id,release_name,release_revision,ordinal,digest,subject_digest,evidence_kind,policy_digest,revoked_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, identity.TenantID, identity.ProjectID, name, revision, ordinal, evidence.GetDigest(), evidence.GetSubjectDigest(), evidence.GetEvidenceKind(), evidence.GetPolicyDigest(), at.UTC()); err != nil {
			return nil, false, err
		}
	}
	updatedRow, err := scanRelease(tx.QueryRowContext(ctx, `SELECT `+releaseColumns+` FROM dataset_releases WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, false, err
	}
	release, err := releaseProto(ctx, tx, updatedRow)
	if err != nil {
		return nil, false, err
	}
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, releaseResource(release), at)
	if err != nil {
		return nil, false, err
	}
	events := make([]*commonv1.EventEnvelope, 0, 2)
	revoked, err := r.Events.Revoked(identity, release, command.GetEvidence(), operation, command.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	events = append(events, revoked)
	datasetRow, err := scanDataset(tx.QueryRowContext(ctx, `SELECT `+datasetColumns+` FROM datasets WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, row.datasetName))
	if err != nil {
		return nil, false, err
	}
	if datasetRow.current == name {
		nextRevision := datasetRow.revision + 1
		nextETag := resourceETag(datasetRow.name, nextRevision)
		result, updateErr := tx.ExecContext(ctx, `UPDATE datasets SET revision=$4,etag=$5,update_time=$6,current_release_name='' WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$7 AND etag=$8`, identity.TenantID, identity.ProjectID, datasetRow.name, nextRevision, nextETag, at.UTC(), datasetRow.revision, datasetRow.etag)
		if updateErr != nil {
			return nil, false, updateErr
		}
		if count, _ := result.RowsAffected(); count != 1 {
			return nil, false, ErrRevisionConflict
		}
		datasetRow.revision, datasetRow.etag, datasetRow.current, datasetRow.updated = nextRevision, nextETag, "", sql.NullTime{Time: at.UTC(), Valid: true}
		dataset, mapErr := datasetProto(ctx, tx, datasetRow)
		if mapErr != nil {
			return nil, false, mapErr
		}
		updated, eventErr := r.Events.Updated(identity, dataset, []string{"current_release_name"}, operation, command.GetContext(), at)
		if eventErr != nil {
			return nil, false, eventErr
		}
		events = append(events, updated)
	}
	if err = recordMutation(ctx, tx, identity, "dataset.release.revoke", command.GetContext().GetIdempotencyKey(), digest, operation, events, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}
