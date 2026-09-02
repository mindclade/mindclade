package admin

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strconv"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

type scanner interface{ Scan(...any) error }

func loadPolicyReference(ctx context.Context, tx *sql.Tx, tenantID string, id sql.NullInt64) (*policyv1.PolicyReference, error) {
	if !id.Valid {
		return nil, nil
	}
	var (
		value      policyv1.PolicyReference
		documentID sql.NullInt64
		effective  time.Time
		expires    sql.NullTime
	)
	err := tx.QueryRowContext(ctx, `SELECT name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification FROM policy_snapshot_references WHERE tenant_id=$1 AND id=$2`, tenantID, id.Int64).Scan(
		&value.Name, &value.Uid, &value.PolicyType, &value.Version, &value.Digest, &documentID,
		&value.ResourceRevision, &effective, &expires, &value.Classification,
	)
	if err != nil {
		return nil, err
	}
	value.Document, err = platformdb.LoadArtifactRef(ctx, tx, tenantID, documentID)
	if err != nil {
		return nil, err
	}
	value.EffectiveTime = timestamppb.New(effective.UTC())
	if expires.Valid {
		value.ExpireTime = timestamppb.New(expires.Time.UTC())
	}
	return &value, nil
}

func resolvePolicyReference(ctx context.Context, tx *sql.Tx, tenantID string, requested *policyv1.PolicyReference) (int64, error) {
	if err := validatePolicyReference(requested); err != nil {
		return 0, err
	}
	var id int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, tenantID, requested.GetName(), requested.GetResourceRevision(), requested.GetDigest()).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, ErrNotFound
	}
	if err != nil {
		return 0, err
	}
	stored, err := loadPolicyReference(ctx, tx, tenantID, sql.NullInt64{Int64: id, Valid: true})
	if err != nil {
		return 0, err
	}
	if !proto.Equal(stored, requested) {
		return 0, ErrRevisionConflict
	}
	return id, nil
}

type tenantRow struct {
	tenant, name, uid, etag, display, classification string
	revision                                         int64
	state                                            int32
	billing                                          sql.NullInt64
	created, updated                                 time.Time
	deleted                                          sql.NullTime
}

const tenantColumns = `tenant_id,name,uid,revision,etag,display_name,state,default_classification,billing_account_ref_id,create_time,update_time,delete_time`

func scanTenant(row scanner) (tenantRow, error) {
	var value tenantRow
	err := row.Scan(&value.tenant, &value.name, &value.uid, &value.revision, &value.etag, &value.display, &value.state, &value.classification, &value.billing, &value.created, &value.updated, &value.deleted)
	return value, err
}

func tenantProto(ctx context.Context, tx *sql.Tx, row tenantRow) (*adminv1.Tenant, error) {
	billing, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.billing)
	if err != nil {
		return nil, err
	}
	value := &adminv1.Tenant{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		DisplayName: row.display, State: adminv1.TenantState(row.state), DefaultClassification: row.classification,
		BillingAccount: billing, Labels: map[string]string{}, Annotations: map[string]string{},
		CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()),
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM administrative_tenant_policy_snapshots WHERE tenant_id=$1 ORDER BY ordinal`, row.tenant)
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
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	for _, id := range policyIDs {
		item, loadErr := loadPolicyReference(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, item)
	}
	rows, err = tx.QueryContext(ctx, `SELECT region FROM administrative_tenant_allowed_regions WHERE tenant_id=$1 ORDER BY ordinal`, row.tenant)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var region string
		if err = rows.Scan(&region); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		value.AllowedRegions = append(value.AllowedRegions, region)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	if err = loadMap(ctx, tx, `SELECT label_key,label_value FROM administrative_tenant_labels WHERE tenant_id=$1 ORDER BY label_key`, []any{row.tenant}, value.Labels); err != nil {
		return nil, err
	}
	if err = loadMap(ctx, tx, `SELECT annotation_key,annotation_value FROM administrative_tenant_annotations WHERE tenant_id=$1 ORDER BY annotation_key`, []any{row.tenant}, value.Annotations); err != nil {
		return nil, err
	}
	return value, nil
}

func loadMap(ctx context.Context, tx *sql.Tx, query string, args []any, target map[string]string) error {
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return err
	}
	for rows.Next() {
		var key, value string
		if err = rows.Scan(&key, &value); err != nil {
			_ = platformdb.CloseRows(rows)
			return err
		}
		target[key] = value
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return err
	}
	return platformdb.CloseRows(rows)
}

func replaceTenantChildren(ctx context.Context, tx *sql.Tx, tenantID string, value *adminv1.Tenant) error {
	for _, table := range []string{"administrative_tenant_policy_snapshots", "administrative_tenant_allowed_regions", "administrative_tenant_labels", "administrative_tenant_annotations"} {
		if _, err := tx.ExecContext(ctx, `DELETE FROM `+table+` WHERE tenant_id=$1`, tenantID); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
			return err
		}
	}
	for ordinal, snapshot := range value.GetPolicySnapshots() {
		id, err := resolvePolicyReference(ctx, tx, tenantID, snapshot)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO administrative_tenant_policy_snapshots(tenant_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3)`, tenantID, ordinal, id); err != nil {
			return err
		}
	}
	seen := map[string]bool{}
	for ordinal, region := range value.GetAllowedRegions() {
		if region == "" || len(region) > 128 || seen[region] {
			return ErrInvalidArgument
		}
		seen[region] = true
		if _, err := tx.ExecContext(ctx, `INSERT INTO administrative_tenant_allowed_regions(tenant_id,ordinal,region) VALUES($1,$2,$3)`, tenantID, ordinal, region); err != nil {
			return err
		}
	}
	if err := replaceMap(ctx, tx, "administrative_tenant_labels", "label", tenantID, "", value.GetLabels(), 256); err != nil {
		return err
	}
	return replaceMap(ctx, tx, "administrative_tenant_annotations", "annotation", tenantID, "", value.GetAnnotations(), 4096)
}

func replaceMap(ctx context.Context, tx *sql.Tx, table, prefix, tenantID, projectID string, values map[string]string, maxValue int) error {
	for key, value := range values {
		if key == "" || len(key) > 128 || len(value) > maxValue {
			return ErrInvalidArgument
		}
		if projectID == "" {
			if _, err := tx.ExecContext(ctx, `INSERT INTO `+table+`(tenant_id,`+prefix+`_key,`+prefix+`_value) VALUES($1,$2,$3)`, tenantID, key, value); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				return err
			}
		} else if _, err := tx.ExecContext(ctx, `INSERT INTO `+table+`(tenant_id,project_id,`+prefix+`_key,`+prefix+`_value) VALUES($1,$2,$3,$4)`, tenantID, projectID, key, value); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
			return err
		}
	}
	return nil
}

type projectRow struct {
	tenant, project, name, uid, etag, display, purpose, classification string
	revision                                                           int64
	state                                                              int32
	tenantRef                                                          sql.NullInt64
	quotaPresent                                                       bool
	maxJobs, maxAcceleratorJobs                                        int64
	maxStorage, maxSpend, maxWork                                      string
	created, updated                                                   time.Time
	deleted                                                            sql.NullTime
}

const projectColumns = `tenant_id,project_id,name,uid,revision,etag,tenant_ref_id,display_name,purpose,state,default_classification,quota_present,maximum_concurrent_jobs,maximum_concurrent_accelerator_jobs,maximum_storage_bytes::text,maximum_monthly_spend_micros::text,maximum_daily_inference_work_units::text,create_time,update_time,delete_time`

func scanProject(row scanner) (projectRow, error) {
	var value projectRow
	err := row.Scan(
		&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.tenantRef,
		&value.display, &value.purpose, &value.state, &value.classification, &value.quotaPresent,
		&value.maxJobs, &value.maxAcceleratorJobs, &value.maxStorage, &value.maxSpend, &value.maxWork,
		&value.created, &value.updated, &value.deleted,
	)
	return value, err
}

func parseUint(value string) (uint64, error) {
	result, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid persisted uint64 %q: %w", value, err)
	}
	return result, nil
}

func projectProto(ctx context.Context, tx *sql.Tx, row projectRow) (*adminv1.Project, error) {
	tenant, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.tenantRef)
	if err != nil {
		return nil, err
	}
	value := &adminv1.Project{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag, Tenant: tenant,
		DisplayName: row.display, Purpose: row.purpose, State: adminv1.ProjectState(row.state),
		DefaultClassification: row.classification, Labels: map[string]string{}, Annotations: map[string]string{},
		CreateTime: timestamppb.New(row.created.UTC()), UpdateTime: timestamppb.New(row.updated.UTC()),
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	if row.quotaPresent {
		storage, parseErr := parseUint(row.maxStorage)
		if parseErr != nil {
			return nil, parseErr
		}
		spend, parseErr := parseUint(row.maxSpend)
		if parseErr != nil {
			return nil, parseErr
		}
		work, parseErr := parseUint(row.maxWork)
		if parseErr != nil {
			return nil, parseErr
		}
		value.Quota = &adminv1.ProjectQuota{
			MaximumConcurrentJobs: uint32(row.maxJobs), MaximumConcurrentAcceleratorJobs: uint32(row.maxAcceleratorJobs), //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
			MaximumStorageBytes: storage, MaximumMonthlySpendMicros: spend, MaximumDailyInferenceWorkUnits: work,
		}
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM administrative_project_policy_snapshots WHERE tenant_id=$1 AND project_id=$2 ORDER BY ordinal`, row.tenant, row.project)
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
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	for _, id := range policyIDs {
		item, loadErr := loadPolicyReference(ctx, tx, row.tenant, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.PolicySnapshots = append(value.PolicySnapshots, item)
	}
	if err = loadMap(ctx, tx, `SELECT label_key,label_value FROM administrative_project_labels WHERE tenant_id=$1 AND project_id=$2 ORDER BY label_key`, []any{row.tenant, row.project}, value.Labels); err != nil {
		return nil, err
	}
	if err = loadMap(ctx, tx, `SELECT annotation_key,annotation_value FROM administrative_project_annotations WHERE tenant_id=$1 AND project_id=$2 ORDER BY annotation_key`, []any{row.tenant, row.project}, value.Annotations); err != nil {
		return nil, err
	}
	return value, nil
}

func replaceProjectChildren(ctx context.Context, tx *sql.Tx, tenantID, projectID string, value *adminv1.Project) error {
	for _, table := range []string{"administrative_project_policy_snapshots", "administrative_project_labels", "administrative_project_annotations"} {
		if _, err := tx.ExecContext(ctx, `DELETE FROM `+table+` WHERE tenant_id=$1 AND project_id=$2`, tenantID, projectID); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
			return err
		}
	}
	for ordinal, snapshot := range value.GetPolicySnapshots() {
		id, err := resolvePolicyReference(ctx, tx, tenantID, snapshot)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO administrative_project_policy_snapshots(tenant_id,project_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4)`, tenantID, projectID, ordinal, id); err != nil {
			return err
		}
	}
	if err := replaceMap(ctx, tx, "administrative_project_labels", "label", tenantID, projectID, value.GetLabels(), 256); err != nil {
		return err
	}
	return replaceMap(ctx, tx, "administrative_project_annotations", "annotation", tenantID, projectID, value.GetAnnotations(), 4096)
}

type auditRecordRow struct {
	tenant, eventID, project, actor, delegated, authContext, origin, action string
	authDecision, beforeRevision, afterRevision, reason, failure            string
	requestID, traceID, detail                                              string
	resource                                                                sql.NullInt64
	result                                                                  int32
	occurred                                                                time.Time
}

const auditRecordColumns = `tenant_id,event_id,project_id,occurred_at,actor_principal_ref,delegated_principal_ref,authentication_context_digest,request_origin_class,action,resource_ref_id,authorization_decision_digest,before_revision,after_revision,policy_reason_code,result,failure_class,request_id,trace_id,detail_digest`

func scanAuditRecord(row scanner) (auditRecordRow, error) {
	var value auditRecordRow
	err := row.Scan(
		&value.tenant, &value.eventID, &value.project, &value.occurred, &value.actor, &value.delegated,
		&value.authContext, &value.origin, &value.action, &value.resource, &value.authDecision,
		&value.beforeRevision, &value.afterRevision, &value.reason, &value.result, &value.failure,
		&value.requestID, &value.traceID, &value.detail,
	)
	return value, err
}

func auditRecordProto(ctx context.Context, tx *sql.Tx, row auditRecordRow) (*adminv1.AuditRecord, error) {
	resource, err := platformdb.LoadResourceRef(ctx, tx, row.tenant, row.resource)
	if err != nil {
		return nil, err
	}
	return &adminv1.AuditRecord{
		EventId: row.eventID, OccurredAt: timestamppb.New(row.occurred.UTC()), ActorPrincipalRef: row.actor,
		DelegatedPrincipalRef: row.delegated, AuthenticationContextDigest: row.authContext,
		RequestOriginClass: row.origin, TenantId: row.tenant, ProjectId: row.project, Action: row.action,
		Resource: resource, AuthorizationDecisionDigest: row.authDecision, BeforeRevision: row.beforeRevision,
		AfterRevision: row.afterRevision, PolicyReasonCode: row.reason, Result: adminv1.AuditActionResult(row.result),
		FailureClass: row.failure, RequestId: row.requestID, TraceId: row.traceID, DetailDigest: row.detail,
	}, nil
}

type exportRow struct {
	tenant, project, name, uid, etag, queryDigest, parent, requestID, traceID, failure, operation string
	revision                                                                                      int64
	state                                                                                         int32
	artifact                                                                                      sql.NullInt64
	start, end, created, updated, expires                                                         time.Time
}

const exportColumns = `tenant_id,project_id,name,uid,revision,etag,state,query_digest,query_parent,query_start_time,query_end_time,query_request_id,query_trace_id,artifact_ref_id,failure_code,operation_id,create_time,update_time,expire_time`

func scanExport(row scanner) (exportRow, error) {
	var value exportRow
	err := row.Scan(
		&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag, &value.state,
		&value.queryDigest, &value.parent, &value.start, &value.end, &value.requestID, &value.traceID,
		&value.artifact, &value.failure, &value.operation, &value.created, &value.updated, &value.expires,
	)
	return value, err
}

func exportProto(ctx context.Context, tx *sql.Tx, row exportRow) (*adminv1.AuditExport, error) {
	artifact, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.artifact)
	if err != nil {
		return nil, err
	}
	return &adminv1.AuditExport{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		State: adminv1.AuditExportState(row.state), Artifact: artifact, QueryDigest: row.queryDigest,
		FailureCode: row.failure, CreateTime: timestamppb.New(row.created.UTC()),
		UpdateTime: timestamppb.New(row.updated.UTC()), ExpireTime: timestamppb.New(row.expires.UTC()),
	}, nil
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
	states := map[string]jobv1.OperationState{
		"PENDING": jobv1.OperationState_OPERATION_STATE_PENDING, "RUNNING": jobv1.OperationState_OPERATION_STATE_RUNNING,
		"SUCCEEDED": jobv1.OperationState_OPERATION_STATE_SUCCEEDED, "FAILED": jobv1.OperationState_OPERATION_STATE_FAILED,
		"CANCELLING": jobv1.OperationState_OPERATION_STATE_CANCELLING, "CANCELLED": jobv1.OperationState_OPERATION_STATE_CANCELLED,
	}
	state, ok := states[row.status]
	if !ok {
		return nil, ErrInvalidArgument
	}
	value := &jobv1.Operation{OperationId: row.id, TenantId: row.tenant, ProjectId: row.project, JobId: row.job, State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag, Result: result, Error: detail, CreatedAt: timestamppb.New(row.created.UTC()), UpdatedAt: timestamppb.New(row.updated.UTC())}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant, ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag}
	}
	return value, nil
}

func getOperationTx(ctx context.Context, tx *sql.Tx, identity Identity, projectID, id string) (*jobv1.Operation, error) {
	row, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, projectID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return operationProto(ctx, tx, row)
}
