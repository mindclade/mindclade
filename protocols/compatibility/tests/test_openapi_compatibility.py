from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml
from google.protobuf import descriptor_pb2

from tools.codegen import generate_protocols

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
ASYNC_CREATE_OPERATIONS = {
    "createTrainingRun",
}
LIST_OPERATIONS = {
    "listTrainingRuns",
}
EXPECTED_TAGS = {
    "Operations",
    "Training",
}


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate OpenAPI compatibility baselines")


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a mapping")
    return value


def operations(document: Mapping[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def iter_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                yield child
            else:
                yield from iter_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_refs(child)


def resolve_local_ref(document: Mapping[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise AssertionError(f"external reference is not allowed in the bundled API: {ref}")
    value: Any = document
    for component in ref[2:].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise AssertionError(f"unresolved OpenAPI reference: {ref}")
        value = value[key]
    return value


def parameter_names(document: Mapping[str, Any], operation: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for parameter in operation.get("parameters", []):
        if "$ref" in parameter:
            parameter = resolve_local_ref(document, parameter["$ref"])
        names.add(parameter["name"])
    return names


class OpenApiCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = root()
        cls.openapi_path = cls.repository / "protocols/openapi/published/mindclade.openapi.yaml"
        cls.openapi_overlay_path = cls.repository / "protocols/openapi/external-api.yaml"
        cls.generation_path = cls.repository / "protocols/openapi/generation.yaml"
        cls.policy_path = cls.repository / "protocols/openapi/compatibility-policy.yaml"
        cls.sdk_generator_path = cls.repository / "tools/codegen/sdk_generator.py"
        cls.openapi = load_yaml(cls.openapi_path)
        cls.generation = load_yaml(cls.generation_path)
        cls.policy = load_yaml(cls.policy_path)

    def test_openapi_31_document_is_bundled_and_references_resolve(self) -> None:
        self.assertEqual(self.openapi["openapi"], "3.1.0")
        self.assertEqual(
            self.openapi["jsonSchemaDialect"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(self.openapi["x-mindclade-api-profile"], "v1")
        self.assertEqual(len(self.openapi["paths"]), 5)
        self.assertGreaterEqual(len(self.openapi["components"]["schemas"]), 15)
        for ref in iter_refs(self.openapi):
            resolve_local_ref(self.openapi, ref)

    def test_checked_openapi_stages_are_distinct_and_published_is_exact(self) -> None:
        raw_path = self.repository / "protocols/openapi/raw/mindclade.openapi.yaml"
        curated_path = self.repository / "protocols/openapi/curated/mindclade.openapi.yaml"
        published_path = self.repository / "protocols/openapi/published/mindclade.openapi.yaml"
        raw = load_yaml(raw_path)
        self.assertEqual(raw["openapi"], "3.1.0")
        self.assertEqual(raw["x-mindclade-schema-version"], "mindclade.raw-openapi-projection/v3")
        for ref in iter_refs(raw):
            resolve_local_ref(raw, ref)
        self.assertEqual(curated_path.read_bytes(), published_path.read_bytes())
        overlay = load_yaml(self.openapi_overlay_path)
        self.assertEqual(overlay["paths"], self.openapi["paths"])
        self.assertGreater(
            len(overlay["components"]["schemas"]),
            len(self.openapi["components"]["schemas"]),
        )

    def test_path_parameters_and_operation_ids_are_complete_and_unique(self) -> None:
        seen: set[str] = set()
        for path, _, operation in operations(self.openapi):
            operation_id = operation.get("operationId")
            self.assertIsInstance(operation_id, str, path)
            self.assertNotIn(operation_id, seen)
            seen.add(operation_id)
            placeholders = set(re.findall(r"\{([^}]+)\}", path))
            self.assertTrue(placeholders.issubset(parameter_names(self.openapi, operation)), path)
            self.assertTrue(operation.get("tags"), operation_id)
            self.assertTrue(
                any(code.startswith("4") for code in operation["responses"]), operation_id
            )

    def test_resource_domains_and_public_security_are_explicit(self) -> None:
        self.assertEqual({tag["name"] for tag in self.openapi["tags"]}, EXPECTED_TAGS)
        self.assertEqual(self.openapi["security"], [{"bearerAuth": []}])
        self.assertEqual(
            self.openapi["components"]["securitySchemes"]["bearerAuth"]["scheme"], "bearer"
        )
        for _, _, operation in operations(self.openapi):
            self.assertTrue(set(operation["tags"]).issubset(EXPECTED_TAGS))

    def test_mutations_are_idempotent_and_async_work_has_absolute_deadlines(self) -> None:
        by_id = {
            operation["operationId"]: operation for _, _, operation in operations(self.openapi)
        }
        for _, method, operation in operations(self.openapi):
            if method in {"delete", "patch", "post", "put"}:
                self.assertIn("Idempotency-Key", parameter_names(self.openapi, operation))
        for operation_id in ASYNC_CREATE_OPERATIONS:
            operation = by_id[operation_id]
            self.assertIn("X-Mindclade-Deadline", parameter_names(self.openapi, operation))
            self.assertIn("202", operation["responses"])
            accepted = resolve_local_ref(self.openapi, operation["responses"]["202"]["$ref"])
            response_schema = accepted["content"]["application/json"]["schema"]
            self.assertEqual(response_schema["$ref"], "#/components/schemas/Operation")

    def test_operation_polling_cancellation_and_revision_contract(self) -> None:
        by_id = {
            operation["operationId"]: operation for _, _, operation in operations(self.openapi)
        }
        get_operation = by_id["getOperation"]
        self.assertIn("If-None-Match", parameter_names(self.openapi, get_operation))
        self.assertIn("304", get_operation["responses"])
        self.assertIn("ETag", get_operation["responses"]["200"]["headers"])
        cancel_operation = by_id["cancelOperation"]
        self.assertIn("If-Match", parameter_names(self.openapi, cancel_operation))
        self.assertIn("Idempotency-Key", parameter_names(self.openapi, cancel_operation))
        operation = self.openapi["components"]["schemas"]["Operation"]
        self.assertTrue({"revision", "etag", "done", "state"}.issubset(operation["required"]))

    def test_list_operations_use_opaque_bounded_pagination(self) -> None:
        by_id = {
            operation["operationId"]: operation for _, _, operation in operations(self.openapi)
        }
        for operation_id in LIST_OPERATIONS:
            parameters = parameter_names(self.openapi, by_id[operation_id])
            self.assertTrue({"pageSize", "pageToken"}.issubset(parameters), operation_id)
        page_size = self.openapi["components"]["parameters"]["PageSize"]["schema"]
        self.assertEqual(page_size["maximum"], 200)
        self.assertEqual(page_size["default"], 50)
        page_token = self.openapi["components"]["parameters"]["PageToken"]
        self.assertIn("Opaque", page_token["description"])

    def test_artifact_and_error_models_preserve_public_semantics(self) -> None:
        artifact_ref = self.openapi["components"]["schemas"]["ArtifactRef"]
        self.assertEqual(
            artifact_ref["x-mindclade-authoritative-message"],
            "mindclade.api.v1.ArtifactRef",
        )
        self.assertEqual(
            set(artifact_ref["required"]), {"artifactKind", "digest", "mediaType", "sizeBytes"}
        )
        self.assertEqual(
            artifact_ref["properties"]["digest"]["$ref"], "#/components/schemas/Digest"
        )
        public_error = self.openapi["components"]["schemas"]["PublicError"]
        self.assertTrue(
            {"code", "message", "requestId", "retryable"}.issubset(public_error["required"])
        )
        self.assertIn("CONFLICT", public_error["properties"]["code"]["enum"])
        self.assertIn("RATE_LIMITED", public_error["properties"]["code"]["enum"])

    def test_public_schema_mappings_resolve_to_domain_proto_sources_only(self) -> None:
        proto_text = "\n".join(
            path.read_text()
            for path in sorted((self.repository / "protocols/proto").glob("**/*.proto"))
        )
        mappings = []
        for schema in self.openapi["components"]["schemas"].values():
            if isinstance(schema, dict) and "x-mindclade-authoritative-message" in schema:
                mappings.append(schema["x-mindclade-authoritative-message"])
            for child in schema.get("allOf", []) if isinstance(schema, dict) else []:
                if isinstance(child, dict) and "x-mindclade-authoritative-message" in child:
                    mappings.append(child["x-mindclade-authoritative-message"])
        self.assertGreaterEqual(len(mappings), 5)
        for mapping in mappings:
            self.assertFalse(mapping.startswith("mindclade.internal."), mapping)
            package, message = mapping.rsplit(".", 1)
            self.assertIn(f"package {package};", proto_text, mapping)
            self.assertRegex(proto_text, rf"\bmessage {re.escape(message)}\s*\{{", mapping)

    def test_public_grpc_descriptor_exactly_matches_openapi_semantics(self) -> None:
        candidate_path = (
            self.repository / "protocols/compatibility/baselines/protobuf.candidate.json"
        )
        candidate = json.loads(candidate_path.read_text())
        descriptor_set = base64.b64decode(candidate["descriptor_set"]["base64"], validate=True)
        raw = generate_protocols.public_openapi_projection(descriptor_set)

        self.assertEqual(raw["openapi"], "3.1.0")
        self.assertEqual(raw["x-mindclade-schema-version"], "mindclade.raw-openapi-projection/v3")
        self.assertEqual(len(raw["x-mindclade-binding-contracts"]), 6)
        generate_protocols.validate_curated_bindings(raw, self.openapi)
        generate_protocols.validate_curated_protojson(raw, self.openapi)

        grpc_path = self.repository / "protocols/proto/mindclade/api/v1/mindclade_service.proto"
        grpc_source = grpc_path.read_text()
        self.assertNotIn('import "proto/mindclade/internal/', grpc_source)

    def test_curated_path_and_parameter_names_are_descriptor_exact(self) -> None:
        raw = load_yaml(self.repository / "protocols/openapi/raw/mindclade.openapi.yaml")

        renamed_path = copy.deepcopy(self.openapi)
        renamed_path["paths"] = {
            path.replace("{tenant}", "{workspace}"): path_item
            for path, path_item in renamed_path["paths"].items()
        }
        renamed_path["components"]["parameters"]["TenantId"]["name"] = "workspace"
        with self.assertRaisesRegex(ValueError, "HTTP path binding drift"):
            generate_protocols.validate_curated_bindings(raw, renamed_path)

        renamed_parameter = copy.deepcopy(self.openapi)
        renamed_parameter["components"]["parameters"]["TenantId"]["name"] = "workspace"
        with self.assertRaisesRegex(ValueError, "path-parameter binding drift"):
            generate_protocols.validate_curated_bindings(raw, renamed_parameter)

    def test_public_descriptor_boundary_rejects_trusted_identity_fields(self) -> None:
        candidate_path = (
            self.repository / "protocols/compatibility/baselines/protobuf.candidate.json"
        )
        candidate = json.loads(candidate_path.read_text())
        descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(
            base64.b64decode(candidate["descriptor_set"]["base64"], validate=True)
        )
        public_file = next(
            file
            for file in descriptor_set.file
            if file.name == "proto/mindclade/api/v1/mindclade_service.proto"
        )
        project_view = next(
            message for message in public_file.message_type if message.name == "ProjectView"
        )
        forbidden = project_view.field.add()
        forbidden.name = "principal_id"
        forbidden.json_name = "principalId"
        forbidden.number = 99
        forbidden.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        forbidden.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

        with self.assertRaisesRegex(ValueError, "forbidden field.*principal_id"):
            generate_protocols.public_openapi_projection(
                descriptor_set.SerializeToString(deterministic=True)
            )

    def test_historical_openapi_drift_regressions_are_closed(self) -> None:
        schemas = self.openapi["components"]["schemas"]
        training_run_properties, _ = generate_protocols.merged_openapi_object(
            self.openapi, schemas["TrainingRun"]
        )
        self.assertEqual(
            schemas["Operation"]["properties"]["state"]["enum"],
            ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLING", "CANCELLED"],
        )
        self.assertEqual(
            training_run_properties["state"]["enum"],
            [
                "CREATED",
                "VALIDATING",
                "ADMITTED",
                "RUNNING",
                "CHECKPOINTING",
                "RECOVERING",
                "DRAINING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            ],
        )
        self.assertEqual(
            set(schemas["TrainingRunCreate"]["required"]),
            {"trainingRunId", "trainingRecipe", "datasetRelease", "modelRelease"},
        )
        self.assertEqual(
            set(schemas["OperationEvent"]["properties"]),
            {
                "eventId",
                "eventType",
                "schemaVersion",
                "operation",
                "operationRevision",
                "resumeCursor",
                "emittedAt",
                "heartbeat",
            },
        )

    def test_internal_sdk_pipeline_uses_native_generated_transport_and_owned_facades(
        self,
    ) -> None:
        spec = self.generation["spec"]
        self.assertEqual(self.generation["kind"], "InternalSdkGeneration")
        self.assertEqual(self.generation["metadata"]["status"], "candidate-unratified")
        self.assertEqual(spec["authority"]["contracts"], ["protocols/proto", "protocols/events"])
        self.assertEqual(spec["authority"]["generatedRoot"], "protocols/generated")
        self.assertEqual(spec["authority"]["generator"], "buf.gen.yaml")
        self.assertEqual(spec["authority"]["facadeRoot"], "internal/sdk")
        self.assertEqual(
            spec["authority"]["dependencyDirection"],
            [
                "protocols/proto-and-events",
                "protocols/generated",
                "internal/sdk",
                "services-workers-training-tools-and-internal-apps",
            ],
        )

        native = spec["nativeGeneration"]
        self.assertEqual(native["implementation"], "buf-and-pinned-native-generators")
        self.assertTrue(native["deterministic"])
        self.assertTrue(native["committedOutputs"])
        self.assertEqual(set(native["languages"]), {"go", "python", "rust", "typescript"})
        for language, configuration in native["languages"].items():
            self.assertEqual(configuration["output"], f"protocols/generated/{language}")
            self.assertEqual(configuration["facade"], f"internal/sdk/{language}")
        self.assertEqual(
            spec["internalSdkPolicy"]["models"],
            "intentionally-exported-generated-protobuf-types",
        )
        self.assertEqual(spec["internalSdkPolicy"]["handwrittenWireModels"], "forbidden")
        self.assertEqual(
            spec["pipeline"]["interfaces"],
            [
                "ProtoContractValidator",
                "BufNativeGenerator",
                "GeneratedBindingCompiler",
                "InternalFacadeBuilder",
                "InternalSdkConformanceVerifier",
                "LayeringPolicyVerifier",
            ],
        )

        optional = spec["optionalRestGeneration"]
        self.assertFalse(optional["enabledByDefault"])
        self.assertFalse(optional["authority"])
        self.assertEqual(optional["policyOwner"], "mindclade")
        self.assertEqual(optional["providerConfigurationRule"], "derived-only")
        providers = {provider["id"]: provider for provider in optional["providers"]}
        self.assertEqual(set(providers), {"fern", "speakeasy"})
        self.assertEqual(providers["fern"]["role"], "optional-internal-rest-generator")
        self.assertEqual(
            providers["speakeasy"]["role"],
            "optional-specialized-rest-benchmark",
        )
        self.assertEqual(
            set(providers["fern"]["languages"]),
            {"go", "python", "rust", "typescript"},
        )
        self.assertEqual(
            set(providers["speakeasy"]["languages"]),
            {"go", "python", "typescript"},
        )
        for provider in providers.values():
            self.assertFalse(provider["foundational"])
            self.assertFalse(provider["releasePrimaryEligible"])
            self.assertEqual(provider["adapter"]["providerVersion"], "unpinned")
            self.assertIsNone(provider["adapter"]["executable"])
            self.assertIsNone(provider["adapter"]["executableSha256"])
            self.assertFalse(provider["release"]["publish"])
        generation_source = self.generation_path.read_text().lower()
        self.assertNotIn("stainless", generation_source)
        self.assertNotIn("oagen", generation_source)
        self.assertNotIn("forge", generation_source)

        self.assertEqual(spec["localOptionalRestAdapter"]["mode"], "offline-plan-and-verify")
        self.assertEqual(
            spec["localOptionalRestAdapter"]["implementation"],
            "tools/codegen/sdk_generator.py",
        )
        self.assertFalse(spec["localOptionalRestAdapter"]["emitsSdkSource"])
        self.assertFalse(spec["qualification"]["optionalRestProviderRequired"])
        self.assertFalse(spec["qualification"]["publishAuthorized"])

        public_http = spec["publicHttpCandidate"]
        self.assertEqual(public_http["authority"], "public-protobuf-descriptor")
        self.assertEqual(public_http["descriptorService"], "mindclade.api.v1.MindcladeService")
        self.assertEqual(
            set(public_http["activeOperationIds"]),
            {
                "getOperation",
                "cancelOperation",
                "watchOperation",
                "listTrainingRuns",
                "createTrainingRun",
                "getTrainingRun",
            },
        )
        self.assertIn(
            "complete-protojson-component-shapes",
            public_http["stages"]["raw"]["contains"],
        )
        self.assertIn(
            "requiredness-or-protojson-representation",
            public_http["stages"]["curated"]["forbiddenTransforms"],
        )
        self.assertEqual(
            public_http["stages"]["published"]["rule"],
            "byte-identical-to-validated-curated-candidate",
        )
        self.assertFalse(public_http["publishAuthorized"])

    def test_optional_rest_plan_is_deterministic_and_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            base = [
                sys.executable,
                str(self.sdk_generator_path),
                "--openapi",
                str(self.openapi_path),
                "--generation",
                str(self.generation_path),
                "--output-root",
                str(output_root),
                "--source-revision",
                "test-revision",
            ]
            first = subprocess.run(
                [*base[:2], "plan", *base[2:], "--output", "first.json"],
                check=False,
                capture_output=True,
                text=True,
            )
            second = subprocess.run(
                [*base[:2], "plan", *base[2:], "--output", "second.json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_bytes = (output_root / "first.json").read_bytes()
            self.assertEqual(first_bytes, (output_root / "second.json").read_bytes())
            plan = json.loads(first_bytes)
            self.assertEqual(plan["schemaVersion"], "mindclade.optional-rest-sdk-plan/v3")
            self.assertEqual(plan["kind"], "OptionalRestSdkPlan")
            self.assertEqual(
                plan["inventory"]["operationIds"],
                [
                    "cancelOperation",
                    "createTrainingRun",
                    "getOperation",
                    "getTrainingRun",
                    "listTrainingRuns",
                    "watchOperation",
                ],
            )
            self.assertIn("ArtifactRef", plan["inventory"]["publicSchemas"])
            self.assertEqual(
                plan["authority"]["protobufSources"],
                ["protocols/proto", "protocols/events"],
            )
            self.assertEqual(plan["authority"]["generatedRoot"], "protocols/generated")
            self.assertEqual(plan["authority"]["internalSdkRoot"], "internal/sdk")
            self.assertEqual(plan["authority"]["nativeGenerator"], "buf.gen.yaml")
            self.assertRegex(plan["authority"]["optionalPolicySha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertNotEqual(
                plan["authority"]["optionalPolicySha256"],
                plan["authority"]["generationConfigSha256"],
            )
            self.assertEqual(
                {(item["provider"], item["language"]) for item in plan["provenance"]},
                {
                    ("fern", "go"),
                    ("fern", "python"),
                    ("fern", "rust"),
                    ("fern", "typescript"),
                    ("speakeasy", "go"),
                    ("speakeasy", "python"),
                    ("speakeasy", "typescript"),
                },
            )
            self.assertEqual(plan["parity"]["reference"], "native-internal-sdk-behavior")
            self.assertTrue(
                all(item["providerRole"].startswith("optional-") for item in plan["provenance"])
            )
            self.assertTrue(
                all(item["providerVersion"] == "unpinned" for item in plan["provenance"])
            )
            self.assertFalse(plan["safety"]["authoritative"])
            self.assertFalse(plan["safety"]["enabledByDefault"])
            verify = subprocess.run(
                [*base[:2], "verify", *base[2:], "--plan", "first.json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_optional_rest_planner_confines_outputs_and_fails_closed_before_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            common = [
                "--openapi",
                str(self.openapi_path),
                "--generation",
                str(self.generation_path),
                "--output-root",
                str(output_root),
                "--source-revision",
                "test-revision",
            ]
            escape = subprocess.run(
                [
                    sys.executable,
                    str(self.sdk_generator_path),
                    "plan",
                    *common,
                    "--output",
                    "../escape.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(escape.returncode, 2)
            self.assertIn("beneath output root", escape.stderr)
            self.assertFalse((output_root.parent / "escape.json").exists())

            generate = subprocess.run(
                [
                    sys.executable,
                    str(self.sdk_generator_path),
                    "generate",
                    *common,
                    "--provider",
                    "fern",
                    "--language",
                    "python",
                    "--allow-connected",
                    "--provider-command",
                    "/definitely/not/a/provider",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generate.returncode, 3)
            self.assertIn("configuration-only", generate.stderr)
            self.assertFalse((output_root / "fern/python").exists())

            unsupported = subprocess.run(
                [
                    sys.executable,
                    str(self.sdk_generator_path),
                    "plan",
                    *common,
                    "--provider",
                    "speakeasy",
                    "--language",
                    "rust",
                    "--output",
                    "unsupported.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(unsupported.returncode, 2)
            self.assertIn("does not support configured language rust", unsupported.stderr)
            self.assertFalse((output_root / "unsupported.json").exists())

    def test_sdk_policy_rejects_native_or_provider_authority_inversion(self) -> None:
        def copied_generation() -> dict[str, Any]:
            return json.loads(json.dumps(self.generation))

        invalid_cases: list[tuple[str, dict[str, Any], str]] = []

        wrong_native = copied_generation()
        wrong_native["spec"]["nativeGeneration"]["implementation"] = "hosted-provider"
        invalid_cases.append(("wrong-native", wrong_native, "Buf and pinned native generators"))

        provider_foundational = copied_generation()
        next(
            provider
            for provider in provider_foundational["spec"]["optionalRestGeneration"]["providers"]
            if provider["id"] == "fern"
        )["foundational"] = True
        invalid_cases.append(
            (
                "provider-foundational",
                provider_foundational,
                "cannot be foundational or primary",
            )
        )

        provider_owned_policy = copied_generation()
        next(
            provider
            for provider in provider_owned_policy["spec"]["optionalRestGeneration"]["providers"]
            if provider["id"] == "fern"
        )["configuration"]["policySource"] = "fern.yml"
        invalid_cases.append(
            (
                "provider-owned-policy",
                provider_owned_policy,
                "must derive from Mindclade policy",
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            for case_name, generation, expected_error in invalid_cases:
                with self.subTest(case=case_name):
                    generation_path = temporary / f"{case_name}.yaml"
                    generation_path.write_text(yaml.safe_dump(generation, sort_keys=False))
                    output_root = temporary / case_name
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(self.sdk_generator_path),
                            "plan",
                            "--openapi",
                            str(self.openapi_path),
                            "--generation",
                            str(generation_path),
                            "--output-root",
                            str(output_root),
                            "--source-revision",
                            "test-revision",
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(expected_error, result.stderr)

    def test_compatibility_policy_keeps_v1_unratified_and_internal_sdk_native(
        self,
    ) -> None:
        spec = self.policy["spec"]
        self.assertEqual(
            spec["authority"]["descriptorSource"],
            "protocols/proto/mindclade/api/v1/mindclade_service.proto",
        )
        self.assertEqual(
            spec["authority"]["curationOverlay"], "protocols/openapi/external-api.yaml"
        )
        self.assertEqual(self.policy["metadata"]["status"], "candidate-unratified")
        self.assertFalse(spec["versioning"]["ratified"])
        self.assertIn("ratification", spec["versioning"]["postBaselineRule"])
        self.assertIn("change-operation-id", spec["compatibility"]["breaking"])
        self.assertIn("mutations-have-explicit-idempotency-semantics", spec["publicInvariants"])
        self.assertEqual(spec["internalSdk"]["authority"], "protobuf")
        self.assertEqual(spec["internalSdk"]["generator"], "buf-and-pinned-native")
        self.assertEqual(spec["internalSdk"]["facadeRoot"], "internal/sdk")
        self.assertEqual(
            set(spec["internalSdk"]["languages"]),
            {"go", "python", "rust", "typescript"},
        )
        self.assertEqual(spec["internalSdk"]["optionalRestProviders"], ["fern", "speakeasy"])
        self.assertFalse(spec["internalSdk"]["optionalRestProvidersAreAuthority"])
        self.assertFalse(spec["rollback"]["publishOrDeployAuthorizedByThisPolicy"])

    def test_candidate_lock_matches_all_openapi_sources(self) -> None:
        candidate = self.repository / "protocols/compatibility/baselines/openapi.lock.json"
        expected = {
            str(path.relative_to(self.repository)): "sha256:"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.repository / "protocols/openapi").glob("**/*"))
            if path.is_file() and path.suffix in {".json", ".yaml"}
        }
        self.assertEqual(
            json.loads(candidate.read_text()),
            {"schema_version": "mindclade.openapi-candidate/v1", "sources": expected},
        )


if __name__ == "__main__":
    unittest.main()
