#!/usr/bin/env python3.12
"""Conformance tests for protected external release signing."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tools.release.build_release_manifest import (
    JsonObject,
    build_manifest,
    canonical_json,
    sha256_digest,
    unsigned_payload,
)
from tools.release.revoke_release import main as revoke_main
from tools.release.sign_release import load_transparency_log
from tools.release.sign_release import main as sign_main
from tools.release.verify_release import main as verify_main

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SOURCE_SHA = "1" * 40
KEY_ID = "gcp-kms://projects/test/locations/global/keyRings/release/cryptoKeys/signing/cryptoKeyVersions/1"


class ReleaseSigningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_path = self.root / "public.pem"
        self.public_path.write_bytes(
            self.private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        self.transparency_path = self.root / "transparency.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _approval(self, gate: str, subject_digest: str, reviewer: str) -> JsonObject:
        return {
            "schema_version": "mindclade.release-approval/v1",
            "kind": "QualificationApproval",
            "gate": gate,
            "approval_id": f"approval-{gate.lower()}-{subject_digest[-8:]}",
            "decision": "approved",
            "reviewer_identity": reviewer,
            "subject_digest": subject_digest,
            "source_revision": SOURCE_SHA,
            "qualification_policy_digest": SHA_A,
            "evidence_digest": SHA_B if gate == "K4" else SHA_C,
            "approved_at": "2026-09-02T00:00:00Z",
        }

    def _release_inputs(
        self, name: str, subject_digest: str, k5_reviewer: str = "principal://qualification/k5"
    ) -> dict[str, Any]:
        k4 = self._approval("K4", subject_digest, "principal://qualification/k4")
        k5 = self._approval("K5", subject_digest, k5_reviewer)
        k4_path = self.root / f"{name}.k4.json"
        k5_path = self.root / f"{name}.k5.json"
        k4_path.write_bytes(canonical_json(k4) + b"\n")
        k5_path.write_bytes(canonical_json(k5) + b"\n")
        manifest = build_manifest(
            argparse.Namespace(
                release_id=f"rel_{name}",
                owner="release-engineering",
                created_at="2026-09-02T00:00:01Z",
                subject_type="native-kernel-bundle",
                subject_digest=subject_digest,
                source_revision=SOURCE_SHA,
                build_target="//kernels/native:native_policy_inputs",
                toolchain_digest=SHA_B,
                lockfile=[f"module={SHA_C}"],
                sbom=[SHA_A],
                provenance=[SHA_B],
                compatibility=[SHA_C],
                qualification_policy=SHA_A,
                evidence=[SHA_B],
                approval=[
                    f"K4={sha256_digest(canonical_json(k4))}",
                    f"K5={sha256_digest(canonical_json(k5))}",
                ],
                environment_constraint=["source-only", "zero-promoted-capabilities"],
            )
        )
        unsigned_path = self.root / f"{name}.unsigned.json"
        signed_path = self.root / f"{name}.signed.json"
        signature_path = self.root / f"{name}.external-signature.json"
        unsigned_path.write_bytes(canonical_json(manifest) + b"\n")
        payload = canonical_json(unsigned_payload(manifest))
        external_signature: JsonObject = {
            "schema_version": "mindclade.external-signature/v1",
            "kind": "ExternalSignature",
            "algorithm": "ecdsa-p256-sha256",
            "key_id": KEY_ID,
            "key_protection": "HSM",
            "signer_identity": "principal://release/external-signer",
            "payload_digest": sha256_digest(payload),
            "signed_at": "2026-09-02T00:00:02Z",
            "signature": base64.b64encode(
                self.private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
            ).decode("ascii"),
        }
        signature_path.write_bytes(canonical_json(external_signature) + b"\n")
        return {
            "manifest": manifest,
            "unsigned": unsigned_path,
            "signed": signed_path,
            "signature": signature_path,
            "k4": k4_path,
            "k5": k5_path,
        }

    def _sign(self, inputs: dict[str, Any]) -> None:
        self.assertEqual(
            sign_main(
                [
                    "--input",
                    str(inputs["unsigned"]),
                    "--output",
                    str(inputs["signed"]),
                    "--external-signature",
                    str(inputs["signature"]),
                    "--public-key",
                    str(self.public_path),
                    "--key-id",
                    KEY_ID,
                    "--k4-approval",
                    str(inputs["k4"]),
                    "--k5-approval",
                    str(inputs["k5"]),
                    "--transparency-log",
                    str(self.transparency_path),
                ]
            ),
            0,
        )

    def _verify_args(self, inputs: dict[str, Any]) -> list[str]:
        return [
            "--input",
            str(inputs["signed"]),
            "--public-key",
            str(self.public_path),
            "--key-id",
            KEY_ID,
            "--k4-approval",
            str(inputs["k4"]),
            "--k5-approval",
            str(inputs["k5"]),
            "--transparency-log",
            str(self.transparency_path),
        ]

    def test_external_signature_and_transparency_verify_exact_subject(self) -> None:
        inputs = self._release_inputs("candidate", SHA_A)
        self._sign(inputs)
        self.assertEqual(
            verify_main([*self._verify_args(inputs), "--expected-subject-digest", SHA_A]),
            0,
        )
        entries = load_transparency_log(self.transparency_path)
        self.assertEqual([entry["event"] for entry in entries], ["release-signed"])
        self.assertEqual(entries[0]["previous_entry_digest"], "sha256:" + "0" * 64)

    def test_independent_k4_k5_reviewers_are_required(self) -> None:
        inputs = self._release_inputs(
            "same-reviewer", SHA_A, k5_reviewer="principal://qualification/k4"
        )
        with self.assertRaises(SystemExit):
            self._sign(inputs)

    def test_tampered_payload_is_rejected_before_attachment(self) -> None:
        inputs = self._release_inputs("tampered", SHA_A)
        manifest = inputs["manifest"]
        manifest["spec"]["subject"]["digest"] = SHA_C
        inputs["unsigned"].write_bytes(canonical_json(manifest) + b"\n")
        with self.assertRaises(SystemExit):
            self._sign(inputs)

    def test_revocation_rollback_drill_preserves_append_only_history(self) -> None:
        rollback = self._release_inputs("prior", SHA_B)
        candidate = self._release_inputs("candidate-drill", SHA_A)
        self._sign(rollback)
        self._sign(candidate)
        drill_path = self.root / "revocation-rollback.json"
        self.assertEqual(
            revoke_main(
                [
                    "--manifest",
                    str(candidate["signed"]),
                    "--public-key",
                    str(self.public_path),
                    "--key-id",
                    KEY_ID,
                    "--k4-approval",
                    str(candidate["k4"]),
                    "--k5-approval",
                    str(candidate["k5"]),
                    "--rollback-manifest",
                    str(rollback["signed"]),
                    "--rollback-public-key",
                    str(self.public_path),
                    "--rollback-key-id",
                    KEY_ID,
                    "--rollback-k4-approval",
                    str(rollback["k4"]),
                    "--rollback-k5-approval",
                    str(rollback["k5"]),
                    "--transparency-log",
                    str(self.transparency_path),
                    "--reason-code",
                    "signer_compromise_drill",
                    "--revoker-identity",
                    "principal://security/revoker",
                    "--rollback-approver-identity",
                    "principal://release/rollback-approver",
                    "--created-at",
                    "2026-09-02T00:00:03Z",
                    "--output",
                    str(drill_path),
                ]
            ),
            0,
        )
        with self.assertRaises(SystemExit):
            verify_main(self._verify_args(candidate))
        self.assertEqual(verify_main(self._verify_args(rollback)), 0)
        entries = load_transparency_log(self.transparency_path)
        self.assertEqual(
            [entry["event"] for entry in entries],
            ["release-signed", "release-signed", "release-revoked", "rollback-selected"],
        )
        self.assertEqual([entry["sequence"] for entry in entries], [1, 2, 3, 4])
        for previous, current in pairwise(entries):
            self.assertEqual(current["previous_entry_digest"], previous["entry_digest"])
        drill = json.loads(drill_path.read_text(encoding="utf-8"))
        self.assertTrue(drill["source_only"])
        self.assertFalse(drill["connected_execution"])


if __name__ == "__main__":
    unittest.main()
