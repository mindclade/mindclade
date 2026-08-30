use std::sync::atomic::{AtomicI64, Ordering};
use std::time::Duration;
pub trait Clock: Send + Sync { fn now_millis(&self) -> i64; fn sleep(&self, duration: Duration); }
pub struct ManualClock(AtomicI64);
impl ManualClock { #[must_use] pub const fn new(now_millis: i64) -> Self { Self(AtomicI64::new(now_millis)) } }
impl Clock for ManualClock { fn now_millis(&self) -> i64 { self.0.load(Ordering::SeqCst) } fn sleep(&self, duration: Duration) { self.0.fetch_add(i64::try_from(duration.as_millis()).unwrap_or(i64::MAX), Ordering::SeqCst); } }
