package policies

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
)

type scanner interface{ Scan(...any) error }

type usePolicyRow struct {
	tenant, project, name, uid, etag, display, revocationReason string
	revision                                                    int64
	state                                                       int32
	documentID, snapshotID                                      sql.NullInt64
	created, updated                                            time.Time
	deleted                                                     sql.NullTime
}

const usePolicyColumns = `tenant_id,project_id,name,uid,revision,etag,display_name,state,policy_document_ref_id,active_snapshot_id,create_time,update_time,delete_time,revocation_reason_code`

func scanUsePolicy(row scanner) (usePolicyRow, error) {
	var value usePolicyRow
	err := row.Scan(
		&value.tenant, &value.project, &value.name, &value.uid, &value.revision, &value.etag,
		&value.display, &value.state, &value.documentID, &value.snapshotID, &value.created,
		&value.updated, &value.deleted, &value.revocationReason,
	)
	return value, err
}

func storePolicyReference(ctx context.Context, tx *sql.Tx, tenantID string, value *policyv1.PolicyReference) (sql.NullInt64, error) {
	if value == nil {
		return sql.NullInt64{}, nil
	}
	if err := validatePolicyReference(value, value.GetEffectiveTime().AsTime()); err != nil {
		return sql.NullInt64{}, err
	}
	lockKey := fmt.Sprintf("%d:%s:%d:%s:%d:%d:%s", len(tenantID), tenantID, len(value.GetName()), value.GetName(), value.GetResourceRevision(), len(value.GetDigest()), value.GetDigest())
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lockKey); err != nil {
		return sql.NullInt64{}, err
	}
	var existingID int64
	err := tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, tenantID, value.GetName(), value.GetResourceRevision(), value.GetDigest()).Scan(&existingID)
	if err == nil {
		stored, loadErr := loadPolicyReference(ctx, tx, tenantID, sql.NullInt64{Int64: existingID, Valid: true})
		if loadErr != nil {
			return sql.NullInt64{}, loadErr
		}
		if !proto.Equal(stored, value) {
			return sql.NullInt64{}, ErrRevisionConflict
		}
		return sql.NullInt64{Int64: existingID, Valid: true}, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return sql.NullInt64{}, err
	}
	documentID, err := platformdb.StoreArtifactRef(ctx, tx, tenantID, value.GetDocument())
	if err != nil {
		return sql.NullInt64{}, err
	}
	var expires any
	if value.GetExpireTime() != nil {
		expires = value.GetExpireTime().AsTime().UTC()
	}
	err = tx.QueryRowContext(ctx, `INSERT INTO policy_snapshot_references(tenant_id,name,uid,policy_type,semantic_version,digest,document_ref_id,resource_revision,effective_time,expire_time,classification) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`,
		tenantID, value.GetName(), value.GetUid(), value.GetPolicyType(), value.GetVersion(), value.GetDigest(), documentID, value.GetResourceRevision(), value.GetEffectiveTime().AsTime().UTC(), expires, value.GetClassification(),
	).Scan(&existingID)
	if err != nil {
		return sql.NullInt64{}, err
	}
	return sql.NullInt64{Int64: existingID, Valid: true}, nil
}

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

func usePolicyProto(ctx context.Context, tx *sql.Tx, row usePolicyRow) (*policyv1.UsePolicy, error) {
	document, err := platformdb.LoadArtifactRef(ctx, tx, row.tenant, row.documentID)
	if err != nil {
		return nil, err
	}
	snapshot, err := loadPolicyReference(ctx, tx, row.tenant, row.snapshotID)
	if err != nil {
		return nil, err
	}
	value := &policyv1.UsePolicy{
		Name: row.name, Uid: row.uid, Revision: row.revision, Etag: row.etag,
		TenantId: row.tenant, ProjectId: row.project, DisplayName: row.display,
		State: policyv1.UsePolicyState(row.state), PolicyDocument: document,
		ActiveSnapshot: snapshot, CreateTime: timestamppb.New(row.created.UTC()),
		UpdateTime: timestamppb.New(row.updated.UTC()),
	}
	if row.deleted.Valid {
		value.DeleteTime = timestamppb.New(row.deleted.Time.UTC())
	}
	for _, tableAndTarget := range []struct {
		table  string
		target *[]string
	}{
		{"use_policy_permitted_purposes", &value.PermittedPurposes},
		{"use_policy_permitted_capabilities", &value.PermittedCapabilities},
		{"use_policy_prohibited_capabilities", &value.ProhibitedCapabilities},
		{"use_policy_accepted_classifications", &value.AcceptedClassifications},
	} {
		rows, queryErr := tx.QueryContext(ctx, `SELECT value FROM `+tableAndTarget.table+` WHERE tenant_id=$1 AND project_id=$2 AND policy_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
		if queryErr != nil {
			return nil, queryErr
		}
		for rows.Next() {
			var item string
			if queryErr = rows.Scan(&item); queryErr != nil {
				_ = platformdb.CloseRows(rows)
				return nil, queryErr
			}
			*tableAndTarget.target = append(*tableAndTarget.target, item)
		}
		if queryErr = rows.Err(); queryErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, queryErr
		}
		_ = platformdb.CloseRows(rows)
	}
	rows, err := tx.QueryContext(ctx, `SELECT action,risk_class,minimum_independent_approvers,step_up_authentication_required,maximum_receipt_age_seconds,maximum_receipt_age_nanos,single_use FROM use_policy_approval_requirements WHERE tenant_id=$1 AND project_id=$2 AND policy_name=$3 ORDER BY ordinal`, row.tenant, row.project, row.name)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var (
			requirement        policyv1.ApprovalRequirement
			risk               int32
			approvers          int64
			durationSeconds    sql.NullInt64
			durationNanosecond sql.NullInt32
		)
		if err = rows.Scan(&requirement.Action, &risk, &approvers, &requirement.StepUpAuthenticationRequired, &durationSeconds, &durationNanosecond, &requirement.SingleUse); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		requirement.RiskClass = policyv1.UseRiskClass(risk)
		requirement.MinimumIndependentApprovers = uint32(approvers) //nolint:gosec // Conversion is bounded by validated protocol invariants or PostgreSQL CHECK constraints.
		if durationSeconds.Valid != durationNanosecond.Valid {
			_ = platformdb.CloseRows(rows)
			return nil, errors.New("persisted policy receipt duration presence is inconsistent")
		}
		if durationSeconds.Valid {
			requirement.MaximumReceiptAge = &durationpb.Duration{Seconds: durationSeconds.Int64, Nanos: durationNanosecond.Int32}
			if err = requirement.MaximumReceiptAge.CheckValid(); err != nil {
				_ = platformdb.CloseRows(rows)
				return nil, err
			}
		}
		value.ApprovalRequirements = append(value.ApprovalRequirements, &requirement)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	return value, nil
}

func replaceStringList(ctx context.Context, tx *sql.Tx, table, tenantID, projectID, policyName string, values []string) error {
	if _, err := tx.ExecContext(ctx, `DELETE FROM `+table+` WHERE tenant_id=$1 AND project_id=$2 AND policy_name=$3`, tenantID, projectID, policyName); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
		return err
	}
	seen := make(map[string]struct{}, len(values))
	for ordinal, value := range values {
		if value == "" || len(value) > 256 {
			return ErrInvalidArgument
		}
		if _, exists := seen[value]; exists {
			return ErrInvalidArgument
		}
		seen[value] = struct{}{}
		if _, err := tx.ExecContext(ctx, `INSERT INTO `+table+`(tenant_id,project_id,policy_name,ordinal,value) VALUES($1,$2,$3,$4,$5)`, tenantID, projectID, policyName, ordinal, value); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
			return err
		}
	}
	return nil
}

func replaceApprovalRequirements(ctx context.Context, tx *sql.Tx, tenantID, projectID, policyName string, values []*policyv1.ApprovalRequirement) error {
	if _, err := tx.ExecContext(ctx, `DELETE FROM use_policy_approval_requirements WHERE tenant_id=$1 AND project_id=$2 AND policy_name=$3`, tenantID, projectID, policyName); err != nil {
		return err
	}
	seen := make(map[string]struct{}, len(values))
	for ordinal, value := range values {
		if value == nil || value.GetAction() == "" || value.GetRiskClass() == policyv1.UseRiskClass_USE_RISK_CLASS_UNSPECIFIED || value.GetMinimumIndependentApprovers() == 0 {
			return ErrInvalidArgument
		}
		if _, exists := seen[value.GetAction()]; exists {
			return ErrInvalidArgument
		}
		seen[value.GetAction()] = struct{}{}
		var seconds any
		var nanos any
		if duration := value.GetMaximumReceiptAge(); duration != nil {
			if err := duration.CheckValid(); err != nil || duration.AsDuration() < 0 {
				return ErrInvalidArgument
			}
			seconds, nanos = duration.GetSeconds(), duration.GetNanos()
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO use_policy_approval_requirements(tenant_id,project_id,policy_name,ordinal,action,risk_class,minimum_independent_approvers,step_up_authentication_required,maximum_receipt_age_seconds,maximum_receipt_age_nanos,single_use) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
			tenantID, projectID, policyName, ordinal, value.GetAction(), int32(value.GetRiskClass()), value.GetMinimumIndependentApprovers(), value.GetStepUpAuthenticationRequired(), seconds, nanos, value.GetSingleUse(),
		); err != nil {
			return err
		}
	}
	return nil
}

func replaceUsePolicyChildren(ctx context.Context, tx *sql.Tx, identity Identity, value *policyv1.UsePolicy) error {
	for _, item := range []struct {
		table  string
		values []string
	}{
		{"use_policy_permitted_purposes", value.GetPermittedPurposes()},
		{"use_policy_permitted_capabilities", value.GetPermittedCapabilities()},
		{"use_policy_prohibited_capabilities", value.GetProhibitedCapabilities()},
		{"use_policy_accepted_classifications", value.GetAcceptedClassifications()},
	} {
		if err := replaceStringList(ctx, tx, item.table, identity.TenantID, identity.ProjectID, value.GetName(), item.values); err != nil {
			return err
		}
	}
	return replaceApprovalRequirements(ctx, tx, identity.TenantID, identity.ProjectID, value.GetName(), value.GetApprovalRequirements())
}

func storeAuthorizationDecision(ctx context.Context, tx *sql.Tx, value *policyv1.AuthorizationDecision) error {
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, value.GetTenantId(), value.GetResource())
	if err != nil {
		return err
	}
	var expires any
	if value.GetExpireTime() != nil {
		expires = value.GetExpireTime().AsTime().UTC()
	}
	var decisionID int64
	err = tx.QueryRowContext(ctx, `INSERT INTO authorization_decisions(tenant_id,name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) RETURNING id`,
		value.GetTenantId(), value.GetName(), value.GetUid(), value.GetProjectId(), value.GetPrincipalRef(), value.GetAction(), resourceID,
		value.GetIntentDigest(), int32(value.GetOutcome()), value.GetReasonCode(), value.GetSafeReason(), value.GetEvaluatedAt().AsTime().UTC(),
		expires, value.GetContextDigest(), value.GetDecisionDigest(),
	).Scan(&decisionID)
	if err != nil {
		return err
	}
	for ordinal, policy := range value.GetPolicies() {
		policyID, storeErr := storePolicyReference(ctx, tx, value.GetTenantId(), policy)
		if storeErr != nil {
			return storeErr
		}
		if _, storeErr = tx.ExecContext(ctx, `INSERT INTO authorization_decision_policies(tenant_id,decision_id,ordinal,policy_snapshot_id) VALUES($1,$2,$3,$4)`, value.GetTenantId(), decisionID, ordinal, policyID); storeErr != nil {
			return storeErr
		}
	}
	for ordinal, constraint := range value.GetConstraints() {
		if constraint == nil || constraint.GetKind() == "" || !validSHA256(constraint.GetDetailsDigest()) {
			return ErrInvalidArgument
		}
		var constraintExpiry any
		if constraint.GetExpireTime() != nil {
			constraintExpiry = constraint.GetExpireTime().AsTime().UTC()
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO authorization_decision_constraints(tenant_id,decision_id,ordinal,constraint_kind,details_digest,expire_time) VALUES($1,$2,$3,$4,$5,$6)`, value.GetTenantId(), decisionID, ordinal, constraint.GetKind(), constraint.GetDetailsDigest(), constraintExpiry); err != nil {
			return err
		}
	}
	return nil
}

func loadAuthorizationDecision(ctx context.Context, tx *sql.Tx, tenantID, name string) (*policyv1.AuthorizationDecision, error) {
	var (
		value      policyv1.AuthorizationDecision
		decisionID int64
		resourceID sql.NullInt64
		outcome    int32
		evaluated  time.Time
		expires    sql.NullTime
	)
	err := tx.QueryRowContext(ctx, `SELECT id,name,uid,project_id,principal_ref,action,resource_ref_id,intent_digest,outcome,reason_code,safe_reason,evaluated_at,expire_time,context_digest,decision_digest FROM authorization_decisions WHERE tenant_id=$1 AND name=$2`, tenantID, name).Scan(
		&decisionID, &value.Name, &value.Uid, &value.ProjectId, &value.PrincipalRef, &value.Action, &resourceID,
		&value.IntentDigest, &outcome, &value.ReasonCode, &value.SafeReason, &evaluated, &expires,
		&value.ContextDigest, &value.DecisionDigest,
	)
	if err != nil {
		return nil, err
	}
	value.TenantId = tenantID
	value.Outcome = policyv1.AuthorizationOutcome(outcome)
	value.EvaluatedAt = timestamppb.New(evaluated.UTC())
	if expires.Valid {
		value.ExpireTime = timestamppb.New(expires.Time.UTC())
	}
	value.Resource, err = platformdb.LoadResourceRef(ctx, tx, tenantID, resourceID)
	if err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, `SELECT policy_snapshot_id FROM authorization_decision_policies WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, decisionID)
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
		item, loadErr := loadPolicyReference(ctx, tx, tenantID, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, loadErr
		}
		value.Policies = append(value.Policies, item)
	}
	rows, err = tx.QueryContext(ctx, `SELECT constraint_kind,details_digest,expire_time FROM authorization_decision_constraints WHERE tenant_id=$1 AND decision_id=$2 ORDER BY ordinal`, tenantID, decisionID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var item policyv1.AuthorizationConstraint
		var itemExpiry sql.NullTime
		if err = rows.Scan(&item.Kind, &item.DetailsDigest, &itemExpiry); err != nil {
			_ = platformdb.CloseRows(rows)
			return nil, err
		}
		if itemExpiry.Valid {
			item.ExpireTime = timestamppb.New(itemExpiry.Time.UTC())
		}
		value.Constraints = append(value.Constraints, &item)
	}
	if err = rows.Err(); err != nil {
		_ = platformdb.CloseRows(rows)
		return nil, err
	}
	_ = platformdb.CloseRows(rows)
	return &value, nil
}

func validateUsePolicyInput(value *policyv1.UsePolicy) error {
	if value == nil || value.GetDisplayName() == "" || len(value.GetDisplayName()) > 256 || validateArtifact(value.GetPolicyDocument()) != nil {
		return ErrInvalidArgument
	}
	return nil
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
	err := row.Scan(
		&value.id, &value.tenant, &value.project, &value.job, &value.status, &value.version,
		&value.done, &value.etag, &value.targetPresent, &value.targetType, &value.targetID,
		&value.targetTenant, &value.targetProject, &value.targetVersion, &value.targetName,
		&value.targetETag, &value.result, &value.errorDetail, &value.created, &value.updated,
	)
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
	value := &jobv1.Operation{
		OperationId: row.id, TenantId: row.tenant, ProjectId: row.project, JobId: row.job,
		State: state, ResourceVersion: row.version, Done: row.done, Etag: row.etag,
		Result: result, Error: detail, CreatedAt: timestamppb.New(row.created.UTC()), UpdatedAt: timestamppb.New(row.updated.UTC()),
	}
	if row.targetPresent {
		value.Target = &commonv1.ResourceRef{
			ResourceType: row.targetType, ResourceId: row.targetID, TenantId: row.targetTenant,
			ProjectId: row.targetProject, ResourceVersion: row.targetVersion, Name: row.targetName, Etag: row.targetETag,
		}
	}
	return value, nil
}

func getOperationTx(ctx context.Context, tx *sql.Tx, identity Identity, id string) (*jobv1.Operation, error) {
	row, err := scanOperation(tx.QueryRowContext(ctx, `SELECT `+operationColumns+` FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3`, identity.TenantID, identity.ProjectID, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return operationProto(ctx, tx, row)
}
