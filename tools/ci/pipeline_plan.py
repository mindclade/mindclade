#!/usr/bin/env python3.12
"""Create a canonical, revision-bound Wave 0 CI plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from affected_targets import changed_paths as discover_changed_paths
from affected_targets import normalize_path, targets_for_paths
from affected_targets import self_test as affected_targets_self_test

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BUILDKITE_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
LAUNCHER_IDENTITY_PATTERN = re.compile(r"^buildkite://[a-z0-9][a-z0-9._/-]{7,255}$")
PROTECTED_DEFINITION_PATHS = (
    ".bazelrc",
    ".bazelversion",
    ".buildkite",
    ".github",
    ".gitignore",
    ".markdownlint-cli2.yaml",
    ".pre-commit-config.yaml",
    ".python-version",
    ".yamllint.yaml",
    "BUILD.bazel",
    "Cargo.lock",
    "Cargo.toml",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "buf.gen.yaml",
    "buf.yaml",
    "component.yaml",
    "docs/adr",
    "docs/architecture",
    "flake.lock",
    "flake.nix",
    "go.mod",
    "go.sum",
    "justfile",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "rust-toolchain.toml",
    "tools",
    "uv.lock",
)
PUBLIC_CACHE_TARGET_ALLOWLIST: tuple[str, ...] = ()
CACHE_NAMESPACE_FIELDS = (
    "schema_version",
    "classification",
    "namespace_epoch",
    "trust_class",
    "system",
    "toolchain_digest",
    "build_mode",
)
CACHE_POISON_RECOVERY = (
    "revoke-affected-namespace",
    "rebuild-with-cache-disabled",
    "compare-clean-output-digests",
    "require-reviewed-reactivation-evidence",
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def build_plan(
    *,
    source_revision: str,
    pipeline_definition_revision: str,
    pipeline_class: str,
    changed_files: list[str],
) -> dict[str, Any]:
    if not SHA_PATTERN.fullmatch(source_revision):
        raise ValueError("source revision must be one full lowercase Git SHA")
    if not SHA_PATTERN.fullmatch(pipeline_definition_revision):
        raise ValueError("pipeline definition revision must be one full lowercase Git SHA")
    if pipeline_class not in {"presubmit", "protected", "nightly", "gpu", "release", "security"}:
        raise ValueError(f"unsupported pipeline class: {pipeline_class}")

    paths = sorted({normalize_path(path) for path in changed_files})
    if pipeline_class == "security":
        targets = []
    else:
        targets = targets_for_paths(paths) or list(targets_for_paths(["BUILD.bazel"]))
    gates = {
        "security": [
            "immutable-launcher",
            "cache-boundary",
            "dependency-and-license-policy",
            "secret-scan",
        ],
        "protected": [
            "immutable-launcher",
            "cache-boundary",
            "repository-governance",
            "dependency-and-license-policy",
            "secret-scan",
            "bazel-native-agreement",
            "source-check",
            "wave1-full",
            "cacheless-reproducibility",
            "fresh-database-integration",
            "authoritative-integration-readiness",
        ],
        "nightly": [
            "immutable-launcher",
            "cache-boundary",
            "repository-governance",
            "dependency-and-license-policy",
            "secret-scan",
            "bazel-native-agreement",
            "source-check",
            "wave1-full",
            "cacheless-reproducibility",
            "fresh-database-integration",
            "authoritative-integration-readiness",
        ],
        "presubmit": [
            "immutable-launcher",
            "cache-boundary",
            "repository-governance",
            "dependency-and-license-policy",
            "secret-scan",
            "bazel-native-agreement",
            "fresh-database-integration",
            "authoritative-integration-readiness",
        ],
    }.get(
        pipeline_class,
        [
            "immutable-launcher",
            "cache-boundary",
            "repository-governance",
            "dependency-and-license-policy",
            "secret-scan",
            "bazel-native-agreement",
        ],
    )
    plan: dict[str, Any] = {
        "schema_version": "pipeline-plan.v1",
        "source_revision": source_revision,
        "pipeline_definition_revision": pipeline_definition_revision,
        "pipeline_class": pipeline_class,
        "changed_paths": paths,
        "targets": targets,
        "gates": gates,
    }
    digest = hashlib.sha256(canonical_json(plan)).hexdigest()
    plan["plan_id"] = f"sha256:{digest}"
    return plan


def protected_definition_digest(root: Path, revision: str) -> str:
    if not SHA_PATTERN.fullmatch(revision):
        raise ValueError("protected definition revision must be one full lowercase Git SHA")
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "archive",
            "--format=tar",
            revision,
            "--",
            *PROTECTED_DEFINITION_PATHS,
        ],
        check=True,
        capture_output=True,
    )
    return f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}"


def build_launcher_observation(
    *,
    source_revision: str,
    pipeline_definition_revision: str,
    launcher_revision: str,
    launcher_digest: str,
    launcher_identity: str,
    definition_tree_digest: str,
    build_id: str,
) -> dict[str, object]:
    for value, name in (
        (source_revision, "source revision"),
        (pipeline_definition_revision, "pipeline definition revision"),
        (launcher_revision, "launcher revision"),
    ):
        if not SHA_PATTERN.fullmatch(value):
            raise ValueError(f"{name} must be one full lowercase Git SHA")
    for value, name in (
        (launcher_digest, "launcher digest"),
        (definition_tree_digest, "definition tree digest"),
    ):
        if not DIGEST_PATTERN.fullmatch(value):
            raise ValueError(f"{name} must be a canonical SHA-256 digest")
    if not LAUNCHER_IDENTITY_PATTERN.fullmatch(launcher_identity):
        raise ValueError("launcher identity must be a canonical buildkite:// identity")
    if not BUILDKITE_UUID_PATTERN.fullmatch(build_id):
        raise ValueError("build ID must be a canonical lowercase Buildkite UUID")
    return {
        "schema_version": "immutable-launcher-observation.v1",
        "qualification": "UNSIGNED_OBSERVATION_INPUT",
        "external_signature_required": True,
        "source_revision": source_revision,
        "pipeline_definition_revision": pipeline_definition_revision,
        "launcher_revision": launcher_revision,
        "launcher_digest": launcher_digest,
        "launcher_identity": launcher_identity,
        "definition_tree_digest": definition_tree_digest,
        "build_id": build_id,
    }


def build_cache_boundary(
    *,
    source_revision: str,
    pipeline_class: str,
    trust_class: str,
    platform: str,
    architecture: str,
    toolchain_digest: str,
    build_mode: str,
    cache_mode: str,
    classification: str,
    namespace_epoch: str,
    iam_qualification_digest: str | None,
    write_activation_digest: str | None,
    endpoint: str | None = None,
    signer_public_key_digest: str | None = None,
    audit_sink_digest: str | None = None,
) -> dict[str, object]:
    if not SHA_PATTERN.fullmatch(source_revision):
        raise ValueError("cache boundary source revision must be a full lowercase Git SHA")
    if trust_class not in {"untrusted", "trusted", "protected"}:
        raise ValueError("cache trust class is not allowlisted")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", platform):
        raise ValueError("cache platform is not canonical")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", architecture):
        raise ValueError("cache architecture is not canonical")
    if not DIGEST_PATTERN.fullmatch(toolchain_digest):
        raise ValueError("cache toolchain digest is not canonical")
    if build_mode != pipeline_class:
        raise ValueError("cache build mode must match the pipeline class")
    if cache_mode not in {"disabled", "read", "write"}:
        raise ValueError("cache mode is not allowlisted")
    evidence = (iam_qualification_digest, signer_public_key_digest, audit_sink_digest)
    if cache_mode == "disabled":
        if any(value is not None for value in (*evidence, write_activation_digest, endpoint)):
            raise ValueError("disabled cache mode must not imply connected activation evidence")
        if classification != "private-internal" or namespace_epoch != "disabled-v2":
            raise ValueError("disabled cache must use the unactivated private namespace")
        qualification = "DISABLED"
    else:
        if not isinstance(endpoint, str) or not re.fullmatch(
            r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", endpoint
        ):
            raise ValueError("active cache requires a canonical HTTPS endpoint")
        if any(
            not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value) for value in evidence
        ):
            raise ValueError("cache use requires IAM, signer, and audit qualification digests")
        if namespace_epoch == "disabled-v2" or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{1,63}", namespace_epoch
        ):
            raise ValueError("active cache requires a qualified namespace epoch")
        if trust_class == "untrusted":
            raise ValueError("untrusted source cannot use the private cache")
        qualification = "IAM_QUALIFIED"
        if cache_mode == "write":
            if trust_class != "protected" or pipeline_class not in {"protected", "nightly"}:
                raise ValueError("cache writes require protected main or nightly execution")
            if not isinstance(write_activation_digest, str) or not DIGEST_PATTERN.fullmatch(
                write_activation_digest
            ):
                raise ValueError("cache writes require immutable activation evidence")
            qualification = "WRITE_ACTIVATED"
        elif write_activation_digest is not None:
            raise ValueError("read-only cache must not carry write activation evidence")
    system = f"{architecture}-{platform}"
    if system not in {"aarch64-darwin", "aarch64-linux", "x86_64-linux"}:
        raise ValueError("cache system is unsupported")
    namespace = {
        "schema_version": "cache-namespace.v2",
        "classification": classification,
        "namespace_epoch": namespace_epoch,
        "trust_class": trust_class,
        "system": system,
        "toolchain_digest": toolchain_digest,
        "build_mode": build_mode,
    }
    if tuple(namespace) != CACHE_NAMESPACE_FIELDS:
        raise AssertionError("cache namespace field order drifted")
    return {
        "schema_version": "cache-boundary.v2",
        "qualification": qualification,
        "source_revision": source_revision,
        "cache_mode": cache_mode,
        "cache_used": cache_mode != "disabled",
        "cache_outputs_are_evidence": False,
        "public_cache_target_allowlist": list(PUBLIC_CACHE_TARGET_ALLOWLIST),
        "endpoint": endpoint,
        "namespace": namespace,
        "iam_qualification_digest": iam_qualification_digest,
        "write_activation_digest": write_activation_digest,
        "signer_public_key_digest": signer_public_key_digest,
        "audit_sink_digest": audit_sink_digest,
        "cacheless_canary": {
            "required": pipeline_class in {"protected", "nightly"},
            "targets": ["//:wave1_tests"],
            "remote_cache_read": False,
            "remote_cache_write": False,
        },
        "poison_recovery": list(CACHE_POISON_RECOVERY),
    }


def _assert_evidence_gate_sets_are_consistent() -> None:
    """Gate the readiness report wherever the fresh-database check is gated.

    `just integration-ci` writes both `integration-ci.v1.json` and
    `authoritative-integration-readiness.v2.json` unconditionally, and
    `just ci-evidence` passes every report present on disk.
    `evidence_bundle.build_evidence` then rejects a bundle whose report set
    differs from the planned gate set. A class planning the fresh-database
    gate while omitting the readiness gate therefore yields a bundle that can
    never validate, failing `ci-evidence` on every real build.

    This reads the real gate lists rather than a fixture: the defect it guards
    against was a production gate list drifting away from a synthetic test
    list that already agreed with the justfile.
    """
    source_revision = "c" * 40
    pipeline_revision = "d" * 40
    for pipeline_class in ("presubmit", "protected", "nightly", "gpu", "release", "security"):
        gates = build_plan(
            source_revision=source_revision,
            pipeline_definition_revision=pipeline_revision,
            pipeline_class=pipeline_class,
            changed_files=["libs/go/audit/writer.go"],
        )["gates"]
        if (
            "fresh-database-integration" in gates
            and "authoritative-integration-readiness" not in gates
        ):
            raise AssertionError(
                f"pipeline class {pipeline_class!r} gates fresh-database-integration without "
                "authoritative-integration-readiness; just integration-ci emits both reports and "
                "ci-evidence requires the report set to equal the planned gate set exactly"
            )


def self_test() -> None:
    affected_targets_self_test()
    _assert_evidence_gate_sets_are_consistent()
    source_revision = "a" * 40
    pipeline_revision = "b" * 40
    plan = build_plan(
        source_revision=source_revision,
        pipeline_definition_revision=pipeline_revision,
        pipeline_class="protected",
        changed_files=["libs/go/audit/writer.go"],
    )
    if plan["targets"] != [
        "//:wave0_tests",
        "//tools:repository_governance_tests",
        "//:wave1_tests",
    ]:
        raise AssertionError("protected plan omitted the active Wave 1 closure")
    unsigned = {key: value for key, value in plan.items() if key != "plan_id"}
    expected_id = f"sha256:{hashlib.sha256(canonical_json(unsigned)).hexdigest()}"
    if plan["plan_id"] != expected_id:
        raise AssertionError("pipeline plan ID does not bind canonical plan bytes")
    from evidence_bundle import validate_plan

    validate_plan(
        plan,
        source_revision=source_revision,
        pipeline_definition_revision=pipeline_revision,
    )
    observation = build_launcher_observation(
        source_revision=source_revision,
        pipeline_definition_revision=pipeline_revision,
        launcher_revision="c" * 40,
        launcher_digest="sha256:" + "d" * 64,
        launcher_identity="buildkite://mindclade/protected-launcher",
        definition_tree_digest="sha256:" + "e" * 64,
        build_id="01234567-89ab-cdef-8123-456789abcdef",
    )
    if observation["qualification"] != "UNSIGNED_OBSERVATION_INPUT":
        raise AssertionError("launcher observation incorrectly claims connected qualification")
    boundary = build_cache_boundary(
        source_revision=source_revision,
        pipeline_class="protected",
        trust_class="protected",
        platform="linux",
        architecture="x86_64",
        toolchain_digest="sha256:" + "f" * 64,
        build_mode="protected",
        cache_mode="disabled",
        classification="private-internal",
        namespace_epoch="disabled-v2",
        iam_qualification_digest=None,
        write_activation_digest=None,
    )
    if boundary["cache_used"] is not False or boundary["cache_outputs_are_evidence"] is not False:
        raise AssertionError("cache boundary treats cache use as qualification evidence")
    if boundary["public_cache_target_allowlist"] != []:
        raise AssertionError("public cache allowlist activated without review")
    for mode, iam, write in (
        ("read", None, None),
        ("write", "sha256:" + "1" * 64, None),
        ("write", "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    ):
        try:
            build_cache_boundary(
                source_revision=source_revision,
                pipeline_class="protected",
                trust_class="protected",
                platform="linux",
                architecture="x86_64",
                toolchain_digest="sha256:" + "f" * 64,
                build_mode="protected",
                cache_mode=mode,
                classification="private-internal",
                namespace_epoch="qualified-epoch-1",
                iam_qualification_digest=iam,
                write_activation_digest=write,
                endpoint="https://nix-cache.mindclade.com" if iam else None,
                signer_public_key_digest="sha256:" + "3" * 64 if iam else None,
                audit_sink_digest="sha256:" + "4" * 64 if iam else None,
            )
        except ValueError:
            if mode != "write" or iam is None or write is None:
                continue
            raise
        if mode != "write" or write is None:
            raise AssertionError(f"cache mode {mode} activated without complete evidence")

    readiness_self_test()


def readiness_self_test() -> None:
    """Prove the readiness gate accepts an exact report and rejects tampering.

    Every rejection case is re-sealed with a freshly computed self-digest so it
    isolates exactly one guard; otherwise the digest check masks the others and
    the gate can silently lose a rule.
    """

    from evidence_bundle import validate_check_report

    source_revision = "c" * 40

    def seal(payload: dict[str, object]) -> dict[str, object]:
        body = {key: value for key, value in payload.items() if key != "report_digest"}
        encoded = (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()
        return {**body, "report_digest": "sha256:" + hashlib.sha256(encoded).hexdigest()}

    criterion: dict[str, object] = {
        "bazel_targets": ["//protocols:protobuf_compatibility_test"],
        "criterion": "Preserve user work \u2014 archive predecessor authority.",
        "criterion_id": "adapted-execution-checklist-01",
        "owner": "contract-governance",
        "qualification_class": "source",
        "stage": "program",
        "status": "evidence-present-unverified",
    }
    report = seal(
        {
            "criteria": [criterion],
            "criterion_map_digest": "sha256:" + "1" * 64,
            "plan_digest": "sha256:" + "2" * 64,
            "ratification_authorized": False,
            "schema_version": "mindclade.authoritative-integration-readiness/v2",
            "source_revision": source_revision,
            "summary": {"evidence-present-unverified": 1},
        }
    )

    def check(payload: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authoritative-integration-readiness.v2.json"
            path.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            validate_check_report(
                "authoritative-integration-readiness",
                path,
                source_revision,
                pipeline_definition_revision="d" * 40,
                pipeline_class="protected",
                build_id="00000000-0000-4000-8000-000000000000",
                context={},
            )

    check(report)

    missing_target = {key: value for key, value in criterion.items() if key != "bazel_targets"}
    unknown_class = {**criterion, "qualification_class": "protected"}
    rejections: list[tuple[str, dict[str, object]]] = [
        ("wrong source revision", seal({**report, "source_revision": "e" * 40})),
        ("self-asserted ratification", seal({**report, "ratification_authorized": True})),
        ("empty criteria", seal({**report, "criteria": []})),
        (
            "wrong schema version",
            seal({**report, "schema_version": "mindclade.authoritative-integration-readiness/v1"}),
        ),
        ("criterion without target binding", seal({**report, "criteria": [missing_target]})),
        ("unsupported qualification class", seal({**report, "criteria": [unknown_class]})),
        ("duplicate criterion", seal({**report, "criteria": [criterion, dict(criterion)]})),
        ("malformed plan digest", seal({**report, "plan_digest": "not-a-digest"})),
        # Deliberately NOT re-sealed: proves the self-digest is enforced.
        ("tampered body with stale digest", {**report, "summary": {"tampered": 1}}),
    ]
    for label, payload in rejections:
        try:
            check(payload)
        except ValueError:
            continue
        raise AssertionError(f"readiness gate accepted an inexact report: {label}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision")
    parser.add_argument("--pipeline-definition-revision")
    parser.add_argument("--pipeline-class", default="presubmit")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launcher-revision")
    parser.add_argument("--launcher-digest")
    parser.add_argument("--launcher-identity")
    parser.add_argument("--build-id")
    parser.add_argument("--launcher-observation-output", type=Path)
    parser.add_argument("--cache-boundary-output", type=Path)
    parser.add_argument("--cache-mode", default="disabled")
    parser.add_argument("--cache-trust-class")
    parser.add_argument("--cache-platform")
    parser.add_argument("--cache-architecture")
    parser.add_argument("--cache-toolchain-digest")
    parser.add_argument("--cache-build-mode")
    parser.add_argument("--cache-classification")
    parser.add_argument("--cache-namespace-epoch")
    parser.add_argument("--cache-iam-qualification-digest")
    parser.add_argument("--cache-write-activation-digest")
    parser.add_argument("--cache-endpoint")
    parser.add_argument("--cache-signer-public-key-digest")
    parser.add_argument("--cache-audit-sink-digest")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        print("pipeline, affected-target, launcher, and cache contract self-test passed")
        return 0
    required_inputs = {
        "source-revision": args.source_revision,
        "pipeline-definition-revision": args.pipeline_definition_revision,
        "launcher-revision": args.launcher_revision,
        "launcher-digest": args.launcher_digest,
        "launcher-identity": args.launcher_identity,
        "build-id": args.build_id,
        "launcher-observation-output": args.launcher_observation_output,
        "cache-boundary-output": args.cache_boundary_output,
        "cache-trust-class": args.cache_trust_class,
        "cache-platform": args.cache_platform,
        "cache-architecture": args.cache_architecture,
        "cache-toolchain-digest": args.cache_toolchain_digest,
        "cache-build-mode": args.cache_build_mode,
        "cache-classification": args.cache_classification,
        "cache-namespace-epoch": args.cache_namespace_epoch,
    }
    missing_inputs = sorted(name for name, value in required_inputs.items() if not value)
    if missing_inputs:
        print(
            f"invalid pipeline plan: missing protected inputs: {', '.join(missing_inputs)}",
            file=sys.stderr,
        )
        return 2
    root = args.root.resolve()
    try:
        paths = (
            args.changed_file
            if args.changed_file
            else discover_changed_paths(root, args.base, args.head, strict=True)
        )
        if not paths:
            raise ValueError("the exact changed-path set is empty")
        plan = build_plan(
            source_revision=cast(str, args.source_revision),
            pipeline_definition_revision=cast(str, args.pipeline_definition_revision),
            pipeline_class=args.pipeline_class,
            changed_files=paths,
        )
        launcher_observation = build_launcher_observation(
            source_revision=cast(str, args.source_revision),
            pipeline_definition_revision=cast(str, args.pipeline_definition_revision),
            launcher_revision=cast(str, args.launcher_revision),
            launcher_digest=cast(str, args.launcher_digest),
            launcher_identity=cast(str, args.launcher_identity),
            definition_tree_digest=protected_definition_digest(
                root, cast(str, args.pipeline_definition_revision)
            ),
            build_id=cast(str, args.build_id),
        )
        cache_boundary = build_cache_boundary(
            source_revision=cast(str, args.source_revision),
            pipeline_class=args.pipeline_class,
            trust_class=cast(str, args.cache_trust_class),
            platform=cast(str, args.cache_platform),
            architecture=cast(str, args.cache_architecture),
            toolchain_digest=cast(str, args.cache_toolchain_digest),
            build_mode=cast(str, args.cache_build_mode),
            cache_mode=args.cache_mode,
            classification=cast(str, args.cache_classification),
            namespace_epoch=cast(str, args.cache_namespace_epoch),
            iam_qualification_digest=args.cache_iam_qualification_digest,
            write_activation_digest=args.cache_write_activation_digest,
            endpoint=args.cache_endpoint,
            signer_public_key_digest=args.cache_signer_public_key_digest,
            audit_sink_digest=args.cache_audit_sink_digest,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
        print(f"invalid pipeline plan: {error}", file=sys.stderr)
        return 2

    rendered = canonical_json(plan)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rendered)
    else:
        sys.stdout.buffer.write(rendered)
    launcher_output = cast(Path, args.launcher_observation_output)
    launcher_output.parent.mkdir(parents=True, exist_ok=True)
    launcher_output.write_bytes(canonical_json(launcher_observation))
    cache_output = cast(Path, args.cache_boundary_output)
    cache_output.parent.mkdir(parents=True, exist_ok=True)
    cache_output.write_bytes(canonical_json(cache_boundary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
