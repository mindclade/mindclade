from __future__ import annotations

import copy
import unittest
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2, evidence_reference_pb2
from mindclade.common.v1 import command_context_pb2, pagination_pb2, resource_reference_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.job.v1 import lease_fencing_pb2
from mindclade.training.v1 import (
    checkpoint_pb2,
    training_commands_pb2,
    training_progress_pb2,
    training_run_pb2,
)
from mindclade_internal_sdk._invocation import AsyncInvoker, SyncInvoker
from mindclade_internal_sdk.calls import CallOptions
from mindclade_internal_sdk.config import ClientConfig, Environment
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.training import AsyncTraining, Training
from mindclade_internal_sdk.transport import (
    CANCEL_TRAINING_RUN,
    COMMIT_CHECKPOINT,
    COMMIT_TRAINING_PROGRESS,
    COMPLETE_TRAINING_RUN,
    GET_CHECKPOINT,
    GET_TRAINING_RUN,
    LIST_CHECKPOINTS,
    LIST_TRAINING_RUNS,
    PREPARE_CHECKPOINT,
    RESUME_TRAINING_ATTEMPT,
    START_TRAINING_ATTEMPT,
    WATCH_TRAINING_RUN,
    Metadata,
)

PARENT = "tenants/tenant-1/projects/project-1"
RUN = f"{PARENT}/trainingRuns/run-1"
CHECKPOINT = f"{RUN}/checkpoints/checkpoint-1"
UNARY_METHODS = (
    GET_TRAINING_RUN,
    LIST_TRAINING_RUNS,
    START_TRAINING_ATTEMPT,
    RESUME_TRAINING_ATTEMPT,
    COMMIT_TRAINING_PROGRESS,
    PREPARE_CHECKPOINT,
    COMMIT_CHECKPOINT,
    COMPLETE_TRAINING_RUN,
    CANCEL_TRAINING_RUN,
    GET_CHECKPOINT,
    LIST_CHECKPOINTS,
)


class _CommandCarrier(Protocol):
    context: command_context_pb2.CommandContext


class _RequestCarrier(Protocol):
    command: _CommandCarrier


def config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:1",
        insecure_for_testing=True,
        default_timeout=1,
    )


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def run(
    state: training_run_pb2.TrainingRunState = training_run_pb2.TRAINING_RUN_STATE_RUNNING,
) -> training_run_pb2.TrainingRun:
    return training_run_pb2.TrainingRun(name=RUN, uid="run-uid", state=state)


def progress() -> training_progress_pb2.TrainingProgress:
    return training_progress_pb2.TrainingProgress(training_run_name=RUN, progress_revision=1)


def point() -> checkpoint_pb2.Checkpoint:
    return checkpoint_pb2.Checkpoint(name=CHECKPOINT, training_run_name=RUN, snapshot_epoch=1)


def fence() -> lease_fencing_pb2.LeaseFence:
    return lease_fencing_pb2.LeaseFence(
        job_id="jobs/job-1",
        run_id="runs/run-1",
        attempt_id="attempts/attempt-1",
        lease_epoch=1,
        deadline=timestamp(datetime.now(UTC) + timedelta(minutes=5)),
        lease_token_digest="sha256:" + "a" * 64,
    )


def reference(name: str, resource_type: str) -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(name=name, resource_type=resource_type)


def artifact() -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + "b" * 64,
        media_type="application/vnd.mindclade.test+json",
    )


def response(request: Message) -> Message:
    if isinstance(request, training_service_pb2.GetTrainingRunRequest):
        return training_service_pb2.GetTrainingRunResponse(training_run=run())
    if isinstance(request, training_service_pb2.ListTrainingRunsRequest):
        return training_service_pb2.ListTrainingRunsResponse(
            training_runs=[run()], page=pagination_pb2.PageResponse(next_page_token="next")
        )
    if isinstance(request, training_service_pb2.StartTrainingAttemptRequest):
        return training_service_pb2.StartTrainingAttemptResponse(training_run=run())
    if isinstance(request, training_service_pb2.ResumeTrainingAttemptRequest):
        return training_service_pb2.ResumeTrainingAttemptResponse(training_run=run())
    if isinstance(request, training_service_pb2.CommitTrainingProgressRequest):
        return training_service_pb2.CommitTrainingProgressResponse(
            progress=progress(), training_run=run()
        )
    if isinstance(request, training_service_pb2.PrepareCheckpointRequest):
        return training_service_pb2.PrepareCheckpointResponse(checkpoint=point())
    if isinstance(request, training_service_pb2.CommitCheckpointRequest):
        return training_service_pb2.CommitCheckpointResponse(checkpoint=point(), training_run=run())
    if isinstance(request, training_service_pb2.CompleteTrainingRunRequest):
        return training_service_pb2.CompleteTrainingRunResponse(training_run=run())
    if isinstance(request, training_service_pb2.CancelTrainingRunRequest):
        return training_service_pb2.CancelTrainingRunResponse(training_run=run())
    if isinstance(request, training_service_pb2.GetCheckpointRequest):
        return training_service_pb2.GetCheckpointResponse(checkpoint=point())
    if isinstance(request, training_service_pb2.ListCheckpointsRequest):
        return training_service_pb2.ListCheckpointsResponse(checkpoints=[point()])
    raise AssertionError(type(request))


def commands() -> tuple[
    training_commands_pb2.StartTrainingAttemptCommand,
    training_commands_pb2.ResumeTrainingAttemptCommand,
    training_commands_pb2.CommitTrainingProgressCommand,
    training_commands_pb2.PrepareCheckpointCommand,
    training_commands_pb2.CommitCheckpointCommand,
    training_commands_pb2.CompleteTrainingRunCommand,
    training_commands_pb2.CancelTrainingRunCommand,
]:
    start = training_commands_pb2.StartTrainingAttemptCommand(
        training_run=reference(RUN, "training_run"),
        fence=fence(),
        deadline=timestamp(datetime.now(UTC) + timedelta(minutes=5)),
    )
    resume = training_commands_pb2.ResumeTrainingAttemptCommand(
        training_run=reference(RUN, "training_run"),
        checkpoint=reference(CHECKPOINT, "checkpoint"),
        fence=fence(),
        deadline=timestamp(datetime.now(UTC) + timedelta(minutes=5)),
    )
    commit_progress = training_commands_pb2.CommitTrainingProgressCommand(
        training_run_name=RUN, fence=fence(), progress=progress()
    )
    prepare = training_commands_pb2.PrepareCheckpointCommand(
        training_run_name=RUN,
        fence=fence(),
        snapshot_epoch=1,
        logical_state_descriptor=artifact(),
        committed_progress=progress(),
    )
    commit = training_commands_pb2.CommitCheckpointCommand(
        training_run_name=RUN,
        fence=fence(),
        snapshot_epoch=1,
        checkpoint_manifest=artifact(),
        logical_state_descriptor=artifact(),
        committed_progress=progress(),
        verification_evidence=evidence_reference_pb2.EvidenceRef(digest="sha256:" + "c" * 64),
        committed_at=timestamp(datetime.now(UTC)),
    )
    complete = training_commands_pb2.CompleteTrainingRunCommand(
        training_run_name=RUN,
        fence=fence(),
        classification=training_run_pb2.TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED,
        completed_at=timestamp(datetime.now(UTC)),
    )
    cancel = training_commands_pb2.CancelTrainingRunCommand(
        training_run_name=RUN, etag="etag-1", reason="operator request"
    )
    return start, resume, commit_progress, prepare, commit, complete, cancel


def exercise_sync(facade: Training) -> None:
    start, resume, commit_progress, prepare, commit, complete, cancel = commands()
    read = CallOptions()
    mutation = CallOptions(idempotency_key="training-idem", lease_token="opaque-lease")
    assert facade.get(RUN, options=read).name == RUN
    assert facade.list_runs().page.next_page_token == "next"
    assert facade.start_attempt(start, options=mutation).name == RUN
    assert facade.resume_attempt(resume, options=mutation).name == RUN
    assert facade.commit_progress(commit_progress, options=mutation)[0].progress_revision == 1
    assert facade.prepare_checkpoint(prepare, options=mutation).name == CHECKPOINT
    assert facade.commit_checkpoint(commit, options=mutation)[0].name == CHECKPOINT
    assert facade.complete(complete, options=mutation).name == RUN
    assert facade.cancel(cancel, options=CallOptions(idempotency_key="cancel")).name == RUN
    assert facade.get_checkpoint(CHECKPOINT).name == CHECKPOINT
    assert (
        facade.list_checkpoints(training_service_pb2.ListCheckpointsRequest(parent=RUN))
        .checkpoints[0]
        .name
        == CHECKPOINT
    )
    assert next(facade.watch(RUN, timeout=1)).sequence == 1


async def exercise_async(facade: AsyncTraining) -> None:
    start, resume, commit_progress, prepare, commit, complete, cancel = commands()
    mutation = CallOptions(idempotency_key="training-idem", lease_token="opaque-lease")
    assert (await facade.get(RUN)).name == RUN
    assert (await facade.list_runs()).page.next_page_token == "next"
    assert (await facade.start_attempt(start, options=mutation)).name == RUN
    assert (await facade.resume_attempt(resume, options=mutation)).name == RUN
    assert (await facade.commit_progress(commit_progress, options=mutation))[
        0
    ].progress_revision == 1
    assert (await facade.prepare_checkpoint(prepare, options=mutation)).name == CHECKPOINT
    assert (await facade.commit_checkpoint(commit, options=mutation))[0].name == CHECKPOINT
    assert (await facade.complete(complete, options=mutation)).name == RUN
    assert (await facade.cancel(cancel, options=CallOptions(idempotency_key="cancel"))).name == RUN
    assert (await facade.get_checkpoint(CHECKPOINT)).name == CHECKPOINT
    assert (
        await facade.list_checkpoints(training_service_pb2.ListCheckpointsRequest(parent=RUN))
    ).checkpoints[0].name == CHECKPOINT
    updates = facade.watch(RUN, timeout=1)
    assert (await anext(updates)).sequence == 1


class TrainingLifecycleTest(unittest.TestCase):
    def test_authoritative_training_resource_leaf_law(self) -> None:
        transport = FakeSyncTransport()
        seen: list[training_service_pb2.GetTrainingRunRequest] = []

        def get_run(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            typed = cast(training_service_pb2.GetTrainingRunRequest, request)
            seen.append(copy.deepcopy(typed))
            return training_service_pb2.GetTrainingRunResponse(
                training_run=training_run_pb2.TrainingRun(
                    name=typed.name,
                    uid="run-uid",
                    state=training_run_pb2.TRAINING_RUN_STATE_RUNNING,
                )
            )

        transport.unary_handlers[GET_TRAINING_RUN] = get_run
        facade = Training(SyncInvoker(config(), transport))
        for leaf in ("01", "A", "a.b_c~d-1"):
            facade.get(leaf)
            self.assertEqual(seen[-1].name, f"{PARENT}/trainingRuns/{leaf}")
        for leaf in (".leading", "~leading", "\x00control", "a" * 129):
            with self.assertRaises(ValueError):
                facade.get(leaf)

    def test_sync_facade_covers_every_lifecycle_route(self) -> None:
        transport = FakeSyncTransport()
        captured: list[tuple[Message, Metadata]] = []

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            captured.append((copy.deepcopy(request), metadata))
            return response(request)

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del timeout
            captured.append((copy.deepcopy(request), metadata))
            return [
                training_service_pb2.WatchTrainingRunResponse(
                    training_run=run(training_run_pb2.TRAINING_RUN_STATE_COMPLETED),
                    progress=progress(),
                    sequence=1,
                )
            ]

        for method in UNARY_METHODS:
            transport.unary_handlers[method] = unary
        transport.stream_handlers[WATCH_TRAINING_RUN] = stream
        exercise_sync(Training(SyncInvoker(config(), transport)))
        self.assertEqual(
            [call.method for call in transport.calls], [*UNARY_METHODS, WATCH_TRAINING_RUN]
        )
        for request, metadata in captured[2:8]:
            context = cast(_RequestCarrier, request).command.context
            self.assertTrue(context.canonical_request_digest.startswith("sha256:"))
            self.assertEqual(context.principal_id, "principal-1")
            self.assertIn(("x-mindclade-lease-token", "opaque-lease"), metadata)


class AsyncTrainingLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_facade_covers_every_lifecycle_route(self) -> None:
        transport = FakeAsyncTransport()

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            return response(request)

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            yield training_service_pb2.WatchTrainingRunResponse(
                training_run=run(training_run_pb2.TRAINING_RUN_STATE_COMPLETED),
                progress=progress(),
                sequence=1,
            )

        for method in UNARY_METHODS:
            transport.unary_handlers[method] = unary
        transport.stream_handlers[WATCH_TRAINING_RUN] = stream
        await exercise_async(AsyncTraining(AsyncInvoker(config(), transport)))
        self.assertEqual(
            [call.method for call in transport.calls], [*UNARY_METHODS, WATCH_TRAINING_RUN]
        )


if __name__ == "__main__":
    unittest.main()
