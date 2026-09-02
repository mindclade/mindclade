from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import yaml


class NamedRequest(Protocol):
    name: str


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "generated").is_dir():
            return candidate
    raise RuntimeError("cannot locate generated protocol bindings")


class GeneratedClientsContractTest(unittest.TestCase):
    def test_every_declared_python_package_round_trips_a_populated_message(
        self,
    ) -> None:
        repository = root()
        sys.path.insert(0, str(repository / "protocols/generated/python"))
        json_format = importlib.import_module("google.protobuf.json_format")
        descriptor = importlib.import_module("google.protobuf.descriptor")
        matrix = json.loads((repository / "tests/conformance/contract_matrix.yaml").read_text())

        def scalar_value(field: object) -> object:
            if field.type == descriptor.FieldDescriptor.TYPE_STRING:  # type: ignore[attr-defined]
                return "fixture"
            if field.type == descriptor.FieldDescriptor.TYPE_BYTES:  # type: ignore[attr-defined]
                return b"fixture"
            if field.type == descriptor.FieldDescriptor.TYPE_BOOL:  # type: ignore[attr-defined]
                return True
            if field.type == descriptor.FieldDescriptor.TYPE_ENUM:  # type: ignore[attr-defined]
                values = field.enum_type.values  # type: ignore[attr-defined]
                return values[1].number if len(values) > 1 else values[0].number
            if field.type in (  # type: ignore[attr-defined]
                descriptor.FieldDescriptor.TYPE_DOUBLE,
                descriptor.FieldDescriptor.TYPE_FLOAT,
            ):
                return 1.25
            return 7

        def populate(message: object, depth: int = 0) -> bool:
            for field in message.DESCRIPTOR.fields:  # type: ignore[attr-defined]
                if field.is_repeated:
                    continue
                if field.type == descriptor.FieldDescriptor.TYPE_MESSAGE:
                    continue
                setattr(message, field.name, scalar_value(field))
                return True
            for field in message.DESCRIPTOR.fields:  # type: ignore[attr-defined]
                if not field.is_repeated or field.type == descriptor.FieldDescriptor.TYPE_MESSAGE:
                    continue
                getattr(message, field.name).append(scalar_value(field))
                return True
            if depth < 8:
                for field in message.DESCRIPTOR.fields:  # type: ignore[attr-defined]
                    if field.is_repeated or field.type != descriptor.FieldDescriptor.TYPE_MESSAGE:
                        continue
                    child = getattr(message, field.name)
                    if populate(child, depth + 1):
                        return True
            return False

        for declaration in matrix["protobuf_packages"]:
            package = declaration["name"]
            with self.subTest(package=package):
                module = importlib.import_module(declaration["module"])
                message_type = getattr(module, declaration["message"])
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

        unknown_type = type(envelope).FromString(envelope.SerializeToString())
        unknown_type.event_type = "mindclade.events.job.v1.UnknownEvent"
        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.parse_event_payload(unknown_type, event_module.JobRequested)

        unknown_version = type(envelope).FromString(envelope.SerializeToString())
        unknown_version.event_version = 2
        with self.assertRaisesRegex(ValueError, "unregistered event type/version"):
            serialization.parse_event_payload(unknown_version, event_module.JobRequested)

        wrong_content_type = type(envelope).FromString(envelope.SerializeToString())
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

        def visit(file_descriptor: object) -> None:
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
        document = yaml.safe_load(
            (repository / "protocols/openapi/published/mindclade.openapi.yaml").read_text()
        )

        def openapi_operations() -> dict[str, tuple[str, str, dict[str, object]]]:
            result = {}
            for path, item in document["paths"].items():
                for method, operation in item.items():
                    if method in {"delete", "get", "patch", "post", "put"}:
                        result[operation["operationId"]] = (method.upper(), path, operation)
            return result

        def parameters(operation: dict[str, object]) -> list[dict[str, object]]:
            result = []
            for parameter in operation.get("parameters", []):
                if "$ref" in parameter:
                    parameter = document["components"]["parameters"][
                        parameter["$ref"].rsplit("/", 1)[1]
                    ]
                result.append(parameter)
            return result

        def skeleton(path: str, *, descriptor: bool) -> str:
            if descriptor:
                path = re.sub(r"\{[^={}]+=([^{}]+)\}", r"\1", path)
                return path.replace("*", "{}")
            return re.sub(r"\{[^{}]+\}", "{}", path)

        def resolve_schema(schema: dict[str, object]) -> dict[str, object]:
            if "$ref" in schema:
                return document["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
            return schema

        def schema_properties(schema: dict[str, object]) -> set[str]:
            schema = resolve_schema(schema)
            result = set(schema.get("properties", {}))
            for part in schema.get("allOf", []):
                result.update(schema_properties(part))
            return result

        operations = openapi_operations()
        service = api.DESCRIPTOR.services_by_name["MindcladeService"]
        self.assertEqual(
            set(operations),
            {method.name[0].lower() + method.name[1:] for method in service.methods},
        )
        for method in service.methods:
            operation_id = method.name[0].lower() + method.name[1:]
            expected_method, expected_path, operation = operations[operation_id]
            rule = method.GetOptions().Extensions[annotations.http]
            descriptor_method = rule.WhichOneof("pattern").upper()
            descriptor_path = getattr(rule, rule.WhichOneof("pattern"))
            self.assertEqual(descriptor_method, expected_method, operation_id)
            self.assertEqual(
                skeleton(descriptor_path, descriptor=True),
                skeleton(expected_path, descriptor=False),
                operation_id,
            )

            contract = method.GetOptions().Extensions[api.public_http]
            self.assertTrue(contract.bearer_auth, operation_id)
            self.assertEqual(document["security"], [{"bearerAuth": []}])
            expected_status = sorted(
                int(code) for code in operation["responses"] if str(code).startswith("2")
            )
            self.assertEqual(list(contract.success_status), expected_status, operation_id)
            expected_headers = sorted(
                parameter["name"]
                for parameter in parameters(operation)
                if parameter["in"] == "header"
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
                parameter["name"]
                for parameter in parameters(operation)
                if parameter["in"] == "query"
            }
            self.assertEqual(descriptor_query, expected_query, operation_id)
            if rule.body:
                body_field = method.input_type.fields_by_name[rule.body]
                media = next(iter(operation["requestBody"]["content"].values()))
                self.assertEqual(
                    {field.json_name for field in body_field.message_type.fields},
                    schema_properties(media["schema"]),
                    operation_id,
                )

            success = operation["responses"][str(expected_status[0])]
            if "$ref" in success:
                success = document["components"]["responses"][success["$ref"].rsplit("/", 1)[1]]
            content_types = set(success.get("content", {}))
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
                schema = success["content"][media_type]["schema"]
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
        document = yaml.safe_load(
            (repository / "protocols/openapi/published/mindclade.openapi.yaml").read_text()
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
        size_schema = document["components"]["schemas"]["ArtifactRef"]["properties"]["sizeBytes"]
        self.assertEqual(size_schema["type"], "string")
        self.assertRegex(payload["sizeBytes"], size_schema["pattern"])
        with self.assertRaisesRegex(json_format.ParseError, "no field named"):
            json_format.ParseDict({"unknownInternalField": "x"}, api.Operation())


if __name__ == "__main__":
    unittest.main()
