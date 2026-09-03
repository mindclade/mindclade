from __future__ import annotations

import copy
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2, evidence_reference_pb2
from mindclade.common.v1 import command_context_pb2, pagination_pb2, resource_reference_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import operation_pb2
from mindclade_internal_sdk import AccessToken, AsyncClient, CallOptions, Client, ClientConfig
from mindclade_internal_sdk._invocation import canonical_digest
from mindclade_internal_sdk.config import RetryPolicy
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    ACQUIRE_ARTIFACT_LEASE,
    CANCEL_OPERATION,
    GET_ARTIFACT,
    LIST_ARTIFACTS,
    LIST_OPERATIONS,
    QUARANTINE_ARTIFACT,
    RELEASE_ARTIFACT_LEASE,
    Metadata,
)

UnaryHandler = Callable[[Message, float, Metadata], Message]
SeenCall = tuple[str, Message, Metadata]


class _CommandContextCarrier(Protocol):
    context: command_context_pb2.CommandContext


class _SyncCredentials:
    def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken("test-token", datetime.now(UTC) + timedelta(minutes=5))


class _AsyncCredentials:
    async def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken("test-token", datetime.now(UTC) + timedelta(minutes=5))


def _config(*, asynchronous: bool) -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        token_provider=_AsyncCredentials() if asynchronous else _SyncCredentials(),
        retry=RetryPolicy(max_attempts=1, base_delay=0.001, max_delay=0.001),
    )


def _timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def _artifact() -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + "a" * 64,
        integrity_digest="sha256:" + "a" * 64,
        media_type="application/octet-stream",
        size_bytes=7,
    )


def _lease(parent: str) -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(
        resource_type="artifact_lease",
        resource_id="lease-1",
        tenant_id="tenant-1",
        project_id="project-1",
        resource_version=1,
        name=f"{parent}/artifactLeases/lease-1",
        etag="lease-etag-1",
    )


def _operation(parent: str) -> operation_pb2.Operation:
    return operation_pb2.Operation(
        operation_id=f"{parent}/operations/op-1",
        tenant_id="tenant-1",
        project_id="project-1",
        state=operation_pb2.OPERATION_STATE_RUNNING,
    )


def _handlers(parent: str, seen: list[SeenCall]) -> dict[str, UnaryHandler]:
    artifact = _artifact()
    lease = _lease(parent)
    operation = _operation(parent)

    def record(method: str, response: Message) -> UnaryHandler:
        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            seen.append((method, copy.deepcopy(request), metadata))
            return copy.deepcopy(response)

        return handler

    return {
        GET_ARTIFACT: record(
            GET_ARTIFACT, artifact_service_pb2.GetArtifactResponse(artifact=artifact)
        ),
        LIST_ARTIFACTS: record(
            LIST_ARTIFACTS,
            artifact_service_pb2.ListArtifactsResponse(
                artifacts=[artifact],
                page=pagination_pb2.PageResponse(next_page_token="artifact-next"),
            ),
        ),
        QUARANTINE_ARTIFACT: record(
            QUARANTINE_ARTIFACT,
            artifact_service_pb2.QuarantineArtifactResponse(operation=operation),
        ),
        ACQUIRE_ARTIFACT_LEASE: record(
            ACQUIRE_ARTIFACT_LEASE,
            artifact_service_pb2.AcquireArtifactLeaseResponse(lease=lease),
        ),
        RELEASE_ARTIFACT_LEASE: record(
            RELEASE_ARTIFACT_LEASE,
            artifact_service_pb2.ReleaseArtifactLeaseResponse(),
        ),
        LIST_OPERATIONS: record(
            LIST_OPERATIONS,
            job_service_pb2.ListOperationsResponse(
                operations=[operation],
                page=pagination_pb2.PageResponse(next_page_token="operation-next"),
            ),
        ),
        CANCEL_OPERATION: record(
            CANCEL_OPERATION,
            job_service_pb2.CancelOperationResponse(operation=operation),
        ),
    }


def _requests(parent: str):
    artifact = _artifact()
    quarantine = artifact_service_pb2.QuarantineArtifactRequest(
        artifact=artifact,
        reason_code="INTEGRITY_FAILURE",
        evidence=[
            evidence_reference_pb2.EvidenceRef(
                digest="sha256:" + "b" * 64,
                subject_digest=artifact.digest,
                evidence_kind="integrity-check",
            )
        ],
    )
    quarantine.context.tenant_id = "forged"
    acquire = artifact_service_pb2.AcquireArtifactLeaseRequest(
        artifact=artifact,
        expire_time=_timestamp(datetime.now(UTC) + timedelta(hours=1)),
    )
    release = artifact_service_pb2.ReleaseArtifactLeaseRequest(
        lease=_lease(parent), etag="lease-etag-1"
    )
    return artifact, quarantine, acquire, release


def _assert_seen(test: unittest.TestCase, seen: list[SeenCall], parent: str) -> None:
    test.assertEqual(
        [method for method, _, _ in seen],
        [
            GET_ARTIFACT,
            LIST_ARTIFACTS,
            QUARANTINE_ARTIFACT,
            ACQUIRE_ARTIFACT_LEASE,
            RELEASE_ARTIFACT_LEASE,
            LIST_OPERATIONS,
            CANCEL_OPERATION,
        ],
    )
    for method, request, metadata in seen:
        if method == LIST_ARTIFACTS:
            request = cast(artifact_service_pb2.ListArtifactsRequest, request)
            test.assertEqual(request.parent, parent)
            test.assertEqual(request.page.page_token, "artifact-page")
        elif method == LIST_OPERATIONS:
            request = cast(job_service_pb2.ListOperationsRequest, request)
            test.assertEqual(request.parent, parent)
            test.assertEqual(request.page.page_token, "operation-page")
        if request.DESCRIPTOR.fields_by_name.get("context") is not None:
            context = cast(_CommandContextCarrier, request).context
            test.assertEqual(context.tenant_id, "tenant-1")
            test.assertEqual(context.project_id, "project-1")
            test.assertEqual(context.principal_id, "principal-1")
            clone = copy.deepcopy(request)
            clone.ClearField("context")
            test.assertEqual(context.canonical_request_digest, canonical_digest(clone))
            test.assertIn("idempotency-key", {key for key, _ in metadata})


class ArtifactOperationGapTest(unittest.TestCase):
    def test_sync_facade_records_exact_generated_requests(self) -> None:
        config = _config(asynchronous=False)
        parent = config.project_parent
        seen: list[SeenCall] = []
        transport = FakeSyncTransport()
        transport.unary_handlers.update(_handlers(parent, seen))
        client = Client(config, transport=transport, close_transport=False)
        artifact, quarantine, acquire, release = _requests(parent)
        self.assertEqual(
            client.artifacts.get(artifact_service_pb2.GetArtifactRequest(digest=artifact.digest)),
            artifact,
        )
        artifact_page = artifact_service_pb2.ListArtifactsRequest(
            page=pagination_pb2.PageRequest(page_size=25, page_token="artifact-page")
        )
        self.assertEqual(client.artifacts.list(artifact_page).page.next_page_token, "artifact-next")
        self.assertEqual(artifact_page.parent, "")
        self.assertTrue(
            client.artifacts.quarantine(
                quarantine, options=CallOptions(idempotency_key="quarantine-1")
            ).operation_id
        )
        self.assertEqual(quarantine.context.tenant_id, "forged")
        self.assertTrue(
            client.artifacts.acquire_lease(
                acquire, options=CallOptions(idempotency_key="acquire-1")
            ).etag
        )
        client.artifacts.release_lease(release, options=CallOptions(idempotency_key="release-1"))
        operation_page = job_service_pb2.ListOperationsRequest(
            page=pagination_pb2.PageRequest(page_size=50, page_token="operation-page")
        )
        self.assertEqual(
            client.operations.list(operation_page).page.next_page_token, "operation-next"
        )
        self.assertEqual(
            client.operations.cancel(
                _operation(parent).operation_id,
                etag="operation-etag-1",
                reason="operator request",
                options=CallOptions(idempotency_key="cancel-operation-1"),
            ).operation_id,
            _operation(parent).operation_id,
        )
        self.assertEqual(operation_page.parent, "")
        _assert_seen(self, seen, parent)


class AsyncArtifactOperationGapTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_facade_records_exact_generated_requests(self) -> None:
        config = _config(asynchronous=True)
        parent = config.project_parent
        seen: list[SeenCall] = []
        transport = FakeAsyncTransport()
        transport.unary_handlers.update(_handlers(parent, seen))
        client = AsyncClient(config, transport=transport, close_transport=False)
        artifact, quarantine, acquire, release = _requests(parent)
        self.assertEqual(
            await client.artifacts.get(
                artifact_service_pb2.GetArtifactRequest(digest=artifact.digest)
            ),
            artifact,
        )
        await client.artifacts.list(
            artifact_service_pb2.ListArtifactsRequest(
                page=pagination_pb2.PageRequest(page_size=25, page_token="artifact-page")
            )
        )
        await client.artifacts.quarantine(
            quarantine, options=CallOptions(idempotency_key="quarantine-1")
        )
        await client.artifacts.acquire_lease(
            acquire, options=CallOptions(idempotency_key="acquire-1")
        )
        await client.artifacts.release_lease(
            release, options=CallOptions(idempotency_key="release-1")
        )
        await client.operations.list(
            job_service_pb2.ListOperationsRequest(
                page=pagination_pb2.PageRequest(page_size=50, page_token="operation-page")
            )
        )
        self.assertEqual(
            (
                await client.operations.cancel(
                    _operation(parent).operation_id,
                    etag="operation-etag-1",
                    reason="operator request",
                    options=CallOptions(idempotency_key="cancel-operation-1"),
                )
            ).operation_id,
            _operation(parent).operation_id,
        )
        _assert_seen(self, seen, parent)


if __name__ == "__main__":
    unittest.main()
