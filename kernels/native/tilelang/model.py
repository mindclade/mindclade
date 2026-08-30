from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

NAMESPACE = "mindclade"
BACKEND = "tilelang"
GENERATOR_ID = "kernels.native.codegen.generate"
GENERATOR_VERSION = 2
REGISTRATION_MODE = "build_time_generated"

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PYTHON_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_LAUNCH_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CallableRef:
    module: str
    symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.module, str) or not self.module:
            raise ValueError("callable module must be a nonempty string")
        if not isinstance(self.symbol, str) or _PYTHON_SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError(f"invalid callable symbol: {self.symbol!r}")

    @classmethod
    def from_mapping(cls, value: object, *, field: str) -> CallableRef:
        if not isinstance(value, Mapping) or set(value) != {"module", "symbol"}:
            raise ValueError(f"{field} must contain exactly 'module' and 'symbol'")
        return cls(module=value["module"], symbol=value["symbol"])  # type: ignore[arg-type]

    def to_manifest(self) -> dict[str, str]:
        return {"module": self.module, "symbol": self.symbol}


@dataclass(frozen=True, slots=True)
class AutogradPolicy:
    mode: str
    setup_context: CallableRef | None = None
    backward: CallableRef | None = None

    def __post_init__(self) -> None:
        if self.mode == "not_supported":
            if self.setup_context is not None or self.backward is not None:
                raise ValueError("not_supported autograd policy cannot contain callables")
            return
        if self.mode != "registered":
            raise ValueError("autograd mode must be 'registered' or 'not_supported'")
        if self.setup_context is None or self.backward is None:
            raise ValueError("registered autograd policy requires setup_context and backward")

    @classmethod
    def from_mapping(cls, value: object) -> AutogradPolicy:
        if not isinstance(value, Mapping) or "mode" not in value:
            raise ValueError("autograd must be an explicit policy object")
        mode = value["mode"]
        if mode == "not_supported":
            if set(value) != {"mode"}:
                raise ValueError("not_supported autograd policy contains unsupported fields")
            return cls(mode="not_supported")
        if mode == "registered":
            if set(value) != {"mode", "setup_context", "backward"}:
                raise ValueError(
                    "registered autograd policy requires exactly mode, setup_context, and backward"
                )
            return cls(
                mode="registered",
                setup_context=CallableRef.from_mapping(
                    value["setup_context"], field="autograd.setup_context"
                ),
                backward=CallableRef.from_mapping(value["backward"], field="autograd.backward"),
            )
        raise ValueError("autograd mode must be 'registered' or 'not_supported'")

    def to_manifest(self) -> dict[str, object]:
        if self.mode == "not_supported":
            return {"mode": "not_supported"}
        assert self.setup_context is not None
        assert self.backward is not None
        return {
            "mode": "registered",
            "setup_context": self.setup_context.to_manifest(),
            "backward": self.backward.to_manifest(),
        }


@dataclass(frozen=True, slots=True)
class KernelSpec:
    """Validated build-time description of one Mindclade TileLang implementation."""

    name: str
    schema: str
    family: str
    source: str
    source_sha256: str
    fake: CallableRef
    autograd: AutogradPolicy
    namespace: str = NAMESPACE
    backend: str = BACKEND
    version: int = 1
    launch_symbol: str | None = None
    devices: tuple[str, ...] = ("cuda",)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NAME.fullmatch(self.name) is None:
            raise ValueError(f"invalid kernel name: {self.name!r}")
        if not isinstance(self.family, str) or _NAME.fullmatch(self.family) is None:
            raise ValueError(f"invalid kernel family: {self.family!r}")
        if self.namespace != NAMESPACE:
            raise ValueError(f"kernel namespace must be exactly {NAMESPACE!r}")
        if self.backend != BACKEND:
            raise ValueError(f"kernel backend must be exactly {BACKEND!r}")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or not 1 <= self.version <= 2_147_483_647
        ):
            raise ValueError("kernel version must be a positive 32-bit integer")
        if not isinstance(self.schema, str):
            raise ValueError("kernel schema must be a string")

        source_path = PurePosixPath(self.source)
        expected_source = PurePosixPath(self.family, self.name, "tilelang.py")
        if source_path != expected_source or source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError(
                f"kernel source must be exactly {expected_source.as_posix()!r}, got {self.source!r}"
            )
        if not isinstance(self.source_sha256, str) or _DIGEST.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 must use sha256:<64 lowercase hex>")
        if not isinstance(self.fake, CallableRef):
            raise ValueError("fake must be a CallableRef")
        if not isinstance(self.autograd, AutogradPolicy):
            raise ValueError("autograd must be an AutogradPolicy")

        expected_module = f"kernels.{self.family}.{self.name}.tilelang"
        references = [self.fake]
        if self.autograd.setup_context is not None:
            references.append(self.autograd.setup_context)
        if self.autograd.backward is not None:
            references.append(self.autograd.backward)
        for reference in references:
            if reference.module != expected_module:
                raise ValueError(
                    f"callable {reference.module}:{reference.symbol} must remain in {expected_module}"
                )

        symbol = self.launch_symbol or f"mindclade_tilelang_{self.name}_launch"
        if not isinstance(symbol, str) or _LAUNCH_SYMBOL.fullmatch(symbol) is None:
            raise ValueError(f"invalid launch symbol: {symbol!r}")
        object.__setattr__(self, "launch_symbol", symbol)

        if not isinstance(self.devices, tuple) or self.devices != ("cuda",):
            raise ValueError("schema v2 supports exactly the declared CUDA device backend")

        from kernels.native.codegen.schema import parse_schema

        parsed = parse_schema(self.schema)
        if parsed.name != self.name:
            raise ValueError(
                f"schema name {parsed.name!r} does not match kernel name {self.name!r}"
            )

    @property
    def qualified_name(self) -> str:
        return f"{NAMESPACE}::{self.name}"

    def to_manifest(self) -> dict[str, Any]:
        return {
            "autograd": self.autograd.to_manifest(),
            "backend": self.backend,
            "devices": list(self.devices),
            "fake": self.fake.to_manifest(),
            "family": self.family,
            "launch_symbol": self.launch_symbol,
            "name": self.name,
            "namespace": self.namespace,
            "qualified_name": self.qualified_name,
            "schema": self.schema,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "version": self.version,
        }

    @classmethod
    def from_manifest(cls, value: object) -> KernelSpec:
        expected = {
            "autograd",
            "backend",
            "devices",
            "fake",
            "family",
            "launch_symbol",
            "name",
            "namespace",
            "qualified_name",
            "schema",
            "source",
            "source_sha256",
            "version",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("operator manifest object has missing or unsupported fields")
        devices = value["devices"]
        if not isinstance(devices, list) or not all(isinstance(device, str) for device in devices):
            raise ValueError("operator devices must be a JSON string array")
        spec = cls(
            name=value["name"],  # type: ignore[arg-type]
            schema=value["schema"],  # type: ignore[arg-type]
            family=value["family"],  # type: ignore[arg-type]
            source=value["source"],  # type: ignore[arg-type]
            source_sha256=value["source_sha256"],  # type: ignore[arg-type]
            fake=CallableRef.from_mapping(value["fake"], field="fake"),
            autograd=AutogradPolicy.from_mapping(value["autograd"]),
            namespace=value["namespace"],  # type: ignore[arg-type]
            backend=value["backend"],  # type: ignore[arg-type]
            version=value["version"],  # type: ignore[arg-type]
            launch_symbol=value["launch_symbol"],  # type: ignore[arg-type]
            devices=tuple(devices),
        )
        if value["qualified_name"] != spec.qualified_name:
            raise ValueError(
                f"qualified_name must be exactly {spec.qualified_name!r}, "
                f"got {value['qualified_name']!r}"
            )
        return spec

    def source_path(self, root: Path) -> Path:
        return root / self.source
