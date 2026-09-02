package mindclade

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"reflect"
	"strings"

	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type requestContextKey struct{}

type requestMetadata struct {
	requestID      string
	traceID        string
	idempotencyKey string
	leaseToken     string
}

// RequestOption applies per-call metadata without changing a generated wire
// request. The server binds tenant and principal claims from authenticated
// transport identity and validates command context against those claims.
type RequestOption func(*requestMetadata)

func WithRequestID(requestID string) RequestOption {
	return func(value *requestMetadata) { value.requestID = strings.TrimSpace(requestID) }
}

func WithTraceID(traceID string) RequestOption {
	return func(value *requestMetadata) { value.traceID = strings.TrimSpace(traceID) }
}

func WithIdempotencyKey(idempotencyKey string) RequestOption {
	return func(value *requestMetadata) { value.idempotencyKey = strings.TrimSpace(idempotencyKey) }
}

// WithLeaseToken attaches the current scheduler-issued raw lease credential
// as transport metadata. It is never copied into generated protobuf state,
// request digests, errors, observer callbacks, or logs.
func WithLeaseToken(leaseToken string) RequestOption {
	return func(value *requestMetadata) { value.leaseToken = strings.TrimSpace(leaseToken) }
}

func withRequestOptions(ctx context.Context, options ...RequestOption) (context.Context, requestMetadata, error) {
	value := requestMetadata{}
	if existing, ok := ctx.Value(requestContextKey{}).(requestMetadata); ok {
		value = existing
	}
	for _, option := range options {
		if option != nil {
			option(&value)
		}
	}
	if value.requestID == "" {
		generated, err := randomID()
		if err != nil {
			return nil, requestMetadata{}, err
		}
		value.requestID = generated
	}
	if value.traceID == "" {
		value.traceID = value.requestID
	}
	if value.leaseToken != "" {
		if len(value.leaseToken) > 4096 || strings.ContainsAny(value.leaseToken, " \t\r\n\x00") {
			return nil, requestMetadata{}, invalidArgument("lease token contains unsafe metadata characters")
		}
	}
	return context.WithValue(ctx, requestContextKey{}, value), value, nil
}

// mutationContext establishes one bounded call identity and guarantees an
// idempotency key. A caller may provide the key through RequestOption; a key
// already carried by a generated command is used only when no behavior option
// was supplied. Identity fields from a caller-provided CommandContext are
// never trusted or forwarded.
func (client *Client) mutationContext(
	ctx context.Context,
	commandKey string,
	options ...RequestOption,
) (context.Context, requestMetadata, context.CancelFunc, error) {
	callContext, request, cancel, err := client.context(ctx, options...)
	if err != nil {
		return nil, requestMetadata{}, cancel, err
	}
	if request.idempotencyKey != "" {
		if err = validateMetadataIdentifier("idempotency key", request.idempotencyKey); err != nil {
			cancel()
			return nil, requestMetadata{}, func() {}, err
		}
		return callContext, request, cancel, nil
	}
	key := strings.TrimSpace(commandKey)
	if key == "" {
		key, err = randomID()
		if err != nil {
			cancel()
			return nil, requestMetadata{}, func() {}, err
		}
	}
	if err = validateMetadataIdentifier("idempotency key", key); err != nil {
		cancel()
		return nil, requestMetadata{}, func() {}, err
	}
	callContext, request, err = withRequestOptions(callContext, WithIdempotencyKey(key))
	if err != nil {
		cancel()
		return nil, requestMetadata{}, func() {}, err
	}
	return callContext, request, cancel, nil
}

func attachRequestMetadata(ctx context.Context, config Config, method string) context.Context {
	value, _ := ctx.Value(requestContextKey{}).(requestMetadata)
	pairs := []string{
		"x-mindclade-sdk", config.UserAgent,
		"x-request-id", value.requestID,
		"x-trace-id", value.traceID,
	}
	if value.idempotencyKey != "" {
		pairs = append(pairs, "idempotency-key", value.idempotencyKey)
	}
	if value.leaseToken != "" && leaseCredentialMethods[method] {
		pairs = append(pairs, "x-mindclade-lease-token", value.leaseToken)
	}
	if config.TenantID != "" {
		pairs = append(pairs, "x-mindclade-expected-tenant", config.TenantID)
	}
	if config.ProjectID != "" {
		pairs = append(pairs, "x-mindclade-expected-project", config.ProjectID)
	}
	if config.PrincipalID != "" {
		pairs = append(pairs, "x-mindclade-expected-principal", config.PrincipalID)
	}
	return metadata.AppendToOutgoingContext(ctx, pairs...)
}

var leaseCredentialMethods = map[string]bool{
	"/mindclade.internal.job.v1.RunService/RenewAttemptLease":                    true,
	"/mindclade.internal.job.v1.RunService/HeartbeatAttempt":                     true,
	"/mindclade.internal.job.v1.RunService/CancelAttempt":                        true,
	"/mindclade.internal.job.v1.RunService/CommitAttempt":                        true,
	"/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition":   true,
	"/mindclade.internal.agent.v1.AgentService/CommitAgentStep":                  true,
	"/mindclade.internal.agent.v1.AgentService/CommitToolReceipt":                true,
	"/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult": true,
	"/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt":       true,
	"/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt":      true,
	"/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress":     true,
	"/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint":          true,
	"/mindclade.internal.training.v1.TrainingService/CommitCheckpoint":           true,
	"/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun":        true,
}

func randomID() (string, error) {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return "", &Error{Code: CodeInternal, Message: "secure request ID generation failed", Cause: err}
	}
	return hex.EncodeToString(value), nil
}

func commandContext(config Config, ctx context.Context, request requestMetadata, canonicalDigest string) *commonv1.CommandContext {
	deadline, _ := ctx.Deadline()
	return &commonv1.CommandContext{
		RequestId:              request.requestID,
		IdempotencyKey:         request.idempotencyKey,
		PrincipalId:            config.PrincipalID,
		TraceId:                request.traceID,
		Deadline:               timestamppb.New(deadline),
		CanonicalRequestDigest: canonicalDigest,
		TenantId:               config.TenantID,
		ProjectId:              config.ProjectID,
		CorrelationId:          request.traceID,
	}
}

func projectName(tenantID, projectID string) string {
	if strings.HasPrefix(projectID, "tenants/") {
		return projectID
	}
	if tenantID == "" && !strings.HasPrefix(projectID, "projects/") {
		return "projects/" + projectID
	}
	tenant := tenantID
	if !strings.HasPrefix(tenant, "tenants/") {
		tenant = "tenants/" + tenant
	}
	if strings.HasPrefix(projectID, "projects/") {
		return tenant + "/" + projectID
	}
	return tenant + "/projects/" + projectID
}

func cloneGenerated[T proto.Message](value T) T {
	reflected := reflect.ValueOf(value)
	if any(value) == nil || (reflected.Kind() == reflect.Pointer && reflected.IsNil()) {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}
