"""Submit a training run through the private SDK and receive an Operation."""

from __future__ import annotations

from mindclade_internal_sdk import CallOptions, Client
from mindclade_internal_sdk.resources import Operation, artifact_reference, resource_reference


def submit_training_operation(
    client: Client,
    *,
    training_run_id: str,
    recipe_digest: str,
    recipe_size_bytes: int,
    dataset_release_name: str,
    model_release_name: str,
    idempotency_key: str,
    request_id: str | None = None,
) -> Operation:
    """Submit immutable training intent through generated transport values."""

    recipe = artifact_reference(
        digest=recipe_digest,
        media_type="application/vnd.mindclade.training-recipe+json",
        size_bytes=recipe_size_bytes,
        artifact_kind="training_recipe",
        schema_id="https://mindclade.dev/schemas/training-recipe/v1",
        schema_version="mindclade.training-recipe/v1",
    )
    dataset = resource_reference(
        name=dataset_release_name,
        resource_type="dataset_release",
    )
    model = resource_reference(
        name=model_release_name,
        resource_type="model_release",
    )
    return client.training.submit(
        training_run_id,
        training_recipe=recipe,
        dataset_release=dataset,
        model_release=model,
        options=CallOptions(
            idempotency_key=idempotency_key,
            request_id=request_id,
        ),
    )
