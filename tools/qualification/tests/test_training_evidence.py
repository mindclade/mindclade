"""Regression tests for non-ratifying integration evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from readiness_report import build_report
from training_rehearsal import (
    POSTGRES_TARGETS,
    build_integration_receipt,
    build_receipt,
    canonical_json,
    sha256_bytes,
)


class TrainingEvidenceTest(unittest.TestCase):
    def test_fresh_database_receipt_is_exact_and_non_ratifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "services/control_plane/migrations"
            migrations.mkdir(parents=True)
            (migrations / "000001.up.sql").write_text("SELECT 1;\n", encoding="utf-8")

            receipt = build_integration_receipt(root, "a" * 40)
            digest = receipt.pop("receipt_digest")

            self.assertFalse(receipt["ratification_authorized"])
            self.assertEqual(receipt["required_bazel_targets"], list(POSTGRES_TARGETS))
            self.assertEqual(len(POSTGRES_TARGETS), len(set(POSTGRES_TARGETS)))
            self.assertEqual(digest, sha256_bytes(canonical_json(receipt)))

    def test_training_receipt_rejects_incomplete_check_set_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "missing=.*database"):
                build_receipt(
                    root,
                    "b" * 40,
                    {"grpc": "//services:grpc_test"},
                    root / "receipt.json",
                    {},
                )

    def test_readiness_report_maps_every_plan_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.md"
            plan.write_text(
                "## Acceptance\n" + "".join(f"- [ ] criterion {index}\n" for index in range(1, 31)),
                encoding="utf-8",
            )
            rehearsal = root / "rehearsal.json"
            rehearsal.write_text(
                json.dumps(
                    {
                        "ratification": {"authorized": False},
                        "schema_version": "mindclade.training-vertical-rehearsal/v1",
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(plan, rehearsal)

            criteria = report["criteria"]
            self.assertIsInstance(criteria, list)
            self.assertEqual(len(cast(list[object], criteria)), 30)
            self.assertFalse(report["ratification_authorized"])


if __name__ == "__main__":
    unittest.main()
