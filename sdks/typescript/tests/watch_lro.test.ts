import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { create } from "@bufbuild/protobuf";
import { Code, ConnectError, createRouterTransport, type Transport } from "@connectrpc/connect";

import { InferenceStreamMessageSchema } from "../../../protocols/generated/typescript/inference/v1/inference_stream_pb.js";
import { InferenceService } from "../../../protocols/generated/typescript/internal/inference/v1/inference_service_pb.js";
import { OperationService } from "../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { TrainingService } from "../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import { WorkflowService } from "../../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";
import { OperationState } from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import { TrainingRunState } from "../../../protocols/generated/typescript/training/v1/training_run_pb.js";
import { WorkflowRunState } from "../../../protocols/generated/typescript/workflow/v1/workflow_run_pb.js";
import {
	CancelledError,
	ClientConfig,
	Environment,
	FakeRuntime,
	MindcladeClient,
	MindcladeError,
	TrainingRunFailure,
} from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const OPERATION = "operations/op-watch";
const TRAINING_RUN = `${PARENT}/trainingRuns/run-1`;
const WORKFLOW_RUN = `${PARENT}/workflowRuns/run-1`;

// The SDK's transport owns the total deadline; suppressing the router
// transport's duplicate timer keeps these assertions hermetic.
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

const loopbackConfig = (): ClientConfig =>
	ClientConfig.create({
		endpoint: "http://127.0.0.1:9443",
		environment: Environment.Local,
		identity: {
			principalId: "principals/worker-1",
			projectId: "projects/p-1",
			tenantId: "tenants/t-1",
		},
		insecureLoopbackForTesting: true,
	});

const clientWith = (transport: Transport, runtime = new FakeRuntime()): MindcladeClient =>
	MindcladeClient.withTransport(loopbackConfig(), transport, runtime);

describe("resumable watcher and long-running operation verbs", () => {
	test("reconnects from the last acknowledged cursor and advertises its retry position", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.5] });
		const cursors: bigint[] = [];
		const retryCounts: (string | null)[] = [];
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation(request, context) {
					cursors.push(request.afterSequence);
					retryCounts.push(context.requestHeader.get("x-mindclade-retry-count"));
					if (cursors.length === 1) {
						yield { operation: { done: false, operationId: OPERATION }, sequence: 1n };
						throw new ConnectError("transient disconnect", Code.Unavailable);
					}
					yield {
						operation: { done: true, operationId: OPERATION, state: OperationState.SUCCEEDED },
						sequence: 2n,
					};
				},
			});
		});
		const observed: bigint[] = [];
		for await (const update of clientWith(transport, runtime).operations.watch(OPERATION)) {
			observed.push(update.sequence);
		}
		assert.deepEqual(observed, [1n, 2n]);
		// Resumption is from the acknowledged cursor, never from the start.
		assert.deepEqual(cursors, [0n, 1n]);
		assert.deepEqual(retryCounts, ["0", "1"]);
		assert.deepEqual(runtime.sleeps, [50]);
	});

	test("a redelivered prefix is skipped rather than yielded twice", async () => {
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					yield { operation: { done: false, operationId: OPERATION }, sequence: 1n };
					yield { operation: { done: false, operationId: OPERATION }, sequence: 2n };
					yield {
						operation: { done: true, operationId: OPERATION, state: OperationState.SUCCEEDED },
						sequence: 3n,
					};
				},
			});
		});
		const observed: bigint[] = [];
		for await (const update of clientWith(transport).operations.watch(OPERATION, 2n)) {
			observed.push(update.sequence);
		}
		assert.deepEqual(observed, [3n]);
	});

	test("a reconnect that does not fit the remaining budget fails as a deadline", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.9] });
		let streams = 0;
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					streams += 1;
					throw new ConnectError("transient disconnect", Code.Unavailable);
					// biome-ignore lint/correctness/noUnreachable: a generator needs a yield to type as one.
					yield { operation: { operationId: OPERATION }, sequence: 1n };
				},
			});
		});
		const client = clientWith(transport, runtime);
		await assert.rejects(
			(async () => {
				for await (const _ of client.operations.watch(OPERATION, 0n, { timeoutMs: 50 })) {
					assert.fail("no update should be delivered");
				}
			})(),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "deadline_exceeded",
		);
		assert.equal(streams, 1);
		assert.deepEqual(runtime.sleeps, []);
	});

	test("a per-request attempt ceiling bounds reconnects", async () => {
		let streams = 0;
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					streams += 1;
					yield { operation: { done: false, operationId: OPERATION }, sequence: BigInt(streams) };
				},
			});
		});
		const client = clientWith(transport);
		await assert.rejects(
			(async () => {
				for await (const _ of client.operations.watch(OPERATION, 0n, { maxAttempts: 1 })) {
					// The single permitted stream ends before a terminal update.
				}
			})(),
			(reason: unknown) => reason instanceof MindcladeError && reason.retryable,
		);
		assert.equal(streams, 1);
	});

	test("a reconnect burst is observable on the error and is bounded by the route", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.5, 0.5, 0.5] });
		let streams = 0;
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					streams += 1;
					if (streams === 1) {
						yield { operation: { done: false, operationId: OPERATION }, sequence: 1n };
					}
					throw new ConnectError("transient disconnect", Code.Unavailable);
				},
			});
		});
		const client = clientWith(transport, runtime);
		const observed: bigint[] = [];
		await assert.rejects(
			(async () => {
				for await (const update of client.operations.watch(OPERATION)) {
					observed.push(update.sequence);
				}
			})(),
			(reason: unknown) => {
				assert.ok(reason instanceof MindcladeError);
				// WatchOperation is a `safe` route, so the client policy's four
				// attempts apply; the delivered update reset the burst, so the
				// reported reconnects and delay are the ones since that update.
				assert.deepEqual(reason.retry, { attempts: 4, cause: "remote", cumulativeDelayMs: 350 });
				return true;
			},
		);
		assert.deepEqual(observed, [1n]);
		// One stream that made progress plus the four-attempt burst that followed.
		assert.equal(streams, 4);
	});

	test("an abort signal ends the watch between messages", async () => {
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					yield { operation: { done: false, operationId: OPERATION }, sequence: 1n };
					yield { operation: { done: false, operationId: OPERATION }, sequence: 2n };
				},
			});
		});
		const controller = new AbortController();
		const iterator = clientWith(transport)
			.operations.watch(OPERATION, 0n, { signal: controller.signal })
			[Symbol.asyncIterator]();
		assert.equal((await iterator.next()).value?.sequence, 1n);
		controller.abort();
		await assert.rejects(iterator.next(), (reason: unknown) => {
			assert.ok(reason instanceof CancelledError);
			assert.equal(reason.kind, "cancelled");
			return true;
		});
	});

	test("identity and ordering violations stay terminal protocol failures", async () => {
		const operations = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					yield { operation: { operationId: "operations/other" }, sequence: 1n };
				},
			});
		});
		const workflows = testTransport((router) => {
			router.service(WorkflowService, {
				async *watchWorkflowRun() {
					yield {
						workflowRun: {
							name: WORKFLOW_RUN,
							state: WorkflowRunState.RUNNING,
							transitionSequence: 7n,
						},
					};
				},
			});
		});
		const training = testTransport((router) => {
			router.service(TrainingService, {
				async *watchTrainingRun() {
					yield {
						sequence: 9n,
						trainingRun: { name: TRAINING_RUN, state: TrainingRunState.RUNNING },
					};
				},
			});
		});
		const inference = testTransport((router) => {
			router.service(InferenceService, {
				async *watchInference() {
					yield {
						message: create(InferenceStreamMessageSchema, {
							requestName: "inferenceRequests/req-1",
							resumeToken: "cursor-1",
							sequence: 1n,
							update: { case: "heartbeat", value: {} },
						}),
					};
				},
			});
		});
		const protocolFailure = (reason: unknown): boolean =>
			reason instanceof MindcladeError && reason.kind === "protocol";
		const drain = async (source: AsyncIterable<unknown>): Promise<void> => {
			for await (const _ of source) {
				// Every stream under test is expected to fail before delivering.
			}
		};
		await assert.rejects(
			drain(clientWith(operations).operations.watch(OPERATION)),
			protocolFailure,
		);
		await assert.rejects(
			drain(clientWith(workflows).workflows.watch(WORKFLOW_RUN)),
			protocolFailure,
		);
		await assert.rejects(drain(clientWith(training).training.watch(TRAINING_RUN)), protocolFailure);
		await assert.rejects(
			drain(clientWith(inference).inference.watch("operations/inference-1")),
			protocolFailure,
		);
	});

	test("resumeWatch demands a positive acknowledged cursor and continues from it", async () => {
		const cursors: bigint[] = [];
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation(request) {
					cursors.push(request.afterSequence);
					yield {
						operation: { done: true, operationId: OPERATION, state: OperationState.SUCCEEDED },
						sequence: request.afterSequence + 1n,
					};
				},
			});
		});
		const client = clientWith(transport);
		await assert.rejects(
			(async () => {
				for await (const _ of client.operations.resumeWatch(OPERATION, 0n)) {
					assert.fail("a zero cursor must be refused before any RPC");
				}
			})(),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
		assert.deepEqual(cursors, []);
		const observed: bigint[] = [];
		for await (const update of client.operations.resumeWatch(OPERATION, 4n)) {
			observed.push(update.sequence);
		}
		assert.deepEqual(cursors, [4n]);
		assert.deepEqual(observed, [5n]);
	});

	test("workflow and training resumeWatch share the operations semantics", async () => {
		const workflowCursors: bigint[] = [];
		const workflows = testTransport((router) => {
			router.service(WorkflowService, {
				async *watchWorkflowRun(request) {
					workflowCursors.push(request.afterTransitionSequence);
					yield {
						workflowRun: {
							name: WORKFLOW_RUN,
							state: WorkflowRunState.SUCCEEDED,
							transitionSequence: request.afterTransitionSequence + 1n,
						},
					};
				},
			});
		});
		const client = clientWith(workflows);
		for await (const run of client.workflows.resumeWatch(WORKFLOW_RUN, 3n)) {
			assert.equal(run.transitionSequence, 4n);
		}
		assert.deepEqual(workflowCursors, [3n]);

		const trainingCursors: bigint[] = [];
		const training = testTransport((router) => {
			router.service(TrainingService, {
				async *watchTrainingRun(request) {
					trainingCursors.push(request.afterSequence);
					yield {
						sequence: request.afterSequence + 1n,
						trainingRun: { name: TRAINING_RUN, state: TrainingRunState.COMPLETED },
					};
				},
			});
		});
		const trainingClient = clientWith(training);
		await assert.rejects(
			(async () => {
				for await (const _ of trainingClient.training.resumeWatch(TRAINING_RUN, 0n)) {
					assert.fail("a zero cursor must be refused before any RPC");
				}
			})(),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
		for await (const update of trainingClient.training.resumeWatch(TRAINING_RUN, 2n)) {
			assert.equal(update.sequence, 3n);
		}
		assert.deepEqual(trainingCursors, [2n]);
	});

	test("training wait mirrors the workflow terminal verb", async () => {
		const terminal = (state: TrainingRunState): Transport =>
			testTransport((router) => {
				router.service(TrainingService, {
					async *watchTrainingRun(request) {
						yield {
							sequence: request.afterSequence + 1n,
							trainingRun: { name: TRAINING_RUN, state },
						};
					},
				});
			});
		const completed = await clientWith(terminal(TrainingRunState.COMPLETED)).training.wait(
			TRAINING_RUN,
		);
		assert.equal(completed.state, TrainingRunState.COMPLETED);

		const failing = clientWith(terminal(TrainingRunState.FAILED));
		await assert.rejects(failing.training.wait(TRAINING_RUN), (reason: unknown) => {
			assert.ok(reason instanceof TrainingRunFailure);
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.run.state, TrainingRunState.FAILED);
			// The generated payload is retained but never serialized.
			assert.equal(JSON.stringify(reason).includes("trainingRuns"), false);
			return true;
		});

		const cancelled = clientWith(terminal(TrainingRunState.CANCELLED));
		await assert.rejects(
			cancelled.training.wait(TRAINING_RUN),
			(reason: unknown) => reason instanceof TrainingRunFailure && reason.kind === "cancelled",
		);
	});
});
