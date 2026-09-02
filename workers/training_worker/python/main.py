"""Private training-worker assignment materialization entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from control_plane import AssignmentMaterializer
from mindclade_internal_sdk import (
    AsyncClient,
    AsyncGoogleWorkloadIdentityProvider,
    ClientConfig,
    Environment,
)

_MAX_ENVELOPE_BYTES = 8 << 20


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize one immutable training assignment")
    parser.add_argument("envelope", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _config() -> ClientConfig:
    environment = Environment(os.environ.get("MINDCLADE_ENVIRONMENT", "development"))
    tenant_id = _required("MINDCLADE_TENANT_ID")
    project_id = _required("MINDCLADE_PROJECT_ID")
    principal_id = _required("MINDCLADE_PRINCIPAL_ID")
    endpoint = os.environ.get("MINDCLADE_ENDPOINT") or None
    if environment is Environment.LOCAL:
        return ClientConfig(
            tenant_id=tenant_id,
            project_id=project_id,
            principal_id=principal_id,
            environment=environment,
            endpoint=endpoint,
            user_agent="mindclade-training-worker/0.1",
            insecure_for_testing=True,
        )
    audience = _required("MINDCLADE_AUDIENCE")
    return ClientConfig(
        tenant_id=tenant_id,
        project_id=project_id,
        principal_id=principal_id,
        environment=environment,
        endpoint=endpoint,
        user_agent="mindclade-training-worker/0.1",
        token_provider=AsyncGoogleWorkloadIdentityProvider(audience),
    )


async def _run() -> None:
    arguments = _arguments()
    serialized = arguments.envelope.read_bytes()
    if len(serialized) > _MAX_ENVELOPE_BYTES:
        raise ValueError("event envelope exceeds 8 MiB")
    async with AsyncClient(_config()) as client:
        assignment = await AssignmentMaterializer(client).materialize(
            serialized,
            arguments.destination,
            timeout=arguments.timeout,
        )
    print(
        json.dumps(
            {
                "configuration_path": str(assignment.configuration_path),
                "event_id": assignment.event_id,
                "input_path": str(assignment.input_path) if assignment.input_path else None,
                "job_id": assignment.job_id,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_run())
