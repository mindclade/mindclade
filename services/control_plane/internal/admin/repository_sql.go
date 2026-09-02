package admin

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

const (
	maximumAuditWindow  = 31 * 24 * time.Hour
	auditExportLifetime = 24 * time.Hour
)

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Pagination == nil || r.Events == nil {
		return errors.New("admin SQL repository requires database, pagination codec, and event factory")
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

func checkReceipt(ctx context.Context, tx *sql.Tx, identity Identity, projectID, action, key, digest string) (string, bool, error) {
	lock := fmt.Sprintf("%d:%s:%d:%s:%d:%s:%s:%s", len(identity.TenantID), identity.TenantID, len(projectID), projectID, len(identity.Principal), identity.Principal, action, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lock); err != nil {
		return "", false, err
	}
	var stored, operationID string
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id FROM policy_admin_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, projectID, identity.Principal, action, key).Scan(&stored, &operationID)
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

func insertReceipt(ctx context.Context, tx *sql.Tx, identity Identity, projectID, action, key, digest, operationID string, at time.Time) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO policy_admin_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, identity.TenantID, projectID, identity.Principal, action, key, digest, operationID, at.UTC())
	return err
}

func insertOutbox(ctx context.Context, tx *sql.Tx, event *commonv1.EventEnvelope, at time.Time) error {
	return queue.InsertOutboxMessage(ctx, tx, event, at)
}

func insertAdminAudit(ctx context.Context, tx *sql.Tx, identity Identity, projectID, action string, subject *commonv1.ResourceRef, result adminv1.AuditActionResult, failure, beforeRevision, afterRevision, detailDigest string, command *commonv1.CommandContext, at time.Time) error {
	decision := "allowed"
	if result != adminv1.AuditActionResult_AUDIT_ACTION_RESULT_SUCCEEDED {
		decision = "denied"
	}
	event, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, subject.GetName(), decision, at.UTC(), nil)
	if err != nil {
		return err
	}
	encoded, err := queue.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, event.GetEventId(), identity.TenantID, identity.Principal, action, subject.GetName(), at.UTC(), detailDigest, event.GetEventVersion(), event.GetPayloadDigest(), encoded); err != nil {
		return err
	}
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, subject)
	if err != nil {
		return err
	}
	requestID, traceID := "", ""
	if command != nil {
		requestID, traceID = command.GetRequestId(), command.GetTraceId()
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO administrative_audit_records(tenant_id,event_id,project_id,occurred_at,actor_principal_ref,action,resource_ref_id,before_revision,after_revision,result,failure_class,request_id,trace_id,detail_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, identity.TenantID, event.GetEventId(), projectID, at.UTC(), identity.Principal, action, resourceID, beforeRevision, afterRevision, int32(result), failure, requestID, traceID, detailDigest)
	return err
}

func insertOperation(ctx context.Context, tx *sql.Tx, identity Identity, projectID, digest, kind string, target *commonv1.ResourceRef, state jobv1.OperationState, detail *commonv1.ErrorDetail, at time.Time) (*jobv1.Operation, error) {
	jobID, err := randomID("jobs/")
	if err != nil {
		return nil, err
	}
	operationID, err := randomID("operations/")
	if err != nil {
		return nil, err
	}
	status := map[jobv1.OperationState]string{
		jobv1.OperationState_OPERATION_STATE_PENDING:   "PENDING",
		jobv1.OperationState_OPERATION_STATE_SUCCEEDED: "SUCCEEDED",
		jobv1.OperationState_OPERATION_STATE_FAILED:    "FAILED",
	}[state]
	if status == "" {
		return nil, ErrInvalidArgument
	}
	desired := "ACCEPTED"
	done := false
	switch state {
	case jobv1.OperationState_OPERATION_STATE_SUCCEEDED:
		desired, done = "SUCCEEDED", true
	case jobv1.OperationState_OPERATION_STATE_FAILED:
		desired, done = "FAILED", true
	}
	jobETag, operationETag := resourceETag(jobID, 1), resourceETag(operationID, 1)
	errorID, err := platformdb.StoreErrorDetail(ctx, tx, identity.TenantID, detail)
	if err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,$5,1,'',$6,NULL,NULL,$7,$8,$9,$9)`, jobID, identity.TenantID, operationID, projectID, desired, kind, digest, jobETag, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$2,$3,$7,$8,$9,$10,1,$11,$12,NULL,$13,$14,$15,$15)`, operationID, identity.TenantID, projectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), status, done, operationETag, errorID, digest, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operation_revisions(operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at) VALUES($1,$2,$3,1,$4,true,$5,$6,$2,$3,$7,$8,$9,$10,$11,$12,NULL,$13,$14,$14,$14)`, operationID, identity.TenantID, projectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), status, done, operationETag, errorID, at.UTC()); err != nil {
		return nil, err
	}
	return &jobv1.Operation{OperationId: operationID, TenantId: identity.TenantID, ProjectId: projectID, JobId: jobID, State: state, ResourceVersion: 1, Done: done, Etag: operationETag, Target: clone(target), Error: clone(detail), CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC())}, nil
}

func finishAdminMutation(ctx context.Context, tx *sql.Tx, identity Identity, projectID, action, key, digest string, target *commonv1.ResourceRef, event func(*jobv1.Operation) (*commonv1.EventEnvelope, error), beforeRevision string, command *commonv1.CommandContext, at time.Time) (*jobv1.Operation, error) {
	operation, err := insertOperation(ctx, tx, identity, projectID, digest, "admin.lifecycle", target, jobv1.OperationState_OPERATION_STATE_SUCCEEDED, nil, at)
	if err != nil {
		return nil, err
	}
	envelope, err := event(operation)
	if err != nil {
		return nil, err
	}
	if err = insertAdminAudit(ctx, tx, identity, projectID, action, target, adminv1.AuditActionResult_AUDIT_ACTION_RESULT_SUCCEEDED, "", beforeRevision, strconv.FormatInt(target.GetResourceVersion(), 10), digest, command, at); err != nil {
		return nil, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, err
	}
	if err = insertReceipt(ctx, tx, identity, projectID, action, key, digest, operation.GetOperationId(), at); err != nil {
		return nil, err
	}
	return operation, nil
}

func (r SQLRepository) GetTenant(ctx context.Context, identity Identity, name string) (*adminv1.Tenant, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	canonical, err := tenantName(identity, name)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanTenant(tx.QueryRowContext(ctx, `SELECT `+tenantColumns+` FROM administrative_tenants WHERE tenant_id=$1 AND name=$2`, identity.TenantID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := tenantProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

var tenantMutableFields = map[string]bool{
	"display_name": true, "state": true, "policy_snapshots": true, "default_classification": true,
	"allowed_regions": true, "billing_account": true, "labels": true, "annotations": true,
}

func fieldMask(paths []string, allowed map[string]bool) ([]string, error) {
	if len(paths) == 0 {
		return nil, ErrInvalidArgument
	}
	seen := map[string]bool{}
	result := make([]string, 0, len(paths))
	for _, path := range paths {
		if !allowed[path] || seen[path] {
			return nil, ErrInvalidArgument
		}
		seen[path] = true
		result = append(result, path)
	}
	return result, nil
}

func validTenantTransition(from, to adminv1.TenantState) bool {
	if from == to {
		return true
	}
	switch from {
	case adminv1.TenantState_TENANT_STATE_PROVISIONING:
		return to == adminv1.TenantState_TENANT_STATE_ACTIVE || to == adminv1.TenantState_TENANT_STATE_SUSPENDED || to == adminv1.TenantState_TENANT_STATE_DELETING
	case adminv1.TenantState_TENANT_STATE_ACTIVE:
		return to == adminv1.TenantState_TENANT_STATE_SUSPENDED || to == adminv1.TenantState_TENANT_STATE_DELETING
	case adminv1.TenantState_TENANT_STATE_SUSPENDED:
		return to == adminv1.TenantState_TENANT_STATE_ACTIVE || to == adminv1.TenantState_TENANT_STATE_DELETING
	case adminv1.TenantState_TENANT_STATE_DELETING:
		return to == adminv1.TenantState_TENANT_STATE_DELETED
	default:
		return false
	}
}

func (r SQLRepository) UpdateTenant(ctx context.Context, identity Identity, request *internaladminv1.UpdateTenantRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetTenant() == nil || request.GetUpdateMask() == nil || request.GetEtag() == "" {
		return nil, false, ErrInvalidArgument
	}
	paths, err := fieldMask(request.GetUpdateMask().GetPaths(), tenantMutableFields)
	if err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), "", at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	name, err := tenantName(identity, request.GetTenant().GetName())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, "", "admin.tenant.update", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, "", operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	row, err := scanTenant(tx.QueryRowContext(ctx, `SELECT `+tenantColumns+` FROM administrative_tenants WHERE tenant_id=$1 AND name=$2 FOR UPDATE`, identity.TenantID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetEtag())) != 1 {
		return nil, false, ErrRevisionConflict
	}
	value, err := tenantProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	incoming := request.GetTenant()
	for _, path := range paths {
		switch path {
		case "display_name":
			value.DisplayName = incoming.GetDisplayName()
		case "state":
			if !validTenantTransition(value.GetState(), incoming.GetState()) {
				return nil, false, ErrInvalidTransition
			}
			value.State = incoming.GetState()
		case "policy_snapshots":
			value.PolicySnapshots = cloneSlice(incoming.GetPolicySnapshots())
		case "default_classification":
			value.DefaultClassification = incoming.GetDefaultClassification()
		case "allowed_regions":
			value.AllowedRegions = append([]string(nil), incoming.GetAllowedRegions()...)
		case "billing_account":
			value.BillingAccount = clone(incoming.GetBillingAccount())
		case "labels":
			value.Labels = cloneStringMap(incoming.GetLabels())
		case "annotations":
			value.Annotations = cloneStringMap(incoming.GetAnnotations())
		}
	}
	if value.GetDisplayName() == "" || value.GetState() == adminv1.TenantState_TENANT_STATE_UNSPECIFIED {
		return nil, false, ErrInvalidArgument
	}
	var billingID sql.NullInt64
	if value.GetBillingAccount() != nil {
		if err = validateResource(value.GetBillingAccount(), identity.TenantID); err != nil {
			return nil, false, err
		}
		billingID, err = platformdb.StoreResourceRef(ctx, tx, identity.TenantID, value.GetBillingAccount())
		if err != nil {
			return nil, false, err
		}
	}
	newRevision, newETag := row.revision+1, resourceETag(name, row.revision+1)
	var deleted any
	if value.GetState() == adminv1.TenantState_TENANT_STATE_DELETED {
		deleted = at.UTC()
	}
	if _, err = tx.ExecContext(ctx, `UPDATE administrative_tenants SET revision=$3,etag=$4,display_name=$5,state=$6,default_classification=$7,billing_account_ref_id=$8,update_time=$9,delete_time=$10 WHERE tenant_id=$1 AND name=$2`, identity.TenantID, name, newRevision, newETag, value.GetDisplayName(), int32(value.GetState()), value.GetDefaultClassification(), billingID, at.UTC(), deleted); err != nil {
		return nil, false, err
	}
	value.Revision, value.Etag, value.UpdateTime = newRevision, newETag, timestamppb.New(at.UTC())
	if deleted != nil {
		value.DeleteTime = timestamppb.New(at.UTC())
	}
	if err = replaceTenantChildren(ctx, tx, identity.TenantID, value); err != nil {
		return nil, false, err
	}
	target := tenantResource(identity, value)
	operation, err := finishAdminMutation(ctx, tx, identity, "", "admin.tenant.update", request.GetContext().GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		return r.Events.TenantUpdated(identity, value, paths, operation, request.GetContext(), at)
	}, strconv.FormatInt(row.revision, 10), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func cloneStringMap(value map[string]string) map[string]string {
	result := make(map[string]string, len(value))
	for key, item := range value {
		result[key] = item
	}
	return result
}

func validateProject(value *adminv1.Project, tenantID string) error {
	if value == nil || value.GetDisplayName() == "" || value.GetPurpose() == "" {
		return ErrInvalidArgument
	}
	if value.GetTenant() == nil || value.GetTenant().GetResourceType() != "tenant" || value.GetTenant().GetResourceId() != tenantID || value.GetTenant().GetName() != "tenants/"+tenantID {
		return ErrPermissionDenied
	}
	return validateResource(value.GetTenant(), tenantID)
}

func (r SQLRepository) CreateProject(ctx context.Context, identity Identity, request *internaladminv1.CreateProjectRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetParent() != "tenants/"+identity.TenantID || !validID(request.GetProjectId()) || validateProject(request.GetProject(), identity.TenantID) != nil {
		return nil, false, ErrInvalidArgument
	}
	name, projectID, err := projectName(identity, request.GetProjectId())
	if err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), projectID, at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	input := clone(request.GetProject())
	if input.GetState() != adminv1.ProjectState_PROJECT_STATE_UNSPECIFIED && input.GetState() != adminv1.ProjectState_PROJECT_STATE_PROVISIONING {
		return nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, projectID, "admin.project.create", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, projectID, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	var tenantExists int
	if err = tx.QueryRowContext(ctx, `SELECT 1 FROM administrative_tenants WHERE tenant_id=$1`, identity.TenantID).Scan(&tenantExists); errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	} else if err != nil {
		return nil, false, err
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM administrative_projects WHERE tenant_id=$1 AND project_id=$2`, identity.TenantID, projectID).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	tenantRefID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, input.GetTenant())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("project_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	quotaPresent := input.GetQuota() != nil
	quota := input.GetQuota()
	if quota == nil {
		quota = &adminv1.ProjectQuota{}
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO administrative_projects(tenant_id,project_id,name,uid,revision,etag,tenant_ref_id,display_name,purpose,state,default_classification,quota_present,maximum_concurrent_jobs,maximum_concurrent_accelerator_jobs,maximum_storage_bytes,maximum_monthly_spend_micros,maximum_daily_inference_work_units,create_time,update_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$17)`, identity.TenantID, projectID, name, uid, etag, tenantRefID, input.GetDisplayName(), input.GetPurpose(), int32(adminv1.ProjectState_PROJECT_STATE_PROVISIONING), input.GetDefaultClassification(), quotaPresent, quota.GetMaximumConcurrentJobs(), quota.GetMaximumConcurrentAcceleratorJobs(), strconv.FormatUint(quota.GetMaximumStorageBytes(), 10), strconv.FormatUint(quota.GetMaximumMonthlySpendMicros(), 10), strconv.FormatUint(quota.GetMaximumDailyInferenceWorkUnits(), 10), at.UTC()); err != nil {
		return nil, false, err
	}
	input.Name, input.Uid, input.Revision, input.Etag = name, uid, 1, etag
	input.State, input.CreateTime, input.UpdateTime, input.DeleteTime = adminv1.ProjectState_PROJECT_STATE_PROVISIONING, timestamppb.New(at.UTC()), timestamppb.New(at.UTC()), nil
	if err = replaceProjectChildren(ctx, tx, identity.TenantID, projectID, input); err != nil {
		return nil, false, err
	}
	row, err := scanProject(tx.QueryRowContext(ctx, `SELECT `+projectColumns+` FROM administrative_projects WHERE tenant_id=$1 AND project_id=$2`, identity.TenantID, projectID))
	if err != nil {
		return nil, false, err
	}
	created, err := projectProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	target := projectResource(identity, created)
	operation, err := finishAdminMutation(ctx, tx, identity, projectID, "admin.project.create", request.GetContext().GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		return r.Events.ProjectCreated(identity, created, operation, request.GetContext(), at)
	}, "", request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) GetProject(ctx context.Context, identity Identity, name string) (*adminv1.Project, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	_, projectID, err := projectName(identity, name)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanProject(tx.QueryRowContext(ctx, `SELECT `+projectColumns+` FROM administrative_projects WHERE tenant_id=$1 AND project_id=$2`, identity.TenantID, projectID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := projectProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) ListProjects(ctx context.Context, identity Identity, page ProjectPage) ([]*adminv1.Project, string, time.Time, error) {
	if err := r.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + projectColumns + ` FROM administrative_projects WHERE tenant_id=$1`
	args := []any{identity.TenantID}
	next := 2
	if identity.ProjectID != "" {
		query += fmt.Sprintf(" AND project_id=$%d", next)
		args, next = append(args, identity.ProjectID), next+1
	}
	if page.State != adminv1.ProjectState_PROJECT_STATE_UNSPECIFIED {
		query += fmt.Sprintf(" AND state=$%d", next)
		args, next = append(args, int32(page.State)), next+1
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (create_time,name)<($%d,$%d)", next, next+1)
		args, next = append(args, page.AfterTime.UTC(), page.AfterName), next+2
	}
	query += fmt.Sprintf(" ORDER BY create_time DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []projectRow
	for rows.Next() {
		item, scanErr := scanProject(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", time.Time{}, err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*adminv1.Project, 0, len(stored))
	for _, item := range stored {
		value, mapErr := projectProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(value))
	}
	nextToken := ""
	if hasMore && len(stored) > 0 {
		last := stored[len(stored)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "projects", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterID: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, nextToken, readAt.UTC(), nil
}

var projectMutableFields = map[string]bool{
	"display_name": true, "purpose": true, "state": true, "policy_snapshots": true,
	"default_classification": true, "quota": true, "labels": true, "annotations": true,
}

func validProjectTransition(from, to adminv1.ProjectState) bool {
	if from == to {
		return true
	}
	switch from {
	case adminv1.ProjectState_PROJECT_STATE_PROVISIONING:
		return to == adminv1.ProjectState_PROJECT_STATE_ACTIVE || to == adminv1.ProjectState_PROJECT_STATE_SUSPENDED || to == adminv1.ProjectState_PROJECT_STATE_DELETING
	case adminv1.ProjectState_PROJECT_STATE_ACTIVE:
		return to == adminv1.ProjectState_PROJECT_STATE_SUSPENDED || to == adminv1.ProjectState_PROJECT_STATE_DELETING
	case adminv1.ProjectState_PROJECT_STATE_SUSPENDED:
		return to == adminv1.ProjectState_PROJECT_STATE_ACTIVE || to == adminv1.ProjectState_PROJECT_STATE_DELETING
	case adminv1.ProjectState_PROJECT_STATE_DELETING:
		return to == adminv1.ProjectState_PROJECT_STATE_DELETED
	default:
		return false
	}
}

func (r SQLRepository) UpdateProject(ctx context.Context, identity Identity, request *internaladminv1.UpdateProjectRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetProject() == nil || request.GetUpdateMask() == nil || request.GetEtag() == "" {
		return nil, false, ErrInvalidArgument
	}
	paths, err := fieldMask(request.GetUpdateMask().GetPaths(), projectMutableFields)
	if err != nil {
		return nil, false, err
	}
	name, projectID, err := projectName(identity, request.GetProject().GetName())
	if err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), projectID, at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, projectID, "admin.project.update", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, projectID, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	row, err := scanProject(tx.QueryRowContext(ctx, `SELECT `+projectColumns+` FROM administrative_projects WHERE tenant_id=$1 AND project_id=$2 FOR UPDATE`, identity.TenantID, projectID))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetEtag())) != 1 {
		return nil, false, ErrRevisionConflict
	}
	value, err := projectProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	incoming := request.GetProject()
	for _, path := range paths {
		switch path {
		case "display_name":
			value.DisplayName = incoming.GetDisplayName()
		case "purpose":
			value.Purpose = incoming.GetPurpose()
		case "state":
			if !validProjectTransition(value.GetState(), incoming.GetState()) {
				return nil, false, ErrInvalidTransition
			}
			value.State = incoming.GetState()
		case "policy_snapshots":
			value.PolicySnapshots = cloneSlice(incoming.GetPolicySnapshots())
		case "default_classification":
			value.DefaultClassification = incoming.GetDefaultClassification()
		case "quota":
			value.Quota = clone(incoming.GetQuota())
		case "labels":
			value.Labels = cloneStringMap(incoming.GetLabels())
		case "annotations":
			value.Annotations = cloneStringMap(incoming.GetAnnotations())
		}
	}
	if validateProject(value, identity.TenantID) != nil {
		return nil, false, ErrInvalidArgument
	}
	quotaPresent := value.GetQuota() != nil
	quota := value.GetQuota()
	if quota == nil {
		quota = &adminv1.ProjectQuota{}
	}
	newRevision, newETag := row.revision+1, resourceETag(name, row.revision+1)
	var deleted any
	if value.GetState() == adminv1.ProjectState_PROJECT_STATE_DELETED {
		deleted = at.UTC()
	}
	if _, err = tx.ExecContext(ctx, `UPDATE administrative_projects SET revision=$3,etag=$4,display_name=$5,purpose=$6,state=$7,default_classification=$8,quota_present=$9,maximum_concurrent_jobs=$10,maximum_concurrent_accelerator_jobs=$11,maximum_storage_bytes=$12,maximum_monthly_spend_micros=$13,maximum_daily_inference_work_units=$14,update_time=$15,delete_time=$16 WHERE tenant_id=$1 AND project_id=$2`, identity.TenantID, projectID, newRevision, newETag, value.GetDisplayName(), value.GetPurpose(), int32(value.GetState()), value.GetDefaultClassification(), quotaPresent, quota.GetMaximumConcurrentJobs(), quota.GetMaximumConcurrentAcceleratorJobs(), strconv.FormatUint(quota.GetMaximumStorageBytes(), 10), strconv.FormatUint(quota.GetMaximumMonthlySpendMicros(), 10), strconv.FormatUint(quota.GetMaximumDailyInferenceWorkUnits(), 10), at.UTC(), deleted); err != nil {
		return nil, false, err
	}
	value.Revision, value.Etag, value.UpdateTime = newRevision, newETag, timestamppb.New(at.UTC())
	if deleted != nil {
		value.DeleteTime = timestamppb.New(at.UTC())
	}
	if err = replaceProjectChildren(ctx, tx, identity.TenantID, projectID, value); err != nil {
		return nil, false, err
	}
	target := projectResource(identity, value)
	operation, err := finishAdminMutation(ctx, tx, identity, projectID, "admin.project.update", request.GetContext().GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		return r.Events.ProjectUpdated(identity, value, paths, operation, request.GetContext(), at)
	}, strconv.FormatInt(row.revision, 10), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func auditQueryDigest(query *adminv1.AuditQuery) (string, error) {
	if query == nil {
		return "", ErrInvalidArgument
	}
	copy := clone(query)
	if copy.Page != nil {
		copy.Page.PageToken = ""
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateAuditQuery(identity Identity, query *adminv1.AuditQuery) (string, error) {
	if query == nil || query.GetStartTime() == nil || query.GetEndTime() == nil || query.GetStartTime().CheckValid() != nil || query.GetEndTime().CheckValid() != nil {
		return "", ErrInvalidArgument
	}
	start, end := query.GetStartTime().AsTime(), query.GetEndTime().AsTime()
	if !end.After(start) || end.Sub(start) > maximumAuditWindow {
		return "", ErrInvalidArgument
	}
	tenantParent := "tenants/" + identity.TenantID
	projectID := ""
	if query.GetParent() != tenantParent {
		prefix := tenantParent + "/projects/"
		if !strings.HasPrefix(query.GetParent(), prefix) {
			return "", ErrPermissionDenied
		}
		projectID = strings.TrimPrefix(query.GetParent(), prefix)
		if !validID(projectID) || (identity.ProjectID != "" && identity.ProjectID != projectID) {
			return "", ErrPermissionDenied
		}
	}
	if identity.ProjectID != "" && projectID == "" {
		return "", ErrPermissionDenied
	}
	for _, size := range []int{len(query.GetActorPrincipalRefs()), len(query.GetActions()), len(query.GetResources()), len(query.GetResults()), len(query.GetPolicyReasonCodes())} {
		if size > 100 {
			return "", ErrInvalidArgument
		}
	}
	for _, resource := range query.GetResources() {
		if err := validateResource(resource, identity.TenantID); err != nil {
			return "", err
		}
	}
	return projectID, nil
}

func (r SQLRepository) QueryAuditRecords(ctx context.Context, identity Identity, query *adminv1.AuditQuery, page AuditPage) ([]*adminv1.AuditRecord, string, error) {
	if err := r.validate(); err != nil {
		return nil, "", err
	}
	projectID, err := validateAuditQuery(identity, query)
	if err != nil || projectID != page.ProjectID {
		if err != nil {
			return nil, "", err
		}
		return nil, "", ErrInvalidArgument
	}
	digest, err := auditQueryDigest(query)
	if err != nil || digest != page.QueryDigest {
		return nil, "", ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", err
	}
	defer func() { _ = tx.Rollback() }()
	sqlQuery := `SELECT ` + auditRecordColumns + ` FROM administrative_audit_records WHERE tenant_id=$1 AND occurred_at >= $2 AND occurred_at < $3`
	args := []any{identity.TenantID, query.GetStartTime().AsTime().UTC(), query.GetEndTime().AsTime().UTC()}
	next := 4
	if projectID != "" {
		sqlQuery += fmt.Sprintf(" AND project_id=$%d", next)
		args, next = append(args, projectID), next+1
	}
	if len(query.GetActorPrincipalRefs()) > 0 {
		sqlQuery += fmt.Sprintf(" AND actor_principal_ref = ANY($%d)", next)
		args, next = append(args, query.GetActorPrincipalRefs()), next+1
	}
	if len(query.GetActions()) > 0 {
		sqlQuery += fmt.Sprintf(" AND action = ANY($%d)", next)
		args, next = append(args, query.GetActions()), next+1
	}
	if len(query.GetPolicyReasonCodes()) > 0 {
		sqlQuery += fmt.Sprintf(" AND policy_reason_code = ANY($%d)", next)
		args, next = append(args, query.GetPolicyReasonCodes()), next+1
	}
	if len(query.GetResults()) > 0 {
		results := make([]int32, len(query.GetResults()))
		for index, result := range query.GetResults() {
			if result == adminv1.AuditActionResult_AUDIT_ACTION_RESULT_UNSPECIFIED {
				return nil, "", ErrInvalidArgument
			}
			results[index] = int32(result)
		}
		sqlQuery += fmt.Sprintf(" AND result = ANY($%d)", next)
		args, next = append(args, results), next+1
	}
	if len(query.GetResources()) > 0 {
		names := make([]string, len(query.GetResources()))
		for index, resource := range query.GetResources() {
			names[index] = resource.GetName()
		}
		sqlQuery += fmt.Sprintf(" AND resource_ref_id IN (SELECT id FROM resource_references WHERE tenant_id=$1 AND name = ANY($%d))", next)
		args, next = append(args, names), next+1
	}
	if !page.AfterTime.IsZero() {
		sqlQuery += fmt.Sprintf(" AND (occurred_at,event_id)<($%d,$%d)", next, next+1)
		args, next = append(args, page.AfterTime.UTC(), page.AfterID), next+2
	}
	sqlQuery += fmt.Sprintf(" ORDER BY occurred_at DESC,event_id DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, sqlQuery, args...)
	if err != nil {
		return nil, "", err
	}
	var stored []auditRecordRow
	for rows.Next() {
		item, scanErr := scanAuditRecord(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", scanErr
		}
		stored = append(stored, item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, "", err
	}
	_ = platformdb.CloseRows(rows)
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*adminv1.AuditRecord, 0, len(stored))
	for _, item := range stored {
		value, mapErr := auditRecordProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", mapErr
		}
		values = append(values, clone(value))
	}
	nextToken := ""
	if hasMore && len(stored) > 0 {
		last := stored[len(stored)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "audit-records", Tenant: identity.TenantID, Project: projectID, QueryDigest: digest, AfterTime: last.occurred.UTC().Format(time.RFC3339Nano), AfterID: last.eventID})
		if err != nil {
			return nil, "", err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", err
	}
	return values, nextToken, nil
}

func (r SQLRepository) ExportAuditRecords(ctx context.Context, identity Identity, request *internaladminv1.ExportAuditRecordsRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetQuery() == nil {
		return nil, false, ErrInvalidArgument
	}
	projectID, err := validateAuditQuery(identity, request.GetQuery())
	if err != nil {
		return nil, false, err
	}
	canonical, err := validateContext(identity, request, request.GetContext(), projectID, at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	queryDigest, err := auditQueryDigest(request.GetQuery())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, replay, err := checkReceipt(ctx, tx, identity, projectID, "admin.audit.export", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, projectID, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	uid, err := randomID("export_")
	if err != nil {
		return nil, false, err
	}
	nameIdentity := identity
	nameIdentity.ProjectID = projectID
	name, _, err := exportName(nameIdentity, uid)
	if err != nil {
		return nil, false, err
	}
	state := adminv1.AuditExportState_AUDIT_EXPORT_STATE_REQUESTED
	operationState := jobv1.OperationState_OPERATION_STATE_PENDING
	failure := ""
	var detail *commonv1.ErrorDetail
	if !r.ExporterConfigured {
		state = adminv1.AuditExportState_AUDIT_EXPORT_STATE_FAILED
		operationState = jobv1.OperationState_OPERATION_STATE_FAILED
		failure = "EXPORTER_NOT_CONFIGURED"
		detail = &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_UNAVAILABLE, Message: "audit exporter is not configured", RetryClass: commonv1.RetryClass_RETRY_CLASS_AFTER_RECONCILIATION, ErrorId: uid}
	}
	etag := resourceETag(name, 1)
	export := &adminv1.AuditExport{Name: name, Uid: uid, Revision: 1, Etag: etag, State: state, QueryDigest: queryDigest, FailureCode: failure, CreateTime: timestamppb.New(at.UTC()), UpdateTime: timestamppb.New(at.UTC()), ExpireTime: timestamppb.New(at.Add(auditExportLifetime).UTC())}
	target := exportResource(nameIdentity, export)
	operation, err := insertOperation(ctx, tx, identity, projectID, digest, "admin.audit.export", target, operationState, detail, at)
	if err != nil {
		return nil, false, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_exports(tenant_id,project_id,name,uid,revision,etag,state,query_digest,query_parent,query_start_time,query_end_time,query_request_id,query_trace_id,failure_code,operation_id,create_time,update_time,expire_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$15,$16)`, identity.TenantID, projectID, name, uid, etag, int32(state), queryDigest, request.GetQuery().GetParent(), request.GetQuery().GetStartTime().AsTime().UTC(), request.GetQuery().GetEndTime().AsTime().UTC(), request.GetQuery().GetRequestId(), request.GetQuery().GetTraceId(), failure, operation.GetOperationId(), at.UTC(), at.Add(auditExportLifetime).UTC()); err != nil {
		return nil, false, err
	}
	if err = storeExportFilters(ctx, tx, identity.TenantID, projectID, name, request.GetQuery()); err != nil {
		return nil, false, err
	}
	event, err := r.Events.AuditExportRequested(nameIdentity, export, request.GetQuery(), operation, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	result := adminv1.AuditActionResult_AUDIT_ACTION_RESULT_SUCCEEDED
	if failure != "" {
		result = adminv1.AuditActionResult_AUDIT_ACTION_RESULT_FAILED
	}
	if err = insertAdminAudit(ctx, tx, identity, projectID, "admin.audit.export", target, result, failure, "", "1", digest, request.GetContext(), at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, event, at); err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, projectID, "admin.audit.export", request.GetContext().GetIdempotencyKey(), digest, operation.GetOperationId(), at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func storeExportFilters(ctx context.Context, tx *sql.Tx, tenantID, projectID, name string, query *adminv1.AuditQuery) error {
	for ordinal, value := range query.GetActorPrincipalRefs() {
		if value == "" || len(value) > 512 {
			return ErrInvalidArgument
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO audit_export_actor_filters(tenant_id,project_id,export_name,ordinal,actor_principal_ref) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, name, ordinal, value); err != nil {
			return err
		}
	}
	for ordinal, value := range query.GetActions() {
		if value == "" || len(value) > 256 {
			return ErrInvalidArgument
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO audit_export_action_filters(tenant_id,project_id,export_name,ordinal,action) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, name, ordinal, value); err != nil {
			return err
		}
	}
	for ordinal, value := range query.GetResources() {
		id, err := platformdb.StoreResourceRef(ctx, tx, tenantID, value)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO audit_export_resource_filters(tenant_id,project_id,export_name,ordinal,resource_ref_id) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, name, ordinal, id); err != nil {
			return err
		}
	}
	for ordinal, value := range query.GetResults() {
		if value == adminv1.AuditActionResult_AUDIT_ACTION_RESULT_UNSPECIFIED {
			return ErrInvalidArgument
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO audit_export_result_filters(tenant_id,project_id,export_name,ordinal,result) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, name, ordinal, int32(value)); err != nil {
			return err
		}
	}
	for ordinal, value := range query.GetPolicyReasonCodes() {
		if value == "" || len(value) > 128 {
			return ErrInvalidArgument
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO audit_export_reason_filters(tenant_id,project_id,export_name,ordinal,reason_code) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, name, ordinal, value); err != nil {
			return err
		}
	}
	return nil
}

func (r SQLRepository) GetAuditExport(ctx context.Context, identity Identity, requestedName string) (*adminv1.AuditExport, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	name, projectID, err := exportName(identity, requestedName)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanExport(tx.QueryRowContext(ctx, `SELECT `+exportColumns+` FROM audit_exports WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, projectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := exportProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) CompleteAuditExport(ctx context.Context, identity Identity, requestedName, etag string, artifact *artifactv1.ArtifactRef, at time.Time) (*adminv1.AuditExport, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	if etag == "" || validateArtifact(artifact) != nil {
		return nil, ErrInvalidArgument
	}
	name, projectID, err := exportName(identity, requestedName)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanExport(tx.QueryRowContext(ctx, `SELECT `+exportColumns+` FROM audit_exports WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, projectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(etag)) != 1 {
		return nil, ErrRevisionConflict
	}
	if adminv1.AuditExportState(row.state) != adminv1.AuditExportState_AUDIT_EXPORT_STATE_REQUESTED && adminv1.AuditExportState(row.state) != adminv1.AuditExportState_AUDIT_EXPORT_STATE_RUNNING {
		return nil, ErrInvalidTransition
	}
	artifactID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, artifact)
	if err != nil {
		return nil, err
	}
	newRevision, newETag := row.revision+1, resourceETag(name, row.revision+1)
	if _, err = tx.ExecContext(ctx, `UPDATE audit_exports SET revision=$4,etag=$5,state=$6,artifact_ref_id=$7,failure_code='',update_time=$8 WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, projectID, name, newRevision, newETag, int32(adminv1.AuditExportState_AUDIT_EXPORT_STATE_SUCCEEDED), artifactID, at.UTC()); err != nil {
		return nil, err
	}
	operationRowValue, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, identity.TenantID, projectID, row.operation))
	if err != nil {
		return nil, err
	}
	operationRowValue.status, operationRowValue.done, operationRowValue.version = "SUCCEEDED", true, operationRowValue.version+1
	operationRowValue.etag, operationRowValue.updated = resourceETag(operationRowValue.id, operationRowValue.version), at.UTC()
	operationRowValue.targetVersion, operationRowValue.targetETag = newRevision, newETag
	if _, err = tx.ExecContext(ctx, `UPDATE operations SET status='SUCCEEDED',version=$4,done=true,etag=$5,target_resource_version=$6,target_etag=$7,updated_at=$8 WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, projectID, row.operation, operationRowValue.version, operationRowValue.etag, newRevision, newETag, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE jobs SET desired_state='SUCCEEDED',version=version+1,etag=$5,updated_at=$6 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4`, identity.TenantID, projectID, operationRowValue.job, operationRowValue.version-1, resourceETag(operationRowValue.job, operationRowValue.version), at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operation_revisions(operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at) VALUES($1,$2,$3,$4,$5,true,$6,$7,$8,$9,$10,$11,$12,'SUCCEEDED',true,$13,NULL,NULL,$14,$15,$15)`, operationRowValue.id, identity.TenantID, projectID, operationRowValue.version, operationRowValue.job, operationRowValue.targetType, operationRowValue.targetID, operationRowValue.targetTenant, operationRowValue.targetProject, newRevision, operationRowValue.targetName, newETag, operationRowValue.etag, operationRowValue.created.UTC(), at.UTC()); err != nil {
		return nil, err
	}
	updatedRow, err := scanExport(tx.QueryRowContext(ctx, `SELECT `+exportColumns+` FROM audit_exports WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, projectID, name))
	if err != nil {
		return nil, err
	}
	value, err := exportProto(ctx, tx, updatedRow)
	if err != nil {
		return nil, err
	}
	operation, err := operationProto(ctx, tx, operationRowValue)
	if err != nil {
		return nil, err
	}
	eventIdentity := identity
	eventIdentity.ProjectID = projectID
	event, err := r.Events.AuditExportCompleted(eventIdentity, value, operation, at)
	if err != nil {
		return nil, err
	}
	if err = insertOutbox(ctx, tx, event, at); err != nil {
		return nil, err
	}
	detailHash := sha256.Sum256([]byte(value.GetQueryDigest() + "\x00" + artifact.GetDigest()))
	detailDigest := "sha256:" + hex.EncodeToString(detailHash[:])
	if err = insertAdminAudit(ctx, tx, identity, projectID, "admin.audit.export.complete", exportResource(eventIdentity, value), adminv1.AuditActionResult_AUDIT_ACTION_RESULT_SUCCEEDED, "", strconv.FormatInt(row.revision, 10), strconv.FormatInt(newRevision, 10), detailDigest, nil, at); err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}
