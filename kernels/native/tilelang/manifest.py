from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from kernels.native.tilelang.model import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    KernelSpec,
    NAMESPACE,
    REGISTRATION_MODE,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOP_LEVEL_KEYS = {
    "generator",
    "namespace",
    "operators",
    "optimized_math_authority",
    "registration_mode",
    "request_time_compilation",
    "runtime_discovery",
    "schema_version",
    "semantic_digest",
    "source_inventory_sha256",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def validate_manifest(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise ValueError("native manifest has missing or unsupported top-level fields")
    generator = value["generator"]
    if generator != {"id": GENERATOR_ID, "version": GENERATOR_VERSION}:
        raise ValueError("native manifest generator identity is unsupported")
    constants = {
        "schema_version": 2,
        "namespace": NAMESPACE,
        "registration_mode": REGISTRATION_MODE,
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
    }
    for field, expected in constants.items():
        if value[field] != expected:
            raise ValueError(f"native manifest {field} must be exactly {expected!r}")
    for field in ("source_inventory_sha256", "semantic_digest"):
        if not isinstance(value[field], str) or _DIGEST.fullmatch(value[field]) is None:
            raise ValueError(f"native manifest {field} must use sha256:<64 lowercase hex>")

    raw_operators = value["operators"]
    if not isinstance(raw_operators, list) or len(raw_operators) > 4096:
        raise ValueError("native manifest operators must be a bounded JSON array")
    specs = [KernelSpec.from_manifest(operator) for operator in raw_operators]
    qualified_names = [spec.qualified_name for spec in specs]
    if qualified_names != sorted(qualified_names) or len(set(qualified_names)) != len(
        qualified_names
    ):
        raise ValueError("native manifest operators must be unique and sorted by qualified_name")

    inventory = [
        {"source": spec.source, "source_sha256": spec.source_sha256}
        for spec in sorted(specs, key=lambda item: item.source)
    ]
    if value["source_inventory_sha256"] != _sha256(inventory):
        raise ValueError("native manifest source inventory digest does not match operators")
    semantic_body = {key: item for key, item in value.items() if key != "semantic_digest"}
    if value["semantic_digest"] != _sha256(semantic_body):
        raise ValueError("native manifest semantic digest does not match canonical content")
    return value


def load_manifest(native_root: Path | None = None) -> dict[str, Any]:
    """Load the committed manifest without discovery, generation, or compilation."""

    root = native_root or Path(__file__).resolve().parents[1]
    path = root / "generated" / "native_ops.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load native operator manifest {path}: {exc}") from exc
    return validate_manifest(value)
