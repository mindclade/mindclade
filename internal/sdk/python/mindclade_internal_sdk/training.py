"""Ergonomic training calls built exclusively from generated contract types."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import cast

import grpc
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.job.v1 import operation_pb2
from mindclade.training.v1 import training_commands_pb2, training_run_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import (
    artifact_ref,
    required_response_message,
    required_text,
    resource_id,
    resource_ref,
)
from .calls import CallOptions, PreparedCall, prepare_call
from .config import ClientConfig
from .errors import (
    CancelledError,
    DeadlineExceededError,
    MindcladeError,
    OperationTimeoutError,
    ProtocolError,
    UnavailableError,
)
from .transport import CREATE_TRAINING_RUN, GET_TRAINING_RUN, WATCH_TRAINING_RUN

_TERMINAL_TRAINING_STATES = frozenset(
    {
        training_run_pb2.TRAINING_RUN_STATE_COMPLETED,
        training_run_pb2.TRAINING_RUN_STATE_FAILED,
        training_run_pb2.TRAINING_RUN_STATE_CANCELLED,
    }
)
_CANCELLATION_POLL_SECONDS = 0.25


def _watch_delay(invoker: SyncInvoker | AsyncInvoker, failures: int, remaining: float) -> float:
    exponent = min(max(0, failures - 1), 30)
    cap = min(
        invoker.config.retry.max_delay,
        invoker.config.retry.base_delay * (2**exponent),
        max(0.0, remaining),
    )
    return random.uniform(0.0, cap) if cap > 0 else 0.0


def _labels(values: Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (values or {}).items():
        normalized_key = required_text("label key", key, maximum=128)
        normalized_value = required_text("label value", value, maximum=256)
        result[normalized_key] = normalized_value
    return result


def _validate_create(command: training_commands_pb2.CreateTrainingRunCommand) -> None:
    resource_id("training_run_id", command.training_run_id)
    resource_ref("project", command.project)
    artifact_ref("training_recipe", command.training_recipe)
    resource_ref("dataset_release", command.dataset_release)
    resource_ref("model_release", command.model_release)
    if command.HasField("executable_plan"):
        artifact_ref("executable_plan", command.executable_plan)
    if command.HasField("hardware_topology"):
        artifact_ref("hardware_topology", command.hardware_topology)
    if command.HasField("use_policy"):
        resource_ref("use_policy", command.use_policy)


def _project_ref(config: ClientConfig) -> resource_reference_pb2.ResourceRef:
    tenant_id = config.tenant_id
    project_id = config.project_id
    parent = config.project_parent
    return resource_reference_pb2.ResourceRef(
        resource_type="project",
        resource_id=project_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=parent,
    )


class Training:
    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def submit(
        self,
        training_run_id: str,
        *,
        training_recipe: artifact_reference_pb2.ArtifactRef,
        dataset_release: resource_reference_pb2.ResourceRef,
        model_release: resource_reference_pb2.ResourceRef,
        executable_plan: artifact_reference_pb2.ArtifactRef | None = None,
        hardware_topology: artifact_reference_pb2.ArtifactRef | None = None,
        use_policy: resource_reference_pb2.ResourceRef | None = None,
        labels: Mapping[str, str] | None = None,
        policy_classification: str = "",
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        command = training_commands_pb2.CreateTrainingRunCommand(
            project=_project_ref(self._invoker.config),
            training_run_id=resource_id("training_run_id", training_run_id),
            training_recipe=training_recipe,
            dataset_release=dataset_release,
            model_release=model_release,
            labels=_labels(labels),
            policy_classification=policy_classification,
        )
        if executable_plan is not None:
            command.executable_plan.CopyFrom(executable_plan)
        if hardware_topology is not None:
            command.hardware_topology.CopyFrom(hardware_topology)
        if use_policy is not None:
            command.use_policy.CopyFrom(use_policy)
        return self.submit_command(command, options=options)

    def submit_command(
        self,
        command: training_commands_pb2.CreateTrainingRunCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = training_commands_pb2.CreateTrainingRunCommand()
        materialized.CopyFrom(command)
        materialized.ClearField("context")
        _validate_create(materialized)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        materialized.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(materialized),
            )
        )
        response = cast(
            training_service_pb2.CreateTrainingRunResponse,
            self._invoker.unary(
                CREATE_TRAINING_RUN,
                training_service_pb2.CreateTrainingRunRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
        )
        operation = required_response_message(
            response,
            "operation",
            operation_pb2.Operation,
            label="training submission",
        )
        required_text("operation id", operation.operation_id)
        return operation

    def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> training_run_pb2.TrainingRun:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.GetTrainingRunResponse,
            self._invoker.unary(
                GET_TRAINING_RUN,
                training_service_pb2.GetTrainingRunRequest(
                    name=required_text("training run name", name),
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        training_run = required_response_message(
            response,
            "training_run",
            training_run_pb2.TrainingRun,
            label="training get",
        )
        required_text("training run name", training_run.name)
        return training_run

    def watch(
        self,
        name: str,
        *,
        after_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: threading.Event | None = None,
        options: CallOptions | None = None,
    ) -> Iterator[training_service_pb2.WatchTrainingRunResponse]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("training watch was cancelled")
        base_call = prepare_call(
            options or CallOptions(timeout=timeout),
            default_timeout=timeout,
            require_idempotency=False,
        )
        run_name = required_text("training run name", name)
        deadline = time.monotonic() + base_call.timeout
        sequence = after_sequence
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("training watch was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationTimeoutError("training watch exceeded its total deadline")
            stream_timeout = (
                min(remaining, _CANCELLATION_POLL_SECONDS)
                if cancellation is not None
                else remaining
            )
            call = PreparedCall(
                timeout=stream_timeout,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = training_service_pb2.WatchTrainingRunRequest(
                name=run_name,
                after_sequence=sequence,
            )
            try:
                for raw_response in self._invoker.stream(
                    WATCH_TRAINING_RUN,
                    request,
                    call=call,
                ):
                    response = cast(training_service_pb2.WatchTrainingRunResponse, raw_response)
                    if response.sequence <= sequence:
                        raise ProtocolError(
                            "training watch sequence did not advance",
                            status=grpc.StatusCode.DATA_LOSS,
                        )
                    training_run = required_response_message(
                        response,
                        "training_run",
                        training_run_pb2.TrainingRun,
                        label="training watch",
                    )
                    if training_run.name != run_name:
                        raise ProtocolError(
                            "training watch returned a different run",
                            status=grpc.StatusCode.DATA_LOSS,
                        )
                    if training_run.state == training_run_pb2.TRAINING_RUN_STATE_UNSPECIFIED:
                        raise ProtocolError(
                            "training watch returned an unspecified state",
                            status=grpc.StatusCode.DATA_LOSS,
                        )
                    sequence = response.sequence
                    failures = 0
                    yield response
                    if training_run.state in _TERMINAL_TRAINING_STATES:
                        return
                stream_error: MindcladeError = UnavailableError(
                    "training watch closed before a terminal event",
                    retryable=True,
                )
            except DeadlineExceededError:
                if cancellation is not None and time.monotonic() < deadline:
                    continue
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = _watch_delay(self._invoker, failures, deadline - time.monotonic())
            if cancellation is not None:
                if cancellation.wait(delay):
                    raise CancelledError("training watch was cancelled")
            elif delay > 0:
                time.sleep(delay)


class AsyncTraining:
    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def submit(
        self,
        training_run_id: str,
        *,
        training_recipe: artifact_reference_pb2.ArtifactRef,
        dataset_release: resource_reference_pb2.ResourceRef,
        model_release: resource_reference_pb2.ResourceRef,
        executable_plan: artifact_reference_pb2.ArtifactRef | None = None,
        hardware_topology: artifact_reference_pb2.ArtifactRef | None = None,
        use_policy: resource_reference_pb2.ResourceRef | None = None,
        labels: Mapping[str, str] | None = None,
        policy_classification: str = "",
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        command = training_commands_pb2.CreateTrainingRunCommand(
            project=_project_ref(self._invoker.config),
            training_run_id=resource_id("training_run_id", training_run_id),
            training_recipe=training_recipe,
            dataset_release=dataset_release,
            model_release=model_release,
            labels=_labels(labels),
            policy_classification=policy_classification,
        )
        if executable_plan is not None:
            command.executable_plan.CopyFrom(executable_plan)
        if hardware_topology is not None:
            command.hardware_topology.CopyFrom(hardware_topology)
        if use_policy is not None:
            command.use_policy.CopyFrom(use_policy)
        return await self.submit_command(command, options=options)

    async def submit_command(
        self,
        command: training_commands_pb2.CreateTrainingRunCommand,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = training_commands_pb2.CreateTrainingRunCommand()
        materialized.CopyFrom(command)
        materialized.ClearField("context")
        _validate_create(materialized)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        materialized.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(materialized),
            )
        )
        response = cast(
            training_service_pb2.CreateTrainingRunResponse,
            await self._invoker.unary(
                CREATE_TRAINING_RUN,
                training_service_pb2.CreateTrainingRunRequest(command=materialized),
                call=call,
                retry_safe=True,
            ),
        )
        operation = required_response_message(
            response,
            "operation",
            operation_pb2.Operation,
            label="training submission",
        )
        required_text("operation id", operation.operation_id)
        return operation

    async def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> training_run_pb2.TrainingRun:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.GetTrainingRunResponse,
            await self._invoker.unary(
                GET_TRAINING_RUN,
                training_service_pb2.GetTrainingRunRequest(
                    name=required_text("training run name", name),
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        training_run = required_response_message(
            response,
            "training_run",
            training_run_pb2.TrainingRun,
            label="training get",
        )
        required_text("training run name", training_run.name)
        return training_run

    async def watch(
        self,
        name: str,
        *,
        after_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: asyncio.Event | None = None,
        options: CallOptions | None = None,
    ) -> AsyncIterator[training_service_pb2.WatchTrainingRunResponse]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("training watch was cancelled")
        base_call = prepare_call(
            options or CallOptions(timeout=timeout),
            default_timeout=timeout,
            require_idempotency=False,
        )
        run_name = required_text("training run name", name)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + base_call.timeout
        sequence = after_sequence
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("training watch was cancelled")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OperationTimeoutError("training watch exceeded its total deadline")
            stream_timeout = (
                min(remaining, _CANCELLATION_POLL_SECONDS)
                if cancellation is not None
                else remaining
            )
            call = PreparedCall(
                timeout=stream_timeout,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = training_service_pb2.WatchTrainingRunRequest(
                name=run_name,
                after_sequence=sequence,
            )
            try:
                async with asyncio.timeout(stream_timeout):
                    async for raw_response in self._invoker.stream(
                        WATCH_TRAINING_RUN,
                        request,
                        call=call,
                    ):
                        response = cast(
                            training_service_pb2.WatchTrainingRunResponse,
                            raw_response,
                        )
                        if response.sequence <= sequence:
                            raise ProtocolError(
                                "training watch sequence did not advance",
                                status=grpc.StatusCode.DATA_LOSS,
                            )
                        training_run = required_response_message(
                            response,
                            "training_run",
                            training_run_pb2.TrainingRun,
                            label="training watch",
                        )
                        if training_run.name != run_name:
                            raise ProtocolError(
                                "training watch returned a different run",
                                status=grpc.StatusCode.DATA_LOSS,
                            )
                        if training_run.state == training_run_pb2.TRAINING_RUN_STATE_UNSPECIFIED:
                            raise ProtocolError(
                                "training watch returned an unspecified state",
                                status=grpc.StatusCode.DATA_LOSS,
                            )
                        sequence = response.sequence
                        failures = 0
                        yield response
                        if training_run.state in _TERMINAL_TRAINING_STATES:
                            return
                stream_error: MindcladeError = UnavailableError(
                    "training watch closed before a terminal event",
                    retryable=True,
                )
            except TimeoutError:
                if cancellation is not None and loop.time() < deadline:
                    continue
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except DeadlineExceededError:
                if cancellation is not None and loop.time() < deadline:
                    continue
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = _watch_delay(self._invoker, failures, deadline - loop.time())
            if cancellation is None:
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                try:
                    await asyncio.wait_for(cancellation.wait(), timeout=delay)
                except TimeoutError:
                    pass
                else:
                    raise CancelledError("training watch was cancelled")
