package mindclade

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

// Code is a transport-neutral failure classification.
type Code string

const (
	CodeUnknown            Code = "unknown"
	CodeCanceled           Code = "canceled"
	CodeInvalidArgument    Code = "invalid_argument"
	CodeDeadlineExceeded   Code = "deadline_exceeded"
	CodeNotFound           Code = "not_found"
	CodeAlreadyExists      Code = "already_exists"
	CodePermissionDenied   Code = "permission_denied"
	CodeResourceExhausted  Code = "resource_exhausted"
	CodeFailedPrecondition Code = "failed_precondition"
	CodeAborted            Code = "aborted"
	CodeOutOfRange         Code = "out_of_range"
	CodeUnimplemented      Code = "unimplemented"
	CodeInternal           Code = "internal"
	CodeUnavailable        Code = "unavailable"
	CodeDataLoss           Code = "data_loss"
	CodeUnauthenticated    Code = "unauthenticated"
)

// Retryability is the tri-state retry classification that mirrors
// mindclade.common.v1.RetryClass. It is deliberately fail-closed: a server
// value outside the three recognised classes — including a future value this
// build does not know and the generated UNRECOGNIZED sentinel — is reported as
// RetryNever and can never authorize an implicit retry.
type Retryability string

const (
	RetryNever               Retryability = "never"
	RetrySafe                Retryability = "safe"
	RetryAfterReconciliation Retryability = "after_reconciliation"
)

// QuotaState is bounded quota telemetry derived from structured server detail.
// It never carries account identifiers, billing data, or provider payloads.
// Limit and Remaining stay zero unless the server named those dimensions.
type QuotaState struct {
	Subject   string
	Limit     int64
	Remaining int64
	ResetAt   time.Time
}

const (
	// maxErrorDetailViolations mirrors the control plane's own violation bound
	// so a hostile or broken server cannot make one error unbounded.
	maxErrorDetailViolations = 32
	// maxErrorDetailTextBytes bounds every server-authored string surfaced
	// through a typed field.
	maxErrorDetailTextBytes = 512
)

// Error preserves machine-actionable status and safe request metadata without
// exposing serialized request/response payloads. It remains the base carrier
// for every typed SDK failure; the typed hierarchy wraps it rather than
// replacing it, so errors.As reaches either form.
type Error struct {
	Code       Code
	Message    string
	RequestID  string
	Retryable  bool
	RetryAfter time.Duration
	Cause      error

	// Structured, safe, server-derived identity and classification.
	TraceID     string
	OperationID string
	Retry       Retryability

	// Observable retry outcome. Attempts counts transport attempts actually
	// issued for the logical call; CumulativeDelay is the total backoff slept
	// between them.
	Attempts        int
	CumulativeDelay time.Duration

	// Generated protobuf types are the models. These are the server's own
	// messages, never a hand-written parallel wire model.
	FieldViolations        []*commonv1.FieldViolation
	PreconditionViolations []*commonv1.PreconditionViolation
	Quota                  *QuotaState
	Fence                  *jobv1.LeaseFence
	ConflictRevision       string
	DiagnosticReference    string

	retryAfterSet       bool
	serverRetryOverride *bool
}

// MindcladeError is the base contract implemented by *Error and by every typed
// SDK error. errors.As with this interface target matches all of them, so a
// caller can read the safe structured detail without switching on a concrete
// type first.
type MindcladeError interface {
	error
	ErrorCode() Code
	Retryability() Retryability
	RetryAfterHint() (time.Duration, bool)
	RequestIdentity() (requestID, traceID string)
	OperationIdentity() string
	Violations() ([]*commonv1.FieldViolation, []*commonv1.PreconditionViolation)
	QuotaTelemetry() *QuotaState
	FenceTelemetry() *jobv1.LeaseFence
	Revision() string
	Diagnostic() string
	RetryOutcome() (attempts int, cumulativeDelay time.Duration)
}

func (err *Error) Error() string {
	if err == nil {
		return "<nil>"
	}
	if err.RequestID != "" {
		return fmt.Sprintf("mindclade: %s: %s (request_id=%s)", err.Code, err.Message, err.RequestID)
	}
	return fmt.Sprintf("mindclade: %s: %s", err.Code, err.Message)
}

func (err *Error) Unwrap() error { return err.Cause }

func (err *Error) ErrorCode() Code { return err.Code }

func (err *Error) Retryability() Retryability {
	if err.Retry == "" {
		if err.Retryable {
			return RetrySafe
		}
		return RetryNever
	}
	return err.Retry
}

func (err *Error) RetryAfterHint() (time.Duration, bool) {
	return err.RetryAfter, err.retryAfterSet || err.RetryAfter > 0
}

func (err *Error) RequestIdentity() (string, string) { return err.RequestID, err.TraceID }

func (err *Error) OperationIdentity() string { return err.OperationID }

func (err *Error) Violations() ([]*commonv1.FieldViolation, []*commonv1.PreconditionViolation) {
	return err.FieldViolations, err.PreconditionViolations
}

func (err *Error) QuotaTelemetry() *QuotaState { return err.Quota }

func (err *Error) FenceTelemetry() *jobv1.LeaseFence { return err.Fence }

func (err *Error) Revision() string { return err.ConflictRevision }

func (err *Error) Diagnostic() string { return err.DiagnosticReference }

func (err *Error) RetryOutcome() (int, time.Duration) { return err.Attempts, err.CumulativeDelay }

// As lets errors.As reach the typed hierarchy from the base carrier. Errors the
// SDK raises locally — a validation refusal, a credential acquisition failure,
// a protocol violation detected client side — are constructed as *Error rather
// than through a gRPC status, and without this a caller matching
// *ValidationError or *AuthenticationError would silently miss them even though
// the documented mapping says otherwise. classify stays the single source of
// that mapping, so the base and typed forms of one failure can never disagree.
func (err *Error) As(target any) bool {
	if err == nil {
		return false
	}
	typed := classify(err)
	switch pointer := target.(type) {
	case **AuthenticationError:
		return assignClassified(typed, pointer)
	case **AuthorizationError:
		return assignClassified(typed, pointer)
	case **ValidationError:
		return assignClassified(typed, pointer)
	case **ConflictError:
		return assignClassified(typed, pointer)
	case **NotFoundError:
		return assignClassified(typed, pointer)
	case **RateLimitError:
		return assignClassified(typed, pointer)
	case **QuotaError:
		return assignClassified(typed, pointer)
	case **RetryableServiceError:
		return assignClassified(typed, pointer)
	case **OperationFailedError:
		return assignClassified(typed, pointer)
	case **CancelledError:
		return assignClassified(typed, pointer)
	case **TransportError:
		return assignClassified(typed, pointer)
	default:
		return false
	}
}

// assignClassified writes the classified error into a caller target when the
// classification produced exactly that concrete type.
func assignClassified[Typed error](classified error, pointer *Typed) bool {
	// errors.As would unwrap and could match a wrapped cause; this asks only
	// whether the classification produced exactly this concrete type.
	concrete, ok := classified.(Typed) //nolint:errorlint // Exact-type check by contract, not chain traversal.
	if ok {
		*pointer = concrete
	}
	return ok
}

// fault is the shared implementation embedded by every typed SDK error. It
// keeps the base *Error private so the carrier can only be reached through
// errors.As, never mutated through a promoted field.
type fault struct{ base *Error }

func (value fault) Error() string { return value.base.Error() }

// Unwrap deliberately returns the original cause rather than the inner *Error.
// A sanitized gRPC status has no cause, so errors.Unwrap on it stays nil and no
// server-authored chain is ever exposed; a context failure keeps errors.Is
// against context.Canceled and context.DeadlineExceeded working.
func (value fault) Unwrap() error { return value.base.Cause }

// As lets errors.As(err, &sdkError) reach the inner *Error without an Unwrap
// edge that would leak a non-nil chain to callers.
func (value fault) As(target any) bool {
	pointer, ok := target.(**Error)
	if !ok {
		return false
	}
	*pointer = value.base
	return true
}

func (value fault) ErrorCode() Code            { return value.base.ErrorCode() }
func (value fault) Retryability() Retryability { return value.base.Retryability() }
func (value fault) RetryAfterHint() (time.Duration, bool) {
	return value.base.RetryAfterHint()
}
func (value fault) RequestIdentity() (string, string) { return value.base.RequestIdentity() }
func (value fault) OperationIdentity() string         { return value.base.OperationIdentity() }
func (value fault) Violations() ([]*commonv1.FieldViolation, []*commonv1.PreconditionViolation) {
	return value.base.Violations()
}
func (value fault) QuotaTelemetry() *QuotaState        { return value.base.QuotaTelemetry() }
func (value fault) FenceTelemetry() *jobv1.LeaseFence  { return value.base.FenceTelemetry() }
func (value fault) Revision() string                   { return value.base.Revision() }
func (value fault) Diagnostic() string                 { return value.base.Diagnostic() }
func (value fault) RetryOutcome() (int, time.Duration) { return value.base.RetryOutcome() }

// AuthenticationError reports a missing, expired, or unverifiable caller
// credential. It is produced from UNAUTHENTICATED and from local credential
// acquisition failures, and is never retried implicitly.
type AuthenticationError struct{ fault }

// AuthorizationError reports an authenticated caller whose request was denied
// by policy. It is produced from PERMISSION_DENIED and from structured detail
// classified ERROR_CODE_POLICY_DENIED.
type AuthorizationError struct{ fault }

// ValidationError reports a request the server rejected as malformed or out of
// range. Field violations name the offending generated fields.
type ValidationError struct{ fault }

// ConflictError reports a concurrent-state conflict: an aborted transaction, an
// already-existing resource, a failed precondition, or structured detail
// classified ERROR_CODE_CONFLICT. Revision carries the server's expected
// resource revision or ETag when it supplied one.
type ConflictError struct{ fault }

// NotFoundError reports an absent or invisible resource. It never distinguishes
// absence from invisibility, so it cannot be used to probe another tenant.
type NotFoundError struct{ fault }

// RateLimitError reports admission throttling that names when to come back. It
// is produced from RESOURCE_EXHAUSTED carrying a retry-after hint.
type RateLimitError struct{ fault }

// QuotaError reports an exhausted budget with no retry hint: the caller must
// change the request or wait for the quota window rather than retry blindly.
type QuotaError struct{ fault }

// RetryableServiceError reports a transient remote fault the server classified
// as safe to repeat: UNAVAILABLE, or INTERNAL carrying RETRY_CLASS_SAFE.
type RetryableServiceError struct{ fault }

// OperationFailedError reports a durable long-running operation or run that
// reached a terminal failure state. The generated message remains available
// through OperationError and WorkflowRunError for authoritative state.
type OperationFailedError struct{ fault }

// CancelledError reports a call the caller or the server cancelled. It is never
// retried implicitly, because cancellation is an instruction, not a fault.
type CancelledError struct{ fault }

// TransportError reports a failure that never reached, or never returned from,
// application logic: a dial or stream failure, an unknown or unimplemented
// method, reported data loss, an unclassified internal fault, or a locally
// observed deadline.
type TransportError struct{ fault }

// classify wraps the base carrier in the typed error the contract requires.
// It is total: every Code produces exactly one concrete type, so callers can
// switch on the hierarchy without a default case that silently swallows a
// failure class.
func classify(base *Error) error {
	if base == nil {
		return nil
	}
	value := fault{base: base}
	switch base.Code {
	case CodeUnauthenticated:
		return &AuthenticationError{fault: value}
	case CodePermissionDenied:
		return &AuthorizationError{fault: value}
	case CodeInvalidArgument, CodeOutOfRange:
		return &ValidationError{fault: value}
	case CodeAborted, CodeAlreadyExists, CodeFailedPrecondition:
		return &ConflictError{fault: value}
	case CodeNotFound:
		return &NotFoundError{fault: value}
	case CodeResourceExhausted:
		if _, hinted := base.RetryAfterHint(); hinted {
			return &RateLimitError{fault: value}
		}
		return &QuotaError{fault: value}
	case CodeUnavailable:
		return &RetryableServiceError{fault: value}
	case CodeInternal:
		if base.Retryability() == RetrySafe {
			return &RetryableServiceError{fault: value}
		}
		return &TransportError{fault: value}
	case CodeCanceled:
		return &CancelledError{fault: value}
	default:
		return &TransportError{fault: value}
	}
}

// OperationError represents a durable terminal failure. The generated
// operation remains available for its authoritative state, result, and error.
type OperationError struct {
	Operation *operationv1.Operation
}

func (err *OperationError) Error() string {
	if err == nil || err.Operation == nil {
		return "mindclade: operation failed"
	}
	return fmt.Sprintf("mindclade: operation %s reached terminal state %s", err.Operation.GetOperationId(), err.Operation.GetState())
}

// Unwrap projects the generated terminal operation onto the typed hierarchy so
// errors.As reaches OperationFailedError and the base *Error. The generated
// operation itself is untouched and stays the authoritative state.
func (err *OperationError) Unwrap() error {
	if err == nil {
		return nil
	}
	base := &Error{
		Code:        CodeInternal,
		Message:     "operation reached a terminal failure state",
		OperationID: safeDetailText(err.Operation.GetOperationId()),
	}
	if err.Operation.GetState() == operationv1.OperationState_OPERATION_STATE_CANCELLED {
		base.Code = CodeCanceled
		base.Message = "operation was cancelled"
	}
	base.ConflictRevision = strconv.FormatInt(err.Operation.GetResourceVersion(), 10)
	if etag := safeDetailText(err.Operation.GetEtag()); etag != "" {
		base.ConflictRevision = etag
	}
	applyErrorDetail(base, err.Operation.GetError())
	return &OperationFailedError{fault: fault{base: base}}
}

// Unwrap projects the generated terminal workflow run onto the typed hierarchy
// so errors.As reaches OperationFailedError and the base *Error. WorkflowRun
// remains the authoritative generated state.
func (err *WorkflowRunError) Unwrap() error {
	if err == nil {
		return nil
	}
	return terminalWorkflowFailure(err.Run)
}

// terminalWorkflowFailure projects a generated terminal workflow run onto the
// typed hierarchy. It lives beside the operation projection so both durable
// terminal failures reach OperationFailedError identically.
func terminalWorkflowFailure(run *workflowv1.WorkflowRun) error {
	base := &Error{
		Code:             CodeInternal,
		Message:          "workflow run reached a terminal failure state",
		OperationID:      safeDetailText(run.GetName()),
		ConflictRevision: strconv.FormatInt(run.GetRevision(), 10),
	}
	if etag := safeDetailText(run.GetEtag()); etag != "" {
		base.ConflictRevision = etag
	}
	applyErrorDetail(base, run.GetFailure())
	return &OperationFailedError{fault: fault{base: base}}
}

func normalizeError(err error) error {
	if err == nil {
		return nil
	}
	var existing MindcladeError
	if errors.As(err, &existing) {
		return existing
	}
	if errors.Is(err, context.Canceled) {
		return classify(&Error{Code: CodeCanceled, Message: "request canceled", Retry: RetryNever, Cause: err})
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return classify(&Error{Code: CodeDeadlineExceeded, Message: "request deadline exceeded", Retryable: true, Retry: RetrySafe, Cause: err})
	}
	grpcStatus, ok := status.FromError(err)
	if !ok {
		return classify(&Error{Code: CodeUnknown, Message: "request failed", Retry: RetryNever})
	}
	base := &Error{
		Code:      codeFromGRPC(grpcStatus.Code()),
		Message:   safeStatusMessage(grpcStatus.Code()),
		Retryable: retryableCode(grpcStatus.Code()),
	}
	applyErrorDetail(base, decodeErrorDetail(grpcStatus))
	base.Fence = decodeLeaseFence(grpcStatus)
	return classify(base)
}

func safeStatusMessage(code codes.Code) string {
	switch code {
	case codes.Canceled:
		return "request canceled"
	case codes.InvalidArgument:
		return "request is invalid"
	case codes.DeadlineExceeded:
		return "request deadline exceeded"
	case codes.NotFound:
		return "resource was not found"
	case codes.AlreadyExists:
		return "resource already exists"
	case codes.PermissionDenied:
		return "permission denied"
	case codes.ResourceExhausted:
		return "remote service is resource constrained"
	case codes.FailedPrecondition:
		return "request precondition failed"
	case codes.Aborted:
		return "request conflicted with concurrent state"
	case codes.OutOfRange:
		return "request is outside the retained range"
	case codes.Unimplemented:
		return "operation is not implemented"
	case codes.Internal:
		return "remote service failed internally"
	case codes.Unavailable:
		return "remote service is unavailable"
	case codes.DataLoss:
		return "remote service reported data loss"
	case codes.Unauthenticated:
		return "authentication is required"
	default:
		return "request failed"
	}
}

// decodeErrorDetail extracts the single authoritative mindclade.common.v1
// ErrorDetail carried by a gRPC status. Absent, duplicated, or undecodable
// detail yields nil and never fails the call. Only the structured fields are
// read; the detail's free-text message is discarded so safeStatusMessage stays
// the sole message source and no server text can reach Error().
func decodeErrorDetail(grpcStatus *status.Status) *commonv1.ErrorDetail {
	if grpcStatus == nil {
		return nil
	}
	for _, any := range grpcStatus.Proto().GetDetails() {
		detail := &commonv1.ErrorDetail{}
		if any == nil || !any.MessageIs(detail) {
			continue
		}
		if err := any.UnmarshalTo(detail); err != nil {
			return nil
		}
		return detail
	}
	return nil
}

// decodeLeaseFence extracts generated fencing state when the server attached
// it. Fence state is diagnostic only: it never carries a lease token, only the
// digest the generated contract already treats as safe to publish.
func decodeLeaseFence(grpcStatus *status.Status) *jobv1.LeaseFence {
	if grpcStatus == nil {
		return nil
	}
	for _, any := range grpcStatus.Proto().GetDetails() {
		fence := &jobv1.LeaseFence{}
		if any == nil || !any.MessageIs(fence) {
			continue
		}
		if err := any.UnmarshalTo(fence); err != nil {
			return nil
		}
		return fence
	}
	return nil
}

// applyErrorDetail copies bounded structured detail onto the base carrier. It
// never copies the detail's message, and it fails closed on an unrecognised
// retry class so an unknown enum value cannot authorize a retry.
func applyErrorDetail(base *Error, detail *commonv1.ErrorDetail) {
	if base == nil {
		return
	}
	base.Retry = retryabilityFromClass(detail.GetRetryClass())
	if base.Retry == "" {
		if base.Retryable {
			base.Retry = RetrySafe
		} else {
			base.Retry = RetryNever
		}
	}
	if detail == nil {
		return
	}
	if code, ok := codeFromDetail(detail.GetCode()); ok {
		base.Code = code
		base.Message = safeStatusMessage(grpcCodeFromDetail(detail.GetCode()))
	}
	base.FieldViolations = boundedFieldViolations(detail.GetFieldViolations())
	base.PreconditionViolations = boundedPreconditionViolations(detail.GetPreconditionViolations())
	base.DiagnosticReference = safeDetailText(detail.GetErrorId())
	if subject := detail.GetSubject(); subject != nil {
		if etag := safeDetailText(subject.GetEtag()); etag != "" {
			base.ConflictRevision = etag
		} else if version := subject.GetResourceVersion(); version != 0 {
			base.ConflictRevision = strconv.FormatInt(version, 10)
		}
		if subject.GetResourceType() == "operation" {
			if name := safeDetailText(subject.GetName()); name != "" {
				base.OperationID = name
			} else if id := safeDetailText(subject.GetResourceId()); id != "" {
				base.OperationID = id
			}
		}
	}
	if hint := detail.GetRetryAfter().AsDuration(); detail.GetRetryAfter() != nil && hint >= 0 && hint <= time.Hour && !base.retryAfterSet {
		base.RetryAfter = hint
		base.retryAfterSet = true
	}
	if base.Code == CodeResourceExhausted {
		base.Quota = quotaState(base, detail)
	}
}

// retryabilityFromClass maps the generated retry class fail-closed. An
// unspecified class reports the empty string so the caller can fall back to the
// status-derived default; every other unrecognised value reports RetryNever.
func retryabilityFromClass(class commonv1.RetryClass) Retryability {
	switch class {
	case commonv1.RetryClass_RETRY_CLASS_SAFE:
		return RetrySafe
	case commonv1.RetryClass_RETRY_CLASS_AFTER_RECONCILIATION:
		return RetryAfterReconciliation
	case commonv1.RetryClass_RETRY_CLASS_NEVER:
		return RetryNever
	case commonv1.RetryClass_RETRY_CLASS_UNSPECIFIED:
		return ""
	default:
		return RetryNever
	}
}

// codeFromDetail refines the transport code with the server's own
// classification. Only codes that add information the transport status cannot
// express are honoured; an unrecognised detail code leaves the status code
// authoritative.
func codeFromDetail(code commonv1.ErrorCode) (Code, bool) {
	switch code {
	case commonv1.ErrorCode_ERROR_CODE_CONFLICT:
		return CodeAborted, true
	case commonv1.ErrorCode_ERROR_CODE_POLICY_DENIED:
		return CodePermissionDenied, true
	default:
		return "", false
	}
}

func grpcCodeFromDetail(code commonv1.ErrorCode) codes.Code {
	switch code {
	case commonv1.ErrorCode_ERROR_CODE_CONFLICT:
		return codes.Aborted
	case commonv1.ErrorCode_ERROR_CODE_POLICY_DENIED:
		return codes.PermissionDenied
	default:
		return codes.Unknown
	}
}

func boundedFieldViolations(values []*commonv1.FieldViolation) []*commonv1.FieldViolation {
	if len(values) == 0 {
		return nil
	}
	bounded := make([]*commonv1.FieldViolation, 0, min(len(values), maxErrorDetailViolations))
	for _, value := range values {
		if len(bounded) >= maxErrorDetailViolations {
			break
		}
		if value == nil {
			continue
		}
		bounded = append(bounded, &commonv1.FieldViolation{
			Field:       safeDetailText(value.GetField()),
			Description: safeDetailText(value.GetDescription()),
		})
	}
	if len(bounded) == 0 {
		return nil
	}
	return bounded
}

func boundedPreconditionViolations(values []*commonv1.PreconditionViolation) []*commonv1.PreconditionViolation {
	if len(values) == 0 {
		return nil
	}
	bounded := make([]*commonv1.PreconditionViolation, 0, min(len(values), maxErrorDetailViolations))
	for _, value := range values {
		if len(bounded) >= maxErrorDetailViolations {
			break
		}
		if value == nil {
			continue
		}
		bounded = append(bounded, &commonv1.PreconditionViolation{
			Type:        safeDetailText(value.GetType()),
			Subject:     safeDetailText(value.GetSubject()),
			Description: safeDetailText(value.GetDescription()),
		})
	}
	if len(bounded) == 0 {
		return nil
	}
	return bounded
}

// quotaState derives bounded quota telemetry. The generated contract carries
// quota numbers only as precondition violations, so a violation typed QUOTA
// contributes one dimension: its subject names the dimension ("limit" or
// "remaining") and its description must be a bounded non-negative decimal
// integer. Anything else is ignored, and an exhausted budget that names no
// dimension still reports its subject and its reset hint.
func quotaState(base *Error, detail *commonv1.ErrorDetail) *QuotaState {
	state := &QuotaState{}
	if subject := detail.GetSubject(); subject != nil {
		state.Subject = safeDetailText(subject.GetName())
		if state.Subject == "" {
			state.Subject = safeDetailText(subject.GetResourceId())
		}
	}
	if base.retryAfterSet && base.RetryAfter > 0 {
		state.ResetAt = time.Now().Add(base.RetryAfter)
	}
	for _, violation := range base.PreconditionViolations {
		if !strings.EqualFold(violation.GetType(), "QUOTA") {
			continue
		}
		amount, err := strconv.ParseInt(violation.GetDescription(), 10, 64)
		if err != nil || amount < 0 {
			continue
		}
		switch strings.ToLower(violation.GetSubject()) {
		case "limit":
			state.Limit = amount
		case "remaining":
			state.Remaining = amount
		}
	}
	if state.Subject == "" && state.Limit == 0 && state.Remaining == 0 && state.ResetAt.IsZero() {
		return nil
	}
	return state
}

// safeDetailText bounds one server-authored string before it can reach a typed
// field. Anything outside printable ASCII is dropped whole rather than
// partially surfaced, so control characters, embedded newlines, and binary
// provider payloads never escape into logs or terminal output.
func safeDetailText(value string) string {
	if value == "" {
		return ""
	}
	if len(value) > maxErrorDetailTextBytes {
		value = value[:maxErrorDetailTextBytes]
	}
	for index := 0; index < len(value); index++ {
		if value[index] < 0x20 || value[index] > 0x7e {
			return ""
		}
	}
	return value
}

func enrichError(err error, trailers metadata.MD) error {
	normalized := normalizeError(err)
	var sdkError *Error
	if !errors.As(normalized, &sdkError) {
		return normalized
	}
	clone := *sdkError
	clone.RequestID = firstMetadata(trailers, "x-request-id")
	clone.TraceID = firstMetadata(trailers, "x-trace-id")
	if value := firstMetadata(trailers, "retry-after-ms"); value != "" {
		if milliseconds, parseErr := strconv.ParseInt(value, 10, 64); parseErr == nil && milliseconds >= 0 && milliseconds <= int64(time.Hour/time.Millisecond) {
			clone.RetryAfter = time.Duration(milliseconds) * time.Millisecond
			clone.retryAfterSet = true
		}
	}
	clone.serverRetryOverride = serverRetryOverrideFromTrailers(trailers)
	// The transport trailer is the authority on when to come back, so a quota
	// reset instant derived from structured detail is recomputed once the
	// trailer has been read rather than left reporting the weaker hint.
	if clone.Quota != nil && clone.retryAfterSet && clone.RetryAfter > 0 {
		quota := *clone.Quota
		quota.ResetAt = time.Now().Add(clone.RetryAfter)
		clone.Quota = &quota
	}
	return classify(&clone)
}

// serverRetryOverrideFromTrailers reads the x-mindclade-should-retry override.
// Only the exact values "true" and "false" are honoured, in both directions;
// any other value is ignored so a malformed trailer cannot change policy.
func serverRetryOverrideFromTrailers(trailers metadata.MD) *bool {
	switch firstMetadata(trailers, "x-mindclade-should-retry") {
	case "true":
		allowed := true
		return &allowed
	case "false":
		denied := false
		return &denied
	default:
		return nil
	}
}

// withRetryOutcome stamps the observable retry outcome onto a terminal error:
// how many transport attempts were issued, how much backoff was slept in
// total, and — through the preserved Code and Cause — the final cause.
func withRetryOutcome(err error, attempts int, cumulativeDelay time.Duration) error {
	var sdkError *Error
	if !errors.As(err, &sdkError) {
		return err
	}
	clone := *sdkError
	clone.Attempts = attempts
	clone.CumulativeDelay = cumulativeDelay
	return classify(&clone)
}

func firstMetadata(values metadata.MD, keys ...string) string {
	for _, key := range keys {
		items := values.Get(key)
		if len(items) > 0 {
			value := items[0]
			if len(value) <= 256 && isGraphicASCII(value) {
				return value
			}
		}
	}
	return ""
}

func codeFromGRPC(code codes.Code) Code {
	switch code {
	case codes.Canceled:
		return CodeCanceled
	case codes.InvalidArgument:
		return CodeInvalidArgument
	case codes.DeadlineExceeded:
		return CodeDeadlineExceeded
	case codes.NotFound:
		return CodeNotFound
	case codes.AlreadyExists:
		return CodeAlreadyExists
	case codes.PermissionDenied:
		return CodePermissionDenied
	case codes.ResourceExhausted:
		return CodeResourceExhausted
	case codes.FailedPrecondition:
		return CodeFailedPrecondition
	case codes.Aborted:
		return CodeAborted
	case codes.OutOfRange:
		return CodeOutOfRange
	case codes.Unimplemented:
		return CodeUnimplemented
	case codes.Internal:
		return CodeInternal
	case codes.Unavailable:
		return CodeUnavailable
	case codes.DataLoss:
		return CodeDataLoss
	case codes.Unauthenticated:
		return CodeUnauthenticated
	default:
		return CodeUnknown
	}
}

// retryableStatus is the single retry-eligibility predicate for the whole SDK.
// Every implicit retry decision — the unary interceptor, watcher reconnects,
// and long-running resume paths — resolves through this function and nothing
// else, so no call site can diverge on which statuses are transient.
func retryableStatus(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, context.Canceled) {
		return false
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}
	var sdkError *Error
	if errors.As(err, &sdkError) {
		switch sdkError.Retryability() {
		case RetryNever:
			// Fail closed: an explicit never, an unrecognised class, and the
			// generated UNRECOGNIZED sentinel all land here.
			return false
		case RetrySafe:
			// The server's own classification is authoritative when it names a
			// class the transport status cannot express — an INTERNAL the
			// control plane knows is safe to repeat, for one. Without this the
			// SDK would type such a failure *RetryableServiceError and then
			// refuse to retry it.
			return true
		}
		return sdkError.Retryable || retryableCode(grpcCodeFromCode(sdkError.Code))
	}
	return retryableCode(status.Code(err))
}

// retryableCode is the code-level form of retryableStatus used while a failure
// is still being normalized.
func retryableCode(code codes.Code) bool {
	return code == codes.Unavailable || code == codes.ResourceExhausted || code == codes.Aborted || code == codes.DeadlineExceeded
}

func grpcCodeFromCode(code Code) codes.Code {
	switch code {
	case CodeCanceled:
		return codes.Canceled
	case CodeInvalidArgument:
		return codes.InvalidArgument
	case CodeDeadlineExceeded:
		return codes.DeadlineExceeded
	case CodeNotFound:
		return codes.NotFound
	case CodeAlreadyExists:
		return codes.AlreadyExists
	case CodePermissionDenied:
		return codes.PermissionDenied
	case CodeResourceExhausted:
		return codes.ResourceExhausted
	case CodeFailedPrecondition:
		return codes.FailedPrecondition
	case CodeAborted:
		return codes.Aborted
	case CodeOutOfRange:
		return codes.OutOfRange
	case CodeUnimplemented:
		return codes.Unimplemented
	case CodeInternal:
		return codes.Internal
	case CodeUnavailable:
		return codes.Unavailable
	case CodeDataLoss:
		return codes.DataLoss
	case CodeUnauthenticated:
		return codes.Unauthenticated
	default:
		return codes.Unknown
	}
}
