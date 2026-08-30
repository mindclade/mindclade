## 11. Build, test, CI/CD, and release architecture

### 11.1 Authority and clean-checkout reproducibility

Bazel is the cross-repository target, visibility, affected-test, and release-closure graph. It does not replace ecosystem authorities:

| Ecosystem | Dependency/tool authority | Required repository integration |
|---|---|---|
| Python | `pyproject.toml`, `uv.lock`, `.python-version` | pinned wheels/sdists, explicit CPU/GPU environments, Bazel targets from the same lock |
| Rust | root `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml` | one workspace, crate/Bazel dependency agreement, reproducible native builds |
| Go | one root `go.mod` and `go.sum` | internal packages in one module; generated clients and images in Bazel graph |
| TypeScript | root workspace and `pnpm-lock.yaml` | package boundaries, browser/server conditions, reproducible builds |
| Protobuf | `buf.yaml`, module/dependency lock, `buf.gen.yaml` | lint, breaking, generation, cross-language conformance |
| System tools | `flake.nix`, `flake.lock`, pinned Bazel version/module | bootstrap, toolchains, system libraries, CI image inputs |

A clean-checkout release build MUST run with network disabled after declared dependency fetch/mirroring, a sanitized environment, fixed locale/timezone, controlled timestamps, no home-directory inputs, and declared hardware/toolchain. Build provenance records source revision, dirty-state prohibition, lock/toolchain digests, Bazel target, builder identity, parameters, dependencies, and outputs. Reproducible byte identity is required where ecosystem formats permit it; otherwise semantic reproducibility and explained nondeterminism are recorded.

Remote cache is acceleration only. Bazel HTTP cache can expose action-cache records, CAS outputs, and captured stdout/stderr; therefore public-readable and private-internal cache data MUST use separate GCP buckets or equivalently IAM- and cryptographically isolated namespaces. Public publication is denied unless the target is on the explicit public-output allowlist, and cache writes are denied until the builder identity, target class, and platform envelope are qualified. Cache keys bind cache-schema version, trust class, platform, architecture, toolchain closure, and build mode. A classification change revokes access to the prior namespace and rotates the namespace; it never relabels existing objects in place. Noncurrent versions receive a short lifecycle, and access logs are exported to a separate destination that cache writers cannot alter.

Trusted qualification runs a periodic cacheless canary. Suspected poisoning revokes or write-denies the affected namespace, performs a clean cacheless rebuild, and compares output digests before reads resume. Release provenance records cache consultation and the compatible cache namespace, but a cache hit is never evidence and cannot replace subject verification, SBOM, qualification, signature, or reproducibility proof.

The monorepo owns cache policy, schemas, allowlists, key contracts, canary behavior, and poison-recovery tests. `bootstrap` owns foundational GCP identities and trust. `infrastructure-live` owns GCP buckets, IAM, access-log destinations, and lifecycle desired state. No policy source in this repository proves that connected resources or controls exist.

### 11.2 Test and qualification ladder

| Gate | Trigger | Minimum evidence |
|---|---|---|
| Fast presubmit | every change | formatting, lint, typing, unit tests, ownership/dependency policy, secret/license checks |
| Contract | protocol/schema/API change | breaking diff, generation drift, round trip/goldens, supported-version tests |
| Scientific | bio/data/feature/model/eval change | golden/property/fuzz tests, feature-key determinism and parity, lineage/leakage, and numerical/scientific assertions |
| GPU correctness | kernel/model/training/inference GPU change | reference parity, gradients, determinism envelope, sanitizer/error cases |
| Distributed | execution/checkpoint/scheduler change | multi-rank/node correctness, failure injection, preemption, restart/reshard |
| Integration | service/worker/storage/queue change | real transaction/outbox, duplicate delivery, auth/tenant, artifact finalize |
| End to end | release candidate and critical vertical | source-to-dataset; train-to-model; inference; agent; promotion/rollback |
| Performance | optimized capability or SLO-sensitive change | statistically valid benchmark against pinned baseline; no correctness waiver |
| Security/safety | trust boundary or protected release | threat tests, tenant isolation, dependency/image scan, biological policy cases |
| Soak/recovery | supported distributed/production release | long horizon, leak detection, kill/restart, restore, error-budget signal validation |

Flaky tests cannot be silently rerun to green. Quarantine requires an owner, issue, impact, expiry, and exclusion from a release gate only with explicit risk approval. Test fixtures use synthetic or approved de-identified/minimized data. GPU tests declare hardware/software envelopes; a pass on one accelerator does not qualify another.

### 11.3 CI trust tiers

1. **Untrusted PR:** no production secrets, no signing, restricted network, read-only source, ephemeral credentials, and attacker-controlled code assumptions.
2. **Trusted merge:** protected revision, dependency fetch through approved mirrors, normal integration tests, no production apply.
3. **Qualified build:** isolated builder, pinned inputs, SBOM/provenance/signature, protected artifact write, risk-specific qualification.
4. **Promotion:** separate identity verifies evidence and changes only environment desired-state references.
5. **Emergency rollback/revocation:** restricted command path with dual authorization where policy requires and complete audit.

Buildkite is the primary scalable pipeline; GitHub workflows handle repository-native metadata and lightweight gates. If both exist, there is one required-check aggregator and one evidence schema. Neither platform becomes the contract authority. A pipeline definition is generated/validated as code, pins images/plugins, and emits step-level provenance.

### 11.4 Release evidence and promotion

A `ReleaseManifest` contains subject type/digest, semantic version where applicable, source/build provenance, SBOM and scan results, contract compatibility, qualification policy/digest, evidence digests, environment/hardware constraints, owner/approver, signature, creation/expiry where relevant, and rollback/revocation references.

Release units are independent:

- service and worker images use image digest and component version;
- Python/TypeScript SDKs use SemVer package versions;
- Protobuf/JSON Schema use package/schema versions and immutable descriptors;
- dataset/model/agent/tool/workflow/policy/kit releases use domain versions plus artifact digest;
- checkpoints use run/generation identity plus digest and are not product releases by default;
- kernels use operation version plus hardware/software qualification envelope;
- deployment packages use chart/bundle version and digest.

There is no repository-wide version. Coordinated releases use a manifest that pins multiple independent digests without assigning them a synthetic shared version.

### 11.5 Supply-chain controls

Third-party sources are pinned by digest and license metadata. Builds produce SPDX or CycloneDX SBOMs and in-toto/SLSA-compatible provenance. Release artifacts are signed using short-lived federated builder identity and KMS-backed keys or keyless identity with transparency evidence as policy permits. Deployment verifies signature, provenance builder, source repository, qualification policy, vulnerability/license status, and revocation. Exceptions are scoped to a subject digest and expiry; wildcard or mutable-tag exceptions are prohibited.

Critical vulnerability response identifies affected release closures from SBOMs, blocks new promotion, publishes revocation, rebuilds from patched locks, requalifies, and rolls forward or back. Re-signing unchanged vulnerable bytes is prohibited.
