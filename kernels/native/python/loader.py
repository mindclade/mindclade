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
    }
)
_REGISTRATION_KEYS = frozenset(
    {"qualified_name", "schema", "kind", "implementation_symbol"}
)
_REGISTRATION_KINDS = ("semantic", "forward", "backward")
_AUTOGRAD_POLICIES = frozenset({"required", "none", "composite"})
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
class _ManifestOperator:
    name: str
    qualified_name: str
    version: int
    devices: tuple[str, ...]
    autograd_policy: str
    registrations: tuple[_ManifestRegistration, ...]


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
    return _ManifestOperator(
        name=name,
        qualified_name=qualified_name,
        version=version,
        devices=tuple(devices),
        autograd_policy=autograd_policy,
        registrations=registrations,
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
        "version": 3,
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
