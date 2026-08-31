#![forbid(unsafe_code)]

pub mod digest;
pub mod reference;

pub use digest::ArtifactDigest;
pub use reference::{ArtifactRef, ArtifactReference, make_artifact_ref, validate_artifact_ref};
