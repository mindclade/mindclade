# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Verified, qualified-only native capability selection.

This module is part of the production runtime plane. It parses one compact,
detached-Ed25519-signed index and performs deterministic exact-envelope
selection. It intentionally contains no compiler, tuner, benchmark runner,
candidate planner, private-key handling, or filesystem discovery.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_ID_RE = re.compile(r"^[a-z][a-z0-9._:/-]{2,255}$")
_OPERATION_RE = re.compile(r"^mindclade::[a-z][a-z0-9_]{0,63}$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9._:/+-]{0,255}$")
_ARCHITECTURE_RE = re.compile(r"^sm[0-9]{2,3}a$")
_WORKLOAD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PAYLOAD_TYPE = "application/vnd.mindclade.qualified-capability-index.v1+json"
_NATIVE_TABLE_KEYS = frozenset(
    {
        "schema_version",
        "generator",
        "selection",
        "row_fields",
        "sort_order",
        "rows",
        "row_count",
        "rows_digest",
        "table_digest",
    }
)
_NATIVE_TABLE_GENERATOR_KEYS = frozenset({"id", "version"})
_NATIVE_TABLE_ROW_FIELDS = (
    "operation",
    "phase",
    "workload_digest",
    "specialization_digest",
    "capability_digest",
    "artifact_digest",
    "architecture",
    "dtype",
    "layout",
    "mode",
    "dimensions",
    "attributes",
    "specificity",
    "priority",
    "adapter_symbols",
)
_NATIVE_TABLE_SORT_ORDER = (
    "operation",
    "phase",
    "-specificity",
    "-priority",
    "capability_digest",
)
_MAX_CAPABILITIES = 4096
_MAX_CONTROL_RECORDS = 4096
_TIER_RANK = {
    "portable": 0,
    "optimized": 1,
    "specialized": 2,
    "hand_specialized": 3,
}
_INDEX_KEYS = frozenset(
    {
        "schema_version",
        "evidence_class",
        "capabilities",
        "revocations",
        "rollbacks",
        "index_digest",
    }
)
_CAPABILITY_KEYS = frozenset(
    {
        "operation",
        "operation_version",
        "implementation",
        "implementation_version",
        "tier",
        "priority",
        "architecture",
        "dtype",
        "layout",
        "mode",
        "workload_digest",
        "specialization_digest",
        "dimensions",
        "attributes",
        "schedule_digest",
        "numerical_envelope_digest",
        "runtime_compatibility_digest",
        "compile_environment_digest",
        "bundle_digest",
        "native_manifest_digest",
        "library_digest",
        "executable_plan_digest",
        "forward_artifact_digest",
        "backward_artifact_digest",
        "release_receipt_digest",
        "release_signature_digest",
        "k4_receipt_digest",
        "qualification_identity",
        "repository_revision",
        "native_manifest_schema_version",
        "native_manifest_generator_version",
        "build_receipt_schema_version",
        "autograd_policy",
        "status",
        "capability_digest",
    }
)
_REVOCATION_KEYS = frozenset(
    {"capability_digest", "revocation_receipt_digest"}
)
_ROLLBACK_KEYS = frozenset(
    {
        "revoked_capability_digest",
        "replacement_capability_digest",
        "rollback_receipt_digest",
    }
)
_SIGNATURE_KEYS = frozenset(
    {"algorithm", "key_id", "subject_digest", "signature"}
)
_DOCUMENT_KEYS = frozenset({"payload_type", "index", "signature"})
_DIMENSION_KEYS = frozenset({"name", "value"})
_ATTRIBUTE_KEYS = frozenset({"name", "type", "value"})


class CapabilityIndexError(RuntimeError):
    """The capability index or selection request failed closed."""


def canonical_json(value: object) -> bytes:
    """Return the one canonical JSON representation used for identity."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CapabilityIndexError("value is not canonical JSON data") from exc


def subject_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise CapabilityIndexError(
            f"{label} has missing or unknown fields; missing={missing}, unknown={unknown}"
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CapabilityIndexError(f"{label} must be an object with string keys")
    return value


def _array(value: object, label: str, maximum: int) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise CapabilityIndexError(f"{label} must be a bounded array")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise CapabilityIndexError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise CapabilityIndexError(f"{label} is not a bounded identifier")
    return value


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise CapabilityIndexError(f"{label} must be a positive integer")
    return value


def _workload_dimensions(
    value: object, label: str
) -> tuple[tuple[str, int], ...]:
    items = _array(value, label, 64)
    if not items:
        raise CapabilityIndexError(f"{label} must not be empty")
    result: list[tuple[str, int]] = []
    for index, raw_value in enumerate(items):
        item_label = f"{label}[{index}]"
        item = _mapping(raw_value, item_label)
        _exact_keys(item, _DIMENSION_KEYS, item_label)
        name = item["name"]
        if not isinstance(name, str) or _WORKLOAD_NAME_RE.fullmatch(name) is None:
            raise CapabilityIndexError(f"{item_label}.name is not lower_snake_case")
        dimension = item["value"]
        if type(dimension) is not int or not 0 <= dimension <= (1 << 63) - 1:
            raise CapabilityIndexError(f"{item_label}.value must be non-negative int64")
        result.append((name, dimension))
    if result != sorted(result) or len({name for name, _ in result}) != len(result):
        raise CapabilityIndexError(f"{label} must have unique names in canonical order")
    return tuple(result)


def _workload_attributes(
    value: object, label: str
) -> tuple[tuple[str, str, bool | int | float | str], ...]:
    items = _array(value, label, 64)
    result: list[tuple[str, str, bool | int | float | str]] = []
    expected_types = {
        "bool": bool,
        "int64": int,
        "float64": float,
        "string": str,
    }
    for index, raw_value in enumerate(items):
        item_label = f"{label}[{index}]"
        item = _mapping(raw_value, item_label)
        _exact_keys(item, _ATTRIBUTE_KEYS, item_label)
        name = item["name"]
        if not isinstance(name, str) or _WORKLOAD_NAME_RE.fullmatch(name) is None:
            raise CapabilityIndexError(f"{item_label}.name is not lower_snake_case")
        scalar_type = item["type"]
        scalar = item["value"]
        expected = expected_types.get(scalar_type) if isinstance(scalar_type, str) else None
        if expected is None or type(scalar) is not expected:
            raise CapabilityIndexError(f"{item_label}.value does not match its scalar type")
        if scalar_type == "int64" and not -(1 << 63) <= scalar <= (1 << 63) - 1:
            raise CapabilityIndexError(f"{item_label}.value is outside int64")
        if scalar_type == "float64" and not math.isfinite(scalar):
            raise CapabilityIndexError(f"{item_label}.value must be finite")
        if scalar_type == "string" and len(scalar.encode("utf-8")) > 1024:
            raise CapabilityIndexError(f"{item_label}.value is too large")
        result.append((name, scalar_type, scalar))
    if result != sorted(result, key=lambda item: item[0]) or len(
        {name for name, _, _ in result}
    ) != len(result):
        raise CapabilityIndexError(f"{label} must have unique names in canonical order")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class QualifiedCapability:
    operation: str
    operation_version: int
    implementation: str
    implementation_version: int
    tier: str
    priority: int
    architecture: str
    dtype: str
    layout: str
    mode: str
    workload_digest: str
    specialization_digest: str
    dimensions: tuple[tuple[str, int], ...]
    attributes: tuple[tuple[str, str, bool | int | float | str], ...]
    schedule_digest: str
    numerical_envelope_digest: str
    runtime_compatibility_digest: str
    compile_environment_digest: str
    bundle_digest: str
    native_manifest_digest: str
    library_digest: str
    executable_plan_digest: str
    forward_artifact_digest: str
    backward_artifact_digest: str | None
    release_receipt_digest: str
    release_signature_digest: str
    k4_receipt_digest: str
    qualification_identity: str
    repository_revision: str
    native_manifest_schema_version: int
    native_manifest_generator_version: int
    build_receipt_schema_version: int
    autograd_policy: str
    capability_digest: str


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    revoked_capability_digest: str
    replacement_capability_digest: str
    rollback_receipt_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedCapabilityIndex:
    capabilities: tuple[QualifiedCapability, ...]
    revoked_capability_digests: frozenset[str]
    rollbacks: tuple[RollbackRecord, ...]
    evidence_class: str
    signer_key_id: str
    subject_digest: str
    production_eligible: bool


@dataclass(frozen=True, slots=True)
class NativeCapabilityTableIdentity:
    """Validated identity of the immutable native selector table."""

    row_count: int
    rows_digest: str
    table_digest: str


@dataclass(frozen=True, slots=True)
class NativeCapabilityRow:
    operation: str
    phase: str
    workload_digest: str
    specialization_digest: str
    capability_digest: str
    artifact_digest: str
    architecture: str
    dtype: str
    layout: str
    mode: str
    dimensions: tuple[tuple[str, int], ...]
    attributes: tuple[tuple[str, str, bool | int | float | str], ...]
    specificity: int
    priority: int
    adapter_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeCapabilityTable:
    rows: tuple[NativeCapabilityRow, ...]
    identity: NativeCapabilityTableIdentity


def _native_row_sort_key(
    row: NativeCapabilityRow,
) -> tuple[str, int, int, int, str]:
    return (
        row.operation,
        1 if row.phase == "forward" else 2,
        -row.specificity,
        -row.priority,
        row.capability_digest,
    )


def _native_row_data(row: NativeCapabilityRow) -> dict[str, object]:
    return {
        "operation": row.operation,
        "phase": row.phase,
        "workload_digest": row.workload_digest,
        "specialization_digest": row.specialization_digest,
        "capability_digest": row.capability_digest,
        "artifact_digest": row.artifact_digest,
        "architecture": row.architecture,
        "dtype": row.dtype,
        "layout": row.layout,
        "mode": row.mode,
        "dimensions": [
            {"name": name, "value": value} for name, value in row.dimensions
        ],
        "attributes": [
            {"name": name, "type": scalar_type, "value": value}
            for name, scalar_type, value in row.attributes
        ],
        "specificity": row.specificity,
        "priority": row.priority,
        "adapter_symbols": list(row.adapter_symbols),
    }


def _native_table_identity_for_rows(
    rows: tuple[NativeCapabilityRow, ...],
) -> NativeCapabilityTableIdentity:
    row_data = [_native_row_data(row) for row in rows]
    body: dict[str, object] = {
        "schema_version": 1,
        "generator": {
            "id": "kernels.native.codegen.generate",
            "version": 8,
        },
        "selection": "exact_qualified_only",
        "row_fields": list(_NATIVE_TABLE_ROW_FIELDS),
        "sort_order": list(_NATIVE_TABLE_SORT_ORDER),
        "rows": row_data,
        "row_count": len(row_data),
        "rows_digest": subject_digest(row_data),
    }
    return NativeCapabilityTableIdentity(
        row_count=len(row_data),
        rows_digest=str(body["rows_digest"]),
        table_digest=subject_digest(body),
    )


def _parse_native_capability_row(
    raw_value: object, index: int
) -> NativeCapabilityRow:
    label = f"native capability table rows[{index}]"
    raw = _mapping(raw_value, label)
    _exact_keys(raw, frozenset(_NATIVE_TABLE_ROW_FIELDS), label)
    operation = raw["operation"]
    if not isinstance(operation, str) or _OPERATION_RE.fullmatch(operation) is None:
        raise CapabilityIndexError(f"{label}.operation is invalid")
    phase = raw["phase"]
    if phase not in {"forward", "backward"}:
        raise CapabilityIndexError(f"{label}.phase is unsupported")
    architecture = raw["architecture"]
    if not isinstance(architecture, str) or _ARCHITECTURE_RE.fullmatch(architecture) is None:
        raise CapabilityIndexError(f"{label}.architecture is not exact")
    dtype = raw["dtype"]
    if dtype not in {"float16", "bfloat16", "float32", "bool", "int64"}:
        raise CapabilityIndexError(f"{label}.dtype is unsupported")
    dimensions = _workload_dimensions(raw["dimensions"], f"{label}.dimensions")
    attributes = _workload_attributes(raw["attributes"], f"{label}.attributes")
    if {name for name, _ in dimensions}.intersection(
        name for name, _, _ in attributes
    ):
        raise CapabilityIndexError(f"{label} dimension and attribute names overlap")
    specificity = raw["specificity"]
    if type(specificity) is not int or not 0 <= specificity <= (1 << 32) - 1:
        raise CapabilityIndexError(f"{label}.specificity must be uint32")
    if specificity != len(dimensions) + len(attributes):
        raise CapabilityIndexError(f"{label}.specificity is not canonical")
    priority = raw["priority"]
    if type(priority) is not int or not -(1 << 31) <= priority <= (1 << 31) - 1:
        raise CapabilityIndexError(f"{label}.priority must be int32")
    raw_symbols = _array(raw["adapter_symbols"], f"{label}.adapter_symbols", 128)
    if not raw_symbols:
        raise CapabilityIndexError(f"{label}.adapter_symbols must not be empty")
    adapter_symbols = tuple(
        _identifier(value, f"{label}.adapter_symbols[{symbol_index}]")
        for symbol_index, value in enumerate(raw_symbols)
    )
    if len(set(adapter_symbols)) != len(adapter_symbols):
        raise CapabilityIndexError(f"{label}.adapter_symbols are not unique")
    return NativeCapabilityRow(
        operation=operation,
        phase=str(phase),
        workload_digest=_digest(raw["workload_digest"], f"{label}.workload_digest"),
        specialization_digest=_digest(
            raw["specialization_digest"], f"{label}.specialization_digest"
        ),
        capability_digest=_digest(raw["capability_digest"], f"{label}.capability_digest"),
        artifact_digest=_digest(raw["artifact_digest"], f"{label}.artifact_digest"),
        architecture=architecture,
        dtype=str(dtype),
        layout=_identifier(raw["layout"], f"{label}.layout"),
        mode=_identifier(raw["mode"], f"{label}.mode"),
        dimensions=dimensions,
        attributes=attributes,
        specificity=specificity,
        priority=priority,
        adapter_symbols=adapter_symbols,
    )


def load_native_capability_table(document_bytes: bytes) -> NativeCapabilityTable:
    """Validate a compact native table without granting execution authority."""

    if not isinstance(document_bytes, bytes) or len(document_bytes) > 8 * 1024 * 1024:
        raise CapabilityIndexError("native capability table must be bounded bytes")
    try:
        raw_value = json.loads(document_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityIndexError("native capability table is not valid JSON") from exc
    table = _mapping(raw_value, "native capability table")
    _exact_keys(table, _NATIVE_TABLE_KEYS, "native capability table")
    if table["schema_version"] != 1 or table["selection"] != "exact_qualified_only":
        raise CapabilityIndexError("native capability table contract is unsupported")
    generator = _mapping(table["generator"], "native capability table generator")
    _exact_keys(generator, _NATIVE_TABLE_GENERATOR_KEYS, "native capability table generator")
    if generator != {"id": "kernels.native.codegen.generate", "version": 8}:
        raise CapabilityIndexError("native capability table generator is unsupported")
    if tuple(_array(table["row_fields"], "native capability table row_fields", 32)) != _NATIVE_TABLE_ROW_FIELDS:
        raise CapabilityIndexError("native capability table row fields drifted")
    if tuple(_array(table["sort_order"], "native capability table sort_order", 16)) != _NATIVE_TABLE_SORT_ORDER:
        raise CapabilityIndexError("native capability table sort order drifted")
    raw_rows = _array(table["rows"], "native capability table rows", _MAX_CAPABILITIES)
    row_count = table["row_count"]
    if type(row_count) is not int or row_count != len(raw_rows):
        raise CapabilityIndexError("native capability table row count mismatch")
    rows_digest = _digest(table["rows_digest"], "native capability table rows_digest")
    if not hmac.compare_digest(rows_digest, subject_digest(raw_rows)):
        raise CapabilityIndexError("native capability table rows digest mismatch")
    table_body = dict(table)
    table_digest = _digest(table_body.pop("table_digest"), "native capability table table_digest")
    if not hmac.compare_digest(table_digest, subject_digest(table_body)):
        raise CapabilityIndexError("native capability table digest mismatch")
    rows = tuple(
        _parse_native_capability_row(value, index)
        for index, value in enumerate(raw_rows)
    )
    if rows != tuple(sorted(rows, key=_native_row_sort_key)):
        raise CapabilityIndexError("native capability table rows are not canonically sorted")
    phase_identities = [(row.capability_digest, row.phase) for row in rows]
    if len(set(phase_identities)) != len(phase_identities):
        raise CapabilityIndexError("native capability table has duplicate capability phases")
    return NativeCapabilityTable(
        rows=rows,
        identity=NativeCapabilityTableIdentity(
            row_count=row_count,
            rows_digest=rows_digest,
            table_digest=table_digest,
        ),
    )


def load_native_capability_table_identity(
    document_bytes: bytes,
) -> NativeCapabilityTableIdentity:
    """Validate and return the immutable native table identity."""

    return load_native_capability_table(document_bytes).identity


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    operation: str
    architecture: str
    dtype: str
    layout: str
    mode: str
    workload_digest: str
    training: bool

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or _OPERATION_RE.fullmatch(self.operation) is None:
            raise CapabilityIndexError("operation must be mindclade::<canonical-name>")
        if not isinstance(self.architecture, str) or _ARCHITECTURE_RE.fullmatch(self.architecture) is None:
            raise CapabilityIndexError("architecture must be an exact smXXa target")
        for label, value in (("dtype", self.dtype), ("layout", self.layout), ("mode", self.mode)):
            _identifier(value, label)
        _digest(self.workload_digest, "workload_digest")
        if type(self.training) is not bool:
            raise CapabilityIndexError("training must be boolean")


@dataclass(frozen=True, slots=True)
class BundleBinding:
    repository_revision: str
    library_digest: str
    native_manifest_digest: str
    executable_plan_digest: str
    qualification_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository_revision, str) or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.repository_revision
        ) is None:
            raise CapabilityIndexError("repository_revision must be immutable")
        _digest(self.library_digest, "library_digest")
        _digest(self.native_manifest_digest, "native_manifest_digest")
        _digest(self.executable_plan_digest, "executable_plan_digest")
        _identifier(self.qualification_identity, "qualification_identity")


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    operation: str
    implementation: str
    workload_digest: str
    capability_digest: str
    artifact_digest: str
    release_receipt_digest: str
    selection_reason: str
    fallback: bool = False
    fallback_reason: str | None = None
    rollback_receipt_digest: str | None = None


def _parse_capability(
    raw_value: object, index: int, *, expected_status: str
) -> QualifiedCapability:
    label = f"capabilities[{index}]"
    raw = _mapping(raw_value, label)
    _exact_keys(raw, _CAPABILITY_KEYS, label)
    if raw["status"] != expected_status:
        raise CapabilityIndexError(f"{label} has an ineligible status")
    operation = raw["operation"]
    if not isinstance(operation, str) or _OPERATION_RE.fullmatch(operation) is None:
        raise CapabilityIndexError(f"{label}.operation is invalid")
    architecture = raw["architecture"]
    if not isinstance(architecture, str) or _ARCHITECTURE_RE.fullmatch(architecture) is None:
        raise CapabilityIndexError(f"{label}.architecture is not exact")
    tier = raw["tier"]
    if tier not in _TIER_RANK:
        raise CapabilityIndexError(f"{label}.tier is unsupported")
    priority = raw["priority"]
    if type(priority) is not int:
        raise CapabilityIndexError(f"{label}.priority must be integer")
    autograd_policy = raw["autograd_policy"]
    if autograd_policy not in {"required", "none", "composite"}:
        raise CapabilityIndexError(f"{label}.autograd_policy is unsupported")
    backward = raw["backward_artifact_digest"]
    if backward is not None:
        backward = _digest(backward, f"{label}.backward_artifact_digest")
    if autograd_policy == "required" and backward is None:
        raise CapabilityIndexError(f"{label} REQUIRED capability lacks atomic BWD")
    if autograd_policy != "required" and backward is not None:
        raise CapabilityIndexError(f"{label} non-REQUIRED capability declares native BWD")
    dimensions = _workload_dimensions(raw["dimensions"], f"{label}.dimensions")
    attributes = _workload_attributes(raw["attributes"], f"{label}.attributes")
    if {name for name, _ in dimensions}.intersection(
        name for name, _, _ in attributes
    ):
        raise CapabilityIndexError(f"{label} dimension and attribute names overlap")
    values = QualifiedCapability(
        operation=operation,
        operation_version=_positive_integer(raw["operation_version"], f"{label}.operation_version"),
        implementation=_identifier(raw["implementation"], f"{label}.implementation"),
        implementation_version=_positive_integer(raw["implementation_version"], f"{label}.implementation_version"),
        tier=str(tier),
        priority=priority,
        architecture=architecture,
        dtype=_identifier(raw["dtype"], f"{label}.dtype"),
        layout=_identifier(raw["layout"], f"{label}.layout"),
        mode=_identifier(raw["mode"], f"{label}.mode"),
        workload_digest=_digest(raw["workload_digest"], f"{label}.workload_digest"),
        specialization_digest=_digest(
            raw["specialization_digest"], f"{label}.specialization_digest"
        ),
        dimensions=dimensions,
        attributes=attributes,
        schedule_digest=_digest(raw["schedule_digest"], f"{label}.schedule_digest"),
        numerical_envelope_digest=_digest(raw["numerical_envelope_digest"], f"{label}.numerical_envelope_digest"),
        runtime_compatibility_digest=_digest(raw["runtime_compatibility_digest"], f"{label}.runtime_compatibility_digest"),
        compile_environment_digest=_digest(raw["compile_environment_digest"], f"{label}.compile_environment_digest"),
        bundle_digest=_digest(raw["bundle_digest"], f"{label}.bundle_digest"),
        native_manifest_digest=_digest(raw["native_manifest_digest"], f"{label}.native_manifest_digest"),
        library_digest=_digest(raw["library_digest"], f"{label}.library_digest"),
        executable_plan_digest=_digest(raw["executable_plan_digest"], f"{label}.executable_plan_digest"),
        forward_artifact_digest=_digest(raw["forward_artifact_digest"], f"{label}.forward_artifact_digest"),
        backward_artifact_digest=backward,
        release_receipt_digest=_digest(raw["release_receipt_digest"], f"{label}.release_receipt_digest"),
        release_signature_digest=_digest(raw["release_signature_digest"], f"{label}.release_signature_digest"),
        k4_receipt_digest=_digest(raw["k4_receipt_digest"], f"{label}.k4_receipt_digest"),
        qualification_identity=_identifier(raw["qualification_identity"], f"{label}.qualification_identity"),
        repository_revision=str(raw["repository_revision"]),
        native_manifest_schema_version=_positive_integer(
            raw["native_manifest_schema_version"],
            f"{label}.native_manifest_schema_version",
        ),
        native_manifest_generator_version=_positive_integer(
            raw["native_manifest_generator_version"],
            f"{label}.native_manifest_generator_version",
        ),
        build_receipt_schema_version=_positive_integer(
            raw["build_receipt_schema_version"],
            f"{label}.build_receipt_schema_version",
        ),
        autograd_policy=str(autograd_policy),
        capability_digest=_digest(raw["capability_digest"], f"{label}.capability_digest"),
    )
    body = dict(raw)
    del body["capability_digest"]
    del body["status"]
    if not hmac.compare_digest(values.capability_digest, subject_digest(body)):
        raise CapabilityIndexError(f"{label}.capability_digest mismatch")
    if re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64})", values.repository_revision
    ) is None:
        raise CapabilityIndexError(f"{label}.repository_revision is not immutable")
    if (
        values.native_manifest_schema_version != 4
        or values.native_manifest_generator_version != 8
        or values.build_receipt_schema_version != 4
    ):
        raise CapabilityIndexError(f"{label} binds an obsolete executable ABI receipt")
    return values


def load_signed_capability_index(
    document_bytes: bytes,
    *,
    trust_roots: Mapping[str, Ed25519PublicKey],
    expected_key_id: str,
    allow_test_evidence: bool = False,
) -> VerifiedCapabilityIndex:
    """Verify and project one signed compact capability index.

    Production trust roots are explicit caller configuration. No key or trust
    root is read from the repository, environment, home directory, or network.
    """

    if not isinstance(document_bytes, bytes) or len(document_bytes) > 8 * 1024 * 1024:
        raise CapabilityIndexError("signed capability index must be bounded bytes")
    try:
        document = json.loads(document_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityIndexError("signed capability index is not valid JSON") from exc
    document = _mapping(document, "signed capability index")
    _exact_keys(document, _DOCUMENT_KEYS, "signed capability index")
    if document["payload_type"] != _PAYLOAD_TYPE:
        raise CapabilityIndexError("capability index payload type is unsupported")
    raw_index = _mapping(document["index"], "index")
    _exact_keys(raw_index, _INDEX_KEYS, "index")
    if raw_index["schema_version"] != 1:
        raise CapabilityIndexError("capability index schema version is unsupported")
    digest_input = dict(raw_index)
    declared_index_digest = _digest(digest_input.pop("index_digest"), "index.index_digest")
    if not hmac.compare_digest(declared_index_digest, subject_digest(digest_input)):
        raise CapabilityIndexError("capability index digest mismatch")
    signature = _mapping(document["signature"], "signature")
    _exact_keys(signature, _SIGNATURE_KEYS, "signature")
    if signature["algorithm"] != "ed25519":
        raise CapabilityIndexError("capability index signature algorithm is unsupported")
    key_id = signature["key_id"]
    if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None or key_id != expected_key_id:
        raise CapabilityIndexError("capability index signer identity mismatch")
    key = trust_roots.get(key_id)
    if not isinstance(key, Ed25519PublicKey):
        raise CapabilityIndexError("capability index signer is not a trusted Ed25519 root")
    exact_subject_digest = subject_digest(raw_index)
    if not hmac.compare_digest(
        _digest(signature["subject_digest"], "signature.subject_digest"),
        exact_subject_digest,
    ):
        raise CapabilityIndexError("capability index signature subject mismatch")
    encoded = signature["signature"]
    if not isinstance(encoded, str):
        raise CapabilityIndexError("capability index signature is missing")
    try:
        raw_signature = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CapabilityIndexError("capability index signature is not canonical base64") from exc
    try:
        key.verify(raw_signature, canonical_json(raw_index))
    except InvalidSignature as exc:
        raise CapabilityIndexError("capability index signature verification failed") from exc

    evidence_class = raw_index["evidence_class"]
    if evidence_class not in {"PRODUCTION_K4_K5", "TEST_ONLY_UNQUALIFIED"}:
        raise CapabilityIndexError("capability index evidence class is unsupported")
    if evidence_class == "TEST_ONLY_UNQUALIFIED" and not allow_test_evidence:
        raise CapabilityIndexError("test-only capability evidence is prohibited")
    raw_capabilities = _array(raw_index["capabilities"], "capabilities", _MAX_CAPABILITIES)
    expected_status = (
        "K5_PASS" if evidence_class == "PRODUCTION_K4_K5" else "TEST_ONLY"
    )
    capabilities = tuple(
        _parse_capability(value, index, expected_status=expected_status)
        for index, value in enumerate(raw_capabilities)
    )
    if tuple(item.capability_digest for item in capabilities) != tuple(
        sorted(item.capability_digest for item in capabilities)
    ):
        raise CapabilityIndexError("capabilities are not in canonical digest order")
    if len({item.capability_digest for item in capabilities}) != len(capabilities):
        raise CapabilityIndexError("capability identities are not unique")

    raw_revocations = _array(raw_index["revocations"], "revocations", _MAX_CONTROL_RECORDS)
    revoked: list[str] = []
    for index, value in enumerate(raw_revocations):
        label = f"revocations[{index}]"
        item = _mapping(value, label)
        _exact_keys(item, _REVOCATION_KEYS, label)
        revoked.append(_digest(item["capability_digest"], f"{label}.capability_digest"))
        _digest(item["revocation_receipt_digest"], f"{label}.revocation_receipt_digest")
    if revoked != sorted(set(revoked)):
        raise CapabilityIndexError("revocations are not unique canonical order")

    raw_rollbacks = _array(raw_index["rollbacks"], "rollbacks", _MAX_CONTROL_RECORDS)
    rollbacks: list[RollbackRecord] = []
    for index, value in enumerate(raw_rollbacks):
        label = f"rollbacks[{index}]"
        item = _mapping(value, label)
        _exact_keys(item, _ROLLBACK_KEYS, label)
        rollbacks.append(
            RollbackRecord(
                revoked_capability_digest=_digest(item["revoked_capability_digest"], f"{label}.revoked_capability_digest"),
                replacement_capability_digest=_digest(item["replacement_capability_digest"], f"{label}.replacement_capability_digest"),
                rollback_receipt_digest=_digest(item["rollback_receipt_digest"], f"{label}.rollback_receipt_digest"),
            )
        )
    if tuple((item.revoked_capability_digest, item.replacement_capability_digest) for item in rollbacks) != tuple(
        sorted((item.revoked_capability_digest, item.replacement_capability_digest) for item in rollbacks)
    ):
        raise CapabilityIndexError("rollbacks are not in canonical order")
    capability_ids = {item.capability_digest for item in capabilities}
    for rollback in rollbacks:
        if rollback.revoked_capability_digest not in revoked:
            raise CapabilityIndexError("rollback source is not revoked")
        if rollback.replacement_capability_digest not in capability_ids:
            raise CapabilityIndexError("rollback replacement is not qualified in this index")
        if rollback.replacement_capability_digest in revoked:
            raise CapabilityIndexError("rollback replacement is revoked")

    production = evidence_class == "PRODUCTION_K4_K5"
    if production and key_id.startswith("test-only"):
        raise CapabilityIndexError("test-only signer cannot authorize production")
    return VerifiedCapabilityIndex(
        capabilities=capabilities,
        revoked_capability_digests=frozenset(revoked),
        rollbacks=tuple(rollbacks),
        evidence_class=str(evidence_class),
        signer_key_id=key_id,
        subject_digest=exact_subject_digest,
        production_eligible=production,
    )


def reconcile_signed_native_capability_table(
    index: VerifiedCapabilityIndex,
    table: NativeCapabilityTable,
    phase_adapter_symbols: Mapping[tuple[str, str], tuple[str, ...]],
) -> NativeCapabilityTableIdentity:
    """Prove the native rows are the exact projection of signed K5 evidence."""

    if not isinstance(index, VerifiedCapabilityIndex):
        raise CapabilityIndexError("index must be a verified capability index")
    if not isinstance(table, NativeCapabilityTable):
        raise CapabilityIndexError("table must be a validated native capability table")
    expected: list[NativeCapabilityRow] = []
    for capability in index.capabilities:
        if capability.capability_digest in index.revoked_capability_digests:
            continue
        phases = [("forward", capability.forward_artifact_digest)]
        if capability.autograd_policy == "required":
            if capability.backward_artifact_digest is None:
                raise CapabilityIndexError("REQUIRED capability lacks atomic BWD")
            phases.append(("backward", capability.backward_artifact_digest))
        for phase, artifact_digest in phases:
            adapters = phase_adapter_symbols.get((capability.operation, phase))
            if not isinstance(adapters, tuple) or not adapters:
                raise CapabilityIndexError(
                    f"{capability.operation} {phase} adapters are not manifest-bound"
                )
            if len(set(adapters)) != len(adapters) or any(
                not isinstance(symbol, str) or _IDENTIFIER_RE.fullmatch(symbol) is None
                for symbol in adapters
            ):
                raise CapabilityIndexError(
                    f"{capability.operation} {phase} adapters are not canonical"
                )
            expected.append(
                NativeCapabilityRow(
                    operation=capability.operation,
                    phase=phase,
                    workload_digest=capability.workload_digest,
                    specialization_digest=capability.specialization_digest,
                    capability_digest=capability.capability_digest,
                    artifact_digest=artifact_digest,
                    architecture=capability.architecture,
                    dtype=capability.dtype,
                    layout=capability.layout,
                    mode=capability.mode,
                    dimensions=capability.dimensions,
                    attributes=capability.attributes,
                    specificity=len(capability.dimensions) + len(capability.attributes),
                    priority=capability.priority,
                    adapter_symbols=adapters,
                )
            )
    exact_expected = tuple(sorted(expected, key=_native_row_sort_key))
    if table.rows != exact_expected:
        raise CapabilityIndexError(
            "native capability rows do not exactly project trusted non-revoked K5 evidence"
        )
    if table.identity != _native_table_identity_for_rows(table.rows):
        raise CapabilityIndexError(
            "native capability table identity is not derived from retained rows"
        )
    return table.identity


def reconcile_exported_native_capability_identity(
    expected: NativeCapabilityTableIdentity,
    *,
    row_count: int,
    rows_digest: str,
    table_digest: str,
) -> None:
    """Match the loaded library's immutable C table identity to its sidecar."""

    if type(row_count) is not int or row_count < 0:
        raise CapabilityIndexError("exported native capability row count is invalid")
    actual = NativeCapabilityTableIdentity(
        row_count=row_count,
        rows_digest=_digest(rows_digest, "exported native rows digest"),
        table_digest=_digest(table_digest, "exported native table digest"),
    )
    if actual != expected:
        raise CapabilityIndexError(
            "loaded native capability identity does not match preverified sidecar"
        )


def select_capability(
    index: VerifiedCapabilityIndex,
    request: CapabilityRequest,
    binding: BundleBinding,
    *,
    require_production: bool = True,
) -> DispatchReceipt:
    """Select one exact qualified capability without tuning or fallback."""

    if not isinstance(index, VerifiedCapabilityIndex):
        raise CapabilityIndexError("index must be a verified capability index")
    if not isinstance(request, CapabilityRequest) or not isinstance(binding, BundleBinding):
        raise CapabilityIndexError("request and bundle binding must be typed")
    if require_production and not index.production_eligible:
        raise CapabilityIndexError("production selection requires K4/K5 evidence")
    candidates = [
        item
        for item in index.capabilities
        if item.capability_digest not in index.revoked_capability_digests
        and item.operation == request.operation
        and item.architecture == request.architecture
        and item.dtype == request.dtype
        and item.layout == request.layout
        and item.mode == request.mode
        and item.workload_digest == request.workload_digest
        and (not request.training or item.autograd_policy == "required")
        and item.library_digest == binding.library_digest
        and item.native_manifest_digest == binding.native_manifest_digest
        and item.executable_plan_digest == binding.executable_plan_digest
        and item.qualification_identity == binding.qualification_identity
        and item.repository_revision == binding.repository_revision
    ]
    if not candidates:
        raise CapabilityIndexError("no exact non-revoked qualified capability")
    candidates.sort(
        key=lambda item: (
            -item.priority,
            -_TIER_RANK[item.tier],
            item.capability_digest,
        )
    )
    selected = candidates[0]
    rollback = next(
        (
            item
            for item in index.rollbacks
            if item.replacement_capability_digest == selected.capability_digest
        ),
        None,
    )
    reason = "exact qualified envelope; stable priority/tier/digest tie-break"
    if rollback is not None:
        reason = "signed rollback to prior exact qualified capability"
    return DispatchReceipt(
        operation=selected.operation,
        implementation=selected.implementation,
        workload_digest=selected.workload_digest,
        capability_digest=selected.capability_digest,
        artifact_digest=selected.bundle_digest,
        release_receipt_digest=selected.release_receipt_digest,
        selection_reason=reason,
        rollback_receipt_digest=(
            rollback.rollback_receipt_digest if rollback is not None else None
        ),
    )
