package mindclade

import (
	"context"
	"strings"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

const jobPageSizeMaximum = 200

// JobService is the generated-type-only private facade for durable admitted
// work. Identity is projected from authenticated client configuration, never
// accepted from a handwritten wire model.
type JobService struct {
	client    *Client
	transport internaljobv1.JobServiceClient
}

// Request admits generated job intent and returns fresh generated Job and
// Operation values. The caller-owned command is never mutated.
func (service *JobService) Request(ctx context.Context, command *jobv1.RequestJobCommand, options ...RequestOption) (*jobv1.Job, *operationv1.Operation, error) {
	if !service.configured() || command == nil || !validResourceLeafSDK(command.GetJobKind()) ||
		!validJobArtifact(command.GetConfiguration(), true) || !validJobArtifact(command.GetInput(), false) ||
		(command.GetRequestedJobId() != "" && !validResourceLeafSDK(command.GetRequestedJobId())) {
		return nil, nil, invalidArgument("job request requires a valid kind, optional ID, and content-addressed configuration")
	}
	value := cloneGenerated(command)
	commandKey := value.GetContext().GetIdempotencyKey()
	value.Context = nil
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, commandKey, options...)
	if err != nil {
		return nil, nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.RequestJob(callContext, &internaljobv1.RequestJobRequest{Command: value})
	if err != nil {
		return nil, nil, normalizeError(err)
	}
	if response.GetJob() == nil || response.GetOperation() == nil || !service.validJob(response.GetJob()) || !service.validOperation(response.GetOperation()) ||
		response.GetJob().GetOperationId() != response.GetOperation().GetOperationId() || response.GetOperation().GetJobId() != response.GetJob().GetJobId() {
		return nil, nil, protocolDataLoss("RequestJob returned inconsistent durable identities")
	}
	return cloneGenerated(response.GetJob()), cloneGenerated(response.GetOperation()), nil
}

// Get reads one durable generated job revision.
func (service *JobService) Get(ctx context.Context, name, ifNoneMatch string, options ...RequestOption) (*jobv1.Job, error) {
	canonical, err := canonicalJobResource(service.client, name, "jobs")
	if !service.configured() || err != nil || len(ifNoneMatch) > 512 || strings.ContainsAny(ifNoneMatch, "\x00\r\n") {
		return nil, invalidArgument("job name or cache validator is invalid")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetJob(callContext, &internaljobv1.GetJobRequest{Name: canonical, IfNoneMatch: ifNoneMatch})
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetJob() == nil || !service.validJob(response.GetJob()) || response.GetJob().GetJobId() != canonical {
		return nil, protocolDataLoss("GetJob returned inconsistent durable state")
	}
	return cloneGenerated(response.GetJob()), nil
}

// JobPage is one bounded list response plus cursor-scheme traversal. The
// embedded generated response remains the authoritative model; the wrapper
// adds only the opaque-cursor mechanics.
type JobPage struct {
	*internaljobv1.ListJobsResponse
	pageBase[*jobv1.Job, *JobPage]
}

// Items returns this page's jobs without traversing any further page.
func (page *JobPage) Items() []*jobv1.Job { return page.GetJobs() }

// List returns one bounded project-scoped page and preserves opaque tokens.
func (service *JobService) List(ctx context.Context, request *internaljobv1.ListJobsRequest, options ...RequestOption) (*JobPage, error) {
	if !service.configured() {
		return nil, invalidArgument("job service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internaljobv1.ListJobsRequest{}
	}
	parent := projectName(service.client.config.TenantID, service.client.config.ProjectID)
	if (value.GetParent() != "" && value.GetParent() != parent) || value.GetPage().GetPageSize() > jobPageSizeMaximum ||
		strings.TrimSpace(value.GetFilter()) != "" || (value.GetOrderBy() != "" && value.GetOrderBy() != "job_id") {
		return nil, invalidArgument("job list scope, page size, filter, or ordering is invalid")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListJobs(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListJobs returned no response")
	}
	for _, job := range response.GetJobs() {
		if !service.validJob(job) {
			return nil, protocolDataLoss("ListJobs returned a job outside configured scope")
		}
	}
	detached := cloneGenerated(response)
	page := &JobPage{ListJobsResponse: detached}
	page.pageBase = newPage[*jobv1.Job](page, detached.GetPage(), paginationLimitsFrom(options), func(ctx context.Context, token string) (*JobPage, error) {
		successor := cloneGenerated(value)
		successor.Page = pageRequestWithToken(value.GetPage(), token)
		return service.List(ctx, successor, options...)
	})
	return page, nil
}

// Cancel records monotonic cancellation under an ETag precondition.
func (service *JobService) Cancel(ctx context.Context, request *internaljobv1.CancelJobRequest, options ...RequestOption) (*operationv1.Operation, error) {
	if !service.configured() || request == nil {
		return nil, invalidArgument("configured job service and generated cancellation request are required")
	}
	value := cloneGenerated(request)
	name, err := canonicalJobResource(service.client, value.GetName(), "jobs")
	if err != nil || strings.TrimSpace(value.GetEtag()) == "" || len(value.GetEtag()) > 512 || strings.ContainsAny(value.GetEtag(), "\x00\r\n") ||
		len(value.GetReason()) > 4096 || strings.ContainsRune(value.GetReason(), '\x00') {
		return nil, invalidArgument("job cancellation requires a valid job, ETag, and bounded reason")
	}
	value.Name = name
	commandKey := value.GetContext().GetIdempotencyKey()
	value.Context = nil
	callContext, metadata, cancel, err := service.client.mutationContext(ctx, commandKey, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	digest, err := deterministicDigest(value)
	if err != nil {
		return nil, err
	}
	value.Context = commandContext(service.client.config, callContext, metadata, digest)
	response, err := service.transport.CancelJob(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetOperation() == nil || !service.validOperation(response.GetOperation()) || response.GetOperation().GetJobId() != name {
		return nil, protocolDataLoss("CancelJob returned an inconsistent operation")
	}
	return cloneGenerated(response.GetOperation()), nil
}

func (service *JobService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil && service.client.config.TenantID != "" && service.client.config.ProjectID != ""
}

func (service *JobService) validJob(value *jobv1.Job) bool {
	return value != nil && value.GetTenantId() == service.client.config.TenantID && value.GetProjectId() == service.client.config.ProjectID &&
		canonicalCollectionID(value.GetJobId(), "jobs") != "" && canonicalCollectionID(value.GetOperationId(), "operations") != "" && value.GetResourceVersion() > 0 && value.GetState() != jobv1.JobState_JOB_STATE_UNSPECIFIED
}

func (service *JobService) validOperation(value *operationv1.Operation) bool {
	return value != nil && value.GetTenantId() == service.client.config.TenantID && value.GetProjectId() == service.client.config.ProjectID &&
		canonicalCollectionID(value.GetOperationId(), "operations") != "" && value.GetResourceVersion() > 0 && value.GetState() != operationv1.OperationState_OPERATION_STATE_UNSPECIFIED
}

func validJobArtifact(value *artifactv1.ArtifactRef, required bool) bool {
	if value == nil {
		return !required
	}
	return validSHA256Digest(value.GetDigest()) && strings.TrimSpace(value.GetMediaType()) != "" && value.GetSizeBytes() >= 0
}

func validResourceLeafSDK(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > 255 || strings.Contains(value, "/") || hasControlCharacters(value) {
		return false
	}
	for _, character := range value {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || character == '-' || character == '_' || character == '.' {
			continue
		}
		return false
	}
	return true
}

func canonicalCollectionID(value, collection string) string {
	parts := strings.Split(strings.TrimSpace(value), "/")
	if len(parts) == 2 && parts[0] == collection && validResourceLeafSDK(parts[1]) {
		return value
	}
	return ""
}

func canonicalJobResource(client *Client, value, collection string) (string, error) {
	if client == nil {
		return "", invalidArgument(collection + " service is not configured")
	}
	value = strings.TrimSpace(value)
	if validResourceLeafSDK(value) {
		return collection + "/" + value, nil
	}
	if canonical := canonicalCollectionID(value, collection); canonical != "" {
		return canonical, nil
	}
	prefix := projectName(client.config.TenantID, client.config.ProjectID) + "/" + collection + "/"
	if strings.HasPrefix(value, prefix) && validResourceLeafSDK(strings.TrimPrefix(value, prefix)) {
		return collection + "/" + strings.TrimPrefix(value, prefix), nil
	}
	return "", invalidArgument(collection + " resource must be in the configured project")
}
