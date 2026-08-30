# Architecture

Mindclade is a domain-first polyglot monorepo. It is the atomic source and build
boundary for biological semantics, contracts, models, execution software,
supported clients, and immutable release inputs. Live state and privileged
control planes remain in separately protected repositories.

## Authorities

| Authority | Owner |
|---|---|
| Intended code and contracts | Protected revision in this repository |
| Durable workflow and business state | Transactional control-plane database |
| Immutable scientific and execution evidence | Content-addressed storage and catalog metadata |
| Live environment desired state | Protected infrastructure and GitOps repositories |

The forward trust chain is:

```text
bootstrap trust
  -> GitHub and infrastructure control planes
  -> monorepo trusted build evidence
  -> immutable release manifest
  -> GitOps digest promotion
```

No downstream repository rebuilds product artifacts or writes source state back
into this repository.

## Wave 0 boundary

The current repository is a greenfield Wave 0 governance baseline. It contains
no implemented product or domain capability. Its active outcomes are the
repository drift report, governed path/owner/dependency metadata, deterministic
architecture rendering, foundational ADRs, and trusted-CI source definitions.

The normative sources live under `docs/architecture/blueprint/`. The generated
full blueprint is a review artifact and must reproduce exactly. The repository
path manifest is the file-level authority; target-only and deferred paths must
not be created early.

## Decision records

The foundational decisions are indexed by `docs/adr/index.yaml` and derive
their specification acceptance from Section 14 of the architecture blueprint.
Future decisions are ratified only immediately before the first implementation
that depends on them.
