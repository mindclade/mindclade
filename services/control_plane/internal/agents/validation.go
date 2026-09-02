package agents

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
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
		return "", fmt.Errorf("canonicalize agent command: %w", err)
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
		if deadline.CheckValid() != nil || !microsecondExact(deadline.AsTime()) {
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
	return projectParent(identity) + "/agentDefinitions/" + id
}

func runName(identity Identity, id string) string {
	return projectParent(identity) + "/agentRuns/" + id
}

func stepName(run string, sequence uint64) string {
	return run + "/agentSteps/" + strconv.FormatUint(sequence, 10)
}

func canonicalScopedName(identity Identity, name, collection string) (string, error) {
	prefix := projectParent(identity) + "/" + collection + "/"
	if !strings.HasPrefix(name, prefix) || !validID(strings.TrimPrefix(name, prefix)) {
		return "", ErrPermissionDenied
	}
	return name, nil
}

func canonicalStepName(identity Identity, name string) (string, error) {
	prefix := projectParent(identity) + "/agentRuns/"
	if !strings.HasPrefix(name, prefix) {
		return "", ErrPermissionDenied
	}
	parts := strings.Split(strings.TrimPrefix(name, prefix), "/")
	if len(parts) != 3 || !validID(parts[0]) || parts[1] != "agentSteps" || !validID(parts[2]) {
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
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" || !validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil || !microsecondExact(value.GetEffectiveTime().AsTime()) {
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
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetName() == "" || value.GetUid() == "" || value.GetPrincipalRef() == "" || value.GetAction() == "" || value.GetOutcome() == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_UNSPECIFIED || value.GetReasonCode() == "" || !validSHA256(value.GetIntentDigest()) || !validSHA256(value.GetContextDigest()) || !validSHA256(value.GetDecisionDigest()) || value.GetEvaluatedAt() == nil || value.GetEvaluatedAt().CheckValid() != nil || !microsecondExact(value.GetEvaluatedAt().AsTime()) || len(value.GetPolicies()) == 0 || len(value.GetPolicies()) > 64 {
		return ErrInvalidArgument
	}
	return validateReference(identity, value.GetResource(), "authorization resource", true)
}

func validateAuthorizationAt(value *policyv1.AuthorizationDecision, at time.Time) error {
	if value == nil || value.GetEvaluatedAt() == nil || value.GetEvaluatedAt().AsTime().After(at) || value.GetExpireTime() != nil && !at.Before(value.GetExpireTime().AsTime()) {
		return ErrPermissionDenied
	}
	for _, policy := range value.GetPolicies() {
		if policy.GetEffectiveTime() == nil || policy.GetEffectiveTime().AsTime().After(at) || policy.GetExpireTime() != nil && !at.Before(policy.GetExpireTime().AsTime()) {
			return ErrPermissionDenied
		}
	}
	return nil
}

func validateFence(identity Identity, value *jobv1.LeaseFence, now time.Time) error {
	if value == nil || identity.WorkerID == "" || identity.LeaseToken == "" || value.GetJobId() == "" || value.GetRunId() == "" || value.GetAttemptId() == "" || value.GetLeaseEpoch() == 0 || value.GetLeaseEpoch() > math.MaxInt64 || !validSHA256(value.GetLeaseTokenDigest()) || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !microsecondExact(value.GetDeadline().AsTime()) || !now.Before(value.GetDeadline().AsTime()) {
		return ErrStaleFence
	}
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validateDefinition(identity Identity, value *agentv1.AgentDefinition, creating bool) error {
	if value == nil || value.GetDisplayName() == "" || value.GetSemanticVersion() == "" || value.GetState() == agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_UNSPECIFIED || value.GetPurpose() == "" || value.GetModelCapability() == "" || value.GetQualificationLevel() == "" || value.GetBudget() == nil || value.GetLimits() == nil || len(value.GetNonGoals()) > 128 || len(value.GetEligibleTools()) == 0 || len(value.GetEligibleTools()) > 256 || len(value.GetPolicySnapshots()) == 0 || len(value.GetPolicySnapshots()) > 64 {
		return ErrInvalidArgument
	}
	if creating && (value.GetName() != "" || value.GetUid() != "" || value.GetRevision() != 0 || value.GetEtag() != "" || value.GetTenantId() != "" || value.GetProjectId() != "" || value.GetCreateTime() != nil || value.GetUpdateTime() != nil || value.GetDeleteTime() != nil) {
		return ErrInvalidArgument
	}
	budget := value.GetBudget()
	if budget.GetMaximumModelTokens() == 0 || budget.GetMaximumModelTokens() > math.MaxInt64 || budget.GetMaximumIterations() == 0 || budget.GetMaximumToolCalls() == 0 || budget.GetMaximumConcurrentBranches() == 0 || budget.GetMaximumStorageBytes() == 0 || budget.GetMaximumStorageBytes() > math.MaxInt64 || budget.GetMaximumExternalSpendMicros() > math.MaxInt64 || budget.GetMaximumWallTime() == nil || budget.GetMaximumWallTime().CheckValid() != nil || budget.GetMaximumWallTime().AsDuration() <= 0 || budget.GetMaximumAcceleratorTime() == nil || budget.GetMaximumAcceleratorTime().CheckValid() != nil || budget.GetMaximumAcceleratorTime().AsDuration() < 0 || budget.GetMaximumCpuTime() == nil || budget.GetMaximumCpuTime().CheckValid() != nil || budget.GetMaximumCpuTime().AsDuration() < 0 {
		return ErrInvalidArgument
	}
	limits := value.GetLimits()
	if limits.GetMaximumDepth() == 0 || limits.GetMaximumFanOut() == 0 || limits.GetMaximumObservationsPerStep() == 0 || limits.GetMaximumArtifactReferencesPerCall() == 0 {
		return ErrInvalidArgument
	}
	if err := validateArtifact(value.GetDefinition(), "agent definition", true); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetWorkflowDefinition(), "workflow definition", true); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetEvaluationSuite(), "evaluation suite", true); err != nil {
		return err
	}
	if err := validateArtifact(value.GetInputSchema(), "input schema", false); err != nil {
		return err
	}
	if err := validateArtifact(value.GetOutputSchema(), "output schema", false); err != nil {
		return err
	}
	seen := make(map[string]struct{}, len(value.GetNonGoals()))
	for _, item := range value.GetNonGoals() {
		if item == "" || len(item) > 1024 {
			return ErrInvalidArgument
		}
		if _, ok := seen[item]; ok {
			return ErrInvalidArgument
		}
		seen[item] = struct{}{}
	}
	seen = make(map[string]struct{}, len(value.GetEligibleTools()))
	for _, ref := range value.GetEligibleTools() {
		if err := validateReference(identity, ref, "eligible tool", true); err != nil {
			return err
		}
		key := ref.GetName() + "\x00" + strconv.FormatInt(ref.GetResourceVersion(), 10)
		if _, ok := seen[key]; ok {
			return ErrInvalidArgument
		}
		seen[key] = struct{}{}
	}
	seen = make(map[string]struct{}, len(value.GetPolicySnapshots()))
	for _, policy := range value.GetPolicySnapshots() {
		if err := validatePolicy(policy); err != nil {
			return err
		}
		key := policy.GetName() + "\x00" + strconv.FormatInt(policy.GetResourceRevision(), 10) + "\x00" + policy.GetDigest()
		if _, ok := seen[key]; ok {
			return ErrInvalidArgument
		}
		seen[key] = struct{}{}
	}
	return nil
}

func validateStartRun(identity Identity, request *internalagentv1.StartAgentRunRequest) error {
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetAgentRunId()) || request.GetAgentRun() == nil {
		return ErrInvalidArgument
	}
	value := request.GetAgentRun()
	if value.GetName() != "" || value.GetUid() != "" || value.GetRevision() != 0 || value.GetEtag() != "" || value.GetTenantId() != "" || value.GetProjectId() != "" || value.GetState() != agentv1.AgentRunState_AGENT_RUN_STATE_UNSPECIFIED || value.GetActiveStepName() != "" || value.GetNextStepSequence() != 0 || value.GetAttemptId() != "" || value.GetLeaseEpoch() != 0 || value.GetCancellationRequested() || value.GetRunManifest() != nil || value.GetOutput() != nil || value.GetFailure() != nil || value.GetCreateTime() != nil || value.GetUpdateTime() != nil || value.GetEndTime() != nil || !validSHA256(value.GetDefinitionDigest()) || len(value.GetPolicySnapshots()) == 0 || len(value.GetPolicySnapshots()) > 64 || value.GetBudgetUsage() != nil && !proto.Equal(value.GetBudgetUsage(), &agentv1.AgentBudgetUsage{}) {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetDefinition(), "agent definition", true); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetWorkflowRun(), "workflow run", false); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetBudgetReservation(), "budget reservation", true); err != nil {
		return err
	}
	if err := validateArtifact(value.GetInput(), "agent input", false); err != nil {
		return err
	}
	if err := validateArtifact(value.GetModelProviderManifest(), "model provider manifest", true); err != nil {
		return err
	}
	for _, policy := range value.GetPolicySnapshots() {
		if err := validatePolicy(policy); err != nil {
			return err
		}
	}
	return nil
}

func validateStep(identity Identity, value *agentv1.AgentStep) error {
	if value == nil || value.GetRun() == nil || value.GetSequence() == 0 || value.GetSequence() > math.MaxInt64 || value.GetKind() == agentv1.AgentStepKind_AGENT_STEP_KIND_UNSPECIFIED || value.GetState() == agentv1.AgentStepState_AGENT_STEP_STATE_UNSPECIFIED || value.GetName() != "" || value.GetUid() != "" || value.GetRevision() != 0 || value.GetEtag() != "" || value.GetAttemptId() != "" || value.GetLeaseEpoch() != 0 || value.GetCreateTime() != nil || value.GetUpdateTime() != nil || value.GetEndTime() != nil || len(value.GetPolicyDecisions()) > 128 || len(value.GetObservations()) > 256 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetRun(), "agent run", true); err != nil {
		return err
	}
	switch value.GetState() {
	case agentv1.AgentStepState_AGENT_STEP_STATE_WAITING,
		agentv1.AgentStepState_AGENT_STEP_STATE_SUCCEEDED,
		agentv1.AgentStepState_AGENT_STEP_STATE_FAILED,
		agentv1.AgentStepState_AGENT_STEP_STATE_CANCELLED,
		agentv1.AgentStepState_AGENT_STEP_STATE_EXPIRED:
	default:
		return ErrInvalidArgument
	}
	if value.GetState() == agentv1.AgentStepState_AGENT_STEP_STATE_FAILED && value.GetFailure() == nil || value.GetState() != agentv1.AgentStepState_AGENT_STEP_STATE_FAILED && value.GetFailure() != nil {
		return ErrInvalidArgument
	}
	for _, decision := range value.GetPolicyDecisions() {
		if err := validateAuthorization(identity, decision, true); err != nil {
			return err
		}
	}
	for _, artifact := range value.GetObservations() {
		if err := validateArtifact(artifact, "step observation", true); err != nil {
			return err
		}
	}
	if err := validateDecision(identity, value.GetDecision()); err != nil {
		return err
	}
	if !stepKindMatchesDecision(value.GetKind(), value.GetDecision()) {
		return ErrInvalidArgument
	}
	if value.GetKind() == agentv1.AgentStepKind_AGENT_STEP_KIND_TERMINAL && value.GetState() == agentv1.AgentStepState_AGENT_STEP_STATE_SUCCEEDED && value.GetOutput() == nil {
		return fmt.Errorf("%w: terminal success requires an AgentRunManifest artifact in step.output", ErrInvalidArgument)
	}
	if err := validateArtifact(value.GetOutput(), "step output", false); err != nil {
		return err
	}
	return validateError(value.GetFailure(), false)
}

func validateDecision(identity Identity, value *agentv1.AgentDecision) error {
	if value == nil || value.GetDecisionId() == "" || value.GetDecisionType() == "" || value.GetRationaleSummary() == "" || len(value.GetRationaleSummary()) > 4096 || !validSHA256(value.GetReplayDigest()) || len(value.GetEvidence()) > 256 {
		return ErrInvalidArgument
	}
	for _, evidence := range value.GetEvidence() {
		if err := validateArtifact(evidence, "decision evidence", true); err != nil {
			return err
		}
	}
	switch action := value.GetNextAction().(type) {
	case *agentv1.AgentDecision_ToolCall:
		return validateToolCall(identity, action.ToolCall)
	case *agentv1.AgentDecision_DomainJob:
		return validateReference(identity, action.DomainJob, "domain job", true)
	case *agentv1.AgentDecision_ApprovalRequest:
		return validateReference(identity, action.ApprovalRequest, "approval request", true)
	case *agentv1.AgentDecision_Wait:
		if action.Wait == nil || action.Wait.GetMaximumDuration() == nil || action.Wait.GetMaximumDuration().CheckValid() != nil || action.Wait.GetMaximumDuration().AsDuration() <= 0 || action.Wait.GetCorrelationRef() == "" {
			return ErrInvalidArgument
		}
	case *agentv1.AgentDecision_TerminalResult:
		return validateArtifact(action.TerminalResult, "terminal result", true)
	default:
		return ErrInvalidArgument
	}
	return nil
}

func validateToolCall(identity Identity, value *agentv1.ToolCall) error {
	if value == nil || value.GetContext() == nil || value.GetContext().GetRequestId() == "" || value.GetContext().GetIdempotencyKey() == "" || value.GetContext().GetPrincipalId() != identity.Principal || value.GetContext().GetTenantId() != identity.TenantID || value.GetContext().GetProjectId() != identity.ProjectID || !validSHA256(value.GetContext().GetCanonicalRequestDigest()) || value.GetCallId() == "" || value.GetAgentRunName() == "" || value.GetAgentStepName() == "" || value.GetToolVersion() == "" || !validSHA256(value.GetInputDigest()) || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !microsecondExact(value.GetDeadline().AsTime()) || value.GetSideEffectClass() == "" || value.GetOutputClassification() == "" || len(value.GetInputArtifacts()) > 256 || len(value.GetApprovals()) > 32 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetTool(), "tool", true); err != nil {
		return err
	}
	if err := validateAuthorization(identity, value.GetAuthorization(), true); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetBudgetReservation(), "budget reservation", true); err != nil {
		return err
	}
	if err := validateArtifact(value.GetParameters(), "tool parameters", false); err != nil {
		return err
	}
	if err := validateArtifact(value.GetExpectedOutputSchema(), "expected output schema", true); err != nil {
		return err
	}
	for _, artifact := range value.GetInputArtifacts() {
		if err := validateArtifact(artifact, "tool input", true); err != nil {
			return err
		}
	}
	for _, approval := range value.GetApprovals() {
		if approval == nil || approval.GetName() == "" || approval.GetBinding() == nil || approval.GetDecision() == workflowv1.ApprovalDecisionValue_APPROVAL_DECISION_VALUE_UNSPECIFIED || approval.GetReceiptDigest() == "" {
			return ErrInvalidArgument
		}
	}
	return nil
}

func validateToolReceipt(identity Identity, value *agentv1.ToolReceipt) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetCallId() == "" || value.GetAgentRunName() == "" || value.GetAgentStepName() == "" || value.GetToolVersion() == "" || value.GetAttemptId() == "" || value.GetLeaseEpoch() == 0 || value.GetLeaseEpoch() > math.MaxInt64 || value.GetIdempotencyKey() == "" || !validSHA256(value.GetInputDigest()) || !validSHA256(value.GetExpectedOutputSchemaDigest()) || value.GetOutcome() == agentv1.ToolExecutionOutcome_TOOL_EXECUTION_OUTCOME_UNSPECIFIED || value.GetSideEffectState() == agentv1.ToolSideEffectState_TOOL_SIDE_EFFECT_STATE_UNSPECIFIED || !validSHA256(value.GetOutputDigest()) || value.GetUsage() == nil || value.GetUsage().GetInputBytes() > math.MaxInt64 || value.GetUsage().GetOutputBytes() > math.MaxInt64 || value.GetUsage().GetCpuMilliseconds() > math.MaxInt64 || value.GetUsage().GetAcceleratorMilliseconds() > math.MaxInt64 || value.GetUsage().GetExternalSpendMicros() > math.MaxInt64 || value.GetUsage().GetInputBytes() > math.MaxInt64-value.GetUsage().GetOutputBytes() || value.GetStartedAt() == nil || value.GetStartedAt().CheckValid() != nil || !microsecondExact(value.GetStartedAt().AsTime()) || value.GetCompletedAt() == nil || value.GetCompletedAt().CheckValid() != nil || !microsecondExact(value.GetCompletedAt().AsTime()) || value.GetCompletedAt().AsTime().Before(value.GetStartedAt().AsTime()) || value.GetExecutorIdentity() == "" || value.GetSourceRevision() == "" || !validSHA256(value.GetReceiptDigest()) || len(value.GetApprovalReceipts()) > 32 || len(value.GetOutputs()) > 256 {
		return ErrInvalidArgument
	}
	if _, err := canonicalScopedName(identity, value.GetAgentRunName(), "agentRuns"); err != nil {
		return err
	}
	if _, err := canonicalScopedName(identity, value.GetName(), "toolReceipts"); err != nil {
		return err
	}
	if _, err := canonicalStepName(identity, value.GetAgentStepName()); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetTool(), "tool", true); err != nil {
		return err
	}
	if err := validateAuthorization(identity, value.GetAuthorization(), true); err != nil {
		return err
	}
	for _, receipt := range value.GetApprovalReceipts() {
		if err := validateReference(identity, receipt, "approval receipt", true); err != nil {
			return err
		}
	}
	for _, output := range value.GetOutputs() {
		if err := validateArtifact(output, "tool output", true); err != nil {
			return err
		}
	}
	if err := validateArtifact(value.GetReconciliationEvidence(), "reconciliation evidence", false); err != nil {
		return err
	}
	return validateError(value.GetFailure(), false)
}

func validateError(value *commonv1.ErrorDetail, required bool) error {
	if value == nil {
		if required {
			return ErrInvalidArgument
		}
		return nil
	}
	if value.GetCode() == commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED || len(value.GetFieldViolations()) > 128 || len(value.GetPreconditionViolations()) > 128 {
		return ErrInvalidArgument
	}
	return nil
}

func microsecondExact(value time.Time) bool { return value.Nanosecond()%1000 == 0 }

func stepKindMatchesDecision(kind agentv1.AgentStepKind, decision *agentv1.AgentDecision) bool {
	if decision == nil {
		return false
	}
	switch decision.GetNextAction().(type) {
	case *agentv1.AgentDecision_ToolCall:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_TOOL
	case *agentv1.AgentDecision_DomainJob:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_DOMAIN_JOB
	case *agentv1.AgentDecision_ApprovalRequest:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_APPROVAL
	case *agentv1.AgentDecision_Wait:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_WAIT
	case *agentv1.AgentDecision_TerminalResult:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_TERMINAL
	default:
		return kind == agentv1.AgentStepKind_AGENT_STEP_KIND_DECISION
	}
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

func normalizeDefinitionOrder(value string) (string, error) {
	if value == "" || value == "create_time desc, name desc" {
		return "create_time desc, name desc", nil
	}
	return "", ErrInvalidArgument
}

func normalizeRunOrder(value string) (string, error) {
	if value == "" || value == "create_time desc, name desc" {
		return "create_time desc, name desc", nil
	}
	return "", ErrInvalidArgument
}

func parseDefinitionFilter(value string) (agentv1.AgentDefinitionState, error) {
	if value == "" {
		return agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_UNSPECIFIED, nil
	}
	prefix := "state = "
	if !strings.HasPrefix(value, prefix) {
		return 0, ErrInvalidArgument
	}
	needle := strings.TrimSpace(strings.TrimPrefix(value, prefix))
	for number := agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_DRAFT; number <= agentv1.AgentDefinitionState_AGENT_DEFINITION_STATE_ARCHIVED; number++ {
		if number.String() == needle {
			return number, nil
		}
	}
	return 0, ErrInvalidArgument
}

func parseRunFilter(value string) (agentv1.AgentRunState, error) {
	if value == "" {
		return agentv1.AgentRunState_AGENT_RUN_STATE_UNSPECIFIED, nil
	}
	prefix := "state = "
	if !strings.HasPrefix(value, prefix) {
		return 0, ErrInvalidArgument
	}
	needle := strings.TrimSpace(strings.TrimPrefix(value, prefix))
	for number := agentv1.AgentRunState_AGENT_RUN_STATE_CREATED; number <= agentv1.AgentRunState_AGENT_RUN_STATE_EXPIRED; number++ {
		if number.String() == needle {
			return number, nil
		}
	}
	return 0, ErrInvalidArgument
}
