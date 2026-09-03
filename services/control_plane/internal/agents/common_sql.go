package agents

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
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

func (repository SQLRepository) validate() error {
	if repository.DB == nil || repository.Pagination == nil || repository.Events == nil {
		return errors.New("agent SQL repository requires database, pagination codec, and generated event factory")
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

func checkReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string) (string, string, bool, error) {
	lock := fmt.Sprintf("%d:%s:%d:%s:%d:%s:%s:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, len(identity.Principal), identity.Principal, action, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lock); err != nil {
		return "", "", false, err
	}
	var stored, response string
	var operation sql.NullString
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id,response_name FROM workflow_agent_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&stored, &operation, &response)
	if errors.Is(err, sql.ErrNoRows) {
		return "", "", false, nil
	}
	if err != nil {
		return "", "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(digest)) != 1 {
		return "", "", false, ErrIdempotencyConflict
	}
	return operation.String, response, true, nil
}

func recordReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, operationID, responseName string, at time.Time) error {
	var operation any
	if operationID != "" {
		operation = operationID
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO workflow_agent_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,response_name,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, operation, responseName, at.UTC())
	return err
}

type operationRow struct {
	id, tenant, project, job, status, etag                                    string
	version                                                                   int64
	done, targetPresent                                                       bool
	targetType, targetID, targetTenant, targetProject, targetName, targetETag string
	targetVersion                                                             int64
	result, errorDetail                                                       sql.NullInt64
	created, updated                                                          time.Time
}

const operationColumns = `id,tenant_id,project_id,job_id,status,version,done,etag,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,result_ref_id,error_detail_id,created_at,updated_at`

func scanOperation(row scanner) (operationRow, error) {
	var value operationRow
	err := row.Scan(&value.id, &value.tenant, &value.project, &value.job, &value.status, &value.version, &value.done, &value.etag, &value.targetPresent, &value.targetType, &value.targetID, &value.targetTenant, &value.targetProject, &value.targetVersion, &value.targetName, &value.targetETag, &value.result, &value.errorDetail, &value.created, &value.updated)
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

func insertOperationRevision(ctx context.Context, tx *sql.Tx, operation *operationv1.Operation, at time.Time) error {
	target := operation.GetTarget()
	if target == nil {
		return ErrInvalidArgument
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO operation_revisions(operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at) VALUES($1,$2,$3,$4,$5,true,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NULL,NULL,$16,$17,$18)`, operation.GetOperationId(), operation.GetTenantId(), operation.GetProjectId(), operation.GetResourceVersion(), operation.GetJobId(), target.GetResourceType(), target.GetResourceId(), target.GetTenantId(), target.GetProjectId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationStateSQL(operation.GetState()), operation.GetDone(), operation.GetEtag(), operation.GetCreatedAt().AsTime().UTC(), operation.GetUpdatedAt().AsTime().UTC(), at.UTC())
	return err
}

func operationStateSQL(state operationv1.OperationState) string {
	switch state {
	case operationv1.OperationState_OPERATION_STATE_PENDING:
		return "PENDING"
	case operationv1.OperationState_OPERATION_STATE_RUNNING:
		return "RUNNING"
	case operationv1.OperationState_OPERATION_STATE_SUCCEEDED:
		return "SUCCEEDED"
	case operationv1.OperationState_OPERATION_STATE_FAILED:
		return "FAILED"
	case operationv1.OperationState_OPERATION_STATE_CANCELLING:
		return "CANCELLING"
	case operationv1.OperationState_OPERATION_STATE_CANCELLED:
		return "CANCELLED"
	default:
		return ""
	}
}

func insertQueuedWork(ctx context.Context, tx *sql.Tx, identity Identity, target *commonv1.ResourceRef, jobKind, requestDigest, configurationDigest string, inputID sql.NullInt64, at time.Time) (*operationv1.Operation, string, error) {
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, "", err
	}
	operationID, err := randomID("operations/")
	if err != nil {
		return nil, "", err
	}
	runID, err := randomID("runs/")
	if err != nil {
		return nil, "", err
	}
	jobETag, operationETag, runETag := resourceETag(jobID, 1), resourceETag(operationID, 1), resourceETag(runID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'QUEUED',1,'',$5,$6,NULL,$7,$8,$9,$9)`, jobID, identity.TenantID, operationID, identity.ProjectID, jobKind, inputID, configurationDigest, jobETag, at.UTC()); err != nil {
		return nil, "", err
	}
	operation := &operationv1.Operation{OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID, State: operationv1.OperationState_OPERATION_STATE_PENDING, ResourceVersion: 1, Done: false, Etag: operationETag, Target: clone(target), CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC())}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$7,$8,$9,$10,$11,'PENDING',1,false,$12,NULL,NULL,$13,$14,$14)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetTenantId(), target.GetProjectId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, requestDigest, at.UTC()); err != nil {
		return nil, "", err
	}
	if err = insertOperationRevision(ctx, tx, operation, at); err != nil {
		return nil, "", err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO runs(id,tenant_id,project_id,job_id,input_ref_id,configuration_ref_id,plan_ref_id,status,version,lease_epoch,error_detail_id,etag,created_at,started_at,completed_at,updated_at) VALUES($1,$2,$3,$4,$5,NULL,NULL,'READY',1,0,NULL,$6,$7,NULL,NULL,$7)`, runID, identity.TenantID, identity.ProjectID, jobID, inputID, runETag, at.UTC()); err != nil {
		return nil, "", err
	}
	return operation, runID, nil
}

func insertCompletedOperation(ctx context.Context, tx *sql.Tx, identity Identity, target *commonv1.ResourceRef, jobKind, digest string, at time.Time) (*operationv1.Operation, error) {
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, err
	}
	operationID, err := randomID("operations/")
	if err != nil {
		return nil, err
	}
	jobETag, operationETag := resourceETag(jobID, 1), resourceETag(operationID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'SUCCEEDED',1,'',$5,NULL,NULL,$6,$7,$8,$8)`, jobID, identity.TenantID, operationID, identity.ProjectID, jobKind, digest, jobETag, at.UTC()); err != nil {
		return nil, err
	}
	operation := &operationv1.Operation{OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID, State: operationv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 1, Done: true, Etag: operationETag, Target: clone(target), CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC())}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$7,$8,$9,$10,$11,'SUCCEEDED',1,true,$12,NULL,NULL,$13,$14,$14)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetTenantId(), target.GetProjectId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, digest, at.UTC()); err != nil {
		return nil, err
	}
	if err = insertOperationRevision(ctx, tx, operation, at); err != nil {
		return nil, err
	}
	return operation, nil
}

func insertOutbox(ctx context.Context, tx *sql.Tx, event *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := pubsubx.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	kind, id, err := pubsubx.AggregateIdentity(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages(id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, event.GetEventId(), event.GetTenantId(), event.GetEventType(), event.GetEventVersion(), kind, id, event.GetAggregateSequence(), event.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func insertAudit(ctx context.Context, tx *sql.Tx, identity Identity, action, subject, digest string, at time.Time) error {
	event, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, subject, "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	encoded, err := pubsubx.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, event.GetEventId(), identity.TenantID, identity.Principal, action, subject, at.UTC(), digest, event.GetEventVersion(), event.GetPayloadDigest(), encoded)
	return err
}

func recordMutation(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, operationID, responseName string, events []*commonv1.EventEnvelope, at time.Time) error {
	if responseName == "" || len(events) == 0 {
		return ErrInvalidArgument
	}
	if err := insertAudit(ctx, tx, identity, action, responseName, digest, at); err != nil {
		return err
	}
	for _, event := range events {
		if err := insertOutbox(ctx, tx, event, at); err != nil {
			return err
		}
	}
	return recordReceipt(ctx, tx, identity, action, key, digest, operationID, responseName, at)
}

func requireOne(result sql.Result) error {
	changed, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if changed != 1 {
		return ErrRevisionConflict
	}
	return nil
}

func getRunTx(ctx context.Context, tx *sql.Tx, identity Identity, name string, lock bool) (*agentv1.AgentRun, runRow, error) {
	canonical, err := canonicalScopedName(identity, name, "agentRuns")
	if err != nil {
		return nil, runRow{}, err
	}
	query := `SELECT ` + runColumns + ` FROM agent_runs WHERE tenant_id=$1 AND project_id=$2 AND name=$3`
	if lock {
		query += " FOR UPDATE"
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

func updateOperationTarget(ctx context.Context, tx *sql.Tx, identity Identity, operationID string, run *agentv1.AgentRun, status string, done bool, at time.Time) error {
	var currentVersion int64
	if err := tx.QueryRowContext(ctx, `SELECT version FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, operationID).Scan(&currentVersion); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE operations SET status=$4,version=version+1,done=$5,etag=$6,target_resource_version=$7,target_etag=$8,updated_at=$9 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$10`, identity.TenantID, identity.ProjectID, operationID, status, done, resourceETag(operationID, currentVersion+1), run.GetRevision(), run.GetEtag(), at.UTC(), currentVersion)
	if err != nil {
		return err
	}
	if err = requireOne(result); err != nil {
		return err
	}
	operation, err := loadOperationTx(ctx, tx, identity, operationID)
	if err != nil {
		return err
	}
	return insertOperationRevision(ctx, tx, operation, at)
}

func advanceSchedulerCancellation(ctx context.Context, tx *sql.Tx, identity Identity, jobID, runID string, at time.Time) error {
	var jobVersion, runVersion int64
	if err := tx.QueryRowContext(ctx, `SELECT version FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, jobID).Scan(&jobVersion); err != nil {
		return err
	}
	if err := tx.QueryRowContext(ctx, `SELECT version FROM runs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, runID).Scan(&runVersion); err != nil {
		return err
	}
	jobResult, err := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='CANCELLING',version=version+1,etag=$4,updated_at=$5 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$6 AND desired_state NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, identity.TenantID, identity.ProjectID, jobID, resourceETag(jobID, jobVersion+1), at.UTC(), jobVersion)
	if err != nil {
		return err
	}
	if err = requireOne(jobResult); err != nil {
		return err
	}
	runResult, err := tx.ExecContext(ctx, `UPDATE runs SET status='CANCELLING',version=version+1,etag=$4,updated_at=$5 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$6 AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED')`, identity.TenantID, identity.ProjectID, runID, resourceETag(runID, runVersion+1), at.UTC(), runVersion)
	if err != nil {
		return err
	}
	return requireOne(runResult)
}
