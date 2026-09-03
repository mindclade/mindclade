use std::{fmt, time::Duration};

use tonic::{Code, Status, metadata::MetadataMap};

/// Stable SDK-level failure classification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ErrorKind {
    Configuration,
    InvalidArgument,
    AlreadyExists,
    PaginationLimit,
    Authentication,
    Cancelled,
    DeadlineExceeded,
    Transport,
    Remote,
    Protocol,
}

/// A normalized failure that preserves machine-actionable gRPC state without
/// retaining credentials or serialized request/response payloads.
#[derive(Debug)]
pub struct Error {
    kind: ErrorKind,
    code: Option<Code>,
    request_id: Option<String>,
    retryable: bool,
    retry_after: Option<Duration>,
    safe_message: String,
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

    #[must_use]
    pub fn request_id(&self) -> Option<&str> {
        self.request_id.as_deref()
    }

    #[must_use]
    pub fn is_retryable(&self) -> bool {
        self.retryable
    }

    #[must_use]
    pub fn retry_after(&self) -> Option<Duration> {
        self.retry_after
    }

    pub(crate) fn configuration(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::Configuration, message)
    }

    pub(crate) fn invalid_argument(message: impl Into<String>) -> Self {
        Self::local(ErrorKind::InvalidArgument, message)
    }

    pub(crate) fn already_exists(message: impl Into<String>) -> Self {
        Self {
            kind: ErrorKind::AlreadyExists,
            code: Some(Code::AlreadyExists),
            request_id: None,
            retryable: false,
            retry_after: None,
            safe_message: message.into(),
        }
    }

    pub(crate) fn pagination_limit(message: impl Into<String>) -> Self {
        Self {
            kind: ErrorKind::PaginationLimit,
            code: Some(Code::ResourceExhausted),
            request_id: None,
            retryable: false,
            retry_after: None,
            safe_message: message.into(),
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
            kind: ErrorKind::DeadlineExceeded,
            code: Some(Code::DeadlineExceeded),
            request_id: None,
            retryable: false,
            retry_after: None,
            safe_message: "request deadline exceeded".to_owned(),
        }
    }

    fn local(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            code: None,
            request_id: None,
            retryable: false,
            retry_after: None,
            safe_message: message.into(),
        }
    }

    pub(crate) fn from_status(status: &Status) -> Self {
        let code = status.code();
        let kind = match code {
            Code::Cancelled => ErrorKind::Cancelled,
            Code::DeadlineExceeded => ErrorKind::DeadlineExceeded,
            Code::AlreadyExists => ErrorKind::AlreadyExists,
            Code::Unauthenticated => ErrorKind::Authentication,
            _ => ErrorKind::Remote,
        };
        Self {
            kind,
            code: Some(code),
            request_id: first_safe_metadata(status.metadata(), &["x-request-id", "request-id"]),
            retryable: is_retryable_code(code),
            retry_after: retry_after(status.metadata()),
            safe_message: safe_status_message(code).to_owned(),
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

pub(crate) fn is_retryable_code(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable | Code::ResourceExhausted | Code::Aborted | Code::DeadlineExceeded
    )
}

fn first_safe_metadata(metadata: &MetadataMap, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        let value = metadata.get(*key)?.to_str().ok()?;
        if value.is_empty()
            || value.len() > 512
            || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
        {
            None
        } else {
            Some(value.to_owned())
        }
    })
}

fn retry_after(metadata: &MetadataMap) -> Option<Duration> {
    let value = metadata.get("retry-after-ms")?.to_str().ok()?;
    let milliseconds = value.parse::<u64>().ok()?;
    Some(Duration::from_millis(milliseconds.min(30_000)))
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
