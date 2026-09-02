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
	authorizer bearerAuthorizer
	client     apiv1.MindcladeServiceClient
	conn       *grpc.ClientConn
	ready      func(context.Context) error
	routes     []route
}

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
		routes = append(routes, route{
			body: body, contract: contract, expression: expression,
			httpMethod: httpMethod, method: method, pathFields: fields,
		})
	}
	return &gateway{
		authorizer: authorizer,
		client:     apiv1.NewMindcladeServiceClient(conn),
		conn:       conn,
		ready:      ready,
		routes:     routes,
	}, nil
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
		g.serveSSE(ctx, writer, input)
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
		content, err := protojson.MarshalOptions{UseProtoNames: false}.Marshal(output)
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

func (g *gateway) serveSSE(ctx context.Context, writer http.ResponseWriter, input *dynamicpb.Message) {
	streamContext, cancel := context.WithCancel(ctx)
	defer cancel()
	name := input.Get(input.Descriptor().Fields().ByName("name")).String()
	stream, err := g.client.WatchOperation(streamContext, &apiv1.WatchOperationRequest{Name: name})
	if err != nil {
		writeHTTPError(writer, err)
		return
	}
	flusher, ok := writer.(http.Flusher)
	if !ok {
		writeHTTPError(writer, status.Error(codes.Unimplemented, "streaming is unavailable"))
		return
	}
	writer.Header().Set("Content-Type", "text/event-stream")
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Accel-Buffering", "no")
	writer.WriteHeader(http.StatusOK)
	if _, err = io.WriteString(writer, "retry: 3000\n\n"); err != nil {
		return
	}
	flusher.Flush()
	type receiveResult struct {
		event *apiv1.OperationEvent
		err   error
	}
	received := make(chan receiveResult, 1)
	consumerDone := make(chan struct{})
	defer close(consumerDone)
	go func() {
		for {
			event, receiveErr := stream.Recv()
			select {
			case received <- receiveResult{event: event, err: receiveErr}:
			case <-consumerDone:
				return
			}
			if receiveErr != nil {
				return
			}
		}
	}()
	heartbeats := time.NewTicker(15 * time.Second)
	defer heartbeats.Stop()
	// The request cursor is intentionally not trusted here. The application
	// establishes durability by returning an event; until then no heartbeat may
	// advance a browser's Last-Event-ID state.
	lastCursor := ""
	for {
		select {
		case result := <-received:
			if errors.Is(result.err, io.EOF) {
				return
			}
			if result.err != nil {
				slog.Warn("operation SSE stream ended", "code", status.Code(result.err))
				_ = writeSSEError(writer, lastCursor, result.err)
				flusher.Flush()
				return
			}
			if result.event == nil || result.event.GetSchemaVersion() != 1 || result.event.GetResumeCursor() == "" {
				slog.Error("operation SSE application stream returned an invalid event")
				_ = writeSSEError(writer, lastCursor, status.Error(codes.DataLoss, "invalid operation event"))
				flusher.Flush()
				return
			}
			lastCursor = result.event.GetResumeCursor()
			if writeSSEEvent(writer, result.event) != nil {
				return
			}
			flusher.Flush()
		case emittedAt := <-heartbeats.C:
			// A heartbeat is resumable only after an application event establishes
			// a validated durable cursor. Emitting an empty or merely presented id
			// would create an acknowledgement the server cannot honor.
			if lastCursor == "" {
				continue
			}
			heartbeat := &apiv1.OperationEvent{
				EventId: lastCursor, EventType: "heartbeat", SchemaVersion: 1,
				ResumeCursor: lastCursor, Heartbeat: true, EmittedAt: timestamppb.New(emittedAt.UTC()),
			}
			if writeSSEEvent(writer, heartbeat) != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeSSEEvent(writer io.Writer, event *apiv1.OperationEvent) error {
	payload, err := protojson.Marshal(event)
	if err != nil {
		return err
	}
	eventID := strings.NewReplacer("\r", "", "\n", "").Replace(event.GetEventId())
	eventType := strings.NewReplacer("\r", "", "\n", "").Replace(event.GetEventType())
	if eventType == "" {
		eventType = "operation.updated"
	}
	_, err = fmt.Fprintf(writer, "id: %s\nevent: %s\ndata: %s\n\n", eventID, eventType, payload)
	return err
}

type sseErrorPayload struct {
	Code         string `json:"code"`
	Message      string `json:"message"`
	ResumeCursor string `json:"resumeCursor,omitempty"`
	Retryable    bool   `json:"retryable"`
}

// writeSSEError is used only after HTTP 200 has committed. It maps transport
// failures to bounded public data and never serializes internal status text.
func writeSSEError(writer io.Writer, durableCursor string, err error) error {
	value := sseErrorPayload{Code: "STREAM_ERROR", Message: "operation stream ended", ResumeCursor: durableCursor}
	switch status.Code(err) {
	case codes.InvalidArgument:
		value.Code, value.Message = "INVALID_CURSOR", "resume cursor is invalid"
	case codes.PermissionDenied:
		value.Code, value.Message = "CURSOR_RESOURCE_MISMATCH", "resume cursor belongs to another operation"
	case codes.FailedPrecondition:
		value.Code, value.Message = "CURSOR_AHEAD", "resume cursor is ahead of durable state"
	case codes.OutOfRange:
		value.Code, value.Message = "CURSOR_EXPIRED", "resume cursor is outside the retention window"
	case codes.NotFound:
		value.Code, value.Message = "NOT_FOUND", "operation was not found"
	case codes.DeadlineExceeded:
		value.Code, value.Message, value.Retryable = "WATCH_DEADLINE", "operation watch deadline elapsed", true
	case codes.Unavailable, codes.ResourceExhausted, codes.Aborted:
		value.Code, value.Message, value.Retryable = "UNAVAILABLE", "operation stream is temporarily unavailable", true
	case codes.DataLoss:
		value.Code, value.Message = "HISTORY_UNAVAILABLE", "operation history is unavailable"
	}
	payload, marshalErr := json.Marshal(value)
	if marshalErr != nil {
		return marshalErr
	}
	cursor := strings.NewReplacer("\r", "", "\n", "").Replace(durableCursor)
	if cursor == "" {
		_, marshalErr = fmt.Fprintf(writer, "event: error\ndata: %s\n\n", payload)
		return marshalErr
	}
	_, marshalErr = fmt.Fprintf(writer, "id: %s\nevent: error\ndata: %s\n\n", cursor, payload)
	return marshalErr
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
	case codes.Unimplemented:
		httpStatus, publicCode, publicMessage = http.StatusNotImplemented, "NOT_IMPLEMENTED", "method is not implemented"
	}
	writer.Header().Set("Content-Type", "application/problem+json")
	writer.WriteHeader(httpStatus)
	_ = json.NewEncoder(writer).Encode(map[string]any{
		"code": publicCode, "message": publicMessage, "retryable": grpcStatus.Code() == codes.Unavailable,
		"requestId": fmt.Sprintf("gateway-%d", time.Now().UTC().UnixNano()),
	})
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
			WriteTimeout:      0,
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
