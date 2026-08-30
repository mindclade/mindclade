## 13. Developer workflows

### 13.1 Bootstrap and daily commands

The documented workflow SHALL work on a clean supported Linux environment and devcontainer:

```text
just bootstrap          # install/verify pinned tools; no production credentials
just doctor             # validate toolchains, locks, generated drift, local services
just test-affected      # Bazel/native affected unit and contract tests
just test-domain <name> # focused domain suite
just integration-up     # ephemeral local DB/object/queue/fake identity
just integration-test   # cross-process vertical tests with synthetic fixtures
just generate           # all declared code generation followed by drift check
just qualify <target>   # target-specific evidence policy
just package <target>   # local unsigned artifact for inspection
```

These command outcomes are bound by the greenfield repository's `AGENTS.md` and `justfile`; a rename is an architecture-tooling change with compatibility documentation. There MUST be one documented, non-interactive path for each outcome. `just` is an ergonomic façade; CI invokes the underlying Bazel/native targets and records them.

### 13.2 Change workflows

**Contract change:** edit source; run lint/breaking; update canonical fixtures; generate; integrate current and previous version; update external projection/SDK if applicable; document migration/deprecation; merge atomically.

**Domain package change:** identify semantic owner and public surface; update component metadata; implement reference behavior/tests; add optimized or deployment integration only after the contract is stable; run affected and domain qualification.

**New deployable:** demonstrate independent process/trust/scaling boundary; create composition root, component metadata, threat model, SLO/runbook, deployment package, integration/E2E, build/release targets, and ADR. A library-to-service split includes data/API migration and rollback.

**Research graduation:** freeze hypothesis and reference; remove notebook-global state; move semantic code into the owning domain; add typed contract, fixtures, deterministic tests, dependency/ownership metadata, documentation, performance/safety evidence; keep the research artifact as provenance. Production never imports the research path.

**Kernel/provider graduation:** define the Mindclade-owned capability first; qualify parity/recovery/performance/hardware; record provenance/license; add dispatch only for the qualified envelope; preserve fallback and revocation.

**Agent/tool graduation:** author with MADK; declare schemas, permission, data, egress, side-effect, budget, timeout, sandbox, receipts, safety and approval; simulate/adversarially test; publish exact digests; enable by tenant/policy only after release approval.

### 13.3 Reviews and contribution policy

Every PR identifies affected component(s), change class, risk, user-visible compatibility, evidence, migration/rollback, and deferred follow-up. CODEOWNERS supplies domain review; protocol, security, biological-safety, database, and architecture reviewers are added by metadata-based policy. Self-approval is prohibited for production release policy, authorization, signing, tenant isolation, protected datasets, biological-safety controls, and destructive migrations.

Review verifies ownership and invariants before style. An accepted exception includes expiry and an executable guard. Large generated diffs are reviewed by source change, generator version, compatibility report, and drift proof. Concurrent/unrelated changes are preserved; mechanical rewrites are isolated when practical.

### 13.4 Documentation and examples

Each supported package has domain-specific README content: purpose/non-purpose, owner, public contracts, dependency/side-effect rules, tests, release unit, maturity, security/data classification, and migration. Deployables add SLO, dashboard, runbook, configuration, capacity, failure/recovery, and rollback. Architecture authors edit the smaller ordered files under `docs/architecture/blueprint/` and the machine-readable path/control manifests; `tools/docs/render_architecture_blueprint.py` generates the combined full blueprint and CI rejects source/render drift. Appendix A6 is generated from `repository-path-manifest.yaml`, never edited independently. Documentation references immutable versions/digests where operationally important. Examples compile/run in CI and use supported public APIs; no example imports internal or research packages.
