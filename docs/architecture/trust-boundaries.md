# Repository and evidence trust boundaries

Status: Wave 0 source contract. This document describes authority; it is not connected-production
qualification.

| Authority | Owns | Must not own |
|---|---|---|
| `mindclade` | product contracts, source, build graph, immutable release inputs and evidence producers | organization settings, durable evidence storage/catalogs, cloud resources, live runtime state |
| organization `.github` | pinned reusable workflows and community-health material | rulesets, product builds, deployment state |
| `github-config` | GitHub organization, team, repository, ruleset, environment, Actions and OIDC desired state | workflow implementation or cloud/runtime state |
| `bootstrap` | root trust, federation roots, signing/audit anchors, state backend and recovery | routine infrastructure or application promotion |
| `infrastructure-live` | cloud projects, network, data services, registries, observability, GKE and typed exports | application source or Kubernetes release selection |
| `gitops` | environment Kubernetes desired state and digest-only promotion | compilation, cloud foundations or mutable image tags |

Permitted handoffs point forward: signed build evidence from the monorepo, bootstrap trust outputs to
governance/infrastructure, typed infrastructure capabilities to GitOps, and signed release manifests
to digest-only promotion. A downstream repository cannot write source authority back into an
upstream repository or rebuild the artifact it verifies.

The five operational repositories and `old/mindclade-internal-monorepo` are `reference_only` inputs
to the Wave 0 drift report. Their immutable HEAD revisions may be inspected; dirty working-tree
content is identified but excluded from baseline facts. No legacy code, history, lock, or generated
output is imported into the greenfield repository.

Connected mutation fails closed until the protected identity, environment, ruleset, and genuinely
independent approval path are available. Local source validation never implies GitHub Enterprise,
Buildkite signing, GCP, GKE, Argo CD, disaster-recovery, or production qualification.
