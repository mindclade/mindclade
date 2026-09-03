package mindclade

import (
	"context"
	"net"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
)

type datasetLifecycleServer struct {
	internaldatasetv1.UnimplementedDatasetServiceServer
	created *datasetv1.CreateDatasetCommand
}

func (*datasetLifecycleServer) operation(id string) *jobv1.Operation {
	return &jobv1.Operation{OperationId: id}
}

func (server *datasetLifecycleServer) CreateDataset(_ context.Context, request *internaldatasetv1.CreateDatasetRequest) (*internaldatasetv1.CreateDatasetResponse, error) {
	server.created = cloneGenerated(request.GetCommand())
	return &internaldatasetv1.CreateDatasetResponse{Operation: server.operation("operations/dataset-create")}, nil
}

func (server *datasetLifecycleServer) GetDataset(context.Context, *internaldatasetv1.GetDatasetRequest) (*internaldatasetv1.GetDatasetResponse, error) {
	return &internaldatasetv1.GetDatasetResponse{Dataset: &datasetv1.Dataset{Name: "tenants/tenant-a/projects/project-a/datasets/dataset-1"}}, nil
}

func (server *datasetLifecycleServer) ListDatasets(_ context.Context, request *internaldatasetv1.ListDatasetsRequest) (*internaldatasetv1.ListDatasetsResponse, error) {
	return &internaldatasetv1.ListDatasetsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-out"}}, nil
}

func (server *datasetLifecycleServer) UpdateDataset(context.Context, *internaldatasetv1.UpdateDatasetRequest) (*internaldatasetv1.UpdateDatasetResponse, error) {
	return &internaldatasetv1.UpdateDatasetResponse{Operation: server.operation("operations/dataset-update")}, nil
}

func (server *datasetLifecycleServer) PublishDatasetRelease(context.Context, *internaldatasetv1.PublishDatasetReleaseRequest) (*internaldatasetv1.PublishDatasetReleaseResponse, error) {
	return &internaldatasetv1.PublishDatasetReleaseResponse{Operation: server.operation("operations/dataset-publish")}, nil
}

func (server *datasetLifecycleServer) RevokeDatasetRelease(context.Context, *internaldatasetv1.RevokeDatasetReleaseRequest) (*internaldatasetv1.RevokeDatasetReleaseResponse, error) {
	return &internaldatasetv1.RevokeDatasetReleaseResponse{Operation: server.operation("operations/dataset-revoke")}, nil
}

func (*datasetLifecycleServer) GetDatasetRelease(context.Context, *internaldatasetv1.GetDatasetReleaseRequest) (*internaldatasetv1.GetDatasetReleaseResponse, error) {
	return &internaldatasetv1.GetDatasetReleaseResponse{DatasetRelease: &datasetv1.DatasetRelease{Name: "tenants/tenant-a/projects/project-a/datasets/dataset-1/releases/v1"}}, nil
}

func (*datasetLifecycleServer) ListDatasetReleases(context.Context, *internaldatasetv1.ListDatasetReleasesRequest) (*internaldatasetv1.ListDatasetReleasesResponse, error) {
	return &internaldatasetv1.ListDatasetReleasesResponse{Page: &commonv1.PageResponse{NextPageToken: "release-out"}}, nil
}

type modelLifecycleServer struct {
	internalmodelv1.UnimplementedModelServiceServer
	registered *modelv1.RegisterModelCommand
}

func (*modelLifecycleServer) operation(id string) *jobv1.Operation {
	return &jobv1.Operation{OperationId: id}
}

func (server *modelLifecycleServer) RegisterModel(_ context.Context, request *internalmodelv1.RegisterModelRequest) (*internalmodelv1.RegisterModelResponse, error) {
	server.registered = cloneGenerated(request.GetCommand())
	return &internalmodelv1.RegisterModelResponse{Operation: server.operation("operations/model-register")}, nil
}

func (*modelLifecycleServer) GetModel(context.Context, *internalmodelv1.GetModelRequest) (*internalmodelv1.GetModelResponse, error) {
	return &internalmodelv1.GetModelResponse{Model: &modelv1.Model{Name: "tenants/tenant-a/projects/project-a/models/model-1"}}, nil
}

func (*modelLifecycleServer) ListModels(_ context.Context, request *internalmodelv1.ListModelsRequest) (*internalmodelv1.ListModelsResponse, error) {
	return &internalmodelv1.ListModelsResponse{Page: &commonv1.PageResponse{NextPageToken: request.GetPage().GetPageToken() + "-out"}}, nil
}

func (server *modelLifecycleServer) RegisterModelRelease(context.Context, *internalmodelv1.RegisterModelReleaseRequest) (*internalmodelv1.RegisterModelReleaseResponse, error) {
	return &internalmodelv1.RegisterModelReleaseResponse{Operation: server.operation("operations/model-release")}, nil
}

func (*modelLifecycleServer) GetModelRelease(context.Context, *internalmodelv1.GetModelReleaseRequest) (*internalmodelv1.GetModelReleaseResponse, error) {
	return &internalmodelv1.GetModelReleaseResponse{ModelRelease: &modelv1.ModelRelease{Name: "tenants/tenant-a/projects/project-a/models/model-1/releases/v1"}}, nil
}

func (*modelLifecycleServer) ListModelReleases(context.Context, *internalmodelv1.ListModelReleasesRequest) (*internalmodelv1.ListModelReleasesResponse, error) {
	return &internalmodelv1.ListModelReleasesResponse{Page: &commonv1.PageResponse{NextPageToken: "model-release-out"}}, nil
}

func (server *modelLifecycleServer) PromoteModelRelease(context.Context, *internalmodelv1.PromoteModelReleaseRequest) (*internalmodelv1.PromoteModelReleaseResponse, error) {
	return &internalmodelv1.PromoteModelReleaseResponse{Operation: server.operation("operations/model-promote")}, nil
}

func (server *modelLifecycleServer) RevokeModelRelease(context.Context, *internalmodelv1.RevokeModelReleaseRequest) (*internalmodelv1.RevokeModelReleaseResponse, error) {
	return &internalmodelv1.RevokeModelReleaseResponse{Operation: server.operation("operations/model-revoke")}, nil
}

func TestDatasetAndModelFacadesUseGeneratedContracts(t *testing.T) {
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	datasets, models := &datasetLifecycleServer{}, &modelLifecycleServer{}
	internaldatasetv1.RegisterDatasetServiceServer(grpcServer, datasets)
	internalmodelv1.RegisterModelServiceServer(grpcServer, models)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(grpcServer.Stop)
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := &Client{config: defaultConfig()}
	client.config.TenantID, client.config.ProjectID, client.config.PrincipalID, client.config.DefaultRPCTimeout = "tenant-a", "project-a", "principal-a", time.Second
	client.Datasets = &DatasetService{client: client, transport: internaldatasetv1.NewDatasetServiceClient(connection)}
	client.Models = &ModelService{client: client, transport: internalmodelv1.NewModelServiceClient(connection)}
	parent := "tenants/tenant-a/projects/project-a"
	datasetName, datasetRelease := parent+"/datasets/dataset-1", parent+"/datasets/dataset-1/releases/v1"
	modelName, modelRelease := parent+"/models/model-1", parent+"/models/model-1/releases/v1"
	if _, err = client.Datasets.Create(context.Background(), &datasetv1.CreateDatasetCommand{DatasetId: "dataset-1", Context: &commonv1.CommandContext{PrincipalId: "forged"}}, WithIdempotencyKey("dataset-create-1")); err != nil {
		t.Fatal(err)
	}
	if datasets.created.GetContext().GetPrincipalId() != "principal-a" || datasets.created.GetContext().GetIdempotencyKey() != "dataset-create-1" || datasets.created.GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatalf("untrusted dataset context was not replaced: %v", datasets.created.GetContext())
	}
	page, err := client.Datasets.List(context.Background(), &internaldatasetv1.ListDatasetsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}})
	if err != nil || page.GetPage().GetNextPageToken() != "opaque-out" {
		t.Fatalf("dataset page=%v err=%v", page, err)
	}
	if dataset, getErr := client.Datasets.Get(context.Background(), datasetName, "etag"); getErr != nil || dataset.GetName() != datasetName {
		t.Fatalf("dataset=%v err=%v", dataset, getErr)
	}
	if _, err = client.Datasets.Update(context.Background(), &datasetv1.UpdateDatasetCommand{Dataset: &datasetv1.Dataset{Name: datasetName}, Etag: "etag"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Datasets.PublishRelease(context.Background(), &datasetv1.PublishDatasetReleaseCommand{Dataset: &commonv1.ResourceRef{ResourceType: "dataset", Name: datasetName}, ReleaseId: "v1"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Datasets.RevokeRelease(context.Background(), &datasetv1.RevokeDatasetReleaseCommand{DatasetRelease: &commonv1.ResourceRef{ResourceType: "dataset_release", Name: datasetRelease}, Etag: "etag", Reason: "superseded"}); err != nil {
		t.Fatal(err)
	}
	if release, getErr := client.Datasets.GetRelease(context.Background(), datasetRelease); getErr != nil || release.GetName() != datasetRelease {
		t.Fatalf("dataset release=%v err=%v", release, getErr)
	}
	if releases, listErr := client.Datasets.ListReleases(context.Background(), &internaldatasetv1.ListDatasetReleasesRequest{Parent: datasetName, Page: &commonv1.PageRequest{PageToken: "release-cursor"}}); listErr != nil || releases.GetPage().GetNextPageToken() != "release-out" {
		t.Fatalf("dataset releases=%v err=%v", releases, listErr)
	}
	if _, err = client.Models.Register(context.Background(), &modelv1.RegisterModelCommand{ModelId: "model-1", Context: &commonv1.CommandContext{PrincipalId: "forged"}}, WithIdempotencyKey("model-register-1")); err != nil {
		t.Fatal(err)
	}
	if models.registered.GetContext().GetPrincipalId() != "principal-a" || models.registered.GetContext().GetIdempotencyKey() != "model-register-1" {
		t.Fatalf("untrusted model context was not replaced: %v", models.registered.GetContext())
	}
	modelPage, err := client.Models.List(context.Background(), &internalmodelv1.ListModelsRequest{Page: &commonv1.PageRequest{PageToken: "opaque"}})
	if err != nil || modelPage.GetPage().GetNextPageToken() != "opaque-out" {
		t.Fatalf("model page=%v err=%v", modelPage, err)
	}
	if model, getErr := client.Models.Get(context.Background(), modelName, "etag"); getErr != nil || model.GetName() != modelName {
		t.Fatalf("model=%v err=%v", model, getErr)
	}
	if _, err = client.Models.RegisterRelease(context.Background(), &modelv1.RegisterModelReleaseCommand{Model: &commonv1.ResourceRef{ResourceType: "model", Name: modelName}, ReleaseId: "v1"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Models.PromoteRelease(context.Background(), &modelv1.PromoteModelReleaseCommand{ModelRelease: &commonv1.ResourceRef{ResourceType: "model_release", Name: modelRelease}, Etag: "etag"}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.Models.RevokeRelease(context.Background(), &modelv1.RevokeModelReleaseCommand{ModelRelease: &commonv1.ResourceRef{ResourceType: "model_release", Name: modelRelease}, Etag: "etag", Reason: "unsafe"}); err != nil {
		t.Fatal(err)
	}
	if release, getErr := client.Models.GetRelease(context.Background(), modelRelease); getErr != nil || release.GetName() != modelRelease {
		t.Fatalf("model release=%v err=%v", release, getErr)
	}
	if releases, listErr := client.Models.ListReleases(context.Background(), &internalmodelv1.ListModelReleasesRequest{Parent: modelName, Page: &commonv1.PageRequest{PageToken: "release-cursor"}}); listErr != nil || releases.GetPage().GetNextPageToken() != "model-release-out" {
		t.Fatalf("model releases=%v err=%v", releases, listErr)
	}
}
