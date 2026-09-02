## Appendix A6 — Authoritative repository tree

The tree below is the complete generated human rendering of `docs/architecture/repository-path-manifest.yaml`, governed by Section 4. The machine-readable manifest is the path authority; this explicit A6 render is normatively equivalent and CI MUST prove byte-for-structure agreement with it. It is not evidence of the current repository. Create a directory only when its implementation wave activates it and it has an owner and at least one real target; the tree is a boundary map, not permission to fill the repository with empty stubs. Paths listed as activation-gated in Section 4.2 and Appendix A6.4 are target-only until activated.

### A6.0 Completeness and activation-stub contract

The machine-readable path manifest is exhaustive for every **approved target file path** in the current architecture: root metadata, contract sources, generated-source outputs, package/component sources, composition roots, tests, fixtures, documentation, operational tooling, and first-PR activation surfaces. A6 is generated from it and therefore shows the same full set explicitly. It does not claim to predict files that have not yet been approved; a future private implementation file is added to the path manifest in the same change that introduces it. Generated authoritative tree renders MUST NOT use brace expansion, ellipses, wildcard path tokens, or an unexpanded leaf directory as a substitute for concrete files. Parent directories may naturally appear as hierarchy, but every approved physical leaf has explicit file children. Activation-gated paths remain target-only until their owning wave creates the real target, and generated files remain generator-owned even though their deterministic target paths are listed here.

#### A6.0.1 Repository path manifest authority

`docs/architecture/repository-path-manifest.yaml` is validated by `repository-path-manifest.schema.json`. Each file entry records enough information to generate and govern the tree without using prose as a second database:

```yaml
path: data/transforms/planning/execution_plan.py
kind: source
owner: data-platform
component: data-transforms
status: target            # target | active | generated | deferred | retired
activation_wave: 2S
source_authority: hand-authored
build_targets:
  - //data/transforms:planning
test_targets:
  - //data/transforms/tests:planning
public_surface: false
```

Required fields include canonical path, path kind, semantic/component owner, activation status/wave, generated/source authority, component identity, build/test targets when active, and an approved exception or activation criterion when applicable. Directory hierarchy is derived from file entries rather than stored as empty nodes.

Generation is deterministic:

```text
repository-path-manifest.yaml
    ↓ schema + ownership/target validation
normalized path set in deterministic authority/display order
    ↓ render_repository_tree.py
Appendix A6 explicit tree
    ↓ verify_repository_path_manifest.py
actual populated paths + component.yaml + Bazel graph
```

A pull request that adds, removes, moves, activates, retires, or changes ownership of a file updates the path manifest first. CI fails when a populated file is absent from the manifest, a target-only path exists prematurely, an active file lacks its required target/owner metadata, or the generated A6 render differs. The full tree remains reviewable while eliminating dual hand-maintained authority.

When a namespace activates, its first PR uses exactly one applicable stub profile and replaces the profile's domain tokens with the concrete namespace already named in the tree:

| Stub profile | Exact minimum files | Required proof |
|---|---|---|
| governed component | `component.yaml`, `BUILD.bazel`, `README.md` | owner/maturity/dependencies/release metadata validate; at least one real target exists |
| Python library | `pyproject.toml` at release root; package `__init__.py`, `py.typed`, domain-named implementation module, `tests/test_<domain_contract>.py`, `BUILD.bazel`, `component.yaml`, `README.md` | import, type, unit, dependency-law, wheel test |
| Rust crate | `Cargo.toml`, `src/lib.rs`, domain-named module, `tests/<domain>_contract.rs`, `BUILD.bazel`, `component.yaml`, `README.md` | cargo/Bazel parity, clippy, unit/conformance, license audit |
| Go package/deployable | domain-named `.go` files, domain-named `_test.go`, `BUILD.bazel`, `component.yaml`, `README.md`; a deployable also has `cmd/<binary>/main.go` | Go/Bazel parity, race/unit/contract tests, composition-root check |
| TypeScript package/application | `package.json`, `src/index.ts` only for a public package barrel, domain-named source, `tests/<domain>.test.ts`, `BUILD.bazel`, `component.yaml`, `README.md` | typecheck, unit/contract, bundle and dependency-law tests |
| Protobuf/event package | domain-named `.proto`, `buf.lock` only at the protocol workspace boundary, `BUILD.bazel`, compatibility baseline, `README.md` | lint, generation drift, breaking-change and cross-language round trip |
| JSON Schema package | domain-named `.schema.json`, positive/negative fixtures, `BUILD.bazel`, compatibility baseline, `README.md` | metaschema, identifier, compatibility and generated-validator tests |
| service/worker image | domain-specific composition root shown in the tree, `component.yaml`, `BUILD.bazel`, `README.md`, contract/failure tests, image target, deployment descriptor reference | clean image build, cancellation/fencing, health, SBOM/provenance and local integration |
| deployment package | `release-package.yaml`, `values.schema.json`, domain-named base/templates, policy fixtures, `BUILD.bazel`, `component.yaml`, `README.md` | deterministic render, schema/policy, upgrade/rollback and digest-pin tests |
| documentation index | domain-named Markdown plus nearest `README.md` index and link-test target | compiled examples, links, ownership and review-date checks |

`<domain_contract>` in the profile is a generator variable, not a repository filename. The generator MUST materialize a concrete name such as `test_artifact_reference.py`; CI rejects literal angle-bracket names, `utils.*`, generic `service.*`, generic `manager.*`, or a generic `api.*` outside an explicitly approved public API boundary. `tools/generators/stub_catalog.yaml` maps every generator profile to these required files. `docs/architecture/repository-path-manifest.yaml` is the machine-readable path/status/owner/wave/build-target authority; `tools/repo/render_repository_tree.py` deterministically renders A6 from it and `tools/repo/verify_repository_path_manifest.py` compares it with actual populated paths and component metadata. All are Wave 0 targets and are drift-checked.

<!-- BEGIN GENERATED: repository-path-manifest -->
```text
mindclade/
├── .buildkite/
│   ├── pipeline.yml
│   ├── pipeline.py
│   ├── hooks/
│   │   ├── environment
│   │   └── pre-command
│   ├── lib/
│   │   ├── affected_targets.py
│   │   ├── annotations.py
│   │   ├── pipeline_model.py
│   │   └── trusted_context.py
│   ├── steps/
│   │   ├── presubmit.py
│   │   ├── gpu.py
│   │   ├── nightly.py
│   │   ├── release.py
│   │   └── security.py
│   └── README.md
├── .github/
│   ├── actions/
│   │   ├── setup-repository/
│   │   │   ├── action.yml
│   │   │   └── README.md
│   │   └── validate-metadata/
│   │       ├── action.yml
│   │       └── README.md
│   ├── workflows/
│   │   ├── pr-metadata.yml
│   │   ├── buildkite-dispatch.yml
│   │   ├── required-check.yml
│   │   ├── docs.yml
│   │   ├── dependency-review.yml
│   │   ├── codeql.yml
│   │   ├── scorecard.yml
│   │   └── mirror-verification.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug.yml
│   │   ├── architecture-change.yml
│   │   ├── scientific-correctness.yml
│   │   ├── security-control-gap.yml
│   │   └── config.yml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── labeler.yml
│   ├── pull_request_template.md
│   └── actionlint.yaml
├── .devcontainer/
│   ├── devcontainer.json
│   ├── Containerfile
│   └── README.md
├── .vscode/
│   ├── extensions.json
│   ├── settings.json
│   └── tasks.json
├── MODULE.bazel
├── MODULE.bazel.lock
├── BUILD.bazel
├── .bazelrc
├── .bazelversion
├── .bazelignore
├── flake.nix
├── flake.lock
├── pyproject.toml
├── uv.lock
├── .python-version
├── Cargo.toml
├── Cargo.lock
├── rust-toolchain.toml
├── go.mod
├── go.sum
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── buf.yaml
├── buf.gen.yaml
├── justfile
├── .editorconfig
├── .gitattributes
├── .gitignore
├── .pre-commit-config.yaml
├── .markdownlint-cli2.yaml
├── .yamllint.yaml
├── component.yaml
├── AGENTS.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── LICENSE
├── NOTICE
├── README.md
├── protocols/
│   ├── proto/
│   │   └── mindclade/
│   │       ├── common/
│   │       │   └── v1/
│   │       │       ├── identifiers.proto
│   │       │       ├── resource_reference.proto
│   │       │       ├── command_context.proto
│   │       │       ├── event_envelope.proto
│   │       │       ├── error_detail.proto
│   │       │       └── pagination.proto
│   │       ├── artifact/
│   │       │   └── v1/
│   │       │       ├── artifact_reference.proto
│   │       │       ├── evidence_reference.proto
│   │       │       └── artifact_commands.proto
│   │       ├── job/
│   │       │   └── v1/
│   │       │       ├── operation.proto
│   │       │       ├── job.proto
│   │       │       ├── run.proto
│   │       │       ├── attempt.proto
│   │       │       ├── lease_fencing.proto
│   │       │       └── job_commands.proto
│   │       ├── dataset/
│   │       │   └── v1/
│   │       │       ├── dataset.proto
│   │       │       ├── dataset_release.proto
│   │       │       └── dataset_commands.proto
│   │       ├── feature/
│   │       │   └── v1/
│   │       │       ├── feature_materialization.proto
│   │       │       └── feature_commands.proto
│   │       ├── transform/
│   │       │   └── v1/
│   │       │       ├── transform_execution.proto
│   │       │       └── transform_commands.proto
│   │       ├── experiment/
│   │       │   └── v1/
│   │       │       ├── experiment.proto
│   │       │       ├── study.proto
│   │       │       ├── trial.proto
│   │       │       └── experiment_commands.proto
│   │       ├── model/
│   │       │   └── v1/
│   │       │       ├── model.proto
│   │       │       ├── model_release.proto
│   │       │       └── model_commands.proto
│   │       ├── training/
│   │       │   └── v1/
│   │       │       ├── training_run.proto
│   │       │       ├── training_progress.proto
│   │       │       ├── checkpoint.proto
│   │       │       └── training_commands.proto
│   │       ├── inference/
│   │       │   └── v1/
│   │       │       ├── inference_request.proto
│   │       │       ├── inference_result.proto
│   │       │       └── inference_stream.proto
│   │       ├── evaluation/
│   │       │   └── v1/
│   │       │       ├── evaluation_run.proto
│   │       │       ├── evaluation_result.proto
│   │       │       └── promotion_decision.proto
│   │       ├── agent/
│   │       │   └── v1/
│   │       │       ├── agent_definition.proto
│   │       │       ├── agent_run.proto
│   │       │       ├── agent_step.proto
│   │       │       └── tool_receipt.proto
│   │       ├── workflow/
│   │       │   └── v1/
│   │       │       ├── workflow_definition.proto
│   │       │       ├── workflow_run.proto
│   │       │       └── approval.proto
│   │       ├── policy/
│   │       │   └── v1/
│   │       │       ├── policy_reference.proto
│   │       │       ├── authorization_decision.proto
│   │       │       └── use_policy.proto
│   │       ├── admin/
│   │       │   └── v1/
│   │       │       ├── tenant.proto
│   │       │       ├── project.proto
│   │       │       └── audit_query.proto
│   │       ├── internal/
│   │       │   ├── artifact/
│   │       │   │   └── v1/
│   │       │   │       └── artifact_service.proto
│   │       │   ├── job/
│   │       │   │   └── v1/
│   │       │   │       └── job_service.proto
│   │       │   ├── dataset/
│   │       │   │   └── v1/
│   │       │   │       └── dataset_service.proto
│   │       │   ├── training/
│   │       │   │   └── v1/
│   │       │   │       └── training_service.proto
│   │       │   ├── model/
│   │       │   │   └── v1/
│   │       │   │       └── model_service.proto
│   │       │   ├── inference/
│   │       │   │   └── v1/
│   │       │   │       └── inference_service.proto
│   │       │   ├── evaluation/
│   │       │   │   └── v1/
│   │       │   │       └── evaluation_service.proto
│   │       │   ├── agent/
│   │       │   │   └── v1/
│   │       │   │       └── agent_service.proto
│   │       │   ├── workflow/
│   │       │   │   └── v1/
│   │       │   │       └── workflow_service.proto
│   │       │   ├── policy/
│   │       │   │   └── v1/
│   │       │   │       └── policy_service.proto
│   │       │   ├── admin/
│   │       │   │   └── v1/
│   │       │   │       └── admin_service.proto
│   │       │   └── experiment/
│   │       │       └── v1/
│   │       │           └── experiment_service.proto
│   │       └── api/
│   │           └── v1/
│   │               └── mindclade_service.proto
│   ├── events/
│   │   ├── mindclade/
│   │   │   ├── artifact/
│   │   │   │   └── v1/
│   │   │   │       ├── artifact_committed.proto
│   │   │   │       └── artifact_quarantined.proto
│   │   │   ├── job/
│   │   │   │   └── v1/
│   │   │   │       ├── job_requested.proto
│   │   │   │       ├── attempt_leased.proto
│   │   │   │       └── attempt_completed.proto
│   │   │   ├── feature/
│   │   │   │   └── v1/
│   │   │   │       └── feature_materialization_completed.proto
│   │   │   ├── transform/
│   │   │   │   └── v1/
│   │   │   │       └── transform_execution_completed.proto
│   │   │   ├── model/
│   │   │   │   └── v1/
│   │   │   │       ├── model_registered.proto
│   │   │   │       ├── model_promoted.proto
│   │   │   │       ├── model_revoked.proto
│   │   │   │       └── model_release_registered.proto
│   │   │   ├── training/
│   │   │   │   └── v1/
│   │   │   │       ├── training_started.proto
│   │   │   │       ├── progress_committed.proto
│   │   │   │       ├── checkpoint_committed.proto
│   │   │   │       ├── training_completed.proto
│   │   │   │       ├── training_run_created.proto
│   │   │   │       └── training_cancellation_requested.proto
│   │   │   ├── agent/
│   │   │   │   └── v1/
│   │   │   │       ├── agent_step_dispatched.proto
│   │   │   │       ├── tool_receipt_committed.proto
│   │   │   │       ├── agent_run_completed.proto
│   │   │   │       ├── agent_cancellation_requested.proto
│   │   │   │       ├── agent_definition_created.proto
│   │   │   │       ├── agent_definition_updated.proto
│   │   │   │       ├── agent_run_started.proto
│   │   │   │       └── agent_step_committed.proto
│   │   │   ├── workflow/
│   │   │   │   └── v1/
│   │   │   │       ├── workflow_transitioned.proto
│   │   │   │       ├── approval_recorded.proto
│   │   │   │       ├── approval_consumed.proto
│   │   │   │       ├── approval_requested.proto
│   │   │   │       ├── workflow_cancellation_requested.proto
│   │   │   │       ├── workflow_definition_created.proto
│   │   │   │       ├── workflow_definition_updated.proto
│   │   │   │       └── workflow_run_started.proto
│   │   │   ├── audit/
│   │   │   │   └── v1/
│   │   │   │       ├── audit_event.proto
│   │   │   │       └── security_event.proto
│   │   │   ├── admin/
│   │   │   │   └── v1/
│   │   │   │       ├── audit_export_completed.proto
│   │   │   │       ├── audit_export_requested.proto
│   │   │   │       ├── project_created.proto
│   │   │   │       ├── project_updated.proto
│   │   │   │       └── tenant_updated.proto
│   │   │   ├── dataset/
│   │   │   │   └── v1/
│   │   │   │       ├── dataset_created.proto
│   │   │   │       ├── dataset_release_published.proto
│   │   │   │       ├── dataset_release_revoked.proto
│   │   │   │       └── dataset_updated.proto
│   │   │   ├── evaluation/
│   │   │   │   └── v1/
│   │   │   │       ├── evaluation_cancellation_requested.proto
│   │   │   │       ├── evaluation_result_committed.proto
│   │   │   │       ├── evaluation_run_created.proto
│   │   │   │       └── promotion_decision_recorded.proto
│   │   │   ├── inference/
│   │   │   │   └── v1/
│   │   │   │       ├── inference_requested.proto
│   │   │   │       └── inference_result_committed.proto
│   │   │   ├── policy/
│   │   │   │   └── v1/
│   │   │   │       ├── authorization_decision_recorded.proto
│   │   │   │       ├── use_policy_activated.proto
│   │   │   │       ├── use_policy_created.proto
│   │   │   │       ├── use_policy_revoked.proto
│   │   │   │       └── use_policy_updated.proto
│   │   │   └── experiment/
│   │   │       └── v1/
│   │   │           ├── experiment_created.proto
│   │   │           ├── experiment_updated.proto
│   │   │           ├── experiment_state_changed.proto
│   │   │           ├── study_created.proto
│   │   │           ├── study_state_changed.proto
│   │   │           ├── trial_created.proto
│   │   │           ├── trial_state_changed.proto
│   │   │           └── trial_completed.proto
│   │   └── registry.yaml
│   ├── schemas/
│   │   ├── artifact_manifest/
│   │   │   ├── artifact_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_missing_digest.json
│   │   ├── evidence_manifest/
│   │   │   ├── evidence_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_subject_mismatch.json
│   │   ├── release_manifest/
│   │   │   ├── release_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_mutable_reference.json
│   │   ├── configuration/
│   │   │   ├── configuration.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_secret_value.json
│   │   ├── dataset_manifest/
│   │   │   ├── dataset_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_lineage.json
│   │   ├── transform_spec/
│   │   │   ├── transform_spec.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_undeclared_state.json
│   │   ├── transform_graph/
│   │   │   ├── transform_graph.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_cycle.json
│   │   ├── transform_receipt/
│   │   │   ├── transform_receipt.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_lineage.json
│   │   ├── transform_execution_plan/
│   │   │   ├── transform_execution_plan.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_semantic_field_override.json
│   │   ├── transform_state_artifact/
│   │   │   ├── transform_state_artifact.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_missing_fit_scope.json
│   │   ├── fit_receipt/
│   │   │   ├── fit_receipt.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_fitting_scope.json
│   │   ├── lineage_map/
│   │   │   ├── lineage_map.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_unreconstructible_mapping.json
│   │   ├── feature_contract/
│   │   │   ├── feature_contract.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_semantic_identity.json
│   │   ├── feature_requirement_set/
│   │   │   ├── feature_requirement_set.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_incompatible_requirement.json
│   │   ├── model_feature_view/
│   │   │   ├── model_feature_view.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_undeclared_feature.json
│   │   ├── feature_manifest/
│   │   │   ├── feature_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_schema_digest.json
│   │   ├── feature_bundle/
│   │   │   ├── feature_bundle.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_feature_reference.json
│   │   ├── feature_plan/
│   │   │   ├── feature_plan.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_cycle.json
│   │   ├── feature_derivation_receipt/
│   │   │   ├── feature_derivation_receipt.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_key_mismatch.json
│   │   ├── feature_coverage_manifest/
│   │   │   ├── feature_coverage_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_missing_requirement.json
│   │   ├── feature_readiness_receipt/
│   │   │   ├── feature_readiness_receipt.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_unverified_coverage.json
│   │   ├── training_dataset_manifest/
│   │   │   ├── training_dataset_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_split_overlap.json
│   │   ├── batch_receipt/
│   │   │   ├── batch_receipt.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_progress_range.json
│   │   ├── checkpoint_manifest/
│   │   │   ├── checkpoint_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_logical_state.json
│   │   ├── evaluation_snapshot/
│   │   │   ├── evaluation_snapshot.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_subject.json
│   │   ├── model_manifest/
│   │   │   ├── model_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_checkpoint.json
│   │   ├── logical_state_schema/
│   │   │   ├── logical_state.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_state_key.json
│   │   ├── training_recipe/
│   │   │   ├── training_recipe.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_unresolved_value.json
│   │   ├── training_phase_graph/
│   │   │   ├── training_phase_graph.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_cycle.json
│   │   ├── training_run_manifest/
│   │   │   ├── training_run_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_plan_digest.json
│   │   ├── hardware_topology_manifest/
│   │   │   ├── hardware_topology_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_capability.json
│   │   ├── executable_plan/
│   │   │   ├── executable_plan.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_unqualified_topology.json
│   │   ├── provider_manifest/
│   │   │   ├── provider_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_qualification.json
│   │   ├── compiled_region_manifest/
│   │   │   ├── compiled_region_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_cache_key.json
│   │   ├── step_capsule/
│   │   │   ├── step_capsule.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_lineage.json
│   │   ├── study_manifest/
│   │   │   ├── study_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_trial_policy.json
│   │   ├── agent_definition/
│   │   │   ├── agent_definition.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_capability.json
│   │   ├── tool_contract/
│   │   │   ├── tool_contract.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_permission.json
│   │   ├── agent_policy/
│   │   │   ├── agent_policy.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_budget.json
│   │   ├── workflow_definition/
│   │   │   ├── workflow_definition.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_cycle.json
│   │   ├── agent_run_manifest/
│   │   │   ├── agent_run_manifest.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_policy_digest.json
│   │   ├── development_kit_assembly/
│   │   │   ├── development_kit_assembly.schema.json
│   │   │   ├── positive.json
│   │   │   └── negative_authority.json
│   │   └── kernel_qualification/
│   │       ├── kernel_qualification.schema.json
│   │       ├── positive.json
│   │       └── negative_parity.json
│   ├── openapi/
│   │   ├── external-api.yaml
│   │   ├── generation.yaml
│   │   ├── compatibility-policy.yaml
│   │   ├── raw/
│   │   │   └── mindclade.openapi.yaml
│   │   ├── curated/
│   │   │   └── mindclade.openapi.yaml
│   │   └── published/
│   │       └── mindclade.openapi.yaml
│   ├── generated/
│   │   ├── go/
│   │   │   ├── README.generated.md
│   │   │   ├── BUILD.bazel
│   │   │   ├── common/
│   │   │   │   └── v1/
│   │   │   │       ├── identifiers.pb.go
│   │   │   │       ├── resource_reference.pb.go
│   │   │   │       ├── command_context.pb.go
│   │   │   │       ├── event_envelope.pb.go
│   │   │   │       ├── error_detail.pb.go
│   │   │   │       ├── pagination.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── artifact/
│   │   │   │   └── v1/
│   │   │   │       ├── artifact_reference.pb.go
│   │   │   │       ├── evidence_reference.pb.go
│   │   │   │       ├── artifact_commands.pb.go
│   │   │   │       ├── artifact_committed.pb.go
│   │   │   │       ├── artifact_quarantined.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── job/
│   │   │   │   └── v1/
│   │   │   │       ├── operation.pb.go
│   │   │   │       ├── job.pb.go
│   │   │   │       ├── run.pb.go
│   │   │   │       ├── attempt.pb.go
│   │   │   │       ├── lease_fencing.pb.go
│   │   │   │       ├── job_commands.pb.go
│   │   │   │       ├── job_requested.pb.go
│   │   │   │       ├── attempt_leased.pb.go
│   │   │   │       ├── attempt_completed.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── dataset/
│   │   │   │   └── v1/
│   │   │   │       ├── dataset.pb.go
│   │   │   │       ├── dataset_release.pb.go
│   │   │   │       ├── dataset_commands.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── dataset_created.pb.go
│   │   │   │       ├── dataset_release_published.pb.go
│   │   │   │       ├── dataset_release_revoked.pb.go
│   │   │   │       └── dataset_updated.pb.go
│   │   │   ├── feature/
│   │   │   │   └── v1/
│   │   │   │       ├── feature_materialization.pb.go
│   │   │   │       ├── feature_commands.pb.go
│   │   │   │       ├── feature_materialization_completed.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── transform/
│   │   │   │   └── v1/
│   │   │   │       ├── transform_execution.pb.go
│   │   │   │       ├── transform_commands.pb.go
│   │   │   │       ├── transform_execution_completed.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── experiment/
│   │   │   │   └── v1/
│   │   │   │       ├── experiment.pb.go
│   │   │   │       ├── study.pb.go
│   │   │   │       ├── trial.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── experiment_commands.pb.go
│   │   │   │       ├── experiment_created.pb.go
│   │   │   │       ├── experiment_updated.pb.go
│   │   │   │       ├── experiment_state_changed.pb.go
│   │   │   │       ├── study_created.pb.go
│   │   │   │       ├── study_state_changed.pb.go
│   │   │   │       ├── trial_created.pb.go
│   │   │   │       ├── trial_state_changed.pb.go
│   │   │   │       └── trial_completed.pb.go
│   │   │   ├── model/
│   │   │   │   └── v1/
│   │   │   │       ├── model.pb.go
│   │   │   │       ├── model_release.pb.go
│   │   │   │       ├── model_commands.pb.go
│   │   │   │       ├── model_registered.pb.go
│   │   │   │       ├── model_promoted.pb.go
│   │   │   │       ├── model_revoked.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       └── model_release_registered.pb.go
│   │   │   ├── training/
│   │   │   │   └── v1/
│   │   │   │       ├── training_run.pb.go
│   │   │   │       ├── training_progress.pb.go
│   │   │   │       ├── checkpoint.pb.go
│   │   │   │       ├── training_commands.pb.go
│   │   │   │       ├── training_started.pb.go
│   │   │   │       ├── progress_committed.pb.go
│   │   │   │       ├── checkpoint_committed.pb.go
│   │   │   │       ├── training_completed.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── training_run_created.pb.go
│   │   │   │       └── training_cancellation_requested.pb.go
│   │   │   ├── inference/
│   │   │   │   └── v1/
│   │   │   │       ├── inference_request.pb.go
│   │   │   │       ├── inference_result.pb.go
│   │   │   │       ├── inference_stream.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── inference_requested.pb.go
│   │   │   │       └── inference_result_committed.pb.go
│   │   │   ├── evaluation/
│   │   │   │   └── v1/
│   │   │   │       ├── evaluation_run.pb.go
│   │   │   │       ├── evaluation_result.pb.go
│   │   │   │       ├── promotion_decision.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── evaluation_cancellation_requested.pb.go
│   │   │   │       ├── evaluation_result_committed.pb.go
│   │   │   │       ├── evaluation_run_created.pb.go
│   │   │   │       └── promotion_decision_recorded.pb.go
│   │   │   ├── agent/
│   │   │   │   └── v1/
│   │   │   │       ├── agent_definition.pb.go
│   │   │   │       ├── agent_run.pb.go
│   │   │   │       ├── agent_step.pb.go
│   │   │   │       ├── tool_receipt.pb.go
│   │   │   │       ├── agent_step_dispatched.pb.go
│   │   │   │       ├── tool_receipt_committed.pb.go
│   │   │   │       ├── agent_run_completed.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── agent_cancellation_requested.pb.go
│   │   │   │       ├── agent_definition_created.pb.go
│   │   │   │       ├── agent_definition_updated.pb.go
│   │   │   │       ├── agent_run_started.pb.go
│   │   │   │       └── agent_step_committed.pb.go
│   │   │   ├── workflow/
│   │   │   │   └── v1/
│   │   │   │       ├── workflow_definition.pb.go
│   │   │   │       ├── workflow_run.pb.go
│   │   │   │       ├── approval.pb.go
│   │   │   │       ├── workflow_transitioned.pb.go
│   │   │   │       ├── approval_recorded.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── approval_consumed.pb.go
│   │   │   │       ├── approval_requested.pb.go
│   │   │   │       ├── workflow_cancellation_requested.pb.go
│   │   │   │       ├── workflow_definition_created.pb.go
│   │   │   │       ├── workflow_definition_updated.pb.go
│   │   │   │       └── workflow_run_started.pb.go
│   │   │   ├── policy/
│   │   │   │   └── v1/
│   │   │   │       ├── policy_reference.pb.go
│   │   │   │       ├── authorization_decision.pb.go
│   │   │   │       ├── use_policy.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── authorization_decision_recorded.pb.go
│   │   │   │       ├── use_policy_activated.pb.go
│   │   │   │       ├── use_policy_created.pb.go
│   │   │   │       ├── use_policy_revoked.pb.go
│   │   │   │       └── use_policy_updated.pb.go
│   │   │   ├── admin/
│   │   │   │   └── v1/
│   │   │   │       ├── tenant.pb.go
│   │   │   │       ├── project.pb.go
│   │   │   │       ├── audit_query.pb.go
│   │   │   │       ├── BUILD.bazel
│   │   │   │       ├── audit_export_completed.pb.go
│   │   │   │       ├── audit_export_requested.pb.go
│   │   │   │       ├── project_created.pb.go
│   │   │   │       ├── project_updated.pb.go
│   │   │   │       └── tenant_updated.pb.go
│   │   │   ├── audit/
│   │   │   │   └── v1/
│   │   │   │       ├── audit_event.pb.go
│   │   │   │       ├── security_event.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   ├── internalrpc/
│   │   │   │   ├── artifact/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── artifact_service.pb.go
│   │   │   │   │       ├── artifact_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── job/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── job_service.pb.go
│   │   │   │   │       ├── job_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── dataset/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── dataset_service.pb.go
│   │   │   │   │       ├── dataset_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── training/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── training_service.pb.go
│   │   │   │   │       ├── training_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── model/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── model_service.pb.go
│   │   │   │   │       ├── model_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── inference/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── inference_service.pb.go
│   │   │   │   │       ├── inference_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── evaluation/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── evaluation_service.pb.go
│   │   │   │   │       ├── evaluation_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── agent/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── agent_service.pb.go
│   │   │   │   │       ├── agent_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── workflow/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── workflow_service.pb.go
│   │   │   │   │       ├── workflow_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── policy/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── policy_service.pb.go
│   │   │   │   │       ├── policy_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   ├── admin/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── admin_service.pb.go
│   │   │   │   │       ├── admin_service_grpc.pb.go
│   │   │   │   │       └── BUILD.bazel
│   │   │   │   └── experiment/
│   │   │   │       └── v1/
│   │   │   │           ├── BUILD.bazel
│   │   │   │           ├── experiment_service.pb.go
│   │   │   │           └── experiment_service_grpc.pb.go
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── mindclade_service.pb.go
│   │   │   │       ├── mindclade_service_grpc.pb.go
│   │   │   │       └── BUILD.bazel
│   │   │   └── schema/
│   │   │       └── v1/
│   │   │           ├── BUILD.bazel
│   │   │           ├── bindings.generated.go
│   │   │           └── bindings_generated_test.go
│   │   ├── python/
│   │   │   ├── README.generated.md
│   │   │   ├── BUILD.bazel
│   │   │   ├── mindclade/
│   │   │   │   ├── common/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── identifiers_pb2.py
│   │   │   │   │       ├── resource_reference_pb2.py
│   │   │   │   │       ├── command_context_pb2.py
│   │   │   │   │       ├── event_envelope_pb2.py
│   │   │   │   │       ├── error_detail_pb2.py
│   │   │   │   │       ├── pagination_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── identifiers_pb2.pyi
│   │   │   │   │       ├── resource_reference_pb2.pyi
│   │   │   │   │       ├── command_context_pb2.pyi
│   │   │   │   │       ├── event_envelope_pb2.pyi
│   │   │   │   │       ├── error_detail_pb2.pyi
│   │   │   │   │       └── pagination_pb2.pyi
│   │   │   │   ├── artifact/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── artifact_reference_pb2.py
│   │   │   │   │       ├── evidence_reference_pb2.py
│   │   │   │   │       ├── artifact_commands_pb2.py
│   │   │   │   │       ├── artifact_committed_pb2.py
│   │   │   │   │       ├── artifact_quarantined_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── artifact_reference_pb2.pyi
│   │   │   │   │       ├── evidence_reference_pb2.pyi
│   │   │   │   │       ├── artifact_commands_pb2.pyi
│   │   │   │   │       ├── artifact_committed_pb2.pyi
│   │   │   │   │       └── artifact_quarantined_pb2.pyi
│   │   │   │   ├── job/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── operation_pb2.py
│   │   │   │   │       ├── job_pb2.py
│   │   │   │   │       ├── run_pb2.py
│   │   │   │   │       ├── attempt_pb2.py
│   │   │   │   │       ├── lease_fencing_pb2.py
│   │   │   │   │       ├── job_commands_pb2.py
│   │   │   │   │       ├── job_requested_pb2.py
│   │   │   │   │       ├── attempt_leased_pb2.py
│   │   │   │   │       ├── attempt_completed_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── operation_pb2.pyi
│   │   │   │   │       ├── job_pb2.pyi
│   │   │   │   │       ├── run_pb2.pyi
│   │   │   │   │       ├── attempt_pb2.pyi
│   │   │   │   │       ├── lease_fencing_pb2.pyi
│   │   │   │   │       ├── job_commands_pb2.pyi
│   │   │   │   │       ├── job_requested_pb2.pyi
│   │   │   │   │       ├── attempt_leased_pb2.pyi
│   │   │   │   │       └── attempt_completed_pb2.pyi
│   │   │   │   ├── dataset/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── dataset_pb2.py
│   │   │   │   │       ├── dataset_release_pb2.py
│   │   │   │   │       ├── dataset_commands_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── dataset_pb2.pyi
│   │   │   │   │       ├── dataset_release_pb2.pyi
│   │   │   │   │       ├── dataset_commands_pb2.pyi
│   │   │   │   │       ├── dataset_created_pb2.py
│   │   │   │   │       ├── dataset_created_pb2.pyi
│   │   │   │   │       ├── dataset_release_published_pb2.py
│   │   │   │   │       ├── dataset_release_published_pb2.pyi
│   │   │   │   │       ├── dataset_release_revoked_pb2.py
│   │   │   │   │       ├── dataset_release_revoked_pb2.pyi
│   │   │   │   │       ├── dataset_updated_pb2.py
│   │   │   │   │       └── dataset_updated_pb2.pyi
│   │   │   │   ├── feature/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── feature_materialization_pb2.py
│   │   │   │   │       ├── feature_commands_pb2.py
│   │   │   │   │       ├── feature_materialization_completed_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── feature_materialization_pb2.pyi
│   │   │   │   │       ├── feature_commands_pb2.pyi
│   │   │   │   │       └── feature_materialization_completed_pb2.pyi
│   │   │   │   ├── transform/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── transform_execution_pb2.py
│   │   │   │   │       ├── transform_commands_pb2.py
│   │   │   │   │       ├── transform_execution_completed_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── transform_execution_pb2.pyi
│   │   │   │   │       ├── transform_commands_pb2.pyi
│   │   │   │   │       └── transform_execution_completed_pb2.pyi
│   │   │   │   ├── experiment/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── experiment_pb2.py
│   │   │   │   │       ├── study_pb2.py
│   │   │   │   │       ├── trial_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── experiment_pb2.pyi
│   │   │   │   │       ├── study_pb2.pyi
│   │   │   │   │       ├── trial_pb2.pyi
│   │   │   │   │       ├── experiment_commands_pb2.py
│   │   │   │   │       ├── experiment_commands_pb2.pyi
│   │   │   │   │       ├── experiment_created_pb2.py
│   │   │   │   │       ├── experiment_created_pb2.pyi
│   │   │   │   │       ├── experiment_updated_pb2.py
│   │   │   │   │       ├── experiment_updated_pb2.pyi
│   │   │   │   │       ├── experiment_state_changed_pb2.py
│   │   │   │   │       ├── experiment_state_changed_pb2.pyi
│   │   │   │   │       ├── study_created_pb2.py
│   │   │   │   │       ├── study_created_pb2.pyi
│   │   │   │   │       ├── study_state_changed_pb2.py
│   │   │   │   │       ├── study_state_changed_pb2.pyi
│   │   │   │   │       ├── trial_created_pb2.py
│   │   │   │   │       ├── trial_created_pb2.pyi
│   │   │   │   │       ├── trial_state_changed_pb2.py
│   │   │   │   │       ├── trial_state_changed_pb2.pyi
│   │   │   │   │       ├── trial_completed_pb2.py
│   │   │   │   │       └── trial_completed_pb2.pyi
│   │   │   │   ├── model/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── model_pb2.py
│   │   │   │   │       ├── model_release_pb2.py
│   │   │   │   │       ├── model_commands_pb2.py
│   │   │   │   │       ├── model_registered_pb2.py
│   │   │   │   │       ├── model_promoted_pb2.py
│   │   │   │   │       ├── model_revoked_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── model_pb2.pyi
│   │   │   │   │       ├── model_release_pb2.pyi
│   │   │   │   │       ├── model_commands_pb2.pyi
│   │   │   │   │       ├── model_registered_pb2.pyi
│   │   │   │   │       ├── model_promoted_pb2.pyi
│   │   │   │   │       ├── model_revoked_pb2.pyi
│   │   │   │   │       ├── model_release_registered_pb2.py
│   │   │   │   │       └── model_release_registered_pb2.pyi
│   │   │   │   ├── training/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── training_run_pb2.py
│   │   │   │   │       ├── training_progress_pb2.py
│   │   │   │   │       ├── checkpoint_pb2.py
│   │   │   │   │       ├── training_commands_pb2.py
│   │   │   │   │       ├── training_started_pb2.py
│   │   │   │   │       ├── progress_committed_pb2.py
│   │   │   │   │       ├── checkpoint_committed_pb2.py
│   │   │   │   │       ├── training_completed_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── training_run_pb2.pyi
│   │   │   │   │       ├── training_progress_pb2.pyi
│   │   │   │   │       ├── checkpoint_pb2.pyi
│   │   │   │   │       ├── training_commands_pb2.pyi
│   │   │   │   │       ├── training_started_pb2.pyi
│   │   │   │   │       ├── progress_committed_pb2.pyi
│   │   │   │   │       ├── checkpoint_committed_pb2.pyi
│   │   │   │   │       ├── training_completed_pb2.pyi
│   │   │   │   │       ├── training_run_created_pb2.pyi
│   │   │   │   │       ├── training_cancellation_requested_pb2.pyi
│   │   │   │   │       ├── training_run_created_pb2.py
│   │   │   │   │       └── training_cancellation_requested_pb2.py
│   │   │   │   ├── inference/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── inference_request_pb2.py
│   │   │   │   │       ├── inference_result_pb2.py
│   │   │   │   │       ├── inference_stream_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── inference_request_pb2.pyi
│   │   │   │   │       ├── inference_result_pb2.pyi
│   │   │   │   │       ├── inference_stream_pb2.pyi
│   │   │   │   │       ├── inference_requested_pb2.py
│   │   │   │   │       ├── inference_requested_pb2.pyi
│   │   │   │   │       ├── inference_result_committed_pb2.py
│   │   │   │   │       └── inference_result_committed_pb2.pyi
│   │   │   │   ├── evaluation/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── evaluation_run_pb2.py
│   │   │   │   │       ├── evaluation_result_pb2.py
│   │   │   │   │       ├── promotion_decision_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── evaluation_run_pb2.pyi
│   │   │   │   │       ├── evaluation_result_pb2.pyi
│   │   │   │   │       ├── promotion_decision_pb2.pyi
│   │   │   │   │       ├── evaluation_cancellation_requested_pb2.py
│   │   │   │   │       ├── evaluation_cancellation_requested_pb2.pyi
│   │   │   │   │       ├── evaluation_result_committed_pb2.py
│   │   │   │   │       ├── evaluation_result_committed_pb2.pyi
│   │   │   │   │       ├── evaluation_run_created_pb2.py
│   │   │   │   │       ├── evaluation_run_created_pb2.pyi
│   │   │   │   │       ├── promotion_decision_recorded_pb2.py
│   │   │   │   │       └── promotion_decision_recorded_pb2.pyi
│   │   │   │   ├── agent/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── agent_definition_pb2.py
│   │   │   │   │       ├── agent_run_pb2.py
│   │   │   │   │       ├── agent_step_pb2.py
│   │   │   │   │       ├── tool_receipt_pb2.py
│   │   │   │   │       ├── agent_step_dispatched_pb2.py
│   │   │   │   │       ├── tool_receipt_committed_pb2.py
│   │   │   │   │       ├── agent_run_completed_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── agent_definition_pb2.pyi
│   │   │   │   │       ├── agent_run_pb2.pyi
│   │   │   │   │       ├── agent_step_pb2.pyi
│   │   │   │   │       ├── tool_receipt_pb2.pyi
│   │   │   │   │       ├── agent_step_dispatched_pb2.pyi
│   │   │   │   │       ├── tool_receipt_committed_pb2.pyi
│   │   │   │   │       ├── agent_run_completed_pb2.pyi
│   │   │   │   │       ├── agent_cancellation_requested_pb2.py
│   │   │   │   │       ├── agent_cancellation_requested_pb2.pyi
│   │   │   │   │       ├── agent_definition_created_pb2.py
│   │   │   │   │       ├── agent_definition_created_pb2.pyi
│   │   │   │   │       ├── agent_definition_updated_pb2.py
│   │   │   │   │       ├── agent_definition_updated_pb2.pyi
│   │   │   │   │       ├── agent_run_started_pb2.py
│   │   │   │   │       ├── agent_run_started_pb2.pyi
│   │   │   │   │       ├── agent_step_committed_pb2.py
│   │   │   │   │       └── agent_step_committed_pb2.pyi
│   │   │   │   ├── workflow/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── workflow_definition_pb2.py
│   │   │   │   │       ├── workflow_run_pb2.py
│   │   │   │   │       ├── approval_pb2.py
│   │   │   │   │       ├── workflow_transitioned_pb2.py
│   │   │   │   │       ├── approval_recorded_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── workflow_definition_pb2.pyi
│   │   │   │   │       ├── workflow_run_pb2.pyi
│   │   │   │   │       ├── approval_pb2.pyi
│   │   │   │   │       ├── workflow_transitioned_pb2.pyi
│   │   │   │   │       ├── approval_recorded_pb2.pyi
│   │   │   │   │       ├── approval_consumed_pb2.py
│   │   │   │   │       ├── approval_consumed_pb2.pyi
│   │   │   │   │       ├── approval_requested_pb2.py
│   │   │   │   │       ├── approval_requested_pb2.pyi
│   │   │   │   │       ├── workflow_cancellation_requested_pb2.py
│   │   │   │   │       ├── workflow_cancellation_requested_pb2.pyi
│   │   │   │   │       ├── workflow_definition_created_pb2.py
│   │   │   │   │       ├── workflow_definition_created_pb2.pyi
│   │   │   │   │       ├── workflow_definition_updated_pb2.py
│   │   │   │   │       ├── workflow_definition_updated_pb2.pyi
│   │   │   │   │       ├── workflow_run_started_pb2.py
│   │   │   │   │       └── workflow_run_started_pb2.pyi
│   │   │   │   ├── policy/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── policy_reference_pb2.py
│   │   │   │   │       ├── authorization_decision_pb2.py
│   │   │   │   │       ├── use_policy_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── policy_reference_pb2.pyi
│   │   │   │   │       ├── authorization_decision_pb2.pyi
│   │   │   │   │       ├── use_policy_pb2.pyi
│   │   │   │   │       ├── authorization_decision_recorded_pb2.py
│   │   │   │   │       ├── authorization_decision_recorded_pb2.pyi
│   │   │   │   │       ├── use_policy_activated_pb2.py
│   │   │   │   │       ├── use_policy_activated_pb2.pyi
│   │   │   │   │       ├── use_policy_created_pb2.py
│   │   │   │   │       ├── use_policy_created_pb2.pyi
│   │   │   │   │       ├── use_policy_revoked_pb2.py
│   │   │   │   │       ├── use_policy_revoked_pb2.pyi
│   │   │   │   │       ├── use_policy_updated_pb2.py
│   │   │   │   │       └── use_policy_updated_pb2.pyi
│   │   │   │   ├── admin/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── tenant_pb2.py
│   │   │   │   │       ├── project_pb2.py
│   │   │   │   │       ├── audit_query_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── tenant_pb2.pyi
│   │   │   │   │       ├── project_pb2.pyi
│   │   │   │   │       ├── audit_query_pb2.pyi
│   │   │   │   │       ├── audit_export_completed_pb2.py
│   │   │   │   │       ├── audit_export_completed_pb2.pyi
│   │   │   │   │       ├── audit_export_requested_pb2.py
│   │   │   │   │       ├── audit_export_requested_pb2.pyi
│   │   │   │   │       ├── project_created_pb2.py
│   │   │   │   │       ├── project_created_pb2.pyi
│   │   │   │   │       ├── project_updated_pb2.py
│   │   │   │   │       ├── project_updated_pb2.pyi
│   │   │   │   │       ├── tenant_updated_pb2.py
│   │   │   │   │       └── tenant_updated_pb2.pyi
│   │   │   │   ├── audit/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── audit_event_pb2.py
│   │   │   │   │       ├── security_event_pb2.py
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── audit_event_pb2.pyi
│   │   │   │   │       └── security_event_pb2.pyi
│   │   │   │   ├── internal/
│   │   │   │   │   ├── artifact/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── artifact_service_pb2.py
│   │   │   │   │   │       ├── artifact_service_pb2.pyi
│   │   │   │   │   │       ├── artifact_service_pb2_grpc.py
│   │   │   │   │   │       ├── artifact_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── job/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── job_service_pb2.py
│   │   │   │   │   │       ├── job_service_pb2.pyi
│   │   │   │   │   │       ├── job_service_pb2_grpc.py
│   │   │   │   │   │       ├── job_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── dataset/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── dataset_service_pb2.py
│   │   │   │   │   │       ├── dataset_service_pb2.pyi
│   │   │   │   │   │       ├── dataset_service_pb2_grpc.py
│   │   │   │   │   │       ├── dataset_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── training/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── training_service_pb2.py
│   │   │   │   │   │       ├── training_service_pb2.pyi
│   │   │   │   │   │       ├── training_service_pb2_grpc.py
│   │   │   │   │   │       ├── training_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── model/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── model_service_pb2.py
│   │   │   │   │   │       ├── model_service_pb2.pyi
│   │   │   │   │   │       ├── model_service_pb2_grpc.py
│   │   │   │   │   │       ├── model_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── inference/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── inference_service_pb2.py
│   │   │   │   │   │       ├── inference_service_pb2.pyi
│   │   │   │   │   │       ├── inference_service_pb2_grpc.py
│   │   │   │   │   │       ├── inference_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── evaluation/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── evaluation_service_pb2.py
│   │   │   │   │   │       ├── evaluation_service_pb2.pyi
│   │   │   │   │   │       ├── evaluation_service_pb2_grpc.py
│   │   │   │   │   │       ├── evaluation_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── agent/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── agent_service_pb2.py
│   │   │   │   │   │       ├── agent_service_pb2.pyi
│   │   │   │   │   │       ├── agent_service_pb2_grpc.py
│   │   │   │   │   │       ├── agent_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── workflow/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── workflow_service_pb2.py
│   │   │   │   │   │       ├── workflow_service_pb2.pyi
│   │   │   │   │   │       ├── workflow_service_pb2_grpc.py
│   │   │   │   │   │       ├── workflow_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── policy/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── policy_service_pb2.py
│   │   │   │   │   │       ├── policy_service_pb2.pyi
│   │   │   │   │   │       ├── policy_service_pb2_grpc.py
│   │   │   │   │   │       ├── policy_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   ├── admin/
│   │   │   │   │   │   └── v1/
│   │   │   │   │   │       ├── admin_service_pb2.py
│   │   │   │   │   │       ├── admin_service_pb2.pyi
│   │   │   │   │   │       ├── admin_service_pb2_grpc.py
│   │   │   │   │   │       ├── admin_service_pb2_grpc.pyi
│   │   │   │   │   │       └── __init__.py
│   │   │   │   │   └── experiment/
│   │   │   │   │       └── v1/
│   │   │   │   │           ├── __init__.py
│   │   │   │   │           ├── experiment_service_pb2.py
│   │   │   │   │           ├── experiment_service_pb2.pyi
│   │   │   │   │           ├── experiment_service_pb2_grpc.py
│   │   │   │   │           └── experiment_service_pb2_grpc.pyi
│   │   │   │   ├── api/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── mindclade_service_pb2.py
│   │   │   │   │       ├── mindclade_service_pb2.pyi
│   │   │   │   │       ├── mindclade_service_pb2_grpc.py
│   │   │   │   │       ├── mindclade_service_pb2_grpc.pyi
│   │   │   │   │       └── __init__.py
│   │   │   │   ├── events/
│   │   │   │   │   └── registry.py
│   │   │   │   └── schema/
│   │   │   │       └── v1/
│   │   │   │           ├── __init__.py
│   │   │   │           └── bindings.py
│   │   │   └── pyproject.toml
│   │   ├── rust/
│   │   │   ├── README.generated.md
│   │   │   ├── BUILD.bazel
│   │   │   ├── common/
│   │   │   │   └── v1/
│   │   │   │       ├── identifiers.rs
│   │   │   │       ├── resource_reference.rs
│   │   │   │       ├── command_context.rs
│   │   │   │       ├── event_envelope.rs
│   │   │   │       ├── error_detail.rs
│   │   │   │       ├── pagination.rs
│   │   │   │       └── mod.rs
│   │   │   ├── artifact/
│   │   │   │   └── v1/
│   │   │   │       ├── artifact_reference.rs
│   │   │   │       ├── evidence_reference.rs
│   │   │   │       ├── artifact_commands.rs
│   │   │   │       ├── artifact_committed.rs
│   │   │   │       ├── artifact_quarantined.rs
│   │   │   │       └── mod.rs
│   │   │   ├── job/
│   │   │   │   └── v1/
│   │   │   │       ├── operation.rs
│   │   │   │       ├── job.rs
│   │   │   │       ├── run.rs
│   │   │   │       ├── attempt.rs
│   │   │   │       ├── lease_fencing.rs
│   │   │   │       ├── job_commands.rs
│   │   │   │       ├── job_requested.rs
│   │   │   │       ├── attempt_leased.rs
│   │   │   │       ├── attempt_completed.rs
│   │   │   │       └── mod.rs
│   │   │   ├── dataset/
│   │   │   │   └── v1/
│   │   │   │       ├── dataset.rs
│   │   │   │       ├── dataset_release.rs
│   │   │   │       ├── dataset_commands.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── dataset_created.rs
│   │   │   │       ├── dataset_release_published.rs
│   │   │   │       ├── dataset_release_revoked.rs
│   │   │   │       └── dataset_updated.rs
│   │   │   ├── feature/
│   │   │   │   └── v1/
│   │   │   │       ├── feature_materialization.rs
│   │   │   │       ├── feature_commands.rs
│   │   │   │       ├── feature_materialization_completed.rs
│   │   │   │       └── mod.rs
│   │   │   ├── transform/
│   │   │   │   └── v1/
│   │   │   │       ├── transform_execution.rs
│   │   │   │       ├── transform_commands.rs
│   │   │   │       ├── transform_execution_completed.rs
│   │   │   │       └── mod.rs
│   │   │   ├── experiment/
│   │   │   │   └── v1/
│   │   │   │       ├── experiment.rs
│   │   │   │       ├── study.rs
│   │   │   │       ├── trial.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── experiment_commands.rs
│   │   │   │       ├── experiment_created.rs
│   │   │   │       ├── experiment_updated.rs
│   │   │   │       ├── experiment_state_changed.rs
│   │   │   │       ├── study_created.rs
│   │   │   │       ├── study_state_changed.rs
│   │   │   │       ├── trial_created.rs
│   │   │   │       ├── trial_state_changed.rs
│   │   │   │       └── trial_completed.rs
│   │   │   ├── model/
│   │   │   │   └── v1/
│   │   │   │       ├── model.rs
│   │   │   │       ├── model_release.rs
│   │   │   │       ├── model_commands.rs
│   │   │   │       ├── model_registered.rs
│   │   │   │       ├── model_promoted.rs
│   │   │   │       ├── model_revoked.rs
│   │   │   │       ├── mod.rs
│   │   │   │       └── model_release_registered.rs
│   │   │   ├── training/
│   │   │   │   └── v1/
│   │   │   │       ├── training_run.rs
│   │   │   │       ├── training_progress.rs
│   │   │   │       ├── checkpoint.rs
│   │   │   │       ├── training_commands.rs
│   │   │   │       ├── training_started.rs
│   │   │   │       ├── progress_committed.rs
│   │   │   │       ├── checkpoint_committed.rs
│   │   │   │       ├── training_completed.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── training_run_created.rs
│   │   │   │       └── training_cancellation_requested.rs
│   │   │   ├── inference/
│   │   │   │   └── v1/
│   │   │   │       ├── inference_request.rs
│   │   │   │       ├── inference_result.rs
│   │   │   │       ├── inference_stream.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── inference_requested.rs
│   │   │   │       └── inference_result_committed.rs
│   │   │   ├── evaluation/
│   │   │   │   └── v1/
│   │   │   │       ├── evaluation_run.rs
│   │   │   │       ├── evaluation_result.rs
│   │   │   │       ├── promotion_decision.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── evaluation_cancellation_requested.rs
│   │   │   │       ├── evaluation_result_committed.rs
│   │   │   │       ├── evaluation_run_created.rs
│   │   │   │       └── promotion_decision_recorded.rs
│   │   │   ├── agent/
│   │   │   │   └── v1/
│   │   │   │       ├── agent_definition.rs
│   │   │   │       ├── agent_run.rs
│   │   │   │       ├── agent_step.rs
│   │   │   │       ├── tool_receipt.rs
│   │   │   │       ├── agent_step_dispatched.rs
│   │   │   │       ├── tool_receipt_committed.rs
│   │   │   │       ├── agent_run_completed.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── agent_cancellation_requested.rs
│   │   │   │       ├── agent_definition_created.rs
│   │   │   │       ├── agent_definition_updated.rs
│   │   │   │       ├── agent_run_started.rs
│   │   │   │       └── agent_step_committed.rs
│   │   │   ├── workflow/
│   │   │   │   └── v1/
│   │   │   │       ├── workflow_definition.rs
│   │   │   │       ├── workflow_run.rs
│   │   │   │       ├── approval.rs
│   │   │   │       ├── workflow_transitioned.rs
│   │   │   │       ├── approval_recorded.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── approval_consumed.rs
│   │   │   │       ├── approval_requested.rs
│   │   │   │       ├── workflow_cancellation_requested.rs
│   │   │   │       ├── workflow_definition_created.rs
│   │   │   │       ├── workflow_definition_updated.rs
│   │   │   │       └── workflow_run_started.rs
│   │   │   ├── policy/
│   │   │   │   └── v1/
│   │   │   │       ├── policy_reference.rs
│   │   │   │       ├── authorization_decision.rs
│   │   │   │       ├── use_policy.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── authorization_decision_recorded.rs
│   │   │   │       ├── use_policy_activated.rs
│   │   │   │       ├── use_policy_created.rs
│   │   │   │       ├── use_policy_revoked.rs
│   │   │   │       └── use_policy_updated.rs
│   │   │   ├── admin/
│   │   │   │   └── v1/
│   │   │   │       ├── tenant.rs
│   │   │   │       ├── project.rs
│   │   │   │       ├── audit_query.rs
│   │   │   │       ├── mod.rs
│   │   │   │       ├── audit_export_completed.rs
│   │   │   │       ├── audit_export_requested.rs
│   │   │   │       ├── project_created.rs
│   │   │   │       ├── project_updated.rs
│   │   │   │       └── tenant_updated.rs
│   │   │   ├── audit/
│   │   │   │   └── v1/
│   │   │   │       ├── audit_event.rs
│   │   │   │       ├── security_event.rs
│   │   │   │       └── mod.rs
│   │   │   ├── Cargo.toml
│   │   │   ├── lib.rs
│   │   │   ├── internal/
│   │   │   │   ├── artifact/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── artifact_service.rs
│   │   │   │   │       ├── artifact_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── job/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── job_service.rs
│   │   │   │   │       ├── job_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── dataset/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── dataset_service.rs
│   │   │   │   │       ├── dataset_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── training/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── training_service.rs
│   │   │   │   │       ├── training_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── model/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── model_service.rs
│   │   │   │   │       ├── model_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── inference/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── inference_service.rs
│   │   │   │   │       ├── inference_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── evaluation/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── evaluation_service.rs
│   │   │   │   │       ├── evaluation_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── agent/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── agent_service.rs
│   │   │   │   │       ├── agent_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── workflow/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── workflow_service.rs
│   │   │   │   │       ├── workflow_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── policy/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── policy_service.rs
│   │   │   │   │       ├── policy_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   ├── admin/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── admin_service.rs
│   │   │   │   │       ├── admin_service_grpc.rs
│   │   │   │   │       └── mod.rs
│   │   │   │   └── experiment/
│   │   │   │       └── v1/
│   │   │   │           ├── mod.rs
│   │   │   │           ├── experiment_service.rs
│   │   │   │           └── experiment_service_grpc.rs
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── mindclade_service.rs
│   │   │   │       ├── mindclade_service_grpc.rs
│   │   │   │       └── mod.rs
│   │   │   └── schema/
│   │   │       └── v1.rs
│   │   ├── typescript/
│   │   │   ├── README.generated.md
│   │   │   ├── BUILD.bazel
│   │   │   ├── common/
│   │   │   │   └── v1/
│   │   │   │       ├── identifiers_pb.ts
│   │   │   │       ├── resource_reference_pb.ts
│   │   │   │       ├── command_context_pb.ts
│   │   │   │       ├── event_envelope_pb.ts
│   │   │   │       ├── error_detail_pb.ts
│   │   │   │       ├── pagination_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── artifact/
│   │   │   │   └── v1/
│   │   │   │       ├── artifact_reference_pb.ts
│   │   │   │       ├── evidence_reference_pb.ts
│   │   │   │       ├── artifact_commands_pb.ts
│   │   │   │       ├── artifact_committed_pb.ts
│   │   │   │       ├── artifact_quarantined_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── job/
│   │   │   │   └── v1/
│   │   │   │       ├── operation_pb.ts
│   │   │   │       ├── job_pb.ts
│   │   │   │       ├── run_pb.ts
│   │   │   │       ├── attempt_pb.ts
│   │   │   │       ├── lease_fencing_pb.ts
│   │   │   │       ├── job_commands_pb.ts
│   │   │   │       ├── job_requested_pb.ts
│   │   │   │       ├── attempt_leased_pb.ts
│   │   │   │       ├── attempt_completed_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── dataset/
│   │   │   │   └── v1/
│   │   │   │       ├── dataset_pb.ts
│   │   │   │       ├── dataset_release_pb.ts
│   │   │   │       ├── dataset_commands_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── dataset_created_pb.ts
│   │   │   │       ├── dataset_release_published_pb.ts
│   │   │   │       ├── dataset_release_revoked_pb.ts
│   │   │   │       └── dataset_updated_pb.ts
│   │   │   ├── feature/
│   │   │   │   └── v1/
│   │   │   │       ├── feature_materialization_pb.ts
│   │   │   │       ├── feature_commands_pb.ts
│   │   │   │       ├── feature_materialization_completed_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── transform/
│   │   │   │   └── v1/
│   │   │   │       ├── transform_execution_pb.ts
│   │   │   │       ├── transform_commands_pb.ts
│   │   │   │       ├── transform_execution_completed_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── experiment/
│   │   │   │   └── v1/
│   │   │   │       ├── experiment_pb.ts
│   │   │   │       ├── study_pb.ts
│   │   │   │       ├── trial_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── experiment_commands_pb.ts
│   │   │   │       ├── experiment_created_pb.ts
│   │   │   │       ├── experiment_updated_pb.ts
│   │   │   │       ├── experiment_state_changed_pb.ts
│   │   │   │       ├── study_created_pb.ts
│   │   │   │       ├── study_state_changed_pb.ts
│   │   │   │       ├── trial_created_pb.ts
│   │   │   │       ├── trial_state_changed_pb.ts
│   │   │   │       └── trial_completed_pb.ts
│   │   │   ├── model/
│   │   │   │   └── v1/
│   │   │   │       ├── model_pb.ts
│   │   │   │       ├── model_release_pb.ts
│   │   │   │       ├── model_commands_pb.ts
│   │   │   │       ├── model_registered_pb.ts
│   │   │   │       ├── model_promoted_pb.ts
│   │   │   │       ├── model_revoked_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       └── model_release_registered_pb.ts
│   │   │   ├── training/
│   │   │   │   └── v1/
│   │   │   │       ├── training_run_pb.ts
│   │   │   │       ├── training_progress_pb.ts
│   │   │   │       ├── checkpoint_pb.ts
│   │   │   │       ├── training_commands_pb.ts
│   │   │   │       ├── training_started_pb.ts
│   │   │   │       ├── progress_committed_pb.ts
│   │   │   │       ├── checkpoint_committed_pb.ts
│   │   │   │       ├── training_completed_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── training_run_created_pb.ts
│   │   │   │       └── training_cancellation_requested_pb.ts
│   │   │   ├── inference/
│   │   │   │   └── v1/
│   │   │   │       ├── inference_request_pb.ts
│   │   │   │       ├── inference_result_pb.ts
│   │   │   │       ├── inference_stream_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── inference_requested_pb.ts
│   │   │   │       └── inference_result_committed_pb.ts
│   │   │   ├── evaluation/
│   │   │   │   └── v1/
│   │   │   │       ├── evaluation_run_pb.ts
│   │   │   │       ├── evaluation_result_pb.ts
│   │   │   │       ├── promotion_decision_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── evaluation_cancellation_requested_pb.ts
│   │   │   │       ├── evaluation_result_committed_pb.ts
│   │   │   │       ├── evaluation_run_created_pb.ts
│   │   │   │       └── promotion_decision_recorded_pb.ts
│   │   │   ├── agent/
│   │   │   │   └── v1/
│   │   │   │       ├── agent_definition_pb.ts
│   │   │   │       ├── agent_run_pb.ts
│   │   │   │       ├── agent_step_pb.ts
│   │   │   │       ├── tool_receipt_pb.ts
│   │   │   │       ├── agent_step_dispatched_pb.ts
│   │   │   │       ├── tool_receipt_committed_pb.ts
│   │   │   │       ├── agent_run_completed_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── agent_cancellation_requested_pb.ts
│   │   │   │       ├── agent_definition_created_pb.ts
│   │   │   │       ├── agent_definition_updated_pb.ts
│   │   │   │       ├── agent_run_started_pb.ts
│   │   │   │       └── agent_step_committed_pb.ts
│   │   │   ├── workflow/
│   │   │   │   └── v1/
│   │   │   │       ├── workflow_definition_pb.ts
│   │   │   │       ├── workflow_run_pb.ts
│   │   │   │       ├── approval_pb.ts
│   │   │   │       ├── workflow_transitioned_pb.ts
│   │   │   │       ├── approval_recorded_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── approval_consumed_pb.ts
│   │   │   │       ├── approval_requested_pb.ts
│   │   │   │       ├── workflow_cancellation_requested_pb.ts
│   │   │   │       ├── workflow_definition_created_pb.ts
│   │   │   │       ├── workflow_definition_updated_pb.ts
│   │   │   │       └── workflow_run_started_pb.ts
│   │   │   ├── policy/
│   │   │   │   └── v1/
│   │   │   │       ├── policy_reference_pb.ts
│   │   │   │       ├── authorization_decision_pb.ts
│   │   │   │       ├── use_policy_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── authorization_decision_recorded_pb.ts
│   │   │   │       ├── use_policy_activated_pb.ts
│   │   │   │       ├── use_policy_created_pb.ts
│   │   │   │       ├── use_policy_revoked_pb.ts
│   │   │   │       └── use_policy_updated_pb.ts
│   │   │   ├── admin/
│   │   │   │   └── v1/
│   │   │   │       ├── tenant_pb.ts
│   │   │   │       ├── project_pb.ts
│   │   │   │       ├── audit_query_pb.ts
│   │   │   │       ├── index.ts
│   │   │   │       ├── audit_export_completed_pb.ts
│   │   │   │       ├── audit_export_requested_pb.ts
│   │   │   │       ├── project_created_pb.ts
│   │   │   │       ├── project_updated_pb.ts
│   │   │   │       └── tenant_updated_pb.ts
│   │   │   ├── audit/
│   │   │   │   └── v1/
│   │   │   │       ├── audit_event_pb.ts
│   │   │   │       ├── security_event_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── package.json
│   │   │   ├── tsconfig.json
│   │   │   ├── internal/
│   │   │   │   ├── artifact/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── artifact_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── job/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── job_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── dataset/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── dataset_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── training/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── training_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── model/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── model_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── inference/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── inference_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── evaluation/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── evaluation_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── agent/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── agent_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── workflow/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── workflow_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── policy/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── policy_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   ├── admin/
│   │   │   │   │   └── v1/
│   │   │   │   │       ├── admin_service_pb.ts
│   │   │   │   │       └── index.ts
│   │   │   │   └── experiment/
│   │   │   │       └── v1/
│   │   │   │           ├── index.ts
│   │   │   │           └── experiment_service_pb.ts
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── mindclade_service_pb.ts
│   │   │   │       └── index.ts
│   │   │   ├── google/
│   │   │   │   └── api/
│   │   │   │       ├── annotations_pb.ts
│   │   │   │       └── http_pb.ts
│   │   │   └── schema/
│   │   │       └── v1/
│   │   │           └── bindings.ts
│   │   ├── README.md
│   │   ├── BUILD.bazel
│   │   └── generated-files.manifest.json
│   ├── compatibility/
│   │   ├── baselines/
│   │   │   ├── protobuf.lock.json
│   │   │   ├── json-schema.lock.json
│   │   │   ├── openapi.lock.json
│   │   │   ├── protobuf.candidate.json
│   │   │   └── protobuf.predecessor.lock.json
│   │   └── tests/
│   │       ├── test_protobuf_compatibility.py
│   │       ├── test_schema_compatibility.py
│   │       └── test_openapi_compatibility.py
│   ├── BUILD.bazel
│   └── README.md
├── libs/
│   ├── python/
│   │   ├── artifacts/
│   │   │   ├── __init__.py
│   │   │   ├── artifact_reference.py
│   │   │   ├── digest.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── resolution.py
│   │   │   ├── redaction.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── contracts/
│   │   │   ├── __init__.py
│   │   │   ├── error_mapping.py
│   │   │   ├── deadline.py
│   │   │   ├── cancellation.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── identifiers/
│   │   │   ├── __init__.py
│   │   │   ├── resource_id.py
│   │   │   ├── resource_reference.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── observability/
│   │   │   ├── __init__.py
│   │   │   ├── logging.py
│   │   │   ├── tracing.py
│   │   │   ├── metrics.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── retry/
│   │   │   ├── __init__.py
│   │   │   ├── retry_policy.py
│   │   │   ├── backoff.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── serialization/
│   │   │   ├── __init__.py
│   │   │   ├── canonical_json.py
│   │   │   ├── protobuf_io.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── testing/
│   │   │   ├── __init__.py
│   │   │   ├── clock.py
│   │   │   ├── fixtures.py
│   │   │   ├── contract_cases.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── time/
│   │   │   ├── __init__.py
│   │   │   ├── clock.py
│   │   │   ├── deadline.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── dependency_policy_test.py
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── rust/
│   │   ├── artifact/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── digest.rs
│   │   │   │   └── reference.rs
│   │   │   └── BUILD.bazel
│   │   ├── bytes/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── chunk.rs
│   │   │   │   └── integrity.rs
│   │   │   └── BUILD.bazel
│   │   ├── config/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── resolution.rs
│   │   │   │   └── redaction.rs
│   │   │   └── BUILD.bazel
│   │   ├── errors/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   └── taxonomy.rs
│   │   │   └── BUILD.bazel
│   │   ├── identifiers/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   └── resource_id.rs
│   │   │   └── BUILD.bazel
│   │   ├── observability/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── tracing.rs
│   │   │   │   └── metrics.rs
│   │   │   └── BUILD.bazel
│   │   ├── retry/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── policy.rs
│   │   │   │   └── backoff.rs
│   │   │   └── BUILD.bazel
│   │   ├── storage/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── object_store.rs
│   │   │   │   └── resumable.rs
│   │   │   └── BUILD.bazel
│   │   ├── testing/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── fixtures.rs
│   │   │   │   └── faults.rs
│   │   │   └── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── go/
│   │   ├── audit/
│   │   │   ├── event.go
│   │   │   ├── writer.go
│   │   │   ├── writer_test.go
│   │   │   └── BUILD.bazel
│   │   ├── auth/
│   │   │   ├── principal.go
│   │   │   ├── authorizer.go
│   │   │   ├── delegation.go
│   │   │   ├── authorizer_test.go
│   │   │   └── BUILD.bazel
│   │   ├── clock/
│   │   │   ├── clock.go
│   │   │   ├── fake_clock.go
│   │   │   ├── clock_test.go
│   │   │   └── BUILD.bazel
│   │   ├── connectx/
│   │   │   ├── interceptors.go
│   │   │   ├── errors.go
│   │   │   ├── deadlines.go
│   │   │   └── BUILD.bazel
│   │   ├── controller/
│   │   │   ├── reconciler.go
│   │   │   ├── result.go
│   │   │   ├── backoff.go
│   │   │   ├── reconciler_test.go
│   │   │   └── BUILD.bazel
│   │   ├── faults/
│   │   │   ├── classification.go
│   │   │   ├── retryability.go
│   │   │   └── BUILD.bazel
│   │   ├── grpcx/
│   │   │   ├── interceptors.go
│   │   │   ├── errors.go
│   │   │   ├── deadlines.go
│   │   │   └── BUILD.bazel
│   │   ├── identifiers/
│   │   │   ├── resource_id.go
│   │   │   ├── resource_reference.go
│   │   │   └── BUILD.bazel
│   │   ├── kubernetes/
│   │   │   ├── client.go
│   │   │   ├── conditions.go
│   │   │   ├── owner_references.go
│   │   │   └── BUILD.bazel
│   │   ├── middleware/
│   │   │   ├── request_context.go
│   │   │   ├── recovery.go
│   │   │   ├── telemetry.go
│   │   │   └── BUILD.bazel
│   │   ├── observability/
│   │   │   ├── metrics.go
│   │   │   ├── tracing.go
│   │   │   ├── logging.go
│   │   │   └── BUILD.bazel
│   │   ├── servicekit/
│   │   │   ├── lifecycle.go
│   │   │   ├── health.go
│   │   │   ├── shutdown.go
│   │   │   └── BUILD.bazel
│   │   ├── storage/
│   │   │   ├── transaction.go
│   │   │   ├── outbox.go
│   │   │   ├── leases.go
│   │   │   └── BUILD.bazel
│   │   ├── testing/
│   │   │   ├── database.go
│   │   │   ├── queue.go
│   │   │   ├── faults.go
│   │   │   └── BUILD.bazel
│   │   ├── component.yaml
│   │   ├── README.md
│   │   └── numconv/
│   │       ├── BUILD.bazel
│   │       ├── conversion.go
│   │       └── conversion_test.go
│   ├── typescript/
│   │   ├── config/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   └── resolution.ts
│   │   │   ├── tests/
│   │   │   │   └── resolution.test.ts
│   │   │   └── BUILD.bazel
│   │   ├── design_system/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   └── tokens.ts
│   │   │   ├── tests/
│   │   │   │   └── accessibility.test.ts
│   │   │   └── BUILD.bazel
│   │   ├── observability/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   └── tracing.ts
│   │   │   ├── tests/
│   │   │   │   └── tracing.test.ts
│   │   │   └── BUILD.bazel
│   │   ├── testing/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   └── fixtures.ts
│   │   │   └── BUILD.bazel
│   │   ├── web/
│   │   │   ├── package.json
│   │   │   ├── src/
│   │   │   │   ├── index.ts
│   │   │   │   ├── errors.ts
│   │   │   │   └── pagination.ts
│   │   │   └── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── BUILD.bazel
│   └── README.md
├── bio/
│   ├── schemas/
│   │   ├── atom/
│   │   │   ├── atom.schema.json
│   │   │   └── atom_conformance.json
│   │   ├── residue/
│   │   │   ├── residue.schema.json
│   │   │   └── residue_conformance.json
│   │   ├── chain/
│   │   │   ├── chain.schema.json
│   │   │   └── chain_conformance.json
│   │   ├── assembly/
│   │   │   ├── assembly.schema.json
│   │   │   └── assembly_conformance.json
│   │   ├── sequence/
│   │   │   ├── sequence.schema.json
│   │   │   └── sequence_conformance.json
│   │   └── feature/
│   │       ├── feature.schema.json
│   │       └── feature_conformance.json
│   ├── entities/
│   │   ├── rust/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   ├── atom.rs
│   │   │   │   ├── residue.rs
│   │   │   │   ├── chain.rs
│   │   │   │   └── assembly.rs
│   │   │   └── BUILD.bazel
│   │   ├── python/
│   │   │   ├── __init__.py
│   │   │   ├── atom.py
│   │   │   ├── residue.py
│   │   │   ├── chain.py
│   │   │   ├── assembly.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── conformance/
│   │   │   ├── entity_cases.json
│   │   │   └── test_cross_language_entities.py
│   │   └── README.md
│   ├── formats/
│   │   ├── rust/
│   │   │   ├── fasta/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── a3m/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── stockholm/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── mmcif/
│   │   │   │   ├── lexer.rs
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── pdb/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── ccd/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── components.rs
│   │   │   │   └── validation.rs
│   │   │   ├── sdf/
│   │   │   │   ├── parser.rs
│   │   │   │   ├── writer.rs
│   │   │   │   └── validation.rs
│   │   │   ├── Cargo.toml
│   │   │   └── BUILD.bazel
│   │   ├── python/
│   │   │   ├── __init__.py
│   │   │   ├── bindings.py
│   │   │   ├── reference_parser.py
│   │   │   ├── py.typed
│   │   │   └── BUILD.bazel
│   │   ├── fixtures/
│   │   │   ├── valid/
│   │   │   │   ├── minimal_protein.cif
│   │   │   │   ├── minimal_rna.cif
│   │   │   │   ├── minimal_dna.cif
│   │   │   │   ├── minimal_ligand.sdf
│   │   │   │   ├── minimal_alignment.a3m
│   │   │   │   └── minimal_alignment.sto
│   │   │   ├── malformed/
│   │   │   │   ├── truncated_mmcif.cif
│   │   │   │   ├── duplicate_atom_identifier.cif
│   │   │   │   ├── invalid_stockholm.sto
│   │   │   │   ├── invalid_sdf.sdf
│   │   │   │   └── invalid_fasta.fasta
│   │   │   └── adversarial/
│   │   │       ├── oversized_token.cif
│   │   │       ├── deep_nesting.cif
│   │   │       ├── expansion_limit.cif
│   │   │       ├── decompression_limits.json
│   │   │       └── path_traversal_archive_manifest.json
│   │   └── conformance/
│   │       ├── format_cases.yaml
│   │       └── test_parser_parity.py
│   ├── chemistry/
│   │   ├── python/
│   │   │   ├── elements.py
│   │   │   ├── bonds.py
│   │   │   ├── components.py
│   │   │   └── stereochemistry.py
│   │   └── tests/
│   │       ├── test_elements.py
│   │       ├── test_bonds.py
│   │       └── test_stereochemistry.py
│   ├── sequences/
│   │   ├── python/
│   │   │   ├── alphabet.py
│   │   │   ├── canonicalization.py
│   │   │   └── identity.py
│   │   └── tests/
│   │       ├── test_canonicalization.py
│   │       └── test_identity.py
│   ├── structures/
│   │   ├── python/
│   │   │   ├── coordinates.py
│   │   │   ├── frames.py
│   │   │   ├── assemblies.py
│   │   │   └── validation.py
│   │   └── tests/
│   │       ├── test_frames.py
│   │       ├── test_assemblies.py
│   │       └── test_validation.py
│   ├── alignments/
│   │   ├── python/
│   │   │   ├── alignment.py
│   │   │   ├── identity.py
│   │   │   └── clustering.py
│   │   ├── rust/
│   │   │   ├── Cargo.toml
│   │   │   └── src/
│   │   │       ├── lib.rs
│   │   │       ├── identity.rs
│   │   │       └── clustering.rs
│   │   └── tests/
│   │       ├── test_identity_parity.py
│   │       └── test_clustering.py
│   ├── featurization/
│   │   ├── contracts/
│   │   │   ├── feature_id.py
│   │   │   ├── feature_definition.py
│   │   │   ├── feature_requirement.py
│   │   │   ├── feature_requirement_set.py
│   │   │   ├── dimension_semantics.py
│   │   │   ├── determinism.py
│   │   │   └── leakage.py
│   │   ├── catalog/
│   │   │   ├── feature_catalog.py
│   │   │   ├── sequence.yaml
│   │   │   ├── structure.yaml
│   │   │   └── geometry.yaml
│   │   ├── transforms/
│   │   │   ├── feature_transform.py
│   │   │   ├── feature_transform_spec.py
│   │   │   └── feature_transform_receipt.py
│   │   ├── python/
│   │   │   ├── sequence_features.py
│   │   │   ├── pair_features.py
│   │   │   ├── structure_features.py
│   │   │   └── geometry_features.py
│   │   ├── rust/
│   │   │   ├── Cargo.toml
│   │   │   └── src/
│   │   │       ├── lib.rs
│   │   │       ├── sequence.rs
│   │   │       ├── pair.rs
│   │   │       ├── structure.rs
│   │   │       └── geometry.rs
│   │   ├── schemas/
│   │   │   ├── feature_value.schema.json
│   │   │   └── tensor_layout.schema.json
│   │   ├── validation/
│   │   │   ├── feature_validator.py
│   │   │   ├── biological_invariants.py
│   │   │   └── shape_semantics.py
│   │   ├── parity/
│   │   │   ├── feature_cases.json
│   │   │   ├── test_feature_parity.py
│   │   │   └── test_key_inputs.py
│   │   └── tests/
│   │       ├── test_feature_registry.py
│   │       ├── test_sequence_features.py
│   │       ├── test_pair_features.py
│   │       ├── test_structure_features.py
│   │       └── test_geometry_features.py
│   ├── bindings/
│   │   ├── python/
│   │   │   ├── __init__.py
│   │   │   ├── formats.py
│   │   │   ├── features.py
│   │   │   └── py.typed
│   │   └── abi/
│   │       ├── abi_manifest.json
│   │       └── compatibility_test.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── data/
│   ├── contracts/
│   │   ├── source.py
│   │   ├── snapshot.py
│   │   ├── lineage.py
│   │   ├── validation.py
│   │   └── BUILD.bazel
│   ├── connectors/
│   │   ├── contracts/
│   │   │   ├── connector.py
│   │   │   ├── source_cursor.py
│   │   │   └── fetch_result.py
│   │   ├── pdb/
│   │   │   ├── connector.py
│   │   │   ├── release_index.py
│   │   │   └── license_policy.py
│   │   ├── uniprot/
│   │   │   ├── connector.py
│   │   │   ├── release_index.py
│   │   │   └── license_policy.py
│   │   ├── rnacentral/
│   │   │   ├── connector.py
│   │   │   ├── release_index.py
│   │   │   └── license_policy.py
│   │   ├── ccd/
│   │   │   ├── connector.py
│   │   │   ├── release_index.py
│   │   │   └── license_policy.py
│   │   └── tests/
│   │       ├── test_connector_contract.py
│   │       ├── test_cursor_resume.py
│   │       └── test_license_policy.py
│   ├── ingestion/
│   │   ├── fetch/
│   │   │   ├── request.py
│   │   │   ├── streaming_fetch.py
│   │   │   └── source_auth.py
│   │   ├── resume/
│   │   │   ├── cursor_store.py
│   │   │   ├── partial_object.py
│   │   │   └── resume_policy.py
│   │   ├── manifests/
│   │   │   ├── raw_snapshot.py
│   │   │   └── fetch_receipt.py
│   │   ├── rate_limits/
│   │   │   ├── source_budget.py
│   │   │   └── adaptive_limiter.py
│   │   ├── integrity/
│   │   │   ├── source_digest.py
│   │   │   ├── object_verification.py
│   │   │   └── quarantine.py
│   │   └── tests/
│   │       ├── test_resume.py
│   │       ├── test_rate_limit.py
│   │       └── test_integrity_failure.py
│   ├── normalization/
│   │   ├── normalization_plan.py
│   │   ├── canonical_record.py
│   │   └── normalization_receipt.py
│   ├── curation/
│   │   ├── curation_policy.py
│   │   ├── filter_reason.py
│   │   └── curated_record.py
│   ├── validation/
│   │   ├── schema/
│   │   │   ├── schema_validator.py
│   │   │   └── validation_report.py
│   │   ├── biological/
│   │   │   ├── structure_validator.py
│   │   │   └── sequence_validator.py
│   │   ├── policy/
│   │   │   ├── source_policy.py
│   │   │   └── data_class_policy.py
│   │   └── quality/
│   │       ├── quality_score.py
│   │       └── quality_gate.py
│   ├── deduplication/
│   │   ├── record_key.py
│   │   ├── cluster_deduplicator.py
│   │   └── deduplication_receipt.py
│   ├── leakage/
│   │   ├── sequence_identity.py
│   │   ├── split_isolation.py
│   │   └── leakage_report.py
│   ├── splits/
│   │   ├── split_contract.py
│   │   ├── deterministic_split.py
│   │   └── split_receipt.py
│   ├── sampling/
│   │   ├── sample_key.py
│   │   ├── deterministic_sampler.py
│   │   └── sampling_receipt.py
│   ├── transforms/
│   │   ├── contracts/
│   │   │   ├── transform.py
│   │   │   ├── transform_spec.py
│   │   │   ├── transform_context.py
│   │   │   ├── transform_receipt.py
│   │   │   ├── transform_semantic_key.py
│   │   │   ├── cardinality.py
│   │   │   ├── ordering.py
│   │   │   ├── state_scope.py
│   │   │   ├── materialization.py
│   │   │   └── profiles/
│   │   │       ├── map.py
│   │   │       ├── filter.py
│   │   │       ├── explode.py
│   │   │       ├── join.py
│   │   │       ├── aggregate.py
│   │   │       ├── fitted.py
│   │   │       ├── semantic_feature.py
│   │   │       └── runtime_stochastic.py
│   │   ├── graph/
│   │   │   ├── node.py
│   │   │   ├── edge.py
│   │   │   ├── transform_graph.py
│   │   │   ├── validation.py
│   │   │   └── canonicalization.py
│   │   ├── planning/
│   │   │   ├── execution_plan.py
│   │   │   ├── planner.py
│   │   │   ├── partition_plan.py
│   │   │   ├── cost_model.py
│   │   │   └── materialization_cost.py
│   │   ├── catalog/
│   │   │   └── transform_catalog.py
│   │   ├── implementations/
│   │   │   ├── implementation_registry.py
│   │   │   ├── operator_identity.py
│   │   │   └── compatibility.py
│   │   ├── fitting/
│   │   │   ├── fit_semantic_key.py
│   │   │   ├── transform_state.py
│   │   │   ├── fit_receipt.py
│   │   │   └── fit_validation.py
│   │   ├── lineage/
│   │   │   ├── lineage_map.py
│   │   │   ├── membership_index.py
│   │   │   └── compaction.py
│   │   ├── execution/
│   │   │   ├── executor.py
│   │   │   ├── local_runner.py
│   │   │   ├── stream_runner.py
│   │   │   ├── partition_runner.py
│   │   │   └── resource_limits.py
│   │   ├── validation/
│   │   │   ├── schema_transition.py
│   │   │   ├── determinism.py
│   │   │   ├── side_effects.py
│   │   │   └── receipt_validation.py
│   │   ├── optimization/
│   │   │   ├── projection_pushdown.py
│   │   │   ├── fusion.py
│   │   │   ├── partition_coalescing.py
│   │   │   └── optimization_receipt.py
│   │   ├── rust/
│   │   │   ├── Cargo.toml
│   │   │   └── src/
│   │   │       ├── lib.rs
│   │   │       ├── executor.rs
│   │   │       ├── stream.rs
│   │   │       ├── partition.rs
│   │   │       └── arrow_bridge.rs
│   │   ├── fixtures/
│   │   │   ├── transform_cases.yaml
│   │   │   ├── partition_cases.yaml
│   │   │   ├── fitted_state_cases.yaml
│   │   │   └── lineage_map_cases.yaml
│   │   └── tests/
│   │       ├── test_transform_spec.py
│   │       ├── test_transform_profiles.py
│   │       ├── test_transform_graph.py
│   │       ├── test_semantic_execution_identity.py
│   │       ├── test_cardinality.py
│   │       ├── test_ordering.py
│   │       ├── test_receipt.py
│   │       ├── test_fit_state.py
│   │       ├── test_fitting_scope_leakage.py
│   │       ├── test_lineage_map.py
│   │       ├── test_cost_aware_materialization.py
│   │       ├── test_determinism.py
│   │       └── test_optimization_equivalence.py
│   ├── featurization/
│   │   ├── planning/
│   │   │   ├── feature_plan.py
│   │   │   ├── feature_plan_validation.py
│   │   │   ├── lower_to_transform_graph.py
│   │   │   └── cache_projection.py
│   │   ├── derivation/
│   │   │   ├── operator.py
│   │   │   ├── feature_implementation_registry.py
│   │   │   ├── implementation_identity.py
│   │   │   └── canonical_parameters.py
│   │   ├── resolution/
│   │   │   ├── resolver.py
│   │   │   ├── feature_key.py
│   │   │   ├── cache_partition.py
│   │   │   ├── coverage.py
│   │   │   └── explain.py
│   │   ├── materialization/
│   │   │   ├── materialize.py
│   │   │   ├── validation.py
│   │   │   ├── atomic_publication.py
│   │   │   └── determinism_guard.py
│   │   ├── manifests/
│   │   │   ├── feature_bundle.py
│   │   │   ├── feature_coverage.py
│   │   │   └── feature_readiness.py
│   │   ├── storage/
│   │   │   ├── feature_index.py
│   │   │   ├── local_index.py
│   │   │   └── index_rebuild.py
│   │   ├── feature_sharding.py
│   │   ├── feature_receipt.py
│   │   └── tests/
│   │       ├── test_feature_key.py
│   │       ├── test_feature_plan_lowering.py
│   │       ├── test_cache_projection.py
│   │       ├── test_atomic_publication.py
│   │       ├── test_determinism_guard.py
│   │       └── test_coverage.py
│   ├── catalog/
│   │   ├── dataset_catalog.py
│   │   ├── alias_policy.py
│   │   └── publication.py
│   ├── storage/
│   │   ├── raw_object_store.py
│   │   ├── shard_store.py
│   │   └── atomic_publication.py
│   ├── fixtures/
│   │   ├── pdb_snapshot_index.json
│   │   ├── synthetic_records.json
│   │   └── malformed_records.json
│   ├── tools/
│   │   ├── snapshot_source.py
│   │   ├── publish_dataset.py
│   │   ├── verify_lineage.py
│   │   ├── transform_validate.py
│   │   ├── transform_plan.py
│   │   ├── transform_run.py
│   │   ├── transform_explain.py
│   │   ├── feature_explain.py
│   │   └── rebuild_feature_index.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── kernels/
│   ├── api/
│   │   ├── operation.py
│   │   ├── signature.py
│   │   ├── capability.py
│   │   ├── result.py
│   │   ├── BUILD.bazel
│   │   ├── __init__.py
│   │   ├── backward.py
│   │   ├── effects.py
│   │   ├── environment.py
│   │   ├── errors.py
│   │   ├── expressions.py
│   │   ├── forward.py
│   │   ├── gradient.py
│   │   ├── implementation.py
│   │   ├── kernel.py
│   │   ├── launch.py
│   │   ├── numerics.py
│   │   ├── output.py
│   │   ├── program_group.py
│   │   ├── qualification.py
│   │   ├── schedule.py
│   │   ├── workload.py
│   │   └── tests/
│   │       ├── BUILD.bazel
│   │       ├── __init__.py
│   │       ├── test_contracts.py
│   │       └── test_expressions.py
│   ├── common/
│   │   ├── layouts/
│   │   │   ├── layout.py
│   │   │   ├── strides.py
│   │   │   └── validation.py
│   │   ├── numerics/
│   │   │   ├── tolerances.py
│   │   │   ├── error_metrics.py
│   │   │   └── accumulation.py
│   │   └── tensor_contracts/
│   │       ├── shape.py
│   │       ├── dtype.py
│   │       └── device.py
│   ├── registry/
│   │   ├── kernel_registry.py
│   │   ├── provider_record.py
│   │   └── registration_policy.py
│   ├── dispatch/
│   │   ├── dispatch_key.py
│   │   ├── capability_match.py
│   │   └── fallback.py
│   ├── attention/
│   │   ├── reference.py
│   │   ├── dispatch.py
│   │   ├── spec.py
│   │   ├── tests/
│   │   │   ├── test_reference.py
│   │   │   ├── test_dispatch.py
│   │   │   ├── test_backward.py
│   │   │   ├── test_determinism.py
│   │   │   ├── test_boundaries.py
│   │   │   └── BUILD.bazel
│   │   └── benchmarks/
│   │       ├── benchmark_attention.py
│   │       ├── cases.yaml
│   │       └── BUILD.bazel
│   ├── pairformer/
│   │   ├── triangle_attention/
│   │   │   ├── reference.py
│   │   │   ├── spec.py
│   │   │   ├── dispatch.py
│   │   │   ├── BUILD.bazel
│   │   │   ├── __init__.py
│   │   │   ├── tests/
│   │   │   │   ├── __init__.py
│   │   │   │   └── test_triangle_attention.py
│   │   │   └── tilelang.py
│   │   ├── triangle_multiplication/
│   │   │   ├── reference.py
│   │   │   ├── spec.py
│   │   │   ├── dispatch.py
│   │   │   ├── BUILD.bazel
│   │   │   ├── README.md
│   │   │   ├── __init__.py
│   │   │   ├── test_triangle_multiplication.py
│   │   │   └── tilelang.py
│   │   ├── outer_product_mean/
│   │   │   ├── reference.py
│   │   │   ├── spec.py
│   │   │   ├── dispatch.py
│   │   │   ├── BUILD.bazel
│   │   │   ├── __init__.py
│   │   │   ├── tests/
│   │   │   │   └── test_outer_product_mean.py
│   │   │   └── tilelang.py
│   │   ├── transition/
│   │   │   ├── reference.py
│   │   │   ├── spec.py
│   │   │   ├── dispatch.py
│   │   │   ├── BUILD.bazel
│   │   │   ├── __init__.py
│   │   │   ├── test_transition.py
│   │   │   └── tilelang.py
│   │   ├── tests/
│   │   │   ├── test_triangle_attention.py
│   │   │   ├── test_triangle_multiplication.py
│   │   │   ├── test_outer_product_mean.py
│   │   │   ├── test_transition.py
│   │   │   ├── test_dispatch.py
│   │   │   └── BUILD.bazel
│   │   ├── benchmarks/
│   │   │   ├── benchmark_pairformer.py
│   │   │   ├── cases.yaml
│   │   │   └── BUILD.bazel
│   │   └── pair_weighted_average/
│   │       ├── dispatch.py
│   │       ├── reference.py
│   │       ├── spec.py
│   │       ├── BUILD.bazel
│   │       ├── __init__.py
│   │       ├── test_tilelang.py
│   │       └── tilelang.py
│   ├── diffusion/
│   │   ├── reference.py
│   │   ├── spec.py
│   │   ├── dispatch.py
│   │   ├── test_reference.py
│   │   └── benchmark.py
│   ├── normalization/
│   │   ├── reference.py
│   │   ├── spec.py
│   │   ├── dispatch.py
│   │   ├── test_reference.py
│   │   └── benchmark.py
│   ├── qualification/
│   │   ├── correctness/
│   │   │   ├── forward_parity.py
│   │   │   └── backward_parity.py
│   │   ├── gradients/
│   │   │   ├── gradient_check.py
│   │   │   └── gradient_tolerance.py
│   │   ├── determinism/
│   │   │   ├── determinism_test.py
│   │   │   └── replay_test.py
│   │   ├── performance/
│   │   │   ├── benchmark_policy.py
│   │   │   └── regression_gate.py
│   │   ├── hardware/
│   │   │   ├── hardware_envelope.py
│   │   │   └── qualification_matrix.py
│   │   └── reports/
│   │       ├── qualification_report.py
│   │       └── report_schema.json
│   ├── benchmarks/
│   │   ├── benchmark_runner.py
│   │   └── benchmark_cases.yaml
│   ├── tests/
│   │   ├── test_registry.py
│   │   ├── test_dispatch_fallback.py
│   │   └── test_reference_contract.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   ├── README.md
│   └── native/
│       ├── BUILD.bazel
│       ├── CMakeLists.txt
│       ├── IMPLEMENTATION_STATUS.md
│       ├── MIGRATION.md
│       ├── README.md
│       ├── __init__.py
│       ├── cmake/
│       │   └── MindcladeTorchStable.cmake
│       ├── codegen/
│       │   ├── __init__.py
│       │   ├── discover.py
│       │   ├── generate.py
│       │   ├── parse_literal_ast.py
│       │   ├── schema.py
│       │   └── callable_abi.py
│       ├── component.yaml
│       ├── cuda/
│       │   ├── CMakeLists.txt
│       │   ├── README.md
│       │   ├── operation_registry.cpp
│       │   ├── device_architecture.cpp
│       │   └── device_architecture.h
│       ├── generated/
│       │   ├── __init__.py
│       │   ├── native_ops.generated.bzl
│       │   ├── native_ops.generated.cmake
│       │   ├── native_ops.json
│       │   ├── operation_registry.generated.cpp
│       │   ├── python_registration_generated.py
│       │   ├── registration.generated.cpp
│       │   ├── tilelang_capabilities.json
│       │   ├── launcher_plans.generated.cpp
│       │   ├── qualified_capabilities.generated.cpp
│       │   └── qualified_capabilities.generated.json
│       ├── manifests/
│       │   ├── benchmark.schema.json
│       │   ├── native_ops.schema.json
│       │   ├── performance_policy.json
│       │   ├── qualification.schema.json
│       │   ├── tilelang_profiles.sm100.json
│       │   ├── tilelang_profiles.sm90.json
│       │   ├── tilelang_capabilities.schema.json
│       │   ├── pairformer_gpu_qualification.json
│       │   ├── pairformer_gpu_qualification.schema.json
│       │   ├── qualification_release.schema.json
│       │   ├── qualified_capability_index.json
│       │   └── qualified_capability_index.schema.json
│       ├── python/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   ├── qualification.py
│       │   ├── reference_runtime.py
│       │   ├── registration.py
│       │   ├── capability_index.py
│       │   └── gpu_qualification.py
│       ├── stable_abi/
│       │   ├── CMakeLists.txt
│       │   ├── abi_manifest.json
│       │   ├── registration.cpp
│       │   ├── tensor_bridge.cpp
│       │   ├── tensor_bridge.h
│       │   ├── node_launch_abi.h
│       │   ├── node_launch_bridge.cpp
│       │   ├── node_launch_bridge.h
│       │   ├── qualified_capability_selector.cpp
│       │   └── qualified_capability_table.h
│       ├── tests/
│       │   ├── pytest_runner.py
│       │   ├── test_abi_compatibility.py
│       │   ├── test_autograd.py
│       │   ├── test_build_policy.py
│       │   ├── test_cmake_policy.py
│       │   ├── test_codegen.py
│       │   ├── test_codegen_drift.py
│       │   ├── test_discovery.py
│       │   ├── test_export.py
│       │   ├── test_fake_tensor.py
│       │   ├── test_loader_policy.py
│       │   ├── test_manifest.py
│       │   ├── test_namespace.py
│       │   ├── test_opcheck.py
│       │   ├── test_parse_literal_ast.py
│       │   ├── test_policy.py
│       │   ├── test_qualification.py
│       │   ├── test_schema.py
│       │   ├── test_reference_runtime.py
│       │   ├── test_schema_manifest.py
│       │   ├── test_tilelang_swizzle.py
│       │   ├── test_tilelang_targets.py
│       │   ├── test_tilelang_tma.py
│       │   ├── test_capability_index.py
│       │   ├── test_gpu_qualification.py
│       │   └── test_qualified_capability_selector.py
│       └── tilelang/
│           ├── README.md
│           ├── __init__.py
│           ├── build.py
│           ├── decorator.py
│           ├── manifest.py
│           ├── model.py
│           ├── registry.py
│           ├── swizzle.py
│           ├── targets.py
│           └── tma.py
├── runtime/
│   ├── distributed/
│   │   ├── mesh/
│   │   │   ├── mesh_contract.py
│   │   │   ├── device_mesh.py
│   │   │   └── placements.py
│   │   ├── collectives/
│   │   │   ├── collective_contract.py
│   │   │   ├── nccl_backend.py
│   │   │   └── collective_timeout.py
│   │   ├── topology/
│   │   │   ├── topology_manifest.py
│   │   │   └── topology_validation.py
│   │   ├── rendezvous/
│   │   │   ├── rendezvous_contract.py
│   │   │   └── static_rendezvous.py
│   │   └── health/
│   │       ├── rank_health.py
│   │       └── collective_watchdog.py
│   ├── dispatch/
│   │   ├── execution_target.py
│   │   └── target_selection.py
│   ├── memory/
│   │   ├── memory_budget.py
│   │   ├── tensor_lifetime.py
│   │   └── oom_policy.py
│   ├── precision/
│   │   ├── dtype_policy.py
│   │   ├── operation_policy.py
│   │   └── numerical_guard.py
│   ├── compilation/
│   │   ├── compile_contract.py
│   │   ├── compile_key.py
│   │   └── cache_policy.py
│   ├── rng/
│   │   ├── rng_contract.py
│   │   ├── seed_derivation.py
│   │   └── state_capture.py
│   ├── extensions/
│   │   ├── rust/
│   │   │   ├── Cargo.toml
│   │   │   ├── src/
│   │   │   │   ├── lib.rs
│   │   │   │   └── abi.rs
│   │   │   └── BUILD.bazel
│   │   └── python/
│   │       ├── __init__.py
│   │       ├── bindings.py
│   │       └── abi_check.py
│   ├── diagnostics/
│   │   ├── runtime_snapshot.py
│   │   ├── memory_snapshot.py
│   │   └── distributed_trace.py
│   ├── testing/
│   │   ├── fake_mesh.py
│   │   ├── fault_injection.py
│   │   └── numerical_assertions.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── models/
│   ├── api/
│   │   ├── model.py
│   │   ├── batch.py
│   │   ├── outputs.py
│   │   ├── capabilities.py
│   │   └── serialization.py
│   ├── common/
│   │   ├── configuration/
│   │   │   ├── model_config.py
│   │   │   ├── config_validation.py
│   │   │   └── config_digest.py
│   │   ├── initialization/
│   │   │   ├── parameter_init.py
│   │   │   └── init_policy.py
│   │   ├── masking/
│   │   │   ├── sequence_mask.py
│   │   │   ├── pair_mask.py
│   │   │   └── coordinate_mask.py
│   │   ├── embeddings/
│   │   │   ├── sequence_embedding.py
│   │   │   ├── pair_embedding.py
│   │   │   └── time_embedding.py
│   │   └── losses/
│   │       ├── loss_contract.py
│   │       ├── loss_reduction.py
│   │       └── masked_losses.py
│   ├── components/
│   │   ├── sequence/
│   │   │   ├── sequence_encoder.py
│   │   │   └── sequence_transition.py
│   │   ├── pairformer/
│   │   │   ├── pairformer_block.py
│   │   │   ├── triangle_attention.py
│   │   │   ├── triangle_multiplication.py
│   │   │   └── outer_product_mean.py
│   │   ├── diffusion/
│   │   │   ├── noise_schedule.py
│   │   │   ├── coordinate_denoiser.py
│   │   │   └── diffusion_objective.py
│   │   ├── confidence/
│   │   │   ├── confidence_head.py
│   │   │   └── calibration_head.py
│   │   ├── geometry/
│   │   │   ├── rigid_frames.py
│   │   │   ├── coordinate_updates.py
│   │   │   └── distogram.py
│   │   └── heads/
│   │       ├── structure_head.py
│   │       └── coordinate_diffusion_head.py
│   ├── families/
│   │   └── clade/
│   │       ├── README.md
│   │       └── cladefold/
│   │           ├── configuration/
│   │           │   ├── cladefold_q0.py
│   │           │   └── configuration.schema.json
│   │           ├── architecture/
│   │           │   ├── cladefold.py
│   │           │   ├── pairformer_stack.py
│   │           │   ├── structure_head.py
│   │           │   └── diffusion_head.py
│   │           ├── capabilities/
│   │           │   ├── capability_manifest.py
│   │           │   ├── input_contract.py
│   │           │   └── output_contract.py
│   │           ├── features/
│   │           │   ├── requirements.py
│   │           │   ├── requirement_set.py
│   │           │   ├── derived_features.py
│   │           │   ├── model_feature_view.py
│   │           │   ├── transforms.py
│   │           │   ├── tensor_views.py
│   │           │   ├── tensorize.py
│   │           │   ├── packing.py
│   │           │   └── validation.py
│   │           ├── checkpoints/
│   │           │   ├── state_mapping.py
│   │           │   └── checkpoint_migration.py
│   │           ├── conversion/
│   │           │   ├── bundle_export.py
│   │           │   └── bundle_import.py
│   │           ├── inference/
│   │           │   ├── inference_pipeline.py
│   │           │   └── default_sampling.py
│   │           ├── qualification/
│   │           │   ├── sqp001.yaml
│   │           │   ├── numerical_gates.py
│   │           │   └── inference_parity.py
│   │           ├── tests/
│   │           │   ├── test_shapes.py
│   │           │   ├── test_overfit_128.py
│   │           │   ├── test_checkpoint_resume.py
│   │           │   └── test_inference_parity.py
│   │           ├── BUILD.bazel
│   │           ├── component.yaml
│   │           └── README.md
│   ├── registry/
│   │   ├── model_definition_registry.py
│   │   ├── capability_index.py
│   │   └── alias_policy.py
│   ├── packaging/
│   │   ├── model_bundle.py
│   │   ├── bundle_manifest.py
│   │   └── bundle_signing.py
│   ├── conversion/
│   │   ├── state_mapping.py
│   │   └── conversion_receipt.py
│   ├── tests/
│   │   ├── test_model_contract.py
│   │   ├── test_bundle_roundtrip.py
│   │   └── test_registry_aliases.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── training/
│   ├── api/
│   │   ├── task.py
│   │   ├── objective.py
│   │   ├── loss.py
│   │   ├── phase.py
│   │   ├── program.py
│   │   ├── state.py
│   │   ├── optimization.py
│   │   ├── parallelism.py
│   │   ├── precision.py
│   │   ├── checkpoint.py
│   │   ├── callbacks.py
│   │   ├── reproducibility.py
│   │   └── events.py
│   ├── core/
│   │   ├── trainer/
│   │   │   ├── trainer.py
│   │   │   ├── lifecycle.py
│   │   │   ├── step.py
│   │   │   ├── phase_graph.py
│   │   │   ├── progress_commit.py
│   │   │   └── fault_policy.py
│   │   ├── state/
│   │   │   ├── identity.py
│   │   │   ├── schema.py
│   │   │   ├── registry.py
│   │   │   ├── epochs.py
│   │   │   └── serialization.py
│   │   ├── optimization/
│   │   │   ├── update_graph.py
│   │   │   ├── parameter_groups.py
│   │   │   ├── reductions.py
│   │   │   ├── clipping.py
│   │   │   ├── schedules.py
│   │   │   ├── ema.py
│   │   │   └── health.py
│   │   ├── data/
│   │   │   ├── manifest.py
│   │   │   ├── progress.py
│   │   │   ├── receipt.py
│   │   │   ├── deterministic.py
│   │   │   ├── sharding.py
│   │   │   ├── batching.py
│   │   │   ├── packing.py
│   │   │   ├── buckets.py
│   │   │   ├── work_units.py
│   │   │   ├── feature_resolver.py
│   │   │   ├── batch_recipe.py
│   │   │   ├── feature_readiness.py
│   │   │   ├── batch_transforms.py
│   │   │   └── prefetch.py
│   │   └── callbacks/
│   │       ├── bus.py
│   │       ├── actions.py
│   │       ├── ordering.py
│   │       └── delivery.py
│   ├── execution/
│   │   ├── ir/
│   │   │   ├── topology.py
│   │   │   ├── mesh.py
│   │   │   ├── placements.py
│   │   │   ├── passes.py
│   │   │   ├── pipeline.py
│   │   │   ├── collectives.py
│   │   │   ├── compiled_regions.py
│   │   │   └── executable.py
│   │   ├── planning/
│   │   │   ├── analysis.py
│   │   │   ├── constraints.py
│   │   │   ├── partition.py
│   │   │   ├── cost_model.py
│   │   │   ├── memory_model.py
│   │   │   └── planner.py
│   │   ├── passes/
│   │   │   ├── replacement.py
│   │   │   ├── tensor_parallel.py
│   │   │   ├── expert_parallel.py
│   │   │   ├── pipeline_partition.py
│   │   │   ├── activation_policy.py
│   │   │   ├── fsdp.py
│   │   │   ├── precision.py
│   │   │   ├── optimizer_state.py
│   │   │   ├── compile_regions.py
│   │   │   └── cuda_graphs.py
│   │   ├── schedules/
│   │   │   ├── registry.py
│   │   │   ├── eager.py
│   │   │   ├── gpipe.py
│   │   │   ├── one_f_one_b.py
│   │   │   ├── interleaved.py
│   │   │   └── zero_bubble.py
│   │   ├── native/
│   │   │   ├── engine.py
│   │   │   ├── program.py
│   │   │   ├── bootstrap.py
│   │   │   ├── materialize.py
│   │   │   ├── device_mesh.py
│   │   │   ├── distributed.py
│   │   │   ├── compilation.py
│   │   │   └── teardown.py
│   │   └── single_process/
│   │       ├── engine.py
│   │       └── program.py
│   ├── providers/
│   │   ├── capability_registry.py
│   │   ├── capability_contract.py
│   │   ├── compatibility_policy.py
│   │   └── pytorch/
│   │       ├── native_engine.py
│   │       ├── fsdp2_adapter.py
│   │       ├── dtensor_adapter.py
│   │       ├── dcp_adapter.py
│   │       └── nccl_adapter.py
│   ├── precision/
│   │   ├── policy.py
│   │   ├── native_amp.py
│   │   ├── scaling.py
│   │   ├── quantization_state.py
│   │   ├── recipes.py
│   │   └── qualification.py
│   ├── checkpointing/
│   │   ├── checkpoint_contract.py
│   │   ├── checkpoint_coordinator.py
│   │   ├── logical_state_schema.py
│   │   ├── epochs.py
│   │   ├── snapshot.py
│   │   ├── tiers.py
│   │   ├── manifest.py
│   │   ├── metadata.py
│   │   ├── dcp.py
│   │   ├── save_planner.py
│   │   ├── load_planner.py
│   │   ├── async_save.py
│   │   ├── backpressure.py
│   │   ├── inflight.py
│   │   ├── request_coalescing.py
│   │   ├── staging_budget.py
│   │   ├── atomic_commit.py
│   │   ├── resume.py
│   │   ├── reshard.py
│   │   ├── partial_load.py
│   │   ├── integrity.py
│   │   ├── migration.py
│   │   ├── conversion.py
│   │   ├── retention.py
│   │   ├── format.py
│   │   ├── serialization.py
│   │   ├── lineage.py
│   │   └── tests/
│   │       ├── test_checkpoint_contract.py
│   │       ├── test_atomic_commit.py
│   │       ├── test_async_save.py
│   │       ├── test_backpressure.py
│   │       ├── test_resume.py
│   │       ├── test_reshard.py
│   │       ├── test_partial_load.py
│   │       ├── test_integrity.py
│   │       ├── test_migration.py
│   │       ├── test_retention.py
│   │       └── BUILD.bazel
│   ├── tasks/
│   │   ├── pretraining/
│   │   │   ├── task.py
│   │   │   ├── objective.py
│   │   │   └── batch_contract.py
│   │   ├── supervised/
│   │   │   ├── task.py
│   │   │   ├── structure_objective.py
│   │   │   └── batch_contract.py
│   │   ├── contrastive/
│   │   │   ├── task.py
│   │   │   ├── contrastive_objective.py
│   │   │   └── batch_contract.py
│   │   ├── diffusion/
│   │   │   ├── task.py
│   │   │   ├── coordinate_objective.py
│   │   │   └── batch_contract.py
│   │   ├── flow/
│   │   │   ├── task.py
│   │   │   ├── flow_objective.py
│   │   │   └── batch_contract.py
│   │   ├── multitask/
│   │   │   ├── task.py
│   │   │   ├── loss_composition.py
│   │   │   └── batch_contract.py
│   │   └── distillation/
│   │       ├── task.py
│   │       ├── teacher_contract.py
│   │       └── batch_contract.py
│   ├── evaluation/
│   │   ├── scheduling.py
│   │   ├── snapshot.py
│   │   ├── leases.py
│   │   └── state.py
│   ├── telemetry/
│   │   ├── events.py
│   │   ├── metrics.py
│   │   ├── reductions.py
│   │   ├── structured_log.py
│   │   ├── tracing.py
│   │   ├── profiler.py
│   │   ├── memory.py
│   │   ├── flight_recorder.py
│   │   ├── step_capsule.py
│   │   └── shadow_qualification.py
│   ├── resilience/
│   │   ├── recovery.py
│   │   ├── preemption.py
│   │   └── failure_injection.py
│   ├── studies/
│   │   ├── definition.py
│   │   ├── trial.py
│   │   └── promotion.py
│   ├── qualification/
│   │   ├── contracts/
│   │   │   ├── qualification_profile.py
│   │   │   └── evidence_contract.py
│   │   ├── numerics/
│   │   │   ├── forward_parity.py
│   │   │   ├── loss_parity.py
│   │   │   └── tolerance_policy.py
│   │   ├── gradients/
│   │   │   ├── gradient_parity.py
│   │   │   └── finite_difference.py
│   │   ├── updates/
│   │   │   ├── optimizer_update_parity.py
│   │   │   └── step_progress.py
│   │   ├── distributed/
│   │   │   ├── rank_parity.py
│   │   │   ├── sharding_parity.py
│   │   │   └── collective_failure.py
│   │   ├── checkpointing/
│   │   │   ├── roundtrip.py
│   │   │   ├── reshard.py
│   │   │   └── partial_load.py
│   │   ├── recovery/
│   │   │   ├── resume_parity.py
│   │   │   ├── preemption.py
│   │   │   └── stale_attempt.py
│   │   ├── providers/
│   │   │   ├── provider_conformance.py
│   │   │   └── provider_rollback.py
│   │   ├── performance/
│   │   │   ├── throughput_budget.py
│   │   │   ├── memory_budget.py
│   │   │   └── regression_gate.py
│   │   └── long_horizon/
│   │       ├── drift_detection.py
│   │       └── stability_gate.py
│   ├── recipes/
│   │   ├── schema.py
│   │   ├── registry.py
│   │   ├── resolution.py
│   │   ├── smoke/
│   │   │   ├── cpu_contract.yaml
│   │   │   └── single_gpu.yaml
│   │   ├── pretraining/
│   │   │   ├── sequence.yaml
│   │   │   └── structure.yaml
│   │   ├── finetuning/
│   │   │   ├── supervised_structure.yaml
│   │   │   └── diffusion_structure.yaml
│   │   └── qualification/
│   │       ├── sqp001_cladefold_q0.yaml
│   │       ├── overfit_128.yaml
│   │       └── resume_parity.yaml
│   ├── cli/
│   │   ├── main.py
│   │   ├── plan.py
│   │   ├── study.py
│   │   ├── run.py
│   │   ├── resume.py
│   │   ├── qualify.py
│   │   ├── inspect.py
│   │   └── convert_checkpoint.py
│   ├── tests/
│   │   ├── test_task_contract.py
│   │   ├── test_phase_graph.py
│   │   ├── test_progress_commit.py
│   │   ├── test_checkpoint_roundtrip.py
│   │   └── test_resume_parity.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── evaluation/
│   ├── contracts/
│   │   ├── suite_contract.py
│   │   ├── metric_contract.py
│   │   └── evidence_contract.py
│   ├── harness/
│   │   ├── suite_loader.py
│   │   ├── evaluation_runner.py
│   │   ├── result_aggregation.py
│   │   └── evidence_writer.py
│   ├── metrics/
│   │   ├── geometry_metrics.py
│   │   ├── confidence_metrics.py
│   │   ├── calibration_metrics.py
│   │   └── statistical_tests.py
│   ├── suites/
│   │   ├── sequence/
│   │   │   ├── suite.yaml
│   │   │   └── sequence_evaluator.py
│   │   ├── structure/
│   │   │   ├── suite.yaml
│   │   │   └── structure_evaluator.py
│   │   ├── complexes/
│   │   │   ├── suite.yaml
│   │   │   └── complex_evaluator.py
│   │   ├── design/
│   │   │   ├── suite.yaml
│   │   │   └── design_evaluator.py
│   │   ├── confidence/
│   │   │   ├── suite.yaml
│   │   │   └── confidence_evaluator.py
│   │   ├── robustness/
│   │   │   ├── suite.yaml
│   │   │   └── robustness_evaluator.py
│   │   └── safety/
│   │       ├── suite.yaml
│   │       └── safety_evaluator.py
│   ├── datasets/
│   │   ├── snapshot_resolver.py
│   │   └── leakage_verification.py
│   ├── regression/
│   │   ├── baseline_registry.py
│   │   ├── comparison.py
│   │   └── promotion_gates.py
│   ├── reports/
│   │   ├── evaluation_report.py
│   │   └── model_card_projection.py
│   ├── fixtures/
│   │   └── sqp001/
│   │       ├── expected_metrics.json
│   │       └── tiny_predictions.json
│   ├── tests/
│   │   ├── test_suite_contract.py
│   │   ├── test_metric_aggregation.py
│   │   └── test_regression_gates.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── inference/
│   ├── contracts/
│   │   ├── request_contract.py
│   │   ├── result_contract.py
│   │   └── stream_contract.py
│   ├── pipeline/
│   │   ├── preprocessing.py
│   │   ├── feature_resolution.py
│   │   ├── model_feature_views.py
│   │   ├── model_execution.py
│   │   └── postprocessing.py
│   ├── batching/
│   │   ├── batch_key.py
│   │   ├── dynamic_batcher.py
│   │   └── batch_limits.py
│   ├── sampling/
│   │   ├── sampler_contract.py
│   │   ├── deterministic_sampler.py
│   │   └── diffusion_sampler.py
│   ├── compilation/
│   │   ├── compile_key.py
│   │   ├── compiled_variant_cache.py
│   │   └── fallback_policy.py
│   ├── postprocessing/
│   │   ├── coordinate_projection.py
│   │   └── structure_validation.py
│   ├── confidence/
│   │   ├── confidence_estimation.py
│   │   └── calibration.py
│   ├── ranking/
│   │   ├── candidate_ranker.py
│   │   └── ranking_evidence.py
│   ├── artifacts/
│   │   ├── result_manifest.py
│   │   ├── stream_writer.py
│   │   └── artifact_commit.py
│   ├── diagnostics/
│   │   ├── execution_trace.py
│   │   └── numerical_diagnostics.py
│   ├── tests/
│   │   ├── test_request_contract.py
│   │   ├── test_inference_parity.py
│   │   └── test_artifact_commit.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── agents/
│   ├── contracts/
│   │   ├── agent.py
│   │   ├── context.py
│   │   ├── decision.py
│   │   ├── tool.py
│   │   ├── policy.py
│   │   ├── workflow.py
│   │   └── state.py
│   ├── tools/
│   │   ├── registry/
│   │   │   ├── tool_registry.py
│   │   │   └── capability_resolution.py
│   │   ├── adapters/
│   │   │   ├── data_adapter.py
│   │   │   ├── inference_adapter.py
│   │   │   └── evaluation_adapter.py
│   │   ├── schemas/
│   │   │   ├── input_validation.py
│   │   │   └── output_validation.py
│   │   ├── permissions/
│   │   │   ├── delegated_capability.py
│   │   │   └── scope_intersection.py
│   │   ├── receipts/
│   │   │   ├── tool_receipt.py
│   │   │   └── receipt_verification.py
│   │   ├── qualification/
│   │   │   ├── tool_conformance.py
│   │   │   └── sandbox_conformance.py
│   │   └── tests/
│   │       ├── test_tool_registry.py
│   │       ├── test_permission_scope.py
│   │       └── test_receipts.py
│   ├── policies/
│   │   ├── authorization/
│   │   │   ├── decision.py
│   │   │   └── capability_policy.py
│   │   ├── biological_safety/
│   │   │   ├── use_policy.py
│   │   │   └── screening_gate.py
│   │   ├── budgets/
│   │   │   ├── resource_budget.py
│   │   │   └── budget_reservation.py
│   │   ├── approvals/
│   │   │   ├── approval_contract.py
│   │   │   └── approval_gate.py
│   │   └── tests/
│   │       ├── test_authorization.py
│   │       ├── test_safety_gate.py
│   │       └── test_budget_enforcement.py
│   ├── workflows/
│   │   ├── graph/
│   │   │   ├── workflow_graph.py
│   │   │   └── graph_validation.py
│   │   ├── planning/
│   │   │   ├── workflow_planner.py
│   │   │   └── plan_freeze.py
│   │   ├── execution/
│   │   │   ├── step_dispatch.py
│   │   │   └── step_reconciliation.py
│   │   ├── compensation/
│   │   │   ├── compensation_policy.py
│   │   │   └── compensation_runner.py
│   │   └── tests/
│   │       ├── test_workflow_graph.py
│   │       └── test_compensation.py
│   ├── state/
│   │   ├── events/
│   │   │   ├── agent_events.py
│   │   │   └── event_reducer.py
│   │   ├── snapshots/
│   │   │   ├── agent_snapshot.py
│   │   │   └── snapshot_migration.py
│   │   ├── memory_refs/
│   │   │   ├── memory_reference.py
│   │   │   └── retention_policy.py
│   │   └── lineage/
│   │       ├── decision_lineage.py
│   │       └── tool_lineage.py
│   ├── biological/
│   │   ├── discovery/
│   │   │   ├── candidate_discovery.py
│   │   │   └── discovery_policy.py
│   │   ├── design/
│   │   │   ├── design_request.py
│   │   │   └── design_constraints.py
│   │   ├── analysis/
│   │   │   ├── analysis_plan.py
│   │   │   └── evidence_synthesis.py
│   │   └── qualification/
│   │       ├── biological_agent_suite.py
│   │       └── adversarial_cases.py
│   ├── runtime/
│   │   ├── coordinator.py
│   │   ├── executor.py
│   │   ├── approvals.py
│   │   ├── budgets.py
│   │   └── replay.py
│   ├── evaluation/
│   │   ├── simulation.py
│   │   ├── adversarial.py
│   │   └── regression.py
│   ├── fixtures/
│   │   ├── tool_receipts.json
│   │   └── workflow_cases.json
│   ├── tests/
│   │   ├── test_replay.py
│   │   ├── test_approval_gates.py
│   │   └── test_sandbox_escape.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── services/
│   ├── control_plane/
│   │   ├── cmd/
│   │   │   └── control-plane/
│   │   │       ├── main.go
│   │   │       ├── wire.go
│   │   │       ├── auth_google.go
│   │   │       ├── training_adapter.go
│   │   │       └── wire_test.go
│   │   ├── internal/
│   │   │   ├── artifacts/
│   │   │   │   ├── artifact_commands.go
│   │   │   │   ├── artifact_repository.go
│   │   │   │   ├── artifact_reconciler.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   └── staging_receipts.go
│   │   │   ├── datasets/
│   │   │   │   ├── dataset_commands.go
│   │   │   │   ├── dataset_repository.go
│   │   │   │   ├── dataset_reconciler.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── contracts.go
│   │   │   │   ├── datasets_test.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mutations_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   └── server.go
│   │   │   ├── experiments/
│   │   │   │   ├── experiment_commands.go
│   │   │   │   ├── experiment_repository.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_experiments.go
│   │   │   │   ├── repository_helpers.go
│   │   │   │   ├── repository_studies.go
│   │   │   │   ├── repository_trials.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   └── validation.go
│   │   │   ├── jobs/
│   │   │   │   ├── job_commands.go
│   │   │   │   ├── job_repository.go
│   │   │   │   ├── job_reconciler.go
│   │   │   │   ├── lease_fencing.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   ├── events.go
│   │   │   │   └── events_test.go
│   │   │   ├── agents/
│   │   │   │   ├── agent_commands.go
│   │   │   │   ├── agent_repository.go
│   │   │   │   ├── agent_reconciler.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── common_sql.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   └── validation.go
│   │   │   ├── workflows/
│   │   │   │   ├── workflow_commands.go
│   │   │   │   ├── workflow_repository.go
│   │   │   │   ├── workflow_reconciler.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── approval_repository.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   └── validation.go
│   │   │   ├── models/
│   │   │   │   ├── model_commands.go
│   │   │   │   ├── model_repository.go
│   │   │   │   ├── promotion_policy.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── list_sql.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── models_test.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   └── server.go
│   │   │   ├── policies/
│   │   │   │   ├── authorization.go
│   │   │   │   ├── policy_repository.go
│   │   │   │   ├── decision_audit.go
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── policies_test.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   └── server.go
│   │   │   ├── projects/
│   │   │   │   ├── project_commands.go
│   │   │   │   └── project_repository.go
│   │   │   ├── tenants/
│   │   │   │   ├── tenant_commands.go
│   │   │   │   ├── tenant_repository.go
│   │   │   │   └── tenant_isolation.go
│   │   │   ├── users/
│   │   │   │   ├── user_projection.go
│   │   │   │   └── principal_mapping.go
│   │   │   ├── platform/
│   │   │   │   ├── database/
│   │   │   │   │   ├── transactions.go
│   │   │   │   │   ├── migration_guard.go
│   │   │   │   │   └── health.go
│   │   │   │   ├── idempotency/
│   │   │   │   │   ├── command_keys.go
│   │   │   │   │   └── idempotency_store.go
│   │   │   │   ├── outbox/
│   │   │   │   │   ├── outbox_store.go
│   │   │   │   │   ├── dispatcher.go
│   │   │   │   │   └── delivery_fencing.go
│   │   │   │   ├── queue/
│   │   │   │   │   ├── transport.go
│   │   │   │   │   ├── delivery.go
│   │   │   │   │   ├── dead_letter.go
│   │   │   │   │   └── event_registry_generated.go
│   │   │   │   ├── storage/
│   │   │   │   │   ├── artifact_catalog.go
│   │   │   │   │   ├── object_store.go
│   │   │   │   │   ├── gcs_object_store.go
│   │   │   │   │   └── gcs_object_store_test.go
│   │   │   │   ├── telemetry/
│   │   │   │   │   ├── metrics.go
│   │   │   │   │   ├── tracing.go
│   │   │   │   │   └── audit_events.go
│   │   │   │   ├── audit/
│   │   │   │   │   └── audit_store.go
│   │   │   │   └── inbox/
│   │   │   │       └── inbox_store.go
│   │   │   ├── operations/
│   │   │   │   ├── operation_commands.go
│   │   │   │   ├── operation_repository.go
│   │   │   │   └── operation_reconciler.go
│   │   │   ├── training/
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── cancellation_sql.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── list_sql.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   ├── server.go
│   │   │   │   ├── training_test.go
│   │   │   │   └── validation.go
│   │   │   ├── evaluations/
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── common_sql.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   ├── server.go
│   │   │   │   ├── server_test.go
│   │   │   │   └── validation.go
│   │   │   ├── admin/
│   │   │   │   ├── BUILD.bazel
│   │   │   │   ├── admin_test.go
│   │   │   │   ├── contracts.go
│   │   │   │   ├── events.go
│   │   │   │   ├── mapping_sql.go
│   │   │   │   ├── pagination.go
│   │   │   │   ├── postgres_integration_test.go
│   │   │   │   ├── repository_sql.go
│   │   │   │   └── server.go
│   │   │   └── inference/
│   │   │       ├── BUILD.bazel
│   │   │       ├── contracts.go
│   │   │       ├── cursor.go
│   │   │       ├── events.go
│   │   │       ├── mapping_sql.go
│   │   │       ├── postgres_integration_test.go
│   │   │       ├── repository_sql.go
│   │   │       ├── server.go
│   │   │       ├── server_test.go
│   │   │       └── validation.go
│   │   ├── migrations/
│   │   │   ├── 000001_kernel.up.sql
│   │   │   ├── 000001_kernel.down.sql
│   │   │   ├── migration_policy.yaml
│   │   │   ├── 000002_artifacts.down.sql
│   │   │   ├── 000002_artifacts.up.sql
│   │   │   ├── 000003_data_model.down.sql
│   │   │   ├── 000003_data_model.up.sql
│   │   │   ├── 000004_evaluation_inference.down.sql
│   │   │   ├── 000004_evaluation_inference.up.sql
│   │   │   ├── 000005_workflow_agent.down.sql
│   │   │   ├── 000005_workflow_agent.up.sql
│   │   │   ├── 000006_policy_admin.down.sql
│   │   │   ├── 000006_policy_admin.up.sql
│   │   │   ├── 000007_numeric_bounds.down.sql
│   │   │   ├── 000007_numeric_bounds.up.sql
│   │   │   ├── 000008_dead_letter_replay.down.sql
│   │   │   ├── 000008_dead_letter_replay.up.sql
│   │   │   ├── 000010_experiment_vertical.down.sql
│   │   │   └── 000010_experiment_vertical.up.sql
│   │   ├── tests/
│   │   │   ├── transaction_outbox_test.go
│   │   │   ├── idempotency_test.go
│   │   │   ├── lease_fencing_test.go
│   │   │   ├── tenant_isolation_test.go
│   │   │   └── reliability_harness_test.go
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   ├── README.md
│   │   ├── grpc-implementation.yaml
│   │   └── grpc-implementation.generated.json
│   ├── runtime_gateway/
│   │   ├── cmd/
│   │   │   └── runtime-gateway/
│   │   │       ├── main.go
│   │   │       └── wire.go
│   │   ├── internal/
│   │   │   ├── admission/
│   │   │   │   ├── request_admission.go
│   │   │   │   └── quota_check.go
│   │   │   ├── authorization/
│   │   │   │   ├── request_authorization.go
│   │   │   │   └── delegation.go
│   │   │   ├── routing/
│   │   │   │   ├── model_route.go
│   │   │   │   └── worker_route.go
│   │   │   ├── streaming/
│   │   │   │   ├── stream_session.go
│   │   │   │   └── backpressure.go
│   │   │   ├── limits/
│   │   │   │   ├── deadline.go
│   │   │   │   ├── body_limit.go
│   │   │   │   └── rate_limit.go
│   │   │   └── telemetry/
│   │   │       ├── request_metrics.go
│   │   │       ├── tracing.go
│   │   │       └── audit.go
│   │   ├── tests/
│   │   │   ├── authorization_test.go
│   │   │   ├── admission_test.go
│   │   │   └── stream_backpressure_test.go
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── artifact_proxy/
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── authorization.rs
│   │   │   ├── transfer.rs
│   │   │   ├── integrity.rs
│   │   │   ├── limits.rs
│   │   │   └── telemetry.rs
│   │   ├── tests/
│   │   │   ├── authorization.rs
│   │   │   ├── resumable_transfer.rs
│   │   │   └── integrity_failure.rs
│   │   ├── Cargo.toml
│   │   ├── Cargo.lock
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── BUILD.bazel
│   └── README.md
├── workers/
│   ├── ingestion_worker/
│   │   ├── rust/
│   │   │   └── src/
│   │   │       ├── main.rs
│   │   │       ├── attempt.rs
│   │   │       ├── source_fetch.rs
│   │   │       ├── artifact_commit.rs
│   │   │       ├── receipt_commit.rs
│   │   │       ├── cancellation.rs
│   │   │       ├── telemetry.rs
│   │   │       └── lib.rs
│   │   ├── tests/
│   │   │   ├── redelivery.rs
│   │   │   ├── stale_lease.rs
│   │   │   └── partial_fetch.rs
│   │   ├── Cargo.toml
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── feature_worker/
│   │   ├── rust/
│   │   │   └── src/
│   │   │       ├── main.rs
│   │   │       ├── attempt.rs
│   │   │       ├── feature_plan.rs
│   │   │       ├── transform_plan.rs
│   │   │       ├── resolve.rs
│   │   │       ├── derive.rs
│   │   │       ├── validate.rs
│   │   │       ├── determinism.rs
│   │   │       ├── artifact_commit.rs
│   │   │       ├── cancellation.rs
│   │   │       └── telemetry.rs
│   │   ├── python/
│   │   │   ├── reference_ops.py
│   │   │   └── parity_adapter.py
│   │   ├── tests/
│   │   │   ├── feature_parity.py
│   │   │   ├── key_stability.py
│   │   │   ├── feature_plan_lowering.py
│   │   │   ├── remote_plan_reference.py
│   │   │   ├── duplicate_derivation.py
│   │   │   ├── determinism_violation.py
│   │   │   ├── redelivery.py
│   │   │   ├── stale_lease.py
│   │   │   └── corrupt_cache.py
│   │   ├── Cargo.toml
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── training_worker/
│   │   ├── python/
│   │   │   ├── main.py
│   │   │   ├── bootstrap.py
│   │   │   ├── job.py
│   │   │   ├── execution.py
│   │   │   ├── cancellation.py
│   │   │   ├── heartbeat.py
│   │   │   ├── artifacts.py
│   │   │   ├── telemetry.py
│   │   │   └── control_plane.py
│   │   ├── tests/
│   │   │   ├── test_redelivery.py
│   │   │   ├── test_stale_lease.py
│   │   │   ├── test_checkpoint_cancel.py
│   │   │   └── test_control_plane.py
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── evaluation_worker/
│   │   ├── python/
│   │   │   ├── main.py
│   │   │   ├── attempt.py
│   │   │   ├── evaluation_execution.py
│   │   │   ├── cancellation.py
│   │   │   ├── artifacts.py
│   │   │   └── telemetry.py
│   │   ├── tests/
│   │   │   ├── test_redelivery.py
│   │   │   ├── test_evidence_commit.py
│   │   │   └── test_cancellation.py
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── inference_worker/
│   │   ├── python/
│   │   │   ├── main.py
│   │   │   ├── attempt.py
│   │   │   ├── model_loading.py
│   │   │   ├── batch_execution.py
│   │   │   ├── streaming.py
│   │   │   ├── cancellation.py
│   │   │   ├── artifacts.py
│   │   │   └── telemetry.py
│   │   ├── tests/
│   │   │   ├── test_batching.py
│   │   │   ├── test_stream_backpressure.py
│   │   │   └── test_artifact_commit.py
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── agent_worker/
│   │   ├── python/
│   │   │   ├── main.py
│   │   │   ├── attempt.py
│   │   │   ├── workflow_execution.py
│   │   │   ├── sandbox.py
│   │   │   ├── cancellation.py
│   │   │   ├── receipts.py
│   │   │   └── telemetry.py
│   │   ├── tests/
│   │   │   ├── test_tool_fencing.py
│   │   │   ├── test_budget_cancel.py
│   │   │   └── test_sandbox_policy.py
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── BUILD.bazel
│   └── README.md
├── sdk/
│   ├── python/
│   │   ├── src/
│   │   │   └── mindclade/
│   │   │       ├── __init__.py
│   │   │       ├── client.py
│   │   │       ├── operations.py
│   │   │       ├── artifacts.py
│   │   │       ├── models.py
│   │   │       ├── datasets.py
│   │   │       ├── inference.py
│   │   │       ├── errors.py
│   │   │       └── py.typed
│   │   ├── tests/
│   │   │   ├── test_client_contract.py
│   │   │   ├── test_operation_polling.py
│   │   │   └── test_artifact_transfer.py
│   │   ├── pyproject.toml
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── typescript/
│   │   ├── src/
│   │   │   ├── index.ts
│   │   │   ├── client.ts
│   │   │   ├── operations.ts
│   │   │   ├── artifacts.ts
│   │   │   ├── models.ts
│   │   │   ├── datasets.ts
│   │   │   ├── inference.ts
│   │   │   └── errors.ts
│   │   ├── tests/
│   │   │   ├── client-contract.test.ts
│   │   │   ├── operation-polling.test.ts
│   │   │   └── artifact-transfer.test.ts
│   │   ├── package.json
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── conformance/
│   │   ├── public_api_cases.yaml
│   │   ├── error_cases.yaml
│   │   └── pagination_cases.yaml
│   ├── examples/
│   │   ├── submit_operation.py
│   │   ├── stream_inference.ts
│   │   └── download_artifact.py
│   ├── BUILD.bazel
│   └── README.md
├── kits/
│   ├── mcdk/
│   │   ├── environment_assembly.go
│   │   ├── environment_validation.go
│   │   └── README.md
│   ├── mddk/
│   │   ├── dataset_assembly.py
│   │   ├── dataset_validation.py
│   │   └── README.md
│   ├── mmdk/
│   │   ├── model_assembly.py
│   │   ├── model_validation.py
│   │   └── README.md
│   ├── mtdk/
│   │   ├── training_assembly.py
│   │   ├── training_validation.py
│   │   └── README.md
│   ├── medk/
│   │   ├── evaluation_assembly.py
│   │   ├── evaluation_validation.py
│   │   └── README.md
│   ├── madk/
│   │   ├── agent_assembly.py
│   │   ├── agent_simulation.py
│   │   └── README.md
│   ├── assembly/
│   │   ├── assembly_manifest.py
│   │   └── assembly_signing.py
│   ├── conformance/
│   │   ├── kit_contract_cases.yaml
│   │   └── clean_project_test.py
│   ├── cli/
│   │   ├── main.py
│   │   ├── validation_commands.py
│   │   └── generation_commands.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── apps/
│   ├── console/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   ├── error.tsx
│   │   │   └── not-found.tsx
│   │   ├── components/
│   │   │   ├── operation-status.tsx
│   │   │   ├── artifact-link.tsx
│   │   │   └── evidence-badge.tsx
│   │   ├── features/
│   │   │   ├── datasets/
│   │   │   │   ├── dataset-list.tsx
│   │   │   │   ├── dataset-detail.tsx
│   │   │   │   ├── dataset-actions.ts
│   │   │   │   ├── dataset-hooks.ts
│   │   │   │   └── dataset-types.ts
│   │   │   ├── models/
│   │   │   │   ├── model-list.tsx
│   │   │   │   ├── model-detail.tsx
│   │   │   │   ├── model-release-actions.ts
│   │   │   │   ├── model-hooks.ts
│   │   │   │   └── model-types.ts
│   │   │   ├── training/
│   │   │   │   ├── training-run-list.tsx
│   │   │   │   ├── training-run-detail.tsx
│   │   │   │   ├── training-actions.ts
│   │   │   │   ├── training-hooks.ts
│   │   │   │   └── training-types.ts
│   │   │   ├── evaluation/
│   │   │   │   ├── evaluation-list.tsx
│   │   │   │   ├── evaluation-detail.tsx
│   │   │   │   ├── evaluation-report.tsx
│   │   │   │   ├── evaluation-hooks.ts
│   │   │   │   └── evaluation-types.ts
│   │   │   ├── inference/
│   │   │   │   ├── inference-form.tsx
│   │   │   │   ├── inference-run.tsx
│   │   │   │   ├── inference-artifacts.tsx
│   │   │   │   ├── inference-hooks.ts
│   │   │   │   └── inference-types.ts
│   │   │   ├── agents/
│   │   │   │   ├── agent-list.tsx
│   │   │   │   ├── agent-run-detail.tsx
│   │   │   │   ├── approval-panel.tsx
│   │   │   │   ├── agent-hooks.ts
│   │   │   │   └── agent-types.ts
│   │   │   └── operations/
│   │   │       ├── operation-list.tsx
│   │   │       ├── operation-detail.tsx
│   │   │       ├── operation-timeline.tsx
│   │   │       ├── operation-hooks.ts
│   │   │       ├── operation-types.ts
│   │   │       └── operation-client.ts
│   │   ├── tests/
│   │   │   ├── authorization.test.ts
│   │   │   ├── operation-flow.test.ts
│   │   │   └── accessibility.test.ts
│   │   ├── package.json
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   ├── README.md
│   │   ├── biome.json
│   │   ├── tsconfig.json
│   │   └── lib/
│   │       └── control-plane.ts
│   ├── admin/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   └── error.tsx
│   │   ├── features/
│   │   │   ├── tenants/
│   │   │   │   ├── tenant-list.tsx
│   │   │   │   ├── tenant-detail.tsx
│   │   │   │   ├── tenant-actions.ts
│   │   │   │   └── tenant-hooks.ts
│   │   │   ├── policies/
│   │   │   │   ├── policy-list.tsx
│   │   │   │   ├── policy-detail.tsx
│   │   │   │   ├── policy-diff.tsx
│   │   │   │   └── policy-actions.ts
│   │   │   ├── audit/
│   │   │   │   ├── audit-search.tsx
│   │   │   │   ├── audit-event-detail.tsx
│   │   │   │   ├── audit-filters.ts
│   │   │   │   └── audit-hooks.ts
│   │   │   └── incidents/
│   │   │       ├── incident-list.tsx
│   │   │       ├── incident-detail.tsx
│   │   │       ├── incident-actions.ts
│   │   │       └── incident-hooks.ts
│   │   ├── tests/
│   │   │   ├── authorization.test.ts
│   │   │   └── audit-view.test.ts
│   │   ├── package.json
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── docs/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── content/
│   │   │   ├── sdk/
│   │   │   │   ├── overview.mdx
│   │   │   │   ├── python.mdx
│   │   │   │   ├── typescript.mdx
│   │   │   │   └── artifacts.mdx
│   │   │   ├── contracts/
│   │   │   │   ├── overview.mdx
│   │   │   │   ├── versioning.mdx
│   │   │   │   ├── compatibility.mdx
│   │   │   │   └── errors.mdx
│   │   │   ├── operations/
│   │   │   │   ├── long-running-operations.mdx
│   │   │   │   ├── idempotency.mdx
│   │   │   │   ├── cancellation.mdx
│   │   │   │   └── pagination.mdx
│   │   │   └── runbooks/
│   │   │       ├── overview.mdx
│   │   │       ├── incident-response.mdx
│   │   │       ├── artifact-recovery.mdx
│   │   │       └── training-recovery.mdx
│   │   ├── tests/
│   │   │   ├── link-integrity.test.ts
│   │   │   └── code-samples.test.ts
│   │   ├── package.json
│   │   ├── BUILD.bazel
│   │   ├── component.yaml
│   │   └── README.md
│   ├── BUILD.bazel
│   └── README.md
├── deploy/
│   ├── crds/
│   │   ├── workload-profile/
│   │   │   ├── workload-profile-crd.yaml
│   │   │   └── conversion-policy.yaml
│   │   └── README.md
│   ├── components/
│   │   ├── control_plane/
│   │   │   ├── release-package.yaml
│   │   │   ├── values.schema.json
│   │   │   ├── base.yaml
│   │   │   └── service-monitor.yaml
│   │   ├── runtime_gateway/
│   │   │   ├── release-package.yaml
│   │   │   ├── values.schema.json
│   │   │   ├── base.yaml
│   │   │   └── service-monitor.yaml
│   │   ├── artifact_proxy/
│   │   │   ├── release-package.yaml
│   │   │   ├── values.schema.json
│   │   │   ├── base.yaml
│   │   │   └── service-monitor.yaml
│   │   └── workers/
│   │       ├── release-package.yaml
│   │       ├── values.schema.json
│   │       ├── worker-templates.yaml
│   │       └── network-policies.yaml
│   ├── local/
│   │   ├── compose.yaml
│   │   ├── local-values.yaml
│   │   ├── fake-identity.yaml
│   │   └── README.md
│   ├── integration/
│   │   ├── kustomization.yaml
│   │   ├── integration-values.yaml
│   │   ├── synthetic-data-policy.yaml
│   │   └── README.md
│   ├── policies/
│   │   ├── signed_images.rego
│   │   ├── workload_identity.rego
│   │   ├── tenant_network.rego
│   │   └── resource_limits.rego
│   ├── tests/
│   │   ├── test_deterministic_render.py
│   │   ├── test_policy_denials.py
│   │   └── test_upgrade_rollback.py
│   ├── BUILD.bazel
│   ├── component.yaml
│   └── README.md
├── research/
│   ├── notebooks/
│   │   ├── README.md
│   │   └── notebook_policy.py
│   ├── prototypes/
│   │   ├── README.md
│   │   └── prototype_manifest.schema.json
│   ├── ablations/
│   │   ├── README.md
│   │   └── ablation_manifest.schema.json
│   ├── studies/
│   │   ├── README.md
│   │   └── study_manifest.schema.json
│   ├── papers/
│   │   ├── README.md
│   │   └── reproduction_manifest.schema.json
│   ├── fixtures/
│   │   ├── synthetic_sequences.fasta
│   │   └── synthetic_structure.cif
│   ├── README.md
│   └── POLICY.md
├── tests/
│   ├── conformance/
│   │   ├── contract_matrix.yaml
│   │   ├── test_generated_clients.py
│   │   ├── test_artifact_manifests.py
│   │   ├── test_configuration_resolution.py
│   │   ├── test_release_signing.py
│   │   ├── test_internal_sdk_application_consumers.py
│   │   ├── generated_go_roundtrip_test.go
│   │   ├── generated_rust_roundtrip_test.rs
│   │   ├── generated_typescript_roundtrip_test.ts
│   │   └── test_generated_package_consumers.py
│   ├── integration/
│   │   ├── local_stack_test.py
│   │   ├── control_worker_test.py
│   │   └── artifact_commit_test.py
│   ├── end_to_end/
│   │   ├── scientific_slice_test.py
│   │   ├── platform_slice_test.py
│   │   └── joined_lifecycle_test.py
│   ├── distributed/
│   │   ├── single_node_fsdp_test.py
│   │   ├── multi_rank_checkpoint_test.py
│   │   └── collective_failure_test.py
│   ├── failure_injection/
│   │   ├── outbox_crash_test.py
│   │   ├── worker_redelivery_test.py
│   │   └── storage_failure_test.py
│   ├── performance/
│   │   ├── budget.yaml
│   │   ├── data_path_benchmark.py
│   │   └── inference_benchmark.py
│   ├── security/
│   │   ├── tenant_isolation_test.py
│   │   ├── artifact_authorization_test.py
│   │   └── sandbox_escape_test.py
│   ├── feature_derivation/
│   │   ├── key_stability_test.py
│   │   ├── feature_plan_lowering_test.py
│   │   ├── cross_model_reuse_test.py
│   │   ├── cache_isolation_test.py
│   │   ├── determinism_race_test.py
│   │   ├── snapshot_leakage_test.py
│   │   └── model_view_separation_test.py
│   ├── transforms/
│   │   ├── semantic_execution_identity_test.py
│   │   ├── fitted_state_leakage_test.py
│   │   ├── lineage_map_reconstruction_test.py
│   │   ├── remote_plan_reference_test.py
│   │   └── backend_replacement_equivalence_test.py
│   ├── BUILD.bazel
│   └── README.md
├── tools/
│   ├── bazel/
│   │   ├── rules/
│   │   │   ├── component_rule.bzl
│   │   │   ├── contract_rule.bzl
│   │   │   └── release_rule.bzl
│   │   ├── macros/
│   │   │   ├── python_component.bzl
│   │   │   ├── rust_component.bzl
│   │   │   ├── go_component.bzl
│   │   │   └── typescript_component.bzl
│   │   ├── aspects/
│   │   │   ├── dependency_graph.bzl
│   │   │   ├── component_metadata.bzl
│   │   │   └── generated_files.bzl
│   │   └── transitions/
│   │       ├── cpu_profile.bzl
│   │       └── gpu_profile.bzl
│   ├── ci/
│   │   ├── affected_targets.py
│   │   ├── pipeline_plan.py
│   │   ├── required_check.py
│   │   └── evidence_bundle.py
│   ├── codegen/
│   │   ├── generate_protocols.py
│   │   ├── generate_schemas.py
│   │   ├── verify_generated_drift.py
│   │   ├── toolchain.lock.json
│   │   ├── sdk_generator.py
│   │   ├── rust_plugins/
│   │   │   ├── Cargo.toml
│   │   │   └── src/
│   │   │       └── bin/
│   │   │           ├── protoc-gen-prost.rs
│   │   │           └── protoc-gen-tonic.rs
│   │   ├── generate_sdk_coverage.py
│   │   └── generate_grpc_implementation_coverage.py
│   ├── docs/
│   │   ├── render_architecture_blueprint.py
│   │   ├── validate_blueprint_sources.py
│   │   ├── blueprint_manifest.schema.json
│   │   └── tests/
│   │       ├── test_render_architecture_blueprint.py
│   │       └── test_blueprint_source_manifest.py
│   ├── dev/
│   │   ├── bootstrap.py
│   │   ├── doctor.py
│   │   ├── environment_profile.py
│   │   └── diagnostic_bundle.py
│   ├── repo/
│   │   ├── build_repository_drift_report.py
│   │   ├── dependency_policy.py
│   │   ├── owner_policy.py
│   │   ├── path_policy.py
│   │   ├── render_repository_tree.py
│   │   ├── verify_repository_path_manifest.py
│   │   ├── component.schema.json
│   │   ├── repository_drift.v1.schema.json
│   │   ├── activation-bundles.schema.json
│   │   ├── activation-bundles.yaml
│   │   ├── activation-bundles.generated.json
│   │   └── tests/
│   │       ├── test_activation_bundles.py
│   │       ├── test_build_repository_drift_report.py
│   │       ├── test_monorepo_tree_authority.py
│   │       ├── test_repository_policies.py
│   │       └── golden/
│   │           └── repository_drift.v1.json
│   ├── release/
│   │   ├── build_release_manifest.py
│   │   ├── verify_release.py
│   │   ├── promote_release.py
│   │   ├── revoke_release.py
│   │   └── sign_release.py
│   ├── qualification/
│   │   ├── resolve_policy.py
│   │   ├── collect_evidence.py
│   │   ├── verify_evidence.py
│   │   └── hardware_envelope.py
│   ├── migration/
│   │   ├── plan_path_move.py
│   │   ├── verify_compatibility.py
│   │   └── remove_shim.py
│   ├── generators/
│   │   ├── stub_catalog.yaml
│   │   ├── generate_component.py
│   │   ├── templates/
│   │   │   ├── python_library/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── component.yaml.j2
│   │   │   │   ├── pyproject.toml.j2
│   │   │   │   ├── src/
│   │   │   │   │   ├── __init__.py.j2
│   │   │   │   │   ├── domain_contract.py.j2
│   │   │   │   │   └── py.typed.j2
│   │   │   │   └── tests/
│   │   │   │       └── test_domain_contract.py.j2
│   │   │   ├── rust_crate/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── component.yaml.j2
│   │   │   │   ├── Cargo.toml.j2
│   │   │   │   ├── src/
│   │   │   │   │   ├── lib.rs.j2
│   │   │   │   │   └── domain_contract.rs.j2
│   │   │   │   └── tests/
│   │   │   │       └── domain_contract.rs.j2
│   │   │   ├── go_package/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── component.yaml.j2
│   │   │   │   ├── domain_contract.go.j2
│   │   │   │   └── domain_contract_test.go.j2
│   │   │   ├── typescript_package/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── component.yaml.j2
│   │   │   │   ├── package.json.j2
│   │   │   │   ├── src/
│   │   │   │   │   ├── index.ts.j2
│   │   │   │   │   └── domain-contract.ts.j2
│   │   │   │   └── tests/
│   │   │   │       └── domain-contract.test.ts.j2
│   │   │   ├── deployable/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── component.yaml.j2
│   │   │   │   ├── release-package.yaml.j2
│   │   │   │   ├── values.schema.json.j2
│   │   │   │   ├── deployment-base.yaml.j2
│   │   │   │   └── tests/
│   │   │   │       └── test_deployment_contract.py.j2
│   │   │   ├── contract/
│   │   │   │   ├── README.md.j2
│   │   │   │   ├── BUILD.bazel.j2
│   │   │   │   ├── contract.proto.j2
│   │   │   │   ├── contract.schema.json.j2
│   │   │   │   ├── positive.json.j2
│   │   │   │   ├── negative.json.j2
│   │   │   │   └── compatibility-baseline.json.j2
│   │   │   └── documentation/
│   │   │       ├── README.md.j2
│   │   │       ├── domain.md.j2
│   │   │       ├── BUILD.bazel.j2
│   │   │       └── link-test.yaml.j2
│   │   └── tests/
│   │       ├── test_stub_catalog.py
│   │       └── test_generated_component.py
│   ├── licenses/
│   │   ├── allowlist.yaml
│   │   ├── exceptions.yaml
│   │   ├── scan_licenses.py
│   │   └── generate_notices.py
│   ├── BUILD.bazel
│   ├── README.md
│   └── mindcladectl/
│       ├── BUILD.bazel
│       ├── README.md
│       ├── command.go
│       ├── command_test.go
│       ├── component.yaml
│       ├── live.go
│       └── cmd/
│           └── main.go
├── docs/
│   ├── architecture/
│   │   ├── repository-path-manifest.yaml
│   │   ├── repository-path-manifest.schema.json
│   │   ├── repository-drift-baseline.md
│   │   ├── dependency-law.md
│   │   ├── trust-boundaries.md
│   │   ├── blueprint/
│   │   │   ├── README.md
│   │   │   ├── manifest.yaml
│   │   │   ├── provenance/
│   │   │   │   ├── MINDCLADE_MONOREPO_BLUEPRINT_v3.4.0_OPTIMIZED.md
│   │   │   │   └── MONOREPO_TREE.md
│   │   │   ├── sections/
│   │   │   │   ├── 01-executive-summary.md
│   │   │   │   ├── 02-goals-non-goals-principles-invariants.md
│   │   │   │   ├── 03-architecture-overview.md
│   │   │   │   ├── 04-authoritative-repository-tree.md
│   │   │   │   ├── 05-ownership-and-dependency-matrix.md
│   │   │   │   ├── 06-contract-and-compatibility-model.md
│   │   │   │   ├── 07-detailed-system-designs.md
│   │   │   │   ├── 08-end-to-end-execution-flows.md
│   │   │   │   ├── 09-security-and-trust-model.md
│   │   │   │   ├── 10-reliability-and-operational-model.md
│   │   │   │   ├── 11-build-test-cicd-release-architecture.md
│   │   │   │   ├── 12-deployment-architecture.md
│   │   │   │   ├── 13-developer-workflows.md
│   │   │   │   ├── 14-adr-index-and-decision-log.md
│   │   │   │   ├── 15-phased-implementation-plan.md
│   │   │   │   ├── 16-verification-and-acceptance-matrix.md
│   │   │   │   ├── 17-risks-technical-debt-deferred-blockers.md
│   │   │   │   └── 18-glossary.md
│   │   │   ├── appendices/
│   │   │   │   ├── A01-executive-decision.md
│   │   │   │   ├── A02-goals.md
│   │   │   │   ├── A03-repository-estate-and-trust-boundaries.md
│   │   │   │   ├── A04-language-ownership-model.md
│   │   │   │   ├── A05-domain-first-language-second.md
│   │   │   │   ├── A06-authoritative-repository-tree.md
│   │   │   │   ├── A07-dependency-laws.md
│   │   │   │   ├── A08-standard-package-shape.md
│   │   │   │   ├── A09-build-and-dependency-architecture.md
│   │   │   │   ├── A10-protocol-and-schema-architecture.md
│   │   │   │   ├── A11-biological-domain-architecture.md
│   │   │   │   ├── A12-data-platform-architecture.md
│   │   │   │   ├── A13-model-architecture.md
│   │   │   │   ├── A14-training-architecture.md
│   │   │   │   ├── A15-kernel-architecture.md
│   │   │   │   ├── A16-evaluation-architecture.md
│   │   │   │   ├── A17-inference-architecture.md
│   │   │   │   ├── A18-service-and-worker-architecture.md
│   │   │   │   ├── A19-sdk-and-application-architecture.md
│   │   │   │   ├── A20-research-graduation-policy.md
│   │   │   │   ├── A21-ci-architecture.md
│   │   │   │   ├── A22-test-and-qualification-matrix.md
│   │   │   │   ├── A23-release-and-artifact-model.md
│   │   │   │   ├── A24-kubernetes-and-workload-execution.md
│   │   │   │   ├── A25-observability.md
│   │   │   │   ├── A26-security-supply-chain-biological-governance.md
│   │   │   │   ├── A27-configuration-architecture.md
│   │   │   │   ├── A28-database-and-migration-policy.md
│   │   │   │   ├── A29-ownership-and-governance.md
│   │   │   │   ├── A30-developer-workflow.md
│   │   │   │   ├── A31-capability-local-implementation-guidance.md
│   │   │   │   ├── A32-what-to-defer.md
│   │   │   │   ├── A33-repository-anti-patterns.md
│   │   │   │   ├── A34-architecture-constitution.md
│   │   │   │   ├── A35-technology-basis.md
│   │   │   │   ├── A36-agent-and-development-kit-architecture.md
│   │   │   │   ├── A37-google-cloud-reference-deployment-profile.md
│   │   │   │   ├── A38-reliability-continuity-first-production-acceptance.md
│   │   │   │   ├── A39-feature-derivation-caching-model-specific-features.md
│   │   │   │   └── A40-feature-and-data-transform-architecture.md
│   │   │   └── generated/
│   │   │       └── MINDCLADE_MONOREPO_BLUEPRINT_FULL.md
│   │   └── authoritative-contract-integration-plan.md
│   ├── adr/
│   │   ├── 0001-repository-identity-and-ownership.md
│   │   ├── 0002-dependency-and-build-law.md
│   │   ├── 0003-artifact-identity-and-cas.md
│   │   ├── 0004-contract-and-codegen-authority.md
│   │   ├── 0005-biological-identity-and-schema-evolution.md
│   │   ├── 0006-durable-work-and-fencing.md
│   │   ├── 0007-training-state-progress-and-checkpoint.md
│   │   ├── index.yaml
│   │   ├── 0008-founder-bootstrap-public-estate-transition.md
│   │   ├── connected-ratification.v1.schema.json
│   │   ├── 0013-deepep-package-and-qualification-boundary.md
│   │   ├── 0015-all-contracts-clean-v1-baseline.md
│   │   ├── 0010-modular-go-control-plane-relational-durability-worker-isolation.md
│   │   ├── 0011-sqp-001-scientific-qualification-profile.md
│   │   ├── 0012-http-json-operation-projection-python-sdk.md
│   │   ├── 0014-tilelang-kernel-platform-source-development.md
│   │   ├── 0009-native-kernel-source-incubation.md
│   │   ├── 0016-pairformer-native-kernel-platform-wave6-source-activation.md
│   │   ├── 0017-jit-06-outer-product-mean-sm90a-sm100a.md
│   │   ├── 0018-jit-06-pair-weighted-average-sm90a-sm100a.md
│   │   ├── 0019-jit-06-transition-sm90a-sm100a.md
│   │   ├── 0020-jit-06-triangle-attention-sm90a-sm100a.md
│   │   ├── 0021-jit-06-triangle-multiplication-sm90a-sm100a.md
│   │   └── 0022-native-signed-qualification-and-production-admission-source-activation.md
│   ├── domains/
│   │   ├── bio.md
│   │   ├── data.md
│   │   ├── features.md
│   │   ├── transforms.md
│   │   ├── models.md
│   │   ├── training.md
│   │   ├── evaluation.md
│   │   ├── inference.md
│   │   ├── agents.md
│   │   └── control-plane.md
│   ├── standards/
│   │   ├── coding.md
│   │   ├── contracts.md
│   │   ├── testing.md
│   │   ├── observability.md
│   │   ├── security.md
│   │   └── releases.md
│   ├── developer/
│   │   ├── bootstrap.md
│   │   ├── build.md
│   │   ├── test.md
│   │   ├── code-generation.md
│   │   ├── data-transforms.md
│   │   ├── feature-derivation.md
│   │   ├── debugging.md
│   │   └── contributing.md
│   ├── security/
│   │   ├── threat-model.md
│   │   ├── data-classification.md
│   │   ├── identity.md
│   │   ├── supply-chain.md
│   │   └── incident-policy.md
│   ├── runbooks/
│   │   ├── control-plane.md
│   │   ├── workers.md
│   │   ├── artifacts.md
│   │   ├── training.md
│   │   ├── inference.md
│   │   └── agents.md
│   ├── operations/
│   │   ├── slos.md
│   │   ├── capacity.md
│   │   ├── cost-attribution.md
│   │   └── disaster-recovery.md
│   ├── model_cards/
│   │   ├── README.md
│   │   └── model-card.schema.json
│   ├── dataset_cards/
│   │   ├── README.md
│   │   └── dataset-card.schema.json
│   ├── BUILD.bazel
│   ├── README.md
│   ├── governance/
│   │   ├── reports/
│   │   │   ├── wave2-preflight-ci.md
│   │   │   ├── wave2-preflight-codegen.md
│   │   │   └── wave2-preflight-decisions.md
│   │   ├── founder-bootstrap-exception.v1.schema.json
│   │   └── exceptions/
│   │       └── FBE-0001.yaml
│   └── policies/
│       ├── pdb-source-use-approval.template.yaml
│       ├── pdb-source-use-approval.v1.schema.json
│       ├── pdb-source-use-data-governance.md
│       ├── sqp-001-h100-approval.template.yaml
│       ├── sqp-001-h100-approval.v1.schema.json
│       └── sqp-001-h100-qualification-envelope.md
├── examples/
│   ├── sdk/
│   │   ├── submit_operation.py
│   │   ├── follow_operation.ts
│   │   ├── download_artifact.py
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── biome.json
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── follow_operation.test.ts
│   │   └── test_sdk_examples.py
│   ├── data_connector/
│   │   ├── connector.py
│   │   ├── connector_contract_test.py
│   │   └── README.md
│   ├── model_extension/
│   │   ├── model_definition.py
│   │   ├── model_package.yaml
│   │   └── README.md
│   ├── training_smoke/
│   │   ├── recipe.yaml
│   │   ├── run_local.py
│   │   └── README.md
│   ├── inference/
│   │   ├── request.json
│   │   ├── run_local.py
│   │   └── README.md
│   ├── agent_workflow/
│   │   ├── agent.yaml
│   │   ├── workflow.yaml
│   │   ├── simulate.py
│   │   ├── README.md
│   │   ├── __init__.py
│   │   └── test_simulate.py
│   └── BUILD.bazel
├── third_party/
│   ├── patches/
│   │   ├── README.md
│   │   ├── patches.lock.json
│   │   └── deep_ep/
│   │       ├── declared-toolchain-paths.patch
│   │       ├── deterministic-version.patch
│   │       ├── gin-attestation.patch
│   │       └── runtime-jit-cache.patch
│   ├── licenses/
│   │   ├── README.md
│   │   └── license_inventory.json
│   ├── notices/
│   │   └── NOTICE.generated.txt
│   ├── source_mirrors/
│   │   ├── README.md
│   │   └── sources.lock.json
│   ├── BUILD.bazel
│   ├── README.md
│   └── packages/
│       └── deep_ep/
│           ├── BUILD.bazel
│           ├── README.md
│           ├── artifact_contract.py
│           ├── gpu-evidence.schema.json
│           ├── package.nix
│           ├── repository.bzl
│           ├── runtime-manifest.schema.json
│           └── test_package.py
├── .golangci.yml
├── biome.json
├── buf.lock
└── internal/
    └── sdk/
        ├── README.md
        ├── go/
        │   └── mindclade/
        │       ├── BUILD.bazel
        │       ├── README.md
        │       ├── admin.go
        │       ├── agent_test.go
        │       ├── agents.go
        │       ├── approvals.go
        │       ├── artifacts.go
        │       ├── auth.go
        │       ├── auth_test.go
        │       ├── client.go
        │       ├── client_test.go
        │       ├── config.go
        │       ├── datasets.go
        │       ├── error.go
        │       ├── evaluations.go
        │       ├── evaluations_test.go
        │       ├── interceptors.go
        │       ├── inference.go
        │       ├── inference_test.go
        │       ├── lifecycle_test.go
        │       ├── method_policy.go
        │       ├── models.go
        │       ├── operations.go
        │       ├── policy_test.go
        │       ├── policies.go
        │       ├── policy_admin_test.go
        │       ├── request.go
        │       ├── training.go
        │       ├── transport.go
        │       ├── workflow_test.go
        │       ├── workflows.go
        │       ├── artifact_operation_gap_test.go
        │       ├── job_run_test.go
        │       ├── jobs.go
        │       ├── runs.go
        │       ├── training_lifecycle_test.go
        │       ├── experiments.go
        │       └── experiments_test.go
        ├── python/
        │   ├── BUILD.bazel
        │   ├── README.md
        │   ├── mindclade_internal_sdk/
        │   │   ├── __init__.py
        │   │   ├── _invocation.py
        │   │   ├── _validation.py
        │   │   ├── admin.py
        │   │   ├── agents.py
        │   │   ├── artifacts.py
        │   │   ├── auth.py
        │   │   ├── calls.py
        │   │   ├── client.py
        │   │   ├── config.py
        │   │   ├── datasets.py
        │   │   ├── errors.py
        │   │   ├── generated.py
        │   │   ├── inference.py
        │   │   ├── method_policy.py
        │   │   ├── models.py
        │   │   ├── operations.py
        │   │   ├── policies.py
        │   │   ├── testing.py
        │   │   ├── training.py
        │   │   ├── transport.py
        │   │   ├── workflows.py
        │   │   ├── evaluations.py
        │   │   ├── jobs.py
        │   │   ├── runs.py
        │   │   ├── experiments.py
        │   │   └── resources.py
        │   ├── pyproject.toml
        │   └── tests/
        │       ├── test_internal_sdk.py
        │       ├── test_agents.py
        │       ├── test_inference.py
        │       ├── test_policy_admin.py
        │       ├── test_workflows.py
        │       ├── test_artifact_operation_gaps.py
        │       ├── test_evaluations.py
        │       ├── test_job_run.py
        │       ├── test_training_lifecycle.py
        │       └── test_experiments.py
        ├── rust/
        │   ├── BUILD.bazel
        │   ├── Cargo.toml
        │   ├── README.md
        │   └── src/
        │       ├── admin.rs
        │       ├── agent_tests.rs
        │       ├── agents.rs
        │       ├── approvals.rs
        │       ├── artifacts.rs
        │       ├── auth.rs
        │       ├── config.rs
        │       ├── datasets.rs
        │       ├── error.rs
        │       ├── inference.rs
        │       ├── lib.rs
        │       ├── models.rs
        │       ├── operations.rs
        │       ├── policies.rs
        │       ├── policy_admin_tests.rs
        │       ├── request.rs
        │       ├── retry.rs
        │       ├── tests.rs
        │       ├── training.rs
        │       ├── transport.rs
        │       ├── workflow_tests.rs
        │       ├── workflows.rs
        │       ├── artifact_operation_gap_tests.rs
        │       ├── evaluation_tests.rs
        │       ├── evaluations.rs
        │       ├── job_run_tests.rs
        │       ├── jobs.rs
        │       ├── runs.rs
        │       ├── training_tests.rs
        │       ├── experiments.rs
        │       └── experiment_tests.rs
        ├── typescript/
        │   ├── BUILD.bazel
        │   ├── README.md
        │   ├── biome.json
        │   ├── package.json
        │   ├── src/
        │   │   ├── admin.ts
        │   │   ├── agents.ts
        │   │   ├── approvals.ts
        │   │   ├── artifacts.ts
        │   │   ├── auth.ts
        │   │   ├── client.ts
        │   │   ├── config.ts
        │   │   ├── core.ts
        │   │   ├── datasets.ts
        │   │   ├── error.ts
        │   │   ├── gcp_auth.ts
        │   │   ├── inference.ts
        │   │   ├── index.ts
        │   │   ├── models.ts
        │   │   ├── operations.ts
        │   │   ├── policies.ts
        │   │   ├── raw.ts
        │   │   ├── request.ts
        │   │   ├── retry.ts
        │   │   ├── runtime.ts
        │   │   ├── safety.ts
        │   │   ├── testing.ts
        │   │   ├── training.ts
        │   │   ├── transport.ts
        │   │   ├── workflows.ts
        │   │   ├── evaluations.ts
        │   │   ├── jobs.ts
        │   │   ├── runs.ts
        │   │   └── experiments.ts
        │   ├── tests/
        │   │   ├── sdk.test.ts
        │   │   ├── policy_admin.test.ts
        │   │   ├── agents.test.ts
        │   │   ├── workflow_approval.test.ts
        │   │   ├── evaluations.test.ts
        │   │   ├── job_run.test.ts
        │   │   ├── training.test.ts
        │   │   └── experiments.test.ts
        │   └── tsconfig.json
        ├── rpc-coverage.yaml
        └── rpc-coverage.generated.json
```
<!-- END GENERATED: repository-path-manifest -->

### A6.1 The tree is a governed namespace

The source tree is a map of authority. A path communicates semantic ownership, dependency direction, release expectations, and operational responsibility. Moving code across top-level paths is therefore an architectural change, not clerical cleanup.

A path is valid only when:

- its parent domain is the canonical semantic owner;
- its owner exists in CODEOWNERS and component metadata;
- its dependencies comply with Appendix A7;
- it contains at least one maintained target or an explicitly reserved interface with an approved consumer milestone;
- its name describes a durable capability;
- its tests and documentation live close enough to evolve atomically.

### A6.2 Top-level directory contracts

| Directory | Owns | Produces | Must not become |
|---|---|---|---|
| `.buildkite/` | authoritative heavy CI graph and trusted build execution source | plans and CI evidence | product logic, deployment state, duplicate policy authority |
| `mindclade/.github/` | repo-local GitHub metadata and thin reusable-workflow callers | repository event/required-check bridge | organization templates/settings, heavy build graph, release or deploy engine |
| root workspace files | toolchains, lockfiles, repository identity, developer command index | hermetic workspace closure | domain configuration or environment desired state |
| `protocols/` | cross-process and manifest contracts | generated clients, schema baselines | business implementation |
| `libs/` | horizontal language foundations | reusable packages | dumping ground for domain code |
| `bio/` | canonical biological semantics and formats | typed records, parsers, bindings | dataset workflow engine |
| `data/` | acquisition through feature-dataset publication | source snapshots, datasets, lineage | model implementation |
| `runtime/` | generic execution primitives | topology, RNG, compiler/runtime services | model/trainer policy |
| `kernels/` | qualified optimized operations | kernel bundles, benchmarks, reports | ungoverned optimization scripts |
| `models/` | model mathematics and logical state | model packages and bundles | launcher or experiment database |
| `training/` | training semantics and execution planning | recipes, plans, checkpoints, evidence | provider-owned trainer shell |
| `evaluation/` | evaluation meaning and statistics | immutable reports | trainer callback collection |
| `inference/` | pure inference pipelines | output artifacts and diagnostics | network gateway |
| `agents/` | tool, policy, workflow, decision, and bounded-autonomy semantics | agent definitions, workflow plans, decision evidence | alternate job system, scientific domain, or unrestricted code runner |
| `services/` | durable service composition | service images and APIs | shared domain library location |
| `workers/` | queue/runtime composition | worker images and result manifests | owner of scientific semantics |
| `sdk/` | supported client experience | versioned SDK packages | generated code passthrough |
| `kits/` | governed authoring and packaging facades | MCDK–MADK assemblies, validation, CLIs | duplicate domain implementations or runtime authorities |
| `apps/` | product interfaces | web applications | policy or database authority |
| `deploy/` | service-owned deployment packages | charts/bases/CRDs | live environment state |
| `research/` | isolated exploration | reproducible studies | production dependency |
| `tests/` | cross-domain qualification | end-to-end evidence | replacement for package tests |
| `tools/` | tested repository automation | generators, linters, release tools | product behavior |
| `docs/` | architecture and operations knowledge | published documentation | hidden source of runtime config |
| `third_party/` | controlled vendoring and notices | patches, mirrors, license evidence | miscellaneous copied source |

### A6.3 Release-unit mapping

Source packages and release units are intentionally many-to-many.

```text
several packages
→ one worker/service image

one model family
→ model wheel + model bundle + evaluation evidence

one protocol package
→ generated language clients + SDK updates

one kernel operation
→ multiple hardware-specific kernel artifacts
```

Each releasable target declares its source closure, build target, runtime entrypoint, configuration schema, artifact type, and qualification dependencies. The tree must not imply that every directory is independently released.

### A6.4 Creation policy for optional directories

Directories marked “create when justified” are not pre-created. Their creation PR must include:

```text
first concrete consumer
owner
public contract
why existing package cannot own the capability
minimum test and release evidence
expected dependency direction
removal condition if experimental
```

Examples include `training/autotune/`, `training/rl/`, Monarch orchestration, webhook dispatch, and public Go/Rust SDKs.

### A6.5 Generated, derived, and vendored material

Generated files live under predictable `generated/` or build output paths and carry a generator header. Their source schema, generator version, and drift check are explicit.

Derived assets that are expensive or environment-specific are artifacts, not Git source. Examples include compiled kernels, exported OpenAPI bundles, model weights, feature shards, benchmark databases, and documentation search indexes.

Vendored code is allowed only when:

- availability, reproducibility, patching, or licensing requires it;
- upstream source revision and integrity are pinned;
- modifications live as reviewable patches where practical;
- license and notice obligations are recorded;
- an owner tracks upstream updates and removal.

### A6.6 Adjacency and locality rules

Keep together what must change together:

- a protocol with compatibility tests and generation configuration;
- a parser with malformed fixtures and conformance tests;
- a kernel with reference, dispatch, qualification, and benchmarks;
- a model family with state migration and bundle conversion;
- a service with migrations, deployment base, runbook links, and component metadata;
- a worker with job contract, cancellation, artifact, and retry tests.

Keep apart what must have independent authority:

- model mathematics and training execution;
- durable job state and Kubernetes observed state;
- public SDK types and service database models;
- source-faithful parsing and scientific normalization;
- service deployment defaults and live environment overlays.

### A6.7 Component catalog and graph metadata

A repository catalog is generated from `component.yaml`, package metadata, Bazel targets, CODEOWNERS, and schema registries. It should expose:

```text
component and package identities
owners and maturity
source paths and public entrypoints
build/test/release targets
incoming and outgoing dependencies
protocols and artifacts
runtime and hardware requirements
data classifications
SLO/runbook links
qualification status
deprecation dates
```

Catalog generation fails on duplicate identity, missing owner, invalid target, forbidden dependency, stale protocol reference, or unresolvable runbook/release metadata.

### A6.8 Path migration protocol

Moving a public or durable capability follows:

1. declare old and new ownership;
2. preserve or migrate public import/resource names;
3. add compatibility shims only for a bounded window;
4. update Bazel labels, generated references, manifests, CODEOWNERS, docs, and release targets atomically;
5. provide state/artifact migration where path identity was incorrectly persisted;
6. test consumers from supported historical revisions or packages;
7. remove shims at the declared deadline.

Physical source paths must not be persisted as long-term resource identity.

### A6.9 Repository tree validation

Presubmit checks enforce:

- approved top-level directories only;
- exact agreement between the explicit file tree, `stub_catalog.yaml`, repository path manifest, generated-file manifest, and populated paths;
- no literal generator tokens, brace expansion, wildcards, ellipses, empty physical leaf directories, README-only production packages, or unexpanded generic stubs;
- required files for package/component class;
- no empty production scaffolds;
- no nested ecosystem roots without an approved boundary;
- no environment-specific production overlays;
- generated-file placement and drift;
- visibility and ownership consistency;
- no restricted artifact extensions or oversized binaries;
- documentation links for public/deployable components.

### A6.10 Definition of done

1. Every populated path corresponds to a real owner and target.
2. Top-level directory contracts are machine-enforced.
3. Release units are declared independently of directory shape.
4. Optional capabilities are created only with a first consumer.
5. Generated, derived, and vendored material follow distinct policies.
6. Path moves preserve compatibility and artifact lineage.
7. The generated component catalog accurately reflects the repository graph.
8. Every approved target file and activation stub is listed explicitly in the tree; generated outputs are listed by deterministic path and verified against `protocols/generated/generated-files.manifest.json`; every populated stub contains a real target and qualification evidence.
9. Repo-local GitHub control files and every external operational repository pass the disjoint-authority checks in Appendix A3.
