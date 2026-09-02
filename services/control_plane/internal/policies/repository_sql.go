package policies

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
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	platformdb "github.com/mindclade/mindclade/services/control_plane/internal/platform/database"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Pagination == nil || r.Events == nil {
		return errors.New("policy SQL repository requires database, pagination codec, and event factory")
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
	var stored string
	var operationID, decisionName sql.NullString
	err := tx.QueryRowContext(ctx, `SELECT request_digest,operation_id,decision_name FROM policy_admin_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&stored, &operationID, &decisionName)
	if errors.Is(err, sql.ErrNoRows) {
		return "", "", false, nil
	}
	if err != nil {
		return "", "", false, err
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(digest)) != 1 {
		return "", "", false, ErrIdempotencyConflict
	}
	return operationID.String, decisionName.String, true, nil
}

func insertReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, operationID, decisionName string, at time.Time) error {
	var operation, decision any
	if operationID != "" {
		operation = operationID
	}
	if decisionName != "" {
		decision = decisionName
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO policy_admin_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,operation_id,decision_name,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, operation, decision, at.UTC())
	return err
}

func insertOutbox(ctx context.Context, tx *sql.Tx, event *commonv1.EventEnvelope, at time.Time) error {
	encoded, err := queue.MarshalEnvelope(event)
	if err != nil {
		return err
	}
	kind, id, err := queue.AggregateIdentity(event)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO outbox_messages(id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, event.GetEventId(), event.GetTenantId(), event.GetEventType(), event.GetEventVersion(), kind, id, event.GetAggregateSequence(), event.GetPayloadDigest(), encoded, at.UTC())
	return err
}

func deniedSecuritySubject(identity Identity, subject *commonv1.ResourceRef, reasonCode, decisionDigest string, command *commonv1.CommandContext) (*commonv1.ResourceRef, error) {
	if subject == nil || command == nil || subject.GetName() == "" || reasonCode == "" || !validSHA256(decisionDigest) ||
		command.GetRequestId() == "" || command.GetIdempotencyKey() == "" || command.GetTenantId() != identity.TenantID ||
		command.GetProjectId() != identity.ProjectID || command.GetPrincipalId() != identity.Principal {
		return nil, ErrInvalidArgument
	}
	// Both request and idempotency identity are trusted command context. Binding
	// them into the subject makes independent denials distinct while an exact
	// idempotent replay deterministically addresses the same security fact.
	securityIdentity := sha256.Sum256([]byte(subject.GetName() + "\x00" + reasonCode + "\x00" + decisionDigest + "\x00" + command.GetRequestId() + "\x00" + command.GetIdempotencyKey()))
	securityID := "security-" + hex.EncodeToString(securityIdentity[:16])
	return &commonv1.ResourceRef{
		ResourceType: "security_event", ResourceId: securityID, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		ResourceVersion: 1, Name: subject.GetName() + "/securityEvents/" + securityID, Etag: decisionDigest,
	}, nil
}

func insertPolicyAudit(ctx context.Context, tx *sql.Tx, identity Identity, action string, subject *commonv1.ResourceRef, result int32, reasonCode, decisionDigest, beforeRevision, afterRevision, detailDigest string, command *commonv1.CommandContext, at time.Time) error {
	decision := "allowed"
	if result == 3 {
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
	if decision == "denied" {
		securitySubject, subjectErr := deniedSecuritySubject(identity, subject, reasonCode, decisionDigest, command)
		if subjectErr != nil {
			return subjectErr
		}
		securityEvent, securityErr := foundationaudit.NewSecurityEvent(identity.TenantID, identity.ProjectID, "high", reasonCode, decisionDigest, securitySubject, command, at.UTC())
		if securityErr != nil {
			return securityErr
		}
		securityBytes, marshalErr := queue.MarshalEnvelope(securityEvent)
		if marshalErr != nil {
			return marshalErr
		}
		if _, securityErr = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, securityEvent.GetEventId(), identity.TenantID, identity.Principal, "security."+action, subject.GetName(), at.UTC(), decisionDigest, securityEvent.GetEventVersion(), securityEvent.GetPayloadDigest(), securityBytes); securityErr != nil {
			return securityErr
		}
		if securityErr = insertOutbox(ctx, tx, securityEvent, at); securityErr != nil {
			return securityErr
		}
	}
	resourceID, err := platformdb.StoreResourceRef(ctx, tx, identity.TenantID, subject)
	if err != nil {
		return err
	}
	requestID, traceID := "", ""
	if command != nil {
		requestID, traceID = command.GetRequestId(), command.GetTraceId()
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO administrative_audit_records(tenant_id,event_id,project_id,occurred_at,actor_principal_ref,action,resource_ref_id,authorization_decision_digest,before_revision,after_revision,policy_reason_code,result,request_id,trace_id,detail_digest) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`, identity.TenantID, event.GetEventId(), identity.ProjectID, at.UTC(), identity.Principal, action, resourceID, decisionDigest, beforeRevision, afterRevision, reasonCode, result, requestID, traceID, detailDigest)
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
	jobETag, operationETag := resourceETag(jobID, 1), resourceETag(operationID, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO jobs(id,tenant_id,operation_id,project_id,desired_state,version,policy_digest,job_kind,input_ref_id,configuration_ref_id,configuration_digest,etag,created_at,updated_at) VALUES($1,$2,$3,$4,'SUCCEEDED',1,'','policy.lifecycle',NULL,NULL,$5,$6,$7,$7)`, jobID, identity.TenantID, operationID, identity.ProjectID, digest, jobETag, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operations(id,tenant_id,project_id,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,version,done,etag,result_ref_id,error_detail_id,request_hash,created_at,updated_at) VALUES($1,$2,$3,$4,true,$5,$6,$2,$3,$7,$8,$9,'SUCCEEDED',1,true,$10,NULL,NULL,$11,$12,$12)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, digest, at.UTC()); err != nil {
		return nil, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO operation_revisions(operation_id,tenant_id,project_id,revision,job_id,target_present,target_resource_type,target_resource_id,target_tenant_id,target_project_id,target_resource_version,target_name,target_etag,status,done,etag,result_ref_id,error_detail_id,created_at,updated_at,recorded_at) VALUES($1,$2,$3,1,$4,true,$5,$6,$2,$3,$7,$8,$9,'SUCCEEDED',true,$10,NULL,NULL,$11,$11,$11)`, operationID, identity.TenantID, identity.ProjectID, jobID, target.GetResourceType(), target.GetResourceId(), target.GetResourceVersion(), target.GetName(), target.GetEtag(), operationETag, at.UTC()); err != nil {
		return nil, err
	}
	return &jobv1.Operation{
		OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID,
		State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 1, Done: true,
		Etag: operationETag, Target: clone(target), CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC()),
	}, nil
}

func finishPolicyMutation(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string, target *commonv1.ResourceRef, event func(*jobv1.Operation) (*commonv1.EventEnvelope, error), beforeRevision string, command *commonv1.CommandContext, at time.Time) (*jobv1.Operation, error) {
	operation, err := insertCompletedOperation(ctx, tx, identity, digest, target, at)
	if err != nil {
		return nil, err
	}
	envelope, err := event(operation)
	if err != nil {
		return nil, err
	}
	if err = insertPolicyAudit(ctx, tx, identity, action, target, 1, "", "", beforeRevision, strconv.FormatInt(target.GetResourceVersion(), 10), digest, command, at); err != nil {
		return nil, err
	}
	if err = insertOutbox(ctx, tx, envelope, at); err != nil {
		return nil, err
	}
	if err = insertReceipt(ctx, tx, identity, action, key, digest, operation.GetOperationId(), "", at); err != nil {
		return nil, err
	}
	return operation, nil
}

func (r SQLRepository) EvaluateAuthorization(ctx context.Context, identity Identity, request *internalpolicyv1.EvaluateAuthorizationRequest, digest string, at time.Time) (*policyv1.AuthorizationDecision, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetTenantId() != identity.TenantID || request.GetProjectId() != identity.ProjectID || request.GetPrincipalRef() != identity.Principal || request.GetAction() == "" || !validSHA256(request.GetIntentDigest()) {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	resource := request.GetResource()
	if resource == nil || resource.GetResourceType() == "" || resource.GetResourceId() == "" || resource.GetName() == "" || resource.GetTenantId() != identity.TenantID || resource.GetProjectId() != identity.ProjectID || resource.GetResourceVersion() < 0 {
		return nil, false, ErrPermissionDenied
	}
	if deadline := request.GetDeadline(); deadline != nil {
		if deadline.CheckValid() != nil {
			return nil, false, ErrInvalidArgument
		}
		if !at.Before(deadline.AsTime()) {
			return nil, false, ErrDeadlineExceeded
		}
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	_, decisionName, replay, err := checkReceipt(ctx, tx, identity, "policy.authorization.evaluate", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		decision, loadErr := loadAuthorizationDecision(ctx, tx, identity.TenantID, decisionName)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(decision), true, nil
	}

	resolved := make([]*policyv1.PolicyReference, 0, len(request.GetPolicySnapshots()))
	unresolved := len(request.GetPolicySnapshots()) == 0
	for _, requested := range request.GetPolicySnapshots() {
		if validatePolicyReference(requested, at) != nil {
			unresolved = true
			continue
		}
		var id int64
		lookupErr := tx.QueryRowContext(ctx, `SELECT id FROM policy_snapshot_references WHERE tenant_id=$1 AND name=$2 AND resource_revision=$3 AND digest=$4`, identity.TenantID, requested.GetName(), requested.GetResourceRevision(), requested.GetDigest()).Scan(&id)
		if errors.Is(lookupErr, sql.ErrNoRows) {
			unresolved = true
			continue
		}
		if lookupErr != nil {
			return nil, false, lookupErr
		}
		stored, loadErr := loadPolicyReference(ctx, tx, identity.TenantID, sql.NullInt64{Int64: id, Valid: true})
		if loadErr != nil {
			return nil, false, loadErr
		}
		if !proto.Equal(stored, requested) {
			unresolved = true
			continue
		}
		resolved = append(resolved, stored)
	}
	engine := r.Evaluator
	if engine == nil {
		engine = DenyAllEvaluator{}
	}
	result, err := engine.Evaluate(ctx, identity, clone(request), cloneSlice(resolved))
	if err != nil {
		result = PolicyEngineResult{Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY, ReasonCode: "POLICY_EVALUATION_FAILED", SafeReason: "authorization could not be granted"}
	}
	if unresolved {
		result = PolicyEngineResult{Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY, ReasonCode: "POLICY_SNAPSHOT_UNRESOLVED", SafeReason: "authorization could not be granted"}
	}
	if result.Outcome == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_UNSPECIFIED || result.ReasonCode == "" {
		return nil, false, ErrInvalidArgument
	}
	for _, constraint := range result.Constraints {
		if constraint == nil || constraint.GetKind() == "" || !validSHA256(constraint.GetDetailsDigest()) {
			return nil, false, ErrInvalidArgument
		}
	}
	uid, err := randomID("decision_")
	if err != nil {
		return nil, false, err
	}
	name := projectParent(identity) + "/authorizationDecisions/" + uid
	decision := &policyv1.AuthorizationDecision{
		Name: name, Uid: uid, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		PrincipalRef: identity.Principal, Action: request.GetAction(), Resource: clone(resource),
		IntentDigest: request.GetIntentDigest(), Policies: cloneSlice(resolved), Outcome: result.Outcome,
		ReasonCode: result.ReasonCode, SafeReason: result.SafeReason, Constraints: cloneSlice(result.Constraints),
		EvaluatedAt: timestamppb.New(at.UTC()), ContextDigest: digest,
	}
	if !result.ExpireTime.IsZero() {
		if !result.ExpireTime.After(at) {
			return nil, false, ErrInvalidArgument
		}
		decision.ExpireTime = timestamppb.New(result.ExpireTime.UTC())
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(decision)
	if err != nil {
		return nil, false, err
	}
	decisionHash := sha256.Sum256(encoded)
	decision.DecisionDigest = "sha256:" + hex.EncodeToString(decisionHash[:])
	if err = storeAuthorizationDecision(ctx, tx, decision); err != nil {
		return nil, false, err
	}
	event, err := r.Events.DecisionRecorded(identity, decision, request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	decisionResource := &commonv1.ResourceRef{ResourceType: "authorization_decision", ResourceId: uid, TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: name, Etag: decision.GetDecisionDigest()}
	auditResult := int32(3)
	if result.Outcome == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW {
		auditResult = 1
	}
	if err = insertPolicyAudit(ctx, tx, identity, "policy.authorization.evaluate", decisionResource, auditResult, decision.GetReasonCode(), decision.GetDecisionDigest(), "", "1", digest, request.GetContext(), at); err != nil {
		return nil, false, err
	}
	if err = insertOutbox(ctx, tx, event, at); err != nil {
		return nil, false, err
	}
	if err = insertReceipt(ctx, tx, identity, "policy.authorization.evaluate", request.GetContext().GetIdempotencyKey(), digest, "", decision.GetName(), at); err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(decision), false, nil
}

func (r SQLRepository) CreateUsePolicy(ctx context.Context, identity Identity, request *internalpolicyv1.CreateUsePolicyRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetUsePolicyId()) || validateUsePolicyInput(request.GetUsePolicy()) != nil {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	input := clone(request.GetUsePolicy())
	if input.GetState() != policyv1.UsePolicyState_USE_POLICY_STATE_UNSPECIFIED && input.GetState() != policyv1.UsePolicyState_USE_POLICY_STATE_DRAFT {
		return nil, false, ErrInvalidArgument
	}
	name, err := policyName(identity, request.GetUsePolicyId())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, "policy.use.create", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	var exists int
	err = tx.QueryRowContext(ctx, `SELECT 1 FROM use_policies WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name).Scan(&exists)
	if err == nil {
		return nil, false, ErrAlreadyExists
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, false, err
	}
	documentID, err := platformdb.StoreArtifactRef(ctx, tx, identity.TenantID, input.GetPolicyDocument())
	if err != nil {
		return nil, false, err
	}
	uid, err := randomID("policy_")
	if err != nil {
		return nil, false, err
	}
	etag := resourceETag(name, 1)
	if _, err = tx.ExecContext(ctx, `INSERT INTO use_policies(tenant_id,project_id,name,uid,revision,etag,display_name,state,policy_document_ref_id,create_time,update_time) VALUES($1,$2,$3,$4,1,$5,$6,$7,$8,$9,$9)`, identity.TenantID, identity.ProjectID, name, uid, etag, input.GetDisplayName(), int32(policyv1.UsePolicyState_USE_POLICY_STATE_DRAFT), documentID, at.UTC()); err != nil {
		return nil, false, err
	}
	input.Name, input.Uid, input.Revision, input.Etag = name, uid, 1, etag
	input.TenantId, input.ProjectId = identity.TenantID, identity.ProjectID
	input.State, input.ActiveSnapshot = policyv1.UsePolicyState_USE_POLICY_STATE_DRAFT, nil
	input.CreateTime, input.UpdateTime, input.DeleteTime = timestamppb.New(at.UTC()), timestamppb.New(at.UTC()), nil
	if err = replaceUsePolicyChildren(ctx, tx, identity, input); err != nil {
		return nil, false, err
	}
	row, err := scanUsePolicy(tx.QueryRowContext(ctx, `SELECT `+usePolicyColumns+` FROM use_policies WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name))
	if err != nil {
		return nil, false, err
	}
	created, err := usePolicyProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	target := usePolicyResource(identity, created)
	operation, err := finishPolicyMutation(ctx, tx, identity, "policy.use.create", request.GetContext().GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		return r.Events.PolicyCreated(identity, created, operation, request.GetContext(), at)
	}, "", request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

var mutablePolicyFields = map[string]bool{
	"display_name": true, "permitted_purposes": true, "permitted_capabilities": true,
	"prohibited_capabilities": true, "accepted_classifications": true, "approval_requirements": true,
}

func policyMask(request *internalpolicyv1.UpdateUsePolicyRequest) ([]string, error) {
	if request.GetUpdateMask() == nil || len(request.GetUpdateMask().GetPaths()) == 0 {
		return nil, ErrInvalidArgument
	}
	seen := map[string]bool{}
	result := make([]string, 0, len(request.GetUpdateMask().GetPaths()))
	for _, path := range request.GetUpdateMask().GetPaths() {
		if !mutablePolicyFields[path] || seen[path] {
			return nil, ErrInvalidArgument
		}
		seen[path] = true
		result = append(result, path)
	}
	return result, nil
}

func (r SQLRepository) UpdateUsePolicy(ctx context.Context, identity Identity, request *internalpolicyv1.UpdateUsePolicyRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	paths, err := policyMask(request)
	if request == nil || request.GetContext() == nil || request.GetUsePolicy() == nil || request.GetEtag() == "" || err != nil {
		return nil, false, ErrInvalidArgument
	}
	canonical, err := validateContext(identity, request, request.GetContext(), at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	name, err := policyName(identity, request.GetUsePolicy().GetName())
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, "policy.use.update", request.GetContext().GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	row, err := scanUsePolicy(tx.QueryRowContext(ctx, `SELECT `+usePolicyColumns+` FROM use_policies WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetEtag())) != 1 || (request.GetUsePolicy().GetEtag() != "" && subtle.ConstantTimeCompare([]byte(row.etag), []byte(request.GetUsePolicy().GetEtag())) != 1) {
		return nil, false, ErrRevisionConflict
	}
	if policyv1.UsePolicyState(row.state) == policyv1.UsePolicyState_USE_POLICY_STATE_REVOKED || policyv1.UsePolicyState(row.state) == policyv1.UsePolicyState_USE_POLICY_STATE_ARCHIVED {
		return nil, false, ErrInvalidTransition
	}
	current, err := usePolicyProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	incoming := request.GetUsePolicy()
	for _, path := range paths {
		switch path {
		case "display_name":
			current.DisplayName = incoming.GetDisplayName()
		case "permitted_purposes":
			current.PermittedPurposes = append([]string(nil), incoming.GetPermittedPurposes()...)
		case "permitted_capabilities":
			current.PermittedCapabilities = append([]string(nil), incoming.GetPermittedCapabilities()...)
		case "prohibited_capabilities":
			current.ProhibitedCapabilities = append([]string(nil), incoming.GetProhibitedCapabilities()...)
		case "accepted_classifications":
			current.AcceptedClassifications = append([]string(nil), incoming.GetAcceptedClassifications()...)
		case "approval_requirements":
			current.ApprovalRequirements = cloneSlice(incoming.GetApprovalRequirements())
		}
	}
	if validateUsePolicyInput(current) != nil {
		return nil, false, ErrInvalidArgument
	}
	newRevision := row.revision + 1
	newETag := resourceETag(name, newRevision)
	if _, err = tx.ExecContext(ctx, `UPDATE use_policies SET revision=$4,etag=$5,display_name=$6,update_time=$7 WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name, newRevision, newETag, current.GetDisplayName(), at.UTC()); err != nil {
		return nil, false, err
	}
	current.Revision, current.Etag, current.UpdateTime = newRevision, newETag, timestamppb.New(at.UTC())
	if err = replaceUsePolicyChildren(ctx, tx, identity, current); err != nil {
		return nil, false, err
	}
	target := usePolicyResource(identity, current)
	operation, err := finishPolicyMutation(ctx, tx, identity, "policy.use.update", request.GetContext().GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		return r.Events.PolicyUpdated(identity, current, paths, operation, request.GetContext(), at)
	}, strconv.FormatInt(row.revision, 10), request.GetContext(), at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) GetUsePolicy(ctx context.Context, identity Identity, name string) (*policyv1.UsePolicy, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	canonical, err := policyName(identity, name)
	if err != nil {
		return nil, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	row, err := scanUsePolicy(tx.QueryRowContext(ctx, `SELECT `+usePolicyColumns+` FROM use_policies WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, canonical))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := usePolicyProto(ctx, tx, row)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}

func (r SQLRepository) ListUsePolicies(ctx context.Context, identity Identity, page PolicyPage) ([]*policyv1.UsePolicy, string, time.Time, error) {
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
	query := `SELECT ` + usePolicyColumns + ` FROM use_policies WHERE tenant_id=$1 AND project_id=$2`
	args := []any{identity.TenantID, identity.ProjectID}
	next := 3
	if page.State != policyv1.UsePolicyState_USE_POLICY_STATE_UNSPECIFIED {
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
	var stored []usePolicyRow
	for rows.Next() {
		item, scanErr := scanUsePolicy(rows)
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
	values := make([]*policyv1.UsePolicy, 0, len(stored))
	for _, item := range stored {
		value, mapErr := usePolicyProto(ctx, tx, item)
		if mapErr != nil {
			return nil, "", time.Time{}, mapErr
		}
		values = append(values, clone(value))
	}
	nextToken := ""
	if hasMore && len(stored) > 0 {
		last := stored[len(stored)-1]
		nextToken, err = r.Pagination.encode(pageToken{Kind: "use-policies", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: last.created.UTC().Format(time.RFC3339Nano), AfterName: last.name})
		if err != nil {
			return nil, "", time.Time{}, err
		}
	}
	if err = tx.Commit(); err != nil {
		return nil, "", time.Time{}, err
	}
	return values, nextToken, readAt.UTC(), nil
}

func (r SQLRepository) ActivateUsePolicy(ctx context.Context, identity Identity, request *internalpolicyv1.ActivateUsePolicyRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	return r.transitionUsePolicy(ctx, identity, "policy.use.activate", request.GetContext(), request.GetName(), request.GetEtag(), "", digest, at, true)
}

func (r SQLRepository) RevokeUsePolicy(ctx context.Context, identity Identity, request *internalpolicyv1.RevokeUsePolicyRequest, digest string, at time.Time) (*jobv1.Operation, bool, error) {
	if request == nil || request.GetReasonCode() == "" || len(request.GetReasonCode()) > 128 {
		return nil, false, ErrInvalidArgument
	}
	return r.transitionUsePolicy(ctx, identity, "policy.use.revoke", request.GetContext(), request.GetName(), request.GetEtag(), request.GetReasonCode(), digest, at, false)
}

func (r SQLRepository) transitionUsePolicy(ctx context.Context, identity Identity, action string, command *commonv1.CommandContext, requestedName, etag, reason, digest string, at time.Time, activate bool) (*jobv1.Operation, bool, error) {
	if err := r.validate(); err != nil {
		return nil, false, err
	}
	if command == nil || etag == "" {
		return nil, false, ErrInvalidArgument
	}
	var request proto.Message
	if activate {
		request = &internalpolicyv1.ActivateUsePolicyRequest{Context: clone(command), Name: requestedName, Etag: etag}
	} else {
		request = &internalpolicyv1.RevokeUsePolicyRequest{Context: clone(command), Name: requestedName, Etag: etag, ReasonCode: reason}
	}
	canonical, err := validateContext(identity, request, command, at)
	if err != nil || subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		if err != nil {
			return nil, false, err
		}
		return nil, false, ErrInvalidArgument
	}
	name, err := policyName(identity, requestedName)
	if err != nil {
		return nil, false, err
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, nil)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	operationID, _, replay, err := checkReceipt(ctx, tx, identity, action, command.GetIdempotencyKey(), digest)
	if err != nil {
		return nil, false, err
	}
	if replay {
		operation, loadErr := getOperationTx(ctx, tx, identity, operationID)
		if loadErr != nil {
			return nil, false, loadErr
		}
		if loadErr = tx.Commit(); loadErr != nil {
			return nil, false, loadErr
		}
		return clone(operation), true, nil
	}
	row, err := scanUsePolicy(tx.QueryRowContext(ctx, `SELECT `+usePolicyColumns+` FROM use_policies WHERE tenant_id=$1 AND project_id=$2 AND name=$3 FOR UPDATE`, identity.TenantID, identity.ProjectID, name))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, false, ErrNotFound
	}
	if err != nil {
		return nil, false, err
	}
	if subtle.ConstantTimeCompare([]byte(row.etag), []byte(etag)) != 1 {
		return nil, false, ErrRevisionConflict
	}
	currentState := policyv1.UsePolicyState(row.state)
	if activate {
		if currentState != policyv1.UsePolicyState_USE_POLICY_STATE_DRAFT && currentState != policyv1.UsePolicyState_USE_POLICY_STATE_SUSPENDED {
			return nil, false, ErrInvalidTransition
		}
	} else if currentState == policyv1.UsePolicyState_USE_POLICY_STATE_REVOKED || currentState == policyv1.UsePolicyState_USE_POLICY_STATE_ARCHIVED {
		return nil, false, ErrInvalidTransition
	}
	value, err := usePolicyProto(ctx, tx, row)
	if err != nil {
		return nil, false, err
	}
	newRevision := row.revision + 1
	newETag := resourceETag(name, newRevision)
	var snapshotID sql.NullInt64
	newState := policyv1.UsePolicyState_USE_POLICY_STATE_REVOKED
	if activate {
		newState = policyv1.UsePolicyState_USE_POLICY_STATE_ACTIVE
		snapshotUID, idErr := randomID("snapshot_")
		if idErr != nil {
			return nil, false, idErr
		}
		classification := ""
		if len(value.GetAcceptedClassifications()) > 0 {
			classification = value.GetAcceptedClassifications()[0]
		}
		snapshot := &policyv1.PolicyReference{
			Name: name + "/snapshots/" + strconv.FormatInt(newRevision, 10), Uid: snapshotUID,
			PolicyType: "use-policy", Version: strconv.FormatInt(newRevision, 10), Digest: value.GetPolicyDocument().GetDigest(),
			Document: clone(value.GetPolicyDocument()), ResourceRevision: newRevision,
			EffectiveTime: timestamppb.New(at.UTC()), Classification: classification,
		}
		snapshotID, err = storePolicyReference(ctx, tx, identity.TenantID, snapshot)
		if err != nil {
			return nil, false, err
		}
		value.ActiveSnapshot = snapshot
	}
	var activeSnapshot any
	if snapshotID.Valid {
		activeSnapshot = snapshotID.Int64
	} else if row.snapshotID.Valid {
		activeSnapshot = row.snapshotID.Int64
	}
	if _, err = tx.ExecContext(ctx, `UPDATE use_policies SET revision=$4,etag=$5,state=$6,active_snapshot_id=$7,update_time=$8,revocation_reason_code=$9 WHERE tenant_id=$1 AND project_id=$2 AND name=$3`, identity.TenantID, identity.ProjectID, name, newRevision, newETag, int32(newState), activeSnapshot, at.UTC(), reason); err != nil {
		return nil, false, err
	}
	value.Revision, value.Etag, value.State, value.UpdateTime = newRevision, newETag, newState, timestamppb.New(at.UTC())
	target := usePolicyResource(identity, value)
	operation, err := finishPolicyMutation(ctx, tx, identity, action, command.GetIdempotencyKey(), digest, target, func(operation *jobv1.Operation) (*commonv1.EventEnvelope, error) {
		if activate {
			return r.Events.PolicyActivated(identity, value, operation, command, at)
		}
		return r.Events.PolicyRevoked(identity, value, reason, operation, command, at)
	}, strconv.FormatInt(row.revision, 10), command, at)
	if err != nil {
		return nil, false, err
	}
	if err = tx.Commit(); err != nil {
		return nil, false, err
	}
	return clone(operation), false, nil
}

func (r SQLRepository) ResolvePolicySnapshot(ctx context.Context, identity Identity, name string, effective time.Time) (*policyv1.PolicyReference, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	canonical, err := policyName(identity, name)
	if err != nil || effective.IsZero() {
		return nil, ErrInvalidArgument
	}
	tx, err := platformdb.BeginTenantTx(ctx, r.DB, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	var id int64
	err = tx.QueryRowContext(ctx, `SELECT snapshot.id FROM policy_snapshot_references snapshot JOIN use_policies policy ON policy.tenant_id=snapshot.tenant_id AND policy.project_id=$2 AND snapshot.name LIKE policy.name||'/snapshots/%' WHERE snapshot.tenant_id=$1 AND policy.name=$3 AND snapshot.effective_time <= $4 AND (snapshot.expire_time IS NULL OR snapshot.expire_time > $4) ORDER BY snapshot.effective_time DESC,snapshot.resource_revision DESC LIMIT 1`, identity.TenantID, identity.ProjectID, canonical, effective.UTC()).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	value, err := loadPolicyReference(ctx, tx, identity.TenantID, sql.NullInt64{Int64: id, Valid: true})
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return clone(value), nil
}
