# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Fail-closed loading of a plan-bound Mindclade native operator bundle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import threading
from typing import Any

import torch

from .registration import register_packaged_python_kernels


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_OPERATOR_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODULE_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]*$")
_MANIFEST_PATH = "generated/native_ops.json"
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "generator",
        "source_inventory_sha256",
        "namespace",
        "registration_mode",
        "optimized_math_authority",
        "runtime_discovery",
        "request_time_compilation",
        "operators",
        "semantic_digest",
        "manifest_digest",
    }
)
_OPERATOR_KEYS = frozenset(
    {
        "name",
        "qualified_name",
        "namespace",
        "family",
        "source",
        "spec_sha256",
        "kernel_spec_digest",
        "implementation_digest",
        "implementation_candidates",
        "operator_schema",
        "facade_outputs",
        "fake",
        "forward",
        "backward",
        "autograd_policy",
        "composite",
        "effects",
        "launch",
        "backend",
        "version",
        "devices",
        "registrations",
        "launcher_plans",
    }
)
_REGISTRATION_KEYS = frozenset(
    {"qualified_name", "schema", "kind", "implementation_symbol"}
)
_REGISTRATION_KINDS = ("semantic", "forward", "backward")
_AUTOGRAD_POLICIES = frozenset({"required", "none", "composite"})
_PROGRAM_GROUP_KEYS = frozenset({"type", "nodes", "workspaces", "version"})
_PROGRAM_NODE_KEYS = frozenset(
    {"type", "name", "builder", "symbol", "depends_on", "workspace_uses", "version"}
)
_WORKSPACE_USE_KEYS = frozenset({"type", "workspace", "access", "version"})
_WORKSPACE_KEYS = frozenset(
    {"type", "name", "shape", "dtype", "zero_initialize", "lifetime", "version"}
)
_LAUNCHER_PLANS_KEYS = frozenset({"forward", "backward"})
_LAUNCHER_PLAN_KEYS = frozenset(
    {
        "phase",
        "logical_symbol",
        "bridge_requirement",
        "execution_order",
        "required_private_symbols",
        "nodes",
        "workspaces",
    }
)
_LAUNCHER_NODE_KEYS = frozenset(
    {"name", "symbol", "depends_on", "workspace_uses"}
)
_LAUNCHER_WORKSPACE_USE_KEYS = frozenset({"workspace", "access"})
_LAUNCHER_WORKSPACE_KEYS = frozenset(
    {"name", "shape", "dtype", "zero_initialize", "lifetime"}
)
_WORKSPACE_ACCESSES = frozenset({"read", "write", "read_write"})
_WORKSPACE_LIFETIMES = frozenset({"node", "program_group"})
_IMPLEMENTATION_CANDIDATE_KEYS = frozenset(
    {"name", "version", "tier", "priority", "requires", "envelope", "envelope_digest", "promoted", "selectable"}
)
_CAPABILITY_KEYS = frozenset(
    {"type", "architectures", "dtypes", "layouts", "modes", "constraints", "graph_capture_safe", "training_capable", "tensor_constraints", "version"}
)
_DIMENSION_CONSTRAINT_KEYS = frozenset({"type", "predicate", "code", "message", "version"})
_TENSOR_CAPABILITY_KEYS = frozenset({"type", "argument", "dtypes", "layouts", "devices", "ranks", "version"})
_IMPLEMENTATION_TIERS = frozenset({"portable", "optimized", "specialized", "hand_specialized"})
_BOOL_EXPRESSION_NODES = frozenset(
    {"bool_literal", "broadcastable", "is_finite", "eq", "not_equal", "less_than", "less_equal", "greater_than", "greater_equal", "and", "or", "not", "in_set"}
)
_SHAPE_EXPRESSION_NODES = frozenset(
    {"shape_of", "shape_prefix", "shape_tuple", "concat_shape"}
)
_DTYPE_EXPRESSION_NODES = frozenset(
    {"dtype_ref", "same_as_input_dtype", "constant_dtype", "select"}
)
_EXPRESSION_KEYS = frozenset(
    {
        "node", "argument", "axis", "trailing_rank", "value_type", "value",
        "lhs", "rhs", "operand", "operands", "members", "condition",
        "when_true", "when_false", "multiple", "dimensions", "parts",
    }
)
_MAX_PLAN_ITEMS = 64
_MAX_EXPRESSION_DEPTH = 32
_MAX_EXPRESSION_NODES = 1024
_MAX_EXPRESSION_BYTES = 64 * 1024
_DEVICE_DISPATCH_KEYS = {"cuda": "CUDA"}
_CONTROLLED_DISPATCH_KEYS = frozenset(
    {
        "CPU",
        "CUDA",
        "MPS",
        "XPU",
        "Meta",
        "Autograd",
        "CompositeExplicitAutograd",
        "CompositeImplicitAutograd",
    }
)


class NativeBundleError(RuntimeError):
    """Base class for native bundle policy failures."""


class NativeBundleVerificationError(NativeBundleError):
    """The descriptor, artifacts, signature, or policy failed verification."""


class NativeBundleLoadError(NativeBundleError):
    """The verified native library could not be loaded safely."""


class NativeOperatorRegistrationError(NativeBundleError):
    """Native or generated Python dispatcher registration was inconsistent."""


class NativeBundleStateError(NativeBundleError):
    """The process already contains a different or partially loaded bundle."""


class BundleActivationPolicy(str, Enum):
    """Signed activation policy carried by the release boundary."""

    PRODUCTION = "production"
    TARGET_EMPTY = "target_empty"


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise NativeBundleVerificationError(
            f"{field} must be sha256:<64 lowercase hex>"
        )
    return value


def _require_safe_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise NativeBundleVerificationError(f"{field} is not a canonical identity")
    return value


def _require_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NativeBundleVerificationError(f"{field} must be a relative path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise NativeBundleVerificationError(f"{field} is not canonical and relative")
    return value


@dataclass(frozen=True, slots=True)
class NativeBundleDescriptor:
    """Immutable release-bound identity for one complete native operator bundle."""

    bundle_root: Path | str | os.PathLike[str]
    library_path: str
    manifest_path: str
    library_sha256: str
    native_manifest_sha256: str
    repository_revision: str
    executable_plan_sha256: str
    qualification_identity: str
    trust_policy_identity: str
    revocation_policy_identity: str
    signature_evidence: bytes
    activation_policy: BundleActivationPolicy = BundleActivationPolicy.PRODUCTION

    def __post_init__(self) -> None:
        root = Path(self.bundle_root)
        if not root.is_absolute():
            raise NativeBundleVerificationError("bundle_root must be absolute")
        object.__setattr__(self, "bundle_root", root)
        _require_relative_path(self.library_path, "library_path")
        _require_relative_path(self.manifest_path, "manifest_path")
        if self.manifest_path != _MANIFEST_PATH:
            raise NativeBundleVerificationError(
                f"manifest_path must be {_MANIFEST_PATH!r}"
            )
        if self.library_path == self.manifest_path:
            raise NativeBundleVerificationError("library and manifest paths must differ")
        _require_digest(self.library_sha256, "library_sha256")
        _require_digest(self.native_manifest_sha256, "native_manifest_sha256")
        _require_digest(self.executable_plan_sha256, "executable_plan_sha256")
        if (
            not isinstance(self.repository_revision, str)
            or _REVISION_RE.fullmatch(self.repository_revision) is None
        ):
            raise NativeBundleVerificationError(
                "repository_revision must be a full lowercase Git revision"
            )
        _require_safe_identity(self.qualification_identity, "qualification_identity")
        _require_safe_identity(self.trust_policy_identity, "trust_policy_identity")
        _require_safe_identity(
            self.revocation_policy_identity, "revocation_policy_identity"
        )
        if not isinstance(self.signature_evidence, bytes) or not self.signature_evidence:
            raise NativeBundleVerificationError(
                "signature_evidence must be non-empty immutable bytes"
            )
        try:
            activation = BundleActivationPolicy(self.activation_policy)
        except (TypeError, ValueError) as exc:
            raise NativeBundleVerificationError(
                "activation_policy is not supported"
            ) from exc
        object.__setattr__(self, "activation_policy", activation)

    def signature_payload(self) -> bytes:
        """Return the canonical, path-independent payload verified by the signer."""

        value = {
            "activation_policy": self.activation_policy.value,
            "executable_plan_sha256": self.executable_plan_sha256,
            "library_path": self.library_path,
            "library_sha256": self.library_sha256,
            "manifest_path": self.manifest_path,
            "native_manifest_sha256": self.native_manifest_sha256,
            "qualification_identity": self.qualification_identity,
            "repository_revision": self.repository_revision,
            "revocation_policy_identity": self.revocation_policy_identity,
            "schema_version": "mindclade.native-bundle-descriptor.v1",
            "trust_policy_identity": self.trust_policy_identity,
        }
        return _canonical_json(value)


@dataclass(frozen=True, slots=True)
class BundleTrustDecision:
    """Typed result from the protected signature and revocation verifier."""

    trusted: bool
    revocation_checked: bool
    revoked: bool
    signer_identity: str
    trust_policy_identity: str
    revocation_policy_identity: str
    qualification_identity: str
    signature_evidence_sha256: str


SignatureVerifier = Callable[
    [NativeBundleDescriptor, bytes], BundleTrustDecision
]


@dataclass(frozen=True, slots=True)
class _ManifestRegistration:
    qualified_name: str
    schema: str
    kind: str
    implementation_symbol: str


@dataclass(frozen=True, slots=True)
class _ManifestWorkspaceUse:
    workspace: str
    access: str


@dataclass(frozen=True, slots=True)
class _ManifestWorkspace:
    name: str
    shape_json: bytes
    dtype_json: bytes
    zero_initialize: bool
    lifetime: str


@dataclass(frozen=True, slots=True)
class _ManifestProgramNode:
    name: str
    symbol: str
    depends_on: tuple[str, ...]
    workspace_uses: tuple[_ManifestWorkspaceUse, ...]


@dataclass(frozen=True, slots=True)
class _ManifestLauncherPlan:
    phase: str
    logical_symbol: str
    execution_order: tuple[str, ...]
    required_private_symbols: tuple[str, ...]
    nodes: tuple[_ManifestProgramNode, ...]
    workspaces: tuple[_ManifestWorkspace, ...]


@dataclass(frozen=True, slots=True)
class _ManifestDimensionConstraint:
    code: str
    message: str
    predicate_json: bytes


@dataclass(frozen=True, slots=True)
class _ManifestTensorCapability:
    argument: str
    dtypes: tuple[str, ...]
    layouts: tuple[str, ...]
    devices: tuple[str, ...]
    ranks: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _ManifestCapabilityEnvelope:
    architectures: tuple[str, ...]
    dtypes: tuple[str, ...]
    layouts: tuple[str, ...]
    modes: tuple[str, ...]
    constraints: tuple[_ManifestDimensionConstraint, ...]
    tensor_constraints: tuple[_ManifestTensorCapability, ...]
    graph_capture_safe: bool
    training_capable: bool
    digest: str


@dataclass(frozen=True, slots=True)
class _ManifestImplementationCandidate:
    name: str
    version: int
    tier: str
    priority: int
    requires: tuple[str, ...]
    envelope: _ManifestCapabilityEnvelope
    promoted: bool
    selectable: bool


@dataclass(frozen=True, slots=True)
class _ManifestOperator:
    name: str
    qualified_name: str
    version: int
    devices: tuple[str, ...]
    autograd_policy: str
    registrations: tuple[_ManifestRegistration, ...]
    implementation_digest: str = ""
    implementation_candidates: tuple[_ManifestImplementationCandidate, ...] = ()
    forward_launcher_plan: _ManifestLauncherPlan | None = None
    backward_launcher_plan: _ManifestLauncherPlan | None = None


@dataclass(frozen=True, slots=True)
class _VerifiedBundle:
    descriptor: NativeBundleDescriptor
    library: Path
    manifest: Path
    operators: tuple[_ManifestOperator, ...]
    trust: BundleTrustDecision


@dataclass(frozen=True, slots=True)
class _LoadedBundle:
    descriptor: NativeBundleDescriptor
    library: Path
    operators: tuple[_ManifestOperator, ...]
    trust: BundleTrustDecision


_LOCK = threading.Lock()
_LOADED_BUNDLE: _LoadedBundle | None = None
_POISONED_REASON: str | None = None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_bundle_root(root: Path) -> Path:
    try:
        root_stat = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise NativeBundleVerificationError(
            f"bundle root is unavailable: {root}"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise NativeBundleVerificationError(
            "bundle_root must be a real directory, not a symlink"
        )
    if resolved != root:
        raise NativeBundleVerificationError(
            "bundle_root must be an absolute canonical path without symlinks"
        )
    return root


def _resolve_regular_file(root: Path, relative: str, label: str) -> Path:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise NativeBundleVerificationError(
                f"{label} is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise NativeBundleVerificationError(f"{label} traverses a symlink")
        final = index == len(parts) - 1
        if final and not stat.S_ISREG(current_stat.st_mode):
            raise NativeBundleVerificationError(f"{label} is not a regular file")
        if not final and not stat.S_ISDIR(current_stat.st_mode):
            raise NativeBundleVerificationError(
                f"{label} parent is not a directory"
            )
    return current


def _read_hashed_file(
    path: Path, expected_digest: str, label: str, *, retain: bool
) -> bytes | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise NativeBundleVerificationError(f"could not open {label}") from exc
    chunks: list[bytes] | None = [] if retain else None
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise NativeBundleVerificationError(f"{label} is not a regular file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fingerprint_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    fingerprint_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if fingerprint_before != fingerprint_after:
        raise NativeBundleVerificationError(f"{label} changed while being verified")
    actual_digest = f"sha256:{digest.hexdigest()}"
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise NativeBundleVerificationError(f"{label} digest mismatch")
    return b"".join(chunks) if chunks is not None else None


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeBundleVerificationError(
                f"native manifest contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise NativeBundleVerificationError(
        f"native manifest contains non-canonical JSON constant: {value}"
    )


def _exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise NativeBundleVerificationError(
            f"{label} keys differ; missing={missing}, unexpected={unexpected}"
        )


def _validate_python_identity(value: object, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or value.count(":") != 1:
        raise NativeBundleVerificationError(
            f"{label} must be a module:function identity or null"
        )
    module, symbol = value.split(":", 1)
    if _MODULE_RE.fullmatch(module) is None or _IDENTIFIER_RE.fullmatch(symbol) is None:
        raise NativeBundleVerificationError(f"{label} is invalid")


def _validate_schema(value: object, qualified_name: str, label: str) -> str:
    if not isinstance(value, str):
        raise NativeBundleVerificationError(f"{label} must be a string")
    bare_name = qualified_name.split("::", 1)[1]
    if not (
        value.startswith(f"{bare_name}(")
        or value.startswith(f"mindclade::{bare_name}(")
    ):
        raise NativeBundleVerificationError(
            f"{label} is not the default schema for {qualified_name}"
        )
    if " -> " not in value:
        raise NativeBundleVerificationError(f"{label} has no return contract")
    return value


def _qualified_schema(schema: str) -> str:
    return schema if schema.startswith("mindclade::") else f"mindclade::{schema}"


def _contract_field(
    value: object, key: str, label: str, *, required: bool = True
) -> object:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    if required and key not in value:
        raise NativeBundleVerificationError(f"{label}.{key} is required")
    return value.get(key)


def _require_v1(value: object, label: str) -> None:
    if type(value) is not int or value != 1:
        raise NativeBundleVerificationError(f"{label}.version must be integer 1")


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise NativeBundleVerificationError(f"{label} must be an identifier")
    return value


def _identifier_tuple(
    value: object, label: str, *, nonempty: bool = False
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > _MAX_PLAN_ITEMS
        or (nonempty and not value)
    ):
        raise NativeBundleVerificationError(f"{label} must be a bounded array")
    result = tuple(
        _require_identifier(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise NativeBundleVerificationError(f"{label} must contain unique values")
    return result


def _canonical_expression(value: object, domain: str, label: str) -> bytes:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an expression object")
    node = value.get("node")
    allowed = {
        "shape": _SHAPE_EXPRESSION_NODES,
        "dtype": _DTYPE_EXPRESSION_NODES,
        "bool": _BOOL_EXPRESSION_NODES,
    }.get(domain)
    if allowed is None:
        raise NativeBundleVerificationError(f"{label} has unsupported expression domain")
    if node not in allowed:
        raise NativeBundleVerificationError(
            f"{label} must be a {domain}-domain expression"
        )
    count = 0

    def walk(item: object, depth: int) -> None:
        nonlocal count
        if depth > _MAX_EXPRESSION_DEPTH:
            raise NativeBundleVerificationError(f"{label} exceeds maximum depth")
        count += 1
        if count > _MAX_EXPRESSION_NODES:
            raise NativeBundleVerificationError(f"{label} exceeds maximum size")
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise NativeBundleVerificationError(f"{label} has a non-string key")
            unexpected = set(item) - _EXPRESSION_KEYS
            if unexpected:
                raise NativeBundleVerificationError(
                    f"{label} has unsupported fields: {sorted(unexpected)}"
                )
            nested_node = item.get("node")
            if not isinstance(nested_node, str) or not nested_node:
                raise NativeBundleVerificationError(
                    f"{label} contains a malformed expression node"
                )
            for nested in item.values():
                walk(nested, depth + 1)
        elif isinstance(item, list):
            if len(item) > _MAX_PLAN_ITEMS:
                raise NativeBundleVerificationError(
                    f"{label} contains an oversized array"
                )
            for nested in item:
                walk(nested, depth + 1)
        elif item is None or isinstance(item, (str, bool, int)):
            if isinstance(item, str) and len(item) > 4096:
                raise NativeBundleVerificationError(
                    f"{label} contains an oversized string"
                )
        elif isinstance(item, float):
            if item != item or item in {float("inf"), float("-inf")}:
                raise NativeBundleVerificationError(
                    f"{label} contains a non-finite number"
                )
        else:
            raise NativeBundleVerificationError(
                f"{label} contains an unsupported JSON value"
            )

    walk(value, 0)
    encoded = _canonical_json(value)
    if len(encoded) > _MAX_EXPRESSION_BYTES:
        raise NativeBundleVerificationError(f"{label} exceeds maximum byte size")
    return encoded


def _parse_workspace_use(
    value: object, label: str, *, derived: bool
) -> _ManifestWorkspaceUse:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(
        value,
        _LAUNCHER_WORKSPACE_USE_KEYS if derived else _WORKSPACE_USE_KEYS,
        label,
    )
    if not derived:
        if value["type"] != "WorkspaceUseSpec":
            raise NativeBundleVerificationError(f"{label}.type is invalid")
        _require_v1(value["version"], label)
    workspace = _require_identifier(value["workspace"], f"{label}.workspace")
    access = value["access"]
    if access not in _WORKSPACE_ACCESSES:
        raise NativeBundleVerificationError(f"{label}.access is invalid")
    return _ManifestWorkspaceUse(workspace, access)


def _parse_workspace(
    value: object, label: str, *, derived: bool
) -> _ManifestWorkspace:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(
        value,
        _LAUNCHER_WORKSPACE_KEYS if derived else _WORKSPACE_KEYS,
        label,
    )
    if not derived:
        if value["type"] != "WorkspaceSpec":
            raise NativeBundleVerificationError(f"{label}.type is invalid")
        _require_v1(value["version"], label)
    name = _require_identifier(value["name"], f"{label}.name")
    zero_initialize = value["zero_initialize"]
    if type(zero_initialize) is not bool:
        raise NativeBundleVerificationError(
            f"{label}.zero_initialize must be a boolean"
        )
    lifetime = value["lifetime"]
    if lifetime not in _WORKSPACE_LIFETIMES:
        raise NativeBundleVerificationError(f"{label}.lifetime is invalid")
    return _ManifestWorkspace(
        name=name,
        shape_json=_canonical_expression(value["shape"], "shape", f"{label}.shape"),
        dtype_json=_canonical_expression(value["dtype"], "dtype", f"{label}.dtype"),
        zero_initialize=zero_initialize,
        lifetime=lifetime,
    )


def _parse_program_node(
    value: object, label: str, *, derived: bool
) -> _ManifestProgramNode:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(value, _LAUNCHER_NODE_KEYS if derived else _PROGRAM_NODE_KEYS, label)
    if not derived:
        if value["type"] != "ProgramNodeSpec":
            raise NativeBundleVerificationError(f"{label}.type is invalid")
        _require_v1(value["version"], label)
        builder = value["builder"]
        if not isinstance(builder, str):
            raise NativeBundleVerificationError(f"{label}.builder is invalid")
        _validate_python_identity(builder, f"{label}.builder")
    name = _require_identifier(value["name"], f"{label}.name")
    symbol = _require_identifier(value["symbol"], f"{label}.symbol")
    depends_on = _identifier_tuple(value["depends_on"], f"{label}.depends_on")
    if depends_on != tuple(sorted(depends_on)):
        raise NativeBundleVerificationError(
            f"{label}.depends_on is not canonically ordered"
        )
    raw_uses = value["workspace_uses"]
    if not isinstance(raw_uses, list) or len(raw_uses) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(
            f"{label}.workspace_uses must be a bounded array"
        )
    uses = tuple(
        _parse_workspace_use(item, f"{label}.workspace_uses[{index}]", derived=derived)
        for index, item in enumerate(raw_uses)
    )
    use_names = tuple(item.workspace for item in uses)
    if len(use_names) != len(set(use_names)):
        raise NativeBundleVerificationError(
            f"{label}.workspace_uses contains duplicate workspaces"
        )
    if use_names != tuple(sorted(use_names)):
        raise NativeBundleVerificationError(
            f"{label}.workspace_uses is not canonically ordered"
        )
    return _ManifestProgramNode(name, symbol, depends_on, uses)


def _validated_program_components(
    nodes: tuple[_ManifestProgramNode, ...],
    workspaces: tuple[_ManifestWorkspace, ...],
    label: str,
) -> tuple[str, ...]:
    names = tuple(node.name for node in nodes)
    symbols = tuple(node.symbol for node in nodes)
    workspace_names = tuple(workspace.name for workspace in workspaces)
    if len(names) != len(set(names)):
        raise NativeBundleVerificationError(f"{label} has duplicate node names")
    if len(symbols) != len(set(symbols)):
        raise NativeBundleVerificationError(f"{label} has duplicate node symbols")
    if len(workspace_names) != len(set(workspace_names)):
        raise NativeBundleVerificationError(f"{label} has duplicate workspace names")
    if workspace_names != tuple(sorted(workspace_names)):
        raise NativeBundleVerificationError(
            f"{label} workspaces are not canonically ordered"
        )
    known = set(names)
    dependencies = {node.name: set(node.depends_on) for node in nodes}
    for node in nodes:
        unknown = set(node.depends_on) - known
        if unknown:
            raise NativeBundleVerificationError(
                f"{label} node {node.name!r} has unknown dependencies: {sorted(unknown)}"
            )
        if node.name in node.depends_on:
            raise NativeBundleVerificationError(
                f"{label} node {node.name!r} depends on itself"
            )
    pending = {name: set(items) for name, items in dependencies.items()}
    order: list[str] = []
    while pending:
        ready = sorted(name for name, items in pending.items() if not items)
        if not ready:
            raise NativeBundleVerificationError(f"{label} contains a dependency cycle")
        order.extend(ready)
        for name in ready:
            del pending[name]
        for items in pending.values():
            items.difference_update(ready)
    execution_order = tuple(order)
    if names != execution_order:
        raise NativeBundleVerificationError(
            f"{label} nodes are not in canonical execution order"
        )

    declared = {workspace.name: workspace for workspace in workspaces}
    users: dict[str, list[tuple[str, str]]] = {name: [] for name in declared}
    for node in nodes:
        for use in node.workspace_uses:
            if use.workspace not in declared:
                raise NativeBundleVerificationError(
                    f"{label} node {node.name!r} uses undeclared workspace {use.workspace!r}"
                )
            users[use.workspace].append((node.name, use.access))
    unused = sorted(name for name, items in users.items() if not items)
    if unused:
        raise NativeBundleVerificationError(
            f"{label} has unused workspaces: {unused}"
        )

    def transitively_depends(node: str, dependency: str) -> bool:
        remaining = list(dependencies[node])
        visited: set[str] = set()
        while remaining:
            current = remaining.pop()
            if current == dependency:
                return True
            if current not in visited:
                visited.add(current)
                remaining.extend(dependencies[current])
        return False

    for name, workspace in declared.items():
        accesses = users[name]
        if workspace.lifetime == "node" and len(accesses) != 1:
            raise NativeBundleVerificationError(
                f"{label} node-lifetime workspace {name!r} must have one using node"
            )
        writers = [
            node
            for node, access in accesses
            if access in {"write", "read_write"}
        ]
        if len(writers) > 1:
            raise NativeBundleVerificationError(
                f"{label} workspace {name!r} has multiple writers"
            )
        if not writers and not workspace.zero_initialize:
            raise NativeBundleVerificationError(
                f"{label} non-zero-initialized workspace {name!r} requires a writer"
            )
        if writers:
            writer = writers[0]
            for reader, access in accesses:
                if reader == writer or access == "write":
                    continue
                if not transitively_depends(reader, writer):
                    raise NativeBundleVerificationError(
                        f"{label} reader {reader!r} must depend on writer {writer!r}"
                    )
    return execution_order


def _parse_program_group(
    value: object, label: str
) -> tuple[
    tuple[_ManifestProgramNode, ...],
    tuple[_ManifestWorkspace, ...],
    tuple[str, ...],
] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object or null")
    _exact_keys(value, _PROGRAM_GROUP_KEYS, label)
    if value["type"] != "ProgramGroupSpec":
        raise NativeBundleVerificationError(f"{label}.type is invalid")
    _require_v1(value["version"], label)
    raw_nodes = value["nodes"]
    raw_workspaces = value["workspaces"]
    if (
        not isinstance(raw_nodes, list)
        or not raw_nodes
        or len(raw_nodes) > _MAX_PLAN_ITEMS
    ):
        raise NativeBundleVerificationError(f"{label}.nodes must be a bounded non-empty array")
    if not isinstance(raw_workspaces, list) or len(raw_workspaces) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label}.workspaces must be a bounded array")
    nodes = tuple(
        _parse_program_node(item, f"{label}.nodes[{index}]", derived=False)
        for index, item in enumerate(raw_nodes)
    )
    workspaces = tuple(
        _parse_workspace(item, f"{label}.workspaces[{index}]", derived=False)
        for index, item in enumerate(raw_workspaces)
    )
    order = _validated_program_components(nodes, workspaces, label)
    return nodes, workspaces, order


def _parse_launcher_plan(
    value: object,
    *,
    phase: str,
    logical_symbol: str,
    raw_group: tuple[
        tuple[_ManifestProgramNode, ...],
        tuple[_ManifestWorkspace, ...],
        tuple[str, ...],
    ] | None,
    label: str,
) -> _ManifestLauncherPlan | None:
    if value is None:
        if raw_group is not None:
            raise NativeBundleVerificationError(
                f"{label} is required for its declared program group"
            )
        return None
    if raw_group is None:
        raise NativeBundleVerificationError(
            f"{label} cannot exist without a declared program group"
        )
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object or null")
    _exact_keys(value, _LAUNCHER_PLAN_KEYS, label)
    if value["phase"] != phase:
        raise NativeBundleVerificationError(f"{label}.phase must be {phase}")
    if value["logical_symbol"] != logical_symbol:
        raise NativeBundleVerificationError(
            f"{label}.logical_symbol does not match its provider"
        )
    if value["bridge_requirement"] != "mindclade_program_group_bridge_v1":
        raise NativeBundleVerificationError(
            f"{label}.bridge_requirement is unsupported"
        )
    execution_order = _identifier_tuple(
        value["execution_order"], f"{label}.execution_order", nonempty=True
    )
    required_symbols = _identifier_tuple(
        value["required_private_symbols"],
        f"{label}.required_private_symbols",
        nonempty=True,
    )
    raw_nodes = value["nodes"]
    raw_workspaces = value["workspaces"]
    if (
        not isinstance(raw_nodes, list)
        or not raw_nodes
        or len(raw_nodes) > _MAX_PLAN_ITEMS
    ):
        raise NativeBundleVerificationError(f"{label}.nodes must be a bounded non-empty array")
    if not isinstance(raw_workspaces, list) or len(raw_workspaces) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label}.workspaces must be a bounded array")
    nodes = tuple(
        _parse_program_node(item, f"{label}.nodes[{index}]", derived=True)
        for index, item in enumerate(raw_nodes)
    )
    workspaces = tuple(
        _parse_workspace(item, f"{label}.workspaces[{index}]", derived=True)
        for index, item in enumerate(raw_workspaces)
    )
    calculated_order = _validated_program_components(nodes, workspaces, label)
    if execution_order != calculated_order:
        raise NativeBundleVerificationError(
            f"{label}.execution_order is not the canonical node order"
        )
    node_symbols = tuple(node.symbol for node in nodes)
    if required_symbols != node_symbols:
        raise NativeBundleVerificationError(
            f"{label}.required_private_symbols does not match node symbols"
        )
    raw_nodes_expected, raw_workspaces_expected, raw_order_expected = raw_group
    if (
        nodes != raw_nodes_expected
        or workspaces != raw_workspaces_expected
        or execution_order != raw_order_expected
    ):
        raise NativeBundleVerificationError(
            f"{label} does not exactly match its raw program group"
        )
    return _ManifestLauncherPlan(
        phase=phase,
        logical_symbol=logical_symbol,
        execution_order=execution_order,
        required_private_symbols=required_symbols,
        nodes=nodes,
        workspaces=workspaces,
    )


def _parse_registration(
    value: object,
    *,
    operation: str,
    index: int,
) -> _ManifestRegistration:
    label = f"operators[{operation}].registrations[{index}]"
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(value, _REGISTRATION_KEYS, label)
    kind = value["kind"]
    if kind not in _REGISTRATION_KINDS:
        raise NativeBundleVerificationError(f"{label}.kind is invalid")
    suffix = {
        "semantic": operation,
        "forward": f"_{operation}_fwd",
        "backward": f"_{operation}_bwd",
    }[kind]
    qualified_name = value["qualified_name"]
    if qualified_name != f"mindclade::{suffix}":
        raise NativeBundleVerificationError(
            f"{label}.qualified_name does not match its kind"
        )
    schema = _validate_schema(value["schema"], qualified_name, f"{label}.schema")
    implementation_symbol = value["implementation_symbol"]
    if (
        not isinstance(implementation_symbol, str)
        or _IDENTIFIER_RE.fullmatch(implementation_symbol) is None
    ):
        raise NativeBundleVerificationError(
            f"{label}.implementation_symbol is invalid"
        )
    return _ManifestRegistration(
        qualified_name=qualified_name,
        schema=schema,
        kind=kind,
        implementation_symbol=implementation_symbol,
    )


def _canonical_string_tuple(value: object, label: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value) or len(value) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label} must be a bounded array")
    result = tuple(_require_safe_identity(item, f"{label} item") for item in value)
    if len(result) != len(set(result)):
        raise NativeBundleVerificationError(f"{label} must contain unique values")
    return result


def _parse_capability(value: object, label: str, expected_digest: object) -> _ManifestCapabilityEnvelope:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(value, _CAPABILITY_KEYS, label)
    if value["type"] != "CapabilityEnvelope":
        raise NativeBundleVerificationError(f"{label}.type is unsupported")
    constraints_value = value["constraints"]
    if not isinstance(constraints_value, list) or len(constraints_value) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label}.constraints must be bounded")
    constraints: list[_ManifestDimensionConstraint] = []
    for index, raw in enumerate(constraints_value):
        item_label = f"{label}.constraints[{index}]"
        if not isinstance(raw, Mapping):
            raise NativeBundleVerificationError(f"{item_label} must be an object")
        _exact_keys(raw, _DIMENSION_CONSTRAINT_KEYS, item_label)
        if raw["type"] != "DimensionConstraint" or raw["version"] != 1:
            raise NativeBundleVerificationError(f"{item_label} contract is unsupported")
        code = _require_identifier(raw["code"], f"{item_label}.code")
        if code != code.upper():
            raise NativeBundleVerificationError(f"{item_label}.code must be uppercase")
        message = raw["message"]
        if not isinstance(message, str) or not message or len(message) > 512:
            raise NativeBundleVerificationError(f"{item_label}.message is invalid")
        constraints.append(_ManifestDimensionConstraint(code, message, _canonical_expression(raw["predicate"], "bool", f"{item_label}.predicate")))
    if len(constraints) != len({item.code for item in constraints}):
        raise NativeBundleVerificationError(f"{label}.constraints must be unique")
    tensors_value = value["tensor_constraints"]
    if not isinstance(tensors_value, list) or len(tensors_value) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label}.tensor_constraints must be bounded")
    tensors: list[_ManifestTensorCapability] = []
    for index, raw in enumerate(tensors_value):
        item_label = f"{label}.tensor_constraints[{index}]"
        if not isinstance(raw, Mapping):
            raise NativeBundleVerificationError(f"{item_label} must be an object")
        _exact_keys(raw, _TENSOR_CAPABILITY_KEYS, item_label)
        if raw["type"] != "TensorCapabilityConstraint" or raw["version"] != 1:
            raise NativeBundleVerificationError(f"{item_label} contract is unsupported")
        ranks = raw["ranks"]
        if not isinstance(ranks, list) or any(type(rank) is not int or rank < 0 for rank in ranks) or ranks != sorted(set(ranks)):
            raise NativeBundleVerificationError(f"{item_label}.ranks must be unique and sorted")
        tensors.append(_ManifestTensorCapability(
            _require_identifier(raw["argument"], f"{item_label}.argument"),
            _canonical_string_tuple(raw["dtypes"], f"{item_label}.dtypes"),
            _canonical_string_tuple(raw["layouts"], f"{item_label}.layouts"),
            _canonical_string_tuple(raw["devices"], f"{item_label}.devices"),
            tuple(ranks),
        ))
    if len(tensors) != len({item.argument for item in tensors}):
        raise NativeBundleVerificationError(f"{label}.tensor_constraints must be unique")
    if type(value["graph_capture_safe"]) is not bool or type(value["training_capable"]) is not bool or value["version"] != 1:
        raise NativeBundleVerificationError(f"{label} flags or version are invalid")
    digest = _require_digest(expected_digest, f"{label}.digest")
    if not hmac.compare_digest(digest, _sha256_bytes(_canonical_json(value))):
        raise NativeBundleVerificationError(f"{label} digest mismatch")
    return _ManifestCapabilityEnvelope(
        _canonical_string_tuple(value["architectures"], f"{label}.architectures", nonempty=True),
        _canonical_string_tuple(value["dtypes"], f"{label}.dtypes", nonempty=True),
        _canonical_string_tuple(value["layouts"], f"{label}.layouts", nonempty=True),
        _canonical_string_tuple(value["modes"], f"{label}.modes", nonempty=True),
        tuple(constraints), tuple(tensors), value["graph_capture_safe"], value["training_capable"], digest,
    )


def _parse_implementation_candidates(value: object, label: str) -> tuple[_ManifestImplementationCandidate, ...]:
    if not isinstance(value, list) or len(value) > _MAX_PLAN_ITEMS:
        raise NativeBundleVerificationError(f"{label} must be a bounded array")
    candidates: list[_ManifestImplementationCandidate] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(raw, Mapping):
            raise NativeBundleVerificationError(f"{item_label} must be an object")
        _exact_keys(raw, _IMPLEMENTATION_CANDIDATE_KEYS, item_label)
        version = raw["version"]
        priority = raw["priority"]
        if type(version) is not int or version < 1 or type(priority) is not int:
            raise NativeBundleVerificationError(f"{item_label} version or priority is invalid")
        if raw["tier"] not in _IMPLEMENTATION_TIERS:
            raise NativeBundleVerificationError(f"{item_label}.tier is invalid")
        if raw["promoted"] is not False or raw["selectable"] is not False:
            raise NativeBundleVerificationError(f"{item_label} cannot be promoted or selectable")
        candidates.append(_ManifestImplementationCandidate(
            _require_identifier(raw["name"], f"{item_label}.name"), version, raw["tier"], priority,
            _canonical_string_tuple(raw["requires"], f"{item_label}.requires"),
            _parse_capability(raw["envelope"], f"{item_label}.envelope", raw["envelope_digest"]),
            False, False,
        ))
    identities = tuple((item.name, item.version) for item in candidates)
    if identities != tuple(sorted(set(identities))):
        raise NativeBundleVerificationError(f"{label} identities must be unique and sorted")
    return tuple(candidates)


def _parse_operator(value: object, index: int) -> _ManifestOperator:
    label = f"operators[{index}]"
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(value, _OPERATOR_KEYS, label)
    name = value["name"]
    if not isinstance(name, str) or _OPERATOR_RE.fullmatch(name) is None:
        raise NativeBundleVerificationError(f"{label}.name is invalid")
    if value["namespace"] != "mindclade":
        raise NativeBundleVerificationError(f"{label}.namespace must be mindclade")
    qualified_name = value["qualified_name"]
    if qualified_name != f"mindclade::{name}":
        raise NativeBundleVerificationError(
            f"{label}.qualified_name does not match its namespace and name"
        )
    operator_schema = _validate_schema(
        value["operator_schema"], qualified_name, f"{label}.operator_schema"
    )
    family = value["family"]
    if not isinstance(family, str) or _OPERATOR_RE.fullmatch(family) is None:
        raise NativeBundleVerificationError(f"{label}.family is invalid")
    source = _require_relative_path(value["source"], f"{label}.source")
    source_parts = PurePosixPath(source).parts
    if (
        len(source_parts) < 3
        or source_parts[-3:] != (family, name, "spec.py")
    ):
        raise NativeBundleVerificationError(f"{label}.source is not operation-local")
    _require_digest(value["spec_sha256"], f"{label}.spec_sha256")
    _require_digest(value["kernel_spec_digest"], f"{label}.kernel_spec_digest")
    implementation_digest = _require_digest(
        value["implementation_digest"], f"{label}.implementation_digest"
    )
    implementation_candidates = _parse_implementation_candidates(
        value["implementation_candidates"], f"{label}.implementation_candidates"
    )
    facade_outputs = value["facade_outputs"]
    if (
        not isinstance(facade_outputs, list)
        or any(
            not isinstance(output, str)
            or _IDENTIFIER_RE.fullmatch(output) is None
            for output in facade_outputs
        )
        or len(facade_outputs) != len(set(facade_outputs))
    ):
        raise NativeBundleVerificationError(
            f"{label}.facade_outputs must be unique identifiers"
        )
    _validate_python_identity(value["fake"], f"{label}.fake")
    if value["backend"] != "tilelang":
        raise NativeBundleVerificationError(f"{label}.backend must be tilelang")
    version = value["version"]
    if type(version) is not int or version < 1:
        raise NativeBundleVerificationError(
            f"{label}.version must be a positive integer"
        )
    devices = value["devices"]
    if not isinstance(devices, list) or not devices:
        raise NativeBundleVerificationError(
            f"{label}.devices is not a positive allowlist"
        )
    if any(not isinstance(device, str) for device in devices):
        raise NativeBundleVerificationError(
            f"{label}.devices is not a positive allowlist"
        )
    if (
        devices != sorted(set(devices))
        or any(device not in _DEVICE_DISPATCH_KEYS for device in devices)
    ):
        raise NativeBundleVerificationError(
            f"{label}.devices is not a positive allowlist"
        )
    autograd_policy = value["autograd_policy"]
    if autograd_policy not in _AUTOGRAD_POLICIES:
        raise NativeBundleVerificationError(
            f"{label}.autograd_policy is invalid"
        )
    forward = value["forward"]
    forward_schema = _validate_schema(
        _contract_field(forward, "schema", f"{label}.forward"),
        f"mindclade::_{name}_fwd",
        f"{label}.forward.schema",
    )
    forward_symbol = _contract_field(forward, "symbol", f"{label}.forward")
    if not isinstance(forward_symbol, str) or _IDENTIFIER_RE.fullmatch(forward_symbol) is None:
        raise NativeBundleVerificationError(f"{label}.forward.symbol is invalid")
    forward_group = _parse_program_group(
        _contract_field(forward, "program_group", f"{label}.forward"),
        f"{label}.forward.program_group",
    )
    backward = value["backward"]
    composite = value["composite"]
    if autograd_policy == "required":
        if not isinstance(backward, Mapping) or composite is not None:
            raise NativeBundleVerificationError(
                f"{label} REQUIRED autograd needs native backward and no composite"
            )
    elif autograd_policy == "composite":
        if backward is not None or not isinstance(composite, Mapping):
            raise NativeBundleVerificationError(
                f"{label} COMPOSITE autograd needs a composite and no native backward"
            )
    elif backward is not None or composite is not None:
        raise NativeBundleVerificationError(
            f"{label} NONE autograd cannot declare backward or composite"
        )
    backward_schema: str | None = None
    backward_symbol: str | None = None
    backward_group = None
    if isinstance(backward, Mapping):
        backward_schema = _validate_schema(
            _contract_field(backward, "schema", f"{label}.backward"),
            f"mindclade::_{name}_bwd",
            f"{label}.backward.schema",
        )
        raw_backward_symbol = _contract_field(
            backward, "symbol", f"{label}.backward"
        )
        if (
            not isinstance(raw_backward_symbol, str)
            or _IDENTIFIER_RE.fullmatch(raw_backward_symbol) is None
        ):
            raise NativeBundleVerificationError(
                f"{label}.backward.symbol is invalid"
        )
        backward_symbol = raw_backward_symbol
        backward_group = _parse_program_group(
            _contract_field(backward, "program_group", f"{label}.backward"),
            f"{label}.backward.program_group",
        )
    if not isinstance(value["effects"], Mapping):
        raise NativeBundleVerificationError(f"{label}.effects must be an object")
    if not isinstance(value["launch"], Mapping):
        raise NativeBundleVerificationError(f"{label}.launch must be an object")
    registrations_value = value["registrations"]
    if not isinstance(registrations_value, list):
        raise NativeBundleVerificationError(
            f"{label}.registrations must be an array"
        )
    registrations = tuple(
        _parse_registration(item, operation=name, index=registration_index)
        for registration_index, item in enumerate(registrations_value)
    )
    expected_kinds = (
        ("semantic", "forward", "backward")
        if autograd_policy == "required"
        else ("semantic", "forward")
    )
    if tuple(registration.kind for registration in registrations) != expected_kinds:
        raise NativeBundleVerificationError(
            f"{label}.registrations must be canonically ordered as {expected_kinds}"
        )
    by_kind = {registration.kind: registration for registration in registrations}
    if len(by_kind) != len(registrations):
        raise NativeBundleVerificationError(
            f"{label}.registrations contains duplicate kinds"
        )
    if _qualified_schema(by_kind["semantic"].schema) != _qualified_schema(operator_schema):
        raise NativeBundleVerificationError(
            f"{label} semantic registration schema differs from operator_schema"
        )
    if _qualified_schema(by_kind["forward"].schema) != _qualified_schema(forward_schema):
        raise NativeBundleVerificationError(
            f"{label} forward registration schema differs from ForwardSpec"
        )
    if by_kind["forward"].implementation_symbol != forward_symbol:
        raise NativeBundleVerificationError(
            f"{label} forward registration symbol differs from ForwardSpec"
        )
    if backward_schema is not None:
        if _qualified_schema(by_kind["backward"].schema) != _qualified_schema(backward_schema):
            raise NativeBundleVerificationError(
                f"{label} backward registration schema differs from BackwardSpec"
            )
        if by_kind["backward"].implementation_symbol != backward_symbol:
            raise NativeBundleVerificationError(
                f"{label} backward registration symbol differs from BackwardSpec"
            )
    launcher_plans = value["launcher_plans"]
    if not isinstance(launcher_plans, Mapping):
        raise NativeBundleVerificationError(f"{label}.launcher_plans must be an object")
    _exact_keys(launcher_plans, _LAUNCHER_PLANS_KEYS, f"{label}.launcher_plans")
    forward_launcher_plan = _parse_launcher_plan(
        launcher_plans["forward"],
        phase="forward",
        logical_symbol=forward_symbol,
        raw_group=forward_group,
        label=f"{label}.launcher_plans.forward",
    )
    backward_launcher_plan = _parse_launcher_plan(
        launcher_plans["backward"],
        phase="backward",
        logical_symbol=backward_symbol or "",
        raw_group=backward_group,
        label=f"{label}.launcher_plans.backward",
    )
    return _ManifestOperator(
        name=name,
        qualified_name=qualified_name,
        version=version,
        devices=tuple(devices),
        autograd_policy=autograd_policy,
        registrations=registrations,
        implementation_digest=implementation_digest,
        implementation_candidates=implementation_candidates,
        forward_launcher_plan=forward_launcher_plan,
        backward_launcher_plan=backward_launcher_plan,
    )


def _parse_manifest(
    contents: bytes, activation_policy: BundleActivationPolicy
) -> tuple[_ManifestOperator, ...]:
    try:
        manifest = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeBundleVerificationError(
            "native manifest is not canonical UTF-8 JSON"
        ) from exc
    if not isinstance(manifest, Mapping):
        raise NativeBundleVerificationError("native manifest must be an object")
    _exact_keys(manifest, _MANIFEST_KEYS, "native manifest")
    if manifest["schema_version"] != 3:
        raise NativeBundleVerificationError(
            "native manifest schema_version must be 3"
        )
    if manifest["generator"] != {
        "id": "kernels.native.codegen.generate",
        "version": 7,
    }:
        raise NativeBundleVerificationError(
            "native manifest generator is unsupported"
        )
    _require_digest(
        manifest["source_inventory_sha256"], "source_inventory_sha256"
    )
    if manifest["namespace"] != "mindclade":
        raise NativeBundleVerificationError(
            "native manifest namespace must be mindclade"
        )
    if manifest["registration_mode"] != "build_time_generated":
        raise NativeBundleVerificationError(
            "native manifest registration_mode must be build_time_generated"
        )
    if manifest["optimized_math_authority"] != "tilelang":
        raise NativeBundleVerificationError(
            "native manifest optimized_math_authority must be tilelang"
        )
    if manifest["runtime_discovery"] is not False:
        raise NativeBundleVerificationError("runtime discovery is prohibited")
    if manifest["request_time_compilation"] is not False:
        raise NativeBundleVerificationError(
            "request-time compilation is prohibited"
        )
    raw_operators = manifest["operators"]
    if not isinstance(raw_operators, list):
        raise NativeBundleVerificationError(
            "native manifest operators must be an array"
        )
    operators = tuple(
        _parse_operator(value, index)
        for index, value in enumerate(raw_operators)
    )
    names = [operator.qualified_name for operator in operators]
    if names != sorted(names) or len(names) != len(set(names)):
        raise NativeBundleVerificationError(
            "native manifest operators must be unique and canonically ordered"
        )
    sources = [value["source"] for value in raw_operators]
    if len(sources) != len(set(sources)):
        raise NativeBundleVerificationError(
            "native manifest operator sources must be unique"
        )
    all_registrations = [
        registration.qualified_name
        for operator in operators
        for registration in operator.registrations
    ]
    if len(all_registrations) != len(set(all_registrations)):
        raise NativeBundleVerificationError(
            "native manifest registrations must be globally unique"
        )
    semantic_input = [
        {
            "qualified_name": value["qualified_name"],
            "kernel_spec_digest": value["kernel_spec_digest"],
        }
        for value in raw_operators
    ]
    semantic_digest = _require_digest(
        manifest["semantic_digest"], "semantic_digest"
    )
    if not hmac.compare_digest(
        semantic_digest, _sha256_bytes(_canonical_json(semantic_input))
    ):
        raise NativeBundleVerificationError(
            "native manifest semantic digest mismatch"
        )
    source_inventory = sorted(
        (
            {
                "source": value["source"],
                "spec_sha256": value["spec_sha256"],
                "kernel_spec_digest": value["kernel_spec_digest"],
                "implementation_digest": value["implementation_digest"],
            }
            for value in raw_operators
        ),
        key=lambda item: item["source"],
    )
    source_inventory_digest = _require_digest(
        manifest["source_inventory_sha256"], "source_inventory_sha256"
    )
    if not hmac.compare_digest(
        source_inventory_digest,
        _sha256_bytes(_canonical_json(source_inventory)),
    ):
        raise NativeBundleVerificationError(
            "native manifest source inventory digest mismatch"
        )
    manifest_digest = _require_digest(
        manifest["manifest_digest"], "manifest_digest"
    )
    manifest_input = dict(manifest)
    del manifest_input["manifest_digest"]
    if not hmac.compare_digest(
        manifest_digest, _sha256_bytes(_canonical_json(manifest_input))
    ):
        raise NativeBundleVerificationError(
            "native manifest digest mismatch"
        )
    if activation_policy is BundleActivationPolicy.TARGET_EMPTY and operators:
        raise NativeBundleVerificationError(
            "TARGET activation policy permits only an empty operator manifest"
        )
    if activation_policy is BundleActivationPolicy.PRODUCTION and not operators:
        raise NativeBundleVerificationError(
            "production activation policy requires at least one qualified operator"
        )
    return operators


def _verify_trust(
    descriptor: NativeBundleDescriptor, verifier: SignatureVerifier
) -> BundleTrustDecision:
    if not callable(verifier):
        raise NativeBundleVerificationError(
            "signature_verifier must be callable"
        )
    payload = descriptor.signature_payload()
    try:
        decision = verifier(descriptor, payload)
    except Exception as exc:
        raise NativeBundleVerificationError(
            "bundle signature verifier failed"
        ) from exc
    if not isinstance(decision, BundleTrustDecision):
        raise NativeBundleVerificationError(
            "signature verifier must return BundleTrustDecision"
        )
    if decision.trusted is not True:
        raise NativeBundleVerificationError("bundle signature is not trusted")
    if decision.revocation_checked is not True:
        raise NativeBundleVerificationError(
            "bundle revocation was not checked"
        )
    if decision.revoked is not False:
        raise NativeBundleVerificationError(
            "bundle signature or signer is revoked"
        )
    _require_safe_identity(decision.signer_identity, "signer_identity")
    if decision.trust_policy_identity != descriptor.trust_policy_identity:
        raise NativeBundleVerificationError("trust policy identity mismatch")
    if (
        decision.revocation_policy_identity
        != descriptor.revocation_policy_identity
    ):
        raise NativeBundleVerificationError(
            "revocation policy identity mismatch"
        )
    if decision.qualification_identity != descriptor.qualification_identity:
        raise NativeBundleVerificationError(
            "qualification identity mismatch"
        )
    evidence_digest = _sha256_bytes(descriptor.signature_evidence)
    if not hmac.compare_digest(
        decision.signature_evidence_sha256, evidence_digest
    ):
        raise NativeBundleVerificationError(
            "signature evidence digest mismatch"
        )
    return decision


def _verify_bundle(
    descriptor: NativeBundleDescriptor, verifier: SignatureVerifier
) -> _VerifiedBundle:
    root = _canonical_bundle_root(Path(descriptor.bundle_root))
    library = _resolve_regular_file(
        root, descriptor.library_path, "native library"
    )
    manifest = _resolve_regular_file(
        root, descriptor.manifest_path, "native manifest"
    )
    _read_hashed_file(
        library,
        descriptor.library_sha256,
        "native library",
        retain=False,
    )
    manifest_contents = _read_hashed_file(
        manifest,
        descriptor.native_manifest_sha256,
        "native manifest",
        retain=True,
    )
    assert manifest_contents is not None
    operators = _parse_manifest(
        manifest_contents, descriptor.activation_policy
    )
    trust = _verify_trust(descriptor, verifier)
    return _VerifiedBundle(
        descriptor, library, manifest, operators, trust
    )


def _dispatcher_snapshot() -> frozenset[str]:
    getter = getattr(torch._C, "_dispatch_get_all_op_names", None)
    if not callable(getter):
        raise NativeOperatorRegistrationError(
            "PyTorch dispatcher enumeration is unavailable"
        )
    try:
        return frozenset(str(name) for name in getter())
    except Exception as exc:
        raise NativeOperatorRegistrationError(
            "could not enumerate PyTorch dispatcher operators"
        ) from exc


def _dispatcher_schema(qualified_name: str) -> str:
    try:
        handle = torch._C._dispatch_find_schema_or_throw(
            qualified_name, ""
        )
        return str(handle.schema())
    except Exception as exc:
        raise NativeOperatorRegistrationError(
            f"dispatcher schema missing for {qualified_name}"
        ) from exc


def _dispatcher_has_kernel(
    qualified_name: str, dispatch_key: str
) -> bool:
    try:
        return bool(
            torch._C._dispatch_has_kernel_for_dispatch_key(
                qualified_name, dispatch_key
            )
        )
    except Exception as exc:
        raise NativeOperatorRegistrationError(
            f"could not inspect {dispatch_key} registration "
            f"for {qualified_name}"
        ) from exc


def _public_operator_overloads(name: str) -> tuple[str, ...]:
    try:
        packet = getattr(torch.ops.mindclade, name)
        return tuple(packet.overloads())
    except Exception as exc:
        raise NativeOperatorRegistrationError(
            f"torch.ops.mindclade.{name} is unavailable"
        ) from exc


def _require_new_operator_set(
    before: frozenset[str],
    after: frozenset[str],
    operators: tuple[_ManifestOperator, ...],
) -> None:
    expected = frozenset(
        registration.qualified_name
        for operator in operators
        for registration in operator.registrations
    )
    existing_mindclade = frozenset(
        name for name in before if name.startswith("mindclade::")
    )
    if existing_mindclade:
        raise NativeBundleStateError(
            "Mindclade dispatcher namespace was populated before verified "
            f"loading: {sorted(existing_mindclade)}"
        )
    introduced = after - before
    if introduced != expected:
        missing = sorted(expected - introduced)
        unexpected = sorted(introduced - expected)
        raise NativeOperatorRegistrationError(
            "native library dispatcher registrations differ from the "
            f"signed manifest; missing={missing}, unexpected={unexpected}"
        )


def _reconcile_dispatcher(
    operators: tuple[_ManifestOperator, ...],
    snapshot: frozenset[str],
) -> None:
    expected_names = frozenset(
        registration.qualified_name
        for operator in operators
        for registration in operator.registrations
    )
    actual_names = frozenset(
        name for name in snapshot if name.startswith("mindclade::")
    )
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        raise NativeOperatorRegistrationError(
            "Mindclade dispatcher namespace differs from the signed "
            f"manifest; missing={missing}, unexpected={unexpected}"
        )
    for operator in operators:
        overloads = _public_operator_overloads(operator.name)
        if overloads != ("default",):
            raise NativeOperatorRegistrationError(
                f"{operator.qualified_name} exposes undeclared overloads: "
                f"{overloads}"
            )
        for registration in operator.registrations:
            actual_schema = _dispatcher_schema(registration.qualified_name)
            expected_schema = _qualified_schema(registration.schema)
            if actual_schema != expected_schema:
                raise NativeOperatorRegistrationError(
                    f"schema mismatch for {registration.qualified_name}: "
                    f"expected {expected_schema!r}, got {actual_schema!r}"
                )
            expected_dispatch = {
                _DEVICE_DISPATCH_KEYS[device] for device in operator.devices
            }
            expected_dispatch.add("Meta")
            if (
                registration.kind == "semantic"
                and operator.autograd_policy in {"required", "composite"}
            ):
                expected_dispatch.add("Autograd")
            for dispatch_key in _CONTROLLED_DISPATCH_KEYS:
                registered = _dispatcher_has_kernel(
                    registration.qualified_name, dispatch_key
                )
                if dispatch_key in expected_dispatch and not registered:
                    raise NativeOperatorRegistrationError(
                        f"{registration.qualified_name} is missing "
                        f"{dispatch_key} registration"
                    )
                if dispatch_key not in expected_dispatch and registered:
                    raise NativeOperatorRegistrationError(
                        f"{registration.qualified_name} has undeclared "
                        f"{dispatch_key} registration"
                    )
        for module_name in ("kernels.native", "kernels.native.python"):
            module = sys.modules.get(module_name)
            if module is not None and operator.name in vars(module):
                raise NativeOperatorRegistrationError(
                    f"Python alias API is prohibited: "
                    f"{module_name}.{operator.name}"
                )


def _load_torch_library(path: Path) -> None:
    torch.ops.load_library(str(path))


def load_native_library(
    descriptor: NativeBundleDescriptor,
    *,
    signature_verifier: SignatureVerifier,
) -> Path:
    """Verify and load one complete, plan-bound operator bundle once.

    The loader never discovers, compiles, dispatches, tunes, regenerates, or
    falls back. Any failure after the dlopen boundary poisons the process-local
    loader because PyTorch has no safe native-library unload path.
    """

    global _LOADED_BUNDLE, _POISONED_REASON
    if not isinstance(descriptor, NativeBundleDescriptor):
        raise TypeError("descriptor must be NativeBundleDescriptor")
    with _LOCK:
        if _POISONED_REASON is not None:
            raise NativeBundleStateError(
                "native loader is poisoned by a partial load: "
                f"{_POISONED_REASON}"
            )
        if _LOADED_BUNDLE is not None:
            if _LOADED_BUNDLE.descriptor != descriptor:
                raise NativeBundleStateError(
                    "a different native bundle is already loaded "
                    "in this process"
                )
            return _LOADED_BUNDLE.library
        verified = _verify_bundle(descriptor, signature_verifier)
        before = _dispatcher_snapshot()
        if any(name.startswith("mindclade::") for name in before):
            _POISONED_REASON = (
                "pre-existing unverified Mindclade dispatcher state"
            )
            raise NativeBundleStateError(_POISONED_REASON)
        load_started = False
        try:
            load_started = True
            try:
                _load_torch_library(verified.library)
            except Exception as exc:
                raise NativeBundleLoadError(
                    "verified native library failed to load"
                ) from exc
            after_native = _dispatcher_snapshot()
            _require_new_operator_set(
                before, after_native, verified.operators
            )
            try:
                register_packaged_python_kernels()
            except Exception as exc:
                raise NativeOperatorRegistrationError(
                    "packaged Python registration failed"
                ) from exc
            after_python = _dispatcher_snapshot()
            _require_new_operator_set(
                before, after_python, verified.operators
            )
            _reconcile_dispatcher(verified.operators, after_python)
        except NativeBundleError as exc:
            if load_started:
                _POISONED_REASON = str(exc)
            raise
        except Exception as exc:
            if load_started:
                _POISONED_REASON = f"{type(exc).__name__}: {exc}"
            raise NativeBundleLoadError(
                "verified native bundle failed during registration"
            ) from exc
        _LOADED_BUNDLE = _LoadedBundle(
            descriptor=verified.descriptor,
            library=verified.library,
            operators=verified.operators,
            trust=verified.trust,
        )
        return verified.library
