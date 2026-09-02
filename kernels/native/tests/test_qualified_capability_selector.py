from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from kernels.native.codegen.generate import render_qualified_capability_table


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _workload_digest() -> str:
    value = {
        "operation": "mindclade::fixture",
        "canonicalization_version": 1,
        "dimensions": [{"name": "batch_size", "value": 2}],
        "input_dtype": "float32",
        "layout": "contiguous",
        "mode": "default",
        "attributes": [],
    }
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _row(phase: str, priority: int, capability: str, symbol: str) -> dict[str, object]:
    return {
        "operation": "mindclade::fixture",
        "phase": phase,
        "workload_digest": _workload_digest(),
        "specialization_digest": _digest("a"),
        "capability_digest": _digest(capability),
        "artifact_digest": _digest("c" if phase == "forward" else "d"),
        "architecture": "sm90a",
        "dtype": "float32",
        "layout": "contiguous",
        "mode": "default",
        "dimensions": [{"name": "batch_size", "value": 2}],
        "attributes": [],
        "specificity": 1,
        "priority": priority,
        "adapter_symbols": [symbol],
    }


def test_nonempty_table_is_canonical_digest_bound_and_training_atomic() -> None:
    rows = [
        _row("backward", 9, "b", "fixture_bwd_fast"),
        _row("forward", 2, "e", "fixture_fwd_slow"),
        _row("forward", 9, "b", "fixture_fwd_fast"),
        _row("backward", 2, "e", "fixture_bwd_slow"),
    ]
    rendered = render_qualified_capability_table(
        rows, required_operations=("mindclade::fixture",)
    )
    table = json.loads(rendered["qualified_capabilities.generated.json"])
    assert table["row_fields"][10:13] == ["dimensions", "attributes", "specificity"]
    assert table["row_count"] == 4
    assert [row["phase"] for row in table["rows"]] == [
        "forward", "forward", "backward", "backward"
    ]
    assert table["rows"][0]["priority"] == 9
    assert table["rows_digest"] == _digest_json(table["rows"])
    without_digest = dict(table)
    assert without_digest.pop("table_digest") == _digest_json(without_digest)
    with pytest.raises(ValueError, match="atomic FWD/BWD"):
        render_qualified_capability_table(
            [rows[1]], required_operations=("mindclade::fixture",)
        )


def _digest_json(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda row: row.update(specificity=2), "specificity"),
        (lambda row: row.update(attributes=[{"name": "batch_size", "type": "int64", "value": 1}]), "overlap"),
        (lambda row: row.update(attributes=[{"name": "flag", "type": "int64", "value": True}]), "typed attribute"),
    ),
)
def test_nonempty_table_rejects_noncanonical_rows(mutation, message: str) -> None:
    row = _row("forward", 1, "b", "fixture_fwd")
    mutation(row)
    with pytest.raises(ValueError, match=message):
        render_qualified_capability_table([row])


def test_native_selector_executes_stable_winner_and_fails_closed(tmp_path: Path) -> None:
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable")
    rows = [
        _row("forward", 2, "e", "fixture_fwd_slow"),
        _row("backward", 2, "e", "fixture_bwd_slow"),
        _row("forward", 9, "b", "fixture_fwd_fast"),
        _row("backward", 9, "b", "fixture_bwd_fast"),
    ]
    rendered = render_qualified_capability_table(
        rows, required_operations=("mindclade::fixture",)
    )
    generated = tmp_path / "qualified.cpp"
    generated.write_text(rendered["qualified_capabilities.generated.cpp"])
    main = tmp_path / "main.cpp"
    main.write_text(
        f'''#include <cassert>
#include <cstdint>
#include <cstring>
#include "kernels/native/stable_abi/qualified_capability_table.h"

extern "C" int32_t fixture_fwd_slow(const MindcladeNodeLaunchV1*) {{ return 0; }}
extern "C" int32_t fixture_bwd_slow(const MindcladeNodeLaunchV1*) {{ return 0; }}
extern "C" int32_t fixture_bwd_fast(const MindcladeNodeLaunchV1*) {{ return 0; }}
extern "C" int32_t fixture_fwd_fast(const MindcladeNodeLaunchV1* launch) {{
  return launch != nullptr && launch->abi_version == 1u &&
         launch->parameter_count == 0u && launch->specialization_digest[0] == 0xaau
      ? MINDCLADE_NODE_STATUS_SUCCESS_V1 : MINDCLADE_NODE_STATUS_INVALID_PARAMETER_V1;
}}
extern "C" int32_t fixture_failure(const MindcladeNodeLaunchV1*) {{
  return MINDCLADE_NODE_STATUS_ENTRY_FAILURE_V1;
}}
int32_t sm90(int32_t device, uint32_t* architecture) {{
  if (device != 0 || architecture == nullptr) return 1;
  *architecture = MINDCLADE_DEVICE_ARCHITECTURE_SM90A_V1; return 0;
}}
int main() {{
  MindcladeCapabilityDimensionV1 dimensions[] = {{{{"batch_size", 2}}}};
  char digest[72]{{}};
  assert(mindclade_canonical_workload_digest_v1(
      "mindclade::fixture", 1u, dimensions, 1u, MINDCLADE_NODE_DTYPE_FLOAT32_V1,
      "contiguous", "default", nullptr, 0u, digest) == 0);
  assert(std::strcmp(digest, "{_workload_digest()}") == 0);
  MindcladeCapabilityRequestV1 request{{}};
  request.operation = "mindclade::fixture";
  request.phase = MINDCLADE_CAPABILITY_PHASE_FORWARD_V1;
  request.workload_digest = digest;
  request.device_index = 0; request.dtype = MINDCLADE_NODE_DTYPE_FLOAT32_V1;
  request.layout = "contiguous"; request.mode = "default";
  request.dimensions = dimensions; request.dimension_count = 1u;
  request.require_atomic_backward = 1u;
  const MindcladeQualifiedCapabilityRowV1* selected = nullptr;
  const auto* rows = mindclade_qualified_capability_rows_v1();
  const auto count = mindclade_qualified_capability_row_count_v1();
  assert(mindclade_select_qualified_capability_v1(rows, count, &request, &sm90, &selected) == 0);
  assert(selected != nullptr && selected->priority == 9);
  MindcladeNodeInvocationV1 invocation{{nullptr, 0u}};
  int32_t adapter_status = -1;
  assert(mindclade_execute_qualified_capability_v1(selected, &invocation, 1u, &adapter_status) == 0);
  assert(adapter_status == 0);
  assert(mindclade_select_qualified_capability_v1(rows, 1u, &request, &sm90, &selected) ==
         MINDCLADE_CAPABILITY_STATUS_INCOMPLETE_TRAINING_PAIR_V1);
  MindcladeQualifiedCapabilityRowV1 failing = rows[0];
  MindcladeNodeAdapterV1 adapters[] = {{&fixture_failure}};
  const char* symbols[] = {{"fixture_failure"}};
  failing.adapters = adapters; failing.adapter_symbols = symbols; failing.adapter_count = 1u;
  assert(mindclade_execute_qualified_capability_v1(&failing, &invocation, 1u, &adapter_status) ==
         MINDCLADE_CAPABILITY_STATUS_ADAPTER_FAILURE_V1);
  assert(adapter_status == MINDCLADE_NODE_STATUS_ENTRY_FAILURE_V1);
  return 0;
}}
'''
    )
    selector = Path("kernels/native/stable_abi/qualified_capability_selector.cpp")
    executable = tmp_path / "selector_test"
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-I", ".", "-I", "kernels/native/stable_abi",
            str(generated), str(selector), str(main), "-o", str(executable),
        ],
        check=True,
        cwd=Path.cwd(),
    )
    subprocess.run([str(executable)], check=True)
