#!/usr/bin/env python3.12
"""Hold one cross-field constraint table to five languages and to the descriptor.

A rule that relates two sibling fields has no single field to live on, so it
gets written into whichever validator noticed it first -- and then copied. The
estate had three copies of one such rule when this was written: the agent
definition, the workflow definition, and the approval request each enumerated
the fields a caller may not set on a create, in three files, and the third list
differed from the other two. Correctly, as it happens -- an approval request
carries `requested_at` rather than the create/update/delete triple -- but
nothing could establish that, because nothing compared them.

Two more create requests embed a resource the same way and had no such check at
all: `CreateProjectRequest` and `CreateUsePolicyRequest`. Both take a `parent`
and a client-chosen id and derive the resource name from them, so a caller that
named its own project was told nothing -- the server discarded the field.
`CreatePromotionDecisionRequest` looks structurally identical and is not: it
carries no id, so the caller names the decision and the server requires it.
Assuming the shape rather than reading the validator is how a constraint that
would have rejected every call got as far as a test run.

`protocols/constraints/cross-field.yaml` is now the single definition, and this
gate holds it to three things: it resolves against the committed descriptor,
the five generated validators are exactly what it generates, and the rules it
declares are the same rules in every language.
"""

from __future__ import annotations

import base64
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

import yaml

from tools.codegen.generate_cross_field_constraints import (
    Constraint,
    GenerationError,
    load_constraints,
    load_json,
    outputs,
)

REPOSITORY = Path(__file__).resolve().parents[2]

CONSTRAINTS = REPOSITORY / "protocols/constraints/cross-field.yaml"
CANDIDATE = REPOSITORY / "protocols/compatibility/baselines/protobuf.candidate.json"
GENERATED_FILES = REPOSITORY / "protocols/generated/generated-files.manifest.json"
GENERATOR = REPOSITORY / "tools/codegen/generate_cross_field_constraints.py"

# Pinned so a constraint deleted by accident cannot shrink the gate silently.
EXPECTED_CONSTRAINTS = 5
EXPECTED_LANGUAGES = 5


def document() -> dict[str, Any]:
    return yaml.safe_load(CONSTRAINTS.read_text(encoding="utf-8"))


class CrossFieldConstraintTest(unittest.TestCase):
    constraints: ClassVar[list[Constraint]]
    digest: ClassVar[str]
    emitted: ClassVar[dict[Path, str]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.constraints, cls.digest = load_constraints(REPOSITORY)
        cls.emitted = outputs(cls.constraints, cls.digest)

    def test_the_table_is_bound_to_the_committed_descriptor(self) -> None:
        """The digest is the join key; three parties must agree on it."""

        raw = base64.b64decode(load_json(CANDIDATE)["descriptor_set"]["base64"])
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        self.assertEqual(self.digest, digest)
        self.assertEqual(document()["descriptor_digest"], digest)
        self.assertEqual(load_json(GENERATED_FILES)["descriptor_digest"], digest)

    def test_the_declared_estate_is_the_expected_size(self) -> None:
        self.assertEqual(len(self.constraints), EXPECTED_CONSTRAINTS)
        self.assertEqual(len(self.emitted), EXPECTED_LANGUAGES)

    def test_every_committed_validator_is_current(self) -> None:
        """The one check a hand-edit to a generated file cannot survive."""

        for relative, content in sorted(self.emitted.items()):
            with self.subTest(path=relative.as_posix()):
                path = REPOSITORY / relative
                self.assertTrue(path.is_file(), f"{relative} is missing")
                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    content,
                    f"{relative} is stale; run tools/codegen/generate_cross_field_constraints.py",
                )

    def test_the_generator_check_mode_agrees(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--root", str(REPOSITORY), "--check"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

    def test_every_constraint_appears_in_every_language(self) -> None:
        """The parity property: no rule may be enforced in one language only."""

        for constraint in self.constraints:
            for relative, content in sorted(self.emitted.items()):
                with self.subTest(constraint=constraint.identifier, path=relative.as_posix()):
                    self.assertIn(constraint.identifier, content)
                    self.assertIn(constraint.message, content)
                    self.assertIn(constraint.rule, content)

    def test_no_language_declares_a_rule_the_table_does_not(self) -> None:
        """The other direction: a generated file may not grow a rule of its own."""

        declared = {constraint.identifier for constraint in self.constraints}
        pattern = re.compile(r'"([a-z][a-z0-9]*(?:-[a-z0-9]+)+)"')
        for relative, content in sorted(self.emitted.items()):
            with self.subTest(path=relative.as_posix()):
                found = {
                    token
                    for token in pattern.findall(content.replace("'", '"'))
                    if token.count("-") >= 3
                }
                self.assertEqual(found - declared, set())

    def test_every_extracted_constraint_names_where_it_came_from(self) -> None:
        """An extracted rule must point at the code it mirrors, and that code must exist."""

        entries = {entry["id"]: entry for entry in document()["constraints"]}
        extracted = 0
        for constraint in self.constraints:
            entry = entries[constraint.identifier]
            if entry["origin"] != "extracted":
                self.assertNotIn("evidence", entry, constraint.identifier)
                continue
            extracted += 1
            with self.subTest(constraint=constraint.identifier):
                source = REPOSITORY / entry["evidence"]["source"]
                self.assertTrue(source.is_file(), entry["evidence"]["source"])
                self.assertIn(entry["evidence"]["symbol"], source.read_text(encoding="utf-8"))
        self.assertGreater(extracted, 0)

    def test_an_unresolvable_field_path_is_rejected(self) -> None:
        """The gate must fail on a table the descriptor does not support.

        Without this, every check above would pass on a table full of field
        paths that no message has.
        """

        for path, expected in (
            ("project.workspace_id", "has no field"),
            ("project.name.deeper", "descends through non-message"),
            ("project.policy_snapshots.name", "repeated"),
        ):
            with self.subTest(path=path):
                broken = document()
                broken["constraints"] = [
                    {
                        "id": "deliberately-broken-constraint",
                        "message": "mindclade.internal.admin.v1.CreateProjectRequest",
                        "rule": "output-only",
                        "fields": [path, "project.uid"],
                        "origin": "introduced",
                        "reason": "A fixture that must not resolve against the descriptor.",
                    }
                ]
                with (
                    TemporaryConstraints(broken) as fixture_root,
                    self.assertRaises(GenerationError) as raised,
                ):
                    load_constraints(fixture_root)
                self.assertIn(expected, str(raised.exception))

    def test_a_stale_descriptor_digest_is_rejected(self) -> None:
        """The table may not outlive the contract it was written against."""

        broken = document()
        broken["descriptor_digest"] = "sha256:" + "0" * 64
        with (
            TemporaryConstraints(broken) as fixture_root,
            self.assertRaises(GenerationError) as raised,
        ):
            load_constraints(fixture_root)
        self.assertIn("was written against", str(raised.exception))


class TemporaryConstraints:
    """Load a fixture table without touching the governed one.

    An earlier version wrote the fixture over
    `protocols/constraints/cross-field.yaml` and restored it afterwards. That
    leaves the real contract file as a one-constraint stub whenever a run is
    interrupted, and it cannot be run twice at once. This builds a throwaway
    root instead: the fixture is a real file, and everything else the loader
    reads is a symlink to the committed article.
    """

    LINKED = (
        "protocols/constraints/cross-field.schema.json",
        "protocols/compatibility/baselines/protobuf.candidate.json",
        "protocols/generated/generated-files.manifest.json",
    )

    def __init__(self, replacement: dict[str, Any]) -> None:
        self._replacement = replacement
        self._directory = tempfile.TemporaryDirectory(prefix="cross-field-fixture-")

    def __enter__(self) -> Path:
        root = Path(self._directory.name)
        for relative in self.LINKED:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(REPOSITORY / relative)
        fixture = root / "protocols/constraints/cross-field.yaml"
        fixture.write_text(yaml.safe_dump(self._replacement, sort_keys=False), encoding="utf-8")
        return root

    def __exit__(self, *_: object) -> None:
        self._directory.cleanup()


if __name__ == "__main__":
    unittest.main()
