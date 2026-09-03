from __future__ import annotations

import unittest
from collections.abc import Callable

import grpc
from google.protobuf.message import Message
from mindclade.common.v1 import pagination_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_pb2
from mindclade_internal_sdk import (
    SAFE_RESPONSE_METADATA_KEYS,
    AsyncClient,
    AsyncPage,
    AsyncWithRawResponse,
    Client,
    ClientConfig,
    Environment,
    Page,
    ProtocolError,
    RawResponse,
    WithRawResponse,
    is_credential_metadata_key,
)
from mindclade_internal_sdk._metadata import safe_metadata
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import GET_JOB, LIST_JOBS, Metadata

NAMESPACES = (
    "admin",
    "agents",
    "approvals",
    "artifacts",
    "datasets",
    "evaluations",
    "experiments",
    "generated",
    "inference",
    "jobs",
    "models",
    "operations",
    "policies",
    "runs",
    "training",
    "workflows",
)

LEASE_TOKEN = "lease-token-" + "s" * 40
BEARER = "Bearer super-secret-value"

CREDENTIAL_METADATA: Metadata = (
    ("authorization", BEARER),
    ("x-mindclade-lease-token", LEASE_TOKEN),
    ("set-cookie", "session=abc123"),
    ("x-custom-secret", "hunter2"),
    ("x-api-key", "key-material"),
    ("x-unlisted-header", "harmless but unlisted"),
)


def config() -> ClientConfig:
    return ClientConfig(
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        insecure_for_testing=True,
    )


def job(*, project_id: str = "project-1") -> job_pb2.Job:
    return job_pb2.Job(
        job_id="jobs/job-1",
        operation_id="operations/op-1",
        tenant_id="tenant-1",
        project_id=project_id,
        state=job_pb2.JOB_STATE_RUNNING,
        resource_version=1,
        etag="etag-1",
    )


def get_job_handler(
    *, project_id: str = "project-1"
) -> Callable[[Message, float, Metadata], Message]:
    def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
        del request, timeout, metadata
        return job_service_pb2.GetJobResponse(job=job(project_id=project_id))

    return handler


def list_jobs_handler() -> Callable[[Message, float, Metadata], Message]:
    def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
        del request, timeout, metadata
        return job_service_pb2.ListJobsResponse(
            jobs=[job()],
            page=pagination_pb2.PageResponse(next_page_token=""),
        )

    return handler


def sync_client(
    transport: FakeSyncTransport | None = None,
) -> tuple[Client, FakeSyncTransport]:
    fake = transport or FakeSyncTransport()
    fake.unary_handlers.setdefault(GET_JOB, get_job_handler())
    fake.unary_handlers.setdefault(LIST_JOBS, list_jobs_handler())
    return Client(config(), transport=fake, close_transport=False), fake


def async_client(
    transport: FakeAsyncTransport | None = None,
) -> tuple[AsyncClient, FakeAsyncTransport]:
    fake = transport or FakeAsyncTransport()
    fake.unary_handlers.setdefault(GET_JOB, get_job_handler())
    fake.unary_handlers.setdefault(LIST_JOBS, list_jobs_handler())
    return AsyncClient(config(), transport=fake, close_transport=False), fake


class MetadataAllowlistTest(unittest.TestCase):
    def test_allowlist_excludes_every_credential_bearing_key(self) -> None:
        for key in SAFE_RESPONSE_METADATA_KEYS:
            with self.subTest(key=key):
                self.assertFalse(is_credential_metadata_key(key))

    def test_credential_patterns_cover_the_declared_denylist(self) -> None:
        for key in (
            "authorization",
            "Proxy-Authorization",
            "x-mindclade-lease-token",
            "cookie",
            "set-cookie",
            "x-api-key",
            "session-token",
            "client_secret",
            "user-password",
            "gcp-credential",
        ):
            with self.subTest(key=key):
                self.assertTrue(is_credential_metadata_key(key))

    def test_safe_metadata_drops_unlisted_binary_and_malformed_values(self) -> None:
        projected = safe_metadata(
            (
                *CREDENTIAL_METADATA,
                ("x-request-id", "request-1"),
                ("X-Trace-Id", b"trace-1"),
                ("grpc-status-details-bin", b"\x00\x01"),
                ("date", "x" * 300),
                ("grpc-message", "line-one\r\nline-two"),
            )
        )
        self.assertEqual(dict(projected), {"x-request-id": "request-1", "x-trace-id": "trace-1"})
        with self.assertRaises(TypeError):
            projected["x-request-id"] = "tampered"  # type: ignore[index]


class SyncRawResponseTest(unittest.TestCase):
    def test_with_raw_response_exists_on_every_namespace(self) -> None:
        client, _ = sync_client()
        for name in NAMESPACES:
            with self.subTest(namespace=name):
                namespace = getattr(client, name)
                self.assertIsInstance(namespace, WithRawResponse)
                self.assertTrue(hasattr(namespace, "with_raw_response"))

    def test_raw_response_exposes_status_request_id_and_trace_id(self) -> None:
        client, transport = sync_client()
        transport.response_metadata[GET_JOB] = (
            ("x-request-id", "server-request-1"),
            ("x-trace-id", "server-trace-1"),
        )
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertIsInstance(raw, RawResponse)
        self.assertIs(raw.status, grpc.StatusCode.OK)
        self.assertEqual(raw.request_id, "server-request-1")
        self.assertEqual(raw.trace_id, "server-trace-1")

    def test_raw_response_falls_back_to_the_client_request_id(self) -> None:
        client, _ = sync_client()
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertTrue(raw.request_id)
        self.assertTrue(raw.trace_id)
        self.assertEqual(dict(raw.metadata), {})

    def test_raw_response_reads_the_trailing_metadata_request_id(self) -> None:
        client, transport = sync_client()
        transport.response_trailers[GET_JOB] = (("x-request-id", "trailer-request-1"),)
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertEqual(raw.request_id, "trailer-request-1")

    def test_raw_response_metadata_is_allowlisted(self) -> None:
        client, transport = sync_client()
        transport.response_metadata[GET_JOB] = (
            *CREDENTIAL_METADATA,
            ("x-request-id", "request-1"),
            ("retry-after-ms", "250"),
        )
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertEqual(sorted(raw.metadata), ["retry-after-ms", "x-request-id"])
        rendered = repr(raw)
        for secret in (BEARER, LEASE_TOKEN, "session=abc123", "hunter2", "key-material"):
            self.assertNotIn(secret, rendered)

    def test_raw_response_parse_returns_the_same_validated_value(self) -> None:
        client, _ = sync_client()
        plain = client.jobs.get("job-1")
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertEqual(raw.parse(), plain)
        self.assertIs(raw.parse(), raw.data)

    def test_raw_response_preserves_every_response_validation(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = get_job_handler(project_id="project-elsewhere")
        client, _ = sync_client(transport)
        with self.assertRaises(ProtocolError):
            client.jobs.with_raw_response.get("job-1")

    def test_raw_response_on_a_list_method_returns_a_page(self) -> None:
        client, _ = sync_client()
        raw = client.jobs.with_raw_response.list()
        self.assertIsInstance(raw.data, Page)
        self.assertEqual([item.job_id for item in raw.data], ["jobs/job-1"])

    def test_streaming_method_rejects_raw_response(self) -> None:
        client, _ = sync_client()
        for namespace, method in (
            (client.operations, "watch"),
            (client.workflows, "watch"),
            (client.inference, "watch"),
            (client.training, "watch"),
            (client.artifacts, "iter_download"),
            (client.generated, "stream"),
        ):
            with self.subTest(method=method), self.assertRaises(ValueError):
                getattr(namespace.with_raw_response, method)

    def test_unknown_attribute_is_an_attribute_error(self) -> None:
        client, _ = sync_client()
        with self.assertRaises(AttributeError):
            client.jobs.with_raw_response.not_a_method  # noqa: B018
        with self.assertRaises(AttributeError):
            client.jobs.with_raw_response._invoker  # noqa: B018

    def test_plain_calls_are_unaffected_by_the_raw_seam(self) -> None:
        client, transport = sync_client()
        transport.response_metadata[GET_JOB] = (("authorization", BEARER),)
        self.assertEqual(client.jobs.get("job-1").job_id, "jobs/job-1")
        raw = client.jobs.with_raw_response.get("job-1")
        self.assertEqual(dict(raw.metadata), {})


class AsyncRawResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_with_raw_response_exists_on_every_async_namespace(self) -> None:
        client, _ = async_client()
        for name in NAMESPACES:
            with self.subTest(namespace=name):
                namespace = getattr(client, name)
                self.assertIsInstance(namespace, AsyncWithRawResponse)
                self.assertTrue(hasattr(namespace, "with_raw_response"))

    async def test_async_raw_response_exposes_transport_facts(self) -> None:
        client, transport = async_client()
        transport.response_metadata[GET_JOB] = (
            *CREDENTIAL_METADATA,
            ("x-request-id", "server-request-1"),
            ("x-trace-id", "server-trace-1"),
        )
        raw = await client.jobs.with_raw_response.get("job-1")
        self.assertIs(raw.status, grpc.StatusCode.OK)
        self.assertEqual(raw.request_id, "server-request-1")
        self.assertEqual(raw.trace_id, "server-trace-1")
        self.assertEqual(sorted(raw.metadata), ["x-request-id", "x-trace-id"])
        self.assertNotIn(LEASE_TOKEN, repr(raw))

    async def test_async_raw_response_reads_the_trailing_metadata_request_id(self) -> None:
        client, transport = async_client()
        transport.response_trailers[GET_JOB] = (("x-request-id", "trailer-request-1"),)
        raw = await client.jobs.with_raw_response.get("job-1")
        self.assertEqual(raw.request_id, "trailer-request-1")

    async def test_async_raw_response_on_a_list_method_returns_a_page(self) -> None:
        client, _ = async_client()
        raw = await client.jobs.with_raw_response.list()
        self.assertIsInstance(raw.data, AsyncPage)
        self.assertEqual([item.job_id async for item in raw.data], ["jobs/job-1"])

    async def test_async_raw_response_preserves_every_response_validation(self) -> None:
        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_JOB] = get_job_handler(project_id="project-elsewhere")
        client, _ = async_client(transport)
        with self.assertRaises(ProtocolError):
            await client.jobs.with_raw_response.get("job-1")

    async def test_async_streaming_method_rejects_raw_response(self) -> None:
        client, _ = async_client()
        with self.assertRaises(ValueError):
            client.operations.with_raw_response.watch  # noqa: B018


if __name__ == "__main__":
    unittest.main()
