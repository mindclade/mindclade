#!/usr/bin/env python3.12
"""Enforce the source-only local integration profile boundary."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/local/compose.yaml"
VALUES = ROOT / "deploy/local/local-values.yaml"
IDENTITY = ROOT / "deploy/local/fake-identity.yaml"
POSTGRES_DIGEST = "sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280"


class LocalStackContractTest(unittest.TestCase):
    def test_profile_is_digest_pinned_loopback_and_ephemeral(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn(f"image: postgres@{POSTGRES_DIGEST}", compose)
        self.assertIn("127.0.0.1:55432:5432", compose)
        self.assertIn("tmpfs:", compose)
        self.assertNotRegex(compose, re.compile(r"(?i)(password|secret|token|private[_-]?key)"))
        self.assertNotIn(":latest", compose)

    def test_adapters_are_local_and_non_production(self) -> None:
        values = VALUES.read_text(encoding="utf-8")
        identity = IDENTITY.read_text(encoding="utf-8")
        self.assertIn("adapter: deterministic-memory", values)
        self.assertIn("adapter: filesystem-cas", values)
        self.assertIn("production_authority: false", values)
        self.assertIn("key_source: ephemeral-process-memory", identity)
        self.assertIn("committed_private_key_allowed: false", identity)
        self.assertIn("connected_authority: false", identity)


if __name__ == "__main__":
    unittest.main()
