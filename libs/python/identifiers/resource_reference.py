from __future__ import annotations

from common.v1.resource_reference_pb2 import ResourceRef as ResourceRef

from .resource_id import Identifier, ResourceVersion


def _identifier_value(value: Identifier | str) -> str:
    return value.to_proto() if isinstance(value, Identifier) else value


def _version_value(value: ResourceVersion | int) -> int:
    return value.to_proto() if isinstance(value, ResourceVersion) else ResourceVersion(value).value


def canonical_resource_name(
    *,
    tenant_id: Identifier | str,
    project_id: Identifier | str,
    resource_type: str,
    resource_id: Identifier | str,
) -> str:
    """Construct the canonical project-scoped resource name from validated parts."""
    tenant = _identifier_value(tenant_id)
    project = _identifier_value(project_id)
    identifier = _identifier_value(resource_id)
    if not tenant or not project or not resource_type or not identifier:
        raise ValueError("resource identity fields are required")
    return f"tenants/{tenant}/projects/{project}/{resource_type}/{identifier}"


def make_resource_ref(
    *,
    tenant_id: Identifier | str,
    project_id: Identifier | str,
    resource_type: str,
    resource_id: Identifier | str,
    resource_version: ResourceVersion | int,
    name: str | None = None,
    etag: str = "",
) -> ResourceRef:
    """Build the authoritative generated resource reference with local validation."""
    canonical_name = canonical_resource_name(
        tenant_id=tenant_id,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if name is not None and name != canonical_name:
        raise ValueError("name does not match resource identity")
    return ResourceRef(
        resource_type=resource_type,
        resource_id=_identifier_value(resource_id),
        tenant_id=_identifier_value(tenant_id),
        project_id=_identifier_value(project_id),
        resource_version=_version_value(resource_version),
        name=canonical_name,
        etag=etag,
    )


def resource_key(reference: ResourceRef) -> str:
    """Return a version-qualified key without modifying the generated message class."""
    canonical_name = canonical_resource_name(
        tenant_id=reference.tenant_id,
        project_id=reference.project_id,
        resource_type=reference.resource_type,
        resource_id=reference.resource_id,
    )
    if reference.name and reference.name != canonical_name:
        raise ValueError("name does not match resource identity")
    ResourceVersion.from_proto(reference.resource_version)
    return f"{canonical_name}@{reference.resource_version}"
