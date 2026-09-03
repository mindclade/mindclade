from __future__ import annotations

import copy
import hashlib
import pickle
import unittest
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from google.protobuf.duration_pb2 import Duration
from google.protobuf.field_mask_pb2 import FieldMask
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import command_context_pb2, pagination_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import (
    attempt_pb2,
    job_commands_pb2,
    job_pb2,
    lease_fencing_pb2,
    operation_pb2,
    run_pb2,
)
from mindclade_internal_sdk import (
    AccessToken,
    AsyncClient,
    AttemptLease,
    CallOptions,
    Client,
    ClientConfig,
    LeaseCredential,
)
from mindclade_internal_sdk._invocation import canonical_digest
from mindclade_internal_sdk.config import RetryPolicy
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    ACQUIRE_ATTEMPT_LEASE,
    CANCEL_ATTEMPT,
    CANCEL_JOB,
    COMMIT_ATTEMPT,
    GET_ATTEMPT,
    GET_JOB,
    GET_RUN,
    HEARTBEAT_ATTEMPT,
    LIST_ATTEMPTS,
    LIST_JOBS,
    LIST_RUNS,
    RENEW_ATTEMPT_LEASE,
    REQUEST_JOB,
    Metadata,
)

_TOKEN = "lease-token-" + "s" * 40


class _SyncCredentials:
    def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken("test-token", datetime.now(UTC) + timedelta(minutes=5))


class _AsyncCredentials:
    async def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        return AccessToken("test-token", datetime.now(UTC) + timedelta(minutes=5))


def _config(*, asynchronous: bool) -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        token_provider=_AsyncCredentials() if asynchronous else _SyncCredentials(),
        retry=RetryPolicy(max_attempts=1, base_delay=0.001, max_delay=0.001),
    )


def _timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def _duration() -> Duration:
    result = Duration()
    result.FromTimedelta(timedelta(minutes=2))
    return result


def _artifact() -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + "a" * 64,
        media_type="application/json",
        size_bytes=12,
    )


def _fixtures() -> tuple[
    job_pb2.Job,
    operation_pb2.Operation,
    run_pb2.Run,
    attempt_pb2.Attempt,
    lease_fencing_pb2.LeaseFence,
]:
    job = job_pb2.Job(
        job_id="jobs/job-1",
        operation_id="operations/op-1",
        tenant_id="tenant-1",
        project_id="project-1",
        state=job_pb2.JOB_STATE_RUNNING,
        resource_version=1,
        etag="job-etag-1",
    )
    operation = operation_pb2.Operation(
        operation_id=job.operation_id,
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        state=operation_pb2.OPERATION_STATE_RUNNING,
        resource_version=1,
        etag="operation-etag-1",
    )
    run = run_pb2.Run(
        run_id="runs/run-1",
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        state=run_pb2.RUN_STATE_EXECUTING,
        resource_version=1,
        lease_epoch=1,
        etag="run-etag-1",
    )
    attempt = attempt_pb2.Attempt(
        attempt_id="attempts/attempt-1",
        run_id=run.run_id,
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        state=attempt_pb2.ATTEMPT_STATE_RUNNING,
        resource_version=1,
        lease_epoch=1,
        worker_id="workers/worker-1",
        lease_expires_at=_timestamp(datetime.now(UTC) + timedelta(hours=1)),
    )
    fence = lease_fencing_pb2.LeaseFence(
        job_id=job.job_id,
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        lease_epoch=attempt.lease_epoch,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        deadline=_timestamp(datetime.now(UTC) + timedelta(hours=1)),
        lease_token_digest="sha256:" + hashlib.sha256(_TOKEN.encode()).hexdigest(),
    )
    return job, operation, run, attempt, fence


type _Seen = list[tuple[str, Message, Metadata]]


class _ContextMessage(Protocol):
    context: command_context_pb2.CommandContext


def _handlers(seen: _Seen):
    job, operation, run, attempt, fence = _fixtures()
    responses: dict[str, Message] = {
        REQUEST_JOB: job_service_pb2.RequestJobResponse(job=job, operation=operation),
        GET_JOB: job_service_pb2.GetJobResponse(job=job),
        LIST_JOBS: job_service_pb2.ListJobsResponse(
            jobs=[job], page=pagination_pb2.PageResponse(next_page_token="jobs-next")
        ),
        CANCEL_JOB: job_service_pb2.CancelJobResponse(operation=operation),
        GET_RUN: job_service_pb2.GetRunResponse(run=run),
        LIST_RUNS: job_service_pb2.ListRunsResponse(
            runs=[run], page=pagination_pb2.PageResponse(next_page_token="runs-next")
        ),
        GET_ATTEMPT: job_service_pb2.GetAttemptResponse(attempt=attempt),
        LIST_ATTEMPTS: job_service_pb2.ListAttemptsResponse(
            attempts=[attempt], page=pagination_pb2.PageResponse(next_page_token="attempts-next")
        ),
        ACQUIRE_ATTEMPT_LEASE: job_service_pb2.AcquireAttemptLeaseResponse(
            attempt=attempt, fence=fence
        ),
        RENEW_ATTEMPT_LEASE: job_service_pb2.RenewAttemptLeaseResponse(
            attempt=attempt, fence=fence
        ),
        HEARTBEAT_ATTEMPT: job_service_pb2.HeartbeatAttemptResponse(
            attempt=attempt,
            fence=fence,
            observed_at=_timestamp(datetime.now(UTC)),
        ),
        CANCEL_ATTEMPT: job_service_pb2.CancelAttemptResponse(attempt=attempt, run=run),
        COMMIT_ATTEMPT: job_service_pb2.CommitAttemptResponse(attempt=attempt, run=run),
    }

    def handler(method: str):
        def invoke(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            seen.append((method, copy.deepcopy(request), metadata))
            return copy.deepcopy(responses[method])

        return invoke

    return {method: handler(method) for method in responses}


def _requests() -> tuple[
    job_commands_pb2.RequestJobCommand,
    job_service_pb2.CancelJobRequest,
    job_service_pb2.AcquireAttemptLeaseRequest,
]:
    command = job_commands_pb2.RequestJobCommand(
        job_kind="training",
        configuration=_artifact(),
        requested_job_id="job-1",
    )
    command.context.tenant_id = "forged"
    cancel = job_service_pb2.CancelJobRequest(
        name="job-1", etag="job-etag-1", reason="requested by test"
    )
    acquire = job_service_pb2.AcquireAttemptLeaseRequest(
        run_name="run-1", attempt_id="attempt-1", lease_duration=_duration()
    )
    return command, cancel, acquire


def _fenced_requests(
    lease: AttemptLease,
) -> tuple[
    job_service_pb2.RenewAttemptLeaseRequest,
    job_service_pb2.HeartbeatAttemptRequest,
    job_service_pb2.CancelAttemptRequest,
    job_service_pb2.CommitAttemptRequest,
]:
    fence = lease.fence
    attempt = lease.attempt
    renew = job_service_pb2.RenewAttemptLeaseRequest(
        fence=fence, lease_duration=_duration(), expected_resource_version=1
    )
    heartbeat = job_service_pb2.HeartbeatAttemptRequest(
        fence=fence, lease_duration=_duration(), expected_resource_version=1
    )
    cancel = job_service_pb2.CancelAttemptRequest(
        fence=fence, expected_resource_version=1, reason="worker shutdown"
    )
    attempt.state = attempt_pb2.ATTEMPT_STATE_SUCCEEDED
    commit = job_service_pb2.CommitAttemptRequest(
        attempt=attempt,
        fence=fence,
        update_mask=FieldMask(paths=["state"]),
        expected_resource_version=1,
    )
    return renew, heartbeat, cancel, commit


def _assert_calls(test: unittest.TestCase, seen: _Seen) -> None:
    test.assertEqual(
        [method for method, _, _ in seen],
        [
            REQUEST_JOB,
            GET_JOB,
            LIST_JOBS,
            CANCEL_JOB,
            GET_RUN,
            LIST_RUNS,
            GET_ATTEMPT,
            LIST_ATTEMPTS,
            ACQUIRE_ATTEMPT_LEASE,
            RENEW_ATTEMPT_LEASE,
            HEARTBEAT_ATTEMPT,
            CANCEL_ATTEMPT,
            COMMIT_ATTEMPT,
        ],
    )
    fenced = {
        RENEW_ATTEMPT_LEASE,
        HEARTBEAT_ATTEMPT,
        CANCEL_ATTEMPT,
        COMMIT_ATTEMPT,
    }
    mutations = {REQUEST_JOB, CANCEL_JOB, ACQUIRE_ATTEMPT_LEASE, *fenced}
    for method, request, metadata in seen:
        values = dict(metadata)
        test.assertNotIn(_TOKEN, request.SerializeToString().decode("latin1"))
        if method == ACQUIRE_ATTEMPT_LEASE:
            test.assertNotIn("x-mindclade-lease-token", values)
        elif method in fenced:
            test.assertEqual(values.get("x-mindclade-lease-token"), _TOKEN)
        if method in mutations:
            if method == REQUEST_JOB:
                test.assertIsInstance(request, job_service_pb2.RequestJobRequest)
                wrapper = cast(job_service_pb2.RequestJobRequest, request)
                command: Message = copy.deepcopy(wrapper.command)
            else:
                test.assertIsInstance(
                    request,
                    (
                        job_service_pb2.CancelJobRequest,
                        job_service_pb2.AcquireAttemptLeaseRequest,
                        job_service_pb2.RenewAttemptLeaseRequest,
                        job_service_pb2.HeartbeatAttemptRequest,
                        job_service_pb2.CancelAttemptRequest,
                        job_service_pb2.CommitAttemptRequest,
                    ),
                )
                command = copy.deepcopy(request)
            context = command_context_pb2.CommandContext()
            context.CopyFrom(cast(_ContextMessage, command).context)
            clone = copy.deepcopy(command)
            clone.ClearField("context")
            test.assertEqual(context.tenant_id, "tenant-1")
            test.assertEqual(context.project_id, "project-1")
            test.assertEqual(context.principal_id, "principal-1")
            test.assertEqual(context.canonical_request_digest, canonical_digest(clone))
            test.assertEqual(values.get("idempotency-key"), context.idempotency_key)


class JobRunTest(unittest.TestCase):
    def test_sync_facades_cover_every_ergonomic_rpc_and_keep_tokens_out_of_protobuf(self) -> None:
        seen: _Seen = []
        transport = FakeSyncTransport()
        transport.unary_handlers.update(_handlers(seen))
        transport.response_metadata[ACQUIRE_ATTEMPT_LEASE] = (("x-mindclade-lease-token", _TOKEN),)
        client = Client(_config(asynchronous=False), transport=transport, close_transport=False)
        command, cancel_job, acquire = _requests()
        client.jobs.request(command, options=CallOptions(idempotency_key="request-job"))
        client.jobs.get("job-1")
        client.jobs.list(
            job_service_pb2.ListJobsRequest(
                page=pagination_pb2.PageRequest(page_size=25, page_token="job-page")
            )
        )
        client.jobs.cancel(cancel_job, options=CallOptions(idempotency_key="cancel-job"))
        client.runs.get_run("run-1")
        client.runs.list_runs(job_service_pb2.ListRunsRequest(parent="job-1"))
        client.runs.get_attempt("attempt-1")
        client.runs.list_attempts(job_service_pb2.ListAttemptsRequest(parent="run-1"))
        lease = client.runs.acquire_lease(acquire, options=CallOptions(idempotency_key="acquire"))
        self.assertIsInstance(lease.credential, LeaseCredential)
        self.assertEqual(repr(lease.credential), "LeaseCredential(<redacted>)")
        self.assertNotIn(_TOKEN, repr(lease.credential))
        with self.assertRaises(TypeError):
            pickle.dumps(lease.credential)
        mutated = lease.attempt
        mutated.attempt_id = "attempts/tampered"
        self.assertEqual(lease.attempt.attempt_id, "attempts/attempt-1")
        renew, heartbeat, cancel, commit = _fenced_requests(lease)
        client.runs.renew_lease(
            renew, lease.credential, options=CallOptions(idempotency_key="renew")
        )
        client.runs.heartbeat(
            heartbeat, lease.credential, options=CallOptions(idempotency_key="heartbeat")
        )
        client.runs.cancel_attempt(
            cancel, lease.credential, options=CallOptions(idempotency_key="cancel-attempt")
        )
        client.runs.commit_attempt(
            commit, lease.credential, options=CallOptions(idempotency_key="commit")
        )
        self.assertEqual(command.context.tenant_id, "forged")
        self.assertEqual(acquire.run_name, "run-1")
        _assert_calls(self, seen)


class AsyncJobRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_facades_cover_job_and_fenced_attempt_lifecycles(self) -> None:
        seen: _Seen = []
        transport = FakeAsyncTransport()
        transport.unary_handlers.update(_handlers(seen))
        transport.response_metadata[ACQUIRE_ATTEMPT_LEASE] = (("x-mindclade-lease-token", _TOKEN),)
        client = AsyncClient(_config(asynchronous=True), transport=transport, close_transport=False)
        command, cancel_job, acquire = _requests()
        await client.jobs.request(command, options=CallOptions(idempotency_key="request-job"))
        await client.jobs.get("job-1")
        await client.jobs.list(job_service_pb2.ListJobsRequest())
        await client.jobs.cancel(cancel_job, options=CallOptions(idempotency_key="cancel-job"))
        await client.runs.get_run("run-1")
        await client.runs.list_runs(job_service_pb2.ListRunsRequest(parent="job-1"))
        await client.runs.get_attempt("attempt-1")
        await client.runs.list_attempts(job_service_pb2.ListAttemptsRequest(parent="run-1"))
        lease = await client.runs.acquire_lease(
            acquire, options=CallOptions(idempotency_key="acquire")
        )
        renew, heartbeat, cancel, commit = _fenced_requests(lease)
        await client.runs.renew_lease(
            renew, lease.credential, options=CallOptions(idempotency_key="renew")
        )
        await client.runs.heartbeat(
            heartbeat, lease.credential, options=CallOptions(idempotency_key="heartbeat")
        )
        await client.runs.cancel_attempt(
            cancel, lease.credential, options=CallOptions(idempotency_key="cancel-attempt")
        )
        await client.runs.commit_attempt(
            commit, lease.credential, options=CallOptions(idempotency_key="commit")
        )
        _assert_calls(self, seen)


if __name__ == "__main__":
    unittest.main()
