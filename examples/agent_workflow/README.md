# Bounded internal analysis-agent client

This application uses only `mindclade_internal_sdk`. It admits an already
registered agent definition after checking an exact definition digest, a closed
tool allowlist, numeric budgets, an unexpired approval binding, and a fixed
`start`/`status`/`cancel` action set. It does not implement a model loop, discover
tools, access PostgreSQL/Pub/Sub/GCS, or perform network, wet-lab, synthesis, or
clinical actions.

`agent.yaml` and `workflow.yaml` are closed application configuration documents
encoded as JSON-compatible YAML. Their example identities are placeholders;
replace them with reviewed internal resources from the same tenant/project as
the SDK client. Non-local use obtains a short-lived audience-bound Google ID
token through Application Default Credentials. No credentials are stored.

```bash
python examples/agent_workflow/simulate.py start \
  --run-id analysis-001 \
  --idempotency-key analysis-001-start
```

Source readiness does not grant connected or production authority. The server
remains authoritative for authorization, tenant binding, approval consumption,
budgets, fencing, durable state, and immutable event delivery.
