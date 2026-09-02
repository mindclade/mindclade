from __future__ import annotations

import asyncio
import hashlib
import io
import tempfile
import threading
import time
import unittest
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import grpc
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import pagination_pb2, resource_reference_pb2
from mindclade.dataset.v1 import dataset_commands_pb2, dataset_pb2, dataset_release_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2_grpc as artifact_service_pb2_grpc
from mindclade.internal.dataset.v1 import dataset_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.internal.model.v1 import model_service_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.job.v1 import operation_pb2
from mindclade.model.v1 import model_commands_pb2, model_pb2, model_release_pb2
from mindclade.training.v1 import training_commands_pb2, training_run_pb2
from mindclade_internal_sdk import (
    AccessToken,
    AsyncClient,
    AuthenticationError,
    CallOptions,
    CancelledError,
    Client,
    ClientConfig,
    ConfigurationError,
    ConflictError,
    DeadlineExceededError,
    Environment,
    GoogleWorkloadIdentityProvider,
    OperationFailedError,
    PaginationLimitError,
    PaginationLimits,
    ProtocolError,
    RetryPolicy,
    UnavailableError,
    apaginate,
    paginate,
)
from mindclade_internal_sdk import artifacts as artifacts_module
from mindclade_internal_sdk._invocation import SyncInvoker, canonical_digest
from mindclade_internal_sdk.calls import prepare_call
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport, SyncUnaryHandler
from mindclade_internal_sdk.transport import (
    ABORT_ARTIFACT_UPLOAD,
    BEGIN_ARTIFACT_UPLOAD,
    COMMIT_ARTIFACT,
    CREATE_DATASET,
    CREATE_TRAINING_RUN,
    DOWNLOAD_ARTIFACT,
    FINALIZE_ARTIFACT_UPLOAD,
    GET_ARTIFACT_UPLOAD,
    GET_DATASET,
    GET_DATASET_RELEASE,
    GET_MODEL,
    GET_MODEL_RELEASE,
    GET_OPERATION,
    GET_TRAINING_RUN,
    INTERNAL_SERVICE_NAMES,
    INTERNAL_STREAM_METHODS,
    INTERNAL_UNARY_METHODS,
    LIST_DATASET_RELEASES,
    LIST_DATASETS,
    LIST_MODEL_RELEASES,
    LIST_MODELS,
    PROMOTE_MODEL_RELEASE,
    PUBLISH_DATASET_RELEASE,
    QUARANTINE_ARTIFACT_UPLOAD,
    REGISTER_MODEL,
    REGISTER_MODEL_RELEASE,
    RESOLVE_ARTIFACT_ALIAS,
    REVOKE_DATASET_RELEASE,
    REVOKE_MODEL_RELEASE,
    UPDATE_DATASET,
    UPLOAD_ARTIFACT_CHUNK,
    WATCH_OPERATION,
    GrpcSyncTransport,
    Metadata,
)


class SyncCredentials:
    def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken(
            "test-only-token",
            datetime.now(UTC) + timedelta(minutes=5),
        )


class AsyncCredentials:
    async def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken(
            "test-only-token",
            datetime.now(UTC) + timedelta(minutes=5),
        )


class ArtifactBoundaryService(artifact_service_pb2_grpc.ArtifactServiceServicer):
    def __init__(self, chunk: bytes) -> None:
        self._chunk = chunk
        self.uploaded_bytes = 0

    def UploadArtifactChunk(  # noqa: N802 -- generated gRPC service method
        self,
        request: artifact_service_pb2.UploadArtifactChunkRequest,
        context: grpc.ServicerContext,
    ) -> artifact_service_pb2.UploadArtifactChunkResponse:
        del context
        self.uploaded_bytes = len(request.data)
        return artifact_service_pb2.UploadArtifactChunkResponse()

    def DownloadArtifact(  # noqa: N802 -- generated gRPC service method
        self,
        request: artifact_service_pb2.DownloadArtifactRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[artifact_service_pb2.DownloadArtifactResponse]:
        del request, context
        yield artifact_service_pb2.DownloadArtifactResponse(
            data=self._chunk,
            chunk_digest="sha256:" + hashlib.sha256(self._chunk).hexdigest(),
            complete=True,
        )


class FakeRpcError(grpc.RpcError):
    def __init__(
        self,
        code: grpc.StatusCode,
        metadata: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__()
        self._code = code
        self._metadata = metadata

    def code(self) -> grpc.StatusCode:
        return self._code

    def trailing_metadata(self) -> Any:
        return self._metadata


def secure_config(*, asynchronous: bool = False) -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-01",
        project_id="project-01",
        principal_id="principal-01",
        token_provider=AsyncCredentials() if asynchronous else SyncCredentials(),
        retry=RetryPolicy(max_attempts=3, base_delay=0.0001, max_delay=0.0002),
        poll_interval=0.0001,
    )


def artifact(digit: str = "1") -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + digit * 64,
        media_type="application/vnd.mindclade.test+json",
        size_bytes=10,
    )


def transfer_artifact(data: bytes) -> artifact_reference_pb2.ArtifactRef:
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return artifact_reference_pb2.ArtifactRef(
        digest=digest,
        integrity_digest=digest,
        media_type="application/octet-stream",
        size_bytes=len(data),
    )


def timestamp_at(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def staging_receipt(
    value: artifact_reference_pb2.ArtifactRef,
) -> artifact_service_pb2.ArtifactStagingReceipt:
    now = datetime.now(UTC)
    return artifact_service_pb2.ArtifactStagingReceipt(
        receipt_digest="sha256:" + "a" * 64,
        artifact=value,
        verified_at=timestamp_at(now),
        expire_time=timestamp_at(now + timedelta(hours=1)),
    )


def upload_session(
    value: artifact_reference_pb2.ArtifactRef,
    *,
    state: artifact_service_pb2.ArtifactUploadState = (
        artifact_service_pb2.ARTIFACT_UPLOAD_STATE_OPEN
    ),
    offset: int = 0,
    chunk_index: int = 0,
    revision: int = 1,
    etag: str = "etag-1",
    receipt: artifact_service_pb2.ArtifactStagingReceipt | None = None,
    name: str = "tenants/tenant-01/projects/project-01/artifactUploads/upload-01",
) -> artifact_service_pb2.ArtifactUploadSession:
    result = artifact_service_pb2.ArtifactUploadSession(
        name=name,
        artifact=value,
        state=state,
        committed_offset=offset,
        next_chunk_index=chunk_index,
        revision=revision,
        etag=etag,
    )
    if receipt is not None:
        result.staging_receipt.CopyFrom(receipt)
    return result


def resource(name: str) -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(name=name)


class ConfigurationTest(unittest.TestCase):
    def test_generated_rpc_escape_hatch_covers_the_descriptor_estate(self) -> None:
        self.assertEqual(
            INTERNAL_SERVICE_NAMES,
            {
                "mindclade.internal.admin.v1.AdminService",
                "mindclade.internal.agent.v1.AgentService",
                "mindclade.internal.artifact.v1.ArtifactService",
                "mindclade.internal.dataset.v1.DatasetService",
                "mindclade.internal.evaluation.v1.EvaluationService",
                "mindclade.internal.experiment.v1.ExperimentService",
                "mindclade.internal.inference.v1.InferenceService",
                "mindclade.internal.job.v1.JobService",
                "mindclade.internal.job.v1.OperationService",
                "mindclade.internal.job.v1.RunService",
                "mindclade.internal.model.v1.ModelService",
                "mindclade.internal.policy.v1.PolicyService",
                "mindclade.internal.training.v1.TrainingService",
                "mindclade.internal.workflow.v1.ApprovalService",
                "mindclade.internal.workflow.v1.WorkflowService",
            },
        )
        self.assertEqual(len(INTERNAL_SERVICE_NAMES), 15)
        self.assertEqual(len(INTERNAL_UNARY_METHODS), 127)
        self.assertEqual(len(INTERNAL_STREAM_METHODS), 5)
        self.assertEqual(len(INTERNAL_UNARY_METHODS | INTERNAL_STREAM_METHODS), 132)
        self.assertFalse(INTERNAL_UNARY_METHODS & INTERNAL_STREAM_METHODS)

    def test_bounded_pagination_preserves_opaque_tokens_and_fails_closed(self) -> None:
        seen: list[str] = []

        def fetch(token: str) -> tuple[tuple[int, ...], str]:
            seen.append(token)
            return ((1, 2), " next token ") if len(seen) == 1 else ((3,), "")

        self.assertEqual(
            list(paginate(fetch, initial_page_token=" initial token ")),
            [1, 2, 3],
        )
        self.assertEqual(seen, [" initial token ", " next token "])

        repeated = iter(paginate(lambda token: ((1,), token), initial_page_token="opaque"))
        with self.assertRaises(ProtocolError):
            next(repeated)

        bounded = iter(
            paginate(
                lambda token: ((1, 2, 3), "more"),
                limits=PaginationLimits(max_pages=2, max_items=2),
            )
        )
        self.assertEqual(next(bounded), 1)
        self.assertEqual(next(bounded), 2)
        with self.assertRaises(PaginationLimitError):
            next(bounded)

    def test_maximum_artifact_chunks_cross_the_production_grpc_transport(self) -> None:
        chunk = b"x" * (4 << 20)
        service = ArtifactBoundaryService(chunk)  # pyright: ignore[reportAbstractUsage]
        with ThreadPoolExecutor(max_workers=1) as executor:
            server = grpc.server(
                executor,
                options=(
                    ("grpc.max_receive_message_length", 16 << 20),
                    ("grpc.max_send_message_length", 16 << 20),
                ),
            )
            artifact_service_pb2_grpc.add_ArtifactServiceServicer_to_server(service, server)
            port = server.add_insecure_port("127.0.0.1:0")
            self.assertGreater(port, 0)
            server.start()
            transport = GrpcSyncTransport(
                ClientConfig(
                    tenant_id="tenant-01",
                    project_id="project-01",
                    principal_id="principal-01",
                    environment=Environment.LOCAL,
                    endpoint=f"127.0.0.1:{port}",
                    insecure_for_testing=True,
                )
            )
            try:
                response = transport.unary_unary(
                    UPLOAD_ARTIFACT_CHUNK,
                    artifact_service_pb2.UploadArtifactChunkRequest(
                        name="tenants/tenant-01/projects/project-01/artifactUploads/upload-01",
                        data=chunk,
                        chunk_digest="sha256:" + hashlib.sha256(chunk).hexdigest(),
                        etag="etag-01",
                    ),
                    timeout=5,
                    metadata=(),
                )
                self.assertIsInstance(response, artifact_service_pb2.UploadArtifactChunkResponse)
                downloaded = list(
                    transport.unary_stream(
                        DOWNLOAD_ARTIFACT,
                        artifact_service_pb2.DownloadArtifactRequest(
                            digest="sha256:" + hashlib.sha256(chunk).hexdigest(),
                            max_chunk_bytes=len(chunk),
                        ),
                        timeout=5,
                        metadata=(),
                    )
                )
            finally:
                transport.close()
                server.stop(None).wait(timeout=5)
        self.assertEqual(service.uploaded_bytes, len(chunk))
        self.assertEqual(
            [
                cast(artifact_service_pb2.DownloadArtifactResponse, value).data
                for value in downloaded
            ],
            [chunk],
        )

    def test_tls_and_workload_identity_are_required_by_default(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "token provider"):
            ClientConfig(
                tenant_id="tenant-01",
                project_id="project-01",
                principal_id="principal-01",
            )

    def test_workload_identity_audience_uses_canonical_https_origin(self) -> None:
        cases = (
            ("CONTROL-PLANE.EXAMPLE:443", "https://control-plane.example"),
            ("control-plane.example:8443", "https://control-plane.example:8443"),
            ("[2001:db8::1]:443", "https://[2001:db8::1]"),
        )
        for endpoint, expected in cases:
            with self.subTest(endpoint=endpoint):
                config = ClientConfig(
                    tenant_id="tenant-01",
                    project_id="project-01",
                    principal_id="principal-01",
                    token_provider=SyncCredentials(),
                    endpoint=endpoint,
                )
                self.assertEqual(config.audience, expected)

        explicit = ClientConfig(
            tenant_id="tenant-01",
            project_id="project-01",
            principal_id="principal-01",
            token_provider=SyncCredentials(),
            endpoint="control-plane.example:443",
            audience="https://verifier.example/custom-audience",
        )
        self.assertEqual(explicit.audience, "https://verifier.example/custom-audience")

        provider = GoogleWorkloadIdentityProvider("https://verifier.example/provider")
        self.assertEqual(provider.audience, "https://verifier.example/provider")
        with self.assertRaisesRegex(ConfigurationError, "does not match"):
            ClientConfig(
                tenant_id="tenant-01",
                project_id="project-01",
                principal_id="principal-01",
                token_provider=provider,
                endpoint="control-plane.example:443",
            )

    def test_cleartext_is_restricted_to_uncredentialed_local_loopback(self) -> None:
        config = ClientConfig(
            environment=Environment.LOCAL,
            endpoint="127.0.0.1:9443",
            tenant_id="tenant-01",
            project_id="project-01",
            principal_id="principal-01",
            insecure_for_testing=True,
        )
        self.assertTrue(config.insecure_for_testing)
        with self.assertRaisesRegex(ConfigurationError, "loopback"):
            ClientConfig(
                environment=Environment.LOCAL,
                endpoint="control-plane.example:443",
                tenant_id="tenant-01",
                project_id="project-01",
                principal_id="principal-01",
                insecure_for_testing=True,
            )
        with self.assertRaisesRegex(ConfigurationError, "credentials"):
            ClientConfig(
                environment=Environment.LOCAL,
                endpoint="localhost:9443",
                tenant_id="tenant-01",
                project_id="project-01",
                principal_id="principal-01",
                token_provider=SyncCredentials(),
                insecure_for_testing=True,
            )

    def test_endpoint_and_identity_injection_are_rejected(self) -> None:
        for endpoint in ("https://example:443/path", "user@example:443", "example", "x\n:443"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigurationError):
                ClientConfig(
                    endpoint=endpoint,
                    tenant_id="tenant-01",
                    project_id="project-01",
                    principal_id="principal-01",
                    token_provider=SyncCredentials(),
                )
        with self.assertRaises(ConfigurationError):
            ClientConfig(
                tenant_id="tenant\nadmin",
                project_id="project-01",
                principal_id="principal-01",
                token_provider=SyncCredentials(),
            )

    def test_token_repr_does_not_expose_secret(self) -> None:
        value = AccessToken(
            "never-print-this",
            datetime.now(UTC) + timedelta(minutes=5),
        )
        self.assertNotIn("never-print-this", repr(value))

    def test_tokens_are_bounded_short_lived_and_refresh_safe(self) -> None:
        now = datetime.now(UTC)
        for secret in ("", "contains space", "line\nbreak", "x" * (16 * 1024 + 1)):
            with self.subTest(secret_length=len(secret)), self.assertRaises(ValueError):
                AccessToken(secret, now + timedelta(minutes=5))
        with self.assertRaisesRegex(ValueError, "refresh window"):
            AccessToken("short-token", now + timedelta(seconds=10)).authorization_header(now=now)
        with self.assertRaisesRegex(ValueError, "maximum lifetime"):
            AccessToken("long-token", now + timedelta(hours=2)).authorization_header(now=now)
        self.assertEqual(
            AccessToken("valid-token", now + timedelta(minutes=5)).authorization_header(now=now),
            "Bearer valid-token",
        )

    def test_google_workload_identity_refresh_is_singleflight_and_audience_bound(self) -> None:
        with self.assertRaisesRegex(ValueError, "audience"):
            GoogleWorkloadIdentityProvider(" audience with spaces ")

        class FakeGoogleProvider(GoogleWorkloadIdentityProvider):
            def __init__(self) -> None:
                super().__init__("https://control-plane.example")
                self.fetches = 0

            def _fetch(self, deadline: float) -> AccessToken:
                self.assert_deadline(deadline)
                self.fetches += 1
                time.sleep(0.01)
                return AccessToken(
                    "singleflight-token",
                    datetime.now(UTC) + timedelta(minutes=5),
                )

            @staticmethod
            def assert_deadline(deadline: float) -> None:
                if deadline <= time.monotonic():
                    raise AssertionError("provider received an expired deadline")

        provider = FakeGoogleProvider()

        def acquire(_index: int) -> AccessToken:
            return provider.get_token(timeout=1)

        with ThreadPoolExecutor(max_workers=8) as executor:
            tokens = list(executor.map(acquire, range(8)))
        self.assertEqual(provider.fetches, 1)
        self.assertEqual({token.value for token in tokens}, {"singleflight-token"})


class SyncClientTest(unittest.TestCase):
    def test_training_submit_uses_generated_contract_and_stable_metadata(self) -> None:
        transport = FakeSyncTransport()
        captured: list[training_service_pb2.CreateTrainingRunRequest] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            typed = cast(training_service_pb2.CreateTrainingRunRequest, request)
            captured.append(typed)
            values = dict(metadata)
            self.assertEqual(values["authorization"], "Bearer test-only-token")
            self.assertEqual(values["idempotency-key"], "idem-01")
            self.assertEqual(values["x-mindclade-expected-tenant"], "tenant-01")
            self.assertEqual(values["x-mindclade-expected-project"], "project-01")
            self.assertEqual(values["x-mindclade-expected-principal"], "principal-01")
            return training_service_pb2.CreateTrainingRunResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/01",
                    state=operation_pb2.OPERATION_STATE_PENDING,
                )
            )

        transport.unary_handlers[CREATE_TRAINING_RUN] = handler
        client = Client(secure_config(), transport=transport)
        operation = client.training.submit(
            "pretrain-v4",
            training_recipe=artifact(),
            dataset_release=resource("datasetReleases/pdb-2026-08"),
            model_release=resource("modelReleases/nova-1"),
            labels={"profile": "sqp-001"},
            options=CallOptions(
                request_id="request-01",
                trace_id="trace-01",
                idempotency_key="idem-01",
            ),
        )
        self.assertIsInstance(operation, operation_pb2.Operation)
        self.assertEqual(operation.operation_id, "operations/01")
        command = captured[0].command
        self.assertEqual(command.context.tenant_id, "tenant-01")
        self.assertEqual(command.context.project_id, "project-01")
        self.assertEqual(command.context.principal_id, "principal-01")
        self.assertEqual(command.context.request_id, "request-01")
        without_context = training_commands_pb2.CreateTrainingRunCommand()
        without_context.CopyFrom(command)
        without_context.ClearField("context")
        self.assertEqual(
            command.context.canonical_request_digest,
            canonical_digest(without_context),
        )
        self.assertNotIn("test-only-token", repr(transport.calls))

    def test_reads_retry_bounded_transient_status_and_preserve_request_id(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise FakeRpcError(
                    grpc.StatusCode.UNAVAILABLE,
                    (("x-request-id", "server-request-01"),),
                )
            return job_service_pb2.GetOperationResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/01",
                    state=operation_pb2.OPERATION_STATE_SUCCEEDED,
                    done=True,
                )
            )

        transport.unary_handlers[GET_OPERATION] = handler
        client = Client(secure_config(), transport=transport)
        operation = client.operations.get(
            "operations/01", options=CallOptions(request_id="client-request-01")
        )
        self.assertTrue(operation.done)
        self.assertEqual(attempts, 3)

        def unavailable(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (
                    ("x-request-id", "server-request-02"),
                    ("retry-after-ms", "1"),
                ),
            )

        transport.unary_handlers[GET_OPERATION] = unavailable
        with self.assertRaises(UnavailableError) as raised:
            client.operations.get("operations/02")
        self.assertEqual(raised.exception.request_id, "server-request-02")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.retry_after, 0.001)
        self.assertNotIn("provider payload", str(raised.exception))

    def test_non_idempotent_invocation_is_never_retried(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def unavailable(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        transport.unary_handlers[GET_OPERATION] = unavailable
        invoker = SyncInvoker(secure_config(), transport)
        call = prepare_call(None, default_timeout=1.0, require_idempotency=False)
        with self.assertRaises(UnavailableError):
            invoker.unary(
                GET_OPERATION,
                job_service_pb2.GetOperationRequest(name="operations/01"),
                call=call,
                retry_safe=False,
            )
        self.assertEqual(attempts, 1)

    def test_operation_poll_alias_resolution_watch_cancellation_and_close(self) -> None:
        transport = FakeSyncTransport()
        operations = iter(
            (
                operation_pb2.Operation(
                    operation_id="operations/01",
                    state=operation_pb2.OPERATION_STATE_RUNNING,
                    done=False,
                ),
                operation_pb2.Operation(
                    operation_id="operations/01",
                    state=operation_pb2.OPERATION_STATE_SUCCEEDED,
                    done=True,
                ),
            )
        )
        transport.unary_handlers[GET_OPERATION] = lambda request, timeout, metadata: (
            job_service_pb2.GetOperationResponse(operation=next(operations))
        )
        transport.unary_handlers[RESOLVE_ARTIFACT_ALIAS] = lambda request, timeout, metadata: (
            artifact_service_pb2.ResolveArtifactAliasResponse(artifact=artifact("2"))
        )
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: [
            job_service_pb2.WatchOperationResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/01",
                    state=operation_pb2.OPERATION_STATE_RUNNING,
                ),
                sequence=1,
            )
        ]
        client = Client(secure_config(), transport=transport)
        self.assertTrue(client.operations.wait("operations/01", timeout=1).done)
        self.assertEqual(client.artifacts.resolve_alias("latest").digest, "sha256:" + "2" * 64)
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(CancelledError):
            list(client.operations.watch("operations/01", cancellation=cancellation))
        self.assertFalse(any(call.method == WATCH_OPERATION for call in transport.calls))
        client.close()
        client.close()
        self.assertTrue(transport.closed)

    def test_artifact_transfer_upload_commit_and_verified_download(self) -> None:
        content = b"generated-rpc-artifact"
        expected = transfer_artifact(content)
        receipt = staging_receipt(expected)
        transport = FakeSyncTransport()
        uploaded = 0
        chunk_index = 0
        contexts: list[str] = []

        def begin(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(artifact_service_pb2.BeginArtifactUploadRequest, request)
            self.assertEqual(typed.parent, "tenants/tenant-01/projects/project-01")
            self.assertEqual(typed.artifact, expected)
            self.assertEqual(typed.upload_id, "upload-01")
            clone = artifact_service_pb2.BeginArtifactUploadRequest()
            clone.CopyFrom(typed)
            contexts.append(clone.context.idempotency_key)
            context = clone.context
            clone.ClearField("context")
            self.assertEqual(context.canonical_request_digest, canonical_digest(clone))
            return artifact_service_pb2.BeginArtifactUploadResponse(upload=upload_session(expected))

        def chunk(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            nonlocal uploaded, chunk_index
            typed = cast(artifact_service_pb2.UploadArtifactChunkRequest, request)
            self.assertEqual(typed.offset, uploaded)
            self.assertEqual(typed.chunk_index, chunk_index)
            self.assertEqual(typed.data, content[uploaded : uploaded + len(typed.data)])
            self.assertEqual(
                typed.chunk_digest,
                "sha256:" + hashlib.sha256(typed.data).hexdigest(),
            )
            clone = artifact_service_pb2.UploadArtifactChunkRequest()
            clone.CopyFrom(typed)
            contexts.append(clone.context.idempotency_key)
            context = clone.context
            clone.ClearField("context")
            self.assertEqual(context.canonical_request_digest, canonical_digest(clone))
            uploaded += len(typed.data)
            chunk_index += 1
            return artifact_service_pb2.UploadArtifactChunkResponse(
                upload=upload_session(
                    expected,
                    offset=uploaded,
                    chunk_index=chunk_index,
                    revision=chunk_index + 1,
                    etag=f"etag-{chunk_index + 1}",
                )
            )

        def finalize(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(artifact_service_pb2.FinalizeArtifactUploadRequest, request)
            self.assertEqual(uploaded, len(content))
            self.assertEqual(typed.etag, f"etag-{chunk_index + 1}")
            clone = artifact_service_pb2.FinalizeArtifactUploadRequest()
            clone.CopyFrom(typed)
            contexts.append(clone.context.idempotency_key)
            context = clone.context
            clone.ClearField("context")
            self.assertEqual(context.canonical_request_digest, canonical_digest(clone))
            return artifact_service_pb2.FinalizeArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED,
                    offset=len(content),
                    chunk_index=chunk_index,
                    revision=chunk_index + 2,
                    etag="etag-final",
                    receipt=receipt,
                ),
                staging_receipt=receipt,
            )

        def commit(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(artifact_service_pb2.CommitArtifactRequest, request)
            self.assertEqual(typed.command.artifact, expected)
            self.assertEqual(typed.command.staging_receipt_digest, receipt.receipt_digest)
            command = type(typed.command)()
            command.CopyFrom(typed.command)
            contexts.append(command.context.idempotency_key)
            context = command.context
            command.ClearField("context")
            self.assertEqual(context.canonical_request_digest, canonical_digest(command))
            return artifact_service_pb2.CommitArtifactResponse(artifact=expected)

        def download(request: Message, timeout: float, metadata: Metadata) -> list[Message]:
            del timeout, metadata
            typed = cast(artifact_service_pb2.DownloadArtifactRequest, request)
            self.assertEqual(typed.digest, expected.digest)
            responses: list[Message] = []
            offset = typed.offset
            for position in range(offset, len(content), 5):
                data = content[position : position + 5]
                responses.append(
                    artifact_service_pb2.DownloadArtifactResponse(
                        artifact=expected,
                        offset=position,
                        data=data,
                        chunk_digest="sha256:" + hashlib.sha256(data).hexdigest(),
                        complete=position + len(data) == len(content),
                    )
                )
            return responses

        transport.unary_handlers[BEGIN_ARTIFACT_UPLOAD] = begin

        def missing_upload(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.NOT_FOUND)

        transport.unary_handlers[GET_ARTIFACT_UPLOAD] = missing_upload
        transport.unary_handlers[UPLOAD_ARTIFACT_CHUNK] = chunk
        transport.unary_handlers[FINALIZE_ARTIFACT_UPLOAD] = finalize
        transport.unary_handlers[COMMIT_ARTIFACT] = commit
        transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
        client = Client(secure_config(), transport=transport)
        result = client.artifacts.upload(
            expected,
            io.BytesIO(content),
            upload_id="upload-01",
            chunk_bytes=4,
            options=CallOptions(idempotency_key="caller-transfer-key"),
        )
        self.assertEqual(result, receipt)
        self.assertEqual(client.artifacts.commit(result), expected)
        destination = io.BytesIO()
        self.assertEqual(client.artifacts.download(expected, destination), len(content))
        self.assertEqual(destination.getvalue(), content)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "artifact.bin"
            self.assertEqual(client.artifacts.download_file(expected, path), len(content))
            with path.open("rb") as published:
                self.assertEqual(published.read(), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ConflictError) as conflict:
                client.artifacts.download_file(expected, path)
            self.assertEqual(conflict.exception.status, grpc.StatusCode.ALREADY_EXISTS)
            with path.open("rb") as published:
                self.assertEqual(published.read(), content)
            self.assertFalse(
                any(entry.name.startswith(".mindclade-download-") for entry in root.iterdir())
            )

            committed = root / "committed-despite-cleanup-error.bin"
            original_unlink = Path.unlink

            def fail_staging_unlink(value: Path, *args: Any, **kwargs: Any) -> None:
                if value.name.startswith(".mindclade-download-"):
                    raise OSError("simulated staging cleanup failure")
                original_unlink(value, *args, **kwargs)

            with (
                patch.object(
                    artifacts_module,
                    "_sync_directory",
                    side_effect=OSError("simulated directory sync failure"),
                ),
                patch.object(Path, "unlink", fail_staging_unlink),
            ):
                self.assertEqual(client.artifacts.download_file(expected, committed), len(content))
            self.assertEqual(committed.read_bytes(), content)
            for entry in root.iterdir():
                if entry.name.startswith(".mindclade-download-"):
                    entry.unlink()
        self.assertEqual(len(contexts), chunk_index + 3)
        self.assertEqual(len(contexts), len(set(contexts)))

    def test_artifact_transfer_resume_status_abort_quarantine_and_corruption(self) -> None:
        content = b"resume-this-artifact"
        expected = transfer_artifact(content)
        receipt = staging_receipt(expected)
        transport = FakeSyncTransport()
        resumed_chunks: list[artifact_service_pb2.UploadArtifactChunkRequest] = []
        resume_offset = 7

        transport.unary_handlers[BEGIN_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.BeginArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    offset=resume_offset,
                    chunk_index=1,
                    revision=2,
                    etag="etag-resume",
                )
            )
        )

        def chunk(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(artifact_service_pb2.UploadArtifactChunkRequest, request)
            clone = artifact_service_pb2.UploadArtifactChunkRequest()
            clone.CopyFrom(typed)
            resumed_chunks.append(clone)
            offset = typed.offset + len(typed.data)
            return artifact_service_pb2.UploadArtifactChunkResponse(
                upload=upload_session(
                    expected,
                    offset=offset,
                    chunk_index=typed.chunk_index + 1,
                    revision=typed.chunk_index + 2,
                    etag=f"etag-{typed.chunk_index + 1}",
                )
            )

        transport.unary_handlers[UPLOAD_ARTIFACT_CHUNK] = chunk
        transport.unary_handlers[FINALIZE_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.FinalizeArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED,
                    offset=len(content),
                    chunk_index=1 + len(resumed_chunks),
                    revision=10,
                    etag="etag-final",
                    receipt=receipt,
                ),
                staging_receipt=receipt,
            )
        )

        def get_upload(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(artifact_service_pb2.GetArtifactUploadRequest, request)
            if typed.name.endswith("/resume-01"):
                return artifact_service_pb2.GetArtifactUploadResponse(
                    upload=upload_session(
                        expected,
                        name=typed.name,
                        offset=resume_offset,
                        chunk_index=1,
                        revision=2,
                        etag="etag-resume",
                    )
                )
            return artifact_service_pb2.GetArtifactUploadResponse(
                upload=upload_session(expected, etag="etag-status")
            )

        transport.unary_handlers[GET_ARTIFACT_UPLOAD] = get_upload
        transport.unary_handlers[ABORT_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.AbortArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_ABORTED,
                    etag="etag-aborted",
                )
            )
        )
        transport.unary_handlers[QUARANTINE_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.QuarantineArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_QUARANTINED,
                    etag="etag-quarantined",
                )
            )
        )
        transport.stream_handlers[DOWNLOAD_ARTIFACT] = lambda request, timeout, metadata: [
            artifact_service_pb2.DownloadArtifactResponse(
                artifact=expected,
                offset=0,
                data=content,
                chunk_digest="sha256:" + "0" * 64,
                complete=True,
            )
        ]
        client = Client(secure_config(), transport=transport)
        self.assertEqual(
            client.artifacts.upload(
                expected,
                io.BytesIO(content),
                upload_id="resume-01",
                chunk_bytes=4,
            ),
            receipt,
        )
        self.assertEqual(resumed_chunks[0].offset, resume_offset)
        self.assertEqual(b"".join(chunk.data for chunk in resumed_chunks), content[resume_offset:])
        status = client.artifacts.get_upload(upload_session(expected).name)
        self.assertEqual(status.etag, "etag-status")
        self.assertEqual(
            client.artifacts.abort_upload(
                status.name, status.etag, reason_code="CALLER_CANCELLED"
            ).state,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_ABORTED,
        )
        self.assertEqual(
            client.artifacts.quarantine_upload(
                status.name, status.etag, reason_code="DIGEST_MISMATCH"
            ).state,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_QUARANTINED,
        )
        with self.assertRaises(ProtocolError) as raised:
            list(client.artifacts.iter_download(expected))
        self.assertEqual(raised.exception.status, grpc.StatusCode.DATA_LOSS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "corrupt.bin"
            with self.assertRaises(ProtocolError):
                client.artifacts.download_file(expected, path)
            self.assertFalse(path.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_artifact_upload_resumes_across_fresh_client_without_new_expiry_digest(
        self,
    ) -> None:
        content = b"cross-process-resume"
        expected = transfer_artifact(content)
        receipt = staging_receipt(expected)
        transport = FakeSyncTransport()
        durable: artifact_service_pb2.ArtifactUploadSession | None = None
        begin_expiry: Timestamp | None = None
        begin_count = 0
        get_count = 0

        def get_upload(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal get_count
            get_count += 1
            if durable is None:
                raise FakeRpcError(grpc.StatusCode.NOT_FOUND)
            return artifact_service_pb2.GetArtifactUploadResponse(upload=durable)

        def begin(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            nonlocal begin_count, begin_expiry, durable
            begin_count += 1
            typed = cast(artifact_service_pb2.BeginArtifactUploadRequest, request)
            begin_expiry = Timestamp()
            begin_expiry.CopyFrom(typed.expire_time)
            durable = upload_session(expected)
            return artifact_service_pb2.BeginArtifactUploadResponse(upload=durable)

        def chunk(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            nonlocal durable
            typed = cast(artifact_service_pb2.UploadArtifactChunkRequest, request)
            durable = upload_session(
                expected,
                offset=typed.offset + len(typed.data),
                chunk_index=typed.chunk_index + 1,
                revision=typed.chunk_index + 2,
                etag=f"etag-{typed.chunk_index + 2}",
            )
            return artifact_service_pb2.UploadArtifactChunkResponse(upload=durable)

        def finalize(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal durable
            durable = upload_session(
                expected,
                state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED,
                offset=len(content),
                chunk_index=5,
                revision=7,
                etag="etag-final",
                receipt=receipt,
            )
            return artifact_service_pb2.FinalizeArtifactUploadResponse(
                upload=durable,
                staging_receipt=receipt,
            )

        transport.unary_handlers[GET_ARTIFACT_UPLOAD] = get_upload
        transport.unary_handlers[BEGIN_ARTIFACT_UPLOAD] = begin
        transport.unary_handlers[UPLOAD_ARTIFACT_CHUNK] = chunk
        transport.unary_handlers[FINALIZE_ARTIFACT_UPLOAD] = finalize
        first_client = Client(secure_config(), transport=transport)
        with self.assertRaisesRegex(ValueError, "ended before"):
            first_client.artifacts.upload(
                expected,
                io.BytesIO(content[:4]),
                upload_id="process-boundary-01",
                chunk_bytes=4,
            )
        self.assertEqual(durable.committed_offset if durable else -1, 4)
        self.assertIsNotNone(begin_expiry)

        second_client = Client(secure_config(), transport=transport)
        result = second_client.artifacts.upload(
            expected,
            io.BytesIO(content),
            upload_id="process-boundary-01",
            chunk_bytes=4,
        )
        self.assertEqual(result, receipt)
        self.assertEqual(begin_count, 1)
        self.assertGreaterEqual(get_count, 2)

    def test_pre_cancelled_wait_performs_no_rpc(self) -> None:
        transport = FakeSyncTransport()
        cancellation = threading.Event()
        cancellation.set()
        client = Client(secure_config(), transport=transport)
        with self.assertRaises(CancelledError):
            client.operations.wait("operations/01", cancellation=cancellation)
        self.assertEqual(transport.calls, [])

    def test_async_provider_is_rejected_by_sync_client_before_transport(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_TRAINING_RUN] = lambda request, timeout, metadata: (
            training_service_pb2.GetTrainingRunResponse(
                training_run=training_run_pb2.TrainingRun(name="trainingRuns/01")
            )
        )
        client = Client(secure_config(asynchronous=True), transport=transport)
        with self.assertRaisesRegex(ConfigurationError, "synchronous token provider"):
            client.training.get("trainingRuns/01")
        self.assertEqual(transport.calls, [])

    def test_sync_credential_failures_are_sanitized_before_transport(self) -> None:
        class FailingCredentials:
            def get_token(self, *, timeout: float) -> AccessToken:
                del timeout
                raise RuntimeError("secret-provider-payload")

        config = replace(secure_config(), token_provider=FailingCredentials())
        transport = FakeSyncTransport()
        client = Client(config, transport=transport)
        with self.assertRaises(AuthenticationError) as raised:
            client.training.get("trainingRuns/01")
        self.assertNotIn("secret-provider-payload", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(raised.exception.request_id is not None, True)
        self.assertEqual(transport.calls, [])

    def test_sync_credentials_receive_and_enforce_remaining_deadline(self) -> None:
        observed: list[float] = []

        class DeadlineCredentials:
            def get_token(self, *, timeout: float) -> AccessToken:
                observed.append(timeout)
                raise TimeoutError

        config = replace(secure_config(), token_provider=DeadlineCredentials())
        transport = FakeSyncTransport()
        client = Client(config, transport=transport)
        with self.assertRaises(DeadlineExceededError) as raised:
            client.training.get(
                "trainingRuns/01",
                options=CallOptions(timeout=0.05, request_id="sync-deadline"),
            )
        self.assertEqual(len(observed), 1)
        self.assertGreater(observed[0], 0)
        self.assertLessEqual(observed[0], 0.05)
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(transport.calls, [])

    def test_missing_generated_resources_fail_as_protocol_data_loss(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_OPERATION] = lambda request, timeout, metadata: (
            job_service_pb2.GetOperationResponse()
        )
        transport.unary_handlers[GET_TRAINING_RUN] = lambda request, timeout, metadata: (
            training_service_pb2.GetTrainingRunResponse()
        )
        transport.unary_handlers[RESOLVE_ARTIFACT_ALIAS] = lambda request, timeout, metadata: (
            artifact_service_pb2.ResolveArtifactAliasResponse()
        )
        client = Client(secure_config(), transport=transport)
        for call in (
            lambda: client.operations.get("operations/01"),
            lambda: client.training.get("trainingRuns/01"),
            lambda: client.artifacts.resolve_alias("latest"),
        ):
            with self.assertRaises(ProtocolError) as raised:
                call()
            self.assertEqual(raised.exception.status, grpc.StatusCode.DATA_LOSS)

    def test_failed_operation_wait_raises_typed_error_with_generated_state(self) -> None:
        transport = FakeSyncTransport()
        failed = operation_pb2.Operation(
            operation_id="operations/failed",
            state=operation_pb2.OPERATION_STATE_FAILED,
            done=True,
        )
        transport.unary_handlers[GET_OPERATION] = lambda request, timeout, metadata: (
            job_service_pb2.GetOperationResponse(operation=failed)
        )
        client = Client(secure_config(), transport=transport)
        with self.assertRaises(OperationFailedError) as raised:
            client.operations.wait("operations/failed", timeout=1)
        self.assertEqual(raised.exception.operation, failed)
        failed.operation_id = "mutated-after-return"
        self.assertEqual(raised.exception.operation.operation_id, "operations/failed")

    def test_watch_resumes_from_last_sequence_and_raw_flag_cannot_promote_mutation(self) -> None:
        transport = FakeSyncTransport()
        seen_after: list[int] = []

        def stream(request: Message, timeout: float, metadata: Metadata) -> list[Message]:
            del timeout, metadata
            typed = cast(job_service_pb2.WatchOperationRequest, request)
            seen_after.append(typed.after_sequence)
            state = (
                operation_pb2.OPERATION_STATE_RUNNING
                if typed.after_sequence == 0
                else operation_pb2.OPERATION_STATE_SUCCEEDED
            )
            sequence = typed.after_sequence + 1
            return [
                job_service_pb2.WatchOperationResponse(
                    sequence=sequence,
                    operation=operation_pb2.Operation(
                        operation_id="operations/01",
                        state=state,
                        done=state == operation_pb2.OPERATION_STATE_SUCCEEDED,
                    ),
                )
            ]

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = Client(secure_config(), transport=transport)
        events = list(client.operations.watch("operations/01", timeout=1))
        self.assertEqual([event.sequence for event in events], [1, 2])
        self.assertEqual(seen_after, [0, 1])

        with self.assertRaisesRegex(ValueError, "cannot promote"):
            client.generated.unary(
                "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun",
                training_service_pb2.CompleteTrainingRunRequest(),
                options=CallOptions(idempotency_key="raw-key"),
                idempotent=True,
            )


class AsyncClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_async_pagination_preserves_opaque_tokens(self) -> None:
        seen: list[str] = []

        async def fetch(token: str) -> tuple[tuple[int, ...], str]:
            seen.append(token)
            return ((1,), " next token ") if len(seen) == 1 else ((2,), "")

        self.assertEqual(
            [item async for item in apaginate(fetch, initial_page_token=" initial token ")],
            [1, 2],
        )
        self.assertEqual(seen, [" initial token ", " next token "])

    async def test_async_services_retry_wait_and_close_without_blocking_adapter(self) -> None:
        transport = FakeAsyncTransport()
        attempts = 0

        def get_operation(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)
            return job_service_pb2.GetOperationResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/async",
                    state=operation_pb2.OPERATION_STATE_SUCCEEDED,
                    done=True,
                )
            )

        captured: list[training_service_pb2.CreateTrainingRunRequest] = []

        def submit(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            captured.append(cast(training_service_pb2.CreateTrainingRunRequest, request))
            return training_service_pb2.CreateTrainingRunResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/submitted",
                    state=operation_pb2.OPERATION_STATE_PENDING,
                )
            )

        transport.unary_handlers[GET_OPERATION] = get_operation
        transport.unary_handlers[CREATE_TRAINING_RUN] = submit
        transport.unary_handlers[RESOLVE_ARTIFACT_ALIAS] = lambda request, timeout, metadata: (
            artifact_service_pb2.ResolveArtifactAliasResponse(artifact=artifact("3"))
        )
        client = AsyncClient(secure_config(asynchronous=True), transport=transport)
        operation = await client.training.submit(
            "async-run",
            training_recipe=artifact(),
            dataset_release=resource("datasetReleases/data"),
            model_release=resource("modelReleases/model"),
        )
        self.assertIsInstance(operation, operation_pb2.Operation)
        self.assertTrue(captured[0].command.context.idempotency_key)
        terminal = await client.operations.wait("operations/async", timeout=1)
        self.assertTrue(terminal.done)
        self.assertEqual(attempts, 2)
        resolved = await client.artifacts.resolve_alias("latest")
        self.assertEqual(resolved.digest, "sha256:" + "3" * 64)
        await client.close()
        await client.close()
        self.assertTrue(transport.closed)

    async def test_async_artifact_transfer_uses_generated_unary_and_stream_clients(
        self,
    ) -> None:
        content = b"async-generated-artifact"
        expected = transfer_artifact(content)
        receipt = staging_receipt(expected)
        transport = FakeAsyncTransport()
        offset = 0
        chunk_index = 0

        transport.unary_handlers[BEGIN_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.BeginArtifactUploadResponse(upload=upload_session(expected))
        )

        def missing_upload(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.NOT_FOUND)

        transport.unary_handlers[GET_ARTIFACT_UPLOAD] = missing_upload

        def chunk(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            nonlocal offset, chunk_index
            typed = cast(artifact_service_pb2.UploadArtifactChunkRequest, request)
            self.assertEqual(typed.offset, offset)
            offset += len(typed.data)
            chunk_index += 1
            return artifact_service_pb2.UploadArtifactChunkResponse(
                upload=upload_session(
                    expected,
                    offset=offset,
                    chunk_index=chunk_index,
                    revision=chunk_index + 1,
                    etag=f"etag-{chunk_index + 1}",
                )
            )

        transport.unary_handlers[UPLOAD_ARTIFACT_CHUNK] = chunk
        transport.unary_handlers[FINALIZE_ARTIFACT_UPLOAD] = lambda request, timeout, metadata: (
            artifact_service_pb2.FinalizeArtifactUploadResponse(
                upload=upload_session(
                    expected,
                    state=artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED,
                    offset=len(content),
                    chunk_index=chunk_index,
                    revision=chunk_index + 2,
                    etag="etag-final",
                    receipt=receipt,
                ),
                staging_receipt=receipt,
            )
        )
        transport.unary_handlers[COMMIT_ARTIFACT] = lambda request, timeout, metadata: (
            artifact_service_pb2.CommitArtifactResponse(artifact=expected)
        )

        async def source() -> AsyncIterator[bytes]:
            yield content[:3]
            yield content[3:11]
            yield content[11:]

        async def download(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            position = 0
            while position < len(content):
                data = content[position : position + 6]
                yield artifact_service_pb2.DownloadArtifactResponse(
                    artifact=expected,
                    offset=position,
                    data=data,
                    chunk_digest="sha256:" + hashlib.sha256(data).hexdigest(),
                    complete=position + len(data) == len(content),
                )
                position += len(data)

        transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
        client = AsyncClient(secure_config(asynchronous=True), transport=transport)
        result = await client.artifacts.upload(
            expected,
            source(),
            upload_id="async-upload-01",
            chunk_bytes=5,
        )
        self.assertEqual(result, receipt)
        self.assertEqual(await client.artifacts.commit(result), expected)
        downloaded = b"".join([chunk async for chunk in client.artifacts.iter_download(expected)])
        self.assertEqual(downloaded, content)
        destination = io.BytesIO()
        self.assertEqual(await client.artifacts.download(expected, destination), len(content))
        self.assertEqual(destination.getvalue(), content)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "artifact.bin"
            self.assertEqual(await client.artifacts.download_file(expected, path), len(content))
            with path.open("rb") as published:
                self.assertEqual(published.read(), content)
            with self.assertRaises(ConflictError) as conflict:
                await client.artifacts.download_file(expected, path)
            self.assertEqual(conflict.exception.status, grpc.StatusCode.ALREADY_EXISTS)
            with path.open("rb") as published:
                self.assertEqual(published.read(), content)
            self.assertFalse(
                any(entry.name.startswith(".mindclade-download-") for entry in root.iterdir())
            )

            committed = root / "async-committed-despite-cleanup-error.bin"
            original_unlink = Path.unlink

            def fail_staging_unlink(value: Path, *args: Any, **kwargs: Any) -> None:
                if value.name.startswith(".mindclade-download-"):
                    raise OSError("simulated staging cleanup failure")
                original_unlink(value, *args, **kwargs)

            with (
                patch.object(
                    artifacts_module,
                    "_sync_directory",
                    side_effect=OSError("simulated directory sync failure"),
                ),
                patch.object(Path, "unlink", fail_staging_unlink),
            ):
                self.assertEqual(
                    await client.artifacts.download_file(expected, committed), len(content)
                )
            self.assertEqual(committed.read_bytes(), content)
            for entry in root.iterdir():
                if entry.name.startswith(".mindclade-download-"):
                    entry.unlink()

            started = asyncio.Event()

            async def stalled_download(
                request: Message, timeout: float, metadata: Metadata
            ) -> AsyncIterator[Message]:
                del request, timeout, metadata
                data = content[:5]
                yield artifact_service_pb2.DownloadArtifactResponse(
                    artifact=expected,
                    offset=0,
                    data=data,
                    chunk_digest="sha256:" + hashlib.sha256(data).hexdigest(),
                )
                started.set()
                await asyncio.sleep(60)

            transport.stream_handlers[DOWNLOAD_ARTIFACT] = stalled_download
            cancelled_path = root / "cancelled.bin"
            task = asyncio.create_task(client.artifacts.download_file(expected, cancelled_path))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(cancelled_path.exists())
            self.assertFalse(
                any(entry.name.startswith(".mindclade-download-") for entry in root.iterdir())
            )

    async def test_async_wait_and_watch_honor_cancellation(self) -> None:
        transport = FakeAsyncTransport()
        cancellation = asyncio.Event()
        cancellation.set()
        client = AsyncClient(secure_config(asynchronous=True), transport=transport)
        with self.assertRaises(CancelledError):
            await client.operations.wait("operations/01", cancellation=cancellation)

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            yield job_service_pb2.WatchOperationResponse(sequence=1)

        transport.stream_handlers[WATCH_OPERATION] = stream
        with self.assertRaises(CancelledError):
            async for _ in client.operations.watch("operations/01", cancellation=cancellation):
                self.fail("cancelled watch yielded a response")
        self.assertFalse(any(call.method == WATCH_OPERATION for call in transport.calls))

    async def test_sync_provider_is_rejected_by_async_client_before_transport(self) -> None:
        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_TRAINING_RUN] = lambda request, timeout, metadata: (
            training_service_pb2.GetTrainingRunResponse(
                training_run=training_run_pb2.TrainingRun(name="trainingRuns/01")
            )
        )
        client = AsyncClient(secure_config(), transport=transport)
        with self.assertRaisesRegex(ConfigurationError, "async token provider"):
            await client.training.get("trainingRuns/01")

    async def test_async_credential_acquisition_consumes_the_call_deadline(self) -> None:
        class SlowCredentials:
            async def get_token(self, *, timeout: float) -> AccessToken:
                del timeout
                await asyncio.sleep(0.1)
                return AccessToken(
                    "too-late-token",
                    datetime.now(UTC) + timedelta(minutes=5),
                )

        config = replace(secure_config(asynchronous=True), token_provider=SlowCredentials())
        transport = FakeAsyncTransport()
        client = AsyncClient(config, transport=transport)
        with self.assertRaises(DeadlineExceededError):
            await client.training.get(
                "trainingRuns/01",
                options=CallOptions(timeout=0.001, request_id="deadline-request"),
            )
        self.assertEqual(transport.calls, [])

    async def test_async_credential_failures_are_sanitized_before_transport(self) -> None:
        class FailingCredentials:
            async def get_token(self, *, timeout: float) -> AccessToken:
                del timeout
                raise RuntimeError("secret-provider-payload")

        config = replace(secure_config(asynchronous=True), token_provider=FailingCredentials())
        transport = FakeAsyncTransport()
        client = AsyncClient(config, transport=transport)
        with self.assertRaises(AuthenticationError) as raised:
            await client.training.get("trainingRuns/01")
        self.assertNotIn("secret-provider-payload", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(transport.calls, [])

    async def test_async_watch_resumes_and_failed_wait_is_typed(self) -> None:
        transport = FakeAsyncTransport()
        seen_after: list[int] = []

        async def stream(
            request: Message,
            timeout: float,
            metadata: Metadata,
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            typed = cast(job_service_pb2.WatchOperationRequest, request)
            seen_after.append(typed.after_sequence)
            state = (
                operation_pb2.OPERATION_STATE_RUNNING
                if typed.after_sequence == 0
                else operation_pb2.OPERATION_STATE_SUCCEEDED
            )
            yield job_service_pb2.WatchOperationResponse(
                sequence=typed.after_sequence + 1,
                operation=operation_pb2.Operation(
                    operation_id="operations/async-watch",
                    state=state,
                    done=state == operation_pb2.OPERATION_STATE_SUCCEEDED,
                ),
            )

        transport.stream_handlers[WATCH_OPERATION] = stream
        transport.unary_handlers[GET_OPERATION] = lambda request, timeout, metadata: (
            job_service_pb2.GetOperationResponse(
                operation=operation_pb2.Operation(
                    operation_id="operations/failed-async",
                    state=operation_pb2.OPERATION_STATE_CANCELLED,
                    done=True,
                )
            )
        )
        client = AsyncClient(secure_config(asynchronous=True), transport=transport)
        events = [
            event
            async for event in client.operations.watch(
                "operations/async-watch",
                timeout=1,
            )
        ]
        self.assertEqual([event.sequence for event in events], [1, 2])
        self.assertEqual(seen_after, [0, 1])
        with self.assertRaises(OperationFailedError):
            await client.operations.wait("operations/failed-async", timeout=1)


class DatasetModelLifecycleTest(unittest.TestCase):
    def test_generated_facades_bind_identity_and_preserve_opaque_pages(self) -> None:
        config = secure_config()
        parent = config.project_parent
        dataset_name = f"{parent}/datasets/dataset-1"
        dataset_release = f"{dataset_name}/releases/v1"
        model_name = f"{parent}/models/model-1"
        model_release = f"{model_name}/releases/v1"
        transport = FakeSyncTransport()
        seen_contexts: list[tuple[str, str]] = []

        def create_dataset(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            typed = cast(dataset_service_pb2.CreateDatasetRequest, request)
            self.assertEqual(typed.command.project.name, parent)
            self.assertIn(("idempotency-key", "dataset-create-1"), metadata)
            seen_contexts.append(
                (typed.command.context.idempotency_key, typed.command.context.principal_id)
            )
            return dataset_service_pb2.CreateDatasetResponse(
                operation=operation_pb2.Operation(operation_id="operations/dataset-create")
            )

        def register_model(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(model_service_pb2.RegisterModelRequest, request)
            self.assertEqual(typed.command.project.name, parent)
            seen_contexts.append(
                (typed.command.context.idempotency_key, typed.command.context.principal_id)
            )
            return model_service_pb2.RegisterModelResponse(
                operation=operation_pb2.Operation(operation_id="operations/model-register")
            )

        def operation(response: Message) -> SyncUnaryHandler:
            def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
                del request, timeout, metadata
                return response

            return handler

        transport.unary_handlers.update(
            {
                CREATE_DATASET: create_dataset,
                GET_DATASET: lambda request, timeout, metadata: (
                    dataset_service_pb2.GetDatasetResponse(
                        dataset=dataset_pb2.Dataset(name=dataset_name)
                    )
                ),
                LIST_DATASETS: lambda request, timeout, metadata: (
                    dataset_service_pb2.ListDatasetsResponse(
                        page=pagination_pb2.PageResponse(next_page_token="opaque-dataset-out")
                    )
                ),
                UPDATE_DATASET: operation(
                    dataset_service_pb2.UpdateDatasetResponse(
                        operation=operation_pb2.Operation(operation_id="operations/dataset-update")
                    )
                ),
                PUBLISH_DATASET_RELEASE: operation(
                    dataset_service_pb2.PublishDatasetReleaseResponse(
                        operation=operation_pb2.Operation(operation_id="operations/dataset-publish")
                    )
                ),
                REVOKE_DATASET_RELEASE: operation(
                    dataset_service_pb2.RevokeDatasetReleaseResponse(
                        operation=operation_pb2.Operation(operation_id="operations/dataset-revoke")
                    )
                ),
                GET_DATASET_RELEASE: lambda request, timeout, metadata: (
                    dataset_service_pb2.GetDatasetReleaseResponse(
                        dataset_release=dataset_release_pb2.DatasetRelease(name=dataset_release)
                    )
                ),
                LIST_DATASET_RELEASES: lambda request, timeout, metadata: (
                    dataset_service_pb2.ListDatasetReleasesResponse(
                        page=pagination_pb2.PageResponse(next_page_token="opaque-release-out")
                    )
                ),
                REGISTER_MODEL: register_model,
                GET_MODEL: lambda request, timeout, metadata: model_service_pb2.GetModelResponse(
                    model=model_pb2.Model(name=model_name)
                ),
                LIST_MODELS: lambda request, timeout, metadata: (
                    model_service_pb2.ListModelsResponse(
                        page=pagination_pb2.PageResponse(next_page_token="opaque-model-out")
                    )
                ),
                REGISTER_MODEL_RELEASE: operation(
                    model_service_pb2.RegisterModelReleaseResponse(
                        operation=operation_pb2.Operation(operation_id="operations/model-release")
                    )
                ),
                GET_MODEL_RELEASE: lambda request, timeout, metadata: (
                    model_service_pb2.GetModelReleaseResponse(
                        model_release=model_release_pb2.ModelRelease(name=model_release)
                    )
                ),
                LIST_MODEL_RELEASES: lambda request, timeout, metadata: (
                    model_service_pb2.ListModelReleasesResponse(
                        page=pagination_pb2.PageResponse(next_page_token="opaque-model-release-out")
                    )
                ),
                PROMOTE_MODEL_RELEASE: operation(
                    model_service_pb2.PromoteModelReleaseResponse(
                        operation=operation_pb2.Operation(operation_id="operations/model-promote")
                    )
                ),
                REVOKE_MODEL_RELEASE: operation(
                    model_service_pb2.RevokeModelReleaseResponse(
                        operation=operation_pb2.Operation(operation_id="operations/model-revoke")
                    )
                ),
            }
        )
        client = Client(config, transport=transport)
        self.assertEqual(
            client.datasets.create(
                dataset_commands_pb2.CreateDatasetCommand(
                    dataset_id="dataset-1",
                    context={"principal_id": "forged"},
                ),
                options=CallOptions(idempotency_key="dataset-create-1"),
            ).operation_id,
            "operations/dataset-create",
        )
        self.assertEqual(client.datasets.get(dataset_name).name, dataset_name)
        self.assertEqual(
            client.datasets.list(
                dataset_service_pb2.ListDatasetsRequest(
                    page=pagination_pb2.PageRequest(page_token="opaque-dataset-in", page_size=25)
                )
            ).page.next_page_token,
            "opaque-dataset-out",
        )
        client.datasets.update(
            dataset_commands_pb2.UpdateDatasetCommand(
                dataset=dataset_pb2.Dataset(name=dataset_name), etag="etag-1"
            )
        )
        client.datasets.publish_release(
            dataset_commands_pb2.PublishDatasetReleaseCommand(
                dataset=resource_reference_pb2.ResourceRef(name=dataset_name), release_id="v1"
            )
        )
        client.datasets.revoke_release(
            dataset_commands_pb2.RevokeDatasetReleaseCommand(
                dataset_release=resource_reference_pb2.ResourceRef(name=dataset_release),
                etag="etag-r",
                reason="superseded",
            )
        )
        self.assertEqual(client.datasets.get_release(dataset_release).name, dataset_release)
        self.assertEqual(
            client.datasets.list_releases(
                dataset_service_pb2.ListDatasetReleasesRequest(parent=dataset_name)
            ).page.next_page_token,
            "opaque-release-out",
        )
        self.assertEqual(
            client.models.register(
                model_commands_pb2.RegisterModelCommand(
                    model_id="model-1", context={"principal_id": "forged"}
                ),
                options=CallOptions(idempotency_key="model-register-1"),
            ).operation_id,
            "operations/model-register",
        )
        self.assertEqual(client.models.get(model_name).name, model_name)
        self.assertEqual(
            client.models.list(
                model_service_pb2.ListModelsRequest(
                    page=pagination_pb2.PageRequest(page_token="opaque-model-in")
                )
            ).page.next_page_token,
            "opaque-model-out",
        )
        client.models.register_release(
            model_commands_pb2.RegisterModelReleaseCommand(
                model=resource_reference_pb2.ResourceRef(name=model_name), release_id="v1"
            )
        )
        self.assertEqual(client.models.get_release(model_release).name, model_release)
        self.assertEqual(
            client.models.list_releases(
                model_service_pb2.ListModelReleasesRequest(parent=model_name)
            ).page.next_page_token,
            "opaque-model-release-out",
        )
        client.models.promote_release(
            model_commands_pb2.PromoteModelReleaseCommand(
                model_release=resource_reference_pb2.ResourceRef(name=model_release), etag="etag-m"
            )
        )
        client.models.revoke_release(
            model_commands_pb2.RevokeModelReleaseCommand(
                model_release=resource_reference_pb2.ResourceRef(name=model_release),
                etag="etag-m2",
                reason="unsafe",
            )
        )
        self.assertEqual(
            seen_contexts,
            [
                ("dataset-create-1", "principal-01"),
                ("model-register-1", "principal-01"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
