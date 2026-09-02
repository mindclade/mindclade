package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/http/httptest"
	"slices"
	"sort"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	trainingapp "github.com/mindclade/mindclade/services/control_plane/internal/training"
)

const generatedServiceCount = 15

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

type activatedSchedulerFoundation struct{ unavailableTrainingFoundation }

func (activatedSchedulerFoundation) InternalJobServer() internaljobv1.JobServiceServer {
	return activatedJobServer{}
}

func (activatedSchedulerFoundation) InternalRunServer() internaljobv1.RunServiceServer {
	return activatedRunServer{}
}

func (activatedArtifactServer) GetArtifact(context.Context, *internalartifactv1.GetArtifactRequest) (*internalartifactv1.GetArtifactResponse, error) {
	return &internalartifactv1.GetArtifactResponse{Artifact: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/octet-stream"}}, nil
}

func TestRegisterGeneratedServicesCoversDescriptorEstate(t *testing.T) {
	t.Parallel()

	server := grpc.NewServer()
	if err := registerGeneratedServices(server, runtimeDependencies{Training: unavailableTrainingFoundation{}}); err != nil {
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
	err := registerGeneratedServices(grpc.NewServer(), runtimeDependencies{
		Training: unavailableTrainingFoundation{},
		Dataset:  datasetServer,
	})
	if err == nil || !strings.Contains(err.Error(), "typed nil") {
		t.Fatalf("register typed-nil dataset dependency error = %v, want typed-nil rejection", err)
	}
}

func TestRegisterGeneratedServicesActivatesArtifactImplementation(t *testing.T) {
	t.Parallel()
	server := grpc.NewServer()
	if err := registerGeneratedServices(server, runtimeDependencies{Training: unavailableTrainingFoundation{}, Artifact: activatedArtifactServer{}}); err != nil {
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
	if err := registerGeneratedServices(server, runtimeDependencies{Training: activatedSchedulerFoundation{}}); err != nil {
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

func TestInactiveGeneratedServicesReturnMethodUnimplemented(t *testing.T) {
	t.Parallel()

	server := grpc.NewServer()
	if err := registerGeneratedServices(server, runtimeDependencies{
		Training:   unavailableTrainingFoundation{},
		Dataset:    activatedDatasetServer{},
		Evaluation: activatedEvaluationServer{},
		Model:      activatedModelServer{},
	}); err != nil {
		t.Fatalf("register generated services: %v", err)
	}
	listener := bufconn.Listen(1 << 20)
	serveResult := make(chan error, 1)
	go func() {
		serveResult <- server.Serve(listener)
	}()
	t.Cleanup(func() {
		server.Stop()
		_ = listener.Close()
		if err := <-serveResult; err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			t.Errorf("serve registered services: %v", err)
		}
	})

	dialer := func(context.Context, string) (net.Conn, error) {
		return listener.Dial()
	}
	connection, err := grpc.NewClient(
		"passthrough:///control-plane-registration-test",
		grpc.WithContextDialer(dialer),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("create in-memory client: %v", err)
	}
	t.Cleanup(func() {
		if err := connection.Close(); err != nil {
			t.Errorf("close in-memory client: %v", err)
		}
	})

	// The first file is the partially implemented public facade. Every service
	// in the remaining internal descriptor files is intentionally inactive and
	// must route to its generated method-specific fail-closed implementation.
	for _, file := range generatedGRPCFiles[1:] {
		services := file.Services()
		for serviceIndex := 0; serviceIndex < services.Len(); serviceIndex++ {
			service := services.Get(serviceIndex)
			if service.FullName() == "mindclade.internal.dataset.v1.DatasetService" || service.FullName() == "mindclade.internal.evaluation.v1.EvaluationService" || service.FullName() == "mindclade.internal.model.v1.ModelService" {
				continue
			}
			method := firstUnaryMethod(t, service)
			t.Run(string(service.FullName()), func(t *testing.T) {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				fullMethod := "/" + string(service.FullName()) + "/" + string(method.Name())
				err := connection.Invoke(
					ctx,
					fullMethod,
					dynamicpb.NewMessage(method.Input()),
					dynamicpb.NewMessage(method.Output()),
				)
				grpcStatus := status.Convert(err)
				if grpcStatus.Code() != codes.Unimplemented {
					t.Fatalf("%s code = %s, want %s: %v", fullMethod, grpcStatus.Code(), codes.Unimplemented, err)
				}
				wantMessage := fmt.Sprintf("method %s not implemented", method.Name())
				if grpcStatus.Message() != wantMessage {
					t.Fatalf("%s message = %q, want generated fail-closed message %q", fullMethod, grpcStatus.Message(), wantMessage)
				}
				if strings.Contains(grpcStatus.Message(), "unknown service") ||
					strings.Contains(grpcStatus.Message(), "unknown method") {
					t.Fatalf("%s reached the gRPC unknown-service fallback: %q", fullMethod, grpcStatus.Message())
				}
			})
		}
	}
}

func TestRegisterGeneratedServicesActivatesDatasetAndModelImplementations(t *testing.T) {
	t.Parallel()
	server := grpc.NewServer()
	if err := registerGeneratedServices(server, runtimeDependencies{
		Training:   unavailableTrainingFoundation{},
		Dataset:    activatedDatasetServer{},
		Evaluation: activatedEvaluationServer{},
		Model:      activatedModelServer{},
	}); err != nil {
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
	public := publicTrainingRun(internal)
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
	operation := &jobv1.Operation{
		OperationId: "operations/op-01", TenantId: "tenant-01", ProjectId: "project-01",
		ResourceVersion: 9, State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true,
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
	if err := writeSSEError(&encoded, "durable-cursor-7", status.Error(codes.Unavailable, "secret database detail")); err != nil {
		t.Fatal(err)
	}
	frame := encoded.String()
	if !strings.Contains(frame, "id: durable-cursor-7\nevent: error\n") || !strings.Contains(frame, `"code":"UNAVAILABLE"`) || !strings.Contains(frame, `"retryable":true`) {
		t.Fatalf("error frame = %q", frame)
	}
	if strings.Contains(frame, "secret database detail") {
		t.Fatalf("error frame leaked internal status: %q", frame)
	}
}

type operationWatchNetworkFixture struct {
	apiv1.UnimplementedMindcladeServiceServer
	event           *apiv1.OperationEvent
	afterEventError error
}

func (f operationWatchNetworkFixture) WatchOperation(_ *apiv1.WatchOperationRequest, stream grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	values, _ := metadata.FromIncomingContext(stream.Context())
	if f.event != nil && first(values.Get("last-event-id")) != f.event.GetResumeCursor() {
		if err := stream.Send(f.event); err != nil {
			return err
		}
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
	return gateway{client: apiv1.NewMindcladeServiceClient(connection), conn: connection}
}

func operationWatchInput(name string) *dynamicpb.Message {
	input := dynamicpb.NewMessage((&apiv1.WatchOperationRequest{}).ProtoReflect().Descriptor())
	input.Set(input.Descriptor().Fields().ByName("name"), protoreflect.ValueOfString(name))
	return input
}

func TestNetworkSSEEmitsSafePost200ErrorAndTerminalReconnectIsExact(t *testing.T) {
	name := "tenants/t-1/projects/p-1/operations/op-1"
	terminalCursor := "signed-terminal-cursor"
	terminal := &apiv1.OperationEvent{
		EventId: terminalCursor, EventType: "operation.terminal", SchemaVersion: 1,
		OperationRevision: 4, ResumeCursor: terminalCursor, EmittedAt: timestamppb.New(time.Now().UTC()),
	}
	failed := operationWatchGateway(t, operationWatchNetworkFixture{
		event: terminal, afterEventError: status.Error(codes.Unavailable, "private backend failure"),
	})
	failedResponse := httptest.NewRecorder()
	failed.serveSSE(context.Background(), failedResponse, operationWatchInput(name))
	if failedResponse.Code != 200 || !strings.Contains(failedResponse.Body.String(), "event: operation.terminal") || !strings.Contains(failedResponse.Body.String(), "event: error") {
		t.Fatalf("failed stream response code=%d body=%q", failedResponse.Code, failedResponse.Body.String())
	}
	if strings.Contains(failedResponse.Body.String(), "private backend failure") {
		t.Fatal("post-200 error exposed a private backend message")
	}

	clean := operationWatchGateway(t, operationWatchNetworkFixture{event: terminal})
	firstResponse := httptest.NewRecorder()
	clean.serveSSE(context.Background(), firstResponse, operationWatchInput(name))
	if strings.Count(firstResponse.Body.String(), "event: operation.terminal") != 1 {
		t.Fatalf("initial terminal stream = %q", firstResponse.Body.String())
	}
	reconnectContext := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("last-event-id", terminalCursor))
	reconnectResponse := httptest.NewRecorder()
	clean.serveSSE(reconnectContext, reconnectResponse, operationWatchInput(name))
	if strings.Contains(reconnectResponse.Body.String(), "event: operation.terminal") || strings.Contains(reconnectResponse.Body.String(), "event: error") {
		t.Fatalf("acknowledged terminal cursor replayed data: %q", reconnectResponse.Body.String())
	}
}

func firstUnaryMethod(t *testing.T, service protoreflect.ServiceDescriptor) protoreflect.MethodDescriptor {
	t.Helper()
	methods := service.Methods()
	for index := 0; index < methods.Len(); index++ {
		method := methods.Get(index)
		if !method.IsStreamingClient() && !method.IsStreamingServer() {
			return method
		}
	}
	t.Fatalf("%s has no unary method for registration conformance", service.FullName())
	return nil
}
