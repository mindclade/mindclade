package evaluations

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
)

type Server struct {
	internalevaluationv1.UnimplementedEvaluationServiceServer
	repository Repository
	identities IdentityResolver
	pages      *PageTokenCodec
	clock      Clock
}

func NewServer(repository Repository, identities IdentityResolver, pages *PageTokenCodec) (*Server, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("evaluation server requires repository, identity resolver, and pagination codec")
	}
	return &Server{repository: repository, identities: identities, pages: pages, clock: realClock{}}, nil
}

func (server *Server) withClock(clock Clock) *Server {
	if clock != nil {
		server.clock = clock
	}
	return server
}

func Register(registrar grpc.ServiceRegistrar, server *Server) error {
	if registrar == nil || server == nil {
		return errors.New("evaluation registrar and server are required")
	}
	internalevaluationv1.RegisterEvaluationServiceServer(registrar, server)
	return nil
}

func (server *Server) identity(ctx context.Context) (Identity, error) {
	identity, err := server.identities.Resolve(ctx)
	if err != nil || validateIdentity(identity) != nil {
		return Identity{}, rpcError(ErrUnauthenticated)
	}
	return identity, nil
}

func (server *Server) CreateEvaluationRun(ctx context.Context, request *internalevaluationv1.CreateEvaluationRunRequest) (*internalevaluationv1.CreateEvaluationRunResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if err = validateCreateRun(identity, request); err != nil {
		return nil, rpcError(err)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.CreateRun(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.CreateEvaluationRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetEvaluationRun(ctx context.Context, request *internalevaluationv1.GetEvaluationRunRequest) (*internalevaluationv1.GetEvaluationRunResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetRun(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.GetEvaluationRunResponse{EvaluationRun: clone(value)}, nil
}

func (server *Server) ListEvaluationRuns(ctx context.Context, request *internalevaluationv1.ListEvaluationRunsRequest) (*internalevaluationv1.ListEvaluationRunsResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, rpcError(ErrPermissionDenied)
	}
	limit, err := pageLimit(request.GetPage().GetPageSize())
	if err != nil {
		return nil, rpcError(err)
	}
	order, err := normalizeRunOrder(request.GetOrderBy())
	if err != nil {
		return nil, rpcError(err)
	}
	state, err := parseRunFilter(request.GetFilter())
	if err != nil {
		return nil, rpcError(err)
	}
	page := RunPage{Limit: limit, Filter: request.GetFilter(), Order: order, State: state}
	if token := request.GetPage().GetPageToken(); token != "" {
		decoded, decodeErr := server.pages.decode(token, pageToken{Kind: "evaluation-runs", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order})
		if decodeErr != nil {
			return nil, rpcError(decodeErr)
		}
		page.AfterTime, err = parsePageTime(decoded.AfterTime)
		if err != nil {
			return nil, rpcError(err)
		}
		page.AfterName = decoded.AfterName
	}
	values, next, readAt, err := server.repository.ListRuns(ctx, identity, page)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.ListEvaluationRunsResponse{EvaluationRuns: cloneSlice(values), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt.UTC())}, nil
}

func (server *Server) CancelEvaluationRun(ctx context.Context, request *internalevaluationv1.CancelEvaluationRunRequest) (*internalevaluationv1.CancelEvaluationRunResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil || request.GetName() == "" || request.GetEtag() == "" || request.GetReason() == "" || len(request.GetReason()) > 1024 {
		return nil, rpcError(ErrInvalidArgument)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.CancelRun(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.CancelEvaluationRunResponse{Operation: clone(operation)}, nil
}

func (server *Server) CommitEvaluationResult(ctx context.Context, request *internalevaluationv1.CommitEvaluationResultRequest) (*internalevaluationv1.CommitEvaluationResultResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	now := server.clock.Now()
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validateReference(identity, request.GetEvaluationRun(), "evaluation run"); err != nil {
		return nil, rpcError(err)
	}
	if err = validateFence(identity, request.GetFence(), now); err != nil {
		return nil, rpcError(err)
	}
	if err = validateResult(identity, request.GetResult()); err != nil {
		return nil, rpcError(err)
	}
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	result, run, _, err := server.repository.CommitResult(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.CommitEvaluationResultResponse{Result: clone(result), EvaluationRun: clone(run)}, nil
}

func (server *Server) GetEvaluationResult(ctx context.Context, request *internalevaluationv1.GetEvaluationResultRequest) (*internalevaluationv1.GetEvaluationResultResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetResult(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.GetEvaluationResultResponse{Result: clone(value)}, nil
}

func (server *Server) CreatePromotionDecision(ctx context.Context, request *internalevaluationv1.CreatePromotionDecisionRequest) (*internalevaluationv1.CreatePromotionDecisionResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	request = clone(request)
	if request == nil || request.GetContext() == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	if err = validatePromotionDecision(identity, request.GetPromotionDecision()); err != nil {
		return nil, rpcError(err)
	}
	now := server.clock.Now()
	digest, err := validateContext(identity, request, request.GetContext(), now)
	if err != nil {
		return nil, rpcError(err)
	}
	operation, _, err := server.repository.CreatePromotionDecision(ctx, identity, request, digest, now)
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.CreatePromotionDecisionResponse{Operation: clone(operation)}, nil
}

func (server *Server) GetPromotionDecision(ctx context.Context, request *internalevaluationv1.GetPromotionDecisionRequest) (*internalevaluationv1.GetPromotionDecisionResponse, error) {
	identity, err := server.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil {
		return nil, rpcError(ErrInvalidArgument)
	}
	value, err := server.repository.GetPromotionDecision(ctx, identity, request.GetName())
	if err != nil {
		return nil, rpcError(err)
	}
	return &internalevaluationv1.GetPromotionDecisionResponse{PromotionDecision: clone(value)}, nil
}

func validateCreateRun(identity Identity, request *internalevaluationv1.CreateEvaluationRunRequest) error {
	if request == nil || request.GetContext() == nil || request.GetParent() != projectParent(identity) || !validID(request.GetEvaluationRunId()) || len(request.GetDatasets()) == 0 || len(request.GetDatasets()) > 256 || len(request.GetPolicySnapshots()) > 64 {
		return ErrInvalidArgument
	}
	if err := validateArtifact(request.GetSuite(), "suite", true); err != nil {
		return err
	}
	if err := validateArtifact(request.GetSnapshot(), "snapshot", true); err != nil {
		return err
	}
	if err := validateArtifact(request.GetInferenceProtocol(), "inference protocol", true); err != nil {
		return err
	}
	if err := validateReference(identity, request.GetModelRelease(), "model release"); err != nil {
		return err
	}
	for index, dataset := range request.GetDatasets() {
		if err := validateArtifact(dataset, fmt.Sprintf("dataset[%d]", index), true); err != nil {
			return err
		}
	}
	if err := validateArtifact(request.GetExecutablePlan(), "executable plan", false); err != nil {
		return err
	}
	if err := validateArtifact(request.GetProviderManifest(), "provider manifest", false); err != nil {
		return err
	}
	if err := validateArtifact(request.GetKernelQualification(), "kernel qualification", false); err != nil {
		return err
	}
	for _, policy := range request.GetPolicySnapshots() {
		if err := validatePolicy(policy); err != nil {
			return err
		}
	}
	return nil
}

func validateResult(identity Identity, result *evaluationv1.EvaluationResult) error {
	if result == nil || result.GetName() == "" || result.GetUid() == "" || !validSHA256(result.GetRunDigest()) || !validSHA256(result.GetResultDigest()) || result.GetOutcome() == evaluationv1.EvaluationResultOutcome_EVALUATION_RESULT_OUTCOME_UNSPECIFIED || result.GetSourceRevision() == "" || result.GetFinalizedAt() == nil || result.GetFinalizedAt().CheckValid() != nil || len(result.GetMetrics()) > 512 || len(result.GetThresholds()) > 512 || len(result.GetFailureCounts()) > 256 {
		return ErrInvalidArgument
	}
	if _, err := canonicalScopedName(identity, result.GetName(), "evaluationResults"); err != nil {
		return err
	}
	if err := validateReference(identity, result.GetRun(), "evaluation run"); err != nil {
		return err
	}
	if err := validateArtifact(result.GetReport(), "report", true); err != nil {
		return err
	}
	if err := validateArtifact(result.GetSuite(), "suite", true); err != nil {
		return err
	}
	if err := validateArtifact(result.GetSnapshot(), "snapshot", true); err != nil {
		return err
	}
	if err := validateArtifact(result.GetDatasetManifest(), "dataset manifest", true); err != nil {
		return err
	}
	if err := validateArtifact(result.GetInferenceProtocol(), "inference protocol", true); err != nil {
		return err
	}
	if err := validateArtifact(result.GetLeakageEvidence(), "leakage evidence", false); err != nil {
		return err
	}
	if err := validateArtifact(result.GetSafetyEvidence(), "safety evidence", false); err != nil {
		return err
	}
	if err := validateArtifact(result.GetStatisticalEvidence(), "statistical evidence", false); err != nil {
		return err
	}
	if err := validateArtifact(result.GetPerformanceEvidence(), "performance evidence", false); err != nil {
		return err
	}
	for _, metric := range result.GetMetrics() {
		if err := validateMetric(metric); err != nil {
			return err
		}
	}
	for _, threshold := range result.GetThresholds() {
		if threshold == nil || threshold.GetRuleId() == "" || threshold.GetMetricId() == "" || threshold.GetResult() == evaluationv1.ThresholdResult_THRESHOLD_RESULT_UNSPECIFIED || threshold.GetReasonCode() == "" {
			return ErrInvalidArgument
		}
		if err := validateArtifact(threshold.GetEvidence(), "threshold evidence", true); err != nil {
			return err
		}
	}
	for _, failure := range result.GetFailureCounts() {
		if failure == nil || failure.GetFailureClass() == "" || failure.GetCount() == 0 {
			return ErrInvalidArgument
		}
	}
	return nil
}

func validatePromotionDecision(identity Identity, decision *evaluationv1.PromotionDecision) error {
	if decision == nil || decision.GetName() == "" || decision.GetUid() == "" || !validSHA256(decision.GetCandidateDigest()) || !validSHA256(decision.GetDecisionDigest()) || decision.GetTargetProfile() == "" || decision.GetOutcome() == evaluationv1.PromotionOutcome_PROMOTION_OUTCOME_UNSPECIFIED || decision.GetReasonCode() == "" || decision.GetDecidedByPrincipalRef() == "" || decision.GetSourceRevision() == "" || decision.GetDecidedAt() == nil || decision.GetDecidedAt().CheckValid() != nil || len(decision.GetEvaluationResults()) == 0 || len(decision.GetEvaluationResults()) > 128 || len(decision.GetRules()) > 512 || len(decision.GetExceptions()) > 64 || len(decision.GetPolicyDecisions()) > 128 {
		return ErrInvalidArgument
	}
	if _, err := canonicalScopedName(identity, decision.GetName(), "promotionDecisions"); err != nil {
		return err
	}
	if err := validateReference(identity, decision.GetCandidateRelease(), "candidate release"); err != nil {
		return err
	}
	for _, result := range decision.GetEvaluationResults() {
		if err := validateReference(identity, result, "evaluation result"); err != nil {
			return err
		}
	}
	for _, rule := range decision.GetRules() {
		if rule == nil || rule.GetRuleId() == "" || rule.GetResult() == evaluationv1.ThresholdResult_THRESHOLD_RESULT_UNSPECIFIED || rule.GetReasonCode() == "" {
			return ErrInvalidArgument
		}
		if err := validateArtifact(rule.GetEvidence(), "promotion rule evidence", true); err != nil {
			return err
		}
	}
	for _, exception := range decision.GetExceptions() {
		if exception == nil || exception.GetExceptionId() == "" || exception.GetRuleId() == "" || exception.GetExpireTime() == nil || exception.GetExpireTime().CheckValid() != nil || !exception.GetExpireTime().AsTime().After(decision.GetDecidedAt().AsTime()) {
			return ErrInvalidArgument
		}
		if err := validateArtifact(exception.GetRationale(), "promotion exception rationale", true); err != nil {
			return err
		}
		for _, approval := range exception.GetApprovalReceipts() {
			if err := validateReference(identity, approval, "approval receipt"); err != nil {
				return err
			}
		}
	}
	if expiry := decision.GetExpireTime(); expiry != nil && (expiry.CheckValid() != nil || !expiry.AsTime().After(decision.GetDecidedAt().AsTime())) {
		return ErrInvalidArgument
	}
	for _, authorization := range decision.GetPolicyDecisions() {
		if authorization == nil || authorization.GetTenantId() != identity.TenantID || authorization.GetProjectId() != identity.ProjectID || authorization.GetName() == "" || authorization.GetUid() == "" || !validSHA256(authorization.GetIntentDigest()) || !validSHA256(authorization.GetContextDigest()) || !validSHA256(authorization.GetDecisionDigest()) {
			return ErrInvalidArgument
		}
	}
	return nil
}

func normalizeRunOrder(value string) (string, error) {
	value = strings.TrimSpace(strings.ToLower(value))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value == "create_time desc,name desc" || value == "create_time asc,name asc" {
		return value, nil
	}
	return "", ErrInvalidArgument
}

func parseRunFilter(value string) (evaluationv1.EvaluationRunState, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return evaluationv1.EvaluationRunState_EVALUATION_RUN_STATE_UNSPECIFIED, nil
	}
	const prefix = "state="
	if !strings.HasPrefix(value, prefix) {
		return 0, ErrInvalidArgument
	}
	name := strings.TrimSpace(strings.TrimPrefix(value, prefix))
	if number, ok := evaluationv1.EvaluationRunState_value[name]; ok && number != 0 {
		return evaluationv1.EvaluationRunState(number), nil
	}
	return 0, ErrInvalidArgument
}

func rpcError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, ErrUnauthenticated):
		return status.Error(codes.Unauthenticated, err.Error())
	case errors.Is(err, ErrPermissionDenied):
		return status.Error(codes.PermissionDenied, err.Error())
	case errors.Is(err, ErrInvalidArgument):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, err.Error())
	case errors.Is(err, ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, ErrIdempotencyConflict), errors.Is(err, ErrRevisionConflict), errors.Is(err, ErrInvalidTransition), errors.Is(err, ErrStaleFence):
		return status.Error(codes.Aborted, err.Error())
	case errors.Is(err, ErrDeadlineExceeded), errors.Is(err, ErrLeaseExpired):
		return status.Error(codes.DeadlineExceeded, err.Error())
	case errors.Is(err, ErrLeaseToken):
		return status.Error(codes.PermissionDenied, err.Error())
	default:
		return status.Error(codes.Internal, "evaluation service failed")
	}
}
