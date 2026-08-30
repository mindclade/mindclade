# Copyright (c) 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

"""Import-safe attachment of build-time-generated Python registrations."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import stat
import threading


_GENERATED_MODULE = "kernels.native.generated.python_registration_generated"
_REGISTRATION_LOCK = threading.Lock()
_REGISTERED = False


def _validate_packaged_module(module: object) -> None:
    if getattr(module, "__name__", None) != _GENERATED_MODULE:
        raise RuntimeError("generated registration resolved to an unexpected module")
    spec = getattr(module, "__spec__", None)
    if spec is None or getattr(spec, "name", None) != _GENERATED_MODULE:
        raise RuntimeError("generated registration has no canonical module spec")
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str):
        raise RuntimeError("generated registration has no packaged source origin")
    source = Path(origin)
    expected = (
        Path(__file__).resolve().parents[1]
        / "generated"
        / "python_registration_generated.py"
    )
    try:
        source_stat = source.lstat()
        source_resolved = source.resolve(strict=True)
        expected_resolved = expected.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("generated registration source is unavailable") from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError("generated registration source is not a regular packaged file")
    if source_resolved != expected_resolved:
        raise RuntimeError("generated registration was not imported from this package")


def register_packaged_python_kernels() -> None:
    """Run only the canonical build-time-generated fake/autograd registrar."""

    global _REGISTERED
    with _REGISTRATION_LOCK:
        if _REGISTERED:
            return
        module = import_module(_GENERATED_MODULE)
        _validate_packaged_module(module)
        register = getattr(module, "register_python_kernels", None)
        if not callable(register):
            raise RuntimeError(
                "packaged generated registration has no register_python_kernels()"
            )
        register()
        _REGISTERED = True
