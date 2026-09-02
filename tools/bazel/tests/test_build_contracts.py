#!/usr/bin/env python3.12
"""Focused tests for hermetic build evidence and launch policy."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "bazel"))
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import evidence_bundle  # noqa: E402
import local_cache  # noqa: E402
import rbe_manifest  # noqa: E402
import toolchain_contract  # noqa: E402
import vendor  # noqa: E402

POLICY_IMPLEMENTATION_REVISION = "49a015c2c0cdd6a75a5756eb8c1e95b49d117917"


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def manifest(root: Path, system: str = "x86_64-linux") -> dict[str, object]:
    executable = root / "nix" / "store" / ("a" * 32 + "-tool") / "bin" / "tool"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"tool")
    record = {
        "path": str(executable),
        "sha256": digest(b"tool"),
        "store_path": str(executable.parents[1]),
        "version": "1.0",
    }
    value: dict[str, object] = {
        "schema_version": "mindclade-toolchain.v2",
        "repository": "mindclade/mindclade",
        "system": system,
        "nixpkgs": dict(toolchain_contract.CANONICAL_NIXPKGS),
        "policy": {
            "authority_repository": "mindclade/.github",
            "authority_revision": POLICY_IMPLEMENTATION_REVISION,
            "policy_digest": (
                "sha256:f2cac5e9ef4933544b042b04b6efeddc74a81e533019a6d42ec19d17c37ab34b"
            ),
        },
        "locks": {
            "flake": digest(b"flake"),
            "module": digest(b"module"),
            "policy": digest(b"policy"),
        },
        "executables": {
            name: dict(record) for name in sorted(toolchain_contract.REQUIRED_EXECUTABLES)
        },
    }
    # Unit fixtures use a temporary Nix-shaped root, so file verification is tested separately.
    executables = cast(dict[str, dict[str, str]], value["executables"])
    for item in executables.values():
        item["path"] = item["path"].replace(str(root / "nix" / "store"), "/nix/store")
        item["store_path"] = item["store_path"].replace(str(root / "nix" / "store"), "/nix/store")
    value["toolchain_digest"] = toolchain_contract.digest_object(value, "toolchain_digest")
    return value


def vendor_toolchain(
    root: Path, *, system: str = "x86_64-linux", module_lock: bytes = b"lock"
) -> dict[str, object]:
    value = manifest(root, system)
    locks = cast(dict[str, str], value["locks"])
    locks["module"] = digest(module_lock)
    value["toolchain_digest"] = toolchain_contract.digest_object(value, "toolchain_digest")
    return value


class BuildContractTests(unittest.TestCase):
    def test_generated_estate_policy_is_digest_locked(self) -> None:
        generated = ROOT / "generated"
        lock = json.loads((generated / "nix-bazel-policy.lock.json").read_text())
        self.assertEqual(
            lock["authority"],
            {
                "repository": "mindclade/.github",
                "revision": POLICY_IMPLEMENTATION_REVISION,
            },
        )
        for relative, expected in lock["artifacts"].items():
            if not relative.startswith("generated/"):
                continue
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(digest(path.read_bytes()), expected, relative)

    def test_toolchain_resolution_and_agreement_bind_every_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = manifest(Path(directory))
            executables = cast(dict[str, dict[str, str]], value["executables"])
            observations: dict[str, dict[str, str]] = {}
            for name in sorted(toolchain_contract.RESOLUTION_EXECUTABLES):
                expected_name = "node" if name == "node_runtime" else name
                record = executables[expected_name]
                observations[name] = {
                    "label": f"nix-bootstrap://{name}",
                    "observation": "fixture",
                    "observed_path": record["path"],
                    "observed_provider_path": record["path"],
                    "observed_provider_realpath": record["path"],
                    "observed_sha256": record["sha256"],
                    "observed_store_path": record["store_path"],
                    "provider_version": record["version"],
                    "toolchain_type": "fixture",
                }
            resolution = toolchain_contract.build_resolution(value, observations)
            agreement = toolchain_contract.build_agreement(value, resolution, verify_files=False)
            self.assertEqual(agreement["conclusion"], "PASS")
            agreement_path = Path(directory) / "bazel-native-agreement.v2.json"
            agreement_path.write_text(json.dumps(agreement), encoding="utf-8")
            context = {
                "cache_architecture": "x86_64",
                "cache_mode": "disabled",
                "cache_platform": "linux",
                "cache_toolchain_digest": value["toolchain_digest"],
            }
            evidence_bundle.validate_bazel_receipt(agreement_path, context)
            with self.assertRaisesRegex(ValueError, "toolchain does not match"):
                evidence_bundle.validate_bazel_receipt(
                    agreement_path,
                    {**context, "cache_toolchain_digest": "sha256:" + "0" * 64},
                )
            wrong_system = json.loads(json.dumps(agreement))
            wrong_system["system"] = "aarch64-linux"
            wrong_system["agreement_digest"] = toolchain_contract.digest_object(
                wrong_system, "agreement_digest"
            )
            agreement_path.write_text(json.dumps(wrong_system), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "system does not match"):
                evidence_bundle.validate_bazel_receipt(agreement_path, context)
            agreement_path.write_text(
                json.dumps(
                    {
                        "conclusion": "PASS",
                        "schema_version": "bazel-native-agreement.v1",
                    }
                ),
                encoding="utf-8",
            )
            evidence_bundle.validate_bazel_receipt(agreement_path, context)
            with self.assertRaisesRegex(ValueError, "cannot authorize active cache use"):
                evidence_bundle.validate_bazel_receipt(
                    agreement_path, {**context, "cache_mode": "read"}
                )
            mutated = json.loads(json.dumps(resolution))
            mutated["toolchains"][0]["observed_sha256"] = "sha256:" + "0" * 64
            mutated["resolution_digest"] = toolchain_contract.digest_object(
                mutated, "resolution_digest"
            )
            with self.assertRaisesRegex(ValueError, "differs"):
                toolchain_contract.build_agreement(value, mutated, verify_files=False)

    def test_toolchain_trace_rejects_downloaded_compilers(self) -> None:
        selected = {
            "@bazel_tools//tools/cpp:toolchain_type": (
                "@@rules_cc++cc_configure_extension+local_config_cc//:cc"
            ),
            "@rules_go//go:toolchain": "@@rules_go++go_sdk+go_sdk//:go",
            "@bazel_tools//tools/jdk:runtime_toolchain_type": (
                "@@rules_java++toolchains+local_jdk//:jdk"
            ),
            "@rules_nodejs//nodejs:toolchain_type": (
                "@@+nix_toolchains_repository+nix_toolchains//:node"
            ),
            "@rules_nodejs//nodejs:runtime_toolchain_type": (
                "@@+nix_toolchains_repository+nix_toolchains//:node-runtime"
            ),
            "@bazel_tools//tools/python:toolchain_type": (
                "@@+nix_toolchains_repository+nix_toolchains//:python_toolchain"
            ),
            "@rules_rust//rust:toolchain_type": "@@rules_rust++rust+1.97.1//:rust",
        }
        trace = "\n".join(
            f"type @@repo{toolchain_type[toolchain_type.index('//') :]} -> toolchain {label}"
            for toolchain_type, label in selected.items()
        )
        with self.assertRaisesRegex(ValueError, "downloaded compiler"):
            toolchain_contract.parse_selected_labels(trace)

    def test_bootstrap_identity_requires_the_manifest_symlink_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "store" / "tool" / "bin" / "tool"
            expected.parent.mkdir(parents=True)
            expected.write_bytes(b"tool")
            provider = root / "toolchain" / "bin" / "tool"
            provider.parent.mkdir(parents=True)
            provider.symlink_to(expected)
            identity, realpath = toolchain_contract.bootstrap_identity_path(
                str(provider), str(expected)
            )
            self.assertEqual(identity, expected)
            self.assertEqual(realpath, expected.resolve())
            with self.assertRaisesRegex(ValueError, "does not resolve through"):
                toolchain_contract.bootstrap_identity_path(
                    str(provider), str(root / "store" / "other" / "bin" / "tool")
                )

    def test_local_cache_is_confined_and_disabled_in_ci(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            checkout.mkdir()
            with self.assertRaisesRegex(ValueError, "inside the checkout"):
                local_cache.cache_path(
                    checkout=checkout,
                    repository="mindclade",
                    system="x86_64-linux",
                    override=checkout / "cache",
                )
            with (
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False),
                self.assertRaisesRegex(ValueError, "disabled in CI"),
            ):
                local_cache.ensure_local_only(["test", "//:wave1_tests"])
            with self.assertRaisesRegex(ValueError, "user override is prohibited"):
                local_cache.ensure_local_only(
                    ["test", "//:wave1_tests", "--remote_executor=grpc://unreviewed"]
                )
            for arguments in (
                ["test", "//:wave1_tests", "--config=ci"],
                ["test", "//:wave1_tests", "--config", "ci"],
            ):
                with (
                    self.subTest(arguments=arguments),
                    self.assertRaisesRegex(ValueError, "disabled for ci profiles"),
                ):
                    local_cache.ensure_local_only(arguments)

    def test_rbe_manifest_is_disconnected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = manifest(Path(directory))
            report = rbe_manifest.build(
                value,
                "us-central1-docker.pkg.dev/project/repo/worker@sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
            )
            self.assertEqual(report["execution"]["activation"], "DISCONNECTED_PREPARATION")
            self.assertEqual(report["repository"], value["repository"])
            self.assertEqual(report["policy"], value["policy"])
            tampered = json.loads(json.dumps(value))
            tampered["repository"] = "attacker/other"
            with self.assertRaisesRegex(ValueError, "repository is not canonical"):
                rbe_manifest.build(
                    tampered,
                    "us-central1-docker.pkg.dev/project/repo/worker@sha256:" + "a" * 64,
                    "sha256:" + "b" * 64,
                )
            tampered = json.loads(json.dumps(value))
            tampered["nixpkgs"]["revision"] = "0" * 40
            tampered["toolchain_digest"] = toolchain_contract.digest_object(
                tampered, "toolchain_digest"
            )
            with self.assertRaisesRegex(ValueError, "Nixpkgs identity is not canonical"):
                rbe_manifest.build(
                    tampered,
                    "us-central1-docker.pkg.dev/project/repo/worker@sha256:" + "a" * 64,
                    "sha256:" + "b" * 64,
                )
            self.assertEqual(report["execution"]["remote_executor"], "")

    def test_vendor_manifest_binds_toolchain_system_lock_and_executable_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "MODULE.bazel.lock").write_bytes(b"lock")
            root = repository / "third_party" / "bazel_vendor"
            root.mkdir(parents=True)
            (root / "module.txt").write_bytes(b"module")
            toolchain = vendor_toolchain(repository)
            vendor.write_manifest(root, repository, toolchain)
            vendor.verify(root, repository, toolchain)
            expected = json.loads((root / "vendor-manifest.v1.json").read_text())
            self.assertEqual(expected["system"], "x86_64-linux")
            self.assertEqual(expected["toolchain_digest"], toolchain["toolchain_digest"])

            (root / "module.txt").chmod(0o755)
            with self.assertRaisesRegex(ValueError, "differs"):
                vendor.verify(root, repository, toolchain)

            (root / "module.txt").chmod(0o644)
            wrong_system = vendor_toolchain(repository, system="aarch64-linux")
            with self.assertRaisesRegex(ValueError, "does not match toolchain system"):
                vendor.verify(root, repository, wrong_system)

            wrong_lock = vendor_toolchain(repository, module_lock=b"other")
            with self.assertRaisesRegex(ValueError, "current MODULE.bazel.lock"):
                vendor.verify(root, repository, wrong_lock)

    def test_vendor_manifest_rejects_escaping_symlinks_and_scopes_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "MODULE.bazel.lock").write_bytes(b"lock")
            root = repository / "third_party" / "bazel_vendor"
            root.mkdir(parents=True)
            toolchain = vendor_toolchain(repository)

            (root / "module.txt").write_bytes(b"module")
            (root / "module-link").symlink_to("module.txt")
            vendor.write_manifest(root, repository, toolchain)
            vendor.verify(root, repository, toolchain)

            (root / "relative-escape").symlink_to("../../MODULE.bazel.lock")
            with self.assertRaisesRegex(ValueError, "escapes its root"):
                vendor.inventory(root, repository, toolchain)
            (root / "relative-escape").unlink()

            (root / "absolute-link").symlink_to(repository / "MODULE.bazel.lock")
            with self.assertRaisesRegex(ValueError, "absolute symlink"):
                vendor.inventory(root, repository, toolchain)
            (root / "absolute-link").unlink()

            (root / vendor.IGNORED_SYMLINK).symlink_to(repository / "MODULE.bazel.lock")
            vendor.inventory(root, repository, toolchain)
            nested = root / "nested"
            nested.mkdir()
            (nested / vendor.IGNORED_SYMLINK).symlink_to(repository / "MODULE.bazel.lock")
            with self.assertRaisesRegex(ValueError, "absolute symlink"):
                vendor.inventory(root, repository, toolchain)

    def test_vendor_refresh_uses_fresh_output_root_and_rolls_back_base_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = (Path(directory) / "repository").resolve()
            repository.mkdir()
            (repository / "MODULE.bazel.lock").write_bytes(b"lock")
            root = repository / "third_party" / "bazel_vendor"
            toolchain = vendor_toolchain(repository, system="aarch64-darwin")
            output_roots: list[Path] = []

            def repositories(_repository: Path, _bazel: str, output_root: Path) -> list[str]:
                self.assertFalse(output_root.exists())
                output_roots.append(output_root)
                return []

            patches = (
                mock.patch.object(toolchain_contract, "validate_manifest"),
                mock.patch.object(vendor, "require_host_system"),
                mock.patch.object(
                    vendor, "validated_bazel", return_value="/nix/store/bazel/bin/bazel"
                ),
                mock.patch.object(vendor, "target_repositories", side_effect=repositories),
                mock.patch.object(vendor.subprocess, "run"),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                vendor.refresh(root, repository, toolchain)
                vendor.refresh(root, repository, toolchain)
            self.assertEqual(len(output_roots), 2)
            self.assertNotEqual(output_roots[0], output_roots[1])
            self.assertTrue((root / "vendor-manifest.v1.json").is_file())

            (root / "old").write_text("old", encoding="utf-8")
            original_replace = Path.replace

            def interrupted_replace(path: Path, target: Path) -> Path:
                if path.name == "snapshot":
                    raise KeyboardInterrupt("simulated termination")
                return original_replace(path, target)

            with (
                mock.patch.object(toolchain_contract, "validate_manifest"),
                mock.patch.object(vendor, "require_host_system"),
                mock.patch.object(
                    vendor, "validated_bazel", return_value="/nix/store/bazel/bin/bazel"
                ),
                mock.patch.object(vendor, "target_repositories", return_value=[]),
                mock.patch.object(vendor.subprocess, "run"),
                mock.patch.object(Path, "replace", interrupted_replace),
                self.assertRaises(KeyboardInterrupt),
            ):
                vendor.refresh(root, repository, toolchain)
            self.assertEqual((root / "old").read_text(encoding="utf-8"), "old")

            with mock.patch.object(vendor.signal, "pthread_sigmask") as mask:
                mask.return_value = set()
                with vendor.blocked_replacement_signals():
                    pass
            blocked_signals = mask.call_args_list[0].args[1]
            self.assertIn(vendor.signal.SIGTERM, blocked_signals)

    def test_vendor_offline_binds_platform_tools_and_empty_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "MODULE.bazel.lock").write_bytes(b"lock")
            root = repository / "third_party" / "bazel_vendor"
            root.mkdir(parents=True)
            toolchain = vendor_toolchain(repository)
            (root / "module.txt").write_bytes(b"module")
            vendor.write_manifest(root, repository, toolchain)

            with (
                mock.patch.object(toolchain_contract, "validate_manifest"),
                mock.patch.object(vendor, "host_system", return_value="x86_64-linux"),
                mock.patch.object(
                    vendor,
                    "validated_bazel",
                    return_value="/nix/store/bazel/bin/bazel",
                ),
                mock.patch.object(
                    vendor,
                    "nix_backed_unshare",
                    return_value="/nix/store/util-linux/bin/unshare",
                ),
                mock.patch.object(vendor.subprocess, "run") as run,
                mock.patch.dict(
                    os.environ,
                    {"HTTP_PROXY": "http://proxy", "http_proxy": "http://proxy"},
                    clear=False,
                ),
            ):
                vendor.offline(root, repository, toolchain)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "/nix/store/util-linux/bin/unshare")
            repository_cache_index = next(
                i for i, value in enumerate(command) if value.startswith("--repository_cache=")
            )
            self.assertLess(command.index("test"), repository_cache_index)
            self.assertIn("--repository_disable_download", command)
            self.assertNotIn("--nofetch", command)
            environment = run.call_args.kwargs["env"]
            self.assertNotIn("HTTP_PROXY", environment)
            self.assertNotIn("http_proxy", environment)

            darwin = vendor_toolchain(repository, system="aarch64-darwin")
            vendor.write_manifest(root, repository, darwin)
            with (
                mock.patch.object(toolchain_contract, "validate_manifest"),
                mock.patch.object(vendor, "host_system", return_value="x86_64-linux"),
                self.assertRaisesRegex(ValueError, "does not match toolchain system"),
            ):
                vendor.offline(root, repository, toolchain)

            with (
                mock.patch.object(vendor.platform, "system", return_value="Linux"),
                mock.patch.object(vendor.platform, "machine", return_value="x86_64"),
            ):
                self.assertEqual(vendor.host_system(), "x86_64-linux")
            with (
                mock.patch.object(vendor.platform, "system", return_value="Linux"),
                mock.patch.object(vendor.platform, "machine", return_value="arm64"),
                self.assertRaisesRegex(ValueError, "unsupported host system"),
            ):
                vendor.host_system()

    def test_vendor_bazel_and_unshare_must_match_trusted_nix_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bazel = root / "bazel"
            bazel.write_bytes(b"bazel")
            value = {
                "executables": {
                    "bazel": {
                        "path": str(bazel),
                        "sha256": digest(b"bazel"),
                    }
                }
            }
            with mock.patch.object(vendor, "require_bazel_version"):
                self.assertEqual(vendor.validated_bazel(value, str(bazel)), str(bazel.resolve()))
                other = root / "other-bazel"
                other.write_bytes(b"bazel")
                with self.assertRaisesRegex(ValueError, "differs from toolchain manifest"):
                    vendor.validated_bazel(value, str(other))
                bazel.write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "digest differs"):
                    vendor.validated_bazel(value, str(bazel))
            with (
                mock.patch.object(
                    vendor.subprocess,
                    "run",
                    return_value=mock.Mock(stdout="bazel 9.1.2\n"),
                ),
                self.assertRaisesRegex(ValueError, "Bazel 9.1.1 is required"),
            ):
                vendor.require_bazel_version(str(bazel))
            with (
                mock.patch.object(vendor.shutil, "which", return_value="/usr/bin/true"),
                self.assertRaisesRegex(ValueError, "not Nix-store backed"),
            ):
                vendor.nix_backed_unshare()


if __name__ == "__main__":
    unittest.main()
