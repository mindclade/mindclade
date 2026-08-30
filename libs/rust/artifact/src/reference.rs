use crate::ArtifactDigest;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactReference {
    pub digest: ArtifactDigest,
    pub media_type: String,
    pub size_bytes: u64,
}

impl ArtifactReference {
    pub fn new(digest: ArtifactDigest, media_type: &str, size_bytes: u64) -> Result<Self, &'static str> {
        if media_type.is_empty() || media_type.len() > 255 || !media_type.is_ascii() { return Err("media type is invalid"); }
        Ok(Self { digest, media_type: media_type.into(), size_bytes })
    }
}
