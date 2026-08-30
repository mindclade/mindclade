## Appendix A3 — Repository estate and trust boundaries

```text
.github
    |
    | shared organization templates and reusable GitHub workflows
    v
github-config
    |
    | GitHub Free public-repository policy, repository settings,
    | branch protection, Actions/OIDC governance
    v
+----------------------+----------------------+----------------------+
| bootstrap            | infrastructure-live  | gitops               |
|                      |                      |                      |
| durable identity,    | normal cloud desired| Kubernetes desired   |
| state, recovery,     | state and shared    | state, Argo CD apps, |
| break-glass trust    | infrastructure      | environment promotion|
+----------------------+----------------------+----------------------+
                                  ^
                                  |
                      immutable artifact digests
                                  |
                                  v
                      mindclade public source monorepo
```

### Repository ownership

| Repository | Owns | Must not own |
|---|---|---|
| `.github` | Organization profile, community health files, shared workflow implementations and templates | Product code, cloud state, environment credentials |
| `mindclade/.github/` | Monorepo-local GitHub metadata and thin reusable-workflow/Buildkite bridges | Organization settings, heavy builds, release, deployment, or privileged founder governance |
| `github-config` | Desired organization/repository governance, teams, repository-level protection, Actions policy, OIDC policy, and the bounded FBE-0001 mode of its existing protected-apply workflow | Runtime services or Kubernetes application manifests; evidence that desired controls are live; privilege outside FBE-0001 or normal independently reviewed apply |
| `bootstrap` | Minimum durable cloud trust, state, recovery, break-glass IAM | Normal application infrastructure |
| `infrastructure-live` | Cloud projects/accounts, networks, clusters, storage, databases, registries, observability backends | Application source or model code |
| `gitops` | Environment-specific Kubernetes desired state and promotion by immutable digest | Building application artifacts |
| `mindclade` | Public product, model, data, training, evaluation, inference, service, worker, SDK, and service-owned deployment source | Secrets, protected data, live cloud/environment desired state, or production authority |
| Public SDK repositories | Stable public SDKs only when external distribution requires independent lifecycle and visibility | Internal implementation details |

### Monorepo deployment boundary

The monorepo may contain:

- service-owned Helm charts or Kustomize bases;
- CRDs and generated CRD documentation;
- local and integration-test deployment definitions;
- policy tests;
- container build definitions;
- canonical default configuration.

The monorepo must not contain:

- production cluster names or credentials;
- production secret references tied to a specific environment;
- mutable image tags used for production;
- environment promotion state;
- Terraform root modules for live environments.

The `gitops` repository consumes versioned deployment packages and immutable image digests produced by the monorepo.

### A3.1 Trust-zone model

The repository estate is divided into trust zones with different compromise assumptions.

| Zone | Primary risk | Required controls |
|---|---|---|
| Source governance | unauthorized or unilateral code/policy change | protected refs, review, CODEOWNERS, signed identity, audit |
| Bootstrap | loss or takeover of root trust and state | minimal surface, break-glass controls, independent recovery, immutable backups |
| Infrastructure desired state | privilege expansion or destructive cloud change | plan review, policy checks, environment separation, drift detection |
| Application source | vulnerable or incorrect product/model code | affected CI, qualification, provenance, least-privilege release identity |
| Artifact production | artifact substitution or poisoned build | isolated build, content digests, SBOM, signed provenance, verification |
| GitOps promotion | deployment of wrong or unapproved digest | protected promotion, policy gates, immutable references, rollback |
| Runtime | tenant escape, data exfiltration, workload compromise | workload identity, network/egress policy, sandboxing, admission controls |

A repository boundary is justified only when it creates a real trust, lifecycle, or blast-radius boundary. Splitting repositories for visual neatness alone is prohibited.

### A3.2 Cross-repository artifact protocol

The monorepo communicates with `gitops` through immutable release records, not copied source or mutable tags.

```text
protected source revision
→ authoritative build
→ immutable artifacts
→ release manifest and attestations
→ verification policy
→ GitOps promotion change referencing digests
→ environment reconciliation
→ observed deployment status
→ promotion/audit receipt
```

The release manifest is the handoff contract. It contains component identity, artifact digests, deployment-package digest, compatibility constraints, migration requirements, SBOM/provenance, qualification level, and signer identity.

GitOps must fail closed when:

- the digest is absent or mutable;
- provenance does not match the artifact;
- signer or builder identity is not trusted;
- required qualification or policy evidence is missing;
- a database/schema migration order is invalid;
- an environment constraint is unsatisfied;
- the component is deprecated or blocked.

### A3.3 Identity and OIDC boundaries

Each repository and automation path uses a distinct workload identity. Trust is scoped by:

```text
organization
repository
protected ref or environment
workflow/pipeline identity
build target or release class
requested cloud audience
```

No build identity should automatically receive deployment authority. No pull-request identity receives production secrets, release signing, shared write caches, or environment mutation.

Long-lived credentials are prohibited except tightly controlled break-glass material. Break-glass use is time-bounded, independently approved where possible, logged, and followed by credential rotation and incident review.

### A3.4 Environment ownership and configuration handoff

The monorepo owns service and workload **defaults**. GitOps owns environment-specific **decisions**.

| Concern | Monorepo | GitOps/infrastructure |
|---|---:|---:|
| container entrypoint and ports | yes | no |
| default resource model and probes | yes | may override within schema |
| CRDs and configuration schemas | yes | consumes |
| production project/cluster names | no | yes |
| workload identity binding | declares requirement | binds identity |
| secret names/values | only abstract references | environment-specific reference/value system |
| image digest | produces | selects/promotes |
| model or recipe digest | produces/validates | selects approved reference |
| autoscaling and disruption policy | safe defaults | environment tuning |
| network/egress policy | required capabilities and base policy | concrete environment policy |

Overrides are schema-validated and cannot change immutable semantic inputs such as recipe, model, dataset, or executable plan without creating a new job or release identity.

### A3.5 Drift and reconciliation

Drift is classified:

- **source drift**: generated outputs or dependency metadata differ from declared source;
- **infrastructure drift**: cloud resources differ from desired state;
- **deployment drift**: cluster objects differ from GitOps state;
- **artifact drift**: mutable tag or alias resolves differently than recorded;
- **runtime drift**: running process reports an undeclared binary, config, provider, or plan;
- **policy drift**: permissions, controls, or qualification evidence expire.

Each class has a detector, owner, severity, and repair path. Runtime drift affecting numerical or security semantics terminates or quarantines the workload rather than being silently reconciled in place.

### A3.6 Repository compromise and recovery scenarios

Required drills include:

1. `.github` or workflow-template compromise;
2. malicious or accidental ruleset change in `github-config`;
3. loss of bootstrap state or break-glass access;
4. compromised CI agent or shared cache;
5. artifact registry substitution attempt;
6. GitOps repository compromise;
7. production cluster drift while Git remains intact;
8. source repository unavailable during an incident;
9. signer or workload-identity revocation;
10. rollback to the last trusted release manifest.

Recovery documentation must identify independent backups, trust roots, minimum personnel, required approvals, and evidence-preservation steps.

### A3.7 Repository creation and retirement

A new repository requires:

```text
owner and purpose
trust/lifecycle boundary not expressible in existing repository
source and artifact handoff contract
identity and permission model
CI/release policy
backup and recovery plan
dependency and visibility impact
retirement condition
```

Repository retirement requires preserving tags, release manifests, provenance, audit records, and migration history for the retention period. Deleting a repository must not orphan artifact lineage.

### A3.8 Canonical names, status, and common repository contract

`mindclade/.github/` means the directory inside the product monorepo. `.github` means the separately protected organization repository named `.github`. A change description, policy, CODEOWNER rule, or audit event MUST use the qualified name when ambiguity is possible.

Every path in the following trees has one of four meanings:

| Mark | Meaning | Creation rule |
|---|---|---|
| no mark | required governed source or metadata | create when the repository is activated |
| `# generated` | reproducible output checked for drift | generator owns it; hand edits fail CI |
| `# local output` | ignored plan/test output | never committed or used as authority |
| `# JIT` | approved activation stub | create only at the named decision gate with a real consumer |

“Stub” means the minimum reviewable first-PR surface named in these trees. It is not an empty directory or placeholder implementation. Each activated stub contains valid metadata, an executable validation/build target where applicable, an owner, tests for its contract, and no unfinished body marker. At `CONNECTED_QUALIFIED`, all five repositories use protected default branches, signed human or workload identity, `CODEOWNERS`, dependency pinning, secret scanning, immutable CI evidence, and a root `component.yaml` identifying owner, repository class, trust tier, recovery tier, and release behavior. `FOUNDER_BOOTSTRAPPED` is a source-only intermediate state and is not evidence that these connected controls are active.

Common rules are:

- repository-local `.github/workflows/` files are thin callers of pinned reusable workflows from the organization `.github` repository; the only privileged founder exception is the exact single-use FBE-0001 mode of `github-config/.github/workflows/protected-apply.yml` under A3.10;
- reusable workflows pin every third-party action by commit digest, set explicit permissions, reject untrusted secret access, and emit a typed evidence record;
- plan and apply are separate identities; apply accepts the exact reviewed plan digest and protected revision only;
- state backends use locking, encryption, versioning, retention, access logging, and independently tested recovery;
- provider-generated state, plan files, credentials, kubeconfigs, decrypted secrets, and rendered secret values are ignored and prohibited from commits;
- all desired-state writes are pull requests; emergency mutation requires an audited break-glass event, bounded lease, and mandatory reconciliation PR;
- compatibility is schema-versioned for cross-repository manifests; repository paths and provider object names are never public resource identity.

#### Public GitHub Free founder-bootstrap profile

The canonical `mindclade/mindclade` repository is public under GitHub Free and uses repository-level protection. Public visibility does not make the proprietary source license permissive and does not authorize secrets, protected biological data, model weights, customer artifacts, provider state, or production configuration in Git.

Readiness progresses only as follows:

```text
BLOCKED -> FOUNDER_BOOTSTRAPPED -> CONNECTED_QUALIFIED
```

ADR-0008 and `docs/governance/exceptions/FBE-0001.yaml` permit `FOUNDER_BOOTSTRAPPED` to proceed with Wave 1 source work while `production_authority` remains `false`. Before the workflow exists on `github-config:main`, the record allows `mindclade-founder` one ordinary pull-request merge publishing only the pinned `.github/workflows/protected-apply.yml` artifact. This distinct initial-publication state is bound to the target branch, exact SHA-256 content digest, actor, and immutable pull-request receipt containing the actual merge SHA, PR URL and number, merge actor, and UTC time; direct `main` pushes, protection waivers, governance mutations, and independent-review claims are denied. It exists only to make the normal repository-local entry point available. That entry point may then perform one fail-closed FBE-0001 foundation execution, bound to the exact public `mindclade/mindclade` repository, `main`, protected revision, and foundation identity. It may only create, adopt, protect, set a non-secret repository variable, and activate the foundation identity. It may not delete, replace, bypass, promote to production, export a secret, force-push, or extend itself. The authorization expires after 2026-09-30.

The workflow must preserve no bypass and two approvals after protection is established. A subject- and revision-bound connected receipt is the consumption authority. The repository records the authorization contract but neither stores a secret nor invents a receipt. Independent review, branch-protection observation, required-check evidence, trusted Buildkite definition evidence, signing trust, and recovery evidence remain required for `CONNECTED_QUALIFIED`.

#### Repo-local `mindclade/.github/` blueprint

The exact directory tree is part of Appendix A6. Developer Platform owns repository event mapping, issue/PR metadata, dependency-update configuration, code scanning entrypoints, and the Buildkite dispatch/required-check bridge; Security reviews permissions and trust-context handling. Each workflow is a thin caller pinned to an organization `.github` reusable workflow or invokes a bounded repo-local action whose implementation is fully present in the directory. No monorepo-local workflow is privileged by FBE-0001; the exception binds only `github-config/.github/workflows/protected-apply.yml` under A3.10. Monorepo-local workflows MUST NOT encode the authoritative test graph, compile/release product artifacts, assume production credentials, or deploy.

On a pull request, repo-local metadata validation classifies the event and source trust, then the dispatch workflow calls the shared reusable workflow with the exact revision. Buildkite returns typed evidence; the repo-local required-check bridge verifies revision, plan, caller, and trust context before publishing one conclusion. GitHub-native CodeQL, dependency review, scorecard, documentation, and mirror verification use explicit least-privilege permissions. Cancellation propagates to Buildkite; an unavailable or ambiguous downstream result stays non-successful. Tests validate YAML/action syntax, pinning, permissions, fork behavior, required-check freshness, issue forms, CODEOWNERS coverage, and label/config drift. Repo-local workflow changes cannot alter organization rulesets or self-approve protected releases.

### A3.9 Organization `.github` repository

#### Organization `.github` canonical file tree

```text
.github/
├── .github/
│   ├── actions/
│   │   ├── validate-trusted-context/
│   │   │   ├── action.yml
│   │   │   └── README.md
│   │   ├── verify-pinned-actions/
│   │   │   ├── action.yml
│   │   │   └── README.md
│   │   └── publish-ci-evidence/
│   │       ├── action.yml
│   │       └── README.md
│   ├── workflows/
│   │   ├── reusable-buildkite-dispatch.yml
│   │   ├── reusable-required-check.yml
│   │   ├── reusable-metadata-validation.yml
│   │   ├── reusable-documentation-check.yml
│   │   ├── reusable-dependency-review.yml
│   │   ├── reusable-codeql.yml
│   │   ├── reusable-scorecard.yml
│   │   └── self-test.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug.yml
│   │   ├── security-control-gap.yml
│   │   ├── architecture-change.yml
│   │   ├── scientific-correctness.yml
│   │   └── config.yml
│   ├── actionlint.yaml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── profile/
│   └── README.md
├── workflow-templates/
│   ├── buildkite-bridge.yml
│   ├── buildkite-bridge.properties.json
│   ├── repository-metadata.yml
│   └── repository-metadata.properties.json
├── schemas/
│   ├── trusted_context.schema.json
│   └── ci_evidence.schema.json
├── policy/
│   ├── action_pinning.rego
│   ├── workflow_permissions.rego
│   ├── reusable_workflow_interface.rego
│   └── tests/
│       ├── action_pinning_test.rego
│       ├── workflow_permissions_test.rego
│       └── reusable_workflow_interface_test.rego
├── tests/
│   ├── fixtures/
│   │   ├── trusted_pull_request.json
│   │   ├── untrusted_pull_request.json
│   │   └── protected_release.json
│   ├── test_reusable_workflow_contract.py
│   ├── test_declared_permissions.py
│   └── test_action_digest_pinning.py
├── tools/
│   ├── validate_reusable_workflows.py
│   └── emit_ci_evidence.py
├── BUILD.bazel
├── MODULE.bazel
├── component.yaml
├── justfile
├── .editorconfig
├── .gitignore
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── GOVERNANCE.md
├── LICENSE
├── README.md
├── SECURITY.md
└── SUPPORT.md
```

#### Organization `.github` implementation blueprint

**Responsibility.** Developer Platform owns reusable workflow interfaces and community-health defaults; Security approves permissions, action sources, OIDC use, and changes to protected workflow outputs. It does not own GitHub settings, repository rulesets, branch protection, build semantics, release policy, or deployment.

**Interfaces and flow.** Callers use a versioned reusable-workflow ref pinned to a protected commit or signed release. Inputs are typed, optional secrets are explicitly declared, and outputs include source revision, caller repository, trust classification, plan/build identifier, conclusion, and evidence digest. A caller event is validated, then either dispatches authoritative Buildkite work or performs a bounded GitHub-native check. The required-check workflow verifies the result belongs to the exact caller revision and trust context; it never treats a successful result from another commit as current.

**State, failure, and recovery.** Git history is the desired-state record; GitHub run metadata is transient evidence indexed by the emitted evidence record. Dispatch timeout, unavailable Buildkite, missing output, permission mismatch, unpinned action, or stale result fails closed. Retries are bounded and preserve the same correlation ID; cancellation propagates to the dispatched build where supported. Recovery uses a retained signed workflow revision and the `github-config` ruleset rollback path.

**Security, observability, and qualification.** Every job declares minimal permissions, protected jobs reject fork secrets, OIDC audiences/subjects are checked at the target, and workflow code cannot self-approve a ruleset change. Signals include dispatch latency/failure, stale-result rejection, permission denials, action-pin drift, and reusable-workflow adoption. Qualification runs fixture calls from trusted, untrusted, and release contexts, schema/policy tests, actionlint/yamllint, pin verification, and a compromise drill. GitHub-hosted concurrency is bounded; heavy or privileged execution stays in Buildkite.

### A3.10 `github-config` repository

#### `github-config` canonical file tree

```text
github-config/
├── .github/
│   ├── workflows/
│   │   ├── pull-request.yml
│   │   ├── drift-detection.yml
│   │   └── protected-apply.yml
│   ├── actionlint.yaml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── config/
│   ├── organization.yaml
│   ├── actions-policy.yaml
│   ├── security-policy.yaml
│   ├── oidc-policy.yaml
│   ├── members.yaml
│   ├── outside-collaborators.yaml
│   ├── teams/
│   │   ├── architecture.yaml
│   │   ├── biological-safety.yaml
│   │   ├── computational-biology.yaml
│   │   ├── data-platform.yaml
│   │   ├── developer-platform.yaml
│   │   ├── ml-systems.yaml
│   │   ├── platform-operations.yaml
│   │   ├── product-engineering.yaml
│   │   ├── release-engineering.yaml
│   │   └── security.yaml
│   ├── repositories/
│   │   ├── dot-github.yaml
│   │   ├── github-config.yaml
│   │   ├── bootstrap.yaml
│   │   ├── infrastructure-live.yaml
│   │   ├── gitops.yaml
│   │   └── mindclade.yaml
│   ├── rulesets/
│   │   ├── application-source.yaml
│   │   ├── governance-source.yaml
│   │   ├── infrastructure-source.yaml
│   │   ├── deployment-source.yaml
│   │   └── release-tags.yaml
│   ├── environments/
│   │   ├── trusted-build.yaml
│   │   ├── release-signing.yaml
│   │   ├── infrastructure-apply.yaml
│   │   └── production-promotion.yaml
│   └── integrations/
│       ├── buildkite.yaml
│       ├── artifact-signing.yaml
│       └── gitops-controller.yaml
├── schemas/
│   └── v1/
│       ├── organization.schema.json
│       ├── actions_policy.schema.json
│       ├── security_policy.schema.json
│       ├── oidc_policy.schema.json
│       ├── membership.schema.json
│       ├── team.schema.json
│       ├── repository.schema.json
│       ├── ruleset.schema.json
│       ├── environment.schema.json
│       └── integration.schema.json
├── compiler/
│   ├── cmd/
│   │   └── github-configctl/
│   │       └── main.go
│   ├── internal/
│   │   ├── catalog/
│   │   │   └── catalog.go
│   │   ├── validation/
│   │   │   └── validation.go
│   │   ├── rendering/
│   │   │   └── rendering.go
│   │   ├── diff/
│   │   │   └── github_diff.go
│   │   └── evidence/
│   │       └── plan_evidence.go
│   ├── go.mod
│   ├── go.sum
│   └── BUILD.bazel
├── opentofu/
│   ├── modules/
│   │   ├── organization-settings/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── repository-governance/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── team-access/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── ruleset/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   └── repository-environment/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── live/
│       └── organization/
│           ├── backend.tf
│           ├── versions.tf
│           ├── providers.tf
│           ├── main.tf
│           ├── imports.tf
│           └── outputs.tf
├── policy/
│   ├── least_privilege.rego
│   ├── protected_rulesets.rego
│   ├── workflow_sources.rego
│   ├── oidc_subjects.rego
│   ├── environment_approvals.rego
│   └── tests/
│       ├── least_privilege_test.rego
│       ├── protected_rulesets_test.rego
│       ├── workflow_sources_test.rego
│       ├── oidc_subjects_test.rego
│       └── environment_approvals_test.rego
├── tests/
│   ├── contract/
│   │   ├── test_catalog_schema.py
│   │   └── test_compiler_determinism.py
│   ├── plan/
│   │   ├── test_ruleset_plan.py
│   │   └── test_permission_reduction.py
│   ├── drift/
│   │   └── test_observed_state_diff.py
│   └── recovery/
│       └── test_last_known_good_restore.py
├── runbooks/
│   ├── unauthorized-settings-change.md
│   ├── oidc-policy-lockout.md
│   ├── compromised-github-app.md
│   └── governance-state-restore.md
├── BUILD.bazel
├── MODULE.bazel
├── component.yaml
├── justfile
├── .editorconfig
├── .gitignore
├── LICENSE
├── README.md
└── SECURITY.md
```

#### `github-config` implementation blueprint

**Responsibility.** Developer Platform is semantic owner; Security is required reviewer for Actions, OIDC, app, environment, and token policy; team owners approve membership. The YAML catalog is the human-reviewed authority and the compiled OpenTofu graph is derived. Direct provider edits are break-glass drift, not a second source of truth.

**Execution and consistency.** Pull-request CI validates schemas, compiles deterministically, imports observed GitHub state read-only, renders a plan, evaluates policy, and signs the plan digest. Before that CI/workflow can be present on its own default branch, the FBE record permits exactly one non-privileged PR merge by the declared actor that publishes only the pinned workflow artifact to `github-config:main`; the source contract requires its canonical content digest and an immutable PR receipt containing the observed merge SHA, PR URL and number, merge actor, and UTC time, and rejects direct-main publication, branch-protection waiver, independent-review claims, governance mutations, and replay. That publication is not a protected apply and does not activate any provider or production authority. Protected apply rechecks revision, plan digest, approvals, provider version, and observed-state preconditions before serial execution. Repository/team/ruleset changes are convergent and idempotent; removals require an explicit destructive-change acknowledgement and dependency analysis. Apply concurrency is one per organization. Under ADR-0008 and an unexpired, unused FBE-0001 only, the existing `github-config/.github/workflows/protected-apply.yml` entry point may perform one founder foundation execution before `CONNECTED_QUALIFIED`; this is not a new or parallel monorepo workflow. It must bind `mindclade/mindclade`, `main`, the exact protected revision and foundation identity, enforce the five allowed and seven denied operations, and consume authority only through the immutable connected receipt. Missing or mismatched scope, expiry, unused state, workflow identity, revision, identity, or receipt fails closed. After consumption or expiry, the workflow retains only its normal independently reviewed protected-apply authority.

**Failure and recovery.** Rate limits use bounded backoff and checkpointed reconciliation; permission loss, provider drift, partial apply, or ambiguous API completion stops the run and re-plans from observed state. Cancellation stops before the next mutation but does not pretend already accepted GitHub mutations rolled back. Last-known-good configuration plus state backup supports restoration; lockout recovery uses bootstrap-controlled break-glass identity. Drift detection runs at least hourly for critical rules and daily for full configuration.

**Security, signals, and qualification.** No personal access token is accepted for apply. A dedicated GitHub App or equivalent short-lived identity has narrowly enumerated administration permissions. Every mutation emits actor, plan, before/after, API request correlation, and policy evidence. Required tests cover schema evolution, compiler determinism, permission reduction, team removal, ruleset lockout, OIDC claim denial, rate-limit recovery, drift, and last-known-good restore. Schema v1 additions are backward compatible; breaking catalog changes require a new major schema and migration tool.

### A3.11 `bootstrap` repository

#### `bootstrap` canonical file tree

```text
bootstrap/
├── .github/
│   ├── workflows/
│   │   ├── pull-request.yml
│   │   ├── recovery-verification.yml
│   │   └── protected-apply.yml
│   ├── actionlint.yaml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── manifests/
│   ├── trust-anchors.yaml
│   ├── state-backends.yaml
│   ├── identity-federation.yaml
│   ├── signing-roots.yaml
│   ├── audit-roots.yaml
│   ├── break-glass-roles.yaml
│   └── recovery-policy.yaml
├── schemas/
│   └── v1/
│       ├── trust_anchor.schema.json
│       ├── state_backend.schema.json
│       ├── federation.schema.json
│       ├── signing_root.schema.json
│       ├── audit_root.schema.json
│       ├── break_glass.schema.json
│       └── recovery_policy.schema.json
├── opentofu/
│   ├── modules/
│   │   ├── state-backend/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── audit-root/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── workforce-identity/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── github-federation/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── buildkite-federation/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── gitops-federation/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── signing-root/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── break-glass/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   └── recovery-exports/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── live/
│       ├── root-trust/
│       │   ├── backend.tf
│       │   ├── versions.tf
│       │   ├── providers.tf
│       │   ├── main.tf
│       │   └── outputs.tf
│       └── recovery-plane/
│           ├── backend.tf
│           ├── versions.tf
│           ├── providers.tf
│           ├── main.tf
│           └── outputs.tf
├── policy/
│   ├── root_separation.rego
│   ├── federation_claims.rego
│   ├── key_administration.rego
│   ├── state_protection.rego
│   ├── break_glass.rego
│   └── tests/
│       ├── root_separation_test.rego
│       ├── federation_claims_test.rego
│       ├── key_administration_test.rego
│       ├── state_protection_test.rego
│       └── break_glass_test.rego
├── recovery/
│   ├── restore-manifest.yaml
│   ├── independent-contact-procedure.md
│   ├── offline-evidence-procedure.md
│   └── quarterly-drill-procedure.md
├── tests/
│   ├── contract/
│   │   └── test_manifest_schemas.py
│   ├── plan/
│   │   └── test_minimum_privilege.py
│   ├── failure/
│   │   └── test_partial_bootstrap_apply.py
│   └── recovery/
│       └── test_isolated_restore.py
├── tooling/
│   ├── cmd/
│   │   └── bootstrapctl/
│   │       └── main.go
│   ├── internal/
│   │   ├── manifest/
│   │   │   └── manifest.go
│   │   ├── plan/
│   │   │   └── plan.go
│   │   ├── evidence/
│   │   │   └── evidence.go
│   │   └── recovery/
│   │       └── recovery.go
│   ├── go.mod
│   ├── go.sum
│   └── BUILD.bazel
├── runbooks/
│   ├── state-backend-unavailable.md
│   ├── root-identity-compromise.md
│   ├── signing-root-recovery.md
│   └── break-glass-activation.md
├── BUILD.bazel
├── MODULE.bazel
├── component.yaml
├── justfile
├── .editorconfig
├── .gitignore
├── LICENSE
├── README.md
└── SECURITY.md
```

#### `bootstrap` implementation blueprint

**Responsibility.** Security owns root trust and break-glass policy; Cloud Platform owns state-backend and federation implementation; two independent approvers are required for apply and recovery. Bootstrap produces typed, non-secret outputs for downstream backends and identity bindings. It MUST NOT create workload clusters, application databases, ordinary buckets, networks beyond what root recovery requires, or any Kubernetes release.

**Execution and state.** Bootstrap uses a deliberately small OpenTofu graph applied from an isolated protected runner. The initial state-backend creation uses a documented one-time local state ceremony; state is immediately migrated, encrypted, locked, versioned, replicated, and verified, then the local copy is destroyed through an audited procedure. Subsequent changes use plan-digest binding and serial apply. Root keys are non-exportable where supported; recovery material is encrypted to independently controlled custodians.

**Failure and recovery.** Partial initial creation resumes only after importing and comparing observed resource identity. Ambiguous key, identity, or state mutations stop and require manual security review. Break-glass grants are time-bound, approval-bound, separately alerted, and automatically revoked. Quarterly isolated restore proves state, audit history, federation, signer verification, and downstream reattachment without access to the normal CI plane. Bootstrap availability is not required for ordinary deployment after foundations exist.

**Signals and qualification.** Monitor state-version/replication health, denied federation, key use/admin separation, break-glass grants, audit-sink delivery, backup age, and recovery-drill age. Qualification covers destructive-plan denial, claim substitution, state lock loss, lost runner, partial apply, compromised federation, signer rotation, and recovery from independently retained evidence. Bootstrap schemas are additive within v1; root-resource replacement is a separately approved migration, never an in-place convenience change.

### A3.12 `infrastructure-live` repository

#### `infrastructure-live` canonical file tree

```text
infrastructure-live/
├── .github/
│   ├── workflows/
│   │   ├── pull-request.yml
│   │   ├── drift-detection.yml
│   │   ├── protected-apply.yml
│   │   └── disaster-recovery.yml
│   ├── actionlint.yaml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── catalog/
│   ├── environments.yaml
│   ├── regions.yaml
│   ├── project-classes.yaml
│   ├── data-classes.yaml
│   ├── resource-profiles.yaml
│   ├── accelerator-profiles.yaml
│   └── service-capabilities.yaml
├── schemas/
│   └── v1/
│       ├── environment.schema.json
│       ├── region.schema.json
│       ├── project_class.schema.json
│       ├── data_class.schema.json
│       ├── resource_profile.schema.json
│       ├── accelerator_profile.schema.json
│       ├── service_capability.schema.json
│       └── infrastructure_export.schema.json
├── opentofu/
│   ├── modules/
│   │   └── gcp/
│   │       ├── project-factory/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── shared-vpc/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── private-dns/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── controlled-egress/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── artifact-registry/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── artifact-bucket/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── cloud-sql-postgres/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── pubsub-transport/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── secret-bindings/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── delegated-kms/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── gke-regional-cluster/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── gke-node-pool/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── workload-identity/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── observability-backend/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       ├── buildkite-agents/
│   │       │   ├── main.tf
│   │       │   ├── variables.tf
│   │       │   └── outputs.tf
│   │       └── argocd-management/
│   │           ├── main.tf
│   │           ├── variables.tf
│   │           └── outputs.tf
│   ├── stacks/
│   │   ├── foundation/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── network/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── artifacts/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── data-services/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── clusters/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── ci-execution/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   └── observability/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── live/
│       ├── development/
│       │   ├── foundation/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── network/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── artifacts/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── data-services/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── clusters/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── ci-execution/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   └── observability/
│       │       ├── backend.tf
│       │       ├── versions.tf
│       │       ├── providers.tf
│       │       ├── main.tf
│       │       ├── environment.auto.tfvars.json
│       │       └── outputs.tf
│       ├── staging/
│       │   ├── foundation/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── network/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── artifacts/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── data-services/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── clusters/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── ci-execution/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   └── observability/
│       │       ├── backend.tf
│       │       ├── versions.tf
│       │       ├── providers.tf
│       │       ├── main.tf
│       │       ├── environment.auto.tfvars.json
│       │       └── outputs.tf
│       ├── production/
│       │   ├── foundation/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── network/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── artifacts/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── data-services/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── clusters/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   ├── ci-execution/
│       │   │   ├── backend.tf
│       │   │   ├── versions.tf
│       │   │   ├── providers.tf
│       │   │   ├── main.tf
│       │   │   ├── environment.auto.tfvars.json
│       │   │   └── outputs.tf
│       │   └── observability/
│       │       ├── backend.tf
│       │       ├── versions.tf
│       │       ├── providers.tf
│       │       ├── main.tf
│       │       ├── environment.auto.tfvars.json
│       │       └── outputs.tf
│       └── restricted/
│           ├── foundation/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           ├── network/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           ├── artifacts/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           ├── data-services/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           ├── clusters/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           ├── ci-execution/
│           │   ├── backend.tf
│           │   ├── versions.tf
│           │   ├── providers.tf
│           │   ├── main.tf
│           │   ├── environment.auto.tfvars.json
│           │   └── outputs.tf
│           └── observability/
│               ├── backend.tf
│               ├── versions.tf
│               ├── providers.tf
│               ├── main.tf
│               ├── environment.auto.tfvars.json
│               └── outputs.tf
├── policy/
│   ├── organization_constraints.rego
│   ├── network_boundaries.rego
│   ├── workload_identity.rego
│   ├── encryption_and_retention.rego
│   ├── database_recovery.rego
│   ├── gke_security.rego
│   ├── accelerator_isolation.rego
│   ├── cost_guardrails.rego
│   └── tests/
│       ├── organization_constraints_test.rego
│       ├── network_boundaries_test.rego
│       ├── workload_identity_test.rego
│       ├── encryption_and_retention_test.rego
│       ├── database_recovery_test.rego
│       ├── gke_security_test.rego
│       ├── accelerator_isolation_test.rego
│       └── cost_guardrails_test.rego
├── tests/
│   ├── contract/
│   │   └── test_environment_plan.py
│   ├── plan/
│   │   ├── test_development_plan.py
│   │   ├── test_staging_plan.py
│   │   └── test_production_plan.py
│   ├── security/
│   │   └── test_cross_environment_denial.py
│   ├── failure/
│   │   └── test_partial_apply_reconciliation.py
│   ├── drift/
│   │   └── test_cloud_drift_classification.py
│   ├── recovery/
│   │   ├── test_database_restore.py
│   │   └── test_artifact_restore.py
│   └── capacity/
│       └── test_accelerator_profile.py
├── tooling/
│   ├── cmd/
│   │   └── infractl/
│   │       └── main.go
│   ├── internal/
│   │   ├── catalog/
│   │   │   └── catalog.go
│   │   ├── plan/
│   │   │   └── plan.go
│   │   ├── policy/
│   │   │   └── policy.go
│   │   ├── drift/
│   │   │   └── drift.go
│   │   └── exports/
│   │       └── exports.go
│   ├── go.mod
│   ├── go.sum
│   └── BUILD.bazel
├── runbooks/
│   ├── infrastructure-apply-failure.md
│   ├── cloud-drift.md
│   ├── network-isolation-failure.md
│   ├── cluster-control-plane-failure.md
│   ├── database-failover-and-restore.md
│   ├── artifact-storage-recovery.md
│   └── regional-recovery.md
├── BUILD.bazel
├── MODULE.bazel
├── component.yaml
├── justfile
├── .editorconfig
├── .gitignore
├── LICENSE
├── README.md
└── SECURITY.md
```

All infrastructure paths above are explicitly expanded to individual files. Authoritative infrastructure trees do not use brace or wildcard shorthand.

#### `infrastructure-live` implementation blueprint

**Responsibility.** Cloud Platform owns cloud resource modules, live root modules, provider mapping, state, drift, and recovery for development, staging, and production. The initial catalog binds `us-central1` as primary and `us-east4` as recovery. Security co-owns IAM, network, encryption, audit, residency, and any later restricted profile; Platform Operations co-owns SLO/capacity and hands typed cluster/service exports to GitOps. This repository does not select application release versions or contain application source. Region selection is source intent, not evidence that quota, protected apply, or recovery has passed.

**Interfaces and consistency.** It consumes bootstrap state-backend/federation outputs and an approved MCDK `EnvironmentPlan` schema. Catalog plus explicit live variables are human authority; OpenTofu state tracks provider realization; signed `InfrastructureExport` records expose only non-secret capability identities and digests to GitOps/control-plane configuration. One state root is used per environment and bounded stack to reduce blast radius. Plans bind revision, backend serial, provider locks, input digests, and policy results. Applies are serialized per root and use optimistic precondition checks.

**Failure, recovery, and scaling.** Provider throttling receives bounded retry; state lock loss, ambiguous mutation, destructive replacement, unexpected cross-stack dependency, policy failure, or observed drift aborts apply. Cancellation stops before the next provider mutation. Reconciliation begins with refresh/import, never blind reapply. Expand/migrate/contract governs databases and network transitions. Scaling occurs through versioned resource/accelerator profiles and independently reviewed capacity changes, not ad hoc console edits. Regional recovery reconstructs from state, catalog, backups, key references, and signed exports, then forces GitOps to revalidate destinations.

**Security, signals, and qualification.** Dedicated environment identities cannot mutate bootstrap roots or GitOps source. Production and restricted applies require protected environment approval. Signals include plan/apply duration, drift age/severity, state-lock contention, quota/capacity, failed backups, database replication, cluster/API health, IAM denials, egress changes, and cost variance. Tests include provider/module contract tests, representative plans for every environment, policy denial, partial apply/import, cross-environment denial, database/artifact restore, cluster rebuild, and capacity qualification. Modules use SemVer; live roots pin exact module digests/commits and migrate one bounded stack at a time.

### A3.13 `gitops` repository

#### `gitops` canonical file tree

```text
gitops/
├── .github/
│   ├── workflows/
│   │   ├── pull-request.yml
│   │   ├── promotion.yml
│   │   ├── drift-detection.yml
│   │   └── rollback-verification.yml
│   ├── actionlint.yaml
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── controllers/
│   ├── argocd/
│   │   ├── namespace.yaml
│   │   ├── repository-credentials-reference.yaml
│   │   ├── notifications.yaml
│   │   ├── resource-customizations.yaml
│   │   └── kustomization.yaml
│   └── applicationsets/
│       ├── platform-components.yaml
│       ├── control-plane-services.yaml
│       ├── execution-workers.yaml
│       └── environment-root.yaml
├── projects/
│   ├── platform.appproject.yaml
│   ├── services.appproject.yaml
│   ├── workers.appproject.yaml
│   └── restricted.appproject.yaml
├── platform/
│   ├── kueue/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   ├── jobset/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   ├── otel-collector/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   ├── external-secrets/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   ├── policy-controller/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   ├── gpu-operator/
│   │   ├── release.yaml
│   │   ├── values.yaml
│   │   └── kustomization.yaml
│   └── ingress/
│       ├── release.yaml
│       ├── values.yaml
│       └── kustomization.yaml
├── environments/
│   ├── development/
│   │   ├── cluster-set.yaml
│   │   ├── infrastructure-exports.yaml
│   │   ├── platform-releases.yaml
│   │   ├── service-releases.yaml
│   │   ├── worker-releases.yaml
│   │   ├── policy-bindings.yaml
│   │   ├── secret-references.yaml
│   │   └── kustomization.yaml
│   ├── staging/
│   │   ├── cluster-set.yaml
│   │   ├── infrastructure-exports.yaml
│   │   ├── platform-releases.yaml
│   │   ├── service-releases.yaml
│   │   ├── worker-releases.yaml
│   │   ├── policy-bindings.yaml
│   │   ├── secret-references.yaml
│   │   └── kustomization.yaml
│   ├── production/
│   │   ├── cluster-set.yaml
│   │   ├── infrastructure-exports.yaml
│   │   ├── platform-releases.yaml
│   │   ├── service-releases.yaml
│   │   ├── worker-releases.yaml
│   │   ├── policy-bindings.yaml
│   │   ├── secret-references.yaml
│   │   └── kustomization.yaml
│   └── restricted/
│       ├── cluster-set.yaml
│       ├── infrastructure-exports.yaml
│       ├── platform-releases.yaml
│       ├── service-releases.yaml
│       ├── worker-releases.yaml
│       ├── policy-bindings.yaml
│       ├── secret-references.yaml
│       └── kustomization.yaml
├── schemas/
│   └── v1/
│       ├── cluster_set.schema.json
│       ├── infrastructure_exports.schema.json
│       ├── platform_releases.schema.json
│       ├── workload_releases.schema.json
│       ├── policy_bindings.schema.json
│       ├── secret_references.schema.json
│       └── promotion_receipt.schema.json
├── policy/
│   ├── signed_release.rego
│   ├── immutable_digest.rego
│   ├── approved_environment.rego
│   ├── destination_allowlist.rego
│   ├── secret_reference.rego
│   ├── rollout_safety.rego
│   └── tests/
│       ├── signed_release_test.rego
│       ├── immutable_digest_test.rego
│       ├── approved_environment_test.rego
│       ├── destination_allowlist_test.rego
│       ├── secret_reference_test.rego
│       └── rollout_safety_test.rego
├── tests/
│   ├── render/
│   │   ├── test_development_render.py
│   │   ├── test_staging_render.py
│   │   ├── test_production_render.py
│   │   └── test_restricted_render.py
│   ├── promotion/
│   │   ├── test_evidence_chain.py
│   │   └── test_schema_compatibility.py
│   ├── failure/
│   │   └── test_partial_sync.py
│   ├── rollback/
│   │   └── test_previous_digest.py
│   └── drift/
│       └── test_live_object_diff.py
├── tooling/
│   ├── cmd/
│   │   └── promotectl/
│   │       └── main.go
│   ├── internal/
│   │   ├── release/
│   │   │   └── verification.go
│   │   ├── rendering/
│   │   │   └── rendering.go
│   │   ├── policy/
│   │   │   └── policy.go
│   │   ├── promotion/
│   │   │   └── promotion.go
│   │   ├── rollback/
│   │   │   └── rollback.go
│   │   └── evidence/
│   │       └── receipt.go
│   ├── go.mod
│   ├── go.sum
│   └── BUILD.bazel
├── runbooks/
│   ├── argocd-unavailable.md
│   ├── failed-synchronization.md
│   ├── deployment-drift.md
│   ├── compromised-release.md
│   ├── emergency-rollback.md
│   └── cluster-rebootstrap.md
├── BUILD.bazel
├── MODULE.bazel
├── component.yaml
├── justfile
├── .editorconfig
├── .gitignore
├── LICENSE
├── README.md
└── SECURITY.md
```

All GitOps paths above are explicitly expanded to individual files. `release.yaml` contains an OCI/package digest and verification policy reference; it MUST NOT contain a mutable tag.

#### `gitops` implementation blueprint

**Responsibility.** Platform Operations owns environment Kubernetes desired state, Argo CD projects/ApplicationSets, release selection, rollout, rollback, and drift reconciliation. Security co-owns destination, source, signature, secret-reference, and admission policy. Component owners approve promotions for their release units. GitOps does not build, transform, or reinterpret a release and does not own business/job state.

**Interfaces and flow.** `promotectl` accepts a signed `ReleaseManifest`, immutable package/image/config digests, evidence references, target environment, and current desired-state revision. It verifies signature, provenance, SBOM, qualification, revocation, schema/migration compatibility, infrastructure capability exports, and approval policy; renders deterministically; then opens or validates a narrow desired-state change. After merge, Argo CD/ApplicationSet reconciles only allowed repositories, destinations, namespaces, and kinds. Observed health produces a signed promotion receipt linked to the Git commit and subject digests.

**Consistency, failure, and recovery.** Git is desired-state authority; cluster objects are observed state; control-plane workload resources remain runtime state. Argo sync is idempotent. A stale base, missing artifact, signature/revocation failure, incompatible migration, unknown destination, partial sync, health timeout, or drift outside the declared set blocks promotion. Cancellation before merge has no live effect; after merge, rollback is a new protected commit selecting a previously qualified digest and compatible configuration. Manual cluster changes are reverted or captured through an emergency reconciliation PR with audit evidence.

**Security, signals, and qualification.** Argo Projects enforce source/destination/kind allowlists; repository credentials and cluster identities are references to short-lived external secrets; rendered secrets are prohibited. Signals include queue-to-merge and merge-to-sync latency, sync/health status, drift age, policy denials, signature/revocation failures, rollout error budget, controller saturation, and rollback time. Qualification renders every environment, tests policy and schema, injects controller/cluster/artifact failures, verifies previous-digest rollback, and rehearses cluster rebootstrap. Environment schemas are additive within v1; package and CRD compatibility obey expand/migrate/contract and conversion rules.

### A3.14 Cross-repository transaction, deployment, and recovery law

| Transition | Authoritative input | Atomic/consistent boundary | Idempotency and retry | Completion evidence |
|---|---|---|---|---|
| monorepo build | protected source revision plus hermetic graph | one immutable subject digest per release unit | build key and subject digest; retries cannot overwrite | provenance, SBOM, qualification/evidence refs |
| GitHub governance apply | reviewed `github-config` plan digest | provider mutation sequence guarded by observed-state preconditions | resource identity plus plan digest; re-plan after ambiguity | signed before/after governance receipt |
| bootstrap apply | reviewed root plan and independent approvals | one locked root-state transaction sequence | import/compare before resume; no blind key recreation | signed root-state and recovery evidence |
| infrastructure apply | reviewed root plan, backend serial, policy result | one locked environment/stack state root | provider operation identity plus refresh/import | signed `InfrastructureExport` and apply receipt |
| GitOps promotion | signed release manifest plus target base revision | protected Git commit | subject/target/base tuple; stale base revalidates | merge, Argo sync/health, promotion receipt |
| rollback | retained trusted manifest and compatible state | new governance/infrastructure/GitOps revision | rollback request ID and exact target digest | restored policy/resource/deployment evidence |

No workflow performs a cross-repository distributed transaction. Each boundary commits locally, emits immutable evidence, and lets the next authority validate that evidence and its own preconditions. Unknown outcomes are observed and reconciled; they are never converted into an assumed success or an unguarded duplicate mutation.

### A3.15 Estate qualification gates

- repository ownership table is machine-validated;
- cross-repository identities are least privilege;
- protected branch and release policies are continuously checked;
- release manifests verify before GitOps acceptance;
- promotion uses the same artifact digest built in authoritative CI;
- rollback can occur without rebuilding;
- break-glass and compromise drills pass;
- infrastructure and deployment drift are detected within policy targets;
- no live environment secret or mutable promotion state exists in the monorepo.

### A3.16 Capability-local qualification progression

#### Estate M0 — ownership and trust inventory

Document repositories, owners, protected refs, identities, secrets, artifacts, and recovery dependencies.

#### Estate M1 — immutable handoff

Implement release manifest generation, signature/provenance verification, and digest-only GitOps promotion.

#### Estate M2 — continuous policy and drift

Continuously validate repository settings, OIDC claims, permissions, drift, and expiration of exceptions.

#### Estate M3 — recovery qualification

Exercise source, signer, CI, registry, GitOps, and bootstrap compromise/recovery scenarios.

### A3.17 Definition of done

1. Every repository has an exclusive purpose and owner.
2. Every cross-repository transition uses an immutable, authenticated contract.
3. Builds, promotions, and deployments have separate least-privilege identities.
4. Production can roll back using retained trusted artifacts without rebuilding.
5. Break-glass and bootstrap recovery are independently documented and tested.
6. Environment desired state never leaks into the application monorepo.
7. Artifact lineage remains intact through repository migration or retirement.
8. Repo-local `mindclade/.github/` and the organization `.github` repository have disjoint, machine-checked ownership.
9. `github-config`, `bootstrap`, `infrastructure-live`, and `gitops` pass their contract, policy, failure, drift, and isolated recovery suites before production authority is enabled.
