use crate::Chunk;
use sha2::{Digest as _, Sha256};

/// Reassembles contiguous chunks and verifies their SHA-256 digest.
///
/// # Errors
///
/// Returns an error when chunk indices are not contiguous or when the
/// reconstructed bytes do not match `expected`.
pub fn verify_chunks(chunks: &[Chunk], expected: &str) -> Result<Vec<u8>, &'static str> {
    if chunks
        .windows(2)
        .any(|pair| pair[0].index.checked_add(1) != Some(pair[1].index))
    {
        return Err("chunk sequence is not contiguous");
    }
    let bytes: Vec<u8> = chunks
        .iter()
        .flat_map(|chunk| chunk.bytes.iter().copied())
        .collect();
    let actual = format!("sha256:{:x}", Sha256::digest(&bytes));
    (actual == expected)
        .then_some(bytes)
        .ok_or("chunk integrity digest mismatch")
}
