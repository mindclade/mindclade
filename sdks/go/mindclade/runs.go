package mindclade

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

const (
	minimumAttemptLease = 5 * time.Second
	maximumAttemptLease = 15 * time.Minute
	leaseTokenHeaderSDK = "x-mindclade-lease-token" // #nosec G101 -- metadata header name, never a credential value.
)

// LeaseCredential is a redacting handle for a scheduler-issued capability.
// The raw token cannot be read or serialized; it is used only by fenced SDK
// calls as gRPC metadata.
type LeaseCredential struct{ token string }

func (LeaseCredential) String() string   { return "LeaseCredential(<redacted>)" }
func (LeaseCredential) GoString() string { return "LeaseCredential(<redacted>)" }

func (credential LeaseCredential) valid() bool {
	return len(credential.token) >= 32 && len(credential.token) <= 4096 && strings.TrimSpace(credential.token) == credential.token && !strings.ContainsAny(credential.token, " \t\r\n\x00")
}

// LeaseGrant combines authoritative generated state with a non-serializable
// behavior credential. Accessors return fresh protobuf clones.
type LeaseGrant struct {
	attempt    *jobv1.Attempt
	fence      *jobv1.LeaseFence
	credential LeaseCredential
}

func (grant *LeaseGrant) Attempt() *jobv1.Attempt {
	if grant == nil {
		return nil
	}
	return cloneGenerated(grant.attempt)
}

func (grant *LeaseGrant) Fence() *jobv1.LeaseFence {
	if grant == nil {
		return nil
	}
	return cloneGenerated(grant.fence)
}

func (grant *LeaseGrant) Credential() LeaseCredential {
	if grant == nil {
		return LeaseCredential{}
	}
	return grant.credential
}

// RunService owns worker-safe ergonomics over generated RunService transport.
// It never exposes database, queue, or storage implementation details.
type RunService struct {
	client    *Client
	transport internaljobv1.RunServiceClient
}

func (service *RunService) GetRun(ctx context.Context, name string, options ...RequestOption) (*jobv1.Run, error) {
	canonical, err := canonicalJobResource(service.client, name, "runs")
	if !service.configured() || err != nil {
		return nil, invalidArgument("run name must be in configured scope")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetRun(callContext, &internaljobv1.GetRunRequest{Name: canonical})
	if err != nil {
		return nil, normalizeError(err)
	}
	if !service.validRun(response.GetRun()) || response.GetRun().GetRunId() != canonical {
		return nil, protocolDataLoss("GetRun returned inconsistent durable state")
	}
	return cloneGenerated(response.GetRun()), nil
}

func (service *RunService) ListRuns(ctx context.Context, request *internaljobv1.ListRunsRequest, options ...RequestOption) (*internaljobv1.ListRunsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("run service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internaljobv1.ListRunsRequest{}
	}
	parent, err := canonicalJobResource(service.client, value.GetParent(), "jobs")
	if err != nil || value.GetPage().GetPageSize() > jobPageSizeMaximum || strings.TrimSpace(value.GetFilter()) != "" {
		return nil, invalidArgument("run list parent, page, or filter is invalid")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListRuns(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListRuns returned no response")
	}
	for _, run := range response.GetRuns() {
		if !service.validRun(run) || run.GetJobId() != parent {
			return nil, protocolDataLoss("ListRuns returned inconsistent scope")
		}
	}
	return cloneGenerated(response), nil
}

func (service *RunService) GetAttempt(ctx context.Context, name string, options ...RequestOption) (*jobv1.Attempt, error) {
	canonical, err := canonicalJobResource(service.client, name, "attempts")
	if !service.configured() || err != nil {
		return nil, invalidArgument("attempt name must be in configured scope")
	}
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.GetAttempt(callContext, &internaljobv1.GetAttemptRequest{Name: canonical})
	if err != nil {
		return nil, normalizeError(err)
	}
	if !service.validAttempt(response.GetAttempt()) || response.GetAttempt().GetAttemptId() != canonical {
		return nil, protocolDataLoss("GetAttempt returned inconsistent durable state")
	}
	return cloneGenerated(response.GetAttempt()), nil
}

func (service *RunService) ListAttempts(ctx context.Context, request *internaljobv1.ListAttemptsRequest, options ...RequestOption) (*internaljobv1.ListAttemptsResponse, error) {
	if !service.configured() {
		return nil, invalidArgument("run service is not configured")
	}
	value := cloneGenerated(request)
	if value == nil {
		value = &internaljobv1.ListAttemptsRequest{}
	}
	parent, err := canonicalJobResource(service.client, value.GetParent(), "runs")
	if err != nil || value.GetPage().GetPageSize() > jobPageSizeMaximum {
		return nil, invalidArgument("attempt list parent or page is invalid")
	}
	value.Parent = parent
	callContext, _, cancel, err := service.client.context(ctx, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.ListAttempts(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response == nil {
		return nil, protocolDataLoss("ListAttempts returned no response")
	}
	for _, attempt := range response.GetAttempts() {
		if !service.validAttempt(attempt) || attempt.GetRunId() != parent {
			return nil, protocolDataLoss("ListAttempts returned inconsistent scope")
		}
	}
	return cloneGenerated(response), nil
}

// AcquireAttemptLease atomically obtains a generated attempt/fence and captures
// the raw token from response metadata into a redacting behavior handle.
func (service *RunService) AcquireAttemptLease(ctx context.Context, request *internaljobv1.AcquireAttemptLeaseRequest, options ...RequestOption) (*LeaseGrant, error) {
	if !service.configured() || request == nil {
		return nil, invalidArgument("generated lease request is required")
	}
	value := cloneGenerated(request)
	name, err := canonicalJobResource(service.client, value.GetRunName(), "runs")
	if err != nil || !validResourceLeafSDK(value.GetAttemptId()) || !validLeaseDuration(value.GetLeaseDuration()) {
		return nil, invalidArgument("lease acquisition requires a run, attempt ID, and duration between 5 seconds and 15 minutes")
	}
	value.RunName = name
	callContext, _, cancel, err := service.prepareMutation(ctx, value, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	var headers metadata.MD
	response, err := service.transport.AcquireAttemptLease(callContext, value, grpc.Header(&headers))
	if err != nil {
		return nil, normalizeError(err)
	}
	tokens := headers.Get(leaseTokenHeaderSDK)
	if len(tokens) != 1 {
		return nil, protocolDataLoss("AcquireAttemptLease omitted its confidential lease credential")
	}
	credential := LeaseCredential{token: tokens[0]}
	if !credential.valid() || !service.validLeaseResponse(response.GetAttempt(), response.GetFence()) || !tokenMatchesFence(credential.token, response.GetFence()) {
		return nil, protocolDataLoss("AcquireAttemptLease returned inconsistent lease authority")
	}
	return newLeaseGrant(response.GetAttempt(), response.GetFence(), credential), nil
}

func (service *RunService) RenewAttemptLease(ctx context.Context, request *internaljobv1.RenewAttemptLeaseRequest, credential LeaseCredential, options ...RequestOption) (*LeaseGrant, error) {
	if request == nil || !credential.valid() || request.GetExpectedResourceVersion() < 1 || !validLeaseDuration(request.GetLeaseDuration()) {
		return nil, invalidArgument("lease renewal requires current credential, revision, fence, and bounded duration")
	}
	value := cloneGenerated(request)
	if err := service.normalizeFence(value.GetFence()); err != nil {
		return nil, err
	}
	callContext, _, cancel, err := service.prepareFencedMutation(ctx, value, credential, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.RenewAttemptLease(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if !service.validLeaseResponse(response.GetAttempt(), response.GetFence()) || !tokenMatchesFence(credential.token, response.GetFence()) {
		return nil, protocolDataLoss("RenewAttemptLease returned inconsistent lease authority")
	}
	return newLeaseGrant(response.GetAttempt(), response.GetFence(), credential), nil
}

func (service *RunService) HeartbeatAttempt(ctx context.Context, request *internaljobv1.HeartbeatAttemptRequest, credential LeaseCredential, options ...RequestOption) (*internaljobv1.HeartbeatAttemptResponse, error) {
	if request == nil || !credential.valid() || request.GetExpectedResourceVersion() < 1 || !validLeaseDuration(request.GetLeaseDuration()) {
		return nil, invalidArgument("heartbeat requires current credential, revision, fence, and bounded duration")
	}
	value := cloneGenerated(request)
	if err := service.normalizeFence(value.GetFence()); err != nil {
		return nil, err
	}
	callContext, _, cancel, err := service.prepareFencedMutation(ctx, value, credential, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.HeartbeatAttempt(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if response.GetObservedAt() == nil || response.GetObservedAt().CheckValid() != nil || !service.validLeaseResponse(response.GetAttempt(), response.GetFence()) || !tokenMatchesFence(credential.token, response.GetFence()) {
		return nil, protocolDataLoss("HeartbeatAttempt returned inconsistent lease authority")
	}
	return cloneGenerated(response), nil
}

func (service *RunService) CancelAttempt(ctx context.Context, request *internaljobv1.CancelAttemptRequest, credential LeaseCredential, options ...RequestOption) (*internaljobv1.CancelAttemptResponse, error) {
	if request == nil || !credential.valid() || request.GetExpectedResourceVersion() < 1 || len(request.GetReason()) > 1024 || strings.ContainsRune(request.GetReason(), '\x00') {
		return nil, invalidArgument("attempt cancellation requires current credential, revision, fence, and bounded reason")
	}
	value := cloneGenerated(request)
	if err := service.normalizeFence(value.GetFence()); err != nil {
		return nil, err
	}
	callContext, _, cancel, err := service.prepareFencedMutation(ctx, value, credential, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CancelAttempt(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if !service.validAttempt(response.GetAttempt()) || !service.validRun(response.GetRun()) || response.GetAttempt().GetRunId() != response.GetRun().GetRunId() || response.GetAttempt().GetJobId() != response.GetRun().GetJobId() {
		return nil, protocolDataLoss("CancelAttempt returned inconsistent durable state")
	}
	return cloneGenerated(response), nil
}

func (service *RunService) CommitAttempt(ctx context.Context, request *internaljobv1.CommitAttemptRequest, credential LeaseCredential, options ...RequestOption) (*internaljobv1.CommitAttemptResponse, error) {
	if request == nil || !credential.valid() || request.GetExpectedResourceVersion() < 1 || request.GetAttempt() == nil || !validAttemptUpdateMask(request.GetUpdateMask()) {
		return nil, invalidArgument("attempt commit requires current credential, revision, generated attempt, fence, and state update mask")
	}
	value := cloneGenerated(request)
	if err := service.normalizeFence(value.GetFence()); err != nil {
		return nil, err
	}
	if !service.validAttempt(value.GetAttempt()) || value.GetAttempt().GetAttemptId() != value.GetFence().GetAttemptId() || value.GetAttempt().GetRunId() != value.GetFence().GetRunId() || value.GetAttempt().GetLeaseEpoch() != value.GetFence().GetLeaseEpoch() {
		return nil, invalidArgument("attempt commit identity does not match current fence")
	}
	callContext, _, cancel, err := service.prepareFencedMutation(ctx, value, credential, options...)
	if err != nil {
		return nil, err
	}
	defer cancel()
	response, err := service.transport.CommitAttempt(callContext, value)
	if err != nil {
		return nil, normalizeError(err)
	}
	if !service.validAttempt(response.GetAttempt()) || !service.validRun(response.GetRun()) || response.GetAttempt().GetRunId() != response.GetRun().GetRunId() || response.GetAttempt().GetJobId() != response.GetRun().GetJobId() {
		return nil, protocolDataLoss("CommitAttempt returned inconsistent durable state")
	}
	return cloneGenerated(response), nil
}

type runMutationRequest interface {
	proto.Message
	GetContext() *commonv1.CommandContext
}

func (service *RunService) prepareMutation(ctx context.Context, message runMutationRequest, options ...RequestOption) (context.Context, requestMetadata, context.CancelFunc, error) {
	return service.prepareProtoMutation(ctx, message, false, LeaseCredential{}, options...)
}

func (service *RunService) prepareFencedMutation(ctx context.Context, message runMutationRequest, credential LeaseCredential, options ...RequestOption) (context.Context, requestMetadata, context.CancelFunc, error) {
	return service.prepareProtoMutation(ctx, message, true, credential, options...)
}

func (service *RunService) prepareProtoMutation(ctx context.Context, value runMutationRequest, fenced bool, credential LeaseCredential, options ...RequestOption) (context.Context, requestMetadata, context.CancelFunc, error) {
	key := value.GetContext().GetIdempotencyKey()
	if fenced {
		options = append(options, WithLeaseToken(credential.token))
	}
	callContext, metadataValue, cancel, err := service.client.mutationContext(ctx, key, options...)
	if err != nil {
		return nil, requestMetadata{}, cancel, err
	}
	reflection := value.ProtoReflect()
	field := reflection.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if field == nil {
		cancel()
		return nil, requestMetadata{}, func() {}, invalidArgument("generated mutation has no command context")
	}
	reflection.Clear(field)
	digest, err := deterministicDigest(value)
	if err != nil {
		cancel()
		return nil, requestMetadata{}, func() {}, err
	}
	reflection.Set(field, protoreflect.ValueOfMessage(commandContext(service.client.config, callContext, metadataValue, digest).ProtoReflect()))
	return callContext, metadataValue, cancel, nil
}

func (service *RunService) configured() bool {
	return service != nil && service.client != nil && service.transport != nil && service.client.config.TenantID != "" && service.client.config.ProjectID != ""
}

func (service *RunService) validRun(value *jobv1.Run) bool {
	return value != nil && value.GetTenantId() == service.client.config.TenantID && value.GetProjectId() == service.client.config.ProjectID && canonicalCollectionID(value.GetRunId(), "runs") != "" && canonicalCollectionID(value.GetJobId(), "jobs") != "" && value.GetResourceVersion() > 0 && value.GetState() != jobv1.RunState_RUN_STATE_UNSPECIFIED
}

func (service *RunService) validAttempt(value *jobv1.Attempt) bool {
	return value != nil && value.GetTenantId() == service.client.config.TenantID && value.GetProjectId() == service.client.config.ProjectID && canonicalCollectionID(value.GetAttemptId(), "attempts") != "" && canonicalCollectionID(value.GetRunId(), "runs") != "" && canonicalCollectionID(value.GetJobId(), "jobs") != "" && value.GetLeaseEpoch() > 0 && value.GetResourceVersion() > 0 && value.GetState() != jobv1.AttemptState_ATTEMPT_STATE_UNSPECIFIED
}

func (service *RunService) validLeaseResponse(attempt *jobv1.Attempt, fence *jobv1.LeaseFence) bool {
	return service.validAttempt(attempt) && fence != nil && attempt.GetAttemptId() == fence.GetAttemptId() && attempt.GetRunId() == fence.GetRunId() && attempt.GetJobId() == fence.GetJobId() && attempt.GetLeaseEpoch() == fence.GetLeaseEpoch() && fence.GetTenantId() == service.client.config.TenantID && fence.GetProjectId() == service.client.config.ProjectID && fence.GetDeadline() != nil && fence.GetDeadline().CheckValid() == nil && time.Now().Before(fence.GetDeadline().AsTime()) && validSHA256Digest(fence.GetLeaseTokenDigest())
}

func (service *RunService) normalizeFence(fence *jobv1.LeaseFence) error {
	if fence == nil || canonicalCollectionID(fence.GetJobId(), "jobs") == "" || canonicalCollectionID(fence.GetRunId(), "runs") == "" || canonicalCollectionID(fence.GetAttemptId(), "attempts") == "" || fence.GetLeaseEpoch() == 0 || fence.GetDeadline() == nil || fence.GetDeadline().CheckValid() != nil || !time.Now().Before(fence.GetDeadline().AsTime()) || !validSHA256Digest(fence.GetLeaseTokenDigest()) {
		return invalidArgument("current complete lease fence is required")
	}
	if fence.GetTenantId() != "" && fence.GetTenantId() != service.client.config.TenantID || fence.GetProjectId() != "" && fence.GetProjectId() != service.client.config.ProjectID {
		return invalidArgument("lease fence conflicts with configured scope")
	}
	fence.TenantId, fence.ProjectId = service.client.config.TenantID, service.client.config.ProjectID
	return nil
}

func validLeaseDuration(value *durationpb.Duration) bool {
	return value != nil && value.CheckValid() == nil && value.AsDuration() >= minimumAttemptLease && value.AsDuration() <= maximumAttemptLease
}

func validAttemptUpdateMask(mask *fieldmaskpb.FieldMask) bool {
	if mask == nil || len(mask.Paths) == 0 || len(mask.Paths) > 3 {
		return false
	}
	allowed := map[string]bool{"state": true, "outputs": true, "error": true}
	seen := map[string]bool{}
	for _, path := range mask.Paths {
		if !allowed[path] || seen[path] {
			return false
		}
		seen[path] = true
	}
	return seen["state"]
}

func tokenMatchesFence(token string, fence *jobv1.LeaseFence) bool {
	if fence == nil {
		return false
	}
	sum := sha256.Sum256([]byte(token))
	digest := "sha256:" + hex.EncodeToString(sum[:])
	return len(digest) == len(fence.GetLeaseTokenDigest()) && subtle.ConstantTimeCompare([]byte(digest), []byte(fence.GetLeaseTokenDigest())) == 1
}

func newLeaseGrant(attempt *jobv1.Attempt, fence *jobv1.LeaseFence, credential LeaseCredential) *LeaseGrant {
	return &LeaseGrant{attempt: cloneGenerated(attempt), fence: cloneGenerated(fence), credential: credential}
}

var _ fmt.Stringer = LeaseCredential{}
