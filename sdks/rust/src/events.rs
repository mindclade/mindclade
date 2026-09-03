use std::fmt;

use mindclade_protocols::{
    common::v1::EventEnvelope, event_registry::EVENT_REGISTRATIONS, job::v1::JobRequested,
};
use prost::Message;
use sha2::{Digest, Sha256};

const JOB_REQUESTED: &str = "mindclade.events.job.v1.JobRequested";
const MAX_ENVELOPE_BYTES: usize = 8 << 20;
const MAX_EVENT_PAYLOAD_BYTES: usize = 64 << 10;

/// Safe failure for an immutable delivery that did not satisfy the registry.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EventRejectedError {
    message: &'static str,
}

impl EventRejectedError {
    fn new(message: &'static str) -> Self {
        Self { message }
    }
}

impl fmt::Display for EventRejectedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for EventRejectedError {}

/// Verified facts from a `JobRequested` delivery. This is an SDK behavior
/// value, not a duplicate wire model; Protobuf remains the decoding authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JobRequestedDelivery {
    pub event_id: String,
    pub job_id: String,
    pub configuration_digest: String,
    pub request_id: String,
    pub trace_id: String,
}

/// Verifies one exact-version registered `JobRequested` event delivery.
///
/// # Errors
///
/// Returns an error for malformed, unknown, non-canonical, or cross-scope bytes.
pub fn decode_job_requested_delivery(
    serialized: &[u8],
    tenant_id: &str,
    project_id: &str,
) -> Result<JobRequestedDelivery, EventRejectedError> {
    if serialized.is_empty() || serialized.len() > MAX_ENVELOPE_BYTES {
        return Err(EventRejectedError::new(
            "event envelope size is outside policy",
        ));
    }
    let envelope = EventEnvelope::decode(serialized)
        .map_err(|_| EventRejectedError::new("event envelope is not valid protobuf"))?;
    let registration = EVENT_REGISTRATIONS
        .iter()
        .find(|registration| registration.full_name == JOB_REQUESTED)
        .ok_or_else(|| EventRejectedError::new("event type is not registered"))?;
    if registration.compatibility_policy != "exact-version"
        || envelope.event_type != registration.full_name
        || envelope.event_version != registration.version
        || envelope.payload_content_type != registration.content_type
        || envelope.tenant_id != tenant_id
        || envelope.project_id != project_id
        || envelope.event_id.is_empty()
        || envelope.aggregate_sequence == 0
        || envelope.occurred_at.is_none()
        || envelope.recorded_at.is_none()
        || envelope.payload.is_empty()
        || envelope.payload.len() > MAX_EVENT_PAYLOAD_BYTES
    {
        return Err(EventRejectedError::new(
            "event identity, version, scope, or timing is invalid",
        ));
    }
    if envelope.payload_digest != sha256(&envelope.payload) {
        return Err(EventRejectedError::new(
            "event payload digest verification failed",
        ));
    }
    let event = JobRequested::decode(envelope.payload.as_slice())
        .map_err(|_| EventRejectedError::new("payload is not a JobRequested protobuf"))?;
    if event.encode_to_vec() != envelope.payload {
        return Err(EventRejectedError::new(
            "JobRequested payload is not canonical",
        ));
    }
    if !valid_resource(&event.job_id, "jobs")
        || !valid_digest(&event.configuration_digest)
        || envelope.job_id != event.job_id
    {
        return Err(EventRejectedError::new(
            "JobRequested identity or configuration digest is invalid",
        ));
    }
    if let Some(subject) = &envelope.subject
        && ((!subject.resource_type.is_empty() && subject.resource_type != "job")
            || (!subject.resource_id.is_empty()
                && subject.resource_id != event.job_id.trim_start_matches("jobs/")))
    {
        return Err(EventRejectedError::new(
            "event subject does not identify the requested job",
        ));
    }
    Ok(JobRequestedDelivery {
        event_id: envelope.event_id.clone(),
        job_id: event.job_id,
        configuration_digest: event.configuration_digest,
        request_id: if envelope.request_id.is_empty() {
            envelope.event_id.clone()
        } else {
            envelope.request_id
        },
        trace_id: if envelope.trace_id.is_empty() {
            envelope.event_id
        } else {
            envelope.trace_id
        },
    })
}

fn sha256(content: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(content))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn valid_resource(value: &str, collection: &str) -> bool {
    value
        .strip_prefix(collection)
        .and_then(|value| value.strip_prefix('/'))
        .is_some_and(|leaf| {
            !leaf.is_empty()
                && leaf.len() <= 255
                && leaf
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        })
}
