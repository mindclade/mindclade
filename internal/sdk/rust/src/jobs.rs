use std::sync::Arc;

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    internal::job::v1::{CancelJobRequest, GetJobRequest, ListJobsRequest, RequestJobRequest},
    job::v1::{Job, Operation, RequestJobCommand},
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_policy,
};

const REQUEST: &str = "/mindclade.internal.job.v1.JobService/RequestJob";
const GET: &str = "/mindclade.internal.job.v1.JobService/GetJob";
const LIST: &str = "/mindclade.internal.job.v1.JobService/ListJobs";
const CANCEL: &str = "/mindclade.internal.job.v1.JobService/CancelJob";

/// Durable admitted-work helpers over authoritative generated `JobService` types.
#[derive(Clone)]
pub struct Jobs {
    core: Arc<ClientCore>,
}

impl Jobs {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Admits a generated job command and returns its durable job and operation.
    ///
    /// # Errors
    ///
    /// Returns an error for malformed intent, invalid credentials, transport
    /// failure, or a response outside the configured identity scope.
    pub async fn request(
        &self,
        mut command: RequestJobCommand,
        options: SubmitOptions,
    ) -> Result<(Job, Operation), Error> {
        if !valid_leaf(&command.job_kind)
            || !valid_artifact(command.configuration.as_ref(), true)
            || !valid_artifact(command.input.as_ref(), false)
            || (!command.requested_job_id.is_empty() && !valid_leaf(&command.requested_job_id))
        {
            return Err(Error::invalid_argument(
                "job request requires a valid kind, optional ID, and content-addressed configuration",
            ));
        }
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&command);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                RequestJobRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_policy(REQUEST),
                Some(&key),
                |transport, request| Box::pin(async move { transport.request_job(request).await }),
            )
            .await?
            .into_inner();
        let job = response
            .job
            .ok_or_else(|| Error::protocol("RequestJob response omitted its job"))?;
        let operation = response
            .operation
            .ok_or_else(|| Error::protocol("RequestJob response omitted its operation"))?;
        if !valid_job(&self.core, &job)
            || !valid_operation(&self.core, &operation)
            || job.operation_id != operation.operation_id
            || operation.job_id != job.job_id
        {
            return Err(Error::protocol(
                "RequestJob response changed durable identity",
            ));
        }
        Ok((job, operation))
    }

    /// Reads one durable job revision.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or cache metadata, credentials,
    /// transport failure, or a malformed response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Job, Error> {
        let name = canonical_resource(&self.core, &name.into(), "jobs")?;
        let if_none_match = if_none_match.into();
        if if_none_match.len() > 512 || contains_transport_control(&if_none_match) {
            return Err(Error::invalid_argument("job cache validator is invalid"));
        }
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetJobRequest {
                    name: name.clone(),
                    if_none_match,
                },
                &prepared,
                registered_method_policy(GET),
                None,
                |transport, request| Box::pin(async move { transport.get_job(request).await }),
            )
            .await?
            .into_inner();
        let job = response
            .job
            .ok_or_else(|| Error::protocol("GetJob response omitted its job"))?;
        if job.job_id != name || !valid_job(&self.core, &job) {
            return Err(Error::protocol("GetJob response changed durable identity"));
        }
        Ok(job)
    }

    /// Lists one bounded project-scoped page and preserves opaque tokens.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or query bounds, credentials,
    /// transport failure, or a response outside the configured project.
    pub fn list(
        &self,
        mut request: ListJobsRequest,
        options: CallOptions,
    ) -> Result<Pages<Job>, Error> {
        let parent = project_name(&self.core);
        if (!request.parent.is_empty() && request.parent != parent)
            || request
                .page
                .as_ref()
                .is_some_and(|page| page.page_size > 200)
            || !request.filter.trim().is_empty()
            || !matches!(request.order_by.as_str(), "" | "job_id")
        {
            return Err(Error::invalid_argument(
                "job list scope, page size, filter, or ordering is invalid",
            ));
        }
        request.parent = parent;
        let core = Arc::clone(&self.core);
        let token = initial_page_token(request.page.as_ref());
        Ok(Pages::new(
            move |page_token| {
                let core = Arc::clone(&core);
                let options = options.clone();
                let mut request = request.clone();
                async move {
                    request.page = Some(page_request(request.page.as_ref(), page_token));
                    let prepared = options.prepare(&core.config);
                    let response = core
                        .unary(
                            request,
                            &prepared,
                            registered_method_policy(LIST),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_jobs(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    if response.jobs.iter().any(|job| !valid_job(&core, job)) {
                        return Err(Error::protocol(
                            "ListJobs response escaped configured scope",
                        ));
                    }
                    Ok(Page::new(
                        response.jobs,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Records monotonic job cancellation under an `ETag` precondition.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid intent, credentials, transport failure,
    /// or a malformed operation response.
    pub async fn cancel(
        &self,
        mut request: CancelJobRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        request.name = canonical_resource(&self.core, &request.name, "jobs")?;
        if request.etag.trim().is_empty()
            || request.etag.len() > 512
            || contains_transport_control(&request.etag)
            || request.reason.len() > 4096
            || request.reason.contains('\0')
        {
            return Err(Error::invalid_argument(
                "job cancellation requires a valid ETag and bounded reason",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let expected_job = request.name.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(CANCEL),
                Some(&key),
                |transport, request| Box::pin(async move { transport.cancel_job(request).await }),
            )
            .await?
            .into_inner();
        let operation = response
            .operation
            .ok_or_else(|| Error::protocol("CancelJob response omitted its operation"))?;
        if operation.job_id != expected_job || !valid_operation(&self.core, &operation) {
            return Err(Error::protocol(
                "CancelJob response changed durable identity",
            ));
        }
        Ok(operation)
    }
}

pub(crate) fn project_name(core: &ClientCore) -> String {
    format!(
        "tenants/{}/projects/{}",
        core.config
            .identity
            .tenant_id()
            .trim_start_matches("tenants/"),
        core.config
            .identity
            .project_id()
            .trim_start_matches("projects/")
    )
}

pub(crate) fn canonical_resource(
    core: &ClientCore,
    value: &str,
    collection: &str,
) -> Result<String, Error> {
    let value = value.trim();
    if valid_leaf(value) {
        return Ok(format!("{collection}/{value}"));
    }
    if valid_compact_resource(value, collection) {
        return Ok(value.to_owned());
    }
    let prefix = format!("{}/{collection}/", project_name(core));
    if let Some(leaf) = value.strip_prefix(&prefix)
        && valid_leaf(leaf)
    {
        return Ok(format!("{collection}/{leaf}"));
    }
    Err(Error::invalid_argument(format!(
        "{collection} resource is outside configured project"
    )))
}

pub(crate) fn valid_leaf(value: &str) -> bool {
    let value = value.trim();
    !value.is_empty()
        && value.len() <= 255
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

pub(crate) fn valid_compact_resource(value: &str, collection: &str) -> bool {
    value
        .strip_prefix(collection)
        .and_then(|rest| rest.strip_prefix('/'))
        .is_some_and(valid_leaf)
}

pub(crate) fn protobuf_digest(value: &impl Message) -> String {
    let bytes = value.encode_to_vec();
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn valid_artifact(value: Option<&ArtifactRef>, required: bool) -> bool {
    match value {
        None => !required,
        Some(value) => {
            valid_sha256(&value.digest)
                && !value.media_type.trim().is_empty()
                && value.size_bytes >= 0
        }
    }
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn valid_job(core: &ClientCore, value: &Job) -> bool {
    value.tenant_id == core.config.identity.tenant_id()
        && value.project_id == core.config.identity.project_id()
        && valid_compact_resource(&value.job_id, "jobs")
        && valid_compact_resource(&value.operation_id, "operations")
        && value.resource_version > 0
        && value.state != 0
}

fn valid_operation(core: &ClientCore, value: &Operation) -> bool {
    value.tenant_id == core.config.identity.tenant_id()
        && value.project_id == core.config.identity.project_id()
        && valid_compact_resource(&value.operation_id, "operations")
        && value.resource_version > 0
        && value.state != 0
}

fn contains_transport_control(value: &str) -> bool {
    value.bytes().any(|byte| matches!(byte, 0 | b'\r' | b'\n'))
}
