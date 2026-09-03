package mindclade

import (
	"context"
	"strings"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

// DatasetService is the private lifecycle façade over the generated dataset
// client. Its boundary contains generated protobuf resources and commands
// only; it owns client behavior such as trusted command context, deadlines,
// retries, idempotency, pagination, and normalized errors.
type DatasetService struct {
	client    *Client
	transport internaldatasetv1.DatasetServiceClient
}

func (service *DatasetService) Create(ctx context.Context, command *datasetv1.CreateDatasetCommand, options ...RequestOption) (*operationv1.Operation, error) {
	if command == nil {
		return nil, invalidArgument("a generated CreateDatasetCommand is required")
	}
	materialized := cloneGenerated(command)
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
	if materialized.Project == nil {
		materialized.Project = projectResource(service.client.config)
	} else if materialized.GetProject().GetName() != projectName(service.client.config.TenantID, service.client.config.ProjectID) {
		return nil, invalidArgument("dataset project must match the configured project")
	}
	callContext, request, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(materialized)
	if err != nil {
		return nil, err
	}
	materialized.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.CreateDataset(callContext, &internaldatasetv1.CreateDatasetRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "CreateDataset")
}

func (service *DatasetService) Get(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*datasetv1.Dataset, error) {
	if !scopedResourceName(service.client.config, name, "datasets") {
		return nil, invalidArgument("dataset name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetDataset(callContext, &internaldatasetv1.GetDatasetRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetDataset() == nil {
		return nil, protocolDataLoss("GetDataset response omitted its dataset")
	}
	return cloneGenerated(response.GetDataset()), nil
}

// List returns one generated, opaque-token page. The configured project is
// authoritative; a missing parent is filled and a mismatched parent is rejected.
func (service *DatasetService) List(ctx context.Context, request *internaldatasetv1.ListDatasetsRequest, options ...RequestOption) (*internaldatasetv1.ListDatasetsResponse, error) {
	materialized := cloneGenerated(request)
	if materialized == nil {
		materialized = &internaldatasetv1.ListDatasetsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if materialized.GetParent() == "" {
		materialized.Parent = parent
	} else if materialized.GetParent() != parent {
		return nil, invalidArgument("dataset list parent must match the configured project")
	}
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("dataset page size cannot exceed 1000")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListDatasets(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

func (service *DatasetService) Update(ctx context.Context, command *datasetv1.UpdateDatasetCommand, options ...RequestOption) (*operationv1.Operation, error) {
	if command == nil || command.GetDataset() == nil {
		return nil, invalidArgument("a generated UpdateDatasetCommand and dataset are required")
	}
	return service.update(ctx, cloneGenerated(command), options...)
}

func (service *DatasetService) update(ctx context.Context, command *datasetv1.UpdateDatasetCommand, options ...RequestOption) (*operationv1.Operation, error) {
	key := command.GetContext().GetIdempotencyKey()
	command.Context = nil
	if !scopedResourceName(service.client.config, command.GetDataset().GetName(), "datasets") {
		return nil, invalidArgument("updated dataset must be in the configured project")
	}
	callContext, request, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(command)
	if err != nil {
		return nil, err
	}
	command.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.UpdateDataset(callContext, &internaldatasetv1.UpdateDatasetRequest{Command: command})
	return operationResponse(response.GetOperation(), err, "UpdateDataset")
}

func (service *DatasetService) PublishRelease(ctx context.Context, command *datasetv1.PublishDatasetReleaseCommand, options ...RequestOption) (*operationv1.Operation, error) {
	if command == nil || command.GetDataset() == nil {
		return nil, invalidArgument("a generated PublishDatasetReleaseCommand is required")
	}
	materialized := cloneGenerated(command)
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
	if !normalizeScopedReference(service.client.config, materialized.GetDataset(), "dataset", "datasets") {
		return nil, invalidArgument("dataset release must target the configured project")
	}
	callContext, request, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(materialized)
	if err != nil {
		return nil, err
	}
	materialized.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.PublishDatasetRelease(callContext, &internaldatasetv1.PublishDatasetReleaseRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "PublishDatasetRelease")
}

func (service *DatasetService) RevokeRelease(ctx context.Context, command *datasetv1.RevokeDatasetReleaseCommand, options ...RequestOption) (*operationv1.Operation, error) {
	if command == nil || command.GetDatasetRelease() == nil {
		return nil, invalidArgument("a generated RevokeDatasetReleaseCommand is required")
	}
	materialized := cloneGenerated(command)
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
	if !normalizeScopedReference(service.client.config, materialized.GetDatasetRelease(), "dataset_release", "datasets") {
		return nil, invalidArgument("dataset release must be in the configured project")
	}
	callContext, request, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(materialized)
	if err != nil {
		return nil, err
	}
	materialized.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.RevokeDatasetRelease(callContext, &internaldatasetv1.RevokeDatasetReleaseRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "RevokeDatasetRelease")
}

func (service *DatasetService) GetRelease(ctx context.Context, name string, options ...RequestOption) (*datasetv1.DatasetRelease, error) {
	if !scopedReleaseName(service.client.config, name, "datasets") {
		return nil, invalidArgument("dataset release name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetDatasetRelease(callContext, &internaldatasetv1.GetDatasetReleaseRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetDatasetRelease() == nil {
		return nil, protocolDataLoss("GetDatasetRelease response omitted its release")
	}
	return cloneGenerated(response.GetDatasetRelease()), nil
}

func (service *DatasetService) ListReleases(ctx context.Context, request *internaldatasetv1.ListDatasetReleasesRequest, options ...RequestOption) (*internaldatasetv1.ListDatasetReleasesResponse, error) {
	if request == nil || !scopedResourceName(service.client.config, request.GetParent(), "datasets") {
		return nil, invalidArgument("dataset release parent must be a dataset in the configured project")
	}
	materialized := cloneGenerated(request)
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("dataset release page size cannot exceed 1000")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListDatasetReleases(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

func projectResource(config Config) *commonv1.ResourceRef {
	name := projectName(config.TenantID, config.ProjectID)
	return &commonv1.ResourceRef{ResourceType: "project", ResourceId: config.ProjectID, TenantId: config.TenantID, ProjectId: config.ProjectID, Name: name}
}

func operationResponse(operation *operationv1.Operation, err error, method string) (*operationv1.Operation, error) {
	if err != nil {
		return nil, normalizeError(err)
	}
	if operation == nil || strings.TrimSpace(operation.GetOperationId()) == "" {
		return nil, protocolDataLoss(method + " response omitted its durable operation")
	}
	return cloneGenerated(operation), nil
}

func scopedResourceName(config Config, name, collection string) bool {
	prefix := projectName(config.TenantID, config.ProjectID) + "/" + collection + "/"
	remainder := strings.TrimPrefix(strings.TrimSpace(name), prefix)
	return strings.HasPrefix(strings.TrimSpace(name), prefix) && remainder != "" && !strings.Contains(remainder, "/") && validResourceIdentifier(remainder)
}

func scopedReleaseName(config Config, name, collection string) bool {
	prefix := projectName(config.TenantID, config.ProjectID) + "/" + collection + "/"
	remainder := strings.TrimPrefix(strings.TrimSpace(name), prefix)
	parts := strings.Split(remainder, "/releases/")
	return strings.HasPrefix(strings.TrimSpace(name), prefix) && len(parts) == 2 && validResourceIdentifier(parts[0]) && validResourceIdentifier(parts[1]) && !strings.Contains(parts[0], "/") && !strings.Contains(parts[1], "/")
}

func normalizeScopedReference(config Config, reference *commonv1.ResourceRef, resourceType, collection string) bool {
	if reference == nil || (reference.GetResourceType() != "" && reference.GetResourceType() != resourceType) ||
		(reference.GetTenantId() != "" && reference.GetTenantId() != config.TenantID) ||
		(reference.GetProjectId() != "" && reference.GetProjectId() != config.ProjectID) {
		return false
	}
	validName := scopedResourceName(config, reference.GetName(), collection)
	if strings.HasSuffix(resourceType, "_release") {
		validName = scopedReleaseName(config, reference.GetName(), collection)
	}
	if !validName {
		return false
	}
	parts := strings.Split(reference.GetName(), "/")
	resourceID := parts[len(parts)-1]
	if reference.GetResourceId() != "" && reference.GetResourceId() != resourceID {
		return false
	}
	reference.ResourceType = resourceType
	reference.ResourceId = resourceID
	reference.TenantId = config.TenantID
	reference.ProjectId = config.ProjectID
	return true
}

func invalidArgument(message string) error {
	return &Error{Code: CodeInvalidArgument, Message: message}
}

func protocolDataLoss(message string) error {
	return &Error{Code: CodeDataLoss, Message: message}
}
