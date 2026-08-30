## 16. Verification and acceptance matrix

### 16.1 Requirements-to-design traceability

| Requirement | Authoritative design | Detailed appendix | Required evidence / wave | Status now |
|---|---|---|---|---|
| repository taxonomy, naming, ownership, and migration | Sections 4–5, 15.1 | A5–A8, A29, A31 | drift baseline, catalog, CODEOWNERS, compatibility-aware move plan / W0 | `INCONCLUSIVE`; canonical identity and source inventory fixed, verified signed baseline pending |
| exhaustive monorepo stubs and operational repository trees | Sections 4.4, 12.1, 15.1, 15.6 | A3.8–A3.17, A6 | path/stub-manifest drift, repository plan/policy/failure/recovery suites / W0 and W5 | `PASS` at pinned-source inventory boundary; connected qualification pending |
| acyclic allowed/forbidden dependencies | Section 5 | A7, A33–A34 | Bazel/native edge policy / W0 | `TARGET` |
| trust/process/language boundaries | Sections 3, 9 | A3–A4, A18, A26 | threat and boundary conformance / W1+ | `TARGET` |
| source-of-truth contracts/codegen | Sections 6.1, 6.5, 6.8 | A9–A10, A19 | minimal-kernel breaking/drift/round-trip tests / W1; domain tests just in time | `TARGET` |
| public versus internal API | Sections 5–6 | A8, A10, A19 | visibility and Python SDK/API diff / W2P/W3; broader surface W4/W8 | `TARGET` |
| build/test/package/release compatibility | Section 11 | A9, A21–A23 | clean build, evidence/signature / W0–W1 | `TARGET` |
| extension points preserve invariants | Sections 4, 5, 7 | A7, A20, A32–A34 | activation ADR and provider/tool qualification | `TARGET` |
| clean-checkout/hermetic developer flow | Sections 11, 13 | A9, A30 | fresh CPU/GPU bootstrap / W0 | `INCONCLUSIVE`; Nix-pinned source checks pass, complete cold-cache external archive closure pending |
| identity/authn/authz/tenancy/audit | Sections 7.3, 9 | A18, A26, A28 | escalation, tenant, audit tests / W1/W4 | `TARGET` |
| state machines, reconciliation, idempotency, outbox | Sections 6.3, 7.4, 8.5 | A18, A24, A28 | chaos/duplicate/stale-fence / W1/W4 | `TARGET` |
| data ingestion/lineage/publication | Sections 7.5, 8.1, 15.3.1 | A11–A12 | exact PDB source-to-release E2E / W2S | `TARGET` |
| cross-model feature derivation/cache safety | Sections 2.4, 7.17, 8.9, 15.3–15.4 | A11–A14, A17–A18, A23, A39 | key-stability, cross-model reuse, determinism race, cache isolation/corruption, snapshot leakage, model-view separation / W2S–W4 | `TARGET` |
| feature/data transform correctness and replaceable execution | Sections 2.4, 7.18, 8.9, 15.3–15.5 | A12, A16–A18, A40 | `FeaturePlan`→`TransformGraph` lowering, typed-profile/schema tests, semantic-vs-execution identity goldens, fitted-state scope/leakage, compact lineage reconstruction, remote plan-reference protocol, cost-policy non-semantic tests, Python/Rust/backend parity / W2S–W5 | `TARGET` |
| model package/registry/release | Sections 7.6, 8.2, 15.3.1 | A13, A23 | SQP-001 bundle and local inference / W2S; release rollback W3 | `TARGET` |
| training tasks/planning/distribution/checkpoint/recovery | Sections 7.7, 8.3, 15.3.1 | A14, A24 | SQP-001 CPU/one-H100/checkpoint recovery / W2S; distributed W5 | `TARGET` |
| evaluation/evidence/promotion | Sections 7.8, 8.2, 15.3–15.4 | A16, A22–A23 | SQP-001 local report / W2S; promotion gate W3 | `TARGET` |
| online/batch inference | Sections 7.9, 8.4, 15.3–15.4 | A17–A18 | independent CPU platform slice / W2P; scientific parity W2S/W3; production W4 | `TARGET` |
| agent/MADK/tool/policy/sandbox | Sections 4.3, 7.10, 8.7 | A36 | adversarial/sandbox/replay E2E / W7 | `TARGET` |
| kernel reference/dispatch/fallback | Section 7.11 | A15 | numerical/hardware/performance matrix / W3/W6 | `TARGET` |
| artifact integrity/provenance/retention/DR | Sections 7.12, 10.4 | A23, A38 | corruption/restore/retention / W1/W8 | `TARGET` |
| observability/SLO/cost/incident | Sections 7.13, 10 | A25, A38 | SLO dashboards, alerts, game day / W4/W8 | `TARGET` |
| per-wave cost approval | Section 15 | A29 | versioned wave scope/cost envelope bound to accountable owner and Finance/Operations approval before paid activation; renewed on scope change or overrun / W0–W8 | `TARGET`; required independently for each wave |
| GCP/GKE, multicloud/on-prem boundary | Sections 7.14, 12 | A24, A37 | environment qualification / W5/W8 | `TARGET`; primary/recovery regions and three environments selected, quota/live qualification pending |
| CI/CD/SBOM/signing/provenance | Sections 7.15, 11 | A21–A23, A26 | trusted release verification / W1 | `TARGET` |
| developer kits MCDK–MADK | Sections 4.3, 14 | A36 | assembly/conformance per wave | `TARGET` |
| development workflow/documentation | Section 13 | A30 | fresh contributor and compiled docs / W0/W8 | `TARGET` |
| repository-path and architecture-source generation | Sections 4, 13, 15.1 | A6, A21, A30 | path-manifest→A6 exact render, blueprint-manifest→combined-document exact render, populated-path/source inclusion and drift-negative fixtures / W0 | `FOUNDER_BOOTSTRAPPED`; v3.4.3 manifests and governance schemas are source-complete, while connected qualification remains pending |
| one implementation sequence | Section 15 | appendix local milestones | wave exit evidence | `TARGET` |
| eight foundational ADRs and just-in-time decisions | Section 14 | A31.13 | eight reviewed files / W0; decision-specific evidence before dependent wave | `FOUNDER_BOOTSTRAPPED`; eight source-complete ADRs exist, independent connected ratification pending |
| independent initial scientific/platform slices | Sections 15.3–15.4 | A31.3–A31.5, A31.9, A31.12 | independent slice evidence plus one integration / W2S/W2P/W3 | `TARGET` |
| exact first scientific workload | Section 15.3.1 | A31.3, A31.11 | SQP-001 owner approval and frozen qualification report / W2S | `TARGET`; owner approval pending |
| narrow technology allowlist and measured intake | Sections 3.5, 15.6–15.7 | A14, A35.12 | active-dependency graph / W2–W5; bottleneck and JIT-06 / W6 | `TARGET` |
| current versus target claims | Sections 1.3, 16.3 | A38 | repository evidence ledger / W0 | `INCONCLUSIVE`; source evidence present, cryptographically verified baseline pending |

### 16.2 Production acceptance gates

| Gate | Pass condition | Evidence owner |
|---|---|---|
| Semantic ownership | each capability and contract has exactly one owner; no shadow registry/lifecycle | Architecture Council and domain owners |
| Dependency integrity | graph is acyclic; visibility/import/runtime boundary tests pass; exceptions unexpired | Developer Platform |
| Architecture source/render integrity | repository-path manifest, A6 render, blueprint source manifest, combined blueprint render, populated paths, and generated-file inventory agree byte-for-byte or by declared canonical render | Developer Platform/Architecture Council |
| Contract compatibility | current/previous supported versions interoperate; generated drift zero | Contract Governance |
| Durable correctness | duplicate/reordered delivery, crash, stale lease, and cancellation cannot double/lost-commit | Control Plane |
| Scientific/data correctness | parser/feature/model/metric goldens, lineage, leakage, uncertainty policies pass | Computational Biology/Data/Model/Evaluation |
| Transform/dataflow correctness | one generic `TransformGraph` substrate; typed transform profiles, semantic/execution identity separation, fitted-state scope, record/cardinality/order evidence, lineage reconstruction, backend equivalence, and remote plan-reference tests pass | Data Platform/Computational Biology/ML Systems |
| Numerical/distributed correctness | reference/update/gradient/checkpoint/recovery tests pass on every advertised envelope | Training/Runtime/Kernel |
| Security and tenancy | threat model, authorization, isolation, secret, image, sandbox, and audit tests have no critical issue | Security |
| Biological governance | approved use/safety policy and protected cases pass; escalation/revocation works | Safety and Scientific Governance |
| Artifact/supply chain | digest/provenance/SBOM/signature/retention/restore are verifiable | Artifact/Release/Security |
| Reliability/operations | launch SLO/capacity soak, alerts, runbooks, restore/failover, rollback/revocation game day pass | SRE/Operations |
| Product compatibility | SDK/app supported-version, accessibility, error and long-operation flows pass | Developer Experience/Product |
| Deployment | desired state references qualified immutable digests and conforms without rebuild/drift | Platform Operations |
| Operational repository estate | `.github`, `github-config`, `bootstrap`, `infrastructure-live`, and `gitops` satisfy disjoint authority, plan/apply identity, drift, rollback, and isolated recovery gates | Developer Platform/Security/Cloud Platform/Platform Operations |

Failure of any applicable gate blocks promotion. Waivers are not permitted for cross-tenant exposure, artifact integrity, uncommitted checkpoint resume, audit omission on privileged mutation, unsafe biological action, or critical supply-chain compromise. Other temporary waivers require subject digest, owner, compensating control, expiry, and visible release annotation.

### 16.3 Verification performed for this revision

| Verification | Result |
|---|---|
| Supplied blueprint v3.4.0 and `MONOREPO_TREE.md` preserved | `PASS` — byte-preserved provenance is bound to SHA-256 in the source manifest |
| Greenfield implementation repository, repository instructions, Git status, ADR targets, and build/source tree inspected | `INCONCLUSIVE` at worktree source boundary — all 199 populated files are governed, but the active `docs/adr/connected-ratification.v1.schema.json` source is intentionally missing; clean committed evidence remains a Wave 0 gate |
| Five operational repositories inspected | `PASS` at explicitly pinned immutable-source boundary — all five Git trees exactly match their Appendix A3 inventories; volatile sibling checkout state is excluded and live qualification is not inferred |
| Connected required-check and protected-definition handoff | `INCONCLUSIVE` — the desired ruleset references a non-canonical workflow path, exposes no policy-permitted definition roll-forward, and no immutable Buildkite launcher binding has been evidenced |
| Operational evidence authenticity | `INCONCLUSIVE` — caller-asserted source checks cannot qualify; the future receipt schema is subject/revision/trust-record bound, but no approved ECDSA verifier or independently anchored trust roots are implemented |
| Cold-cache dependency closure | `INCONCLUSIVE` — direct Nix Bazel and locked tools pass with the resolved cache, but the flake does not yet package every Bzlmod/PyPI external archive in an offline registry or distdir |
| Required 18-section structure and 40 appendices | `PASS` — main sections are exactly 1–18; appendices are exactly A1–A40 |
| Required system designs and vertical flows | `PASS` — 18 system contract cards and nine vertical flows are present, including cross-model feature derivation/cache and feature/data transform architecture |
| Contradiction/deferred-path/generated-code reconciliation | `PASS` at specification level — one wave sequence, activation-gated paths, committed Protobuf policy, and canonical terms are explicit |
| Markdown structure, source inclusion, and fence balance | `PASS` — the locked source validator checks the manifest schema, ordered inclusion, headings, line endings, whitespace, placeholders, relative links, and balanced fences |
| Heading and numbering integrity | `PASS` — section/appendix numbering is exact and the combined render has no duplicate generated or explicit anchors |
| Table of contents and internal anchors | `PASS` — the table of contents is generated from the ordered manifest and every internal anchor target resolves |
| Monorepo and operational repository trees | `FOUNDER_BOOTSTRAPPED` at source level — Appendix A6 is generated from the sole corrected path manifest: 2,488 explicit files with canonical path-set SHA-256 `18ecbf2fb4c9bfecdabbf66b061fc077af7c31ae6d01464bedb0e30d66e200a2`. The preserved v3.4.0 tree is provenance, not a second path authority. Populated-path evidence is recomputed by source validation; this row does not infer live protection or connected qualification |
| Stale planning markers and unsupported readiness claims | `PASS` — no actionable placeholders; readiness statements are conditional gates, not current-state claims |
| Referenced top-level path vocabulary | `PASS` at document level — paths resolve to Section 4/A6, activation-gated paths, local relative paths, or named external repositories; populated target status is checked separately by the path-manifest validator |
| Implementation or production readiness | `NOT CLAIMED` |
