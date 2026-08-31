# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

from __future__ import annotations

import torch

from .reference import outer_product_mean_reference

def outer_product_mean(left, right, mask, epsilon: float, *, use_reference: bool = False):
    """Run the semantic operator, or the explicit development reference path."""
    if use_reference:
        return outer_product_mean_reference(left, right, mask, epsilon)
    return torch.ops.mindclade.outer_product_mean(left, right, mask, epsilon)
