from dataclasses import dataclass

from .resource_id import Identifier, ResourceVersion


@dataclass(frozen=True)
class ResourceRef:
    tenant_id: Identifier
    project_id: Identifier
    resource_type: str
    resource_id: Identifier
    resource_version: ResourceVersion

    def key(self):
        return (
            f"{self.tenant_id.value}/{self.project_id.value}/"
            f"{self.resource_type}/{self.resource_id.value}@"
            f"{self.resource_version.value}"
        )
