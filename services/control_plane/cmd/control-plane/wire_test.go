package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"slices"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
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
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	trainingapp "github.com/mindclade/mindclade/services/control_plane/internal/training"
)

const generatedServiceCount = 16

type unavailableTrainingFoundation struct {
	apiv1.UnimplementedMindcladeServiceServer
}

func (unavailableTrainingFoundation) unavailable() error {
	return status.Error(codes.Unavailable, "durable foundation training backend is not configured")
}

func (u unavailableTrainingFoundation) Ready(context.Context) error { return u.unavailable() }

func (u unavailableTrainingFoundation) CreateTrainingRun(context.Context, *apiv1.CreateTrainingRunRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}

func (u unavailableTrainingFoundation) GetTrainingRun(context.Context, *apiv1.GetResourceRequest) (*apiv1.TrainingRunView, error) {
	return nil, u.unavailable()
}

func (u unavailableTrainingFoundation) ListTrainingRuns(context.Context, *apiv1.ListResourcesRequest) (*apiv1.TrainingRunList, error) {
	return nil, u.unavailable()
}

func (u unavailableTrainingFoundation) GetOperation(context.Context, *apiv1.GetResourceRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}

func (u unavailableTrainingFoundation) CancelOperation(context.Context, *apiv1.CancelOperationRequest) (*apiv1.Operation, error) {
	return nil, u.unavailable()
}

func (u unavailableTrainingFoundation) WatchOperation(*apiv1.WatchOperationRequest, grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	return u.unavailable()
}

type activatedAdminServer struct {
	internaladminv1.UnimplementedAdminServiceServer
}

type activatedAgentServer struct {
	internalagentv1.UnimplementedAgentServiceServer
}

type activatedArtifactServer struct {
	internalartifactv1.UnimplementedArtifactServiceServer
}

type activatedDatasetServer struct {
	internaldatasetv1.UnimplementedDatasetServiceServer
}

func (activatedDatasetServer) GetDataset(context.Context, *internaldatasetv1.GetDatasetRequest) (*internaldatasetv1.GetDatasetResponse, error) {
	return &internaldatasetv1.GetDatasetResponse{Dataset: &datasetv1.Dataset{Name: "tenants/tenant/projects/project/datasets/activated"}}, nil
}

type activatedModelServer struct {
	internalmodelv1.UnimplementedModelServiceServer
}

type activatedEvaluationServer struct {
	internalevaluationv1.UnimplementedEvaluationServiceServer
}

type activatedExperimentServer struct {
	internalexperimentv1.UnimplementedExperimentServiceServer
}

type activatedInferenceServer struct {
	internalinferencev1.UnimplementedInferenceServiceServer
}

func (activatedEvaluationServer) GetEvaluationRun(context.Context, *internalevaluationv1.GetEvaluationRunRequest) (*internalevaluationv1.GetEvaluationRunResponse, error) {
	return &internalevaluationv1.GetEvaluationRunResponse{EvaluationRun: &evaluationv1.EvaluationRun{Name: "tenants/tenant/projects/project/evaluationRuns/activated"}}, nil
}

func (activatedModelServer) GetModel(context.Context, *internalmodelv1.GetModelRequest) (*internalmodelv1.GetModelResponse, error) {
	return &internalmodelv1.GetModelResponse{Model: &modelv1.Model{Name: "tenants/tenant/projects/project/models/activated"}}, nil
}

type activatedJobServer struct {
	internaljobv1.UnimplementedJobServiceServer
}

func (activatedJobServer) GetJob(context.Context, *internaljobv1.GetJobRequest) (*internaljobv1.GetJobResponse, error) {
	return &internaljobv1.GetJobResponse{Job: &jobv1.Job{JobId: "jobs/activated"}}, nil
}

type activatedRunServer struct {
	internaljobv1.UnimplementedRunServiceServer
}

type activatedOperationServer struct {
	internaljobv1.UnimplementedOperationServiceServer
}

type activatedPolicyServer struct {
	internalpolicyv1.UnimplementedPolicyServiceServer
}

type activatedTrainingServer struct {
	internaltrainingv1.UnimplementedTrainingServiceServer
}

type activatedWorkflowServer struct {
	internalworkflowv1.UnimplementedWorkflowServiceServer
}

type activatedApprovalServer struct {
	internalworkflowv1.UnimplementedApprovalServiceServer
}

func (activatedArtifactServer) GetArtifact(context.Context, *internalartifactv1.GetArtifactRequest) (*internalartifactv1.GetArtifactResponse, error) {
	return &internalartifactv1.GetArtifactResponse{Artifact: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/octet-stream"}}, nil
}

func completeRuntimeDependencies() runtimeDependencies {
	return runtimeDependencies{
		Public:     unavailableTrainingFoundation{},
		Ready:      unavailableTrainingFoundation{}.Ready,
		Admin:      activatedAdminServer{},
		Agent:      activatedAgentServer{},
		Artifact:   activatedArtifactServer{},
		Dataset:    activatedDatasetServer{},
		Evaluation: activatedEvaluationServer{},
		Experiment: activatedExperimentServer{},
		Inference:  activatedInferenceServer{},
		Operation:  activatedOperationServer{},
		Job:        activatedJobServer{},
		Run:        activatedRunServer{},
		Model:      activatedModelServer{},
		Policy:     activatedPolicyServer{},
		Training:   activatedTrainingServer{},
		Workflow:   activatedWorkflowServer{},
		Approval:   activatedApprovalServer{},
	}
}

func TestRegisterGeneratedServicesCoversDescriptorEstate(t *testing.T) {
	t.Parallel()

	server := grpc.NewServer()
	if err := registerGeneratedServices(server, completeRuntimeDependencies()); err != nil {
		t.Fatalf("register generated services: %v", err)
	}

	want := generatedGRPCServiceNames()
	if len(want) != generatedServiceCount {
		t.Fatalf("descriptor estate contains %d services, want %d", len(want), generatedServiceCount)
	}
	sort.Strings(want)

	serviceInfo := server.GetServiceInfo()
	got := make([]string, 0, len(serviceInfo))
	for name := range serviceInfo {
		got = append(got, name)
	}
	sort.Strings(got)
	if !slices.Equal(got, want) {
		t.Fatalf("registered service set = %v, descriptor service set = %v", got, want)
	}
}

func TestRegisterGeneratedServicesRejectsTypedNilDependencies(t *testing.T) {
	t.Parallel()

	var datasetServer *activatedDatasetServer
	dependencies := completeRuntimeDependencies()
	dependencies.Dataset = datasetServer
	err := registerGeneratedServices(grpc.NewServer(), dependencies)
	if err == nil || !strings.Contains(err.Error(), "typed nil") {
		t.Fatalf("register typed-nil dataset dependency error = %v, want typed-nil rejection", err)
	}
}

func TestRegisterGeneratedServicesActivatesArtifactImplementation(t *testing.T) {
	t.Parallel()
	server := grpc.NewServer()
	dependencies := completeRuntimeDependencies()
	dependencies.Artifact = activatedArtifactServer{}
	if err := registerGeneratedServices(server, dependencies); err != nil {
		t.Fatal(err)
	}
	listener := bufconn.Listen(1 << 20)
	serveResult := make(chan error, 1)
	go func() { serveResult <- server.Serve(listener) }()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
		if err := <-serveResult; err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			t.Errorf("serve artifact service: %v", err)
		}
	})
	connection, err := grpc.NewClient("passthrough:///artifact-activation", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	response, err := internalartifactv1.NewArtifactServiceClient(connection).GetArtifact(context.Background(), &internalartifactv1.GetArtifactRequest{Digest: "sha256:" + strings.Repeat("a", 64)})
	if err != nil || response.GetArtifact().GetDigest() == "" {
		t.Fatalf("activated artifact response=%v err=%v", response, err)
	}
}

func TestRegisterGeneratedServicesActivatesJobImplementation(t *testing.T) {
	t.Parallel()
	server := grpc.NewServer()
	dependencies := completeRuntimeDependencies()
	dependencies.Job = activatedJobServer{}
	if err := registerGeneratedServices(server, dependencies); err != nil {
		t.Fatal(err)
	}
	listener := bufconn.Listen(1 << 20)
	serveResult := make(chan error, 1)
	go func() { serveResult <- server.Serve(listener) }()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
		if err := <-serveResult; err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			t.Errorf("serve job service: %v", err)
		}
	})
	connection, err := grpc.NewClient("passthrough:///job-activation", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	response, err := internaljobv1.NewJobServiceClient(connection).GetJob(context.Background(), &internaljobv1.GetJobRequest{Name: "jobs/activated"})
	if err != nil || response.GetJob().GetJobId() != "jobs/activated" {
		t.Fatalf("activated job response=%v err=%v", response, err)
	}
}

func TestRegisterGeneratedServicesRejectsEveryMissingDependency(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name   string
		remove func(*runtimeDependencies)
	}{
		{"public", func(value *runtimeDependencies) { value.Public = nil }},
		{"admin", func(value *runtimeDependencies) { value.Admin = nil }},
		{"agent", func(value *runtimeDependencies) { value.Agent = nil }},
		{"artifact", func(value *runtimeDependencies) { value.Artifact = nil }},
		{"dataset", func(value *runtimeDependencies) { value.Dataset = nil }},
		{"evaluation", func(value *runtimeDependencies) { value.Evaluation = nil }},
		{"experiment", func(value *runtimeDependencies) { value.Experiment = nil }},
		{"inference", func(value *runtimeDependencies) { value.Inference = nil }},
		{"operation", func(value *runtimeDependencies) { value.Operation = nil }},
		{"job", func(value *runtimeDependencies) { value.Job = nil }},
		{"run", func(value *runtimeDependencies) { value.Run = nil }},
		{"model", func(value *runtimeDependencies) { value.Model = nil }},
		{"policy", func(value *runtimeDependencies) { value.Policy = nil }},
		{"training", func(value *runtimeDependencies) { value.Training = nil }},
		{"workflow", func(value *runtimeDependencies) { value.Workflow = nil }},
		{"approval", func(value *runtimeDependencies) { value.Approval = nil }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			dependencies := completeRuntimeDependencies()
			test.remove(&dependencies)
			err := registerGeneratedServices(grpc.NewServer(), dependencies)
			want := "generated " + test.name + " service dependency is required"
			if err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("missing %s dependency error = %v, want %q", test.name, err, want)
			}
		})
	}
}

func TestRegisterGeneratedServicesActivatesDatasetAndModelImplementations(t *testing.T) {
	t.Parallel()
	server := grpc.NewServer()
	dependencies := completeRuntimeDependencies()
	dependencies.Dataset = activatedDatasetServer{}
	dependencies.Evaluation = activatedEvaluationServer{}
	dependencies.Model = activatedModelServer{}
	if err := registerGeneratedServices(server, dependencies); err != nil {
		t.Fatal(err)
	}
	listener := bufconn.Listen(1 << 20)
	serveResult := make(chan error, 1)
	go func() { serveResult <- server.Serve(listener) }()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
		if err := <-serveResult; err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			t.Errorf("serve dataset/model services: %v", err)
		}
	})
	connection, err := grpc.NewClient("passthrough:///data-model-activation", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	datasetResponse, err := internaldatasetv1.NewDatasetServiceClient(connection).GetDataset(context.Background(), &internaldatasetv1.GetDatasetRequest{Name: "activated"})
	if err != nil || datasetResponse.GetDataset().GetName() == "" {
		t.Fatalf("activated dataset response=%v err=%v", datasetResponse, err)
	}
	modelResponse, err := internalmodelv1.NewModelServiceClient(connection).GetModel(context.Background(), &internalmodelv1.GetModelRequest{Name: "activated"})
	if err != nil || modelResponse.GetModel().GetName() == "" {
		t.Fatalf("activated model response=%v err=%v", modelResponse, err)
	}
	evaluationResponse, err := internalevaluationv1.NewEvaluationServiceClient(connection).GetEvaluationRun(context.Background(), &internalevaluationv1.GetEvaluationRunRequest{Name: "activated"})
	if err != nil || evaluationResponse.GetEvaluationRun().GetName() == "" {
		t.Fatalf("activated evaluation response=%v err=%v", evaluationResponse, err)
	}
}

func TestAuthenticationInterceptorReplacesSpoofedIdentityMetadata(t *testing.T) {
	t.Parallel()
	authorizer := bearerAuthorizer{
		token: "0123456789abcdef0123456789abcdef",
		claims: verifiedIdentityClaims{
			tenantID: "trusted-tenant", projectID: "trusted-project", principalID: "trusted-principal",
			roles: map[string]struct{}{"worker": {}},
		},
	}
	contextWithSpoofedClaims := metadata.NewIncomingContext(context.Background(), metadata.Pairs(
		"authorization", "Bearer 0123456789abcdef0123456789abcdef",
		verifiedTenantMetadata, "attacker-tenant",
		verifiedProjectMetadata, "attacker-project",
		verifiedPrincipalMetadata, "attacker-principal",
		verifiedRoleMetadata, "admin",
	))
	_, err := authorizer.unary(contextWithSpoofedClaims, struct{}{}, &grpc.UnaryServerInfo{}, func(ctx context.Context, _ any) (any, error) {
		identity, resolveErr := (metadataIdentityResolver{}).Resolve(ctx)
		if resolveErr != nil {
			return nil, resolveErr
		}
		if identity.TenantID != "trusted-tenant" || identity.ProjectID != "trusted-project" || identity.Principal != "trusted-principal" {
			return nil, fmt.Errorf("resolved untrusted identity: %+v", identity)
		}
		roles := applicationRoles(ctx)
		if _, ok := roles["automation-worker"]; !ok {
			return nil, fmt.Errorf("verified worker role was not projected: %v", roles)
		}
		if _, ok := roles["platform-admin"]; ok {
			return nil, fmt.Errorf("spoofed role survived authentication: %v", roles)
		}
		return struct{}{}, nil
	})
	if err != nil {
		t.Fatalf("authorize verified identity: %v", err)
	}
}

func TestSubjectMappingsBindEachWorkloadToExplicitTenantScope(t *testing.T) {
	t.Parallel()
	mappings, err := parseSubjectMappings(`{
		"service-a@example.iam.gserviceaccount.com": {
			"tenant_id": "tenant-a", "project_id": "project-a",
			"principal_id": "service-a", "roles": ["platform"]
		},
		"worker-b@example.iam.gserviceaccount.com": {
			"tenant_id": "tenant-b", "project_id": "project-b",
			"principal_id": "worker-b", "worker_id": "worker-b", "roles": ["worker"]
		}
	}`)
	if err != nil {
		t.Fatalf("parse subject mappings: %v", err)
	}
	if len(mappings) != 2 {
		t.Fatalf("mapping count = %d, want 2", len(mappings))
	}
	worker := mappings["worker-b@example.iam.gserviceaccount.com"]
	if worker.tenantID != "tenant-b" || worker.projectID != "project-b" || worker.workerID != "worker-b" {
		t.Fatalf("worker mapping = %+v", worker)
	}
	if _, ok := worker.roles["worker"]; !ok {
		t.Fatal("worker role was not preserved")
	}
	if _, err = newGoogleIDTokenVerifier("https://control.mindclade.internal", mappings); err != nil {
		t.Fatalf("construct multi-tenant verifier: %v", err)
	}
}

func TestSubjectMappingsRejectUnknownFieldsAndUnsupportedRoles(t *testing.T) {
	t.Parallel()
	for name, document := range map[string]string{
		"unknown field":     `{"subject":{"tenant_id":"tenant","project_id":"project","principal_id":"principal","roles":["platform"],"lease_token":"secret"}}`,
		"unsupported role":  `{"subject":{"tenant_id":"tenant","project_id":"project","principal_id":"principal","roles":["owner"]}}`,
		"trailing document": `{"subject":{"tenant_id":"tenant","project_id":"project","principal_id":"principal","roles":["platform"]}} {}`,
	} {
		document := document
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			if _, err := parseSubjectMappings(document); err == nil {
				t.Fatal("invalid subject mapping unexpectedly accepted")
			}
		})
	}
}

func TestAuthenticationInterceptorRejectsConfiguredScopeMismatch(t *testing.T) {
	t.Parallel()
	authorizer := bearerAuthorizer{
		token: "0123456789abcdef0123456789abcdef",
		claims: verifiedIdentityClaims{
			tenantID: "trusted-tenant", projectID: "trusted-project", principalID: "trusted-principal",
		},
	}
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs(
		"authorization", "Bearer 0123456789abcdef0123456789abcdef",
		"x-mindclade-expected-tenant", "different-tenant",
		"x-mindclade-expected-project", "trusted-project",
	))
	_, err := authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{}, func(context.Context, any) (any, error) {
		return struct{}{}, nil
	})
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("scope mismatch code = %s, want %s: %v", status.Code(err), codes.PermissionDenied, err)
	}
}

func TestAuthenticationInterceptorEnforcesMethodRoles(t *testing.T) {
	t.Parallel()
	authorizer := bearerAuthorizer{
		token: "0123456789abcdef0123456789abcdef",
		claims: verifiedIdentityClaims{
			tenantID: "tenant-01", projectID: "project-01", principalID: "principal-01", workerID: "worker-01",
			roles: map[string]struct{}{"worker": {}},
		},
	}
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs(
		"authorization", "Bearer 0123456789abcdef0123456789abcdef",
	))
	handler := func(context.Context, any) (any, error) { return struct{}{}, nil }
	_, err := authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.job.v1.RunService/HeartbeatAttempt",
	}, handler)
	if err != nil {
		t.Fatalf("worker heartbeat authorization: %v", err)
	}
	_, err = authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases",
	}, handler)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("worker expiry code = %s, want %s: %v", status.Code(err), codes.PermissionDenied, err)
	}
	_, err = authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease",
	}, handler)
	if err != nil {
		t.Fatalf("worker dataset read authorization: %v", err)
	}
	_, err = authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.model.v1.ModelService/RegisterModelRelease",
	}, handler)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("worker model mutation code = %s, want %s: %v", status.Code(err), codes.PermissionDenied, err)
	}
	_, err = authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.experiment.v1.ExperimentService/GetTrial",
	}, handler)
	if err != nil {
		t.Fatalf("worker experiment read authorization: %v", err)
	}
	_, err = authorizer.unary(ctx, struct{}{}, &grpc.UnaryServerInfo{
		FullMethod: "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial",
	}, handler)
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("worker experiment mutation code = %s, want %s: %v", status.Code(err), codes.PermissionDenied, err)
	}
}

func TestPublicTrainingProjectionRedactsPrivateExecutionState(t *testing.T) {
	t.Parallel()
	internal := &trainingv1.TrainingRun{
		Name: "trainingRuns/run-01", Uid: "run-uid", Revision: 7, Etag: "etag-7",
		TenantName: "tenants/tenant-01", ProjectName: "tenants/tenant-01/projects/project-01",
		TrainingRecipe: &artifactv1.ArtifactRef{
			Digest: "sha256:recipe", MediaType: "application/json", Uri: "gs://private-bucket/recipe.json",
		},
		ExecutablePlan: &artifactv1.ArtifactRef{Digest: "sha256:secret-plan", Uri: "gs://private-bucket/plan"},
		ActiveFence:    &jobv1.LeaseFence{LeaseTokenDigest: "sha256:secret-token"},
		DatasetRelease: &commonv1.ResourceRef{
			ResourceType: "dataset_release", ResourceId: "data-01", TenantId: "tenant-01",
			ProjectId: "project-01", Name: "datasetReleases/data-01", ResourceVersion: 3,
		},
	}
	public, err := publicTrainingRun(internal)
	if err != nil {
		t.Fatal(err)
	}
	if public.GetName() != "tenants/tenant-01/projects/project-01/trainingRuns/run-01" {
		t.Fatalf("public name = %q", public.GetName())
	}
	if public.GetTrainingRecipe().GetDigest() != "sha256:recipe" {
		t.Fatal("safe immutable artifact identity was not projected")
	}
	if public.GetDatasetRelease().GetName() != "tenants/tenant-01/projects/project-01/datasetReleases/data-01" {
		t.Fatalf("public dataset name = %q", public.GetDatasetRelease().GetName())
	}
	// Compile-time public types expose neither URI, executable-plan, fence, nor
	// lease-token fields. These equality checks prove only the explicit safe
	// projection was populated from the richer internal aggregate.
	if public.GetHardwareTopology() != nil || public.GetLatestCheckpoint() != nil {
		t.Fatal("absent safe fields acquired internal execution state")
	}
}

func TestTrainingProjectionRejectsUnrepresentableNumericValues(t *testing.T) {
	t.Parallel()
	for _, test := range []struct {
		name string
		call func() error
		code codes.Code
	}{
		{
			name: "negative operation revision",
			call: func() error {
				_, err := publicOperation(&operationv1.Operation{ResourceVersion: -1})
				return err
			},
			code: codes.Internal,
		},
		{
			name: "negative training revision",
			call: func() error {
				_, err := publicTrainingRun(&trainingv1.TrainingRun{Revision: -1})
				return err
			},
			code: codes.Internal,
		},
		{
			name: "negative artifact size",
			call: func() error {
				_, err := publicArtifact(&artifactv1.ArtifactRef{SizeBytes: -1})
				return err
			},
			code: codes.Internal,
		},
		{
			name: "negative resource revision",
			call: func() error {
				_, err := publicResource(&commonv1.ResourceRef{ResourceVersion: -1})
				return err
			},
			code: codes.Internal,
		},
		{
			name: "artifact size above PostgreSQL bigint",
			call: func() error {
				_, err := domainArtifact(&apiv1.ArtifactRef{Digest: "sha256:artifact", MediaType: "application/octet-stream", SizeBytes: ^uint64(0)})
				return err
			},
			code: codes.InvalidArgument,
		},
		{
			name: "resource revision above PostgreSQL bigint",
			call: func() error {
				_, err := domainResource(
					trainingapp.Identity{TenantID: "tenant-01", ProjectID: "project-01"},
					&apiv1.ResourceRef{Name: "tenants/tenant-01/projects/project-01/modelReleases/model-01", Revision: ^uint64(0)},
					"model_release",
				)
				return err
			},
			code: codes.InvalidArgument,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			if got := status.Code(test.call()); got != test.code {
				t.Fatalf("status code = %s, want %s", got, test.code)
			}
		})
	}
}

func TestPublicCommandContextUsesVerifiedScopeAndCanonicalDigest(t *testing.T) {
	t.Parallel()
	identity := trainingapp.Identity{TenantID: "tenant-01", ProjectID: "project-01", Principal: "principal-01"}
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("idempotency-key", "create-run-01"))
	command := &trainingv1.CreateTrainingRunCommand{TrainingRunId: "run-01"}
	commandContext, err := publicCommandContext(ctx, identity, command)
	if err != nil {
		t.Fatalf("build command context: %v", err)
	}
	if commandContext.GetTenantId() != identity.TenantID || commandContext.GetProjectId() != identity.ProjectID || commandContext.GetPrincipalId() != identity.Principal {
		t.Fatalf("command context scope = %+v", commandContext)
	}
	digest, err := canonicalDigest(command)
	if err != nil {
		t.Fatalf("compute canonical digest: %v", err)
	}
	if digest != commandContext.GetCanonicalRequestDigest() {
		t.Fatalf("canonical digest = %q, context = %q", digest, commandContext.GetCanonicalRequestDigest())
	}
}

func TestGoogleVerifierRequiresExplicitAudienceScopeAndSubjectMapping(t *testing.T) {
	t.Parallel()
	scope := verifiedIdentityClaims{
		tenantID: "tenant-01", projectID: "project-01", principalID: "principal-01",
		roles: map[string]struct{}{"platform": {}},
	}
	subjects := map[string]verifiedIdentityClaims{"subject-01": scope}
	if _, err := newGoogleIDTokenVerifier("", subjects); err == nil {
		t.Fatal("empty ID-token audience was accepted")
	}
	if _, err := newGoogleIDTokenVerifier("https://control-plane.test", nil); err == nil {
		t.Fatal("empty ID-token subject mapping was accepted")
	}
	if _, err := newGoogleIDTokenVerifier("https://control-plane.test", subjects); err != nil {
		t.Fatalf("valid ID-token verifier configuration: %v", err)
	}
}

func TestOutboxTenantListIsBoundedAndDeduplicated(t *testing.T) {
	t.Parallel()
	values, err := parseIdentityList("tenant-01,tenant-02,tenant-01")
	if err != nil {
		t.Fatalf("parse outbox tenant list: %v", err)
	}
	if !slices.Equal(values, []string{"tenant-01", "tenant-02"}) {
		t.Fatalf("outbox tenants = %v", values)
	}
	if _, err = parseIdentityList("tenant-01,invalid tenant"); err == nil {
		t.Fatal("unsafe outbox tenant identity was accepted")
	}
}

func TestRequiredHMACKeyRingSupportsRotationAndZeroing(t *testing.T) {
	current := base64.RawStdEncoding.EncodeToString([]byte(strings.Repeat("c", 32)))
	previous := base64.RawStdEncoding.EncodeToString([]byte(strings.Repeat("p", 32)))
	raw := fmt.Sprintf(`{"current":"%s","previous":"%s"}`, current, previous)
	keys, err := parseHMACKeyRing(raw, "current")
	if err != nil || len(keys) != 2 || len(keys["current"]) != 32 || len(keys["previous"]) != 32 {
		t.Fatalf("parse rotating key ring: keys=%v err=%v", len(keys), err)
	}
	zeroKeyRing(keys)
	for keyID, key := range keys {
		for index, value := range key {
			if value != 0 {
				t.Fatalf("key %s byte %d was not zeroed", keyID, index)
			}
		}
	}
	if _, err = parseHMACKeyRing(raw, "missing"); err == nil {
		t.Fatal("key ring without active key was accepted")
	}
}

func operationWatchMethod(t *testing.T) protoreflect.MethodDescriptor {
	t.Helper()
	service := apiv1.File_proto_mindclade_api_v1_mindclade_service_proto.
		Services().ByName("MindcladeService")
	method := service.Methods().ByName("WatchOperation")
	if method == nil {
		t.Fatal("WatchOperation descriptor is unavailable")
	}
	return method
}

func operationWatchContract(t *testing.T) *apiv1.PublicHttpContract {
	t.Helper()
	value := proto.GetExtension(operationWatchMethod(t).Options(), apiv1.E_PublicHttp)
	contract, ok := value.(*apiv1.PublicHttpContract)
	if !ok || contract == nil || contract.GetSse() == nil {
		t.Fatal("WatchOperation SSE contract is unavailable")
	}
	return contract
}

func operationSSEEvent(t *testing.T, name string, cursor string, revision uint64, terminal bool) *apiv1.OperationEvent {
	t.Helper()
	state := "RUNNING"
	eventType := "operation.updated"
	if terminal {
		state = "SUCCEEDED"
		eventType = "operation.terminal"
	}
	emittedAtSeconds, err := numconv.Uint64ToInt64(revision)
	if err != nil {
		t.Fatalf("operation revision %d is out of range: %v", revision, err)
	}
	emittedAt := timestamppb.New(time.Unix(emittedAtSeconds, 0).UTC())
	return &apiv1.OperationEvent{
		EventId: cursor, EventType: eventType, SchemaVersion: 1,
		OperationRevision: revision, ResumeCursor: cursor,
		EmittedAt: emittedAt,
		Operation: &apiv1.Operation{
			Name: name, Uid: "operation-uid", Revision: revision, Etag: "etag-operation",
			State: state, Done: terminal, CreateTime: emittedAt, UpdateTime: emittedAt,
		},
	}
}

func TestGatewayValidatesDescriptorOwnedSSEContract(t *testing.T) {
	t.Parallel()
	method := operationWatchMethod(t)
	contract := operationWatchContract(t)
	httpMethod, template, body, err := httpRule(method)
	if err != nil {
		t.Fatal(err)
	}
	if err = validateHTTPStreamContract(method, httpMethod, template, body, contract); err != nil {
		t.Fatalf("valid WatchOperation SSE contract: %v", err)
	}
	service, ok := method.Parent().(protoreflect.ServiceDescriptor)
	if !ok {
		t.Fatalf("WatchOperation parent is %T, want protoreflect.ServiceDescriptor", method.Parent())
	}
	wrongMethod := service.Methods().ByName("GetOperation")
	if err = validateHTTPStreamContract(wrongMethod, httpMethod, template, body, contract); err == nil {
		t.Fatal("SSE contract was accepted for a method other than WatchOperation")
	}

	invalidMetadata := map[string]func(*apiv1.PublicHttpContract){
		"extra request header": func(candidate *apiv1.PublicHttpContract) {
			candidate.RequestHeaders = append(candidate.RequestHeaders, "X-Extra")
		},
		"required resume header": func(candidate *apiv1.PublicHttpContract) {
			candidate.RequiredRequestHeaders = []string{"Last-Event-ID"}
		},
		"extra response header": func(candidate *apiv1.PublicHttpContract) {
			candidate.ResponseHeaders = append(candidate.ResponseHeaders, "X-Extra")
		},
		"wrong non-success status": func(candidate *apiv1.PublicHttpContract) {
			candidate.NonSuccessStatus = []uint32{400, 401, 403, 404, 412, 500, 503}
		},
		"required request body": func(candidate *apiv1.PublicHttpContract) {
			candidate.RequestBodyRequired = true
		},
		"binary projection": func(candidate *apiv1.PublicHttpContract) {
			candidate.Stream = apiv1.StreamProjection_STREAM_PROJECTION_BINARY
			candidate.Sse = nil
		},
	}
	for testName, mutate := range invalidMetadata {
		t.Run(testName, func(t *testing.T) {
			candidate := proto.Clone(contract).(*apiv1.PublicHttpContract)
			mutate(candidate)
			if contractErr := validateHTTPStreamContract(method, httpMethod, template, body, candidate); contractErr == nil {
				t.Fatal("invalid SSE descriptor metadata was accepted")
			}
		})
	}

	missingTiming := proto.Clone(contract).(*apiv1.PublicHttpContract)
	missingTiming.GetSse().RetryMilliseconds = 0
	if err = validateHTTPStreamContract(method, httpMethod, template, body, missingTiming); err == nil {
		t.Fatal("SSE contract without retry timing was accepted")
	}

	missingPresence := proto.Clone(contract).(*apiv1.PublicHttpContract)
	field := missingPresence.GetSse().ProtoReflect().Descriptor().Fields().ByName("replay_acknowledged_terminal_event")
	missingPresence.GetSse().ProtoReflect().Clear(field)
	if err = validateHTTPStreamContract(method, httpMethod, template, body, missingPresence); err == nil {
		t.Fatal("SSE contract without explicit terminal replay policy was accepted")
	}

	unsupportedReplay := proto.Clone(contract).(*apiv1.PublicHttpContract)
	unsupportedReplay.GetSse().ProtoReflect().Set(field, protoreflect.ValueOfBool(true))
	if err = validateHTTPStreamContract(method, httpMethod, template, body, unsupportedReplay); err == nil {
		t.Fatal("unsupported terminal replay behavior was accepted")
	}
}

func TestOperationSSEValidationRejectsInvalidDurableEvents(t *testing.T) {
	t.Parallel()
	name := "tenants/t-1/projects/p-1/operations/op-1"
	valid := operationSSEEvent(t, name, "cursor-2", 2, false)
	if err := validateOperationSSEEvent(valid, name, 1); err != nil {
		t.Fatalf("valid operation event: %v", err)
	}

	tests := map[string]func(*apiv1.OperationEvent){
		"mismatched event and resume cursor": func(event *apiv1.OperationEvent) { event.ResumeCursor = "other" },
		"control character in metadata":      func(event *apiv1.OperationEvent) { event.EventId = "bad\ncursor" },
		"wrong operation identity":           func(event *apiv1.OperationEvent) { event.Operation.Name = "tenants/t-1/projects/p-1/operations/other" },
		"non-monotonic revision":             func(event *apiv1.OperationEvent) { event.OperationRevision = 1; event.Operation.Revision = 1 },
		"revision mismatch":                  func(event *apiv1.OperationEvent) { event.Operation.Revision = 3 },
		"invalid emitted timestamp": func(event *apiv1.OperationEvent) {
			event.EmittedAt = timestamppb.New(time.Date(10000, 1, 1, 0, 0, 0, 0, time.UTC))
		},
		"updated terminal operation":           func(event *apiv1.OperationEvent) { event.Operation.Done = true; event.Operation.State = "SUCCEEDED" },
		"terminal type without terminal state": func(event *apiv1.OperationEvent) { event.EventType = "operation.terminal" },
		"application heartbeat": func(event *apiv1.OperationEvent) {
			event.EventType = "heartbeat"
			event.Heartbeat = true
			event.Operation = nil
		},
		"operation and error payloads": func(event *apiv1.OperationEvent) {
			event.Error = &apiv1.PublicError{Code: "INTERNAL", Message: "safe", RequestId: "request-1"}
		},
		"application error event": func(event *apiv1.OperationEvent) {
			event.EventType = "error"
			event.Operation = nil
			event.Error = &apiv1.PublicError{Code: "INTERNAL", Message: "safe", RequestId: "request-1"}
		},
		"unsupported public error code": func(event *apiv1.OperationEvent) {
			event.EventType = "error"
			event.Operation = nil
			event.Error = &apiv1.PublicError{Code: "CURSOR_EXPIRED", Message: "safe", RequestId: "request-1"}
		},
		"invalid nested operation error": func(event *apiv1.OperationEvent) {
			event.Operation.Error = &apiv1.PublicError{Code: "INTERNAL", Message: "safe", RequestId: "bad\nrequest"}
		},
	}
	for testName, mutate := range tests {
		t.Run(testName, func(t *testing.T) {
			event := proto.Clone(valid).(*apiv1.OperationEvent)
			mutate(event)
			if err := validateOperationSSEEvent(event, name, 1); err == nil {
				t.Fatal("invalid operation SSE event was accepted")
			}
		})
	}
}

func TestLastEventIDValidationIsExactBoundedAndControlSafe(t *testing.T) {
	t.Parallel()
	if value, err := validateOptionalLastEventID(nil); err != nil || value != "" {
		t.Fatalf("absent Last-Event-ID value=%q err=%v", value, err)
	}
	valid := strings.Repeat("x", 4096)
	if value, err := validateOptionalLastEventID([]string{valid}); err != nil || value != valid {
		t.Fatalf("4096-byte Last-Event-ID length=%d err=%v", len(value), err)
	}
	for name, values := range map[string][]string{
		"empty":     {""},
		"oversized": {valid + "x"},
		"control":   {"opaque\nvalue"},
		"duplicate": {"opaque", "opaque"},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := validateOptionalLastEventID(values); err == nil {
				t.Fatal("invalid Last-Event-ID was accepted")
			}
		})
	}
	headers := http.Header{
		"Last-Event-Id": {"cursor-one"},
		"last-event-id": {"cursor-two"},
	}
	if values := exactHTTPHeaderValues(headers, "Last-Event-ID"); len(values) != 2 {
		t.Fatalf("case-insensitive duplicate header values=%v", values)
	} else if _, err := validateOptionalLastEventID(values); err == nil {
		t.Fatal("case-insensitive duplicate Last-Event-ID was accepted")
	}
}

func TestPublicProtoJSONEmitsRequiredDefaultsWithoutAbsentOptionals(t *testing.T) {
	t.Parallel()
	publicFailure := &apiv1.PublicError{Code: "INTERNAL", Message: "safe failure", RequestId: "request-1"}
	payload, err := marshalPublicProtoJSON(publicFailure)
	if err != nil {
		t.Fatal(err)
	}
	encoded := string(payload)
	if !strings.Contains(encoded, `"retryable":false`) {
		t.Fatalf("required false retryable field is absent: %s", payload)
	}
	for _, absent := range []string{`"traceId"`, `"retryAfter"`, `"diagnosticRef"`, `"details"`} {
		if strings.Contains(encoded, absent) {
			t.Fatalf("absent optional field %s was emitted: %s", absent, payload)
		}
	}

	event := operationSSEEvent(t, "tenants/t-1/projects/p-1/operations/op-1", "cursor-1", 1, false)
	payload, err = marshalPublicProtoJSON(event)
	if err != nil {
		t.Fatal(err)
	}
	encoded = string(payload)
	if !strings.Contains(encoded, `"done":false`) || !strings.Contains(encoded, `"heartbeat":false`) {
		t.Fatalf("descriptor-required false fields are absent: %s", payload)
	}
	for _, absent := range []string{`"error"`, `"result"`, `"target"`} {
		if strings.Contains(encoded, absent) {
			t.Fatalf("absent message field %s was emitted: %s", absent, payload)
		}
	}
}

func TestInternalErrorCodeProjectionIsExhaustiveAndFailClosed(t *testing.T) {
	t.Parallel()
	want := map[commonv1.ErrorCode]string{
		commonv1.ErrorCode_ERROR_CODE_INVALID_ARGUMENT:    "INVALID_ARGUMENT",
		commonv1.ErrorCode_ERROR_CODE_FAILED_PRECONDITION: "FAILED_PRECONDITION",
		commonv1.ErrorCode_ERROR_CODE_NOT_FOUND:           "NOT_FOUND",
		commonv1.ErrorCode_ERROR_CODE_ALREADY_EXISTS:      "CONFLICT",
		commonv1.ErrorCode_ERROR_CODE_PERMISSION_DENIED:   "PERMISSION_DENIED",
		commonv1.ErrorCode_ERROR_CODE_UNAUTHENTICATED:     "AUTHENTICATION_REQUIRED",
		commonv1.ErrorCode_ERROR_CODE_RESOURCE_EXHAUSTED:  "RATE_LIMITED",
		commonv1.ErrorCode_ERROR_CODE_ABORTED:             "CONFLICT",
		commonv1.ErrorCode_ERROR_CODE_CONFLICT:            "CONFLICT",
		commonv1.ErrorCode_ERROR_CODE_UNAVAILABLE:         "UNAVAILABLE",
		commonv1.ErrorCode_ERROR_CODE_DEADLINE_EXCEEDED:   "DEADLINE_EXCEEDED",
		commonv1.ErrorCode_ERROR_CODE_CANCELLED:           "CANCELLED",
		commonv1.ErrorCode_ERROR_CODE_INTERNAL:            "INTERNAL",
		commonv1.ErrorCode_ERROR_CODE_DATA_LOSS:           "INTERNAL",
		commonv1.ErrorCode_ERROR_CODE_UNSUPPORTED:         "FAILED_PRECONDITION",
		commonv1.ErrorCode_ERROR_CODE_POLICY_DENIED:       "PERMISSION_DENIED",
	}
	for number := range commonv1.ErrorCode_name {
		code := commonv1.ErrorCode(number)
		projected, err := publicError(&commonv1.ErrorDetail{
			Code: code, RetryClass: commonv1.RetryClass_RETRY_CLASS_NEVER,
		})
		if code == commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED {
			if err == nil {
				t.Fatal("unspecified internal error code was projected")
			}
			continue
		}
		if err != nil || projected.GetCode() != want[code] {
			t.Fatalf("internal error code %s projected=%v err=%v", code, projected, err)
		}
		if projected.GetRequestId() == "" || len(projected.GetRequestId()) > 128 {
			t.Fatalf("internal error code %s request ID=%q", code, projected.GetRequestId())
		}
	}
	if _, err := publicError(&commonv1.ErrorDetail{Code: commonv1.ErrorCode(999)}); err == nil {
		t.Fatal("unknown internal error code was projected")
	}
	projected, err := publicError(&commonv1.ErrorDetail{
		Code:            commonv1.ErrorCode_ERROR_CODE_INVALID_ARGUMENT,
		RetryClass:      commonv1.RetryClass_RETRY_CLASS_NEVER,
		FieldViolations: []*commonv1.FieldViolation{{Field: "profile", Description: "is invalid"}},
	})
	if err != nil || len(projected.GetDetails()) != 1 || projected.GetDetails()[0].GetKind() != "fieldViolation" {
		t.Fatalf("field violation projection=%v err=%v", projected, err)
	}
	tooMany := &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_INTERNAL}
	for range 33 {
		tooMany.FieldViolations = append(tooMany.FieldViolations, &commonv1.FieldViolation{Field: "field"})
	}
	if _, err = publicError(tooMany); err == nil {
		t.Fatal("oversized nested public error was projected")
	}
}

func TestOperationSSEEventCarriesVersionedResumeState(t *testing.T) {
	t.Parallel()
	codec, err := trainingapp.NewPageTokenCodec([]byte(strings.Repeat("s", 32)))
	if err != nil {
		t.Fatal(err)
	}
	var sent *apiv1.OperationEvent
	bridge := &publicOperationStream{send: func(event *apiv1.OperationEvent) error {
		sent = event
		return nil
	}, encode: codec.EncodeOperationCursor}
	operation := &operationv1.Operation{
		OperationId: "operations/op-01", TenantId: "tenant-01", ProjectId: "project-01",
		ResourceVersion: 9, Etag: "etag-operation", State: operationv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true,
		CreatedAt: timestamppb.New(time.Unix(9, 0).UTC()), UpdatedAt: timestamppb.New(time.Unix(10, 0).UTC()),
	}
	if sendErr := bridge.Send(&internaljobv1.WatchOperationResponse{
		Operation: operation, Sequence: 9, ObservedAt: timestamppb.New(time.Unix(10, 0).UTC()),
	}); sendErr != nil {
		t.Fatalf("bridge operation event: %v", sendErr)
	}
	if sent.GetSchemaVersion() != 1 || sent.GetEventType() != "operation.terminal" || sent.GetOperationRevision() != 9 || sent.GetResumeCursor() == "" {
		t.Fatalf("SSE event lacks versioned resume state: %v", sent)
	}
	sequence, err := codec.DecodeOperationCursor(sent.GetResumeCursor(), publicOperationName(operation))
	if err != nil || sequence != 9 {
		t.Fatalf("resume sequence=%d err=%v", sequence, err)
	}
	var encoded strings.Builder
	if err = writeSSEEvent(&encoded, sent); err != nil {
		t.Fatalf("serialize SSE event: %v", err)
	}
	if !strings.Contains(encoded.String(), "event: operation.terminal\n") || !strings.Contains(encoded.String(), "\ndata: {") {
		t.Fatalf("SSE frame = %q", encoded.String())
	}
}

func TestSSEErrorFrameIsSafeAndKeepsLastDurableCursor(t *testing.T) {
	t.Parallel()
	var encoded strings.Builder
	emittedAt := time.Unix(20, 0).UTC()
	if err := writeSSEError(
		&encoded, "durable-cursor-7", 7, emittedAt, status.Error(codes.Unavailable, "secret database detail"),
	); err != nil {
		t.Fatal(err)
	}
	frame := encoded.String()
	if !strings.Contains(frame, "id: durable-cursor-7\nevent: error\n") ||
		!strings.Contains(frame, `"eventType":"error"`) ||
		!strings.Contains(frame, `"operationRevision":"7"`) ||
		!strings.Contains(frame, `"code":"UNAVAILABLE"`) ||
		!strings.Contains(frame, `"requestId":"gateway_`) ||
		!strings.Contains(frame, `"retryable":true`) {
		t.Fatalf("error frame = %q", frame)
	}
	if strings.Contains(frame, "secret database detail") {
		t.Fatalf("error frame leaked internal status: %q", frame)
	}
	encoded.Reset()
	if err := writeSSEError(
		&encoded, "bad\ncursor", 7, emittedAt, status.Error(codes.Unavailable, "private"),
	); err == nil {
		t.Fatal("error frame accepted a cursor containing a control character")
	}
	if encoded.Len() != 0 {
		t.Fatalf("invalid cursor produced a partial SSE frame: %q", encoded.String())
	}
	if err := writeSSEError(&encoded, "", 7, emittedAt, status.Error(codes.Internal, "private")); err == nil {
		t.Fatal("error frame accepted an empty durable cursor")
	}
	if err := writeSSEError(&encoded, "durable-cursor-7", 0, emittedAt, status.Error(codes.Internal, "private")); err == nil {
		t.Fatal("error frame accepted a zero durable revision")
	}
}

func TestSSECursorContractAccepts4096BytesAndRejects4097(t *testing.T) {
	t.Parallel()
	cursor := strings.Repeat("x", 4096)
	var encoded strings.Builder
	if err := writeSSEError(
		&encoded, cursor, 17, time.Unix(20, 0).UTC(), status.Error(codes.DataLoss, "private history detail"),
	); err != nil {
		t.Fatal(err)
	}
	frame := encoded.String()
	if !strings.HasPrefix(frame, "id: "+cursor+"\nevent: error\n") ||
		!strings.Contains(frame, `"resumeCursor":"`+cursor+`"`) ||
		!strings.Contains(frame, `"code":"INTERNAL"`) {
		t.Fatalf("long cursor error frame was not preserved: length=%d", len(frame))
	}
	encoded.Reset()
	if err := writeSSEError(
		&encoded, cursor+"x", 17, time.Unix(20, 0).UTC(), status.Error(codes.DataLoss, "private history detail"),
	); err == nil {
		t.Fatal("4097-byte cursor was accepted")
	}
	if encoded.Len() != 0 {
		t.Fatalf("4097-byte cursor produced a partial frame: %q", encoded.String())
	}
}

type operationWatchNetworkFixture struct {
	apiv1.UnimplementedMindcladeServiceServer
	event            *apiv1.OperationEvent
	events           []*apiv1.OperationEvent
	afterEventError  error
	releaseEvent     <-chan struct{}
	preflightWaiting chan<- struct{}
	waitForCancel    bool
	cancelled        chan<- struct{}
}

func (f operationWatchNetworkFixture) WatchOperation(_ *apiv1.WatchOperationRequest, stream grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	values, _ := metadata.FromIncomingContext(stream.Context())
	events := f.events
	if f.event != nil {
		events = append([]*apiv1.OperationEvent{f.event}, events...)
	}
	if len(events) != 0 && f.releaseEvent != nil {
		if f.preflightWaiting != nil {
			close(f.preflightWaiting)
		}
		select {
		case <-f.releaseEvent:
		case <-stream.Context().Done():
			return status.FromContextError(stream.Context().Err()).Err()
		}
	}
	for _, event := range events {
		if first(values.Get("last-event-id")) == event.GetResumeCursor() {
			continue
		}
		if err := stream.Send(event); err != nil {
			return err
		}
	}
	if f.waitForCancel {
		<-stream.Context().Done()
		if f.cancelled != nil {
			close(f.cancelled)
		}
		return status.FromContextError(stream.Context().Err()).Err()
	}
	return f.afterEventError
}

func operationWatchGateway(t *testing.T, fixture operationWatchNetworkFixture) gateway {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	server := grpc.NewServer()
	apiv1.RegisterMindcladeServiceServer(server, fixture)
	serveResult := make(chan error, 1)
	go func() { serveResult <- server.Serve(listener) }()
	connection, err := grpc.NewClient(
		"passthrough:///operation-sse-network-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		server.Stop()
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = connection.Close()
		server.Stop()
		_ = listener.Close()
		if serveErr := <-serveResult; serveErr != nil && !errors.Is(serveErr, grpc.ErrServerStopped) {
			t.Errorf("serve operation watch fixture: %v", serveErr)
		}
	})
	return gateway{
		client: apiv1.NewMindcladeServiceClient(connection), clock: wallSSEClock{}, conn: connection,
		sseWriteDeadlineSetter: func(http.ResponseWriter, time.Time) error { return nil },
	}
}

func TestNewGatewayAcceptsGeneratedHTTPContracts(t *testing.T) {
	connection := operationWatchGateway(t, operationWatchNetworkFixture{}).conn
	configured, err := newGateway(connection, bearerAuthorizer{}, func(context.Context) error { return nil })
	if err != nil {
		t.Fatalf("construct gateway from generated HTTP contracts: %v", err)
	}
	if len(configured.routes) == 0 {
		t.Fatal("generated gateway has no routes")
	}
}

func operationWatchInput(name string) *dynamicpb.Message {
	input := dynamicpb.NewMessage((&apiv1.WatchOperationRequest{}).ProtoReflect().Descriptor())
	input.Set(input.Descriptor().Fields().ByName("name"), protoreflect.ValueOfString(name))
	return input
}

func TestNetworkSSEEmitsSafePost200ErrorAndTerminalReconnectIsExact(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	terminalCursor := "signed-terminal-cursor"
	terminal := operationSSEEvent(t, name, terminalCursor, 4, true)
	updated := operationSSEEvent(t, name, "signed-update-cursor", 3, false)
	failed := operationWatchGateway(t, operationWatchNetworkFixture{
		event: updated, afterEventError: status.Error(codes.Unavailable, "private backend failure"),
	})
	failedResponse := httptest.NewRecorder()
	failed.serveSSE(context.Background(), failedResponse, operationWatchInput(name), operationWatchContract(t).GetSse())
	if failedResponse.Code != 200 || !strings.Contains(failedResponse.Body.String(), "event: operation.updated") || !strings.Contains(failedResponse.Body.String(), "event: error") {
		t.Fatalf("failed stream response code=%d body=%q", failedResponse.Code, failedResponse.Body.String())
	}
	if strings.Contains(failedResponse.Body.String(), "private backend failure") {
		t.Fatal("post-200 error exposed a private backend message")
	}

	clean := operationWatchGateway(t, operationWatchNetworkFixture{event: terminal})
	firstResponse := httptest.NewRecorder()
	clean.serveSSE(context.Background(), firstResponse, operationWatchInput(name), operationWatchContract(t).GetSse())
	if strings.Count(firstResponse.Body.String(), "event: operation.terminal") != 1 {
		t.Fatalf("initial terminal stream = %q", firstResponse.Body.String())
	}
	if strings.Contains(firstResponse.Body.String(), "event: error") {
		t.Fatalf("terminal event was followed by an error frame: %q", firstResponse.Body.String())
	}
	reconnectContext := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("last-event-id", terminalCursor))
	reconnectResponse := httptest.NewRecorder()
	clean.serveSSE(reconnectContext, reconnectResponse, operationWatchInput(name), operationWatchContract(t).GetSse())
	if reconnectResponse.Code != http.StatusOK || reconnectResponse.Header().Get("Content-Type") != "text/event-stream" ||
		!strings.Contains(reconnectResponse.Body.String(), "retry: 3000\n\n") ||
		strings.Contains(reconnectResponse.Body.String(), "event:") {
		t.Fatalf("acknowledged terminal cursor replayed data: %q", reconnectResponse.Body.String())
	}
}

func TestSSEPreflightErrorsRemainHTTPProblems(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	tests := []struct {
		name       string
		fixture    operationWatchNetworkFixture
		statusCode int
		publicCode string
	}{
		{
			name: "expired cursor",
			fixture: operationWatchNetworkFixture{
				afterEventError: status.Error(codes.OutOfRange, "private retention detail"),
			},
			statusCode: http.StatusGone,
			publicCode: `"code":"FAILED_PRECONDITION"`,
		},
		{
			name:       "invalid initial event",
			fixture:    operationWatchNetworkFixture{event: operationSSEEvent(t, "wrong-operation", "cursor-1", 1, false)},
			statusCode: http.StatusInternalServerError,
			publicCode: `"code":"INTERNAL"`,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			preflightGateway := operationWatchGateway(t, test.fixture)
			response := httptest.NewRecorder()
			preflightGateway.serveSSE(context.Background(), response, operationWatchInput(name), operationWatchContract(t).GetSse())
			body := response.Body.String()
			if response.Code != test.statusCode || response.Header().Get("Content-Type") != "application/problem+json" ||
				!strings.Contains(body, test.publicCode) {
				t.Fatalf("preflight response code=%d headers=%v body=%q", response.Code, response.Header(), body)
			}
			if strings.Contains(body, "retry:") || strings.Contains(body, "private retention detail") ||
				strings.Contains(body, "wrong-operation") {
				t.Fatalf("preflight response leaked SSE or upstream detail: %q", body)
			}
		})
	}
}

func TestSSEPreflightEOFStartsAndClosesCleanStream(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	preflightGateway := operationWatchGateway(t, operationWatchNetworkFixture{})
	response := httptest.NewRecorder()
	preflightGateway.serveSSE(context.Background(), response, operationWatchInput(name), operationWatchContract(t).GetSse())
	if response.Code != http.StatusOK || response.Header().Get("Content-Type") != "text/event-stream" ||
		response.Header().Get("Cache-Control") != "no-store" ||
		response.Header().Get("X-Accel-Buffering") != "no" ||
		response.Body.String() != "retry: 3000\n\n" {
		t.Fatalf("clean empty SSE response code=%d headers=%v body=%q", response.Code, response.Header(), response.Body.String())
	}
}

func TestNetworkSSERejectsInvalidEventWithSafePost200Error(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	valid := operationSSEEvent(t, name, "durable-cursor-1", 1, false)
	invalid := operationSSEEvent(t, name, "cursor\ninjection", 2, false)
	watchGateway := operationWatchGateway(t, operationWatchNetworkFixture{events: []*apiv1.OperationEvent{valid, invalid}})
	response := httptest.NewRecorder()
	watchGateway.serveSSE(context.Background(), response, operationWatchInput(name), operationWatchContract(t).GetSse())
	body := response.Body.String()
	if response.Code != http.StatusOK || !strings.Contains(body, "event: error\n") ||
		!strings.Contains(body, "id: durable-cursor-1\nevent: error\n") ||
		!strings.Contains(body, `"eventType":"error"`) ||
		!strings.Contains(body, `"operationRevision":"1"`) ||
		!strings.Contains(body, `"code":"INTERNAL"`) {
		t.Fatalf("invalid event response code=%d body=%q", response.Code, body)
	}
	if strings.Contains(body, "cursor\ninjection") || strings.Contains(body, "invalid operation event") {
		t.Fatalf("invalid event metadata reached the SSE stream: %q", body)
	}
}

func TestNetworkSSEPreencodesBeforeCommitAndCursorAdvance(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	invalidFirst := operationSSEEvent(t, name, "cursor-1", 1, false)
	invalidFirst.Operation.Etag = string([]byte{0xff})
	preflightGateway := operationWatchGateway(t, operationWatchNetworkFixture{event: invalidFirst})
	preflightResponse := httptest.NewRecorder()
	preflightGateway.serveSSE(
		context.Background(), preflightResponse, operationWatchInput(name), operationWatchContract(t).GetSse(),
	)
	if preflightResponse.Code != http.StatusInternalServerError ||
		preflightResponse.Header().Get("Content-Type") != "application/problem+json" ||
		strings.Contains(preflightResponse.Body.String(), "retry:") {
		t.Fatalf("unencodable preflight event committed SSE: code=%d body=%q", preflightResponse.Code, preflightResponse.Body.String())
	}

	first := operationSSEEvent(t, name, "cursor-1", 1, false)
	invalidSecond := operationSSEEvent(t, name, "cursor-2", 2, false)
	invalidSecond.Operation.Etag = string([]byte{0xff})
	commitGateway := operationWatchGateway(t, operationWatchNetworkFixture{
		events: []*apiv1.OperationEvent{first, invalidSecond},
	})
	response := httptest.NewRecorder()
	commitGateway.serveSSE(context.Background(), response, operationWatchInput(name), operationWatchContract(t).GetSse())
	body := response.Body.String()
	if response.Code != http.StatusOK ||
		strings.Count(body, "event: operation.updated\n") != 1 ||
		!strings.Contains(body, "id: cursor-1\nevent: error\n") ||
		strings.Contains(body, "id: cursor-2\n") {
		t.Fatalf("unencodable subsequent event advanced durable cursor: %q", body)
	}
}

type manualSSETicker struct {
	ticks    chan time.Time
	stopped  chan struct{}
	stopOnce sync.Once
}

func (ticker *manualSSETicker) C() <-chan time.Time { return ticker.ticks }

func (ticker *manualSSETicker) Stop() {
	ticker.stopOnce.Do(func() { close(ticker.stopped) })
}

type manualSSEClock struct {
	intervals chan time.Duration
	now       time.Time
	ticker    *manualSSETicker
}

func (clock manualSSEClock) NewTicker(interval time.Duration) sseTicker {
	clock.intervals <- interval
	return clock.ticker
}

func (clock manualSSEClock) Now() time.Time {
	if clock.now.IsZero() {
		return time.Unix(1, 0).UTC()
	}
	return clock.now.UTC()
}

type notifyingSSEWriter struct {
	*httptest.ResponseRecorder
	heartbeat  chan struct{}
	updated    chan struct{}
	heartOnce  sync.Once
	updateOnce sync.Once
}

func (writer *notifyingSSEWriter) Write(payload []byte) (int, error) {
	written, err := writer.ResponseRecorder.Write(payload)
	value := string(payload)
	if strings.Contains(value, "event: operation.updated") {
		writer.updateOnce.Do(func() { close(writer.updated) })
	}
	if strings.Contains(value, "event: heartbeat") {
		writer.heartOnce.Do(func() { close(writer.heartbeat) })
	}
	return written, err
}

type failingSSEWriter struct {
	body        strings.Builder
	header      http.Header
	statusCode  int
	writes      int
	failOnWrite int
}

func (writer *failingSSEWriter) Header() http.Header {
	if writer.header == nil {
		writer.header = make(http.Header)
	}
	return writer.header
}

func (writer *failingSSEWriter) WriteHeader(statusCode int) { writer.statusCode = statusCode }

func (writer *failingSSEWriter) Write(payload []byte) (int, error) {
	writer.writes++
	if writer.writes == writer.failOnWrite {
		return 0, errors.New("injected writer failure")
	}
	return writer.body.Write(payload)
}

func (*failingSSEWriter) Flush() {}

type nonFlushingResponseWriter struct {
	recorder *httptest.ResponseRecorder
}

func (writer *nonFlushingResponseWriter) Header() http.Header { return writer.recorder.Header() }

func (writer *nonFlushingResponseWriter) WriteHeader(statusCode int) {
	writer.recorder.WriteHeader(statusCode)
}

func (writer *nonFlushingResponseWriter) Write(payload []byte) (int, error) {
	return writer.recorder.Write(payload)
}

type deadlineBlockingSSEWriter struct {
	body         strings.Builder
	deadline     time.Time
	deadlines    []time.Time
	header       http.Header
	statusCode   int
	writes       int
	blockOnWrite int
}

func (writer *deadlineBlockingSSEWriter) Header() http.Header {
	if writer.header == nil {
		writer.header = make(http.Header)
	}
	return writer.header
}

func (writer *deadlineBlockingSSEWriter) WriteHeader(statusCode int) { writer.statusCode = statusCode }

func (writer *deadlineBlockingSSEWriter) SetWriteDeadline(deadline time.Time) error {
	writer.deadline = deadline
	writer.deadlines = append(writer.deadlines, deadline)
	return nil
}

func (writer *deadlineBlockingSSEWriter) Write(payload []byte) (int, error) {
	writer.writes++
	if writer.writes == writer.blockOnWrite {
		delay := time.Until(writer.deadline)
		if delay > 0 {
			timer := time.NewTimer(delay)
			defer timer.Stop()
			<-timer.C
		}
		return 0, errors.New("simulated write deadline exceeded")
	}
	return writer.body.Write(payload)
}

func (*deadlineBlockingSSEWriter) Flush() {}

func TestSSEWithoutFlushCapabilityReturnsDocumentedInternalError(t *testing.T) {
	writer := &nonFlushingResponseWriter{recorder: httptest.NewRecorder()}
	(&gateway{}).serveSSE(
		context.Background(), writer, operationWatchInput("tenants/t-1/projects/p-1/operations/op-1"),
		operationWatchContract(t).GetSse(),
	)
	if writer.recorder.Code != http.StatusInternalServerError ||
		!strings.Contains(writer.recorder.Body.String(), `"code":"INTERNAL"`) {
		t.Fatalf("non-flushing response code=%d body=%q", writer.recorder.Code, writer.recorder.Body.String())
	}
}

func TestSSEFrameWriteDeadlineHasProductionDefault(t *testing.T) {
	t.Parallel()
	var deadline time.Time
	deadlineGateway := gateway{sseWriteDeadlineSetter: func(_ http.ResponseWriter, value time.Time) error {
		deadline = value
		return nil
	}}
	before := time.Now().UTC()
	if err := deadlineGateway.setSSEFrameWriteDeadline(httptest.NewRecorder()); err != nil {
		t.Fatal(err)
	}
	after := time.Now().UTC()
	if deadline.Before(before.Add(defaultSSEFrameWriteTimeout)) ||
		deadline.After(after.Add(defaultSSEFrameWriteTimeout)) {
		t.Fatalf("default SSE deadline=%s before=%s after=%s", deadline, before, after)
	}
}

func TestSSEFrameWriteDeadlineBoundsSlowClientAndCancelsUpstream(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	cancelled := make(chan struct{})
	gateway := operationWatchGateway(t, operationWatchNetworkFixture{
		event: operationSSEEvent(t, name, "cursor-1", 1, false), waitForCancel: true, cancelled: cancelled,
	})
	gateway.sseWriteDeadlineSetter = nil
	gateway.sseFrameWriteTimeout = 25 * time.Millisecond
	writer := &deadlineBlockingSSEWriter{blockOnWrite: 2}
	started := time.Now()
	gateway.serveSSE(context.Background(), writer, operationWatchInput(name), operationWatchContract(t).GetSse())
	if writer.statusCode != http.StatusOK || writer.writes != 2 || len(writer.deadlines) < 2 {
		t.Fatalf("slow writer status=%d writes=%d deadlines=%d", writer.statusCode, writer.writes, len(writer.deadlines))
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("slow writer remained blocked for %s", elapsed)
	}
	select {
	case <-cancelled:
	case <-time.After(5 * time.Second):
		t.Fatal("upstream stream did not observe cancellation after the write deadline")
	}
}

func TestSSEWriterFailureCancelsPreflightStream(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	cancelled := make(chan struct{})
	gateway := operationWatchGateway(t, operationWatchNetworkFixture{
		event: operationSSEEvent(t, name, "cursor-1", 1, false), waitForCancel: true, cancelled: cancelled,
	})
	writer := &failingSSEWriter{failOnWrite: 2}
	gateway.serveSSE(context.Background(), writer, operationWatchInput(name), operationWatchContract(t).GetSse())
	if writer.statusCode != http.StatusOK || writer.writes != 2 || writer.body.String() != "retry: 3000\n\n" {
		t.Fatalf("failed writer status=%d writes=%d body=%q", writer.statusCode, writer.writes, writer.body.String())
	}
	select {
	case <-cancelled:
	case <-time.After(5 * time.Second):
		t.Fatal("upstream stream did not observe cancellation after writer failure")
	}
}

func TestSSENeverHeartbeatsBeforeDurableCursor(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	releaseEvent := make(chan struct{})
	preflightWaiting := make(chan struct{})
	cancelled := make(chan struct{})
	gateway := operationWatchGateway(t, operationWatchNetworkFixture{
		event: operationSSEEvent(t, name, "cursor-2", 2, false), releaseEvent: releaseEvent,
		preflightWaiting: preflightWaiting, waitForCancel: true, cancelled: cancelled,
	})
	ticker := &manualSSETicker{
		ticks: make(chan time.Time, 1), stopped: make(chan struct{}),
	}
	intervals := make(chan time.Duration, 1)
	gateway.clock = manualSSEClock{intervals: intervals, ticker: ticker}
	response := &notifyingSSEWriter{
		ResponseRecorder: httptest.NewRecorder(),
		heartbeat:        make(chan struct{}),
		updated:          make(chan struct{}),
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	policy := operationWatchContract(t).GetSse()
	done := make(chan struct{})
	go func() {
		gateway.serveSSE(ctx, response, operationWatchInput(name), policy)
		close(done)
	}()

	select {
	case <-preflightWaiting:
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not enter first-event preflight")
	}
	select {
	case interval := <-intervals:
		t.Fatalf("SSE handler created %s ticker before durable cursor truth", interval)
	default:
	}
	if response.Header().Get("Content-Type") != "" || response.Body.Len() != 0 {
		t.Fatalf("SSE handler committed before durable cursor truth: headers=%v body=%q", response.Header(), response.Body.String())
	}
	close(releaseEvent)
	select {
	case <-response.updated:
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not emit the released durable event")
	}
	select {
	case interval := <-intervals:
		if interval != 15*time.Second {
			t.Fatalf("heartbeat interval = %s", interval)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not create its post-preflight heartbeat ticker")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not stop after cancellation")
	}
	select {
	case <-cancelled:
	case <-time.After(5 * time.Second):
		t.Fatal("upstream stream did not observe cancellation")
	}
	if strings.Contains(response.Body.String(), "event: heartbeat") ||
		!strings.Contains(response.Body.String(), "event: operation.updated") {
		t.Fatalf("unexpected preflight SSE response: %q", response.Body.String())
	}
}

func TestSSEUsesDescriptorHeartbeatPolicyAndCleansUpOnCancellation(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	cancelled := make(chan struct{})
	gateway := operationWatchGateway(t, operationWatchNetworkFixture{
		event: operationSSEEvent(t, name, "cursor-2", 2, false), waitForCancel: true, cancelled: cancelled,
	})
	ticker := &manualSSETicker{
		ticks: make(chan time.Time, 1), stopped: make(chan struct{}),
	}
	intervals := make(chan time.Duration, 1)
	gateway.clock = manualSSEClock{intervals: intervals, ticker: ticker}
	response := &notifyingSSEWriter{
		ResponseRecorder: httptest.NewRecorder(),
		heartbeat:        make(chan struct{}),
		updated:          make(chan struct{}),
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	policy := operationWatchContract(t).GetSse()
	input := operationWatchInput(name)
	done := make(chan struct{})
	go func() {
		gateway.serveSSE(ctx, response, input, policy)
		close(done)
	}()

	select {
	case interval := <-intervals:
		if interval != 15*time.Second {
			t.Fatalf("heartbeat interval = %s", interval)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not create its heartbeat ticker")
	}
	select {
	case <-response.updated:
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not emit the durable application event")
	}
	ticker.ticks <- time.Unix(20, 0).UTC()
	select {
	case <-response.heartbeat:
	case <-time.After(5 * time.Second):
		t.Fatal("SSE handler did not emit a heartbeat")
	}
	cancel()
	for label, signal := range map[string]<-chan struct{}{
		"handler": done, "upstream stream": cancelled, "heartbeat ticker": ticker.stopped,
	} {
		select {
		case <-signal:
		case <-time.After(5 * time.Second):
			t.Fatalf("%s was not cleaned up after cancellation", label)
		}
	}
	body := response.Body.String()
	if !strings.Contains(body, "retry: 3000\n\n") ||
		!strings.Contains(body, "id: cursor-2\nevent: heartbeat\n") ||
		!strings.Contains(body, `"operationRevision":"2"`) {
		t.Fatalf("descriptor-owned SSE frames = %q", body)
	}
}
