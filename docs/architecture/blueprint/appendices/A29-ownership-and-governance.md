## Appendix A29 — Ownership and governance

### A29.1 Ownership layers

- central `mindclade/.github/CODEOWNERS`;
- `component.yaml` owner;
- package README owner;
- service/runbook on-call owner for production components;
- model/data/kernel qualification owner.

CI fails when a production component has no valid owner.

### A29.2 ADRs

Use `docs/adr/` for decisions that change:

- top-level boundaries;
- protocol compatibility;
- storage formats;
- training task, compiled step-program, and trainer ownership;
- logical state identity and migration;
- loss normalization and reduction scopes;
- parameter update ownership and phase transitions;
- snapshot epochs, checkpoint tiers, and durable recovery points;
- data progress, BatchReceipts, and RNG semantics;
- transformation-pass ordering, collectives, and executable-plan ownership;
- provider composition, compilation, and reproducibility levels;
- systems autotuning versus scientific HPO;
- kernel dispatch policy;
- security trust boundaries;
- release semantics;
- infrastructure repository ownership.

ADRs describe context, decision, alternatives, consequences, and migration. They do not duplicate implementation documentation.

### A29.3 Maturity labels

Recommended component maturity:

```text
experimental
incubating
supported
production
deprecated
retired
```

Maturity controls required tests, compatibility promises, owner expectations, and release eligibility.

### A29.4 Governance operating model

Governance converts architecture rules into accountable decisions and maintained evidence. It exists to preserve correctness, velocity, security, and scientific integrity—not to create review ceremony detached from risk.

```text
clear owner and decision right
→ review proportional to risk
→ immutable decision/evidence
→ implementation and verification
→ periodic reassessment or retirement
```

The default is local ownership within established contracts. Cross-domain or trust-boundary changes invoke broader review.

### A29.5 Roles and decision rights

| Role | Primary authority |
|---|---|
| component owner | API, implementation, tests, compatibility, maintenance |
| domain owner | domain contracts, package boundaries, cross-component consistency |
| architecture owner/group | top-level boundaries, dependency laws, system-of-record decisions |
| scientific owner | model/data/evaluation meaning and scientific qualification |
| security/safety owner | threat, policy, classification, biological governance, release restrictions |
| operations owner | SLOs, capacity, runbooks, rollout/recovery, on-call readiness |
| release owner | evidence completeness, artifact identity, promotion decision |
| incident commander | time-bounded incident coordination and recovery decision |

One person may hold several roles early in the company, but the decision rights remain distinct and are recorded.

### A29.6 Ownership contract

An owner is responsible for:

- maintained public contract and documentation;
- dependency and compatibility discipline;
- test/qualification evidence;
- security/data classification;
- operational health and runbooks if applicable;
- triage and vulnerability response;
- deprecation/retirement;
- approving or rejecting exceptions;
- succession when ownership changes.

Ownership is not merely CODEOWNERS review routing. An unmaintained component cannot remain `production` maturity.

### A29.7 Component catalog governance

`component.yaml` is validated against repository targets, packages, CODEOWNERS, protocols, artifacts, runbooks, and maturity. CI checks:

```text
unique component identity
valid owner/team
real build/test/release targets
language and dependency classification
handled data classes
runtime/deployment metadata
maturity-required evidence
public protocols/artifacts
on-call/runbook where required
```

Catalog drift fails presubmit or release according to severity. Generated developer-portal views derive from this source.

### A29.8 Architecture review triggers

Architecture review is required when a change:

- creates or removes a top-level domain/repository/service;
- changes a system of record or trust boundary;
- adds a cross-language/process contract;
- changes checkpoint/state/data identity or migration;
- changes job/attempt/fencing/transaction semantics;
- introduces a provider/control plane or custom orchestrator;
- changes public API compatibility;
- changes security classification, egress, tenant isolation, or biological safeguards;
- changes release/provenance/admission semantics;
- introduces significant irreversible operational cost.

Ordinary implementation inside an approved contract remains owner-reviewed without central approval.

### A29.9 ADR lifecycle

ADRs have states:

```text
PROPOSED → ACCEPTED → SUPERSEDED
       ↘ REJECTED
ACCEPTED → DEPRECATED → RETIRED
```

An ADR includes context, forces, decision, alternatives, consequences, migration, compatibility, security/safety implications, verification, owner, and review triggers. Accepted ADRs link implementation and tests. Superseding ADRs preserve historical rationale.

ADRs state decisions, not exhaustive tutorials. Domain design documents and package docs explain implementation details.

### A29.10 RFC and design-review process

Use an RFC/design document for substantial designs that need collaborative iteration before an ADR. The RFC identifies:

```text
problem and user/system outcomes
scope/non-goals
current constraints and source evidence
proposed contracts and flows
alternatives and tradeoffs
failure/security/operations
migration and rollout
qualification and definition of done
open questions and decision deadline
```

Comments resolve to decisions or explicit follow-up. Once settled, durable architectural decisions are captured in ADRs and implementation docs.

### A29.11 Exception governance

An architecture/policy exception contains:

- violated rule and rationale;
- exact path/component/environment scope;
- risk and impact;
- compensating controls;
- owner and approver;
- start and expiry;
- removal/migration plan;
- CI enforcement so scope cannot spread;
- review evidence.

Exceptions are machine-readable where possible and visible in component/release evidence. Expired exceptions fail CI. An exception is not a permanent alternative architecture.

#### Founder bootstrap exception

ADR-0008 defines one exceptional lifecycle for the public GitHub Free repository-level foundation:

```text
BLOCKED -> FOUNDER_BOOTSTRAPPED -> CONNECTED_QUALIFIED
```

`FounderBootstrapException/v1` is the machine authority and FBE-0001 is the only authorized record. It expires after 2026-09-30, is single-use and fail-closed, and grants Wave 1 source-only permission with `production_authority: false`. Before protected apply can exist on the `github-config` default branch, the same record permits one separately tracked, non-privileged pull-request publication of the exact workflow artifact by the declared actor. Its machine fields bind the target `main` branch, canonical SHA-256 content digest, actor, immutable receipt containing the actual merge SHA, PR URL and number, merge actor, and UTC time, and `UNPUBLISHED`/`PUBLISHED` state; no direct-main push, branch-protection waiver, independent-review claim, governance mutation, or production authority is allowed. Once published, the record authorizes only create, adopt, protect, set-non-secret-variable, and activate-foundation-identity through the exact `github-config/.github/workflows/protected-apply.yml` repository-local privileged workflow under A3.10. No workflow in `mindclade/.github/workflows/` receives this authority. Deletes, replacement, bypass, production promotion, secret export, force push, and self-extension are always denied.

Founder authorization is not independent review. Initial publication cannot assert that it is and does not waive the later no-bypass/two-approval protection. The exception cannot emit or stand in for connected GitHub, Buildkite, signer, recovery, or production evidence. Missing expiry, subject, protected revision, workflow identity, publication or consumption state, or immutable receipt fails closed. `CONNECTED_QUALIFIED` remains available only through the normal independent review and connected-evidence path.

### A29.12 Maturity model

Maturity gates are evidence-based:

| Maturity | Contract |
|---|---|
| experimental | no compatibility promise; isolated; owner and risk label required |
| incubating | intended direction; initial tests/docs; limited consumers |
| supported | documented API, compatibility window, conformance, responsive owner |
| production | release/security/operations/DR evidence, SLO/on-call where applicable |
| deprecated | supported migration and removal date; no new consumers |
| retired | no runtime consumers; archived evidence/tombstones only |

A component cannot self-declare maturity above its lowest required qualification. CI and release policy enforce allowed dependency directions by maturity—for example, production code may not depend on experimental code without an approved bounded exception.

### A29.13 API and compatibility governance

Every supported public/internal API has:

```text
owner
stability level
consumer inventory where possible
compatibility rules and baseline
versioning/deprecation policy
migration tooling and timeline
conformance tests
```

Breaking changes require impact analysis and coordinated rollout. “Internal” does not mean ungoverned when multiple teams/components depend on the contract.

### A29.14 Data, model, and scientific governance

Scientific governance assigns owners for:

- dataset source/license/quality/leakage/split decisions;
- reusable FeatureContracts/FeatureCatalog and biological semantics;
- fitted-transform state/fitting-scope and leakage policy where applicable;
- model configuration/state/capabilities;
- evaluation suites/statistics/thresholds;
- safety and intended-use policy;
- baseline updates and release decisions;
- research claim reproducibility.

Scientific decisions and platform decisions are reviewed by the relevant owners; neither silently overrides the other. For example, a systems owner cannot relax a scientific metric, and a researcher cannot bypass recovery/security requirements for a production run.

### A29.15 Security and privacy governance

Security reviews are risk-tiered and cover threat model, identity, authorization, classification, egress, supply chain, logging, retention, incident response, and biological safeguards. High-risk releases may require dual approval or independent review.

Policy owners maintain exception and incident registers, vulnerability SLAs, vendor risk, and public disclosure/release criteria. Security ownership does not remove responsibility from component owners.

### A29.16 Operational governance

Tiered production components declare:

```text
availability and recovery objectives
on-call ownership and escalation
SLOs and error-budget policy
capacity and dependency model
runbooks and dashboards
rollout/rollback and change windows
backup/restore and incident drills
```

A component cannot reach production maturity without an operator who can safely diagnose, stop, recover, and roll back it.

### A29.17 Change and release approval

Routine changes merge through CODEOWNERS and automated evidence. High-risk release promotion may require explicit approvals from release, scientific, security/safety, and operations owners. Approvals bind exact artifact/evidence digests and expire when inputs change.

Emergency changes are permitted through a documented path with stronger audit, narrowed scope, rollback plan, and mandatory post-change review.

### A29.18 Documentation governance

Each document has an owner, status, audience, source-of-truth relationship, and review trigger/date where appropriate. Generated reference is clearly distinguished from authored guidance. Broken links, stale component references, and contradictory architecture rules fail docs checks.

Runbooks are tested during drills. Model/data cards update with releases. A document that is no longer authoritative is marked superseded or removed rather than left ambiguous.

### A29.19 Risk register

Maintain a focused technical/scientific risk register with:

```text
risk and affected outcomes
likelihood/impact
leading indicators
owner
mitigation and contingency
accepted residual risk
review date
linked incidents/evidence
```

Risks include data/license, numerical correctness, checkpoint/recovery, provider lock-in, capacity/cost, security/biological misuse, key-person ownership, and dependency maturity. The register drives milestones and qualification, not generic status reporting.

### A29.20 Governance metrics

Measure health without rewarding bureaucracy:

- components without valid owners/docs/evidence;
- expired exceptions and deprecations;
- review and merge latency by risk class;
- incident recurrence and action closure;
- flaky/quarantined qualification age;
- unsupported dependencies or compatibility debt;
- runbook/restore drill freshness;
- security vulnerability/waiver age;
- research graduation/retirement throughput;
- release rollback/failure rate.

Metrics are used to fix system friction, not to incentivize superficial document counts.

### A29.21 Ownership transfer and succession

Ownership transfer includes current architecture, consumers, open risks, incidents, credentials/access, SLOs, runbooks, qualification state, release process, and planned changes. CODEOWNERS/catalog/on-call/docs update atomically where practical.

No production component remains with a departed or nonexistent owner. For Wave 0, the current founder accounts may provide temporary stewardship through 2026-09-30 for otherwise unstaffed source-owner teams. That assignment has an expiry and successor plan and never counts as the independent approval or review counterpart required by a protected gate.

### A29.22 Deprecation and retirement

Deprecation specifies replacement, migration guide/tooling, consumer inventory, warning mechanism, compatibility period, owner, and removal date. CI prevents new dependencies after a cutoff. Retirement verifies no runtime/build consumers, artifacts/retention handled, operational resources removed, and historical docs/ADRs preserved.

### A29.23 Governance qualification levels

| Level | Required evidence |
|---|---|
| `gov-g0` | owners, component catalog, CODEOWNERS, ADR/exception templates |
| `gov-g1` | maturity gates, architecture review triggers, compatibility/deprecation process |
| `gov-g2` | scientific/security/operations release decisions, risk register, runbook ownership |
| `gov-g3` | audited exceptions, ownership transfers, incident/restore drills, governance metrics |
| `gov-g4` | sustained evidence freshness, low orphan/debt rate, independent review readiness |

### A29.24 Capability-local qualification progression

**Milestone 0 — ownership foundation:** component schema, CODEOWNERS validation, owner directory, ADR/RFC/exception templates, and architecture-review triggers.

**Milestone 1 — evidence-linked maturity:** qualification-to-maturity checks, API compatibility inventory, docs ownership, deprecation tooling.

**Milestone 2 — production governance:** release approval matrix, security/scientific/operations reviews, SLO/on-call/runbook requirements, risk register.

**Milestone 3 — lifecycle and audit:** exception expiry, ownership succession, retirement, incident action tracking, and periodic independent review.

### A29.25 Definition of done

Governance is production-ready when:

1. every production component and scientific artifact class has an accountable valid owner;
2. local owners can move quickly inside explicit contracts while cross-boundary changes trigger proportional review;
3. ADRs, RFCs, exceptions, maturity, and deprecations have enforceable lifecycles;
4. maturity and release eligibility derive from evidence rather than labels;
5. scientific, security/safety, operations, and release decision rights are distinct and recorded;
6. exceptions are narrow, compensating, machine-visible, and expiring;
7. documentation, runbooks, ownership, and component metadata cannot drift silently;
8. ownership transfer and component retirement remove orphaned authority and access;
9. risk and incident actions drive measurable platform changes;
10. approvals bind immutable artifacts/evidence and cannot be reused after inputs change.

### A29.26 Final governance invariants

- every authority has an owner and every owner has explicit obligations;
- review depth follows risk and boundary impact;
- architecture decisions preserve history and verification;
- exceptions expire and never create shadow standards;
- production maturity requires scientific, technical, security, and operational evidence;
- governance optimizes trustworthy delivery, not document volume.
