"""Observer-backed logging that can only ever emit bounded RPC facts.

The SDK logs through the stdlib :mod:`logging` module under one named logger
and never touches the root logger, adds a handler, or changes propagation: an
embedding application keeps full control of where records go.

What may be logged is fixed by contract — method, attempt, elapsed time,
status, request id, trace id, retry accounting, and metadata *key names*. There
is no code path here that can reach a request payload, a response payload, an
access token, a lease token, or a metadata value.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .calls import RpcObservation
from .config import ConfigurationError

LOGGER_NAME = "mindclade_internal_sdk"

LOG_ENVIRONMENT_VARIABLE = "MINDCLADE_LOG"

# ``off`` maps to ``None``: no observer is installed at all, so the SDK does not
# even build a record it would then discard.
LOG_LEVELS: Mapping[str, int | None] = {
    "off": None,
    "none": None,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

_MESSAGE = (
    "mindclade rpc method=%s attempt=%d status=%s elapsed_ms=%d "
    "request_id=%s trace_id=%s retry_count=%d cumulative_delay_ms=%d metadata_keys=%s"
)


def logger() -> logging.Logger:
    """Return the SDK's logger without configuring it."""

    return logging.getLogger(LOGGER_NAME)


def log_level_from_env(environ: Mapping[str, str] | None = None) -> int | None:
    """Map ``MINDCLADE_LOG`` onto a stdlib level, or ``None`` for no logging."""

    source = os.environ if environ is None else environ
    raw = source.get(LOG_ENVIRONMENT_VARIABLE)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized not in LOG_LEVELS:
        raise ConfigurationError(
            f"{LOG_ENVIRONMENT_VARIABLE} must be one of: " + ", ".join(sorted(LOG_LEVELS))
        )
    return LOG_LEVELS[normalized]


class LoggingObserver:
    """Emit one bounded log record per RPC attempt."""

    __slots__ = ("_level", "_logger")

    def __init__(
        self,
        target: logging.Logger | None = None,
        *,
        level: int = logging.DEBUG,
    ) -> None:
        self._logger = target or logger()
        self._level = level

    @property
    def level(self) -> int:
        return self._level

    def observe(self, event: RpcObservation) -> None:
        if not self._logger.isEnabledFor(self._level):
            return
        self._logger.log(
            self._level,
            _MESSAGE,
            event.method,
            event.attempt,
            event.status,
            int(max(0.0, event.elapsed_seconds) * 1000),
            event.request_id,
            event.trace_id,
            event.retry_count,
            int(max(0.0, event.cumulative_delay_seconds) * 1000),
            ",".join(event.metadata_keys),
        )


def default_observer(environ: Mapping[str, str] | None = None) -> LoggingObserver | None:
    """Return a :class:`LoggingObserver` when ``MINDCLADE_LOG`` selects a level."""

    level = log_level_from_env(environ)
    if level is None:
        return None
    return LoggingObserver(level=level)
