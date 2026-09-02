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
CANONICAL_FILE_COUNT = 3342
AUTHORITY_PATH_SET_SHA256 = "f2011dd32ccc19649e6abb70ffb4473aea4a224410062d40292222e2e6263692"
CANONICAL_PATH_SET_SHA256 = "a53521ed4fb8fd9873ba6fae6fa8c1bb256c40445116df695223a5db19634781"

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
    "kernels/native/tests/test_schema.py",
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
    "kernels/pairformer/pair_weighted_average/dispatch.py",
    "kernels/pairformer/pair_weighted_average/reference.py",
    "kernels/pairformer/pair_weighted_average/spec.py",
)
KERNEL_PLATFORM_PREDECLARED_OPERATION_PATHS = (
    "kernels/pairformer/outer_product_mean/dispatch.py",
    "kernels/pairformer/outer_product_mean/reference.py",
    "kernels/pairformer/outer_product_mean/spec.py",
    "kernels/pairformer/transition/dispatch.py",
    "kernels/pairformer/transition/reference.py",
    "kernels/pairformer/transition/spec.py",
    "kernels/pairformer/triangle_attention/dispatch.py",
    "kernels/pairformer/triangle_attention/reference.py",
    "kernels/pairformer/triangle_attention/spec.py",
    "kernels/pairformer/triangle_multiplication/dispatch.py",
    "kernels/pairformer/triangle_multiplication/reference.py",
    "kernels/pairformer/triangle_multiplication/spec.py",
)
KERNEL_PLATFORM_AUTHORIZED_PATHS = (
    *KERNEL_PLATFORM_SOURCE_PATHS,
    *KERNEL_PLATFORM_PREDECLARED_OPERATION_PATHS,
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
        "kernels/native/manifests/pairformer_gpu_qualification.json",
        "kernels/native/manifests/pairformer_gpu_qualification.schema.json",
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
        "kernels/native/python/gpu_qualification.py",
        "kernels/native/stable_abi/CMakeLists.txt",
        "kernels/native/stable_abi/abi_manifest.json",
        "kernels/native/stable_abi/registration.cpp",
        "kernels/native/stable_abi/tensor_bridge.cpp",
        "kernels/native/tests/test_gpu_qualification.py",
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
    "//kernels/native:test_schema",
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

ALL_CONTRACT_BASELINE_ADR = "docs/adr/0015-all-contracts-clean-v1-baseline.md"

ALL_CONTRACT_BASELINE_DOMAINS = frozenset(
    {
        "admin",
        "agent",
        "api",
        "artifact",
        "audit",
        "common",
        "dataset",
        "evaluation",
        "experiment",
        "feature",
        "inference",
        "job",
        "model",
        "policy",
        "training",
        "transform",
        "workflow",
    }
)

ALL_CONTRACT_PYTHON_MODULES = (
    "common/v1/identifiers",
    "common/v1/resource_reference",
    "common/v1/command_context",
    "common/v1/event_envelope",
    "common/v1/error_detail",
    "common/v1/pagination",
    "artifact/v1/artifact_reference",
    "artifact/v1/evidence_reference",
    "artifact/v1/artifact_commands",
    "artifact/v1/artifact_committed",
    "artifact/v1/artifact_quarantined",
    "job/v1/operation",
    "job/v1/job",
    "job/v1/run",
    "job/v1/attempt",
    "job/v1/lease_fencing",
    "job/v1/job_commands",
    "job/v1/job_requested",
    "job/v1/attempt_leased",
    "job/v1/attempt_completed",
    "dataset/v1/dataset",
    "dataset/v1/dataset_release",
    "dataset/v1/dataset_commands",
    "feature/v1/feature_materialization",
    "feature/v1/feature_commands",
    "feature/v1/feature_materialization_completed",
    "transform/v1/transform_execution",
    "transform/v1/transform_commands",
    "transform/v1/transform_execution_completed",
    "experiment/v1/experiment",
    "experiment/v1/study",
    "experiment/v1/trial",
    "model/v1/model",
    "model/v1/model_release",
    "model/v1/model_commands",
    "model/v1/model_registered",
    "model/v1/model_promoted",
    "model/v1/model_revoked",
    "training/v1/training_run",
    "training/v1/training_progress",
    "training/v1/checkpoint",
    "training/v1/training_commands",
    "training/v1/training_started",
    "training/v1/progress_committed",
    "training/v1/checkpoint_committed",
    "training/v1/training_completed",
    "training/v1/training_run_created",
    "training/v1/training_cancellation_requested",
    "inference/v1/inference_request",
    "inference/v1/inference_result",
    "inference/v1/inference_stream",
    "evaluation/v1/evaluation_run",
    "evaluation/v1/evaluation_result",
    "evaluation/v1/promotion_decision",
    "agent/v1/agent_definition",
    "agent/v1/agent_run",
    "agent/v1/agent_step",
    "agent/v1/tool_receipt",
    "agent/v1/agent_step_dispatched",
    "agent/v1/tool_receipt_committed",
    "agent/v1/agent_run_completed",
    "workflow/v1/workflow_definition",
    "workflow/v1/workflow_run",
    "workflow/v1/approval",
    "workflow/v1/workflow_transitioned",
    "workflow/v1/approval_recorded",
    "policy/v1/policy_reference",
    "policy/v1/authorization_decision",
    "policy/v1/use_policy",
    "admin/v1/tenant",
    "admin/v1/project",
    "admin/v1/audit_query",
    "audit/v1/audit_event",
    "audit/v1/security_event",
)

ALL_CONTRACT_PYTHON_STUB_PATHS = tuple(
    f"protocols/generated/python/mindclade/{module}_pb2.pyi"
    for module in ALL_CONTRACT_PYTHON_MODULES
)

ALL_CONTRACT_GRPC_SERVICES = (
    ("artifact", "artifact_service", "internal/artifact"),
    ("job", "job_service", "internal/job"),
    ("dataset", "dataset_service", "internal/dataset"),
    ("training", "training_service", "internal/training"),
    ("model", "model_service", "internal/model"),
    ("inference", "inference_service", "internal/inference"),
    ("evaluation", "evaluation_service", "internal/evaluation"),
    ("agent", "agent_service", "internal/agent"),
    ("workflow", "workflow_service", "internal/workflow"),
    ("policy", "policy_service", "internal/policy"),
    ("admin", "admin_service", "internal/admin"),
    ("api", "mindclade_service", "api"),
)

ALL_CONTRACT_GRPC_SOURCE_PATHS = tuple(
    f"protocols/proto/mindclade/{source_family}/v1/{stem}.proto"
    for _, stem, source_family in ALL_CONTRACT_GRPC_SERVICES
)

ALL_CONTRACT_GRPC_PROJECTION_PATHS = tuple(
    path
    for _, stem, output_family in ALL_CONTRACT_GRPC_SERVICES
    for path in (
        "protocols/generated/go/"
        f"{output_family.replace('internal/', 'internalrpc/')}/v1/{stem}.pb.go",
        "protocols/generated/go/"
        f"{output_family.replace('internal/', 'internalrpc/')}/v1/{stem}_grpc.pb.go",
        f"protocols/generated/python/mindclade/{output_family}/v1/{stem}_pb2.py",
        f"protocols/generated/python/mindclade/{output_family}/v1/{stem}_pb2.pyi",
        f"protocols/generated/python/mindclade/{output_family}/v1/{stem}_pb2_grpc.py",
        f"protocols/generated/python/mindclade/{output_family}/v1/{stem}_pb2_grpc.pyi",
        f"protocols/generated/rust/{output_family}/v1/{stem}.rs",
        f"protocols/generated/rust/{output_family}/v1/{stem}_grpc.rs",
        f"protocols/generated/typescript/{output_family}/v1/{stem}_pb.ts",
    )
)

ALL_CONTRACT_GRPC_PACKAGE_PATHS = tuple(
    path
    for _, _, output_family in ALL_CONTRACT_GRPC_SERVICES
    for path in (
        "protocols/generated/go/"
        f"{output_family.replace('internal/', 'internalrpc/')}/v1/BUILD.bazel",
        f"protocols/generated/python/mindclade/{output_family}/v1/__init__.py",
        f"protocols/generated/rust/{output_family}/v1/mod.rs",
        f"protocols/generated/typescript/{output_family}/v1/index.ts",
    )
)

ALL_CONTRACT_GRPC_ADDITIONS = (
    *ALL_CONTRACT_PYTHON_STUB_PATHS,
    *ALL_CONTRACT_GRPC_SOURCE_PATHS,
    *ALL_CONTRACT_GRPC_PROJECTION_PATHS,
    *ALL_CONTRACT_GRPC_PACKAGE_PATHS,
)

TRAINING_EVENT_CONTRACT_ADDITIONS = (
    "protocols/events/mindclade/training/v1/training_run_created.proto",
    "protocols/events/mindclade/training/v1/training_cancellation_requested.proto",
    "protocols/generated/go/training/v1/training_run_created.pb.go",
    "protocols/generated/go/training/v1/training_cancellation_requested.pb.go",
    "protocols/generated/python/mindclade/training/v1/training_run_created_pb2.py",
    "protocols/generated/python/mindclade/training/v1/training_cancellation_requested_pb2.py",
    "protocols/generated/rust/training/v1/training_run_created.rs",
    "protocols/generated/rust/training/v1/training_cancellation_requested.rs",
    "protocols/generated/typescript/training/v1/training_run_created_pb.ts",
    "protocols/generated/typescript/training/v1/training_cancellation_requested_pb.ts",
)

VERTICAL_EVENT_CONTRACTS = (
    ("admin", "audit_export_completed"),
    ("admin", "audit_export_requested"),
    ("admin", "project_created"),
    ("admin", "project_updated"),
    ("admin", "tenant_updated"),
    ("agent", "agent_cancellation_requested"),
    ("agent", "agent_definition_created"),
    ("agent", "agent_definition_updated"),
    ("agent", "agent_run_started"),
    ("agent", "agent_step_committed"),
    ("dataset", "dataset_created"),
    ("dataset", "dataset_release_published"),
    ("dataset", "dataset_release_revoked"),
    ("dataset", "dataset_updated"),
    ("evaluation", "evaluation_cancellation_requested"),
    ("evaluation", "evaluation_result_committed"),
    ("evaluation", "evaluation_run_created"),
    ("evaluation", "promotion_decision_recorded"),
    ("inference", "inference_requested"),
    ("inference", "inference_result_committed"),
    ("model", "model_release_registered"),
    ("policy", "authorization_decision_recorded"),
    ("policy", "use_policy_activated"),
    ("policy", "use_policy_created"),
    ("policy", "use_policy_revoked"),
    ("policy", "use_policy_updated"),
    ("workflow", "approval_consumed"),
    ("workflow", "approval_requested"),
    ("workflow", "workflow_cancellation_requested"),
    ("workflow", "workflow_definition_created"),
    ("workflow", "workflow_definition_updated"),
    ("workflow", "workflow_run_started"),
)

VERTICAL_EVENT_CONTRACT_ADDITIONS = tuple(
    path
    for domain, stem in VERTICAL_EVENT_CONTRACTS
    for path in (
        f"protocols/events/mindclade/{domain}/v1/{stem}.proto",
        f"protocols/generated/go/{domain}/v1/{stem}.pb.go",
        f"protocols/generated/python/mindclade/{domain}/v1/{stem}_pb2.py",
        f"protocols/generated/python/mindclade/{domain}/v1/{stem}_pb2.pyi",
        f"protocols/generated/rust/{domain}/v1/{stem}.rs",
        f"protocols/generated/typescript/{domain}/v1/{stem}_pb.ts",
    )
)

ALL_CONTRACT_RUST_PLUGIN_PATHS = (
    "tools/codegen/rust_plugins/Cargo.toml",
    "tools/codegen/rust_plugins/src/bin/protoc-gen-prost.rs",
    "tools/codegen/rust_plugins/src/bin/protoc-gen-tonic.rs",
)

CONTRACT_RUNTIME_ADDITIONS = (
    "buf.lock",
    "protocols/events/registry.yaml",
    "protocols/compatibility/baselines/protobuf.candidate.json",
    "protocols/compatibility/baselines/protobuf.predecessor.lock.json",
    "protocols/generated/python/mindclade/events/registry.py",
    "protocols/generated/typescript/google/api/annotations_pb.ts",
    "protocols/generated/typescript/google/api/http_pb.ts",
    "services/control_plane/internal/platform/queue/event_registry_generated.go",
)

SCHEMA_BINDING_ADDITIONS = (
    "protocols/generated/go/schema/v1/BUILD.bazel",
    "protocols/generated/go/schema/v1/bindings.generated.go",
    "protocols/generated/go/schema/v1/bindings_generated_test.go",
    "protocols/generated/python/mindclade/schema/v1/__init__.py",
    "protocols/generated/python/mindclade/schema/v1/bindings.py",
    "protocols/generated/rust/schema/v1.rs",
    "protocols/generated/typescript/schema/v1/bindings.ts",
)

WAVE_ZERO_REQUIRED_ADDITIONS = (
    ".bazelignore",
    ".golangci.yml",
    ".github/actionlint.yaml",
    "biome.json",
    "docs/architecture/blueprint/provenance/MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md",
    "docs/architecture/blueprint/provenance/MONOREPO_TREE.md",
    "docs/architecture/authoritative-contract-integration-plan.md",
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

# ADR-0015 couples each newly activated contract family to its first executable
# producer/consumer.  These additions are intentionally exact rather than
# prefix based: adding a new SDK or training file still requires an explicit
# governance review and manifest refresh.
INTERNAL_SDK_ADDITIONS = (
    "internal/sdk/README.md",
    "internal/sdk/go/mindclade/BUILD.bazel",
    "internal/sdk/go/mindclade/README.md",
    "internal/sdk/go/mindclade/admin.go",
    "internal/sdk/go/mindclade/agent_test.go",
    "internal/sdk/go/mindclade/agents.go",
    "internal/sdk/go/mindclade/approvals.go",
    "internal/sdk/go/mindclade/artifacts.go",
    "internal/sdk/go/mindclade/auth.go",
    "internal/sdk/go/mindclade/auth_test.go",
    "internal/sdk/go/mindclade/client.go",
    "internal/sdk/go/mindclade/client_test.go",
    "internal/sdk/go/mindclade/config.go",
    "internal/sdk/go/mindclade/datasets.go",
    "internal/sdk/go/mindclade/error.go",
    "internal/sdk/go/mindclade/evaluations.go",
    "internal/sdk/go/mindclade/evaluations_test.go",
    "internal/sdk/go/mindclade/interceptors.go",
    "internal/sdk/go/mindclade/inference.go",
    "internal/sdk/go/mindclade/inference_test.go",
    "internal/sdk/go/mindclade/lifecycle_test.go",
    "internal/sdk/go/mindclade/method_policy.go",
    "internal/sdk/go/mindclade/models.go",
    "internal/sdk/go/mindclade/operations.go",
    "internal/sdk/go/mindclade/policy_test.go",
    "internal/sdk/go/mindclade/policies.go",
    "internal/sdk/go/mindclade/policy_admin_test.go",
    "internal/sdk/go/mindclade/request.go",
    "internal/sdk/go/mindclade/training.go",
    "internal/sdk/go/mindclade/transport.go",
    "internal/sdk/go/mindclade/workflow_test.go",
    "internal/sdk/go/mindclade/workflows.go",
    "internal/sdk/python/BUILD.bazel",
    "internal/sdk/python/README.md",
    "internal/sdk/python/mindclade_internal_sdk/__init__.py",
    "internal/sdk/python/mindclade_internal_sdk/_invocation.py",
    "internal/sdk/python/mindclade_internal_sdk/_validation.py",
    "internal/sdk/python/mindclade_internal_sdk/admin.py",
    "internal/sdk/python/mindclade_internal_sdk/agents.py",
    "internal/sdk/python/mindclade_internal_sdk/artifacts.py",
    "internal/sdk/python/mindclade_internal_sdk/auth.py",
    "internal/sdk/python/mindclade_internal_sdk/calls.py",
    "internal/sdk/python/mindclade_internal_sdk/client.py",
    "internal/sdk/python/mindclade_internal_sdk/config.py",
    "internal/sdk/python/mindclade_internal_sdk/datasets.py",
    "internal/sdk/python/mindclade_internal_sdk/errors.py",
    "internal/sdk/python/mindclade_internal_sdk/generated.py",
    "internal/sdk/python/mindclade_internal_sdk/inference.py",
    "internal/sdk/python/mindclade_internal_sdk/method_policy.py",
    "internal/sdk/python/mindclade_internal_sdk/models.py",
    "internal/sdk/python/mindclade_internal_sdk/operations.py",
    "internal/sdk/python/mindclade_internal_sdk/policies.py",
    "internal/sdk/python/mindclade_internal_sdk/testing.py",
    "internal/sdk/python/mindclade_internal_sdk/training.py",
    "internal/sdk/python/mindclade_internal_sdk/transport.py",
    "internal/sdk/python/mindclade_internal_sdk/workflows.py",
    "internal/sdk/python/pyproject.toml",
    "internal/sdk/python/tests/test_internal_sdk.py",
    "internal/sdk/python/tests/test_agents.py",
    "internal/sdk/python/tests/test_inference.py",
    "internal/sdk/python/tests/test_policy_admin.py",
    "internal/sdk/python/tests/test_workflows.py",
    "internal/sdk/rust/BUILD.bazel",
    "internal/sdk/rust/Cargo.toml",
    "internal/sdk/rust/README.md",
    "internal/sdk/rust/src/admin.rs",
    "internal/sdk/rust/src/agent_tests.rs",
    "internal/sdk/rust/src/agents.rs",
    "internal/sdk/rust/src/approvals.rs",
    "internal/sdk/rust/src/artifacts.rs",
    "internal/sdk/rust/src/auth.rs",
    "internal/sdk/rust/src/config.rs",
    "internal/sdk/rust/src/datasets.rs",
    "internal/sdk/rust/src/error.rs",
    "internal/sdk/rust/src/inference.rs",
    "internal/sdk/rust/src/lib.rs",
    "internal/sdk/rust/src/models.rs",
    "internal/sdk/rust/src/operations.rs",
    "internal/sdk/rust/src/policies.rs",
    "internal/sdk/rust/src/policy_admin_tests.rs",
    "internal/sdk/rust/src/request.rs",
    "internal/sdk/rust/src/retry.rs",
    "internal/sdk/rust/src/tests.rs",
    "internal/sdk/rust/src/training.rs",
    "internal/sdk/rust/src/transport.rs",
    "internal/sdk/rust/src/workflow_tests.rs",
    "internal/sdk/rust/src/workflows.rs",
    "internal/sdk/typescript/BUILD.bazel",
    "internal/sdk/typescript/README.md",
    "internal/sdk/typescript/biome.json",
    "internal/sdk/typescript/package.json",
    "internal/sdk/typescript/src/admin.ts",
    "internal/sdk/typescript/src/agents.ts",
    "internal/sdk/typescript/src/approvals.ts",
    "internal/sdk/typescript/src/artifacts.ts",
    "internal/sdk/typescript/src/auth.ts",
    "internal/sdk/typescript/src/client.ts",
    "internal/sdk/typescript/src/config.ts",
    "internal/sdk/typescript/src/core.ts",
    "internal/sdk/typescript/src/datasets.ts",
    "internal/sdk/typescript/src/error.ts",
    "internal/sdk/typescript/src/gcp_auth.ts",
    "internal/sdk/typescript/src/inference.ts",
    "internal/sdk/typescript/src/index.ts",
    "internal/sdk/typescript/src/models.ts",
    "internal/sdk/typescript/src/operations.ts",
    "internal/sdk/typescript/src/policies.ts",
    "internal/sdk/typescript/src/raw.ts",
    "internal/sdk/typescript/src/request.ts",
    "internal/sdk/typescript/src/retry.ts",
    "internal/sdk/typescript/src/runtime.ts",
    "internal/sdk/typescript/src/safety.ts",
    "internal/sdk/typescript/src/testing.ts",
    "internal/sdk/typescript/src/training.ts",
    "internal/sdk/typescript/src/transport.ts",
    "internal/sdk/typescript/src/workflows.ts",
    "internal/sdk/typescript/tests/sdk.test.ts",
    "internal/sdk/typescript/tests/policy_admin.test.ts",
    "internal/sdk/typescript/tests/agents.test.ts",
    "internal/sdk/typescript/tests/workflow_approval.test.ts",
    "internal/sdk/typescript/tsconfig.json",
)

TRAINING_VERTICAL_ADDITIONS = (
    "services/control_plane/internal/training/BUILD.bazel",
    "services/control_plane/internal/training/cancellation_sql.go",
    "services/control_plane/internal/training/contracts.go",
    "services/control_plane/internal/training/events.go",
    "services/control_plane/internal/training/list_sql.go",
    "services/control_plane/internal/training/mapping_sql.go",
    "services/control_plane/internal/training/pagination.go",
    "services/control_plane/internal/training/postgres_integration_test.go",
    "services/control_plane/internal/training/repository_sql.go",
    "services/control_plane/internal/training/server.go",
    "services/control_plane/internal/training/training_test.go",
    "services/control_plane/internal/training/validation.go",
)

CONTROL_PLANE_TRANSPORT_ADDITIONS = (
    "services/control_plane/cmd/control-plane/auth_google.go",
    "services/control_plane/cmd/control-plane/training_adapter.go",
    "services/control_plane/cmd/control-plane/wire_test.go",
)

WORKER_COORDINATION_ADDITIONS = (
    "services/control_plane/internal/jobs/server.go",
    "services/control_plane/internal/jobs/server_test.go",
)

ARTIFACT_VERTICAL_ADDITIONS = (
    "services/control_plane/internal/artifacts/contracts.go",
    "services/control_plane/internal/artifacts/postgres_integration_test.go",
    "services/control_plane/internal/artifacts/repository_sql.go",
    "services/control_plane/internal/artifacts/server.go",
    "services/control_plane/internal/artifacts/server_test.go",
    "services/control_plane/internal/artifacts/staging_receipts.go",
    "services/control_plane/internal/platform/storage/gcs_object_store.go",
    "services/control_plane/internal/platform/storage/gcs_object_store_test.go",
    "services/control_plane/migrations/000002_artifacts.down.sql",
    "services/control_plane/migrations/000002_artifacts.up.sql",
)

DATA_MODEL_VERTICAL_ADDITIONS = (
    "services/control_plane/internal/datasets/BUILD.bazel",
    "services/control_plane/internal/datasets/contracts.go",
    "services/control_plane/internal/datasets/datasets_test.go",
    "services/control_plane/internal/datasets/events.go",
    "services/control_plane/internal/datasets/mutations_sql.go",
    "services/control_plane/internal/datasets/pagination.go",
    "services/control_plane/internal/datasets/postgres_integration_test.go",
    "services/control_plane/internal/datasets/repository_sql.go",
    "services/control_plane/internal/datasets/server.go",
    "services/control_plane/internal/models/BUILD.bazel",
    "services/control_plane/internal/models/contracts.go",
    "services/control_plane/internal/models/events.go",
    "services/control_plane/internal/models/list_sql.go",
    "services/control_plane/internal/models/mapping_sql.go",
    "services/control_plane/internal/models/models_test.go",
    "services/control_plane/internal/models/pagination.go",
    "services/control_plane/internal/models/postgres_integration_test.go",
    "services/control_plane/internal/models/repository_sql.go",
    "services/control_plane/internal/models/server.go",
    "services/control_plane/migrations/000003_data_model.down.sql",
    "services/control_plane/migrations/000003_data_model.up.sql",
    "services/control_plane/migrations/000004_evaluation_inference.down.sql",
    "services/control_plane/migrations/000004_evaluation_inference.up.sql",
)

EVALUATION_VERTICAL_ADDITIONS = (
    "services/control_plane/internal/evaluations/BUILD.bazel",
    "services/control_plane/internal/evaluations/common_sql.go",
    "services/control_plane/internal/evaluations/contracts.go",
    "services/control_plane/internal/evaluations/events.go",
    "services/control_plane/internal/evaluations/mapping_sql.go",
    "services/control_plane/internal/evaluations/pagination.go",
    "services/control_plane/internal/evaluations/postgres_integration_test.go",
    "services/control_plane/internal/evaluations/repository_sql.go",
    "services/control_plane/internal/evaluations/server.go",
    "services/control_plane/internal/evaluations/server_test.go",
    "services/control_plane/internal/evaluations/validation.go",
)

CONTROL_PLANE_DOMAIN_ADDITIONS = (
    "services/control_plane/internal/admin/BUILD.bazel",
    "services/control_plane/internal/admin/admin_test.go",
    "services/control_plane/internal/admin/contracts.go",
    "services/control_plane/internal/admin/events.go",
    "services/control_plane/internal/admin/mapping_sql.go",
    "services/control_plane/internal/admin/pagination.go",
    "services/control_plane/internal/admin/postgres_integration_test.go",
    "services/control_plane/internal/admin/repository_sql.go",
    "services/control_plane/internal/admin/server.go",
    "services/control_plane/internal/agents/BUILD.bazel",
    "services/control_plane/internal/agents/common_sql.go",
    "services/control_plane/internal/agents/contracts.go",
    "services/control_plane/internal/agents/events.go",
    "services/control_plane/internal/agents/mapping_sql.go",
    "services/control_plane/internal/agents/pagination.go",
    "services/control_plane/internal/agents/postgres_integration_test.go",
    "services/control_plane/internal/agents/repository_sql.go",
    "services/control_plane/internal/agents/server.go",
    "services/control_plane/internal/agents/server_test.go",
    "services/control_plane/internal/agents/validation.go",
    "services/control_plane/internal/inference/BUILD.bazel",
    "services/control_plane/internal/inference/contracts.go",
    "services/control_plane/internal/inference/cursor.go",
    "services/control_plane/internal/inference/events.go",
    "services/control_plane/internal/inference/mapping_sql.go",
    "services/control_plane/internal/inference/postgres_integration_test.go",
    "services/control_plane/internal/inference/repository_sql.go",
    "services/control_plane/internal/inference/server.go",
    "services/control_plane/internal/inference/server_test.go",
    "services/control_plane/internal/inference/validation.go",
    "services/control_plane/internal/policies/BUILD.bazel",
    "services/control_plane/internal/policies/contracts.go",
    "services/control_plane/internal/policies/events.go",
    "services/control_plane/internal/policies/mapping_sql.go",
    "services/control_plane/internal/policies/pagination.go",
    "services/control_plane/internal/policies/policies_test.go",
    "services/control_plane/internal/policies/postgres_integration_test.go",
    "services/control_plane/internal/policies/repository_sql.go",
    "services/control_plane/internal/policies/server.go",
    "services/control_plane/internal/workflows/BUILD.bazel",
    "services/control_plane/internal/workflows/approval_repository.go",
    "services/control_plane/internal/workflows/contracts.go",
    "services/control_plane/internal/workflows/events.go",
    "services/control_plane/internal/workflows/mapping_sql.go",
    "services/control_plane/internal/workflows/pagination.go",
    "services/control_plane/internal/workflows/postgres_integration_test.go",
    "services/control_plane/internal/workflows/server.go",
    "services/control_plane/internal/workflows/server_test.go",
    "services/control_plane/internal/workflows/validation.go",
    "services/control_plane/migrations/000005_workflow_agent.down.sql",
    "services/control_plane/migrations/000005_workflow_agent.up.sql",
    "services/control_plane/migrations/000006_policy_admin.down.sql",
    "services/control_plane/migrations/000006_policy_admin.up.sql",
)

CONTRACT_CONFORMANCE_ADDITIONS = (
    "tests/conformance/generated_go_roundtrip_test.go",
    "tests/conformance/generated_rust_roundtrip_test.rs",
    "tests/conformance/generated_typescript_roundtrip_test.ts",
    "tests/conformance/test_generated_package_consumers.py",
)

ALL_CONTRACT_CONSUMER_ADDITIONS = (
    *INTERNAL_SDK_ADDITIONS,
    *TRAINING_VERTICAL_ADDITIONS,
    *CONTROL_PLANE_TRANSPORT_ADDITIONS,
    *WORKER_COORDINATION_ADDITIONS,
    *ARTIFACT_VERTICAL_ADDITIONS,
    *DATA_MODEL_VERTICAL_ADDITIONS,
    *EVALUATION_VERTICAL_ADDITIONS,
    *CONTROL_PLANE_DOMAIN_ADDITIONS,
    *CONTRACT_CONFORMANCE_ADDITIONS,
)

SDK_GENERATOR_ADDITIONS = ("tools/codegen/sdk_generator.py",)

OPENAPI_STAGE_ARTIFACT_ADDITIONS = (
    "protocols/openapi/raw/mindclade.openapi.yaml",
    "protocols/openapi/curated/mindclade.openapi.yaml",
    "protocols/openapi/published/mindclade.openapi.yaml",
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
        "services/control_plane/cmd/control-plane/main.go",
        "services/control_plane/cmd/control-plane/wire.go",
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
        "services/control_plane/internal/platform/queue/event_registry_generated.go",
        "services/control_plane/internal/platform/queue/transport.go",
        "services/control_plane/internal/platform/storage/artifact_catalog.go",
        "services/control_plane/internal/platform/storage/object_store.go",
        "services/control_plane/internal/platform/telemetry/audit_events.go",
        "services/control_plane/internal/policies/authorization.go",
        "services/control_plane/internal/policies/decision_audit.go",
        "services/control_plane/internal/tenants/tenant_isolation.go",
        "services/control_plane/internal/workflows/workflow_reconciler.go",
        "services/control_plane/internal/workflows/workflow_repository.go",
        "services/control_plane/migrations/000001_kernel.down.sql",
        "services/control_plane/migrations/000001_kernel.up.sql",
        "services/control_plane/migrations/migration_policy.yaml",
        "services/control_plane/tests/idempotency_test.go",
        "services/control_plane/tests/lease_fencing_test.go",
        "services/control_plane/tests/tenant_isolation_test.go",
        "services/control_plane/tests/transaction_outbox_test.go",
        "protocols/events/registry.yaml",
        "tests/integration/artifact_commit_test.py",
        "tests/integration/control_worker_test.py",
        "tests/integration/local_stack_test.py",
    }
)

WAVE_ONE_REQUIRED_ADDITIONS = (
    *WAVE_ONE_DURABILITY_ADDITIONS,
    *GENERATED_PACKAGE_AUTHORITY_ADDITIONS,
    *SDK_GENERATOR_ADDITIONS,
)

REQUIRED_ADDITIONS = (
    *WAVE_ZERO_REQUIRED_ADDITIONS,
    *WAVE_ONE_REQUIRED_ADDITIONS,
    *KERNEL_PLATFORM_SOURCE_ADDITIONS,
    *NATIVE_SOURCE_INCUBATION_ADDITIONS,
    *THIRD_PARTY_DEEP_EP_PACKAGE_PATHS,
    *DEEP_EP_PATCH_PATHS,
    *ALL_CONTRACT_RUST_PLUGIN_PATHS,
    *ALL_CONTRACT_GRPC_ADDITIONS,
    *TRAINING_EVENT_CONTRACT_ADDITIONS,
    *VERTICAL_EVENT_CONTRACT_ADDITIONS,
    *CONTRACT_RUNTIME_ADDITIONS,
    *SCHEMA_BINDING_ADDITIONS,
    *ALL_CONTRACT_CONSUMER_ADDITIONS,
    *OPENAPI_STAGE_ARTIFACT_ADDITIONS,
)

STATUSES = {"target", "active", "generated", "deferred", "retired"}
SOURCE_AUTHORITIES = {"hand-authored", "immutable-provenance", "reviewed-generated"}
PRE_ACTIVATION_SOURCE_PATHS = frozenset(
    (*NATIVE_SOURCE_INCUBATION_PATHS, *KERNEL_PLATFORM_AUTHORIZED_PATHS)
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
        and path != ".bazelignore"
        and path not in provenance_additions
        and path not in repository_additions
    )
    result: list[str] = []
    for path in source_paths:
        reconciled = ADR_REPLACEMENTS.get(path, path)
        python_prefix = "protocols/generated/python/"
        if reconciled.startswith(python_prefix) and reconciled not in {
            "protocols/generated/python/BUILD.bazel",
            "protocols/generated/python/README.generated.md",
            "protocols/generated/python/pyproject.toml",
        }:
            reconciled = python_prefix + "mindclade/" + reconciled.removeprefix(python_prefix)
        result.append(reconciled)
        if path == "MODULE.bazel":
            result.append("MODULE.bazel.lock")
        if path == ".bazelversion":
            result.append(".bazelignore")
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
    if path.startswith("internal/sdk/"):
        return "developer-experience"
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
        ("internal/sdk/go", "internal-sdk-go"),
        ("internal/sdk/python", "internal-sdk-python"),
        ("internal/sdk/rust", "internal-sdk-rust"),
        ("internal/sdk/typescript", "internal-sdk-typescript"),
        ("internal/sdk", "internal-sdk"),
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
            raw = (
                f"{parts[1]}-internal-{parts[4]}-{parts[5]}"
                if parts[1] == "proto" and parts[3] == "internal" and len(parts) >= 7
                else f"{parts[1]}-{parts[3]}-{parts[4]}"
            )
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
    if path == "buf.lock":
        return "0"
    if (
        path in WAVE_ONE_REWAVE_PATHS
        or path in WAVE_ONE_REQUIRED_ADDITIONS
        or path in CONTRACT_RUNTIME_ADDITIONS
        or path in SCHEMA_BINDING_ADDITIONS
        or path in ALL_CONTRACT_CONSUMER_ADDITIONS
    ):
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
        if (
            family in {"proto", "generated"}
            and domain in {"internal", "internalrpc"}
            and len(parts) > 4
        ):
            domain = parts[4]
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
    if domain == "api":
        return "4"
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
    if path in {
        "protocols/compatibility/baselines/openapi.lock.json",
        "protocols/compatibility/baselines/protobuf.candidate.json",
        "services/control_plane/internal/platform/queue/event_registry_generated.go",
        *OPENAPI_STAGE_ARTIFACT_ADDITIONS,
    }:
        return "reviewed-generated"
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
            "pair_weighted_average": "test_pair_weighted_average",
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


def _build_native_source_incubation_target_entry(path: str) -> dict[str, Any]:
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
    if path.startswith("kernels/pairformer/"):
        operation = PurePosixPath(path).parts[2]
        package = f"//kernels/pairformer/{operation}"
        test_names = {
            "outer_product_mean": "test_outer_product_mean",
            "pair_weighted_average": "test_pair_weighted_average",
            "transition": "test_transition",
            "triangle_attention": "test_triangle_attention",
            "triangle_multiplication": "test_triangle_multiplication",
        }
        return [f"{package}:tilelang.py"], [f"{package}:{test_names[operation]}"]
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


def _build_kernel_platform_source_target_entry(path: str) -> dict[str, Any]:
    if path not in KERNEL_PLATFORM_AUTHORIZED_PATHS:
        raise PolicyError(f"unapproved kernel-platform source path: {path}")
    build_targets, test_targets = _kernel_platform_source_targets(path)
    predeclared_operation_path = path in KERNEL_PLATFORM_PREDECLARED_OPERATION_PATHS
    activation_wave = "6" if predeclared_operation_path else "2S"
    activation_criterion = (
        "Activate only in Wave 6 with a concrete operation consumer, qualified native "
        "implementation, real target, tests, and qualification evidence."
        if predeclared_operation_path
        else KERNEL_PLATFORM_SOURCE_ACTIVATION_CRITERION
    )
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
        "activation_wave": activation_wave,
        "source_authority": "hand-authored",
        "build_targets": build_targets,
        "test_targets": test_targets,
        "public_surface": False,
        "activation_criterion": activation_criterion,
    }


def is_all_contract_baseline_path(path: str) -> bool:
    """Return whether ADR-0015 activates this predeclared v1 projection."""

    if path in ALL_CONTRACT_CONSUMER_ADDITIONS:
        return True
    if path in SCHEMA_BINDING_ADDITIONS:
        return True
    if path in ALL_CONTRACT_RUST_PLUGIN_PATHS:
        return True
    if path in ALL_CONTRACT_GRPC_ADDITIONS:
        return True
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
        if parts[3] == "internal" and len(parts) >= 7:
            return parts[4] in {
                domain for domain, _, _ in ALL_CONTRACT_GRPC_SERVICES if domain != "api"
            } and parts[-1].endswith(".proto")
        return parts[3] in ALL_CONTRACT_BASELINE_DOMAINS and parts[-1].endswith(".proto")
    if len(parts) >= 5 and parts[:2] == ("protocols", "generated"):
        package_index = 3
        if parts[2] == "python" and parts[3] == "mindclade":
            package_index = 4
        if len(parts) <= package_index:
            return False
        domain = parts[package_index]
        if domain == "internal" and len(parts) > package_index + 1:
            domain = parts[package_index + 1]
        return domain in ALL_CONTRACT_BASELINE_DOMAINS
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
    if path in KERNEL_PLATFORM_AUTHORIZED_PATHS:
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
    pending_ratified_baseline = path == "protocols/compatibility/baselines/protobuf.lock.json"
    if pending_ratified_baseline:
        status = "target"
    elif all_contract_baseline:
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
        "public_surface": path.startswith(("sdk/", "protocols/"))
        and not path.startswith("protocols/proto/mindclade/internal/")
        and not (
            path in ALL_CONTRACT_GRPC_PROJECTION_PATHS + ALL_CONTRACT_GRPC_PACKAGE_PATHS
            and "/api/v1/" not in path
        ),
    }
    if pending_ratified_baseline:
        entry["activation_criterion"] = (
            "Create and activate only through the explicit ADR-0015 ratification action after "
            "cross-language, database, gRPC, gateway, event, and SDK training-vertical evidence "
            "is passed and bound to the exact candidate descriptor."
        )
    elif all_contract_baseline:
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


def _base_reconciliation_addition_reason(path: str) -> str:
    if path in {".golangci.yml", "biome.json"}:
        return "Required tracked Wave 0 lint configuration omitted by A6."
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
    if path in KERNEL_PLATFORM_AUTHORIZED_PATHS:
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
    if path in SDK_GENERATOR_ADDITIONS:
        return (
            "ADR-0015 provider-neutral offline SDK planning and verification boundary for the "
            "curated OpenAPI contract; connected generation and publication remain unqualified."
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
    if path in ALL_CONTRACT_GRPC_SOURCE_PATHS:
        return (
            "ADR-0015 authoritative gRPC service source required to bind the clean-v1 "
            "resource and command catalog to concrete internal or curated public RPCs."
        )
    if path in ALL_CONTRACT_PYTHON_STUB_PATHS:
        return (
            "Required authoritative Python type-stub projection from the locked ADR-0015 "
            "Protobuf generator closure."
        )
    if path in ALL_CONTRACT_GRPC_PROJECTION_PATHS:
        return (
            "Required Go, Python, Rust, or TypeScript generated message/gRPC projection "
            "from an authoritative ADR-0015 service contract."
        )
    if path in ALL_CONTRACT_GRPC_PACKAGE_PATHS:
        return (
            "Required generated package authority for an isolated internal gRPC service "
            "namespace or the curated mindclade.api.v1 facade."
        )
    if path in VERTICAL_EVENT_CONTRACT_ADDITIONS:
        return (
            "Authoritative candidate-v1 domain event contract or generated projection required "
            "by an activated dataset, model, evaluation, or inference producer/consumer."
        )
    if path in CONTRACT_RUNTIME_ADDITIONS:
        return (
            "Required contract runtime input or generated dependency for public HTTP annotations, "
            "the authoritative event registry, and durable delivery enforcement."
        )
    if path in SCHEMA_BINDING_ADDITIONS:
        return (
            "Required generated typed binding and Draft 2020-12 validator projection from the "
            "authoritative JSON Schema catalog."
        )
    if path in INTERNAL_SDK_ADDITIONS:
        return (
            "ADR-0015 private Mindclade-owned SDK facade or conformance source that wraps "
            "Buf-generated native transport clients without redefining wire models."
        )
    if path in TRAINING_VERTICAL_ADDITIONS:
        return (
            "ADR-0015 training-vertical producer/consumer source required to prove generated "
            "contracts, normalized PostgreSQL state, and immutable event delivery end to end."
        )
    if path in CONTROL_PLANE_TRANSPORT_ADDITIONS:
        return (
            "ADR-0015 authenticated control-plane transport adapter or registration test "
            "required to bind generated gRPC services to the training application service."
        )
    if path in WORKER_COORDINATION_ADDITIONS:
        return (
            "ADR-0015 worker-coordination server required to bind generated lease, renewal, "
            "heartbeat, expiry, cancellation, and fencing RPCs to normalized durable state."
        )
    if path in ARTIFACT_VERTICAL_ADDITIONS:
        return (
            "ADR-0015 artifact-vertical producer/consumer source required to prove generated "
            "contracts, normalized PostgreSQL state, schema validation, and durable GCS storage "
            "end to end."
        )
    if path in DATA_MODEL_VERTICAL_ADDITIONS:
        return (
            "ADR-0015 dataset/model producer-consumer source or migration required to prove "
            "candidate contracts, normalized PostgreSQL state, and durable event delivery."
        )
    if path in EVALUATION_VERTICAL_ADDITIONS:
        return (
            "ADR-0015 evaluation producer-consumer source required to prove candidate contracts, "
            "normalized PostgreSQL state, authorization, and durable event delivery."
        )
    if path in CONTROL_PLANE_DOMAIN_ADDITIONS:
        return (
            "ADR-0015 admin, agent, inference, policy, or workflow producer-consumer source "
            "required to prove candidate contracts, normalized PostgreSQL state, fencing, "
            "authorization, and durable event delivery."
        )
    if path in CONTRACT_CONFORMANCE_ADDITIONS:
        return (
            "ADR-0015 native cross-language round-trip or consumer-coverage evidence for the "
            "authoritative generated contract estate."
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
        expected = set(reconcile_authority_paths(normalized_original))
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
        # git ls-files --cached retains index entries for working-tree
        # deletions. Actual-path validation describes the current checkout,
        # so a tracked path is present only while its file still exists.
        if not (root / pure).is_file():
            continue
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



# Pairformer Wave 6 governance activation (ADR-0016 through ADR-0021).
PAIRFORMER_WAVE6_PLATFORM_ACTIVATION_ADR = (
    "docs/adr/0016-pairformer-native-kernel-platform-wave6-source-activation.md"
)
PAIRFORMER_WAVE6_JIT06_ADRS: tuple[str, ...] = (
    "docs/adr/0017-jit-06-outer-product-mean-sm90a-sm100a.md",
    "docs/adr/0018-jit-06-pair-weighted-average-sm90a-sm100a.md",
    "docs/adr/0019-jit-06-transition-sm90a-sm100a.md",
    "docs/adr/0020-jit-06-triangle-attention-sm90a-sm100a.md",
    "docs/adr/0021-jit-06-triangle-multiplication-sm90a-sm100a.md",
)
PAIRFORMER_WAVE6_ADRS: tuple[str, ...] = (
    PAIRFORMER_WAVE6_PLATFORM_ACTIVATION_ADR,
    *PAIRFORMER_WAVE6_JIT06_ADRS,
)
_PAIRFORMER_WAVE6_OPERATIONS: tuple[str, ...] = (
    "outer_product_mean",
    "pair_weighted_average",
    "transition",
    "triangle_attention",
    "triangle_multiplication",
)
_PAIRFORMER_WAVE6_OPERATION_PREFIXES: tuple[str, ...] = tuple(
    f"kernels/pairformer/{operation}/" for operation in _PAIRFORMER_WAVE6_OPERATIONS
)
PAIRFORMER_WAVE6_OPERATION_PATHS: tuple[str, ...] = tuple(
    path
    for path in dict.fromkeys(
        (*NATIVE_SOURCE_INCUBATION_PATHS, *KERNEL_PLATFORM_AUTHORIZED_PATHS)
    )
    if path.startswith(_PAIRFORMER_WAVE6_OPERATION_PREFIXES)
)
PAIRFORMER_WAVE6_ACTIVATION_CRITERION = (
    "Activated by ADR-0016 as an operation-local source, build, and qualification "
    "input. Production selection remains denied until the exact operation and "
    "architecture satisfy JIT-06 K0-K5 evidence, immutable signing, runtime "
    "compatibility, revocation, and rollback requirements."
)
_PAIRFORMER_WAVE6_TEST_TARGETS: dict[str, str] = {
    operation: f"//kernels/pairformer/{operation}:test_{operation}"
    for operation in _PAIRFORMER_WAVE6_OPERATIONS
}


def _pairformer_wave6_operation(path: str) -> str | None:
    for operation, prefix in zip(
        _PAIRFORMER_WAVE6_OPERATIONS,
        _PAIRFORMER_WAVE6_OPERATION_PREFIXES,
        strict=True,
    ):
        if path.startswith(prefix):
            return operation
    return None


def _activate_pairformer_wave6_entry(
    entry: dict[str, object], path: str
) -> dict[str, object]:
    operation = _pairformer_wave6_operation(path)
    if operation is None or path not in PAIRFORMER_WAVE6_OPERATION_PATHS:
        return entry
    activated = dict(entry)
    activated.update(
        {
            "component": "kernels",
            "status": "active",
            "build_targets": [
                f"//kernels/pairformer/{operation}:policy_inputs"
            ],
            "test_targets": [_PAIRFORMER_WAVE6_TEST_TARGETS[operation]],
            "activation_criterion": PAIRFORMER_WAVE6_ACTIVATION_CRITERION,
        }
    )
    return activated


def build_native_source_incubation_entry(path: str) -> dict[str, object]:
    return _activate_pairformer_wave6_entry(
        _build_native_source_incubation_target_entry(path), path
    )


def build_kernel_platform_source_entry(path: str) -> dict[str, object]:
    return _activate_pairformer_wave6_entry(
        _build_kernel_platform_source_target_entry(path), path
    )


def _reconciliation_addition_reason(path: str) -> str:
    if path == PAIRFORMER_WAVE6_PLATFORM_ACTIVATION_ADR:
        return (
            "ADR-0016 records the governed source activation boundary for the five "
            "operation-local Pairformer packages while leaving generic native and "
            "future runtime subsystems fail closed."
        )
    if path in PAIRFORMER_WAVE6_JIT06_ADRS:
        return (
            "JIT-06 records the exact operation-by-architecture qualification "
            "decision for sm90a and sm100a without granting promotion or support."
        )
    if path in PAIRFORMER_WAVE6_OPERATION_PATHS:
        return (
            "ADR-0016 activates this existing operation-local path under its exact "
            "Bazel policy-input and test closure; K0-K5 production qualification "
            "remains outstanding."
        )
    return _base_reconciliation_addition_reason(path)


NATIVE_STABLE_ABI_TENSOR_BRIDGE_HEADER = (
    "kernels/native/stable_abi/tensor_bridge.h"
)
NATIVE_SOURCE_INCUBATION_PATHS = (
    *NATIVE_SOURCE_INCUBATION_PATHS,
    NATIVE_STABLE_ABI_TENSOR_BRIDGE_HEADER,
)
NATIVE_SOURCE_INCUBATION_ADDITIONS = (
    *NATIVE_SOURCE_INCUBATION_ADDITIONS,
    NATIVE_STABLE_ABI_TENSOR_BRIDGE_HEADER,
)
REQUIRED_ADDITIONS = (
    *REQUIRED_ADDITIONS,
    NATIVE_STABLE_ABI_TENSOR_BRIDGE_HEADER,
    *PAIRFORMER_WAVE6_ADRS,
)
CANONICAL_FILE_COUNT = CANONICAL_FILE_COUNT + len(PAIRFORMER_WAVE6_ADRS) + 1
CANONICAL_PATH_SET_SHA256 = (
    "978e5706369c7372cff6730558adea2a4af5d7b9c766fb5bbedd02196bd31b54"
)
PRE_ACTIVATION_SOURCE_PATHS = frozenset(
    path
    for path in (*PRE_ACTIVATION_SOURCE_PATHS, NATIVE_STABLE_ABI_TENSOR_BRIDGE_HEADER)
    if path not in PAIRFORMER_WAVE6_OPERATION_PATHS
)

# Native signed-qualification and callable-ABI governance (ADR-0022).
NATIVE_SIGNED_QUALIFICATION_ADR = (
    "docs/adr/0022-native-signed-qualification-and-production-admission-source-activation.md"
)
NATIVE_SIGNED_QUALIFICATION_NEW_PATHS: tuple[str, ...] = (
    "kernels/native/python/capability_index.py",
    "kernels/native/python/gpu_qualification.py",
    "kernels/native/manifests/pairformer_gpu_qualification.json",
    "kernels/native/manifests/pairformer_gpu_qualification.schema.json",
    "kernels/native/manifests/qualification_release.schema.json",
    "kernels/native/manifests/qualified_capability_index.json",
    "kernels/native/manifests/qualified_capability_index.schema.json",
    "kernels/native/tests/test_capability_index.py",
    "kernels/native/tests/test_gpu_qualification.py",
)
NATIVE_CALLABLE_ABI_NEW_PATHS: tuple[str, ...] = (
    "kernels/native/codegen/callable_abi.py",
    "kernels/native/generated/launcher_plans.generated.cpp",
    "kernels/native/generated/qualified_capabilities.generated.cpp",
    "kernels/native/generated/qualified_capabilities.generated.json",
    "kernels/native/stable_abi/node_launch_abi.h",
    "kernels/native/stable_abi/node_launch_bridge.cpp",
    "kernels/native/stable_abi/node_launch_bridge.h",
    "kernels/native/stable_abi/qualified_capability_selector.cpp",
    "kernels/native/stable_abi/qualified_capability_table.h",
    "kernels/native/tests/test_qualified_capability_selector.py",
)
NATIVE_ADR0022_GENERATED_PROJECTIONS: tuple[str, ...] = (
    "kernels/native/generated/launcher_plans.generated.cpp",
    "kernels/native/generated/qualified_capabilities.generated.cpp",
    "kernels/native/generated/qualified_capabilities.generated.json",
)
NATIVE_GENERATED_PROJECTIONS = (
    *NATIVE_GENERATED_PROJECTIONS,
    *NATIVE_ADR0022_GENERATED_PROJECTIONS,
)
NATIVE_SIGNED_QUALIFICATION_ACTIVE_PATHS: tuple[str, ...] = (
    "kernels/native/BUILD.bazel",
    "kernels/native/IMPLEMENTATION_STATUS.md",
    "kernels/native/README.md",
    "kernels/native/__init__.py",
    "kernels/native/component.yaml",
    "kernels/native/manifests/pairformer_gpu_qualification.json",
    "kernels/native/manifests/pairformer_gpu_qualification.schema.json",
    "kernels/native/manifests/qualification_release.schema.json",
    "kernels/native/manifests/qualified_capability_index.json",
    "kernels/native/manifests/qualified_capability_index.schema.json",
    "kernels/native/python/__init__.py",
    "kernels/native/python/capability_index.py",
    "kernels/native/python/gpu_qualification.py",
    "kernels/native/python/loader.py",
    "kernels/native/python/qualification.py",
    "kernels/native/tests/test_capability_index.py",
    "kernels/native/tests/test_gpu_qualification.py",
    "kernels/native/tests/test_loader_policy.py",
    "kernels/native/tests/test_qualification.py",
)
NATIVE_SIGNED_QUALIFICATION_ACTIVATION_CRITERION = (
    "Activated by ADR-0022 as signed-qualification, exact capability-inspection, "
    "and fail-closed loader source. CPU/test-only evidence grants no K4, K5, "
    "promotion, or production authority. Nonempty native execution remains "
    "denied until signed K5 and generated native-table projections reconcile."
)

_build_pairformer_wave6_native_source_entry = build_native_source_incubation_entry


def build_native_source_incubation_entry(path: str) -> dict[str, object]:
    entry = _build_pairformer_wave6_native_source_entry(path)
    if path not in NATIVE_SIGNED_QUALIFICATION_ACTIVE_PATHS:
        return entry
    activated = dict(entry)
    activated.update(
        {
            "component": "kernels-native",
            "status": "active",
            "build_targets": ["//kernels/native:native_policy_inputs"],
            "test_targets": [
                "//kernels/native:test_capability_index",
                "//kernels/native:test_gpu_qualification",
                "//kernels/native:test_loader_policy",
                "//kernels/native:test_qualification",
            ],
            "activation_criterion": NATIVE_SIGNED_QUALIFICATION_ACTIVATION_CRITERION,
        }
    )
    return activated


_pairformer_wave6_reconciliation_addition_reason = _reconciliation_addition_reason


def _reconciliation_addition_reason(path: str) -> str:
    if path == NATIVE_SIGNED_QUALIFICATION_ADR:
        return (
            "ADR-0022 activates the exact signed-qualification and loader source "
            "closure while retaining zero promoted capability rows."
        )
    if path in NATIVE_SIGNED_QUALIFICATION_NEW_PATHS:
        return (
            "ADR-0022 governs immutable K4/K5 evidence, explicit Ed25519 trust, "
            "revocation/rollback, and fail-closed qualified-index inspection."
        )
    if path in NATIVE_CALLABLE_ABI_NEW_PATHS:
        return (
            "ADR-0022 governs the callable-node ABI and compact native-table "
            "source/generated boundary without granting production execution."
        )
    return _pairformer_wave6_reconciliation_addition_reason(path)


_NATIVE_ADR0022_NEW_PATHS = (
    *NATIVE_SIGNED_QUALIFICATION_NEW_PATHS,
    *NATIVE_CALLABLE_ABI_NEW_PATHS,
)
NATIVE_SOURCE_INCUBATION_PATHS = (
    *NATIVE_SOURCE_INCUBATION_PATHS,
    *_NATIVE_ADR0022_NEW_PATHS,
)
NATIVE_SOURCE_INCUBATION_ADDITIONS = (
    *NATIVE_SOURCE_INCUBATION_ADDITIONS,
    *_NATIVE_ADR0022_NEW_PATHS,
)
REQUIRED_ADDITIONS = (
    *REQUIRED_ADDITIONS,
    *_NATIVE_ADR0022_NEW_PATHS,
    NATIVE_SIGNED_QUALIFICATION_ADR,
)
CANONICAL_FILE_COUNT = CANONICAL_FILE_COUNT + len(_NATIVE_ADR0022_NEW_PATHS) + 1
PRE_ACTIVATION_SOURCE_PATHS = frozenset(
    path
    for path in (*PRE_ACTIVATION_SOURCE_PATHS, *_NATIVE_ADR0022_NEW_PATHS)
    if path not in NATIVE_SIGNED_QUALIFICATION_ACTIVE_PATHS
)

if __name__ == "__main__":
    raise SystemExit(main())
