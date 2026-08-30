"""Safe Buildkite annotations that never interpolate secret values."""

from __future__ import annotations

import re
import subprocess

ALLOWED_STYLES = {"info", "success", "warning", "error"}
SENSITIVE_PATTERN = re.compile(r"(?i)(token|secret|password|private[_ -]?key)\s*[:=]\s*\S+")


def redact(message: str) -> str:
    return SENSITIVE_PATTERN.sub(r"\1=[REDACTED]", message)[:8000]


def annotate(message: str, *, context: str, style: str = "info") -> None:
    if style not in ALLOWED_STYLES:
        raise ValueError(f"invalid annotation style: {style}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,100}", context):
        raise ValueError("invalid annotation context")
    subprocess.run(
        ["buildkite-agent", "annotate", "--context", context, "--style", style, redact(message)],
        check=True,
        timeout=30,
    )
