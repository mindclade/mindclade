"""Single declarative integration contract for a logical Mindclade operation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .backward import BackwardSpec
from .effects import EffectSpec
from .errors import KernelContractError, SchemaError
from .forward import ForwardSpec
from .gradient import GradientSpec
from .launch import DeterminismClass, LaunchContract
from .output import ContractModel, _nonempty, _unique

_SCHEMA_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<args>.*)\)\s*->\s*(?P<returns>.+?)\s*$",
    re.DOTALL,
)
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AutogradPolicy(StrEnum):
    REQUIRED = "required"
    NONE = "none"
    COMPOSITE = "composite"


@dataclass(frozen=True, slots=True)
class CompositeAutogradSpec(ContractModel):
    decomposition: str
    source_digest: str
    runtime_envelope: str
    gradients: tuple[GradientSpec, ...]
    supports_double_backward: bool
    setup_context: str | None = None
    backward: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.decomposition, "composite decomposition")
        _nonempty(self.runtime_envelope, "composite runtime envelope")
        _nonempty(self.setup_context, "composite setup_context")
        _nonempty(self.backward, "composite backward")
        for label, identity in (
            ("decomposition", self.decomposition),
            ("setup_context", self.setup_context),
            ("backward", self.backward),
        ):
            assert identity is not None
            if identity.count(":") != 1:
                raise KernelContractError(
                    f"composite {label} must be one module:function identity"
                )
            module, function = identity.split(":", 1)
            if not module or not function or not all(
                part.isidentifier() for part in module.split(".")
            ) or not function.isidentifier():
                raise KernelContractError(
                    f"composite {label} must be one module:function identity"
                )
        if self.version != 1:
            raise KernelContractError(f"unsupported CompositeAutogradSpec version: {self.version}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_digest):
            raise KernelContractError("composite source_digest must be sha256:<64 lowercase hex>")
        if not self.gradients:
            raise KernelContractError("composite autograd must declare named gradients")
        _unique(
            tuple(gradient.input_name for gradient in self.gradients),
            "composite gradient input mappings",
        )
        _unique(
            tuple(gradient.output_name for gradient in self.gradients),
            "composite gradient output mappings",
        )


@dataclass(frozen=True, slots=True)
class _Schema:
    name: str
    arguments: tuple[str, ...]
    outputs: tuple[str | None, ...]
    raw: str


@dataclass(frozen=True, slots=True)
class KernelSpec(ContractModel):
    name: str
    namespace: str
    family: str
    source: str
    operator_schema: str
    facade_outputs: tuple[str, ...]
    fake: str | None
    forward: ForwardSpec
    backward: BackwardSpec | None
    autograd_policy: AutogradPolicy
    effects: EffectSpec
    launch: LaunchContract
    backend: str = "tilelang"
    version: int = 1
    devices: tuple[str, ...] = ("cuda",)
    composite: CompositeAutogradSpec | None = None

    def __post_init__(self) -> None:
        for label in ("name", "namespace", "family", "source", "operator_schema", "backend"):
            _nonempty(getattr(self, label), f"kernel {label}")
        if self.version != 1:
            raise KernelContractError(f"unsupported KernelSpec version: {self.version}")
        if self.namespace != "mindclade":
            raise KernelContractError("kernel namespace must be mindclade")
        if self.backend != "tilelang":
            raise KernelContractError("first-party optimized kernel backend must be tilelang")
        if self.devices != ("cuda",):
            raise KernelContractError("v1 native kernels must declare exactly the cuda device")
        self._validate_source()

        semantic = _parse_schema(self.operator_schema)
        forward = _parse_schema(self.forward.schema)
        if semantic.name != self.name:
            raise SchemaError(
                f"semantic operator name {semantic.name!r} must equal KernelSpec name {self.name!r}"
            )
        if forward.name != f"_{self.name}_fwd":
            raise SchemaError(
                f"forward provider must be named _{self.name}_fwd, got {forward.name!r}"
            )
        if forward.arguments != semantic.arguments:
            raise SchemaError(
                "semantic and forward provider argument names must match exactly in declaration order"
            )
        output_names = tuple(output.name for output in self.forward.outputs)
        _validate_schema_outputs(semantic, output_names, "semantic")
        _validate_schema_outputs(forward, output_names, "forward")
        _unique(self.facade_outputs, "facade_outputs")
        unknown_facade = set(self.facade_outputs) - set(output_names)
        if unknown_facade:
            raise KernelContractError(f"unknown facade outputs: {sorted(unknown_facade)}")
        expected_facade = tuple(
            output.name for output in self.forward.outputs if output.visible_in_facade
        )
        if self.facade_outputs != expected_facade:
            raise KernelContractError(
                "facade_outputs must exactly match visible forward outputs in declaration order"
            )

        semantic_arguments = set(semantic.arguments)
        if self.backward is not None:
            self._validate_backward(semantic_arguments)
        if self.autograd_policy is AutogradPolicy.REQUIRED:
            if self.backward is None:
                raise KernelContractError("AutogradPolicy.REQUIRED requires a backward provider")
            if self.composite is not None:
                raise KernelContractError("REQUIRED native autograd cannot declare a composite decomposition")
        elif self.autograd_policy is AutogradPolicy.NONE:
            if self.backward is not None:
                raise KernelContractError("AutogradPolicy.NONE cannot declare a backward provider")
            if self.composite is not None:
                raise KernelContractError("AutogradPolicy.NONE cannot declare a composite decomposition")
        elif self.autograd_policy is AutogradPolicy.COMPOSITE:
            if self.backward is not None:
                raise KernelContractError("COMPOSITE autograd cannot declare a native backward provider")
            if self.composite is None:
                raise KernelContractError("COMPOSITE autograd requires a qualified decomposition identity")
            self._validate_composite(semantic_arguments)

        if self.effects.uses_rng and self.launch.determinism is DeterminismClass.DETERMINISTIC:
            raise KernelContractError("RNG-using kernel cannot claim unconditional determinism")
        if self.effects.uses_atomics and self.launch.determinism is DeterminismClass.DETERMINISTIC:
            raise KernelContractError("atomic kernel cannot claim unconditional determinism")
        self._validate_effects(semantic)
        if self.fake is not None and ":" not in self.fake:
            raise KernelContractError("custom fake must be a module:function identity")

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}::{self.name}"

    def _validate_source(self) -> None:
        path = PurePosixPath(self.source)
        if path.is_absolute() or ".." in path.parts or path.name != "spec.py":
            raise KernelContractError("kernel source must be a canonical relative spec.py path")
        if len(path.parts) < 3 or path.parts[-3:] != (self.family, self.name, "spec.py"):
            raise KernelContractError(
                "kernel source must end with <family>/<operation>/spec.py"
            )

    def _validate_backward(self, semantic_arguments: set[str]) -> None:
        assert self.backward is not None
        backward_schema = _parse_schema(self.backward.schema)
        if backward_schema.name != f"_{self.name}_bwd":
            raise SchemaError(
                f"backward provider must be named _{self.name}_bwd, got {backward_schema.name!r}"
            )
        backward_outputs = tuple(
            output for output in backward_schema.outputs if output is not None
        )
        for gradient in self.backward.gradients:
            if gradient.input_name not in semantic_arguments:
                raise KernelContractError(
                    f"gradient input {gradient.input_name!r} is not a semantic operator argument"
                )
            if gradient.output_name not in backward_outputs:
                raise KernelContractError(
                    f"gradient output {gradient.output_name!r} is not a named backward output"
                )
        saved_outputs = {
            output.name for output in self.forward.outputs if output.saved_for_backward
        }
        backward_arguments = set(backward_schema.arguments)
        missing_saved = saved_outputs - backward_arguments
        if missing_saved:
            raise KernelContractError(
                f"saved forward outputs missing from backward schema: {sorted(missing_saved)}"
            )
        if self.backward.supports_double_backward:
            raise KernelContractError(
                "double-backward claims require an explicit second-order provider contract in schema version 2"
            )

    def _validate_composite(self, semantic_arguments: set[str]) -> None:
        assert self.composite is not None
        unknown = {
            gradient.input_name
            for gradient in self.composite.gradients
            if gradient.input_name not in semantic_arguments
        }
        if unknown:
            raise KernelContractError(
                f"composite gradient inputs are not semantic operator arguments: {sorted(unknown)}"
            )
        if self.composite.supports_double_backward:
            raise KernelContractError(
                "composite double-backward claims require explicit second-order qualification in schema version 2"
            )

    def _validate_effects(self, semantic: _Schema) -> None:
        arguments = set(semantic.arguments)
        unknown_mutations = set(self.effects.mutates_inputs) - arguments
        if unknown_mutations:
            raise KernelContractError(f"mutated inputs are not schema arguments: {sorted(unknown_mutations)}")
        outputs = {output.name for output in self.forward.outputs}
        for output_name, input_name in self.effects.aliases_outputs:
            if output_name not in outputs or input_name not in arguments:
                raise KernelContractError(
                    f"invalid alias mapping {output_name!r} -> {input_name!r}"
                )
        if self.effects.mutates_inputs and "!" not in semantic.raw:
            raise SchemaError("mutating effect requires a mutable alias annotation in operator schema")
        if self.effects.aliases_outputs and not re.search(r"Tensor\([^)]*[A-Za-z][^)]*\)", semantic.raw):
            raise SchemaError("alias effect requires alias annotations in operator schema")


def _parse_schema(schema: str) -> _Schema:
    match = _SCHEMA_RE.match(schema)
    if match is None:
        raise SchemaError(f"invalid operator schema: {schema!r}")
    arguments = tuple(_argument_name(item) for item in _split_top_level(match.group("args")))
    returns = match.group("returns").strip()
    if returns.startswith("(") and returns.endswith(")"):
        return_items = _split_top_level(returns[1:-1])
    else:
        return_items = (returns,)
    outputs = tuple(_output_name(item) for item in return_items)
    _unique(arguments, "schema argument names")
    named_outputs = tuple(item for item in outputs if item is not None)
    _unique(named_outputs, "schema output names")
    return _Schema(match.group("name"), arguments, outputs, schema)


def _split_top_level(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    result: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
            if depth < 0:
                raise SchemaError("unbalanced schema delimiters")
        elif character == "," and depth == 0:
            result.append(value[start:index].strip())
            start = index + 1
    if depth != 0:
        raise SchemaError("unbalanced schema delimiters")
    result.append(value[start:].strip())
    if any(not item for item in result):
        raise SchemaError("empty item in operator schema")
    return tuple(result)


def _argument_name(item: str) -> str:
    without_default = item.split("=", 1)[0].strip()
    matches = _NAME_RE.findall(without_default)
    if len(matches) < 2:
        raise SchemaError(f"schema argument must have a type and name: {item!r}")
    return matches[-1]


def _output_name(item: str) -> str | None:
    matches = _NAME_RE.findall(item.strip())
    if not matches:
        raise SchemaError(f"invalid schema output: {item!r}")
    return matches[-1] if len(matches) >= 2 else None


def _validate_schema_outputs(schema: _Schema, expected: tuple[str, ...], label: str) -> None:
    if len(schema.outputs) != len(expected):
        raise SchemaError(
            f"{label} schema returns {len(schema.outputs)} outputs but metadata declares {len(expected)}"
        )
    named = tuple(output for output in schema.outputs if output is not None)
    if named and named != expected:
        raise SchemaError(
            f"{label} schema output names {named!r} do not match metadata {expected!r}"
        )
