# Codex Batch Report: Wave 2 preflight decisions

## Summary

- Added proposed, non-effective ADR-0010, ADR-0011, and ADR-0012 for JIT-01 through JIT-03.
- Added fail-closed PDB source-use and SQP-001 H100 approval schemas, pending templates, and policy ceremonies.
- Added Bazel/GCP remote-cache isolation, classification, lifecycle, logging, cacheless-canary, poison-recovery, and repository-boundary invariants.
- Extended the governed path authority from 2,488 to 2,497 paths and regenerated Appendix A6 and the combined blueprint.
- Preserved `production_authority: false`; no approval, ratification, connected control, PDB permission, GPU allocation, cost authorization, or receipt is claimed.

## Changed files

- Decisions: `docs/adr/0002-dependency-and-build-law.md`, `docs/adr/0010-*.md`, `docs/adr/0011-*.md`, `docs/adr/0012-*.md`, and `docs/adr/index.yaml`.
- Policies: six files under `docs/policies/` covering PDB source use and the SQP-001 H100 envelope.
- Blueprint sources/outputs: Section 11, Section 14, Appendix A9, generated Appendix A6, and the generated full blueprint.
- Governance: repository-path manifest, `tools/repo/path_policy.py`, repository-policy tests, and the deterministic drift golden.

## Tests and results

- PASS: 37 repository-policy unit tests.
- PASS: 11 blueprint unit tests.
- PASS: manifest semantic validation and deterministic path ordering.
- PASS: both JSON Schemas validate; both pending templates validate; false status-only approval is rejected.
- PASS: blueprint source validation and generated-render drift check.
- PASS: scoped Markdown lint for all eight changed hand-authored Markdown sources.
- PASS: yamllint for ADR index and both pending templates.
- PASS: `git diff --check`.
- INTEGRATION BLOCKED: current isolated ADR validator hardcodes exactly eight ADRs; the preflight-ci shard owns the proposed-ADR registry update.
- INTEGRATION BLOCKED: full path/docs verification observes the separate kernel agent's 52 unknown `kernels/native/**` paths, one malformed YAML key, and nine Markdown findings.
- INTEGRATION BLOCKED: this branch lacks the coordinator's `/docs/policies/** @mindclade/architecture` CODEOWNERS rule.

## External approvals still required

- Protected independent ratification of ADR-0010 by Control Plane, Architecture, and Security.
- Protected independent ratification of ADR-0011 by Scientific Leadership, Data Governance, and ML Systems.
- Protected independent ratification of ADR-0012 by Developer Experience, Control Plane, Architecture, Security, and Contract Governance.
- Legal, Data Governance, and Biological Safety approval of the exact PDB terms/snapshot/purpose/retention/export/safety subject.
- ML Systems and Finance/Operations approval of the exact H100 software, reservation, expiry, and maximum-cost subject.
- Connected signed receipts binding every approval to an immutable protected revision and decision/contract digest.

## Risks and follow-ups

- Rebase after the kernel agent lands ADR-0009 and manifest entries; recompute canonical count/digest, regenerate A6/full blueprint, and refresh the drift golden once.
- Integrate the preflight-ci ADR registry before running the final `--validate-adrs` gate.
- Integrate the coordinator CODEOWNERS rule without changing accurate architecture ownership.
- Let the coordinator decide the blueprint/reconciliation version after all preflight and kernel sources converge.
- Do not activate Wave 2S or Wave 2P merely because these proposal/template files exist; the contracts intentionally fail closed while pending.

## Requested shared changes

- Preflight CI: support ordered proposed ADRs with pending ratification and no `specificationAccepted` or receipt fields.
- Coordinator: own `/docs/policies/**` in CODEOWNERS, integrate kernel corrections, recompute manifest authority, and regenerate once.
- Kernel agent: correct its manifest, malformed YAML, and Markdown findings; this shard did not edit any `kernels/**` or ADR-0009 material.
