from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest import mock

from control_plane import (
    AssignmentDeadlineError,
    AssignmentMaterializer,
    AssignmentRejectedError,
    client_options,
    decode_job_requested,
)
from google.protobuf.message import Message
from mindclade_internal_sdk import (
    AsyncClient,
    AsyncGoogleWorkloadIdentityProvider,
    ClientConfig,
    ConfigurationError,
    ConflictError,
    DeadlineExceededError,
    Environment,
    RetryPolicy,
    config_from_env,
)
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


_WORKER_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_ENVIRONMENT = {
    "MINDCLADE_ENVIRONMENT": "local",
    "MINDCLADE_TENANT_ID": "tenant-1",
    "MINDCLADE_PROJECT_ID": "project-1",
    "MINDCLADE_PRINCIPAL_ID": "training-worker-1",
    "MINDCLADE_ENDPOINT": "127.0.0.1:9443",
}
_SECURE_ENVIRONMENT = {
    "MINDCLADE_ENVIRONMENT": "staging",
    "MINDCLADE_TENANT_ID": "tenant-1",
    "MINDCLADE_PROJECT_ID": "project-1",
    "MINDCLADE_PRINCIPAL_ID": "training-worker-1",
}


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

    async def test_sdk_deadline_surfaces_as_the_single_worker_deadline_error(self) -> None:
        # The SDK owns every per-call deadline. Its DeadlineExceededError does
        # not derive from the builtin TimeoutError, so the worker must map it
        # onto the same surface as its own total-intake budget.
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise DeadlineExceededError("job get exceeded its deadline")

        transport.unary_handlers[GET_JOB] = get_job
        client = AsyncClient(_config(), transport=transport)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(AssignmentDeadlineError) as raised,
        ):
            await AssignmentMaterializer(client).materialize(
                _envelope("sha256:" + "a" * 64), Path(directory)
            )
        self.assertIsInstance(raised.exception.__cause__, DeadlineExceededError)

    async def test_rejects_local_copy_whose_digest_differs(self) -> None:
        configuration_artifact = artifact_fixture(b'{"recipe":"pretrain-v4"}')
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration_artifact)

        transport.unary_handlers[GET_JOB] = get_job
        client = AsyncClient(_config(), transport=transport)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "job-1"
            root.mkdir()
            (root / "configuration.artifact").write_bytes(b"stale bytes")
            with self.assertRaises(AssignmentRejectedError):
                await AssignmentMaterializer(client).materialize(
                    _envelope(configuration_artifact.digest), Path(directory)
                )
        self.assertEqual([call.method for call in transport.calls], [GET_JOB])

    async def test_rejects_artifacts_above_the_worker_intake_ceiling(self) -> None:
        configuration_artifact = artifact_fixture(b'{"recipe":"pretrain-v4"}')
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration_artifact)

        transport.unary_handlers[GET_JOB] = get_job
        client = AsyncClient(_config(), transport=transport)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(AssignmentRejectedError),
        ):
            await AssignmentMaterializer(client, maximum_artifact_bytes=8).materialize(
                _envelope(configuration_artifact.digest), Path(directory)
            )
        self.assertEqual([call.method for call in transport.calls], [GET_JOB])

    async def test_publishes_artifacts_create_only_through_the_sdk(self) -> None:
        content = b'{"recipe":"pretrain-v4"}'
        configuration_artifact = artifact_fixture(content)
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration_artifact)

        async def download(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            yield artifact_download_fixture(configuration_artifact, content)

        transport.unary_handlers[GET_JOB] = get_job
        transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
        client = AsyncClient(_config(), transport=transport)
        with tempfile.TemporaryDirectory() as directory:
            result = await AssignmentMaterializer(client).materialize(
                _envelope(configuration_artifact.digest), Path(directory)
            )
            published = result.configuration_path
            self.assertEqual(published.read_bytes(), content)
            # The SDK publishes a private, create-only file and leaves no
            # staging entry of its own behind.
            self.assertEqual(published.stat().st_mode & 0o777, 0o600)
            self.assertEqual([entry.name for entry in published.parent.iterdir()], [published.name])

    async def test_concurrent_publication_of_matching_bytes_is_idempotent(self) -> None:
        content = b'{"recipe":"pretrain-v4"}'
        configuration_artifact = artifact_fixture(content)
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration_artifact)

        transport.unary_handlers[GET_JOB] = get_job
        client = AsyncClient(_config(), transport=transport)
        with tempfile.TemporaryDirectory() as directory:
            # The materializer publishes under `destination.resolve()`, so the
            # expectation is resolved as well: on macOS tempfile returns /tmp,
            # a symlink to /private/tmp, and an unresolved expectation compares
            # two spellings of the same file.
            published = Path(directory).resolve() / "job-1" / "configuration.artifact"

            async def download(
                request: Message, timeout: float, metadata: Metadata
            ) -> AsyncIterator[Message]:
                del request, timeout, metadata
                # A concurrent delivery publishes the same verified bytes while
                # this download is in flight, so the SDK's create-only
                # publication raises ConflictError.
                published.write_bytes(content)
                yield artifact_download_fixture(configuration_artifact, content)

            transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
            result = await AssignmentMaterializer(client).materialize(
                _envelope(configuration_artifact.digest), Path(directory)
            )
            self.assertEqual(result.configuration_path, published)
            self.assertEqual(published.read_bytes(), content)

    async def test_other_sdk_conflicts_stay_sdk_errors(self) -> None:
        configuration_artifact = artifact_fixture(b'{"recipe":"pretrain-v4"}')
        transport = FakeAsyncTransport()

        def get_job(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            return job_response_fixture(configuration_artifact)

        async def download(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            raise ConflictError("artifact is quarantined")
            yield  # pragma: no cover - unreachable generator body

        transport.unary_handlers[GET_JOB] = get_job
        transport.stream_handlers[DOWNLOAD_ARTIFACT] = download
        client = AsyncClient(_config(), transport=transport)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ConflictError),
        ):
            await AssignmentMaterializer(client).materialize(
                _envelope(configuration_artifact.digest), Path(directory)
            )


class WorkerConfigurationTest(unittest.TestCase):
    def test_local_configuration_comes_from_the_sdk_environment_reader(self) -> None:
        with mock.patch.dict(os.environ, _LOCAL_ENVIRONMENT, clear=True):
            config = config_from_env(**client_options())
        self.assertEqual(config.environment, Environment.LOCAL)
        self.assertEqual(config.tenant_id, "tenant-1")
        self.assertEqual(config.project_id, "project-1")
        self.assertEqual(config.principal_id, "training-worker-1")
        self.assertEqual(config.endpoint, "127.0.0.1:9443")
        self.assertTrue(config.insecure_for_testing)
        self.assertIsNone(config.token_provider)
        self.assertEqual(config.user_agent, "mindclade-training-worker/0.1")

    def test_secure_configuration_binds_workload_identity_to_the_resolved_audience(self) -> None:
        environ = dict(_SECURE_ENVIRONMENT, MINDCLADE_AUDIENCE="https://control.example")
        with mock.patch.dict(os.environ, environ, clear=True):
            config = config_from_env(**client_options())
        self.assertEqual(config.environment, Environment.STAGING)
        self.assertFalse(config.insecure_for_testing)
        self.assertEqual(config.audience, "https://control.example")
        provider = config.token_provider
        self.assertIsInstance(provider, AsyncGoogleWorkloadIdentityProvider)
        self.assertEqual(getattr(provider, "audience", None), "https://control.example")

    def test_audience_defaults_to_the_endpoint_the_sdk_resolved(self) -> None:
        with mock.patch.dict(os.environ, _SECURE_ENVIRONMENT, clear=True):
            config = config_from_env(**client_options())
        self.assertTrue(config.audience and config.audience.startswith("https://"))
        self.assertEqual(getattr(config.token_provider, "audience", None), config.audience)

    def test_missing_identity_fails_through_the_sdk_configuration_error(self) -> None:
        environ = dict(_SECURE_ENVIRONMENT)
        del environ["MINDCLADE_PROJECT_ID"]
        with (
            mock.patch.dict(os.environ, environ, clear=True),
            self.assertRaises(ConfigurationError) as raised,
        ):
            client_options()
        self.assertIn("MINDCLADE_PROJECT_ID", str(raised.exception))


class WorkerBoundaryTest(unittest.TestCase):
    def _sources(self) -> list[Path]:
        return sorted((_WORKER_ROOT / "python").glob("*.py"))

    def test_worker_sources_never_read_the_process_environment(self) -> None:
        for path in self._sources():
            with self.subTest(source=path.name):
                text = path.read_text()
                self.assertNotIn("os.environ", text)
                self.assertNotIn("os.getenv", text)

    def test_worker_never_imports_generated_protocol_packages(self) -> None:
        direct = re.compile(r"^\s*(?:from|import)\s+mindclade\.", re.MULTILINE)
        for path in self._sources():
            with self.subTest(source=path.name):
                self.assertIsNone(direct.search(path.read_text()))

    def test_worker_build_configuration_never_depends_on_generated_protocols(self) -> None:
        """No declared dependency edge may reach the generated bindings directly.

        BUILD.bazel and component.yaml are where such an edge would be written,
        so they must not name the generated tree at all. The worker reaches those
        bindings only transitively, through
        ``//sdks/python:mindclade_internal_sdk``, which is the sanctioned
        direction.
        """

        for name in ("BUILD.bazel", "component.yaml"):
            with self.subTest(configuration=name):
                self.assertNotIn("protocols/generated", (_WORKER_ROOT / name).read_text())

    def test_the_type_checker_resolves_generated_types_only_through_the_facade(self) -> None:
        """The type checker may resolve generated types; it may not add a dependency.

        The facade's public signatures return generated protobuf messages -- the
        SDK README is explicit that those types *are* the models -- so a strict
        type check of a consumer cannot resolve its own call sites without the
        generated root on the search path. That path is a resolution detail, not
        a dependency: it grants no import (``test_worker_never_imports_generated
        _protocol_packages`` still forbids one) and no build edge. It is pinned
        to exactly the one search-path entry so that a future edit cannot smuggle
        a real dependency into this file.
        """

        configuration = json.loads((_WORKER_ROOT / "pyrightconfig.json").read_text())
        generated = [
            value
            for key, value in configuration.items()
            if key != "extraPaths" and "protocols/generated" in json.dumps(value)
        ]
        self.assertEqual(generated, [])
        self.assertEqual(
            [path for path in configuration["extraPaths"] if "protocols/generated" in path],
            ["../../protocols/generated/python"],
        )
