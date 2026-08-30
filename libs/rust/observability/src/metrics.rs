#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MetricValue(f64);
impl MetricValue { pub fn new(value: f64) -> Result<Self, &'static str> { value.is_finite().then_some(Self(value)).ok_or("metric value must be finite") } #[must_use] pub const fn get(self) -> f64 { self.0 } }
