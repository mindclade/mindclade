from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import BinaryIO, cast

from mindclade_internal_sdk import CallOptions, Client, ProtocolError
from mindclade_internal_sdk.resources import ArtifactRef, Operation, artifact_reference

from examples.sdk.download_artifact import download_verified_artifact
from examples.sdk.submit_operation import submit_training_operation


class _FakeTraining:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def submit(self, training_run_id: str, **arguments: object) -> Operation:
        self.arguments = {"training_run_id": training_run_id, **arguments}
        return Operation(operation_id="operations/training-1")


class _FakeArtifacts:
    def __init__(self, content: bytes, *, advertised_content: bytes | None = None) -> None:
        self.content = content
        identity = advertised_content if advertised_content is not None else content
        self.artifact = artifact_reference(
            digest="sha256:" + hashlib.sha256(identity).hexdigest(),
            media_type="application/octet-stream",
            size_bytes=len(identity),
        )
        self.aliases: list[str] = []

    def resolve_alias(
        self,
        alias: str,
        *,
        parent: str | None = None,
        options: CallOptions | None = None,
    ) -> ArtifactRef:
        del parent, options
        self.aliases.append(alias)
        return self.artifact

    def download(
        self,
        artifact: ArtifactRef,
        destination: BinaryIO,
        *,
        options: CallOptions | None = None,
    ) -> int:
        del artifact, options
        return destination.write(self.content)


class _FakeClient:
    def __init__(self, content: bytes = b"") -> None:
        self.training = _FakeTraining()
        self.artifacts = _FakeArtifacts(content)


class SdkExamplesTest(unittest.TestCase):
    def test_training_submission_uses_sdk_factories_and_idempotency(self) -> None:
        fake = _FakeClient()
        operation = submit_training_operation(
            cast(Client, fake),
            training_run_id="run-1",
            recipe_digest="sha256:" + "a" * 64,
            recipe_size_bytes=123,
            dataset_release_name="tenants/t/projects/p/datasetReleases/dataset-1",
            model_release_name="tenants/t/projects/p/modelReleases/model-1",
            idempotency_key="training-run-1",
            request_id="request-1",
        )
        self.assertEqual(operation.operation_id, "operations/training-1")
        self.assertEqual(fake.training.arguments["training_run_id"], "run-1")
        options = fake.training.arguments["options"]
        self.assertIsInstance(options, CallOptions)
        assert isinstance(options, CallOptions)
        self.assertEqual(options.idempotency_key, "training-run-1")
        recipe = cast(ArtifactRef, fake.training.arguments["training_recipe"])
        self.assertEqual(recipe.digest, "sha256:" + "a" * 64)

    def test_download_is_digest_verified_and_atomically_published(self) -> None:
        content = b"verified artifact\n"
        fake = _FakeClient(content)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.bin"
            artifact = download_verified_artifact(
                cast(Client, fake), alias="latest", destination=destination
            )
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(artifact, fake.artifacts.artifact)
            self.assertEqual(fake.artifacts.aliases, ["latest"])
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_download_never_publishes_corrupt_or_partial_content(self) -> None:
        fake = _FakeClient()
        fake.artifacts = _FakeArtifacts(b"corrupt", advertised_content=b"expected")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.bin"
            with self.assertRaises(ProtocolError):
                download_verified_artifact(
                    cast(Client, fake), alias="latest", destination=destination
                )
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
