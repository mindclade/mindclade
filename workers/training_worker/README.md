# Training worker control-plane client

This bounded worker slice consumes deterministic `JobRequested` envelopes,
verifies exact event version, digest, scope, and correlation identity, then
loads the durable job and generation-pinned artifacts exclusively through the
private Python SDK. It does not connect to PostgreSQL, Pub/Sub, or GCS.

Artifact materialization is size-bounded, digest-verified by the SDK,
create-only on disk, idempotent for matching duplicate deliveries, and covered
by a single caller deadline. Scientific execution remains a separate worker
phase and receives only these verified local inputs.
