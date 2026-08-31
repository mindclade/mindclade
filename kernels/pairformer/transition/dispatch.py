# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import torch

from .reference import transition_reference

def transition(gate, value, output_weight, output_bias, mask, *, use_reference: bool = False):
    """Run the semantic operator, or the explicit development reference path."""
    if use_reference:
        return transition_reference(gate, value, output_weight, output_bias, mask)
    return torch.ops.mindclade.transition(gate, value, output_weight, output_bias, mask)
