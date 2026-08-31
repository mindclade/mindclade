#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UploadSession {
    pub id: String,
    pub next_offset: u64,
    pub total_bytes: u64,
}
impl UploadSession {
    /// Creates a bounded resumable upload session.
    ///
    /// # Errors
    ///
    /// Returns an error when `id` is empty or `total_bytes` is zero.
    pub fn new(id: &str, total_bytes: u64) -> Result<Self, &'static str> {
        if id.is_empty() || total_bytes == 0 {
            return Err("upload identity or length is invalid");
        }
        Ok(Self {
            id: id.into(),
            next_offset: 0,
            total_bytes,
        })
    }
    /// Accepts the next contiguous upload range.
    ///
    /// # Errors
    ///
    /// Returns an error when the offset is not the next expected offset, the
    /// range is empty or overflows, or its end exceeds the declared total.
    pub fn accept(&mut self, offset: u64, length: u64) -> Result<(), &'static str> {
        if offset != self.next_offset
            || length == 0
            || offset
                .checked_add(length)
                .is_none_or(|end| end > self.total_bytes)
        {
            return Err("resumable upload offset is invalid");
        }
        self.next_offset += length;
        Ok(())
    }
    #[must_use]
    pub const fn complete(&self) -> bool {
        self.next_offset == self.total_bytes
    }
}
