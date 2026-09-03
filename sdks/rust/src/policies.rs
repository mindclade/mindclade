use std::sync::Arc;

use mindclade_protocols::{
    common::v1::{PageRequest, ResourceRef},
    internal::policy::v1::{
        ActivateUsePolicyRequest, CreateUsePolicyRequest, EvaluateAuthorizationRequest,
        GetUsePolicyRequest, ListUsePoliciesRequest, ResolvePolicySnapshotRequest,
        RevokeUsePolicyRequest, UpdateUsePolicyRequest,
    },
    operation::v1::Operation,
    policy::v1::{AuthorizationDecision, PolicyReference, UsePolicy},
};
use prost_types::Timestamp;

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_policy,
};

const EVALUATE: &str = "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization";
const CREATE: &str = "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy";
const UPDATE: &str = "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy";
const GET: &str = "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy";
const LIST: &str = "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies";
const ACTIVATE: &str = "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy";
const REVOKE: &str = "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy";
const RESOLVE: &str = "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot";

/// Fail-closed authorization and use-policy lifecycle over generated messages.
#[derive(Clone)]
pub struct Policies {
    core: Arc<ClientCore>,
}

impl Policies {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Evaluates exact intent and returns the immutable generated decision.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, intent, idempotency metadata, transport failure, or an incomplete response.
    pub async fn evaluate(
        &self,
        mut request: EvaluateAuthorizationRequest,
        options: SubmitOptions,
    ) -> Result<AuthorizationDecision, Error> {
        if request.action.trim().is_empty() || !valid_sha256(&request.intent_digest) {
            return Err(Error::invalid_argument(
                "authorization evaluation requires an action and sha256 intent digest",
            ));
        }
        normalize_resource(
            &self.core,
            request.resource.as_mut().ok_or_else(|| {
                Error::invalid_argument("authorization evaluation requires a resource")
            })?,
        )?;
        request.tenant_id = self.core.config.identity.tenant_id().to_owned();
        request.project_id = self.core.config.identity.project_id().to_owned();
        request.principal_ref = self.core.config.identity.principal_id().to_owned();
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.deadline = Some(prepared.deadline_timestamp()?);
        request.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(EVALUATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.evaluate_authorization(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .decision
            .ok_or_else(|| Error::protocol("EvaluateAuthorization response omitted its decision"))
    }

    /// Creates a use-policy and returns its durable generated operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, metadata, transport failure, or an incomplete response.
    pub async fn create(
        &self,
        mut request: CreateUsePolicyRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let parent = project_name(&self.core);
        if (!request.parent.is_empty() && request.parent != parent)
            || !valid_id(&request.use_policy_id)
            || request.use_policy.is_none()
        {
            return Err(Error::invalid_argument(
                "policy creation requires the configured project, a valid ID, and a policy",
            ));
        }
        request.parent = parent;
        request.context = None;
        let response = self
            .mutate(request, options, CREATE, |transport, request| {
                Box::pin(async move { transport.create_use_policy(request).await })
            })
            .await?;
        require_operation(response.operation, "CreateUsePolicy")
    }

    /// Applies a generated optimistic update.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/concurrency metadata, transport failure, or an incomplete response.
    pub async fn update(
        &self,
        mut request: UpdateUsePolicyRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let name = request
            .use_policy
            .as_ref()
            .map(|value| value.name.as_str())
            .unwrap_or_default();
        policy_name(&self.core, name)?;
        if request.update_mask.is_none() || request.etag.trim().is_empty() {
            return Err(Error::invalid_argument(
                "policy update requires a field mask and etag",
            ));
        }
        request.context = None;
        let response = self
            .mutate(request, options, UPDATE, |transport, request| {
                Box::pin(async move { transport.update_use_policy(request).await })
            })
            .await?;
        require_operation(response.operation, "UpdateUsePolicy")
    }

    /// Reads one generated policy resource.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or an incomplete response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<UsePolicy, Error> {
        let name = policy_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetUsePolicyRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_policy(GET),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_use_policy(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .use_policy
            .ok_or_else(|| Error::protocol("GetUsePolicy response omitted its policy"))
    }

    /// Lists one bounded generated policy page while preserving its opaque token.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination and for transport failures.
    pub fn list(
        &self,
        mut request: ListUsePoliciesRequest,
        options: CallOptions,
    ) -> Result<Pages<UsePolicy>, Error> {
        let parent = project_name(&self.core);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "policy list parent does not match client scope",
            ));
        }
        validate_page(request.page.as_ref())?;
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
                                Box::pin(async move { transport.list_use_policies(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.use_policies,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Activates the exact policy snapshot under optimistic concurrency.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or etag, transport failure, or an incomplete response.
    pub async fn activate(
        &self,
        name: impl Into<String>,
        etag: impl Into<String>,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let name = policy_name(&self.core, &name.into())?;
        let etag = etag.into();
        if etag.trim().is_empty() {
            return Err(Error::invalid_argument(
                "policy activation requires an etag",
            ));
        }
        let request = ActivateUsePolicyRequest {
            context: None,
            name,
            etag,
        };
        let response = self
            .mutate(request, options, ACTIVATE, |transport, request| {
                Box::pin(async move { transport.activate_use_policy(request).await })
            })
            .await?;
        require_operation(response.operation, "ActivateUsePolicy")
    }

    /// Records a fail-closed policy revocation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or reason, transport failure, or an incomplete response.
    pub async fn revoke(
        &self,
        name: impl Into<String>,
        etag: impl Into<String>,
        reason_code: impl Into<String>,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let name = policy_name(&self.core, &name.into())?;
        let etag = etag.into();
        let reason_code = reason_code.into();
        if etag.trim().is_empty() || reason_code.trim().is_empty() {
            return Err(Error::invalid_argument(
                "policy revocation requires an etag and reason code",
            ));
        }
        let request = RevokeUsePolicyRequest {
            context: None,
            name,
            etag,
            reason_code,
        };
        let response = self
            .mutate(request, options, REVOKE, |transport, request| {
                Box::pin(async move { transport.revoke_use_policy(request).await })
            })
            .await?;
        require_operation(response.operation, "RevokeUsePolicy")
    }

    /// Resolves an immutable policy snapshot at an explicit effective time.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or time, transport failure, or an incomplete response.
    pub async fn resolve_snapshot(
        &self,
        name: impl Into<String>,
        effective_time: Timestamp,
        options: CallOptions,
    ) -> Result<PolicyReference, Error> {
        let name = policy_name(&self.core, &name.into())?;
        if effective_time.nanos < 0 || effective_time.nanos >= 1_000_000_000 {
            return Err(Error::invalid_argument("effective time is invalid"));
        }
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                ResolvePolicySnapshotRequest {
                    name,
                    effective_time: Some(effective_time),
                },
                &prepared,
                registered_method_policy(RESOLVE),
                None,
                |transport, request| {
                    Box::pin(async move { transport.resolve_policy_snapshot(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .policy_snapshot
            .ok_or_else(|| Error::protocol("ResolvePolicySnapshot response omitted its snapshot"))
    }

    async fn mutate<T, R, F>(
        &self,
        mut request: T,
        options: SubmitOptions,
        method: &'static str,
        assign: F,
    ) -> Result<R, Error>
    where
        T: PolicyCommand + Clone + Send + 'static,
        R: Send + 'static,
        F: Fn(Arc<dyn crate::RpcTransport>, tonic::Request<T>) -> crate::retry::RpcFuture<R>,
    {
        let prepared = options.call.prepare(&self.core.config);
        request.set_context(Some(prepared.command_context(&self.core.config, &options)?));
        let key = options.idempotency_key.clone();
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(method),
                Some(&key),
                assign,
            )
            .await?
            .into_inner())
    }
}

trait PolicyCommand {
    fn set_context(&mut self, context: Option<mindclade_protocols::common::v1::CommandContext>);
}

macro_rules! policy_command {
    ($($value:ty),+ $(,)?) => {$(
        impl PolicyCommand for $value {
            fn set_context(&mut self, context: Option<mindclade_protocols::common::v1::CommandContext>) {
                self.context = context;
            }
        }
    )+};
}

policy_command!(
    CreateUsePolicyRequest,
    UpdateUsePolicyRequest,
    ActivateUsePolicyRequest,
    RevokeUsePolicyRequest,
);

fn project_name(core: &ClientCore) -> String {
    let tenant = tenant_name(core);
    let project = core.config.identity.project_id();
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn tenant_name(core: &ClientCore) -> String {
    let tenant = core.config.identity.tenant_id();
    if tenant.starts_with("tenants/") {
        tenant.to_owned()
    } else {
        format!("tenants/{tenant}")
    }
}

fn policy_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    let prefix = format!("{}/usePolicies/", project_name(core));
    let id = name
        .strip_prefix(&prefix)
        .ok_or_else(|| Error::invalid_argument("policy is outside the configured project"))?;
    if !valid_id(id) {
        return Err(Error::invalid_argument("policy name is invalid"));
    }
    Ok(name.to_owned())
}

fn normalize_resource(core: &ClientCore, resource: &mut ResourceRef) -> Result<(), Error> {
    let parent = project_name(core);
    if resource.name != parent && !resource.name.starts_with(&format!("{parent}/")) {
        return Err(Error::invalid_argument(
            "resource is outside the configured project",
        ));
    }
    if (!resource.tenant_id.is_empty() && resource.tenant_id != core.config.identity.tenant_id())
        || (!resource.project_id.is_empty()
            && resource.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "resource scope conflicts with client identity",
        ));
    }
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut resource.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut resource.project_id);
    Ok(())
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_' | b'.'))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..].bytes().all(|value| value.is_ascii_hexdigit())
}

fn validate_page(page: Option<&PageRequest>) -> Result<(), Error> {
    if page.is_some_and(|value| value.page_size > 1000) {
        return Err(Error::invalid_argument("page size cannot exceed 1000"));
    }
    Ok(())
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
