# Control plane durability kernel

This Wave 1 component owns tenant-scoped operation acceptance, jobs, runs,
fenced attempts, immutable artifact metadata, and their transactional evidence.
It is deliberately transport- and driver-neutral: PostgreSQL migrations define
the durable authority while Go ports keep queues, object storage, and catalogs
outside database transactions.

Workers receive queue envelopes and lease capabilities only. They never receive
a control-plane database interface. A completion must match both attempt ID and
lease epoch; stale completions are retained as audit history and cannot advance
the run.

Run the focused source checks with:

```text
go test ./services/control_plane/...
```
