from pathlib import Path

from kernels.native.codegen.generate import check_outputs, render_all, write_outputs

ROOT = Path(__file__).resolve().parents[1]

SOURCE_FILES = (
    ROOT.parent / "pairformer" / "outer_product_mean" / "tilelang.py",
    ROOT.parent / "pairformer" / "pair_weighted_average" / "tilelang.py",
    ROOT.parent / "pairformer" / "triangle_attention" / "tilelang.py",
    ROOT.parent / "pairformer" / "triangle_multiplication" / "tilelang.py",
)


def test_committed_generated_outputs_have_zero_drift():
    rendered = render_all(ROOT, source_files=SOURCE_FILES)
    assert check_outputs(rendered, ROOT / "generated") == ()


def test_check_is_nonmutating_and_reports_exact_filename_drift(tmp_path: Path):
    native_root = tmp_path / "kernels" / "native"
    native_root.mkdir(parents=True)
    rendered = render_all(native_root, source_files=[])
    output = tmp_path / "generated"
    write_outputs(rendered, output)
    drifted = output / "native_ops.json"
    drifted.write_text("{}\n", encoding="utf-8")
    legacy = output / "python_registration.generated.py"
    legacy.write_text("legacy\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    errors = check_outputs(rendered, output)
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert any("native_ops.json" in error for error in errors)
    assert any("python_registration.generated.py" in error for error in errors)
    assert before == after
