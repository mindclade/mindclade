package mindclade

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"path"
	"strings"
	"sync"
	"time"
	"unicode"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

// Model, Dataset, Recipe, Artifact, and Policy are ergonomic identifiers. They
// are resolved into generated ResourceRef/ArtifactRef messages before an RPC;
// they are not alternate wire resources.
type (
	Model    string
	Dataset  string
	Recipe   string
	Artifact string
	Policy   string
)

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
	return cloneGenerated(response.GetOperation()), nil
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
	name, err := canonicalTrainingRunNameSDK(service.client, name)
	if !service.configured() || err != nil {
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
	if response.GetTrainingRun() == nil || response.GetTrainingRun().GetName() != name {
		return nil, protocolDataLoss("GetTrainingRun returned inconsistent durable state")
	}
	return cloneGenerated(response.GetTrainingRun()), nil
}

type TrainingPage struct {
	Runs          []*trainingv1.TrainingRun
	NextPageToken string
}

const maximumTrainingPageSize = 200

func (service *TrainingService) List(ctx context.Context, pageSize uint32, pageToken string) (*TrainingPage, error) {
	if pageSize > maximumTrainingPageSize {
		return nil, &Error{Code: CodeInvalidArgument, Message: "training page size cannot exceed 200"}
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
	if response == nil {
		return nil, protocolDataLoss("ListTrainingRuns returned no response")
	}
	detached := cloneGenerated(response)
	for _, run := range detached.GetTrainingRuns() {
		canonical, nameErr := canonicalTrainingRunNameSDK(service.client, run.GetName())
		if run == nil || nameErr != nil || canonical != run.GetName() {
			return nil, protocolDataLoss("ListTrainingRuns returned a run outside configured scope")
		}
	}
	page := &TrainingPage{Runs: detached.GetTrainingRuns()}
	if detached.GetPage() != nil {
		page.NextPageToken = detached.GetPage().GetNextPageToken()
	}
	return page, nil
}

// ListRuns sends an authoritative generated list request while binding an
// omitted parent to the configured project and preserving opaque page tokens.
func (service *TrainingService) ListRuns(ctx context.Context, request *internaltrainingv1.ListTrainingRunsRequest, options ...RequestOption) (*internaltrainingv1.ListTrainingRunsResponse, error) {
	if !service.configured() {
		return nil, &Error{Code: CodeFailedPrecondition, Message: "training service is not configured"}
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internaltrainingv1.ListTrainingRunsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if value.GetParent() != "" && value.GetParent() != parent {
		return nil, invalidArgument("training list parent must match the configured project")
	}
	if value.GetPage().GetPageSize() > maximumTrainingPageSize {
		return nil, invalidArgument("training page size cannot exceed 200")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListTrainingRuns(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListTrainingRuns returned no response")
	}
	for _, run := range response.GetTrainingRuns() {
		canonical, nameErr := canonicalTrainingRunNameSDK(service.client, run.GetName())
		if run == nil || nameErr != nil || canonical != run.GetName() {
			return nil, protocolDataLoss("ListTrainingRuns returned a run outside configured scope")
		}
	}
	return cloneGenerated(response), nil
}

// StartAttempt binds a generated training attempt to the current scheduler
// fence. The raw lease capability is carried only in transport metadata.
func (service *TrainingService) StartAttempt(ctx context.Context, command *trainingv1.StartTrainingAttemptCommand, options ...RequestOption) (*trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !service.normalizeRunReference(value.GetTrainingRun()) || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !time.Now().Before(value.GetDeadline().AsTime()) {
		return nil, invalidArgument("start training attempt requires a scoped run and future deadline")
	}
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, err
	}
	if value.GetDelegatedCapability() != nil && !normalizeReferenceScope(service.client.config, value.GetDelegatedCapability()) {
		return nil, invalidArgument("delegated capability must match the configured project")
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.StartTrainingAttempt(callContext, &internaltrainingv1.StartTrainingAttemptRequest{Command: value})
	return service.trainingRunResponse(response.GetTrainingRun(), err, value.GetTrainingRun().GetName(), "StartTrainingAttempt")
}

// ResumeAttempt resumes only from a generated immutable checkpoint reference
// under the current lease fence.
func (service *TrainingService) ResumeAttempt(ctx context.Context, command *trainingv1.ResumeTrainingAttemptCommand, options ...RequestOption) (*trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	if !service.configured() || value == nil || !service.normalizeRunReference(value.GetTrainingRun()) || !service.normalizeCheckpointReference(value.GetCheckpoint()) || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !time.Now().Before(value.GetDeadline().AsTime()) {
		return nil, invalidArgument("resume training attempt requires a scoped run, checkpoint, and future deadline")
	}
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, err
	}
	if value.GetDelegatedCapability() != nil && !normalizeReferenceScope(service.client.config, value.GetDelegatedCapability()) {
		return nil, invalidArgument("delegated capability must match the configured project")
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ResumeTrainingAttempt(callContext, &internaltrainingv1.ResumeTrainingAttemptRequest{Command: value})
	return service.trainingRunResponse(response.GetTrainingRun(), err, value.GetTrainingRun().GetName(), "ResumeTrainingAttempt")
}

// CommitProgress advances the generated monotonic progress frontier under the
// current lease fence.
func (service *TrainingService) CommitProgress(ctx context.Context, command *trainingv1.CommitTrainingProgressCommand, options ...RequestOption) (*trainingv1.TrainingProgress, *trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	name, nameErr := canonicalTrainingRunNameSDK(service.client, value.GetTrainingRunName())
	progressName, progressErr := canonicalTrainingRunNameSDK(service.client, value.GetProgress().GetTrainingRunName())
	if !service.configured() || value == nil || nameErr != nil || progressErr != nil || progressName != name || value.GetProgress() == nil || value.GetProgress().GetProgressRevision() == 0 {
		return nil, nil, invalidArgument("progress commit requires a generated monotonic snapshot for the target run")
	}
	value.TrainingRunName = name
	value.Progress.TrainingRunName = name
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, nil, err
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	response, err := service.transport.CommitTrainingProgress(callContext, &internaltrainingv1.CommitTrainingProgressRequest{Command: value})
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetProgress() == nil || response.GetTrainingRun() == nil || response.GetProgress().GetTrainingRunName() != value.GetTrainingRunName() || response.GetTrainingRun().GetName() != value.GetTrainingRunName() {
		return nil, nil, protocolDataLoss("CommitTrainingProgress returned inconsistent durable state")
	}
	return cloneGenerated(response.GetProgress()), cloneGenerated(response.GetTrainingRun()), nil
}

// PrepareCheckpoint establishes a fenced snapshot boundary and returns the
// generated checkpoint resource under preparation.
func (service *TrainingService) PrepareCheckpoint(ctx context.Context, command *trainingv1.PrepareCheckpointCommand, options ...RequestOption) (*trainingv1.Checkpoint, error) {
	value := cloneGenerated(command)
	name, nameErr := canonicalTrainingRunNameSDK(service.client, value.GetTrainingRunName())
	progressName, progressErr := canonicalTrainingRunNameSDK(service.client, value.GetCommittedProgress().GetTrainingRunName())
	if !service.configured() || value == nil || nameErr != nil || progressErr != nil || progressName != name || value.GetSnapshotEpoch() == 0 || value.GetLogicalStateDescriptor() == nil || value.GetCommittedProgress() == nil || value.GetCommittedProgress().GetProgressRevision() == 0 {
		return nil, invalidArgument("checkpoint preparation requires run, epoch, descriptor, and committed progress")
	}
	value.TrainingRunName = name
	value.CommittedProgress.TrainingRunName = name
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, err
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.PrepareCheckpoint(callContext, &internaltrainingv1.PrepareCheckpointRequest{Command: value})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetCheckpoint() == nil || response.GetCheckpoint().GetTrainingRunName() != value.GetTrainingRunName() || response.GetCheckpoint().GetSnapshotEpoch() != value.GetSnapshotEpoch() {
		return nil, protocolDataLoss("PrepareCheckpoint returned inconsistent checkpoint identity")
	}
	return cloneGenerated(response.GetCheckpoint()), nil
}

// CommitCheckpoint publishes a verified immutable generated checkpoint under
// the current lease fence.
func (service *TrainingService) CommitCheckpoint(ctx context.Context, command *trainingv1.CommitCheckpointCommand, options ...RequestOption) (*trainingv1.Checkpoint, *trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	name, nameErr := canonicalTrainingRunNameSDK(service.client, value.GetTrainingRunName())
	progressName, progressErr := canonicalTrainingRunNameSDK(service.client, value.GetCommittedProgress().GetTrainingRunName())
	if !service.configured() || value == nil || nameErr != nil || progressErr != nil || progressName != name || value.GetSnapshotEpoch() == 0 || value.GetCheckpointManifest() == nil || value.GetLogicalStateDescriptor() == nil || value.GetCommittedProgress() == nil || value.GetCommittedProgress().GetProgressRevision() == 0 || value.GetVerificationEvidence() == nil || value.GetCommittedAt() == nil || value.GetCommittedAt().CheckValid() != nil {
		return nil, nil, invalidArgument("checkpoint commit requires immutable manifests, evidence, progress, epoch, and commit time")
	}
	value.TrainingRunName = name
	value.CommittedProgress.TrainingRunName = name
	if value.GetParentCheckpoint() != nil && !service.normalizeCheckpointReference(value.GetParentCheckpoint()) {
		return nil, nil, invalidArgument("parent checkpoint must match the configured project")
	}
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, nil, err
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	response, err := service.transport.CommitCheckpoint(callContext, &internaltrainingv1.CommitCheckpointRequest{Command: value})
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetCheckpoint() == nil || response.GetTrainingRun() == nil || response.GetCheckpoint().GetTrainingRunName() != value.GetTrainingRunName() || response.GetCheckpoint().GetSnapshotEpoch() != value.GetSnapshotEpoch() || response.GetTrainingRun().GetName() != value.GetTrainingRunName() {
		return nil, nil, protocolDataLoss("CommitCheckpoint returned inconsistent durable state")
	}
	return cloneGenerated(response.GetCheckpoint()), cloneGenerated(response.GetTrainingRun()), nil
}

// Complete publishes terminal generated training truth under the current
// lease fence.
func (service *TrainingService) Complete(ctx context.Context, command *trainingv1.CompleteTrainingRunCommand, options ...RequestOption) (*trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	name, nameErr := canonicalTrainingRunNameSDK(service.client, value.GetTrainingRunName())
	if !service.configured() || value == nil || nameErr != nil || value.GetClassification() == trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED || value.GetCompletedAt() == nil || value.GetCompletedAt().CheckValid() != nil {
		return nil, invalidArgument("training completion requires a target, terminal classification, and completion time")
	}
	value.TrainingRunName = name
	if value.GetFinalCheckpoint() != nil && !service.normalizeCheckpointReference(value.GetFinalCheckpoint()) {
		return nil, invalidArgument("final checkpoint must match the configured project")
	}
	if err := normalizeTrainingFence(service.client.config, value.GetFence(), time.Now()); err != nil {
		return nil, err
	}
	callContext, cancel, err := service.prepareMutation(ctx, value, true, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CompleteTrainingRun(callContext, &internaltrainingv1.CompleteTrainingRunRequest{Command: value})
	return service.trainingRunResponse(response.GetTrainingRun(), err, value.GetTrainingRunName(), "CompleteTrainingRun")
}

// Cancel records generated, ETag-protected cancellation intent.
func (service *TrainingService) Cancel(ctx context.Context, command *trainingv1.CancelTrainingRunCommand, options ...RequestOption) (*trainingv1.TrainingRun, error) {
	value := cloneGenerated(command)
	name, nameErr := canonicalTrainingRunNameSDK(service.client, value.GetTrainingRunName())
	if !service.configured() || value == nil || nameErr != nil || strings.TrimSpace(value.GetEtag()) == "" || strings.TrimSpace(value.GetReason()) == "" || len(value.GetReason()) > 1024 {
		return nil, invalidArgument("training cancellation requires a run, ETag, and bounded reason")
	}
	value.TrainingRunName = name
	callContext, cancel, err := service.prepareMutation(ctx, value, false, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CancelTrainingRun(callContext, &internaltrainingv1.CancelTrainingRunRequest{Command: value})
	return service.trainingRunResponse(response.GetTrainingRun(), err, value.GetTrainingRunName(), "CancelTrainingRun")
}

// GetCheckpoint reads one immutable generated checkpoint.
func (service *TrainingService) GetCheckpoint(ctx context.Context, name string, options ...RequestOption) (*trainingv1.Checkpoint, error) {
	name, nameErr := canonicalTrainingCheckpointNameSDK(service.client, name)
	if !service.configured() || nameErr != nil {
		return nil, invalidArgument("valid checkpoint name is required")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetCheckpoint(callContext, &internaltrainingv1.GetCheckpointRequest{Name: name})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetCheckpoint() == nil || response.GetCheckpoint().GetName() != name {
		return nil, protocolDataLoss("GetCheckpoint returned inconsistent immutable state")
	}
	return cloneGenerated(response.GetCheckpoint()), nil
}

// ListCheckpoints returns one generated bounded page beneath a training run.
func (service *TrainingService) ListCheckpoints(ctx context.Context, request *internaltrainingv1.ListCheckpointsRequest, options ...RequestOption) (*internaltrainingv1.ListCheckpointsResponse, error) {
	value := cloneGenerated(request)
	parent, parentErr := canonicalTrainingRunNameSDK(service.client, value.GetParent())
	if !service.configured() || value == nil || parentErr != nil || value.GetPage().GetPageSize() > maximumTrainingPageSize {
		return nil, invalidArgument("checkpoint list requires a run parent and page size at most 200")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListCheckpoints(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListCheckpoints returned no response")
	}
	for _, checkpoint := range response.GetCheckpoints() {
		if checkpoint == nil || checkpoint.GetTrainingRunName() != value.GetParent() {
			return nil, protocolDataLoss("ListCheckpoints returned a checkpoint under another run")
		}
	}
	return cloneGenerated(response), nil
}

func (service *TrainingService) prepareMutation(ctx context.Context, command proto.Message, requireLease bool, options ...RequestOption) (context.Context, context.CancelFunc, error) {
	reflected := command.ProtoReflect()
	contextField := reflected.Descriptor().Fields().ByName("context")
	if contextField == nil {
		return nil, nil, invalidArgument("training command has no command context field")
	}
	key := ""
	if reflected.Has(contextField) {
		key = reflected.Get(contextField).Message().Interface().(*commonv1.CommandContext).GetIdempotencyKey()
	}
	reflected.Clear(contextField)
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, nil, err
	}
	if requireLease && metadata.leaseToken == "" {
		cancel()
		return nil, nil, invalidArgument("fenced training command requires WithLeaseToken transport metadata")
	}
	digest, err := deterministicDigest(command)
	if err != nil {
		cancel()
		return nil, nil, err
	}
	setCommandContext(command, commandContext(service.client.config, callContext, metadata, digest))
	return callContext, cancel, nil
}

func (service *TrainingService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil
}

func (service *TrainingService) normalizeRunReference(reference *commonv1.ResourceRef) bool {
	return service.normalizeTrainingReference(reference, "training_run")
}

func (service *TrainingService) normalizeCheckpointReference(reference *commonv1.ResourceRef) bool {
	return service.normalizeTrainingReference(reference, "checkpoint")
}

func (service *TrainingService) normalizeTrainingReference(reference *commonv1.ResourceRef, resourceType string) bool {
	if reference == nil || (reference.GetResourceType() != "" && reference.GetResourceType() != resourceType) || !normalizeMessageScope(service.client.config, &reference.TenantId, &reference.ProjectId) {
		return false
	}
	name, err := canonicalTrainingRunNameSDK(service.client, reference.GetName())
	if resourceType == "checkpoint" {
		name, err = canonicalTrainingCheckpointNameSDK(service.client, reference.GetName())
	}
	if err != nil {
		return false
	}
	reference.Name = name
	resourceID := path.Base(reference.GetName())
	if !validTrainingResourceIDSDK(resourceID) || (reference.GetResourceId() != "" && reference.GetResourceId() != resourceID) {
		return false
	}
	reference.ResourceType = resourceType
	reference.ResourceId = resourceID
	return true
}

func normalizeTrainingFence(config Config, fence *jobv1.LeaseFence, now time.Time) error {
	if fence == nil || strings.TrimSpace(fence.GetJobId()) == "" || strings.TrimSpace(fence.GetRunId()) == "" || strings.TrimSpace(fence.GetAttemptId()) == "" || fence.GetLeaseEpoch() == 0 || fence.GetDeadline() == nil || fence.GetDeadline().CheckValid() != nil || !now.Before(fence.GetDeadline().AsTime()) || !validSHA256Digest(fence.GetLeaseTokenDigest()) {
		return invalidArgument("training fence is incomplete, expired, or missing its token digest")
	}
	if !normalizeMessageScope(config, &fence.TenantId, &fence.ProjectId) {
		return invalidArgument("training fence must match the configured project")
	}
	return nil
}

func (service *TrainingService) trainingRunResponse(run *trainingv1.TrainingRun, err error, expectedName, method string) (*trainingv1.TrainingRun, error) {
	if err != nil {
		return nil, normalizeError(err)
	}
	if run == nil || run.GetName() != expectedName {
		return nil, protocolDataLoss(method + " returned inconsistent durable state")
	}
	return cloneGenerated(run), nil
}

// TrainingWatcher resumes the generated stream from the last accepted durable
// sequence. Recv is serialized and Close is idempotent.
type TrainingWatcher struct {
	service  *TrainingService
	ctx      context.Context //nolint:containedctx // A stream watcher owns its cancellable lifecycle context.
	cancel   context.CancelFunc
	name     string
	after    uint64
	stream   grpc.ServerStreamingClient[internaltrainingv1.WatchTrainingRunResponse]
	terminal bool
	mu       sync.Mutex
}

func (service *TrainingService) Watch(ctx context.Context, name string, afterSequence uint64) (*TrainingWatcher, error) {
	name, nameErr := canonicalTrainingRunNameSDK(service.client, name)
	if !service.configured() || ctx == nil || nameErr != nil {
		return nil, invalidArgument("context and valid training run name are required")
	}
	watchContext, cancel, err := service.client.Operations.longRunningContext(ctx)
	if err != nil {
		return nil, err
	}
	watcher := &TrainingWatcher{service: service, ctx: watchContext, cancel: cancel, name: name, after: afterSequence}
	if err = watcher.connect(); err != nil {
		cancel()
		return nil, err
	}
	return watcher, nil
}

func canonicalTrainingRunNameSDK(client *Client, value string) (string, error) {
	if client == nil {
		return "", invalidArgument("training service is not configured")
	}
	value = strings.TrimSpace(value)
	prefix := projectName(client.config.TenantID, client.config.ProjectID) + "/trainingRuns/"
	switch {
	case strings.HasPrefix(value, prefix):
		value = strings.TrimPrefix(value, prefix)
	case strings.HasPrefix(value, "tenants/"):
		return "", invalidArgument("training run is outside the configured project")
	case strings.HasPrefix(value, "trainingRuns/"):
		value = strings.TrimPrefix(value, "trainingRuns/")
	}
	if !validTrainingResourceIDSDK(value) {
		return "", invalidArgument("training run name is invalid")
	}
	return prefix + value, nil
}

func canonicalTrainingCheckpointNameSDK(client *Client, value string) (string, error) {
	if client == nil {
		return "", invalidArgument("training service is not configured")
	}
	value = strings.TrimSpace(value)
	prefix := projectName(client.config.TenantID, client.config.ProjectID) + "/trainingRuns/"
	switch {
	case strings.HasPrefix(value, prefix):
		value = strings.TrimPrefix(value, prefix)
	case strings.HasPrefix(value, "tenants/"):
		return "", invalidArgument("checkpoint is outside the configured project")
	case strings.HasPrefix(value, "trainingRuns/"):
		value = strings.TrimPrefix(value, "trainingRuns/")
	}
	parts := strings.Split(value, "/")
	if len(parts) != 3 || !validTrainingResourceIDSDK(parts[0]) || parts[1] != "checkpoints" || !validTrainingResourceIDSDK(parts[2]) {
		return "", invalidArgument("checkpoint name is invalid")
	}
	return prefix + strings.Join(parts, "/"), nil
}

func (watcher *TrainingWatcher) connect() error {
	request := &internaltrainingv1.WatchTrainingRunRequest{Name: watcher.name, AfterSequence: watcher.after}
	if deadline, ok := watcher.ctx.Deadline(); ok {
		request.Deadline = timestamppb.New(deadline)
	}
	stream, err := watcher.service.transport.WatchTrainingRun(watcher.ctx, request)
	if err != nil {
		return normalizeError(err)
	}
	watcher.stream = stream
	return nil
}

func (watcher *TrainingWatcher) Recv() (*internaltrainingv1.WatchTrainingRunResponse, error) {
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	if watcher.terminal {
		return nil, io.EOF
	}
	failures := 0
	for {
		response, err := watcher.stream.Recv()
		if err == nil {
			run := response.GetTrainingRun()
			if run == nil || run.GetName() != watcher.name || response.GetSequence() != watcher.after+1 || run.GetState() == trainingv1.TrainingRunState_TRAINING_RUN_STATE_UNSPECIFIED {
				return nil, protocolDataLoss("training watch returned invalid identity, state, or sequence")
			}
			watcher.after = response.GetSequence()
			watcher.terminal = terminalTrainingState(run.GetState())
			return cloneGenerated(response), nil
		}
		if errors.Is(err, io.EOF) && watcher.terminal {
			return nil, io.EOF
		}
		if watcher.ctx.Err() != nil {
			return nil, normalizeError(watcher.ctx.Err())
		}
		if !errors.Is(err, io.EOF) && !isRetryable(err) {
			return nil, normalizeError(err)
		}
		failures++
		if failures >= watcher.service.client.config.MaxAttempts {
			return nil, normalizeError(err)
		}
		if waitErr := waitContext(watcher.ctx, retryDelay(watcher.service.client.config, failures)); waitErr != nil {
			return nil, normalizeError(waitErr)
		}
		if connectErr := watcher.connect(); connectErr != nil {
			return nil, connectErr
		}
	}
}

func (watcher *TrainingWatcher) Close() error {
	if watcher != nil && watcher.cancel != nil {
		watcher.cancel()
	}
	return nil
}

func terminalTrainingState(state trainingv1.TrainingRunState) bool {
	return state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_COMPLETED || state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_FAILED || state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_CANCELLED
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

// validTrainingResourceIDSDK mirrors the authoritative control-plane leaf
// contract. It deliberately validates a single path segment rather than an
// arbitrary resource name or artifact alias.
func validTrainingResourceIDSDK(value string) bool {
	if len(value) == 0 || len(value) > 128 {
		return false
	}
	for index, character := range value {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' ||
			index > 0 && strings.ContainsRune("._~-", character) {
			continue
		}
		return false
	}
	return true
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
