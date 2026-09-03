import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Code, ConnectError, createRouterTransport, type Transport } from "@connectrpc/connect";

import {
	ErrorCode,
	ErrorDetailSchema,
	RetryClass,
} from "../../../protocols/generated/typescript/common/v1/error_detail_pb.js";
import { OperationService } from "../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import {
	AuthenticationError,
	AuthorizationError,
	CancelledError,
	ClientConfig,
	ConflictError,
	Environment,
	FakeRuntime,
	MindcladeClient,
	MindcladeError,
	NotFoundError,
	OperationFailure,
	OperationState,
	QuotaError,
	RateLimitError,
	RetryableServiceError,
	shouldRetry,
	TransportError,
	ValidationError,
} from "../src/index.js";

const OPERATION = "operations/op-1";
const LEAKY = 'SQLSTATE 23505 duplicate key value violates unique constraint "runs_pkey"';

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
	retry: { initialBackoffMs: 10, maxAttempts: 1, maxBackoffMs: 100 },
});

const clientThrowing = (raise: () => never): MindcladeClient => {
	const transport = testTransport((router) => {
		router.service(OperationService, {
			getOperation() {
				return raise();
			},
		});
	});
	return MindcladeClient.withTransport(config, transport, new FakeRuntime());
};

const failWith = async (raise: () => never): Promise<MindcladeError> => {
	try {
		await clientThrowing(raise).operations.get(OPERATION);
	} catch (reason) {
		assert.ok(reason instanceof MindcladeError);
		return reason;
	}
	throw new Error("expected the call to fail");
};

const remote = async (code: Code, metadata?: HeadersInit): Promise<MindcladeError> =>
	failWith(() => {
		throw new ConnectError(LEAKY, code, metadata);
	});

describe("error hierarchy", () => {
	test("every transport status maps to its typed class and stable code", async () => {
		const cases: ReadonlyArray<
			readonly [Code, HeadersInit | undefined, new (...args: never[]) => MindcladeError, string]
		> = [
			[Code.Unauthenticated, undefined, AuthenticationError, "authentication"],
			[Code.PermissionDenied, undefined, AuthorizationError, "authorization"],
			[Code.InvalidArgument, undefined, ValidationError, "validation"],
			[Code.OutOfRange, undefined, ValidationError, "validation"],
			[Code.Aborted, undefined, ConflictError, "conflict"],
			[Code.AlreadyExists, undefined, ConflictError, "conflict"],
			[Code.NotFound, undefined, NotFoundError, "not_found"],
			[Code.ResourceExhausted, { "retry-after-ms": "25" }, RateLimitError, "rate_limit"],
			[Code.ResourceExhausted, undefined, QuotaError, "quota"],
			[Code.Unavailable, undefined, RetryableServiceError, "retryable_service"],
			[Code.Internal, undefined, RetryableServiceError, "retryable_service"],
			[Code.DataLoss, undefined, RetryableServiceError, "retryable_service"],
			[Code.Canceled, undefined, CancelledError, "cancelled"],
			[Code.Unimplemented, undefined, TransportError, "transport"],
		];
		for (const [code, metadata, expected, stableCode] of cases) {
			const error = await remote(code, metadata);
			assert.ok(error instanceof expected, `${Code[code]} should produce ${expected.name}`);
			assert.ok(error instanceof MindcladeError);
			assert.equal(error.stableCode, stableCode);
			assert.equal(error.code, code);
		}
	});

	test("locally raised failures use the same hierarchy", () => {
		assert.ok(MindcladeError.invalidArgument("bad") instanceof ValidationError);
		assert.ok(MindcladeError.alreadyExists("dup") instanceof ConflictError);
		assert.ok(MindcladeError.paginationLimit("budget") instanceof QuotaError);
		assert.ok(MindcladeError.transport("socket") instanceof TransportError);
		assert.ok(MindcladeError.protocol("framing") instanceof TransportError);
		assert.ok(MindcladeError.authentication() instanceof AuthenticationError);
		assert.ok(MindcladeError.cancelled() instanceof CancelledError);
		// Configuration failures stay on the base class so a local policy mistake
		// is never mistaken for a wire failure.
		const configuration = MindcladeError.configuration("bad endpoint");
		assert.equal(configuration.constructor, MindcladeError);
		assert.equal(configuration.stableCode, "unclassified");
	});

	test("a terminal operation failure keeps its typed class and generated resource", async () => {
		const transport = testTransport((router) => {
			router.service(OperationService, {
				getOperation() {
					return {
						operation: {
							done: true,
							operationId: OPERATION,
							state: OperationState.FAILED,
						},
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await assert.rejects(client.operations.wait(OPERATION), (reason: unknown) => {
			assert.ok(reason instanceof OperationFailure);
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.stableCode, "operation_failed");
			assert.equal(reason.operationId, OPERATION);
			assert.equal(reason.operation.operationId, OPERATION);
			// The generated payload stays non-enumerable; only sanitized identity leaks.
			assert.equal(Object.hasOwn(JSON.parse(JSON.stringify(reason)) as object, "operation"), false);
			return true;
		});
	});

	test("structured server detail is exposed as sanitized, frozen typed fields", async () => {
		const error = await failWith(() => {
			throw new ConnectError(LEAKY, Code.FailedPrecondition, undefined, [
				{
					desc: ErrorDetailSchema,
					value: {
						code: ErrorCode.CONFLICT,
						errorId: "diagnostics/err-42",
						fieldViolations: [
							{ description: "must be a canonical name", field: "name" },
							{ description: `at Object.run (file.ts:1)\n${LEAKY}`, field: "leaky" },
						],
						message: LEAKY,
						preconditionViolations: [
							{
								description: "the attempt lease is stale",
								subject: "attempts/a-1",
								type: "LEASE_FENCE",
							},
						],
						retryClass: RetryClass.NEVER,
						subject: {
							etag: "revision-9",
							name: "tenants/t-1/projects/p-1/runs/run-1",
							resourceId: "run-1",
							resourceType: "run",
						},
					},
				},
			]);
		});

		assert.ok(error instanceof ConflictError);
		assert.equal(error.diagnosticReference, "diagnostics/err-42");
		assert.equal(error.conflictRevision, "revision-9");
		assert.equal(error.retryable, false, "RETRY_CLASS_NEVER forbids a retry");
		assert.equal(error.fieldViolations.length, 2);
		assert.equal(error.fieldViolations[0]?.field, "name");
		assert.equal(error.fieldViolations[0]?.description, "must be a canonical name");
		// The multi-line description is dropped rather than truncated.
		assert.equal(error.fieldViolations[1]?.description, "");
		assert.ok(Object.isFrozen(error.fieldViolations));
		assert.ok(Object.isFrozen(error.fieldViolations[0]));
		assert.equal(error.preconditionViolations.length, 1);
		assert.ok(Object.isFrozen(error.preconditionViolations[0]));
		assert.deepEqual(error.fence, {
			description: "the attempt lease is stale",
			subject: "attempts/a-1",
		});
		assert.equal(error.quota, undefined);
	});

	test("resource exhaustion carries a derived quota state", async () => {
		const error = await failWith(() => {
			throw new ConnectError("exhausted", Code.ResourceExhausted, undefined, [
				{
					desc: ErrorDetailSchema,
					value: {
						code: ErrorCode.RESOURCE_EXHAUSTED,
						preconditionViolations: [
							{
								description: "concurrent training runs per project",
								subject: "projects/p-1",
								type: "PROJECT_QUOTA",
							},
						],
						subject: { name: "projects/p-1", resourceId: "p-1", resourceType: "project" },
					},
				},
			]);
		});
		assert.ok(error instanceof QuotaError);
		assert.deepEqual(error.quota, {
			description: "concurrent training runs per project",
			limit: "PROJECT_QUOTA",
			subject: "projects/p-1",
		});
	});

	test("remote text and stack traces never reach the message or a serialization", async () => {
		const error = await remote(Code.Internal, { "x-request-id": "server-request-9" });
		assert.doesNotMatch(error.message, /SQLSTATE/);
		assert.doesNotMatch(error.message, /runs_pkey/);
		assert.equal(error.safeMessage, "remote service failed internally");
		const serialized = JSON.stringify(error);
		assert.doesNotMatch(serialized, /SQLSTATE/);
		assert.doesNotMatch(serialized, /runs_pkey/);
		assert.match(serialized, /server-request-9/);
	});

	test("correlation reads x-request-id and x-trace-id only", async () => {
		const canonical = await remote(Code.Internal, {
			"x-request-id": "server-request-1",
			"x-trace-id": "server-trace-1",
		});
		assert.equal(canonical.requestId, "server-request-1");
		assert.equal(canonical.traceId, "server-trace-1");

		const retired = await remote(Code.Internal, { "request-id": "legacy-alias" });
		assert.equal(retired.requestId, undefined);
		assert.equal(retired.traceId, undefined);
		assert.doesNotMatch(retired.message, /legacy-alias/);
	});

	test("the retry predicate applies one precedence order everywhere", () => {
		assert.equal(shouldRetry({ code: Code.Unavailable }), true);
		assert.equal(shouldRetry({ code: Code.ResourceExhausted }), true);
		assert.equal(shouldRetry({ code: Code.Aborted }), true);
		assert.equal(shouldRetry({ code: Code.DeadlineExceeded }), true);
		assert.equal(shouldRetry({ code: Code.FailedPrecondition }), false);
		assert.equal(shouldRetry({ code: undefined }), false);
		assert.equal(shouldRetry({ code: Code.Unavailable, retryClass: RetryClass.NEVER }), false);
		assert.equal(
			shouldRetry({ code: Code.Unavailable, trailerOverride: false, retryClass: RetryClass.SAFE }),
			false,
		);
		assert.equal(
			shouldRetry({
				code: Code.FailedPrecondition,
				retryClass: RetryClass.NEVER,
				trailerOverride: true,
			}),
			true,
		);
	});

	test("retry state is attached without mutating the error the caller holds", () => {
		const original = MindcladeError.transport("socket closed");
		const observed = original.withRetryState({
			attempts: 3,
			cause: "transport",
			cumulativeDelayMs: 42,
		});
		assert.notEqual(observed, original);
		assert.equal(original.retry, undefined);
		assert.ok(observed instanceof TransportError);
		assert.deepEqual(observed.retry, { attempts: 3, cause: "transport", cumulativeDelayMs: 42 });
		assert.equal(observed.message, original.message);
		assert.ok(Object.isFrozen(observed.retry));
	});
});
