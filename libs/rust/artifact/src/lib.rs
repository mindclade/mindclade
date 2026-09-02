#![forbid(unsafe_code)]

pub mod digest;
pub mod reference;

pub use digest::ArtifactDigest;
pub use reference::{
    ArtifactManifest, ArtifactRef, ArtifactReference, SchemaError, decode_artifact_manifest,
    make_artifact_ref, validate_artifact_ref,
};
