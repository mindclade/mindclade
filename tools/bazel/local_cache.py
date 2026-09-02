#!/usr/bin/env python3.12
"""Run Bazel with a bounded, checkout-external local disk cache."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SYSTEMS = {"aarch64-darwin", "aarch64-linux", "x86_64-linux"}
REPOSITORY = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "BUILDKITE")
PROHIBITED_PROFILES = ("ci", "release", "offline", "cacheless", "rbe-preparation")
PROHIBITED_OPTIONS = (
    "--disk_cache",
    "--experimental_disk_cache_gc_max_age",
    "--experimental_disk_cache_gc_max_size",
    "--remote_accept_cached",
    "--remote_cache",
    "--remote_executor",
    "--remote_upload_local_results",
)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def cache_path(
    *, checkout: Path, repository: str, system: str, override: Path | None = None
) -> Path:
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("repository cache key is not canonical")
    if system not in SYSTEMS:
        raise ValueError("system is unsupported")
    base = (
        override
        or Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        / "mindclade"
        / "bazel"
        / repository
        / system
    )
    resolved_checkout = checkout.resolve()
    resolved = base.expanduser().resolve(strict=False)
    if is_within(resolved, resolved_checkout):
        raise ValueError("local Bazel cache cannot be inside the checkout")
    return resolved


def ensure_local_only(arguments: list[str]) -> None:
    active_ci = [
        name for name in CI_VARIABLES if os.environ.get(name, "").lower() not in {"", "0", "false"}
    ]
    if active_ci:
        raise ValueError(f"local Bazel cache is disabled in CI ({', '.join(active_ci)})")
    for index, argument in enumerate(arguments):
        lowered = argument.lower()
        profile = ""
        if lowered == "--config" and index + 1 < len(arguments):
            profile = arguments[index + 1].lower()
        elif lowered.startswith("--config="):
            profile = lowered.partition("=")[2]
        if profile in PROHIBITED_PROFILES:
            raise ValueError(f"local Bazel cache is disabled for {profile} profiles")
        option = argument.lower().split("=", 1)[0]
        if option in PROHIBITED_OPTIONS:
            raise ValueError(f"local Bazel cache controls {option}; user override is prohibited")


def bazel_arguments(cache: Path) -> list[str]:
    return [
        f"--disk_cache={cache}",
        "--experimental_disk_cache_gc_max_size=20G",
        "--experimental_disk_cache_gc_max_age=14d",
        "--noremote_accept_cached",
        "--noremote_upload_local_results",
        "--remote_cache=",
        "--remote_executor=",
    ]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--checkout", type=Path, default=Path.cwd())
    value.add_argument("--repository", required=True)
    value.add_argument("--system", choices=sorted(SYSTEMS), required=True)
    value.add_argument("--cache-dir", type=Path)
    value.add_argument("--print", action="store_true", dest="print_only")
    value.add_argument("bazel_args", nargs=argparse.REMAINDER)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    command = list(args.bazel_args)
    if command and command[0] == "--":
        command.pop(0)
    try:
        ensure_local_only(command)
        path = cache_path(
            checkout=args.checkout,
            repository=args.repository,
            system=args.system,
            override=args.cache_dir,
        )
        flags = bazel_arguments(path)
        if args.print_only:
            print(json.dumps({"cache": str(path), "flags": flags}, sort_keys=True))
            return 0
        if not command:
            raise ValueError("a Bazel command is required after --")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        executable = os.environ.get("BAZEL", "bazel")
        return subprocess.run(
            [executable, command[0], *flags, *command[1:]], check=False
        ).returncode
    except (OSError, ValueError) as error:
        print(f"bazel-local-cache: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
