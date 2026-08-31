# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import torch

from .reference import pair_weighted_average_reference

def pair_weighted_average(value, weights, mask, epsilon: float, *, use_reference: bool = False):
    """Run the semantic operator, or the explicit development reference path."""
    if use_reference:
        return pair_weighted_average_reference(value, weights, mask, epsilon)
    return torch.ops.mindclade.pair_weighted_average(value, weights, mask, epsilon)
