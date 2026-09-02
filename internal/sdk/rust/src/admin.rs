use std::sync::Arc;

use mindclade_protocols::{
    admin::v1::{AuditExport, AuditQuery, AuditQueryPage, Project, Tenant},
    common::v1::{CommandContext, PageRequest, ResourceRef},
    internal::admin::v1::{
        CreateProjectRequest, ExportAuditRecordsRequest, GetAuditExportRequest, GetProjectRequest,
        GetTenantRequest, ListProjectsRequest, ListProjectsResponse, QueryAuditRecordsRequest,
        UpdateProjectRequest, UpdateTenantRequest,
    },
    job::v1::Operation,
};

use crate::{CallOptions, ClientCore, Error, SubmitOptions, retry::registered_method_safety};

const GET_TENANT: &str = "/mindclade.internal.admin.v1.AdminService/GetTenant";
const UPDATE_TENANT: &str = "/mindclade.internal.admin.v1.AdminService/UpdateTenant";
const CREATE_PROJECT: &str = "/mindclade.internal.admin.v1.AdminService/CreateProject";
const GET_PROJECT: &str = "/mindclade.internal.admin.v1.AdminService/GetProject";
const LIST_PROJECTS: &str = "/mindclade.internal.admin.v1.AdminService/ListProjects";
const UPDATE_PROJECT: &str = "/mindclade.internal.admin.v1.AdminService/UpdateProject";
const QUERY_AUDIT: &str = "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords";
const EXPORT_AUDIT: &str = "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords";
const GET_EXPORT: &str = "/mindclade.internal.admin.v1.AdminService/GetAuditExport";

/// Tenant, project, and payload-minimized audit API over generated messages.
#[derive(Clone)]
pub struct Admin {
    core: Arc<ClientCore>,
}

impl Admin {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Reads the configured tenant.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or an incomplete response.
    pub async fn get_tenant(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Tenant, Error> {
        let name = name.into();
        if name != tenant_name(&self.core) {
            return Err(Error::invalid_argument(
                "tenant name does not match client scope",
            ));
        }
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetTenantRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET_TENANT),
                None,
                |transport, request| Box::pin(async move { transport.get_tenant(request).await }),
            )
            .await?
            .into_inner();
        response
            .tenant
            .ok_or_else(|| Error::protocol("GetTenant response omitted its tenant"))
    }

    /// Applies a generated optimistic tenant update.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid concurrency metadata, transport failure, or an incomplete response.
    pub async fn update_tenant(
        &self,
        mut request: UpdateTenantRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        if request.tenant.as_ref().map(|value| value.name.as_str())
            != Some(tenant_name(&self.core).as_str())
            || request.update_mask.is_none()
            || request.etag.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "tenant update requires the configured tenant, a field mask, and etag",
            ));
        }
        request.context = None;
        let response = self
            .mutate(
                request,
                options,
                UPDATE_TENANT,
                Some(""),
                |transport, request| {
                    Box::pin(async move { transport.update_tenant(request).await })
                },
            )
            .await?;
        require_operation(response.operation, "UpdateTenant")
    }

    /// Creates the configured project in the configured tenant.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, transport failure, or an incomplete response.
    pub async fn create_project(
        &self,
        mut request: CreateProjectRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let tenant = tenant_name(&self.core);
        let project_id = configured_project_id(&self.core);
        if (!request.parent.is_empty() && request.parent != tenant)
            || (!request.project_id.is_empty() && request.project_id != project_id)
        {
            return Err(Error::invalid_argument(
                "project creation must target the configured tenant and project",
            ));
        }
        request.parent = tenant;
        request.project_id = project_id;
        let project = request.project.as_mut().ok_or_else(|| {
            Error::invalid_argument("project creation requires a generated project")
        })?;
        if let Some(reference) = project.tenant.as_mut() {
            normalize_tenant_reference(&self.core, reference)?;
        } else {
            project.tenant = Some(tenant_reference(&self.core));
        }
        request.context = None;
        let response = self
            .mutate(
                request,
                options,
                CREATE_PROJECT,
                None,
                |transport, request| {
                    Box::pin(async move { transport.create_project(request).await })
                },
            )
            .await?;
        require_operation(response.operation, "CreateProject")
    }

    /// Reads the configured project.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or an incomplete response.
    pub async fn get_project(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<Project, Error> {
        let name = name.into();
        if name != project_name(&self.core) {
            return Err(Error::invalid_argument(
                "project name does not match client scope",
            ));
        }
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetProjectRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET_PROJECT),
                None,
                |transport, request| Box::pin(async move { transport.get_project(request).await }),
            )
            .await?
            .into_inner();
        response
            .project
            .ok_or_else(|| Error::protocol("GetProject response omitted its project"))
    }

    /// Lists one bounded tenant-scoped project page.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination and for transport failures.
    pub async fn list_projects(
        &self,
        mut request: ListProjectsRequest,
        options: CallOptions,
    ) -> Result<ListProjectsResponse, Error> {
        let parent = tenant_name(&self.core);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "project list parent does not match client scope",
            ));
        }
        validate_page(request.page.as_ref())?;
        request.parent = parent;
        let prepared = options.prepare(&self.core.config);
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST_PROJECTS),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_projects(request).await })
                },
            )
            .await?
            .into_inner())
    }

    /// Applies a generated optimistic project update.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid concurrency metadata, transport failure, or an incomplete response.
    pub async fn update_project(
        &self,
        mut request: UpdateProjectRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        if request.project.as_ref().map(|value| value.name.as_str())
            != Some(project_name(&self.core).as_str())
            || request.update_mask.is_none()
            || request.etag.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "project update requires the configured project, a field mask, and etag",
            ));
        }
        request.context = None;
        let response = self
            .mutate(
                request,
                options,
                UPDATE_PROJECT,
                None,
                |transport, request| {
                    Box::pin(async move { transport.update_project(request).await })
                },
            )
            .await?;
        require_operation(response.operation, "UpdateProject")
    }

    /// Queries one bounded page of payload-minimized audit records.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or time bounds, transport failure, or an incomplete response.
    pub async fn query_audit(
        &self,
        mut query: AuditQuery,
        options: CallOptions,
    ) -> Result<AuditQueryPage, Error> {
        validate_audit_query(&self.core, &mut query)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                QueryAuditRecordsRequest { query: Some(query) },
                &prepared,
                registered_method_safety(QUERY_AUDIT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.query_audit_records(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .result
            .ok_or_else(|| Error::protocol("QueryAuditRecords response omitted its result"))
    }

    /// Starts a durable, policy-controlled audit export.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or time bounds, transport failure, or an incomplete response.
    pub async fn export_audit(
        &self,
        mut query: AuditQuery,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        validate_audit_query(&self.core, &mut query)?;
        let tenant_scope = query.parent == tenant_name(&self.core);
        let request = ExportAuditRecordsRequest {
            context: None,
            query: Some(query),
        };
        let response = self
            .mutate(
                request,
                options,
                EXPORT_AUDIT,
                tenant_scope.then_some(""),
                |transport, request| {
                    Box::pin(async move { transport.export_audit_records(request).await })
                },
            )
            .await?;
        require_operation(response.operation, "ExportAuditRecords")
    }

    /// Reads one protected immutable audit-export resource.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or an incomplete response.
    pub async fn get_audit_export(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<AuditExport, Error> {
        let name = scoped_name(&self.core, &name.into(), "auditExports")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetAuditExportRequest { name },
                &prepared,
                registered_method_safety(GET_EXPORT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_audit_export(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .audit_export
            .ok_or_else(|| Error::protocol("GetAuditExport response omitted its export"))
    }

    async fn mutate<T, R, F>(
        &self,
        mut request: T,
        options: SubmitOptions,
        method: &'static str,
        project_override: Option<&str>,
        invoke: F,
    ) -> Result<R, Error>
    where
        T: AdminCommand + Clone + Send + 'static,
        R: Send + 'static,
        F: Fn(Arc<dyn crate::RpcTransport>, tonic::Request<T>) -> crate::retry::RpcFuture<R>,
    {
        let prepared = options.call.prepare(&self.core.config);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        if let Some(value) = project_override {
            context.project_id = value.to_owned();
        }
        request.set_context(Some(context));
        let key = options.idempotency_key.clone();
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(method),
                Some(&key),
                invoke,
            )
            .await?
            .into_inner())
    }
}

trait AdminCommand {
    fn set_context(&mut self, context: Option<CommandContext>);
}

macro_rules! admin_command {
    ($($value:ty),+ $(,)?) => {$(
        impl AdminCommand for $value {
            fn set_context(&mut self, context: Option<CommandContext>) {
                self.context = context;
            }
        }
    )+};
}

admin_command!(
    UpdateTenantRequest,
    CreateProjectRequest,
    UpdateProjectRequest,
    ExportAuditRecordsRequest,
);

fn tenant_name(core: &ClientCore) -> String {
    let tenant = core.config.identity.tenant_id();
    if tenant.starts_with("tenants/") {
        tenant.to_owned()
    } else {
        format!("tenants/{tenant}")
    }
}

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

fn configured_project_id(core: &ClientCore) -> String {
    project_name(core)
        .rsplit('/')
        .next()
        .unwrap_or_default()
        .to_owned()
}

fn tenant_reference(core: &ClientCore) -> ResourceRef {
    let name = tenant_name(core);
    ResourceRef {
        resource_type: "tenant".to_owned(),
        resource_id: name.rsplit('/').next().unwrap_or_default().to_owned(),
        tenant_id: core.config.identity.tenant_id().to_owned(),
        name,
        ..ResourceRef::default()
    }
}

fn normalize_tenant_reference(core: &ClientCore, reference: &mut ResourceRef) -> Result<(), Error> {
    let expected = tenant_reference(core);
    if reference.name != expected.name
        || (!reference.resource_type.is_empty() && reference.resource_type != "tenant")
        || (!reference.resource_id.is_empty() && reference.resource_id != expected.resource_id)
        || (!reference.tenant_id.is_empty()
            && reference.tenant_id != core.config.identity.tenant_id())
    {
        return Err(Error::invalid_argument(
            "tenant reference conflicts with client identity",
        ));
    }
    *reference = expected;
    Ok(())
}

fn scoped_name(core: &ClientCore, name: &str, collection: &str) -> Result<String, Error> {
    let prefix = format!("{}/{collection}/", project_name(core));
    let id = name
        .strip_prefix(&prefix)
        .ok_or_else(|| Error::invalid_argument("resource is outside the configured project"))?;
    if id.is_empty() || id.contains('/') {
        return Err(Error::invalid_argument("resource name is invalid"));
    }
    Ok(name.to_owned())
}

fn validate_page(page: Option<&PageRequest>) -> Result<(), Error> {
    if page.is_some_and(|value| value.page_size > 1000) {
        return Err(Error::invalid_argument("page size cannot exceed 1000"));
    }
    Ok(())
}

fn validate_audit_query(core: &ClientCore, query: &mut AuditQuery) -> Result<(), Error> {
    let tenant = tenant_name(core);
    let project = project_name(core);
    if query.parent != tenant && query.parent != project {
        return Err(Error::invalid_argument(
            "audit query parent does not match client scope",
        ));
    }
    validate_page(query.page.as_ref())?;
    let start = query
        .start_time
        .as_ref()
        .ok_or_else(|| Error::invalid_argument("audit query requires start time"))?;
    let end = query
        .end_time
        .as_ref()
        .ok_or_else(|| Error::invalid_argument("audit query requires end time"))?;
    if (end.seconds, end.nanos) <= (start.seconds, start.nanos)
        || start.nanos < 0
        || end.nanos < 0
        || start.nanos >= 1_000_000_000
        || end.nanos >= 1_000_000_000
    {
        return Err(Error::invalid_argument("audit query time range is invalid"));
    }
    for resource in &mut query.resources {
        let parent = project_name(core);
        if resource.name != parent && !resource.name.starts_with(&format!("{parent}/")) {
            return Err(Error::invalid_argument(
                "audit resource is outside the configured project",
            ));
        }
        if (!resource.tenant_id.is_empty()
            && resource.tenant_id != core.config.identity.tenant_id())
            || (!resource.project_id.is_empty()
                && resource.project_id != core.config.identity.project_id())
        {
            return Err(Error::invalid_argument(
                "audit resource conflicts with client identity",
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
