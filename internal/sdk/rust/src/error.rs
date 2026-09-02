//! Sanitized, machine-actionable SDK failures.
//!
//! Every error leaving this SDK is sanitized: provider strings, SQL, SQLSTATE,
//! Pub/Sub internals, and stack traces never reach the caller. Structured
//! server detail arrives only through the generated
//! [`mindclade_protocols::common::v1::ErrorDetail`] message and is exposed as
//! typed fields; the detail's own text is never used as the error message.

use std::{fmt, time::Duration};

use mindclade_protocols::common::v1::{
    ErrorCode, ErrorDetail, FieldViolation, PreconditionViolation, ResourceRef, RetryClass,
};
use prost::Message as _;
use tonic::{Code, Status, metadata::MetadataMap};

/// Canonical request-correlation metadata key. The historical
/// `x-mindclade-request-id` alias is retired and is never read or emitted.
pub const REQUEST_ID_METADATA: &str = "x-request-id";
/// Canonical distributed-trace metadata key.
pub const TRACE_ID_METADATA: &str = "x-trace-id";
/// Response trailer through which a server overrides retry eligibility.
pub const SHOULD_RETRY_TRAILER: &str = "x-mindclade-should-retry";
/// Response trailer carrying a server-pinned backoff in whole milliseconds.
pub const RETRY_AFTER_TRAILER: &str = "retry-after-ms";
/// Request metadata carrying the zero-based index of the current attempt.
pub const RETRY_COUNT_METADATA: &str = "x-mindclade-retry-count";
/// Request metadata carrying the remaining total timeout budget in whole
/// milliseconds.
pub const TIMEOUT_MS_METADATA: &str = "x-mindclade-timeout-ms";

/// Precondition-violation `type` marking a durable allocation ceiling.
pub const QUOTA_PRECONDITION_TYPE: &str = "QUOTA_EXHAUSTED";
/// Precondition-violation `type` marking a rejected fenced mutation.
pub const FENCE_PRECONDITION_TYPE: &str = "LEASE_FENCE";
/// Precondition-violation `type` marking an optimistic-concurrency conflict.
pub const REVISION_PRECONDITION_TYPE: &str = "RESOURCE_VERSION";

/// Absolute ceiling applied to any server-supplied `retry-after-ms`. The retry
/// loop clamps a second time to the configured maximum backoff.
const MAX_RETRY_AFTER: Duration = Duration::from_secs(30);
const MAX_DETAIL_BYTES: usize = 64 * 1024;
const MAX_DETAIL_ITEMS: usize = 32;
const MAX_DETAIL_TEXT: usize = 512;
const ERROR_DETAIL_MESSAGE_NAME: &str = "/mindclade.common.v1.ErrorDetail";

/// Stable SDK-level failure classification.
///
/// Each documented failure class is a distinct variant so callers can branch
/// without parsing text. The enum is `#[non_exhaustive]`: a future class is an
/// additive change.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum ErrorKind {
    // Locally raised classes.
    Configuration,
    InvalidArgument,
    AlreadyExists,
    PaginationLimit,
    Protocol,
    // Remote classes.
    Authentication,
    Authorization,
    Validation,
    Conflict,
    NotFound,
    RateLimit,
    Quota,
    RetryableService,
    OperationFailed,
    Cancelled,
    DeadlineExceeded,
    Transport,
    /// Residual class for statuses with no documented mapping.
    Remote,
}

impl ErrorKind {
    /// Returns the stable, log-safe code for this class.
    ///
    /// The value is pinned to the variant and never derived from remote text,
    /// so it is safe to switch on and safe to record.
    #[must_use]
    pub fn stable_code(self) -> &'static str {
        match self {
            Self::Configuration => "mindclade.configuration_invalid",
            Self::InvalidArgument | Self::Validation => "mindclade.validation_failed",
            Self::AlreadyExists => "mindclade.already_exists",
            Self::PaginationLimit => "mindclade.pagination_limit",
            Self::Protocol => "mindclade.protocol_violation",
            Self::Authentication => "mindclade.authentication_failed",
            Self::Authorization => "mindclade.authorization_denied",
            Self::Conflict => "mindclade.conflict",
            Self::NotFound => "mindclade.not_found",
            Self::RateLimit => "mindclade.rate_limited",
            Self::Quota => "mindclade.quota_exhausted",
            Self::RetryableService => "mindclade.service_unavailable",
            Self::OperationFailed => "mindclade.operation_failed",
            Self::Cancelled => "mindclade.cancelled",
            Self::DeadlineExceeded => "mindclade.deadline_exceeded",
            Self::Transport => "mindclade.transport_failure",
            Self::Remote => "mindclade.remote_failure",
        }
    }
}

/// Why the retry loop stopped issuing attempts.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
#[non_exhaustive]
pub enum FinalCause {
    /// The call never entered a retry decision.
    #[default]
    NotRetried,
    /// The status was not retry-eligible.
    NonRetryableStatus,
    /// The attempt budget was spent.
    AttemptsExhausted,
    /// The total timeout budget was spent.
    DeadlineExceeded,
    /// The server sent `x-mindclade-should-retry: false`.
    ServerRetryOptOut,
    /// Credential acquisition failed before an attempt could be issued.
    CredentialFailure,
}

/// Observable outcome of the retry loop that produced a terminal failure.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct RetryAttemptSummary {
    attempts: u32,
    cumulative_delay: Duration,
    final_cause: FinalCause,
}

impl RetryAttemptSummary {
    pub(crate) fn new(attempts: u32, cumulative_delay: Duration, final_cause: FinalCause) -> Self {
        Self {
            attempts,
            cumulative_delay,
            final_cause,
        }
    }

    /// Attempts actually issued, including the one that failed terminally.
    #[must_use]
    pub fn attempts(self) -> u32 {
        self.attempts
    }

    /// Total backoff actually slept between those attempts.
    #[must_use]
    pub fn cumulative_delay(self) -> Duration {
        self.cumulative_delay
    }

    /// The reason the loop stopped.
    #[must_use]
    pub fn final_cause(self) -> FinalCause {
        self.final_cause
    }
}

/// Sanitized projection of a resource-exhaustion subject. Derived from
/// structured detail; never a wire type.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct QuotaState {
    subject: String,
    description: String,
}

impl QuotaState {
    /// The resource whose allocation ceiling was reached.
    #[must_use]
    pub fn subject(&self) -> &str {
        &self.subject
    }

    /// A bounded, non-secret explanation supplied by the server.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.description
    }
}

/// Sanitized projection of a lease-fencing precondition. Derived from
/// structured detail; never a wire type.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FenceState {
    subject: String,
    description: String,
}

impl FenceState {
    /// The fenced resource the rejected mutation addressed.
    #[must_use]
    pub fn subject(&self) -> &str {
        &self.subject
    }

    /// A bounded, non-secret explanation supplied by the server.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.description
    }
}

/// Structured detail a server supplied for one failure.
///
/// It is boxed and allocated only when a server actually sent detail, so the
/// common `Result<T, Error>` stays small on the success path.
#[derive(Debug, Default)]
struct ErrorDetails {
    retry_after: Option<Duration>,
    attempts: RetryAttemptSummary,
    trace_id: Option<String>,
    operation_id: Option<String>,
    field_violations: Vec<FieldViolation>,
    precondition_violations: Vec<PreconditionViolation>,
    quota: Option<QuotaState>,
    fence: Option<FenceState>,
    conflict_revision: Option<String>,
    diagnostic_reference: Option<String>,
}

impl ErrorDetails {
    fn is_empty(&self) -> bool {
        self.retry_after.is_none()
            && self.attempts == RetryAttemptSummary::default()
            && self.trace_id.is_none()
            && self.operation_id.is_none()
            && self.field_violations.is_empty()
            && self.precondition_violations.is_empty()
            && self.quota.is_none()
            && self.fence.is_none()
            && self.conflict_revision.is_none()
            && self.diagnostic_reference.is_none()
    }

    fn boxed(self) -> Option<Box<Self>> {
        (!self.is_empty()).then(|| Box::new(self))
    }
}

const EMPTY_FIELD_VIOLATIONS: &[FieldViolation] = &[];
const EMPTY_PRECONDITION_VIOLATIONS: &[PreconditionViolation] = &[];

/// A normalized failure that preserves machine-actionable gRPC state without
/// retaining credentials or serialized request/response payloads.
#[derive(Debug)]
pub struct Error {
    kind: ErrorKind,
    code: Option<Code>,
    retryable: bool,
    retry_override: Option<bool>,
    safe_message: String,
    request_id: Option<String>,
    details: Option<Box<ErrorDetails>>,
}

impl Error {
    #[must_use]
    pub fn kind(&self) -> ErrorKind {
        self.kind
    }

    #[must_use]
    pub fn code(&self) -> Option<Code> {
        self.code
    }

    /// Returns the stable, log-safe classification code.
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        self.kind.stable_code()
    }

    #[must_use]
    pub fn request_id(&self) -> Option<&str> {
        self.request_id.as_deref()
    }

    #[must_use]
    pub fn trace_id(&self) -> Option<&str> {
        self.details.as_ref()?.trace_id.as_deref()
    }

    /// Returns the durable operation this failure belongs to, when the server
    /// named one.
    #[must_use]
    pub fn operation_id(&self) -> Option<&str> {
        self.details.as_ref()?.operation_id.as_deref()
    }

    /// The single effective retry-eligibility predicate.
    ///
    /// An `x-mindclade-should-retry` trailer wins in both directions;
    /// otherwise eligibility follows [`retryable_status_code`], narrowed by a
    /// `RETRY_CLASS_NEVER` server classification.
    #[must_use]
    pub fn is_retryable(&self) -> bool {
        self.retry_override.unwrap_or(self.retryable)
    }

    /// The strict server override, when the trailer was present and valid.
    #[must_use]
    pub fn server_retry_override(&self) -> Option<bool> {
        self.retry_override
    }

    #[must_use]
    pub fn retry_after(&self) -> Option<Duration> {
        self.details.as_ref()?.retry_after
    }

    /// Request fields the server rejected, copied from structured detail.
    #[must_use]
    pub fn field_violations(&self) -> &[FieldViolation] {
        self.details
            .as_ref()
            .map_or(EMPTY_FIELD_VIOLATIONS, |details| &details.field_violations)
    }

    /// Unmet server preconditions, copied from structured detail.
    #[must_use]
    pub fn precondition_violations(&self) -> &[PreconditionViolation] {
        self.details
            .as_ref()
            .map_or(EMPTY_PRECONDITION_VIOLATIONS, |details| {
                &details.precondition_violations
            })
    }

    /// Durable quota facts attached to an exhausted-resource failure.
    #[must_use]
    pub fn quota_state(&self) -> Option<&QuotaState> {
        self.details.as_ref()?.quota.as_ref()
    }

    /// Lease-fencing facts attached to a rejected fenced mutation.
    #[must_use]
    pub fn fence_state(&self) -> Option<&FenceState> {
        self.details.as_ref()?.fence.as_ref()
    }

    /// The revision that lost an optimistic-concurrency conflict.
    #[must_use]
    pub fn conflict_revision(&self) -> Option<&str> {
        self.details.as_ref()?.conflict_revision.as_deref()
    }

    /// The server's opaque diagnostic reference (`ErrorDetail.error_id`).
    #[must_use]
    pub fn diagnostic_reference(&self) -> Option<&str> {
        self.details.as_ref()?.diagnostic_reference.as_deref()
    }

    /// Retry count, cumulative delay, and final cause for this failure.
    #[must_use]
    pub fn retry_attempts(&self) -> RetryAttemptSummary {
        self.details
            .as_ref()
            .map_or_else(RetryAttemptSummary::default, |details| details.attempts)
    }

    pub(crate) fn configuration(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::Configuration, message)
    }

    pub(crate) fn invalid_argument(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::InvalidArgument, message)
    }

    pub(crate) fn already_exists(message: impl Into<String>) -> Self {
        Self {
            code: Some(Code::AlreadyExists),
            ..Self::local(ErrorKind::AlreadyExists, message)
        }
    }

    pub(crate) fn pagination_limit(message: impl Into<String>) -> Self {
        Self {
            code: Some(Code::ResourceExhausted),
            ..Self::local(ErrorKind::PaginationLimit, message)
        }
    }

    pub(crate) fn authentication(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::Authentication, message)
    }

    pub(crate) fn protocol(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::Protocol, message)
    }

    pub(crate) fn transport() -> Self {
        Self::local(ErrorKind::Transport, "transport connection failed")
    }

    pub(crate) fn filesystem(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::Transport, message)
    }

    pub(crate) fn cancelled() -> Self {
        Self::local(ErrorKind::Cancelled, "operation wait was cancelled")
    }

    pub(crate) fn deadline_exceeded() -> Self {
        Self {
            code: Some(Code::DeadlineExceeded),
            ..Self::local(ErrorKind::DeadlineExceeded, "request deadline exceeded")
        }
    }

    /// Projects a durable terminal operation failure onto the error hierarchy.
    /// The generated resource stays authoritative; only bounded, non-secret
    /// fields are copied out of its structured detail.
    pub(crate) fn operation_failed(operation_id: &str, detail: Option<&ErrorDetail>) -> Self {
        let (field_violations, precondition_violations) = sanitize_violations(detail);
        let subject = detail.and_then(|value| value.subject.as_ref());
        let exhausted =
            detail.is_some_and(|value| value.code == ErrorCode::ResourceExhausted as i32);
        let details = ErrorDetails {
            retry_after: detail.and_then(detail_retry_after),
            attempts: RetryAttemptSummary::default(),
            trace_id: None,
            operation_id: sanitize_optional(operation_id).or_else(|| operation_subject(subject)),
            quota: quota_state(exhausted, subject, &precondition_violations),
            fence: fence_state(subject, &precondition_violations),
            conflict_revision: conflict_revision(
                subject,
                &precondition_violations,
                ErrorKind::OperationFailed,
            ),
            diagnostic_reference: detail.and_then(|value| sanitize_optional(&value.error_id)),
            field_violations,
            precondition_violations,
        };
        let mut error = Self::local(
            ErrorKind::OperationFailed,
            "operation reached a failed terminal state",
        );
        error.details = details.boxed();
        error
    }

    /// Records the observable outcome of the retry loop on a terminal failure.
    pub(crate) fn with_attempts(mut self, attempts: RetryAttemptSummary) -> Self {
        self.details
            .get_or_insert_with(Box::<ErrorDetails>::default)
            .attempts = attempts;
        self
    }

    fn local(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            code: None,
            retryable: false,
            retry_override: None,
            safe_message: message.into(),
            request_id: None,
            details: None,
        }
    }

    pub(crate) fn from_status(status: &Status) -> Self {
        let code = status.code();
        let metadata = status.metadata();
        let detail = structured_detail(status);
        let detail = detail.as_ref();
        let (field_violations, precondition_violations) = sanitize_violations(detail);
        let subject = detail.and_then(|value| value.subject.as_ref());
        let never = detail.is_some_and(|value| value.retry_class == RetryClass::Never as i32);
        let kind = classify(code, detail, &precondition_violations, never);
        let retry_after =
            retry_after_hint(metadata).or_else(|| detail.and_then(detail_retry_after));
        let details = ErrorDetails {
            retry_after,
            attempts: RetryAttemptSummary::default(),
            trace_id: first_safe_metadata(metadata, TRACE_ID_METADATA),
            operation_id: operation_subject(subject),
            quota: quota_state(
                code == Code::ResourceExhausted
                    || detail
                        .is_some_and(|value| value.code == ErrorCode::ResourceExhausted as i32),
                subject,
                &precondition_violations,
            ),
            fence: fence_state(subject, &precondition_violations),
            conflict_revision: conflict_revision(subject, &precondition_violations, kind),
            diagnostic_reference: detail.and_then(|value| sanitize_optional(&value.error_id)),
            field_violations,
            precondition_violations,
        };
        Self {
            kind,
            code: Some(code),
            retryable: !never && retryable_status_code(code),
            retry_override: should_retry_override(metadata),
            safe_message: safe_status_message(code).to_owned(),
            request_id: first_safe_metadata(metadata, REQUEST_ID_METADATA),
            details: details.boxed(),
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "mindclade: {:?}: {}",
            self.kind, self.safe_message
        )?;
        if let Some(request_id) = &self.request_id {
            write!(formatter, " (request_id={request_id})")?;
        }
        Ok(())
    }
}

impl std::error::Error for Error {}

/// The one retryable-status predicate for the whole SDK. Nothing else in this
/// crate may define a second set of retryable gRPC statuses.
#[must_use]
pub fn retryable_status_code(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable | Code::ResourceExhausted | Code::Aborted | Code::DeadlineExceeded
    )
}

/// Reads the strict `x-mindclade-should-retry` server override. Any value
/// other than `true` or `false` is ignored rather than guessed at.
pub(crate) fn should_retry_override(metadata: &MetadataMap) -> Option<bool> {
    let value = metadata.get(SHOULD_RETRY_TRAILER)?.to_str().ok()?;
    match value.trim() {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    }
}

/// Reads `retry-after-ms`, bounded by an absolute ceiling. The retry loop
/// clamps a second time to the configured maximum backoff.
pub(crate) fn retry_after_hint(metadata: &MetadataMap) -> Option<Duration> {
    let value = metadata.get(RETRY_AFTER_TRAILER)?.to_str().ok()?;
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    let milliseconds = value.parse::<u64>().ok()?;
    Some(Duration::from_millis(milliseconds).min(MAX_RETRY_AFTER))
}

fn classify(
    code: Code,
    detail: Option<&ErrorDetail>,
    preconditions: &[PreconditionViolation],
    never_retry: bool,
) -> ErrorKind {
    if let Some(detail) = detail {
        if detail.code == ErrorCode::PolicyDenied as i32 {
            return ErrorKind::Authorization;
        }
        if detail.code == ErrorCode::Conflict as i32 {
            return ErrorKind::Conflict;
        }
    }
    match code {
        Code::Unauthenticated => ErrorKind::Authentication,
        Code::PermissionDenied => ErrorKind::Authorization,
        Code::InvalidArgument | Code::OutOfRange => ErrorKind::Validation,
        Code::NotFound => ErrorKind::NotFound,
        Code::AlreadyExists => ErrorKind::AlreadyExists,
        Code::FailedPrecondition | Code::Aborted => ErrorKind::Conflict,
        Code::ResourceExhausted => {
            if never_retry || has_precondition(preconditions, QUOTA_PRECONDITION_TYPE) {
                ErrorKind::Quota
            } else {
                ErrorKind::RateLimit
            }
        }
        Code::Unavailable => ErrorKind::RetryableService,
        Code::DeadlineExceeded => ErrorKind::DeadlineExceeded,
        Code::Cancelled => ErrorKind::Cancelled,
        _ => ErrorKind::Remote,
    }
}

/// Minimal decoder for the `google.rpc.Status` envelope carried in
/// `grpc-status-details-bin`.
///
/// No generated Rust binding for `google.rpc` exists in this repository's
/// protocol set. This type is never constructed, sent, stored, or exposed: it
/// exists only to reach the generated `mindclade.common.v1.ErrorDetail` inside
/// the envelope, which remains the authoritative model.
#[derive(Clone, PartialEq, ::prost::Message)]
struct RpcStatusEnvelope {
    #[prost(int32, tag = "1")]
    code: i32,
    #[prost(string, tag = "2")]
    message: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "3")]
    details: ::prost::alloc::vec::Vec<::prost_types::Any>,
}

/// Decodes bounded structured detail from a status, preferring the standard
/// `google.rpc.Status` envelope and falling back to a bare `ErrorDetail` that
/// re-encodes byte-for-byte. Anything else is ignored rather than guessed at.
fn structured_detail(status: &Status) -> Option<ErrorDetail> {
    let bytes = status.details();
    if bytes.is_empty() || bytes.len() > MAX_DETAIL_BYTES {
        return None;
    }
    if let Ok(envelope) = RpcStatusEnvelope::decode(bytes) {
        let found = envelope.details.into_iter().find_map(|any| {
            if !any.type_url.ends_with(ERROR_DETAIL_MESSAGE_NAME) {
                return None;
            }
            recognized_detail(ErrorDetail::decode(any.value.as_slice()).ok()?)
        });
        if found.is_some() {
            return found;
        }
    }
    let detail = ErrorDetail::decode(bytes).ok()?;
    if detail.encode_to_vec() != bytes {
        return None;
    }
    recognized_detail(detail)
}

/// An unrecognized or unspecified `ErrorCode` never authorizes an action and
/// never contributes typed fields.
fn recognized_detail(detail: ErrorDetail) -> Option<ErrorDetail> {
    ErrorCode::try_from(detail.code)
        .ok()
        .filter(|code| *code != ErrorCode::Unspecified)
        .map(|_| detail)
}

fn detail_retry_after(detail: &ErrorDetail) -> Option<Duration> {
    let value = detail.retry_after.as_ref()?;
    let seconds = u64::try_from(value.seconds).ok()?;
    let nanos = u32::try_from(value.nanos).ok()?;
    if nanos >= 1_000_000_000 {
        return None;
    }
    let hint = Duration::from_secs(seconds).saturating_add(Duration::from_nanos(u64::from(nanos)));
    Some(hint.min(MAX_RETRY_AFTER))
}

fn has_precondition(preconditions: &[PreconditionViolation], kind: &str) -> bool {
    preconditions
        .iter()
        .any(|violation| violation.r#type == kind)
}

fn find_precondition<'a>(
    preconditions: &'a [PreconditionViolation],
    kind: &str,
) -> Option<&'a PreconditionViolation> {
    preconditions
        .iter()
        .find(|violation| violation.r#type == kind)
}

fn quota_state(
    exhausted: bool,
    subject: Option<&ResourceRef>,
    preconditions: &[PreconditionViolation],
) -> Option<QuotaState> {
    let violation = find_precondition(preconditions, QUOTA_PRECONDITION_TYPE);
    if !exhausted && violation.is_none() {
        return None;
    }
    let mut state = QuotaState {
        subject: subject_name(subject),
        description: String::new(),
    };
    if let Some(violation) = violation {
        if !violation.subject.is_empty() {
            state.subject.clone_from(&violation.subject);
        }
        state.description.clone_from(&violation.description);
    }
    Some(state)
}

fn fence_state(
    subject: Option<&ResourceRef>,
    preconditions: &[PreconditionViolation],
) -> Option<FenceState> {
    let violation = find_precondition(preconditions, FENCE_PRECONDITION_TYPE)?;
    let subject_value = if violation.subject.is_empty() {
        subject_name(subject)
    } else {
        violation.subject.clone()
    };
    Some(FenceState {
        subject: subject_value,
        description: violation.description.clone(),
    })
}

fn conflict_revision(
    subject: Option<&ResourceRef>,
    preconditions: &[PreconditionViolation],
    kind: ErrorKind,
) -> Option<String> {
    let relevant = matches!(kind, ErrorKind::Conflict | ErrorKind::AlreadyExists)
        || has_precondition(preconditions, REVISION_PRECONDITION_TYPE);
    if !relevant {
        return None;
    }
    let subject = subject?;
    sanitize_optional(&subject.etag)
        .or_else(|| (subject.resource_version > 0).then(|| subject.resource_version.to_string()))
}

fn subject_name(subject: Option<&ResourceRef>) -> String {
    let Some(subject) = subject else {
        return String::new();
    };
    if let Some(name) = sanitize_optional(&subject.name) {
        return name;
    }
    match (
        sanitize_optional(&subject.resource_type),
        sanitize_optional(&subject.resource_id),
    ) {
        (Some(kind), Some(id)) => format!("{kind}/{id}"),
        _ => String::new(),
    }
}

fn operation_subject(subject: Option<&ResourceRef>) -> Option<String> {
    let subject = subject?;
    if subject.resource_type != "operation" {
        return None;
    }
    sanitize_optional(&subject_name(Some(subject)))
}

fn sanitize_violations(
    detail: Option<&ErrorDetail>,
) -> (Vec<FieldViolation>, Vec<PreconditionViolation>) {
    let Some(detail) = detail else {
        return (Vec::new(), Vec::new());
    };
    let fields = detail
        .field_violations
        .iter()
        .take(MAX_DETAIL_ITEMS)
        .map(|violation| FieldViolation {
            field: sanitize_text(&violation.field),
            description: sanitize_text(&violation.description),
        })
        .collect();
    let preconditions = detail
        .precondition_violations
        .iter()
        .take(MAX_DETAIL_ITEMS)
        .map(|violation| PreconditionViolation {
            r#type: sanitize_text(&violation.r#type),
            subject: sanitize_text(&violation.subject),
            description: sanitize_text(&violation.description),
        })
        .collect();
    (fields, preconditions)
}

/// Accepts bounded single-line printable ASCII only. Multi-line text, control
/// characters, and oversized blobs are dropped rather than truncated, so a
/// stack trace, SQL fragment, or provider dump can never reach a typed field.
fn sanitize_text(value: &str) -> String {
    if value.is_empty()
        || value.len() > MAX_DETAIL_TEXT
        || !value.bytes().all(|byte| (0x20..=0x7e).contains(&byte))
    {
        return String::new();
    }
    value.to_owned()
}

fn sanitize_optional(value: &str) -> Option<String> {
    let sanitized = sanitize_text(value);
    (!sanitized.is_empty()).then_some(sanitized)
}

fn first_safe_metadata(metadata: &MetadataMap, key: &str) -> Option<String> {
    let value = metadata.get(key)?.to_str().ok()?;
    if value.is_empty()
        || value.len() > 512
        || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
    {
        None
    } else {
        Some(value.to_owned())
    }
}

fn safe_status_message(code: Code) -> &'static str {
    match code {
        Code::Cancelled => "remote request was cancelled",
        Code::InvalidArgument => "remote request was invalid",
        Code::DeadlineExceeded => "remote request deadline exceeded",
        Code::NotFound => "requested resource was not found",
        Code::AlreadyExists => "resource already exists",
        Code::PermissionDenied => "permission was denied",
        Code::ResourceExhausted => "remote service is resource constrained",
        Code::FailedPrecondition => "remote precondition failed",
        Code::Aborted => "remote transaction was aborted",
        Code::OutOfRange => "request was outside the supported range",
        Code::Unimplemented => "remote method is not implemented",
        Code::Internal => "remote service failed internally",
        Code::Unavailable => "remote service is unavailable",
        Code::DataLoss => "remote service reported data loss",
        Code::Unauthenticated => "authentication failed",
        Code::Unknown | Code::Ok => "remote request failed",
    }
}
