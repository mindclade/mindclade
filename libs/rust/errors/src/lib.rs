#![forbid(unsafe_code)]
pub mod taxonomy;
pub use taxonomy::{
    ErrorCode, ErrorCodeExt, ErrorDetail, FoundationError, RetryClass, default_retry_class,
    retryable,
};
