from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_reference_runtime_registers_only_mindclade_ops_in_isolated_process():
    root = Path(__file__).resolve().parents[3]
    script = r'''import torch
from kernels.native.python.reference_runtime import enable_reference_runtime
ops = enable_reference_runtime()
assert len(ops) == 4
left = torch.randn(2, 3, 2)
right = torch.randn(2, 3, 4)
mask = torch.ones(2, 3)
assert torch.ops.mindclade.outer_product_mean(left, right, mask, 1e-6).shape == (3, 3, 2, 4)
value = torch.randn(3, 2)
weights = torch.randn(3, 3, 2)
node_mask = torch.ones(3, dtype=torch.bool)
assert torch.ops.mindclade.pair_weighted_average(value, weights, node_mask, 1e-6).shape == (3, 2, 2)
q = torch.randn(2, 2, 1, 4)
bias = torch.zeros(2, 1, 2, 2)
pair_mask = torch.ones(2, 2, dtype=torch.bool)
assert torch.ops.mindclade.triangle_attention(q, q, q, bias, pair_mask, 0.5).shape == q.shape
pair = torch.randn(2, 2, 3)
assert torch.ops.mindclade.triangle_multiplication(pair, pair, pair_mask, True).shape == pair.shape
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    environment["MINDCLADE_NATIVE_REFERENCE_RUNTIME"] = "1"
    subprocess.run([sys.executable, "-c", script], env=environment, check=True)
