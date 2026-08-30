## Appendix A35 — Technology basis

This blueprint is intentionally version-agnostic at the document level; exact versions must be pinned in repository lockfiles and upgraded through qualification. The architecture aligns with the current official capabilities and guidance of:

- Bazel Bzlmod: <https://bazel.build/external/overview>
- PyTorch distributed overview, DeviceMesh/DTensor, FSDP2, distributed checkpointing, and pipeline parallelism:
  - <https://docs.pytorch.org/tutorials/beginner/dist_overview.html>
  - <https://docs.pytorch.org/docs/stable/distributed.checkpoint.html>
  - <https://docs.pytorch.org/docs/stable/distributed.pipelining.html>
- TorchTitan native PyTorch training reference: <https://github.com/pytorch/torchtitan>
- Megatron-LM and Megatron Core: <https://github.com/NVIDIA/Megatron-LM>
- DeepSpeed ZeRO/offload and training APIs: <https://deepspeed.readthedocs.io/>
- PyTorch Lightning and Lightning Fabric: <https://lightning.ai/docs/fabric/stable/>
- TorchForge scalable RL/post-training: <https://github.com/meta-pytorch/torchforge>
- Monarch (TorchMonarch) distributed actor framework: <https://github.com/meta-pytorch/monarch>
- NVIDIA Transformer Engine: <https://github.com/NVIDIA/TransformerEngine>
- TorchAO quantization and sparsity: <https://github.com/pytorch/ao>
- TileLang kernel language: <https://github.com/tile-ai/tilelang>
- uv workspaces: <https://docs.astral.sh/uv/concepts/projects/workspaces/>
- Cargo workspaces: <https://doc.rust-lang.org/cargo/reference/workspaces.html>
- Go modules/workspaces: <https://go.dev/ref/mod>
- pnpm workspaces: <https://pnpm.io/workspaces>
- Buf linting and breaking-change detection: <https://buf.build/docs/breaking/>
- OpenTelemetry signals and context propagation:
  - <https://opentelemetry.io/docs/concepts/signals/>
  - <https://opentelemetry.io/docs/concepts/context-propagation/>
- Kueue and JobSet:
  - <https://kueue.sigs.k8s.io/docs/overview/>
  - <https://jobset.sigs.k8s.io/>
- Argo CD cluster bootstrapping and ApplicationSets:
  - <https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/>
  - <https://argo-cd.readthedocs.io/en/latest/user-guide/application-set/>
- Buildkite dynamic pipelines and monorepo practices:
  - <https://buildkite.com/docs/pipelines/configure/dynamic-pipelines>
  - <https://buildkite.com/docs/pipelines/best-practices/working-with-monorepos>
- Nix flakes and lockfiles:
  - <https://nixos.org/manual/nix/stable/command-ref/new-cli/nix3-flake-check.html>
  - <https://nixos.org/manual/nix/stable/command-ref/new-cli/nix3-flake-lock.html>
- Google Cloud architecture and platform guidance:
  - <https://cloud.google.com/architecture/framework>
  - <https://cloud.google.com/kubernetes-engine/docs/concepts/about-workload-identity-federation>
  - <https://cloud.google.com/storage/docs/introduction>
  - <https://cloud.google.com/sql/docs/postgres>
  - <https://cloud.google.com/pubsub/docs/overview>
- SLSA provenance: <https://slsa.dev/spec/v1.2/>

---

**Canonical repository name:** `mindclade` for the internal monorepo.
**Canonical Git remote:** `github.com/mindclade/mindclade`.
**Canonical Go module:** `github.com/mindclade/mindclade`.
**Recommended Python namespace:** `mindclade.*`.
**Recommended TypeScript scope:** `@mindclade/*`.
**Recommended Protobuf namespace:** `mindclade.<domain>.v1`.
**Recommended Kubernetes/API group:** `mindclade.dev`.

### A35.1 Technology selection policy

Technology choices implement Mindclade contracts; they do not define them. Selection is based on:

```text
semantic fit and maturity
correctness and recovery behavior
performance on real workloads
operability and failure modes
security and supply chain
license/support/community health
integration and exit cost
qualification burden
```

Popularity or benchmark headlines alone are insufficient. A selected technology receives a named owner and bounded responsibility.

### A35.2 Primary-source rule

Architecture and upgrade decisions use official documentation, source repositories, specifications, release notes, and upstream tests as primary evidence. Secondary commentary may help discover issues but does not override primary contracts.

For rapidly evolving training/compiler/provider systems, Mindclade records exact commit/version and verified capabilities rather than relying on project-level claims.

### A35.3 Version pinning

Exact versions and source revisions live in:

```text
uv.lock
Cargo.lock
go.mod/go.sum
pnpm-lock.yaml
MODULE.bazel/module lock state
flake.lock
OCI/base-image digests
provider/kernel/compiled-region manifests
```

The blueprint remains version-agnostic unless an architectural dependency requires a minimum capability. Production images install no packages at startup.

### A35.4 Stable and edge intake lanes

The **stable lane** contains versions that passed required compatibility, numerical, recovery, performance, security, and operations evidence.

The **edge lane** tracks candidate upstream revisions in isolated builds. It may generate comparison evidence but cannot publish production artifacts or become a hidden dependency.

Promotion is explicit:

```text
upstream candidate
→ compatibility/build intake
→ Mindclade adapter/contract mapping
→ domain qualification
→ composition and scale qualification
→ lock/image update
→ stable release evidence
```

### A35.5 Upgrade classification

Upgrades are classified:

| Class | Examples | Minimum response |
|---|---|---|
| patch/low-risk tool | bugfix with no relevant behavior change | affected tests, security/license review |
| runtime/compiler | Python/Rust/Go/Node/Bazel/CUDA/compiler | clean build, compatibility and performance evidence |
| protocol/schema tool | Buf/protoc/generator | generated diff and cross-language conformance |
| numerical provider | PyTorch, TE, Megatron, TileLang, TorchAO | forward/gradient/update/recovery/long-horizon as applicable |
| infrastructure controller | Kueue, JobSet, Argo, Kubernetes | API conversion, reconciliation, failure/rollout evidence |
| security-critical | identity, crypto, image/signing, base OS | threat/vulnerability, rollout and rollback evidence |

SemVer labels do not determine risk; observed contract impact does.

### A35.6 Upgrade workflow

```text
open automated/manual upgrade proposal
→ collect release/security/license notes
→ resolve native lock and Bazel/Nix state
→ build in edge lane
→ run affected and compatibility matrices
→ compare numerical/performance/recovery evidence
→ update adapters/migrations/docs
→ approve and promote exact lock/image changes
→ monitor and retain rollback artifacts
```

One proposal avoids unrelated broad upgrades unless a coordinated stack change is necessary and qualified together.

### A35.7 Upstream patch policy

Patches live under `third_party/patches/` or the appropriate dependency mechanism with:

- upstream/version applicability;
- rationale and owner;
- source/license review;
- tests proving need and behavior;
- link to upstream issue/PR where possible;
- removal condition;
- rebase/conflict behavior.

Mindclade does not silently fork critical dependencies through untracked source edits. Long-lived forks require an explicit ownership/support ADR.

### A35.8 Technology evaluation record

Before adopting a material system, record:

```text
required capabilities and non-goals
candidate versions
proof-of-concept scope
correctness/state/recovery fit
performance and resource evidence
security/license/supply chain
operational model and failure modes
integration boundary
migration/exit strategy
decision and review trigger
```

A proof of concept remains under research/edge until the record and qualification support promotion.

### A35.9 Build-system basis

Bazel remains the cross-language integration graph and Bzlmod dependency mechanism. Native ecosystem manifests remain authoritative for package resolution and local ergonomics. Nix pins tools/system dependencies. This separation is tested through lock reconciliation and clean-checkout builds rather than duplicating dependency truth manually.

A build technology change would require a replacement for visibility, affected graph, code generation, remote cache/execution, OCI/package composition, and provenance—not merely faster local compilation.

### A35.10 Protocol and schema basis

Protobuf/Buf remain the default for RPC/events/generated clients; JSON Schema remains the portable manifest/configuration contract. OpenAPI is derived at HTTP edges. Arrow-compatible structures and canonical scientific formats support high-volume data interchange.

Alternatives must preserve compatibility baselines, multi-language generation, unknown-field behavior, canonical identity, and conformance. Serialization preference alone is not sufficient reason to split authority.

### A35.11 Language/toolchain basis

Python remains the PyTorch/scientific semantics lane; Rust remains parsing/I/O/native safety/performance; Go remains control plane/controllers; TypeScript remains applications/SDK; TileLang/CUDA/C++ remain specialized acceleration.

Toolchain upgrades must maintain language interoperability, wheel/native ABI, generated code, Bazel/Nix integration, static analysis, and production image support. A new language requires a domain need, owner, build/security/operations support, and proof that existing lanes are unsuitable.

### A35.12 Training technology basis

Native PyTorch is the execution substrate because the Mindclade trainer contracts map to its model/autograd/distributed ecosystem. TorchTitan patterns and upstream components are intake sources. Megatron Core, DeepSpeed, Lightning/Fabric, TorchForge, Monarch, Transformer Engine, TorchAO, and TileLang remain capability providers under Appendix A14.

The initial active allowlist is narrower than the technology basis: native PyTorch, DeviceMesh/DTensor, FSDP2, DCP, NCCL, Kueue/JobSet, and PyTorch reference kernels. Every other named technology is `INTAKE` or `DEFERRED` until a measured gap and just-in-time ADR activate it. Inclusion in the technology basis means “understood and bounded,” not “planned dependency.”

Upstream configuration, state, process groups, and trainer lifecycles never become canonical. Every upgrade is qualified at the capability/composition level actually used.

### A35.13 Data and storage basis

Object storage is canonical for immutable large artifacts; relational storage is canonical for operational metadata/catalog; queues/workflow substrates deliver work; reconstructible caches accelerate. Rust/Arrow-compatible processing supports high-throughput biological data.

A new database, warehouse, lakehouse, feature store, or streaming system requires a concrete access/consistency/scale need and a clear source-of-truth relationship.

### A35.14 Kubernetes platform basis

Kubernetes remains the workload substrate, Kueue the batch quota/admission layer, JobSet or qualified distributed API the coordinated workload grouping, and Argo CD/ApplicationSet the GitOps reconciliation mechanism. Device plugins/operators provide accelerator integration.

Version upgrades require API/CRD conversion, rendered manifests, policy, rollout/rollback, admission, preemption, and distributed failure evidence. Controllers do not redefine Mindclade job or training state.

### A35.15 Observability basis

OpenTelemetry-compatible APIs/semantic conventions provide cross-language traces, metrics, logs, and context. Backends remain replaceable. Durable domain/run events, audit, and artifacts preserve correctness evidence independent of observability vendor.

Adopting vendor-specific instrumentation is acceptable behind adapters when it does not leak into domain APIs or create an unavailable correctness dependency.

### A35.16 Supply-chain basis

Build provenance follows a SLSA-aligned model appropriate to Mindclade's risk, with immutable source/build identity, SBOMs, signatures, attestations, protected builders, and verification at promotion/deployment/load boundaries.

The chosen signing, SBOM, vulnerability, and admission tools may evolve. Their predicates and trust policy remain stable Mindclade contracts.

### A35.17 Deprecation and end-of-life

Track upstream support and Mindclade support separately. A dependency approaching end-of-life triggers upgrade or replacement planning. End-of-life records include affected artifacts/environments, migration, qualification, fallback/rollback, and final removal.

Unsupported upstream does not automatically force an unsafe immediate upgrade; risk is assessed and mitigated under a time-bounded exception.

### A35.18 License and intellectual-property basis

Mindclade-authored monorepo source is proprietary and internal-use only under the root `LICENSE`. Internal SDKs, generated clients, models, and other distributions inherit an explicit proprietary policy unless a separately approved release states otherwise. A repository checkout or generated artifact grants no public redistribution right.

Every dependency, source mirror, model/checkpoint, dataset, and generated artifact has license/source terms and distribution constraints. Provider integration uses public supported APIs or independently authored adapters consistent with license obligations.

Third-party code is not copied into proprietary packages without review. Public release eligibility is distinct from internal-use eligibility.

### A35.19 Technology radar

Maintain a lightweight radar:

```text
adopt        stable qualified default
trial        bounded real-consumer pilot
assess       research/edge evidence only
hold         prohibited for new use or being removed
```

Entries name scope, version, owner, evidence, and review trigger. The radar communicates current support but does not replace lockfiles, ADRs, or qualification manifests.

### A35.20 Review cadence and triggers

Review the technology basis when:

- an upstream reaches end-of-life or security crisis;
- a required capability matures;
- a production incident reveals a platform defect;
- workload scale/topology changes materially;
- license/support terms change;
- a replacement demonstrates substantial measured benefit;
- portability/customer/regulatory requirements change.

Avoid calendar-driven churn solely to remain on the newest version. Security patches and critical fixes follow their own urgency policy.

### A35.21 Definition of done

Technology governance is production-ready when:

1. architecture contracts remain provider/tool independent and exact versions live in authoritative locks/manifests;
2. primary upstream sources and exact capabilities inform adoption/upgrade decisions;
3. stable and edge lanes prevent experimental revisions from leaking into production;
4. upgrades are risk-classified and produce compatibility, numerical, recovery, performance, security, and operational evidence as applicable;
5. patches/forks have owners, tests, upstream/removal plans, and license review;
6. every major technology has a bounded responsibility and exit strategy;
7. new languages/services/stores/control planes require real domain evidence;
8. supply-chain and license constraints apply to software, models, datasets, and generated artifacts;
9. end-of-life and revocation are tracked and recoverable;
10. the technology radar, ADRs, lockfiles, manifests, and qualification evidence agree.

### A35.22 Final technology invariants

- contracts choose technologies; technologies do not seize contract authority;
- exact versions are locked and production installs nothing at runtime;
- edge intake is isolated from stable release;
- capability composition is qualified, not inferred from project names;
- critical dependencies are patchable, replaceable, and attributable;
- novelty is adopted only when it improves a measured Mindclade outcome without weakening correctness, security, or operations.
