"""Private tenant, project, and payload-minimized audit façade."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import cast

from mindclade.admin.v1 import audit_query_pb2, project_pb2, tenant_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.admin.v1 import admin_service_pb2
from mindclade.job.v1 import operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .transport import (
    CREATE_PROJECT,
    EXPORT_AUDIT_RECORDS,
    GET_AUDIT_EXPORT,
    GET_PROJECT,
    GET_TENANT,
    LIST_PROJECTS,
    QUERY_AUDIT_RECORDS,
    UPDATE_PROJECT,
    UPDATE_TENANT,
)


def _tenant(invoker: SyncInvoker | AsyncInvoker) -> str:
    value = invoker.config.tenant_id
    return value if value.startswith("tenants/") else f"tenants/{value}"


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _project_id(invoker: SyncInvoker | AsyncInvoker) -> str:
    return _project(invoker).rsplit("/", 1)[-1]


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_mutation[
    RequestT: (
        admin_service_pb2.UpdateTenantRequest,
        admin_service_pb2.CreateProjectRequest,
        admin_service_pb2.UpdateProjectRequest,
        admin_service_pb2.ExportAuditRecordsRequest,
    )
](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
    *,
    project_id: str,
) -> tuple[RequestT, PreparedCall]:
    materialized = copy.deepcopy(request)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    authoritative = command_context(
        invoker.config, call, request_digest=canonical_digest(materialized)
    )
    authoritative.project_id = project_id
    materialized.context.CopyFrom(authoritative)
    return materialized, call


def _operation(response: object, label: str) -> operation_pb2.Operation:
    operation = required_response_message(
        cast(admin_service_pb2.UpdateTenantResponse, response),
        "operation",
        operation_pb2.Operation,
        label=label,
    )
    required_text("operation id", operation.operation_id)
    return operation


def _normalize_tenant_reference(
    invoker: SyncInvoker | AsyncInvoker, reference: resource_reference_pb2.ResourceRef
) -> None:
    tenant = _tenant(invoker)
    tenant_id = tenant.rsplit("/", 1)[-1]
    config = invoker.config
    if (
        reference.name != tenant
        or reference.resource_type not in ("", "tenant")
        or reference.resource_id not in ("", tenant_id)
        or reference.tenant_id not in ("", config.tenant_id)
    ):
        raise ValueError("project tenant reference conflicts with the configured tenant")
    reference.resource_type = "tenant"
    reference.resource_id = tenant_id
    reference.tenant_id = config.tenant_id
    reference.project_id = ""


def _validate_audit_query(
    invoker: SyncInvoker | AsyncInvoker, query: audit_query_pb2.AuditQuery
) -> audit_query_pb2.AuditQuery:
    materialized = copy.deepcopy(query)
    if not materialized.HasField("start_time") or not materialized.HasField("end_time"):
        raise ValueError("audit query requires a bounded time range")
    if materialized.end_time.ToDatetime() <= materialized.start_time.ToDatetime():
        raise ValueError("audit query end_time must follow start_time")
    if materialized.parent not in (_tenant(invoker), _project(invoker)):
        raise ValueError("audit query parent must match the configured tenant or project")
    if materialized.HasField("page") and materialized.page.page_size > 1000:
        raise ValueError("audit page size cannot exceed 1000")
    config = invoker.config
    project = _project(invoker)
    for resource in materialized.resources:
        if resource.name != project and not resource.name.startswith(f"{project}/"):
            raise ValueError("audit resource is outside the configured project")
        if resource.tenant_id not in ("", config.tenant_id) or resource.project_id not in (
            "",
            config.project_id,
        ):
            raise ValueError("audit resource scope conflicts with client identity")
        resource.tenant_id = config.tenant_id
        resource.project_id = config.project_id
    return materialized


class Admin:
    """Synchronous generated-type-only administration API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def get_tenant(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> tenant_pb2.Tenant:
        if required_text("tenant name", name) != _tenant(self._invoker):
            raise ValueError("tenant name must match the configured tenant")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetTenantResponse,
            self._invoker.unary(
                GET_TENANT,
                admin_service_pb2.GetTenantRequest(name=name, if_none_match=if_none_match.strip()),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(response, "tenant", tenant_pb2.Tenant, label="tenant get")

    def update_tenant(
        self,
        request: admin_service_pb2.UpdateTenantRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("tenant")
            or request.tenant.name != _tenant(self._invoker)
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("tenant update requires the configured tenant, field mask, and etag")
        materialized, call = _prepare_mutation(self._invoker, request, options, project_id="")
        return _operation(
            self._invoker.unary(UPDATE_TENANT, materialized, call=call, retry_safe=True),
            "tenant update",
        )

    def create_project(
        self,
        request: admin_service_pb2.CreateProjectRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        if not materialized.HasField("project") or materialized.project_id not in (
            "",
            _project_id(self._invoker),
        ):
            raise ValueError("project create requires the configured project")
        if materialized.parent not in ("", _tenant(self._invoker)):
            raise ValueError("project parent must match the configured tenant")
        materialized.parent = _tenant(self._invoker)
        materialized.project_id = _project_id(self._invoker)
        if materialized.project.HasField("tenant"):
            _normalize_tenant_reference(self._invoker, materialized.project.tenant)
        else:
            materialized.project.tenant.CopyFrom(
                resource_reference_pb2.ResourceRef(name=_tenant(self._invoker))
            )
            _normalize_tenant_reference(self._invoker, materialized.project.tenant)
        materialized, call = _prepare_mutation(
            self._invoker,
            materialized,
            options,
            project_id=self._invoker.config.project_id,
        )
        return _operation(
            self._invoker.unary(CREATE_PROJECT, materialized, call=call, retry_safe=True),
            "project create",
        )

    def get_project(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> project_pb2.Project:
        if required_text("project name", name) != _project(self._invoker):
            raise ValueError("project name must match the configured project")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetProjectResponse,
            self._invoker.unary(
                GET_PROJECT,
                admin_service_pb2.GetProjectRequest(name=name, if_none_match=if_none_match.strip()),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "project", project_pb2.Project, label="project get"
        )

    def list_projects(
        self,
        request: admin_service_pb2.ListProjectsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> admin_service_pb2.ListProjectsResponse:
        materialized = admin_service_pb2.ListProjectsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        if materialized.parent not in ("", _tenant(self._invoker)):
            raise ValueError("project list parent must match the configured tenant")
        materialized.parent = _tenant(self._invoker)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("project page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            admin_service_pb2.ListProjectsResponse,
            self._invoker.unary(LIST_PROJECTS, materialized, call=call, retry_safe=True),
        )

    def update_project(
        self,
        request: admin_service_pb2.UpdateProjectRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("project")
            or request.project.name != _project(self._invoker)
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("project update requires the configured project, field mask, and etag")
        materialized, call = _prepare_mutation(
            self._invoker,
            request,
            options,
            project_id=self._invoker.config.project_id,
        )
        return _operation(
            self._invoker.unary(UPDATE_PROJECT, materialized, call=call, retry_safe=True),
            "project update",
        )

    def query_audit(
        self,
        query: audit_query_pb2.AuditQuery,
        *,
        options: CallOptions | None = None,
    ) -> audit_query_pb2.AuditQueryPage:
        materialized = _validate_audit_query(self._invoker, query)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.QueryAuditRecordsResponse,
            self._invoker.unary(
                QUERY_AUDIT_RECORDS,
                admin_service_pb2.QueryAuditRecordsRequest(query=materialized),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "result", audit_query_pb2.AuditQueryPage, label="audit query"
        )

    def export_audit(
        self,
        query: audit_query_pb2.AuditQuery,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = _validate_audit_query(self._invoker, query)
        project_id = (
            "" if materialized.parent == _tenant(self._invoker) else self._invoker.config.project_id
        )
        request, call = _prepare_mutation(
            self._invoker,
            admin_service_pb2.ExportAuditRecordsRequest(query=materialized),
            options,
            project_id=project_id,
        )
        return _operation(
            self._invoker.unary(EXPORT_AUDIT_RECORDS, request, call=call, retry_safe=True),
            "audit export",
        )

    def get_audit_export(
        self, name: str, *, options: CallOptions | None = None
    ) -> audit_query_pb2.AuditExport:
        prefix = f"{_project(self._invoker)}/auditExports/"
        if (
            not name.startswith(prefix)
            or not name.removeprefix(prefix)
            or "/" in name.removeprefix(prefix)
        ):
            raise ValueError("audit export name must match the configured project")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetAuditExportResponse,
            self._invoker.unary(
                GET_AUDIT_EXPORT,
                admin_service_pb2.GetAuditExportRequest(name=name),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "audit_export", audit_query_pb2.AuditExport, label="audit export get"
        )


class AsyncAdmin:
    """Asyncio variant of the generated-type-only administration API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def get_tenant(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> tenant_pb2.Tenant:
        if required_text("tenant name", name) != _tenant(self._invoker):
            raise ValueError("tenant name must match the configured tenant")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetTenantResponse,
            await self._invoker.unary(
                GET_TENANT,
                admin_service_pb2.GetTenantRequest(name=name, if_none_match=if_none_match.strip()),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(response, "tenant", tenant_pb2.Tenant, label="tenant get")

    async def update_tenant(
        self, request: admin_service_pb2.UpdateTenantRequest, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("tenant")
            or request.tenant.name != _tenant(self._invoker)
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("tenant update requires the configured tenant, field mask, and etag")
        materialized, call = _prepare_mutation(self._invoker, request, options, project_id="")
        return _operation(
            await self._invoker.unary(UPDATE_TENANT, materialized, call=call, retry_safe=True),
            "tenant update",
        )

    async def create_project(
        self, request: admin_service_pb2.CreateProjectRequest, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        if not materialized.HasField("project") or materialized.project_id not in (
            "",
            _project_id(self._invoker),
        ):
            raise ValueError("project create requires the configured project")
        if materialized.parent not in ("", _tenant(self._invoker)):
            raise ValueError("project parent must match the configured tenant")
        materialized.parent, materialized.project_id = (
            _tenant(self._invoker),
            _project_id(self._invoker),
        )
        if not materialized.project.HasField("tenant"):
            materialized.project.tenant.CopyFrom(
                resource_reference_pb2.ResourceRef(name=_tenant(self._invoker))
            )
        _normalize_tenant_reference(self._invoker, materialized.project.tenant)
        materialized, call = _prepare_mutation(
            self._invoker, materialized, options, project_id=self._invoker.config.project_id
        )
        return _operation(
            await self._invoker.unary(CREATE_PROJECT, materialized, call=call, retry_safe=True),
            "project create",
        )

    async def get_project(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> project_pb2.Project:
        if required_text("project name", name) != _project(self._invoker):
            raise ValueError("project name must match the configured project")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetProjectResponse,
            await self._invoker.unary(
                GET_PROJECT,
                admin_service_pb2.GetProjectRequest(name=name, if_none_match=if_none_match.strip()),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "project", project_pb2.Project, label="project get"
        )

    async def list_projects(
        self,
        request: admin_service_pb2.ListProjectsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> admin_service_pb2.ListProjectsResponse:
        materialized = admin_service_pb2.ListProjectsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        if materialized.parent not in ("", _tenant(self._invoker)):
            raise ValueError("project list parent must match the configured tenant")
        materialized.parent = _tenant(self._invoker)
        if materialized.HasField("page") and materialized.page.page_size > 1000:
            raise ValueError("project page size cannot exceed 1000")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            admin_service_pb2.ListProjectsResponse,
            await self._invoker.unary(LIST_PROJECTS, materialized, call=call, retry_safe=True),
        )

    async def update_project(
        self, request: admin_service_pb2.UpdateProjectRequest, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        if (
            not request.HasField("project")
            or request.project.name != _project(self._invoker)
            or not request.HasField("update_mask")
            or not request.etag.strip()
        ):
            raise ValueError("project update requires the configured project, field mask, and etag")
        materialized, call = _prepare_mutation(
            self._invoker, request, options, project_id=self._invoker.config.project_id
        )
        return _operation(
            await self._invoker.unary(UPDATE_PROJECT, materialized, call=call, retry_safe=True),
            "project update",
        )

    async def query_audit(
        self, query: audit_query_pb2.AuditQuery, *, options: CallOptions | None = None
    ) -> audit_query_pb2.AuditQueryPage:
        materialized = _validate_audit_query(self._invoker, query)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.QueryAuditRecordsResponse,
            await self._invoker.unary(
                QUERY_AUDIT_RECORDS,
                admin_service_pb2.QueryAuditRecordsRequest(query=materialized),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "result", audit_query_pb2.AuditQueryPage, label="audit query"
        )

    async def export_audit(
        self, query: audit_query_pb2.AuditQuery, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        materialized = _validate_audit_query(self._invoker, query)
        project_id = (
            "" if materialized.parent == _tenant(self._invoker) else self._invoker.config.project_id
        )
        request, call = _prepare_mutation(
            self._invoker,
            admin_service_pb2.ExportAuditRecordsRequest(query=materialized),
            options,
            project_id=project_id,
        )
        return _operation(
            await self._invoker.unary(EXPORT_AUDIT_RECORDS, request, call=call, retry_safe=True),
            "audit export",
        )

    async def get_audit_export(
        self, name: str, *, options: CallOptions | None = None
    ) -> audit_query_pb2.AuditExport:
        prefix = f"{_project(self._invoker)}/auditExports/"
        if (
            not name.startswith(prefix)
            or not name.removeprefix(prefix)
            or "/" in name.removeprefix(prefix)
        ):
            raise ValueError("audit export name must match the configured project")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = cast(
            admin_service_pb2.GetAuditExportResponse,
            await self._invoker.unary(
                GET_AUDIT_EXPORT,
                admin_service_pb2.GetAuditExportRequest(name=name),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "audit_export", audit_query_pb2.AuditExport, label="audit export get"
        )
