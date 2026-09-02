#!/usr/bin/env python3.12
"""Bind the four SDK retry-safety tables to the descriptor-derived RPC estate.

`internal/sdk/go/mindclade/method_policy.go` has long carried the comment "A
descriptor-conformance test keeps these identities tied to the generated service
estate." No such test existed. The tables were referenced nowhere outside their own
modules, and they drifted exactly as an unchecked table does: at the revision this
test was written, TypeScript classified 122 of 132 RPCs, Go 126, Rust 131 and Python
57, so the same RPC was retried in one language and not another.

Retry eligibility is a contract property -- whether replaying a call is
semantically valid -- so it must be identical in every language. This test is the
gate that makes divergence impossible: it reads the committed coverage projection,
which the atomic contract transaction derives from the candidate descriptor, and
holds all four SDKs to it.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
COVERAGE = REPOSITORY / "internal/sdk/rpc-coverage.generated.json"
PROJECTION_SCHEMA = "mindclade.internal-sdk-rpc-coverage-projection/v2"

ROUTE = re.compile(r'"(/mindclade\.[A-Za-z0-9_.]+/[A-Za-z0-9_]+)"')

# The single deliberate escape hatch. Lease expiry is a control-plane reconciler
# primitive, so replaying it is never safe and no language may retry it.
NEVER_RETRY = "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases"

SAFE = "safe"
IDEMPOTENT = "idempotent"
NEVER = "never"


def _routes_between(text: str, start: str, end: str) -> set[str]:
    index = text.find(start)
    if index < 0:
        return set()
    stop = text.find(end, index)
    return set(ROUTE.findall(text[index : stop if stop > 0 else len(text)]))


def go_policy() -> dict[str, str]:
    text = (REPOSITORY / "internal/sdk/go/mindclade/method_policy.go").read_text(encoding="utf-8")
    policy: dict[str, str] = {}
    for marker, classification in (
        ("var safeMethods", SAFE),
        ("var idempotentMutationMethods", IDEMPOTENT),
        ("var neverRetryMethods", NEVER),
    ):
        for route in _routes_between(text, marker, "\n}"):
            policy[route] = classification
    return policy


def python_policy() -> dict[str, str]:
    text = (REPOSITORY / "internal/sdk/python/mindclade_internal_sdk/method_policy.py").read_text(
        encoding="utf-8"
    )
    policy: dict[str, str] = {}
    for marker, classification in (
        ("SAFE_UNARY_METHODS", SAFE),
        ("IDEMPOTENT_MUTATION_METHODS", IDEMPOTENT),
        ("NEVER_RETRY_METHODS", NEVER),
    ):
        for route in _routes_between(text, marker, "\n)"):
            policy[route] = classification
    return policy


def rust_policy() -> dict[str, str]:
    text = (REPOSITORY / "internal/sdk/rust/src/retry.rs").read_text(encoding="utf-8")
    policy: dict[str, str] = {}
    for marker, classification in (
        ("fn safe_method", SAFE),
        ("fn idempotent_method", IDEMPOTENT),
        ("fn never_retry_method", NEVER),
    ):
        for route in _routes_between(text, marker, "\n}"):
            policy[route] = classification
    return policy


def typescript_policy() -> dict[str, str]:
    text = (REPOSITORY / "internal/sdk/typescript/src/safety.ts").read_text(encoding="utf-8")
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r'"(/mindclade\.[^"]+)",\s*"(safe|idempotent|never|unsafe)"', text)
    }


POLICIES = {
    "go": go_policy,
    "python": python_policy,
    "rust": rust_policy,
    "typescript": typescript_policy,
}


class SdkRetrySafetyParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        projection = json.loads(COVERAGE.read_text(encoding="utf-8"))
        if projection.get("schema_version") != PROJECTION_SCHEMA:
            raise AssertionError(
                f"{COVERAGE.name} is not a {PROJECTION_SCHEMA} document; "
                "regenerate it with `just generate-contracts`"
            )
        cls.projection = projection
        cls.routes = {str(rpc["route"]): rpc for rpc in projection["rpcs"]}
        cls.policies = {language: build() for language, build in POLICIES.items()}

    def test_projection_declares_the_expected_estate(self) -> None:
        """A shrunken projection must not silently relax every assertion below."""

        self.assertEqual(len(self.routes), len(self.projection["rpcs"]))
        self.assertIn(NEVER_RETRY, self.routes)

    def test_every_rpc_is_classified_in_every_language(self) -> None:
        """An unclassified RPC falls back to a per-language default, which is drift."""

        for language, policy in self.policies.items():
            missing = sorted(set(self.routes) - set(policy))
            with self.subTest(language=language):
                self.assertEqual(
                    missing,
                    [],
                    f"{language} does not classify {len(missing)} RPC(s) the descriptor "
                    f"declares: {missing[:8]}",
                )

    def test_no_language_classifies_an_unknown_rpc(self) -> None:
        """A table entry the descriptor does not declare is a stale identity."""

        for language, policy in self.policies.items():
            unknown = sorted(set(policy) - set(self.routes))
            with self.subTest(language=language):
                self.assertEqual(unknown, [], f"{language} classifies unknown RPCs: {unknown[:8]}")

    def test_all_four_languages_agree_on_every_rpc(self) -> None:
        """Retry eligibility is a contract property, so it cannot vary by language."""

        disagreements: dict[str, dict[str, str | None]] = {}
        for route in sorted(self.routes):
            verdicts = {language: policy.get(route) for language, policy in self.policies.items()}
            if len({value for value in verdicts.values() if value is not None}) > 1:
                disagreements[route] = verdicts
        self.assertEqual(disagreements, {}, f"languages disagree on {len(disagreements)} RPC(s)")

    def test_the_raw_only_rpc_is_never_retried_anywhere(self) -> None:
        """ExpireAttemptLeases replays a reconciler primitive; retrying it is unsafe."""

        for language, policy in self.policies.items():
            with self.subTest(language=language):
                self.assertEqual(
                    policy.get(NEVER_RETRY),
                    NEVER,
                    f"{language} does not mark {NEVER_RETRY} never-retry",
                )

    def test_only_the_projection_raw_only_rpc_is_never_retried(self) -> None:
        """The never-retry tier is the escape hatch, not a place to hide mutations."""

        expected = {
            route for route, rpc in self.routes.items() if rpc["classification"] == "raw-only"
        }
        for language, policy in self.policies.items():
            actual = {route for route, value in policy.items() if value == NEVER}
            with self.subTest(language=language):
                self.assertEqual(actual, expected)

    def test_read_rpcs_are_never_classified_as_mutations(self) -> None:
        """A server-streaming watch or a Get must not be treated as an idempotent write."""

        for route, rpc in self.routes.items():
            method = str(rpc["method"])
            if not method.startswith(("Get", "List", "Watch", "Query", "Resolve", "Describe")):
                continue
            for language, policy in self.policies.items():
                with self.subTest(language=language, method=method):
                    self.assertNotEqual(
                        policy.get(route),
                        IDEMPOTENT,
                        f"{language} classifies read RPC {method} as an idempotent mutation",
                    )


if __name__ == "__main__":
    unittest.main()
