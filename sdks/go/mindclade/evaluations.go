package mindclade

import (
	"context"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

// EvaluationService is the private generated-type-only evaluation lifecycle,
// fenced result publication, and evidence-governance facade. It never exposes
// PostgreSQL, Pub/Sub, object-store, or handwritten wire values.
type EvaluationService struct {
	client    *Client
	transport internalevaluationv1.EvaluationServiceClient
}

// CreateRun submits immutable generated evaluation inputs and returns the
// durable operation controlling validation and execution.
func (service *EvaluationService) CreateRun(ctx context.Context, request *internalevaluationv1.CreateEvaluationRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	value := cloneGenerated(request)
	if !service.configured() || value == nil || !validEvaluationID(value.GetEvaluationRunId()) {
		return nil, invalidArgument("evaluation creation requires a configured service and valid generated run ID")
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() != "" && value.GetParent() != parent {
		return nil, invalidArgument("evaluation parent must match the configured project")
	}
	value.Parent = parent
	if !validEvaluationArtifact(value.GetSuite(), true) || !validEvaluationArtifact(value.GetSnapshot(), true) || !validEvaluationArtifact(value.GetInferenceProtocol(), true) || len(value.GetDatasets()) == 0 || len(value.GetDatasets()) > 256 {
		return nil, invalidArgument("evaluation creation requires valid immutable suite, dataset, snapshot, and inference-protocol artifacts")
	}
	for _, dataset := range value.GetDatasets() {
		if !validEvaluationArtifact(dataset, true) {
			return nil, invalidArgument("evaluation datasets must be valid immutable artifacts")
		}
	}
	for _, optional := range []*artifactv1.ArtifactRef{value.GetExecutablePlan(), value.GetProviderManifest(), value.GetKernelQualification()} {
		if !validEvaluationArtifact(optional, false) {
			return nil, invalidArgument("optional evaluation plan, provider, and qualification artifacts must be valid when present")
		}
	}
	if !normalizeScopedReference(service.client.config, value.GetModelRelease(), "model_release", "models") {
		return nil, invalidArgument("evaluation model release must be in the configured project")
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, value.GetContext(), func(context *commonv1.CommandContext) { value.Context = context }, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.CreateEvaluationRun(callContext, value)
	if response == nil {
		return nil, normalizeEvaluationRPCError(rpcErr, "CreateEvaluationRun returned no response")
	}
	return operationResponse(response.GetOperation(), rpcErr, "CreateEvaluationRun")
}

// GetRun reads one current generated evaluation-run revision.
func (service *EvaluationService) GetRun(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*evaluationv1.EvaluationRun, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "evaluationRuns") {
		return nil, invalidArgument("evaluation run name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetEvaluationRun(callContext, &internalevaluationv1.GetEvaluationRunRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetEvaluationRun() == nil || response.GetEvaluationRun().GetName() != name {
		return nil, protocolDataLoss("GetEvaluationRun returned inconsistent durable state")
	}
	return cloneGenerated(response.GetEvaluationRun()), nil
}

// EvaluationRunPage is one bounded list response plus cursor-scheme traversal. The
// embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type EvaluationRunPage struct {
	*internalevaluationv1.ListEvaluationRunsResponse
	pageBase[*evaluationv1.EvaluationRun, *EvaluationRunPage]
}

// Items returns this page's evaluation runs without traversing any further page.
func (page *EvaluationRunPage) Items() []*evaluationv1.EvaluationRun { return page.GetEvaluationRuns() }

// ListRuns returns one bounded project-scoped page while preserving opaque
// server-issued pagination tokens.
func (service *EvaluationService) ListRuns(ctx context.Context, request *internalevaluationv1.ListEvaluationRunsRequest, options ...RequestOption) (*EvaluationRunPage, error) {
	if !service.configured() {
		return nil, invalidArgument("evaluation service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internalevaluationv1.ListEvaluationRunsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() != "" && value.GetParent() != parent {
		return nil, invalidArgument("evaluation list parent must match the configured project")
	}
	if value.GetPage().GetPageSize() > 200 {
		return nil, invalidArgument("evaluation page size cannot exceed 200")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListEvaluationRuns(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	detached := cloneGenerated(response)
	page := &EvaluationRunPage{ListEvaluationRunsResponse: detached}
	page.pageBase = newPage[*evaluationv1.EvaluationRun](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*EvaluationRunPage, error) {
		successor := cloneGenerated(value)
		successor.Page = pageRequestWithToken(value.GetPage(), token)
		return service.ListRuns(ctx, successor, options...)
	})
	return page, nil
}

// CancelRun records monotonic cancellation under an ETag precondition.
func (service *EvaluationService) CancelRun(ctx context.Context, request *internalevaluationv1.CancelEvaluationRunRequest, options ...RequestOption) (*operationv1.Operation, error) {
	value := cloneGenerated(request)
	if !service.configured() || value == nil || !scopedResourceName(service.client.config, value.GetName(), "evaluationRuns") || strings.TrimSpace(value.GetEtag()) == "" || strings.TrimSpace(value.GetReason()) == "" || len(value.GetReason()) > 1024 {
		return nil, invalidArgument("evaluation cancellation requires a scoped run, ETag, and bounded reason")
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, value.GetContext(), func(context *commonv1.CommandContext) { value.Context = context }, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.CancelEvaluationRun(callContext, value)
	if response == nil {
		return nil, normalizeEvaluationRPCError(rpcErr, "CancelEvaluationRun returned no response")
	}
	return operationResponse(response.GetOperation(), rpcErr, "CancelEvaluationRun")
}

// CommitResult publishes immutable generated evaluation truth under the
// current lease fence. The raw lease capability is required as transport-only
// metadata and is never copied into the request, digest, errors, or telemetry.
func (service *EvaluationService) CommitResult(ctx context.Context, request *internalevaluationv1.CommitEvaluationResultRequest, options ...RequestOption) (*evaluationv1.EvaluationResult, *evaluationv1.EvaluationRun, error) {
	value := cloneGenerated(request)
	if !service.configured() || value == nil || value.GetEvaluationRun() == nil || value.GetResult() == nil || strings.TrimSpace(value.GetEtag()) == "" {
		return nil, nil, invalidArgument("evaluation result commit requires a generated run reference, result, fence, and ETag")
	}
	if !normalizeScopedReference(service.client.config, value.GetEvaluationRun(), "evaluation_run", "evaluationRuns") || !normalizeScopedReference(service.client.config, value.GetResult().GetRun(), "evaluation_run", "evaluationRuns") || value.GetEvaluationRun().GetName() != value.GetResult().GetRun().GetName() {
		return nil, nil, invalidArgument("evaluation result must reference the configured evaluation run")
	}
	if !scopedResourceName(service.client.config, value.GetResult().GetName(), "evaluationResults") || !validSHA256Digest(value.GetResult().GetRunDigest()) || !validSHA256Digest(value.GetResult().GetResultDigest()) {
		return nil, nil, invalidArgument("evaluation result identity and canonical digests are required")
	}
	if err := normalizeEvaluationFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, nil, err
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, value.GetContext(), func(context *commonv1.CommandContext) { value.Context = context }, true, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	response, err := service.transport.CommitEvaluationResult(callContext, value)
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetResult() == nil || response.GetEvaluationRun() == nil || response.GetResult().GetName() != value.GetResult().GetName() || response.GetEvaluationRun().GetName() != value.GetEvaluationRun().GetName() {
		return nil, nil, protocolDataLoss("CommitEvaluationResult returned inconsistent durable state")
	}
	return cloneGenerated(response.GetResult()), cloneGenerated(response.GetEvaluationRun()), nil
}

// GetResult reads one immutable generated evaluation result.
func (service *EvaluationService) GetResult(ctx context.Context, name string, options ...RequestOption) (*evaluationv1.EvaluationResult, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "evaluationResults") {
		return nil, invalidArgument("evaluation result name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetEvaluationResult(callContext, &internalevaluationv1.GetEvaluationResultRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetResult() == nil || response.GetResult().GetName() != name {
		return nil, protocolDataLoss("GetEvaluationResult returned inconsistent immutable truth")
	}
	return cloneGenerated(response.GetResult()), nil
}

// CreatePromotionDecision records a generated evidence-governance decision.
// It never deploys, promotes, or mutates the referenced release itself.
func (service *EvaluationService) CreatePromotionDecision(ctx context.Context, request *internalevaluationv1.CreatePromotionDecisionRequest, options ...RequestOption) (*operationv1.Operation, error) {
	value := cloneGenerated(request)
	decision := value.GetPromotionDecision()
	if !service.configured() || value == nil || decision == nil || !scopedResourceName(service.client.config, decision.GetName(), "promotionDecisions") || !validSHA256Digest(decision.GetCandidateDigest()) || !validSHA256Digest(decision.GetDecisionDigest()) || len(decision.GetEvaluationResults()) == 0 {
		return nil, invalidArgument("promotion decision requires scoped generated identity and canonical evidence digests")
	}
	if !normalizeReferenceScope(service.client.config, decision.GetCandidateRelease()) {
		return nil, invalidArgument("promotion candidate must be in the configured project")
	}
	for _, result := range decision.GetEvaluationResults() {
		if !normalizeScopedReference(service.client.config, result, "evaluation_result", "evaluationResults") {
			return nil, invalidArgument("promotion evaluation results must be in the configured project")
		}
	}
	for _, authorization := range decision.GetPolicyDecisions() {
		if authorization == nil || (authorization.GetTenantId() != "" && authorization.GetTenantId() != service.client.config.TenantID) || (authorization.GetProjectId() != "" && authorization.GetProjectId() != service.client.config.ProjectID) {
			return nil, invalidArgument("promotion policy decisions must be in the configured project")
		}
		authorization.TenantId = service.client.config.TenantID
		authorization.ProjectId = service.client.config.ProjectID
	}
	decision.DecidedByPrincipalRef = service.client.config.PrincipalID
	callContext, cancel, err := service.prepareMutation(ctx, value, value.GetContext(), func(context *commonv1.CommandContext) { value.Context = context }, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, rpcErr := service.transport.CreatePromotionDecision(callContext, value)
	if response == nil {
		return nil, normalizeEvaluationRPCError(rpcErr, "CreatePromotionDecision returned no response")
	}
	return operationResponse(response.GetOperation(), rpcErr, "CreatePromotionDecision")
}

// GetPromotionDecision reads one immutable generated governed decision.
func (service *EvaluationService) GetPromotionDecision(ctx context.Context, name string, options ...RequestOption) (*evaluationv1.PromotionDecision, error) {
	if !service.configured() || !scopedResourceName(service.client.config, name, "promotionDecisions") {
		return nil, invalidArgument("promotion decision name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetPromotionDecision(callContext, &internalevaluationv1.GetPromotionDecisionRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetPromotionDecision() == nil || response.GetPromotionDecision().GetName() != name {
		return nil, protocolDataLoss("GetPromotionDecision returned inconsistent immutable truth")
	}
	return cloneGenerated(response.GetPromotionDecision()), nil
}

func (service *EvaluationService) prepareMutation(ctx context.Context, message proto.Message, existing *commonv1.CommandContext, assign func(*commonv1.CommandContext), requireLease bool, options ...RequestOption) (context.Context, context.CancelFunc, error) {
	key := existing.GetIdempotencyKey()
	assign(nil)
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, nil, err
	}
	if requireLease && metadata.leaseToken == "" {
		cancel()
		return nil, nil, invalidArgument("fenced evaluation result commit requires WithLeaseToken transport metadata")
	}
	digest, err := deterministicDigest(message)
	if err != nil {
		cancel()
		return nil, nil, err
	}
	assign(commandContext(service.client.config, callContext, metadata, digest))
	return callContext, cancel, nil
}

func (service *EvaluationService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func validEvaluationID(value string) bool {
	return validResourceIdentifier(value) && !strings.Contains(value, "/") && len(value) <= 128
}

func validEvaluationArtifact(value *artifactv1.ArtifactRef, required bool) bool {
	if value == nil {
		return !required
	}
	return validSHA256Digest(value.GetDigest()) && strings.TrimSpace(value.GetMediaType()) != "" && value.GetSizeBytes() >= 0 && (value.GetIntegrityDigest() == "" || validSHA256Digest(value.GetIntegrityDigest()))
}

func normalizeEvaluationFence(config Config, fence *jobv1.LeaseFence, now time.Time) error {
	if fence == nil || strings.TrimSpace(fence.GetJobId()) == "" || strings.TrimSpace(fence.GetRunId()) == "" || strings.TrimSpace(fence.GetAttemptId()) == "" || fence.GetLeaseEpoch() == 0 || fence.GetDeadline() == nil || fence.GetDeadline().CheckValid() != nil || !now.Before(fence.GetDeadline().AsTime()) || !validSHA256Digest(fence.GetLeaseTokenDigest()) {
		return invalidArgument("evaluation fence is incomplete, expired, or missing its token digest")
	}
	if !normalizeMessageScope(config, &fence.TenantId, &fence.ProjectId) {
		return invalidArgument("evaluation fence must match the configured project")
	}
	return nil
}

func normalizeEvaluationRPCError(err error, fallback string) error {
	if err != nil {
		return normalizeError(err)
	}
	return protocolDataLoss(fallback)
}

// validateEvaluationMutationRetry binds retries to the exact generated
// command context and deterministic pre-context protobuf digest.
func validateEvaluationMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalevaluationv1.CreateEvaluationRunRequest:
		copy := proto.Clone(typed).(*internalevaluationv1.CreateEvaluationRunRequest)
		command, copy.Context = copy.Context, nil
		message = copy
	case *internalevaluationv1.CancelEvaluationRunRequest:
		copy := proto.Clone(typed).(*internalevaluationv1.CancelEvaluationRunRequest)
		command, copy.Context = copy.Context, nil
		message = copy
	case *internalevaluationv1.CommitEvaluationResultRequest:
		copy := proto.Clone(typed).(*internalevaluationv1.CommitEvaluationResultRequest)
		command, copy.Context = copy.Context, nil
		message = copy
	case *internalevaluationv1.CreatePromotionDecisionRequest:
		copy := proto.Clone(typed).(*internalevaluationv1.CreatePromotionDecisionRequest)
		command, copy.Context = copy.Context, nil
		message = copy
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}
