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
ADR-0008 and FBE-0001, Wave 1 activates the durability kernel: shared
identifiers and envelopes, immutable artifact/evidence references, durable
operation/job/run/attempt state, idempotency, outbox/inbox, lease fencing,
deterministic configuration, release manifests, and local qualification
evidence. ADR-0015 additionally activates the complete contract program as a
one-time clean-v1 baseline. Original wave values remain design-sequencing
provenance; exact path status in the repository-path manifest governs presence.

The normative sources live under `docs/architecture/blueprint/`. The generated
full blueprint is a review artifact and must reproduce exactly. The blueprint's
architecture and safety law remains binding while its wave timing is guidance
under ADR-0015. The repository-path manifest is the file-level authority;
target-only and deferred paths must not be created early.

Protobuf owns internal resources, commands, events, and gRPC services; JSON
Schema owns durable documents; a curated public facade generates OpenAPI.
Generated Go, Python, Rust, and TypeScript bindings are authoritative consumers'
types. PostgreSQL-compatible normalized relations remain durable business-state
authority; immutable Protobuf bytes are limited to outbox, inbox, audit, and
dead-letter evidence boundaries. Public Go/Python/TypeScript SDK generation is
Stainless-primary with an oagen parity shadow and a provider-neutral boundary.

This source activation grants no runtime, public-release, Kubernetes, cloud,
connected promotion, scientific, or production authority. Workers cannot
mutate control-plane state, filesystem paths are not durable identity, and
local signing evidence is not trusted connected signing.

## Decision records

The foundational decisions are indexed by `docs/adr/index.yaml`. ADR-0015 is
the accepted source-implementation authority for the clean-v1 contract reset;
connected and production decisions still require their protected ratification
immediately before use.
