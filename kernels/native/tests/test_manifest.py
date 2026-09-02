from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kernels.native.tilelang.manifest import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SPEC_SOURCES = (
    "pairformer/outer_product_mean/spec.py",
    "pairformer/pair_weighted_average/spec.py",
    "pairformer/transition/spec.py",
    "pairformer/triangle_attention/spec.py",
    "pairformer/triangle_multiplication/spec.py",
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _gradient(input_name: str, output_name: str) -> dict[str, object]:
    return {
        "type": "GradientSpec",
        "input_name": input_name,
        "output_name": output_name,
        "optional": False,
        "accumulation_dtype": None,
        "version": 1,
    }


def _operator(source: str) -> dict[str, object]:
    family, name, _ = source.split("/")
    symbol = f"mindclade_tilelang_{name}_fwd_launch"
    operator: dict[str, object] = {
        "name": name,
        "qualified_name": f"mindclade::{name}",
        "namespace": "mindclade",
        "family": family,
        "source": source,
        "spec_sha256": _digest({"source": source}),
        "kernel_spec_digest": "",
        "implementation_digest": _digest([]),
        "implementation_candidates": [],
        "operator_schema": f"{name}(Tensor input) -> Tensor output",
        "facade_outputs": ["output"],
        "fake": None,
        "forward": {
            "type": "ForwardSpec",
            "schema": f"_{name}_fwd(Tensor input) -> Tensor output",
            "builder": f"kernels.{family}.{name}.tilelang:build_tilelang_program",
            "symbol": symbol,
            "outputs": [
                {
                    "type": "OutputSpec",
                    "name": "output",
                    "shape": {"argument": "input", "node": "shape_of"},
                    "dtype": {"argument": "input", "node": "dtype_ref"},
                    "device": {"argument": "input", "node": "device_ref"},
                    "semantic_axes": ["elements"],
                    "visible_in_facade": True,
                    "saved_for_backward": False,
                    "initialization": None,
                    "version": 1,
                }
            ],
            "program_group": None,
            "version": 1,
        },
        "backward": None,
        "autograd_policy": "composite",
        "composite": {
            "type": "CompositeAutogradSpec",
            "decomposition": f"kernels.{family}.{name}.reference:reference",
            "source_digest": _digest({"reference": source}),
            "runtime_envelope": "pytorch>=2.10,<2.11",
            "gradients": [_gradient("input", "grad_input")],
            "supports_double_backward": False,
            "setup_context": f"kernels.{family}.{name}.reference:setup_context",
            "backward": f"kernels.{family}.{name}.reference:composite_backward",
            "version": 1,
        },
        "effects": {
            "type": "EffectSpec",
            "mutates_inputs": [],
            "aliases_outputs": [],
            "uses_rng": False,
            "uses_atomics": False,
            "version": 1,
        },
        "launch": {
            "type": "LaunchContract",
            "current_stream_only": True,
            "global_synchronization": False,
            "hidden_device_allocation": False,
            "graph_capture_safe": False,
            "determinism": "conditionally_deterministic",
            "version": 1,
        },
        "backend": "tilelang",
        "version": 1,
        "devices": ["cuda"],
        "registrations": [
            {
                "qualified_name": f"mindclade::{name}",
                "schema": f"{name}(Tensor input) -> Tensor output",
                "kind": "semantic",
                "implementation_symbol": symbol,
            },
            {
                "qualified_name": f"mindclade::_{name}_fwd",
                "schema": f"_{name}_fwd(Tensor input) -> Tensor output",
                "kind": "forward",
                "implementation_symbol": symbol,
            },
        ],
        "launcher_plans": {"forward": None, "backward": None},
    }
    kernel_spec = {
        "type": "KernelSpec",
        **{
            key: operator[key]
            for key in (
                "name", "namespace", "family", "source", "operator_schema",
                "facade_outputs", "fake", "forward", "backward", "autograd_policy",
                "effects", "launch", "backend", "version", "devices", "composite",
            )
        },
    }
    operator["kernel_spec_digest"] = _digest(kernel_spec)
    return operator


def _resign(manifest: dict[str, object]) -> dict[str, object]:
    operators = manifest["operators"]
    assert isinstance(operators, list)
    manifest["source_inventory_sha256"] = _digest(
        [
            {
                "source": operator["source"],
                "spec_sha256": operator["spec_sha256"],
                "kernel_spec_digest": operator["kernel_spec_digest"],
                "implementation_digest": operator["implementation_digest"],
                "implementation_digest": operator["implementation_digest"],
            }
            for operator in sorted(operators, key=lambda item: item["source"])
        ]
    )
    manifest["semantic_digest"] = _digest(
        [
            {
                "qualified_name": operator["qualified_name"],
                "kernel_spec_digest": operator["kernel_spec_digest"],
            }
            for operator in operators
        ]
    )
    manifest["manifest_digest"] = _digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )
    return manifest


def _manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 3,
        "generator": {"id": "kernels.native.codegen.generate", "version": 7},
        "source_inventory_sha256": "",
        "namespace": "mindclade",
        "registration_mode": "build_time_generated",
        "optimized_math_authority": "tilelang",
        "runtime_discovery": False,
        "request_time_compilation": False,
        "operators": [_operator(source) for source in EXPECTED_SPEC_SOURCES],
        "semantic_digest": "",
        "manifest_digest": "",
    }
    return _resign(manifest)


def test_v3_fixture_is_strict_closed_world_target_inventory():
    manifest = validate_manifest(_manifest())
    assert set(manifest) == {
        "schema_version", "generator", "source_inventory_sha256", "namespace",
        "registration_mode", "optimized_math_authority", "runtime_discovery",
        "request_time_compilation", "operators", "semantic_digest", "manifest_digest",
    }
    assert manifest["schema_version"] == 3
    assert tuple(operator["source"] for operator in manifest["operators"]) == EXPECTED_SPEC_SOURCES
    assert all("qualification" not in operator for operator in manifest["operators"])


def test_v3_fixture_digest_roots_match_exact_canonical_inventories():
    manifest = validate_manifest(_manifest())
    operators = manifest["operators"]
    source_inventory = [
        {
            "source": operator["source"],
                "spec_sha256": operator["spec_sha256"],
                "kernel_spec_digest": operator["kernel_spec_digest"],
                "implementation_digest": operator["implementation_digest"],
            }
        for operator in sorted(operators, key=lambda item: item["source"])
    ]
    semantic_inventory = [
        {
            "qualified_name": operator["qualified_name"],
            "kernel_spec_digest": operator["kernel_spec_digest"],
        }
        for operator in operators
    ]
    assert manifest["source_inventory_sha256"] == _digest(source_inventory)
    assert manifest["semantic_digest"] == _digest(semantic_inventory)
    assert manifest["manifest_digest"] == _digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )


@pytest.mark.parametrize(
    ("field", "expected_error"),
    (
        ("source_inventory_sha256", "source inventory digest"),
        ("semantic_digest", "semantic digest"),
        ("manifest_digest", "manifest_digest"),
    ),
)
def test_manifest_rejects_each_independent_digest_root(field: str, expected_error: str):
    manifest = _manifest()
    manifest[field] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match=expected_error):
        validate_manifest(manifest)


def test_manifest_rejects_kernel_spec_digest_tampering_through_inventory_root():
    manifest = _manifest()
    manifest["operators"][0]["kernel_spec_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="source inventory digest"):
        validate_manifest(manifest)


def test_manifest_rejects_malformed_generator_bound_kernel_spec_digest():
    manifest = _manifest()
    manifest["operators"][0]["kernel_spec_digest"] = "not-a-digest"
    with pytest.raises(ValueError, match="kernel_spec_digest must use sha256"):
        validate_manifest(manifest)


def test_manifest_rejects_registration_contract_drift():
    manifest = _manifest()
    manifest["operators"][0]["registrations"][1]["kind"] = "semantic"
    with pytest.raises(ValueError, match="registrations do not match"):
        validate_manifest(manifest)


def test_manifest_rejects_launcher_plan_drift():
    manifest = _manifest()
    manifest["operators"][0]["launcher_plans"]["forward"] = {}
    _resign(manifest)
    with pytest.raises(ValueError, match="launcher plan"):
        validate_manifest(manifest)


def test_manifest_rejects_unsorted_or_duplicate_operator_identities():
    manifest = _manifest()
    manifest["operators"][0], manifest["operators"][1] = (
        manifest["operators"][1], manifest["operators"][0]
    )
    _resign(manifest)
    with pytest.raises(ValueError, match="sorted by qualified_name"):
        validate_manifest(manifest)


def test_manifest_rejects_unknown_fields_before_digest_validation():
    manifest = _manifest()
    manifest["operators"][0]["unexpected"] = True
    with pytest.raises(ValueError, match="missing or unsupported fields"):
        validate_manifest(manifest)


def test_manifest_load_never_regenerates_missing_output(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path)
    assert not (tmp_path / "generated").exists()


def test_manifest_loads_valid_v3_without_authoring_imports(tmp_path: Path):
    manifest = _manifest()
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "native_ops.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_manifest(tmp_path) == manifest


def test_manifest_rejects_duplicate_json_keys(tmp_path: Path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "native_ops.json").write_text(
        '{"schema_version":3,"schema_version":3}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_manifest(tmp_path)


def test_committed_manifest_is_current_v3_generated_output():
    manifest = load_manifest(ROOT)
    assert tuple(operator["source"] for operator in manifest["operators"]) == EXPECTED_SPEC_SOURCES
