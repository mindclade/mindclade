import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";

import { create } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { Code, ConnectError, createRouterTransport, type Transport } from "@connectrpc/connect";

import { ArtifactRefSchema } from "../../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import { InferenceStreamMessageSchema } from "../../../protocols/generated/typescript/inference/v1/inference_stream_pb.js";
import {
	AcquireArtifactLeaseRequestSchema,
	ArtifactService,
	ArtifactUploadState,
	GetArtifactRequestSchema,
	ListArtifactsRequestSchema,
	QuarantineArtifactRequestSchema,
	ReleaseArtifactLeaseRequestSchema,
} from "../../../protocols/generated/typescript/internal/artifact/v1/artifact_service_pb.js";
import { DatasetService } from "../../../protocols/generated/typescript/internal/dataset/v1/dataset_service_pb.js";
import { InferenceService } from "../../../protocols/generated/typescript/internal/inference/v1/inference_service_pb.js";
import {
	ListOperationsRequestSchema,
	OperationService,
} from "../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { ModelService } from "../../../protocols/generated/typescript/internal/model/v1/model_service_pb.js";
import { TrainingService } from "../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import { OperationState } from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import {
	AccessToken,
	ClientConfig,
	Environment,
	FakeRuntime,
	type GcpIdentityTokenExchange,
	GcpWorkloadIdentityProvider,
	inferenceRequest,
	MindcladeClient,
	MindcladeError,
	OperationFailure,
	paginate,
	RecordingTransport,
	type TokenProvider,
} from "../src/index.js";

test("bounded pagination preserves opaque tokens and fails closed", async () => {
	const seen: string[] = [];
	const values: number[] = [];
	for await (const value of paginate(
		async (pageToken) => {
			seen.push(pageToken);
			return seen.length === 1
				? { items: [1, 2], nextPageToken: " next token " }
				: { items: [3], nextPageToken: "" };
		},
		{ initialPageToken: " initial token " },
	)) {
		values.push(value);
	}
	assert.deepEqual(seen, [" initial token ", " next token "]);
	assert.deepEqual(values, [1, 2, 3]);

	await assert.rejects(
		async () => {
			for await (const _ of paginate(
				async (pageToken) => ({
					items: [1],
					nextPageToken: pageToken,
				}),
				{ initialPageToken: "opaque" },
			)) {
				// The repeated token is rejected before page items are exposed.
			}
		},
		(reason: unknown) => reason instanceof MindcladeError && reason.kind === "protocol",
	);

	const bounded: number[] = [];
	await assert.rejects(
		async () => {
			for await (const value of paginate(
				async () => ({
					items: [1, 2, 3],
					nextPageToken: "more",
				}),
				{ limits: { maxItems: 2 } },
			)) {
				bounded.push(value);
			}
		},
		(reason: unknown) => reason instanceof MindcladeError && reason.kind === "pagination_limit",
	);
	assert.deepEqual(bounded, [1, 2]);
});

class FakeTokenProvider implements TokenProvider {
	readonly audiences: string[] = [];
	readonly #runtime: FakeRuntime;

	constructor(runtime: FakeRuntime) {
		this.#runtime = runtime;
	}

	async getToken(audience: string, signal: AbortSignal): Promise<AccessToken> {
		if (signal.aborted) throw signal.reason;
		this.audiences.push(audience);
		return new AccessToken("short-lived-test-token", this.#runtime.nowMs() + 60 * 60 * 1_000);
	}
}

const config = (
	runtime: FakeRuntime,
	options: { readonly attempts?: number } = {},
): { readonly config: ClientConfig; readonly provider: FakeTokenProvider } => {
	const provider = new FakeTokenProvider(runtime);
	return {
		config: ClientConfig.create({
			environment: Environment.Development,
			identity: {
				principalId: "principals/worker-1",
				projectId: "projects/p-1",
				tenantId: "tenants/t-1",
			},
			pollIntervalMs: 2,
			retry: {
				initialBackoffMs: 10,
				maxAttempts: options.attempts ?? 3,
				maxBackoffMs: 100,
			},
			tokenProvider: provider,
		}),
		provider,
	};
};

// The SDK's authenticated transport owns the total deadline. Suppressing the
// router transport's duplicate timer keeps in-process tests fully hermetic and
// avoids leaving a ref-counted test-server timer behind after each assertion.
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

const hasFilesystemCode =
	(code: string) =>
	(reason: unknown): boolean =>
		typeof reason === "object" && reason !== null && "code" in reason && reason.code === code;

describe("configuration and credentials", () => {
	test("TLS is required except explicit Local loopback", () => {
		const runtime = new FakeRuntime();
		const provider = new FakeTokenProvider(runtime);
		const identity = {
			principalId: "principal",
			projectId: "project",
			tenantId: "tenant",
		};
		const production = ClientConfig.create({
			environment: Environment.Production,
			identity,
			tokenProvider: provider,
		});
		assert.match(production.endpoint, /^https:/);
		assert.throws(
			() =>
				ClientConfig.create({
					endpoint: "http://127.0.0.1:9443",
					environment: Environment.Production,
					identity,
					insecureLoopbackForTesting: true,
					tokenProvider: provider,
				}),
			MindcladeError,
		);
		assert.throws(
			() =>
				ClientConfig.create({
					endpoint: "http://127.0.0.1:9443",
					environment: Environment.Local,
					identity,
					insecureLoopbackForTesting: true,
					tokenProvider: provider,
				}),
			/credentials cannot be sent over plaintext transport/,
		);
		const local = ClientConfig.create({
			endpoint: "http://127.0.0.1:9443",
			environment: Environment.Local,
			identity,
			insecureLoopbackForTesting: true,
		});
		assert.equal(local.tokenProvider, undefined);
		assert.throws(
			() =>
				ClientConfig.create({
					endpoint: "https://user:password@control-plane.example/v1",
					environment: Environment.Development,
					identity,
					tokenProvider: provider,
				}),
			MindcladeError,
		);
	});

	test("workload identity audience uses canonical HTTPS origin", () => {
		const runtime = new FakeRuntime();
		const provider = new FakeTokenProvider(runtime);
		const identity = {
			principalId: "principal",
			projectId: "project",
			tenantId: "tenant",
		};
		for (const [endpoint, expected] of [
			["https://CONTROL-PLANE.EXAMPLE:443", "https://control-plane.example"],
			["https://control-plane.example:8443", "https://control-plane.example:8443"],
			["https://[2001:db8::1]:443", "https://[2001:db8::1]"],
		] as const) {
			const config = ClientConfig.create({
				endpoint,
				environment: Environment.Development,
				identity,
				tokenProvider: provider,
			});
			assert.equal(config.audience, expected);
		}
		const explicit = ClientConfig.create({
			audience: "https://verifier.example/custom-audience",
			endpoint: "https://control-plane.example:443",
			environment: Environment.Development,
			identity,
			tokenProvider: provider,
		});
		assert.equal(explicit.audience, "https://verifier.example/custom-audience");
	});

	test("tokens reject unsafe lifetimes and redact secrets", () => {
		const now = Date.now();
		const token = new AccessToken("very-sensitive-token", now + 60 * 60 * 1_000);
		assert.equal(String(token), "AccessToken(<redacted>)");
		assert.equal(JSON.stringify(token), '"AccessToken(<redacted>)"');
		assert.doesNotMatch(String(token), /very-sensitive-token/);
		assert.throws(
			() => new AccessToken("long-lived", now + 2 * 60 * 60 * 1_000).authorizationHeader(now),
			MindcladeError,
		);
		assert.throws(() => new AccessToken("contains whitespace", now + 60_000), MindcladeError);
	});

	test("the total call deadline also bounds a non-cooperative token provider", async () => {
		const runtime = new FakeRuntime();
		const slowProvider: TokenProvider = {
			getToken: () =>
				new Promise((resolve) => {
					setTimeout(
						() => resolve(new AccessToken("eventual-token", runtime.nowMs() + 60 * 60 * 1_000)),
						30,
					);
				}),
		};
		const bounded = ClientConfig.create({
			environment: Environment.Development,
			identity: {
				principalId: "principals/worker-1",
				projectId: "projects/p-1",
				tenantId: "tenants/t-1",
			},
			tokenProvider: slowProvider,
		});
		const client = MindcladeClient.withTransport(
			bounded,
			testTransport(() => undefined),
			runtime,
		);
		await assert.rejects(
			client.raw.training.createTrainingRun({}, { timeoutMs: 2 }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "deadline_exceeded",
		);
	});

	test("GCP workload identity validates, caches, and singleflights audience-bound tokens", async () => {
		let exchanges = 0;
		const expiresAt = Math.floor(Date.now() / 1_000) + 3_600;
		const body = Buffer.from(
			JSON.stringify({ aud: "https://control-plane.example", exp: expiresAt }),
		).toString("base64url");
		const exchange: GcpIdentityTokenExchange = {
			async exchange(audience, signal) {
				assert.equal(audience, "https://control-plane.example");
				assert.equal(signal.aborted, false);
				exchanges += 1;
				await Promise.resolve();
				return `e30.${body}.signature`;
			},
		};
		const provider = new GcpWorkloadIdentityProvider({ exchange, exchangeTimeoutMs: 100 });
		const controller = new AbortController();
		const [first, second] = await Promise.all([
			provider.getToken("https://control-plane.example", controller.signal),
			provider.getToken("https://control-plane.example", controller.signal),
		]);
		assert.equal(first, second);
		assert.equal(exchanges, 1);
		await assert.rejects(provider.getToken("bad audience\n", controller.signal), MindcladeError);

		const wrongAudienceBody = Buffer.from(
			JSON.stringify({ aud: "https://different.example", exp: expiresAt }),
		).toString("base64url");
		const wrongAudienceProvider = new GcpWorkloadIdentityProvider({
			exchange: {
				async exchange() {
					return `e30.${wrongAudienceBody}.signature`;
				},
			},
			exchangeTimeoutMs: 100,
		});
		await assert.rejects(
			wrongAudienceProvider.getToken("https://control-plane.example", controller.signal),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "authentication",
		);
	});

	test("cancelling one GCP token waiter does not cancel the shared refresh", async () => {
		const expiresAt = Math.floor(Date.now() / 1_000) + 3_600;
		const body = Buffer.from(
			JSON.stringify({ aud: "https://control-plane.example", exp: expiresAt }),
		).toString("base64url");
		const jwt = `e30.${body}.signature`;
		let exchanges = 0;
		let release = (): void => undefined;
		const exchange: GcpIdentityTokenExchange = {
			exchange: () =>
				new Promise<string>((resolve) => {
					exchanges += 1;
					release = () => resolve(jwt);
				}),
		};
		const provider = new GcpWorkloadIdentityProvider({ exchange, exchangeTimeoutMs: 100 });
		const cancelled = new AbortController();
		const active = new AbortController();
		const first = provider.getToken("https://control-plane.example", cancelled.signal);
		const second = provider.getToken("https://control-plane.example", active.signal);
		cancelled.abort();
		await assert.rejects(
			first,
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "cancelled",
		);
		release();
		await second;
		assert.equal(exchanges, 1);
	});

	test("plaintext Local calls never acquire or transmit credentials", async () => {
		const runtime = new FakeRuntime();
		const local = ClientConfig.create({
			endpoint: "http://127.0.0.1:9443",
			environment: Environment.Local,
			identity: { principalId: "principal", projectId: "project", tenantId: "tenant" },
			insecureLoopbackForTesting: true,
		});
		const transport = testTransport((router) => {
			router.service(OperationService, {
				getOperation(_request, context) {
					assert.equal(context.requestHeader.has("authorization"), false);
					assert.equal(context.requestHeader.has("proxy-authorization"), false);
					assert.equal(context.requestHeader.has("cookie"), false);
					assert.equal(context.requestHeader.has("x-api-key"), false);
					return {
						operation: {
							done: true,
							operationId: "operations/local",
							state: OperationState.SUCCEEDED,
						},
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(local, transport, runtime);
		assert.equal((await client.operations.get("operations/local")).operationId, "operations/local");
		await client.raw.operations.getOperation(
			{ name: "operations/local" },
			{
				headers: {
					authorization: "Bearer caller-controlled",
					cookie: "session=caller-controlled",
					"proxy-authorization": "Basic caller-controlled",
					"x-api-key": "caller-controlled",
				},
			},
		);
		await assert.rejects(
			client.raw.operations.getOperation(
				{ name: "operations/local" },
				{ headers: { "x-request-id": "x".repeat(513) } },
			),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
	});
});

describe("ergonomic generated-contract APIs", () => {
	test("artifact lifecycle and operation listing invoke exact generated RPCs with trusted scope", async () => {
		const runtime = new FakeRuntime({ now: 1_800_000_000_000 });
		const setup = config(runtime, { attempts: 1 });
		const digest = `sha256:${"a".repeat(64)}`;
		const artifact = create(ArtifactRefSchema, {
			digest,
			mediaType: "application/octet-stream",
			sizeBytes: 7n,
		});
		const parent = "tenants/t-1/projects/p-1";
		const lease = {
			etag: "lease-etag-1",
			name: `${parent}/artifactLeases/lease-1`,
			projectId: "projects/p-1",
			resourceId: "lease-1",
			resourceType: "artifact_lease",
			resourceVersion: 1n,
			tenantId: "tenants/t-1",
		};
		const seen: Array<{ method: string; request: unknown; headers: Headers }> = [];
		const delegate = testTransport((router) => {
			router.service(ArtifactService, {
				getArtifact(request, context) {
					seen.push({ method: "GetArtifact", request, headers: context.requestHeader });
					return { artifact };
				},
				listArtifacts(request, context) {
					seen.push({ method: "ListArtifacts", request, headers: context.requestHeader });
					return { artifacts: [artifact], page: { nextPageToken: "opaque-next" } };
				},
				quarantineArtifact(request, context) {
					seen.push({ method: "QuarantineArtifact", request, headers: context.requestHeader });
					return {
						operation: {
							operationId: `${parent}/operations/quarantine-1`,
							projectId: "projects/p-1",
							state: OperationState.PENDING,
							tenantId: "tenants/t-1",
						},
					};
				},
				acquireArtifactLease(request, context) {
					seen.push({ method: "AcquireArtifactLease", request, headers: context.requestHeader });
					return { lease };
				},
				releaseArtifactLease(request, context) {
					seen.push({ method: "ReleaseArtifactLease", request, headers: context.requestHeader });
					return {};
				},
			});
			router.service(OperationService, {
				cancelOperation(request, context) {
					seen.push({ method: "CancelOperation", request, headers: context.requestHeader });
					return {
						operation: {
							operationId: `${parent}/operations/op-1`,
							projectId: "projects/p-1",
							state: OperationState.RUNNING,
							tenantId: "tenants/t-1",
						},
					};
				},
				listOperations(request, context) {
					seen.push({ method: "ListOperations", request, headers: context.requestHeader });
					return {
						operations: [
							{
								operationId: `${parent}/operations/op-1`,
								projectId: "projects/p-1",
								state: OperationState.RUNNING,
								tenantId: "tenants/t-1",
							},
						],
						page: { nextPageToken: "op-next" },
					};
				},
			});
		});
		const recording = new RecordingTransport(delegate);
		const client = MindcladeClient.withTransport(setup.config, recording, runtime);

		const getRequest = create(GetArtifactRequestSchema, { digest });
		assert.equal((await client.artifacts.get(getRequest)).digest, digest);
		const listRequest = create(ListArtifactsRequestSchema, {
			page: { pageSize: 25, pageToken: "opaque-artifact" },
		});
		assert.equal((await client.artifacts.list(listRequest)).page?.nextPageToken, "opaque-next");
		assert.equal(listRequest.parent, "");
		const quarantine = create(QuarantineArtifactRequestSchema, {
			artifact,
			context: { principalId: "forged", tenantId: "forged" },
			evidence: [
				{
					digest: `sha256:${"b".repeat(64)}`,
					evidenceKind: "integrity-check",
					subjectDigest: digest,
				},
			],
			reasonCode: "INTEGRITY_FAILURE",
		});
		await client.artifacts.quarantine(quarantine, { idempotencyKey: "quarantine-1" });
		assert.equal(quarantine.context?.tenantId, "forged");
		await client.artifacts.acquireLease(
			create(AcquireArtifactLeaseRequestSchema, {
				artifact,
				expireTime: timestampFromDate(new Date(runtime.now + 60_000)),
			}),
			{ idempotencyKey: "acquire-1" },
		);
		await client.artifacts.releaseLease(
			create(ReleaseArtifactLeaseRequestSchema, { etag: lease.etag, lease }),
			{ idempotencyKey: "release-1" },
		);
		const operationRequest = create(ListOperationsRequestSchema, {
			page: { pageSize: 50, pageToken: "opaque-operation" },
		});
		assert.equal((await client.operations.list(operationRequest)).page?.nextPageToken, "op-next");
		assert.equal(operationRequest.parent, "");
		assert.equal(
			(
				await client.operations.cancel(
					`${parent}/operations/op-1`,
					"operation-etag-1",
					"operator-request",
					{ idempotencyKey: "cancel-operation-1" },
				)
			).operationId,
			`${parent}/operations/op-1`,
		);

		assert.deepEqual(
			recording.calls.map((call) => call.method),
			[
				"/mindclade.internal.artifact.v1.ArtifactService/GetArtifact",
				"/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts",
				"/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact",
				"/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease",
				"/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease",
				"/mindclade.internal.job.v1.OperationService/ListOperations",
				"/mindclade.internal.job.v1.OperationService/CancelOperation",
			],
		);
		for (const item of seen) {
			const request = item.request as {
				parent?: string;
				context?: {
					canonicalRequestDigest: string;
					principalId: string;
					projectId: string;
					tenantId: string;
				};
			};
			if (item.method.startsWith("List")) assert.equal(request.parent, parent);
			if (request.context !== undefined) {
				assert.match(request.context.canonicalRequestDigest, /^sha256:[0-9a-f]{64}$/);
				assert.equal(request.context.tenantId, "tenants/t-1");
				assert.equal(request.context.projectId, "projects/p-1");
				assert.equal(request.context.principalId, "principals/worker-1");
				assert.ok(item.headers.has("idempotency-key"));
			}
		}
	});
	test("training submit binds identity metadata and retries idempotently with jitter", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.5] });
		const setup = config(runtime);
		let calls = 0;
		const seenHeaders: Headers[] = [];
		const seenTenantIds: string[] = [];
		const transport = testTransport((router) => {
			router.service(TrainingService, {
				createTrainingRun(request, context) {
					calls += 1;
					seenHeaders.push(new Headers(context.requestHeader));
					seenTenantIds.push(request.command?.context?.tenantId ?? "");
					if (calls === 1) {
						throw new ConnectError("serialized sensitive payload", Code.Unavailable);
					}
					return {
						operation: {
							done: false,
							operationId: "operations/op-1",
						},
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const operation = await client.training.submit(
			{
				context: {
					tenantId: "forged",
				},
				trainingRunId: "run-1",
			},
			{
				idempotencyKey: "idem-1",
				requestId: "request-1",
				traceId: "trace-1",
			},
		);
		assert.equal(operation.operationId, "operations/op-1");
		assert.equal(calls, 2);
		assert.deepEqual(seenTenantIds, ["tenants/t-1", "tenants/t-1"]);
		assert.deepEqual(runtime.sleeps, [5]);
		for (const headers of seenHeaders) {
			assert.equal(headers.get("authorization"), "Bearer short-lived-test-token");
			assert.equal(headers.get("idempotency-key"), "idem-1");
			assert.equal(headers.get("x-request-id"), "request-1");
			assert.equal(headers.get("x-trace-id"), "trace-1");
			assert.equal(headers.get("x-mindclade-expected-tenant"), "tenants/t-1");
			assert.equal(headers.get("x-mindclade-expected-project"), "projects/p-1");
		}
		assert.deepEqual(setup.provider.audiences, [setup.config.audience, setup.config.audience]);
	});

	test("raw generated calls are authenticated but never implicitly retried", async () => {
		const runtime = new FakeRuntime({ requestIds: ["raw-request"] });
		const setup = config(runtime);
		let calls = 0;
		const transport = testTransport((router) => {
			router.service(TrainingService, {
				createTrainingRun(_request, context) {
					calls += 1;
					assert.equal(context.requestHeader.get("authorization"), "Bearer short-lived-test-token");
					assert.equal(context.requestHeader.get("x-request-id"), "raw-request");
					throw new ConnectError("do not expose", Code.Unavailable);
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		await assert.rejects(client.raw.training.createTrainingRun({}), ConnectError);
		assert.equal(calls, 1);
	});

	test("errors retain code and request ID while removing remote payloads", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		const transport = testTransport((router) => {
			router.service(OperationService, {
				getOperation() {
					throw new ConnectError(
						"sensitive serialized request",
						Code.Unavailable,
						new Headers({ "retry-after-ms": "7", "x-request-id": "server-request-7" }),
					);
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		await assert.rejects(client.operations.get("operations/op-2"), (reason: unknown) => {
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.code, Code.Unavailable);
			assert.equal(reason.requestId, "server-request-7");
			assert.equal(reason.retryAfterMs, 7);
			assert.equal(reason.retryable, true);
			assert.doesNotMatch(reason.message, /sensitive serialized request/);
			return true;
		});
	});

	test("polling reaches terminal state and cancellation fails closed", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		let calls = 0;
		const transport = testTransport((router) => {
			router.service(OperationService, {
				getOperation() {
					calls += 1;
					return {
						operation: {
							done: calls === 2,
							operationId: "operations/op-3",
							state: calls === 2 ? OperationState.SUCCEEDED : OperationState.RUNNING,
						},
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const result = await client.operations.wait("operations/op-3", { waitTimeoutMs: 1_000 });
		assert.equal(result.done, true);
		assert.deepEqual(runtime.sleeps, [2]);

		const controller = new AbortController();
		controller.abort();
		await assert.rejects(
			client.operations.get("operations/op-4", { signal: controller.signal }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "cancelled",
		);
	});

	test("wait raises a typed failure carrying the generated terminal operation", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		const transport = testTransport((router) => {
			router.service(OperationService, {
				getOperation() {
					return {
						operation: {
							done: false,
							error: { message: "sensitive terminal detail" },
							operationId: "operations/failed",
							state: OperationState.FAILED,
						},
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		await assert.rejects(client.operations.wait("operations/failed"), (reason: unknown) => {
			assert.ok(reason instanceof OperationFailure);
			assert.equal(reason.operation.operationId, "operations/failed");
			assert.doesNotMatch(JSON.stringify(reason), /sensitive terminal detail/);
			return true;
		});
	});

	test("watch skips replayed sequences and returns a generated terminal operation", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					yield {
						operation: { done: false, operationId: "operations/op-5" },
						sequence: 2n,
					};
					yield {
						operation: {
							done: true,
							operationId: "operations/op-5",
							state: OperationState.SUCCEEDED,
						},
						sequence: 3n,
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const updates = [];
		for await (const update of client.operations.watch("operations/op-5", 2n)) {
			updates.push(update.sequence);
		}
		assert.deepEqual(updates, [3n]);
	});

	test("watch resumes with jitter when a partial stream ends before terminal state", async () => {
		const runtime = new FakeRuntime({ randomValues: [0.5] });
		const setup = config(runtime, { attempts: 2 });
		let streams = 0;
		const transport = testTransport((router) => {
			router.service(OperationService, {
				async *watchOperation() {
					streams += 1;
					yield {
						operation: {
							done: streams === 2,
							operationId: "operations/op-resume",
							state: streams === 2 ? OperationState.SUCCEEDED : OperationState.RUNNING,
						},
						sequence: BigInt(streams),
					};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const updates = [];
		for await (const update of client.operations.watch("operations/op-resume")) {
			updates.push(update.sequence);
		}
		assert.deepEqual(updates, [1n, 2n]);
		assert.equal(streams, 2);
		assert.deepEqual(runtime.sleeps, [5]);
	});

	test("watch observes caller cancellation before opening a stream", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 2 });
		const client = MindcladeClient.withTransport(
			setup.config,
			testTransport(() => undefined),
			runtime,
		);
		const controller = new AbortController();
		controller.abort();
		const iterator = client.operations
			.watch("operations/cancelled-watch", 0n, { signal: controller.signal })
			[Symbol.asyncIterator]();
		await assert.rejects(
			iterator.next(),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "cancelled",
		);
	});

	test("watch rejects missing or different operation identity", async () => {
		for (const operationId of ["", "operations/wrong"]) {
			const runtime = new FakeRuntime();
			const setup = config(runtime, { attempts: 1 });
			const transport = testTransport((router) => {
				router.service(OperationService, {
					async *watchOperation() {
						yield {
							operation: { operationId },
							sequence: 1n,
						};
					},
				});
			});
			const client = MindcladeClient.withTransport(setup.config, transport, runtime);
			const iterator = client.operations.watch("operations/expected")[Symbol.asyncIterator]();
			await assert.rejects(
				iterator.next(),
				(reason: unknown) => reason instanceof MindcladeError && reason.kind === "protocol",
			);
		}
	});

	test("artifact aliases return generated references and reject missing payloads", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		let calls = 0;
		const transport = testTransport((router) => {
			router.service(ArtifactService, {
				resolveArtifactAlias() {
					calls += 1;
					return calls === 1 ? { artifact: { digest: "sha256:artifact" } } : {};
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const artifact = await client.artifacts.resolveAlias("projects/p-1", "latest");
		assert.equal(artifact.digest, "sha256:artifact");
		await assert.rejects(
			client.artifacts.resolveAlias("projects/p-1", "missing"),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "protocol",
		);
	});

	test("artifact transfer resumes in a fresh client and verifies commit and download", async () => {
		const runtime = new FakeRuntime({
			requestIds: Array.from({ length: 32 }, (_, index) => `r-${index}`),
		});
		const setup = config(runtime, { attempts: 1 });
		const content = new TextEncoder().encode("abcdef");
		const digest = `sha256:${createHash("sha256").update(content).digest("hex")}`;
		const artifact = create(ArtifactRefSchema, {
			artifactKind: "test-fixture",
			digest,
			integrityDigest: digest,
			mediaType: "application/octet-stream",
			sizeBytes: 6n,
		});
		const uploadName = "tenants/t-1/projects/p-1/artifactUploads/resume-1";
		const createTime = timestampFromDate(new Date(runtime.nowMs()));
		let began = false;
		let beginCalls = 0;
		let committedOffset = 0n;
		let nextChunkIndex = 0n;
		let chunkCalls = 0;
		let corruptDownload = false;
		const session = (state = ArtifactUploadState.OPEN) => ({
			artifact,
			committedOffset,
			createTime,
			etag: `etag-${committedOffset}`,
			expireTime: timestampFromDate(new Date(runtime.nowMs() + 7_200_000)),
			name: uploadName,
			nextChunkIndex,
			revision: nextChunkIndex + 1n,
			state,
			updateTime: createTime,
		});
		const receipt = {
			artifact,
			expireTime: timestampFromDate(new Date(runtime.nowMs() + 86_400_000)),
			receiptDigest: `sha256:${"7".repeat(64)}`,
			verifiedAt: timestampFromDate(new Date(runtime.nowMs() + 1_000)),
		};
		const transport = testTransport((router) => {
			router.service(ArtifactService, {
				getArtifactUpload(request) {
					assert.equal(request.name, uploadName);
					if (!began) throw new ConnectError("not found", Code.NotFound);
					return { upload: session() };
				},
				beginArtifactUpload(request, context) {
					beginCalls += 1;
					began = true;
					assert.equal(request.parent, "tenants/t-1/projects/p-1");
					assert.equal(request.uploadId, "resume-1");
					assert.match(request.context?.canonicalRequestDigest ?? "", /^sha256:/);
					assert.match(context.requestHeader.get("idempotency-key") ?? "", /^artifact-transfer:/);
					return { upload: session() };
				},
				uploadArtifactChunk(request) {
					chunkCalls += 1;
					assert.equal(request.offset, committedOffset);
					assert.equal(request.chunkIndex, nextChunkIndex);
					assert.match(request.context?.canonicalRequestDigest ?? "", /^sha256:/);
					if (chunkCalls === 2) throw new ConnectError("process lost", Code.Aborted);
					committedOffset += BigInt(request.data.byteLength);
					nextChunkIndex += 1n;
					return { upload: session() };
				},
				finalizeArtifactUpload(request) {
					assert.equal(committedOffset, 6n);
					assert.match(request.context?.canonicalRequestDigest ?? "", /^sha256:/);
					return {
						stagingReceipt: receipt,
						upload: { ...session(ArtifactUploadState.FINALIZED), stagingReceipt: receipt },
					};
				},
				commitArtifact(request) {
					assert.match(request.command?.context?.canonicalRequestDigest ?? "", /^sha256:/);
					return { artifact };
				},
				async *downloadArtifact() {
					const first = content.subarray(0, 3);
					const second = content.subarray(3);
					yield {
						artifact,
						chunkDigest: `sha256:${createHash("sha256").update(first).digest("hex")}`,
						data: first,
						offset: 0n,
					};
					yield {
						artifact,
						chunkDigest: corruptDownload
							? `sha256:${"0".repeat(64)}`
							: `sha256:${createHash("sha256").update(second).digest("hex")}`,
						complete: true,
						data: second,
						offset: 3n,
					};
				},
			});
		});

		const first = MindcladeClient.withTransport(setup.config, transport, runtime);
		await assert.rejects(
			first.artifacts.upload(artifact, content, { chunkBytes: 3, uploadId: "resume-1" }),
			(reason: unknown) => reason instanceof MindcladeError && reason.code === Code.Aborted,
		);
		const second = MindcladeClient.withTransport(setup.config, transport, runtime);
		const resumed = await second.artifacts.upload(artifact, content, {
			chunkBytes: 3,
			uploadId: "resume-1",
		});
		assert.equal(resumed.receiptDigest, receipt.receiptDigest);
		assert.equal(beginCalls, 1);
		assert.equal(chunkCalls, 3);
		const committed = await second.artifacts.commit(resumed, {
			idempotencyKey: "commit-resume-1",
		});
		assert.equal(committed.digest, digest);
		const downloaded: Uint8Array[] = [];
		assert.equal(
			await second.artifacts.download(artifact, (chunk) => {
				downloaded.push(chunk);
			}),
			6n,
		);
		assert.deepEqual(Buffer.concat(downloaded), Buffer.from(content));
		const directory = await mkdtemp(join(tmpdir(), "mindclade-sdk-artifact-"));
		try {
			const destination = join(directory, "artifact.bin");
			assert.equal(await second.artifacts.downloadFile(artifact, destination), 6n);
			assert.deepEqual(await readFile(destination), Buffer.from(content));
			assert.equal((await stat(destination)).mode & 0o777, 0o600);

			const existing = join(directory, "existing.bin");
			await writeFile(existing, "caller-owned", { mode: 0o600 });
			await assert.rejects(
				second.artifacts.downloadFile(artifact, existing),
				(reason: unknown) => reason instanceof MindcladeError && reason.kind === "already_exists",
			);
			assert.equal(await readFile(existing, "utf8"), "caller-owned");

			const cancelled = new AbortController();
			cancelled.abort();
			const cancelledPath = join(directory, "cancelled.bin");
			await assert.rejects(
				second.artifacts.downloadFile(artifact, cancelledPath, {
					signal: cancelled.signal,
				}),
				(reason: unknown) => reason instanceof MindcladeError && reason.kind === "cancelled",
			);
			await assert.rejects(readFile(cancelledPath), hasFilesystemCode("ENOENT"));

			const racePath = join(directory, "race.bin");
			const race = await Promise.allSettled([
				second.artifacts.downloadFile(artifact, racePath),
				second.artifacts.downloadFile(artifact, racePath),
			]);
			assert.equal(race.filter((result) => result.status === "fulfilled").length, 1);
			assert.equal(
				race.filter(
					(result) =>
						result.status === "rejected" &&
						result.reason instanceof MindcladeError &&
						result.reason.kind === "already_exists",
				).length,
				1,
			);
			assert.deepEqual(await readFile(racePath), Buffer.from(content));

			corruptDownload = true;
			const corruptPath = join(directory, "corrupt.bin");
			await assert.rejects(
				second.artifacts.downloadFile(artifact, corruptPath),
				(reason: unknown) => reason instanceof MindcladeError && reason.kind === "protocol",
			);
			await assert.rejects(readFile(corruptPath), hasFilesystemCode("ENOENT"));
			assert.deepEqual(
				(await readdir(directory)).filter((name) => name.startsWith(".mindclade-download-")),
				[],
			);
		} finally {
			await rm(directory, { force: true, recursive: true });
		}
		corruptDownload = true;
		await assert.rejects(
			second.artifacts.download(artifact, () => undefined),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "protocol",
		);
	});

	test("artifact upload terminal transitions enforce generated lifecycle state", async () => {
		const runtime = new FakeRuntime();
		const setup = config(runtime, { attempts: 1 });
		const base = {
			artifact: {
				digest: `sha256:${"a".repeat(64)}`,
				mediaType: "application/octet-stream",
			},
			committedOffset: 0n,
			etag: "etag-2",
			name: "tenants/t-1/projects/p-1/artifactUploads/terminal-1",
			nextChunkIndex: 0n,
			revision: 2n,
		};
		const transport = testTransport((router) => {
			router.service(ArtifactService, {
				abortArtifactUpload() {
					return { upload: { ...base, state: ArtifactUploadState.ABORTED } };
				},
				quarantineArtifactUpload() {
					return { upload: { ...base, state: ArtifactUploadState.QUARANTINED } };
				},
			});
		});
		const client = MindcladeClient.withTransport(setup.config, transport, runtime);
		const aborted = await client.artifacts.abortUpload(base.name, "etag-1", "CLIENT_CANCELLED", {
			idempotencyKey: "abort-terminal-1",
		});
		assert.equal(aborted.state, ArtifactUploadState.ABORTED);
		const quarantined = await client.artifacts.quarantineUpload(
			base.name,
			"etag-1",
			"DIGEST_MISMATCH",
			{ idempotencyKey: "quarantine-terminal-1" },
		);
		assert.equal(quarantined.state, ArtifactUploadState.QUARANTINED);
	});
});

test("recording transport covers unary and streaming generated clients without payloads", async () => {
	const runtime = new FakeRuntime();
	const setup = config(runtime, { attempts: 1 });
	const recorder = new RecordingTransport(
		testTransport((router) => {
			router.service(OperationService, {
				getOperation() {
					return {
						operation: {
							done: true,
							operationId: "operations/secret-payload-id",
							state: OperationState.SUCCEEDED,
						},
					};
				},
				async *watchOperation() {
					yield {
						operation: {
							done: true,
							operationId: "operations/secret-stream-id",
							state: OperationState.SUCCEEDED,
						},
						sequence: 1n,
					};
				},
			});
		}),
	);
	const client = MindcladeClient.withTransport(setup.config, recorder, runtime);
	await client.operations.get("operations/secret-payload-id");
	for await (const _update of client.operations.watch("operations/secret-stream-id")) {
		// Consume the generated stream through the complete transport seam.
	}
	assert.deepEqual(
		recorder.calls.map(({ method, streaming }) => ({ method, streaming })),
		[
			{
				method: "/mindclade.internal.job.v1.OperationService/GetOperation",
				streaming: false,
			},
			{
				method: "/mindclade.internal.job.v1.OperationService/WatchOperation",
				streaming: true,
			},
		],
	);
	assert.match(recorder.calls[0]?.headerKeys.join(",") ?? "", /authorization/);
	assert.doesNotMatch(JSON.stringify(recorder.calls), /secret-(payload|stream)-id/);
});

test("raw estate covers all fifteen internal services and a descriptor escape hatch", () => {
	const runtime = new FakeRuntime();
	const setup = config(runtime);
	const transport = testTransport(() => undefined);
	const raw = MindcladeClient.withTransport(setup.config, transport, runtime).raw;
	const clients = [
		raw.admin,
		raw.agents,
		raw.artifacts,
		raw.datasets,
		raw.evaluations,
		raw.experiments,
		raw.inference,
		raw.jobs,
		raw.operations,
		raw.runs,
		raw.models,
		raw.policy,
		raw.training,
		raw.workflows,
		raw.approvals,
	];
	assert.equal(clients.length, 15);
	assert.equal(typeof raw.forService(TrainingService).createTrainingRun, "function");
});

test("dataset and model facades bind identity and preserve opaque pagination", async () => {
	const runtime = new FakeRuntime();
	const setup = config(runtime, { attempts: 1 });
	const parent = "tenants/t-1/projects/p-1";
	const datasetName = `${parent}/datasets/dataset-1`;
	const datasetRelease = `${datasetName}/releases/v1`;
	const modelName = `${parent}/models/model-1`;
	const modelRelease = `${modelName}/releases/v1`;
	const contexts: Array<{ idempotencyKey: string; principalId: string }> = [];
	const transport = testTransport((router) => {
		router.service(DatasetService, {
			createDataset(request, context) {
				assert.equal(context.requestHeader.get("idempotency-key"), "dataset-create-1");
				assert.equal(request.command?.project?.name, parent);
				contexts.push({
					idempotencyKey: request.command?.context?.idempotencyKey ?? "",
					principalId: request.command?.context?.principalId ?? "",
				});
				return { operation: { operationId: "operations/dataset-create" } };
			},
			getDataset() {
				return { dataset: { name: datasetName } };
			},
			listDatasets(request) {
				assert.equal(request.page?.pageToken, "opaque-dataset-in");
				return { page: { nextPageToken: "opaque-dataset-out" } };
			},
			updateDataset() {
				return { operation: { operationId: "operations/dataset-update" } };
			},
			publishDatasetRelease() {
				return { operation: { operationId: "operations/dataset-publish" } };
			},
			revokeDatasetRelease() {
				return { operation: { operationId: "operations/dataset-revoke" } };
			},
			getDatasetRelease() {
				return { datasetRelease: { name: datasetRelease } };
			},
			listDatasetReleases() {
				return { page: { nextPageToken: "opaque-release-out" } };
			},
		});
		router.service(ModelService, {
			registerModel(request) {
				assert.equal(request.command?.project?.name, parent);
				contexts.push({
					idempotencyKey: request.command?.context?.idempotencyKey ?? "",
					principalId: request.command?.context?.principalId ?? "",
				});
				return { operation: { operationId: "operations/model-register" } };
			},
			getModel() {
				return { model: { name: modelName } };
			},
			listModels(request) {
				assert.equal(request.page?.pageToken, "opaque-model-in");
				return { page: { nextPageToken: "opaque-model-out" } };
			},
			registerModelRelease() {
				return { operation: { operationId: "operations/model-release" } };
			},
			getModelRelease() {
				return { modelRelease: { name: modelRelease } };
			},
			listModelReleases() {
				return { page: { nextPageToken: "opaque-model-release-out" } };
			},
			promoteModelRelease() {
				return { operation: { operationId: "operations/model-promote" } };
			},
			revokeModelRelease() {
				return { operation: { operationId: "operations/model-revoke" } };
			},
		});
	});
	const client = MindcladeClient.withTransport(setup.config, transport, runtime);
	assert.equal(
		(
			await client.datasets.create(
				{ context: { principalId: "forged" }, datasetId: "dataset-1" },
				{ idempotencyKey: "dataset-create-1" },
			)
		).operationId,
		"operations/dataset-create",
	);
	assert.equal((await client.datasets.get({ name: datasetName })).name, datasetName);
	assert.equal(
		(await client.datasets.list({ page: { pageToken: "opaque-dataset-in", pageSize: 25 } })).page
			?.nextPageToken,
		"opaque-dataset-out",
	);
	await client.datasets.update(
		{ dataset: { name: datasetName }, etag: "etag-1" },
		{ idempotencyKey: "dataset-update-1" },
	);
	await client.datasets.publishRelease(
		{ dataset: { name: datasetName }, releaseId: "v1" },
		{ idempotencyKey: "dataset-publish-1" },
	);
	await client.datasets.revokeRelease(
		{ datasetRelease: { name: datasetRelease }, etag: "etag-r", reason: "superseded" },
		{ idempotencyKey: "dataset-revoke-1" },
	);
	assert.equal((await client.datasets.getRelease({ name: datasetRelease })).name, datasetRelease);
	assert.equal(
		(await client.datasets.listReleases({ parent: datasetName })).page?.nextPageToken,
		"opaque-release-out",
	);
	assert.equal(
		(
			await client.models.register(
				{ context: { principalId: "forged" }, modelId: "model-1" },
				{ idempotencyKey: "model-register-1" },
			)
		).operationId,
		"operations/model-register",
	);
	assert.equal((await client.models.get({ name: modelName })).name, modelName);
	assert.equal(
		(await client.models.list({ page: { pageToken: "opaque-model-in" } })).page?.nextPageToken,
		"opaque-model-out",
	);
	await client.models.registerRelease(
		{ model: { name: modelName }, releaseId: "v1" },
		{ idempotencyKey: "model-release-1" },
	);
	assert.equal((await client.models.getRelease({ name: modelRelease })).name, modelRelease);
	assert.equal(
		(await client.models.listReleases({ parent: modelName })).page?.nextPageToken,
		"opaque-model-release-out",
	);
	await client.models.promoteRelease(
		{ modelRelease: { name: modelRelease }, etag: "etag-m" },
		{ idempotencyKey: "model-promote-1" },
	);
	await client.models.revokeRelease(
		{ modelRelease: { name: modelRelease }, etag: "etag-m2", reason: "unsafe" },
		{ idempotencyKey: "model-revoke-1" },
	);
	assert.deepEqual(contexts, [
		{ idempotencyKey: "dataset-create-1", principalId: "principals/worker-1" },
		{ idempotencyKey: "model-register-1", principalId: "principals/worker-1" },
	]);
});

test("inference facade binds identity, publishes fenced results, and resumes exact cursors", async () => {
	const runtime = new FakeRuntime({
		randomValues: [0, 0, 0],
		requestIds: [
			"submit-request",
			"get-request",
			"commit-request",
			"watch-request",
			"wait-request",
		],
	});
	const setup = config(runtime);
	const requestName = "inferenceRequests/request-1";
	const operationName = "operations/inference-1";
	const resultName = "inferenceResults/result-1";
	let watchCalls = 0;
	const delegate = testTransport((router) => {
		router.service(InferenceService, {
			submitInference(request, context) {
				assert.equal(request.inferenceRequest?.tenantId, "tenants/t-1");
				assert.equal(request.inferenceRequest?.projectId, "projects/p-1");
				assert.equal(request.inferenceRequest?.context?.principalId, "principals/worker-1");
				assert.equal(request.inferenceRequest?.context?.idempotencyKey, "inference-submit-1");
				assert.match(request.inferenceRequest?.context?.canonicalRequestDigest ?? "", /^sha256:/);
				assert.equal(context.requestHeader.get("idempotency-key"), "inference-submit-1");
				return { operation: { operationId: operationName } };
			},
			getInferenceRequest(request) {
				assert.equal(request.name, requestName);
				return {
					inferenceRequest: {
						name: requestName,
						tenantId: "tenants/t-1",
						projectId: "projects/p-1",
					},
				};
			},
			getInferenceResult(request) {
				assert.equal(request.operationName, operationName);
				return {
					operation: { done: true, operationId: operationName, state: OperationState.SUCCEEDED },
					result: { name: resultName, requestDigest: "sha256:request" },
				};
			},
			commitInferenceResult(request, context) {
				assert.equal(request.inferenceRequest?.name, requestName);
				assert.equal(request.context?.principalId, "principals/worker-1");
				assert.equal(request.context?.idempotencyKey, "inference-commit-1");
				assert.match(request.context?.canonicalRequestDigest ?? "", /^sha256:/);
				assert.equal(context.requestHeader.get("idempotency-key"), "inference-commit-1");
				return {
					operation: { done: true, operationId: operationName, state: OperationState.SUCCEEDED },
					result: { name: resultName, requestDigest: "sha256:request" },
				};
			},
			async *watchInference(request) {
				watchCalls += 1;
				assert.equal(request.operationName, operationName);
				if (watchCalls === 1) {
					assert.equal(request.cursor, undefined);
					yield {
						message: create(InferenceStreamMessageSchema, {
							requestName,
							resumeToken: "cursor-1",
							sequence: 1n,
							update: {
								case: "progress",
								value: { completionBasisPoints: 5000, lifecycleState: "RUNNING" },
							},
						}),
					};
					throw new ConnectError("transient disconnect", Code.Unavailable);
				}
				if (watchCalls === 2) {
					assert.equal(request.cursor?.requestName, requestName);
					assert.equal(request.cursor?.afterSequence, 1n);
					assert.equal(request.cursor?.resumeToken, "cursor-1");
					yield {
						message: create(InferenceStreamMessageSchema, {
							requestName,
							resumeToken: "cursor-1",
							sequence: 1n,
							update: { case: "heartbeat", value: {} },
						}),
					};
					yield {
						message: create(InferenceStreamMessageSchema, {
							requestName,
							resumeToken: "cursor-2",
							sequence: 2n,
							update: { case: "finalResult", value: { resultDigest: "sha256:result" } },
						}),
					};
					return;
				}
				yield {
					message: create(InferenceStreamMessageSchema, {
						requestName,
						resumeToken: "cursor-terminal",
						sequence: 1n,
						update: { case: "finalResult", value: { resultDigest: "sha256:result" } },
					}),
				};
			},
		});
	});
	const recorder = new RecordingTransport(delegate);
	const client = MindcladeClient.withTransport(setup.config, recorder, runtime);
	const intent = inferenceRequest({
		context: { principalId: "caller-forged" },
		name: requestName,
		projectId: "caller-project",
		tenantId: "caller-tenant",
	});
	const operation = await client.inference.submit(intent, {
		idempotencyKey: "inference-submit-1",
	});
	assert.equal(operation.operationId, operationName);
	const admitted = await client.inference.getRequest(requestName);
	assert.equal(admitted.name, requestName);
	const committed = await client.inference.commitResult(
		{
			fence: {},
			inferenceRequest: { name: requestName },
			requestDigest: "sha256:request",
			result: { name: resultName },
		},
		{ idempotencyKey: "inference-commit-1" },
	);
	assert.equal(committed[0].name, resultName);
	const cases: string[] = [];
	for await (const message of client.inference.watch(operationName)) {
		cases.push(message.update.case ?? "missing");
	}
	assert.deepEqual(cases, ["progress", "heartbeat", "finalResult"]);
	assert.equal(watchCalls, 2);
	const terminal = await client.inference.wait(operationName);
	assert.equal(terminal[0].name, resultName);
	assert.equal(terminal[1].operationId, operationName);
	assert.equal(watchCalls, 3);
	assert.deepEqual(
		recorder.calls
			.filter((call) => call.method.includes("InferenceService"))
			.map((call) => call.method),
		[
			"/mindclade.internal.inference.v1.InferenceService/SubmitInference",
			"/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest",
			"/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult",
			"/mindclade.internal.inference.v1.InferenceService/WatchInference",
			"/mindclade.internal.inference.v1.InferenceService/WatchInference",
			"/mindclade.internal.inference.v1.InferenceService/WatchInference",
			"/mindclade.internal.inference.v1.InferenceService/GetInferenceResult",
		],
	);
});
