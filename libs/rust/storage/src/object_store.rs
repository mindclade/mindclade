use mindclade_artifact::ArtifactDigest;
use std::collections::BTreeMap;
pub struct MemoryObjectStore {
    max_bytes: usize,
    values: BTreeMap<ArtifactDigest, Vec<u8>>,
}
impl MemoryObjectStore {
    /// Creates an in-memory object store with a per-object byte bound.
    ///
    /// # Errors
    ///
    /// Returns an error when `max_bytes` is zero.
    pub fn new(max_bytes: usize) -> Result<Self, &'static str> {
        (max_bytes > 0)
            .then_some(Self {
                max_bytes,
                values: BTreeMap::new(),
            })
            .ok_or("object bound must be positive")
    }
    /// Stores bytes under their content digest.
    ///
    /// # Errors
    ///
    /// Returns an error when the object exceeds the configured bound or its
    /// computed digest does not match `expected`.
    pub fn put(
        &mut self,
        bytes: &[u8],
        expected: Option<&ArtifactDigest>,
    ) -> Result<ArtifactDigest, &'static str> {
        if bytes.len() > self.max_bytes {
            return Err("object exceeds bound");
        }
        let digest = ArtifactDigest::from_bytes(bytes);
        if expected.is_some_and(|value| value != &digest) {
            return Err("object digest mismatch");
        }
        self.values.insert(digest.clone(), bytes.into());
        Ok(digest)
    }
    pub fn get(&self, digest: &ArtifactDigest) -> Option<&[u8]> {
        self.values.get(digest).map(Vec::as_slice)
    }
}
