#!/usr/bin/env python3.12
"""Repository path authority parsing, reconciliation, and validation.

The module deliberately uses the Python standard library only.  The path manifest is
JSON encoded (and therefore valid YAML 1.2). The pinned JSON Schema runtime validates the
structural contract; this module adds repository-specific semantic invariants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TypeGuard, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

API_VERSION = "mindclade.dev/v1"
MANIFEST_KIND = "RepositoryPathManifest"
AUTHORITY_SHA256 = "1854013cd9bf44bf03087e6d5a3de4283b371d878d91e02604c0029e417e5e3b"
BLUEPRINT_SHA256 = "d099074e755168bbdce076d50918bf06aff677f9e5d620fdfe53cb7cef745803"
ANCHOR_COMMIT = "292b71f47b1b29cc9ba7cf760a9bd07cd5e0ffa7"
AUTHORITY_FILE_COUNT = 2461
AUTHORITY_DIRECTORY_COUNT = 787
CANONICAL_FILE_COUNT = 2632
AUTHORITY_PATH_SET_SHA256 = "f2011dd32ccc19649e6abb70ffb4473aea4a224410062d40292222e2e6263692"
CANONICAL_PATH_SET_SHA256 = "c7b3bb14975e394850a2083e5fa5e899352c1b9e4712def7f420f8299c727184"

ADR_REPLACEMENTS = {
    "docs/adr/0001-repository-identity.md": "docs/adr/0001-repository-identity-and-ownership.md",
    "docs/adr/0002-dependency-direction.md": "docs/adr/0002-dependency-and-build-law.md",
    "docs/adr/0003-artifact-identity.md": "docs/adr/0003-artifact-identity-and-cas.md",
    "docs/adr/0004-contract-authority.md": "docs/adr/0004-contract-and-codegen-authority.md",
    "docs/adr/0005-biological-identity.md": (
        "docs/adr/0005-biological-identity-and-schema-evolution.md"
    ),
    "docs/adr/0006-durable-work.md": "docs/adr/0006-durable-work-and-fencing.md",
    "docs/adr/0007-training-state.md": "docs/adr/0007-training-state-progress-and-checkpoint.md",
}

# Sections 14 and 15 require these machine interfaces even though the supplied A6
# rendering omitted them. These lists are intentionally closed and machine tested.
CONNECTED_RATIFICATION_SCHEMA = "docs/adr/connected-ratification.v1.schema.json"
FOUNDER_BOOTSTRAP_ADR = "docs/adr/0008-founder-bootstrap-public-estate-transition.md"
FOUNDER_BOOTSTRAP_SCHEMA = "docs/governance/founder-bootstrap-exception.v1.schema.json"
FOUNDER_BOOTSTRAP_RECORD = "docs/governance/exceptions/FBE-0001.yaml"
FOUNDER_BOOTSTRAP_GOVERNANCE_ADDITIONS = (
    FOUNDER_BOOTSTRAP_ADR,
    FOUNDER_BOOTSTRAP_SCHEMA,
    FOUNDER_BOOTSTRAP_RECORD,
)

NATIVE_SOURCE_INCUBATION_ADR = "docs/adr/0009-native-kernel-source-incubation.md"
NATIVE_SOURCE_INCUBATION_PATHS = (
    "kernels/native/BUILD.bazel",
    "kernels/native/CMakeLists.txt",
    "kernels/native/IMPLEMENTATION_STATUS.md",
    "kernels/native/MIGRATION.md",
    "kernels/native/README.md",
    "kernels/native/__init__.py",
    "kernels/native/cmake/MindcladeTorchStable.cmake",
    "kernels/native/codegen/__init__.py",
    "kernels/native/codegen/discover.py",
    "kernels/native/codegen/generate.py",
    "kernels/native/codegen/parse_literal_ast.py",
    "kernels/native/codegen/schema.py",
    "kernels/native/component.yaml",
    "kernels/native/cuda/CMakeLists.txt",
    "kernels/native/cuda/README.md",
    "kernels/native/cuda/operation_registry.cpp",
    "kernels/native/generated/__init__.py",
    "kernels/native/generated/native_ops.generated.bzl",
    "kernels/native/generated/native_ops.generated.cmake",
    "kernels/native/generated/native_ops.json",
    "kernels/native/generated/operation_registry.generated.cpp",
    "kernels/native/generated/python_registration_generated.py",
    "kernels/native/generated/registration.generated.cpp",
    "kernels/native/manifests/benchmark.schema.json",
    "kernels/native/manifests/native_ops.schema.json",
    "kernels/native/manifests/performance_policy.json",
    "kernels/native/manifests/qualification.schema.json",
    "kernels/native/manifests/tilelang_profiles.sm100.json",
    "kernels/native/manifests/tilelang_profiles.sm90.json",
    "kernels/native/python/__init__.py",
    "kernels/native/python/loader.py",
    "kernels/native/python/qualification.py",
    "kernels/native/python/reference_runtime.py",
    "kernels/native/python/registration.py",
    "kernels/native/stable_abi/CMakeLists.txt",
    "kernels/native/stable_abi/abi_manifest.json",
    "kernels/native/stable_abi/registration.cpp",
    "kernels/native/stable_abi/tensor_bridge.cpp",
    "kernels/native/tests/pytest_runner.py",
    "kernels/native/tests/test_abi_compatibility.py",
    "kernels/native/tests/test_autograd.py",
    "kernels/native/tests/test_build_policy.py",
    "kernels/native/tests/test_cmake_policy.py",
    "kernels/native/tests/test_codegen.py",
    "kernels/native/tests/test_codegen_drift.py",
    "kernels/native/tests/test_discovery.py",
    "kernels/native/tests/test_export.py",
    "kernels/native/tests/test_fake_tensor.py",
    "kernels/native/tests/test_loader_policy.py",
    "kernels/native/tests/test_manifest.py",
    "kernels/native/tests/test_namespace.py",
    "kernels/native/tests/test_opcheck.py",
    "kernels/native/tests/test_parse_literal_ast.py",
    "kernels/native/tests/test_policy.py",
    "kernels/native/tests/test_qualification.py",
    "kernels/native/tests/test_reference_runtime.py",
    "kernels/native/tests/test_schema_manifest.py",
    "kernels/native/tilelang/README.md",
    "kernels/native/tilelang/__init__.py",
    "kernels/native/tilelang/build.py",
    "kernels/native/tilelang/decorator.py",
    "kernels/native/tilelang/manifest.py",
    "kernels/native/tilelang/model.py",
    "kernels/native/tilelang/registry.py",
    "kernels/pairformer/outer_product_mean/BUILD.bazel",
    "kernels/pairformer/outer_product_mean/__init__.py",
    "kernels/pairformer/outer_product_mean/tests/test_outer_product_mean.py",
    "kernels/pairformer/outer_product_mean/tilelang.py",
    "kernels/pairformer/pair_weighted_average/BUILD.bazel",
    "kernels/pairformer/pair_weighted_average/__init__.py",
    "kernels/pairformer/pair_weighted_average/test_tilelang.py",
    "kernels/pairformer/pair_weighted_average/tilelang.py",
    "kernels/pairformer/triangle_attention/BUILD.bazel",
    "kernels/pairformer/triangle_attention/__init__.py",
    "kernels/pairformer/triangle_attention/tests/__init__.py",
    "kernels/pairformer/triangle_attention/tests/test_triangle_attention.py",
    "kernels/pairformer/triangle_attention/tilelang.py",
    "kernels/pairformer/triangle_multiplication/BUILD.bazel",
    "kernels/pairformer/triangle_multiplication/README.md",
    "kernels/pairformer/triangle_multiplication/__init__.py",
    "kernels/pairformer/triangle_multiplication/test_triangle_multiplication.py",
    "kernels/pairformer/triangle_multiplication/tilelang.py",
    "kernels/pairformer/transition/BUILD.bazel",
    "kernels/pairformer/transition/__init__.py",
    "kernels/pairformer/transition/test_transition.py",
    "kernels/pairformer/transition/tilelang.py",
    "kernels/native/generated/tilelang_capabilities.json",
    "kernels/native/manifests/tilelang_capabilities.schema.json",
    "kernels/native/tests/test_tilelang_swizzle.py",
    "kernels/native/tests/test_tilelang_targets.py",
    "kernels/native/tests/test_tilelang_tma.py",
    "kernels/native/tilelang/swizzle.py",
    "kernels/native/tilelang/targets.py",
    "kernels/native/tilelang/tma.py",
)
NATIVE_SOURCE_INCUBATION_ADDITIONS = (
    NATIVE_SOURCE_INCUBATION_ADR,
    *NATIVE_SOURCE_INCUBATION_PATHS,
)

KERNEL_PLATFORM_SOURCE_ADR = "docs/adr/0014-tilelang-kernel-platform-source-development.md"
KERNEL_PLATFORM_SOURCE_PATHS = (
    "kernels/api/BUILD.bazel",
    "kernels/api/__init__.py",
    "kernels/api/backward.py",
    "kernels/api/capability.py",
    "kernels/api/effects.py",
    "kernels/api/environment.py",
    "kernels/api/errors.py",
    "kernels/api/expressions.py",
    "kernels/api/forward.py",
    "kernels/api/gradient.py",
    "kernels/api/implementation.py",
    "kernels/api/kernel.py",
    "kernels/api/launch.py",
    "kernels/api/numerics.py",
    "kernels/api/output.py",
    "kernels/api/program_group.py",
    "kernels/api/qualification.py",
    "kernels/api/schedule.py",
    "kernels/api/workload.py",
    "kernels/api/tests/BUILD.bazel",
    "kernels/api/tests/__init__.py",
    "kernels/api/tests/test_contracts.py",
    "kernels/api/tests/test_expressions.py",
)
KERNEL_PLATFORM_SOURCE_ADDITIONS = (
    KERNEL_PLATFORM_SOURCE_ADR,
    *(path for path in KERNEL_PLATFORM_SOURCE_PATHS if path != "kernels/api/capability.py"),
)
KERNEL_PLATFORM_SOURCE_ACTIVATION_CRITERION = (
    "ADR-0014 permits bounded source development only through 2026-11-30; activate in "
    "Wave 2S only with concrete operation consumers, stable typed contracts, real Bazel "
    "targets, qualification evidence, and a separately reviewed production decision."
)

DEEP_EP_INTAKE_ADR = "docs/adr/0013-deepep-package-and-qualification-boundary.md"
THIRD_PARTY_DEEP_EP_PACKAGE_PATHS = (
    "third_party/packages/deep_ep/BUILD.bazel",
    "third_party/packages/deep_ep/README.md",
    "third_party/packages/deep_ep/artifact_contract.py",
    "third_party/packages/deep_ep/gpu-evidence.schema.json",
    "third_party/packages/deep_ep/package.nix",
    "third_party/packages/deep_ep/repository.bzl",
    "third_party/packages/deep_ep/runtime-manifest.schema.json",
    "third_party/packages/deep_ep/test_package.py",
)
DEEP_EP_PATCH_PATHS = (
    "third_party/patches/deep_ep/declared-toolchain-paths.patch",
    "third_party/patches/deep_ep/deterministic-version.patch",
    "third_party/patches/deep_ep/gin-attestation.patch",
    "third_party/patches/deep_ep/runtime-jit-cache.patch",
)
NATIVE_GENERATED_PROJECTIONS = frozenset(
    {
        "kernels/native/generated/native_ops.generated.bzl",
        "kernels/native/generated/native_ops.generated.cmake",
        "kernels/native/generated/native_ops.json",
        "kernels/native/generated/operation_registry.generated.cpp",
        "kernels/native/generated/python_registration_generated.py",
        "kernels/native/generated/registration.generated.cpp",
    }
)
NATIVE_POLICY_INPUTS = frozenset(
    {
        "kernels/native/BUILD.bazel",
        "kernels/native/CMakeLists.txt",
        "kernels/native/IMPLEMENTATION_STATUS.md",
        "kernels/native/manifests/benchmark.schema.json",
        "kernels/native/manifests/performance_policy.json",
        "kernels/native/manifests/qualification.schema.json",
        "kernels/native/manifests/tilelang_profiles.sm100.json",
        "kernels/native/manifests/tilelang_profiles.sm90.json",
        "kernels/native/MIGRATION.md",
        "kernels/native/README.md",
        "kernels/native/cmake/MindcladeTorchStable.cmake",
        "kernels/native/component.yaml",
        "kernels/native/cuda/CMakeLists.txt",
        "kernels/native/cuda/README.md",
        "kernels/native/cuda/operation_registry.cpp",
        "kernels/native/stable_abi/CMakeLists.txt",
        "kernels/native/stable_abi/abi_manifest.json",
        "kernels/native/stable_abi/registration.cpp",
        "kernels/native/stable_abi/tensor_bridge.cpp",
        "kernels/native/tilelang/README.md",
    }
)
NATIVE_CODEGEN_TEST_LABELS = (
    "//kernels/native:test_build_policy",
    "//kernels/native:test_codegen",
    "//kernels/native:test_codegen_drift",
    "//kernels/native:test_discovery",
    "//kernels/native:test_manifest",
    "//kernels/native:test_parse_literal_ast",
    "//kernels/native:test_schema_manifest",
)
NATIVE_ACTIVATION_CRITERION = (
    "ADR-0009 permits source incubation only through 2026-11-30; activate only after "
    "Wave 5 evidence and an operation-specific JIT-06 decision prove measured need, "
    "reference parity, gradients, locked dependencies, immutable artifacts, fallback, and "
    "revocation."
)

WAVE_TWO_PREFLIGHT_GOVERNANCE_ADDITIONS = (
    "docs/adr/0010-modular-go-control-plane-relational-durability-worker-isolation.md",
    "docs/adr/0011-sqp-001-scientific-qualification-profile.md",
    "docs/adr/0012-http-json-operation-projection-python-sdk.md",
    "docs/policies/pdb-source-use-approval.template.yaml",
    "docs/policies/pdb-source-use-approval.v1.schema.json",
    "docs/policies/pdb-source-use-data-governance.md",
    "docs/policies/sqp-001-h100-approval.template.yaml",
    "docs/policies/sqp-001-h100-approval.v1.schema.json",
    "docs/policies/sqp-001-h100-qualification-envelope.md",
)

ALL_CONTRACT_BASELINE_ADR = (
    "docs/adr/0015-all-contracts-clean-v1-baseline.md"
)

ALL_CONTRACT_BASELINE_DOMAINS = frozenset(
    {
        "admin",
        "agent",
        "dataset",
        "evaluation",
        "experiment",
        "feature",
        "inference",
        "model",
        "policy",
        "training",
        "transform",
        "workflow",
    }
)

ALL_CONTRACT_RUST_PLUGIN_PATHS = (
    "tools/codegen/rust_plugins/Cargo.toml",
    "tools/codegen/rust_plugins/src/bin/protoc-gen-prost.rs",
    "tools/codegen/rust_plugins/src/bin/protoc-gen-tonic.rs",
)

WAVE_ZERO_REQUIRED_ADDITIONS = (
    ".github/actionlint.yaml",
    "docs/architecture/blueprint/provenance/MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md",
    "docs/architecture/blueprint/provenance/MONOREPO_TREE.md",
    "MODULE.bazel.lock",
    "tools/repo/component.schema.json",
    "tools/repo/repository_drift.v1.schema.json",
    "tools/repo/tests/test_build_repository_drift_report.py",
    "tools/repo/tests/test_monorepo_tree_authority.py",
    "tools/repo/tests/test_repository_policies.py",
    "tools/repo/tests/golden/repository_drift.v1.json",
    FOUNDER_BOOTSTRAP_ADR,
    CONNECTED_RATIFICATION_SCHEMA,
    FOUNDER_BOOTSTRAP_SCHEMA,
    FOUNDER_BOOTSTRAP_RECORD,
    DEEP_EP_INTAKE_ADR,
    ALL_CONTRACT_BASELINE_ADR,
    *WAVE_TWO_PREFLIGHT_GOVERNANCE_ADDITIONS,
)

WAVE_ONE_DURABILITY_ADDITIONS = (
    "services/control_plane/internal/operations/operation_commands.go",
    "services/control_plane/internal/operations/operation_repository.go",
    "services/control_plane/internal/operations/operation_reconciler.go",
    "services/control_plane/internal/platform/audit/audit_store.go",
    "services/control_plane/internal/platform/inbox/inbox_store.go",
    "tools/release/sign_release.py",
    "tests/conformance/test_configuration_resolution.py",
    "tests/conformance/test_release_signing.py",
)

GENERATED_PACKAGE_AUTHORITY_ADDITIONS = (
    "protocols/generated/rust/Cargo.toml",
    "protocols/generated/rust/lib.rs",
    "protocols/generated/typescript/package.json",
    "protocols/generated/typescript/tsconfig.json",
    "protocols/generated/python/pyproject.toml",
)

HAND_AUTHORED_GENERATED_PACKAGE_AUTHORITIES = frozenset(
    {
        "protocols/generated/rust/Cargo.toml",
        "protocols/generated/typescript/package.json",
        "protocols/generated/typescript/tsconfig.json",
        "protocols/generated/python/pyproject.toml",
    }
)

WAVE_ONE_REWAVE_PATHS = frozenset(
    {
        "services/control_plane/BUILD.bazel",
        "services/control_plane/README.md",
        "services/control_plane/component.yaml",
        "services/control_plane/internal/artifacts/artifact_commands.go",
        "services/control_plane/internal/artifacts/artifact_reconciler.go",
        "services/control_plane/internal/artifacts/artifact_repository.go",
        "services/control_plane/internal/jobs/job_commands.go",
        "services/control_plane/internal/jobs/job_reconciler.go",
        "services/control_plane/internal/jobs/job_repository.go",
        "services/control_plane/internal/jobs/lease_fencing.go",
        "services/control_plane/internal/platform/database/migration_guard.go",
        "services/control_plane/internal/platform/database/transactions.go",
        "services/control_plane/internal/platform/idempotency/command_keys.go",
        "services/control_plane/internal/platform/idempotency/idempotency_store.go",
        "services/control_plane/internal/platform/outbox/delivery_fencing.go",
        "services/control_plane/internal/platform/outbox/dispatcher.go",
        "services/control_plane/internal/platform/outbox/outbox_store.go",
        "services/control_plane/internal/platform/queue/dead_letter.go",
        "services/control_plane/internal/platform/queue/delivery.go",
        "services/control_plane/internal/platform/queue/transport.go",
        "services/control_plane/internal/platform/storage/artifact_catalog.go",
        "services/control_plane/internal/platform/storage/object_store.go",
        "services/control_plane/internal/platform/telemetry/audit_events.go",
        "services/control_plane/internal/policies/authorization.go",
        "services/control_plane/internal/policies/decision_audit.go",
        "services/control_plane/internal/tenants/tenant_isolation.go",
        "services/control_plane/migrations/000001_kernel.down.sql",
        "services/control_plane/migrations/000001_kernel.up.sql",
        "services/control_plane/migrations/migration_policy.yaml",
        "services/control_plane/tests/idempotency_test.go",
        "services/control_plane/tests/lease_fencing_test.go",
        "services/control_plane/tests/tenant_isolation_test.go",
        "services/control_plane/tests/transaction_outbox_test.go",
        "tests/integration/artifact_commit_test.py",
        "tests/integration/control_worker_test.py",
        "tests/integration/local_stack_test.py",
    }
)

WAVE_ONE_REQUIRED_ADDITIONS = (
    *WAVE_ONE_DURABILITY_ADDITIONS,
    *GENERATED_PACKAGE_AUTHORITY_ADDITIONS,
)

REQUIRED_ADDITIONS = (
    *WAVE_ZERO_REQUIRED_ADDITIONS,
    *WAVE_ONE_REQUIRED_ADDITIONS,
    *KERNEL_PLATFORM_SOURCE_ADDITIONS,
    *NATIVE_SOURCE_INCUBATION_ADDITIONS,
    *THIRD_PARTY_DEEP_EP_PACKAGE_PATHS,
    *DEEP_EP_PATCH_PATHS,
    *ALL_CONTRACT_RUST_PLUGIN_PATHS,
)

STATUSES = {"target", "active", "generated", "deferred", "retired"}
SOURCE_AUTHORITIES = {"hand-authored", "immutable-provenance", "reviewed-generated"}
PRE_ACTIVATION_SOURCE_PATHS = frozenset(
    (*NATIVE_SOURCE_INCUBATION_PATHS, *KERNEL_PLATFORM_SOURCE_PATHS)
)
FORBIDDEN_PATH_TOKENS = ("*", "{", "}", "<", ">", "…")
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
    "dist",
    "node_modules",
    "target",
}
RESTRICTED_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".h5",
    ".kubeconfig",
    ".onnx",
    ".pem",
    ".pth",
    ".pt",
    ".safetensors",
}
OWNER_TEAMS = {
    "agent-platform": "product-engineering",
    "architecture": "architecture",
    "computational-biology": "computational-biology",
    "contract-governance": "architecture",
    "data-platform": "data-platform",
    "developer-experience": "product-engineering",
    "developer-platform": "developer-platform",
    "evaluation-science": "ml-systems",
    "inference-systems": "ml-systems",
    "ml-systems-performance": "ml-systems",
    "model-architecture": "ml-systems",
    "platform-control-plane": "product-engineering",
    "platform-operations": "platform-operations",
    "product-engineering": "product-engineering",
    "release-engineering": "release-engineering",
    "research": "computational-biology",
    "security": "security",
    "training-systems": "ml-systems",
}


class PolicyError(ValueError):
    """A deterministic policy input is invalid."""


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


def _json_schema_errors(value: Any, schema: Mapping[str, Any]) -> list[str]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"invalid repository path manifest schema: {error.message}"]
    validator = Draft202012Validator(schema)
    findings: list[str] = []
    validation_errors = cast(_Validator, validator).iter_errors(value)
    for error in validation_errors:
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        findings.append(f"schema {location}: {error.message}")
    return sorted(findings)


def validate_manifest_schema(manifest: Mapping[str, Any]) -> list[str]:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs/architecture/repository-path-manifest.schema.json"
    )
    if not schema_path.is_file():
        return [f"repository path manifest schema is missing: {schema_path}"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"repository path manifest schema is unreadable: {error}"]
    if not isinstance(schema, Mapping):
        return ["repository path manifest schema root must be an object"]
    return _json_schema_errors(manifest, cast(Mapping[str, Any], schema))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def path_set_sha256(paths: Iterable[str]) -> str:
    normalized = "\n".join(sorted(set(paths))) + "\n"
    return sha256_bytes(normalized.encode("utf-8"))


def normalize_path(value: str) -> str:
    if not value:
        raise PolicyError("repository paths must be non-empty strings")
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise PolicyError(f"path is not canonical POSIX file path: {value!r}")
    if any(token in value for token in FORBIDDEN_PATH_TOKENS):
        raise PolicyError(f"path contains a forbidden generator token: {value!r}")
    path = PurePosixPath(value)
    if str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise PolicyError(f"path is not normalized: {value!r}")
    return value


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(
        isinstance(item, str) for item in cast(list[object], value)
    )


def _is_mapping_list(value: object) -> TypeGuard[list[Mapping[str, Any]]]:
    return isinstance(value, list) and all(
        isinstance(item, Mapping) for item in cast(list[object], value)
    )


def extract_authority_paths(markdown: str) -> list[str]:
    """Parse the one explicit fenced ``mindclade/`` tree in an authority document."""

    matches = list(re.finditer(r"```text\nmindclade/\n(?P<body>.*?)\n```", markdown, re.DOTALL))
    if len(matches) != 1:
        raise PolicyError(f"expected exactly one fenced mindclade tree, found {len(matches)}")

    stack: list[str] = []
    paths: list[str] = []
    for line_number, line in enumerate(matches[0].group("body").splitlines(), start=1):
        match = re.fullmatch(r"(?P<prefix>(?:│   |    )*)(?:├── |└── )(?P<name>.+)", line)
        if match is None:
            raise PolicyError(f"unparseable tree line {line_number}: {line!r}")
        depth = len(match.group("prefix")) // 4
        if depth > len(stack):
            raise PolicyError(f"tree skips a parent at line {line_number}: {line!r}")
        stack = stack[:depth]
        raw_name = match.group("name")
        if "  # " in raw_name:
            name, annotation = raw_name.split("  # ", 1)
            if not name or not annotation.strip():
                raise PolicyError(f"invalid inline tree annotation at line {line_number}: {line!r}")
        else:
            name = raw_name
        is_directory = name.endswith("/")
        leaf = name[:-1] if is_directory else name
        candidate = normalize_path("/".join((*stack, leaf)))
        if is_directory:
            stack.append(leaf)
        else:
            paths.append(candidate)

    if len(paths) != len(set(paths)):
        raise PolicyError("authority tree contains duplicate file paths")
    return paths


def reconcile_authority_paths(source_paths: Sequence[str]) -> list[str]:
    """Apply the closed v3.4.3 plus ADR-0009 reconciliation in display order."""

    source_set = set(source_paths)
    missing = set(ADR_REPLACEMENTS) - source_set
    if missing:
        raise PolicyError(f"ADR reconciliation sources are absent: {sorted(missing)!r}")
    if set(REQUIRED_ADDITIONS) & source_set:
        raise PolicyError("required reconciliation addition already exists in source authority")

    provenance_additions = tuple(
        path
        for path in REQUIRED_ADDITIONS
        if path.startswith("docs/architecture/blueprint/provenance/")
    )
    repository_additions = tuple(
        path for path in REQUIRED_ADDITIONS if path.startswith("tools/repo/")
    )
    contextual_additions = tuple(
        path
        for path in REQUIRED_ADDITIONS
        if path != "MODULE.bazel.lock"
        and path not in provenance_additions
        and path not in repository_additions
    )
    result: list[str] = []
    for path in source_paths:
        result.append(ADR_REPLACEMENTS.get(path, path))
        if path == "MODULE.bazel":
            result.append("MODULE.bazel.lock")
        if path == "docs/architecture/blueprint/manifest.yaml":
            result.extend(provenance_additions)
        if path == "tools/repo/verify_repository_path_manifest.py":
            result.extend(repository_additions)
    for path in contextual_additions:
        parent = PurePosixPath(path).parent
        insert_at = len(result)
        while str(parent) != ".":
            prefix = f"{parent}/"
            related = [
                index for index, candidate in enumerate(result) if candidate.startswith(prefix)
            ]
            if related:
                insert_at = related[-1] + 1
                break
            parent = parent.parent
        result.insert(insert_at, path)
    if len(result) != len(set(result)):
        raise PolicyError("reconciled authority contains duplicate file paths")
    return result


def _top_level(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else "<root>"


def infer_owner(path: str) -> str:
    top = _top_level(path)
    if path == "component.yaml":
        return "product-engineering"
    if path in {"LICENSE", "NOTICE", "SECURITY.md"}:
        return "security"
    if path.startswith("docs/security/"):
        return "security"
    if path.startswith(("docs/runbooks/", "docs/operations/")):
        return "platform-operations"
    if path == "docs/adr/0005-biological-identity-and-schema-evolution.md":
        return "computational-biology"
    if path.startswith(("docs/architecture/", "docs/adr/", "docs/governance/", "docs/policies/")):
        return "architecture"
    if path.startswith("workers/"):
        worker = PurePosixPath(path).parts[1]
        return {
            "ingestion_worker": "data-platform",
            "feature_worker": "data-platform",
            "training_worker": "training-systems",
            "evaluation_worker": "evaluation-science",
            "inference_worker": "inference-systems",
            "agent_worker": "agent-platform",
        }.get(worker, "platform-control-plane")
    if path.startswith("kits/"):
        kit = PurePosixPath(path).parts[1]
        return {
            "mddk": "data-platform",
            "mmdk": "model-architecture",
            "mtdk": "training-systems",
            "medk": "evaluation-science",
            "madk": "agent-platform",
            "mcdk": "platform-operations",
        }.get(kit, "developer-experience")
    return {
        "protocols": "contract-governance",
        "libs": "developer-platform",
        "bio": "computational-biology",
        "data": "data-platform",
        "runtime": "ml-systems-performance",
        "kernels": "ml-systems-performance",
        "models": "model-architecture",
        "training": "training-systems",
        "evaluation": "evaluation-science",
        "inference": "inference-systems",
        "agents": "agent-platform",
        "services": "platform-control-plane",
        "sdk": "developer-experience",
        "apps": "product-engineering",
        "deploy": "platform-operations",
        "research": "research",
        "third_party": "security",
    }.get(top, "developer-platform")


def infer_component(path: str) -> str:
    parts = PurePosixPath(path).parts
    top = parts[0] if parts else ""
    if path == "component.yaml":
        return "mindclade"
    declared_component_roots = (
        ("models/families/clade/cladefold", "model-family-clade-cladefold"),
        ("services/control_plane", "services-control-plane"),
        ("services/runtime_gateway", "services-runtime-gateway"),
        ("services/artifact_proxy", "services-artifact-proxy"),
        ("workers/ingestion_worker", "workers-ingestion-worker"),
        ("workers/feature_worker", "workers-feature-worker"),
        ("workers/training_worker", "workers-training-worker"),
        ("workers/evaluation_worker", "workers-evaluation-worker"),
        ("workers/inference_worker", "workers-inference-worker"),
        ("workers/agent_worker", "workers-agent-worker"),
        ("libs/typescript", "libs-typescript"),
        ("libs/python", "libs-python"),
        ("libs/rust", "libs-rust"),
        ("libs/go", "libs-go"),
        ("sdk/typescript", "sdk-typescript"),
        ("sdk/python", "sdk-python"),
        ("apps/console", "apps-console"),
        ("apps/admin", "apps-admin"),
        ("apps/docs", "apps-docs"),
        ("evaluation", "evaluation"),
        ("inference", "inference"),
        ("training", "training"),
        ("kernels", "kernels"),
        ("runtime", "runtime"),
        ("models", "models"),
        ("agents", "agents"),
        ("deploy", "deploy"),
        ("services", "services"),
        ("workers", "workers"),
        ("bio", "bio"),
        ("data", "data"),
        ("kits", "kits"),
    )
    for root, component in declared_component_roots:
        if path == root or path.startswith(root + "/"):
            return component
    if len(parts) == 1:
        return "repository-governance"
    if top.startswith("."):
        return f"repository-{top.lstrip('.')}"
    if top == "protocols" and len(parts) >= 2:
        if parts[1] in {"proto", "events"} and len(parts) >= 5:
            raw = f"{parts[1]}-{parts[3]}-{parts[4]}"
        elif parts[1] == "generated" and len(parts) >= 5:
            raw = f"generated-{parts[2]}-{parts[3]}-{parts[4]}"
        elif parts[1] == "schemas" and len(parts) >= 3:
            raw = f"schema-{parts[2]}"
        else:
            raw = "-".join(parts[:2])
    elif top == "libs" and len(parts) >= 3:
        raw = f"lib-{parts[1]}-{parts[2]}"
    elif top == "models" and len(parts) >= 4 and parts[1] == "families":
        raw = f"model-family-{parts[2]}-{parts[3]}"
    elif (
        top
        in {
            "bio",
            "data",
            "runtime",
            "kernels",
            "models",
            "training",
            "evaluation",
            "inference",
            "agents",
            "services",
            "workers",
            "sdk",
            "kits",
            "apps",
            "deploy",
            "research",
        }
        and len(parts) >= 2
    ):
        raw = "-".join(parts[:2])
    else:
        raw = "-".join(parts[:2])
    raw = raw.lower().replace("_", "-")
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


def infer_kind(path: str) -> str:
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix.lower()
    if path in HAND_AUTHORED_GENERATED_PACKAGE_AUTHORITIES:
        return "configuration"
    if suffix in {".bzl", ".bazel"} or name in {"BUILD", "BUILD.bazel", "MODULE.bazel"}:
        return "build"
    if "/tests/" in f"/{path}/" or name.startswith("test_") or "_test." in name:
        return "test"
    if suffix in {".md", ".rst"}:
        return "documentation"
    if name.endswith(".schema.json"):
        return "schema"
    if "/fixtures/" in f"/{path}/" or (
        suffix == ".json" and name.startswith(("positive", "negative"))
    ):
        return "fixture"
    if "/schemas/" in f"/{path}/":
        return "schema"
    if suffix in {".yml", ".yaml", ".toml", ".lock"} or name.startswith("."):
        return "configuration"
    if suffix in {".json", ".jsonl"}:
        return "data"
    return "source"


def infer_wave(path: str) -> str:
    if path in WAVE_ONE_REWAVE_PATHS or path in WAVE_ONE_REQUIRED_ADDITIONS:
        return "1"
    if is_wave_zero_path(path):
        return "0"

    parts = PurePosixPath(path).parts
    name = parts[-1] if parts else ""
    top = parts[0]
    if top == "protocols":
        return _protocol_wave(parts)
    if top == "libs":
        return _library_wave(parts)
    if top == "bio":
        return _bio_wave(parts)
    if top == "data":
        return _data_wave(parts)
    if top == "models":
        return _model_wave(parts)
    if top == "evaluation":
        return _evaluation_wave(parts)
    if top == "inference":
        return _inference_wave(parts)
    if top == "runtime":
        if len(parts) == 2 and parts[1] in {"BUILD.bazel", "component.yaml", "README.md"}:
            return "2S"
        if len(parts) > 1 and parts[1] == "distributed":
            return "5"
        if len(parts) > 1 and parts[1] in {"precision", "rng", "testing"}:
            return "2S"
        if len(parts) > 1 and parts[1] in {"compilation", "extensions"}:
            return "6"
        return "4"
    if top == "kernels":
        return _kernel_wave(parts)
    if top == "training":
        return _training_wave(parts)
    if top == "services":
        if len(parts) == 2 and parts[1] in {"BUILD.bazel", "README.md"}:
            return "2P"
        if len(parts) > 3 and parts[1] == "control_plane" and parts[2] == "internal":
            if parts[3] in {"agents", "workflows"}:
                return "7"
            if parts[3] in {"datasets", "experiments", "models"}:
                return "3"
        if len(parts) > 1 and parts[1] == "control_plane":
            return "2P" if _is_platform_slice_service_path(parts) else "4"
        return "4"
    if top == "workers":
        if len(parts) == 2 and parts[1] in {"BUILD.bazel", "README.md"}:
            return "2P"
        if len(parts) > 1 and parts[1] == "agent_worker":
            return "7"
        if len(parts) > 1 and parts[1] == "inference_worker":
            if name in {
                "batch_execution.py",
                "streaming.py",
                "test_batching.py",
                "test_stream_backpressure.py",
            }:
                return "4"
            return "2P"
        if len(parts) > 1 and parts[1] in {"training_worker", "evaluation_worker"}:
            return "3"
        return "4"
    if top == "sdk":
        if len(parts) == 2 and parts[1] in {"BUILD.bazel", "README.md"}:
            return "2P"
        if len(parts) > 1 and parts[1] == "python":
            return "2P" if _is_platform_slice_sdk_path(parts) else "3"
        return "8"
    if top == "agents":
        return "7"
    if top == "kits":
        if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
            return "7"
        return "7" if len(parts) > 1 and parts[1] == "madk" else "8"
    if top == "apps":
        if name in STRUCTURAL_NAMES and (len(parts) == 2 or parts[1] == "console"):
            return "7"
        return "7" if "agents" in parts else "8"
    if top == "deploy":
        if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
            return "1"
        if len(parts) > 1 and parts[1] == "local":
            return "1"
        if len(parts) > 1 and parts[1] in {"crds", "policies"}:
            return "5"
        if len(parts) > 1 and parts[1] == "tests":
            return "5"
        return "4"
    if top == "tests":
        if len(parts) == 2 and parts[1] in {"BUILD.bazel", "README.md"}:
            return "1"
        return _qualification_test_wave(parts)
    if top == "tools":
        if len(parts) > 1 and parts[1] in {"codegen", "release", "qualification"}:
            return "1"
        if len(parts) > 1 and parts[1] == "migration":
            return "3"
        return "8"
    if top == "docs":
        if path == "docs/architecture/artifacts.md":
            return "1"
        if path in {"docs/architecture/training.md", "docs/architecture/inference.md"}:
            return "2S"
        if path == "docs/architecture/agents.md":
            return "7"
        return "8"
    if top == "third_party":
        return "1"
    if top == "research":
        return "8"
    return "8"


STRUCTURAL_NAMES = {"BUILD.bazel", "component.yaml", "README.md"}


def _bio_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    section = parts[1] if len(parts) > 1 else ""
    if section in {"chemistry", "bindings"}:
        return "8"
    if section == "schemas" and len(parts) > 2 and parts[2] == "assembly":
        return "8"
    if section == "entities" and any("assembly" in part for part in parts):
        return "8"
    if section == "formats":
        excluded_formats = {"a3m", "stockholm", "ccd", "sdf"}
        if any(part in excluded_formats for part in parts):
            return "8"
        if any(
            token in name for token in ("rna", "dna", "ligand", "alignment", "stockholm", "sdf")
        ):
            return "8"
    if section == "structures" and any("assembl" in part for part in parts):
        return "8"
    return "2S"


def _data_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    if (
        len(parts) > 2
        and parts[1] == "connectors"
        and parts[2]
        in {
            "uniprot",
            "rnacentral",
            "ccd",
        }
    ):
        return "8"
    if len(parts) > 2 and parts[1] == "transforms":
        transform_section = parts[2]
        if transform_section == "optimization":
            return "6"
        if transform_section in {"fitting"}:
            return "3"
        if transform_section == "contracts" and any(
            part in {"join.py", "aggregate.py", "fitted.py", "runtime_stochastic.py"}
            for part in parts
        ):
            return "3"
        if transform_section == "planning" and any(
            part in {"partition_plan.py", "cost_model.py", "materialization_cost.py"}
            for part in parts
        ):
            return "4"
        if transform_section == "execution" and any(
            part in {"stream_runner.py", "partition_runner.py"} for part in parts
        ):
            return "4"
        if transform_section == "rust" and name in {"stream.rs", "partition.rs"}:
            return "4"
        if transform_section == "fixtures" and any(
            part in {"partition_cases.yaml", "fitted_state_cases.yaml"} for part in parts
        ):
            return "3" if "fitted_state_cases.yaml" in parts else "4"
        if transform_section == "tests":
            if any(token in name for token in ("fit_", "fitting_")):
                return "3"
            if any(token in name for token in ("cost_aware", "optimization_")):
                return "6"
    return "2S"


def _model_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    if len(parts) > 2 and parts[1] == "components" and parts[2] == "confidence":
        return "8"
    if len(parts) > 1 and parts[1] in {"registry", "packaging", "conversion"}:
        return "3"
    if "checkpoint_migration.py" in parts or (
        "conversion" in parts and name in {"bundle_export.py", "bundle_import.py"}
    ):
        return "3"
    if (
        len(parts) > 2
        and parts[1] == "tests"
        and any(token in name for token in ("bundle", "registry"))
    ):
        return "3"
    return "2S"


def _evaluation_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    if (
        len(parts) > 2
        and parts[1] == "suites"
        and parts[2]
        in {
            "complexes",
            "confidence",
            "design",
            "robustness",
            "safety",
        }
    ):
        return "8"
    if (
        len(parts) > 2
        and parts[1] == "metrics"
        and name
        in {
            "confidence_metrics.py",
            "calibration_metrics.py",
        }
    ):
        return "8"
    if len(parts) > 1 and parts[1] == "regression":
        return "3"
    if len(parts) > 2 and parts[1] == "tests" and name == "test_regression_gates.py":
        return "3"
    return "2S"


def _inference_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    section = parts[1] if len(parts) > 1 else ""
    if section == "contracts":
        return "4" if name == "stream_contract.py" else "2P"
    if section == "batching":
        return "4"
    if section == "compilation":
        return "6"
    if section == "ranking":
        return "8"
    if section == "confidence":
        return "8"
    if section == "artifacts" and name == "stream_writer.py":
        return "4"
    if section == "tests" and name == "test_request_contract.py":
        return "2P"
    return "2S"


def _kernel_wave(parts: tuple[str, ...]) -> str:
    name = parts[-1] if parts else ""
    if len(parts) == 2 and parts[1] in STRUCTURAL_NAMES:
        return "2S"
    if len(parts) > 2 and parts[1] == "qualification":
        reference_qualification = {"correctness", "gradients", "determinism", "reports"}
        return "3" if parts[2] in reference_qualification else "6"
    if len(parts) > 1 and parts[1] in {"registry", "dispatch", "benchmarks"}:
        return "6"
    if "benchmarks" in parts or name.startswith("benchmark"):
        return "6"
    if name in {"dispatch.py", "spec.py", "test_dispatch.py"}:
        return "6"
    if (
        len(parts) > 2
        and parts[1] == "tests"
        and name
        in {
            "test_registry.py",
            "test_dispatch_fallback.py",
        }
    ):
        return "6"
    return "2S"


def _protocol_wave(parts: tuple[str, ...]) -> str:
    domain = ""
    family = parts[1] if len(parts) > 1 else ""
    name = parts[-1] if parts else ""
    if family == "generated" and (
        len(parts) <= 4 or name in {"README.generated.md", "generated-files.manifest.json"}
    ):
        return "1"
    if (family in {"proto", "events"} and len(parts) > 3) or (
        family == "generated" and len(parts) > 3
    ):
        domain = parts[3]
    elif family == "schemas" and len(parts) > 2:
        schema = parts[2]
        if schema in {
            "artifact_manifest",
            "evidence_manifest",
            "release_manifest",
            "configuration",
        }:
            return "1"
        if schema in {
            "dataset_manifest",
            "transform_spec",
            "transform_graph",
            "transform_receipt",
            "transform_execution_plan",
            "transform_state_artifact",
            "fit_receipt",
            "lineage_map",
            "feature_contract",
            "feature_requirement_set",
            "model_feature_view",
            "feature_manifest",
            "feature_bundle",
            "feature_plan",
            "feature_derivation_receipt",
            "feature_coverage_manifest",
            "feature_readiness_receipt",
            "training_dataset_manifest",
            "batch_receipt",
            "checkpoint_manifest",
            "evaluation_snapshot",
            "model_manifest",
            "logical_state_schema",
            "training_recipe",
            "training_phase_graph",
            "training_run_manifest",
        }:
            return "3"
        if schema in {"hardware_topology_manifest", "executable_plan", "step_capsule"}:
            return "5"
        if schema in {
            "provider_manifest",
            "compiled_region_manifest",
            "kernel_qualification",
        }:
            return "6"
        if schema in {
            "agent_definition",
            "tool_contract",
            "agent_policy",
            "workflow_definition",
            "agent_run_manifest",
        }:
            return "7"
        return "8"
    elif family in {"compatibility", "BUILD.bazel", "README.md"}:
        return "1"
    elif family == "openapi":
        return "4"

    if domain in {"common", "artifact", "job", "audit"}:
        return "1"
    if domain == "inference":
        if "stream" in name:
            return "4"
        if family == "generated" and len(parts) > 2:
            language = parts[2]
            if language == "rust":
                return "8"
            if language == "typescript":
                return "4"
        return "2P"
    if domain in {"dataset", "model", "training", "evaluation"}:
        return "3"
    if domain in {"feature", "transform", "admin"}:
        return "4"
    if domain in {"agent", "workflow", "policy"}:
        return "7"
    return "8"


def _library_wave(parts: tuple[str, ...]) -> str:
    if len(parts) < 3:
        return "1"
    language, package = parts[1], parts[2]
    kernel = {
        "python": {
            "artifacts",
            "config",
            "contracts",
            "identifiers",
            "observability",
            "retry",
            "serialization",
            "testing",
            "time",
        },
        "rust": {
            "artifact",
            "bytes",
            "config",
            "errors",
            "identifiers",
            "observability",
            "retry",
            "storage",
            "testing",
        },
        "go": {
            "audit",
            "auth",
            "clock",
            "faults",
            "identifiers",
            "observability",
            "storage",
            "testing",
        },
        "typescript": {"config", "observability", "testing"},
    }
    if package in kernel.get(language, set()) or package in {
        "BUILD.bazel",
        "component.yaml",
        "README.md",
    }:
        return "1"
    if language == "go" and package == "kubernetes":
        return "5"
    return "4" if language == "go" else "8"


def _training_wave(parts: tuple[str, ...]) -> str:
    if len(parts) < 2:
        return "2S"
    section = parts[1]
    name = parts[-1] if parts else ""
    if len(parts) == 2 and section in STRUCTURAL_NAMES:
        return "2S"
    if section == "api":
        if name == "parallelism.py":
            return "5"
        if name == "events.py":
            return "4"
        return "2S"
    if section == "execution" and len(parts) > 2:
        return "2S" if parts[2] == "single_process" else "5"
    if section == "providers":
        if len(parts) > 3 and parts[2] == "pytorch" and parts[3] == "native_engine.py":
            return "2S"
        if (
            len(parts) > 3
            and parts[2] == "pytorch"
            and parts[3]
            in {
                "fsdp2_adapter.py",
                "dtensor_adapter.py",
                "dcp_adapter.py",
                "nccl_adapter.py",
            }
        ):
            return "5"
        return "6"
    if section == "precision":
        return "6" if name == "quantization_state.py" else "2S"
    if section == "checkpointing":
        if name in {"dcp.py", "test_dcp.py"}:
            return "5"
        if any(token in name for token in ("reshard", "partial_load")):
            return "5"
        if any(
            token in name
            for token in (
                "async_save",
                "backpressure",
                "inflight",
                "request_coalescing",
                "staging_budget",
            )
        ):
            return "5"
        if any(token in name for token in ("migration", "conversion")):
            return "3"
        if "retention" in name:
            return "4"
        return "2S"
    if section == "tasks":
        task = parts[2] if len(parts) > 2 else ""
        if task in {"supervised", "diffusion", "multitask"}:
            return "2S"
        if task == "pretraining":
            return "3"
        return "8"
    if section == "telemetry":
        if name in {"flight_recorder.py", "step_capsule.py"}:
            return "5"
        if name == "shadow_qualification.py":
            return "6"
    if section == "resilience" and name == "preemption.py":
        return "5"
    if section == "studies":
        return "8"
    if section == "evaluation":
        return "2S" if name == "snapshot.py" else "4"
    if section == "qualification" and len(parts) > 2:
        area = parts[2]
        if area == "distributed":
            return "5"
        if area == "providers":
            return "6"
        if area in {"performance", "long_horizon"}:
            return "5"
        if area == "checkpointing" and name in {"partial_load.py", "reshard.py"}:
            return "5"
        if area == "recovery":
            if name == "preemption.py":
                return "5"
            if name == "stale_attempt.py":
                return "4"
            return "2S"
    if section == "recipes" and len(parts) > 2 and parts[2] == "pretraining":
        return "3"
    if section == "cli" and name == "study.py":
        return "8"
    if section == "cli" and name == "convert_checkpoint.py":
        return "3"
    if section in {
        "core",
        "precision",
        "checkpointing",
        "tasks",
        "evaluation",
        "telemetry",
        "resilience",
        "qualification",
        "recipes",
        "cli",
        "tests",
    }:
        if any(
            token in path_part
            for path_part in parts
            for token in ("distributed", "reshard", "topology")
        ):
            return "5"
        return "2S"
    return "2S"


def _is_platform_slice_service_path(parts: tuple[str, ...]) -> bool:
    if len(parts) < 3:
        return True
    if parts[2] in {"cmd", "migrations", "tests", "BUILD.bazel", "component.yaml", "README.md"}:
        return True
    return (
        len(parts) > 3
        and parts[2] == "internal"
        and parts[3]
        in {
            "artifacts",
            "jobs",
            "policies",
            "projects",
            "tenants",
            "users",
            "platform",
        }
    )


def _is_platform_slice_sdk_path(parts: tuple[str, ...]) -> bool:
    return not any(name in {"models.py", "datasets.py"} for name in parts)


def _qualification_test_wave(parts: tuple[str, ...]) -> str:
    section = parts[1] if len(parts) > 1 else ""
    name = parts[-1] if parts else ""
    if section == "conformance":
        return "1"
    if section == "distributed":
        return "5"
    if section in {"feature_derivation", "transforms"}:
        return "3"
    if section == "end_to_end":
        if "scientific" in name:
            return "2S"
        if "platform" in name:
            return "2P"
        return "3"
    if section == "integration":
        return "2P"
    if section in {"failure_injection", "performance", "security"}:
        return "4"
    return "8"


DEFERRED_PREFIXES = (
    "sdk/go/",
    "sdk/rust/",
    "training/tasks/reinforcement/",
    "training/rl/",
    "training/orchestration/monarch/",
    "training/resilience/live_elasticity/",
    "training/offload/nvme/",
    "training/autotune/",
    "protocols/schemas/autotune_record/",
    "protocols/schemas/rollout_manifest/",
    "services/webhook_dispatcher/",
    "services/event_dispatcher/",
)


def is_wave_zero_path(path: str) -> bool:
    if path in WAVE_ZERO_REQUIRED_ADDITIONS or path in ADR_REPLACEMENTS.values():
        return True
    if "/" not in path:
        return True
    if path.startswith((".buildkite/", ".github/", ".devcontainer/", ".vscode/")):
        return True
    if path.startswith(
        ("tools/bazel/", "tools/ci/", "tools/dev/", "tools/docs/", "tools/licenses/", "tools/repo/")
    ):
        return True
    if path in {"tools/generators/stub_catalog.yaml", "tools/BUILD.bazel", "tools/README.md"}:
        return True
    if path.startswith("docs/architecture/blueprint/") or path.startswith("docs/adr/"):
        return True
    return path in {
        "docs/architecture/repository-path-manifest.yaml",
        "docs/architecture/repository-path-manifest.schema.json",
        "docs/architecture/repository-drift-baseline.md",
        "docs/architecture/dependency-law.md",
        "docs/architecture/trust-boundaries.md",
        "docs/BUILD.bazel",
        "docs/README.md",
        "component.yaml",
    }


def infer_source_authority(path: str) -> str:
    if path.startswith("docs/architecture/blueprint/provenance/"):
        return "immutable-provenance"
    if path in HAND_AUTHORED_GENERATED_PACKAGE_AUTHORITIES:
        return "hand-authored"
    generated_markers = (
        "/generated/",
        "MINDCLADE_MONOREPO_BLUEPRINT_FULL.md",
        "A06-authoritative-repository-tree.md",
        "repository-drift-baseline.md",
        "MODULE.bazel.lock",
        "NOTICE.generated.txt",
    )
    return (
        "reviewed-generated"
        if any(marker in path for marker in generated_markers)
        else "hand-authored"
    )


def _native_source_incubation_kind(path: str) -> str:
    name = PurePosixPath(path).name
    suffix = PurePosixPath(path).suffix
    if path.startswith("kernels/native/tests/"):
        return "test"
    if name.endswith(".schema.json"):
        return "schema"
    if name in {"BUILD.bazel", "CMakeLists.txt"} or suffix in {".bzl", ".cmake"}:
        return "build"
    if suffix == ".md":
        return "documentation"
    if name == "component.yaml" or suffix in {".yaml", ".yml", ".toml"}:
        return "configuration"
    if suffix == ".json":
        return "data"
    return "source"


def _native_source_incubation_targets(path: str) -> tuple[list[str], list[str]]:
    name = PurePosixPath(path).name
    if path.startswith("kernels/pairformer/"):
        operation = PurePosixPath(path).parts[2]
        package = f"//kernels/pairformer/{operation}"
        test_names = {
            "outer_product_mean": "test_outer_product_mean",
            "pair_weighted_average": "test_tilelang",
            "triangle_attention": "test_triangle_attention",
            "triangle_multiplication": "test_triangle_multiplication",
            "transition": "test_transition",
        }
        test_target = f"{package}:{test_names[operation]}"
        if name.startswith("test_") and name.endswith(".py"):
            return [], [test_target]
        if path.endswith("tests/__init__.py"):
            return [], [test_target]
        return [f"{package}:tilelang.py"], []
    if path == "kernels/native/tests/pytest_runner.py":
        return [], list(NATIVE_CODEGEN_TEST_LABELS)
    if path.startswith("kernels/native/tests/") and name.startswith("test_"):
        return [], [f"//kernels/native:{name.removesuffix('.py')}"]
    if path in NATIVE_GENERATED_PROJECTIONS:
        return ["//kernels/native:generate_native_ops"], ["//kernels/native:test_codegen_drift"]

    build_targets: list[str] = []
    if path in NATIVE_POLICY_INPUTS:
        build_targets.append("//kernels/native:native_policy_inputs")
    if path in {
        "kernels/native/stable_abi/registration.cpp",
        "kernels/native/stable_abi/tensor_bridge.cpp",
    }:
        build_targets.append("//kernels/native:native_schema")
    if path.startswith("kernels/native/codegen/"):
        build_targets.append("//kernels/native:native_codegen_lib")
        if path == "kernels/native/codegen/generate.py":
            build_targets.append("//kernels/native:generate_native_ops")
    if path.startswith("kernels/native/tilelang/") and path.endswith(".py"):
        build_targets.append("//kernels/native:tilelang_codegen_lib")
    if path.startswith("kernels/native/manifests/"):
        build_targets.append("//kernels/native:native_codegen_lib")
    if path in {
        "kernels/native/__init__.py",
        "kernels/native/generated/__init__.py",
    } or path.startswith("kernels/native/python/"):
        build_targets.append("//kernels/native:native_python")
    if not build_targets:
        build_targets.append("//kernels/native:native_policy_inputs")
    return list(dict.fromkeys(build_targets)), []


def build_native_source_incubation_entry(path: str) -> dict[str, Any]:
    if path not in NATIVE_SOURCE_INCUBATION_PATHS:
        raise PolicyError(f"unapproved native source-incubation path: {path}")
    generated = path in NATIVE_GENERATED_PROJECTIONS
    build_targets, test_targets = _native_source_incubation_targets(path)
    return {
        "path": path,
        "kind": _native_source_incubation_kind(path),
        "owner": "ml-systems-performance",
        "component": "kernels-native",
        "status": "generated" if generated else "target",
        "activation_wave": "6",
        "source_authority": "reviewed-generated" if generated else "hand-authored",
        "build_targets": build_targets,
        "test_targets": test_targets,
        "public_surface": False,
        "activation_criterion": NATIVE_ACTIVATION_CRITERION,
    }


def _kernel_platform_source_targets(path: str) -> tuple[list[str], list[str]]:
    if path == "kernels/api/tests/test_contracts.py":
        return [], ["//kernels/api/tests:test_contracts"]
    if path == "kernels/api/tests/test_expressions.py":
        return [], ["//kernels/api/tests:test_expressions"]
    if path.startswith("kernels/api/tests/"):
        return [], [
            "//kernels/api/tests:test_contracts",
            "//kernels/api/tests:test_expressions",
        ]
    return ["//kernels/api:api"], []


def build_kernel_platform_source_entry(path: str) -> dict[str, Any]:
    if path not in KERNEL_PLATFORM_SOURCE_PATHS:
        raise PolicyError(f"unapproved kernel-platform source path: {path}")
    build_targets, test_targets = _kernel_platform_source_targets(path)
    return {
        "path": path,
        "kind": (
            "test"
            if path.startswith("kernels/api/tests/") and PurePosixPath(path).name != "BUILD.bazel"
            else infer_kind(path)
        ),
        "owner": "ml-systems-performance",
        "component": "kernels",
        "status": "target",
        "activation_wave": "2S",
        "source_authority": "hand-authored",
        "build_targets": build_targets,
        "test_targets": test_targets,
        "public_surface": False,
        "activation_criterion": KERNEL_PLATFORM_SOURCE_ACTIVATION_CRITERION,
    }


def is_all_contract_baseline_path(path: str) -> bool:
    """Return whether ADR-0015 activates this predeclared v1 projection."""

    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[:2] in {
        ("protocols", "openapi"),
        ("protocols", "schemas"),
    }:
        return True
    if len(parts) >= 6 and parts[:3] in {
        ("protocols", "proto", "mindclade"),
        ("protocols", "events", "mindclade"),
    }:
        return parts[3] in ALL_CONTRACT_BASELINE_DOMAINS and parts[-1].endswith(".proto")
    if len(parts) >= 5 and parts[:2] == ("protocols", "generated"):
        return parts[3] in ALL_CONTRACT_BASELINE_DOMAINS
    return False


def build_all_contract_rust_plugin_entry(path: str) -> dict[str, Any]:
    if path not in ALL_CONTRACT_RUST_PLUGIN_PATHS:
        raise PolicyError(f"unapproved Rust protocol plugin path: {path}")
    return {
        "path": path,
        "kind": infer_kind(path),
        "owner": "contract-governance",
        "component": "codegen-rust-plugins",
        "status": "active",
        "activation_wave": "1",
        "source_authority": "hand-authored",
        "build_targets": ["//:all_contract_sources"],
        "test_targets": ["//:all_contract_tests"],
        "public_surface": False,
        "activation_criterion": (
            "Activated by ADR-0015 as a pinned hermetic Prost/Tonic plugin wrapper; "
            "it grants no release or production authority."
        ),
    }


def build_path_entry(path: str) -> dict[str, Any]:
    if path in ALL_CONTRACT_RUST_PLUGIN_PATHS:
        return build_all_contract_rust_plugin_entry(path)
    if path in KERNEL_PLATFORM_SOURCE_PATHS:
        return build_kernel_platform_source_entry(path)
    if path in NATIVE_SOURCE_INCUBATION_PATHS:
        return build_native_source_incubation_entry(path)
    if path in THIRD_PARTY_DEEP_EP_PACKAGE_PATHS or path in DEEP_EP_PATCH_PATHS:
        package_input = path in THIRD_PARTY_DEEP_EP_PACKAGE_PATHS
        return {
            "path": path,
            "kind": infer_kind(path),
            "owner": "security",
            "component": ("third-party-packages" if package_input else "third-party-patches"),
            "status": "active",
            "activation_wave": "1",
            "source_authority": "hand-authored",
            "build_targets": [
                "//third_party/packages/deep_ep:policy_inputs"
                if package_input
                else "//third_party:wave1_third_party_sources"
            ],
            "test_targets": ["//third_party:test_deep_ep_package_policy"],
            "public_surface": False,
            "activation_criterion": (
                "Development intake only; production use requires an activated consumer, "
                "hardware qualification, artifact SBOM and provenance, and protected review."
            ),
        }
    wave = infer_wave(path)
    deferred = any(path.startswith(prefix) for prefix in DEFERRED_PREFIXES)
    generated = infer_source_authority(path) == "reviewed-generated"
    all_contract_baseline = is_all_contract_baseline_path(path)
    if all_contract_baseline:
        status = "generated" if generated else "active"
    elif deferred:
        status = "deferred"
    elif is_wave_zero_path(path) or wave == "1":
        status = "generated" if generated else "active"
    else:
        status = "target"
    active = status in {"active", "generated"}
    build_targets: list[str] = []
    test_targets: list[str] = []
    if active and wave == "0":
        build_targets = ["//:wave0_governance_sources"]
        test_targets = ["//:wave0_tests"]
    elif active and all_contract_baseline:
        build_targets = ["//:all_contract_sources"]
        test_targets = ["//:all_contract_tests"]
    elif active and wave == "1":
        build_targets = ["//:wave1_sources"]
        test_targets = ["//:wave1_tests"]
    entry: dict[str, Any] = {
        "path": path,
        "kind": infer_kind(path),
        "owner": infer_owner(path),
        "component": infer_component(path),
        "status": status,
        "activation_wave": wave,
        "source_authority": infer_source_authority(path),
        "build_targets": build_targets,
        "test_targets": test_targets,
        "public_surface": path.startswith(("sdk/", "protocols/")),
    }
    if all_contract_baseline:
        entry["activation_criterion"] = (
            "Generated from the ADR-0015 clean-v1 contract baseline; the original wave "
            "remains design-sequencing provenance."
            if generated
            else "Activated by ADR-0015 in the one-time clean-v1 contract baseline; the "
            "original wave remains design-sequencing provenance."
        )
    elif status in {"target", "deferred"} or wave == "1":
        entry["activation_criterion"] = (
            "Activate only in the declared wave with a concrete consumer, owner, real target, "
            "tests, and qualification evidence."
        )
    return entry


def _reconciliation_addition_reason(path: str) -> str:
    if path == ".github/actionlint.yaml":
        return "Required Wave 0 GitHub Actions lint configuration omitted by A6."
    if path == "MODULE.bazel.lock":
        return (
            "Required root workspace lock omitted by A6; Bazel 9 Bzlmod resolution is "
            "generator-owned."
        )
    if path.startswith("docs/architecture/blueprint/provenance/"):
        return "Immutable user-supplied authority provenance required for exact-tree verification."
    if path == CONNECTED_RATIFICATION_SCHEMA:
        return (
            "Required Wave 0 schema for machine-verifiable connected ADR ratification; "
            "declared active before its separately reviewed implementation."
        )
    if path in FOUNDER_BOOTSTRAP_GOVERNANCE_ADDITIONS:
        return (
            "Required Wave 0 governance source for the bounded founder bootstrap and public-estate "
            "transition authorized by ADR-0008."
        )
    if path == KERNEL_PLATFORM_SOURCE_ADR:
        return (
            "Accepted ADR-0014 authority for bounded, pre-activation development of the typed "
            "TileLang kernel-platform contract surface."
        )
    if path in KERNEL_PLATFORM_SOURCE_PATHS:
        return (
            "ADR-0014 bounded Wave 2S kernel-platform API source surface with real Bazel "
            "ownership and tests; TARGET only, with no runtime or production authority."
        )
    if path == NATIVE_SOURCE_INCUBATION_ADR:
        return (
            "Accepted ADR-0009 authority for the bounded, expiring kernels/native "
            "source-incubation exception."
        )
    if path in NATIVE_SOURCE_INCUBATION_PATHS:
        return (
            "ADR-0009 bounded Wave 6 native source-incubation surface; TARGET or "
            "reviewed-generated only, with zero active or qualified operations and no "
            "production authority."
        )
    if path in THIRD_PARTY_DEEP_EP_PACKAGE_PATHS:
        return (
            "Required Wave 1 DeepEP development-intake package definition, documentation, "
            "and source-policy test omitted by A6."
        )
    if path in DEEP_EP_PATCH_PATHS:
        return (
            "ADR-0013 reviewed DeepEP build and qualification patch required for immutable "
            "toolchain discovery, backend attestation, and fail-closed JIT behavior."
        )
    if path == DEEP_EP_INTAKE_ADR:
        return (
            "Accepted bounded DeepEP package and qualification authority required to replace "
            "the unrelated ADR-0009 review reference."
        )
    if path in GENERATED_PACKAGE_AUTHORITY_ADDITIONS:
        return (
            "Required Wave 1 native generated-binding package authority omitted by A6; "
            "keeps native and Bazel compilation authorities explicit."
        )
    if path in WAVE_ONE_DURABILITY_ADDITIONS:
        return (
            "Required Wave 1 durability, reconciliation, configuration, or release-signing "
            "interface omitted by A6."
        )
    if path == ALL_CONTRACT_BASELINE_ADR:
        return (
            "Required accepted authority for the one-time clean-v1 activation of the complete "
            "contract catalog and its generated consumers."
        )
    if path in ALL_CONTRACT_RUST_PLUGIN_PATHS:
        return (
            "Required pinned in-workspace Prost/Tonic plugin wrapper eliminating mutable "
            "cargo-install and cache dependencies from protocol generation."
        )
    if path in WAVE_TWO_PREFLIGHT_GOVERNANCE_ADDITIONS:
        return (
            "Required fail-closed Wave 2 decision or approval contract omitted by A6; "
            "activation records a proposal or pending approval and grants no production authority."
        )
    return (
        "Required Wave 0 schema, deterministic golden, or executable governance test omitted by A6."
    )


def build_manifest(authority_path: Path, blueprint_path: Path) -> dict[str, Any]:
    if sha256_file(authority_path) != AUTHORITY_SHA256:
        raise PolicyError("MONOREPO_TREE.md checksum does not match the immutable authority")
    if sha256_file(blueprint_path) != BLUEPRINT_SHA256:
        raise PolicyError("blueprint checksum does not match v3.4.0 provenance")
    source_paths = extract_authority_paths(authority_path.read_text(encoding="utf-8"))
    if len(source_paths) != AUTHORITY_FILE_COUNT:
        raise PolicyError(
            f"authority must contain {AUTHORITY_FILE_COUNT} files, found {len(source_paths)}"
        )
    blueprint_text = blueprint_path.read_text(encoding="utf-8")
    appendix_start = blueprint_text.find("## Appendix A6 —")
    appendix_end = blueprint_text.find("### A6.1 ", appendix_start)
    if appendix_start < 0 or appendix_end < 0:
        raise PolicyError("cannot locate the authoritative Appendix A6 tree")
    blueprint_paths = extract_authority_paths(blueprint_text[appendix_start:appendix_end])
    if source_paths != blueprint_paths:
        raise PolicyError(
            "MONOREPO_TREE.md and blueprint Appendix A6 differ path-for-path or in order"
        )
    canonical_paths = reconcile_authority_paths(source_paths)
    if len(canonical_paths) != CANONICAL_FILE_COUNT:
        raise PolicyError(f"reconciled manifest must contain {CANONICAL_FILE_COUNT} files")
    additions = [
        {
            "path": path,
            "reason": _reconciliation_addition_reason(path),
        }
        for path in REQUIRED_ADDITIONS
    ]
    additions.extend(
        {
            "path": replacement,
            "replaces": original,
            "reason": (
                "Sections 1-18 and Section 14.1 take precedence over the stale A6 short ADR name."
            ),
        }
        for original, replacement in ADR_REPLACEMENTS.items()
    )
    return {
        "$schema": "./repository-path-manifest.schema.json",
        "api_version": API_VERSION,
        "kind": MANIFEST_KIND,
        "metadata": {
            "name": "mindclade",
            "canonical_repository": "https://github.com/mindclade/mindclade",
            "canonical_anchor_commit": ANCHOR_COMMIT,
            "authority": {
                "source": "MONOREPO_TREE.md",
                "sha256": AUTHORITY_SHA256,
                "blueprint_source": "MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md",
                "blueprint_sha256": BLUEPRINT_SHA256,
                "original_file_count": len(source_paths),
                "original_directory_count": AUTHORITY_DIRECTORY_COUNT,
                "original_path_set_sha256": path_set_sha256(source_paths),
                "original_paths": source_paths,
            },
            "reconciliation": {
                "version": "3.4.3",
                "remove_paths": list(ADR_REPLACEMENTS),
                "additions": additions,
                "canonical_file_count": len(canonical_paths),
                "canonical_path_set_sha256": path_set_sha256(canonical_paths),
            },
            "owners": {
                owner: {"team": f"@mindclade/{team}"} for owner, team in sorted(OWNER_TEAMS.items())
            },
        },
        "paths": [build_path_entry(path) for path in canonical_paths],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot load path manifest {path}: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError("path manifest root must be an object")
    return cast(dict[str, Any], value)


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors = validate_manifest_schema(manifest)
    if manifest.get("api_version") != API_VERSION:
        errors.append(f"api_version must be {API_VERSION}")
    if manifest.get("kind") != MANIFEST_KIND:
        errors.append(f"kind must be {MANIFEST_KIND}")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, Mapping):
        return [*errors, "metadata must be an object"]
    metadata = cast(Mapping[str, Any], metadata)
    authority = metadata.get("authority")
    reconciliation = metadata.get("reconciliation")
    if not isinstance(authority, Mapping) or not isinstance(reconciliation, Mapping):
        return [*errors, "metadata.authority and metadata.reconciliation must be objects"]
    authority = cast(Mapping[str, Any], authority)
    reconciliation = cast(Mapping[str, Any], reconciliation)
    original = authority.get("original_paths")
    if not _is_string_list(original):
        return [*errors, "metadata.authority.original_paths must be a string array"]
    try:
        normalized_original = [normalize_path(path) for path in original]
    except PolicyError as error:
        errors.append(str(error))
        normalized_original = []
    if len(normalized_original) != len(set(normalized_original)):
        errors.append("original authority path list has duplicates")
    if authority.get("sha256") != AUTHORITY_SHA256:
        errors.append("authority document checksum is not the approved MONOREPO_TREE checksum")
    if authority.get("blueprint_sha256") != BLUEPRINT_SHA256:
        errors.append("blueprint checksum is not the approved v3.4.0 provenance checksum")
    if authority.get("original_file_count") != AUTHORITY_FILE_COUNT:
        errors.append(f"original_file_count must be {AUTHORITY_FILE_COUNT}")
    if authority.get("original_directory_count") != AUTHORITY_DIRECTORY_COUNT:
        errors.append(f"original_directory_count must be {AUTHORITY_DIRECTORY_COUNT}")
    if authority.get("original_path_set_sha256") != AUTHORITY_PATH_SET_SHA256:
        errors.append("original authority path-set digest is not the approved digest")
    if authority.get("original_path_set_sha256") != path_set_sha256(normalized_original):
        errors.append("original authority path-set checksum mismatch")

    removes = reconciliation.get("remove_paths")
    additions = reconciliation.get("additions")
    if not _is_string_list(removes):
        errors.append("reconciliation.remove_paths must be a string array")
        removes = []
    if not _is_mapping_list(additions):
        errors.append("reconciliation.additions must be an object array")
        additions = []
    addition_paths = [str(item.get("path", "")) for item in additions]
    expected_additions = set(REQUIRED_ADDITIONS) | set(ADR_REPLACEMENTS.values())
    if list(removes) != list(ADR_REPLACEMENTS):
        errors.append("reconciliation removal list is not the closed ADR replacement set")
    if set(addition_paths) != expected_additions or len(addition_paths) != len(expected_additions):
        errors.append("reconciliation additions are not the closed approved set")
    replacement_map = {
        str(item.get("replaces")): str(item.get("path"))
        for item in additions
        if item.get("replaces") is not None
    }
    if replacement_map != ADR_REPLACEMENTS:
        errors.append("ADR replacement mapping differs from authoritative Section 14 filenames")
    try:
        expected: set[str] = (set(normalized_original) - set(removes)) | {
            normalize_path(path) for path in addition_paths
        }
    except PolicyError as error:
        errors.append(str(error))
        expected = set()
    entries = manifest.get("paths")
    if not isinstance(entries, list):
        return [*errors, "paths must be an array"]
    entries = cast(list[Any], entries)
    entry_paths: list[str] = []
    owners = metadata.get("owners", {})
    if not isinstance(owners, Mapping):
        return [*errors, "metadata.owners must be an object"]
    owners = cast(Mapping[str, Any], owners)
    for index, entry in enumerate(entries):
        prefix = f"paths[{index}]"
        if not isinstance(entry, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        entry = cast(Mapping[str, Any], entry)
        try:
            path = normalize_path(str(entry.get("path", "")))
            entry_paths.append(path)
        except PolicyError as error:
            errors.append(f"{prefix}: {error}")
            continue
        for field in (
            "kind",
            "owner",
            "component",
            "status",
            "activation_wave",
            "source_authority",
            "build_targets",
            "test_targets",
            "public_surface",
        ):
            if field not in entry:
                errors.append(f"{prefix} ({path}) lacks {field}")
        if entry.get("status") not in STATUSES:
            errors.append(f"{prefix} ({path}) has invalid status {entry.get('status')!r}")
        if entry.get("source_authority") not in SOURCE_AUTHORITIES:
            errors.append(f"{prefix} ({path}) has invalid source_authority")
        if entry.get("owner") not in owners:
            errors.append(f"{prefix} ({path}) names unknown owner {entry.get('owner')!r}")
        if entry.get("status") in {"active", "generated"} and (
            not entry.get("build_targets") or not entry.get("test_targets")
        ):
            errors.append(f"{prefix} ({path}) is populated but lacks build/test targets")
        if entry.get("status") in {"target", "deferred"} and not entry.get("activation_criterion"):
            errors.append(f"{prefix} ({path}) lacks an activation criterion")
    if len(entry_paths) != len(set(entry_paths)):
        errors.append("canonical path entries contain duplicates")
    if set(entry_paths) != expected:
        errors.append(
            "original authority plus reconciliation does not equal canonical path entries"
        )
    if normalized_original and entry_paths != reconcile_authority_paths(normalized_original):
        errors.append("canonical path display order is not the deterministic reconciliation order")
    if (
        reconciliation.get("canonical_file_count") != CANONICAL_FILE_COUNT
        or len(entry_paths) != CANONICAL_FILE_COUNT
    ):
        errors.append("canonical_file_count does not match path entries")
    if reconciliation.get("canonical_path_set_sha256") != CANONICAL_PATH_SET_SHA256:
        errors.append("canonical path-set digest is not the approved reconciliation digest")
    if reconciliation.get("canonical_path_set_sha256") != path_set_sha256(entry_paths):
        errors.append("canonical path-set checksum mismatch")
    return errors


def _git_paths(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def discover_actual_paths(root: Path) -> list[str]:
    candidates = _git_paths(root)
    if candidates is None:
        candidates = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]
    paths: list[str] = []
    for candidate in candidates:
        pure = PurePosixPath(candidate)
        if any(part in IGNORED_PARTS for part in pure.parts):
            continue
        if pure.name in {".DS_Store"} or pure.suffix in {".pyc", ".pyo"}:
            continue
        paths.append(normalize_path(candidate))
    return sorted(set(paths))


def validate_populated_paths(
    manifest: Mapping[str, Any], root: Path, *, allow_missing_active: bool = False
) -> dict[str, list[str]]:
    entries = {str(entry["path"]): entry for entry in manifest["paths"]}
    actual = set(discover_actual_paths(root))
    approved = set(entries)
    unknown = sorted(actual - approved)
    premature = sorted(
        path
        for path in actual & approved
        if entries[path].get("status") in {"target", "deferred", "retired"}
        and path not in PRE_ACTIVATION_SOURCE_PATHS
    )
    missing = []
    if not allow_missing_active:
        missing = sorted(
            path
            for path, entry in entries.items()
            if entry.get("status") in {"active", "generated"} and path not in actual
        )
    restricted = sorted(
        path for path in actual if PurePosixPath(path).suffix.lower() in RESTRICTED_SUFFIXES
    )
    oversized = sorted(
        path
        for path in actual
        if (root / path).is_file() and (root / path).stat().st_size > 5 * 1024 * 1024
    )
    return {
        "unknown_paths": unknown,
        "premature_paths": premature,
        "missing_active_paths": missing,
        "restricted_artifacts": restricted,
        "oversized_files": oversized,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--blueprint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--build-manifest", action="store_true")
    parser.add_argument("--allow-missing-active", action="store_true")
    args = parser.parse_args(argv)

    if args.build_manifest:
        if not args.authority or not args.blueprint or not args.output:
            parser.error("--build-manifest requires --authority, --blueprint, and --output")
        manifest = build_manifest(args.authority, args.blueprint)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        return 0
    if not args.manifest:
        parser.error("--manifest is required unless --build-manifest is used")
    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    populated = validate_populated_paths(
        manifest, args.root, allow_missing_active=args.allow_missing_active
    )
    for category, findings in populated.items():
        errors.extend(f"{category}: {path}" for path in findings)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"repository path policy: PASS ({len(manifest['paths'])} canonical files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
