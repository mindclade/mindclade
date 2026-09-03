package workflows

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"fmt"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

const maximumApprovalLifetime = 30 * 24 * time.Hour

func storeApprovalBinding(ctx context.Context, tx *sql.Tx, identity Identity, binding *workflowv1.ApprovalBinding) (sql.NullInt64, int64, error) {
	if binding == nil {
		return sql.NullInt64{}, 0, ErrInvalidArgument
	}
	toolID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, binding.GetTool())
	if err != nil {
		return sql.NullInt64{}, 0, err
	}
	policyID, err := StorePolicySnapshot(ctx, tx, identity.TenantID, binding.GetPolicySnapshot())
	return toolID, policyID, err
}

func storeApprovalRequestChildren(ctx context.Context, tx *sql.Tx, identity Identity, value *workflowv1.ApprovalRequest) error {
	for ordinal, artifact := range value.GetBinding().GetInputArtifacts() {
		id, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, artifact)
		if err != nil {
			return err
		}
		if !id.Valid {
			return ErrInvalidArgument
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO approval_request_input_artifacts(tenant_id,project_id,approval_request_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id.Int64); err != nil {
			return err
		}
	}
	for ordinal, decision := range value.GetPolicyDecisions() {
		id, err := StoreAuthorizationDecision(ctx, tx, identity, decision)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO approval_request_policy_decisions(tenant_id,project_id,approval_request_name,ordinal,authorization_decision_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id); err != nil {
			return err
		}
	}
	return nil
}

func validateApprovalWindow(value *workflowv1.ApprovalRequest, at time.Time) error {
	if value == nil || value.GetExpireTime() == nil || value.GetExpireTime().CheckValid() != nil {
		return ErrInvalidArgument
	}
	expiry := value.GetExpireTime().AsTime().UTC()
	if !expiry.After(at) || expiry.Sub(at) > maximumApprovalLifetime {
		return ErrApprovalExpired
	}
	for _, decision := range value.GetPolicyDecisions() {
		if decision.GetOutcome() != policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW {
			return ErrPermissionDenied
		}
		if decision.GetExpireTime() != nil && !decision.GetExpireTime().AsTime().After(at) {
			return ErrApprovalExpired
		}
	}
	return nil
}

func (repository SQLRepository) RequestApproval(ctx context.Context, identity Identity, requested *workflowv1.ApprovalRequest, digest string, at time.Time) (*workflowv1.ApprovalRequest, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	if err := validateApprovalWindow(requested, at); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "approval.request", requested.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, _, loadErr := getApprovalTx(ctx, tx, identity, responseName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	id, err := randomID("approval_")
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("apr_")
	if err != nil {
		return nil, false, err
	}
	value := clone(requested)
	value.Name, value.Uid, value.Revision = approvalName(identity, id), uid, 1
	value.Etag, value.TenantId, value.ProjectId = resourceETag(value.GetName(), 1), identity.TenantID, identity.ProjectID
	value.State, value.RequestedAt = workflowv1.ApprovalState_APPROVAL_STATE_PENDING, timestamppb.New(at.UTC())
	contextRow, err := contextValues(value.GetContext())
	if err != nil {
		return nil, false, err
	}
	toolID, policyID, err := storeApprovalBinding(ctx, tx, identity, value.GetBinding())
	if err != nil {
		return nil, false, err
	}
	expiry, err := requireTimestamp(value.GetExpireTime(), "approval expiry")
	if err != nil {
		return nil, false, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO approval_requests(tenant_id,project_id,name,uid,revision,etag,context_request_id,context_idempotency_key,context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,context_correlation_id,context_causation_id,context_cancellation_token_id,binding_action,binding_intent_digest,binding_parameters_digest,binding_agent_run_name,binding_agent_step_name,binding_tool_ref_id,binding_tool_version,binding_policy_snapshot_id,binding_risk_class,binding_digest,requested_by_principal_ref,minimum_independent_approvers,reuse_policy,state,requested_at,expire_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30)`,
		identity.TenantID, identity.ProjectID, value.GetName(), value.GetUid(), value.GetEtag(), contextRow.requestID, contextRow.idempotencyKey, contextRow.principalID, contextRow.traceID, contextRow.deadline, contextRow.canonicalDigest, contextRow.correlationID, contextRow.causationID, contextRow.cancellationTokenID,
		value.GetBinding().GetAction(), value.GetBinding().GetIntentDigest(), value.GetBinding().GetParametersDigest(), value.GetBinding().GetAgentRunName(), value.GetBinding().GetAgentStepName(), toolID, value.GetBinding().GetToolVersion(), policyID, value.GetBinding().GetRiskClass(), value.GetBinding().GetBindingDigest(), value.GetRequestedByPrincipalRef(), value.GetMinimumIndependentApprovers(), int32(value.GetReusePolicy()), int32(value.GetState()), at.UTC(), expiry)
	if err != nil {
		return nil, false, err
	}
	if err = storeApprovalRequestChildren(ctx, tx, identity, value); err != nil {
		return nil, false, err
	}
	event, err := repository.Events.ApprovalRequested(identity, value, at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", value.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(value), false, nil
}

func (repository SQLRepository) GetApproval(ctx context.Context, identity Identity, name string) (*workflowv1.ApprovalRequest, error) {
	if err := repository.validate(); err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	value, _, err := getApprovalTx(ctx, tx, identity, name, false)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (repository SQLRepository) ListApprovals(ctx context.Context, identity Identity, page ApprovalPage) ([]*workflowv1.ApprovalRequest, string, time.Time, error) {
	if err := repository.validate(); err != nil {
		return nil, "", time.Time{}, err
	}
	if page.Limit <= 0 || page.Limit > maximumPageSize {
		return nil, "", time.Time{}, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return nil, "", time.Time{}, err
	}
	defer func() { _ = tx.Rollback() }()
	var readAt time.Time
	if err = tx.QueryRowContext(ctx, `SELECT transaction_timestamp()`).Scan(&readAt); err != nil {
		return nil, "", time.Time{}, err
	}
	query := `SELECT ` + approvalColumns + ` FROM approval_requests WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != workflowv1.ApprovalState_APPROVAL_STATE_UNSPECIFIED {
		query += fmt.Sprintf(" AND state=$%d", next)
		args = append(args, int32(page.State))
		next++
	}
	if !page.AfterTime.IsZero() {
		query += fmt.Sprintf(" AND (requested_at,name)<($%d,$%d)", next, next+1)
		args = append(args, page.AfterTime.UTC(), page.AfterName)
		next += 2
	}
	query += fmt.Sprintf(" ORDER BY requested_at DESC,name DESC LIMIT $%d", next) //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
	args = append(args, page.Limit+1)
	rows, err := tx.QueryContext(ctx, query, args...) //nolint:sqlclosecheck // Rows are closed eagerly through platformdb.CloseRows on every exit path.
	if err != nil {
		return nil, "", time.Time{}, err
	}
	var stored []approvalRow
	for rows.Next() {
		item, scanErr := scanApproval(rows)
		if scanErr != nil {
			_ = platformdb.CloseRows(rows)
			return nil, "", time.Time{}, scanErr
		}
		stored = append(stored, item)
	}
	if err = platformdb.CloseRows(rows); err != nil {
		return nil, "", time.Time{}, err
	}
	if err = rows.Err(); err != nil {
		return nil, "", time.Time{}, err
	}
	hasMore := len(stored) > page.Limit
	if hasMore {
		stored = stored[:page.Limit]
	}
	values := make([]*workflowv1.ApprovalRequest, 0, len(stored))
	for _, item := range stored {
		value, mapErr := approvalProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, value)
	}
	token := ""
	if hasMore {
		last := stored[len(stored)-1]
		token, err = repository.Pagination.encode(pageToken{Kind: "approvals", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.requestedAt.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return cloneSlice(values), token, readAt.UTC(), nil
}

func approverAuthority(identity Identity) (*commonv1.ResourceRef, error) {
	role := ""
	for _, candidate := range []string{"platform-admin", "approver"} {
		if identity.HasAnyRole(candidate) {
			role = candidate
			break
		}
	}
	if role == "" {
		return nil, ErrPermissionDenied
	}
	name := projectParent(identity) + "/approvalAuthorities/" + role
	return &commonv1.ResourceRef{ResourceType: "mindclade.iam.v1.ApprovalAuthority", ResourceId: role, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: name, Etag: resourceETag(name, 1)}, nil
}

func canonicalReceiptDigest(value *workflowv1.ApprovalReceipt) (string, error) {
	if value == nil {
		return "", ErrInvalidArgument
	}
	copy := clone(value)
	copy.ReceiptDigest, copy.ConsumedByCallId, copy.ConsumedAt = "", "", nil
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func storeReceiptChildren(ctx context.Context, tx *sql.Tx, identity Identity, value *workflowv1.ApprovalReceipt) error {
	for ordinal, artifact := range value.GetBinding().GetInputArtifacts() {
		id, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, artifact)
		if err != nil {
			return err
		}
		if !id.Valid {
			return ErrInvalidArgument
		}
		if _, err = tx.ExecContext(ctx, `INSERT INTO approval_receipt_input_artifacts(tenant_id,project_id,approval_receipt_name,ordinal,artifact_ref_id) VALUES($1,$2,$3,$4,$5)`, identity.TenantID, identity.ProjectID, value.GetName(), ordinal, id.Int64); err != nil {
			return err
		}
	}
	return nil
}

func (repository SQLRepository) DecideApproval(ctx context.Context, identity Identity, request *internalworkflowv1.DecideApprovalRequest, digest string, at time.Time) (*workflowv1.ApprovalReceipt, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "approval.decide", request.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		value, loadErr := LoadApprovalReceipt(ctx, tx, identity.TenantID, identity.ProjectID, responseName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		value.ConsumedAt, value.ConsumedByCallId = nil, ""
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(value), true, nil
	}
	approval, _, err := getApprovalTx(ctx, tx, identity, request.GetName(), true)
	if err != nil {
		return nil, false, err
	}
	if request.GetEtag() != approval.GetEtag() {
		return nil, false, ErrRevisionConflict
	}
	if approval.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_PENDING {
		return nil, false, ErrInvalidTransition
	}
	if !at.Before(approval.GetExpireTime().AsTime()) {
		return nil, false, ErrApprovalExpired
	}
	if subtle.ConstantTimeCompare([]byte(identity.Principal), []byte(approval.GetRequestedByPrincipalRef())) == 1 {
		return nil, false, ErrPermissionDenied
	}
	var already bool
	if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM approval_receipts WHERE tenant_id=$1 AND project_id=$2 AND request_ref_id IN (SELECT id FROM resource_references WHERE tenant_id=$1 AND name=$3) AND approver_principal_ref=$4)`, identity.TenantID, identity.ProjectID, approval.GetName(), identity.Principal).Scan(&already); err != nil {
		return nil, false, err
	}
	if already {
		return nil, false, ErrAlreadyExists
	}
	authority, err := approverAuthority(identity)
	if err != nil {
		return nil, false, err
	}
	receiptID, err := randomID("receipt_")
	if err != nil {
		return nil, false, err
	}
	receiptUID, err := randomID("aprct_")
	if err != nil {
		return nil, false, err
	}
	newState := workflowv1.ApprovalState_APPROVAL_STATE_PENDING
	if request.GetDecision() == workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_DENY {
		newState = workflowv1.ApprovalState_APPROVAL_STATE_DENIED
	} else {
		var approvals int64
		if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM approval_receipts r JOIN resource_references rr ON rr.tenant_id=r.tenant_id AND rr.id=r.request_ref_id WHERE r.tenant_id=$1 AND r.project_id=$2 AND rr.name=$3 AND r.decision=$4`, identity.TenantID, identity.ProjectID, approval.GetName(), int32(workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_APPROVE)).Scan(&approvals); err != nil {
			return nil, false, err
		}
		if approvals+1 >= int64(approval.GetMinimumIndependentApprovers()) {
			newState = workflowv1.ApprovalState_APPROVAL_STATE_APPROVED
		}
	}
	approval.Revision++
	approval.Etag, approval.State = resourceETag(approval.GetName(), approval.GetRevision()), newState
	result, err := tx.ExecContext(ctx, `UPDATE approval_requests SET revision=$4,etag=$5,state=$6 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$7 AND etag=$8 AND state=$9`, identity.TenantID, identity.ProjectID, approval.GetName(), approval.GetRevision(), approval.GetEtag(), int32(newState), approval.GetRevision()-1, request.GetEtag(), int32(workflowv1.ApprovalState_APPROVAL_STATE_PENDING))
	if err != nil {
		return nil, false, err
	}
	if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
		if rowsErr != nil {
			return nil, false, rowsErr
		}
		return nil, false, ErrRevisionConflict
	}
	receipt := &workflowv1.ApprovalReceipt{Context: clone(request.GetContext()), Name: approvalReceiptName(identity, receiptID), Uid: receiptUID, Request: approvalRequestResource(approval), Binding: clone(approval.GetBinding()), Decision: request.GetDecision(), ApproverPrincipalRef: identity.Principal, ApproverAuthority: authority, ReasonCode: request.GetReasonCode(), SafeReason: request.GetSafeReason(), ReusePolicy: approval.GetReusePolicy(), DecidedAt: timestamppb.New(at.UTC()), ExpireTime: clone(approval.GetExpireTime()), SignerIdentity: "mindclade-approval-authority"}
	receipt.ReceiptDigest, err = canonicalReceiptDigest(receipt)
	if err != nil {
		return nil, false, err
	}
	contextRow, err := contextValues(receipt.GetContext())
	if err != nil {
		return nil, false, err
	}
	requestRefID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, receipt.GetRequest())
	if err != nil || !requestRefID.Valid {
		if err == nil {
			err = ErrInvalidArgument
		}
		return nil, false, err
	}
	toolID, policyID, err := storeApprovalBinding(ctx, tx, identity, receipt.GetBinding())
	if err != nil {
		return nil, false, err
	}
	authorityID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, authority)
	if err != nil || !authorityID.Valid {
		if err == nil {
			err = ErrInvalidArgument
		}
		return nil, false, err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO approval_receipts(tenant_id,project_id,name,uid,context_request_id,context_idempotency_key,context_principal_id,context_trace_id,context_deadline,context_canonical_request_digest,context_correlation_id,context_causation_id,context_cancellation_token_id,request_ref_id,binding_action,binding_intent_digest,binding_parameters_digest,binding_agent_run_name,binding_agent_step_name,binding_tool_ref_id,binding_tool_version,binding_policy_snapshot_id,binding_risk_class,binding_digest,decision,approver_principal_ref,approver_authority_ref_id,reason_code,safe_reason,reuse_policy,decided_at,expire_time,signer_identity,receipt_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34)`,
		identity.TenantID, identity.ProjectID, receipt.GetName(), receipt.GetUid(), contextRow.requestID, contextRow.idempotencyKey, contextRow.principalID, contextRow.traceID, contextRow.deadline, contextRow.canonicalDigest, contextRow.correlationID, contextRow.causationID, contextRow.cancellationTokenID, requestRefID.Int64,
		receipt.GetBinding().GetAction(), receipt.GetBinding().GetIntentDigest(), receipt.GetBinding().GetParametersDigest(), receipt.GetBinding().GetAgentRunName(), receipt.GetBinding().GetAgentStepName(), toolID, receipt.GetBinding().GetToolVersion(), policyID, receipt.GetBinding().GetRiskClass(), receipt.GetBinding().GetBindingDigest(), int32(receipt.GetDecision()), receipt.GetApproverPrincipalRef(), authorityID.Int64, receipt.GetReasonCode(), receipt.GetSafeReason(), int32(receipt.GetReusePolicy()), at.UTC(), receipt.GetExpireTime().AsTime().UTC(), receipt.GetSignerIdentity(), receipt.GetReceiptDigest())
	if err != nil {
		return nil, false, err
	}
	if err = storeReceiptChildren(ctx, tx, identity, receipt); err != nil {
		return nil, false, err
	}
	event, err := repository.Events.ApprovalRecorded(identity, approval, receipt, at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", receipt.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(receipt), false, nil
}

func loadReceiptConsumption(ctx context.Context, tx *sql.Tx, identity Identity, name, callID string) (time.Time, string, error) {
	var consumed time.Time
	var principal string
	err := tx.QueryRowContext(ctx, `SELECT consumed_at,consumed_by_principal_ref FROM approval_receipt_consumptions WHERE tenant_id=$1 AND project_id=$2 AND approval_receipt_name=$3 AND consumed_by_call_id=$4`, identity.TenantID, identity.ProjectID, name, callID).Scan(&consumed, &principal)
	return consumed, principal, err
}

func (repository SQLRepository) ConsumeApproval(ctx context.Context, identity Identity, request *internalworkflowv1.ConsumeApprovalRequest, digest string, at time.Time) (*workflowv1.ApprovalReceipt, bool, error) {
	if err := repository.validate(); err != nil {
		return nil, false, err
	}
	canonical, err := canonicalScopedName(identity, request.GetReceiptName(), "approvalReceipts")
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, repository.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	action, key := "approval.consume", request.GetContext().GetIdempotencyKey()
	_, responseName, replay, err := checkReceipt(ctx, tx, identity, action, key, digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		receipt, loadErr := LoadApprovalReceipt(ctx, tx, identity.TenantID, identity.ProjectID, responseName, false)
		if loadErr != nil {
			return nil, false, loadErr
		}
		consumed, principal, loadErr := loadReceiptConsumption(ctx, tx, identity, responseName, request.GetCallId())
		if loadErr != nil || principal != identity.Principal {
			if loadErr == nil {
				loadErr = ErrPermissionDenied
			}
			return nil, false, loadErr
		}
		receipt.ConsumedAt, receipt.ConsumedByCallId = timestamppb.New(consumed.UTC()), request.GetCallId()
		if err = tx.Commit(); err != nil {
			return nil, false, err
		}
		return clone(receipt), true, nil
	}
	receipt, err := LoadApprovalReceipt(ctx, tx, identity.TenantID, identity.ProjectID, canonical, true)
	if err != nil {
		return nil, false, err
	}
	if receipt.GetDecision() != workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_APPROVE {
		return nil, false, ErrPermissionDenied
	}
	if !at.Before(receipt.GetExpireTime().AsTime()) {
		return nil, false, ErrApprovalExpired
	}
	if subtle.ConstantTimeCompare([]byte(request.GetBindingDigest()), []byte(receipt.GetBinding().GetBindingDigest())) != 1 {
		return nil, false, ErrPermissionDenied
	}
	var consumptionCount int64
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM approval_receipt_consumptions WHERE tenant_id=$1 AND project_id=$2 AND approval_receipt_name=$3`, identity.TenantID, identity.ProjectID, receipt.GetName()).Scan(&consumptionCount); err != nil {
		return nil, false, err
	}
	if receipt.GetReusePolicy() == workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_SINGLE_USE && consumptionCount != 0 {
		return nil, false, ErrApprovalConsumed
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO approval_receipt_consumptions(tenant_id,project_id,approval_receipt_name,consumed_at,consumed_by_call_id,consumed_by_principal_ref) VALUES($1,$2,$3,$4,$5,$6)`, identity.TenantID, identity.ProjectID, receipt.GetName(), at.UTC(), request.GetCallId(), identity.Principal)
	if err != nil {
		return nil, false, err
	}
	receipt.ConsumedAt, receipt.ConsumedByCallId = timestamppb.New(at.UTC()), request.GetCallId()
	if receipt.GetReusePolicy() == workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_SINGLE_USE {
		requestName := receipt.GetRequest().GetName()
		approval, _, loadErr := getApprovalTx(ctx, tx, identity, requestName, true)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if approval.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_APPROVED {
			return nil, false, ErrInvalidTransition
		}
		approval.Revision++
		approval.State, approval.Etag = workflowv1.ApprovalState_APPROVAL_STATE_CONSUMED, resourceETag(approval.GetName(), approval.GetRevision())
		result, updateErr := tx.ExecContext(ctx, `UPDATE approval_requests SET revision=$4,etag=$5,state=$6 WHERE tenant_id=$1 AND project_id=$2 AND name=$3 AND revision=$7 AND state=$8`, identity.TenantID, identity.ProjectID, approval.GetName(), approval.GetRevision(), approval.GetEtag(), int32(approval.GetState()), approval.GetRevision()-1, int32(workflowv1.ApprovalState_APPROVAL_STATE_APPROVED))
		if updateErr != nil {
			return nil, false, updateErr
		}
		if changed, rowsErr := result.RowsAffected(); rowsErr != nil || changed != 1 {
			if rowsErr != nil {
				return nil, false, rowsErr
			}
			return nil, false, ErrRevisionConflict
		}
	}
	sequence, conversionErr := numconv.Int64ToUint64(consumptionCount + 1)
	if conversionErr != nil {
		return nil, false, conversionErr
	}
	event, err := repository.Events.ApprovalConsumed(identity, receipt, request.GetCallId(), sequence, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = recordMutation(ctx, tx, identity, action, key, digest, "", receipt.GetName(), []*commonv1.EventEnvelope{event}, at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(receipt), false, nil
}
