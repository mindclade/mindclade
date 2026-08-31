from __future__ import annotations

import base64
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

from google.protobuf import descriptor_pb2


def root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "protocols" / "compatibility" / "baselines").is_dir():
            return candidate
    raise RuntimeError("cannot locate protocol compatibility baselines")


def baseline(repository: Path) -> dict[str, Any]:
    value: Any = json.loads(
        (repository / "protocols/compatibility/baselines/protobuf.lock.json").read_text()
    )
    if not isinstance(value, dict):
        raise TypeError("Protobuf baseline must be an object")
    return cast(dict[str, Any], value)


class ProtobufCompatibilityTest(unittest.TestCase):
    def test_committed_descriptor_baseline_matches_sources_and_is_non_breaking(self) -> None:
        repository = root()
        value = baseline(repository)
        self.assertEqual(value["schema_version"], "mindclade.protobuf-baseline/v2")
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
            with tempfile.NamedTemporaryFile(suffix=".binpb") as previous:
                previous.write(descriptor)
                previous.flush()
                subprocess.run(
                    ["buf", "breaking", "--against", previous.name],
                    cwd=repository,
                    env={
                        **os.environ,
                        "BUF_CACHE_DIR": str(repository / "build" / "buf-cache"),
                    },
                    check=True,
                )

    def test_descriptor_preserves_wave_one_scalar_wire_types(self) -> None:
        value = baseline(root())
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

    def test_python_go_rust_and_typescript_round_trip_identical_wire_bytes(self) -> None:
        if "TEST_SRCDIR" in os.environ:
            self.skipTest("native language toolchains are qualified outside the Bazel sandbox")
        repository = root()
        value = baseline(repository)
        fixture = base64.b64decode(cast(dict[str, str], value["wire_fixture"])["base64"])

        sys.path.insert(0, str(repository / "protocols/generated/python"))
        module = importlib.import_module("common.v1.identifiers_pb2")
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
