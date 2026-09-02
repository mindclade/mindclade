from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from control_plane import (
    AssignmentDeadlineError,
    AssignmentMaterializer,
    AssignmentRejectedError,
    decode_job_requested,
)
from google.protobuf.message import Message
from mindclade_internal_sdk import AsyncClient, ClientConfig, Environment, RetryPolicy
from mindclade_internal_sdk.testing import (
    FakeAsyncTransport,
    artifact_download_fixture,
    artifact_download_request_digest,
    artifact_fixture,
    get_job_request_name,
    job_requested_delivery_fixture,
    job_response_fixture,
)
from mindclade_internal_sdk.transport import DOWNLOAD_ARTIFACT, GET_JOB, Metadata


class _BlockingTransport(FakeAsyncTransport):
    async def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message:
        del method, request, timeout, metadata
        await asyncio.Future()
        raise AssertionError("unreachable")


def _envelope(configuration_digest: str) -> bytes:
    return job_requested_delivery_fixture(configuration_digest)


def _config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="training-worker-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        insecure_for_testing=True,
        retry=RetryPolicy(max_attempts=1, base_delay=0.001, max_delay=0.001),
    )


class AssignmentMaterializerTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_job_and_verified_artifacts_through_sdk(self) -> None:
        configuration = b'{"recipe":"pretrain-v4"}'
        input_data = b"dataset-manifest"
        configuration_artifact = artifact_fixture(configuration)
        input_artifact = artifact_fixture(input_data)
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            self.assertLessEqual(timeout, 1.0)
            self.assertIn(("x-trace-id", "trace-1"), metadata)
            self.assertEqual(get_job_request_name(request), "jobs/job-1")
            return job_response_fixture(
                configuration_artifact,
                input_artifact=input_artifact,
            )

        async def download(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            digest = artifact_download_request_digest(request)
            artifact, content = (
                (configuration_artifact, configuration)
                if digest == configuration_artifact.digest
                else (input_artifact, input_data)
            )
            midpoint = max(1, len(content) // 2)
            offset = 0
            for index, chunk in enumerate((content[:midpoint], content[midpoint:])):
                if not chunk:
                    continue
                yield artifact_download_fixture(
                    artifact,
                    chunk,
                    offset=offset,
                    complete=index == 1 or midpoint == len(content),
                )
                offset += len(chunk)

        transport.unary_handlers[GET_JOB] = get_job
        transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
        client = AsyncClient(_config(), transport=transport)
        with tempfile.TemporaryDirectory() as directory:
            result = await AssignmentMaterializer(client, rpc_timeout=1).materialize(
                _envelope(configuration_artifact.digest), Path(directory), timeout=2
            )
            self.assertEqual(result.configuration_path.parent.name, "job-1")
            self.assertEqual(result.configuration_path.read_bytes(), configuration)
            self.assertEqual(result.input_path and result.input_path.read_bytes(), input_data)
            # Duplicate delivery is idempotent and does not redownload verified local bytes.
            calls = len(transport.calls)
            await AssignmentMaterializer(client, rpc_timeout=1).materialize(
                _envelope(configuration_artifact.digest), Path(directory), timeout=2
            )
            self.assertEqual(len(transport.calls), calls + 1)
        self.assertEqual(
            [call.method for call in transport.calls[:3]],
            [GET_JOB, DOWNLOAD_ARTIFACT, DOWNLOAD_ARTIFACT],
        )

    async def test_rejects_digest_drift_before_artifact_io(self) -> None:
        configuration = artifact_fixture(b"actual")
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration)

        transport.unary_handlers[GET_JOB] = get_job
        client = AsyncClient(_config(), transport=transport)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(AssignmentRejectedError),
        ):
            await AssignmentMaterializer(client).materialize(
                _envelope("sha256:" + "f" * 64), Path(directory)
            )
        self.assertEqual([call.method for call in transport.calls], [GET_JOB])

    async def test_total_deadline_cancels_noncooperative_transport(self) -> None:
        transport = _BlockingTransport()
        client = AsyncClient(_config(), transport=transport)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(AssignmentDeadlineError),
        ):
            await AssignmentMaterializer(client).materialize(
                _envelope("sha256:" + "a" * 64), Path(directory), timeout=0.01
            )

    def test_invalid_envelopes_fail_closed(self) -> None:
        digest = "sha256:" + "a" * 64
        cases = [
            job_requested_delivery_fixture(digest, event_version=2),
            job_requested_delivery_fixture(digest, tenant_id="other"),
            job_requested_delivery_fixture(digest, payload_digest="sha256:" + "0" * 64),
        ]
        for serialized in cases:
            with (
                self.subTest(serialized=serialized[:12]),
                self.assertRaises(AssignmentRejectedError),
            ):
                decode_job_requested(serialized, tenant_id="tenant-1", project_id="project-1")
