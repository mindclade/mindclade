#![forbid(unsafe_code)]

pub mod redaction;
pub mod resolution;

pub use resolution::{resolve, ConfigLayer, Resolution};
