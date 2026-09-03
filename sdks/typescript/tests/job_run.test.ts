import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, test } from "node:test";

import { create, type DescMessage, type MessageShape, toBinary } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { ArtifactRefSchema } from "../../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import {
	AcquireAttemptLeaseRequestSchema,
	CancelAttemptRequestSchema,
	CancelJobRequestSchema,
	CommitAttemptRequestSchema,
	HeartbeatAttemptRequestSchema,
	JobService,
	ListAttemptsRequestSchema,
	ListJobsRequestSchema,
	ListRunsRequestSchema,
	RenewAttemptLeaseRequestSchema,
	RunService,
} from "../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import {
	AttemptSchema,
	AttemptState,
} from "../../../protocols/generated/typescript/job/v1/attempt_pb.js";
import { RequestJobCommandSchema } from "../../../protocols/generated/typescript/job/v1/job_commands_pb.js";
import { JobState } from "../../../protocols/generated/typescript/job/v1/job_pb.js";
import { LeaseFenceSchema } from "../../../protocols/generated/typescript/job/v1/lease_fencing_pb.js";
import { OperationState } from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import { RunState } from "../../../protocols/generated/typescript/job/v1/run_pb.js";
import {
	ClientConfig,
	Environment,
	FakeRuntime,
	LeaseCredential,
	MindcladeClient,
} from "../src/index.js";

const TOKEN = `lease-token-${"s".repeat(40)}`;
const TENANT = "tenant-1";
const PROJECT = "project-1";
const PRINCIPAL = "principal-1";

const testTransport = (routes: Parameters<typeof createRouterTransport>[0]): Transport => {
	const delegate = createRouterTransport(routes);
	return {
		unary(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.unary(method, signal, undefined, header, input, contextValues);
		},
		stream(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.stream(method, signal, undefined, header, input, contextValues);
		},
	};
};

const digest = (value: string): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;

const canonical = <Schema extends DescMessage>(
	schema: Schema,
	value: MessageShape<Schema>,
): string => `sha256:${createHash("sha256").update(toBinary(schema, value)).digest("hex")}`;

const verifyContext = <Schema extends DescMessage>(
	schema: Schema,
	value: MessageShape<Schema> & {
		context?: {
			canonicalRequestDigest: string;
			principalId: string;
			projectId: string;
			tenantId: string;
		};
	},
): void => {
	const clone = create(schema, value) as typeof value;
	const context = clone.context;
	assert.ok(context !== undefined);
	delete clone.context;
	assert.equal(context.canonicalRequestDigest, canonical(schema, clone));
	assert.equal(context.tenantId, TENANT);
	assert.equal(context.projectId, PROJECT);
	assert.equal(context.principalId, PRINCIPAL);
};

describe("JobService and RunService ergonomic facades", () => {
	test("cover every intended RPC while keeping lease credentials metadata-only", async () => {
		const runtime = new FakeRuntime({
			now: 1_800_000_000_000,
			requestIds: Array.from({ length: 32 }, (_, index) => `request-${index}`),
		});
		const deadline = timestampFromDate(new Date(runtime.now + 60 * 60 * 1_000));
		const artifact = create(ArtifactRefSchema, {
			digest: `sha256:${"a".repeat(64)}`,
			mediaType: "application/json",
			sizeBytes: 12n,
		});
		const job = {
			jobId: "jobs/job-1",
			operationId: "operations/op-1",
			projectId: PROJECT,
			resourceVersion: 1n,
			state: JobState.RUNNING,
			tenantId: TENANT,
		};
		const operation = {
			jobId: job.jobId,
			operationId: job.operationId,
			projectId: PROJECT,
			resourceVersion: 1n,
			state: OperationState.RUNNING,
			tenantId: TENANT,
		};
		const run = {
			jobId: job.jobId,
			leaseEpoch: 1n,
			projectId: PROJECT,
			resourceVersion: 1n,
			runId: "runs/run-1",
			state: RunState.EXECUTING,
			tenantId: TENANT,
		};
		const attempt = create(AttemptSchema, {
			attemptId: "attempts/attempt-1",
			jobId: job.jobId,
			leaseEpoch: 1n,
			leaseExpiresAt: deadline,
			projectId: PROJECT,
			resourceVersion: 1n,
			runId: run.runId,
			state: AttemptState.RUNNING,
			tenantId: TENANT,
			workerId: "workers/worker-1",
		});
		const fence = create(LeaseFenceSchema, {
			attemptId: attempt.attemptId,
			deadline,
			jobId: attempt.jobId,
			leaseEpoch: attempt.leaseEpoch,
			leaseTokenDigest: digest(TOKEN),
			projectId: PROJECT,
			runId: attempt.runId,
			tenantId: TENANT,
		});
		const calls: string[] = [];
		const leaseHeaders: Array<string | null> = [];
		const transport = testTransport((router) => {
			router.service(JobService, {
				requestJob(request) {
					calls.push("RequestJob");
					assert.ok(request.command !== undefined);
					verifyContext(RequestJobCommandSchema, request.command);
					return { job, operation };
				},
				getJob(request) {
					calls.push("GetJob");
					assert.equal(request.name, job.jobId);
					return { job };
				},
				listJobs(request) {
					calls.push("ListJobs");
					assert.equal(request.parent, "tenants/tenant-1/projects/project-1");
					return { jobs: [job], page: { nextPageToken: "jobs-next" } };
				},
				cancelJob(request) {
					calls.push("CancelJob");
					verifyContext(CancelJobRequestSchema, request);
					return { operation };
				},
			});
			router.service(RunService, {
				getRun(request) {
					calls.push("GetRun");
					assert.equal(request.name, run.runId);
					return { run };
				},
				listRuns(request) {
					calls.push("ListRuns");
					assert.equal(request.parent, job.jobId);
					return { runs: [run], page: { nextPageToken: "runs-next" } };
				},
				getAttempt(request) {
					calls.push("GetAttempt");
					assert.equal(request.name, attempt.attemptId);
					return { attempt };
				},
				listAttempts(request) {
					calls.push("ListAttempts");
					assert.equal(request.parent, run.runId);
					return { attempts: [attempt], page: { nextPageToken: "attempts-next" } };
				},
				acquireAttemptLease(request, context) {
					calls.push("AcquireAttemptLease");
					verifyContext(AcquireAttemptLeaseRequestSchema, request);
					assert.equal(context.requestHeader.has("x-mindclade-lease-token"), false);
					context.responseHeader.set("x-mindclade-lease-token", TOKEN);
					return { attempt, fence };
				},
				renewAttemptLease(request, context) {
					calls.push("RenewAttemptLease");
					verifyContext(RenewAttemptLeaseRequestSchema, request);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { attempt, fence };
				},
				heartbeatAttempt(request, context) {
					calls.push("HeartbeatAttempt");
					verifyContext(HeartbeatAttemptRequestSchema, request);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { attempt, fence, observedAt: timestampFromDate(new Date(runtime.now)) };
				},
				cancelAttempt(request, context) {
					calls.push("CancelAttempt");
					verifyContext(CancelAttemptRequestSchema, request);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { attempt, run };
				},
				commitAttempt(request, context) {
					calls.push("CommitAttempt");
					verifyContext(CommitAttemptRequestSchema, request);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { attempt, run };
				},
			});
		});
		const config = ClientConfig.create({
			endpoint: "http://127.0.0.1:9443",
			environment: Environment.Local,
			identity: { principalId: PRINCIPAL, projectId: PROJECT, tenantId: TENANT },
			insecureLoopbackForTesting: true,
			retry: { initialBackoffMs: 1, maxAttempts: 1, maxBackoffMs: 1 },
		});
		const client = MindcladeClient.withTransport(config, transport, runtime);
		const command = create(RequestJobCommandSchema, {
			configuration: artifact,
			context: { tenantId: "forged" },
			jobKind: "training",
			requestedJobId: "job-1",
		});
		await client.jobs.request(command, { idempotencyKey: "request-job" });
		await client.jobs.get("job-1");
		await client.jobs.list(create(ListJobsRequestSchema, { page: { pageSize: 25 } }));
		await client.jobs.cancel(
			create(CancelJobRequestSchema, { etag: "job-etag-1", name: "job-1", reason: "test" }),
			{ idempotencyKey: "cancel-job" },
		);
		await client.runs.getRun("run-1");
		await client.runs.listRuns(create(ListRunsRequestSchema, { parent: "job-1" }));
		await client.runs.getAttempt("attempt-1");
		await client.runs.listAttempts(create(ListAttemptsRequestSchema, { parent: "run-1" }));
		const acquisition = create(AcquireAttemptLeaseRequestSchema, {
			attemptId: "attempt-1",
			leaseDuration: { seconds: 120n },
			runName: "run-1",
		});
		const lease = await client.runs.acquire(acquisition, { idempotencyKey: "acquire" });
		assert.ok(lease.credential instanceof LeaseCredential);
		assert.equal(String(lease.credential), "LeaseCredential(<redacted>)");
		assert.doesNotMatch(String(lease.credential), new RegExp(TOKEN));
		const tampered = lease.attempt;
		tampered.attemptId = "attempts/tampered";
		assert.equal(lease.attempt.attemptId, attempt.attemptId);
		await client.runs.renew(
			create(RenewAttemptLeaseRequestSchema, {
				expectedResourceVersion: 1n,
				fence: lease.fence,
				leaseDuration: { seconds: 120n },
			}),
			lease.credential,
			{ idempotencyKey: "renew" },
		);
		await client.runs.heartbeat(
			create(HeartbeatAttemptRequestSchema, {
				expectedResourceVersion: 1n,
				fence: lease.fence,
				leaseDuration: { seconds: 120n },
			}),
			lease.credential,
			{ idempotencyKey: "heartbeat" },
		);
		await client.runs.cancelAttempt(
			create(CancelAttemptRequestSchema, {
				expectedResourceVersion: 1n,
				fence: lease.fence,
				reason: "worker shutdown",
			}),
			lease.credential,
			{ idempotencyKey: "cancel-attempt" },
		);
		const committedAttempt = create(AttemptSchema, lease.attempt);
		committedAttempt.state = AttemptState.SUCCEEDED;
		await client.runs.commitAttempt(
			create(CommitAttemptRequestSchema, {
				attempt: committedAttempt,
				expectedResourceVersion: 1n,
				fence: lease.fence,
				updateMask: { paths: ["state"] },
			}),
			lease.credential,
			{ idempotencyKey: "commit" },
		);

		assert.equal(command.context?.tenantId, "forged");
		assert.equal(acquisition.runName, "run-1");
		assert.deepEqual(calls, [
			"RequestJob",
			"GetJob",
			"ListJobs",
			"CancelJob",
			"GetRun",
			"ListRuns",
			"GetAttempt",
			"ListAttempts",
			"AcquireAttemptLease",
			"RenewAttemptLease",
			"HeartbeatAttempt",
			"CancelAttempt",
			"CommitAttempt",
		]);
		assert.deepEqual(leaseHeaders, [TOKEN, TOKEN, TOKEN, TOKEN]);
	});
});
