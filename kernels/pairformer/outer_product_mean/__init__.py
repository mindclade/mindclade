# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Outer-product-mean semantic facade and independent reference."""
from .dispatch import outer_product_mean
from .reference import outer_product_mean_reference
from .spec import KERNEL_SPEC
__all__ = ["KERNEL_SPEC", "outer_product_mean", "outer_product_mean_reference"]
