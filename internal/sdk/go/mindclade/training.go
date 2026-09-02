package mindclade

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"path"
	"strings"
	"unicode"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	"google.golang.org/protobuf/proto"
)

// Model, Dataset, Recipe, Artifact, and Policy are ergonomic identifiers. They
// are resolved into generated ResourceRef/ArtifactRef messages before an RPC;
// they are not alternate wire resources.
type Model string
type Dataset string
type Recipe string
type Artifact string
type Policy string

// TrainingJob is workflow intent for Submit. Authoritative persisted state and
// RPC payloads remain generated protobuf messages.
type TrainingJob struct {
	ID                   string
	Model                Model
	Dataset              Dataset
	Recipe               Recipe
	HardwareTopology     Artifact
	UsePolicy            Policy
	Labels               map[string]string
	PolicyClassification string
	IdempotencyKey       string
}

type TrainingService struct {
	client    *Client
	transport internaltrainingv1.TrainingServiceClient
}

// Submit resolves mutable artifact aliases, freezes generated command intent,
// derives its deterministic digest, and returns the generated durable
// Operation that controls admission and execution.
func (service *TrainingService) Submit(ctx context.Context, job TrainingJob) (*jobv1.Operation, error) {
	if err := service.validateJob(job); err != nil {
		return nil, err
	}
	idempotencyKey := strings.TrimSpace(job.IdempotencyKey)
	if idempotencyKey == "" {
		var err error
		idempotencyKey, err = randomID()
		if err != nil {
			return nil, err
		}
	}
	callContext, request, cancel, err := service.client.context(ctx, WithIdempotencyKey(idempotencyKey))
	if err != nil {
		return nil, err
	}
	defer cancel()
	requestOptions := []RequestOption{
		WithRequestID(request.requestID),
		WithTraceID(request.traceID),
		WithIdempotencyKey(idempotencyKey),
	}
	trainingRecipe, err := service.client.Artifacts.Resolve(callContext, string(job.Recipe), requestOptions...)
	if err != nil {
		return nil, err
	}
	var hardwareTopology *artifactv1.ArtifactRef
	if job.HardwareTopology != "" {
		hardwareTopology, err = service.client.Artifacts.Resolve(callContext, string(job.HardwareTopology), requestOptions...)
		if err != nil {
			return nil, err
		}
	}
	command := &trainingv1.CreateTrainingRunCommand{
		Project:              resourceRef(service.client.config, "project", projectName(service.client.config.TenantID, service.client.config.ProjectID)),
		TrainingRunId:        strings.TrimSpace(job.ID),
		TrainingRecipe:       trainingRecipe,
		DatasetRelease:       resourceRef(service.client.config, "dataset_release", string(job.Dataset)),
		ModelRelease:         resourceRef(service.client.config, "model_release", string(job.Model)),
		HardwareTopology:     hardwareTopology,
		Labels:               cloneLabels(job.Labels),
		PolicyClassification: strings.TrimSpace(job.PolicyClassification),
	}
	if job.UsePolicy != "" {
		command.UsePolicy = resourceRef(service.client.config, "use_policy", string(job.UsePolicy))
	}
	digest, err := deterministicDigest(command)
	if err != nil {
		return nil, err
	}
	command.Context = commandContext(service.client.config, callContext, request, digest)
	response, err := service.transport.CreateTrainingRun(callContext, &internaltrainingv1.CreateTrainingRunRequest{Command: command})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetOperation() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "training service returned no durable operation"}
	}
	return response.GetOperation(), nil
}

// SubmitAndWait is the bounded common path: submit a durable operation, wait
// for its terminal state, then read the authoritative generated TrainingRun.
func (service *TrainingService) SubmitAndWait(ctx context.Context, job TrainingJob) (*trainingv1.TrainingRun, error) {
	operation, err := service.Submit(ctx, job)
	if err != nil {
		return nil, err
	}
	operationName := operation.GetOperationId()
	terminal, err := service.client.Operations.Wait(ctx, operationName, WaitOptions{})
	if err != nil {
		return nil, err
	}
	if terminal.GetTarget() == nil || terminal.GetTarget().GetName() == "" {
		return nil, &Error{Code: CodeDataLoss, Message: "terminal training operation has no linked domain run"}
	}
	return service.Get(ctx, terminal.GetTarget().GetName())
}

func (service *TrainingService) Get(ctx context.Context, name string, options ...RequestOption) (*trainingv1.TrainingRun, error) {
	if !validResourceIdentifier(name) {
		return nil, &Error{Code: CodeInvalidArgument, Message: "valid training run name is required"}
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetTrainingRun(callContext, &internaltrainingv1.GetTrainingRunRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetTrainingRun() == nil {
		return nil, &Error{Code: CodeDataLoss, Message: "training service returned no run"}
	}
	return response.GetTrainingRun(), nil
}

type TrainingPage struct {
	Runs          []*trainingv1.TrainingRun
	NextPageToken string
}

func (service *TrainingService) List(ctx context.Context, pageSize uint32, pageToken string) (*TrainingPage, error) {
	if pageSize > 1000 {
		return nil, &Error{Code: CodeInvalidArgument, Message: "training page size cannot exceed 1000"}
	}
	callContext, _, cancel, err := service.client.context(ctx)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListTrainingRuns(callContext, &internaltrainingv1.ListTrainingRunsRequest{
		Parent: projectName(service.client.config.TenantID, service.client.config.ProjectID),
		Page:   &commonv1.PageRequest{PageSize: pageSize, PageToken: pageToken},
	})
	if err != nil {
		return nil, normalizeError(err)
	}
	page := &TrainingPage{Runs: response.GetTrainingRuns()}
	if response.GetPage() != nil {
		page.NextPageToken = response.GetPage().GetNextPageToken()
	}
	return page, nil
}

func (service *TrainingService) validateJob(job TrainingJob) error {
	if service.client.config.TenantID == "" || service.client.config.ProjectID == "" {
		return &Error{Code: CodeFailedPrecondition, Message: "tenant and project configuration are required for training"}
	}
	if !validResourceIdentifier(string(job.Model)) || !validResourceIdentifier(string(job.Dataset)) ||
		strings.TrimSpace(string(job.Recipe)) == "" {
		return &Error{Code: CodeInvalidArgument, Message: "model, dataset, and recipe are required"}
	}
	if !validResourceIdentifier(job.ID) && strings.TrimSpace(job.ID) != "" {
		return &Error{Code: CodeInvalidArgument, Message: "training job ID is invalid"}
	}
	for key, value := range job.Labels {
		if strings.TrimSpace(key) == "" || hasControlCharacters(key) || hasControlCharacters(value) {
			return &Error{Code: CodeInvalidArgument, Message: "training labels contain invalid text"}
		}
	}
	return nil
}

func deterministicDigest(message proto.Message) (string, error) {
	content, err := (proto.MarshalOptions{Deterministic: true}).Marshal(message)
	if err != nil {
		return "", &Error{Code: CodeInternal, Message: "canonical command serialization failed", Cause: err}
	}
	digest := sha256.Sum256(content)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func resourceRef(config Config, resourceType, value string) *commonv1.ResourceRef {
	value = strings.TrimSpace(value)
	name := value
	if !strings.Contains(value, "/") {
		name = resourceType + "s/" + value
	}
	return &commonv1.ResourceRef{
		ResourceType: resourceType,
		ResourceId:   path.Base(name),
		TenantId:     config.TenantID,
		ProjectId:    config.ProjectID,
		Name:         name,
	}
}

func validResourceIdentifier(value string) bool {
	value = strings.TrimSpace(value)
	return value != "" && value != "." && value != ".." && !strings.HasPrefix(value, "/") &&
		!strings.Contains(value, "//") && !hasControlCharacters(value)
}

func hasControlCharacters(value string) bool {
	return strings.IndexFunc(value, unicode.IsControl) >= 0
}

func cloneLabels(labels map[string]string) map[string]string {
	if labels == nil {
		return nil
	}
	clone := make(map[string]string, len(labels))
	for key, value := range labels {
		clone[key] = value
	}
	return clone
}
