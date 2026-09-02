import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { TrainingService } from "../../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import { TrainingRunState } from "../../../../protocols/generated/typescript/training/v1/training_run_pb.js";
import { ClientConfig, Environment, FakeRuntime, MindcladeClient } from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const RUN = `${PARENT}/trainingRuns/run-1`;
const CHECKPOINT = `${RUN}/checkpoints/checkpoint-1`;
const digest = (character: string): string => `sha256:${character.repeat(64)}`;

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

const config = ClientConfig.create({
	endpoint: "http://127.0.0.1:9443",
	environment: Environment.Local,
	identity: {
		principalId: "principals/worker-1",
		projectId: "projects/p-1",
		tenantId: "tenants/t-1",
	},
	insecureLoopbackForTesting: true,
});

const reference = (resourceType: string, name: string) => ({ resourceType, name });
const artifact = () => ({ digest: digest("b") });
const progress = () => ({ progressRevision: 1n, trainingRunName: RUN });
const run = (state = TrainingRunState.RUNNING) => ({ name: RUN, state, uid: "run-uid" });
const checkpoint = () => ({ name: CHECKPOINT, snapshotEpoch: 1n, trainingRunName: RUN });
const fence = () => ({
	attemptId: "attempts/a-1",
	deadline: timestampFromDate(new Date(1_900_000_000_000)),
	jobId: "jobs/j-1",
	leaseEpoch: 1n,
	leaseTokenDigest: digest("a"),
	runId: "runs/r-1",
});
const deadline = () => timestampFromDate(new Date(1_900_000_000_000));

describe("Training generated-contract facade", () => {
	test("enforces the authoritative training resource-leaf law", async () => {
		const transport = testTransport((router) => {
			router.service(TrainingService, {
				getTrainingRun(request) {
					return { trainingRun: { name: request.name, state: TrainingRunState.RUNNING } };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		for (const leaf of ["01", "A", "a.b_c~d-1"]) {
			const name = `${PARENT}/trainingRuns/${leaf}`;
			assert.equal((await client.training.get(name)).name, name);
		}
		for (const leaf of [".leading", "~leading", "\u0000control", "a".repeat(129)]) {
			await assert.rejects(client.training.get(`${PARENT}/trainingRuns/${leaf}`));
		}
	});

	test("covers all thirteen RPCs with exact routes, context, lease, paging, and stream cursor", async () => {
		const calls: string[] = [];
		const contexts: Array<{
			readonly digest: string;
			readonly principal: string;
			readonly project: string;
			readonly tenant: string;
		}> = [];
		const leases: Array<string | null> = [];
		const capture = (method: string, input: unknown, lease?: string | null): void => {
			const request = input as {
				readonly command?: {
					readonly context?: {
						readonly canonicalRequestDigest: string;
						readonly principalId: string;
						readonly projectId: string;
						readonly tenantId: string;
					};
				};
			};
			calls.push(method);
			if (request.command?.context !== undefined) {
				contexts.push({
					digest: request.command.context.canonicalRequestDigest,
					principal: request.command.context.principalId,
					project: request.command.context.projectId,
					tenant: request.command.context.tenantId,
				});
			}
			if (lease !== undefined) leases.push(lease);
		};
		const transport = testTransport((router) => {
			router.service(TrainingService, {
				createTrainingRun(request) {
					capture("CreateTrainingRun", request);
					return { operation: { operationId: "operations/create" } };
				},
				getTrainingRun(request) {
					capture("GetTrainingRun", request);
					return { trainingRun: run() };
				},
				listTrainingRuns(request) {
					capture("ListTrainingRuns", request);
					assert.equal(request.parent, PARENT);
					assert.equal(request.page?.pageToken, "opaque");
					return { page: { nextPageToken: "next" }, trainingRuns: [run()] };
				},
				startTrainingAttempt(request, context) {
					capture(
						"StartTrainingAttempt",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { trainingRun: run() };
				},
				resumeTrainingAttempt(request, context) {
					capture(
						"ResumeTrainingAttempt",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { trainingRun: run() };
				},
				commitTrainingProgress(request, context) {
					capture(
						"CommitTrainingProgress",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { progress: progress(), trainingRun: run() };
				},
				prepareCheckpoint(request, context) {
					capture(
						"PrepareCheckpoint",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { checkpoint: checkpoint() };
				},
				commitCheckpoint(request, context) {
					capture(
						"CommitCheckpoint",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { checkpoint: checkpoint(), trainingRun: run() };
				},
				completeTrainingRun(request, context) {
					capture(
						"CompleteTrainingRun",
						request,
						context.requestHeader.get("x-mindclade-lease-token"),
					);
					return { trainingRun: run(TrainingRunState.COMPLETED) };
				},
				cancelTrainingRun(request) {
					capture("CancelTrainingRun", request);
					return { trainingRun: run(TrainingRunState.CANCELLED) };
				},
				getCheckpoint(request) {
					capture("GetCheckpoint", request);
					return { checkpoint: checkpoint() };
				},
				listCheckpoints(request) {
					capture("ListCheckpoints", request);
					return { checkpoints: [checkpoint()] };
				},
				async *watchTrainingRun(request) {
					capture("WatchTrainingRun", request);
					assert.equal(request.afterSequence, 0n);
					yield { sequence: 1n, trainingRun: run(TrainingRunState.COMPLETED) };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		const mutation = {
			idempotencyKey: "training-idempotency",
			leaseToken: "opaque-lease",
			workerId: "workers/worker-1",
		};

		assert.equal(
			(await client.training.submit({ trainingRunId: "run-1" }, { idempotencyKey: "create" }))
				.operationId,
			"operations/create",
		);
		assert.equal((await client.training.get(RUN)).name, RUN);
		assert.equal(
			(await client.training.listRuns({ page: { pageSize: 20, pageToken: "opaque" } })).page
				?.nextPageToken,
			"next",
		);
		assert.equal(
			(
				await client.training.startAttempt(
					{ deadline: deadline(), fence: fence(), trainingRun: reference("training_run", RUN) },
					mutation,
				)
			).name,
			RUN,
		);
		assert.equal(
			(
				await client.training.resumeAttempt(
					{
						checkpoint: reference("checkpoint", CHECKPOINT),
						deadline: deadline(),
						fence: fence(),
						trainingRun: reference("training_run", RUN),
					},
					mutation,
				)
			).name,
			RUN,
		);
		assert.equal(
			(
				await client.training.commitProgress(
					{ fence: fence(), progress: progress(), trainingRunName: RUN },
					mutation,
				)
			)[0].progressRevision,
			1n,
		);
		assert.equal(
			(
				await client.training.prepareCheckpoint(
					{
						committedProgress: progress(),
						fence: fence(),
						logicalStateDescriptor: artifact(),
						snapshotEpoch: 1n,
						trainingRunName: RUN,
					},
					mutation,
				)
			).name,
			CHECKPOINT,
		);
		assert.equal(
			(
				await client.training.commitCheckpoint(
					{
						checkpointManifest: artifact(),
						committedAt: deadline(),
						committedProgress: progress(),
						fence: fence(),
						logicalStateDescriptor: artifact(),
						snapshotEpoch: 1n,
						trainingRunName: RUN,
						verificationEvidence: { digest: digest("c") },
					},
					mutation,
				)
			)[0].name,
			CHECKPOINT,
		);
		assert.equal(
			(
				await client.training.complete(
					{ classification: 1, completedAt: deadline(), fence: fence(), trainingRunName: RUN },
					mutation,
				)
			).name,
			RUN,
		);
		assert.equal(
			(
				await client.training.cancel(
					{ etag: "etag", reason: "operator request", trainingRunName: RUN },
					{ idempotencyKey: "cancel" },
				)
			).name,
			RUN,
		);
		assert.equal((await client.training.getCheckpoint(CHECKPOINT)).name, CHECKPOINT);
		assert.equal(
			(await client.training.listCheckpoints({ parent: RUN })).checkpoints[0]?.name,
			CHECKPOINT,
		);
		for await (const update of client.training.watch(RUN)) assert.equal(update.sequence, 1n);

		assert.deepEqual(calls, [
			"CreateTrainingRun",
			"GetTrainingRun",
			"ListTrainingRuns",
			"StartTrainingAttempt",
			"ResumeTrainingAttempt",
			"CommitTrainingProgress",
			"PrepareCheckpoint",
			"CommitCheckpoint",
			"CompleteTrainingRun",
			"CancelTrainingRun",
			"GetCheckpoint",
			"ListCheckpoints",
			"WatchTrainingRun",
		]);
		assert.equal(contexts.length, 8);
		assert.ok(
			contexts.every(
				(value) =>
					value.tenant === "tenants/t-1" &&
					value.project === "projects/p-1" &&
					value.principal === "principals/worker-1" &&
					/^sha256:[0-9a-f]{64}$/.test(value.digest),
			),
		);
		assert.deepEqual(
			leases,
			Array.from({ length: 6 }, () => "opaque-lease"),
		);
	});
});
