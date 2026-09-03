from __future__ import annotations

import asyncio
import copy
import unittest

from google.protobuf.duration_pb2 import Duration
from google.protobuf.field_mask_pb2 import FieldMask
from google.protobuf.message import Message
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import pagination_pb2, resource_reference_pb2
from mindclade.experiment.v1 import (
    experiment_commands_pb2,
    experiment_pb2,
    study_pb2,
    trial_pb2,
)
from mindclade.internal.experiment.v1 import experiment_service_pb2
from mindclade_internal_sdk._invocation import AsyncInvoker, SyncInvoker, canonical_digest
from mindclade_internal_sdk.calls import CallOptions
from mindclade_internal_sdk.config import ClientConfig, Environment
from mindclade_internal_sdk.experiments import AsyncExperiments, Experiments
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
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
    Metadata,
)

PARENT = "tenants/tenant-1/projects/project-1"
EXPERIMENT = f"{PARENT}/experiments/experiment-1"
STUDY = f"{EXPERIMENT}/studies/study-1"
TRIAL = f"{STUDY}/trials/trial-1"
ROUTES = (
    CREATE_EXPERIMENT,
    GET_EXPERIMENT,
    LIST_EXPERIMENTS,
    UPDATE_EXPERIMENT,
    TRANSITION_EXPERIMENT,
    CREATE_STUDY,
    GET_STUDY,
    LIST_STUDIES,
    TRANSITION_STUDY,
    CREATE_TRIAL,
    GET_TRIAL,
    LIST_TRIALS,
    TRANSITION_TRIAL,
    COMPLETE_TRIAL,
)


def config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:1",
        insecure_for_testing=True,
        default_timeout=2,
    )


def digest(seed: str) -> str:
    return "sha256:" + seed * 64


def artifact(seed: str) -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest=digest(seed),
        integrity_digest=digest(seed),
        media_type="application/json",
        size_bytes=7,
        artifact_kind="manifest",
    )


def reference(kind: str, name: str) -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(
        resource_type=kind,
        resource_id=name.rsplit("/", 1)[-1],
        tenant_id="tenant-1",
        project_id="project-1",
        resource_version=1,
        name=name,
        etag=digest("e"),
    )


def experiment() -> experiment_pb2.Experiment:
    return experiment_pb2.Experiment(name=EXPERIMENT, revision=1, etag=digest("e"))


def study() -> study_pb2.Study:
    return study_pb2.Study(name=STUDY, revision=1, etag=digest("e"))


def trial() -> trial_pb2.Trial:
    return trial_pb2.Trial(name=TRIAL, revision=1, etag=digest("e"))


def response(request: Message) -> Message:
    if isinstance(request, experiment_service_pb2.CreateExperimentRequest):
        return experiment_service_pb2.CreateExperimentResponse(experiment=experiment())
    if isinstance(request, experiment_service_pb2.GetExperimentRequest):
        return experiment_service_pb2.GetExperimentResponse(
            experiment=experiment_pb2.Experiment(name=request.name)
        )
    if isinstance(request, experiment_service_pb2.ListExperimentsRequest):
        return experiment_service_pb2.ListExperimentsResponse(
            experiments=[experiment()],
            page=pagination_pb2.PageResponse(next_page_token="next"),
        )
    if isinstance(request, experiment_service_pb2.UpdateExperimentRequest):
        return experiment_service_pb2.UpdateExperimentResponse(experiment=experiment())
    if isinstance(request, experiment_service_pb2.TransitionExperimentRequest):
        return experiment_service_pb2.TransitionExperimentResponse(experiment=experiment())
    if isinstance(request, experiment_service_pb2.CreateStudyRequest):
        return experiment_service_pb2.CreateStudyResponse(study=study())
    if isinstance(request, experiment_service_pb2.GetStudyRequest):
        return experiment_service_pb2.GetStudyResponse(study=study_pb2.Study(name=request.name))
    if isinstance(request, experiment_service_pb2.ListStudiesRequest):
        return experiment_service_pb2.ListStudiesResponse(
            studies=[study()], page=pagination_pb2.PageResponse(next_page_token="next")
        )
    if isinstance(request, experiment_service_pb2.TransitionStudyRequest):
        return experiment_service_pb2.TransitionStudyResponse(study=study())
    if isinstance(request, experiment_service_pb2.CreateTrialRequest):
        return experiment_service_pb2.CreateTrialResponse(trial=trial())
    if isinstance(request, experiment_service_pb2.GetTrialRequest):
        return experiment_service_pb2.GetTrialResponse(trial=trial_pb2.Trial(name=request.name))
    if isinstance(request, experiment_service_pb2.ListTrialsRequest):
        return experiment_service_pb2.ListTrialsResponse(
            trials=[trial()], page=pagination_pb2.PageResponse(next_page_token="next")
        )
    if isinstance(request, experiment_service_pb2.TransitionTrialRequest):
        return experiment_service_pb2.TransitionTrialResponse(trial=trial())
    if isinstance(request, experiment_service_pb2.CompleteTrialRequest):
        return experiment_service_pb2.CompleteTrialResponse(trial=trial())
    raise AssertionError(type(request))


def commands() -> tuple[
    experiment_commands_pb2.CreateExperimentCommand,
    experiment_commands_pb2.UpdateExperimentCommand,
    experiment_commands_pb2.TransitionExperimentCommand,
    experiment_commands_pb2.CreateStudyCommand,
    experiment_commands_pb2.TransitionStudyCommand,
    experiment_commands_pb2.CreateTrialCommand,
    experiment_commands_pb2.TransitionTrialCommand,
    experiment_commands_pb2.CompleteTrialCommand,
]:
    create = experiment_commands_pb2.CreateExperimentCommand(
        experiment_id="experiment-1",
        display_name="Experiment One",
        kind=experiment_pb2.EXPERIMENT_KIND_SCIENTIFIC,
        intent_manifest=artifact("a"),
        subjects=[reference("dataset", f"{PARENT}/datasets/dataset-1")],
        use_policy=reference("use_policy", f"{PARENT}/policies/policy-1"),
        policy_classification="internal",
    )
    update = experiment_commands_pb2.UpdateExperimentCommand(
        experiment=experiment_pb2.Experiment(
            name=EXPERIMENT,
            revision=1,
            etag=digest("e"),
            display_name="Renamed",
        ),
        update_mask=FieldMask(paths=["display_name"]),
        etag=digest("e"),
    )
    transition_experiment = experiment_commands_pb2.TransitionExperimentCommand(
        experiment=reference("experiment", EXPERIMENT),
        expected_state=experiment_pb2.EXPERIMENT_STATE_DRAFT,
        target_state=experiment_pb2.EXPERIMENT_STATE_ACTIVE,
        etag=digest("e"),
        reason_code="INTENT_APPROVED",
    )
    create_study = experiment_commands_pb2.CreateStudyCommand(
        experiment=reference("experiment", EXPERIMENT),
        study_id="study-1",
        type=study_pb2.STUDY_TYPE_SCIENTIFIC,
        study_manifest=artifact("b"),
        base_configuration=artifact("c"),
        search_space=artifact("d"),
        objective_specification=artifact("f"),
        budget=study_pb2.StudyBudget(
            maximum_trials=8,
            maximum_parallel_trials=2,
            maximum_duration=Duration(seconds=3600),
        ),
    )
    transition_study = experiment_commands_pb2.TransitionStudyCommand(
        study=reference("study", STUDY),
        expected_state=study_pb2.STUDY_STATE_CREATED,
        target_state=study_pb2.STUDY_STATE_RUNNING,
        etag=digest("e"),
        reason_code="ADMISSION_OPEN",
    )
    create_trial = experiment_commands_pb2.CreateTrialCommand(
        study=reference("study", STUDY),
        trial_id="trial-1",
        trial_number=1,
        resolved_configuration=artifact("1"),
    )
    transition_trial = experiment_commands_pb2.TransitionTrialCommand(
        trial=reference("trial", TRIAL),
        expected_state=trial_pb2.TRIAL_STATE_CREATED,
        target_state=trial_pb2.TRIAL_STATE_ADMITTED,
        etag=digest("e"),
        reason_code="CAPACITY_GRANTED",
    )
    complete = experiment_commands_pb2.CompleteTrialCommand(
        trial=reference("trial", TRIAL),
        outcome=trial_pb2.TRIAL_OUTCOME_SUCCEEDED,
        result_manifest=artifact("2"),
        etag=digest("e"),
    )
    return (
        create,
        update,
        transition_experiment,
        create_study,
        transition_study,
        create_trial,
        transition_trial,
        complete,
    )


def exercise_sync(facade: Experiments) -> None:
    (
        create,
        update,
        exp_transition,
        create_study,
        study_transition,
        create_trial,
        trial_transition,
        complete,
    ) = commands()
    original = copy.deepcopy(create)
    assert facade.create(create, options=CallOptions(idempotency_key="create")).name == EXPERIMENT
    assert create == original
    assert facade.get(EXPERIMENT).name == EXPERIMENT
    assert facade.list().page.next_page_token == "next"
    assert facade.update(update, options=CallOptions(idempotency_key="update")).name == EXPERIMENT
    assert (
        facade.transition(exp_transition, options=CallOptions(idempotency_key="transition")).name
        == EXPERIMENT
    )
    assert (
        facade.create_study(create_study, options=CallOptions(idempotency_key="study-create")).name
        == STUDY
    )
    assert facade.get_study(STUDY).name == STUDY
    assert (
        facade.list_studies(
            experiment_service_pb2.ListStudiesRequest(parent=EXPERIMENT)
        ).page.next_page_token
        == "next"
    )
    assert (
        facade.transition_study(
            study_transition, options=CallOptions(idempotency_key="study-transition")
        ).name
        == STUDY
    )
    assert (
        facade.create_trial(create_trial, options=CallOptions(idempotency_key="trial-create")).name
        == TRIAL
    )
    assert facade.get_trial(TRIAL).name == TRIAL
    assert (
        facade.list_trials(
            experiment_service_pb2.ListTrialsRequest(parent=STUDY)
        ).page.next_page_token
        == "next"
    )
    assert (
        facade.transition_trial(
            trial_transition, options=CallOptions(idempotency_key="trial-transition")
        ).name
        == TRIAL
    )
    assert (
        facade.complete_trial(complete, options=CallOptions(idempotency_key="trial-complete")).name
        == TRIAL
    )


async def exercise_async(facade: AsyncExperiments) -> None:
    (
        create,
        update,
        exp_transition,
        create_study,
        study_transition,
        create_trial,
        trial_transition,
        complete,
    ) = commands()
    assert (
        await facade.create(create, options=CallOptions(idempotency_key="create"))
    ).name == EXPERIMENT
    assert (await facade.get(EXPERIMENT)).name == EXPERIMENT
    assert (await facade.list()).page.next_page_token == "next"
    assert (
        await facade.update(update, options=CallOptions(idempotency_key="update"))
    ).name == EXPERIMENT
    assert (
        await facade.transition(exp_transition, options=CallOptions(idempotency_key="transition"))
    ).name == EXPERIMENT
    assert (
        await facade.create_study(create_study, options=CallOptions(idempotency_key="study-create"))
    ).name == STUDY
    assert (await facade.get_study(STUDY)).name == STUDY
    assert (
        await facade.list_studies(experiment_service_pb2.ListStudiesRequest(parent=EXPERIMENT))
    ).page.next_page_token == "next"
    assert (
        await facade.transition_study(
            study_transition, options=CallOptions(idempotency_key="study-transition")
        )
    ).name == STUDY
    assert (
        await facade.create_trial(create_trial, options=CallOptions(idempotency_key="trial-create"))
    ).name == TRIAL
    assert (await facade.get_trial(TRIAL)).name == TRIAL
    assert (
        await facade.list_trials(experiment_service_pb2.ListTrialsRequest(parent=STUDY))
    ).page.next_page_token == "next"
    assert (
        await facade.transition_trial(
            trial_transition, options=CallOptions(idempotency_key="trial-transition")
        )
    ).name == TRIAL
    assert (
        await facade.complete_trial(complete, options=CallOptions(idempotency_key="trial-complete"))
    ).name == TRIAL


class ExperimentFacadeTest(unittest.TestCase):
    def test_all_generated_routes_scope_digest_deadline_and_clone_safety(self) -> None:
        transport = FakeSyncTransport()
        captured: list[Message] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 2)
            self.assertIn("x-request-id", dict(metadata))
            self.assertNotIn("x-mindclade-request-id", dict(metadata))
            captured.append(copy.deepcopy(request))
            return response(request)

        for route in ROUTES:
            transport.unary_handlers[route] = handler
        exercise_sync(Experiments(SyncInvoker(config(), transport)))
        self.assertEqual([call.method for call in transport.calls], list(ROUTES))
        self.assertEqual(len(captured), 14)
        for request in captured:
            command = getattr(request, "command", None)
            if command is None:
                continue
            self.assertEqual(command.context.tenant_id, "tenant-1")
            self.assertEqual(command.context.project_id, "project-1")
            self.assertEqual(command.context.principal_id, "principal-1")
            canonical = copy.deepcopy(command)
            canonical.ClearField("context")
            self.assertEqual(command.context.canonical_request_digest, canonical_digest(canonical))

    def test_rejects_scope_page_and_retry_identity_violations_before_transport(self) -> None:
        facade = Experiments(SyncInvoker(config(), FakeSyncTransport()))
        with self.assertRaisesRegex(ValueError, "configured project"):
            facade.get("tenants/other/projects/other/experiments/nope")
        with self.assertRaisesRegex(ValueError, "page size"):
            facade.list(
                experiment_service_pb2.ListExperimentsRequest(
                    page=pagination_pb2.PageRequest(page_size=201)
                )
            )
        create = commands()[0]
        create.context.idempotency_key = "intent-key"
        with self.assertRaisesRegex(ValueError, "idempotency"):
            facade.create(create, options=CallOptions(idempotency_key="different-key"))

    def test_async_facade_uses_the_same_authoritative_routes(self) -> None:
        transport = FakeAsyncTransport()

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            self.assertGreater(timeout, 0)
            self.assertIn("x-request-id", dict(metadata))
            self.assertNotIn("x-mindclade-request-id", dict(metadata))
            return response(request)

        for route in ROUTES:
            transport.unary_handlers[route] = handler
        asyncio.run(exercise_async(AsyncExperiments(AsyncInvoker(config(), transport))))
        self.assertEqual([call.method for call in transport.calls], list(ROUTES))


if __name__ == "__main__":
    unittest.main()
