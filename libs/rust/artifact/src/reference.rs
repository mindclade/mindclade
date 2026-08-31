use crate::ArtifactDigest;

pub use mindclade_protocols::artifact::v1::ArtifactRef;

/// Compatibility name for the authoritative generated artifact contract.
pub type ArtifactReference = ArtifactRef;

/// Builds and validates an authoritative generated artifact reference.
///
/// # Errors
///
/// Returns an error when `size_bytes` exceeds the protobuf `int64` range or
/// any populated contract field fails [`validate_artifact_ref`].
pub fn make_artifact_ref(
    digest: &ArtifactDigest,
    media_type: &str,
    size_bytes: u64,
    artifact_kind: &str,
) -> Result<ArtifactRef, &'static str> {
    let size_bytes = i64::try_from(size_bytes).map_err(|_| "size_bytes exceeds int64")?;
    let reference = ArtifactRef {
        digest: digest.as_str().to_owned(),
        media_type: media_type.to_owned(),
        size_bytes,
        artifact_kind: artifact_kind.to_owned(),
        ..ArtifactRef::default()
    };
    validate_artifact_ref(&reference)?;
    Ok(reference)
}

/// Validates the semantic constraints carried by a generated artifact reference.
///
/// # Errors
///
/// Returns an error for a non-canonical digest, invalid media type, negative
/// size, missing artifact kind, or non-canonical integrity digest.
pub fn validate_artifact_ref(reference: &ArtifactRef) -> Result<(), &'static str> {
    ArtifactDigest::parse(&reference.digest)?;
    if reference.media_type.is_empty()
        || reference.media_type.len() > 255
        || !reference.media_type.is_ascii()
    {
        return Err("media type is invalid");
    }
    if reference.size_bytes < 0 {
        return Err("size_bytes must be non-negative");
    }
    if reference.artifact_kind.is_empty() {
        return Err("artifact_kind is required");
    }
    if !reference.integrity_digest.is_empty() {
        ArtifactDigest::parse(&reference.integrity_digest)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn factory_returns_the_authoritative_generated_type() {
        let digest = ArtifactDigest::from_bytes(b"artifact");
        let reference: mindclade_protocols::artifact::v1::ArtifactRef =
            make_artifact_ref(&digest, "application/octet-stream", 8, "test-output")
                .expect("valid reference");

        assert_eq!(reference.digest, digest.as_str());
        assert_eq!(reference.size_bytes, 8);
        assert_eq!(reference.artifact_kind, "test-output");
    }

    #[test]
    fn validator_rejects_invalid_generated_values() {
        let digest = ArtifactDigest::from_bytes(b"artifact");
        let mut reference =
            make_artifact_ref(&digest, "application/octet-stream", 8, "test-output")
                .expect("valid reference");
        reference.size_bytes = -1;

        assert_eq!(
            validate_artifact_ref(&reference),
            Err("size_bytes must be non-negative")
        );
    }

    #[test]
    fn factory_rejects_values_outside_the_wire_range() {
        let digest = ArtifactDigest::from_bytes(b"artifact");

        assert_eq!(
            make_artifact_ref(&digest, "application/octet-stream", u64::MAX, "test-output"),
            Err("size_bytes exceeds int64")
        );
    }
}
