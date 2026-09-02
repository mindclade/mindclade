import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Code, ConnectError, createRouterTransport, type Transport } from "@connectrpc/connect";

import {
	OperationService,
	RunService,
} from "../../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { TrainingService } from "../../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import type { ClientCore } from "../src/core.js";
import {
	AccessToken,
	ClientConfig,
	Environment,
	FakeRuntime,
	isNeverRetryable,
	MindcladeClient,
	MindcladeError,
	registeredMethodSafety,
	type TokenProvider,
	withUnsafeRetryOfNonIdempotent,
} from "../src/index.js";
import type { RawInternalClients } from "../src/raw.js";
import type { PreparedCall } from "../src/request.js";
import { retryableAttempts } from "../src/retry.js";

const OPERATION = "operations/op-1";
const EXPIRE_ATTEMPT_LEASES = "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases";
const GET_OPERATION = "/mindclade.internal.job.v1.OperationService/GetOperation";

// The SDK's transport owns the total deadline. Suppressing the router
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

const identity = {
	principalId: "principals/worker-1",
	projectId: "projects/p-1",
	tenantId: "tenants/t-1",
};

const loopbackConfig = (attempts = 3): ClientConfig =>
	ClientConfig.create({
		endpoint: "http://127.0.0.1:9443",
		environment: Environment.Local,
		identity,
		insecureLoopbackForTesting: true,
		retry: { initialBackoffMs: 10, maxAttempts: attempts, maxBackoffMs: 100 },
	});

/** Charges a fixed slice of the caller's total budget to every acquisition. */
class SlowTokenProvider implements TokenProvider {
	acquisitions = 0;
	readonly #runtime: FakeRuntime;
	readonly #costMs: number;

	constructor(runtime: FakeRuntime, costMs: number) {
		this.#runtime = runtime;
		this.#costMs = costMs;
	}

	async getToken(_audience: string, signal: AbortSignal): Promise<AccessToken> {
		if (signal.aborted) throw signal.reason;
		this.acquisitions += 1;
		this.#runtime.now += this.#costMs;
		return new AccessToken("short-lived-test-token", this.#runtime.nowMs() + 3_600_000);
	}
}

const failingOperations = (
	error: () => never,
	succeedFrom = Number.POSITIVE_INFINITY,
): { readonly transport: Transport; readonly headers: Headers[] } => {
	const headers: Headers[] = [];
	const transport = testTransport((router) => {
		router.service(OperationService, {
			getOperation(_request, context) {
				headers.push(new Headers(context.requestHeader));
				if (headers.length >= succeedFrom) {
					return { operation: { done: true, operationId: OPERATION } };
				}
				return error();
			},
		});
	});
	return { headers, transport };
};

describe("retry and timeout policy", () => {
	test("a should-retry trailer overrides eligibility in both directions", async () => {
		const runtime = new FakeRuntime();
		const refused = failingOperations(() => {
			throw new ConnectError(
				"serialized sensitive payload",
				Code.Unavailable,
				new Headers({ "x-mindclade-should-retry": "false" }),
			);
		});
		const refusedClient = MindcladeClient.withTransport(
			loopbackConfig(),
			refused.transport,
			runtime,
		);
		await assert.rejects(refusedClient.operations.get(OPERATION), (reason: unknown) => {
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.retryable, false);
			assert.equal(reason.retry?.attempts, 1);
			return true;
		});
		assert.equal(refused.headers.length, 1);
		assert.deepEqual(runtime.sleeps, []);

		const forcedRuntime = new FakeRuntime({ randomValues: [0.5] });
		const forced = failingOperations(() => {
			throw new ConnectError(
				"serialized sensitive payload",
				Code.FailedPrecondition,
				new Headers({ "x-mindclade-should-retry": "true" }),
			);
		}, 2);
		const forcedClient = MindcladeClient.withTransport(
			loopbackConfig(),
			forced.transport,
			forcedRuntime,
		);
		const operation = await forcedClient.operations.get(OPERATION);
		assert.equal(operation.done, true);
		assert.equal(forced.headers.length, 2);
		assert.deepEqual(forcedRuntime.sleeps, [5]);
	});

	test("a server-pinned retry-after is honoured exactly and clamped to max backoff", async () => {
		const runtime = new FakeRuntime();
		const server = failingOperations(() => {
			throw new ConnectError(
				"serialized sensitive payload",
				Code.Unavailable,
				new Headers({ "retry-after-ms": "999999" }),
			);
		}, 2);
		const client = MindcladeClient.withTransport(loopbackConfig(), server.transport, runtime);
		await client.operations.get(OPERATION);
		assert.deepEqual(runtime.sleeps, [100]);
		assert.equal(runtime.randomValues.length, 1, "a pinned backoff must not consume jitter");
	});

	test("full jitter is drawn from the injected source and advertised on every attempt", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.25, 0.75] });
		const server = failingOperations(() => {
			throw new ConnectError("serialized sensitive payload", Code.Unavailable);
		});
		const client = MindcladeClient.withTransport(loopbackConfig(), server.transport, runtime);
		await assert.rejects(client.operations.get(OPERATION), (reason: unknown) => {
			assert.ok(reason instanceof MindcladeError);
			assert.deepEqual(reason.retry, {
				attempts: 3,
				cause: "remote",
				cumulativeDelayMs: 17,
			});
			return true;
		});
		// floor(0.25 * (10 + 1)) then floor(0.75 * (20 + 1)).
		assert.deepEqual(runtime.sleeps, [2, 15]);
		assert.deepEqual(
			server.headers.map((headers) => headers.get("x-mindclade-retry-count")),
			["0", "1", "2"],
		);
		const budgets = server.headers.map((headers) => Number(headers.get("x-mindclade-timeout-ms")));
		assert.equal(budgets.length, 3);
		for (const [index, budget] of budgets.entries()) {
			assert.ok(Number.isInteger(budget) && budget > 0);
			if (index > 0) assert.ok(budget < (budgets[index - 1] ?? 0));
		}
	});

	test("the timeout is a total budget spanning retries and credential acquisition", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.9] });
		const provider = new SlowTokenProvider(runtime, 40);
		const config = ClientConfig.create({
			environment: Environment.Development,
			identity,
			retry: { initialBackoffMs: 10, maxAttempts: 4, maxBackoffMs: 100 },
			tokenProvider: provider,
		});
		const server = failingOperations(() => {
			throw new ConnectError("serialized sensitive payload", Code.Unavailable);
		});
		const client = MindcladeClient.withTransport(config, server.transport, runtime);
		await assert.rejects(client.operations.get(OPERATION, { timeoutMs: 50 }), (reason: unknown) => {
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.kind, "deadline_exceeded");
			assert.ok((reason.retry?.attempts ?? 0) < 4, "the budget must stop the attempt ladder");
			return true;
		});
		assert.ok(provider.acquisitions >= 1);
		assert.ok(server.headers.length < 4);
	});

	test("a per-request attempt ceiling overrides the client policy in both directions", async () => {
		const single = new FakeRuntime();
		const narrowed = failingOperations(() => {
			throw new ConnectError("serialized sensitive payload", Code.Unavailable);
		});
		const narrowedClient = MindcladeClient.withTransport(
			loopbackConfig(3),
			narrowed.transport,
			single,
		);
		await assert.rejects(narrowedClient.operations.get(OPERATION, { maxAttempts: 1 }));
		assert.equal(narrowed.headers.length, 1);
		assert.deepEqual(single.sleeps, []);

		const widened = new FakeRuntime({ randomValues: [0, 0, 0] });
		const server = failingOperations(() => {
			throw new ConnectError("serialized sensitive payload", Code.Unavailable);
		});
		const widenedClient = MindcladeClient.withTransport(
			loopbackConfig(2),
			server.transport,
			widened,
		);
		await assert.rejects(widenedClient.operations.get(OPERATION, { maxAttempts: 4 }));
		assert.equal(server.headers.length, 4);

		await assert.rejects(
			narrowedClient.operations.get(OPERATION, { maxAttempts: 9 }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
		await assert.rejects(
			narrowedClient.operations.get(OPERATION, { maxAttempts: 0 }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
	});

	test("ExpireAttemptLeases is pinned raw-only and is never retried", async () => {
		assert.equal(registeredMethodSafety(EXPIRE_ATTEMPT_LEASES), "never");
		assert.equal(isNeverRetryable(EXPIRE_ATTEMPT_LEASES), true);
		assert.equal(isNeverRetryable(GET_OPERATION), false);

		const runtime = new FakeRuntime();
		let calls = 0;
		const transport = testTransport((router) => {
			router.service(RunService, {
				expireAttemptLeases() {
					calls += 1;
					throw new ConnectError("do not expose", Code.Unavailable);
				},
			});
		});
		const client = MindcladeClient.withTransport(loopbackConfig(), transport, runtime);
		await assert.rejects(client.raw.runs.expireAttemptLeases({}), ConnectError);
		assert.equal(calls, 1);
	});

	test("the attempt budget honours safety class and the named unsafe override", () => {
		const runtime = new FakeRuntime();
		const core = {
			config: loopbackConfig(3),
			raw: {} as RawInternalClients,
			runtime,
		} satisfies ClientCore;
		const prepared = (overrides: Partial<PreparedCall> = {}): PreparedCall => ({
			deadlineMs: runtime.nowMs() + 1_000,
			leaseToken: undefined,
			maxAttempts: undefined,
			requestId: "request-1",
			signal: undefined,
			traceId: "trace-1",
			unsafeRetryOfNonIdempotent: undefined,
			workerId: undefined,
			...overrides,
		});
		const override = withUnsafeRetryOfNonIdempotent("operator accepts duplicate execution");

		assert.equal(retryableAttempts(core, prepared(), "safe"), 3);
		assert.equal(retryableAttempts(core, prepared(), "idempotent"), 3);
		assert.equal(retryableAttempts(core, prepared(), "unsafe"), 1);
		assert.equal(
			retryableAttempts(core, prepared({ unsafeRetryOfNonIdempotent: override }), "unsafe"),
			3,
		);
		assert.equal(
			retryableAttempts(core, prepared({ unsafeRetryOfNonIdempotent: override }), "never"),
			1,
		);
		assert.equal(retryableAttempts(core, prepared({ maxAttempts: 2 }), "safe"), 2);
	});

	test("the unsafe override is a named token that validates its justification", () => {
		const override = withUnsafeRetryOfNonIdempotent("replay is reconciled downstream");
		assert.equal(override.acknowledged, true);
		assert.equal(override.justification, "replay is reconciled downstream");
		assert.throws(
			() => withUnsafeRetryOfNonIdempotent(""),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
		assert.throws(
			() => withUnsafeRetryOfNonIdempotent("line one\nline two"),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
	});

	test("idempotent mutations retry under the same single policy", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.5] });
		let calls = 0;
		const seen: string[] = [];
		const transport = testTransport((router) => {
			router.service(TrainingService, {
				createTrainingRun(_request, context) {
					calls += 1;
					seen.push(context.requestHeader.get("x-mindclade-retry-count") ?? "");
					if (calls === 1) {
						throw new ConnectError("serialized sensitive payload", Code.Unavailable);
					}
					return { operation: { done: false, operationId: "operations/op-1" } };
				},
			});
		});
		const client = MindcladeClient.withTransport(loopbackConfig(), transport, runtime);
		const operation = await client.training.submit(
			{ trainingRunId: "run-1" },
			{ idempotencyKey: "idem-1" },
		);
		assert.equal(operation.operationId, "operations/op-1");
		assert.deepEqual(seen, ["0", "1"]);
		assert.deepEqual(runtime.sleeps, [5]);
	});
});
