#!/usr/bin/env python3.12
"""Emit an immutable, disconnected remote-execution worker manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from toolchain_contract import validate_manifest

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._:/-]+@sha256:[0-9a-f]{64}$")
SYSTEMS = {"aarch64-linux", "x86_64-linux"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("toolchain manifest is not an object")
    return cast(dict[str, Any], value)


def build(toolchain: Mapping[str, Any], image: str, closure_digest: str) -> dict[str, Any]:
    validate_manifest(toolchain, verify_files=False)
    if toolchain.get("system") not in SYSTEMS:
        raise ValueError("RBE worker supports only Linux systems")
    if not IMAGE.fullmatch(image):
        raise ValueError("worker image must use an immutable OCI digest")
    if not DIGEST.fullmatch(closure_digest):
        raise ValueError("Nix closure digest is not canonical")
    executables = cast(Mapping[str, Mapping[str, str]], toolchain.get("executables"))
    report: dict[str, Any] = {
        "schema_version": "rbe-worker-manifest.v1",
        "repository": toolchain["repository"],
        "system": toolchain["system"],
        "image": image,
        "nix_closure_digest": closure_digest,
        "nixpkgs": toolchain["nixpkgs"],
        "locks": toolchain["locks"],
        "policy": toolchain["policy"],
        "bazel": executables["bazel"],
        "jdk": executables["java"],
        "compiler": {"cc": executables["cc"], "cxx": executables["cxx"]},
        "toolchain_policy_digest": toolchain["toolchain_digest"],
        "execution": {
            "remote_executor": "",
            "remote_cache": "",
            "accept_remote_cache": False,
            "upload_local_results": False,
            "activation": "DISCONNECTED_PREPARATION",
        },
    }
    report["manifest_digest"] = "sha256:" + hashlib.sha256(canonical_json(report)).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--closure-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        toolchain = load(args.toolchain)
        validate_manifest(toolchain, verify_files=True)
        report = build(toolchain, args.image, args.closure_digest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json(report) + b"\n")
        return 0
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"rbe worker manifest: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
