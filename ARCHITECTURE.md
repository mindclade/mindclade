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

Protobuf owns resources, commands, events, and gRPC services; JSON Schema owns
durable documents. `mindclade.api.v1` and the curated OpenAPI document are an
unratified, public-safe candidate projection for a possible future HTTP API;
they do not establish a supported public SDK or release authority. Exact
descriptor, binding, and ProtoJSON mappings keep that candidate from drifting.
Generated Go, Python, Rust, and TypeScript bindings are authoritative internal
transport types. PostgreSQL-compatible normalized relations remain durable
business-state authority; immutable Protobuf bytes are limited to outbox,
inbox, audit, and dead-letter evidence boundaries. Buf and pinned native
plugins generate the internal Go, Python, Rust, and TypeScript
Protobuf/gRPC/Connect transport. Thin Mindclade-owned facades under
`internal/sdk` add client ergonomics while reusing generated wire types.
Client-side services, workers, training code, tools, and internal applications
consume those facades. Fern and Speakeasy are optional HTTP/JSON comparison
tools only; provider state never owns an internal transport, contract, or
release decision.

This ownership is retroactive across the complete service estate: every gRPC
service and RPC signature is declared in a versioned `.proto` file. Handwritten
Go/Python/Rust/TypeScript code may implement or wrap generated interfaces, but
it may not define a parallel network service contract.

This source activation grants no runtime, public-release, Kubernetes, cloud,
connected promotion, scientific, or production authority. Workers cannot
mutate control-plane state, filesystem paths are not durable identity, and
local signing evidence is not trusted connected signing.

## Decision records

The foundational decisions are indexed by `docs/adr/index.yaml`. ADR-0015 is
the accepted source-implementation authority for the clean-v1 contract reset;
connected and production decisions still require their protected ratification
immediately before use.
