from __future__ import annotations

import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.admin.v1 import audit_query_pb2
from mindclade.common.v1 import pagination_pb2
from mindclade.internal.admin.v1 import admin_service_pb2
from mindclade.internal.agent.v1 import agent_service_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.internal.dataset.v1 import dataset_service_pb2
from mindclade.internal.evaluation.v1 import evaluation_service_pb2
from mindclade.internal.experiment.v1 import experiment_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.internal.model.v1 import model_service_pb2
from mindclade.internal.policy.v1 import policy_service_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.internal.workflow.v1 import workflow_service_pb2
from mindclade.job.v1 import job_pb2
from mindclade_internal_sdk import (
    AsyncClient,
    AsyncPage,
    Client,
    ClientConfig,
    Environment,
    Page,
    PaginationLimitError,
    PaginationLimits,
    ProtocolError,
)
from mindclade_internal_sdk.agents import (
    LIST_AGENT_DEFINITIONS,
    LIST_AGENT_RUNS,
    LIST_AGENT_STEPS,
)
from mindclade_internal_sdk.pagination import (
    PageBudget,
    apply_default_page_size,
    checked_next_token,
    next_request,
)
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    LIST_APPROVAL_REQUESTS,
    LIST_ARTIFACTS,
    LIST_ATTEMPTS,
    LIST_CHECKPOINTS,
    LIST_DATASET_RELEASES,
    LIST_DATASETS,
    LIST_EVALUATION_RUNS,
    LIST_EXPERIMENTS,
    LIST_JOBS,
    LIST_MODEL_RELEASES,
    LIST_MODELS,
    LIST_OPERATIONS,
    LIST_PROJECTS,
    LIST_RUNS,
    LIST_STUDIES,
    LIST_TRAINING_RUNS,
    LIST_TRIALS,
    LIST_USE_POLICIES,
    LIST_WORKFLOW_DEFINITIONS,
    LIST_WORKFLOW_RUNS,
    QUERY_AUDIT_RECORDS,
    Metadata,
)

TENANT = "tenants/tenant-1"
PARENT = f"{TENANT}/projects/project-1"
AGENT_RUN = f"{PARENT}/agentRuns/run-1"
DATASET = f"{PARENT}/datasets/dataset-1"
EXPERIMENT = f"{PARENT}/experiments/experiment-1"
MODEL = f"{PARENT}/models/model-1"
STUDY = f"{EXPERIMENT}/studies/study-1"
TRAINING_RUN = f"{PARENT}/trainingRuns/run-1"


def config() -> ClientConfig:
    return ClientConfig(
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        insecure_for_testing=True,
    )


def job(index: int, *, project_id: str = "project-1") -> job_pb2.Job:
    """Build one job that satisfies every list-response identity check."""

    return job_pb2.Job(
        job_id=f"jobs/job-{index}",
        operation_id=f"operations/op-{index}",
        tenant_id="tenant-1",
        project_id=project_id,
        state=job_pb2.JOB_STATE_RUNNING,
        resource_version=1,
        etag=f"etag-{index}",
    )


def job_page(jobs: list[job_pb2.Job], next_page_token: str) -> job_service_pb2.ListJobsResponse:
    return job_service_pb2.ListJobsResponse(
        jobs=jobs,
        page=pagination_pb2.PageResponse(next_page_token=next_page_token),
    )


def scripted_jobs(
    pages: dict[str, job_service_pb2.ListJobsResponse],
    requests: list[job_service_pb2.ListJobsRequest],
) -> Callable[[Message, float, Metadata], Message]:
    """Serve a scripted ListJobs script keyed by the opaque cursor it receives."""

    def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
        del timeout, metadata
        assert isinstance(request, job_service_pb2.ListJobsRequest)
        materialized = job_service_pb2.ListJobsRequest()
        materialized.CopyFrom(request)
        requests.append(materialized)
        return pages[request.page.page_token]

    return handler


def three_pages() -> dict[str, job_service_pb2.ListJobsResponse]:
    return {
        "": job_page([job(1), job(2)], "cursor-1"),
        "cursor-1": job_page([job(3), job(4)], "cursor-2"),
        "cursor-2": job_page([job(5), job(6)], ""),
    }


def sync_jobs_client(
    pages: dict[str, job_service_pb2.ListJobsResponse],
) -> tuple[Client, list[job_service_pb2.ListJobsRequest], FakeSyncTransport]:
    requests: list[job_service_pb2.ListJobsRequest] = []
    transport = FakeSyncTransport()
    transport.unary_handlers[LIST_JOBS] = scripted_jobs(pages, requests)
    client = Client(config(), transport=transport, close_transport=False)
    return client, requests, transport


def async_jobs_client(
    pages: dict[str, job_service_pb2.ListJobsResponse],
) -> tuple[AsyncClient, list[job_service_pb2.ListJobsRequest], FakeAsyncTransport]:
    requests: list[job_service_pb2.ListJobsRequest] = []
    transport = FakeAsyncTransport()
    transport.unary_handlers[LIST_JOBS] = scripted_jobs(pages, requests)
    client = AsyncClient(config(), transport=transport, close_transport=False)
    return client, requests, transport


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def audit_query() -> audit_query_pb2.AuditQuery:
    now = datetime.now(UTC)
    return audit_query_pb2.AuditQuery(
        parent=PARENT,
        start_time=timestamp(now - timedelta(hours=1)),
        end_time=timestamp(now),
    )


EMPTY_LIST_RESPONSES: dict[str, Message] = {
    LIST_PROJECTS: admin_service_pb2.ListProjectsResponse(),
    QUERY_AUDIT_RECORDS: admin_service_pb2.QueryAuditRecordsResponse(
        result=audit_query_pb2.AuditQueryPage()
    ),
    LIST_AGENT_DEFINITIONS: agent_service_pb2.ListAgentDefinitionsResponse(),
    LIST_AGENT_RUNS: agent_service_pb2.ListAgentRunsResponse(),
    LIST_AGENT_STEPS: agent_service_pb2.ListAgentStepsResponse(),
    LIST_ARTIFACTS: artifact_service_pb2.ListArtifactsResponse(),
    LIST_DATASETS: dataset_service_pb2.ListDatasetsResponse(),
    LIST_DATASET_RELEASES: dataset_service_pb2.ListDatasetReleasesResponse(),
    LIST_EVALUATION_RUNS: evaluation_service_pb2.ListEvaluationRunsResponse(),
    LIST_EXPERIMENTS: experiment_service_pb2.ListExperimentsResponse(),
    LIST_STUDIES: experiment_service_pb2.ListStudiesResponse(),
    LIST_TRIALS: experiment_service_pb2.ListTrialsResponse(),
    LIST_JOBS: job_service_pb2.ListJobsResponse(),
    LIST_MODELS: model_service_pb2.ListModelsResponse(),
    LIST_MODEL_RELEASES: model_service_pb2.ListModelReleasesResponse(),
    LIST_OPERATIONS: job_service_pb2.ListOperationsResponse(),
    LIST_USE_POLICIES: policy_service_pb2.ListUsePoliciesResponse(),
    LIST_RUNS: job_service_pb2.ListRunsResponse(),
    LIST_ATTEMPTS: job_service_pb2.ListAttemptsResponse(),
    LIST_TRAINING_RUNS: training_service_pb2.ListTrainingRunsResponse(),
    LIST_CHECKPOINTS: training_service_pb2.ListCheckpointsResponse(),
    LIST_WORKFLOW_DEFINITIONS: workflow_service_pb2.ListWorkflowDefinitionsResponse(),
    LIST_WORKFLOW_RUNS: workflow_service_pb2.ListWorkflowRunsResponse(),
    LIST_APPROVAL_REQUESTS: workflow_service_pb2.ListApprovalRequestsResponse(),
}


def empty_handler(response: Message) -> Callable[[Message, float, Metadata], Message]:
    def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
        del request, timeout, metadata
        return response

    return handler


def install_empty_handlers(transport: FakeSyncTransport | FakeAsyncTransport) -> None:
    for method, response in EMPTY_LIST_RESPONSES.items():
        transport.unary_handlers[method] = empty_handler(response)


def sync_list_calls(client: Client) -> dict[str, object]:
    """Invoke every ergonomic synchronous list method exactly once."""

    return {
        "admin.list_projects": client.admin.list_projects(),
        "admin.query_audit": client.admin.query_audit(audit_query()),
        "agents.list_definitions": client.agents.list_definitions(),
        "agents.list_runs": client.agents.list_runs(),
        "agents.list_steps": client.agents.list_steps(
            agent_service_pb2.ListAgentStepsRequest(parent=AGENT_RUN)
        ),
        "artifacts.list": client.artifacts.list(),
        "datasets.list": client.datasets.list(),
        "datasets.list_releases": client.datasets.list_releases(
            dataset_service_pb2.ListDatasetReleasesRequest(parent=DATASET)
        ),
        "evaluations.list_runs": client.evaluations.list_runs(),
        "experiments.list": client.experiments.list(),
        "experiments.list_studies": client.experiments.list_studies(
            experiment_service_pb2.ListStudiesRequest(parent=EXPERIMENT)
        ),
        "experiments.list_trials": client.experiments.list_trials(
            experiment_service_pb2.ListTrialsRequest(parent=STUDY)
        ),
        "jobs.list": client.jobs.list(),
        "models.list": client.models.list(),
        "models.list_releases": client.models.list_releases(
            model_service_pb2.ListModelReleasesRequest(parent=MODEL)
        ),
        "operations.list": client.operations.list(),
        "policies.list": client.policies.list(),
        "runs.list_runs": client.runs.list_runs(job_service_pb2.ListRunsRequest(parent="job-1")),
        "runs.list_attempts": client.runs.list_attempts(
            job_service_pb2.ListAttemptsRequest(parent="run-1")
        ),
        "training.list_runs": client.training.list_runs(),
        "training.list_checkpoints": client.training.list_checkpoints(
            training_service_pb2.ListCheckpointsRequest(parent=TRAINING_RUN)
        ),
        "workflows.list_definitions": client.workflows.list_definitions(),
        "workflows.list_runs": client.workflows.list_runs(),
        "approvals.list": client.approvals.list(),
    }


async def async_list_calls(client: AsyncClient) -> dict[str, object]:
    """Invoke every ergonomic asynchronous list method exactly once."""

    return {
        "admin.list_projects": await client.admin.list_projects(),
        "admin.query_audit": await client.admin.query_audit(audit_query()),
        "agents.list_definitions": await client.agents.list_definitions(),
        "agents.list_runs": await client.agents.list_runs(),
        "agents.list_steps": await client.agents.list_steps(
            agent_service_pb2.ListAgentStepsRequest(parent=AGENT_RUN)
        ),
        "artifacts.list": await client.artifacts.list(),
        "datasets.list": await client.datasets.list(),
        "datasets.list_releases": await client.datasets.list_releases(
            dataset_service_pb2.ListDatasetReleasesRequest(parent=DATASET)
        ),
        "evaluations.list_runs": await client.evaluations.list_runs(),
        "experiments.list": await client.experiments.list(),
        "experiments.list_studies": await client.experiments.list_studies(
            experiment_service_pb2.ListStudiesRequest(parent=EXPERIMENT)
        ),
        "experiments.list_trials": await client.experiments.list_trials(
            experiment_service_pb2.ListTrialsRequest(parent=STUDY)
        ),
        "jobs.list": await client.jobs.list(),
        "models.list": await client.models.list(),
        "models.list_releases": await client.models.list_releases(
            model_service_pb2.ListModelReleasesRequest(parent=MODEL)
        ),
        "operations.list": await client.operations.list(),
        "policies.list": await client.policies.list(),
        "runs.list_runs": await client.runs.list_runs(
            job_service_pb2.ListRunsRequest(parent="job-1")
        ),
        "runs.list_attempts": await client.runs.list_attempts(
            job_service_pb2.ListAttemptsRequest(parent="run-1")
        ),
        "training.list_runs": await client.training.list_runs(),
        "training.list_checkpoints": await client.training.list_checkpoints(
            training_service_pb2.ListCheckpointsRequest(parent=TRAINING_RUN)
        ),
        "workflows.list_definitions": await client.workflows.list_definitions(),
        "workflows.list_runs": await client.workflows.list_runs(),
        "approvals.list": await client.approvals.list(),
    }


class PageBudgetTest(unittest.TestCase):
    def test_limits_reject_values_outside_their_hard_caps(self) -> None:
        for kwargs in (
            {"max_pages": 0},
            {"max_pages": 1_001},
            {"max_items": 0},
            {"max_items": 1_000_001},
            {"page_size": 0},
            {"page_size": 1_001},
            {"max_items": 10.0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PaginationLimits(**kwargs)  # type: ignore[arg-type]

    def test_declared_defaults_match_the_cross_language_contract(self) -> None:
        limits = PaginationLimits()
        self.assertEqual((limits.page_size, limits.max_items), (100, 10_000))
        self.assertEqual(limits.max_pages, 100)

    def test_budget_advances_and_fails_closed(self) -> None:
        budget = PageBudget(PaginationLimits(max_pages=2, max_items=3))
        advanced = budget.advanced(2)
        self.assertEqual((advanced.pages_read, advanced.items_read), (2, 2))
        advanced.check()
        with self.assertRaises(PaginationLimitError):
            advanced.advanced(2).check()

    def test_non_text_cursor_is_a_protocol_error(self) -> None:
        with self.assertRaises(ProtocolError):
            checked_next_token(7, frozenset())

    def test_repeated_cursor_is_a_protocol_error(self) -> None:
        with self.assertRaises(ProtocolError):
            checked_next_token("cursor-1", frozenset({"cursor-1"}))

    def test_next_request_forwards_the_cursor_verbatim(self) -> None:
        original = job_service_pb2.ListJobsRequest(parent=PARENT)
        follow = next_request(original, "opaque cursor/=+")
        self.assertEqual(follow.page.page_token, "opaque cursor/=+")
        self.assertEqual(follow.parent, PARENT)
        self.assertEqual(original.page.page_token, "")

    def test_default_page_size_only_fills_an_unset_request(self) -> None:
        unset = job_service_pb2.ListJobsRequest()
        apply_default_page_size(unset, None)
        self.assertEqual(unset.page.page_size, 100)
        explicit = job_service_pb2.ListJobsRequest(
            page=pagination_pb2.PageRequest(page_size=25),
        )
        apply_default_page_size(explicit, PaginationLimits(page_size=50))
        self.assertEqual(explicit.page.page_size, 25)


class SyncPaginationTest(unittest.TestCase):
    def test_page_iterates_transparently_across_pages(self) -> None:
        client, requests, transport = sync_jobs_client(three_pages())
        page = client.jobs.list()
        self.assertIsInstance(page, Page)
        self.assertEqual(
            [item.job_id for item in page],
            [f"jobs/job-{index}" for index in range(1, 7)],
        )
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            [value.page.page_token for value in requests], ["", "cursor-1", "cursor-2"]
        )

    def test_page_keeps_page_level_access(self) -> None:
        client, _, _ = sync_jobs_client(three_pages())
        first = client.jobs.list()
        self.assertTrue(first.has_next_page)
        self.assertEqual(len(first), 2)
        second = first.next_page()
        self.assertEqual([item.job_id for item in second.items], ["jobs/job-3", "jobs/job-4"])
        third = second.next_page()
        self.assertFalse(third.has_next_page)
        with self.assertRaises(ValueError):
            third.next_page()
        self.assertEqual(len(list(first.pages())), 3)

    def test_page_delegates_generated_fields_for_compatibility(self) -> None:
        client, _, _ = sync_jobs_client(three_pages())
        page = client.jobs.list()
        self.assertEqual(page.page.next_page_token, "cursor-1")
        self.assertEqual([value.job_id for value in page.jobs], ["jobs/job-1", "jobs/job-2"])
        self.assertIs(page.response, page.response)
        with self.assertRaises(AttributeError):
            page.not_a_generated_field  # noqa: B018

    def test_opaque_token_is_forwarded_verbatim(self) -> None:
        pages = {
            "": job_page([job(1)], "opaque cursor/=+"),
            "opaque cursor/=+": job_page([job(2)], ""),
        }
        client, requests, _ = sync_jobs_client(pages)
        self.assertEqual(len(list(client.jobs.list())), 2)
        self.assertEqual(requests[1].page.page_token, "opaque cursor/=+")

    def test_repeated_cursor_raises_protocol_error(self) -> None:
        pages = {"": job_page([job(1)], "loop"), "loop": job_page([job(2)], "loop")}
        client, _, _ = sync_jobs_client(pages)
        with self.assertRaises(ProtocolError):
            list(client.jobs.list())

    def test_item_budget_stops_the_traversal(self) -> None:
        client, _, _ = sync_jobs_client(three_pages())
        page = client.jobs.list(limits=PaginationLimits(max_items=3))
        collected: list[str] = []
        with self.assertRaises(PaginationLimitError):
            for item in page:
                collected.append(item.job_id)
        self.assertEqual(collected, ["jobs/job-1", "jobs/job-2", "jobs/job-3"])

    def test_page_budget_stops_the_traversal(self) -> None:
        client, _, _ = sync_jobs_client(three_pages())
        page = client.jobs.list(limits=PaginationLimits(max_pages=2))
        with self.assertRaises(PaginationLimitError):
            list(page)

    def test_per_item_validation_runs_on_every_page(self) -> None:
        pages = {
            "": job_page([job(1)], "cursor-1"),
            "cursor-1": job_page([job(2, project_id="project-elsewhere")], ""),
        }
        client, _, _ = sync_jobs_client(pages)
        with self.assertRaises(ProtocolError):
            list(client.jobs.list())

    def test_default_page_size_reaches_the_server(self) -> None:
        client, requests, _ = sync_jobs_client({"": job_page([], "")})
        client.jobs.list()
        self.assertEqual(requests[0].page.page_size, 100)

    def test_every_list_method_returns_a_page(self) -> None:
        transport = FakeSyncTransport()
        install_empty_handlers(transport)
        client = Client(config(), transport=transport, close_transport=False)
        results = sync_list_calls(client)
        self.assertEqual(len(results), 24)
        for label, value in results.items():
            with self.subTest(method=label):
                self.assertIsInstance(value, Page)
                self.assertFalse(value.has_next_page)  # type: ignore[union-attr]
                self.assertEqual(list(value), [])  # type: ignore[call-overload]


class AsyncPaginationTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_page_iterates_transparently_across_pages(self) -> None:
        client, requests, transport = async_jobs_client(three_pages())
        page = await client.jobs.list()
        self.assertIsInstance(page, AsyncPage)
        collected = [item.job_id async for item in page]
        self.assertEqual(collected, [f"jobs/job-{index}" for index in range(1, 7)])
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            [value.page.page_token for value in requests], ["", "cursor-1", "cursor-2"]
        )

    async def test_async_page_keeps_page_level_access(self) -> None:
        client, _, _ = async_jobs_client(three_pages())
        first = await client.jobs.list()
        self.assertTrue(first.has_next_page)
        self.assertEqual(first.page.next_page_token, "cursor-1")
        second = await first.next_page()
        self.assertEqual([item.job_id for item in second.items], ["jobs/job-3", "jobs/job-4"])
        walked = [page.next_page_token async for page in first.pages()]
        self.assertEqual(walked, ["cursor-1", "cursor-2", ""])

    async def test_async_item_budget_stops_the_traversal(self) -> None:
        client, _, _ = async_jobs_client(three_pages())
        page = await client.jobs.list(limits=PaginationLimits(max_items=3))
        collected: list[str] = []
        with self.assertRaises(PaginationLimitError):
            async for item in page:
                collected.append(item.job_id)
        self.assertEqual(collected, ["jobs/job-1", "jobs/job-2", "jobs/job-3"])

    async def test_async_repeated_cursor_raises_protocol_error(self) -> None:
        pages = {"": job_page([job(1)], "loop"), "loop": job_page([job(2)], "loop")}
        client, _, _ = async_jobs_client(pages)
        page = await client.jobs.list()
        with self.assertRaises(ProtocolError):
            await page.next_page()

    async def test_every_async_list_method_returns_a_page(self) -> None:
        transport = FakeAsyncTransport()
        install_empty_handlers(transport)
        client = AsyncClient(config(), transport=transport, close_transport=False)
        results = await async_list_calls(client)
        self.assertEqual(len(results), 24)
        for label, value in results.items():
            with self.subTest(method=label):
                self.assertIsInstance(value, AsyncPage)


if __name__ == "__main__":
    unittest.main()
