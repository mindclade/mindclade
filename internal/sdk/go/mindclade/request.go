package mindclade

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"iter"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"

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
	timeout        time.Duration
	maxAttempts    int
	unsafeRetry    bool
	pagination     PaginationLimits
	responseTarget *ResponseMetadata
	responseSink   *responseSink
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

// WithPaginationLimits bounds automatic traversal for one list call. Zero
// fields select the SDK defaults of 100 pages and 10,000 items; the hard caps
// of 1,000 pages and 1,000,000 items are enforced by Paginate itself. The
// budget governs All, which walks the collection; NextPage fetches exactly one
// explicitly requested page and is bounded by the caller instead.
func WithPaginationLimits(limits PaginationLimits) RequestOption {
	return func(value *requestMetadata) { value.pagination = limits }
}

// paginationLimitsFrom resolves the traversal budget a caller asked for. It
// applies the options to a throwaway record so reading the budget never
// generates or disturbs the per-call transport identity.
func paginationLimitsFrom(options []RequestOption) PaginationLimits {
	value := requestMetadata{}
	for _, option := range options {
		if option != nil {
			option(&value)
		}
	}
	return value.pagination
}

// pageReader is the minimal page-level contract the shared traversal needs.
// Every SDK list page satisfies it. It is unexported, and one of its methods
// is unexported, so it constrains the SDK's own page types without becoming
// public surface a caller could implement.
type pageReader[Item any] interface {
	Items() []Item
	nextPageToken() string
}

// pageBase supplies the uniform page-level surface every SDK list page
// exposes. Self is the concrete page type, so NextPage stays typed and no
// caller has to assert a domain type back out of a generic container.
type pageBase[Item any, Self pageReader[Item]] struct {
	metadata *commonv1.PageResponse
	self     Self
	limits   PaginationLimits
	// fetch re-invokes the owning list method with the caller's original
	// request and options and a replaced page token. Every traversed page
	// therefore re-runs the same scope, page-size, and cross-project
	// validation the first page did; retraversal is never a validation bypass.
	fetch func(ctx context.Context, pageToken string) (Self, error)
}

// pageRequestWithToken returns a detached page request whose opaque cursor is
// replaced, allocating one when the caller supplied none. The token is copied
// byte-for-byte: an opaque server cursor is never trimmed or normalized.
func pageRequestWithToken(page *commonv1.PageRequest, token string) *commonv1.PageRequest {
	successor := cloneGenerated(page)
	if successor == nil {
		successor = &commonv1.PageRequest{}
	}
	successor.PageToken = token
	return successor
}

// newPage binds one fetched list response to the shared cursor mechanics.
func newPage[Item any, Self pageReader[Item]](
	self Self,
	metadata *commonv1.PageResponse,
	limits PaginationLimits,
	fetch func(ctx context.Context, pageToken string) (Self, error),
) pageBase[Item, Self] {
	return pageBase[Item, Self]{metadata: metadata, self: self, limits: limits, fetch: fetch}
}

func (page pageBase[Item, Self]) nextPageToken() string { return page.metadata.GetNextPageToken() }

// HasNextPage reports whether the server issued another opaque cursor.
func (page pageBase[Item, Self]) HasNextPage() bool { return page.nextPageToken() != "" }

// PageMetadata returns the generated page-level response backing this page.
// The generated list response itself stays embedded and authoritative.
func (page pageBase[Item, Self]) PageMetadata() *commonv1.PageResponse { return page.metadata }

// NextPage fetches the page following this one, re-running the owning list
// method's validation. It returns a nil page and a nil error at the end of the
// collection, so a page-at-a-time loop terminates on the zero page.
func (page pageBase[Item, Self]) NextPage(ctx context.Context) (Self, error) {
	var zero Self
	if page.fetch == nil {
		return zero, invalidArgument("page was not produced by an SDK list method")
	}
	if ctx == nil {
		return zero, invalidArgument("pagination context is required")
	}
	token := page.nextPageToken()
	if token == "" {
		return zero, nil
	}
	return page.fetch(ctx, token)
}

// All iterates every item across every page transparently under the traversal
// budget. It reports at most one terminal error, which callers must check with
// each yielded item, and it never refetches the page it was called on.
func (page pageBase[Item, Self]) All(ctx context.Context) iter.Seq2[Item, error] {
	if page.fetch == nil {
		return func(yield func(Item, error) bool) {
			yieldPaginationError(yield, invalidArgument("page was not produced by an SDK list method"))
		}
	}
	// Traversal state is established per iteration, not per call, so ranging
	// the same sequence twice restarts from this page instead of resuming
	// wherever the previous walk stopped.
	return func(yield func(Item, error) bool) {
		current, first := page.self, true
		Paginate(ctx, "", page.limits, func(ctx context.Context, token string) (Page[Item], error) {
			if !first {
				fetched, err := page.fetch(ctx, token)
				if err != nil {
					return Page[Item]{}, err
				}
				current = fetched
			}
			first = false
			return Page[Item]{Items: current.Items(), NextPageToken: current.nextPageToken()}, nil
		})(yield)
	}
}

// ResponseMetadata is the safe, allowlisted view of one call's transport
// response. Values outside the allowlist — and every credential-bearing key,
// whatever the allowlist says — are dropped before a caller can observe them,
// and the status message is the SDK's sanitized text rather than the server's.
type ResponseMetadata struct {
	Status    Code
	RequestID string
	TraceID   string
	Metadata  map[string][]string
}

// responseSink holds metadata captured for a context-scoped capture. It is
// guarded because one capture context may be reused across calls; concurrent
// calls sharing a capture overwrite one another and only the last is readable.
type responseSink struct {
	mutex    sync.Mutex
	present  bool
	metadata ResponseMetadata
}

type responseCaptureKey struct{}

// WithResponseMetadata captures the transport response of one call into the
// supplied record. It is written exactly once, after the terminal attempt, for
// a success and for a failure alike, and is left untouched when the call fails
// before it reaches the transport.
func WithResponseMetadata(into *ResponseMetadata) RequestOption {
	return func(value *requestMetadata) {
		if into != nil {
			value.responseTarget = into
		}
	}
}

// CaptureResponseMetadata derives a context whose calls record their transport
// response for ResponseMetadataFromContext to read back. It is the typed
// accessor companion to WithResponseMetadata, for callers that would otherwise
// have to thread a record through an intermediate layer.
func CaptureResponseMetadata(ctx context.Context) context.Context {
	return context.WithValue(ctx, responseCaptureKey{}, &responseSink{})
}

// ResponseMetadataFromContext returns the metadata captured for the most
// recent call made with a context derived from CaptureResponseMetadata. The
// second result is false when no call has completed on that context.
func ResponseMetadataFromContext(ctx context.Context) (ResponseMetadata, bool) {
	sink, ok := ctx.Value(responseCaptureKey{}).(*responseSink)
	if !ok || sink == nil {
		return ResponseMetadata{}, false
	}
	sink.mutex.Lock()
	defer sink.mutex.Unlock()
	if !sink.present {
		return ResponseMetadata{}, false
	}
	return sink.metadata, true
}

// safeResponseMetadataKeys is the cross-language allowlist of response
// metadata the SDK will surface. It is a strict allowlist, not a denylist: a
// key that does not appear here is never exposed, however innocuous it looks.
var safeResponseMetadataKeys = map[string]bool{
	"x-request-id":             true,
	"x-trace-id":               true,
	"x-mindclade-should-retry": true,
	"retry-after-ms":           true,
	"x-mindclade-retry-count":  true,
	"content-type":             true,
	"grpc-status":              true,
	"grpc-message":             true,
	"date":                     true,
	"server":                   true,
}

// credentialDenylistKeys are the exact metadata keys that carry a credential.
var credentialDenylistKeys = map[string]bool{
	"authorization":           true,
	"proxy-authorization":     true,
	"cookie":                  true,
	"set-cookie":              true,
	"x-api-key":               true,
	"x-goog-api-key":          true,
	"x-mindclade-lease-token": true,
}

// credentialDenylistPatterns are the substrings that mark a key as
// credential-bearing whatever its exact spelling.
var credentialDenylistPatterns = []string{"token", "secret", "key", "credential", "password", "auth"}

// credentialBearingKey is the shared denylist for response metadata exposure
// and for caller-supplied metadata pass-through. It is applied on top of the
// allowlist so that a future allowlist mistake still cannot leak a credential.
func credentialBearingKey(key string) bool {
	normalized := strings.ToLower(strings.TrimSpace(key))
	if credentialDenylistKeys[normalized] {
		return true
	}
	for _, pattern := range credentialDenylistPatterns {
		if strings.Contains(normalized, pattern) {
			return true
		}
	}
	return false
}

// maxResponseMetadataValues bounds how many values one surfaced key may carry
// so a hostile server cannot make one captured response unbounded.
const maxResponseMetadataValues = 8

// safeMetadataValue bounds one surfaced metadata value at 256 bytes of
// printable ASCII, space included. A value that fails the bound is dropped
// rather than truncated, so a caller never reads a half-decoded value.
func safeMetadataValue(value string) bool {
	if len(value) > 256 {
		return false
	}
	for index := 0; index < len(value); index++ {
		if value[index] < 0x20 || value[index] > 0x7e {
			return false
		}
	}
	return true
}

// safeResponseMetadata projects transport headers and trailers onto the
// allowlisted subset. grpc-message is allowlisted as a key but its value is
// replaced with the SDK's sanitized status text, so raw server prose — which
// may quote SQL, provider errors, or internal state — is never surfaced.
func safeResponseMetadata(headers, trailers metadata.MD, statusMessage string) map[string][]string {
	safe := map[string][]string{}
	for _, source := range []metadata.MD{headers, trailers} {
		for key, values := range source {
			normalized := strings.ToLower(strings.TrimSpace(key))
			if !safeResponseMetadataKeys[normalized] || credentialBearingKey(normalized) {
				continue
			}
			for _, value := range values {
				if normalized == "grpc-message" {
					value = statusMessage
				}
				if !safeMetadataValue(value) {
					continue
				}
				if len(safe[normalized]) >= maxResponseMetadataValues {
					break
				}
				safe[normalized] = append(safe[normalized], value)
			}
		}
	}
	return safe
}

// captureResponseMetadata records the terminal transport response of one
// logical call. Request and trace identity fall back to the identity the SDK
// itself sent, so a server that does not echo them still gives the caller a
// correlatable id on success.
func captureResponseMetadata(request requestMetadata, headers, trailers metadata.MD, code Code, statusMessage string) {
	if request.responseTarget == nil && request.responseSink == nil {
		return
	}
	captured := ResponseMetadata{
		Status:    code,
		RequestID: firstMetadata(headers, "x-request-id"),
		TraceID:   firstMetadata(headers, "x-trace-id"),
		Metadata:  safeResponseMetadata(headers, trailers, statusMessage),
	}
	if captured.RequestID == "" {
		captured.RequestID = firstMetadata(trailers, "x-request-id")
	}
	if captured.TraceID == "" {
		captured.TraceID = firstMetadata(trailers, "x-trace-id")
	}
	if captured.RequestID == "" {
		captured.RequestID = request.requestID
	}
	if captured.TraceID == "" {
		captured.TraceID = request.traceID
	}
	if request.responseTarget != nil {
		*request.responseTarget = captured
	}
	if request.responseSink != nil {
		request.responseSink.mutex.Lock()
		request.responseSink.present = true
		request.responseSink.metadata = captured
		request.responseSink.mutex.Unlock()
	}
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

// WithTimeout sets the TOTAL budget for one logical call. Every retry attempt,
// every backoff wait, and the credential acquisition performed for each attempt
// share it. It replaces the configured per-RPC default, but it never extends a
// deadline the caller's own context already imposes.
func WithTimeout(timeout time.Duration) RequestOption {
	return func(value *requestMetadata) { value.timeout = timeout }
}

// WithMaxAttempts bounds the transport attempts for one call. It can only
// narrow the configured retry policy: a method the policy does not classify as
// safe or idempotent still gets exactly one attempt, however large the value.
func WithMaxAttempts(attempts int) RequestOption {
	return func(value *requestMetadata) { value.maxAttempts = attempts }
}

// WithUnsafeRetryOfNonIdempotentRPC permits implicit retry of a mutation that
// does not embed a validated CommandContext. The caller asserts that
// duplicating the server-side effect is safe; the SDK cannot verify that, which
// is why the option is named rather than expressed as a bare boolean. It has no
// effect on RunService.ExpireAttemptLeases, which is never retried.
func WithUnsafeRetryOfNonIdempotentRPC() RequestOption {
	return func(value *requestMetadata) { value.unsafeRetry = true }
}

func withRequestOptions(ctx context.Context, options ...RequestOption) (context.Context, requestMetadata, error) {
	value := requestMetadata{}
	if existing, ok := ctx.Value(requestContextKey{}).(requestMetadata); ok {
		value = existing
	}
	if sink, ok := ctx.Value(responseCaptureKey{}).(*responseSink); ok {
		value.responseSink = sink
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
	// Per-request policy is bounded by the same limits config.finalize enforces
	// for the client-wide policy, so one call can never widen transport policy
	// past what the configuration itself is allowed to express.
	if value.timeout < 0 || value.timeout > 5*time.Minute {
		return nil, requestMetadata{}, invalidArgument("request timeout must be positive and at most five minutes")
	}
	if value.maxAttempts < 0 || value.maxAttempts > 8 {
		return nil, requestMetadata{}, invalidArgument("request max attempts must be between 1 and 8")
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
		// The x-mindclade-request-id alias is retired. Deleting it makes the
		// retirement enforceable: a caller that still emits it cannot have it
		// reach the server alongside the authoritative x-request-id.
		"x-mindclade-request-id",
		"x-trace-id",
		"idempotency-key",
		"x-mindclade-lease-token",
		"x-mindclade-retry-count",
		"x-mindclade-timeout-ms",
		"x-mindclade-should-retry",
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

// attachAttemptMetadata stamps the per-attempt retry counter and the remaining
// total budget. These are the only metadata values that differ between the
// attempts of one logical call, so they are appended to the shared identity
// context rather than rebuilt with it — each attempt therefore carries exactly
// one value for each key. The counter is 0-based: the first attempt sends "0".
func attachAttemptMetadata(ctx context.Context, attempt int) context.Context {
	if attempt < 0 {
		attempt = 0
	}
	pairs := []string{"x-mindclade-retry-count", strconv.Itoa(attempt)}
	if deadline, ok := ctx.Deadline(); ok {
		remaining := time.Until(deadline).Milliseconds()
		if remaining < 0 {
			remaining = 0
		}
		pairs = append(pairs, "x-mindclade-timeout-ms", strconv.FormatInt(remaining, 10))
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
