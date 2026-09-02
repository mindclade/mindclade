package inference

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"math"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

const (
	maximumInlineBytes      = 1 << 20
	maximumCandidates       = 256
	maximumPolicySnapshots  = 64
	maximumSafetyDecisions  = 128
	maximumOutputKinds      = 64
	operationWatchBatchSize = 64
)

func validateIdentity(identity Identity) error {
	for label, value := range map[string]string{"tenant": identity.TenantID, "project": identity.ProjectID, "principal": identity.Principal} {
		if !validBoundedString(value, 255) {
			return fmt.Errorf("%w: invalid %s", ErrUnauthenticated, label)
		}
	}
	return nil
}

func validBoundedString(value string, limit int) bool {
	return value != "" && len(value) <= limit && strings.TrimSpace(value) == value && !strings.ContainsAny(value, "\x00\r\n")
}

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	decoded, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil && len(decoded) == sha256.Size
}

func canonicalDigest(message proto.Message) (string, error) {
	if message == nil {
		return "", ErrInvalidArgument
	}
	copy := proto.Clone(message)
	reflection := copy.ProtoReflect()
	if contextField := reflection.Descriptor().Fields().ByName(protoreflect.Name("context")); contextField != nil && contextField.Kind() == protoreflect.MessageKind {
		reflection.Clear(contextField)
	}
	// InferenceRequest owns its command context directly.
	if request, ok := copy.(*inferencev1.InferenceRequest); ok {
		request.Context = nil
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", fmt.Errorf("canonicalize inference command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || !validBoundedString(value.GetRequestId(), 255) || !validBoundedString(value.GetIdempotencyKey(), 255) || now.IsZero() {
		return "", ErrInvalidArgument
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID || value.GetPrincipalId() != "" && value.GetPrincipalId() != identity.Principal {
		return "", ErrPermissionDenied
	}
	for _, item := range []string{value.GetTraceId(), value.GetCorrelationId(), value.GetCausationId(), value.GetCancellationTokenId()} {
		if item != "" && (!validBoundedString(item, 255)) {
			return "", ErrInvalidArgument
		}
	}
	if deadline := value.GetDeadline(); deadline != nil {
		if deadline.CheckValid() != nil {
			return "", ErrInvalidArgument
		}
		if !now.UTC().Before(deadline.AsTime().UTC()) {
			return "", ErrDeadlineExceeded
		}
	}
	digest, err := canonicalDigest(command)
	if err != nil {
		return "", err
	}
	if supplied := value.GetCanonicalRequestDigest(); supplied != "" && subtle.ConstantTimeCompare([]byte(supplied), []byte(digest)) != 1 {
		return "", ErrInvalidArgument
	}
	return digest, nil
}

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func canonicalName(identity Identity, name, collection string) (string, error) {
	prefix := projectParent(identity) + "/" + collection + "/"
	id := strings.TrimPrefix(name, prefix)
	if id == name || !validID(id) {
		return "", ErrPermissionDenied
	}
	return name, nil
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

func operationID(name string) (string, error) {
	if !strings.HasPrefix(name, "operations/") || !validID(strings.TrimPrefix(name, "operations/")) {
		return "", ErrInvalidArgument
	}
	return name, nil
}

func validateArtifact(value *artifactv1.ArtifactRef, required bool) error {
	if value == nil {
		if required {
			return ErrInvalidArgument
		}
		return nil
	}
	if !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 || value.GetSizeBytes() > 1<<50 || value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest()) || len(value.GetUri()) > 8192 {
		return ErrInvalidArgument
	}
	return nil
}

func validateReference(identity Identity, value *commonv1.ResourceRef, resourceType string) error {
	if value == nil || value.GetResourceType() == "" || resourceType != "" && value.GetResourceType() != resourceType || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 || len(value.GetName()) > 2048 {
		return ErrInvalidArgument
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validatePolicy(value *policyv1.PolicyReference) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" || !validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil || validateArtifact(value.GetDocument(), true) != nil {
		return ErrInvalidArgument
	}
	if expiry := value.GetExpireTime(); expiry != nil && (expiry.CheckValid() != nil || !expiry.AsTime().After(value.GetEffectiveTime().AsTime())) {
		return ErrInvalidArgument
	}
	return nil
}

func validateInferenceRequest(identity Identity, value *inferencev1.InferenceRequest, now time.Time) error {
	if value == nil || value.GetContext() == nil || value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetUid() == "" || value.GetCapability() == "" || value.GetMode() == inferencev1.InferenceMode_INFERENCE_MODE_UNSPECIFIED || value.GetReproducibility() == inferencev1.ReproducibilityIntent_REPRODUCIBILITY_INTENT_UNSPECIFIED || value.GetResourceClass() == "" || value.GetDataClassification() == "" {
		return ErrInvalidArgument
	}
	if _, err := canonicalName(identity, value.GetName(), "inferenceRequests"); err != nil {
		return err
	}
	if err := validateReference(identity, value.GetModel(), ""); err != nil {
		return err
	}
	for _, artifact := range []*artifactv1.ArtifactRef{value.GetResolvedModelBundle(), value.GetFeaturePolicy(), value.GetConfidencePolicy()} {
		if err := validateArtifact(artifact, true); err != nil {
			return err
		}
	}
	switch input := value.GetInput().(type) {
	case *inferencev1.InferenceRequest_InputArtifact:
		if err := validateArtifact(input.InputArtifact, true); err != nil {
			return err
		}
	case *inferencev1.InferenceRequest_InlineInput:
		if input.InlineInput == nil || input.InlineInput.GetMediaType() == "" || input.InlineInput.GetSchemaId() == "" || len(input.InlineInput.GetPayload()) > maximumInlineBytes || !validSHA256(input.InlineInput.GetContentDigest()) {
			return ErrInvalidArgument
		}
		digest := sha256.Sum256(input.InlineInput.GetPayload())
		if subtle.ConstantTimeCompare([]byte(input.InlineInput.GetContentDigest()), []byte("sha256:"+hex.EncodeToString(digest[:]))) != 1 {
			return ErrInvalidArgument
		}
	default:
		return ErrInvalidArgument
	}
	policy := value.GetSamplingPolicy()
	if policy == nil || policy.GetAlgorithm() == "" || policy.GetAlgorithmVersion() == "" || policy.GetCandidateCount() == 0 || policy.GetCandidateCount() > maximumCandidates || policy.GetMaximumSteps() == 0 || policy.GetRandomKey() == "" || policy.GetMaximumComputeTime() == nil || policy.GetMaximumComputeTime().CheckValid() != nil || policy.GetMaximumComputeTime().AsDuration() <= 0 || validateArtifact(policy.GetPolicy(), true) != nil {
		return ErrInvalidArgument
	}
	if policy.Temperature != nil && (math.IsNaN(policy.GetTemperature()) || math.IsInf(policy.GetTemperature(), 0) || policy.GetTemperature() < 0) || policy.GuidanceScale != nil && (math.IsNaN(policy.GetGuidanceScale()) || math.IsInf(policy.GetGuidanceScale(), 0) || policy.GetGuidanceScale() < 0) {
		return ErrInvalidArgument
	}
	options := value.GetOutputOptions()
	if options == nil || options.GetResultSchemaId() == "" || len(options.GetRequestedArtifactKinds()) > maximumOutputKinds {
		return ErrInvalidArgument
	}
	seenKinds := make(map[string]struct{}, len(options.GetRequestedArtifactKinds()))
	for _, kind := range options.GetRequestedArtifactKinds() {
		if !validBoundedString(kind, 128) {
			return ErrInvalidArgument
		}
		if _, exists := seenKinds[kind]; exists {
			return ErrInvalidArgument
		}
		seenKinds[kind] = struct{}{}
	}
	if len(value.GetPolicySnapshots()) == 0 || len(value.GetPolicySnapshots()) > maximumPolicySnapshots {
		return ErrInvalidArgument
	}
	for _, snapshot := range value.GetPolicySnapshots() {
		if err := validatePolicy(snapshot); err != nil {
			return err
		}
	}
	if value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || value.GetCreateTime() == nil || value.GetCreateTime().CheckValid() != nil || !value.GetDeadline().AsTime().After(value.GetCreateTime().AsTime()) || !now.UTC().Before(value.GetDeadline().AsTime().UTC()) || value.GetCreateTime().AsTime().After(now.Add(time.Minute)) {
		return ErrInvalidArgument
	}
	return nil
}

func validateAuthorization(identity Identity, value *policyv1.AuthorizationDecision) error {
	if value == nil || value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetName() == "" || value.GetUid() == "" || value.GetPrincipalRef() == "" || value.GetAction() == "" || value.GetOutcome() == policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_UNSPECIFIED || value.GetReasonCode() == "" || !validSHA256(value.GetIntentDigest()) || !validSHA256(value.GetContextDigest()) || !validSHA256(value.GetDecisionDigest()) || value.GetEvaluatedAt() == nil || value.GetEvaluatedAt().CheckValid() != nil || len(value.GetPolicies()) == 0 || len(value.GetPolicies()) > maximumPolicySnapshots || len(value.GetConstraints()) > 64 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetResource(), ""); err != nil {
		return err
	}
	for _, policy := range value.GetPolicies() {
		if err := validatePolicy(policy); err != nil {
			return err
		}
	}
	for _, constraint := range value.GetConstraints() {
		if constraint == nil || constraint.GetKind() == "" || !validSHA256(constraint.GetDetailsDigest()) || constraint.GetExpireTime() != nil && constraint.GetExpireTime().CheckValid() != nil {
			return ErrInvalidArgument
		}
	}
	return nil
}

func validateInferenceResult(identity Identity, request *inferencev1.InferenceRequest, value *inferencev1.InferenceResult, fence *jobv1.LeaseFence, requestDigest string) error {
	if request == nil || value == nil || fence == nil || value.GetUid() == "" || value.GetOutcome() == inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_UNSPECIFIED || !validSHA256(value.GetRequestDigest()) || !validSHA256(value.GetResultDigest()) || value.GetSourceRevision() == "" || value.GetCompletedAt() == nil || value.GetCompletedAt().CheckValid() != nil || len(value.GetCandidates()) > maximumCandidates || len(value.GetSafetyDecisions()) > maximumSafetyDecisions {
		return ErrInvalidArgument
	}
	if _, err := canonicalName(identity, value.GetName(), "inferenceResults"); err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(value.GetRequestDigest()), []byte(requestDigest)) != 1 || value.GetJobId() != fence.GetJobId() || value.GetRunId() != fence.GetRunId() || value.GetAttemptId() != fence.GetAttemptId() || value.GetLeaseEpoch() != fence.GetLeaseEpoch() {
		return ErrStaleFence
	}
	if err := validateReference(identity, value.GetRequest(), "inference_request"); err != nil || value.GetRequest().GetName() != request.GetName() {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetOperation(), "operation"); err != nil {
		return err
	}
	for _, artifact := range []*artifactv1.ArtifactRef{value.GetResultManifest(), value.GetModelBundle()} {
		if err := validateArtifact(artifact, true); err != nil {
			return err
		}
	}
	for _, artifact := range []*artifactv1.ArtifactRef{value.GetInputArtifact(), value.GetFeatureBundle(), value.GetExecutablePlan(), value.GetProviderManifest(), value.GetKernelQualification(), value.GetConfidenceReport(), value.GetRankingReport(), value.GetFailureDiagnostics()} {
		if err := validateArtifact(artifact, false); err != nil {
			return err
		}
	}
	seenIDs := make(map[string]struct{}, len(value.GetCandidates()))
	seenSamples := make(map[uint32]struct{}, len(value.GetCandidates()))
	selected := 0
	for _, candidate := range value.GetCandidates() {
		if candidate == nil || !validBoundedString(candidate.GetCandidateId(), 128) || validateArtifact(candidate.GetOutput(), true) != nil || validateArtifact(candidate.GetDiagnostics(), false) != nil || candidate.Confidence != nil && (math.IsNaN(candidate.GetConfidence()) || math.IsInf(candidate.GetConfidence(), 0)) {
			return ErrInvalidArgument
		}
		if _, exists := seenIDs[candidate.GetCandidateId()]; exists {
			return ErrInvalidArgument
		}
		if _, exists := seenSamples[candidate.GetSampleIndex()]; exists {
			return ErrInvalidArgument
		}
		seenIDs[candidate.GetCandidateId()] = struct{}{}
		seenSamples[candidate.GetSampleIndex()] = struct{}{}
		if candidate.GetSelected() {
			selected++
			if value.GetSelectedCandidateId() != candidate.GetCandidateId() {
				return ErrInvalidArgument
			}
		}
	}
	if selected > 1 || (value.GetSelectedCandidateId() == "") != (selected == 0) {
		return ErrInvalidArgument
	}
	for _, decision := range value.GetSafetyDecisions() {
		if err := validateAuthorization(identity, decision); err != nil {
			return err
		}
	}
	return nil
}

func validateCommit(identity Identity, value *internalinferencev1.CommitInferenceResultRequest, request *inferencev1.InferenceRequest, now time.Time) error {
	if value == nil || value.GetContext() == nil || value.GetInferenceRequest() == nil || value.GetFence() == nil || value.GetResult() == nil || !validSHA256(value.GetRequestDigest()) {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, value.GetInferenceRequest(), "inference_request"); err != nil || value.GetInferenceRequest().GetName() != request.GetName() {
		return ErrInvalidArgument
	}
	if err := validateFenceShape(identity, value.GetFence(), now); err != nil {
		return err
	}
	return validateInferenceResult(identity, request, value.GetResult(), value.GetFence(), value.GetRequestDigest())
}

func validateFenceShape(identity Identity, value *jobv1.LeaseFence, now time.Time) error {
	if value == nil || identity.WorkerID == "" || identity.LeaseToken == "" || value.GetJobId() == "" || value.GetRunId() == "" || value.GetAttemptId() == "" || value.GetLeaseEpoch() == 0 || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil {
		return ErrStaleFence
	}
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	if !now.UTC().Before(value.GetDeadline().AsTime().UTC()) {
		return ErrLeaseExpired
	}
	return nil
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func requestResource(identity Identity, request *inferencev1.InferenceRequest, digest string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "inference_request", ResourceId: resourceID(request.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: request.GetName(), Etag: digest}
}

func resultResource(identity Identity, result *inferencev1.InferenceResult) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "inference_result", ResourceId: resourceID(result.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: result.GetName(), Etag: result.GetResultDigest()}
}

func operationResource(value *jobv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "operation", ResourceId: resourceID(value.GetOperationId()), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetResourceVersion(), Name: value.GetOperationId(), Etag: value.GetEtag()}
}

func resourceID(name string) string {
	if index := strings.LastIndexByte(name, '/'); index >= 0 {
		return name[index+1:]
	}
	return name
}

func terminalOperationState(outcome inferencev1.InferenceResultOutcome) jobv1.OperationState {
	switch outcome {
	case inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_CANCELLED:
		return jobv1.OperationState_OPERATION_STATE_CANCELLED
	case inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_FAILED,
		inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_EXPIRED,
		inferencev1.InferenceResultOutcome_INFERENCE_RESULT_OUTCOME_POLICY_DENIED:
		return jobv1.OperationState_OPERATION_STATE_FAILED
	default:
		return jobv1.OperationState_OPERATION_STATE_SUCCEEDED
	}
}
