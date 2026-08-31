from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Iterable, Mapping

from kernels.native.codegen.discover import discover_specs
from kernels.native.codegen.schema import parse_schema
from kernels.native.tilelang.model import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    KernelSpec,
    NAMESPACE,
    REGISTRATION_MODE,
)

HEADER = f"// GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.\n"
PY_HEADER = f"# GENERATED FILE - DO NOT EDIT. Generator: {GENERATOR_ID}@{GENERATOR_VERSION}.\n"
GENERATED_FILENAMES = (
    "native_ops.json",
    "registration.generated.cpp",
    "operation_registry.generated.cpp",
    "python_registration_generated.py",
    "native_ops.generated.cmake",
    "native_ops.generated.bzl",
)
LEGACY_FILENAMES = ("python_registration.generated.py",)
_NON_GENERATED_ENTRIES = {"__init__.py", "__pycache__"}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _source_inventory(specs: Iterable[KernelSpec]) -> list[dict[str, str]]:
    return [
        {"source": spec.source, "source_sha256": spec.source_sha256}
        for spec in sorted(specs, key=lambda item: item.source)
    ]


def _manifest(specs: list[KernelSpec]) -> str:
    for spec in specs:
        if spec.namespace != NAMESPACE or spec.qualified_name != f"{NAMESPACE}::{spec.name}":
            raise ValueError("generator accepts only mindclade namespace specifications")
    inventory = _source_inventory(specs)
    body = {
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "namespace": NAMESPACE,
        "operators": [spec.to_manifest() for spec in specs],
        "optimized_math_authority": "tilelang",
        "registration_mode": REGISTRATION_MODE,
        "request_time_compilation": False,
        "runtime_discovery": False,
        "schema_version": 2,
        "source_inventory_sha256": _sha256(_canonical_json(inventory).encode("utf-8")),
    }
    result = dict(body)
    result["semantic_digest"] = _sha256(_canonical_json(body).encode("utf-8"))
    return json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _registration_cpp(specs: list[KernelSpec]) -> str:
    lines = [
        HEADER.rstrip(),
        "#include <torch/csrc/stable/library.h>",
        "",
        "STABLE_TORCH_LIBRARY(mindclade, m) {",
    ]
    lines.extend(f'  m.def("{spec.schema}");' for spec in specs)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _impl_cpp(specs: list[KernelSpec]) -> str:
    lines = [
        HEADER.rstrip(),
        "#include <cstdint>",
        "#include <torch/csrc/stable/library.h>",
        "#include <torch/csrc/stable/tensor.h>",
        "",
    ]
    for spec in specs:
        parsed = parse_schema(spec.schema)
        lines.append(
            f'extern "C" {parsed.cpp_return_type} {spec.launch_symbol}'
            f"({parsed.cpp_parameters});"
        )
    if specs:
        lines.append("")
    lines.append("namespace mindclade::native::tilelang {")
    for spec in specs:
        parsed = parse_schema(spec.schema)
        arguments = ", ".join(argument.name for argument in parsed.args)
        lines.extend(
            [
                f"{parsed.cpp_return_type} {spec.name}({parsed.cpp_parameters}) {{",
                f"  return {spec.launch_symbol}({arguments});",
                "}",
            ]
        )
    lines.extend(
        [
            "}  // namespace mindclade::native::tilelang",
            "",
            "STABLE_TORCH_LIBRARY_IMPL(mindclade, CUDA, m) {",
        ]
    )
    lines.extend(
        f'  m.impl("{spec.name}", TORCH_BOX(&mindclade::native::tilelang::{spec.name}));'
        for spec in specs
    )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _python_registration(specs: list[KernelSpec]) -> str:
    lines = [
        PY_HEADER.rstrip(),
        "from __future__ import annotations",
        "",
        "_REGISTERED = False",
        "",
        "",
        "def register_python_kernels() -> None:",
        "    global _REGISTERED",
        "    if _REGISTERED:",
        "        return",
    ]
    if specs:
        lines.append("    import torch")
    for index, spec in enumerate(specs):
        lines.append(
            f"    from {spec.fake.module} import {spec.fake.symbol} as _mindclade_fake_{index}"
        )
        lines.append(
            f"    torch.library.register_fake({spec.qualified_name!r})(_mindclade_fake_{index})"
        )
        if spec.autograd.mode == "registered":
            assert spec.autograd.setup_context is not None
            assert spec.autograd.backward is not None
            lines.append(
                f"    from {spec.autograd.setup_context.module} import "
                f"{spec.autograd.setup_context.symbol} as _mindclade_setup_context_{index}"
            )
            lines.append(
                f"    from {spec.autograd.backward.module} import "
                f"{spec.autograd.backward.symbol} as _mindclade_backward_{index}"
            )
            lines.append(
                f"    torch.library.register_autograd({spec.qualified_name!r}, "
                f"_mindclade_backward_{index}, setup_context=_mindclade_setup_context_{index})"
            )
    lines.extend(["    _REGISTERED = True", ""])
    return "\n".join(lines)


def _cmake(specs: list[KernelSpec]) -> str:
    lines = [
        PY_HEADER.rstrip(),
        "set(MINDCLADE_TILELANG_KERNEL_SOURCES",
    ]
    lines.extend(
        f'  "${{CMAKE_CURRENT_LIST_DIR}}/../../{spec.source}"' for spec in specs
    )
    lines.append(")")
    return "\n".join(lines) + "\n"


def _bzl(specs: list[KernelSpec]) -> str:
    lines = [PY_HEADER.rstrip(), "MINDCLADE_TILELANG_KERNEL_SOURCES = ["]
    for spec in specs:
        source = Path(spec.source)
        lines.append(f'    "//kernels/{source.parent.as_posix()}:{source.name}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


def render_all(
    native_root: Path,
    *,
    source_files: Iterable[str | Path],
) -> dict[str, str]:
    """Purely render every projection from the explicit source inventory."""

    if native_root.is_symlink():
        raise ValueError(f"native root must not be a symlink: {native_root}")
    try:
        root = native_root.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ValueError(f"native root does not exist: {native_root}") from exc
    specs = discover_specs(root.parent, source_files)
    return {
        "native_ops.json": _manifest(specs),
        "registration.generated.cpp": _registration_cpp(specs),
        "operation_registry.generated.cpp": _impl_cpp(specs),
        "python_registration_generated.py": _python_registration(specs),
        "native_ops.generated.cmake": _cmake(specs),
        "native_ops.generated.bzl": _bzl(specs),
    }


def _validate_rendered(rendered: Mapping[str, str]) -> None:
    if set(rendered) != set(GENERATED_FILENAMES):
        raise ValueError("rendered outputs do not match the exact generated filename contract")
    if not all(isinstance(value, str) for value in rendered.values()):
        raise ValueError("all generated outputs must be text")


def _atomic_write(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def write_outputs(rendered: Mapping[str, str], output_dir: Path) -> tuple[Path, ...]:
    """Atomically replace each declared generated output."""

    _validate_rendered(rendered)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name in GENERATED_FILENAMES:
        path = output_dir / name
        _atomic_write(path, rendered[name])
        paths.append(path)
    for legacy_name in LEGACY_FILENAMES:
        (output_dir / legacy_name).unlink(missing_ok=True)
    return tuple(paths)


def check_outputs(rendered: Mapping[str, str], output_dir: Path) -> tuple[str, ...]:
    """Return byte-drift diagnostics without mutating the filesystem."""

    _validate_rendered(rendered)
    if not output_dir.is_dir():
        return (f"generated output directory is missing: {output_dir}",)
    errors: list[str] = []
    actual_entries = {entry.name for entry in output_dir.iterdir()}
    unexpected = sorted(actual_entries - set(GENERATED_FILENAMES) - _NON_GENERATED_ENTRIES)
    errors.extend(f"unexpected generated entry: {name}" for name in unexpected)
    for name in GENERATED_FILENAMES:
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing generated output: {name}")
        elif path.read_bytes() != rendered[name].encode("utf-8"):
            errors.append(f"generated output drift: {name}")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render deterministic Mindclade native bindings")
    parser.add_argument(
        "--native-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        type=Path,
        help="explicit Bazel-declared source, relative to the kernels root or absolute",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    output = args.output or args.native_root / "generated"
    rendered = render_all(args.native_root, source_files=args.source)
    if args.write:
        for path in write_outputs(rendered, output):
            print(path)
        return 0
    errors = check_outputs(rendered, output)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
