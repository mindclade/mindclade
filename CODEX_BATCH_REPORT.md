# Codex Batch Report: preflight-ci

## Summary

Implemented the fail-closed source-side Buildkite qualification authority for Wave 1 and future Wave 2 execution. The pipeline now binds source, protected definition, immutable launcher, Buildkite build, affected plan, cache boundary, canonical source checks, full Wave 1 tests, and cacheless reproducibility inputs before the existing detached required-check signature can qualify a result. No connected success, signature, cache, GCP IAM, or bucket state is asserted.

Commit: `8bc3340` (`ci: establish protected wave qualification authority`), created with configured commit signing.

## Changed files

- `.buildkite/README.md`
- `.buildkite/hooks/pre-command`
- `.buildkite/lib/trusted_context.py`
- `.buildkite/pipeline.py`
- `.buildkite/steps/nightly.py`
- `.buildkite/steps/presubmit.py`
- `.buildkite/steps/security.py`
- `justfile`
- `tools/BUILD.bazel`
- `tools/ci/affected_targets.py`
- `tools/ci/evidence_bundle.py`
- `tools/ci/pipeline_plan.py`
- `tools/ci/required_check.py`

## Tests and results

PASS:

- `python3.12 tools/ci/affected_targets.py --self-test`
- `python3.12 tools/ci/pipeline_plan.py --self-test`
- `python3.12 tools/ci/required_check.py --self-test`
- `python3.12 .buildkite/pipeline.py --check`
- `bash -n .buildkite/hooks/environment .buildkite/hooks/pre-command`
- `ruff check .buildkite tools/ci tools/qualification`
- `ruff format --check .buildkite tools/ci tools/qualification`
- `pyright .buildkite tools/ci tools/qualification`
- `buildifier -mode=check tools/BUILD.bazel`
- `just --fmt --check`
- `git diff --check`
- Bazel: `//:buildkite_pipeline_model_test`, `//tools:pipeline_plan_contract_test`, and `//tools:required_check_contract_test` (3/3 passed)
- Revision-bound `just ci-plan` dry run generated canonical pipeline, unsigned launcher, and disabled-cache inputs from the exact Git revision.

Not run / integration dependent:

- `just check` and repository ADR validation require the preflight-decisions shard's proposed ADR-0010/0011/0012 files and index entries.
- Connected Buildkite, GitHub, signer, GCP, and cache qualification were not run and are not inferred.
- Coordinator reports the separate integration baseline currently has 52 unknown `kernels/native/**` paths and one malformed YAML key owned by the kernel agent; this shard did not edit or mask those failures.
- Root and test BUILD files have pre-existing buildifier drift; only the changed `tools/BUILD.bazel` was formatted.

## Risks and follow-ups

- Future mappings emit `//:wave2s_tests` or `//:wave2p_tests` only for manifest-assigned Wave 2 paths. The coordinator must add each real root suite atomically with the first activated implementation before executing those mappings.
- The ADR registry intentionally accepts ADR-0010/0011/0012 only as exact `proposed` records with pending connected ratification and no acceptance/receipt fields. It must be integrated with the decisions shard in the same train.
- Connected governance evidence is now accepted only after the repository report proves exact commit-bound, cryptographically verified operational observations. The outer organization-compatible CI evidence still requires its independently qualified detached signature.
- The protected hook now rejects tracked dirty state. Untracked/unknown paths remain governed by the repository path validator.
- Cacheless canary execution uses a clean Bazel output root and disables remote/disk action cache reads and writes. Cold dependency acquisition remains a separately qualified mirror/closure concern.

## Connected setup requirements

- The immutable launcher must run outside the pull-request checkout and inject exact launcher identity, launcher revision, launcher digest, source revision, protected definition revision, cache namespace fields, and the canonical trusted-context digest.
- The pinned organization reusable workflow must include the new launcher/cache fields in trusted context before its revision can be rolled forward in this repository.
- The Buildkite qualified signer must sign only after verifying the unsigned launcher/cache inputs, exact plan/check digests, build ID, definition tree, source revision, and protected queue identity.
- Remote/public Bazel cache remains disabled. The explicit public target allowlist is empty. Future use requires separately reviewed source activation plus connected IAM qualification; writes additionally require write-activation evidence. This shard does not implement or claim GCP IAM, bucket, or cache state.
- Cache namespace identity is fixed to schema version, trust class, platform, architecture, toolchain digest, and build mode. Cache outputs are provenance metadata, never qualification evidence.

## Requested shared changes

- Integrate the preflight-decisions shard before running `--validate-adrs` or `just check`.
- Add real `//:wave2s_tests` and `//:wave2p_tests` root suites only when their implementation/test closures activate.
- Update the separately protected organization workflow/Buildkite launcher contract to emit the new trusted-context fields, then roll the pinned workflow revision through protected review.
- Resolve kernel manifest/YAML failures in the kernel-owned shard; do not suppress them in CI.

## Native dependency license closure follow-up

### Summary
- Commit `ccb85e9` replaces false no-third-party claims with deterministic, fail-closed enumeration of the resolved Cargo.lock, go.sum/go.mod, and pnpm-lock.yaml authorities.
- The policy now covers 21 Cargo registry packages, 16 Go checksum module/version identities, and 3 pnpm package identities. Workspace/root records remain explicit in the canonical inventory.
- Parser self-tests cover direct/transitive classification, stable ordering, integrity/hash propagation, go.mod-to-go.sum validation, and rejection of an identity missing from policy.

### Changed files
- `tools/licenses/scan_licenses.py`
- `tools/licenses/allowlist.yaml`
- `tools/BUILD.bazel`

### Tests/results
- PASS: `python3.12 tools/licenses/scan_licenses.py --self-test`.
- PASS: Ruff check and Ruff format check for the scanner.
- PASS: Pyright for the scanner, 0 errors and 0 warnings.
- PASS: `buildifier -mode=check tools/BUILD.bazel` and JSON parse of the policy authority.
- PASS: `bazel test //tools:license_scanner_contract_test`, 1/1.
- PASS: repository scan produced 93 records, zero violations, and complete coverage records for Cargo.lock, go.sum/go.mod, and pnpm-lock.yaml.
- PASS: a second repository scan was byte-identical to the first.
- EXPECTED INTEGRATION DIFFERENCE: regenerated NOTICE differs at line 54 because the newly enumerated native dependency closures are absent from the committed root NOTICE.

### Risks/follow-ups
- Go evidence conservatively enumerates every module/version checksum retained in go.sum, including historical versions, while verifying each go.mod requirement is represented. It does not claim the checksum set is the minimal selected module graph.
- License classifications are pinned repository policy assertions; this source-side shard did not perform connected upstream license-document retrieval or legal review.
- pnpm parsing is deliberately bound to the pinned v9.0 lockfile shape and fails closed on an authority format change.

### Connected setup requirements
- None added. This scanner emits source-side inventory only and claims no connected qualification or legal approval.

### Requested shared changes
- Regenerate and review the root `NOTICE` from the new inventory in an integration change; root NOTICE is outside this shard's allowed paths.
