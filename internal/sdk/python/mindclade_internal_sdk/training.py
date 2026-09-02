"""Ergonomic training calls built exclusively from generated contract types."""

from __future__ import annotations

import asyncio
import copy
import threading
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import grpc
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import command_context_pb2 as common_context_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.job.v1 import lease_fencing_pb2, operation_pb2
from mindclade.training.v1 import (
    checkpoint_pb2,
    training_commands_pb2,
    training_progress_pb2,
    training_run_pb2,
)

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context, retry_delay
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
from .transport import (
    CANCEL_TRAINING_RUN,
    COMMIT_CHECKPOINT,
    COMMIT_TRAINING_PROGRESS,
    COMPLETE_TRAINING_RUN,
    CREATE_TRAINING_RUN,
    GET_CHECKPOINT,
    GET_TRAINING_RUN,
    LIST_CHECKPOINTS,
    LIST_TRAINING_RUNS,
    PREPARE_CHECKPOINT,
    RESUME_TRAINING_ATTEMPT,
    START_TRAINING_ATTEMPT,
    WATCH_TRAINING_RUN,
)

_TERMINAL_TRAINING_STATES = frozenset(
    {
        training_run_pb2.TRAINING_RUN_STATE_COMPLETED,
        training_run_pb2.TRAINING_RUN_STATE_FAILED,
        training_run_pb2.TRAINING_RUN_STATE_CANCELLED,
    }
)
_MAXIMUM_PAGE_SIZE = 200


class _CommandContextCarrier(Protocol):
    context: common_context_pb2.CommandContext


def _deadline_timestamp(seconds: float) -> Timestamp:
    value = Timestamp()
    value.FromDatetime(datetime.now(UTC) + timedelta(seconds=seconds))
    return value


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


def _run_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    name = required_text("training run name", value, maximum=2048)
    prefix = invoker.config.project_parent + "/trainingRuns/"
    if name.startswith(prefix):
        run_id = name.removeprefix(prefix)
    elif name.startswith("tenants/"):
        raise ValueError("training run name conflicts with client scope")
    elif name.startswith("trainingRuns/"):
        run_id = name.removeprefix("trainingRuns/")
    else:
        run_id = name
    return prefix + resource_id("training run ID", run_id)


def _checkpoint_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    name = required_text("checkpoint name", value, maximum=2048)
    prefix = invoker.config.project_parent + "/trainingRuns/"
    if name.startswith(prefix):
        relative = name.removeprefix(prefix)
    elif name.startswith("tenants/"):
        raise ValueError("checkpoint name conflicts with client scope")
    elif name.startswith("trainingRuns/"):
        relative = name.removeprefix("trainingRuns/")
    else:
        relative = name
    parts = relative.split("/")
    if len(parts) != 3 or parts[1] != "checkpoints":
        raise ValueError("checkpoint name must be nested under a training run")
    run_id = resource_id("training run ID", parts[0])
    checkpoint_id = resource_id("checkpoint ID", parts[2])
    return f"{prefix}{run_id}/checkpoints/{checkpoint_id}"


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str,
) -> None:
    name = required_text(f"{resource_type} name", reference.name, maximum=2048)
    if resource_type == "checkpoint":
        name = _checkpoint_name(invoker, name)
    else:
        name = _run_name(invoker, name)
    resource_identifier = name.rsplit("/", 1)[-1]
    if reference.resource_type not in ("", resource_type):
        raise ValueError(f"{resource_type} reference has the wrong resource type")
    if reference.resource_id not in ("", resource_identifier):
        raise ValueError(f"{resource_type} reference ID conflicts with its name")
    if reference.tenant_id not in ("", invoker.config.tenant_id) or reference.project_id not in (
        "",
        invoker.config.project_id,
    ):
        raise ValueError(f"{resource_type} reference conflicts with client scope")
    reference.resource_type = resource_type
    reference.resource_id = resource_identifier
    reference.tenant_id = invoker.config.tenant_id
    reference.project_id = invoker.config.project_id
    reference.name = name


def _validate_fence(
    invoker: SyncInvoker | AsyncInvoker, fence: lease_fencing_pb2.LeaseFence
) -> None:
    if (
        not fence.job_id
        or not fence.run_id
        or not fence.attempt_id
        or fence.lease_epoch <= 0
        or not fence.HasField("deadline")
        or not fence.lease_token_digest.startswith("sha256:")
        or len(fence.lease_token_digest) != 71
    ):
        raise ValueError("training lease fence is incomplete")
    try:
        deadline = fence.deadline.ToDatetime(tzinfo=UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError("training lease deadline is invalid") from error
    if deadline <= datetime.now(UTC):
        raise ValueError("training lease fence has expired")
    if fence.tenant_id not in ("", invoker.config.tenant_id) or fence.project_id not in (
        "",
        invoker.config.project_id,
    ):
        raise ValueError("training lease fence conflicts with client scope")
    fence.tenant_id = invoker.config.tenant_id
    fence.project_id = invoker.config.project_id


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_command(
    invoker: SyncInvoker | AsyncInvoker,
    command: Message,
    options: CallOptions | None,
    *,
    require_lease: bool,
) -> tuple[Message, PreparedCall]:
    materialized = copy.deepcopy(command)
    context = cast(_CommandContextCarrier, materialized).context
    key = context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    selected = _mutation_options(key, options)
    if require_lease and (selected is None or selected.lease_token is None):
        raise ValueError("fenced training command requires a lease_token")
    call = prepare_call(
        selected,
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    cast(_CommandContextCarrier, materialized).context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


def _required_run(
    response: Message, label: str, expected_name: str
) -> training_run_pb2.TrainingRun:
    run = required_response_message(
        response, "training_run", training_run_pb2.TrainingRun, label=label
    )
    if run.name != expected_name:
        raise ProtocolError(
            f"{label} response changed training run identity",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return run


def _normalize_progress(
    invoker: SyncInvoker | AsyncInvoker,
    progress: training_progress_pb2.TrainingProgress,
    run_name: str,
) -> None:
    if (
        progress.progress_revision <= 0
        or _run_name(invoker, progress.training_run_name) != run_name
    ):
        raise ValueError("training progress must be monotonic and belong to the target run")
    progress.training_run_name = run_name


def _validated_run_page(
    invoker: SyncInvoker | AsyncInvoker,
    response: training_service_pb2.ListTrainingRunsResponse,
) -> training_service_pb2.ListTrainingRunsResponse:
    for run in response.training_runs:
        try:
            canonical = _run_name(invoker, run.name)
        except ValueError as error:
            raise ProtocolError(
                "training list returned a run outside client scope",
                status=grpc.StatusCode.DATA_LOSS,
            ) from error
        if canonical != run.name:
            raise ProtocolError(
                "training list returned a non-canonical run identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
    return response


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
        run_name = _run_name(self._invoker, name)
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
                    name=run_name,
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training get", run_name)

    def list_runs(
        self,
        request: training_service_pb2.ListTrainingRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> training_service_pb2.ListTrainingRunsResponse:
        materialized = training_service_pb2.ListTrainingRunsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = self._invoker.config.project_parent
        if materialized.parent not in ("", parent):
            raise ValueError("training list parent conflicts with client scope")
        if materialized.HasField("page") and materialized.page.page_size > _MAXIMUM_PAGE_SIZE:
            raise ValueError("training page size cannot exceed 200")
        materialized.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.ListTrainingRunsResponse,
            self._invoker.unary(LIST_TRAINING_RUNS, materialized, call=call, retry_safe=True),
        )
        return _validated_run_page(self._invoker, response)

    def start_attempt(
        self,
        command: training_commands_pb2.StartTrainingAttemptCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        _normalize_reference(self._invoker, value.training_run, resource_type="training_run")
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("deadline") or value.deadline.ToDatetime(tzinfo=UTC) <= datetime.now(
            UTC
        ):
            raise ValueError("training attempt deadline must be in the future")
        if value.HasField("delegated_capability"):
            resource_ref("delegated_capability", value.delegated_capability)
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.StartTrainingAttemptCommand, value)
        response = cast(
            training_service_pb2.StartTrainingAttemptResponse,
            self._invoker.unary(
                START_TRAINING_ATTEMPT,
                training_service_pb2.StartTrainingAttemptRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training attempt start", typed.training_run.name)

    def resume_attempt(
        self,
        command: training_commands_pb2.ResumeTrainingAttemptCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        _normalize_reference(self._invoker, value.training_run, resource_type="training_run")
        _normalize_reference(self._invoker, value.checkpoint, resource_type="checkpoint")
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("deadline") or value.deadline.ToDatetime(tzinfo=UTC) <= datetime.now(
            UTC
        ):
            raise ValueError("training resume deadline must be in the future")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.ResumeTrainingAttemptCommand, value)
        response = cast(
            training_service_pb2.ResumeTrainingAttemptResponse,
            self._invoker.unary(
                RESUME_TRAINING_ATTEMPT,
                training_service_pb2.ResumeTrainingAttemptRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training attempt resume", typed.training_run.name)

    def commit_progress(
        self,
        command: training_commands_pb2.CommitTrainingProgressCommand,
        *,
        options: CallOptions,
    ) -> tuple[training_progress_pb2.TrainingProgress, training_run_pb2.TrainingRun]:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("progress"):
            raise ValueError("training progress is required")
        _normalize_progress(self._invoker, value.progress, run_name)
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CommitTrainingProgressCommand, value)
        response = cast(
            training_service_pb2.CommitTrainingProgressResponse,
            self._invoker.unary(
                COMMIT_TRAINING_PROGRESS,
                training_service_pb2.CommitTrainingProgressRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        progress = required_response_message(
            response,
            "progress",
            training_progress_pb2.TrainingProgress,
            label="training progress commit",
        )
        if progress.training_run_name != run_name:
            raise ProtocolError("training progress response changed identity")
        return progress, _required_run(response, "training progress commit", run_name)

    def prepare_checkpoint(
        self,
        command: training_commands_pb2.PrepareCheckpointCommand,
        *,
        options: CallOptions,
    ) -> checkpoint_pb2.Checkpoint:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.snapshot_epoch <= 0
            or not value.HasField("logical_state_descriptor")
            or not value.HasField("committed_progress")
        ):
            raise ValueError("checkpoint preparation requires epoch, descriptor, and progress")
        artifact_ref("logical_state_descriptor", value.logical_state_descriptor)
        _normalize_progress(self._invoker, value.committed_progress, run_name)
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.PrepareCheckpointCommand, value)
        response = cast(
            training_service_pb2.PrepareCheckpointResponse,
            self._invoker.unary(
                PREPARE_CHECKPOINT,
                training_service_pb2.PrepareCheckpointRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint preparation"
        )
        if (
            checkpoint.training_run_name != run_name
            or checkpoint.snapshot_epoch != typed.snapshot_epoch
        ):
            raise ProtocolError("checkpoint preparation response changed identity")
        return checkpoint

    def commit_checkpoint(
        self,
        command: training_commands_pb2.CommitCheckpointCommand,
        *,
        options: CallOptions,
    ) -> tuple[checkpoint_pb2.Checkpoint, training_run_pb2.TrainingRun]:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.snapshot_epoch <= 0
            or not value.HasField("checkpoint_manifest")
            or not value.HasField("logical_state_descriptor")
            or not value.HasField("committed_progress")
            or not value.HasField("verification_evidence")
            or not value.HasField("committed_at")
        ):
            raise ValueError(
                "checkpoint commit requires immutable manifests, evidence, progress, and time"
            )
        artifact_ref("checkpoint_manifest", value.checkpoint_manifest)
        artifact_ref("logical_state_descriptor", value.logical_state_descriptor)
        _normalize_progress(self._invoker, value.committed_progress, run_name)
        if value.HasField("parent_checkpoint"):
            _normalize_reference(self._invoker, value.parent_checkpoint, resource_type="checkpoint")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CommitCheckpointCommand, value)
        response = cast(
            training_service_pb2.CommitCheckpointResponse,
            self._invoker.unary(
                COMMIT_CHECKPOINT,
                training_service_pb2.CommitCheckpointRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint commit"
        )
        if (
            checkpoint.training_run_name != run_name
            or checkpoint.snapshot_epoch != typed.snapshot_epoch
        ):
            raise ProtocolError("checkpoint commit response changed identity")
        return checkpoint, _required_run(response, "checkpoint commit", run_name)

    def complete(
        self,
        command: training_commands_pb2.CompleteTrainingRunCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.classification == training_run_pb2.TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED
            or not value.HasField("completed_at")
        ):
            raise ValueError("training completion requires classification and completion time")
        if value.HasField("final_checkpoint"):
            _normalize_reference(self._invoker, value.final_checkpoint, resource_type="checkpoint")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CompleteTrainingRunCommand, value)
        response = cast(
            training_service_pb2.CompleteTrainingRunResponse,
            self._invoker.unary(
                COMPLETE_TRAINING_RUN,
                training_service_pb2.CompleteTrainingRunRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training completion", run_name)

    def cancel(
        self,
        command: training_commands_pb2.CancelTrainingRunCommand,
        *,
        options: CallOptions | None = None,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        required_text("training ETag", value.etag)
        required_text("training cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_command(self._invoker, value, options, require_lease=False)
        typed = cast(training_commands_pb2.CancelTrainingRunCommand, value)
        response = cast(
            training_service_pb2.CancelTrainingRunResponse,
            self._invoker.unary(
                CANCEL_TRAINING_RUN,
                training_service_pb2.CancelTrainingRunRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training cancellation", run_name)

    def get_checkpoint(
        self, name: str, *, options: CallOptions | None = None
    ) -> checkpoint_pb2.Checkpoint:
        checkpoint_name = _checkpoint_name(self._invoker, name)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.GetCheckpointResponse,
            self._invoker.unary(
                GET_CHECKPOINT,
                training_service_pb2.GetCheckpointRequest(name=checkpoint_name),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint get"
        )
        if checkpoint.name != checkpoint_name:
            raise ProtocolError("checkpoint response changed identity")
        return checkpoint

    def list_checkpoints(
        self,
        request: training_service_pb2.ListCheckpointsRequest,
        *,
        options: CallOptions | None = None,
    ) -> training_service_pb2.ListCheckpointsResponse:
        materialized = copy.deepcopy(request)
        materialized.parent = _run_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > _MAXIMUM_PAGE_SIZE:
            raise ValueError("checkpoint page size cannot exceed 200")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.ListCheckpointsResponse,
            self._invoker.unary(LIST_CHECKPOINTS, materialized, call=call, retry_safe=True),
        )
        if any(item.training_run_name != materialized.parent for item in response.checkpoints):
            raise ProtocolError("checkpoint list crossed training run identity")
        return response

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
        run_name = _run_name(self._invoker, name)
        deadline = time.monotonic() + base_call.timeout
        sequence = after_sequence
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("training watch was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationTimeoutError("training watch exceeded its total deadline")
            call = PreparedCall(
                timeout=remaining,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = training_service_pb2.WatchTrainingRunRequest(
                name=run_name,
                after_sequence=sequence,
                deadline=_deadline_timestamp(remaining),
            )
            try:
                for raw_response in self._invoker.stream(
                    WATCH_TRAINING_RUN,
                    request,
                    call=call,
                    cancellation=cancellation,
                ):
                    response = cast(training_service_pb2.WatchTrainingRunResponse, raw_response)
                    if response.sequence != sequence + 1:
                        raise ProtocolError(
                            "training watch sequence was not contiguous",
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
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                deadline - time.monotonic(),
                retry_after=stream_error.retry_after,
            )
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
        run_name = _run_name(self._invoker, name)
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
                    name=run_name,
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training get", run_name)

    async def list_runs(
        self,
        request: training_service_pb2.ListTrainingRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> training_service_pb2.ListTrainingRunsResponse:
        materialized = training_service_pb2.ListTrainingRunsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = self._invoker.config.project_parent
        if materialized.parent not in ("", parent):
            raise ValueError("training list parent conflicts with client scope")
        if materialized.HasField("page") and materialized.page.page_size > _MAXIMUM_PAGE_SIZE:
            raise ValueError("training page size cannot exceed 200")
        materialized.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.ListTrainingRunsResponse,
            await self._invoker.unary(LIST_TRAINING_RUNS, materialized, call=call, retry_safe=True),
        )
        return _validated_run_page(self._invoker, response)

    async def start_attempt(
        self,
        command: training_commands_pb2.StartTrainingAttemptCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        _normalize_reference(self._invoker, value.training_run, resource_type="training_run")
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("deadline") or value.deadline.ToDatetime(tzinfo=UTC) <= datetime.now(
            UTC
        ):
            raise ValueError("training attempt deadline must be in the future")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.StartTrainingAttemptCommand, value)
        response = cast(
            training_service_pb2.StartTrainingAttemptResponse,
            await self._invoker.unary(
                START_TRAINING_ATTEMPT,
                training_service_pb2.StartTrainingAttemptRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training attempt start", typed.training_run.name)

    async def resume_attempt(
        self,
        command: training_commands_pb2.ResumeTrainingAttemptCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        _normalize_reference(self._invoker, value.training_run, resource_type="training_run")
        _normalize_reference(self._invoker, value.checkpoint, resource_type="checkpoint")
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("deadline") or value.deadline.ToDatetime(tzinfo=UTC) <= datetime.now(
            UTC
        ):
            raise ValueError("training resume deadline must be in the future")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.ResumeTrainingAttemptCommand, value)
        response = cast(
            training_service_pb2.ResumeTrainingAttemptResponse,
            await self._invoker.unary(
                RESUME_TRAINING_ATTEMPT,
                training_service_pb2.ResumeTrainingAttemptRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training attempt resume", typed.training_run.name)

    async def commit_progress(
        self,
        command: training_commands_pb2.CommitTrainingProgressCommand,
        *,
        options: CallOptions,
    ) -> tuple[training_progress_pb2.TrainingProgress, training_run_pb2.TrainingRun]:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if not value.HasField("progress"):
            raise ValueError("training progress is required")
        _normalize_progress(self._invoker, value.progress, run_name)
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CommitTrainingProgressCommand, value)
        response = cast(
            training_service_pb2.CommitTrainingProgressResponse,
            await self._invoker.unary(
                COMMIT_TRAINING_PROGRESS,
                training_service_pb2.CommitTrainingProgressRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        progress = required_response_message(
            response,
            "progress",
            training_progress_pb2.TrainingProgress,
            label="training progress commit",
        )
        if progress.training_run_name != run_name:
            raise ProtocolError("training progress response changed identity")
        return progress, _required_run(response, "training progress commit", run_name)

    async def prepare_checkpoint(
        self,
        command: training_commands_pb2.PrepareCheckpointCommand,
        *,
        options: CallOptions,
    ) -> checkpoint_pb2.Checkpoint:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.snapshot_epoch <= 0
            or not value.HasField("logical_state_descriptor")
            or not value.HasField("committed_progress")
        ):
            raise ValueError("checkpoint preparation requires epoch, descriptor, and progress")
        artifact_ref("logical_state_descriptor", value.logical_state_descriptor)
        _normalize_progress(self._invoker, value.committed_progress, run_name)
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.PrepareCheckpointCommand, value)
        response = cast(
            training_service_pb2.PrepareCheckpointResponse,
            await self._invoker.unary(
                PREPARE_CHECKPOINT,
                training_service_pb2.PrepareCheckpointRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint preparation"
        )
        if (
            checkpoint.training_run_name != run_name
            or checkpoint.snapshot_epoch != typed.snapshot_epoch
        ):
            raise ProtocolError("checkpoint preparation response changed identity")
        return checkpoint

    async def commit_checkpoint(
        self,
        command: training_commands_pb2.CommitCheckpointCommand,
        *,
        options: CallOptions,
    ) -> tuple[checkpoint_pb2.Checkpoint, training_run_pb2.TrainingRun]:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.snapshot_epoch <= 0
            or not value.HasField("checkpoint_manifest")
            or not value.HasField("logical_state_descriptor")
            or not value.HasField("committed_progress")
            or not value.HasField("verification_evidence")
            or not value.HasField("committed_at")
        ):
            raise ValueError(
                "checkpoint commit requires immutable manifests, evidence, progress, and time"
            )
        artifact_ref("checkpoint_manifest", value.checkpoint_manifest)
        artifact_ref("logical_state_descriptor", value.logical_state_descriptor)
        _normalize_progress(self._invoker, value.committed_progress, run_name)
        if value.HasField("parent_checkpoint"):
            _normalize_reference(self._invoker, value.parent_checkpoint, resource_type="checkpoint")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CommitCheckpointCommand, value)
        response = cast(
            training_service_pb2.CommitCheckpointResponse,
            await self._invoker.unary(
                COMMIT_CHECKPOINT,
                training_service_pb2.CommitCheckpointRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint commit"
        )
        if (
            checkpoint.training_run_name != run_name
            or checkpoint.snapshot_epoch != typed.snapshot_epoch
        ):
            raise ProtocolError("checkpoint commit response changed identity")
        return checkpoint, _required_run(response, "checkpoint commit", run_name)

    async def complete(
        self,
        command: training_commands_pb2.CompleteTrainingRunCommand,
        *,
        options: CallOptions,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        _validate_fence(self._invoker, value.fence)
        if (
            value.classification == training_run_pb2.TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED
            or not value.HasField("completed_at")
        ):
            raise ValueError("training completion requires classification and completion time")
        if value.HasField("final_checkpoint"):
            _normalize_reference(self._invoker, value.final_checkpoint, resource_type="checkpoint")
        value, call = _prepare_command(self._invoker, value, options, require_lease=True)
        typed = cast(training_commands_pb2.CompleteTrainingRunCommand, value)
        response = cast(
            training_service_pb2.CompleteTrainingRunResponse,
            await self._invoker.unary(
                COMPLETE_TRAINING_RUN,
                training_service_pb2.CompleteTrainingRunRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training completion", run_name)

    async def cancel(
        self,
        command: training_commands_pb2.CancelTrainingRunCommand,
        *,
        options: CallOptions | None = None,
    ) -> training_run_pb2.TrainingRun:
        value = copy.deepcopy(command)
        run_name = _run_name(self._invoker, value.training_run_name)
        value.training_run_name = run_name
        required_text("training ETag", value.etag)
        required_text("training cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_command(self._invoker, value, options, require_lease=False)
        typed = cast(training_commands_pb2.CancelTrainingRunCommand, value)
        response = cast(
            training_service_pb2.CancelTrainingRunResponse,
            await self._invoker.unary(
                CANCEL_TRAINING_RUN,
                training_service_pb2.CancelTrainingRunRequest(command=typed),
                call=call,
                retry_safe=True,
            ),
        )
        return _required_run(response, "training cancellation", run_name)

    async def get_checkpoint(
        self, name: str, *, options: CallOptions | None = None
    ) -> checkpoint_pb2.Checkpoint:
        checkpoint_name = _checkpoint_name(self._invoker, name)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.GetCheckpointResponse,
            await self._invoker.unary(
                GET_CHECKPOINT,
                training_service_pb2.GetCheckpointRequest(name=checkpoint_name),
                call=call,
                retry_safe=True,
            ),
        )
        checkpoint = required_response_message(
            response, "checkpoint", checkpoint_pb2.Checkpoint, label="checkpoint get"
        )
        if checkpoint.name != checkpoint_name:
            raise ProtocolError("checkpoint response changed identity")
        return checkpoint

    async def list_checkpoints(
        self,
        request: training_service_pb2.ListCheckpointsRequest,
        *,
        options: CallOptions | None = None,
    ) -> training_service_pb2.ListCheckpointsResponse:
        materialized = copy.deepcopy(request)
        materialized.parent = _run_name(self._invoker, materialized.parent)
        if materialized.HasField("page") and materialized.page.page_size > _MAXIMUM_PAGE_SIZE:
            raise ValueError("checkpoint page size cannot exceed 200")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            training_service_pb2.ListCheckpointsResponse,
            await self._invoker.unary(LIST_CHECKPOINTS, materialized, call=call, retry_safe=True),
        )
        if any(item.training_run_name != materialized.parent for item in response.checkpoints):
            raise ProtocolError("checkpoint list crossed training run identity")
        return response

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
        run_name = _run_name(self._invoker, name)
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
            call = PreparedCall(
                timeout=remaining,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = training_service_pb2.WatchTrainingRunRequest(
                name=run_name,
                after_sequence=sequence,
                deadline=_deadline_timestamp(remaining),
            )
            try:
                async with asyncio.timeout(remaining):
                    async for raw_response in self._invoker.stream(
                        WATCH_TRAINING_RUN,
                        request,
                        call=call,
                        cancellation=cancellation,
                    ):
                        response = cast(
                            training_service_pb2.WatchTrainingRunResponse,
                            raw_response,
                        )
                        if response.sequence != sequence + 1:
                            raise ProtocolError(
                                "training watch sequence was not contiguous",
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
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except DeadlineExceededError:
                raise OperationTimeoutError("training watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                deadline - loop.time(),
                retry_after=stream_error.retry_after,
            )
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
