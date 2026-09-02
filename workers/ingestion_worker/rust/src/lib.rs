//! Bounded ingestion-worker intake through the private SDK.

#![forbid(unsafe_code)]

mod source_fetch;

pub use source_fetch::{
    AssignmentError, MaterializedAssignment, SourceFetcher, decode_job_requested,
};
