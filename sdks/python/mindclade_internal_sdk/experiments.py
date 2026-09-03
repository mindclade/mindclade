"""Private generated-type Experiment, Study, and Trial lifecycle façade."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import grpc
from google.protobuf.message import Message
from mindclade.artifact.v1 import artifact_reference_pb2, evidence_reference_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.experiment.v1 import (
    experiment_commands_pb2,
    experiment_pb2,
    study_pb2,
    trial_pb2,
)
from mindclade.internal.experiment.v1 import experiment_service_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._raw import AsyncWithRawResponse, WithRawResponse
from ._validation import artifact_ref, required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ProtocolError
from .pagination import (
    AsyncPage,
    Page,
    PaginationLimits,
    apply_default_page_size,
    async_page,
    next_request,
    sync_page,
)
from .transport import (
    COMPLETE_TRIAL,
    CREATE_EXPERIMENT,
    CREATE_STUDY,
    CREATE_TRIAL,
    GET_EXPERIMENT,
    GET_STUDY,
    GET_TRIAL,
    LIST_EXPERIMENTS,
    LIST_STUDIES,
    LIST_TRIALS,
    TRANSITION_EXPERIMENT,
    TRANSITION_STUDY,
    TRANSITION_TRIAL,
    UPDATE_EXPERIMENT,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LEAF = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,127})\Z")
_REASON = re.compile(r"[A-Z0-9](?:[A-Z0-9_]{0,127})\Z")
_MAX_PAGE_SIZE = 200
_MAX_STUDY_DURATION_NANOSECONDS = 31_536_000 * 1_000_000_000


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _leaf(label: str, value: str) -> str:
    if _LEAF.fullmatch(value) is None:
        raise ValueError(f"{label} must be one bounded resource-name segment")
    return value


def _experiment_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    prefix = f"{_project(invoker)}/experiments/"
    suffix = value.removeprefix(prefix)
    if not value.startswith(prefix) or _LEAF.fullmatch(suffix) is None:
        raise ValueError("experiment name must be scoped to the configured project")
    return value


def _study_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    prefix = f"{_project(invoker)}/experiments/"
    suffix = value.removeprefix(prefix)
    parts = suffix.split("/studies/")
    if (
        not value.startswith(prefix)
        or len(parts) != 2
        or any(_LEAF.fullmatch(x) is None for x in parts)
    ):
        raise ValueError("study name must be scoped to one configured experiment")
    return value


def _trial_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    parent, marker, leaf = value.rpartition("/trials/")
    if not marker or _LEAF.fullmatch(leaf) is None:
        raise ValueError("trial name must be scoped to one configured study")
    _study_name(invoker, parent)
    return value


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    value: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str = "",
    name_kind: str = "",
) -> None:
    if resource_type and value.resource_type not in ("", resource_type):
        raise ValueError("experiment resource reference type conflicts with command intent")
    if value.resource_version < 1 or _DIGEST.fullmatch(value.etag) is None:
        raise ValueError("experiment resource reference must carry revision and canonical ETag")
    config = invoker.config
    if value.tenant_id not in ("", config.tenant_id) or value.project_id not in (
        "",
        config.project_id,
    ):
        raise ValueError("experiment resource reference conflicts with client scope")
    if name_kind == "experiment":
        _experiment_name(invoker, value.name)
    elif name_kind == "study":
        _study_name(invoker, value.name)
    elif name_kind == "trial":
        _trial_name(invoker, value.name)
    else:
        required_text("resource reference name", value.name, maximum=2048)
    resource_id = value.name.rsplit("/", 1)[-1]
    _leaf("resource reference ID", resource_id)
    if value.resource_id not in ("", resource_id):
        raise ValueError("experiment resource reference ID conflicts with its name")
    if resource_type:
        value.resource_type = resource_type
    value.resource_id = resource_id
    value.tenant_id = config.tenant_id
    value.project_id = config.project_id


def _artifact(label: str, value: artifact_reference_pb2.ArtifactRef | None) -> None:
    if value is None:
        raise ValueError(f"{label} is required")
    artifact_ref(label, value)
    if value.integrity_digest and _DIGEST.fullmatch(value.integrity_digest) is None:
        raise ValueError(f"{label}.integrity_digest must be a canonical sha256 digest")


def _bounded_map(label: str, value: Mapping[str, str], maximum: int) -> None:
    if len(value) > 128 or any(
        not key.strip()
        or key != key.strip()
        or len(key) > 128
        or len(item) > maximum
        or "\x00" in key
        or "\x00" in item
        for key, item in value.items()
    ):
        raise ValueError(f"{label} exceeds bounded contract limits")


def _reason(value: str) -> None:
    if _REASON.fullmatch(value) is None:
        raise ValueError("reason_code must be uppercase snake case and no more than 128 bytes")


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if key and options is not None and options.idempotency_key not in (None, key):
        raise ValueError("command and call idempotency keys must match exactly")
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_mutation[
    T: (
        experiment_commands_pb2.CreateExperimentCommand,
        experiment_commands_pb2.UpdateExperimentCommand,
        experiment_commands_pb2.TransitionExperimentCommand,
        experiment_commands_pb2.CreateStudyCommand,
        experiment_commands_pb2.TransitionStudyCommand,
        experiment_commands_pb2.CreateTrialCommand,
        experiment_commands_pb2.TransitionTrialCommand,
        experiment_commands_pb2.CompleteTrialCommand,
    )
](
    invoker: SyncInvoker | AsyncInvoker,
    command: T,
    options: CallOptions | None,
) -> tuple[T, PreparedCall]:
    materialized = copy.deepcopy(command)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


def _read_call(invoker: SyncInvoker | AsyncInvoker, options: CallOptions | None) -> PreparedCall:
    return prepare_call(
        options, default_timeout=invoker.config.default_timeout, require_idempotency=False
    )


def _response[T: Message](response: Message, field: str, kind: type[T], name: str, label: str) -> T:
    value = required_response_message(response, field, kind, label=label)
    if cast(object, value).name != name:  # type: ignore[attr-defined]
        raise ProtocolError(f"{label} changed durable identity", status=grpc.StatusCode.DATA_LOSS)
    return value


def _experiment_page(
    invoker: SyncInvoker | AsyncInvoker,
    response: experiment_service_pb2.ListExperimentsResponse,
) -> experiment_service_pb2.ListExperimentsResponse:
    for value in response.experiments:
        _experiment_name(invoker, value.name)
    return response


def _study_page(
    invoker: SyncInvoker | AsyncInvoker,
    parent: str,
    response: experiment_service_pb2.ListStudiesResponse,
) -> experiment_service_pb2.ListStudiesResponse:
    for value in response.studies:
        name = _study_name(invoker, value.name)
        if not name.startswith(f"{parent}/studies/"):
            raise ProtocolError(
                "study list returned an out-of-parent resource", status=grpc.StatusCode.DATA_LOSS
            )
    return response


def _trial_page(
    invoker: SyncInvoker | AsyncInvoker,
    parent: str,
    response: experiment_service_pb2.ListTrialsResponse,
) -> experiment_service_pb2.ListTrialsResponse:
    for value in response.trials:
        name = _trial_name(invoker, value.name)
        if not name.startswith(f"{parent}/trials/"):
            raise ProtocolError(
                "trial list returned an out-of-parent resource", status=grpc.StatusCode.DATA_LOSS
            )
    return response


def _validate_create_experiment(
    invoker: SyncInvoker | AsyncInvoker, value: experiment_commands_pb2.CreateExperimentCommand
) -> str:
    identifier = _leaf("experiment_id", value.experiment_id)
    required_text("experiment display_name", value.display_name, maximum=512)
    required_text("policy_classification", value.policy_classification, maximum=128)
    if (
        value.kind == experiment_pb2.EXPERIMENT_KIND_UNSPECIFIED
        or not 1 <= len(value.subjects) <= 256
    ):
        raise ValueError("experiment kind and between one and 256 subjects are required")
    value.project.CopyFrom(
        resource_reference_pb2.ResourceRef(
            resource_type="project",
            resource_id=invoker.config.project_id,
            tenant_id=invoker.config.tenant_id,
            project_id=invoker.config.project_id,
            name=_project(invoker),
        )
    )
    _artifact(
        "intent_manifest", value.intent_manifest if value.HasField("intent_manifest") else None
    )
    if not value.HasField("use_policy"):
        raise ValueError("use_policy is required")
    _normalize_reference(invoker, value.use_policy, resource_type="use_policy")
    for subject in value.subjects:
        _normalize_reference(invoker, subject)
    _bounded_map("labels", value.labels, 256)
    _bounded_map("annotations", value.annotations, 4096)
    return f"{_project(invoker)}/experiments/{identifier}"


def _validate_update(
    invoker: SyncInvoker | AsyncInvoker, value: experiment_commands_pb2.UpdateExperimentCommand
) -> str:
    if not value.HasField("experiment") or not value.HasField("update_mask"):
        raise ValueError("experiment update requires generated state and FieldMask")
    name = _experiment_name(invoker, value.experiment.name)
    required_text("experiment ETag", value.etag)
    if value.etag != value.experiment.etag:
        raise ValueError("experiment update ETag conflicts with generated state")
    allowed = {"display_name", "labels", "annotations", "policy_classification"}
    if not 1 <= len(value.update_mask.paths) <= 4 or not set(value.update_mask.paths) <= allowed:
        raise ValueError("experiment update mask contains unsupported fields")
    _bounded_map("labels", value.experiment.labels, 256)
    _bounded_map("annotations", value.experiment.annotations, 4096)
    return name


type _TransitionCommand = (
    experiment_commands_pb2.TransitionExperimentCommand
    | experiment_commands_pb2.TransitionStudyCommand
    | experiment_commands_pb2.TransitionTrialCommand
)


def _validate_transition(
    invoker: SyncInvoker | AsyncInvoker, value: _TransitionCommand, kind: str
) -> str:
    if isinstance(value, experiment_commands_pb2.TransitionExperimentCommand):
        reference = value.experiment
    elif isinstance(value, experiment_commands_pb2.TransitionStudyCommand):
        reference = value.study
    else:
        reference = value.trial
    _normalize_reference(invoker, reference, resource_type=kind, name_kind=kind)
    required_text(f"{kind} ETag", value.etag)
    expected = value.expected_state
    target = value.target_state
    if expected == 0 or target == 0 or expected == target:
        raise ValueError(f"{kind} transition requires distinct specified states")
    _reason(value.reason_code)
    return reference.name


def _validate_create_study(
    invoker: SyncInvoker | AsyncInvoker, value: experiment_commands_pb2.CreateStudyCommand
) -> str:
    identifier = _leaf("study_id", value.study_id)
    if not value.HasField("experiment"):
        raise ValueError("study experiment reference is required")
    _normalize_reference(
        invoker, value.experiment, resource_type="experiment", name_kind="experiment"
    )
    if value.type == study_pb2.STUDY_TYPE_UNSPECIFIED or not value.HasField("budget"):
        raise ValueError("study type and budget are required")
    budget = value.budget
    duration = budget.maximum_duration
    if (
        not 1 <= budget.maximum_trials <= 100000
        or not 1 <= budget.maximum_parallel_trials <= budget.maximum_trials
        or not budget.HasField("maximum_duration")
        or not 0 <= duration.nanos < 1_000_000_000
        or not 0 < duration.ToNanoseconds() <= _MAX_STUDY_DURATION_NANOSECONDS
    ):
        raise ValueError("study budget is invalid or unbounded")
    for field, label in (
        ("study_manifest", "study_manifest"),
        ("base_configuration", "base_configuration"),
        ("search_space", "search_space"),
        ("objective_specification", "objective_specification"),
    ):
        _artifact(label, getattr(value, field) if value.HasField(field) else None)
    return f"{value.experiment.name}/studies/{identifier}"


def _validate_create_trial(
    invoker: SyncInvoker | AsyncInvoker, value: experiment_commands_pb2.CreateTrialCommand
) -> str:
    identifier = _leaf("trial_id", value.trial_id)
    if not value.HasField("study") or value.trial_number <= 0:
        raise ValueError("trial study and positive trial_number are required")
    _normalize_reference(invoker, value.study, resource_type="study", name_kind="study")
    _artifact(
        "resolved_configuration",
        value.resolved_configuration if value.HasField("resolved_configuration") else None,
    )
    if value.HasField("execution"):
        _normalize_reference(invoker, value.execution)
    return f"{value.study.name}/trials/{identifier}"


def _validate_complete(
    invoker: SyncInvoker | AsyncInvoker, value: experiment_commands_pb2.CompleteTrialCommand
) -> str:
    if not value.HasField("trial"):
        raise ValueError("trial completion reference is required")
    _normalize_reference(invoker, value.trial, resource_type="trial", name_kind="trial")
    required_text("trial ETag", value.etag)
    if value.outcome in (trial_pb2.TRIAL_OUTCOME_UNSPECIFIED, trial_pb2.TRIAL_OUTCOME_CANCELLED):
        raise ValueError("trial completion outcome is unsupported")
    if value.outcome == trial_pb2.TRIAL_OUTCOME_FAILED:
        if (
            not value.HasField("error")
            or not value.error.message.strip()
            or value.HasField("result_manifest")
        ):
            raise ValueError("failed trial requires generated error and no result manifest")
    else:
        _artifact(
            "result_manifest", value.result_manifest if value.HasField("result_manifest") else None
        )
        if value.HasField("error"):
            raise ValueError("non-failed trial cannot carry an error")
    if len(value.evidence) > 256:
        raise ValueError("trial evidence exceeds the bounded limit")
    for item in cast(list[evidence_reference_pb2.EvidenceRef], value.evidence):
        if (
            _DIGEST.fullmatch(item.digest) is None
            or _DIGEST.fullmatch(item.subject_digest) is None
            or not item.evidence_kind.strip()
            or (item.policy_digest and _DIGEST.fullmatch(item.policy_digest) is None)
        ):
            raise ValueError("trial evidence requires canonical immutable digests")
    return value.trial.name


class Experiments(WithRawResponse):
    """Synchronous private Experiment, Study, and Trial API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def _mutation(
        self, route: str, command: Message, request: Message, call: PreparedCall
    ) -> Message:
        return self._invoker.unary(route, request, call=call, retry_safe=True)

    def create(
        self,
        command: experiment_commands_pb2.CreateExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_create_experiment(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            CREATE_EXPERIMENT,
            value,
            experiment_service_pb2.CreateExperimentRequest(command=value),
            call,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment creation"
        )

    def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> experiment_pb2.Experiment:
        scoped = _experiment_name(self._invoker, name)
        response = self._invoker.unary(
            GET_EXPERIMENT,
            experiment_service_pb2.GetExperimentRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, scoped, "experiment get"
        )

    def list(
        self,
        request: experiment_service_pb2.ListExperimentsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[experiment_pb2.Experiment]:
        value = (
            copy.deepcopy(request)
            if request is not None
            else experiment_service_pb2.ListExperimentsRequest()
        )
        if (
            value.parent not in ("", _project(self._invoker))
            or value.page.page_size > _MAX_PAGE_SIZE
        ):
            raise ValueError("experiment list scope or page size is invalid")
        value.parent = _project(self._invoker)
        apply_default_page_size(value, limits)
        response = _experiment_page(
            self._invoker,
            cast(
                experiment_service_pb2.ListExperimentsResponse,
                self._invoker.unary(
                    LIST_EXPERIMENTS,
                    value,
                    call=_read_call(self._invoker, options),
                    retry_safe=True,
                ),
            ),
        )

        def follow(page_token: str) -> Page[experiment_pb2.Experiment]:
            return self.list(next_request(value, page_token), options=options, limits=limits)

        return sync_page(response, items_field="experiments", fetch=follow, limits=limits)

    def update(
        self,
        command: experiment_commands_pb2.UpdateExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_update(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            UPDATE_EXPERIMENT,
            value,
            experiment_service_pb2.UpdateExperimentRequest(command=value),
            call,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment update"
        )

    def transition(
        self,
        command: experiment_commands_pb2.TransitionExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "experiment")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            TRANSITION_EXPERIMENT,
            value,
            experiment_service_pb2.TransitionExperimentRequest(command=value),
            call,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment transition"
        )

    def create_study(
        self,
        command: experiment_commands_pb2.CreateStudyCommand,
        *,
        options: CallOptions | None = None,
    ) -> study_pb2.Study:
        value = copy.deepcopy(command)
        name = _validate_create_study(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            CREATE_STUDY, value, experiment_service_pb2.CreateStudyRequest(command=value), call
        )
        return _response(response, "study", study_pb2.Study, name, "study creation")

    def get_study(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> study_pb2.Study:
        scoped = _study_name(self._invoker, name)
        response = self._invoker.unary(
            GET_STUDY,
            experiment_service_pb2.GetStudyRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(response, "study", study_pb2.Study, scoped, "study get")

    def list_studies(
        self,
        request: experiment_service_pb2.ListStudiesRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[study_pb2.Study]:
        value = copy.deepcopy(request)
        _experiment_name(self._invoker, value.parent)
        if value.page.page_size > _MAX_PAGE_SIZE:
            raise ValueError("study page size cannot exceed 200")
        apply_default_page_size(value, limits)
        response = _study_page(
            self._invoker,
            value.parent,
            cast(
                experiment_service_pb2.ListStudiesResponse,
                self._invoker.unary(
                    LIST_STUDIES, value, call=_read_call(self._invoker, options), retry_safe=True
                ),
            ),
        )

        def follow(page_token: str) -> Page[study_pb2.Study]:
            return self.list_studies(
                next_request(value, page_token), options=options, limits=limits
            )

        return sync_page(response, items_field="studies", fetch=follow, limits=limits)

    def transition_study(
        self,
        command: experiment_commands_pb2.TransitionStudyCommand,
        *,
        options: CallOptions | None = None,
    ) -> study_pb2.Study:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "study")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            TRANSITION_STUDY,
            value,
            experiment_service_pb2.TransitionStudyRequest(command=value),
            call,
        )
        return _response(response, "study", study_pb2.Study, name, "study transition")

    def create_trial(
        self,
        command: experiment_commands_pb2.CreateTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_create_trial(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            CREATE_TRIAL, value, experiment_service_pb2.CreateTrialRequest(command=value), call
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial creation")

    def get_trial(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> trial_pb2.Trial:
        scoped = _trial_name(self._invoker, name)
        response = self._invoker.unary(
            GET_TRIAL,
            experiment_service_pb2.GetTrialRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(response, "trial", trial_pb2.Trial, scoped, "trial get")

    def list_trials(
        self,
        request: experiment_service_pb2.ListTrialsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[trial_pb2.Trial]:
        value = copy.deepcopy(request)
        _study_name(self._invoker, value.parent)
        if value.page.page_size > _MAX_PAGE_SIZE:
            raise ValueError("trial page size cannot exceed 200")
        apply_default_page_size(value, limits)
        response = _trial_page(
            self._invoker,
            value.parent,
            cast(
                experiment_service_pb2.ListTrialsResponse,
                self._invoker.unary(
                    LIST_TRIALS, value, call=_read_call(self._invoker, options), retry_safe=True
                ),
            ),
        )

        def follow(page_token: str) -> Page[trial_pb2.Trial]:
            return self.list_trials(next_request(value, page_token), options=options, limits=limits)

        return sync_page(response, items_field="trials", fetch=follow, limits=limits)

    def transition_trial(
        self,
        command: experiment_commands_pb2.TransitionTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "trial")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            TRANSITION_TRIAL,
            value,
            experiment_service_pb2.TransitionTrialRequest(command=value),
            call,
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial transition")

    def complete_trial(
        self,
        command: experiment_commands_pb2.CompleteTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_complete(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = self._mutation(
            COMPLETE_TRIAL, value, experiment_service_pb2.CompleteTrialRequest(command=value), call
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial completion")


class AsyncExperiments(AsyncWithRawResponse):
    """Asyncio-native private Experiment, Study, and Trial API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def create(
        self,
        command: experiment_commands_pb2.CreateExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_create_experiment(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            CREATE_EXPERIMENT,
            experiment_service_pb2.CreateExperimentRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment creation"
        )

    async def get(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> experiment_pb2.Experiment:
        scoped = _experiment_name(self._invoker, name)
        response = await self._invoker.unary(
            GET_EXPERIMENT,
            experiment_service_pb2.GetExperimentRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, scoped, "experiment get"
        )

    async def list(
        self,
        request: experiment_service_pb2.ListExperimentsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[experiment_pb2.Experiment]:
        value = (
            copy.deepcopy(request)
            if request is not None
            else experiment_service_pb2.ListExperimentsRequest()
        )
        if (
            value.parent not in ("", _project(self._invoker))
            or value.page.page_size > _MAX_PAGE_SIZE
        ):
            raise ValueError("experiment list scope or page size is invalid")
        value.parent = _project(self._invoker)
        apply_default_page_size(value, limits)
        response = _experiment_page(
            self._invoker,
            cast(
                experiment_service_pb2.ListExperimentsResponse,
                await self._invoker.unary(
                    LIST_EXPERIMENTS,
                    value,
                    call=_read_call(self._invoker, options),
                    retry_safe=True,
                ),
            ),
        )

        async def follow(page_token: str) -> AsyncPage[experiment_pb2.Experiment]:
            return await self.list(next_request(value, page_token), options=options, limits=limits)

        return async_page(response, items_field="experiments", fetch=follow, limits=limits)

    async def update(
        self,
        command: experiment_commands_pb2.UpdateExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_update(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            UPDATE_EXPERIMENT,
            experiment_service_pb2.UpdateExperimentRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment update"
        )

    async def transition(
        self,
        command: experiment_commands_pb2.TransitionExperimentCommand,
        *,
        options: CallOptions | None = None,
    ) -> experiment_pb2.Experiment:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "experiment")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            TRANSITION_EXPERIMENT,
            experiment_service_pb2.TransitionExperimentRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(
            response, "experiment", experiment_pb2.Experiment, name, "experiment transition"
        )

    async def create_study(
        self,
        command: experiment_commands_pb2.CreateStudyCommand,
        *,
        options: CallOptions | None = None,
    ) -> study_pb2.Study:
        value = copy.deepcopy(command)
        name = _validate_create_study(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            CREATE_STUDY,
            experiment_service_pb2.CreateStudyRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(response, "study", study_pb2.Study, name, "study creation")

    async def get_study(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> study_pb2.Study:
        scoped = _study_name(self._invoker, name)
        response = await self._invoker.unary(
            GET_STUDY,
            experiment_service_pb2.GetStudyRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(response, "study", study_pb2.Study, scoped, "study get")

    async def list_studies(
        self,
        request: experiment_service_pb2.ListStudiesRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[study_pb2.Study]:
        value = copy.deepcopy(request)
        _experiment_name(self._invoker, value.parent)
        if value.page.page_size > _MAX_PAGE_SIZE:
            raise ValueError("study page size cannot exceed 200")
        apply_default_page_size(value, limits)
        response = _study_page(
            self._invoker,
            value.parent,
            cast(
                experiment_service_pb2.ListStudiesResponse,
                await self._invoker.unary(
                    LIST_STUDIES, value, call=_read_call(self._invoker, options), retry_safe=True
                ),
            ),
        )

        async def follow(page_token: str) -> AsyncPage[study_pb2.Study]:
            return await self.list_studies(
                next_request(value, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="studies", fetch=follow, limits=limits)

    async def transition_study(
        self,
        command: experiment_commands_pb2.TransitionStudyCommand,
        *,
        options: CallOptions | None = None,
    ) -> study_pb2.Study:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "study")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            TRANSITION_STUDY,
            experiment_service_pb2.TransitionStudyRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(response, "study", study_pb2.Study, name, "study transition")

    async def create_trial(
        self,
        command: experiment_commands_pb2.CreateTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_create_trial(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            CREATE_TRIAL,
            experiment_service_pb2.CreateTrialRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial creation")

    async def get_trial(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> trial_pb2.Trial:
        scoped = _trial_name(self._invoker, name)
        response = await self._invoker.unary(
            GET_TRIAL,
            experiment_service_pb2.GetTrialRequest(
                name=scoped, if_none_match=if_none_match.strip()
            ),
            call=_read_call(self._invoker, options),
            retry_safe=True,
        )
        return _response(response, "trial", trial_pb2.Trial, scoped, "trial get")

    async def list_trials(
        self,
        request: experiment_service_pb2.ListTrialsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[trial_pb2.Trial]:
        value = copy.deepcopy(request)
        _study_name(self._invoker, value.parent)
        if value.page.page_size > _MAX_PAGE_SIZE:
            raise ValueError("trial page size cannot exceed 200")
        apply_default_page_size(value, limits)
        response = _trial_page(
            self._invoker,
            value.parent,
            cast(
                experiment_service_pb2.ListTrialsResponse,
                await self._invoker.unary(
                    LIST_TRIALS, value, call=_read_call(self._invoker, options), retry_safe=True
                ),
            ),
        )

        async def follow(page_token: str) -> AsyncPage[trial_pb2.Trial]:
            return await self.list_trials(
                next_request(value, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="trials", fetch=follow, limits=limits)

    async def transition_trial(
        self,
        command: experiment_commands_pb2.TransitionTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_transition(self._invoker, value, "trial")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            TRANSITION_TRIAL,
            experiment_service_pb2.TransitionTrialRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial transition")

    async def complete_trial(
        self,
        command: experiment_commands_pb2.CompleteTrialCommand,
        *,
        options: CallOptions | None = None,
    ) -> trial_pb2.Trial:
        value = copy.deepcopy(command)
        name = _validate_complete(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = await self._invoker.unary(
            COMPLETE_TRIAL,
            experiment_service_pb2.CompleteTrialRequest(command=value),
            call=call,
            retry_safe=True,
        )
        return _response(response, "trial", trial_pb2.Trial, name, "trial completion")
