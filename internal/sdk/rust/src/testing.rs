//! Hermetic SDK-owned fakes for application-consumer tests.

use std::{
    collections::{HashMap, VecDeque},
    future::pending,
    sync::Mutex,
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{EventEnvelope, ResourceRef},
    internal::{
        artifact::v1::{DownloadArtifactRequest, DownloadArtifactResponse},
        job::v1::{GetJobRequest, GetJobResponse},
    },
    job::v1::{Job, JobRequested, JobState},
};
use prost::Message;
use prost_types::Timestamp;
use sha2::{Digest, Sha256};
use tonic::{Code, Request, Response, Status, codegen::async_trait, codegen::tokio_stream};

use crate::{ArtifactStream, JitterSource, RpcTransport};

#[must_use]
/// Builds a digest-consistent artifact reference for hermetic SDK consumer tests.
///
/// # Panics
///
/// Panics only when the fixture is larger than the protocol's signed 64-bit
/// size field, which cannot occur in a practical in-memory test fixture.
pub fn artifact_fixture(content: &[u8], media_type: &str) -> ArtifactRef {
    ArtifactRef {
        digest: sha256(content),
        media_type: media_type.to_owned(),
        size_bytes: i64::try_from(content.len()).expect("test artifact fits i64"),
        ..ArtifactRef::default()
    }
}

#[must_use]
pub fn job_fixture(
    tenant_id: &str,
    project_id: &str,
    configuration: ArtifactRef,
    input: Option<ArtifactRef>,
) -> Job {
    Job {
        job_id: "jobs/job-1".to_owned(),
        operation_id: "operations/operation-1".to_owned(),
        tenant_id: tenant_id.to_owned(),
        project_id: project_id.to_owned(),
        state: JobState::Running as i32,
        resource_version: 1,
        configuration: Some(configuration),
        input,
        etag: "job-etag-1".to_owned(),
        ..Job::default()
    }
}

#[must_use]
pub fn job_requested_delivery_fixture(
    configuration_digest: &str,
    tenant_id: &str,
    project_id: &str,
    event_version: u32,
    payload_digest_override: Option<&str>,
) -> Vec<u8> {
    let event = JobRequested {
        job_id: "jobs/job-1".to_owned(),
        configuration_digest: configuration_digest.to_owned(),
    };
    let payload = event.encode_to_vec();
    EventEnvelope {
        event_id: "events/event-1".to_owned(),
        event_type: "mindclade.events.job.v1.JobRequested".to_owned(),
        event_version,
        occurred_at: Some(Timestamp {
            seconds: 1,
            nanos: 0,
        }),
        tenant_id: tenant_id.to_owned(),
        trace_id: "trace-1".to_owned(),
        subject: Some(ResourceRef {
            resource_type: "job".to_owned(),
            resource_id: "job-1".to_owned(),
            ..ResourceRef::default()
        }),
        payload_digest: payload_digest_override.map_or_else(|| sha256(&payload), str::to_owned),
        payload,
        recorded_at: Some(Timestamp {
            seconds: 1,
            nanos: 0,
        }),
        project_id: project_id.to_owned(),
        aggregate_sequence: 1,
        request_id: "request-1".to_owned(),
        job_id: "jobs/job-1".to_owned(),
        payload_content_type: "application/x-protobuf; deterministic=true".to_owned(),
        ..EventEnvelope::default()
    }
    .encode_to_vec()
}

/// A content-addressed fake for `Jobs.Get` and `Artifacts.Download`.
pub struct ScriptedJobArtifactTransport {
    job: Job,
    artifacts: HashMap<String, Vec<u8>>,
    get_job_failure: Option<Code>,
    block_get_job: bool,
    requested_digests: Mutex<Vec<String>>,
}

impl ScriptedJobArtifactTransport {
    #[must_use]
    pub fn new(job: Job, artifacts: impl IntoIterator<Item = (ArtifactRef, Vec<u8>)>) -> Self {
        Self {
            job,
            artifacts: artifacts
                .into_iter()
                .map(|(artifact, content)| (artifact.digest, content))
                .collect(),
            get_job_failure: None,
            block_get_job: false,
            requested_digests: Mutex::new(Vec::new()),
        }
    }

    #[must_use]
    pub fn failing_get_job(mut self, code: Code) -> Self {
        self.get_job_failure = Some(code);
        self
    }

    #[must_use]
    pub fn blocking_get_job(mut self) -> Self {
        self.block_get_job = true;
        self
    }

    #[must_use]
    pub fn requested_digests(&self) -> Vec<String> {
        self.requested_digests
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }
}

#[async_trait]
impl RpcTransport for ScriptedJobArtifactTransport {
    async fn get_job(
        &self,
        request: Request<GetJobRequest>,
    ) -> Result<Response<GetJobResponse>, Status> {
        if self.block_get_job {
            pending::<()>().await;
        }
        if let Some(code) = self.get_job_failure {
            return Err(Status::new(code, "redacted fake failure"));
        }
        if request.get_ref().name != self.job.job_id {
            return Err(Status::not_found("unknown fake job"));
        }
        Ok(Response::new(GetJobResponse {
            job: Some(self.job.clone()),
        }))
    }

    async fn download_artifact(
        &self,
        request: Request<DownloadArtifactRequest>,
    ) -> Result<Response<ArtifactStream>, Status> {
        let digest = request.get_ref().digest.clone();
        self.requested_digests
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(digest.clone());
        let artifact = [&self.job.configuration, &self.job.input]
            .into_iter()
            .flatten()
            .find(|artifact| artifact.digest == digest)
            .cloned()
            .ok_or_else(|| Status::not_found("unknown fake artifact"))?;
        let content = self
            .artifacts
            .get(&digest)
            .cloned()
            .ok_or_else(|| Status::not_found("missing fake artifact content"))?;
        let response = DownloadArtifactResponse {
            artifact: Some(artifact),
            offset: 0,
            chunk_digest: sha256(&content),
            data: content,
            complete: true,
        };
        let stream: ArtifactStream = Box::pin(tokio_stream::iter([Ok(response)]));
        Ok(Response::new(stream))
    }
}

fn sha256(content: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(content))
}

/// Scripted retry jitter for hermetic tests.
///
/// Each entry is a fraction of the caller's full-jitter window, consumed in
/// order; the queue repeats its final entry once exhausted, so a test never
/// depends on how many delays the SDK happens to draw.
#[derive(Debug)]
pub struct ScriptedJitter {
    fractions: Mutex<VecDeque<f64>>,
    last: Mutex<f64>,
}

impl ScriptedJitter {
    /// Always returns the full capped exponential window.
    #[must_use]
    pub fn max() -> Self {
        Self::repeating(1.0)
    }

    /// Always returns a zero delay.
    #[must_use]
    pub fn zero() -> Self {
        Self::repeating(0.0)
    }

    /// Returns each fraction of the window in turn, then repeats the last one.
    /// Values outside `[0.0, 1.0]` are clamped rather than rejected so a test
    /// fixture can never produce a delay outside the SDK's own window.
    #[must_use]
    pub fn scripted(fractions: Vec<f64>) -> Self {
        let last = fractions.last().copied().unwrap_or(1.0);
        Self {
            fractions: Mutex::new(fractions.into()),
            last: Mutex::new(clamp_fraction(last)),
        }
    }

    fn repeating(fraction: f64) -> Self {
        Self {
            fractions: Mutex::new(VecDeque::new()),
            last: Mutex::new(clamp_fraction(fraction)),
        }
    }
}

impl JitterSource for ScriptedJitter {
    // The scripted fraction is clamped to `[0.0, 1.0]` and the product is
    // clamped to the caller's window, so the conversions below are bounded by
    // construction and a rounding difference on a very large window is
    // irrelevant to a test fixture.
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss
    )]
    fn jitter_micros(&self, upper_bound_micros: u64) -> u64 {
        let mut queue = self
            .fractions
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut last = self
            .last
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(next) = queue.pop_front() {
            *last = clamp_fraction(next);
        }
        let scaled = *last * upper_bound_micros as f64;
        // `scaled` is finite and within `[0, upper_bound_micros]` by
        // construction, so the cast cannot saturate to an out-of-range value.
        (scaled.round() as u64).min(upper_bound_micros)
    }
}

fn clamp_fraction(value: f64) -> f64 {
    if value.is_nan() {
        return 0.0;
    }
    value.clamp(0.0, 1.0)
}
