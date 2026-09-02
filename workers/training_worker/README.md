# Training worker control-plane client

This bounded worker slice consumes deterministic `JobRequested` envelopes,
verifies exact event version, digest, scope, and correlation identity, then
loads the durable job and generation-pinned artifacts exclusively through the
private Python SDK. It does not connect to PostgreSQL, Pub/Sub, or GCS, and it
never imports a generated protocol package.

Configuration is read only by the SDK. `client_options()` supplies the worker's
user agent and, outside the local loopback environment, a workload-identity
provider bound to the audience the SDK itself resolved; every `MINDCLADE_*`
variable is then read by `AsyncClient.from_env`, which owns their names,
defaults, and failure messages.

Artifact materialization is size-bounded by this worker's intake ceiling and
otherwise delegated: the SDK verifies each digest and atomically publishes a
create-only mode-0600 file that it never overwrites. A duplicate delivery whose
local bytes already carry the same digest is an idempotent no-op, and a
divergent local copy is rejected. Retries, per-call deadlines, idempotency, and
metadata belong to the SDK; the worker owns only the single budget spanning the
whole multi-call intake, and both that budget and the SDK's own
`DeadlineExceededError` surface as one `AssignmentDeadlineError`. Scientific
execution remains a separate worker phase and receives only these verified
local inputs.
