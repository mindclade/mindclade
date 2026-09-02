# Mindclade internal Python SDK

This private, unpublished package is the ergonomic Python façade over the
authoritative generated `mindclade.*` Protobuf and gRPC bindings. It is for
Mindclade services, workers, training code, tools, and internal applications.
It is not the future public API and is not published to a package registry.

The dependency direction is strict:

```text
protocols/proto -> protocols/generated/python -> internal/sdk/python -> consumers
```

The SDK owns secure channel setup, workload-identity token injection, bounded
safe-call retries, deadlines, correlation metadata, typed errors, operation
helpers, artifact alias resolution, and training conveniences. Generated
messages remain the only request, response, resource, and event models.
PostgreSQL durable state and Pub/Sub event delivery stay behind the control
plane and are never accessed directly by this SDK.

## Synchronous use

```python
from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef
from mindclade.common.v1.resource_reference_pb2 import ResourceRef
from mindclade_internal_sdk import (
    Client,
    ClientConfig,
    Environment,
    GoogleWorkloadIdentityProvider,
)


config = ClientConfig(
    environment=Environment.DEVELOPMENT,
    tenant_id="tenant-01",
    project_id="project-01",
    principal_id="training-orchestrator",
    token_provider=GoogleWorkloadIdentityProvider(
        "https://control-plane.development.mindclade.internal"
    ),
)

with Client(config) as client:
    operation = client.training.submit(
        "pretrain-v4",
        training_recipe=ArtifactRef(
            digest="sha256:" + "1" * 64,
            media_type="application/vnd.mindclade.training-recipe.v1+json",
        ),
        dataset_release=ResourceRef(name="datasetReleases/pdb-2026-08"),
        model_release=ResourceRef(name="modelReleases/nova-1"),
    )
    terminal = client.operations.wait(operation.operation_id)
```

`AsyncClient` has the same service layout and requires a provider with
`async get_token(*, timeout: float)`. Use
`AsyncGoogleWorkloadIdentityProvider` for ADC-backed asynchronous clients.
Custom synchronous providers implement `get_token(*, timeout: float)` and must
honor that remaining budget for every external exchange. Never wrap the
synchronous client in an event loop.

All declared internal services remain reachable through `client.generated`
using their generated request and response messages and fully qualified gRPC
method paths. This advanced surface applies the same authentication, deadline,
correlation, observation, and retry policy as the ergonomic helpers. A generic
mutation is retried only when its fully qualified method is allowlisted and its
generated `CommandContext` contains the same explicit idempotency key, scope,
and canonical request digest. A boolean flag cannot promote arbitrary raw RPCs.

## Safety and retry behavior

- TLS and a short-lived token provider are mandatory by default.
- Credential acquisition is bounded by the end-to-end call deadline. The
  built-in Google providers apply one deadline across ADC metadata, STS, and
  service-account exchanges, validate token audience and expiry, and singleflight
  refreshes.
- Cleartext transport exists only for the local loopback environment and
  rejects credentials.
- Automatic retries are bounded and occur only for reads or mutations carrying
  an idempotency key and canonical request digest.
- Errors preserve gRPC status, request ID, and retryability without copying
  provider details or request/response payloads.
- Observers receive method, attempt, elapsed time, status, and request ID only.
  Tokens and payloads are never logged.
- `FakeSyncTransport` and `FakeAsyncTransport` support hermetic consumer tests.

Run focused tests with:

```bash
PYTHONPATH=internal/sdk/python:protocols/generated/python \
  python -m unittest discover -s internal/sdk/python/tests -v
```
