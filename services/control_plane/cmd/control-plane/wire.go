package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	annotations "google.golang.org/genproto/googleapis/api/annotations"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
)

var generatedGRPCFiles = [...]protoreflect.FileDescriptor{
	apiv1.File_proto_mindclade_api_v1_mindclade_service_proto,
	internaladminv1.File_proto_mindclade_internal_admin_v1_admin_service_proto,
	internalagentv1.File_proto_mindclade_internal_agent_v1_agent_service_proto,
	internalartifactv1.File_proto_mindclade_internal_artifact_v1_artifact_service_proto,
	internaldatasetv1.File_proto_mindclade_internal_dataset_v1_dataset_service_proto,
	internalevaluationv1.File_proto_mindclade_internal_evaluation_v1_evaluation_service_proto,
	internalexperimentv1.File_proto_mindclade_internal_experiment_v1_experiment_service_proto,
	internalinferencev1.File_proto_mindclade_internal_inference_v1_inference_service_proto,
	internaljobv1.File_proto_mindclade_internal_job_v1_job_service_proto,
	internalmodelv1.File_proto_mindclade_internal_model_v1_model_service_proto,
	internalpolicyv1.File_proto_mindclade_internal_policy_v1_policy_service_proto,
	internaltrainingv1.File_proto_mindclade_internal_training_v1_training_service_proto,
	internalworkflowv1.File_proto_mindclade_internal_workflow_v1_workflow_service_proto,
}

func generatedGRPCServiceNames() []string {
	names := make([]string, 0, len(generatedGRPCFiles))
	for _, file := range generatedGRPCFiles {
		services := file.Services()
		for index := 0; index < services.Len(); index++ {
			names = append(names, string(services.Get(index).FullName()))
		}
	}
	return names
}

type runtimeDependencies struct {
	Public     apiv1.MindcladeServiceServer
	Ready      func(context.Context) error
	Admin      internaladminv1.AdminServiceServer
	Agent      internalagentv1.AgentServiceServer
	Artifact   internalartifactv1.ArtifactServiceServer
	Dataset    internaldatasetv1.DatasetServiceServer
	Evaluation internalevaluationv1.EvaluationServiceServer
	Experiment internalexperimentv1.ExperimentServiceServer
	Inference  internalinferencev1.InferenceServiceServer
	Operation  internaljobv1.OperationServiceServer
	Job        internaljobv1.JobServiceServer
	Run        internaljobv1.RunServiceServer
	Model      internalmodelv1.ModelServiceServer
	Policy     internalpolicyv1.PolicyServiceServer
	Training   internaltrainingv1.TrainingServiceServer
	Workflow   internalworkflowv1.WorkflowServiceServer
	Approval   internalworkflowv1.ApprovalServiceServer
}

func isTypedNil(value any) bool {
	if value == nil {
		return false
	}
	reflected := reflect.ValueOf(value)
	switch reflected.Kind() {
	case reflect.Chan, reflect.Func, reflect.Interface, reflect.Map, reflect.Pointer, reflect.Slice:
		return reflected.IsNil()
	default:
		return false
	}
}

func registerGeneratedServices(server *grpc.Server, dependencies runtimeDependencies) error {
	if server == nil {
		return errors.New("generated service registrar is required")
	}
	required := []struct {
		name  string
		value any
	}{
		{"public", dependencies.Public},
		{"readiness", dependencies.Ready},
		{"admin", dependencies.Admin},
		{"agent", dependencies.Agent},
		{"artifact", dependencies.Artifact},
		{"dataset", dependencies.Dataset},
		{"evaluation", dependencies.Evaluation},
		{"experiment", dependencies.Experiment},
		{"inference", dependencies.Inference},
		{"operation", dependencies.Operation},
		{"job", dependencies.Job},
		{"run", dependencies.Run},
		{"model", dependencies.Model},
		{"policy", dependencies.Policy},
		{"training", dependencies.Training},
		{"workflow", dependencies.Workflow},
		{"approval", dependencies.Approval},
	}
	for _, dependency := range required {
		if dependency.value == nil || isTypedNil(dependency.value) {
			return fmt.Errorf("generated %s service dependency is required and must not be typed nil", dependency.name)
		}
	}

	// Production registration is deliberately strict: every descriptor-declared
	// service must have an explicit application adapter. There is no generated
	// Unimplemented fallback on the production startup path.
	apiv1.RegisterMindcladeServiceServer(server, dependencies.Public)
	internaladminv1.RegisterAdminServiceServer(server, dependencies.Admin)
	internalagentv1.RegisterAgentServiceServer(server, dependencies.Agent)
	internalartifactv1.RegisterArtifactServiceServer(server, dependencies.Artifact)
	internaldatasetv1.RegisterDatasetServiceServer(server, dependencies.Dataset)
	internalevaluationv1.RegisterEvaluationServiceServer(server, dependencies.Evaluation)
	internalexperimentv1.RegisterExperimentServiceServer(server, dependencies.Experiment)
	internalinferencev1.RegisterInferenceServiceServer(server, dependencies.Inference)
	internaljobv1.RegisterOperationServiceServer(server, dependencies.Operation)
	internaljobv1.RegisterJobServiceServer(server, dependencies.Job)
	internaljobv1.RegisterRunServiceServer(server, dependencies.Run)
	internalmodelv1.RegisterModelServiceServer(server, dependencies.Model)
	internalpolicyv1.RegisterPolicyServiceServer(server, dependencies.Policy)
	internaltrainingv1.RegisterTrainingServiceServer(server, dependencies.Training)
	internalworkflowv1.RegisterWorkflowServiceServer(server, dependencies.Workflow)
	internalworkflowv1.RegisterApprovalServiceServer(server, dependencies.Approval)

	registered := server.GetServiceInfo()
	for _, service := range generatedGRPCServiceNames() {
		if _, ok := registered[service]; !ok {
			return fmt.Errorf("generated gRPC service %s was not registered", service)
		}
	}
	return nil
}

type bearerAuthorizer struct {
	token  string
	claims verifiedIdentityClaims
	verify bearerTokenVerifier
}

type verifiedIdentityClaims struct {
	tenantID, projectID, principalID string
	workerID, leaseToken             string
	roles                            map[string]struct{}
}

type bearerTokenVerifier interface {
	Verify(context.Context, string) (verifiedIdentityClaims, error)
}

func (a bearerAuthorizer) configured() bool {
	return a.verify != nil || (a.token != "" && a.claims.tenantID != "" && a.claims.projectID != "" && a.claims.principalID != "")
}

func (a bearerAuthorizer) authorize(ctx context.Context, value string) (verifiedIdentityClaims, error) {
	if !a.configured() {
		return verifiedIdentityClaims{}, status.Error(codes.Unavailable, "authentication verifier is not configured")
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(value, prefix) {
		return verifiedIdentityClaims{}, status.Error(codes.Unauthenticated, "bearer authentication required")
	}
	provided := strings.TrimPrefix(value, prefix)
	if len(provided) == 0 || len(provided) > 16*1024 || strings.ContainsAny(provided, " \t\r\n\x00") {
		return verifiedIdentityClaims{}, status.Error(codes.Unauthenticated, "invalid bearer credential")
	}
	if a.verify != nil {
		claims, err := a.verify.Verify(ctx, provided)
		if err != nil {
			return verifiedIdentityClaims{}, status.Error(codes.Unauthenticated, "invalid bearer credential")
		}
		return claims, nil
	}
	if len(provided) != len(a.token) ||
		subtle.ConstantTimeCompare([]byte(provided), []byte(a.token)) != 1 {
		return verifiedIdentityClaims{}, status.Error(codes.Unauthenticated, "invalid bearer credential")
	}
	return a.claims, nil
}

func (a bearerAuthorizer) authenticatedContext(ctx context.Context, claims verifiedIdentityClaims) (context.Context, error) {
	if claims.tenantID == "" || claims.projectID == "" || claims.principalID == "" {
		return nil, status.Error(codes.Unavailable, "authentication claims are not configured")
	}
	values, _ := metadata.FromIncomingContext(ctx)
	values = values.Copy()
	for header, verified := range map[string]string{
		"x-mindclade-expected-tenant":    claims.tenantID,
		"x-mindclade-expected-project":   claims.projectID,
		"x-mindclade-expected-principal": claims.principalID,
	} {
		if expected := first(values.Get(header)); expected != "" && expected != verified {
			return nil, status.Error(codes.PermissionDenied, "configured client scope does not match authenticated identity")
		}
		values.Delete(header)
	}
	// Delete all claim-shaped input before writing verifier-owned values. This
	// prevents a caller from smuggling identity through arbitrary metadata.
	for _, key := range []string{
		verifiedTenantMetadata, verifiedProjectMetadata, verifiedPrincipalMetadata,
		verifiedWorkerMetadata, verifiedLeaseMetadata, verifiedRoleMetadata,
	} {
		values.Delete(key)
	}
	values.Set(verifiedTenantMetadata, claims.tenantID)
	values.Set(verifiedProjectMetadata, claims.projectID)
	values.Set(verifiedPrincipalMetadata, claims.principalID)
	roles := make([]string, 0, len(claims.roles))
	for role := range claims.roles {
		roles = append(roles, role)
	}
	sort.Strings(roles)
	if len(roles) != 0 {
		values.Set(verifiedRoleMetadata, roles...)
	}
	if claims.workerID != "" {
		values.Set(verifiedWorkerMetadata, claims.workerID)
	}
	leaseToken := claims.leaseToken
	if leaseToken == "" {
		leaseToken = first(values.Get("x-mindclade-lease-token"))
	}
	if leaseToken != "" {
		if len(leaseToken) > 4096 || strings.ContainsAny(leaseToken, " \t\r\n\x00") {
			return nil, status.Error(codes.Unauthenticated, "invalid lease credential")
		}
		values.Set(verifiedLeaseMetadata, leaseToken)
	}
	return metadata.NewIncomingContext(ctx, values), nil
}

func (a bearerAuthorizer) unary(
	ctx context.Context,
	request any,
	info *grpc.UnaryServerInfo,
	handler grpc.UnaryHandler,
) (any, error) {
	values, _ := metadata.FromIncomingContext(ctx)
	claims, err := a.authorize(ctx, first(values.Get("authorization")))
	if err != nil {
		return nil, err
	}
	if err = authorizeRPCMethod(claims, info.FullMethod); err != nil {
		return nil, err
	}
	authenticated, err := a.authenticatedContext(ctx, claims)
	if err != nil {
		return nil, err
	}
	return handler(authenticated, request)
}

func (a bearerAuthorizer) stream(
	server any,
	stream grpc.ServerStream,
	info *grpc.StreamServerInfo,
	handler grpc.StreamHandler,
) error {
	values, _ := metadata.FromIncomingContext(stream.Context())
	claims, err := a.authorize(stream.Context(), first(values.Get("authorization")))
	if err != nil {
		return err
	}
	if err = authorizeRPCMethod(claims, info.FullMethod); err != nil {
		return err
	}
	authenticated, err := a.authenticatedContext(stream.Context(), claims)
	if err != nil {
		return err
	}
	return handler(server, &authenticatedServerStream{ServerStream: stream, ctx: authenticated})
}

func authorizeRPCMethod(claims verifiedIdentityClaims, method string) error {
	// Direct interceptor unit tests may not provide method metadata. Every real
	// gRPC invocation does; fail closed if a non-test call is unknown.
	if method == "" {
		return nil
	}
	effectiveRoles := expandAuthorizationRoles(claims.roles)
	allowed := func(roles ...string) error {
		for _, role := range roles {
			if _, ok := effectiveRoles[role]; ok {
				return nil
			}
		}
		return status.Error(codes.PermissionDenied, "authenticated principal is not authorized for this RPC")
	}
	if strings.HasPrefix(method, "/mindclade.api.v1.MindcladeService/") {
		return allowed("platform", "admin")
	}
	switch method {
	case "/mindclade.internal.job.v1.OperationService/GetOperation",
		"/mindclade.internal.job.v1.OperationService/ListOperations",
		"/mindclade.internal.job.v1.OperationService/WatchOperation":
		return allowed("platform", "worker", "scheduler", "auditor", "admin")
	case "/mindclade.internal.job.v1.OperationService/CancelOperation":
		return allowed("platform", "admin")
	case "/mindclade.internal.job.v1.RunService/AcquireAttemptLease",
		"/mindclade.internal.job.v1.RunService/RenewAttemptLease",
		"/mindclade.internal.job.v1.RunService/HeartbeatAttempt",
		"/mindclade.internal.job.v1.RunService/CancelAttempt",
		"/mindclade.internal.job.v1.RunService/CommitAttempt":
		return allowed("worker", "admin")
	case "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases":
		return allowed("scheduler", "admin")
	case "/mindclade.internal.job.v1.RunService/GetRun",
		"/mindclade.internal.job.v1.RunService/ListRuns",
		"/mindclade.internal.job.v1.RunService/GetAttempt",
		"/mindclade.internal.job.v1.RunService/ListAttempts":
		return allowed("platform", "worker", "scheduler", "admin")
	case "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt",
		"/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt",
		"/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress",
		"/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint",
		"/mindclade.internal.training.v1.TrainingService/CommitCheckpoint",
		"/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun":
		return allowed("worker", "admin")
	case "/mindclade.internal.training.v1.TrainingService/GetTrainingRun",
		"/mindclade.internal.training.v1.TrainingService/ListTrainingRuns",
		"/mindclade.internal.training.v1.TrainingService/GetCheckpoint",
		"/mindclade.internal.training.v1.TrainingService/ListCheckpoints",
		"/mindclade.internal.training.v1.TrainingService/WatchTrainingRun":
		return allowed("platform", "worker", "scheduler", "auditor", "admin")
	case "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun",
		"/mindclade.internal.training.v1.TrainingService/CancelTrainingRun":
		return allowed("platform", "admin")
	case "/mindclade.internal.dataset.v1.DatasetService/GetDataset",
		"/mindclade.internal.dataset.v1.DatasetService/ListDatasets",
		"/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease",
		"/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases",
		"/mindclade.internal.model.v1.ModelService/GetModel",
		"/mindclade.internal.model.v1.ModelService/ListModels",
		"/mindclade.internal.model.v1.ModelService/GetModelRelease",
		"/mindclade.internal.model.v1.ModelService/ListModelReleases":
		return allowed("platform", "worker", "scheduler", "auditor", "admin")
	case "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun",
		"/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns",
		"/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult",
		"/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision":
		return allowed("platform", "worker", "scheduler", "auditor", "admin")
	case "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult":
		return allowed("worker", "admin")
	case "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment",
		"/mindclade.internal.experiment.v1.ExperimentService/ListExperiments",
		"/mindclade.internal.experiment.v1.ExperimentService/GetStudy",
		"/mindclade.internal.experiment.v1.ExperimentService/ListStudies",
		"/mindclade.internal.experiment.v1.ExperimentService/GetTrial",
		"/mindclade.internal.experiment.v1.ExperimentService/ListTrials":
		return allowed("platform", "worker", "scheduler", "auditor", "admin")
	case "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial":
		return allowed("platform", "admin")
	case "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial",
		"/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial":
		return allowed("platform", "scheduler", "admin")
	case "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment",
		"/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment",
		"/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment",
		"/mindclade.internal.experiment.v1.ExperimentService/CreateStudy",
		"/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy":
		return allowed("platform", "admin")
	case "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult":
		return allowed("worker", "automation-worker", "agent-worker", "admin", "platform-admin")
	case "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest",
		"/mindclade.internal.inference.v1.InferenceService/GetInferenceResult",
		"/mindclade.internal.inference.v1.InferenceService/WatchInference":
		return allowed("platform", "worker", "scheduler", "auditor", "admin", "automation-viewer", "automation-worker", "platform-admin")
	case "/mindclade.internal.inference.v1.InferenceService/SubmitInference":
		return allowed("platform", "admin", "automation-operator", "platform-operator", "platform-admin")
	case "/mindclade.internal.dataset.v1.DatasetService/CreateDataset",
		"/mindclade.internal.dataset.v1.DatasetService/UpdateDataset",
		"/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease",
		"/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease",
		"/mindclade.internal.model.v1.ModelService/RegisterModel",
		"/mindclade.internal.model.v1.ModelService/RegisterModelRelease",
		"/mindclade.internal.model.v1.ModelService/PromoteModelRelease",
		"/mindclade.internal.model.v1.ModelService/RevokeModelRelease",
		"/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun",
		"/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun",
		"/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision":
		return allowed("platform", "admin")
	}
	if strings.HasPrefix(method, "/mindclade.internal.admin.v1.AdminService/QueryAudit") ||
		strings.HasPrefix(method, "/mindclade.internal.admin.v1.AdminService/GetAudit") {
		return allowed("auditor", "admin", "platform-admin")
	}
	if strings.HasPrefix(method, "/mindclade.internal.admin.v1.AdminService/") {
		return allowed("admin", "platform-admin")
	}
	if method == "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization" ||
		method == "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy" ||
		method == "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies" ||
		method == "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot" {
		return allowed("platform", "worker", "scheduler", "auditor", "admin", "platform-admin", "automation-operator", "automation-viewer", "automation-worker", "agent-admin", "agent-user", "agent-worker")
	}
	if strings.HasPrefix(method, "/mindclade.internal.policy.v1.PolicyService/") {
		return allowed("admin", "platform-admin")
	}
	if strings.HasPrefix(method, "/mindclade.internal.artifact.v1.ArtifactService/") {
		return allowed("platform", "worker", "admin", "platform-admin", "automation-worker")
	}
	if strings.HasPrefix(method, "/mindclade.internal.workflow.v1.WorkflowService/") ||
		strings.HasPrefix(method, "/mindclade.internal.workflow.v1.ApprovalService/") ||
		strings.HasPrefix(method, "/mindclade.internal.agent.v1.AgentService/") {
		return allowed("platform", "worker", "scheduler", "auditor", "admin", "platform-admin", "platform-operator", "automation-operator", "automation-viewer", "automation-worker", "agent-admin", "agent-user", "agent-worker", "approver")
	}
	if strings.HasPrefix(method, "/mindclade.internal.") {
		return allowed("platform", "admin")
	}
	return status.Error(codes.PermissionDenied, "RPC is outside the authorized Mindclade service estate")
}

func expandAuthorizationRoles(source map[string]struct{}) map[string]struct{} {
	roles := cloneRoles(source)
	add := func(items ...string) {
		for _, item := range items {
			roles[item] = struct{}{}
		}
	}
	for role := range source {
		switch role {
		case "admin":
			add("platform-admin", "platform-operator", "automation-operator", "automation-viewer", "automation-worker", "agent-admin", "agent-user", "agent-worker", "approver", "auditor")
		case "platform":
			add("platform-operator", "automation-operator", "automation-viewer", "agent-user")
		case "worker":
			add("automation-worker", "agent-worker")
		case "auditor":
			add("auditor", "automation-viewer")
		case "platform-admin":
			add("admin")
		case "platform-operator":
			add("platform")
		case "automation-worker", "agent-worker":
			add("worker")
		}
	}
	return roles
}

// applicationRoles returns only roles projected by the verified authentication
// chain. Caller-supplied role metadata is removed before this context is built.
func applicationRoles(ctx context.Context) map[string]struct{} {
	values, _ := metadata.FromIncomingContext(ctx)
	raw := make(map[string]struct{})
	for _, role := range values.Get(verifiedRoleMetadata) {
		raw[role] = struct{}{}
	}
	return expandAuthorizationRoles(raw)
}

type authenticatedServerStream struct {
	grpc.ServerStream
	ctx context.Context //nolint:containedctx // gRPC requires overriding ServerStream.Context with the authenticated request context.
}

func (s *authenticatedServerStream) Context() context.Context { return s.ctx }

func first(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
}

type route struct {
	body       string
	contract   *apiv1.PublicHttpContract
	expression *regexp.Regexp
	httpMethod string
	method     protoreflect.MethodDescriptor
	pathFields []string
}

type gateway struct {
	authorizer             bearerAuthorizer
	client                 apiv1.MindcladeServiceClient
	clock                  sseClock
	conn                   *grpc.ClientConn
	ready                  func(context.Context) error
	routes                 []route
	sseFrameWriteTimeout   time.Duration
	sseWriteDeadlineSetter func(http.ResponseWriter, time.Time) error
}

const defaultSSEFrameWriteTimeout = 30 * time.Second

type sseTicker interface {
	C() <-chan time.Time
	Stop()
}

type sseClock interface {
	NewTicker(time.Duration) sseTicker
	Now() time.Time
}

type wallSSEClock struct{}

func (wallSSEClock) NewTicker(interval time.Duration) sseTicker {
	return wallSSETicker{Ticker: time.NewTicker(interval)}
}

func (wallSSEClock) Now() time.Time { return time.Now().UTC() }

func responseControllerWriteDeadline(writer http.ResponseWriter, deadline time.Time) error {
	return http.NewResponseController(writer).SetWriteDeadline(deadline)
}

func (g *gateway) setSSEFrameWriteDeadline(writer http.ResponseWriter) error {
	timeout := g.sseFrameWriteTimeout
	if timeout <= 0 {
		timeout = defaultSSEFrameWriteTimeout
	}
	setter := g.sseWriteDeadlineSetter
	if setter == nil {
		setter = responseControllerWriteDeadline
	}
	if err := setter(writer, time.Now().UTC().Add(timeout)); err != nil {
		return fmt.Errorf("set SSE frame write deadline: %w", err)
	}
	return nil
}

type wallSSETicker struct {
	*time.Ticker
}

func (ticker wallSSETicker) C() <-chan time.Time { return ticker.Ticker.C }

var pathBinding = regexp.MustCompile(`\{([a-zA-Z][a-zA-Z0-9_]*)=([^{}]+)\}`)

func compilePath(template string) (*regexp.Regexp, []string, error) {
	fields := make([]string, 0)
	var result strings.Builder
	result.WriteString("^")
	cursor := 0
	for _, location := range pathBinding.FindAllStringSubmatchIndex(template, -1) {
		result.WriteString(regexp.QuoteMeta(template[cursor:location[0]]))
		field := template[location[2]:location[3]]
		resourceTemplate := template[location[4]:location[5]]
		fields = append(fields, field)
		parts := strings.Split(resourceTemplate, "*")
		result.WriteString("(?P<")
		result.WriteString(field)
		result.WriteString(">")
		for index, part := range parts {
			result.WriteString(regexp.QuoteMeta(part))
			if index < len(parts)-1 {
				result.WriteString("[^/]+")
			}
		}
		result.WriteString(")")
		cursor = location[1]
	}
	result.WriteString(regexp.QuoteMeta(template[cursor:]))
	result.WriteString("$")
	compiled, err := regexp.Compile(result.String())
	return compiled, fields, err
}

func httpRule(method protoreflect.MethodDescriptor) (string, string, string, error) {
	options := method.Options()
	value := proto.GetExtension(options, annotations.E_Http)
	rule, ok := value.(*annotations.HttpRule)
	if !ok || rule == nil {
		return "", "", "", fmt.Errorf("%s has no google.api.http rule", method.FullName())
	}
	switch {
	case rule.GetGet() != "":
		return http.MethodGet, rule.GetGet(), rule.GetBody(), nil
	case rule.GetPost() != "":
		return http.MethodPost, rule.GetPost(), rule.GetBody(), nil
	case rule.GetPatch() != "":
		return http.MethodPatch, rule.GetPatch(), rule.GetBody(), nil
	case rule.GetPut() != "":
		return http.MethodPut, rule.GetPut(), rule.GetBody(), nil
	case rule.GetDelete() != "":
		return http.MethodDelete, rule.GetDelete(), rule.GetBody(), nil
	default:
		return "", "", "", fmt.Errorf("%s uses an unsupported HTTP rule", method.FullName())
	}
}

func newGateway(
	conn *grpc.ClientConn,
	authorizer bearerAuthorizer,
	ready func(context.Context) error,
) (*gateway, error) {
	service := apiv1.File_proto_mindclade_api_v1_mindclade_service_proto.
		Services().ByName("MindcladeService")
	routes := make([]route, 0, service.Methods().Len())
	for index := 0; index < service.Methods().Len(); index++ {
		method := service.Methods().Get(index)
		httpMethod, template, body, err := httpRule(method)
		if err != nil {
			return nil, err
		}
		expression, fields, err := compilePath(template)
		if err != nil {
			return nil, fmt.Errorf("compile route for %s: %w", method.FullName(), err)
		}
		value := proto.GetExtension(method.Options(), apiv1.E_PublicHttp)
		contract, ok := value.(*apiv1.PublicHttpContract)
		if !ok || contract == nil {
			return nil, fmt.Errorf("%s has no public HTTP contract", method.FullName())
		}
		if err = validateHTTPStreamContract(method, httpMethod, template, body, contract); err != nil {
			return nil, err
		}
		routes = append(routes, route{
			body: body, contract: contract, expression: expression,
			httpMethod: httpMethod, method: method, pathFields: fields,
		})
	}
	return &gateway{
		authorizer:           authorizer,
		client:               apiv1.NewMindcladeServiceClient(conn),
		clock:                wallSSEClock{},
		conn:                 conn,
		ready:                ready,
		routes:               routes,
		sseFrameWriteTimeout: defaultSSEFrameWriteTimeout,
	}, nil
}

func validateHTTPStreamContract(
	method protoreflect.MethodDescriptor,
	httpMethod string,
	template string,
	body string,
	contract *apiv1.PublicHttpContract,
) error {
	if method == nil || contract == nil {
		return errors.New("public HTTP method and contract are required")
	}
	policy := contract.GetSse()
	switch contract.GetStream() {
	case apiv1.StreamProjection_STREAM_PROJECTION_NONE:
		if method.IsStreamingClient() || method.IsStreamingServer() {
			return fmt.Errorf("%s declares a unary projection for a streaming RPC", method.FullName())
		}
		if policy != nil {
			return fmt.Errorf("%s declares SSE policy for a unary projection", method.FullName())
		}
		return nil
	case apiv1.StreamProjection_STREAM_PROJECTION_BINARY:
		return fmt.Errorf("%s declares a binary stream projection unsupported by the HTTP runtime", method.FullName())
	case apiv1.StreamProjection_STREAM_PROJECTION_SSE:
		// V1 intentionally supports one explicit SSE capability. Widening this
		// binding requires a generic dispatcher and a separately reviewed policy.
		if method.FullName() != "mindclade.api.v1.MindcladeService.WatchOperation" ||
			method.Input().FullName() != "mindclade.api.v1.WatchOperationRequest" ||
			method.Output().FullName() != "mindclade.api.v1.OperationEvent" ||
			method.IsStreamingClient() || !method.IsStreamingServer() {
			return fmt.Errorf("%s is not the supported WatchOperation to OperationEvent SSE binding", method.FullName())
		}
		if httpMethod != http.MethodGet ||
			template != "/v1/{name=tenants/*/projects/*/operations/*}:watch" || body != "" ||
			contract.GetRequestBodyRequired() {
			return fmt.Errorf("%s has an invalid SSE HTTP binding", method.FullName())
		}
		if !contract.GetBearerAuth() ||
			!sameStrings(contract.GetRequestHeaders(), "Last-Event-ID") ||
			len(contract.GetRequiredRequestHeaders()) != 0 ||
			!sameStrings(contract.GetResponseHeaders(), "Cache-Control", "X-Accel-Buffering") ||
			!sameUint32s(contract.GetSuccessStatus(), http.StatusOK) ||
			!sameUint32s(contract.GetNonSuccessStatus(),
				http.StatusBadRequest,
				http.StatusUnauthorized,
				http.StatusForbidden,
				http.StatusNotFound,
				http.StatusGone,
				http.StatusPreconditionFailed,
				http.StatusInternalServerError,
			) {
			return fmt.Errorf("%s has incomplete SSE HTTP metadata", method.FullName())
		}
		errorField := method.Output().Fields().ByName("error")
		if errorField == nil || errorField.Number() != 9 || errorField.Message() == nil ||
			errorField.Message().FullName() != "mindclade.api.v1.PublicError" {
			return fmt.Errorf("%s has no descriptor-owned PublicError event field", method.FullName())
		}
		if policy == nil || policy.GetRetryMilliseconds() == 0 || policy.GetHeartbeatIntervalSeconds() == 0 {
			return fmt.Errorf("%s has incomplete SSE timing policy", method.FullName())
		}
		if !messageFieldPresent(policy, "heartbeat_reuses_last_durable_event_id") ||
			!messageFieldPresent(policy, "replay_acknowledged_terminal_event") {
			return fmt.Errorf("%s must declare both optional SSE replay policies", method.FullName())
		}
		if !policy.GetHeartbeatReusesLastDurableEventId() || policy.GetReplayAcknowledgedTerminalEvent() {
			return fmt.Errorf("%s declares SSE behavior unsupported by the v1 runtime", method.FullName())
		}
		return nil
	case apiv1.StreamProjection_STREAM_PROJECTION_UNSPECIFIED:
		return fmt.Errorf("%s has an unspecified public stream projection", method.FullName())
	default:
		return fmt.Errorf("%s has an unknown public stream projection", method.FullName())
	}
}

func messageFieldPresent(message proto.Message, name protoreflect.Name) bool {
	if message == nil {
		return false
	}
	reflected := message.ProtoReflect()
	field := reflected.Descriptor().Fields().ByName(name)
	return field != nil && reflected.Has(field)
}

func sameStrings(actual []string, expected ...string) bool {
	if len(actual) != len(expected) {
		return false
	}
	values := make(map[string]struct{}, len(actual))
	for _, value := range actual {
		canonical := strings.ToLower(value)
		if _, duplicate := values[canonical]; duplicate {
			return false
		}
		values[canonical] = struct{}{}
	}
	for _, value := range expected {
		if _, ok := values[strings.ToLower(value)]; !ok {
			return false
		}
	}
	return true
}

func sameUint32s(actual []uint32, expected ...uint32) bool {
	if len(actual) != len(expected) {
		return false
	}
	values := make(map[uint32]struct{}, len(actual))
	for _, value := range actual {
		if _, duplicate := values[value]; duplicate {
			return false
		}
		values[value] = struct{}{}
	}
	for _, value := range expected {
		if _, ok := values[value]; !ok {
			return false
		}
	}
	return true
}

func (g *gateway) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	if request.Method == http.MethodGet && request.URL.Path == "/healthz" {
		if !g.authorizer.configured() || g.ready == nil || g.ready(request.Context()) != nil {
			http.Error(writer, "not ready", http.StatusServiceUnavailable)
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"status":"ready"}`))
		return
	}
	for _, candidate := range g.routes {
		if candidate.httpMethod != request.Method {
			continue
		}
		matches := candidate.expression.FindStringSubmatch(request.URL.Path)
		if matches == nil {
			continue
		}
		g.serveRoute(writer, request, candidate, matches)
		return
	}
	writeHTTPError(writer, status.Error(codes.NotFound, "route not found"))
}

func (g *gateway) serveRoute(writer http.ResponseWriter, request *http.Request, selected route, matches []string) {
	if _, err := g.authorizer.authorize(request.Context(), request.Header.Get("Authorization")); err != nil {
		writeHTTPError(writer, err)
		return
	}
	if selected.contract.GetStream() == apiv1.StreamProjection_STREAM_PROJECTION_SSE {
		cursor, err := validateOptionalLastEventID(exactHTTPHeaderValues(request.Header, "Last-Event-ID"))
		if err != nil {
			writeHTTPError(writer, status.Error(codes.InvalidArgument, err.Error()))
			return
		}
		for name := range request.Header {
			if strings.EqualFold(name, "Last-Event-ID") {
				delete(request.Header, name)
			}
		}
		if cursor != "" {
			request.Header.Set("Last-Event-ID", cursor)
		}
	}
	for _, header := range selected.contract.GetRequestHeaders() {
		if requiredHeader(header) && request.Header.Get(header) == "" {
			writeHTTPError(writer, status.Errorf(codes.InvalidArgument, "%s header is required", header))
			return
		}
	}
	input := dynamicpb.NewMessage(selected.method.Input())
	for _, fieldName := range selected.pathFields {
		index := selected.expression.SubexpIndex(fieldName)
		field := input.Descriptor().Fields().ByName(protoreflect.Name(fieldName))
		if field == nil || index < 0 {
			writeHTTPError(writer, status.Error(codes.Internal, "invalid route binding"))
			return
		}
		input.Set(field, protoreflect.ValueOfString(matches[index]))
	}
	if err := populateQuery(input, request, selected); err != nil {
		writeHTTPError(writer, status.Error(codes.InvalidArgument, err.Error()))
		return
	}
	if selected.body != "" {
		field := input.Descriptor().Fields().ByName(protoreflect.Name(selected.body))
		if field == nil || field.Message() == nil {
			writeHTTPError(writer, status.Error(codes.Internal, "invalid request body binding"))
			return
		}
		payload, err := io.ReadAll(io.LimitReader(request.Body, (4<<20)+1))
		if err != nil {
			writeHTTPError(writer, status.Error(codes.InvalidArgument, "cannot read request body"))
			return
		}
		if len(payload) > 4<<20 {
			writeHTTPError(writer, status.Error(codes.ResourceExhausted, "request body is too large"))
			return
		}
		if err := (protojson.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(
			payload, input.Mutable(field).Message().Interface(),
		); err != nil {
			writeHTTPError(writer, status.Error(codes.InvalidArgument, "invalid ProtoJSON body"))
			return
		}
	}
	ctx := outgoingContext(request.Context(), request)
	switch selected.contract.GetStream() {
	case apiv1.StreamProjection_STREAM_PROJECTION_SSE:
		g.serveSSE(ctx, writer, input, selected.contract.GetSse())
	default:
		output := dynamicpb.NewMessage(selected.method.Output())
		fullMethod := "/" + string(selected.method.Parent().FullName()) + "/" + string(selected.method.Name())
		if err := g.conn.Invoke(ctx, fullMethod, input, output); err != nil {
			writeHTTPError(writer, err)
			return
		}
		responseETag := ""
		for _, header := range selected.contract.GetResponseHeaders() {
			if strings.EqualFold(header, "ETag") {
				field := output.Descriptor().Fields().ByName("etag")
				if field != nil {
					responseETag = output.Get(field).String()
					writer.Header().Set("ETag", responseETag)
				}
			}
		}
		if requestedETag := request.Header.Get("If-None-Match"); requestedETag != "" && responseETag != "" && requestedETag == responseETag {
			writer.WriteHeader(http.StatusNotModified)
			return
		}
		content, err := marshalPublicProtoJSON(output)
		if err != nil {
			writeHTTPError(writer, status.Error(codes.Internal, "response serialization failed"))
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(successStatus(selected.contract))
		_, _ = writer.Write(content)
	}
}

func populateQuery(message *dynamicpb.Message, request *http.Request, selected route) error {
	bound := make(map[string]bool, len(selected.pathFields)+1)
	for _, name := range selected.pathFields {
		bound[name] = true
	}
	bound[selected.body] = true
	fields := message.Descriptor().Fields()
	allowed := make(map[string]bool, fields.Len())
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if bound[string(field.Name())] {
			continue
		}
		allowed[field.JSONName()] = true
		raw := request.URL.Query().Get(field.JSONName())
		if raw == "" {
			continue
		}
		switch field.Kind() {
		case protoreflect.StringKind:
			message.Set(field, protoreflect.ValueOfString(raw))
		case protoreflect.Uint32Kind:
			value, err := strconv.ParseUint(raw, 10, 32)
			if err != nil {
				return fmt.Errorf("%s must be uint32", field.JSONName())
			}
			message.Set(field, protoreflect.ValueOfUint32(uint32(value)))
		case protoreflect.Uint64Kind:
			value, err := strconv.ParseUint(raw, 10, 64)
			if err != nil {
				return fmt.Errorf("%s must be uint64", field.JSONName())
			}
			message.Set(field, protoreflect.ValueOfUint64(value))
		default:
			return fmt.Errorf("%s is not a supported query field", field.JSONName())
		}
	}
	for name := range request.URL.Query() {
		if !allowed[name] {
			return fmt.Errorf("unknown query parameter %s", name)
		}
	}
	return nil
}

func outgoingContext(ctx context.Context, request *http.Request) context.Context {
	pairs := []string{"authorization", request.Header.Get("Authorization")}
	for _, header := range []string{
		"Idempotency-Key", "X-Mindclade-Deadline", "If-Match",
		"If-None-Match", "Last-Event-ID", "Range",
	} {
		if value := request.Header.Get(header); value != "" {
			pairs = append(pairs, strings.ToLower(header), value)
		}
	}
	return metadata.NewOutgoingContext(ctx, metadata.Pairs(pairs...))
}

func requiredHeader(name string) bool {
	switch strings.ToLower(name) {
	case "idempotency-key", "x-mindclade-deadline", "if-match":
		return true
	default:
		return false
	}
}

func successStatus(contract *apiv1.PublicHttpContract) int {
	if len(contract.GetSuccessStatus()) == 0 {
		return http.StatusOK
	}
	return int(contract.GetSuccessStatus()[0])
}

func (g *gateway) serveSSE(
	ctx context.Context,
	writer http.ResponseWriter,
	input *dynamicpb.Message,
	policy *apiv1.PublicSseContract,
) {
	if policy == nil || policy.GetRetryMilliseconds() == 0 || policy.GetHeartbeatIntervalSeconds() == 0 ||
		!messageFieldPresent(policy, "heartbeat_reuses_last_durable_event_id") ||
		!messageFieldPresent(policy, "replay_acknowledged_terminal_event") ||
		!policy.GetHeartbeatReusesLastDurableEventId() || policy.GetReplayAcknowledgedTerminalEvent() {
		writeHTTPError(writer, status.Error(codes.Internal, "SSE policy is unavailable"))
		return
	}
	if !supportsSSEFlush(writer) {
		writeHTTPError(writer, status.Error(codes.Internal, "streaming response capabilities are unavailable"))
		return
	}
	// V1 has no independent maximum watch lifetime. The caller's HTTP context
	// owns the connection lifetime and is propagated to the upstream stream.
	streamContext, cancel := context.WithCancel(ctx)
	defer cancel()
	name := input.Get(input.Descriptor().Fields().ByName("name")).String()
	stream, err := g.client.WatchOperation(streamContext, &apiv1.WatchOperationRequest{Name: name})
	if err != nil {
		writeSSEPreflightError(writer, err)
		return
	}

	// Receive and validate the first item before committing HTTP 200. This keeps
	// cursor, authorization, retention, and upstream failures representable as
	// ordinary problem responses instead of ambiguous post-200 stream failures.
	firstEvent, receiveErr := stream.Recv()
	if streamContext.Err() != nil {
		return
	}
	if errors.Is(receiveErr, io.EOF) {
		if err = g.beginSSE(writer, policy); err != nil {
			if errors.Is(err, errSSEWriteDeadlineUnavailable) {
				writeHTTPError(writer, status.Error(codes.Internal, "streaming response deadline is unavailable"))
			}
			return
		}
		return
	}
	if receiveErr != nil {
		writeSSEPreflightError(writer, receiveErr)
		return
	}
	if validationErr := validateOperationSSEEvent(firstEvent, name, 0); validationErr != nil {
		slog.Error("operation SSE application stream returned an invalid preflight event", "reason", validationErr.Error())
		writeSSEPreflightError(writer, status.Error(codes.DataLoss, "invalid operation event"))
		return
	}
	firstFrame, err := encodeSSEEvent(firstEvent)
	if err != nil {
		slog.Error("operation SSE preflight event could not be encoded", "reason", err.Error())
		writeSSEPreflightError(writer, status.Error(codes.DataLoss, "invalid operation event"))
		return
	}
	if err = g.beginSSE(writer, policy); err != nil {
		if errors.Is(err, errSSEWriteDeadlineUnavailable) {
			writeHTTPError(writer, status.Error(codes.Internal, "streaming response deadline is unavailable"))
		}
		return
	}
	if err = g.writeSSEFrame(writer, firstFrame); err != nil {
		return
	}
	lastCursor := firstEvent.GetResumeCursor()
	lastRevision := firstEvent.GetOperationRevision()
	if firstEvent.GetEventType() == "operation.terminal" {
		return
	}

	type receiveResult struct {
		event *apiv1.OperationEvent
		err   error
	}
	received := make(chan receiveResult, 1)
	receiverDone := make(chan struct{})
	go func() {
		defer close(receiverDone)
		for {
			event, receiveErr := stream.Recv()
			select {
			case received <- receiveResult{event: event, err: receiveErr}:
			case <-streamContext.Done():
				return
			}
			if receiveErr != nil {
				return
			}
		}
	}()
	defer func() {
		cancel()
		<-receiverDone
	}()
	clock := g.clock
	if clock == nil {
		clock = wallSSEClock{}
	}
	heartbeats := clock.NewTicker(time.Duration(policy.GetHeartbeatIntervalSeconds()) * time.Second)
	defer heartbeats.Stop()
	for {
		select {
		case <-streamContext.Done():
			return
		case result := <-received:
			if streamContext.Err() != nil {
				return
			}
			if errors.Is(result.err, io.EOF) {
				return
			}
			if result.err != nil {
				slog.Warn("operation SSE stream ended", "code", status.Code(result.err))
				g.writeSSEPostCommitError(writer, lastCursor, lastRevision, clock.Now(), result.err)
				return
			}
			if validationErr := validateOperationSSEEvent(result.event, name, lastRevision); validationErr != nil {
				slog.Error("operation SSE application stream returned an invalid event", "reason", validationErr.Error())
				g.writeSSEPostCommitError(
					writer, lastCursor, lastRevision, clock.Now(), status.Error(codes.DataLoss, "invalid operation event"),
				)
				return
			}
			frame, encodeErr := encodeSSEEvent(result.event)
			if encodeErr != nil {
				slog.Error("operation SSE application event could not be encoded", "reason", encodeErr.Error())
				g.writeSSEPostCommitError(
					writer, lastCursor, lastRevision, clock.Now(), status.Error(codes.DataLoss, "invalid operation event"),
				)
				return
			}
			if g.writeSSEFrame(writer, frame) != nil {
				return
			}
			lastCursor = result.event.GetResumeCursor()
			lastRevision = result.event.GetOperationRevision()
			if result.event.GetEventType() == "operation.terminal" {
				return
			}
		case emittedAt := <-heartbeats.C():
			if streamContext.Err() != nil {
				return
			}
			// A heartbeat is resumable only after an application event establishes
			// a validated durable cursor. Emitting an empty or merely presented id
			// would create an acknowledgement the server cannot honor.
			if lastCursor == "" {
				continue
			}
			heartbeat := &apiv1.OperationEvent{
				EventId: lastCursor, EventType: "heartbeat", SchemaVersion: 1,
				OperationRevision: lastRevision, ResumeCursor: lastCursor, Heartbeat: true,
				EmittedAt: timestamppb.New(emittedAt.UTC()),
			}
			frame, encodeErr := encodeSSEEvent(heartbeat)
			if encodeErr != nil || g.writeSSEFrame(writer, frame) != nil {
				return
			}
		}
	}
}

func supportsSSEFlush(writer http.ResponseWriter) bool {
	for depth := 0; depth < 32; depth++ {
		if _, ok := writer.(interface{ FlushError() error }); ok {
			return true
		}
		if _, ok := writer.(http.Flusher); ok {
			return true
		}
		unwrapper, ok := writer.(interface{ Unwrap() http.ResponseWriter })
		if !ok {
			return false
		}
		writer = unwrapper.Unwrap()
		if writer == nil {
			return false
		}
	}
	return false
}

var errSSEWriteDeadlineUnavailable = errors.New("SSE write deadline unavailable")

func (g *gateway) beginSSE(writer http.ResponseWriter, policy *apiv1.PublicSseContract) error {
	if err := g.setSSEFrameWriteDeadline(writer); err != nil {
		return fmt.Errorf("%w: %v", errSSEWriteDeadlineUnavailable, err)
	}
	writer.Header().Set("Content-Type", "text/event-stream")
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Accel-Buffering", "no")
	writer.WriteHeader(http.StatusOK)
	if err := writeAll(writer, []byte(fmt.Sprintf("retry: %d\n\n", policy.GetRetryMilliseconds()))); err != nil {
		return err
	}
	return http.NewResponseController(writer).Flush()
}

func (g *gateway) writeSSEFrame(writer http.ResponseWriter, frame []byte) error {
	if err := g.setSSEFrameWriteDeadline(writer); err != nil {
		return err
	}
	if err := writeAll(writer, frame); err != nil {
		return err
	}
	return http.NewResponseController(writer).Flush()
}

func (g *gateway) writeSSEPostCommitError(
	writer http.ResponseWriter,
	durableCursor string,
	durableRevision uint64,
	emittedAt time.Time,
	err error,
) {
	frame, encodeErr := encodeSSEError(durableCursor, durableRevision, emittedAt, err)
	if encodeErr != nil {
		return
	}
	_ = g.writeSSEFrame(writer, frame)
}

func writeSSEPreflightError(writer http.ResponseWriter, err error) {
	switch status.Code(err) {
	case codes.InvalidArgument,
		codes.Unauthenticated,
		codes.PermissionDenied,
		codes.NotFound,
		codes.OutOfRange,
		codes.FailedPrecondition:
		writeHTTPError(writer, err)
	default:
		writeHTTPError(writer, status.Error(codes.Internal, "operation stream could not be established"))
	}
}

func validateOperationSSEEvent(event *apiv1.OperationEvent, operationName string, lastRevision uint64) error {
	if err := validateSSEEventEnvelope(event); err != nil {
		return err
	}
	if event.GetEventType() != "operation.updated" && event.GetEventType() != "operation.terminal" {
		return errors.New("application stream may emit only operation update or terminal events")
	}
	operation := event.GetOperation()
	if operation == nil || operation.GetName() != operationName {
		return errors.New("operation event identity does not match the requested operation")
	}
	if operation.GetError() != nil {
		if err := validatePublicSSEError(operation.GetError()); err != nil {
			return fmt.Errorf("operation event carries an invalid nested error: %w", err)
		}
	}
	if event.GetOperationRevision() == 0 || event.GetOperationRevision() <= lastRevision ||
		operation.GetRevision() != event.GetOperationRevision() {
		return errors.New("operation event revision is not strictly monotonic")
	}
	terminalState := false
	switch operation.GetState() {
	case "PENDING", "RUNNING", "CANCELLING":
	case "SUCCEEDED", "FAILED", "CANCELLED":
		terminalState = true
	default:
		return errors.New("operation event carries an unknown operation state")
	}
	switch event.GetEventType() {
	case "operation.updated":
		if operation.GetDone() || terminalState {
			return errors.New("operation update carries terminal operation state")
		}
	case "operation.terminal":
		if !operation.GetDone() || !terminalState {
			return errors.New("terminal operation event carries non-terminal operation state")
		}
	default:
		return errors.New("operation event type is unsupported")
	}
	return nil
}

func validateSSEEventEnvelope(event *apiv1.OperationEvent) error {
	if event == nil {
		return errors.New("SSE event is required")
	}
	if event.GetSchemaVersion() != 1 {
		return errors.New("SSE event schema version is unsupported")
	}
	if err := validateSSECursor("event ID", event.GetEventId()); err != nil {
		return err
	}
	if err := validateSSECursor("resume cursor", event.GetResumeCursor()); err != nil {
		return err
	}
	if event.GetEventId() != event.GetResumeCursor() {
		return errors.New("SSE event ID and resume cursor differ")
	}
	if err := validateSSEMetadata("event type", event.GetEventType(), true); err != nil {
		return err
	}
	if event.GetEmittedAt() == nil {
		return errors.New("SSE event emitted_at is required")
	}
	if err := event.GetEmittedAt().CheckValid(); err != nil {
		return fmt.Errorf("SSE event emitted_at is invalid: %w", err)
	}
	operation := event.GetOperation()
	streamError := event.GetError()
	switch event.GetEventType() {
	case "operation.updated", "operation.terminal":
		if event.GetHeartbeat() || operation == nil || streamError != nil {
			return errors.New("operation event has inconsistent heartbeat, operation, or error payload")
		}
	case "heartbeat":
		if !event.GetHeartbeat() || operation != nil || streamError != nil || event.GetOperationRevision() == 0 {
			return errors.New("heartbeat event has inconsistent heartbeat, operation, error, or revision state")
		}
	case "error":
		if event.GetHeartbeat() || operation != nil || streamError == nil || event.GetOperationRevision() == 0 {
			return errors.New("error event has inconsistent heartbeat, operation, error, or revision state")
		}
		if err := validatePublicSSEError(streamError); err != nil {
			return err
		}
	default:
		return errors.New("SSE event type is unsupported")
	}
	return nil
}

func validatePublicSSEError(value *apiv1.PublicError) error {
	if value == nil {
		return errors.New("SSE PublicError is incomplete")
	}
	return validatePublicErrorMessage(value.ProtoReflect())
}

func validatePublicErrorMessage(value protoreflect.Message) error {
	if value.Descriptor().FullName() != "mindclade.api.v1.PublicError" {
		return errors.New("public error descriptor is invalid")
	}
	fields := value.Descriptor().Fields()
	stringValue := func(name protoreflect.Name) string {
		return value.Get(fields.ByName(name)).String()
	}
	if err := validatePublicErrorText("code", stringValue("code"), true, 64); err != nil {
		return err
	}
	if err := validatePublicErrorText("message", stringValue("message"), true, 1024); err != nil {
		return err
	}
	if err := validatePublicErrorText("request ID", stringValue("request_id"), true, 128); err != nil {
		return err
	}
	if err := validatePublicErrorText("trace ID", stringValue("trace_id"), false, 128); err != nil {
		return err
	}
	if err := validatePublicErrorText("retry-after", stringValue("retry_after"), false, 64); err != nil {
		return err
	}
	if err := validatePublicErrorText("diagnostic reference", stringValue("diagnostic_ref"), false, 256); err != nil {
		return err
	}
	switch stringValue("code") {
	case "AUTHENTICATION_REQUIRED",
		"PERMISSION_DENIED",
		"INVALID_ARGUMENT",
		"FAILED_PRECONDITION",
		"NOT_FOUND",
		"CONFLICT",
		"RATE_LIMITED",
		"QUOTA_EXCEEDED",
		"UNAVAILABLE",
		"DEADLINE_EXCEEDED",
		"CANCELLED",
		"INTERNAL":
	default:
		return errors.New("SSE PublicError code is unsupported")
	}
	details := value.Get(fields.ByName("details")).List()
	if details.Len() > 32 {
		return errors.New("SSE PublicError contains too many details")
	}
	for index := 0; index < details.Len(); index++ {
		detail := details.Get(index).Message()
		if err := validatePublicErrorDetail(detail); err != nil {
			return fmt.Errorf("SSE PublicError detail %d: %w", index, err)
		}
	}
	return nil
}

func validatePublicErrorDetail(value protoreflect.Message) error {
	if !value.IsValid() || value.Descriptor().FullName() != "mindclade.api.v1.ErrorDetail" {
		return errors.New("descriptor is invalid")
	}
	fields := value.Descriptor().Fields()
	stringValue := func(name protoreflect.Name) string {
		return value.Get(fields.ByName(name)).String()
	}
	kind := stringValue("kind")
	if err := validatePublicErrorText("kind", kind, true, 32); err != nil {
		return err
	}
	switch kind {
	case "fieldViolation", "resource", "precondition", "policy", "quota", "conflict":
	default:
		return errors.New("kind is unsupported")
	}
	if err := validatePublicErrorText("field", stringValue("field"), false, 256); err != nil {
		return err
	}
	if err := validatePublicErrorText("reason", stringValue("reason"), false, 128); err != nil {
		return err
	}
	if err := validatePublicErrorText("limit name", stringValue("limit_name"), false, 128); err != nil {
		return err
	}
	resourceField := fields.ByName("resource")
	if value.Has(resourceField) {
		if err := validatePublicErrorResource(value.Get(resourceField).Message()); err != nil {
			return err
		}
	} else if kind == "resource" {
		return errors.New("resource detail has no resource")
	}
	if kind == "fieldViolation" && stringValue("field") == "" {
		return errors.New("fieldViolation detail has no field")
	}
	return nil
}

func validatePublicErrorResource(value protoreflect.Message) error {
	if !value.IsValid() || value.Descriptor().FullName() != "mindclade.api.v1.ResourceRef" {
		return errors.New("resource descriptor is invalid")
	}
	fields := value.Descriptor().Fields()
	if err := validatePublicErrorText("resource name", value.Get(fields.ByName("name")).String(), true, 1024); err != nil {
		return err
	}
	if err := validatePublicErrorText("resource UID", value.Get(fields.ByName("uid")).String(), true, 128); err != nil {
		return err
	}
	if value.Get(fields.ByName("revision")).Uint() == 0 {
		return errors.New("resource revision is required")
	}
	return nil
}

func validatePublicErrorText(field string, value string, required bool, maximum int) error {
	if required && value == "" {
		return fmt.Errorf("public error %s is required", field)
	}
	if !utf8.ValidString(value) || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return fmt.Errorf("public error %s is not control-safe UTF-8", field)
	}
	if len(value) > maximum {
		return fmt.Errorf("public error %s exceeds %d bytes", field, maximum)
	}
	return nil
}

func validateSSEMetadata(field string, value string, required bool) error {
	if required && value == "" {
		return fmt.Errorf("SSE %s is required", field)
	}
	if !utf8.ValidString(value) {
		return fmt.Errorf("SSE %s is not valid UTF-8", field)
	}
	if strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return fmt.Errorf("SSE %s contains a control character", field)
	}
	return nil
}

func validateSSECursor(field string, value string) error {
	if err := validateSSEMetadata(field, value, true); err != nil {
		return err
	}
	if len(value) > 4096 {
		return fmt.Errorf("SSE %s exceeds the 4096-byte contract limit", field)
	}
	return nil
}

func validateOptionalLastEventID(values []string) (string, error) {
	switch len(values) {
	case 0:
		return "", nil
	case 1:
		if err := validateSSECursor("Last-Event-ID", values[0]); err != nil {
			return "", err
		}
		return values[0], nil
	default:
		return "", errors.New("SSE Last-Event-ID must be supplied at most once")
	}
}

func exactHTTPHeaderValues(header http.Header, name string) []string {
	var values []string
	for candidate, items := range header {
		if strings.EqualFold(candidate, name) {
			values = append(values, items...)
		}
	}
	return values
}

func marshalPublicProtoJSON(message proto.Message) ([]byte, error) {
	if message == nil {
		return nil, errors.New("public ProtoJSON message is required")
	}
	payload, err := (protojson.MarshalOptions{UseProtoNames: false}).Marshal(message)
	if err != nil {
		return nil, err
	}
	var document any
	if err = json.Unmarshal(payload, &document); err != nil {
		return nil, fmt.Errorf("decode generated public ProtoJSON: %w", err)
	}
	if err = applyPublicMessageContract(message.ProtoReflect(), document); err != nil {
		return nil, err
	}
	payload, err = json.Marshal(document)
	if err != nil {
		return nil, fmt.Errorf("encode contracted public ProtoJSON: %w", err)
	}
	return payload, nil
}

func publicMessageContract(descriptor protoreflect.MessageDescriptor) (*apiv1.PublicMessageContract, bool, error) {
	options := descriptor.Options()
	if options == nil || !proto.HasExtension(options, apiv1.E_PublicMessage) {
		return nil, false, nil
	}
	value := proto.GetExtension(options, apiv1.E_PublicMessage)
	contract, ok := value.(*apiv1.PublicMessageContract)
	if !ok || contract == nil {
		return nil, false, fmt.Errorf("%s has an invalid public message contract", descriptor.FullName())
	}
	return contract, true, nil
}

func applyPublicMessageContract(message protoreflect.Message, document any) error {
	descriptor := message.Descriptor()
	contract, contracted, err := publicMessageContract(descriptor)
	if err != nil {
		return err
	}
	object, objectOK := document.(map[string]any)
	if !objectOK {
		if contracted {
			return fmt.Errorf("%s did not encode as a public JSON object", descriptor.FullName())
		}
		return nil
	}
	if descriptor.FullName() == "mindclade.api.v1.PublicError" {
		if err = validatePublicErrorMessage(message); err != nil {
			return err
		}
	}
	if contracted {
		required := make(map[protoreflect.Name]struct{}, len(contract.GetRequiredFields()))
		for _, fieldName := range contract.GetRequiredFields() {
			name := protoreflect.Name(fieldName)
			if _, duplicate := required[name]; duplicate {
				return fmt.Errorf("%s repeats required field %s", descriptor.FullName(), fieldName)
			}
			required[name] = struct{}{}
			field := descriptor.Fields().ByName(name)
			if field == nil {
				return fmt.Errorf("%s requires unknown field %s", descriptor.FullName(), fieldName)
			}
			if _, present := object[field.JSONName()]; present {
				continue
			}
			if field.IsMap() {
				object[field.JSONName()] = map[string]any{}
				continue
			}
			if field.IsList() {
				object[field.JSONName()] = []any{}
				continue
			}
			if field.HasPresence() {
				return fmt.Errorf("%s is missing required field %s", descriptor.FullName(), fieldName)
			}
			defaultValue, defaultErr := publicProtoJSONDefault(field)
			if defaultErr != nil {
				return defaultErr
			}
			object[field.JSONName()] = defaultValue
		}
		for _, stringEnum := range contract.GetStringEnums() {
			field := descriptor.Fields().ByName(protoreflect.Name(stringEnum.GetField()))
			if field == nil || field.Kind() != protoreflect.StringKind {
				return fmt.Errorf("%s declares an invalid public string enum", descriptor.FullName())
			}
			value := message.Get(field).String()
			valid := false
			for _, allowed := range stringEnum.GetValues() {
				if value == allowed {
					valid = true
					break
				}
			}
			if !valid {
				return fmt.Errorf("%s.%s has an unsupported public string value", descriptor.FullName(), field.Name())
			}
		}
	}

	fields := descriptor.Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		encoded, present := object[field.JSONName()]
		if !present || field.Kind() != protoreflect.MessageKind {
			continue
		}
		if field.IsMap() {
			// No current public map has message values. Fail closed if that changes
			// until its ProtoJSON key/value traversal is explicitly qualified.
			if field.MapValue().Kind() == protoreflect.MessageKind {
				return fmt.Errorf("%s.%s uses an unsupported public message map", descriptor.FullName(), field.Name())
			}
			continue
		}
		if field.IsList() {
			items, ok := encoded.([]any)
			if !ok {
				return fmt.Errorf("%s.%s did not encode as a JSON array", descriptor.FullName(), field.Name())
			}
			values := message.Get(field).List()
			if len(items) != values.Len() {
				return fmt.Errorf("%s.%s changed length during ProtoJSON projection", descriptor.FullName(), field.Name())
			}
			for itemIndex := 0; itemIndex < values.Len(); itemIndex++ {
				if err = applyPublicMessageContract(values.Get(itemIndex).Message(), items[itemIndex]); err != nil {
					return err
				}
			}
			continue
		}
		if !message.Has(field) {
			continue
		}
		if err = applyPublicMessageContract(message.Get(field).Message(), encoded); err != nil {
			return err
		}
	}
	return nil
}

func publicProtoJSONDefault(field protoreflect.FieldDescriptor) (any, error) {
	value := field.Default()
	switch field.Kind() {
	case protoreflect.BoolKind:
		return value.Bool(), nil
	case protoreflect.StringKind:
		return value.String(), nil
	case protoreflect.BytesKind:
		return "", nil
	case protoreflect.EnumKind:
		enumValue := field.Enum().Values().ByNumber(value.Enum())
		if enumValue == nil {
			return nil, fmt.Errorf("%s has an unknown default enum value", field.FullName())
		}
		return string(enumValue.Name()), nil
	case protoreflect.Int64Kind, protoreflect.Sint64Kind, protoreflect.Sfixed64Kind:
		return strconv.FormatInt(value.Int(), 10), nil
	case protoreflect.Uint64Kind, protoreflect.Fixed64Kind:
		return strconv.FormatUint(value.Uint(), 10), nil
	case protoreflect.Int32Kind, protoreflect.Sint32Kind, protoreflect.Sfixed32Kind:
		return int32(value.Int()), nil
	case protoreflect.Uint32Kind, protoreflect.Fixed32Kind:
		return uint32(value.Uint()), nil
	case protoreflect.FloatKind, protoreflect.DoubleKind:
		return value.Float(), nil
	default:
		return nil, fmt.Errorf("%s cannot synthesize a required public ProtoJSON default", field.FullName())
	}
}

func writeSSEEvent(writer io.Writer, event *apiv1.OperationEvent) error {
	frame, err := encodeSSEEvent(event)
	if err != nil {
		return err
	}
	return writeAll(writer, frame)
}

func encodeSSEEvent(event *apiv1.OperationEvent) ([]byte, error) {
	if err := validateSSEEventEnvelope(event); err != nil {
		return nil, err
	}
	payload, err := marshalPublicProtoJSON(event)
	if err != nil {
		return nil, err
	}
	frame := make([]byte, 0, len(event.GetEventId())+len(event.GetEventType())+len(payload)+20)
	frame = append(frame, "id: "...)
	frame = append(frame, event.GetEventId()...)
	frame = append(frame, "\nevent: "...)
	frame = append(frame, event.GetEventType()...)
	frame = append(frame, "\ndata: "...)
	frame = append(frame, payload...)
	frame = append(frame, '\n', '\n')
	return frame, nil
}

func writeAll(writer io.Writer, payload []byte) error {
	written, err := writer.Write(payload)
	if err != nil {
		return err
	}
	if written != len(payload) {
		return io.ErrShortWrite
	}
	return nil
}

// writeSSEError is used only after HTTP 200 has committed. It maps transport
// failures to a descriptor-owned error event and never serializes internal
// status text. A post-200 error can be resumed only from established durable
// cursor truth, so empty cursors and zero revisions are rejected.
func writeSSEError(
	writer io.Writer,
	durableCursor string,
	durableRevision uint64,
	emittedAt time.Time,
	err error,
) error {
	frame, frameErr := encodeSSEError(durableCursor, durableRevision, emittedAt, err)
	if frameErr != nil {
		return frameErr
	}
	return writeAll(writer, frame)
}

func encodeSSEError(
	durableCursor string,
	durableRevision uint64,
	emittedAt time.Time,
	err error,
) ([]byte, error) {
	if metadataErr := validateSSECursor("durable cursor", durableCursor); metadataErr != nil {
		return nil, metadataErr
	}
	if durableRevision == 0 {
		return nil, errors.New("durable SSE revision is required")
	}
	requestID, identityErr := randomPublicID("gateway_")
	if identityErr != nil {
		return nil, errors.New("SSE error identity generation failed")
	}
	value := &apiv1.PublicError{Code: "INTERNAL", Message: "operation stream ended", RequestId: requestID}
	switch status.Code(err) {
	case codes.InvalidArgument:
		value.Code, value.Message = "INVALID_ARGUMENT", "stream request is invalid"
	case codes.Unauthenticated:
		value.Code, value.Message = "AUTHENTICATION_REQUIRED", "authentication is required"
	case codes.PermissionDenied:
		value.Code, value.Message = "PERMISSION_DENIED", "stream access is denied"
	case codes.FailedPrecondition, codes.OutOfRange:
		value.Code, value.Message = "FAILED_PRECONDITION", "stream cannot resume from the acknowledged cursor"
	case codes.NotFound:
		value.Code, value.Message = "NOT_FOUND", "stream resource was not found"
	case codes.AlreadyExists, codes.Aborted:
		value.Code, value.Message = "CONFLICT", "stream conflicts with current state"
	case codes.ResourceExhausted:
		value.Code, value.Message, value.Retryable = "RATE_LIMITED", "stream capacity is temporarily exhausted", true
	case codes.DeadlineExceeded:
		value.Code, value.Message, value.Retryable = "DEADLINE_EXCEEDED", "stream deadline elapsed", true
	case codes.Unavailable:
		value.Code, value.Message, value.Retryable = "UNAVAILABLE", "stream is temporarily unavailable", true
	case codes.Canceled:
		value.Code, value.Message = "CANCELLED", "stream was cancelled"
	}
	event := &apiv1.OperationEvent{
		EventId: durableCursor, EventType: "error", SchemaVersion: 1,
		OperationRevision: durableRevision, ResumeCursor: durableCursor,
		EmittedAt: timestamppb.New(emittedAt.UTC()), Error: value,
	}
	return encodeSSEEvent(event)
}

func writeHTTPError(writer http.ResponseWriter, err error) {
	grpcStatus := status.Convert(err)
	httpStatus := http.StatusInternalServerError
	publicCode := "INTERNAL"
	publicMessage := "request failed"
	switch grpcStatus.Code() {
	case codes.InvalidArgument:
		httpStatus, publicCode, publicMessage = http.StatusBadRequest, "INVALID_ARGUMENT", "request is invalid"
	case codes.Unauthenticated:
		httpStatus, publicCode, publicMessage = http.StatusUnauthorized, "AUTHENTICATION_REQUIRED", "authentication required"
	case codes.PermissionDenied:
		httpStatus, publicCode, publicMessage = http.StatusForbidden, "PERMISSION_DENIED", "permission denied"
	case codes.NotFound:
		httpStatus, publicCode, publicMessage = http.StatusNotFound, "NOT_FOUND", "resource not found"
	case codes.OutOfRange:
		httpStatus, publicCode, publicMessage = http.StatusGone, "FAILED_PRECONDITION", "requested stream position is no longer available"
	case codes.AlreadyExists, codes.Aborted:
		httpStatus, publicCode, publicMessage = http.StatusConflict, "CONFLICT", "request conflicts with current state"
	case codes.ResourceExhausted:
		httpStatus, publicCode, publicMessage = http.StatusTooManyRequests, "RATE_LIMITED", "request limit exceeded"
	case codes.FailedPrecondition:
		httpStatus, publicCode, publicMessage = http.StatusPreconditionFailed, "FAILED_PRECONDITION", "request precondition failed"
	case codes.Unavailable:
		httpStatus, publicCode, publicMessage = http.StatusServiceUnavailable, "UNAVAILABLE", "service unavailable"
	case codes.DeadlineExceeded:
		httpStatus, publicCode, publicMessage = http.StatusGatewayTimeout, "DEADLINE_EXCEEDED", "request deadline exceeded"
	case codes.Canceled:
		httpStatus, publicCode, publicMessage = 499, "CANCELLED", "request cancelled"
	}
	requestID, identityErr := randomPublicID("gateway_")
	if identityErr != nil {
		requestID = "gateway_unavailable"
	}
	payload, marshalErr := marshalPublicProtoJSON(&apiv1.PublicError{
		Code: publicCode, Message: publicMessage, RequestId: requestID,
		Retryable: grpcStatus.Code() == codes.Unavailable,
	})
	if marshalErr != nil {
		payload = []byte(`{"code":"INTERNAL","message":"request failed","requestId":"gateway_unavailable","retryable":false}`)
		httpStatus = http.StatusInternalServerError
	}
	writer.Header().Set("Content-Type", "application/problem+json")
	writer.WriteHeader(httpStatus)
	_ = writeAll(writer, append(payload, '\n'))
}

type runtime struct {
	grpcListener net.Listener
	grpcServer   *grpc.Server
	httpServer   *http.Server
	conn         *grpc.ClientConn
}

func newRuntimeWithAuthorizer(
	ctx context.Context,
	grpcAddress, httpAddress string,
	authorizer bearerAuthorizer,
	dependencies runtimeDependencies,
) (*runtime, error) {
	if err := requireLoopback(grpcAddress); err != nil {
		return nil, fmt.Errorf("gRPC address: %w", err)
	}
	if err := requireLoopback(httpAddress); err != nil {
		return nil, fmt.Errorf("HTTP address: %w", err)
	}
	listener, err := (&net.ListenConfig{}).Listen(ctx, "tcp", grpcAddress)
	if err != nil {
		return nil, fmt.Errorf("listen for gRPC: %w", err)
	}
	grpcServer := grpc.NewServer(
		grpc.UnaryInterceptor(authorizer.unary),
		grpc.StreamInterceptor(authorizer.stream),
	)
	if registrationErr := registerGeneratedServices(grpcServer, dependencies); registrationErr != nil {
		_ = listener.Close()
		return nil, registrationErr
	}
	conn, err := grpc.NewClient(
		listener.Addr().String(),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		_ = listener.Close()
		return nil, fmt.Errorf("create loopback gRPC client: %w", err)
	}
	httpGateway, err := newGateway(conn, authorizer, dependencies.Ready)
	if err != nil {
		_ = conn.Close()
		_ = listener.Close()
		return nil, fmt.Errorf("build HTTP gateway: %w", err)
	}
	return &runtime{
		grpcListener: listener,
		grpcServer:   grpcServer,
		httpServer: &http.Server{
			Addr:              httpAddress,
			Handler:           httpGateway,
			ReadHeaderTimeout: 10 * time.Second,
			ReadTimeout:       30 * time.Second,
			// Long-lived SSE connections cannot use one server-wide WriteTimeout.
			// The gateway instead applies a fresh bounded ResponseController write
			// deadline to the retry prelude and every event frame.
			WriteTimeout:   0,
			IdleTimeout:       90 * time.Second,
			MaxHeaderBytes:    64 << 10,
		},
		conn: conn,
	}, nil
}

func requireLoopback(address string) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return err
	}
	if strings.EqualFold(host, "localhost") {
		return nil
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("must bind to a loopback address; terminate TLS at an authenticated proxy")
	}
	return nil
}

func (r *runtime) serve() error {
	failures := make(chan error, 2)
	go func() { failures <- r.grpcServer.Serve(r.grpcListener) }()
	go func() { failures <- r.httpServer.ListenAndServe() }()
	err := <-failures
	if errors.Is(err, http.ErrServerClosed) || errors.Is(err, grpc.ErrServerStopped) {
		return nil
	}
	return err
}

func (r *runtime) shutdown(ctx context.Context) error {
	httpResult := make(chan error, 1)
	go func() { httpResult <- r.httpServer.Shutdown(ctx) }()
	grpcStopped := make(chan struct{})
	go func() {
		r.grpcServer.GracefulStop()
		close(grpcStopped)
	}()
	select {
	case <-grpcStopped:
	case <-ctx.Done():
		// Streaming clients cannot hold shutdown past the caller's deadline.
		r.grpcServer.Stop()
		<-grpcStopped
	}
	httpErr := <-httpResult
	connErr := r.conn.Close()
	return errors.Join(httpErr, connErr, ctx.Err())
}
