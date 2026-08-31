# Protocol Contracts

This directory contains Mindclade's authoritative versioned contract sources.
Under ADR-0015, the complete catalog is implemented now as a one-time clean-v1
baseline; the blueprint waves remain design-sequencing provenance.

- Protobuf defines internal resources, commands, events, and gRPC services.
- JSON Schema defines durable manifests, evidence, release metadata, and
  human-authored configuration.
- The curated public service facade derives OpenAPI without exposing internal
  Protobuf, persistence, queue, or provider layouts.
- `generated/{go,python,rust,typescript}` contains deterministic committed
  projections. Product code, including `libs/python`, consumes these types and
  must not hand-define competing wire contracts.

Compatibility baselines are generated from the v1 sources and change only
through the pinned local generator. After this initial baseline, field numbers,
enum values, stable meaning, and supported public behavior follow the normal
versioned compatibility process.
