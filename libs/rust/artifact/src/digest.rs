use sha2::{Digest as _, Sha256};

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ArtifactDigest(String);

impl ArtifactDigest {
    /// Parses the canonical `sha256:<64 lowercase hex>` artifact identity.
    ///
    /// # Errors
    ///
    /// Returns an error when `value` is not a canonical SHA-256 digest.
    pub fn parse(value: &str) -> Result<Self, &'static str> {
        let hex = value
            .strip_prefix("sha256:")
            .ok_or("digest must use sha256")?;
        if hex.len() != 64
            || !hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err("digest must be sha256:<64 lowercase hex>");
        }
        Ok(Self(value.into()))
    }

    #[must_use]
    pub fn from_bytes(bytes: &[u8]) -> Self {
        Self(format!("sha256:{:x}", Sha256::digest(bytes)))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}
