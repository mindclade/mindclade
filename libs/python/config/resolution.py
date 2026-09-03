from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import cast

from serialization.canonical_json import JsonValue, encode

from .redaction import SecretRef, redact


class LayerPhase(IntEnum):
    DEFAULTS = 0
    BASE = 1
    OVERLAY = 2
    SUBSTITUTION = 3
    OVERRIDE = 4


class FieldKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    MAP = "map"
    SEQUENCE = "sequence"
    SECRET_REF = "secret_ref"


class MergeMode(StrEnum):
    REPLACE = "replace"
    MAP_MERGE = "map_merge"
    APPEND = "append"


@dataclass(frozen=True)
class FieldSpec:
    kind: FieldKind
    merge: MergeMode = MergeMode.REPLACE
    required: bool = False
    sensitive: bool = False


@dataclass(frozen=True)
class ConfigLayer:
    name: str
    phase: LayerPhase
    values: Mapping[str, JsonValue | SecretRef]


@dataclass(frozen=True)
class Resolution:
    schema_version: str
    effective: Mapping[str, JsonValue | SecretRef]
    redacted: Mapping[str, JsonValue]
    provenance: Mapping[str, str]
    canonical_json: bytes
    digest: str


def _combine(
    spec: FieldSpec,
    existing: JsonValue | SecretRef | None,
    incoming: JsonValue | SecretRef,
) -> JsonValue | SecretRef:
    """Fold one layer's value into the value the lower layers resolved to.

    A field carries a merge mode precisely so that a later layer can refine an
    earlier one rather than discard it.  Replacement is the default and stays
    the behaviour for every field that does not ask for something else.
    """

    if existing is None or spec.merge is MergeMode.REPLACE:
        return incoming
    if spec.merge is MergeMode.MAP_MERGE:
        if not isinstance(existing, dict) or not isinstance(incoming, dict):
            raise TypeError("map_merge requires mapping values")
        return {**cast(dict[str, JsonValue], existing), **cast(dict[str, JsonValue], incoming)}
    if not isinstance(existing, list) or not isinstance(incoming, list):
        raise TypeError("append requires sequence values")
    return [*cast(list[JsonValue], existing), *cast(list[JsonValue], incoming)]


def resolve(
    schema_version: str, specs: Mapping[str, FieldSpec], layers: list[ConfigLayer]
) -> Resolution:
    effective: dict[str, JsonValue | SecretRef] = {}
    provenance: dict[str, str] = {}
    for layer in layers:
        for key, value in layer.values.items():
            if key not in specs:
                raise ValueError("unknown field")
            if specs[key].kind is FieldKind.SECRET_REF and not isinstance(value, SecretRef):
                raise TypeError("secret fields require SecretRef")
            effective[key] = _combine(specs[key], effective.get(key), value)
            provenance[key] = layer.name
    missing = sorted(key for key, spec in specs.items() if spec.required and key not in effective)
    if missing:
        raise ValueError(f"required fields are unset: {', '.join(missing)}")
    redacted: dict[str, JsonValue] = {
        key: cast(JsonValue, redact(value)) if isinstance(value, SecretRef) else value
        for key, value in effective.items()
    }
    canonical = encode({"schema_version": schema_version, "values": redacted})
    return Resolution(
        schema_version,
        effective,
        redacted,
        provenance,
        canonical,
        "sha256:" + hashlib.sha256(canonical).hexdigest(),
    )
