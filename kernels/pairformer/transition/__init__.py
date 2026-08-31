# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Pairformer transition semantic facade and independent reference."""
from .dispatch import transition
from .reference import transition_reference
from .spec import KERNEL_SPEC
__all__ = ["KERNEL_SPEC", "transition", "transition_reference"]
