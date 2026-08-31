use std::time::Duration;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RetryPolicy {
    pub max_attempts: u8,
    pub initial_delay: Duration,
    pub max_delay: Duration,
}
impl RetryPolicy {
    /// Validates that the retry policy is bounded and internally consistent.
    ///
    /// # Errors
    ///
    /// Returns an error when the attempt count is zero or greater than 16, the
    /// initial delay is zero, or the maximum delay is less than the initial delay.
    pub fn validate(self) -> Result<Self, &'static str> {
        if self.max_attempts == 0
            || self.max_attempts > 16
            || self.initial_delay.is_zero()
            || self.max_delay < self.initial_delay
        {
            return Err("retry policy is unbounded or invalid");
        }
        Ok(self)
    }
}
