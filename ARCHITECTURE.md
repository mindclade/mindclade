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

## Current activation boundary

Wave 0 governance remains an independently testable evidence closure. Under
ADR-0008 and FBE-0001, Wave 1 activates only the minimal contract and durability
kernel: shared identifiers and envelopes, immutable artifact/evidence
references, durable operation/job/run/attempt state, idempotency, outbox/inbox,
lease fencing, deterministic configuration, release manifests, and local
qualification evidence.

The normative sources live under `docs/architecture/blueprint/`. The generated
full blueprint is a review artifact and must reproduce exactly. The repository
path manifest is the file-level authority; target-only and deferred paths must
not be created early.

Wave 1 has no public API or SDK compatibility promise and no dataset, model,
training, inference, Kubernetes, cloud, connected promotion, or production
authority. Workers cannot mutate control-plane state, filesystem paths are not
durable identity, and local signing evidence is not trusted connected signing.

## Decision records

The foundational decisions are indexed by `docs/adr/index.yaml` and derive
their specification acceptance from Section 14 of the architecture blueprint.
Future decisions are ratified only immediately before the first implementation
that depends on them.
