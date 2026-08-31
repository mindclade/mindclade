# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Pair-weighted-average semantic facade and independent reference."""
from .dispatch import pair_weighted_average
from .reference import pair_weighted_average_reference
from .spec import KERNEL_SPEC
__all__ = ["KERNEL_SPEC", "pair_weighted_average", "pair_weighted_average_reference"]
