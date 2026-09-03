# Ingestion worker control-plane client

This private Rust worker path verifies exact-version `JobRequested` event bytes, resolves the durable job through the internal SDK, and materializes content-addressed inputs through the SDK's verified download-and-publish helper. It never imports generated service clients or accesses PostgreSQL, Pub/Sub, or GCS directly.

The binary accepts an immutable protobuf envelope file and a destination root. Secure environments use GCP workload identity and verified TLS; plaintext is limited by the SDK to explicit local-loopback mode.

Deadlines and retries belong to the SDK. Every worker RPC carries the delivery's request and trace identifiers and inherits the deadline configured through `Config::default_rpc_timeout`; the worker layers no timer of its own over the facade, and a deadline surfaces as the SDK's `DeadlineExceeded` classification rather than a worker-invented variant. Failures are classified only by the SDK error hierarchy, reachable through `AssignmentError::sdk_kind`, `AssignmentError::stable_code`, and `AssignmentError::is_retryable`; the worker never inspects a transport status.

What remains worker-owned is local intake policy: an artifact byte cap, generation-pinned artifact references taken from the durable job, the event-to-job configuration digest match, and the idempotent reuse of an already-materialized file whose digest matches. Publication itself — mode-0600 staging, verification, and same-directory hard-link commit that never overwrites — is the SDK's.

Configuration reads the canonical SDK environment variable names: `MINDCLADE_ENVIRONMENT`, `MINDCLADE_TENANT_ID`, `MINDCLADE_PROJECT_ID`, `MINDCLADE_PRINCIPAL_ID`, `MINDCLADE_ENDPOINT`, and `MINDCLADE_AUDIENCE`.
