package mindclade

import (
	"context"
	"strings"

	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
)

// ModelService is the private model and immutable-release lifecycle façade.
// All resource, command, request, response, and operation values are generated.
type ModelService struct {
	client    *Client
	transport internalmodelv1.ModelServiceClient
}

func (service *ModelService) Register(ctx context.Context, command *modelv1.RegisterModelCommand, options ...RequestOption) (*jobv1.Operation, error) {
	if command == nil {
		return nil, invalidArgument("a generated RegisterModelCommand is required")
	}
	materialized := cloneGenerated(command)
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
	if materialized.Project == nil {
		materialized.Project = projectResource(service.client.config)
	} else if materialized.GetProject().GetName() != projectName(service.client.config.TenantID, service.client.config.ProjectID) {
		return nil, invalidArgument("model project must match the configured project")
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
	response, err := service.transport.RegisterModel(callContext, &internalmodelv1.RegisterModelRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "RegisterModel")
}

func (service *ModelService) Get(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*modelv1.Model, error) {
	if !scopedResourceName(service.client.config, name, "models") {
		return nil, invalidArgument("model name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetModel(callContext, &internalmodelv1.GetModelRequest{Name: name, IfNoneMatch: strings.TrimSpace(ifNoneMatch)})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetModel() == nil {
		return nil, protocolDataLoss("GetModel response omitted its model")
	}
	return cloneGenerated(response.GetModel()), nil
}

func (service *ModelService) List(ctx context.Context, request *internalmodelv1.ListModelsRequest, options ...RequestOption) (*internalmodelv1.ListModelsResponse, error) {
	materialized := cloneGenerated(request)
	if materialized == nil {
		materialized = &internalmodelv1.ListModelsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if materialized.GetParent() == "" {
		materialized.Parent = parent
	} else if materialized.GetParent() != parent {
		return nil, invalidArgument("model list parent must match the configured project")
	}
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("model page size cannot exceed 1000")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListModels(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

func (service *ModelService) RegisterRelease(ctx context.Context, command *modelv1.RegisterModelReleaseCommand, options ...RequestOption) (*jobv1.Operation, error) {
	return service.mutateRelease(ctx, command, options...)
}

func (service *ModelService) mutateRelease(ctx context.Context, command *modelv1.RegisterModelReleaseCommand, options ...RequestOption) (*jobv1.Operation, error) {
	if command == nil {
		return nil, invalidArgument("a generated release command for the configured model project is required")
	}
	materialized := cloneGenerated(command)
	if !normalizeScopedReference(service.client.config, materialized.GetModel(), "model", "models") {
		return nil, invalidArgument("a generated release command for the configured model project is required")
	}
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
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
	response, err := service.transport.RegisterModelRelease(callContext, &internalmodelv1.RegisterModelReleaseRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "RegisterModelRelease")
}

func (service *ModelService) GetRelease(ctx context.Context, name string, options ...RequestOption) (*modelv1.ModelRelease, error) {
	if !scopedReleaseName(service.client.config, name, "models") {
		return nil, invalidArgument("model release name must be in the configured project")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetModelRelease(callContext, &internalmodelv1.GetModelReleaseRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetModelRelease() == nil {
		return nil, protocolDataLoss("GetModelRelease response omitted its release")
	}
	return cloneGenerated(response.GetModelRelease()), nil
}

func (service *ModelService) ListReleases(ctx context.Context, request *internalmodelv1.ListModelReleasesRequest, options ...RequestOption) (*internalmodelv1.ListModelReleasesResponse, error) {
	if request == nil || !scopedResourceName(service.client.config, request.GetParent(), "models") {
		return nil, invalidArgument("model release parent must be a model in the configured project")
	}
	materialized := cloneGenerated(request)
	if materialized.GetPage().GetPageSize() > 1000 {
		return nil, invalidArgument("model release page size cannot exceed 1000")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListModelReleases(callContext, materialized)
	if err != nil {
		return nil, normalizeError(err)
	}
	return cloneGenerated(response), nil
}

func (service *ModelService) PromoteRelease(ctx context.Context, command *modelv1.PromoteModelReleaseCommand, options ...RequestOption) (*jobv1.Operation, error) {
	if command == nil {
		return nil, invalidArgument("a generated promotion command for the configured project is required")
	}
	materialized := cloneGenerated(command)
	if !normalizeScopedReference(service.client.config, materialized.GetModelRelease(), "model_release", "models") {
		return nil, invalidArgument("a generated promotion command for the configured project is required")
	}
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
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
	response, err := service.transport.PromoteModelRelease(callContext, &internalmodelv1.PromoteModelReleaseRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "PromoteModelRelease")
}

func (service *ModelService) RevokeRelease(ctx context.Context, command *modelv1.RevokeModelReleaseCommand, options ...RequestOption) (*jobv1.Operation, error) {
	if command == nil {
		return nil, invalidArgument("a generated revocation command for the configured project is required")
	}
	materialized := cloneGenerated(command)
	if !normalizeScopedReference(service.client.config, materialized.GetModelRelease(), "model_release", "models") {
		return nil, invalidArgument("a generated revocation command for the configured project is required")
	}
	key := materialized.GetContext().GetIdempotencyKey()
	materialized.Context = nil
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
	response, err := service.transport.RevokeModelRelease(callContext, &internalmodelv1.RevokeModelReleaseRequest{Command: materialized})
	return operationResponse(response.GetOperation(), err, "RevokeModelRelease")
}
