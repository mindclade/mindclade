## 17. Risks, technical debt, deferred work, and blockers

### 17.1 Principal risks and mitigations

| Risk | Exposure | Mitigation and trigger |
|---|---|---|
| Blueprint diverges from actual repository | implementation starts from incorrect paths/contracts | Wave 0 evidence inventory and drift report before domain changes |
| Polyglot build complexity | slow/fragile CI and duplicate dependencies | one native authority each, Bazel integration, affected graph, CPU/GPU profiles |
| Control/execution state divergence | duplicate work, false success, unrecoverable jobs | DB authority, transactional outbox, fenced observations, level reconciliation, chaos tests |
| Scientific semantics leak into providers | lock-in and inconsistent checkpoints/results | Mindclade contracts, reference path, adapter parity, provider revocation |
| Data/license/lineage error | unusable or unsafe releases | immutable raw zone, propagated policy, lineage closure, release approval/revocation |
| GPU optimization regression | silent numerical/scientific error | reference-first qualification, envelope dispatch, anomaly monitoring, fallback |
| Agent tool/prompt abuse | unauthorized or unsafe action | capability tokens, policy recheck, sandbox, approval, receipts, adversarial tests |
| Tenant leakage through caches/telemetry/artifacts | severe security/privacy incident | tenant-scoped keys/authorization, prohibited telemetry, cross-tenant tests |
| Feature semantic collision, stale reuse, or evaluation leakage | silent scientific corruption across models/runs | complete `FeatureKeyDigest`, immutable manifests, snapshot/cutoff identity, determinism violation quarantine, model-view separation, leakage guard and adversarial cache tests |
| Duplicate transform/feature planning stacks | graph behavior diverges and feature execution acquires separate partition/retry semantics | feature resolution lowers into the single `TransformGraph`; dependency/presubmit rules reject a second feature graph planner or executor |
| Fitted-transform leakage or mutable fitted state | train/evaluation contamination and irreproducible preprocessing | immutable `TransformStateArtifact`, `FitSemanticKey`, `FitReceipt`, fitting-scope policy, evaluation denial tests, no apply-time refit |
| Execution plan accidentally becomes semantic input | worker count/backend/fusion changes scientific output or cache identity | `TransformSemanticKey`/`TransformExecutionPlanDigest` separation, equivalence gates, execution-plan perturbation tests, fail closed on semantic divergence |
| Generated architecture/path drift | full tree or combined specification no longer reflects editable authorities | manifest-first editing, deterministic render, source inclusion checks, generated-diff presubmit and clean-checkout regeneration |
| Toolchain appears hermetic only with a warm cache | a clean worker reaches undeclared external archives or fails offline | package the complete Bzlmod/PyPI archive closure in the Nix/store registry or distdir and qualify with empty caches plus denied egress |
| Asserted operational evidence is mistaken for verified evidence | stale or fabricated PASS claims activate a protected phase | subject/revision-bound signed receipts, independently anchored trust roots, cryptographic verification, and fail-closed consumers; asserted observations remain non-qualifying |
| Over-engineering deferred capabilities | critical path delay and unused abstractions | activation-gated paths, no empty scaffolds, two-consumer rule |
| GCP coupling blocks on-prem | expensive rewrite | bounded environment ports and capability manifest, not pervasive abstraction |
| Qualification cost grows without bounds | developer bypass or release delay | risk-tiered/affected tests, reusable evidence, scheduled full matrix, cost signals |

### 17.2 Explicitly deferred work

| Capability | Why deferred | Activation evidence |
|---|---|---|
| public Go and Rust SDKs | no supported external consumer/compatibility budget | named consumer, API surface, release/support owner |
| reinforcement/post-training system | reward/rollout/safety lifecycle is not needed for first vertical | approved workload, policy/evaluation design, data and checkpoint contract |
| live elasticity | topology-changing restart is simpler and auditable | measured need and qualified membership/state semantics |
| Monarch orchestration | native Kubernetes/PyTorch roles cover initial topology | independent role-scaling failure/cost evidence |
| DeepSpeed/Megatron/TE/TorchAO/Lightning capability packages | no assumed gap before native reference/profile | measured capability gap and parity/recovery qualification plan |
| NVMe checkpoint/offload tier | operational complexity and failure modes | memory/I/O study plus integrity/recovery design |
| general autotuning and open-ended runtime plugin systems | speculative abstraction/dynamic-authority risk; closed-world `ImplementationRegistry` is already part of the transform execution design | first real bounded search/extension consumer, threat/compatibility model, and second implementation requiring runtime extensibility |
| extra cloud providers | GCP first; no lowest-common-denominator layer | funded provider deployment and conformance environment |
| arbitrary customer code/tools | materially stronger isolation and governance needed | threat model, isolated runtime, abuse/safety/compliance approval |
| service decomposition | modular monolith is simpler initially | measured scaling/trust/failure/release boundary and migration ADR |

Deferred means absent from production source and dependency graphs, not hidden behind empty interfaces. Design notes may live in ADR proposals or research without imports from production.

### 17.3 Genuine blockers requiring owner decisions

1. **Connected Wave 0 governance and independent review.** Canonical identity is fixed as `github.com/mindclade/mindclade`, and the greenfield repository plus five explicitly pinned operational source revisions are available. Connected exit remains blocked until Enterprise Cloud protections, exact required checks, a cryptographically verified signed baseline, and an independent reviewer are active. The inspected `application-source` ruleset names `.github/workflows/pull-request.yml` while the canonical tree names `.github/workflows/required-check.yml`; the operational authority MUST reconcile to the canonical path before activation. The same ruleset has no bypass actor, organization policy prohibits one, and the current dispatch contract offers no reviewed candidate-definition lane, so a change to the protected CI enforcement closure cannot satisfy its own required check. Developer Platform and Security MUST establish an externally governed two-stage roll-forward or an immutable organization-owned candidate validator, MUST evidence that Buildkite executes the pinned definition revision rather than an untrusted source checkout, and MUST implement a subject/revision-bound ECDSA receipt verifier backed by independently approved trust roots before asserted source or connected-control observations can qualify. Developer Platform MUST also package and deny-egress qualify the complete cold-cache Bzlmod/PyPI archive closure before the clean CPU CI gate can pass. Temporary founder stewardship expires on 2026-09-30 and supplies ownership continuity, not independent authorization.
2. **Data rights and biological-governance policy.** Legal, Data Governance, and Biological Safety owners MUST approve the source-use/license matrix, restricted-data classes, screening/escalation rules, retention/export controls, and release authority before Wave 2S acquires/publishes SQP-001 data or Wave 7 activates biological agents.
3. **Production residency and continuity policy.** The initial environments are development, staging, and production, with `us-central1` primary and `us-east4` recovery. Security/Privacy and Platform owners MUST still approve residency partitions, cross-region replication classes, and whether each protected dataset may enter the recovery region before production data infrastructure is approved.
4. **Scientific and launch hardware profile.** ML Systems and Finance/Operations MUST approve the SQP-001 one-H100/eight-H100 ceiling and exact driver/software envelope before Wave 2S, then name the reservation/capacity budget and representative distributed scale before Wave 5 qualification and SLO/cost gates.

These decisions do not block Wave 0 discovery. Items 2–4 must be resolved before their cited wave; item 3 does not reopen the fixed environment or region selection. No other architectural choice is intentionally delegated to implementers.

### 17.4 Technical debt policy

Technical debt is a versioned record with owner, affected invariant, present evidence, risk, user/operational impact, remediation, trigger, target wave/date, and expiry. It cannot be a permanent disabled test or broad dependency exception. Debt affecting correctness, tenant isolation, biological safety, artifact integrity, recovery, or release provenance blocks maturity promotion. Debt metrics include exception count/age, use of deprecated interfaces, flaky/quarantined tests, unqualified fallback frequency, unsupported artifact readers, manual runbook steps, and restore findings.
