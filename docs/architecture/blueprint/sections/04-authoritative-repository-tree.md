## 4. Authoritative repository tree

`docs/architecture/repository-path-manifest.yaml` is the machine-readable authority for file-level path completeness. Appendix A6 is its deterministic complete explicit render, while the compact tree in this section is authoritative only as an ownership/dependency summary. All describe target paths, not observed current paths. A path is created only in its activation wave with at least one real build target; generated and release-output files remain generator-owned and are never hand-authored.

```text
mindclade/
├── .buildkite/                # authoritative heavy CI planning and execution
├── .github/                   # repo-local GitHub metadata and thin workflow bridges only
├── .devcontainer/             # generated/tested local container profile
├── .vscode/                   # non-authoritative editor recommendations
├── MODULE.bazel               # repository integration graph
├── BUILD.bazel                # root policy/validation targets
├── flake.nix                  # pinned system-tool environment
├── justfile                   # discoverable developer command façade
├── protocols/                 # Protobuf, events, JSON Schema, compatibility baselines
│   ├── proto/mindclade/{common,artifact,job,dataset,feature,transform,experiment,model,training,inference,evaluation,agent,workflow,policy,admin}/v1/
│   ├── events/mindclade/{artifact,job,feature,transform,model,training,agent,workflow,audit}/v1/
│   ├── schemas/{artifact_manifest,evidence_manifest,release_manifest,configuration}/
│   ├── schemas/{dataset_manifest,feature_contract,feature_requirement_set,feature_manifest,feature_bundle,model_feature_view,checkpoint_manifest,model_manifest,evaluation_snapshot}/
│   ├── schemas/{transform_spec,transform_graph,transform_receipt,transform_execution_plan,transform_state_artifact,fit_receipt,lineage_map,training_recipe,training_phase_graph,executable_plan,kernel_qualification}/
│   ├── schemas/{agent_definition,tool_contract,agent_policy,workflow_definition,agent_run_manifest}/
│   ├── generated/{go,python,rust,typescript}/       # committed, generated
│   └── compatibility/{baselines,tests}/
├── libs/{python,rust,go,typescript}/                   # narrow cross-domain foundations
├── bio/{schemas,entities,formats,chemistry,sequences,structures,alignments,featurization,bindings}/
├── data/{contracts,connectors,ingestion,normalization,curation,validation,deduplication,leakage,splits,sampling,transforms,featurization,catalog}/
├── runtime/{distributed,dispatch,memory,precision,compilation,rng,extensions,diagnostics,testing}/
├── kernels/{api,dispatch,attention,pairformer,diffusion,normalization,qualification,benchmarks}/
├── models/{api,components,families,packaging,conversion,qualification}/
├── training/
│   ├── api/                         # task, phase, program, state, precision, parallelism contracts
│   ├── core/{trainer,state,optimization,data,callbacks}/
│   ├── execution/{ir,planning,passes,schedules,native,single_process}/
│   ├── providers/pytorch/
│   ├── checkpointing/               # domain-specific checkpoint contract and coordinator names
│   ├── tasks/{pretraining,supervised,contrastive,diffusion,flow,multitask,distillation}/
│   ├── {precision,evaluation,telemetry,resilience,qualification,recipes,cli}/
│   └── tests/
├── evaluation/{contracts,harness,metrics,suites,datasets,regression,reports,fixtures}/
├── inference/{contracts,pipeline,batching,sampling,compilation,postprocessing,confidence,ranking,artifacts,diagnostics}/
├── agents/
│   ├── contracts/                   # definitions, capabilities, decisions, state
│   ├── tools/{definitions,adapters,schemas,permissions,receipts,qualification}/
│   ├── policies/{authorization,biological_safety,budgets,approvals}/
│   ├── workflows/{definitions,planning,execution,compensation}/
│   ├── state/{events,snapshots,memory_references,lineage}/
│   ├── biological/{discovery,design,analysis,qualification}/
│   ├── runtime/{coordination,step_execution,approval_gates,budget_enforcement,replay}/
│   └── evaluation/{simulation,adversarial,regression}/
├── services/
│   ├── control_plane/{cmd/control-plane,internal,migrations,tests}/
│   ├── runtime_gateway/{cmd/runtime-gateway,internal,tests}/
│   └── artifact_proxy/{src,tests}/
├── workers/{ingestion_worker,feature_worker,training_worker,evaluation_worker,inference_worker,agent_worker}/
├── sdk/{python,typescript,conformance,examples}/
├── kits/{mcdk,mddk,mmdk,mtdk,medk,madk,assembly,conformance,cli}/
├── apps/{console,admin,docs}/
├── deploy/{components,local,integration,policies,tests}/
├── research/{notebooks,prototypes,ablations,studies,papers,fixtures}/
├── tests/{conformance,integration,end_to_end,distributed,failure_injection,performance,security}/
├── tools/{bazel,ci,codegen,dev,repo,release,qualification,migration,generators,licenses}/
├── docs/{architecture,adr,domains,standards,developer,security,runbooks,operations,model_cards,dataset_cards}/
├── examples/{sdk,data_connector,model_extension,training_smoke,inference,agent_workflow}/
└── third_party/{patches,licenses,notices,source_mirrors}/
```

`docs/architecture/repository-path-manifest.yaml` is the machine-readable authority for approved repository paths, owners, activation waves, maturity, generated/source status, and expected build/test targets. Appendix A6 is the deterministic full explicit rendering of that manifest and MUST show every approved target file; it is not a separately hand-maintained path authority. CI regenerates the A6 tree and fails on any source/render/actual-path mismatch. “Complete” means every approved namespace, composition root, contract source, repository-control file, generated target path, and required first-PR stub is named. It does not freeze unapproved future private implementation files. Adding a domain-specific private file inside an approved component requires updating the path manifest in the same change but does not require an ADR when ownership, dependency, contract, and release boundaries do not change.

Every deployable has exactly one composition root: `services/*/cmd/`, `workers/*/<language>/main.*`, or a Bazel-declared binary with equivalent domain-specific naming. Domain libraries MUST NOT start servers, create global clients, read ambient configuration, or own process shutdown.

### 4.1 Top-level ownership and maturity

| Path | Semantic owner | Initial maturity | Release behavior |
|---|---|---|---|
| `.buildkite/` | developer platform | internal trusted pipeline source | no product release; pipeline revisions are audited evidence |
| `.github/` | developer platform with security review | repo-local control metadata | no product release; only thin GitHub-native checks and Buildkite bridge |
| root workspace/toolchain files | developer platform | stable build contract | lock/toolchain changes qualify with affected release units |
| `protocols/` | contract governance | minimal kernel stable after Wave 1; domain packages stabilize with owning waves | schema packages and generated internal clients; no repo-wide version |
| `libs/` | developer platform | internal stable | language packages released only when externally consumed |
| `bio/` | computational biology | qualified core | source packages and versioned biological schemas |
| `data/` | data platform | qualified core | dataset manifests and worker libraries; datasets release independently |
| `runtime/`, `kernels/` | ML systems/performance | experimental → qualified | runtime package and per-envelope kernel bundles |
| `models/` | model architecture | experimental → released family | model package, bundle, and model release |
| `training/` | training systems | qualified internal | recipe/plan/checkpoint schemas and worker image |
| `evaluation/` | evaluation science | stable gates | suite packages and immutable evidence reports |
| `inference/` | inference systems | qualified | inference worker/gateway image and output schemas |
| `agents/` | agent platform with safety co-ownership | experimental → qualified | agent/tool/workflow/policy releases and MADK assembly |
| `services/` | platform control plane | production service | independently versioned images and migrations |
| `workers/` | owning execution team | production deployable | independently versioned images |
| `sdk/` | developer experience | supported public | SemVer Python and TypeScript packages |
| `kits/` | developer experience plus mapped domain | supported authoring façade | independently versioned assemblies; no domain truth |
| `apps/` | product engineering | production application | application bundles/images |
| `deploy/` | platform operations | release input | service-shipped charts/bases only |
| `research/` | research | non-production | no production release or inbound production dependency |
| `tests/`, `tools/`, `docs/`, `third_party/` | developer platform / relevant reviewers | internal | evidence, tooling, documentation, controlled vendoring |

### 4.2 Activation-gated paths

The following paths are `DEFERRED` and MUST NOT be pre-created. Their first PR requires a concrete consumer, owner, contract, tests, deletion condition, and ADR where the dependency graph changes.

| Conditional path | Activation criterion |
|---|---|
| `sdk/go/`, `sdk/rust/` | approved external consumer plus a funded compatibility and release commitment |
| `training/tasks/reinforcement/`, `training/rl/` | approved post-training workload with reward, rollout, policy-version, safety, and evaluation contracts |
| `training/orchestration/monarch/` | measured need for independently scaling distributed roles that native JobSet topology cannot meet |
| `training/resilience/live_elasticity/` | topology-changing restart evidence is insufficient and live membership change has a proven workload benefit |
| `training/offload/nvme/` | memory/cost study shows host offload is insufficient and data-loss/recovery behavior is qualified |
| non-PyTorch provider packages | a capability gap, adapter design, reference parity suite, and removal/rollback plan are approved |
| `training/autotune/` | a real systems-tuning consumer and bounded search-space contract exist |
| `protocols/schemas/autotune_record/`, `protocols/schemas/rollout_manifest/` | their corresponding systems-tuning or post-training capability is activated |
| `services/webhook_dispatcher/` | an external webhook product surface exists with delivery SLO and abuse controls |
| `services/event_dispatcher/` | outbox throughput or isolation evidence justifies extraction from the modular monolith |
| cloud-provider adapters beyond GCP | a funded deployment with two-provider conformance tests exists |

### 4.3 Development-kit mapping

| Kit | Canonical owners | Languages | Public output and release unit | Location and boundary |
|---|---|---|---|---|
| MCDK | `deploy/`, infrastructure contract owners | Go CLI, JSON Schema | `EnvironmentPlan` and deployment assembly | `kits/mcdk/`; may have a separately released binary, but live state remains outside this repo |
| MDDK | `bio/`, `data/` | Python, Rust-backed CLI | source, curation, dataset, and evidence assembly | `kits/mddk/`; invokes canonical validators and workers |
| MMDK | `models/`, `bio/`, `kernels/` | Python | model definition/package templates and model assembly | `kits/mmdk/`; no alternate model registry |
| MTDK | `training/`, `runtime/` | Python | recipe/plan/checkpoint developer workflow | `kits/mtdk/`; no alternate trainer lifecycle |
| MEDK | `evaluation/` | Python | suite, metric, snapshot, and evidence assembly | `kits/medk/`; no separate promotion policy |
| MADK | `agents/` with policy/safety owners | Python and TypeScript façade | agent/tool/workflow/policy assembly and simulator | `kits/madk/`; no alternate durable agent store |
| Mindclade SDKs | service/API owners and developer experience | Python, TypeScript | supported runtime client packages | `sdk/`; wraps external API, operations, artifacts, and agent sessions |

All kit assemblies conform to `protocols/schemas/development_kit_assembly/`. A kit MAY be published from a separate distribution repository only when that repository consumes a signed monorepo-built assembly by digest, contains no copied domain implementation, and passes the same conformance suite. Examples and templates are versioned with the kit but MUST pin contract ranges and immutable artifacts. Kit qualification includes clean-project generation, schema validation, supported-version compatibility, no hidden network access, and end-to-end execution against a local or integration profile.

### 4.4 Operational repository estate

One repo-local control directory and five separately protected repositories complete the source-to-production chain. They are not product packages and MUST NOT be imported by product code. Their complete trees, implementation contracts, transaction law, and qualification gates are in Appendix A3.8–A3.17 and Appendix A6.

| Canonical name | Form | Sole authority | Forbidden authority |
|---|---|---|---|
| `mindclade/.github/` | directory in this monorepo | repo-local issue/PR metadata, least-privilege GitHub workflow entrypoints, required-check bridge | shared organization workflows, organization settings, heavy builds, releases, deployment |
| `.github` | organization repository | shared community-health files, pinned reusable workflows/actions, organization profile | repository rulesets, cloud resources, product source, release promotion |
| `github-config` | separate governance repository | GitHub organization/repository/team/ruleset/environment/Actions/OIDC desired state | workflow implementation, application manifests, cloud or Kubernetes desired state |
| `bootstrap` | separate root-trust repository | minimum cloud state backend, identity federation roots, KMS/signing anchors, audit roots, break-glass and recovery | normal networks, clusters, databases, application deployment, routine promotion |
| `infrastructure-live` | separate infrastructure repository | normal cloud projects, networking, GKE, managed data services, registries, observability backends, CI/GitOps controller infrastructure | application source, Kubernetes workload release selection, artifact rebuild |
| `gitops` | separate deployment repository | cluster/environment Kubernetes desired state and digest-only application promotion | source compilation, cloud foundations, mutable image tags, business state |

The only permitted forward handoffs are signed source/build evidence from `mindclade` to deployment verification, bootstrap outputs referenced by `github-config` or `infrastructure-live`, infrastructure capability exports consumed by `gitops`, and signed release manifests consumed by `gitops`. No downstream repository writes back into source, rebuilds a subject, or copies domain configuration.
