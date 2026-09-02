# Protocol Contracts

This directory contains Mindclade's authoritative versioned contract sources.
Under ADR-0015, the complete catalog is implemented now as an unratified v1
candidate; the blueprint waves remain design-sequencing provenance.

- Protobuf defines internal resources, commands, events, and gRPC services.
- JSON Schema defines durable manifests, evidence, release metadata, and
  human-authored configuration.
- `mindclade.api.v1` owns the unratified public-safe gRPC facade. The checked
  `openapi/raw` projection is generated from its descriptors, deterministic
  curation trims unreachable components without changing runtime semantics,
  and `openapi/published` is byte-identical to that validated candidate. This
  creates no supported public API or SDK release authority.
- `generated/{go,python,rust,typescript}` contains deterministic committed
  projections. Mindclade-owned facades under `internal/sdk` reuse those wire
  types and are the client-side boundary for services, workers, training,
  tools, and internal applications. Server adapters, persistence mappers, and
  contract tests are the narrow direct-import exceptions.

The descriptor and OpenAPI artifacts remain candidates until the training
vertical passes its evidence gate. Ratification then establishes the first v1
compatibility baseline; subsequent changes follow normal versioned
compatibility rules.
