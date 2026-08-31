from __future__ import annotations

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

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
ASYNC_CREATE_OPERATIONS = {
    "createAgentRun",
    "createEvaluationRun",
    "createTrainingRun",
    "createWorkflowRun",
    "submitInference",
}
LIST_OPERATIONS = {
    "listAgentDefinitions",
    "listAgentRuns",
    "listApprovalRequests",
    "listDatasetReleases",
    "listDatasets",
    "listEvaluationRuns",
    "listModelReleases",
    "listModels",
    "listProjects",
    "listTrainingRuns",
    "listWorkflowDefinitions",
    "listWorkflowRuns",
}
EXPECTED_TAGS = {
    "Administration",
    "Agents",
    "Artifacts",
    "Datasets",
    "Evaluation",
    "Inference",
    "Models",
    "Operations",
    "Training",
    "Workflows",
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
        cls.openapi_path = cls.repository / "protocols/openapi/external-api.yaml"
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
        self.assertGreaterEqual(len(self.openapi["paths"]), 25)
        self.assertGreaterEqual(len(self.openapi["components"]["schemas"]), 50)
        for ref in iter_refs(self.openapi):
            resolve_local_ref(self.openapi, ref)

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
            "mindclade.artifact.v1.ArtifactRef",
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
        self.assertGreaterEqual(len(mappings), 15)
        for mapping in mappings:
            self.assertFalse(mapping.startswith("mindclade.internal."), mapping)
            package, message = mapping.rsplit(".", 1)
            self.assertIn(f"package {package};", proto_text, mapping)
            self.assertRegex(proto_text, rf"\bmessage {re.escape(message)}\s*\{{", mapping)

    def test_public_grpc_facade_exactly_covers_openapi_operations(self) -> None:
        grpc_path = self.repository / "protocols/proto/mindclade/api/v1/mindclade_service.proto"
        grpc_source = grpc_path.read_text()
        service = re.search(
            r"\bservice\s+MindcladeService\s*\{(?P<body>.*?)^\}",
            grpc_source,
            flags=re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(service, grpc_path)
        assert service is not None
        rpc_names = re.findall(r"^\s*rpc\s+(\w+)\s*\(", service.group("body"), re.MULTILINE)
        grpc_operation_ids = {name[0].lower() + name[1:] for name in rpc_names}
        openapi_operation_ids = {
            operation["operationId"] for _, _, operation in operations(self.openapi)
        }
        self.assertEqual(len(rpc_names), len(set(rpc_names)), "duplicate public gRPC RPC")
        self.assertEqual(grpc_operation_ids, openapi_operation_ids)
        self.assertNotIn('import "proto/mindclade/internal/', grpc_source)

    def test_sdk_pipeline_keeps_mindclade_forge_primary_and_policy_owned(self) -> None:
        spec = self.generation["spec"]
        self.assertEqual(spec["authority"]["source"], "protocols/openapi/external-api.yaml")
        self.assertEqual(spec["authority"]["sdkPolicyOwner"], "mindclade")
        self.assertEqual(spec["sdkPolicy"]["owner"], "mindclade")
        self.assertEqual(
            spec["sdkPolicy"]["source"], "protocols/openapi/generation.yaml#spec.sdkPolicy"
        )
        self.assertEqual(spec["sdkPolicy"]["canonicalization"], "canonical-json-sorted-keys")
        self.assertEqual(spec["sdkPolicy"]["providerConfigurationRule"], "derived-only")
        self.assertEqual(
            spec["pipeline"]["interfaces"],
            [
                "OpenApiValidator",
                "SdkPolicyCompiler",
                "SdkEmitter",
                "SdkSurfaceExtractor",
                "SdkBehaviorVerifier",
                "SdkPackager",
                "SdkPublisher",
                "SdkReleaseOrchestrator",
            ],
        )
        self.assertEqual(spec["pipeline"]["releaseReceipt"]["emittedBy"], "SdkReleaseOrchestrator")
        self.assertEqual(spec["localContractAdapter"]["mode"], "offline-plan-and-verify")
        self.assertEqual(
            spec["localContractAdapter"]["implementation"], "tools/codegen/sdk_generator.py"
        )
        self.assertEqual(spec["localContractAdapter"]["readiness"], "implemented")
        self.assertFalse(spec["localContractAdapter"]["emitsSdkSource"])
        providers = {provider["id"]: provider for provider in spec["providers"]}
        self.assertEqual(set(providers), {"fern", "forge", "speakeasy", "stainless"})
        self.assertEqual(providers["forge"]["role"], "primary-owned")
        self.assertTrue(providers["forge"]["longTerm"])
        self.assertTrue(providers["forge"]["releasePrimaryEligible"])
        self.assertEqual(providers["forge"]["foundation"]["id"], "oagen")
        self.assertEqual(providers["forge"]["foundation"]["purpose"], "openapi-parser-and-typed-ir")
        self.assertEqual(providers["fern"]["role"], "preferred-qualified-shadow")
        self.assertEqual(
            providers["fern"]["qualificationNotes"]["selfHostedWorkflow"],
            "enterprise-docker-token-and-outbound-verification-required",
        )
        self.assertEqual(providers["speakeasy"]["role"], "commercial-benchmark-fallback")
        self.assertEqual(providers["speakeasy"]["qualificationNotes"]["cliLicense"], "Elastic-2.0")
        self.assertEqual(providers["stainless"]["role"], "legacy-comparison-only")
        self.assertEqual(providers["stainless"]["availability"], "existing-project-only")
        self.assertFalse(providers["stainless"]["longTerm"])
        for provider in providers.values():
            self.assertEqual(set(provider["languages"]), {"go", "python", "typescript"})
            self.assertEqual(provider["adapter"]["contractVersion"], "v1")
            self.assertEqual(provider["adapter"]["providerVersion"], "unpinned")
            self.assertIsNone(provider["adapter"]["executable"])
            self.assertIsNone(provider["adapter"]["executableSha256"])
            self.assertEqual(
                provider["configuration"]["policySource"],
                "protocols/openapi/generation.yaml#spec.sdkPolicy",
            )
            self.assertFalse(provider["release"]["publish"])
        self.assertFalse(spec["connectedGap"]["ownedCompilerPinned"])
        self.assertEqual(spec["parity"]["primary"], "forge")
        self.assertEqual(spec["parity"]["preferredShadow"], "fern")
        self.assertEqual(spec["parity"]["benchmarks"], ["speakeasy"])
        self.assertEqual(spec["parity"]["legacyComparisons"], ["stainless"])
        self.assertEqual(spec["qualification"]["connectedStatus"], "not-run")
        self.assertFalse(spec["qualification"]["publishAuthorized"])

    def test_local_sdk_plan_is_deterministic_and_provider_neutral(self) -> None:
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
            self.assertEqual(plan["schemaVersion"], "mindclade.sdk-generation-plan/v2")
            self.assertIn("submitInference", plan["inventory"]["operationIds"])
            self.assertIn("ArtifactRef", plan["inventory"]["publicSchemas"])
            self.assertEqual(
                plan["authority"]["sdkPolicy"],
                "protocols/openapi/generation.yaml#spec.sdkPolicy",
            )
            self.assertRegex(plan["authority"]["sdkPolicySha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertNotEqual(
                plan["authority"]["sdkPolicySha256"],
                plan["authority"]["generationConfigSha256"],
            )
            self.assertEqual(
                {(item["provider"], item["language"]) for item in plan["provenance"]},
                {
                    (provider, language)
                    for provider in ("fern", "forge", "speakeasy", "stainless")
                    for language in ("go", "python", "typescript")
                },
            )
            self.assertEqual(plan["parity"]["primary"], "forge")
            self.assertEqual(plan["parity"]["preferredShadow"], "fern")
            self.assertEqual(plan["parity"]["benchmarks"], ["speakeasy"])
            self.assertEqual(plan["parity"]["legacyComparisons"], ["stainless"])
            forge_plans = [item for item in plan["provenance"] if item["provider"] == "forge"]
            self.assertTrue(forge_plans)
            self.assertTrue(all(item["foundation"] == "oagen" for item in forge_plans))
            self.assertTrue(all(item["providerReleasePrimaryEligible"] for item in forge_plans))
            self.assertTrue(
                all(
                    not item["providerReleasePrimaryEligible"]
                    for item in plan["provenance"]
                    if item["provider"] != "forge"
                )
            )
            self.assertTrue(
                all(item["providerVersion"] == "unpinned" for item in plan["provenance"])
            )
            self.assertTrue(
                all(
                    item["sdkPolicySha256"] == plan["authority"]["sdkPolicySha256"]
                    for item in plan["provenance"]
                )
            )
            verify = subprocess.run(
                [*base[:2], "verify", *base[2:], "--plan", "first.json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_sdk_generator_confines_outputs_and_fails_closed_before_provider_execution(
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
                    "forge",
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
            self.assertFalse((output_root / "forge/python").exists())

            legacy_stainless = subprocess.run(
                [
                    sys.executable,
                    str(self.sdk_generator_path),
                    "generate",
                    *common,
                    "--provider",
                    "stainless",
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
            self.assertEqual(legacy_stainless.returncode, 3)
            self.assertIn("existing-project legacy comparison", legacy_stainless.stderr)
            self.assertFalse((output_root / "stainless/python").exists())

    def test_sdk_plan_rejects_provider_or_policy_authority_inversion(self) -> None:
        def copied_generation() -> dict[str, Any]:
            return json.loads(json.dumps(self.generation))

        invalid_cases: list[tuple[str, dict[str, Any], str]] = []

        wrong_primary = copied_generation()
        next(
            provider for provider in wrong_primary["spec"]["providers"] if provider["id"] == "forge"
        )["role"] = "preferred-qualified-shadow"
        invalid_cases.append(("wrong-primary", wrong_primary, "forge role must be primary-owned"))

        wrong_foundation = copied_generation()
        next(
            provider
            for provider in wrong_foundation["spec"]["providers"]
            if provider["id"] == "forge"
        )["foundation"]["id"] = "provider-native"
        invalid_cases.append(("wrong-foundation", wrong_foundation, "must use OAGen"))

        provider_owned_policy = copied_generation()
        next(
            provider
            for provider in provider_owned_policy["spec"]["providers"]
            if provider["id"] == "fern"
        )["configuration"]["policySource"] = "fern.yml"
        invalid_cases.append(
            (
                "provider-owned-policy",
                provider_owned_policy,
                "must derive from the Mindclade SDK policy",
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

    def test_compatibility_policy_freezes_the_clean_v1_baseline(self) -> None:
        spec = self.policy["spec"]
        self.assertEqual(spec["authority"]["source"], "protocols/openapi/external-api.yaml")
        self.assertIn("Additive", spec["versioning"]["postBaselineRule"])
        self.assertIn("change-operation-id", spec["compatibility"]["breaking"])
        self.assertIn("mutations-have-explicit-idempotency-semantics", spec["publicInvariants"])
        self.assertTrue(spec["sdkSkew"]["providerSemanticParityRequired"])
        self.assertEqual(spec["sdkSkew"]["providers"]["primary"], "forge")
        self.assertEqual(spec["sdkSkew"]["providers"]["implementationFoundation"], "oagen")
        self.assertEqual(spec["sdkSkew"]["providers"]["preferredShadow"], "fern")
        self.assertEqual(spec["sdkSkew"]["providers"]["benchmarks"], ["speakeasy"])
        self.assertEqual(spec["sdkSkew"]["providers"]["legacyComparisons"], ["stainless"])
        self.assertTrue(spec["sdkSkew"]["providerRules"]["mindcladePolicyIsAuthoritative"])
        self.assertFalse(spec["rollback"]["publishOrDeployAuthorizedByThisPolicy"])

    def test_committed_baseline_matches_all_openapi_sources(self) -> None:
        baseline = self.repository / "protocols/compatibility/baselines/openapi.lock.json"
        expected = {
            str(path.relative_to(self.repository)): "sha256:"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.repository / "protocols/openapi").glob("*.yaml"))
        }
        self.assertEqual(
            json.loads(baseline.read_text()),
            {"schema_version": "mindclade.openapi-baseline/v1", "sources": expected},
        )


if __name__ == "__main__":
    unittest.main()
