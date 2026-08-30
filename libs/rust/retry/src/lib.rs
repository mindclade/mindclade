#![forbid(unsafe_code)]
pub mod backoff;
pub mod policy;
pub use backoff::{Clock, ManualClock};
pub use policy::RetryPolicy;
