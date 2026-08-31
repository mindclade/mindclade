#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Chunk {
    pub index: u32,
    pub bytes: Vec<u8>,
}

impl Chunk {
    /// Creates a chunk within the configured byte bound.
    ///
    /// # Errors
    ///
    /// Returns an error when `bytes` is empty or exceeds `max_bytes`.
    pub fn new(index: u32, bytes: Vec<u8>, max_bytes: usize) -> Result<Self, &'static str> {
        if bytes.is_empty() || bytes.len() > max_bytes {
            return Err("chunk exceeds configured bounds");
        }
        Ok(Self { index, bytes })
    }
}
