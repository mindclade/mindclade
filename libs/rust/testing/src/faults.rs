use std::collections::BTreeSet;
#[derive(Default)] pub struct FaultInjector { failures: BTreeSet<u32> }
impl FaultInjector { #[must_use] pub fn with_failures(failures: impl IntoIterator<Item = u32>) -> Self { Self { failures: failures.into_iter().collect() } } #[must_use] pub fn should_fail(&self, attempt: u32) -> bool { self.failures.contains(&attempt) } }
