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
    }
)
_OPERATOR_KEYS = frozenset(
    {
        "name",
        "qualified_name",
        "schema",
        "family",
        "source",
        "source_sha256",
        "fake",
        "namespace",
        "backend",
        "version",
        "launch_symbol",
        "autograd",
        "devices",
    }
)
_CALLABLE_KEYS = frozenset({"module", "symbol"})
_REGISTERED_AUTOGRAD_KEYS = frozenset(
    {"mode", "setup_context", "backward"}
)
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
class _ManifestOperator:
    name: str
    qualified_name: str
    schema: str
    version: int
    devices: tuple[str, ...]
    autograd_mode: str


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


def _validate_callable(
    value: object, *, operation: str, label: str
) -> None:
    if not isinstance(value, Mapping):
        raise NativeBundleVerificationError(f"{label} must be an object")
    _exact_keys(value, _CALLABLE_KEYS, label)
    module = value["module"]
    symbol = value["symbol"]
    if not isinstance(module, str) or _MODULE_RE.fullmatch(module) is None:
        raise NativeBundleVerificationError(f"{label}.module is invalid")
    if operation not in module.split("."):
        raise NativeBundleVerificationError(
            f"{label}.module must be operation-local"
        )
    if not isinstance(symbol, str) or _IDENTIFIER_RE.fullmatch(symbol) is None:
        raise NativeBundleVerificationError(f"{label}.symbol is invalid")


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
    schema = value["schema"]
    if not isinstance(schema, str) or not (
        schema.startswith(f"{name}(")
        or schema.startswith(f"mindclade::{name}(")
    ):
        raise NativeBundleVerificationError(
            f"{label}.schema is not the default overload"
        )
    if " -> " not in schema:
        raise NativeBundleVerificationError(f"{label}.schema has no return contract")
    family = value["family"]
    if not isinstance(family, str) or _OPERATOR_RE.fullmatch(family) is None:
        raise NativeBundleVerificationError(f"{label}.family is invalid")
    source = _require_relative_path(value["source"], f"{label}.source")
    source_parts = PurePosixPath(source).parts
    if (
        PurePosixPath(source).suffix != ".py"
        or family not in source_parts
        or name not in source_parts
    ):
        raise NativeBundleVerificationError(f"{label}.source is not operation-local")
    _require_digest(value["source_sha256"], f"{label}.source_sha256")
    _validate_callable(value["fake"], operation=name, label=f"{label}.fake")
    if value["backend"] != "tilelang":
        raise NativeBundleVerificationError(f"{label}.backend must be tilelang")
    version = value["version"]
    if type(version) is not int or version < 1:
        raise NativeBundleVerificationError(
            f"{label}.version must be a positive integer"
        )
    launch_symbol = value["launch_symbol"]
    if (
        not isinstance(launch_symbol, str)
        or _IDENTIFIER_RE.fullmatch(launch_symbol) is None
    ):
        raise NativeBundleVerificationError(f"{label}.launch_symbol is invalid")
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
    autograd = value["autograd"]
    if not isinstance(autograd, Mapping):
        raise NativeBundleVerificationError(f"{label}.autograd must be an object")
    mode = autograd.get("mode")
    if mode == "not_supported":
        _exact_keys(autograd, frozenset({"mode"}), f"{label}.autograd")
    elif mode == "registered":
        _exact_keys(
            autograd, _REGISTERED_AUTOGRAD_KEYS, f"{label}.autograd"
        )
        _validate_callable(
            autograd["setup_context"],
            operation=name,
            label=f"{label}.autograd.setup_context",
        )
        _validate_callable(
            autograd["backward"],
            operation=name,
            label=f"{label}.autograd.backward",
        )
    else:
        raise NativeBundleVerificationError(f"{label}.autograd.mode is invalid")
    return _ManifestOperator(
        name=name,
        qualified_name=qualified_name,
        schema=schema,
        version=version,
        devices=tuple(devices),
        autograd_mode=mode,
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
    if manifest["schema_version"] != 2:
        raise NativeBundleVerificationError(
            "native manifest schema_version must be 2"
        )
    if manifest["generator"] != {
        "id": "kernels.native.codegen.generate",
        "version": 2,
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
    semantic_digest = _require_digest(
        manifest["semantic_digest"], "semantic_digest"
    )
    semantic_input = dict(manifest)
    del semantic_input["semantic_digest"]
    calculated = _sha256_bytes(_canonical_json(semantic_input))
    if not hmac.compare_digest(semantic_digest, calculated):
        raise NativeBundleVerificationError(
            "native manifest semantic digest mismatch"
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


def _expected_schema(operator: _ManifestOperator) -> str:
    if operator.schema.startswith("mindclade::"):
        return operator.schema
    return f"mindclade::{operator.schema}"


def _require_new_operator_set(
    before: frozenset[str],
    after: frozenset[str],
    operators: tuple[_ManifestOperator, ...],
) -> None:
    expected = frozenset(
        operator.qualified_name for operator in operators
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
        operator.qualified_name for operator in operators
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
        actual_schema = _dispatcher_schema(operator.qualified_name)
        expected_schema = _expected_schema(operator)
        if actual_schema != expected_schema:
            raise NativeOperatorRegistrationError(
                f"schema mismatch for {operator.qualified_name}: "
                f"expected {expected_schema!r}, got {actual_schema!r}"
            )
        overloads = _public_operator_overloads(operator.name)
        if overloads != ("default",):
            raise NativeOperatorRegistrationError(
                f"{operator.qualified_name} exposes undeclared overloads: "
                f"{overloads}"
            )
        expected_dispatch = {
            _DEVICE_DISPATCH_KEYS[device] for device in operator.devices
        }
        expected_dispatch.add("Meta")
        if operator.autograd_mode == "registered":
            expected_dispatch.add("Autograd")
        for dispatch_key in _CONTROLLED_DISPATCH_KEYS:
            registered = _dispatcher_has_kernel(
                operator.qualified_name, dispatch_key
            )
            if dispatch_key in expected_dispatch and not registered:
                raise NativeOperatorRegistrationError(
                    f"{operator.qualified_name} is missing "
                    f"{dispatch_key} registration"
                )
            if dispatch_key not in expected_dispatch and registered:
                raise NativeOperatorRegistrationError(
                    f"{operator.qualified_name} has undeclared "
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
