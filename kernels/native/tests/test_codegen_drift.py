from pathlib import Path

from kernels.native.codegen.generate import DEFAULT_SPEC_SOURCES, check_outputs, render_all, write_outputs

ROOT = Path(__file__).resolve().parents[1]


def test_committed_generated_outputs_have_zero_drift():
    rendered = render_all(ROOT, source_files=DEFAULT_SPEC_SOURCES)
    assert check_outputs(rendered, ROOT / "generated") == ()


def test_check_is_nonmutating_and_reports_exact_filename_drift(tmp_path: Path):
    native_root = tmp_path / "kernels" / "native"
    native_root.mkdir(parents=True)
    rendered = render_all(native_root, source_files=[])
    output = tmp_path / "generated"
    write_outputs(rendered, output)
    (output / "native_ops.json").write_text("{}\n", encoding="utf-8")
    (output / "python_registration.generated.py").write_text("legacy\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    errors = check_outputs(rendered, output)
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert any("native_ops.json" in error for error in errors)
    assert any("python_registration.generated.py" in error for error in errors)
    assert before == after
