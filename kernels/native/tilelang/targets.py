"""Immutable CUDA capability contracts for offline TileLang compilation.

This module is import-safe without TileLang, Torch, CUDA, or a GPU. It never
performs runtime device discovery. Architecture selection is an explicit input
to the offline builder and is included in qualification receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

APPROVED_TILELANG_VERSION: Final = "0.1.13"
CAPABILITY_SCHEMA_VERSION: Final = 1
TargetInput: TypeAlias = "TargetContract | str | Mapping[str, object]"


class TargetCapabilityError(ValueError):
    """Raised when a requested target or feature is not statically legal."""


@dataclass(frozen=True, slots=True)
class TargetContract:
    """Build-time CUDA target and its conservatively approved capabilities."""

    name: str
    architecture: str | None
    minimum_cuda: str | None
    managed_tma: bool
    manual_tma: bool
    cluster_tma: bool
    gather_scatter4: bool
    wgmma_layout: bool
    tcgen05_layout: bool
    swizzled_tma_alignment: int

    @property
    def tilelang_target(self) -> dict[str, str]:
        target = {"kind": "cuda"}
        if self.architecture is not None:
            target["arch"] = self.architecture
        return target

    def as_dict(self) -> dict[str, object]:
        return {
            "architecture": self.architecture,
            "cluster_tma": self.cluster_tma,
            "gather_scatter4": self.gather_scatter4,
            "managed_tma": self.managed_tma,
            "manual_tma": self.manual_tma,
            "minimum_cuda": self.minimum_cuda,
            "name": self.name,
            "swizzled_tma_alignment": self.swizzled_tma_alignment,
            "tcgen05_layout": self.tcgen05_layout,
            "tilelang_target": self.tilelang_target,
            "wgmma_layout": self.wgmma_layout,
        }

    @property
    def capability_digest(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


PORTABLE_CUDA: Final = TargetContract(
    name="cuda-portable",
    architecture=None,
    minimum_cuda=None,
    managed_tma=False,
    manual_tma=False,
    cluster_tma=False,
    gather_scatter4=False,
    wgmma_layout=False,
    tcgen05_layout=False,
    swizzled_tma_alignment=128,
)
SM90: Final = TargetContract(
    name="sm90",
    architecture="sm_90",
    minimum_cuda="12.0",
    managed_tma=True,
    manual_tma=True,
    cluster_tma=True,
    gather_scatter4=False,
    wgmma_layout=False,
    tcgen05_layout=False,
    swizzled_tma_alignment=1024,
)
SM90A: Final = TargetContract(
    name="sm90a",
    architecture="sm_90a",
    minimum_cuda="12.0",
    managed_tma=True,
    manual_tma=True,
    cluster_tma=True,
    gather_scatter4=False,
    wgmma_layout=True,
    tcgen05_layout=False,
    swizzled_tma_alignment=1024,
)
SM100: Final = TargetContract(
    name="sm100",
    architecture="sm_100",
    minimum_cuda="12.8",
    managed_tma=True,
    manual_tma=True,
    cluster_tma=True,
    gather_scatter4=False,
    wgmma_layout=False,
    tcgen05_layout=False,
    swizzled_tma_alignment=1024,
)
SM100A: Final = TargetContract(
    name="sm100a",
    architecture="sm_100a",
    minimum_cuda="12.8",
    managed_tma=True,
    manual_tma=True,
    cluster_tma=True,
    gather_scatter4=True,
    wgmma_layout=False,
    tcgen05_layout=True,
    swizzled_tma_alignment=1024,
)

TARGET_CONTRACTS: Final[tuple[TargetContract, ...]] = (
    PORTABLE_CUDA,
    SM90,
    SM90A,
    SM100,
    SM100A,
)
_BY_NAME: Final = {contract.name: contract for contract in TARGET_CONTRACTS}
_BY_ARCH: Final = {
    contract.architecture: contract
    for contract in TARGET_CONTRACTS
    if contract.architecture is not None
}
_ALIASES: Final = {
    "cuda": "cuda-portable",
    "cuda-portable": "cuda-portable",
    "sm90": "sm90",
    "sm90a": "sm90a",
    "sm100": "sm100",
    "sm100a": "sm100a",
    "sm_90": "sm90",
    "sm_90a": "sm90a",
    "sm_100": "sm100",
    "sm_100a": "sm100a",
}


def normalize_target(target: TargetInput) -> TargetContract:
    """Normalize an explicit CUDA target without consulting runtime hardware."""

    if isinstance(target, TargetContract):
        return target
    if isinstance(target, str):
        key = target.strip().lower().replace(" ", "")
        canonical = _ALIASES.get(key)
        if canonical is None:
            raise TargetCapabilityError(f"unsupported explicit CUDA target: {target!r}")
        return _BY_NAME[canonical]
    if not isinstance(target, Mapping):
        raise TargetCapabilityError("target must be a CUDA string or mapping")
    kind = target.get("kind")
    if kind != "cuda":
        raise TargetCapabilityError("TMA/swizzle contracts require target kind 'cuda'")
    arch = target.get("arch")
    if arch is None:
        return PORTABLE_CUDA
    if not isinstance(arch, str) or arch not in _BY_ARCH:
        raise TargetCapabilityError(f"unsupported explicit CUDA architecture: {arch!r}")
    return _BY_ARCH[arch]


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if match is None:
        raise TargetCapabilityError(f"invalid toolchain version: {value!r}")
    return tuple(int(part) for part in match.groups(default="0"))


def validate_toolchain(
    target: TargetInput,
    *,
    tilelang_version: str,
    cuda_version: str | None = None,
) -> TargetContract:
    """Fail closed when compiler identity or a supplied CUDA version is invalid."""

    contract = normalize_target(target)
    if tilelang_version != APPROVED_TILELANG_VERSION:
        raise TargetCapabilityError(
            f"TileLang {APPROVED_TILELANG_VERSION} is required, got {tilelang_version!r}"
        )
    if cuda_version is not None and contract.minimum_cuda is not None:
        if _version_tuple(cuda_version) < _version_tuple(contract.minimum_cuda):
            raise TargetCapabilityError(
                f"{contract.name} requires CUDA >= {contract.minimum_cuda}, got {cuda_version}"
            )
    return contract


def capability_manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "compiler": {"id": "tilelang", "version": APPROVED_TILELANG_VERSION},
        "registration_mode": "offline_build",
        "request_time_compilation": False,
        "runtime_discovery": False,
        "targets": [contract.as_dict() | {"capability_digest": contract.capability_digest} for contract in TARGET_CONTRACTS],
        "swizzled_buffer_prohibitions": [
            "all_of",
            "any_of",
            "cross_width_view",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["semantic_digest"] = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    return payload


def render_capability_manifest(output: Path, *, check: bool = False) -> None:
    rendered = json.dumps(capability_manifest(), indent=2, sort_keys=True) + "\n"
    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise TargetCapabilityError(f"capability manifest drift: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    render_capability_manifest(args.output, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
