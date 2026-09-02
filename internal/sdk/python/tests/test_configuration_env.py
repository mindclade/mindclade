"""Configuration and escape-hatch tests: environment, metadata, and middleware."""

from __future__ import annotations

import pathlib
import re
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import grpc
from google.protobuf.message import Message
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_pb2
from mindclade_internal_sdk import (
    ENVIRONMENT_VARIABLES,
    AccessToken,
    AsyncClient,
    Client,
    ClientConfig,
    ConfigurationError,
    Environment,
    PlatformMetadata,
    config_from_env,
    is_credential_metadata_key,
)
from mindclade_internal_sdk._env import environment_from_env
from mindclade_internal_sdk._middleware import CredentialShield, shielded
from mindclade_internal_sdk._platform import (
    MAX_USER_AGENT_LENGTH,
    SDK_NAME,
    base_user_agent,
    platform_user_agent,
)
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import GET_JOB, Metadata

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mindclade_internal_sdk"

# Names a credential could plausibly hide behind. None of them may appear
# anywhere in the package: the SDK reads no credential from the environment.
FORBIDDEN_ENVIRONMENT_NAMES = (
    "MINDCLADE_TOKEN",
    "MINDCLADE_API_KEY",
    "MINDCLADE_APIKEY",
    "MINDCLADE_SECRET",
    "MINDCLADE_PASSWORD",
    "MINDCLADE_CREDENTIAL",
    "MINDCLADE_CREDENTIALS",
    "MINDCLADE_ACCESS_TOKEN",
    "MINDCLADE_AUTH",
    "GOOGLE_APPLICATION_CREDENTIALS",
)

FULL_ENVIRONMENT = {
    "MINDCLADE_ENVIRONMENT": "staging",
    "MINDCLADE_ENDPOINT": "control-plane.staging.mindclade.internal:8443",
    "MINDCLADE_TENANT_ID": "tenant-env",
    "MINDCLADE_PROJECT_ID": "project-env",
    "MINDCLADE_PRINCIPAL_ID": "principal-env",
    "MINDCLADE_AUDIENCE": "https://control-plane.staging.mindclade.internal:8443",
    "MINDCLADE_LOG": "info",
}


class StubTokenProvider:
    """A token provider that is only ever supplied explicitly, never by the shell."""

    audience = "https://control-plane.staging.mindclade.internal:8443"

    def get_token(self, *, timeout: float) -> AccessToken:  # pragma: no cover - never called
        del timeout
        raise AssertionError("no test in this module performs a real RPC")


class AsyncStubTokenProvider:
    """The asyncio twin, also only ever supplied explicitly."""

    audience = StubTokenProvider.audience

    async def get_token(self, *, timeout: float) -> AccessToken:  # pragma: no cover - never called
        del timeout
        raise AssertionError("no test in this module performs a real RPC")


def local_config(**overrides: Any) -> ClientConfig:
    settings: dict[str, Any] = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "principal_id": "principal-1",
        "environment": Environment.LOCAL,
        "endpoint": "127.0.0.1:1",
        "insecure_for_testing": True,
        "default_timeout": 1,
    }
    settings.update(overrides)
    return ClientConfig(**settings)


def job_response(request: Message, timeout: float, metadata: Metadata) -> Message:
    del request, timeout, metadata
    return job_service_pb2.GetJobResponse(
        job=job_pb2.Job(
            job_id="jobs/job-1",
            operation_id="operations/op-1",
            tenant_id="tenant-1",
            project_id="project-1",
            state=job_pb2.JOB_STATE_RUNNING,
            resource_version=1,
            etag="etag-1",
        )
    )


class EnvironmentTest(unittest.TestCase):
    def test_from_env_is_the_only_environment_reading_path(self) -> None:
        explicit = local_config()
        # Every recognised variable is set to something different; the ordinary
        # constructor must ignore all of it.
        with mock.patch.dict("os.environ", FULL_ENVIRONMENT, clear=False):
            shadowed = local_config()
        self.assertEqual(shadowed.tenant_id, explicit.tenant_id)
        self.assertEqual(shadowed.project_id, explicit.project_id)
        self.assertEqual(shadowed.principal_id, explicit.principal_id)
        self.assertEqual(shadowed.environment, explicit.environment)
        self.assertEqual(shadowed.endpoint, explicit.endpoint)
        self.assertEqual(shadowed.audience, explicit.audience)

    def test_from_env_recognises_exactly_the_declared_variables(self) -> None:
        self.assertEqual(
            set(ENVIRONMENT_VARIABLES),
            {
                "MINDCLADE_ENVIRONMENT",
                "MINDCLADE_ENDPOINT",
                "MINDCLADE_TENANT_ID",
                "MINDCLADE_PROJECT_ID",
                "MINDCLADE_PRINCIPAL_ID",
                "MINDCLADE_AUDIENCE",
                "MINDCLADE_LOG",
            },
        )

    def test_config_from_env_reads_every_declared_variable(self) -> None:
        config = config_from_env(
            token_provider=StubTokenProvider(),
            environ=FULL_ENVIRONMENT,
        )
        self.assertEqual(config.environment, Environment.STAGING)
        self.assertEqual(config.endpoint, FULL_ENVIRONMENT["MINDCLADE_ENDPOINT"])
        self.assertEqual(config.tenant_id, "tenant-env")
        self.assertEqual(config.project_id, "project-env")
        self.assertEqual(config.principal_id, "principal-env")
        self.assertEqual(config.audience, FULL_ENVIRONMENT["MINDCLADE_AUDIENCE"])

    def test_explicit_overrides_beat_the_environment(self) -> None:
        config = config_from_env(
            token_provider=StubTokenProvider(),
            environ=FULL_ENVIRONMENT,
            project_id="project-override",
        )
        self.assertEqual(config.project_id, "project-override")
        self.assertEqual(config.tenant_id, "tenant-env")

    def test_missing_identity_names_the_variable_and_not_its_value(self) -> None:
        for variable in ("MINDCLADE_TENANT_ID", "MINDCLADE_PROJECT_ID", "MINDCLADE_PRINCIPAL_ID"):
            with self.subTest(variable=variable):
                environ = dict(FULL_ENVIRONMENT)
                del environ[variable]
                with self.assertRaises(ConfigurationError) as raised:
                    config_from_env(token_provider=StubTokenProvider(), environ=environ)
                self.assertIn(variable, str(raised.exception))

    def test_unknown_environment_is_rejected_without_echoing_the_value(self) -> None:
        with self.assertRaises(ConfigurationError) as raised:
            environment_from_env({"MINDCLADE_ENVIRONMENT": "prod-eu-secret-cluster"})
        self.assertNotIn("secret-cluster", str(raised.exception))
        self.assertIn("production", str(raised.exception))

    def test_no_credential_environment_variable_is_recognised(self) -> None:
        environ = dict(FULL_ENVIRONMENT)
        environ.update(dict.fromkeys(FORBIDDEN_ENVIRONMENT_NAMES, "super-secret"))
        # Every plausible credential variable is set, and the SDK still refuses
        # to build a secure client: only an explicit provider can supply one.
        with self.assertRaisesRegex(ConfigurationError, "token provider"):
            config_from_env(environ=environ)
        config = config_from_env(token_provider=StubTokenProvider(), environ=environ)
        self.assertIsInstance(config.token_provider, StubTokenProvider)
        self.assertNotIn("secret", str(config.audience))

    def test_the_package_names_no_credential_environment_variable(self) -> None:
        sources = "\n".join(path.read_text() for path in sorted(PACKAGE_ROOT.glob("*.py")))
        for name in FORBIDDEN_ENVIRONMENT_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, sources)

    def test_only_env_module_and_logging_touch_os_environ(self) -> None:
        readers = {
            path.name
            for path in sorted(PACKAGE_ROOT.glob("*.py"))
            if re.search(r"os\.environ", path.read_text())
        }
        self.assertEqual(readers, {"_env.py", "_logging.py"})

    def test_client_from_env_builds_a_usable_client(self) -> None:
        environ = dict(FULL_ENVIRONMENT)
        environ.pop("MINDCLADE_LOG")
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        with mock.patch.dict("os.environ", environ, clear=True):
            client = Client.from_env(
                token_provider=StubTokenProvider(),
                transport=transport,
            )
        self.assertEqual(client.config.tenant_id, "tenant-env")
        self.assertEqual(client.config.environment, Environment.STAGING)
        client.close()

    def test_async_client_from_env_builds_a_usable_client(self) -> None:
        environ = dict(FULL_ENVIRONMENT)
        environ.pop("MINDCLADE_LOG")
        with mock.patch.dict("os.environ", environ, clear=True):
            client = AsyncClient.from_env(
                token_provider=AsyncStubTokenProvider(),
                transport=FakeAsyncTransport(),
            )
        self.assertEqual(client.config.project_id, "project-env")


class CustomMetadataTest(unittest.TestCase):
    def test_custom_metadata_reaches_every_request(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        client = Client(
            local_config(custom_metadata={"x-team": "platform", "x-run": "nightly"}),
            transport=transport,
        )
        client.jobs.get("job-1")
        keys = transport.calls[0].metadata_keys
        self.assertIn("x-team", keys)
        self.assertIn("x-run", keys)

    def test_custom_metadata_denylist_rejects_credentials(self) -> None:
        for key in (
            "authorization",
            "proxy-authorization",
            "cookie",
            "x-api-key",
            "session-token",
            "client-secret",
            "user-password",
        ):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                local_config(custom_metadata={key: "value"})

    def test_custom_metadata_cannot_shadow_sdk_keys(self) -> None:
        for key in (
            "x-request-id",
            "x-trace-id",
            "idempotency-key",
            "x-mindclade-expected-tenant",
            "x-mindclade-sdk",
        ):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                local_config(custom_metadata={key: "value"})

    def test_custom_metadata_is_bounded_and_well_formed(self) -> None:
        with self.assertRaises(ConfigurationError):
            local_config(custom_metadata={"x-team": "a" * 257})
        with self.assertRaises(ConfigurationError):
            local_config(custom_metadata={"x-team": "line\nbreak"})
        with self.assertRaises(ConfigurationError):
            local_config(custom_metadata={"X Team": "value"})
        with self.assertRaises(ConfigurationError):
            local_config(custom_metadata={"x-team-bin": "value"})
        with self.assertRaises(ConfigurationError):
            local_config(custom_metadata={f"x-key-{index}": "v" for index in range(17)})

    def test_custom_metadata_is_immutable_after_validation(self) -> None:
        source = {"x-team": "platform"}
        config = local_config(custom_metadata=source)
        source["x-team"] = "changed"
        self.assertEqual(dict(config.custom_metadata), {"x-team": "platform"})
        with self.assertRaises(TypeError):
            config.custom_metadata["x-team"] = "changed"  # pyright: ignore[reportIndexIssue]


class PlatformMetadataTest(unittest.TestCase):
    def test_platform_metadata_is_structured_and_bounded(self) -> None:
        value = local_config().user_agent
        self.assertTrue(value.startswith(f"{SDK_NAME}/"))
        self.assertLessEqual(len(value), MAX_USER_AGENT_LENGTH)
        for field in ("lang=", "os=", "arch=", "runtime=", "runtime_version="):
            self.assertIn(field, value)
        self.assertIsNone(re.search(r"[\r\n\x00]", value))

    def test_platform_values_come_from_a_closed_allowlist(self) -> None:
        detected = PlatformMetadata.detect()
        self.assertEqual(detected.language, "python")
        self.assertIn(detected.os, {"linux", "darwin", "windows", "unknown"})
        self.assertIn(detected.arch, {"x86_64", "amd64", "aarch64", "arm64", "unknown"})
        exotic = PlatformMetadata(os="Totally Made Up OS", arch="!!", runtime="???")
        self.assertNotIn("Totally", exotic.encode())

    def test_omit_platform_metadata_emits_only_the_sdk_identity(self) -> None:
        config = local_config(omit_platform_metadata=True)
        self.assertEqual(config.user_agent, base_user_agent())
        self.assertNotIn("os=", config.user_agent)
        self.assertNotEqual(platform_user_agent(), base_user_agent())

    def test_an_explicit_user_agent_is_never_overwritten(self) -> None:
        config = local_config(user_agent="consumer-tool/9.9")
        self.assertEqual(config.user_agent, "consumer-tool/9.9")

    def test_the_sdk_header_is_stamped_on_every_request(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        client = Client(local_config(), transport=transport)
        client.jobs.get("job-1")
        self.assertIn("x-mindclade-sdk", transport.calls[0].metadata_keys)


class RecordingInterceptor(grpc.UnaryUnaryClientInterceptor):
    """A caller interceptor that tries to read and strip the SDK's credentials."""

    def __init__(self) -> None:
        self.observed: list[tuple[str, Any]] = []
        self.forwarded: list[tuple[str, Any]] = []

    def intercept_unary_unary(
        self,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        metadata = list(client_call_details.metadata or ())
        self.observed.extend(metadata)
        stripped: list[tuple[str, Any]] = [
            entry for entry in metadata if entry[0] != "x-mindclade-expected-tenant"
        ]
        stripped.append(("authorization", "Bearer forged-by-middleware"))
        stripped.append(("x-mindclade-lease-token", "forged-lease"))
        details = _CallDetails(client_call_details, tuple(stripped))
        self.forwarded.append(("called", None))
        return continuation(details, request)


class _CallDetails(grpc.ClientCallDetails):
    def __init__(self, source: Any, metadata: tuple[tuple[str, Any], ...]) -> None:
        self.method = source.method
        self.timeout = source.timeout
        self.metadata = metadata
        self.credentials = source.credentials
        self.wait_for_ready = source.wait_for_ready
        self.compression = getattr(source, "compression", None)


class _Continuation:
    """Stands in for the channel, recording what actually goes on the wire."""

    def __init__(self) -> None:
        self.sent: tuple[tuple[str, Any], ...] = ()

    def __call__(self, details: Any, request: Any) -> str:
        del request
        self.sent = tuple(details.metadata or ())
        return "sent"


class _Details(grpc.ClientCallDetails):
    def __init__(self, metadata: tuple[tuple[str, Any], ...]) -> None:
        self.method = "/mindclade.internal.job.v1.JobService/GetJob"
        self.timeout = 1.0
        self.metadata = metadata
        self.credentials = None
        self.wait_for_ready = None
        self.compression = None


class MiddlewareTest(unittest.TestCase):
    def outgoing(self) -> tuple[tuple[str, Any], ...]:
        return (
            ("x-mindclade-expected-tenant", "tenant-1"),
            ("x-request-id", "request-1"),
            ("authorization", "Bearer sdk-issued"),
            ("x-mindclade-lease-token", "sdk-lease"),
        )

    def test_middleware_cannot_read_or_strip_credentials(self) -> None:
        interceptor = RecordingInterceptor()
        shield = CredentialShield(interceptor)
        continuation = _Continuation()
        result = shield.intercept_unary_unary(continuation, _Details(self.outgoing()), object())
        self.assertEqual(result, "sent")
        observed_keys = {key for key, _ in interceptor.observed}
        self.assertNotIn("authorization", observed_keys)
        self.assertNotIn("x-mindclade-lease-token", observed_keys)
        self.assertIn("x-request-id", observed_keys)
        sent = dict(continuation.sent)
        # The SDK's own credentials go out untouched, and the interceptor's
        # forged replacements never reach the wire.
        self.assertEqual(sent["authorization"], "Bearer sdk-issued")
        self.assertEqual(sent["x-mindclade-lease-token"], "sdk-lease")
        # Non-credential edits the interceptor made are still honoured.
        self.assertNotIn("x-mindclade-expected-tenant", sent)

    def test_a_shield_without_a_matching_hook_passes_the_call_through(self) -> None:
        class StreamOnly(grpc.UnaryStreamClientInterceptor):
            def intercept_unary_stream(
                self,
                continuation: Callable[[Any, Any], Any],
                client_call_details: Any,
                request: Any,
            ) -> Any:  # pragma: no cover - not exercised here
                return continuation(client_call_details, request)

        continuation = _Continuation()
        shield = CredentialShield(StreamOnly())
        shield.intercept_unary_unary(continuation, _Details(self.outgoing()), object())
        self.assertEqual(dict(continuation.sent)["authorization"], "Bearer sdk-issued")

    def test_middleware_must_be_an_interceptor(self) -> None:
        with self.assertRaises(ConfigurationError):
            local_config(middleware=[object()])
        with self.assertRaises(ConfigurationError):
            local_config(middleware=[RecordingInterceptor()] * 9)

    def test_valid_middleware_is_accepted_and_shielded(self) -> None:
        interceptor = RecordingInterceptor()
        config = local_config(middleware=[interceptor])
        self.assertEqual(tuple(config.middleware), (interceptor,))
        wrapped = shielded(config.middleware)
        self.assertEqual(len(wrapped), 1)
        self.assertIsInstance(wrapped[0], CredentialShield)

    def test_credential_predicate_covers_every_shielded_key(self) -> None:
        for key in ("authorization", "x-mindclade-lease-token", "set-cookie", "x-api-key"):
            self.assertTrue(is_credential_metadata_key(key))


if __name__ == "__main__":
    unittest.main()
