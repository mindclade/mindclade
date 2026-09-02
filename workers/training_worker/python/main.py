"""Private training-worker assignment materialization entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from control_plane import AssignmentMaterializer, client_options
from mindclade_internal_sdk import AsyncClient

_MAX_ENVELOPE_BYTES = 8 << 20


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize one immutable training assignment")
    parser.add_argument("envelope", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


async def _run() -> None:
    arguments = _arguments()
    serialized = arguments.envelope.read_bytes()
    if len(serialized) > _MAX_ENVELOPE_BYTES:
        raise ValueError("event envelope exceeds 8 MiB")
    # ``from_env`` is the SDK's only environment-reading path, and it also
    # installs the SDK's default observer for MINDCLADE_LOG.
    async with AsyncClient.from_env(**client_options()) as client:
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
