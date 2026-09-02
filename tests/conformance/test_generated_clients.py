from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import unittest
from collections.abc import Iterable, MutableSequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import yaml
from google.protobuf.descriptor import FieldDescriptor, FileDescriptor, MethodDescriptor
from google.protobuf.message import Message


class NamedRequest(Protocol):
    name: str


class EventEnvelopeLike(Protocol):
    event_type: str
    event_version: int
    payload_content_type: str
    payload_digest: str

    def SerializeToString(  # noqa: N802
        self, *, deterministic: bool = False
    ) -> bytes: ...


class EventEnvelopeType(Protocol):
    def FromString(self, data: bytes) -> EventEnvelopeLike: ...  # noqa: N802


class HttpRuleLike(Protocol):
    body: str

    def WhichOneof(self, oneof_group: str) -> str | None: ...  # noqa: N802


class PublicHttpContractLike(Protocol):
    bearer_auth: bool
    success_status: Iterable[int]
    request_headers: Iterable[str]
    stream: int


def object_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"{context} must be an object with string keys")
    raw_mapping = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw_mapping):
        raise AssertionError(f"{context} must be an object with string keys")
    return cast(dict[str, object], raw_mapping)


def object_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise AssertionError(f"{context} must be a list")
    return cast(list[object], value)


def string_value(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"{context} must be a string")
    return value


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "generated").is_dir():
            return candidate
    raise RuntimeError("cannot locate generated protocol bindings")


class GeneratedClientsContractTest(unittest.TestCase):
    def test_every_json_schema_fixture_has_native_python_conformance(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        bindings = importlib.import_module("mindclade.schema.v1.bindings")
        bindings.assert_fixture_conformance()

    def test_every_declared_python_package_round_trips_a_populated_message(
        self,
    ) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        json_format = importlib.import_module("google.protobuf.json_format")
        matrix = json.loads((repository / "tests/conformance/contract_matrix.yaml").read_text())

        def scalar_value(field: FieldDescriptor) -> object:
            if field.type == FieldDescriptor.TYPE_STRING:
                return "fixture"
            if field.type == FieldDescriptor.TYPE_BYTES:
                return b"fixture"
            if field.type == FieldDescriptor.TYPE_BOOL:
                return True
            if field.type == FieldDescriptor.TYPE_ENUM:
                assert field.enum_type is not None
                values = field.enum_type.values
                return values[1].number if len(values) > 1 else values[0].number
            if field.type in (
                FieldDescriptor.TYPE_DOUBLE,
                FieldDescriptor.TYPE_FLOAT,
            ):
                return 1.25
            return 7

        def populate(message: Message, depth: int = 0) -> bool:
            for field in message.DESCRIPTOR.fields:
                if field.is_repeated:
                    continue
                if field.type == FieldDescriptor.TYPE_MESSAGE:
                    continue
                setattr(message, field.name, scalar_value(cast(FieldDescriptor, field)))
                return True
            for field in message.DESCRIPTOR.fields:
                if not field.is_repeated or field.type == FieldDescriptor.TYPE_MESSAGE:
                    continue
                repeated = cast(MutableSequence[object], getattr(message, field.name))
                repeated.append(scalar_value(cast(FieldDescriptor, field)))
                return True
            if depth < 8:
                for field in message.DESCRIPTOR.fields:
                    if field.is_repeated or field.type != FieldDescriptor.TYPE_MESSAGE:
                        continue
                    child = cast(Message, getattr(message, field.name))
                    if populate(child, depth + 1):
                        return True
            return False

        for declaration in matrix["protobuf_packages"]:
            package = declaration["name"]
            with self.subTest(package=package):
                module = importlib.import_module(declaration["module"])
                message_type = cast(type[Message], getattr(module, declaration["message"]))
                original = message_type()
                self.assertEqual(original.DESCRIPTOR.file.package, package)
                self.assertTrue(
                    populate(original),
                    f"{original.DESCRIPTOR.full_name} has no populatable scalar field",
                )
                self.assertTrue(original.ListFields())

                wire = original.SerializeToString(deterministic=True)
                self.assertTrue(wire)
                wire_decoded = message_type.FromString(wire)
                self.assertEqual(original, wire_decoded)

                json_payload = json_format.MessageToJson(original)
                json_decoded = message_type()
                json_format.Parse(json_payload, json_decoded)
                self.assertEqual(original, json_decoded)

    def test_public_grpc_facade_executes_a_loopback_rpc(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))

        grpc = importlib.import_module("grpc")
        api = importlib.import_module("mindclade.api.v1.mindclade_service_pb2")
        api_grpc = importlib.import_module("mindclade.api.v1.mindclade_service_pb2_grpc")

        class Servicer(api_grpc.MindcladeServiceServicer):
            def GetOperation(  # noqa: N802
                self, request: NamedRequest, context: object
            ) -> object:
                del context
                return api.Operation(
                    name=request.name,
                    uid="operation-uid",
                    state="RUNNING",
                    revision=3,
                    etag='"operation-3"',
                )

        server = grpc.server(ThreadPoolExecutor(max_workers=1))
        api_grpc.add_MindcladeServiceServicer_to_server(Servicer(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        self.assertGreater(port, 0)
        server.start()
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                grpc.channel_ready_future(channel).result(timeout=5)
                response = api_grpc.MindcladeServiceStub(channel).GetOperation(
                    api.GetResourceRequest(
                        name="tenants/tenant_1/projects/project_1/operations/op_1"
                    ),
                    timeout=5,
                )
            self.assertEqual(response.name, "tenants/tenant_1/projects/project_1/operations/op_1")
            self.assertEqual(response.state, "RUNNING")
            self.assertEqual(response.revision, 3)
        finally:
            server.stop(grace=None).wait(timeout=5)

    def test_generated_bindings_are_current_and_compilable(self) -> None:
        repository = root()
        subprocess.run(
            [sys.executable, "tools/codegen/verify_generated_drift.py", "--root", "."],
            cwd=repository,
            check=True,
        )
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        generated_python = repository / "protocols/generated/python"
        modules = sorted(
            ".".join(path.relative_to(generated_python).with_suffix("").parts)
            for path in generated_python.glob("**/*_pb2.py")
        )
        self.assertTrue(modules)
        imported = {name: importlib.import_module(name) for name in modules}
        module = imported["mindclade.common.v1.identifiers_pb2"]
        self.assertEqual(module.Identifiers(tenant_id="tenant").tenant_id, "tenant")
        if "TEST_SRCDIR" not in os.environ:
            subprocess.run(
                ["go", "test", "./protocols/generated/go/..."], cwd=repository, check=True
            )
            subprocess.run(
                ["cargo", "test", "--locked", "-p", "mindclade-protocols"],
                cwd=repository,
                check=True,
            )
        typescript = (
            repository / "protocols/generated/typescript/common/v1/identifiers_pb.ts"
        ).read_text()
        self.assertIn(
            'export type Identifiers = Message<"mindclade.common.v1.Identifiers"> & {',
            typescript,
        )
        self.assertIn(
            "export const IdentifiersSchema: GenMessage<Identifiers> = /*@__PURE__*/",
            typescript,
        )

    def test_python_foundations_consume_generated_contract_types(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        sys.path.insert(0, str(repository / "libs/python"))

        artifact_module = importlib.import_module("mindclade.artifact.v1.artifact_reference_pb2")
        evidence_module = importlib.import_module("mindclade.artifact.v1.evidence_reference_pb2")
        resource_module = importlib.import_module("mindclade.common.v1.resource_reference_pb2")
        artifacts = importlib.import_module("artifacts")
        contracts = importlib.import_module("contracts")
        identifiers = importlib.import_module("identifiers")
        serialization = importlib.import_module("serialization")

        self.assertIs(artifacts.ArtifactRef, artifact_module.ArtifactRef)
        self.assertIs(artifacts.EvidenceRef, evidence_module.EvidenceRef)
        self.assertEqual(
            contracts.ErrorDetail.DESCRIPTOR.full_name,
            "mindclade.common.v1.ErrorDetail",
        )
        error_module = importlib.import_module("mindclade.common.v1.error_detail_pb2")
        self.assertIs(contracts.ErrorCode, error_module.ErrorCode)
        self.assertIs(identifiers.ResourceRef, resource_module.ResourceRef)

        digest = "sha256:" + "a" * 64
        subject_digest = "sha256:" + "b" * 64
        policy_digest = "sha256:" + "c" * 64
        artifact = artifacts.make_artifact_ref(
            digest=digest,
            media_type="application/octet-stream",
            size_bytes=7,
            artifact_kind="fixture",
        )
        evidence = artifacts.make_evidence_ref(
            digest=digest,
            subject_digest=subject_digest,
            evidence_kind="qualification",
            policy_digest=policy_digest,
        )
        resource = identifiers.make_resource_ref(
            tenant_id=identifiers.Identifier("tenant", "tenant_1"),
            project_id=identifiers.Identifier("project", "project_1"),
            resource_type="jobs",
            resource_id=identifiers.Identifier("job", "job_1"),
            resource_version=identifiers.ResourceVersion(2),
        )

        self.assertEqual(artifact.digest, digest)
        self.assertEqual(evidence.subject_digest, subject_digest)
        error_detail = contracts.to_error_detail(
            contracts.ContractError(
                contracts.ErrorCode.ERROR_CODE_UNAVAILABLE,
                "try again",
                retryable=True,
            ),
            subject=resource,
        )
        self.assertEqual(error_detail.subject.name, resource.name)
        self.assertTrue(contracts.from_error_detail(error_detail).retryable)
        self.assertEqual(
            identifiers.resource_key(resource),
            "tenants/tenant_1/projects/project_1/jobs/job_1@2",
        )
        self.assertEqual(
            resource.SerializeToString(deterministic=True),
            resource_module.ResourceRef.FromString(
                resource.SerializeToString(deterministic=True)
            ).SerializeToString(deterministic=True),
        )

        event_module = importlib.import_module("mindclade.job.v1.job_requested_pb2")
        payload = event_module.JobRequested(
            job_id="job_1",
            configuration_digest="sha256:" + "d" * 64,
        )
        envelope = serialization.make_event_envelope(
            payload,
            event_id="event_1",
            event_version=1,
            tenant_id="tenant_1",
            project_id="project_1",
            producer="control-plane",
            occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
            subject=resource,
            job_id="job_1",
        )
        decoded = serialization.parse_event_payload(envelope, event_module.JobRequested)
        self.assertEqual(decoded, payload)

        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.make_event_envelope(
                resource,
                event_id="event_unregistered_type",
                event_version=1,
                tenant_id="tenant_1",
                producer="control-plane",
                occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
                subject=resource,
            )
        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.make_event_envelope(
                payload,
                event_id="event_unregistered_version",
                event_version=2,
                tenant_id="tenant_1",
                producer="control-plane",
                occurred_at=datetime(2026, 8, 31, tzinfo=UTC),
                subject=resource,
            )

        envelope = cast(EventEnvelopeLike, envelope)
        envelope_type = cast(EventEnvelopeType, type(envelope))
        unknown_type = envelope_type.FromString(envelope.SerializeToString())
        unknown_type.event_type = "mindclade.events.job.v1.UnknownEvent"
        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.parse_event_payload(unknown_type, event_module.JobRequested)

        unknown_version = envelope_type.FromString(envelope.SerializeToString())
        unknown_version.event_version = 2
        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.parse_event_payload(unknown_version, event_module.JobRequested)

        wrong_content_type = envelope_type.FromString(envelope.SerializeToString())
        wrong_content_type.payload_content_type = "application/json"
        with self.assertRaisesRegex(ValueError, "event content type mismatch"):
            serialization.parse_event_payload(wrong_content_type, event_module.JobRequested)

        envelope.payload_digest = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            serialization.parse_event_payload(envelope, event_module.JobRequested)

    def test_public_descriptor_closure_is_exact_and_safe(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        api = importlib.import_module("mindclade.api.v1.mindclade_service_pb2")

        closure: set[str] = set()

        def visit(file_descriptor: FileDescriptor) -> None:
            name = file_descriptor.name
            if name in closure:
                return
            closure.add(name)
            for dependency in file_descriptor.dependencies:
                visit(dependency)

        visit(api.DESCRIPTOR)
        self.assertEqual(
            closure,
            {
                "google/api/annotations.proto",
                "google/api/http.proto",
                "google/protobuf/descriptor.proto",
                "google/protobuf/timestamp.proto",
                "proto/mindclade/api/v1/mindclade_service.proto",
            },
        )
        forbidden_tokens = {
            "any",
            "command_context",
            "delivery",
            "executable_plan",
            "fence",
            "lease",
            "principal",
            "storage_locator",
            "tenant_id",
        }
        messages = list(api.DESCRIPTOR.message_types_by_name.values())
        while messages:
            message = messages.pop()
            messages.extend(message.nested_types)
            self.assertTrue(message.full_name.startswith("mindclade.api.v1."))
            for field in message.fields:
                self.assertNotIn(field.name, forbidden_tokens, field.full_name)
                if field.message_type is not None:
                    package = field.message_type.file.package
                    self.assertIn(package, {"google.protobuf", "mindclade.api.v1"})
                    self.assertNotEqual(field.message_type.full_name, "google.protobuf.Any")

    def test_descriptor_http_contract_matches_curated_openapi(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        api = importlib.import_module("mindclade.api.v1.mindclade_service_pb2")
        annotations = importlib.import_module("google.api.annotations_pb2")
        document = object_mapping(
            yaml.safe_load(
                (repository / "protocols/openapi/published/mindclade.openapi.yaml").read_text()
            ),
            "OpenAPI document",
        )

        def openapi_operations() -> dict[str, tuple[str, str, dict[str, object]]]:
            result: dict[str, tuple[str, str, dict[str, object]]] = {}
            paths = object_mapping(document["paths"], "OpenAPI paths")
            for path, item_value in paths.items():
                item = object_mapping(item_value, f"OpenAPI path {path}")
                for method, operation_value in item.items():
                    if method in {"delete", "get", "patch", "post", "put"}:
                        operation = object_mapping(
                            operation_value, f"OpenAPI operation {method.upper()} {path}"
                        )
                        operation_id = string_value(
                            operation["operationId"], f"operationId for {method.upper()} {path}"
                        )
                        result[operation_id] = (method.upper(), path, operation)
            return result

        def parameters(operation: dict[str, object]) -> list[dict[str, object]]:
            result: list[dict[str, object]] = []
            for parameter_value in object_list(
                operation.get("parameters", []), "operation parameters"
            ):
                parameter = object_mapping(parameter_value, "operation parameter")
                if "$ref" in parameter:
                    reference = string_value(parameter["$ref"], "parameter reference")
                    components = object_mapping(document["components"], "OpenAPI components")
                    shared_parameters = object_mapping(
                        components["parameters"], "OpenAPI shared parameters"
                    )
                    parameter = object_mapping(
                        shared_parameters[reference.rsplit("/", 1)[1]],
                        f"OpenAPI shared parameter {reference}",
                    )
                result.append(parameter)
            return result

        def skeleton(path: str, *, descriptor: bool) -> str:
            if descriptor:
                path = re.sub(r"\{[^={}]+=([^{}]+)\}", r"\1", path)
                return path.replace("*", "{}")
            return re.sub(r"\{[^{}]+\}", "{}", path)

        def resolve_schema(schema: dict[str, object]) -> dict[str, object]:
            if "$ref" in schema:
                reference = string_value(schema["$ref"], "schema reference")
                components = object_mapping(document["components"], "OpenAPI components")
                schemas = object_mapping(components["schemas"], "OpenAPI schemas")
                return object_mapping(
                    schemas[reference.rsplit("/", 1)[1]], f"OpenAPI schema {reference}"
                )
            return schema

        def schema_properties(schema: dict[str, object]) -> set[str]:
            schema = resolve_schema(schema)
            result = set(object_mapping(schema.get("properties", {}), "schema properties").keys())
            for part in object_list(schema.get("allOf", []), "schema allOf"):
                result.update(schema_properties(object_mapping(part, "schema allOf member")))
            return result

        operations = openapi_operations()
        service = api.DESCRIPTOR.services_by_name["MindcladeService"]
        self.assertEqual(
            set(operations),
            {method.name[0].lower() + method.name[1:] for method in service.methods},
        )
        for method_value in service.methods:
            method = cast(MethodDescriptor, method_value)
            operation_id = method.name[0].lower() + method.name[1:]
            expected_method, expected_path, operation = operations[operation_id]
            rule = cast(HttpRuleLike, method.GetOptions().Extensions[annotations.http])
            descriptor_pattern = rule.WhichOneof("pattern")
            self.assertIsNotNone(descriptor_pattern, operation_id)
            assert descriptor_pattern is not None
            descriptor_method = descriptor_pattern.upper()
            descriptor_path = string_value(
                getattr(rule, descriptor_pattern), f"HTTP binding for {operation_id}"
            )
            self.assertEqual(descriptor_method, expected_method, operation_id)
            self.assertEqual(
                skeleton(descriptor_path, descriptor=True),
                skeleton(expected_path, descriptor=False),
                operation_id,
            )

            contract = cast(PublicHttpContractLike, method.GetOptions().Extensions[api.public_http])
            self.assertTrue(contract.bearer_auth, operation_id)
            self.assertEqual(document["security"], [{"bearerAuth": []}])
            responses = object_mapping(operation["responses"], f"responses for {operation_id}")
            expected_status = sorted(int(code) for code in responses if code.startswith("2"))
            self.assertEqual(list(contract.success_status), expected_status, operation_id)
            expected_headers = sorted(
                string_value(parameter["name"], f"parameter name for {operation_id}")
                for parameter in parameters(operation)
                if string_value(parameter["in"], f"parameter location for {operation_id}")
                == "header"
            )
            self.assertEqual(sorted(contract.request_headers), expected_headers, operation_id)
            self.assertEqual(bool(rule.body), "requestBody" in operation, operation_id)

            bound_fields = set(re.findall(r"\{([^={}]+)=", descriptor_path))
            descriptor_query = {
                field.json_name
                for field in method.input_type.fields
                if field.name not in bound_fields and field.name != rule.body
            }
            expected_query = {
                string_value(parameter["name"], f"query parameter for {operation_id}")
                for parameter in parameters(operation)
                if string_value(parameter["in"], f"parameter location for {operation_id}")
                == "query"
            }
            self.assertEqual(descriptor_query, expected_query, operation_id)
            if rule.body:
                body_field = method.input_type.fields_by_name[rule.body]
                request_body = object_mapping(
                    operation["requestBody"], f"request body for {operation_id}"
                )
                request_content = object_mapping(
                    request_body["content"], f"request content for {operation_id}"
                )
                media = object_mapping(
                    next(iter(request_content.values())), f"request media for {operation_id}"
                )
                assert body_field.message_type is not None
                self.assertEqual(
                    {field.json_name for field in body_field.message_type.fields},
                    schema_properties(object_mapping(media["schema"], "request schema")),
                    operation_id,
                )

            success = object_mapping(
                responses[str(expected_status[0])], f"success response for {operation_id}"
            )
            if "$ref" in success:
                reference = string_value(success["$ref"], "response reference")
                components = object_mapping(document["components"], "OpenAPI components")
                shared_responses = object_mapping(
                    components["responses"], "OpenAPI shared responses"
                )
                success = object_mapping(
                    shared_responses[reference.rsplit("/", 1)[1]],
                    f"OpenAPI shared response {reference}",
                )
            success_content = object_mapping(
                success.get("content", {}), f"success content for {operation_id}"
            )
            content_types = set(success_content)
            if method.server_streaming and operation_id == "watchOperation":
                self.assertEqual(contract.stream, api.STREAM_PROJECTION_SSE)
                self.assertEqual(content_types, {"text/event-stream"})
            elif method.server_streaming:
                self.assertEqual(contract.stream, api.STREAM_PROJECTION_BINARY)
                self.assertEqual(content_types, {"application/octet-stream"})
            else:
                self.assertEqual(contract.stream, api.STREAM_PROJECTION_NONE)
                self.assertFalse(method.client_streaming)
            if content_types.intersection({"application/json", "text/event-stream"}):
                media_type = next(iter(content_types))
                media = object_mapping(
                    success_content[media_type], f"success media for {operation_id}"
                )
                schema = object_mapping(media["schema"], f"success schema for {operation_id}")
                self.assertEqual(
                    {field.json_name for field in method.output_type.fields},
                    schema_properties(schema),
                    operation_id,
                )

    def test_public_protojson_uses_camel_case_and_decimal_int64_strings(self) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        api = importlib.import_module("mindclade.api.v1.mindclade_service_pb2")
        json_format = importlib.import_module("google.protobuf.json_format")
        document = object_mapping(
            yaml.safe_load(
                (repository / "protocols/openapi/published/mindclade.openapi.yaml").read_text()
            ),
            "OpenAPI document",
        )

        payload = json.loads(
            json_format.MessageToJson(
                api.ArtifactRef(
                    digest="sha256:" + "a" * 64,
                    media_type="application/octet-stream",
                    size_bytes=9007199254740993,
                    artifact_kind="fixture",
                )
            )
        )
        self.assertEqual(payload["mediaType"], "application/octet-stream")
        self.assertEqual(payload["sizeBytes"], "9007199254740993")
        components = object_mapping(document["components"], "OpenAPI components")
        schemas = object_mapping(components["schemas"], "OpenAPI schemas")
        artifact_schema = object_mapping(schemas["ArtifactRef"], "ArtifactRef schema")
        properties = object_mapping(artifact_schema["properties"], "ArtifactRef properties")
        size_schema = object_mapping(properties["sizeBytes"], "ArtifactRef.sizeBytes schema")
        self.assertEqual(size_schema["type"], "string")
        self.assertRegex(
            string_value(payload["sizeBytes"], "ProtoJSON sizeBytes"),
            string_value(size_schema["pattern"], "ArtifactRef.sizeBytes pattern"),
        )
        with self.assertRaisesRegex(json_format.ParseError, "no field named"):
            json_format.ParseDict({"unknownInternalField": "x"}, api.Operation())


if __name__ == "__main__":
    unittest.main()
