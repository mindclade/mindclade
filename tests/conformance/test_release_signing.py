#!/usr/bin/env python3.12
"""Conformance tests for canonical Wave 1 release signing."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tools.release.build_release_manifest import build_manifest
from tools.release.sign_release import main as sign_main
from tools.release.verify_release import main as verify_main

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SOURCE_SHA = "1" * 40


class ReleaseSigningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        private_key = ec.generate_private_key(ec.SECP256R1())
        self.private_path = self.root / "private.pem"
        self.public_path = self.root / "public.pem"
        self.private_path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.private_path.chmod(0o600)
        self.public_path.write_bytes(
            private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _unsigned_manifest(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            build_manifest(
                argparse.Namespace(
                    release_id="rel_wave1_fixture",
                    owner="release-engineering",
                    created_at="2026-08-30T00:00:00Z",
                    subject_type="wave1-kernel-fixture",
                    subject_digest=SHA_A,
                    source_revision=SOURCE_SHA,
                    build_target="//tests:wave1_fixture",
                    toolchain_digest=SHA_B,
                    lockfile=[f"gomod={SHA_C}"],
                    sbom=[SHA_A],
                    provenance=[SHA_B],
                    compatibility=[SHA_C],
                    qualification_policy=SHA_A,
                    evidence=[SHA_B],
                    environment_constraint=["cpu-only"],
                )
            ),
        )

    @staticmethod
    def _subject(manifest: MutableMapping[str, object]) -> MutableMapping[str, object]:
        spec = manifest.get("spec")
        if not isinstance(spec, dict):
            raise AssertionError("release manifest spec is missing")
        validated_spec = cast(MutableMapping[str, object], spec)
        subject = validated_spec.get("subject")
        if not isinstance(subject, dict):
            raise AssertionError("release manifest subject is missing")
        return cast(MutableMapping[str, object], subject)

    def test_sign_and_verify_exact_subject(self) -> None:
        unsigned_path = self.root / "unsigned.json"
        signed_path = self.root / "signed.json"
        unsigned_path.write_text(json.dumps(self._unsigned_manifest()), encoding="utf-8")
        self.assertEqual(
            sign_main(
                [
                    "--input",
                    str(unsigned_path),
                    "--output",
                    str(signed_path),
                    "--private-key",
                    str(self.private_path),
                    "--key-id",
                    "test/wave1-key",
                    "--signed-at",
                    "2026-08-30T00:00:01Z",
                ]
            ),
            0,
        )
        self.assertEqual(
            verify_main(
                [
                    "--input",
                    str(signed_path),
                    "--public-key",
                    str(self.public_path),
                    "--key-id",
                    "test/wave1-key",
                    "--expected-subject-digest",
                    SHA_A,
                ]
            ),
            0,
        )

    def test_tampered_payload_is_rejected(self) -> None:
        unsigned = self._unsigned_manifest()
        self._subject(unsigned)["digest"] = SHA_C
        path = self.root / "tampered.json"
        path.write_text(json.dumps(unsigned), encoding="utf-8")
        with self.assertRaises(SystemExit):
            sign_main(
                [
                    "--input",
                    str(path),
                    "--output",
                    str(self.root / "signed.json"),
                    "--private-key",
                    str(self.private_path),
                    "--key-id",
                    "test/wave1-key",
                    "--signed-at",
                    "2026-08-30T00:00:01Z",
                ]
            )


if __name__ == "__main__":
    unittest.main()
