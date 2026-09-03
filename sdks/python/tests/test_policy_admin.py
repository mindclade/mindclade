from __future__ import annotations

import copy
import unittest
from datetime import UTC, datetime, timedelta
from typing import cast

from google.protobuf.field_mask_pb2 import FieldMask
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.admin.v1 import audit_query_pb2, project_pb2, tenant_pb2
from mindclade.common.v1 import command_context_pb2, resource_reference_pb2
from mindclade.internal.admin.v1 import admin_service_pb2
from mindclade.internal.policy.v1 import policy_service_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.policy.v1 import authorization_decision_pb2, policy_reference_pb2, use_policy_pb2
from mindclade_internal_sdk import AsyncClient, CallOptions, Client, ClientConfig, Environment
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    ACTIVATE_USE_POLICY,
    CREATE_PROJECT,
    CREATE_USE_POLICY,
    EVALUATE_AUTHORIZATION,
    EXPORT_AUDIT_RECORDS,
    GET_AUDIT_EXPORT,
    GET_PROJECT,
    GET_TENANT,
    GET_USE_POLICY,
    LIST_PROJECTS,
    LIST_USE_POLICIES,
    QUERY_AUDIT_RECORDS,
    RESOLVE_POLICY_SNAPSHOT,
    REVOKE_USE_POLICY,
    UPDATE_PROJECT,
    UPDATE_TENANT,
    UPDATE_USE_POLICY,
    Metadata,
)


def config() -> ClientConfig:
    return ClientConfig(
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        tenant_id="tenant-a",
        project_id="project-a",
        principal_id="principal-a",
        insecure_for_testing=True,
    )


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def operation(label: str) -> operation_pb2.Operation:
    return operation_pb2.Operation(operation_id=f"operations/{label}")


class PolicyAdminFacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeSyncTransport()
        self.requests: dict[str, list[Message]] = {}

        def handler(method: str, response: Message):
            def invoke(request: Message, timeout: float, metadata: Metadata) -> Message:
                del timeout, metadata
                self.requests.setdefault(method, []).append(copy.deepcopy(request))
                return response

            return invoke

        self.transport.unary_handlers.update(
            {
                EVALUATE_AUTHORIZATION: handler(
                    EVALUATE_AUTHORIZATION,
                    policy_service_pb2.EvaluateAuthorizationResponse(
                        decision=authorization_decision_pb2.AuthorizationDecision(
                            name="decisions/decision-a",
                            outcome=authorization_decision_pb2.AUTHORIZATION_OUTCOME_DENY,
                        )
                    ),
                ),
                CREATE_USE_POLICY: handler(
                    CREATE_USE_POLICY,
                    policy_service_pb2.CreateUsePolicyResponse(
                        operation=operation("create-policy")
                    ),
                ),
                UPDATE_USE_POLICY: handler(
                    UPDATE_USE_POLICY,
                    policy_service_pb2.UpdateUsePolicyResponse(
                        operation=operation("update-policy")
                    ),
                ),
                GET_USE_POLICY: handler(
                    GET_USE_POLICY,
                    policy_service_pb2.GetUsePolicyResponse(
                        use_policy=use_policy_pb2.UsePolicy(name=self.policy_name)
                    ),
                ),
                LIST_USE_POLICIES: handler(
                    LIST_USE_POLICIES,
                    policy_service_pb2.ListUsePoliciesResponse(
                        use_policies=[use_policy_pb2.UsePolicy(name=self.policy_name)]
                    ),
                ),
                ACTIVATE_USE_POLICY: handler(
                    ACTIVATE_USE_POLICY,
                    policy_service_pb2.ActivateUsePolicyResponse(
                        operation=operation("activate-policy")
                    ),
                ),
                REVOKE_USE_POLICY: handler(
                    REVOKE_USE_POLICY,
                    policy_service_pb2.RevokeUsePolicyResponse(
                        operation=operation("revoke-policy")
                    ),
                ),
                RESOLVE_POLICY_SNAPSHOT: handler(
                    RESOLVE_POLICY_SNAPSHOT,
                    policy_service_pb2.ResolvePolicySnapshotResponse(
                        policy_snapshot=policy_reference_pb2.PolicyReference(
                            name=self.policy_name, digest="sha256:" + "a" * 64
                        )
                    ),
                ),
                GET_TENANT: handler(
                    GET_TENANT,
                    admin_service_pb2.GetTenantResponse(
                        tenant=tenant_pb2.Tenant(name=self.tenant_name)
                    ),
                ),
                UPDATE_TENANT: handler(
                    UPDATE_TENANT,
                    admin_service_pb2.UpdateTenantResponse(operation=operation("update-tenant")),
                ),
                CREATE_PROJECT: handler(
                    CREATE_PROJECT,
                    admin_service_pb2.CreateProjectResponse(operation=operation("create-project")),
                ),
                GET_PROJECT: handler(
                    GET_PROJECT,
                    admin_service_pb2.GetProjectResponse(
                        project=project_pb2.Project(name=self.project_name)
                    ),
                ),
                LIST_PROJECTS: handler(
                    LIST_PROJECTS,
                    admin_service_pb2.ListProjectsResponse(
                        projects=[project_pb2.Project(name=self.project_name)]
                    ),
                ),
                UPDATE_PROJECT: handler(
                    UPDATE_PROJECT,
                    admin_service_pb2.UpdateProjectResponse(operation=operation("update-project")),
                ),
                QUERY_AUDIT_RECORDS: handler(
                    QUERY_AUDIT_RECORDS,
                    admin_service_pb2.QueryAuditRecordsResponse(
                        result=audit_query_pb2.AuditQueryPage(
                            records=[audit_query_pb2.AuditRecord(event_id="event-a")]
                        )
                    ),
                ),
                EXPORT_AUDIT_RECORDS: handler(
                    EXPORT_AUDIT_RECORDS,
                    admin_service_pb2.ExportAuditRecordsResponse(
                        operation=operation("export-audit")
                    ),
                ),
                GET_AUDIT_EXPORT: handler(
                    GET_AUDIT_EXPORT,
                    admin_service_pb2.GetAuditExportResponse(
                        audit_export=audit_query_pb2.AuditExport(name=self.export_name)
                    ),
                ),
            }
        )
        self.client = Client(config(), transport=self.transport)

    @property
    def tenant_name(self) -> str:
        return "tenants/tenant-a"

    @property
    def project_name(self) -> str:
        return f"{self.tenant_name}/projects/project-a"

    @property
    def policy_name(self) -> str:
        return f"{self.project_name}/usePolicies/safe"

    @property
    def export_name(self) -> str:
        return f"{self.project_name}/auditExports/export-a"

    def audit_query(self) -> audit_query_pb2.AuditQuery:
        now = datetime.now(UTC)
        return audit_query_pb2.AuditQuery(
            parent=self.project_name,
            start_time=timestamp(now - timedelta(hours=1)),
            end_time=timestamp(now),
        )

    def test_policy_surface_uses_generated_values_and_authoritative_context(self) -> None:
        caller = policy_service_pb2.CreateUsePolicyRequest(
            context=command_context_pb2.CommandContext(
                tenant_id="attacker", idempotency_key="stable-key"
            ),
            use_policy_id="safe",
            use_policy=use_policy_pb2.UsePolicy(display_name="Safe"),
        )
        caller_copy = copy.deepcopy(caller)
        self.client.policies.create(caller)
        self.client.policies.update(
            policy_service_pb2.UpdateUsePolicyRequest(
                use_policy=use_policy_pb2.UsePolicy(name=self.policy_name),
                update_mask=FieldMask(paths=["display_name"]),
                etag="etag-a",
            )
        )
        self.client.policies.get(self.policy_name)
        self.assertEqual(len(self.client.policies.list().use_policies), 1)
        self.client.policies.activate(self.policy_name, "etag-a")
        self.client.policies.revoke(self.policy_name, "etag-b", "WITHDRAWN")
        self.client.policies.resolve_snapshot(self.policy_name, timestamp(datetime.now(UTC)))
        decision = self.client.policies.evaluate(
            policy_service_pb2.EvaluateAuthorizationRequest(
                action="model.read",
                resource=resource_reference_pb2.ResourceRef(
                    name=f"{self.project_name}/models/model-a"
                ),
                intent_digest="sha256:" + "b" * 64,
            )
        )
        self.assertEqual(decision.outcome, authorization_decision_pb2.AUTHORIZATION_OUTCOME_DENY)
        self.assertEqual(caller, caller_copy)
        received = self.requests[CREATE_USE_POLICY][0]
        assert isinstance(received, policy_service_pb2.CreateUsePolicyRequest)
        self.assertEqual(received.parent, self.project_name)
        self.assertEqual(received.context.tenant_id, "tenant-a")
        self.assertEqual(received.context.project_id, "project-a")
        self.assertEqual(received.context.principal_id, "principal-a")
        self.assertRegex(received.context.canonical_request_digest, r"^sha256:[0-9a-f]{64}$")

    def test_admin_surface_scopes_tenant_project_and_audit(self) -> None:
        self.client.admin.get_tenant(self.tenant_name)
        self.client.admin.update_tenant(
            admin_service_pb2.UpdateTenantRequest(
                tenant=tenant_pb2.Tenant(name=self.tenant_name),
                update_mask=FieldMask(paths=["display_name"]),
                etag="tenant-etag",
            )
        )
        self.client.admin.create_project(
            admin_service_pb2.CreateProjectRequest(
                project=project_pb2.Project(display_name="Project", purpose="research")
            )
        )
        self.client.admin.get_project(self.project_name)
        self.assertEqual(len(self.client.admin.list_projects().projects), 1)
        self.client.admin.update_project(
            admin_service_pb2.UpdateProjectRequest(
                project=project_pb2.Project(name=self.project_name),
                update_mask=FieldMask(paths=["display_name"]),
                etag="project-etag",
            )
        )
        query = self.audit_query()
        self.assertEqual(len(self.client.admin.query_audit(query).records), 1)
        self.client.admin.export_audit(query, options=CallOptions(idempotency_key="audit-key"))
        self.client.admin.get_audit_export(self.export_name)
        tenant_update = self.requests[UPDATE_TENANT][0]
        project_create = self.requests[CREATE_PROJECT][0]
        assert isinstance(tenant_update, admin_service_pb2.UpdateTenantRequest)
        assert isinstance(project_create, admin_service_pb2.CreateProjectRequest)
        self.assertEqual(tenant_update.context.project_id, "")
        self.assertRegex(tenant_update.context.canonical_request_digest, r"^sha256:")
        self.assertEqual(project_create.parent, self.tenant_name)
        self.assertEqual(project_create.project_id, "project-a")
        self.assertEqual(project_create.project.tenant.name, self.tenant_name)

    def test_scope_and_page_validation_happen_before_transport(self) -> None:
        with self.assertRaisesRegex(ValueError, "configured project"):
            self.client.policies.get("tenants/other/projects/other/usePolicies/bad")
        with self.assertRaisesRegex(ValueError, "page size"):
            self.client.admin.list_projects(
                admin_service_pb2.ListProjectsRequest(page={"page_size": 1001})
            )


class AsyncPolicyAdminFacadeTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_facades_share_authoritative_generated_pipeline(self) -> None:
        transport = FakeAsyncTransport()
        captured: list[Message] = []

        def evaluate(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            captured.append(copy.deepcopy(request))
            return policy_service_pb2.EvaluateAuthorizationResponse(
                decision=authorization_decision_pb2.AuthorizationDecision(
                    outcome=authorization_decision_pb2.AUTHORIZATION_OUTCOME_DENY
                )
            )

        def update_tenant(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            captured.append(copy.deepcopy(request))
            return admin_service_pb2.UpdateTenantResponse(operation=operation("tenant"))

        transport.unary_handlers[EVALUATE_AUTHORIZATION] = evaluate
        transport.unary_handlers[UPDATE_TENANT] = update_tenant
        client = AsyncClient(config(), transport=transport)
        project = "tenants/tenant-a/projects/project-a"
        await client.policies.evaluate(
            policy_service_pb2.EvaluateAuthorizationRequest(
                action="model.read",
                resource=resource_reference_pb2.ResourceRef(name=f"{project}/models/model-a"),
                intent_digest="sha256:" + "b" * 64,
            )
        )
        await client.admin.update_tenant(
            admin_service_pb2.UpdateTenantRequest(
                tenant=tenant_pb2.Tenant(name="tenants/tenant-a"),
                update_mask=FieldMask(paths=["display_name"]),
                etag="etag",
            )
        )
        self.assertEqual(len(captured), 2)
        evaluation_request = cast(policy_service_pb2.EvaluateAuthorizationRequest, captured[0])
        tenant_request = cast(admin_service_pb2.UpdateTenantRequest, captured[1])
        self.assertEqual(evaluation_request.context.principal_id, "principal-a")
        self.assertEqual(tenant_request.context.project_id, "")
        await client.close()


if __name__ == "__main__":
    unittest.main()
