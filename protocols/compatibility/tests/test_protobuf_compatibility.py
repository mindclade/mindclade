from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import yaml
from google.protobuf import descriptor_pb2, json_format

from tools.codegen import generate_grpc_implementation_coverage, generate_protocols


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate protocol compatibility baselines")


def candidate(repository: Path) -> dict[str, Any]:
    value: Any = json.loads(
        (repository / "protocols/compatibility/baselines/protobuf.candidate.json").read_text()
    )
    if not isinstance(value, dict):
        raise TypeError("Protobuf candidate must be an object")
    return cast(dict[str, Any], value)


def predecessor(repository: Path) -> dict[str, Any]:
    value: Any = json.loads(
        (
            repository / "protocols/compatibility/baselines/protobuf.predecessor.lock.json"
        ).read_text()
    )
    if not isinstance(value, dict):
        raise TypeError("Protobuf predecessor must be an object")
    return cast(dict[str, Any], value)


class ProtobufCompatibilityTest(unittest.TestCase):
    def test_generation_transaction_rolls_back_and_publishes_manifest_last(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mindclade-generation-transaction-") as value:
            repository = Path(value)
            existing = repository / "protocols/generated/example.txt"
            stale = repository / "protocols/generated/stale.txt"
            created = repository / "services/control_plane/generated.txt"
            manifest = repository / generate_protocols.GENERATED_MANIFEST
            existing.parent.mkdir(parents=True)
            existing.write_text("before\n", encoding="utf-8")
            stale.write_text("stale\n", encoding="utf-8")
            outputs = {
                existing: b"after\n",
                created: b"created\n",
                manifest: b'{"complete":true}\n',
            }

            replace = generate_protocols.atomic_replace_generated_file
            attempts = 0

            def fail_second(path: Path, content: bytes, mode: int = 0o644) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    raise OSError("synthetic commit failure")
                replace(path, content, mode)

            with (
                mock.patch.object(
                    generate_protocols,
                    "atomic_replace_generated_file",
                    fail_second,
                ),
                self.assertRaisesRegex(OSError, "synthetic commit failure"),
            ):
                generate_protocols.commit_generation_transaction(repository, outputs, [stale])
            self.assertEqual(existing.read_text(encoding="utf-8"), "before\n")
            self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")
            self.assertFalse(created.exists())
            self.assertFalse(manifest.exists())

            write_order: list[Path] = []

            def observe(path: Path, content: bytes, mode: int = 0o644) -> None:
                write_order.append(path)
                replace(path, content, mode)

            with mock.patch.object(
                generate_protocols,
                "atomic_replace_generated_file",
                observe,
            ):
                generate_protocols.commit_generation_transaction(repository, outputs, [stale])
            self.assertEqual(write_order[-1], manifest)
            self.assertEqual(existing.read_bytes(), b"after\n")
            self.assertEqual(created.read_bytes(), b"created\n")
            self.assertFalse(stale.exists())

    def test_control_plane_explicitly_implements_every_descriptor_rpc(self) -> None:
        repository = root()
        expected = generate_grpc_implementation_coverage.render(repository)
        projection_path = repository / "services/control_plane/grpc-implementation.generated.json"
        self.assertEqual(projection_path.read_bytes(), expected)
        projection = cast(dict[str, Any], json.loads(expected))
        services = cast(list[dict[str, Any]], projection["services"])
        self.assertEqual(projection["service_count"], len(services))
        self.assertEqual(
            projection["explicit_rpc_count"],
            sum(len(cast(list[dict[str, Any]], service["methods"])) for service in services),
        )
        # This exact architecture assertion makes an intentional service-estate
        # change visible in review; the consistency checks above prevent a stale
        # projection from satisfying it accidentally.
        self.assertEqual((projection["service_count"], projection["explicit_rpc_count"]), (16, 138))
        self.assertEqual(
            projection["descriptor_digest"],
            cast(dict[str, Any], candidate(repository)["descriptor_set"])["digest"],
        )

    def test_grpc_authority_rejects_handwritten_transport_contracts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mindclade-grpc-authority-") as temporary:
            fixture = Path(temporary)
            (fixture / "manual.go").write_text(
                "package manual\nvar raw = grpc."
                + "ServiceDesc{}\nserver."
                + "RegisterService(&raw, implementation)\n"
                + "func invoke() { conn.Invoke(ctx, method, input, output) }\n"
                + "type ManualService interface {\n"
                + "  GetWidget(context.Context, *GetWidgetRequest) (*Widget, error)\n"
                + "  ListWidgets(context.Context, *ListWidgetsRequest) (*WidgetList, error)\n"
                + "}\n",
                encoding="utf-8",
            )
            (fixture / "manual.py").write_text(
                "handler = grpc.method_handlers_generic_" + "handler('manual.Service', {})\n",
                encoding="utf-8",
            )
            (fixture / "manual.rs").write_text(
                "impl tonic::server::"
                + 'NamedService for Manual { const NAME: &\'static str = "manual.Service"; }\n',
                encoding="utf-8",
            )
            (fixture / "manual.ts").write_text(
                "const ManualService = { " + "typeName: 'manual.Service', methods: {} };\n",
                encoding="utf-8",
            )
            findings = generate_grpc_implementation_coverage.handwritten_contract_findings(
                fixture,
                {
                    "mindclade.fixture.v1.ManualService": {
                        "GetWidget": {
                            "input_type": "mindclade.fixture.v1.GetWidgetRequest",
                            "output_type": "mindclade.fixture.v1.Widget",
                        },
                        "ListWidgets": {
                            "input_type": "mindclade.fixture.v1.ListWidgetsRequest",
                            "output_type": "mindclade.fixture.v1.WidgetList",
                        },
                    }
                },
            )
        rendered = "\n".join(findings)
        for expected in (
            "raw grpc service descriptor",
            "raw grpc service registration",
            "generic grpc handler construction",
            "raw tonic named-service contract",
            "handwritten Connect service descriptor",
            "reproduces generated service mindclade.fixture.v1.ManualService",
            "generic grpc invocation is outside the sole descriptor-backed HTTP adapter",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, rendered)

    def test_grpc_authority_allows_generated_contract_consumers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mindclade-grpc-authority-") as temporary:
            fixture = Path(temporary)
            (fixture / "server.go").write_text(
                "package server\n"
                + 'import widgetv1 "github.com/mindclade/mindclade/protocols/'
                + 'generated/go/internalrpc/widget/v1"\n'
                + textwrap.dedent(
                    """
                    func register(
                        registrar grpc.ServiceRegistrar,
                        server widgetv1.WidgetServiceServer,
                    ) {
                        widgetv1.RegisterWidgetServiceServer(registrar, server)
                    }
                    """
                ),
                encoding="utf-8",
            )
            (fixture / "server.py").write_text(
                "from mindclade.internal.widget.v1 import widget_service_pb2_grpc as widget_grpc\n"
                "widget_grpc.add_WidgetServiceServicer_" + "to_server(implementation, server)\n",
                encoding="utf-8",
            )
            (fixture / "client.rs").write_text(
                "#[tonic::async_trait]\nimpl WidgetService for Server {}\n",
                encoding="utf-8",
            )
            (fixture / "client.ts").write_text(
                "import type { DescService } from '@bufbuild/protobuf';\n"
                "export function client<S extends DescService>(service: S) { return service; }\n",
                encoding="utf-8",
            )
            findings = generate_grpc_implementation_coverage.handwritten_contract_findings(fixture)
        self.assertEqual(findings, [])

    def test_ratification_evidence_binds_the_complete_supply_chain(self) -> None:
        repository = root()
        bindings: dict[str, Any] = {
            "candidate_descriptor_digest": "sha256:" + "1" * 64,
            "codegen_toolchain_digest": "sha256:" + "2" * 64,
            "event_registry_digest": "sha256:" + "3" * 64,
            "generated_manifest_digest": "sha256:" + "4" * 64,
            "grpc_implementation_digest": "sha256:" + "5" * 64,
            "migration_set_digest": "sha256:" + "6" * 64,
            "openapi_projection_digest": "sha256:" + "7" * 64,
            "sdk_package_digests": {
                language: "sha256:" + value * 64
                for language, value in zip(
                    ("go", "python", "rust", "typescript"),
                    ("8", "9", "a", "b"),
                    strict=True,
                )
            },
            "sdk_rpc_coverage_digest": "sha256:" + "c" * 64,
            "source_revision": "d" * 40,
        }
        evidence = {
            **bindings,
            "checks": {
                name: {"status": "passed", "receipt_digest": "sha256:" + "e" * 64}
                for name in (
                    "cross_language",
                    "database",
                    "event",
                    "gateway",
                    "grpc",
                    "sdk",
                )
            },
            "schema_version": "mindclade.training-vertical-evidence/v2",
            "status": "passed",
        }
        with tempfile.TemporaryDirectory(
            prefix=".ratification-evidence-test-", dir=repository
        ) as temporary:
            path = Path(temporary) / "receipt.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            validated, evidence_digest = generate_protocols.validate_training_vertical_evidence(
                repository, path, bindings=bindings
            )
            self.assertEqual(validated, evidence)
            self.assertEqual(
                evidence_digest, "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            )

            mismatched = copy.deepcopy(evidence)
            mismatched["openapi_projection_digest"] = "sha256:" + "f" * 64
            path.write_text(json.dumps(mismatched), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "openapi_projection_digest"):
                generate_protocols.validate_training_vertical_evidence(
                    repository, path, bindings=bindings
                )

    def test_committed_descriptor_candidate_matches_sources_but_is_not_a_baseline(self) -> None:
        repository = root()
        value = candidate(repository)
        self.assertEqual(value["schema_version"], "mindclade.protobuf-candidate/v1")
        lifecycle = cast(dict[str, Any], value["lifecycle"])
        self.assertEqual(lifecycle["state"], "unratified-candidate")
        self.assertEqual(lifecycle["breaking_enforcement"], "not-started")
        ratification = cast(dict[str, Any], lifecycle["ratification"])
        self.assertEqual(
            ratification["required_evidence"],
            ["cross_language", "database", "event", "gateway", "grpc", "sdk"],
        )
        self.assertEqual(
            ratification["required_bindings"],
            [
                "candidate_descriptor_digest",
                "codegen_toolchain_digest",
                "event_registry_digest",
                "generated_manifest_digest",
                "grpc_implementation_digest",
                "migration_set_digest",
                "openapi_projection_digest",
                "sdk_package_digests",
                "sdk_rpc_coverage_digest",
                "source_revision",
            ],
        )
        self.assertFalse(
            (repository / "protocols/compatibility/baselines/protobuf.lock.json").exists(),
            "normal v1 breaking enforcement must not begin before training ratification",
        )
        sources = cast(dict[str, str], value["sources"])
        actual_sources = {
            path.relative_to(repository).as_posix(): "sha256:"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((repository / "protocols").glob("**/*.proto"))
        }
        self.assertEqual(sources, actual_sources)
        descriptor = base64.b64decode(cast(dict[str, str], value["descriptor_set"])["base64"])
        self.assertEqual(
            cast(dict[str, str], value["descriptor_set"])["digest"],
            "sha256:" + hashlib.sha256(descriptor).hexdigest(),
        )
        if "TEST_SRCDIR" not in os.environ:
            with tempfile.TemporaryDirectory(prefix="mindclade-candidate-descriptor-") as tmp:
                descriptor_json = Path(tmp) / "descriptor.json"
                descriptor_binary = Path(tmp) / "descriptor.binpb"
                environment = {
                    **os.environ,
                    "BUF_CACHE_DIR": str(repository / "build" / "buf-cache"),
                }
                subprocess.run(
                    [
                        "buf",
                        "build",
                        "--exclude-source-info",
                        "--as-file-descriptor-set",
                        "-o",
                        str(descriptor_json),
                    ],
                    cwd=repository,
                    env=environment,
                    check=True,
                )
                subprocess.run(
                    [
                        "buf",
                        "build",
                        str(descriptor_json),
                        "--as-file-descriptor-set",
                        "-o",
                        str(descriptor_binary),
                    ],
                    cwd=repository,
                    env=environment,
                    check=True,
                )
                self.assertEqual(descriptor_binary.read_bytes(), descriptor)

    def test_exact_22_source_predecessor_is_archived_immutably(self) -> None:
        repository = root()
        path = repository / "protocols/compatibility/baselines/protobuf.predecessor.lock.json"
        self.assertEqual(
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "sha256:07d7ee37e68211870861b7fc1ec5118c423447319603523bd9589c1c5dea6aaf",
        )
        value = predecessor(repository)
        self.assertEqual(value["schema_version"], "mindclade.protobuf-baseline/v2")
        self.assertEqual(len(cast(dict[str, str], value["sources"])), 22)
        self.assertEqual(
            cast(dict[str, str], value["descriptor_set"])["digest"],
            "sha256:c817a8313d6378738386f6733337fd54fbeb37c38ddf86ac79859f10afb471d9",
        )
        lifecycle = cast(dict[str, Any], candidate(repository)["lifecycle"])
        predecessor_metadata = cast(dict[str, Any], lifecycle["predecessor"])
        self.assertEqual(
            predecessor_metadata["artifact_digest"],
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            predecessor_metadata["revision"],
            "9b5fbea8a44b15c291c6fd6247a57ad350487544",
        )

    def test_descriptor_preserves_wave_one_scalar_wire_types(self) -> None:
        value = candidate(root())
        encoded = base64.b64decode(cast(dict[str, str], value["descriptor_set"])["base64"])
        descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(encoded)
        fields = {
            f"{file.package}.{message.name}.{field.name}": field.type
            for file in descriptor_set.file
            for message in file.message_type
            for field in message.field
        }
        self.assertEqual(
            fields["mindclade.artifact.v1.ArtifactRef.size_bytes"],
            descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
        )
        self.assertEqual(
            fields["mindclade.job.v1.Attempt.lease_epoch"],
            descriptor_pb2.FieldDescriptorProto.TYPE_UINT64,
        )
        self.assertEqual(
            fields["mindclade.common.v1.PageRequest.page_size"],
            descriptor_pb2.FieldDescriptorProto.TYPE_UINT32,
        )

    def test_event_registry_is_descriptor_complete_strict_and_ratification_bound(self) -> None:
        repository = root()
        value = candidate(repository)
        encoded = base64.b64decode(cast(dict[str, str], value["descriptor_set"])["base64"])
        descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(encoded)
        descriptors = [json_format.MessageToDict(file) for file in descriptor_set.file]
        entries, digest = generate_protocols.event_registry_entries(repository, descriptors)

        descriptor_event_count = sum(
            len(file.message_type)
            for file in descriptor_set.file
            if file.package.startswith("mindclade.events.")
        )
        self.assertEqual(len(entries), descriptor_event_count)
        active = [entry for entry in entries if entry.lifecycle_state == "active"]
        self.assertTrue(active)
        self.assertTrue(all(entry.producers for entry in active))
        self.assertTrue(all(entry.consumers for entry in entries))
        self.assertTrue(all(entry.fixture.status == "verified" for entry in entries))
        blockers = generate_protocols.event_registry_ratification_blockers(entries)
        self.assertEqual(len(active), len(entries) - len(blockers))
        self.assertTrue(
            all(
                entry.activation_gaps == ("producer",)
                for entry in entries
                if entry.full_name in blockers
            )
        )

        registry_binding = cast(dict[str, Any], value["event_registry"])
        self.assertEqual(registry_binding["digest"], digest)
        self.assertEqual(registry_binding["event_count"], descriptor_event_count)
        self.assertEqual(registry_binding["active_event_count"], len(active))
        self.assertEqual(registry_binding["blockers"], list(blockers))
        self.assertEqual(registry_binding["ratifiable"], not blockers)

        for generated_path in (
            "protocols/generated/python/mindclade/events/registry.py",
            "protocols/generated/rust/lib.rs",
            "protocols/generated/typescript/common/v1/index.ts",
            "services/control_plane/internal/platform/queue/event_registry_generated.go",
        ):
            self.assertIn(digest, (repository / generated_path).read_text())

        raw_registry = yaml.safe_load((repository / "protocols/events/registry.yaml").read_text())
        missing_owner = copy.deepcopy(raw_registry)
        del missing_owner["events"][0]["owner"]
        with (
            mock.patch.object(generate_protocols.yaml, "safe_load", return_value=missing_owner),
            self.assertRaisesRegex(ValueError, "fields are invalid"),
        ):
            generate_protocols.event_registry_entries(repository, descriptors)

        active_with_gap = copy.deepcopy(raw_registry)
        job_requested = next(
            event
            for event in active_with_gap["events"]
            if event["full_name"] == "mindclade.events.job.v1.JobRequested"
        )
        job_requested["consumers"] = []
        job_requested["activation_gaps"] = ["semantic-consumer"]
        with (
            mock.patch.object(generate_protocols.yaml, "safe_load", return_value=active_with_gap),
            self.assertRaisesRegex(ValueError, "active event registry entry"),
        ):
            generate_protocols.event_registry_entries(repository, descriptors)

    def test_python_go_rust_and_typescript_round_trip_identical_wire_bytes(self) -> None:
        if "TEST_SRCDIR" in os.environ:
            self.skipTest("native language toolchains are qualified outside the Bazel sandbox")
        repository = root()
        value = candidate(repository)
        fixture = base64.b64decode(cast(dict[str, str], value["wire_fixture"])["base64"])

        sys.path.insert(0, str(repository / "protocols/generated/python"))
        module = importlib.import_module("mindclade.common.v1.identifiers_pb2")
        message = module.Identifiers.FromString(fixture)
        self.assertEqual(message.SerializeToString(deterministic=True), fixture)

        go_source = textwrap.dedent(
            """
            package main
            import (
                "io"
                "os"
                commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
                "google.golang.org/protobuf/proto"
            )
            func main() {
                input, _ := io.ReadAll(os.Stdin)
                value := &commonv1.Identifiers{}
                if err := proto.Unmarshal(input, value); err != nil { panic(err) }
                output, err := (proto.MarshalOptions{Deterministic: true}).Marshal(value)
                if err != nil { panic(err) }
                _, _ = os.Stdout.Write(output)
            }
            """
        )
        with tempfile.NamedTemporaryFile(suffix=".go", mode="w", encoding="utf-8") as source:
            source.write(go_source)
            source.flush()
            go_output = subprocess.run(
                ["go", "run", source.name],
                cwd=repository,
                input=fixture,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
        self.assertEqual(go_output, fixture)

        with tempfile.TemporaryDirectory(prefix="mindclade-rust-roundtrip-") as temporary:
            rust_root = Path(temporary)
            generated = repository / "protocols/generated/rust"
            (rust_root / "Cargo.toml").write_text(
                textwrap.dedent(
                    f"""
                    [package]
                    name = "mindclade-wire-roundtrip"
                    version = "0.0.0"
                    edition = "2024"

                    [dependencies]
                    mindclade-protocols = {{ path = "{generated}" }}
                    prost = "=0.14.4"
                    """
                ),
                encoding="utf-8",
            )
            (rust_root / "src").mkdir()
            (rust_root / "src/main.rs").write_text(
                textwrap.dedent(
                    """
                    use prost::Message;
                    use std::io::{Read, Write};
                    fn main() {
                        let mut input = Vec::new();
                        std::io::stdin().read_to_end(&mut input).unwrap();
                        let value = mindclade_protocols::common::v1::Identifiers
                            ::decode(input.as_slice()).unwrap();
                        std::io::stdout().write_all(&value.encode_to_vec()).unwrap();
                    }
                    """
                ),
                encoding="utf-8",
            )
            rust_output = subprocess.run(
                ["cargo", "run", "--quiet", "--offline"],
                cwd=rust_root,
                env={
                    **os.environ,
                    "CARGO_HOME": str(repository / "build" / "cargo-home"),
                    "CARGO_TARGET_DIR": str(repository / "build" / "rust-roundtrip"),
                },
                input=fixture,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
        self.assertEqual(rust_output, fixture)

        with tempfile.TemporaryDirectory(
            prefix=".protocol-roundtrip-", dir=repository
        ) as temporary:
            compiled = Path(temporary) / "compiled"
            (Path(temporary) / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            subprocess.run(
                [
                    "pnpm",
                    "exec",
                    "tsc",
                    "--project",
                    "protocols/generated/typescript/tsconfig.json",
                    "--noEmit",
                    "false",
                    "--outDir",
                    str(compiled),
                ],
                cwd=repository,
                check=True,
            )
            binding_uri = (compiled / "common/v1/identifiers_pb.js").as_uri()
            script = textwrap.dedent(
                f"""
                import {{ fromBinary, toBinary }} from "@bufbuild/protobuf";
                import {{ IdentifiersSchema }} from "{binding_uri}";
                const chunks = [];
                for await (const chunk of process.stdin) chunks.push(chunk);
                const input = Buffer.concat(chunks);
                const value = fromBinary(IdentifiersSchema, input);
                process.stdout.write(toBinary(IdentifiersSchema, value));
                """
            )
            ts_output = subprocess.run(
                ["node", "--input-type=module", "--eval", script],
                cwd=repository,
                input=fixture,
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
        self.assertEqual(ts_output, fixture)


if __name__ == "__main__":
    unittest.main()
