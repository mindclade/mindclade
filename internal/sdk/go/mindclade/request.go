package mindclade

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"iter"
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

const (
	defaultPaginationMaxPages = 100
	defaultPaginationMaxItems = 10_000
	hardPaginationMaxPages    = 1_000
	hardPaginationMaxItems    = 1_000_000
)

// PaginationLimits bound automatic traversal so a changing collection or a
// broken server cursor cannot create unbounded work. Zero fields select the
// conservative defaults (100 pages and 10,000 items).
type PaginationLimits struct {
	MaxPages int
	MaxItems int
}

// Page is the transport-neutral result expected by Paginate. Fetchers should
// call an ergonomic SDK list method and copy its generated repeated field into
// Items; NextPageToken remains opaque and must not be normalized.
type Page[T any] struct {
	Items         []T
	NextPageToken string
}

// Paginate lazily traverses opaque-token list pages under explicit hard
// bounds. The sequence reports at most one terminal error; callers must check
// the error value yielded with each item. Stopping iteration cancels no work
// because pages are fetched only on demand.
func Paginate[T any](
	ctx context.Context,
	initialPageToken string,
	limits PaginationLimits,
	fetchPage func(context.Context, string) (Page[T], error),
) iter.Seq2[T, error] {
	return func(yield func(T, error) bool) {
		maxPages, maxItems, err := normalizedPaginationLimits(limits)
		if err != nil {
			yieldPaginationError(yield, err)
			return
		}
		if ctx == nil {
			yieldPaginationError(yield, invalidArgument("pagination context is required"))
			return
		}
		if fetchPage == nil {
			yieldPaginationError(yield, invalidArgument("pagination fetch function is required"))
			return
		}

		token := initialPageToken
		seen := make(map[string]struct{})
		if token != "" {
			seen[token] = struct{}{}
		}
		pages, items := 0, 0
		for {
			if err := ctx.Err(); err != nil {
				yieldPaginationError(yield, normalizeError(err))
				return
			}
			if pages >= maxPages {
				yieldPaginationError(yield, paginationLimit("automatic pagination exceeded its page budget"))
				return
			}
			if items >= maxItems {
				yieldPaginationError(yield, paginationLimit("automatic pagination exceeded its item budget"))
				return
			}
			page, err := fetchPage(ctx, token)
			if err != nil {
				yieldPaginationError(yield, normalizeError(err))
				return
			}
			pages++
			if page.NextPageToken != "" {
				if _, exists := seen[page.NextPageToken]; exists {
					yieldPaginationError(yield, protocolDataLoss("list response repeated an opaque page token"))
					return
				}
				seen[page.NextPageToken] = struct{}{}
			}
			for _, item := range page.Items {
				if items >= maxItems {
					yieldPaginationError(yield, paginationLimit("automatic pagination exceeded its item budget"))
					return
				}
				items++
				if !yield(item, nil) {
					return
				}
			}
			if page.NextPageToken == "" {
				return
			}
			token = page.NextPageToken
		}
	}
}

func normalizedPaginationLimits(limits PaginationLimits) (int, int, error) {
	maxPages, maxItems := limits.MaxPages, limits.MaxItems
	if maxPages == 0 {
		maxPages = defaultPaginationMaxPages
	}
	if maxItems == 0 {
		maxItems = defaultPaginationMaxItems
	}
	if maxPages < 1 || maxPages > hardPaginationMaxPages {
		return 0, 0, invalidArgument("pagination max pages must be in [1, 1000]")
	}
	if maxItems < 1 || maxItems > hardPaginationMaxItems {
		return 0, 0, invalidArgument("pagination max items must be in [1, 1000000]")
	}
	return maxPages, maxItems, nil
}

func yieldPaginationError[T any](yield func(T, error) bool, err error) {
	var zero T
	yield(zero, err)
}

func paginationLimit(message string) error {
	return &Error{Code: CodeResourceExhausted, Message: message}
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
	for _, field := range []struct {
		label string
		value string
	}{
		{label: "request ID", value: value.requestID},
		{label: "trace ID", value: value.traceID},
	} {
		if err := validateMetadataIdentifier(field.label, field.value); err != nil {
			return nil, requestMetadata{}, err
		}
	}
	if value.idempotencyKey != "" {
		if err := validateMetadataIdentifier("idempotency key", value.idempotencyKey); err != nil {
			return nil, requestMetadata{}, err
		}
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
	// Outgoing contexts are caller-controlled, including on the raw generated
	// transport escape hatch. Rebuild the metadata map without SDK-authoritative
	// identity or credential fields so a caller cannot smuggle credentials into
	// Local plaintext calls or create ambiguous duplicate scope metadata.
	existing, _ := metadata.FromOutgoingContext(ctx)
	sanitized := existing.Copy()
	for _, key := range []string{
		"authorization",
		"proxy-authorization",
		"cookie",
		"x-api-key",
		"x-goog-api-key",
		"x-mindclade-sdk",
		"x-mindclade-expected-tenant",
		"x-mindclade-expected-project",
		"x-mindclade-expected-principal",
		"x-request-id",
		"x-trace-id",
		"idempotency-key",
		"x-mindclade-lease-token",
	} {
		sanitized.Delete(key)
	}
	ctx = metadata.NewOutgoingContext(ctx, sanitized)
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
