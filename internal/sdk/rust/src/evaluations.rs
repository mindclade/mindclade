use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::ResourceRef,
    evaluation::v1::{EvaluationResult, EvaluationRun, PromotionDecision},
    internal::evaluation::v1::{
        CancelEvaluationRunRequest, CommitEvaluationResultRequest, CreateEvaluationRunRequest,
        CreatePromotionDecisionRequest, GetEvaluationResultRequest, GetEvaluationRunRequest,
        GetPromotionDecisionRequest, ListEvaluationRunsRequest, ListEvaluationRunsResponse,
    },
    job::v1::{LeaseFence, Operation},
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{CallOptions, ClientCore, Error, SubmitOptions, retry::registered_method_safety};

const CREATE: &str = "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun";
const GET_RUN: &str = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun";
const LIST: &str = "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns";
const CANCEL: &str = "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun";
const COMMIT: &str = "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult";
const GET_RESULT: &str = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult";
const CREATE_DECISION: &str =
    "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision";
const GET_DECISION: &str =
    "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision";

/// Generated-type-only evaluation execution and evidence-governance facade.
#[derive(Clone)]
pub struct Evaluations {
    core: Arc<ClientCore>,
}

impl Evaluations {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Creates one immutable evaluation intent and returns its durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error when intent validation, authentication, transport, or
    /// response validation fails.
    pub async fn create_run(
        &self,
        mut request: CreateEvaluationRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let parent = project_name(&self.core);
        if (!request.parent.is_empty() && request.parent != parent)
            || !valid_id(&request.evaluation_run_id)
            || request.datasets.is_empty()
            || request.datasets.len() > 256
        {
            return Err(Error::invalid_argument(
                "evaluation creation requires configured scope, a valid ID, and bounded datasets",
            ));
        }
        validate_artifact(request.suite.as_ref(), "evaluation suite")?;
        validate_artifact(request.snapshot.as_ref(), "evaluation snapshot")?;
        validate_artifact(request.inference_protocol.as_ref(), "inference protocol")?;
        for dataset in &request.datasets {
            validate_artifact(Some(dataset), "evaluation dataset")?;
        }
        normalize_reference(
            &self.core,
            request
                .model_release
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("evaluation model release is required"))?,
            "model_release",
            "/models/",
        )?;
        request.parent = parent;
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CREATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_evaluation_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CreateEvaluationRun")
    }

    /// Reads one generated evaluation run revision.
    ///
    /// # Errors
    ///
    /// Returns an error when the name is out of scope or the transport returns
    /// missing or inconsistent generated state.
    pub async fn get_run(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<EvaluationRun, Error> {
        let name = scoped_name(&self.core, &name.into(), "evaluationRuns")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetEvaluationRunRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET_RUN),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_evaluation_run(request).await })
                },
            )
            .await?
            .into_inner();
        let value = response
            .evaluation_run
            .ok_or_else(|| Error::protocol("GetEvaluationRun response omitted its run"))?;
        if value.name != name {
            return Err(Error::protocol(
                "GetEvaluationRun response changed resource identity",
            ));
        }
        Ok(value)
    }

    /// Lists one bounded project-scoped page and preserves opaque page tokens.
    ///
    /// # Errors
    ///
    /// Returns an error when scope or pagination is invalid or the transport
    /// call fails.
    pub async fn list_runs(
        &self,
        mut request: ListEvaluationRunsRequest,
        options: CallOptions,
    ) -> Result<ListEvaluationRunsResponse, Error> {
        let parent = project_name(&self.core);
        if (!request.parent.is_empty() && request.parent != parent)
            || request
                .page
                .as_ref()
                .is_some_and(|page| page.page_size > 200)
        {
            return Err(Error::invalid_argument(
                "evaluation list scope or page size is invalid",
            ));
        }
        request.parent = parent;
        let prepared = options.prepare(&self.core.config);
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_evaluation_runs(request).await })
                },
            )
            .await?
            .into_inner())
    }

    /// Records monotonic cancellation under optimistic concurrency.
    ///
    /// # Errors
    ///
    /// Returns an error when the request is invalid, authentication or
    /// transport fails, or the response omits its durable operation.
    pub async fn cancel_run(
        &self,
        mut request: CancelEvaluationRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        request.name = scoped_name(&self.core, &request.name, "evaluationRuns")?;
        if request.etag.trim().is_empty() || request.reason.trim().is_empty() {
            return Err(Error::invalid_argument(
                "evaluation cancellation requires an etag and reason",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CANCEL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_evaluation_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CancelEvaluationRun")
    }

    /// Commits one immutable result under the scheduler-issued lease capability.
    ///
    /// # Errors
    ///
    /// Returns an error when result identity, digests, fencing, authentication,
    /// transport, or returned durable state is invalid.
    pub async fn commit_result(
        &self,
        mut request: CommitEvaluationResultRequest,
        options: SubmitOptions,
    ) -> Result<(EvaluationResult, EvaluationRun), Error> {
        if request.etag.trim().is_empty() {
            return Err(Error::invalid_argument(
                "evaluation result commit requires an etag",
            ));
        }
        let run = request
            .evaluation_run
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("evaluation result commit requires a run"))?;
        normalize_reference(&self.core, run, "evaluation_run", "/evaluationRuns/")?;
        let run_name = run.name.clone();
        let result = request
            .result
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("evaluation result commit requires a result"))?;
        result.name = scoped_name(&self.core, &result.name, "evaluationResults")?;
        let result_name = result.name.clone();
        let result_run = result
            .run
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("evaluation result requires its run"))?;
        normalize_reference(&self.core, result_run, "evaluation_run", "/evaluationRuns/")?;
        if result_run.name != run_name
            || !valid_sha256(&result.run_digest)
            || !valid_sha256(&result.result_digest)
        {
            return Err(Error::invalid_argument(
                "evaluation result identity or digest is invalid",
            ));
        }
        normalize_fence(
            &self.core,
            request.fence.as_mut().ok_or_else(|| {
                Error::invalid_argument("evaluation result commit requires a fence")
            })?,
        )?;
        request.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(COMMIT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_evaluation_result(request).await })
                },
            )
            .await?
            .into_inner();
        let result = response
            .result
            .ok_or_else(|| Error::protocol("CommitEvaluationResult response omitted its result"))?;
        let run = response
            .evaluation_run
            .ok_or_else(|| Error::protocol("CommitEvaluationResult response omitted its run"))?;
        if result.name != result_name || run.name != run_name {
            return Err(Error::protocol(
                "CommitEvaluationResult response changed durable identity",
            ));
        }
        Ok((result, run))
    }

    /// Reads one immutable generated evaluation result.
    ///
    /// # Errors
    ///
    /// Returns an error when the resource is out of scope or returned state is
    /// missing or inconsistent.
    pub async fn get_result(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<EvaluationResult, Error> {
        let name = scoped_name(&self.core, &name.into(), "evaluationResults")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetEvaluationResultRequest { name: name.clone() },
                &prepared,
                registered_method_safety(GET_RESULT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_evaluation_result(request).await })
                },
            )
            .await?
            .into_inner();
        let value = response
            .result
            .ok_or_else(|| Error::protocol("GetEvaluationResult response omitted its result"))?;
        if value.name != name {
            return Err(Error::protocol(
                "GetEvaluationResult response changed resource identity",
            ));
        }
        Ok(value)
    }

    /// Records an immutable evidence-governance decision without deploying it.
    ///
    /// # Errors
    ///
    /// Returns an error when evidence, scope, authentication, transport, or the
    /// returned durable operation is invalid.
    pub async fn create_promotion_decision(
        &self,
        mut request: CreatePromotionDecisionRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let decision = request
            .promotion_decision
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("promotion decision is required"))?;
        decision.name = scoped_name(&self.core, &decision.name, "promotionDecisions")?;
        if !valid_sha256(&decision.candidate_digest)
            || !valid_sha256(&decision.decision_digest)
            || decision.evaluation_results.is_empty()
        {
            return Err(Error::invalid_argument(
                "promotion decision evidence or digest is invalid",
            ));
        }
        normalize_reference(
            &self.core,
            decision
                .candidate_release
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("promotion candidate is required"))?,
            "model_release",
            "/models/",
        )?;
        for result in &mut decision.evaluation_results {
            normalize_reference(
                &self.core,
                result,
                "evaluation_result",
                "/evaluationResults/",
            )?;
        }
        for policy in &mut decision.policy_decisions {
            if (!policy.tenant_id.is_empty()
                && policy.tenant_id != self.core.config.identity.tenant_id())
                || (!policy.project_id.is_empty()
                    && policy.project_id != self.core.config.identity.project_id())
            {
                return Err(Error::invalid_argument(
                    "promotion policy evidence conflicts with client scope",
                ));
            }
            self.core
                .config
                .identity
                .tenant_id()
                .clone_into(&mut policy.tenant_id);
            self.core
                .config
                .identity
                .project_id()
                .clone_into(&mut policy.project_id);
        }
        self.core
            .config
            .identity
            .principal_id()
            .clone_into(&mut decision.decided_by_principal_ref);
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CREATE_DECISION),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_promotion_decision(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CreatePromotionDecision")
    }

    /// Reads one immutable generated promotion decision.
    ///
    /// # Errors
    ///
    /// Returns an error when the resource is out of scope or returned state is
    /// missing or inconsistent.
    pub async fn get_promotion_decision(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<PromotionDecision, Error> {
        let name = scoped_name(&self.core, &name.into(), "promotionDecisions")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetPromotionDecisionRequest { name: name.clone() },
                &prepared,
                registered_method_safety(GET_DECISION),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_promotion_decision(request).await })
                },
            )
            .await?
            .into_inner();
        let value = response
            .promotion_decision
            .ok_or_else(|| Error::protocol("GetPromotionDecision response omitted its decision"))?;
        if value.name != name {
            return Err(Error::protocol(
                "GetPromotionDecision response changed resource identity",
            ));
        }
        Ok(value)
    }
}

fn project_name(core: &ClientCore) -> String {
    let tenant = core.config.identity.tenant_id();
    let tenant = if tenant.starts_with("tenants/") {
        tenant.to_owned()
    } else {
        format!("tenants/{tenant}")
    };
    let project = core.config.identity.project_id();
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn scoped_name(core: &ClientCore, name: &str, collection: &str) -> Result<String, Error> {
    let prefix = format!("{}/{collection}/", project_name(core));
    let id = name
        .strip_prefix(&prefix)
        .ok_or_else(|| Error::invalid_argument("resource is outside the configured project"))?;
    if !valid_id(id) {
        return Err(Error::invalid_argument("resource name is invalid"));
    }
    Ok(name.to_owned())
}

fn normalize_reference(
    core: &ClientCore,
    value: &mut ResourceRef,
    resource_type: &str,
    required_path: &str,
) -> Result<(), Error> {
    let parent = project_name(core);
    if !value.name.starts_with(&format!("{parent}/")) || !value.name.contains(required_path) {
        return Err(Error::invalid_argument(
            "resource reference is outside the configured project",
        ));
    }
    let id = value.name.rsplit('/').next().unwrap_or_default();
    if !valid_id(id)
        || (!value.resource_type.is_empty() && value.resource_type != resource_type)
        || (!value.resource_id.is_empty() && value.resource_id != id)
        || (!value.tenant_id.is_empty() && value.tenant_id != core.config.identity.tenant_id())
        || (!value.project_id.is_empty() && value.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "resource reference conflicts with evaluation intent",
        ));
    }
    resource_type.clone_into(&mut value.resource_type);
    value.resource_id = id.to_owned();
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut value.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut value.project_id);
    Ok(())
}

fn validate_artifact(value: Option<&ArtifactRef>, label: &str) -> Result<(), Error> {
    let value = value.ok_or_else(|| Error::invalid_argument(format!("{label} is required")))?;
    if !valid_sha256(&value.digest)
        || (!value.integrity_digest.is_empty() && !valid_sha256(&value.integrity_digest))
        || value.media_type.trim().is_empty()
        || value.size_bytes < 0
    {
        return Err(Error::invalid_argument(format!("{label} is invalid")));
    }
    Ok(())
}

fn normalize_fence(core: &ClientCore, fence: &mut LeaseFence) -> Result<(), Error> {
    let deadline = fence
        .deadline
        .as_ref()
        .ok_or_else(|| Error::invalid_argument("evaluation fence deadline is required"))?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::invalid_argument("system clock is invalid"))?;
    if fence.job_id.is_empty()
        || fence.run_id.is_empty()
        || fence.attempt_id.is_empty()
        || fence.lease_epoch == 0
        || !valid_sha256(&fence.lease_token_digest)
        || deadline.seconds < i64::try_from(now.as_secs()).unwrap_or(i64::MAX)
        || (!fence.tenant_id.is_empty() && fence.tenant_id != core.config.identity.tenant_id())
        || (!fence.project_id.is_empty() && fence.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "evaluation lease fence is invalid or expired",
        ));
    }
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut fence.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut fence.project_id);
    Ok(())
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.contains('/')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn protobuf_digest(message: &impl Message) -> String {
    format!("sha256:{:x}", Sha256::digest(message.encode_to_vec()))
}

fn require_operation(operation: Option<Operation>, method: &str) -> Result<Operation, Error> {
    let operation = operation
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its operation")))?;
    if operation.operation_id.trim().is_empty() {
        return Err(Error::protocol(format!(
            "{method} response operation has no identity"
        )));
    }
    Ok(operation)
}
