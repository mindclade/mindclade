#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct OpaqueId { kind: String, value: String }
impl OpaqueId {
    pub fn parse(kind: &str, value: &str) -> Result<Self, &'static str> {
        let suffix = value.strip_prefix(&format!("{kind}_")).ok_or("identifier kind prefix mismatch")?;
        if !(8..=128).contains(&suffix.len()) || !suffix.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')) { return Err("identifier must be bounded lowercase opaque text"); }
        Ok(Self { kind: kind.into(), value: value.into() })
    }
    #[must_use] pub fn kind(&self) -> &str { &self.kind }
    #[must_use] pub fn value(&self) -> &str { &self.value }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)] pub struct ResourceVersion(u64);
impl ResourceVersion { pub fn new(value: u64) -> Result<Self, &'static str> { (value > 0).then_some(Self(value)).ok_or("resource version must be positive") } #[must_use] pub const fn get(self) -> u64 { self.0 } }
