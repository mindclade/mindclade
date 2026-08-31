#![forbid(unsafe_code)]

pub mod redaction;
pub mod resolution;

pub use resolution::{ConfigLayer, Resolution, resolve};
