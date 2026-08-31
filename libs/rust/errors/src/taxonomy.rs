pub use mindclade_protocols::common::v1::{ErrorCode, ErrorDetail, RetryClass};

#[must_use]
pub const fn default_retry_class(code: ErrorCode) -> RetryClass {
    match code {
        ErrorCode::Unspecified => RetryClass::Unspecified,
        ErrorCode::DeadlineExceeded | ErrorCode::Unavailable => RetryClass::Safe,
        _ => RetryClass::Never,
    }
}

#[must_use]
pub const fn retryable(code: ErrorCode) -> bool {
    matches!(default_retry_class(code), RetryClass::Safe)
}

pub trait ErrorCodeExt {
    #[must_use]
    fn retry_class(self) -> RetryClass;

    #[must_use]
    fn retryable(self) -> bool;
}

impl ErrorCodeExt for ErrorCode {
    fn retry_class(self) -> RetryClass {
        default_retry_class(self)
    }

    fn retryable(self) -> bool {
        retryable(self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FoundationError {
    pub code: ErrorCode,
    pub message: String,
}
impl FoundationError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl From<FoundationError> for ErrorDetail {
    fn from(value: FoundationError) -> Self {
        let retry_class = value.code.retry_class();
        Self {
            code: value.code as i32,
            message: value.message,
            retry_class: retry_class as i32,
            ..Self::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_code_is_the_authoritative_generated_enum() {
        let code: mindclade_protocols::common::v1::ErrorCode = ErrorCode::InvalidArgument;

        assert_eq!(code.as_str_name(), "ERROR_CODE_INVALID_ARGUMENT");
    }

    #[test]
    fn retry_classification_preserves_the_existing_policy() {
        assert!(ErrorCode::Unavailable.retryable());
        assert!(ErrorCode::DeadlineExceeded.retryable());
        assert!(!ErrorCode::Internal.retryable());
        assert_eq!(
            ErrorCode::Unspecified.retry_class(),
            RetryClass::Unspecified
        );
    }

    #[test]
    fn foundation_error_projects_to_generated_error_detail() {
        let detail: ErrorDetail = FoundationError::new(ErrorCode::Unavailable, "try again").into();

        assert_eq!(detail.code, ErrorCode::Unavailable as i32);
        assert_eq!(detail.retry_class, RetryClass::Safe as i32);
        assert_eq!(detail.message, "try again");
    }
}
