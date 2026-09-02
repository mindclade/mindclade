use std::sync::Arc;

use mindclade_protocols::{
    common::v1::ResourceRef,
    dataset::v1::{
        CreateDatasetCommand, Dataset, DatasetRelease, PublishDatasetReleaseCommand,
        RevokeDatasetReleaseCommand, UpdateDatasetCommand,
    },
    internal::dataset::v1::{
        CreateDatasetRequest, GetDatasetReleaseRequest, GetDatasetRequest,
        ListDatasetReleasesRequest, ListDatasetsRequest, PublishDatasetReleaseRequest,
        RevokeDatasetReleaseRequest, UpdateDatasetRequest,
    },
    job::v1::Operation,
};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_safety,
};

const CREATE: &str = "/mindclade.internal.dataset.v1.DatasetService/CreateDataset";
const GET: &str = "/mindclade.internal.dataset.v1.DatasetService/GetDataset";
const LIST: &str = "/mindclade.internal.dataset.v1.DatasetService/ListDatasets";
const UPDATE: &str = "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset";
const PUBLISH: &str = "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease";
const REVOKE: &str = "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease";
const GET_RELEASE: &str = "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease";
const LIST_RELEASES: &str = "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases";

/// Private Dataset lifecycle API backed exclusively by generated contracts.
#[derive(Clone)]
pub struct Datasets {
    core: Arc<ClientCore>,
}

impl Datasets {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Creates a dataset and returns its durable generated operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, command metadata, credentials, transport failure, or a malformed response.
    pub async fn create(
        &self,
        mut command: CreateDatasetCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let expected = project_name(&self.core);
        match &command.project {
            Some(project) if project.name != expected => {
                return Err(Error::invalid_argument(
                    "dataset project does not match client scope",
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
                CreateDatasetRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_dataset(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CreateDataset")
    }

    /// Gets one generated dataset resource in the configured project.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, credentials, transport failure, or a malformed response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Dataset, Error> {
        let name = dataset_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetDatasetRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET),
                None,
                |transport, request| Box::pin(async move { transport.get_dataset(request).await }),
            )
            .await?
            .into_inner();
        response
            .dataset
            .ok_or_else(|| Error::protocol("GetDataset response omitted its dataset"))
    }

    /// Lists one bounded page of generated dataset resources.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials, or transport failure.
    pub fn list(
        &self,
        mut request: ListDatasetsRequest,
        options: CallOptions,
    ) -> Result<Pages<Dataset>, Error> {
        let parent = project_name(&self.core);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "dataset list parent does not match client scope",
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
                            registered_method_safety(LIST),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_datasets(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.datasets,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Applies a generated optimistic dataset update command.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or command metadata, credentials, transport failure, or a malformed response.
    pub async fn update(
        &self,
        mut command: UpdateDatasetCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        dataset_name(
            &self.core,
            &command
                .dataset
                .as_ref()
                .ok_or_else(|| Error::invalid_argument("update requires a dataset"))?
                .name,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                UpdateDatasetRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(UPDATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.update_dataset(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "UpdateDataset")
    }

    /// Publishes an immutable dataset release through a durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid reference or command, credentials, transport failure, or a malformed response.
    pub async fn publish_release(
        &self,
        mut command: PublishDatasetReleaseCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_reference(
            &self.core,
            command.dataset.as_mut().ok_or_else(|| {
                Error::invalid_argument("publication requires a dataset reference")
            })?,
            "dataset",
            false,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                PublishDatasetReleaseRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(PUBLISH),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.publish_dataset_release(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "PublishDatasetRelease")
    }

    /// Records a non-destructive dataset release revocation.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid reference or command, credentials, transport failure, or a malformed response.
    pub async fn revoke_release(
        &self,
        mut command: RevokeDatasetReleaseCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_reference(
            &self.core,
            command.dataset_release.as_mut().ok_or_else(|| {
                Error::invalid_argument("revocation requires a dataset release reference")
            })?,
            "dataset_release",
            true,
        )?;
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(prepared.command_context(&self.core.config, &options)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                RevokeDatasetReleaseRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(REVOKE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.revoke_dataset_release(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "RevokeDatasetRelease")
    }

    /// Gets one generated immutable dataset release.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, credentials, transport failure, or a malformed response.
    pub async fn get_release(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<DatasetRelease, Error> {
        let name = dataset_release_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetDatasetReleaseRequest { name },
                &prepared,
                registered_method_safety(GET_RELEASE),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_dataset_release(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .dataset_release
            .ok_or_else(|| Error::protocol("GetDatasetRelease response omitted its release"))
    }

    /// Lists one bounded page of releases under a generated dataset name.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials, or transport failure.
    pub fn list_releases(
        &self,
        request: ListDatasetReleasesRequest,
        options: CallOptions,
    ) -> Result<Pages<DatasetRelease>, Error> {
        dataset_name(&self.core, &request.parent)?;
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
                            registered_method_safety(LIST_RELEASES),
                            None,
                            |transport, request| {
                                Box::pin(
                                    async move { transport.list_dataset_releases(request).await },
                                )
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.dataset_releases,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
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

fn dataset_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    scoped_name(core, name, "datasets", false)
}

fn dataset_release_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    scoped_name(core, name, "datasets", true)
}

fn scoped_name(
    core: &ClientCore,
    name: &str,
    collection: &str,
    release: bool,
) -> Result<String, Error> {
    let prefix = format!("{}/{collection}/", project_name(core));
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
        dataset_release_name(core, &reference.name)?
    } else {
        dataset_name(core, &reference.name)?
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
