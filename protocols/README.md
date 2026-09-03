# Protocol Contracts

This directory contains Mindclade's authoritative versioned contract sources.
Under ADR-0015, the complete catalog is implemented now as an unratified v1
candidate; the blueprint waves remain design-sequencing provenance.

- Protobuf defines internal resources, commands, events, and gRPC services.
  Every registered service and RPC, including the existing estate, must trace
  to a versioned `.proto` declaration; handwritten parallel service
  descriptors, registrars, and transport interfaces fail the contract gate.
- JSON Schema defines durable manifests, evidence, release metadata, and
  human-authored configuration.
- `mindclade.api.v1` owns the unratified public-safe gRPC facade. The checked
  `openapi/raw` projection is generated from its descriptors, deterministic
  curation trims unreachable components without changing runtime semantics,
  and `openapi/published` is byte-identical to that validated candidate. This
  creates no supported public API or SDK release authority.
- `generated/{go,python,rust,typescript}` contains deterministic committed
  projections. Mindclade-owned facades under `sdks` reuse those wire
  types and are the client-side boundary for services, workers, training,
  tools, and internal applications. Server adapters, persistence mappers, and
  contract tests are the narrow direct-import exceptions.

`just generate-contracts` is the sole write path for generated contract
artifacts. It builds and validates the descriptor, all four transport estates,
OpenAPI stages, event-registry projections, SDK coverage, gRPC implementation
coverage, and the final file manifest before committing any output. Every
projection carries the same descriptor digest, the manifest is published last,
and a failed commit is rolled back. `just check-contract-drift` runs the same
complete transaction in read-only check mode.

The descriptor and OpenAPI artifacts remain candidates until the training
vertical passes its evidence gate. Ratification then establishes the first v1
compatibility baseline; subsequent changes follow normal versioned
compatibility rules.
