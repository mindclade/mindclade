#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ErrorCode { InvalidArgument, NotFound, Conflict, Unauthorized, Forbidden, DeadlineExceeded, Cancelled, Unavailable, Internal }

impl ErrorCode { #[must_use] pub const fn retryable(self) -> bool { matches!(self, Self::DeadlineExceeded | Self::Unavailable) } }

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FoundationError { pub code: ErrorCode, pub message: String }
impl FoundationError { pub fn new(code: ErrorCode, message: impl Into<String>) -> Self { Self { code, message: message.into() } } }
