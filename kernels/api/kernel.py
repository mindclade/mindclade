"""Single declarative integration contract for a logical Mindclade operation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .backward import (
    BackwardArgumentSource,
    BackwardSpec,
    MissingGradientPolicy,
)
from .effects import EffectSpec
from .errors import KernelContractError, SchemaError
from .forward import ForwardSpec
from .gradient import GradientSpec
from .expressions import expression_references
from .launch import DeterminismClass, LaunchContract
from .output import ContractModel, _nonempty, _unique
from .program_group import ProgramGroupSpec
from .workload import RuntimeWorkloadSpec

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
    argument_kinds: tuple[str, ...]
    outputs: tuple[str | None, ...]
    output_kinds: tuple[str, ...]
    raw: str

    @property
    def argument_signature(self) -> tuple[tuple[str, str], ...]:
        return tuple(zip(self.arguments, self.argument_kinds, strict=True))

    @property
    def output_signature(self) -> tuple[tuple[str | None, str], ...]:
        return tuple(zip(self.outputs, self.output_kinds, strict=True))


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
    runtime_workload: RuntimeWorkloadSpec
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
        self._validate_program_groups()

        semantic = _parse_schema(self.operator_schema)
        forward = _parse_schema(self.forward.schema)
        self._validate_runtime_workload(semantic)
        if semantic.name != self.name:
            raise SchemaError(
                f"semantic operator name {semantic.name!r} must equal KernelSpec name {self.name!r}"
            )
        if forward.name != f"_{self.name}_fwd":
            raise SchemaError(
                f"forward provider must be named _{self.name}_fwd, got {forward.name!r}"
            )
        if forward.argument_signature != semantic.argument_signature:
            raise SchemaError(
                "semantic and forward provider argument names and kinds must match exactly "
                "in declaration order"
            )
        if forward.output_signature != semantic.output_signature:
            raise SchemaError(
                "semantic and forward provider output names and kinds do not match exactly "
                "in declaration order"
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
            self._validate_backward(semantic, forward)
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

    def _validate_program_groups(self) -> None:
        raw_groups = (
            self.forward.program_group,
            self.backward.program_group if self.backward is not None else None,
        )
        if any(
            group is not None and not isinstance(group, ProgramGroupSpec)
            for group in raw_groups
        ):
            raise KernelContractError("provider program_group must be a ProgramGroupSpec")
        groups = tuple(group for group in raw_groups if group is not None)
        logical_symbols = {self.forward.symbol}
        if self.backward is not None:
            logical_symbols.add(self.backward.symbol)
        private_symbols = [node.symbol for group in groups for node in group.nodes]
        collisions = sorted(logical_symbols.intersection(private_symbols))
        if collisions:
            raise KernelContractError(
                f"private program symbols collide with logical launchers: {collisions}"
            )
        if len(private_symbols) != len(set(private_symbols)):
            raise KernelContractError("private program symbols must be globally unique")
        if groups and not self.launch.current_stream_only:
            raise KernelContractError("v1 program groups require current-stream-only launch")
        if groups and self.launch.global_synchronization:
            raise KernelContractError("v1 program groups prohibit global synchronization")
        has_workspaces = any(group.workspaces for group in groups)
        if self.launch.hidden_device_allocation is not has_workspaces:
            raise KernelContractError(
                "launch.hidden_device_allocation must equal whether program-group "
                "workspaces are declared"
            )
        if has_workspaces and self.launch.graph_capture_safe:
            raise KernelContractError(
                "workspace-bearing v1 program groups cannot claim graph capture safety"
            )

    def _validate_runtime_workload(self, semantic: _Schema) -> None:
        if not isinstance(self.runtime_workload, RuntimeWorkloadSpec):
            raise KernelContractError("runtime_workload must be RuntimeWorkloadSpec")
        semantic_kinds = dict(semantic.argument_signature)
        expressions = [
            *(binding.value for binding in self.runtime_workload.dimensions),
            self.runtime_workload.input_dtype,
            *(binding.value for binding in self.runtime_workload.attributes),
        ]
        tensor_references: set[str] = set()
        scalar_references: set[str] = set()
        for expression in expressions:
            references = expression_references(expression)
            tensor_references.update(references.tensors)
            scalar_references.update(references.scalars)
        unknown = (tensor_references | scalar_references) - set(semantic.arguments)
        if unknown:
            raise KernelContractError(
                f"runtime workload references unknown semantic arguments: {sorted(unknown)}"
            )
        invalid_tensors = {
            name
            for name in tensor_references
            if semantic_kinds.get(name) not in {"Tensor", "Tensor?"}
        }
        invalid_scalars = {
            name
            for name in scalar_references
            if semantic_kinds.get(name) not in {"bool", "int", "float"}
        }
        if invalid_tensors or invalid_scalars:
            raise KernelContractError(
                "runtime workload expression reference kinds do not match semantic arguments; "
                f"tensors={sorted(invalid_tensors)}, scalars={sorted(invalid_scalars)}"
            )
        selectors = tuple(
            selector
            for provider in (self.forward, self.backward)
            if provider is not None and provider.program_group is not None
            for selector in provider.program_group.selector_bindings
        )
        selector_keys = {selector.selector_key for selector in selectors}
        if self.runtime_workload.mode_selector is None:
            if selector_keys:
                raise KernelContractError(
                    "runtime workload mode_selector is required for program selector bindings"
                )
            return
        if selector_keys != {self.runtime_workload.mode_selector}:
            raise KernelContractError(
                "runtime workload mode_selector must exactly match program selector keys"
            )
        cases_by_key = {
            tuple(selector.cases)
            for selector in selectors
            if selector.selector_key == self.runtime_workload.mode_selector
        }
        if len(cases_by_key) != 1:
            raise KernelContractError(
                "runtime workload mode selector cases must be identical across provider phases"
            )

    def _validate_backward(self, semantic: _Schema, forward: _Schema) -> None:
        assert self.backward is not None
        backward_schema = _parse_schema(self.backward.schema)
        if backward_schema.name != f"_{self.name}_bwd":
            raise SchemaError(
                f"backward provider must be named _{self.name}_bwd, got {backward_schema.name!r}"
            )
        semantic_kinds = dict(semantic.argument_signature)
        forward_output_kinds = {
            name: kind
            for name, kind in forward.output_signature
            if name is not None
        }
        backward_argument_kinds = dict(backward_schema.argument_signature)
        backward_outputs = tuple(output for output in backward_schema.outputs if output is not None)
        if len(backward_outputs) != len(backward_schema.outputs):
            raise SchemaError("backward provider outputs must all be explicitly named")

        bindings = {
            binding.provider_argument: binding
            for binding in self.backward.argument_bindings
        }
        provider_arguments = set(backward_schema.arguments)
        if set(bindings) != provider_arguments:
            missing = sorted(provider_arguments - set(bindings))
            extra = sorted(set(bindings) - provider_arguments)
            raise KernelContractError(
                "backward argument bindings must exactly cover provider parameters; "
                f"missing={missing}, extra={extra}"
            )

        gradient_inputs = {gradient.input_name for gradient in self.backward.gradients}
        forward_outputs = {output.name: output for output in self.forward.outputs}
        consumed_forward_outputs: set[str] = set()
        needs_input_grad_counts: dict[str, int] = {}
        output_gradient_policies: dict[str, MissingGradientPolicy] = {}
        for provider_argument in backward_schema.arguments:
            binding = bindings[provider_argument]
            provider_kind = backward_argument_kinds[provider_argument]
            if binding.source is BackwardArgumentSource.OUTPUT_GRADIENT:
                if binding.source_name not in forward_outputs:
                    raise KernelContractError(
                        f"output-gradient source {binding.source_name!r} is not a forward output"
                    )
                prior_policy = output_gradient_policies.get(binding.source_name)
                if prior_policy is not None and prior_policy is not binding.missing:
                    raise KernelContractError(
                        f"output-gradient source {binding.source_name!r} has conflicting "
                        "missing-gradient policies"
                    )
                output_gradient_policies[binding.source_name] = binding.missing
                expected_kind = forward_output_kinds[binding.source_name]
                if binding.missing is MissingGradientPolicy.PASS_NONE:
                    if provider_kind != f"{expected_kind}?":
                        raise SchemaError(
                            "PASS_NONE output-gradient binding requires an optional provider kind"
                        )
                elif provider_kind != expected_kind:
                    raise SchemaError(
                        f"output-gradient provider argument {provider_argument!r} kind "
                        f"{provider_kind!r} must match forward output kind {expected_kind!r}"
                    )
                if binding.missing is MissingGradientPolicy.ZERO:
                    output = forward_outputs[binding.source_name]
                    if not output.saved_for_backward:
                        raise KernelContractError(
                            f"ZERO output-gradient source {binding.source_name!r} must be "
                            "saved for backward"
                        )
                    if not self.launch.hidden_device_allocation:
                        raise KernelContractError(
                            "ZERO missing-gradient policy requires "
                            "launch.hidden_device_allocation=True"
                        )
                    consumed_forward_outputs.add(binding.source_name)
            elif binding.source is BackwardArgumentSource.OPERATOR_ARGUMENT:
                if binding.source_name not in semantic_kinds:
                    raise KernelContractError(
                        f"operator-argument source {binding.source_name!r} is not a semantic argument"
                    )
                if semantic_kinds[binding.source_name] == "Tensor?":
                    raise SchemaError(
                        "optional Tensor operator-argument bindings require schema version 2"
                    )
                if provider_kind != semantic_kinds[binding.source_name]:
                    raise SchemaError(
                        f"operator-argument provider kind {provider_kind!r} does not match "
                        f"semantic kind {semantic_kinds[binding.source_name]!r}"
                    )
            elif binding.source is BackwardArgumentSource.FORWARD_OUTPUT:
                output = forward_outputs.get(binding.source_name)
                if output is None:
                    raise KernelContractError(
                        f"forward-output source {binding.source_name!r} is not a forward output"
                    )
                if not output.saved_for_backward:
                    raise KernelContractError(
                        f"forward output {binding.source_name!r} is not saved for backward"
                    )
                if provider_kind != forward_output_kinds[binding.source_name]:
                    raise SchemaError(
                        f"forward-output provider kind {provider_kind!r} does not match "
                        f"output kind {forward_output_kinds[binding.source_name]!r}"
                    )
                consumed_forward_outputs.add(binding.source_name)
            elif binding.source is BackwardArgumentSource.NEEDS_INPUT_GRAD:
                if binding.source_name not in gradient_inputs:
                    raise KernelContractError(
                        f"needs_input_grad source {binding.source_name!r} is not a declared gradient input"
                    )
                if semantic_kinds.get(binding.source_name) != "Tensor":
                    raise KernelContractError(
                        f"needs_input_grad source {binding.source_name!r} must be a Tensor argument"
                    )
                if provider_kind != "bool":
                    raise SchemaError("needs_input_grad provider argument must have bool kind")
                count = needs_input_grad_counts.get(binding.source_name, 0) + 1
                if count > 1:
                    raise KernelContractError(
                        f"needs_input_grad source {binding.source_name!r} is bound more than once"
                    )
                needs_input_grad_counts[binding.source_name] = count

        semantic_arguments = set(semantic.arguments)
        metadata_sources = {
            binding.source_name
            for binding in self.backward.argument_bindings
            if binding.source is BackwardArgumentSource.OPERATOR_ARGUMENT
        }
        for gradient in self.backward.gradients:
            if gradient.input_name not in semantic_arguments:
                raise KernelContractError(
                    f"gradient input {gradient.input_name!r} is not a semantic operator argument"
                )
            if gradient.output_name not in backward_outputs:
                raise KernelContractError(
                    f"gradient output {gradient.output_name!r} is not a named backward output"
                )
            if semantic_kinds[gradient.input_name] != "Tensor":
                raise KernelContractError(
                    f"gradient input {gradient.input_name!r} must be a Tensor semantic argument"
                )
            output_index = backward_schema.outputs.index(gradient.output_name)
            output_kind = backward_schema.output_kinds[output_index]
            expected_kind = "Tensor?" if gradient.optional else "Tensor"
            if output_kind != expected_kind:
                raise SchemaError(
                    f"gradient output {gradient.output_name!r} kind {output_kind!r} "
                    f"must be {expected_kind!r}"
                )
            references = tuple(
                expression_references(expression)
                for expression in (gradient.shape, gradient.dtype, gradient.device)
            )
            tensor_references = {
                name for inventory in references for name in inventory.tensors
            }
            scalar_references = {
                name for inventory in references for name in inventory.scalars
            }
            all_references = tensor_references | scalar_references
            unknown_references = all_references - semantic_arguments
            if unknown_references:
                raise KernelContractError(
                    f"gradient {gradient.output_name!r} metadata references unknown semantic "
                    f"arguments: {sorted(unknown_references)}"
                )
            invalid_tensor_references = {
                name
                for name in tensor_references
                if semantic_kinds.get(name) not in {"Tensor", "Tensor?"}
            }
            invalid_scalar_references = {
                name
                for name in scalar_references
                if semantic_kinds.get(name) not in {"bool", "int", "float"}
            }
            if invalid_tensor_references or invalid_scalar_references:
                raise KernelContractError(
                    f"gradient {gradient.output_name!r} metadata reference kinds do not "
                    f"match semantic arguments; tensors={sorted(invalid_tensor_references)}, "
                    f"scalars={sorted(invalid_scalar_references)}"
                )
            unavailable_references = all_references - metadata_sources
            if unavailable_references:
                raise KernelContractError(
                    f"gradient {gradient.output_name!r} metadata requires named backward "
                    f"OPERATOR_ARGUMENT sources: {sorted(unavailable_references)}"
                )
        mapped_outputs = {gradient.output_name for gradient in self.backward.gradients}
        if mapped_outputs != set(backward_outputs):
            missing = sorted(set(backward_outputs) - mapped_outputs)
            extra = sorted(mapped_outputs - set(backward_outputs))
            raise KernelContractError(
                "gradient mappings must exactly cover backward outputs; "
                f"missing={missing}, extra={extra}"
            )
        missing_optional_requests = sorted(
            gradient.input_name
            for gradient in self.backward.gradients
            if gradient.optional
            and needs_input_grad_counts.get(gradient.input_name, 0) != 1
        )
        if missing_optional_requests:
            raise KernelContractError(
                "optional gradients require exactly one NEEDS_INPUT_GRAD binding; "
                f"missing={missing_optional_requests}"
            )
        saved_outputs = {
            output.name for output in self.forward.outputs if output.saved_for_backward
        }
        if saved_outputs != consumed_forward_outputs:
            missing_saved = sorted(saved_outputs - consumed_forward_outputs)
            unexpected = sorted(consumed_forward_outputs - saved_outputs)
            raise KernelContractError(
                "saved forward outputs must be consumed exactly once by named bindings; "
                f"missing={missing_saved}, unexpected={unexpected}"
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
    parsed_arguments = tuple(
        _typed_schema_item(item, require_name=True)
        for item in _split_top_level(match.group("args"))
    )
    returns = match.group("returns").strip()
    if returns.startswith("(") and returns.endswith(")"):
        return_items = _split_top_level(returns[1:-1])
    else:
        return_items = (returns,)
    parsed_outputs = tuple(
        _typed_schema_item(item, require_name=False) for item in return_items
    )
    arguments = tuple(name for name, _ in parsed_arguments)
    argument_kinds = tuple(kind for _, kind in parsed_arguments)
    outputs = tuple(name for name, _ in parsed_outputs)
    output_kinds = tuple(kind for _, kind in parsed_outputs)
    _unique(arguments, "schema argument names")
    named_outputs = tuple(item for item in outputs if item is not None)
    _unique(named_outputs, "schema output names")
    return _Schema(
        match.group("name"),
        arguments,
        argument_kinds,
        outputs,
        output_kinds,
        schema,
    )


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


def _typed_schema_item(
    item: str, *, require_name: bool
) -> tuple[str | None, str]:
    without_default = item.split("=", 1)[0].strip()
    match = re.fullmatch(r"(?P<kind>\S(?:.*\S)?)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", without_default)
    if match is None:
        if require_name:
            raise SchemaError(f"schema argument must have a type and name: {item!r}")
        kind = re.sub(r"\s+", "", without_default)
        if not kind or _NAME_RE.search(kind) is None:
            raise SchemaError(f"invalid schema output: {item!r}")
        return None, kind
    kind = re.sub(r"\s+", "", match.group("kind"))
    return match.group("name"), kind


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
