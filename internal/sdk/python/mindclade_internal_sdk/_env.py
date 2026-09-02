"""The only place this SDK reads the process environment.

``Client.from_env()`` and ``AsyncClient.from_env()`` route through
:func:`config_from_env`; the ordinary :class:`~mindclade_internal_sdk.ClientConfig`
constructor reads nothing, so a program that builds a config explicitly gets
exactly what it asked for regardless of what the shell happens to export.

**There is no credential environment variable, and there never will be.** The
recognised names are enumerated in :data:`ENVIRONMENT_VARIABLES`; a workload
identity token provider is always an explicit constructor argument, so a
mis-set variable can never silently change which identity the SDK presents.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .auth import AsyncTokenProvider, SyncTokenProvider
from .config import ClientConfig, ConfigurationError, Environment

ENVIRONMENT_VARIABLE_PREFIX = "MINDCLADE_"

ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "MINDCLADE_ENVIRONMENT",
    "MINDCLADE_ENDPOINT",
    "MINDCLADE_TENANT_ID",
    "MINDCLADE_PROJECT_ID",
    "MINDCLADE_PRINCIPAL_ID",
    "MINDCLADE_AUDIENCE",
    "MINDCLADE_LOG",
)

# Variables that carry an identity the config object needs and that have no
# safe default: their absence is a configuration error naming the variable.
_REQUIRED_IDENTITY = (
    ("tenant_id", "MINDCLADE_TENANT_ID"),
    ("project_id", "MINDCLADE_PROJECT_ID"),
    ("principal_id", "MINDCLADE_PRINCIPAL_ID"),
)

_OPTIONAL = (
    ("endpoint", "MINDCLADE_ENDPOINT"),
    ("audience", "MINDCLADE_AUDIENCE"),
)


def _value(source: Mapping[str, str], name: str) -> str | None:
    raw = source.get(name)
    if raw is None:
        return None
    normalized = raw.strip()
    return normalized or None


def environment_from_env(environ: Mapping[str, str] | None = None) -> Environment | None:
    """Resolve ``MINDCLADE_ENVIRONMENT`` without naming its value in any error."""

    source = os.environ if environ is None else environ
    raw = _value(source, "MINDCLADE_ENVIRONMENT")
    if raw is None:
        return None
    try:
        return Environment(raw.lower())
    except ValueError as error:
        raise ConfigurationError(
            "MINDCLADE_ENVIRONMENT must be one of: "
            + ", ".join(member.value for member in Environment)
        ) from error


def config_from_env(
    *,
    token_provider: SyncTokenProvider | AsyncTokenProvider | None = None,
    environ: Mapping[str, str] | None = None,
    **overrides: Any,
) -> ClientConfig:
    """Build a :class:`ClientConfig` from ``MINDCLADE_*`` variables.

    Explicit ``overrides`` always beat the environment, and ``token_provider``
    is passed in by the caller because no environment variable may ever supply
    a credential.
    """

    source = os.environ if environ is None else environ
    settings: dict[str, Any] = {}

    environment = environment_from_env(source)
    if environment is not None:
        settings["environment"] = environment

    for field_name, variable in _REQUIRED_IDENTITY:
        value = _value(source, variable)
        if value is None and field_name not in overrides:
            raise ConfigurationError(
                f"{variable} is required to build a client from the environment"
            )
        if value is not None:
            settings[field_name] = value

    for field_name, variable in _OPTIONAL:
        value = _value(source, variable)
        if value is not None:
            settings[field_name] = value

    if token_provider is not None:
        settings["token_provider"] = token_provider
    settings.update(overrides)
    return ClientConfig(**settings)
