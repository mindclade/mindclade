package workflows

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

const (
	defaultPageSize = 50
	maximumPageSize = 200
)

func validateIdentity(identity Identity) error {
	for label, value := range map[string]string{"tenant": identity.TenantID, "project": identity.ProjectID, "principal": identity.Principal} {
		if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return fmt.Errorf("%w: invalid %s", ErrUnauthenticated, label)
		}
	}
	return nil
}

func requireRole(identity Identity, roles ...string) error {
	if identity.HasAnyRole(roles...) {
		return nil
	}
	return ErrPermissionDenied
}

func canonicalDigest(command proto.Message) (string, error) {
	if command == nil {
		return "", ErrInvalidArgument
	}
	copy := proto.Clone(command)
	message := copy.ProtoReflect()
	field := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if field != nil && field.Kind() == protoreflect.MessageKind {
		message.Clear(field)
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", fmt.Errorf("canonicalize workflow command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" || now.IsZero() {
		return "", fmt.Errorf("%w: context, request_id, and idempotency_key are required", ErrInvalidArgument)
	}
	for label, item := range map[string]string{"request_id": value.GetRequestId(), "idempotency_key": value.GetIdempotencyKey()} {
		if len(item) > 255 || strings.TrimSpace(item) != item || strings.ContainsAny(item, "\x00\r\n") {
			return "", fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
		}
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID || value.GetPrincipalId() != "" && value.GetPrincipalId() != identity.Principal {
		return "", ErrPermissionDenied
	}
	if deadline := value.GetDeadline(); deadline != nil {
		if deadline.CheckValid() != nil {
			return "", ErrInvalidArgument
		}
		if !now.Before(deadline.AsTime()) {
			return "", ErrDeadlineExceeded
		}
	}
	digest, err := canonicalDigest(command)
	if err != nil {
		return "", err
	}
	if supplied := value.GetCanonicalRequestDigest(); supplied != "" && subtle.ConstantTimeCompare([]byte(supplied), []byte(digest)) != 1 {
		return "", fmt.Errorf("%w: canonical request digest mismatch", ErrInvalidArgument)
	}
	// Persist and emit only authenticated scope. Callers operate on a cloned
	// request, so normalizing the context here cannot mutate caller-owned state.
	value.TenantId = identity.TenantID
	value.ProjectId = identity.ProjectID
	value.PrincipalId = identity.Principal
	value.CanonicalRequestDigest = digest
	return digest, nil
}

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validID(value string) bool {
	if value == "" || len(value) > 128 {
		return false
	}
	for index, character := range value {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || index > 0 && strings.ContainsRune("._~-", character) {
			continue
		}
		return false
	}
	return true
}

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func definitionName(identity Identity, id string) string {
	return projectParent(identity) + "/workflowDefinitions/" + id
}

func runName(identity Identity, id string) string {
	return projectParent(identity) + "/workflowRuns/" + id
}

func approvalName(identity Identity, id string) string {
	return projectParent(identity) + "/approvalRequests/" + id
}

func approvalReceiptName(identity Identity, id string) string {
	return projectParent(identity) + "/approvalReceipts/" + id
}

func canonicalScopedName(identity Identity, name, collection string) (string, error) {
	prefix := projectParent(identity) + "/" + collection + "/"
	if !strings.HasPrefix(name, prefix) || !validID(strings.TrimPrefix(name, prefix)) {
		return "", ErrPermissionDenied
	}
	return name, nil
}

func validateArtifact(value *artifactv1.ArtifactRef, label string, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: %s is required", ErrInvalidArgument, label)
		}
		return nil
	}
	if !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 || value.GetSizeBytes() > 1<<50 || value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest()) || len(value.GetUri()) > 8192 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateReference(identity Identity, value *commonv1.ResourceRef, label string, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: %s is required", ErrInvalidArgument, label)
		}
		return nil
	}
	if value.GetResourceType() == "" || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 || len(value.GetName()) > 2048 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validatePolicy(value *policyv1.PolicyReference) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" || !validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil {
		return fmt.Errorf("%w: invalid policy snapshot", ErrInvalidArgument)
	}
	return validateArtifact(value.GetDocument(), "policy document", true)
}

func validateAuthorization(identity Identity, value *policyv1.AuthorizationDecision, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: authorization decision is required", ErrInvalidArgument)
		}
		return nil
	}
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetName() == "" || value.GetUid() == "" || value.GetPrincipalRef() == "" || value.GetAction() == "" || value.GetOutcome() == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_UNSPECIFIED || value.GetReasonCode() == "" || !validSHA256(value.GetIntentDigest()) || !validSHA256(value.GetContextDigest()) || !validSHA256(value.GetDecisionDigest()) || value.GetEvaluatedAt() == nil || value.GetEvaluatedAt().CheckValid() != nil || len(value.GetPolicies()) == 0 || len(value.GetPolicies()) > 64 {
		return ErrInvalidArgument
	}
	return validateReference(identity, value.GetResource(), "authorization resource", true)
}

func validateFence(identity Identity, value *jobv1.LeaseFence, now time.Time) error {
	if value == nil || identity.WorkerID == "" || identity.LeaseToken == "" || value.GetJobId() == "" || value.GetRunId() == "" || value.GetAttemptId() == "" || value.GetLeaseEpoch() == 0 || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !now.Before(value.GetDeadline().AsTime()) {
		return ErrStaleFence
	}
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validateWorkflowDefinition(identity Identity, value *workflowv1.WorkflowDefinition) error {
	if value == nil || value.GetDisplayName() == "" || value.GetSemanticVersion() == "" || value.GetState() == workflowv1.WorkflowDefinitionState_WORKFLOW_DEFINITION_STATE_UNSPECIFIED || !validSHA256(value.GetResolvedGraphDigest()) || value.GetLimits() == nil || value.GetLimits().GetMaximumIterations() == 0 || value.GetLimits().GetMaximumFanOut() == 0 || value.GetLimits().GetMaximumParallelNodes() == 0 || value.GetLimits().GetMaximumWallTime() == nil || value.GetLimits().GetMaximumWallTime().CheckValid() != nil || value.GetLimits().GetMaximumWallTime().AsDuration() <= 0 || len(value.GetEligibleTools()) > 256 || len(value.GetPolicySnapshots()) > 64 {
		return ErrInvalidArgument
	}
	if err := validateArtifact(value.GetDefinition(), "workflow definition", true); err != nil {
		return err
	}
	if err := validateArtifact(value.GetInputSchema(), "input schema", false); err != nil {
		return err
	}
	if err := validateArtifact(value.GetOutputSchema(), "output schema", false); err != nil {
		return err
	}
	for _, tool := range value.GetEligibleTools() {
		if err := validateReference(identity, tool, "eligible tool", true); err != nil {
			return err
		}
	}
	for _, policy := range value.GetPolicySnapshots() {
		if err := validatePolicy(policy); err != nil {
			return err
		}
	}
	return nil
}

func validateStartRun(identity Identity, request *internalworkflowv1.StartWorkflowRunRequest, now time.Time) error {
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetWorkflowRunId()) || request.GetWorkflowRun() == nil {
		return ErrInvalidArgument
	}
	value := request.GetWorkflowRun()
	if now.IsZero() || value.GetName() != "" || value.GetUid() != "" || value.GetRevision() != 0 || value.GetEtag() != "" || value.GetTenantId() != "" || value.GetProjectId() != "" || value.GetState() != workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_UNSPECIFIED || len(value.GetActiveNodeIds()) != 0 || value.GetCompletedNodeCount() != 0 || value.GetIterationCount() != 0 || value.GetTransitionSequence() != 0 || value.GetAttemptId() != "" || value.GetLeaseEpoch() != 0 || value.GetOutput() != nil || value.GetReplayState() != nil || value.GetDecisionLog() != nil || value.GetFailure() != nil || value.GetCreateTime() != nil || value.GetUpdateTime() != nil || value.GetEndTime() != nil || !validSHA256(value.GetDefinitionDigest()) {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetDefinition(), "workflow definition", true); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetAgentRun(), "agent run", false); err != nil {
		return err
	}
	if err := validateArtifact(value.GetInput(), "workflow input", false); err != nil {
		return err
	}
	if err := validateAuthorization(identity, value.GetAdmissionDecision(), false); err != nil {
		return err
	}
	if decision := value.GetAdmissionDecision(); decision != nil {
		if decision.GetOutcome() != policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_ALLOW || decision.GetExpireTime() != nil && !decision.GetExpireTime().AsTime().After(now) {
			return ErrPermissionDenied
		}
	}
	return nil
}

func validateApproval(identity Identity, value *workflowv1.ApprovalRequest, creating bool) error {
	if value == nil || value.GetContext() == nil || value.GetBinding() == nil || value.GetRequestedByPrincipalRef() != identity.Principal || value.GetMinimumIndependentApprovers() == 0 || value.GetMinimumIndependentApprovers() > 32 || value.GetReusePolicy() == workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_UNSPECIFIED || value.GetState() != workflowv1.ApprovalState_APPROVAL_STATE_UNSPECIFIED && creating || value.GetExpireTime() == nil || value.GetExpireTime().CheckValid() != nil || len(value.GetPolicyDecisions()) == 0 || len(value.GetPolicyDecisions()) > 64 {
		return ErrInvalidArgument
	}
	binding := value.GetBinding()
	if binding.GetAction() == "" || !validSHA256(binding.GetIntentDigest()) || !validSHA256(binding.GetParametersDigest()) || !validSHA256(binding.GetBindingDigest()) || binding.GetRiskClass() == "" || len(binding.GetInputArtifacts()) > 256 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, binding.GetTool(), "approval tool", false); err != nil {
		return err
	}
	if (binding.GetTool() == nil) != (binding.GetToolVersion() == "") {
		return ErrInvalidArgument
	}
	if err := validatePolicy(binding.GetPolicySnapshot()); err != nil {
		return err
	}
	for _, artifact := range binding.GetInputArtifacts() {
		if err := validateArtifact(artifact, "approval input artifact", true); err != nil {
			return err
		}
	}
	for _, decision := range value.GetPolicyDecisions() {
		if err := validateAuthorization(identity, decision, true); err != nil {
			return err
		}
	}
	digest, err := canonicalBindingDigest(binding)
	if err != nil || subtle.ConstantTimeCompare([]byte(digest), []byte(binding.GetBindingDigest())) != 1 {
		return fmt.Errorf("%w: approval binding digest mismatch", ErrInvalidArgument)
	}
	return nil
}

func canonicalBindingDigest(value *workflowv1.ApprovalBinding) (string, error) {
	if value == nil {
		return "", ErrInvalidArgument
	}
	copy := clone(value)
	copy.BindingDigest = ""
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func pageLimit(requested uint32) (int, error) {
	if requested == 0 {
		return defaultPageSize, nil
	}
	if requested > maximumPageSize {
		return 0, fmt.Errorf("%w: page_size exceeds %d", ErrInvalidArgument, maximumPageSize)
	}
	return int(requested), nil
}
