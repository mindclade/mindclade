package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/mindclade/mindclade/libs/go/numconv"
	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	jobsapp "github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	trainingapp "github.com/mindclade/mindclade/services/control_plane/internal/training"
)

const (
	verifiedTenantMetadata    = "x-mindclade-verified-tenant"
	verifiedProjectMetadata   = "x-mindclade-verified-project"
	verifiedPrincipalMetadata = "x-mindclade-verified-principal"
	verifiedWorkerMetadata    = "x-mindclade-verified-worker"
	verifiedLeaseMetadata     = "x-mindclade-verified-lease-token"
	verifiedRoleMetadata      = "x-mindclade-verified-role"
)

// metadataIdentityResolver consumes only claims written by the authentication
// interceptor. It intentionally ignores similarly named client metadata.
type metadataIdentityResolver struct{}

func (metadataIdentityResolver) Resolve(ctx context.Context) (trainingapp.Identity, error) {
	values, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return trainingapp.Identity{}, trainingapp.ErrUnauthenticated
	}
	identity := trainingapp.Identity{
		TenantID:   first(values.Get(verifiedTenantMetadata)),
		ProjectID:  first(values.Get(verifiedProjectMetadata)),
		Principal:  first(values.Get(verifiedPrincipalMetadata)),
		WorkerID:   first(values.Get(verifiedWorkerMetadata)),
		LeaseToken: first(values.Get(verifiedLeaseMetadata)),
	}
	if identity.TenantID == "" || identity.ProjectID == "" || identity.Principal == "" {
		return trainingapp.Identity{}, trainingapp.ErrUnauthenticated
	}
	return identity, nil
}

// ResolveWorker projects the same verifier-owned metadata into the worker
// coordination application boundary. There is one authentication decision,
// not a second caller-controlled identity path.
func (resolver metadataIdentityResolver) ResolveWorker(ctx context.Context) (jobsapp.WorkerIdentity, error) {
	identity, err := resolver.Resolve(ctx)
	if err != nil {
		return jobsapp.WorkerIdentity{}, err
	}
	return jobsapp.WorkerIdentity{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal,
		WorkerID: identity.WorkerID, LeaseToken: identity.LeaseToken,
	}, nil
}

func (resolver metadataIdentityResolver) ResolveJob(ctx context.Context) (jobsapp.JobIdentity, error) {
	identity, err := resolver.Resolve(ctx)
	if err != nil {
		return jobsapp.JobIdentity{}, err
	}
	return jobsapp.JobIdentity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}, nil
}

// publicTrainingAdapter is a transport projection over the same application
// service used by native internal gRPC. It never exposes internal executable
// plans, storage URIs, worker leases, fences, or transport credentials.
type publicTrainingAdapter struct {
	apiv1.UnimplementedMindcladeServiceServer
	application *trainingapp.Server
	jobs        internaljobv1.JobServiceServer
	runs        internaljobv1.RunServiceServer
	identities  trainingapp.IdentityResolver
	ready       func(context.Context) error
}

var _ apiv1.MindcladeServiceServer = (*publicTrainingAdapter)(nil)

func newPublicTrainingAdapter(
	application *trainingapp.Server,
	jobs internaljobv1.JobServiceServer,
	runs internaljobv1.RunServiceServer,
	identities trainingapp.IdentityResolver,
	ready func(context.Context) error,
) (*publicTrainingAdapter, error) {
	if application == nil || jobs == nil || runs == nil || identities == nil || ready == nil {
		return nil, errors.New("public training adapter requires application, job, worker, identity, and readiness services")
	}
	return &publicTrainingAdapter{application: application, jobs: jobs, runs: runs, identities: identities, ready: ready}, nil
}

func (a *publicTrainingAdapter) Ready(ctx context.Context) error { return a.ready(ctx) }

func (a *publicTrainingAdapter) InternalTrainingServer() internaltrainingv1.TrainingServiceServer {
	return a.application
}

func (a *publicTrainingAdapter) InternalOperationServer() internaljobv1.OperationServiceServer {
	return a.application
}

func (a *publicTrainingAdapter) InternalRunServer() internaljobv1.RunServiceServer {
	return a.runs
}

func (a *publicTrainingAdapter) InternalJobServer() internaljobv1.JobServiceServer {
	return a.jobs
}

func (a *publicTrainingAdapter) CreateTrainingRun(ctx context.Context, request *apiv1.CreateTrainingRunRequest) (*apiv1.Operation, error) {
	identity, err := a.identities.Resolve(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	if request == nil || request.GetTrainingRun() == nil || request.GetParent() != projectParent(identity) {
		return nil, status.Error(codes.PermissionDenied, "parent is outside the authenticated scope")
	}
	intent := request.GetTrainingRun()
	if !validResourceID(intent.GetTrainingRunId()) {
		return nil, status.Error(codes.InvalidArgument, "trainingRunId is invalid")
	}
	datasetRelease, err := domainResource(identity, intent.GetDatasetRelease(), "dataset_release")
	if err != nil {
		return nil, err
	}
	modelRelease, err := domainResource(identity, intent.GetModelRelease(), "model_release")
	if err != nil {
		return nil, err
	}
	usePolicy, err := domainResource(identity, intent.GetUsePolicy(), "use_policy")
	if err != nil {
		return nil, err
	}
	trainingRecipe, err := domainArtifact(intent.GetTrainingRecipe())
	if err != nil {
		return nil, err
	}
	hardwareTopology, err := domainArtifact(intent.GetHardwareTopology())
	if err != nil {
		return nil, err
	}
	command := &trainingv1.CreateTrainingRunCommand{
		Project: &commonv1.ResourceRef{
			ResourceType: "project", ResourceId: identity.ProjectID, TenantId: identity.TenantID,
			ProjectId: identity.ProjectID, Name: projectParent(identity),
		},
		TrainingRunId:        intent.GetTrainingRunId(),
		TrainingRecipe:       trainingRecipe,
		DatasetRelease:       datasetRelease,
		ModelRelease:         modelRelease,
		HardwareTopology:     hardwareTopology,
		UsePolicy:            usePolicy,
		Labels:               cloneStringMap(intent.GetLabels()),
		PolicyClassification: intent.GetPolicyClassification(),
	}
	if command.GetTrainingRecipe() == nil || command.GetDatasetRelease() == nil || command.GetModelRelease() == nil {
		return nil, status.Error(codes.InvalidArgument, "trainingRecipe, datasetRelease, and modelRelease are required")
	}
	command.Context, err = publicCommandContext(ctx, identity, command)
	if err != nil {
		return nil, err
	}
	response, err := a.application.CreateTrainingRun(ctx, &internaltrainingv1.CreateTrainingRunRequest{Command: command})
	if err != nil {
		return nil, err
	}
	return publicOperation(response.GetOperation())
}

func (a *publicTrainingAdapter) GetTrainingRun(ctx context.Context, request *apiv1.GetResourceRequest) (*apiv1.TrainingRunView, error) {
	identity, err := a.identities.Resolve(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	name, err := internalResourceName(identity, request.GetName(), "trainingRuns")
	if err != nil {
		return nil, err
	}
	response, err := a.application.GetTrainingRun(ctx, &internaltrainingv1.GetTrainingRunRequest{Name: name})
	if err != nil {
		return nil, err
	}
	return publicTrainingRun(response.GetTrainingRun())
}

func (a *publicTrainingAdapter) ListTrainingRuns(ctx context.Context, request *apiv1.ListResourcesRequest) (*apiv1.TrainingRunList, error) {
	identity, err := a.identities.Resolve(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	if request == nil || request.GetParent() != projectParent(identity) {
		return nil, status.Error(codes.PermissionDenied, "parent is outside the authenticated scope")
	}
	response, err := a.application.ListTrainingRuns(ctx, &internaltrainingv1.ListTrainingRunsRequest{
		Parent: request.GetParent(),
		Page:   &commonv1.PageRequest{PageSize: request.GetPageSize(), PageToken: request.GetPageToken()},
		Filter: request.GetFilter(), OrderBy: request.GetOrderBy(),
	})
	if err != nil {
		return nil, err
	}
	result := &apiv1.TrainingRunList{Page: &apiv1.PageMetadata{NextPageToken: response.GetPage().GetNextPageToken()}}
	for _, value := range response.GetTrainingRuns() {
		projected, projectionErr := publicTrainingRun(value)
		if projectionErr != nil {
			return nil, projectionErr
		}
		result.TrainingRuns = append(result.TrainingRuns, projected)
	}
	return result, nil
}

func (a *publicTrainingAdapter) GetOperation(ctx context.Context, request *apiv1.GetResourceRequest) (*apiv1.Operation, error) {
	identity, err := a.identities.Resolve(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	name, err := internalResourceName(identity, request.GetName(), "operations")
	if err != nil {
		return nil, err
	}
	response, err := a.application.GetOperation(ctx, &internaljobv1.GetOperationRequest{Name: name})
	if err != nil {
		return nil, err
	}
	return publicOperation(response.GetOperation())
}

func (a *publicTrainingAdapter) CancelOperation(ctx context.Context, request *apiv1.CancelOperationRequest) (*apiv1.Operation, error) {
	identity, err := a.identities.Resolve(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	name, err := internalResourceName(identity, request.GetName(), "operations")
	if err != nil {
		return nil, err
	}
	internal := &internaljobv1.CancelOperationRequest{
		Name: name, Etag: incomingMetadata(ctx, "if-match"), Reason: request.GetCancellation().GetReason(),
	}
	internal.Context, err = publicCommandContext(ctx, identity, internal)
	if err != nil {
		return nil, err
	}
	response, err := a.application.CancelOperation(ctx, internal)
	if err != nil {
		return nil, err
	}
	return publicOperation(response.GetOperation())
}

func (a *publicTrainingAdapter) WatchOperation(request *apiv1.WatchOperationRequest, stream grpc.ServerStreamingServer[apiv1.OperationEvent]) error {
	identity, err := a.identities.Resolve(stream.Context())
	if err != nil {
		return status.Error(codes.Unauthenticated, "authenticated identity is required")
	}
	if request == nil {
		return status.Error(codes.InvalidArgument, "operation watch request is required")
	}
	publicName := request.GetName()
	name, err := internalResourceName(identity, publicName, "operations")
	if err != nil {
		return err
	}
	metadataValues, _ := metadata.FromIncomingContext(stream.Context())
	cursor, err := validateOptionalLastEventID(metadataValues.Get("last-event-id"))
	if err != nil {
		return status.Error(codes.InvalidArgument, "Last-Event-ID is invalid")
	}
	sequence := uint64(0)
	if cursor != "" {
		sequence, err = a.application.DecodeOperationCursor(cursor, publicName)
		if err != nil {
			return err
		}
	}
	return a.application.WatchOperation(
		&internaljobv1.WatchOperationRequest{Name: name, AfterSequence: sequence},
		&publicOperationStream{ServerStream: stream, send: stream.Send, encode: a.application.EncodeOperationCursor},
	)
}

type publicOperationStream struct {
	grpc.ServerStream
	send   func(*apiv1.OperationEvent) error
	encode func(string, uint64) (string, error)
}

func (s *publicOperationStream) Send(response *internaljobv1.WatchOperationResponse) error {
	if response == nil || response.GetOperation() == nil {
		return status.Error(codes.Internal, "operation watch returned an empty event")
	}
	if s.encode == nil {
		return status.Error(codes.Internal, "operation cursor encoder is unavailable")
	}
	cursor, err := s.encode(publicOperationName(response.GetOperation()), response.GetSequence())
	if err != nil {
		return status.Error(codes.Internal, "operation cursor encoding failed")
	}
	eventType := "operation.updated"
	if response.GetOperation().GetDone() {
		eventType = "operation.terminal"
	}
	operation, err := publicOperation(response.GetOperation())
	if err != nil {
		return err
	}
	return s.send(&apiv1.OperationEvent{
		EventId: cursor, Operation: operation, EventType: eventType,
		SchemaVersion: 1, OperationRevision: response.GetSequence(), ResumeCursor: cursor,
		EmittedAt: cloneTimestamp(response.GetObservedAt()),
	})
}

func publicCommandContext(ctx context.Context, identity trainingapp.Identity, command proto.Message) (*commonv1.CommandContext, error) {
	idempotencyKey := incomingMetadata(ctx, "idempotency-key")
	if idempotencyKey == "" || len(idempotencyKey) > 512 || strings.ContainsAny(idempotencyKey, "\x00\r\n") {
		return nil, status.Error(codes.InvalidArgument, "a bounded Idempotency-Key is required")
	}
	requestID, err := randomPublicID("req_")
	if err != nil {
		return nil, status.Error(codes.Internal, "request identity generation failed")
	}
	traceID := incomingMetadata(ctx, "x-trace-id")
	if traceID == "" {
		traceID, err = randomPublicID("trace_")
		if err != nil {
			return nil, status.Error(codes.Internal, "trace identity generation failed")
		}
	}
	value := &commonv1.CommandContext{
		RequestId: requestID, IdempotencyKey: idempotencyKey, PrincipalId: identity.Principal,
		TraceId: traceID, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
	}
	if deadline, ok := ctx.Deadline(); ok {
		value.Deadline = timestamppb.New(deadline.UTC())
	} else if header := incomingMetadata(ctx, "x-mindclade-deadline"); header != "" {
		parsed, parseErr := time.Parse(time.RFC3339Nano, header)
		if parseErr != nil || !time.Now().UTC().Before(parsed.UTC()) {
			return nil, status.Error(codes.InvalidArgument, "X-Mindclade-Deadline must be a future RFC3339 timestamp")
		}
		value.Deadline = timestamppb.New(parsed.UTC())
	}
	command.ProtoReflect().Set(
		command.ProtoReflect().Descriptor().Fields().ByName(protoreflect.Name("context")),
		protoreflect.ValueOfMessage(value.ProtoReflect()),
	)
	digest, err := canonicalDigest(command)
	if err != nil {
		return nil, status.Error(codes.Internal, "canonical request digest failed")
	}
	value.CanonicalRequestDigest = digest
	return value, nil
}

func canonicalDigest(command proto.Message) (string, error) {
	cloned := proto.Clone(command)
	message := cloned.ProtoReflect()
	contextField := message.Descriptor().Fields().ByName("context")
	if contextField == nil || contextField.Kind() != protoreflect.MessageKind {
		return "", errors.New("durable command has no context")
	}
	message.Clear(contextField)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(cloned)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func randomPublicID(prefix string) (string, error) {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(value), nil
}

func publicOperation(value *jobv1.Operation) (*apiv1.Operation, error) {
	if value == nil {
		return nil, nil
	}
	revision, err := numconv.Int64ToUint64(value.GetResourceVersion())
	if err != nil {
		return nil, status.Errorf(codes.Internal, "persisted operation revision is out of range: %v", err)
	}
	target, err := publicResource(value.GetTarget())
	if err != nil {
		return nil, err
	}
	result := &apiv1.Operation{
		Name: publicOperationName(value), Uid: resourceTail(value.GetOperationId()), Revision: revision,
		Etag: value.GetEtag(), State: strings.TrimPrefix(value.GetState().String(), "OPERATION_STATE_"),
		Done: value.GetDone(), CreateTime: cloneTimestamp(value.GetCreatedAt()),
		UpdateTime: cloneTimestamp(value.GetUpdatedAt()), Target: target,
	}
	if value.GetResult() != nil {
		manifest, projectionErr := publicArtifact(value.GetResult())
		if projectionErr != nil {
			return nil, projectionErr
		}
		result.Result = &apiv1.OperationResult{Manifest: manifest}
	}
	result.Error, err = publicError(value.GetError())
	if err != nil {
		return nil, status.Error(codes.Internal, "persisted operation error cannot be projected safely")
	}
	return result, nil
}

func publicOperationName(value *jobv1.Operation) string {
	if value == nil {
		return ""
	}
	return canonicalName(value.GetTenantId(), value.GetProjectId(), "operations", resourceTail(value.GetOperationId()))
}

func publicTrainingRun(value *trainingv1.TrainingRun) (*apiv1.TrainingRunView, error) {
	if value == nil {
		return nil, nil
	}
	revision, err := numconv.Int64ToUint64(value.GetRevision())
	if err != nil {
		return nil, status.Errorf(codes.Internal, "persisted training run revision is out of range: %v", err)
	}
	trainingRecipe, err := publicArtifact(value.GetTrainingRecipe())
	if err != nil {
		return nil, err
	}
	datasetRelease, err := publicResource(value.GetDatasetRelease())
	if err != nil {
		return nil, err
	}
	modelRelease, err := publicResource(value.GetModelRelease())
	if err != nil {
		return nil, err
	}
	hardwareTopology, err := publicArtifact(value.GetHardwareTopology())
	if err != nil {
		return nil, err
	}
	latestCheckpoint, err := publicResource(value.GetLatestCheckpoint())
	if err != nil {
		return nil, err
	}
	resultManifest, err := publicArtifact(value.GetResultManifest())
	if err != nil {
		return nil, err
	}
	tenantID := resourceTail(value.GetTenantName())
	projectID := resourceTail(value.GetProjectName())
	updated := value.GetCreateTime()
	if value.GetStartTime() != nil {
		updated = value.GetStartTime()
	}
	if value.GetCompleteTime() != nil {
		updated = value.GetCompleteTime()
	}
	projectedFailure, err := publicError(value.GetError())
	if err != nil {
		return nil, status.Error(codes.Internal, "persisted training error cannot be projected safely")
	}
	return &apiv1.TrainingRunView{
		Name: canonicalName(tenantID, projectID, "trainingRuns", resourceTail(value.GetName())),
		Uid:  value.GetUid(), Revision: revision, Etag: value.GetEtag(),
		CreateTime: cloneTimestamp(value.GetCreateTime()), UpdateTime: cloneTimestamp(updated),
		State:          strings.TrimPrefix(value.GetState().String(), "TRAINING_RUN_STATE_"),
		TrainingRecipe: trainingRecipe, DatasetRelease: datasetRelease,
		ModelRelease: modelRelease, HardwareTopology: hardwareTopology,
		LatestCheckpoint: latestCheckpoint, ResultManifest: resultManifest,
		Failure: projectedFailure,
	}, nil
}

func publicArtifact(value *artifactv1.ArtifactRef) (*apiv1.ArtifactRef, error) {
	if value == nil {
		return nil, nil
	}
	sizeBytes, err := numconv.Int64ToUint64(value.GetSizeBytes())
	if err != nil {
		return nil, status.Errorf(codes.Internal, "persisted artifact size is out of range: %v", err)
	}
	return &apiv1.ArtifactRef{
		Digest: value.GetDigest(), MediaType: value.GetMediaType(), SizeBytes: sizeBytes,
		ArtifactKind: value.GetArtifactKind(), SchemaId: value.GetSchemaId(), IntegrityDigest: value.GetIntegrityDigest(),
	}, nil
}

func domainArtifact(value *apiv1.ArtifactRef) (*artifactv1.ArtifactRef, error) {
	if value == nil {
		return nil, nil
	}
	if value.GetDigest() == "" || value.GetMediaType() == "" {
		return nil, status.Error(codes.InvalidArgument, "artifact digest and mediaType are required")
	}
	sizeBytes, err := numconv.Uint64ToInt64(value.GetSizeBytes())
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "artifact size is out of range: %v", err)
	}
	return &artifactv1.ArtifactRef{
		Digest: value.GetDigest(), MediaType: value.GetMediaType(), SizeBytes: sizeBytes,
		ArtifactKind: value.GetArtifactKind(), SchemaId: value.GetSchemaId(), IntegrityDigest: value.GetIntegrityDigest(),
	}, nil
}

func publicResource(value *commonv1.ResourceRef) (*apiv1.ResourceRef, error) {
	if value == nil {
		return nil, nil
	}
	revision, err := numconv.Int64ToUint64(value.GetResourceVersion())
	if err != nil {
		return nil, status.Errorf(codes.Internal, "persisted resource revision is out of range: %v", err)
	}
	name := value.GetName()
	if value.GetTenantId() != "" && value.GetProjectId() != "" && !strings.HasPrefix(name, "tenants/") {
		kind := publicCollection(value.GetResourceType())
		name = canonicalName(value.GetTenantId(), value.GetProjectId(), kind, resourceTail(name))
	}
	return &apiv1.ResourceRef{Name: name, Uid: value.GetResourceId(), Revision: revision}, nil
}

func domainResource(identity trainingapp.Identity, value *apiv1.ResourceRef, resourceType string) (*commonv1.ResourceRef, error) {
	if value == nil {
		return nil, nil
	}
	if value.GetName() == "" {
		return nil, status.Error(codes.InvalidArgument, "resource reference name is required")
	}
	revision, conversionErr := numconv.Uint64ToInt64(value.GetRevision())
	if conversionErr != nil {
		return nil, status.Errorf(codes.InvalidArgument, "resource reference revision exceeds PostgreSQL bigint: %v", conversionErr)
	}
	collection := publicCollection(resourceType)
	internal, err := internalResourceName(identity, value.GetName(), collection)
	if err != nil {
		return nil, err
	}
	id := value.GetUid()
	if id == "" {
		id = resourceTail(internal)
	}
	return &commonv1.ResourceRef{
		ResourceType: resourceType, ResourceId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		ResourceVersion: revision, Name: internal,
	}, nil
}

func publicError(value *commonv1.ErrorDetail) (*apiv1.PublicError, error) {
	if value == nil {
		return nil, nil
	}
	code, err := publicErrorCode(value.GetCode())
	if err != nil {
		return nil, err
	}
	requestID, err := randomPublicID("request_")
	if err != nil {
		return nil, errors.New("public error request identity generation failed")
	}
	detailCount := len(value.GetFieldViolations()) + len(value.GetPreconditionViolations())
	if value.GetSubject() != nil {
		detailCount++
	}
	if detailCount > 32 {
		return nil, errors.New("public error detail count exceeds the contract limit")
	}
	result := &apiv1.PublicError{
		Code: code, Message: "the operation failed", RequestId: requestID,
		Retryable:     value.GetRetryClass() == commonv1.RetryClass_RETRY_CLASS_SAFE,
		DiagnosticRef: value.GetErrorId(),
	}
	if retry := value.GetRetryAfter(); retry != nil {
		if err = retry.CheckValid(); err != nil {
			return nil, fmt.Errorf("public error retry-after is invalid: %w", err)
		}
		result.RetryAfter = retry.AsDuration().String()
	}
	for _, violation := range value.GetFieldViolations() {
		if violation == nil {
			return nil, errors.New("public error contains an empty field violation")
		}
		result.Details = append(result.Details, &apiv1.ErrorDetail{
			Kind: "fieldViolation", Field: violation.GetField(), Reason: violation.GetDescription(),
		})
	}
	for _, violation := range value.GetPreconditionViolations() {
		if violation == nil {
			return nil, errors.New("public error contains an empty precondition violation")
		}
		result.Details = append(result.Details, &apiv1.ErrorDetail{
			Kind: "precondition", Field: violation.GetSubject(), Reason: violation.GetDescription(),
			LimitName: violation.GetType(),
		})
	}
	if value.GetSubject() != nil {
		resource, projectionErr := publicResource(value.GetSubject())
		if projectionErr != nil {
			return nil, projectionErr
		}
		result.Details = append(result.Details, &apiv1.ErrorDetail{Kind: "resource", Resource: resource})
	}
	if err = validatePublicSSEError(result); err != nil {
		return nil, err
	}
	return result, nil
}

func publicErrorCode(value commonv1.ErrorCode) (string, error) {
	switch value {
	case commonv1.ErrorCode_ERROR_CODE_INVALID_ARGUMENT:
		return "INVALID_ARGUMENT", nil
	case commonv1.ErrorCode_ERROR_CODE_FAILED_PRECONDITION:
		return "FAILED_PRECONDITION", nil
	case commonv1.ErrorCode_ERROR_CODE_NOT_FOUND:
		return "NOT_FOUND", nil
	case commonv1.ErrorCode_ERROR_CODE_ALREADY_EXISTS,
		commonv1.ErrorCode_ERROR_CODE_ABORTED,
		commonv1.ErrorCode_ERROR_CODE_CONFLICT:
		return "CONFLICT", nil
	case commonv1.ErrorCode_ERROR_CODE_PERMISSION_DENIED,
		commonv1.ErrorCode_ERROR_CODE_POLICY_DENIED:
		return "PERMISSION_DENIED", nil
	case commonv1.ErrorCode_ERROR_CODE_UNAUTHENTICATED:
		return "AUTHENTICATION_REQUIRED", nil
	case commonv1.ErrorCode_ERROR_CODE_RESOURCE_EXHAUSTED:
		return "RATE_LIMITED", nil
	case commonv1.ErrorCode_ERROR_CODE_UNAVAILABLE:
		return "UNAVAILABLE", nil
	case commonv1.ErrorCode_ERROR_CODE_DEADLINE_EXCEEDED:
		return "DEADLINE_EXCEEDED", nil
	case commonv1.ErrorCode_ERROR_CODE_CANCELLED:
		return "CANCELLED", nil
	case commonv1.ErrorCode_ERROR_CODE_UNSUPPORTED:
		return "FAILED_PRECONDITION", nil
	case commonv1.ErrorCode_ERROR_CODE_INTERNAL,
		commonv1.ErrorCode_ERROR_CODE_DATA_LOSS:
		return "INTERNAL", nil
	case commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED:
		return "", errors.New("public error code is unspecified")
	default:
		return "", fmt.Errorf("public error code %d is unknown", value)
	}
}

func projectParent(identity trainingapp.Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func canonicalName(tenantID, projectID, collection, id string) string {
	return "tenants/" + tenantID + "/projects/" + projectID + "/" + collection + "/" + id
}

func internalResourceName(identity trainingapp.Identity, name, collection string) (string, error) {
	prefix := projectParent(identity) + "/" + collection + "/"
	if !strings.HasPrefix(name, prefix) {
		return "", status.Error(codes.PermissionDenied, "resource is outside the authenticated scope")
	}
	id := strings.TrimPrefix(name, prefix)
	if !validResourceID(id) {
		return "", status.Error(codes.InvalidArgument, "resource name is invalid")
	}
	return collection + "/" + id, nil
}

func publicCollection(resourceType string) string {
	switch resourceType {
	case "dataset_release":
		return "datasetReleases"
	case "model_release":
		return "modelReleases"
	case "use_policy", "policy":
		return "policies"
	case "checkpoint":
		return "checkpoints"
	case "training_run":
		return "trainingRuns"
	case "operation":
		return "operations"
	default:
		return resourceType + "s"
	}
}

func validResourceID(value string) bool {
	if value == "" || len(value) > 128 || strings.TrimSpace(value) != value {
		return false
	}
	for _, character := range value {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || character == '-' || character == '_' || character == '.' {
			continue
		}
		return false
	}
	return true
}

func resourceTail(name string) string {
	if index := strings.LastIndexByte(name, '/'); index >= 0 {
		return name[index+1:]
	}
	return name
}

func incomingMetadata(ctx context.Context, name string) string {
	values, _ := metadata.FromIncomingContext(ctx)
	return first(values.Get(strings.ToLower(name)))
}

func cloneTimestamp(value *timestamppb.Timestamp) *timestamppb.Timestamp {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*timestamppb.Timestamp)
}

func cloneStringMap(value map[string]string) map[string]string {
	if value == nil {
		return nil
	}
	result := make(map[string]string, len(value))
	for key, item := range value {
		result[key] = item
	}
	return result
}
