from __future__ import annotations

import hashlib
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from google.protobuf.message import Message
from mindclade_internal_sdk import (
    AuthorizationError,
    CallOptions,
    Client,
    FieldViolation,
    NotFoundError,
    Page,
    PageBudget,
    PaginationLimitError,
    PaginationLimits,
    ProtocolError,
    ValidationError,
)
from mindclade_internal_sdk.resources import ArtifactRef, Operation, artifact_reference

from examples.sdk.download_artifact import download_verified_artifact
from examples.sdk.handle_errors import failure_report, operation_if_present
from examples.sdk.list_operations import collect_operations, first_operation_page
from examples.sdk.submit_operation import submit_training_operation


class _FakeTraining:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def submit(self, training_run_id: str, **arguments: object) -> Operation:
        self.arguments = {"training_run_id": training_run_id, **arguments}
        return Operation(operation_id="operations/training-1")


class _FakeOperations:
    """List namespace returning the SDK's own auto-paginating page type."""

    def __init__(
        self,
        pages: Sequence[Sequence[Operation]] = (),
        *,
        get_error: Exception | None = None,
    ) -> None:
        self._pages = tuple(tuple(page) for page in pages)
        self._get_error = get_error
        self.limits: list[PaginationLimits | None] = []
        self.options: list[CallOptions | None] = []
        self.names: list[str] = []

    def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> Operation:
        del if_none_match
        self.names.append(name)
        self.options.append(options)
        if self._get_error is not None:
            raise self._get_error
        return Operation(operation_id=name)

    def list(
        self,
        request: object | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[Operation]:
        del request
        self.options.append(options)
        self.limits.append(limits)
        return self._page(0, limits)

    def _page(self, index: int, limits: PaginationLimits | None) -> Page[Operation]:
        token = "" if index + 1 == len(self._pages) else f"operations-page-{index + 1}"
        return Page(
            items=self._pages[index],
            next_page_token=token,
            # The SDK carries the generated ListOperationsResponse here. A
            # consumer cannot build one without importing a generated package,
            # which the boundary forbids, and these examples read items and
            # cursors only, so the fake declines to fabricate a wire model.
            response=cast(Message, None),
            fetch=lambda following: self._page(int(following.rsplit("-", 1)[1]), limits),
            budget=PageBudget(limits=limits or PaginationLimits()),
            seen=frozenset({token}) if token else frozenset(),
        )


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
        self.resolutions: list[tuple[str, str | None, CallOptions | None]] = []
        self.downloads: list[tuple[ArtifactRef, Path, CallOptions | None]] = []

    def resolve_alias(
        self,
        alias: str,
        *,
        parent: str | None = None,
        options: CallOptions | None = None,
    ) -> ArtifactRef:
        self.aliases.append(alias)
        self.resolutions.append((alias, parent, options))
        return self.artifact

    def download_file(
        self,
        artifact: ArtifactRef,
        destination: Path,
        *,
        options: CallOptions | None = None,
    ) -> int:
        target = Path(destination)
        self.downloads.append((artifact, target, options))
        if target.exists():
            raise FileExistsError(target)
        if "sha256:" + hashlib.sha256(self.content).hexdigest() != artifact.digest:
            raise ProtocolError("fake SDK rejected corrupt artifact content")
        target.write_bytes(self.content)
        return len(self.content)


class _FakeClient:
    def __init__(
        self,
        content: bytes = b"",
        *,
        operation_pages: Sequence[Sequence[Operation]] = (),
    ) -> None:
        self.training = _FakeTraining()
        self.artifacts = _FakeArtifacts(content)
        self.operations = _FakeOperations(operation_pages)


def _operations(*identifiers: str) -> tuple[Operation, ...]:
    return tuple(Operation(operation_id=identifier) for identifier in identifiers)


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
            options = CallOptions(request_id="artifact-download-01")
            artifact = download_verified_artifact(
                cast(Client, fake),
                alias="latest",
                destination=destination,
                parent="tenants/t/projects/p",
                options=options,
            )
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(artifact, fake.artifacts.artifact)
            self.assertEqual(fake.artifacts.aliases, ["latest"])
            self.assertEqual(
                fake.artifacts.resolutions,
                [("latest", "tenants/t/projects/p", options)],
            )
            self.assertEqual(
                fake.artifacts.downloads,
                [(fake.artifacts.artifact, destination, options)],
            )

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

    def test_download_never_overwrites_an_existing_destination(self) -> None:
        fake = _FakeClient(b"replacement")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.bin"
            destination.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                download_verified_artifact(
                    cast(Client, fake), alias="latest", destination=destination
                )
            self.assertEqual(destination.read_bytes(), b"existing")


class ListOperationsExampleTest(unittest.TestCase):
    def test_collection_crosses_page_boundaries_under_a_declared_budget(self) -> None:
        fake = _FakeClient(
            operation_pages=(
                _operations("operations/op-1", "operations/op-2"),
                _operations("operations/op-3", "operations/op-4"),
                _operations("operations/op-5"),
            )
        )
        options = CallOptions(request_id="operation-list-01")
        operations = collect_operations(
            cast(Client, fake), max_items=10, page_size=2, options=options
        )
        self.assertEqual(
            [operation.operation_id for operation in operations],
            [
                "operations/op-1",
                "operations/op-2",
                "operations/op-3",
                "operations/op-4",
                "operations/op-5",
            ],
        )
        self.assertEqual(fake.operations.options, [options])
        self.assertEqual(fake.operations.limits, [PaginationLimits(max_items=10, page_size=2)])

    def test_a_spent_item_budget_fails_instead_of_truncating_silently(self) -> None:
        fake = _FakeClient(
            operation_pages=(
                _operations("operations/op-1", "operations/op-2"),
                _operations("operations/op-3"),
            )
        )
        with self.assertRaises(PaginationLimitError):
            collect_operations(cast(Client, fake), max_items=2, page_size=2)

    def test_page_level_access_keeps_the_opaque_cursor(self) -> None:
        fake = _FakeClient(
            operation_pages=(
                _operations("operations/op-1"),
                _operations("operations/op-2"),
            )
        )
        page = first_operation_page(cast(Client, fake), page_size=1)
        self.assertEqual([operation.operation_id for operation in page.items], ["operations/op-1"])
        self.assertTrue(page.has_next_page)
        self.assertEqual(page.next_page_token, "operations-page-1")
        following = page.next_page()
        self.assertEqual(
            [operation.operation_id for operation in following.items], ["operations/op-2"]
        )
        self.assertFalse(following.has_next_page)


class HandleErrorsExampleTest(unittest.TestCase):
    def test_a_present_operation_is_returned_unchanged(self) -> None:
        fake = _FakeClient()
        options = CallOptions(request_id="operation-get-01")
        operation = operation_if_present(cast(Client, fake), "operations/op-1", options=options)
        self.assertIsNotNone(operation)
        assert operation is not None
        self.assertEqual(operation.operation_id, "operations/op-1")
        self.assertEqual(fake.operations.names, ["operations/op-1"])
        self.assertEqual(fake.operations.options, [options])

    def test_a_missing_operation_is_absence_and_not_a_failure(self) -> None:
        fake = _FakeClient()
        fake.operations = _FakeOperations(get_error=NotFoundError("operation does not exist"))
        self.assertIsNone(operation_if_present(cast(Client, fake), "operations/op-1"))

    def test_every_other_sdk_error_keeps_its_class(self) -> None:
        fake = _FakeClient()
        fake.operations = _FakeOperations(
            get_error=AuthorizationError("caller may not read this operation")
        )
        with self.assertRaises(AuthorizationError):
            operation_if_present(cast(Client, fake), "operations/op-1")

    def test_failure_report_carries_only_the_sdk_errors_own_fields(self) -> None:
        error = ValidationError(
            "training submission was rejected",
            code="validation",
            request_id="request-9",
            trace_id="trace-9",
            retryable=False,
            retry_after=1.5,
            field_violations=(FieldViolation(field="training_recipe.digest", description="bad"),),
        )
        report = failure_report(error)
        self.assertEqual(report.code, "validation")
        self.assertFalse(report.retryable)
        self.assertEqual(report.retry_after_seconds, 1.5)
        self.assertEqual(report.request_id, "request-9")
        self.assertEqual(report.trace_id, "trace-9")
        self.assertEqual(report.invalid_fields, ("training_recipe.digest",))


if __name__ == "__main__":
    unittest.main()
