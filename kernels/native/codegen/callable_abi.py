"""Cross-contract validation for callable program-node ABI v1."""

from __future__ import annotations

from collections import defaultdict

from kernels.api import (
    BackwardArgumentSource,
    KernelSpec,
    ProgramBindingSource,
    ProgramParameterKind,
    ScalarABIType,
    WorkspaceAccess,
)

from .schema import Argument, Return, parse_schema


_BACKWARD_SOURCE = {
    BackwardArgumentSource.OUTPUT_GRADIENT: ProgramBindingSource.OUTPUT_GRADIENT,
    BackwardArgumentSource.OPERATOR_ARGUMENT: ProgramBindingSource.OPERATOR_ARGUMENT,
    BackwardArgumentSource.FORWARD_OUTPUT: ProgramBindingSource.FORWARD_OUTPUT,
    BackwardArgumentSource.NEEDS_INPUT_GRAD: ProgramBindingSource.GRADIENT_REQUEST,
}


def _expected_parameter_kind(value: Argument | Return) -> tuple[ProgramParameterKind, ScalarABIType | None]:
    if value.is_tensor:
        return ProgramParameterKind.TENSOR, None
    scalar = {
        "bool": ScalarABIType.BOOL,
        "int": ScalarABIType.INT64,
        "float": ScalarABIType.FLOAT64,
    }[value.normalized_kind]
    return ProgramParameterKind.SCALAR, scalar


def _validate_parameter_type(parameter, value: Argument | Return, label: str) -> None:
    expected_kind, expected_scalar = _expected_parameter_kind(value)
    if parameter.kind is not expected_kind or parameter.scalar_type is not expected_scalar:
        raise ValueError(f"{label}: parameter kind does not match provider schema")
    if isinstance(value, Argument) and parameter.optional != value.is_optional:
        raise ValueError(f"{label}: parameter optionality does not match provider schema")


def _phase_sources(spec: KernelSpec, phase: str):
    semantic = parse_schema(spec.operator_schema)
    if phase == "forward":
        provider = parse_schema(spec.forward.schema)
        sources = {
            (ProgramBindingSource.OPERATOR_ARGUMENT, argument.name): argument
            for argument in provider.args
        }
        sources.update(
            {
                (ProgramBindingSource.FORWARD_OUTPUT, returned.name): returned
                for returned in provider.returns
            }
        )
        return provider, sources
    if spec.backward is None:
        raise ValueError(f"{spec.qualified_name}: backward callable ABI has no BackwardSpec")
    provider = parse_schema(spec.backward.schema)
    sources: dict[tuple[ProgramBindingSource, str], Argument] = {}
    for binding in spec.backward.argument_bindings:
        source = _BACKWARD_SOURCE[binding.source]
        key = (source, binding.source_name)
        argument = provider.argument_by_name(binding.provider_argument)
        if key in sources and sources[key].name != argument.name:
            raise ValueError(
                f"{spec.qualified_name}: callable source {source.value}/{binding.source_name} "
                "maps to multiple provider arguments"
            )
        sources[key] = argument
    return provider, sources


def _validate_phase(spec: KernelSpec, phase: str, provider_spec) -> None:
    group = provider_spec.program_group
    if group is None:
        return
    provider, sources = _phase_sources(spec, phase)
    provider_outputs = {returned.name: returned for returned in provider.returns}
    covered_arguments: set[str] = set()
    selector_arguments: set[str] = set()
    output_writers: dict[str, list[str]] = defaultdict(list)
    gradients = (
        {gradient.output_name: gradient for gradient in spec.backward.gradients}
        if phase == "backward" and spec.backward is not None
        else {}
    )

    for selector in group.selector_bindings:
        try:
            argument = provider.argument_by_name(selector.provider_argument)
        except KeyError as exc:
            raise ValueError(
                f"{spec.qualified_name}/{phase}: selector argument "
                f"{selector.provider_argument!r} is not a provider parameter"
            ) from exc
        if not argument.is_bool:
            raise ValueError(
                f"{spec.qualified_name}/{phase}: selector argument must have bool schema kind"
            )
        selector_arguments.add(argument.name)

    for node in group.nodes:
        parameters = {parameter.name: parameter for parameter in node.parameters}
        request_sources = {
            binding.source_name
            for binding in node.bindings
            if binding.source is ProgramBindingSource.GRADIENT_REQUEST
        }
        optional_request_sources: set[str] = set()
        for binding in node.bindings:
            parameter = parameters[binding.parameter]
            label = f"{spec.qualified_name}/{phase}/{node.name}/{binding.parameter}"
            if binding.source in {
                ProgramBindingSource.CURRENT_STREAM,
                ProgramBindingSource.WORKSPACE,
            }:
                continue
            if binding.source is ProgramBindingSource.PROVIDER_OUTPUT:
                try:
                    returned = provider_outputs[binding.source_name or ""]
                except KeyError as exc:
                    raise ValueError(f"{label}: unknown provider output") from exc
                expected_optional = False
                gradient = gradients.get(returned.name)
                if gradient is not None:
                    expected_optional = gradient.optional
                if parameter.optional != expected_optional:
                    raise ValueError(
                        f"{label}: provider-output optionality differs from GradientSpec"
                    )
                _validate_parameter_type(
                    parameter,
                    Return(
                        "Tensor?" if parameter.optional else returned.kind,
                        returned.name,
                    ),
                    label,
                )
                if parameter.access not in {
                    WorkspaceAccess.WRITE,
                    WorkspaceAccess.READ_WRITE,
                }:
                    raise ValueError(f"{label}: provider output is not writable")
                output_writers[returned.name].append(node.name)
                if expected_optional:
                    assert gradient is not None
                    optional_request_sources.add(gradient.input_name)
                    if gradient.input_name not in request_sources:
                        raise ValueError(
                            f"{label}: optional gradient output requires matching "
                            f"GRADIENT_REQUEST for {gradient.input_name!r}"
                        )
                continue
            key = (binding.source, binding.source_name or "")
            try:
                argument = sources[key]
            except KeyError as exc:
                raise ValueError(f"{label}: binding source does not map to provider schema") from exc
            _validate_parameter_type(parameter, argument, label)
            if parameter.access is not WorkspaceAccess.READ:
                raise ValueError(f"{label}: provider input must be read-only")
            covered_arguments.add(argument.name)
        if len(optional_request_sources) > 1:
            raise ValueError(
                f"{spec.qualified_name}/{phase}/{node.name}: independently optional provider "
                "outputs cannot share one node"
            )

    overlap = sorted(covered_arguments & selector_arguments)
    if overlap:
        raise ValueError(
            f"{spec.qualified_name}/{phase}: provider arguments cannot be both raw-bound "
            f"and selector-bound: {overlap}"
        )
    missing_arguments = sorted(
        set(provider.argument_names) - covered_arguments - selector_arguments
    )
    if missing_arguments:
        raise ValueError(
            f"{spec.qualified_name}/{phase}: provider arguments lack callable bindings: "
            f"{missing_arguments}"
        )
    for output in provider.return_names:
        writers = output_writers.get(output, [])
        if len(writers) != 1:
            raise ValueError(
                f"{spec.qualified_name}/{phase}: provider output {output!r} requires exactly "
                f"one writer, got {writers}"
            )


def validate_callable_abi(spec: KernelSpec, implementations=()) -> None:
    """Validate every callable program group against named provider schemas."""

    _validate_phase(spec, "forward", spec.forward)
    if spec.backward is not None:
        _validate_phase(spec, "backward", spec.backward)
    selector_modes = {
        mode
        for provider in (spec.forward, spec.backward)
        if provider is not None and provider.program_group is not None
        for selector in provider.program_group.selector_bindings
        for _case, mode in selector.cases
    }
    if selector_modes:
        envelope_modes = {
            mode
            for implementation in implementations
            for mode in implementation.envelope.modes
        }
        if envelope_modes != selector_modes:
            raise ValueError(
                f"{spec.qualified_name}: selector cases must exactly match implementation "
                f"envelope modes; selector={sorted(selector_modes)}, "
                f"envelopes={sorted(envelope_modes)}"
            )
