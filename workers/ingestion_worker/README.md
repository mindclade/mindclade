# Ingestion worker control-plane client

This private Rust worker path verifies exact-version `JobRequested` event bytes, resolves the durable job through the internal SDK, and downloads content-addressed inputs through the SDK's checked artifact stream. It never imports generated service clients or accesses PostgreSQL, Pub/Sub, or GCS directly.

The binary accepts an immutable protobuf envelope file and a destination root. Secure environments use GCP workload identity and verified TLS; plaintext is limited by the SDK to explicit local-loopback mode. Materialization is bounded by total and per-RPC deadlines, byte caps, digest checks, generation-pinned artifact references, and create-only local writes.
