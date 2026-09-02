use std::sync::Arc;

use mindclade_protocols::{
    common::v1::ResourceRef,
    internal::model::v1::{
        GetModelReleaseRequest, GetModelRequest, ListModelReleasesRequest, ListModelsRequest,
        PromoteModelReleaseRequest, RegisterModelReleaseRequest, RegisterModelRequest,
        RevokeModelReleaseRequest,
    },
    job::v1::Operation,
    model::v1::{
        Model, ModelRelease, PromoteModelReleaseCommand, RegisterModelCommand,
        RegisterModelReleaseCommand, RevokeModelReleaseCommand,
    },
};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_policy,
};

const REGISTER: &str = "/mindclade.internal.model.v1.ModelService/RegisterModel";
const GET: &str = "/mindclade.internal.model.v1.ModelService/GetModel";
const LIST: &str = "/mindclade.internal.model.v1.ModelService/ListModels";
const REGISTER_RELEASE: &str = "/mindclade.internal.model.v1.ModelService/RegisterModelRelease";
const GET_RELEASE: &str = "/mindclade.internal.model.v1.ModelService/GetModelRelease";
const LIST_RELEASES: &str = "/mindclade.internal.model.v1.ModelService/ListModelReleases";
const PROMOTE: &str = "/mindclade.internal.model.v1.ModelService/PromoteModelRelease";
const REVOKE: &str = "/mindclade.internal.model.v1.ModelService/RevokeModelRelease";

/// Private model registry and immutable release API over generated contracts.
#[derive(Clone)]
pub struct Models {
    core: Arc<ClientCore>,
}

impl Models {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Registers a generated logical model and returns its durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, command metadata, credentials, transport failure, or a malformed response.
    pub async fn register(
        &self,
        mut command: RegisterModelCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let expected = project_name(&self.core);
        match &command.project {
            Some(project) if project.name != expected => {
                return Err(Error::invalid_argument(
                    "model project does not match client scope",
                ));
            }
            None => command.project = Some(project_ref(&self.core)),
            _ => {}
        }
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                RegisterModelRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_policy(REGISTER),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.register_model(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "RegisterModel")
    }

    /// Gets one generated model resource in the configured project.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, credentials, transport failure, or a malformed response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Model, Error> {
        let name = model_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetModelRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_policy(GET),
                None,
                |transport, request| Box::pin(async move { transport.get_model(request).await }),
            )
            .await?
            .into_inner();
        response
            .model
            .ok_or_else(|| Error::protocol("GetModel response omitted its model"))
    }

    /// Lists one bounded page of generated model resources.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials, or transport failure.
    pub fn list(
        &self,
        mut request: ListModelsRequest,
        options: CallOptions,
    ) -> Result<Pages<Model>, Error> {
        let parent = project_name(&self.core);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "model list parent does not match client scope",
            ));
        }
        request.parent = parent;
        validate_page(request.page.as_ref())?;
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
                                Box::pin(async move { transport.list_models(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.models,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Registers an immutable generated model release.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid reference or command, credentials, transport failure, or a malformed response.
    pub async fn register_release(
        &self,
        mut command: RegisterModelReleaseCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_reference(
            &self.core,
            command
                .model
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("release requires a model reference"))?,
            "model",
            false,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                RegisterModelReleaseRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_policy(REGISTER_RELEASE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.register_model_release(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "RegisterModelRelease")
    }

    /// Gets one generated immutable model release.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, credentials, transport failure, or a malformed response.
    pub async fn get_release(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<ModelRelease, Error> {
        let name = release_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetModelReleaseRequest { name },
                &prepared,
                registered_method_policy(GET_RELEASE),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_model_release(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .model_release
            .ok_or_else(|| Error::protocol("GetModelRelease response omitted its release"))
    }

    /// Lists one bounded page of releases under a generated model name.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials, or transport failure.
    pub fn list_releases(
        &self,
        request: ListModelReleasesRequest,
        options: CallOptions,
    ) -> Result<Pages<ModelRelease>, Error> {
        model_name(&self.core, &request.parent)?;
        validate_page(request.page.as_ref())?;
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
                            registered_method_policy(LIST_RELEASES),
                            None,
                            |transport, request| {
                                Box::pin(
                                    async move { transport.list_model_releases(request).await },
                                )
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.model_releases,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Promotes a generated model release using optimistic evidence-bound intent.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid reference or command, credentials, transport failure, or a malformed response.
    pub async fn promote_release(
        &self,
        mut command: PromoteModelReleaseCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_reference(
            &self.core,
            command.model_release.as_mut().ok_or_else(|| {
                Error::invalid_argument("promotion requires a model release reference")
            })?,
            "model_release",
            true,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                PromoteModelReleaseRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_policy(PROMOTE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.promote_model_release(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "PromoteModelRelease")
    }

    /// Records a non-destructive generated model release revocation.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid reference or command, credentials, transport failure, or a malformed response.
    pub async fn revoke_release(
        &self,
        mut command: RevokeModelReleaseCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_reference(
            &self.core,
            command.model_release.as_mut().ok_or_else(|| {
                Error::invalid_argument("revocation requires a model release reference")
            })?,
            "model_release",
            true,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                RevokeModelReleaseRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_policy(REVOKE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.revoke_model_release(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "RevokeModelRelease")
    }
}

fn project_name(core: &ClientCore) -> String {
    project_parent(&core.config)
}

fn project_parent(config: &crate::Config) -> String {
    let tenant = if config.identity.tenant_id().starts_with("tenants/") {
        config.identity.tenant_id().to_owned()
    } else {
        format!("tenants/{}", config.identity.tenant_id())
    };
    let project = config.identity.project_id();
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn project_ref(core: &ClientCore) -> ResourceRef {
    ResourceRef {
        resource_type: "project".to_owned(),
        resource_id: core.config.identity.project_id().to_owned(),
        tenant_id: core.config.identity.tenant_id().to_owned(),
        project_id: core.config.identity.project_id().to_owned(),
        name: project_name(core),
        ..ResourceRef::default()
    }
}

fn model_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    scoped_name(core, name, false)
}
fn release_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    scoped_name(core, name, true)
}

fn scoped_name(core: &ClientCore, name: &str, release: bool) -> Result<String, Error> {
    let prefix = format!("{}/models/", project_name(core));
    let suffix = name
        .strip_prefix(&prefix)
        .ok_or_else(|| Error::invalid_argument("resource is outside the configured project"))?;
    let valid = if release {
        let mut parts = suffix.split("/releases/");
        matches!((parts.next(), parts.next(), parts.next()), (Some(left), Some(right), None) if !left.is_empty() && !right.is_empty() && !left.contains('/') && !right.contains('/'))
    } else {
        !suffix.is_empty() && !suffix.contains('/')
    };
    if !valid {
        return Err(Error::invalid_argument("resource name is invalid"));
    }
    Ok(name.to_owned())
}

fn normalize_reference(
    core: &ClientCore,
    reference: &mut ResourceRef,
    resource_type: &str,
    release: bool,
) -> Result<(), Error> {
    let name = if release {
        release_name(core, &reference.name)?
    } else {
        model_name(core, &reference.name)?
    };
    let resource_id = name
        .rsplit('/')
        .next()
        .ok_or_else(|| Error::invalid_argument("resource reference name is invalid"))?;
    if (!reference.resource_type.is_empty() && reference.resource_type != resource_type)
        || (!reference.resource_id.is_empty() && reference.resource_id != resource_id)
        || (!reference.tenant_id.is_empty()
            && reference.tenant_id != core.config.identity.tenant_id())
        || (!reference.project_id.is_empty()
            && reference.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "resource reference does not match the configured project",
        ));
    }
    reference.resource_type.clear();
    reference.resource_type.push_str(resource_type);
    reference.resource_id.clear();
    reference.resource_id.push_str(resource_id);
    reference.tenant_id.clear();
    reference
        .tenant_id
        .push_str(core.config.identity.tenant_id());
    reference.project_id.clear();
    reference
        .project_id
        .push_str(core.config.identity.project_id());
    Ok(())
}

fn validate_page(page: Option<&mindclade_protocols::common::v1::PageRequest>) -> Result<(), Error> {
    if page.is_some_and(|value| value.page_size > 1000) {
        return Err(Error::invalid_argument("page size cannot exceed 1000"));
    }
    Ok(())
}

fn require_operation(operation: Option<Operation>, method: &str) -> Result<Operation, Error> {
    let value = operation
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its operation")))?;
    if value.operation_id.trim().is_empty() {
        return Err(Error::protocol(format!(
            "{method} response operation has no identity"
        )));
    }
    Ok(value)
}
