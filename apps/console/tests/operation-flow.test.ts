import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, test } from "node:test";

import {
	create,
	type DescMessage,
	type DescMethodStreaming,
	type DescMethodUnary,
	type MessageInitShape,
} from "@bufbuild/protobuf";
// `Transport` is the injection seam `MindcladeClient.withTransport` accepts, and
// `ConnectError`/`Code` are how a fake *server* reports a status. Both configure
// a fake below the SDK; no console source parses a status code or a wire type.
import {
	Code,
	ConnectError,
	type ContextValues,
	type StreamResponse,
	type Transport,
	type UnaryResponse,
} from "@connectrpc/connect";
import {
	AccessToken,
	AuthorizationError,
	CancelledError,
	Environment,
	FakeRuntime,
	MAX_MESSAGE_BYTES,
	MindcladeClient,
	MindcladeError,
	OperationState,
	RecordingTransport,
	type TokenProvider,
	TransportError,
	ValidationError,
} from "@mindclade/internal-sdk";

import { OperationController } from "../features/operations/operation-client.js";
import { createControlPlaneConfig } from "../lib/control-plane.js";

const artifactContent = new TextEncoder().encode("verified-result");
const artifactDigest = `sha256:${createHash("sha256").update(artifactContent).digest("hex")}`;

class StaticTokenProvider implements TokenProvider {
	async getToken(_audience: string, signal: AbortSignal): Promise<AccessToken> {
		if (signal.aborted) throw signal.reason;
		return new AccessToken("short-lived-test-token", Date.now() + 60 * 60 * 1_000);
	}
}

class ScenarioTransport implements Transport {
	readonly inputs: Array<{ readonly method: string; readonly value: unknown }> = [];
	failGet = false;
	blockGet = false;
	oversizedArtifact = false;

	async unary<I extends DescMessage, O extends DescMessage>(
		method: DescMethodUnary<I, O>,
		signal: AbortSignal | undefined,
		_timeoutMs: number | undefined,
		_header: HeadersInit | undefined,
		input: MessageInitShape<I>,
		_contextValues?: ContextValues,
	): Promise<UnaryResponse<I, O>> {
		const request = create(method.input, input) as unknown as Record<string, unknown>;
		this.inputs.push({ method: method.name, value: request });
		if (method.name === "GetOperation" && this.blockGet) await waitForAbort(signal);
		if (method.name === "GetOperation" && this.failGet) {
			throw new ConnectError("sensitive remote detail", Code.PermissionDenied);
		}
		const response = (() => {
			switch (method.name) {
				case "ListOperations": {
					const paging = request.page as { readonly pageToken?: string } | undefined;
					return (paging?.pageToken ?? "") === ""
						? {
								operations: [operation("operations/op-1", OperationState.RUNNING, false)],
								page: { nextPageToken: "next-1" },
							}
						: {
								operations: [operation("operations/op-2", OperationState.SUCCEEDED, true)],
								page: { nextPageToken: "" },
							};
				}
				case "GetOperation":
					return { operation: operation("operations/op-1", OperationState.RUNNING, false) };
				case "CancelOperation":
					return { operation: operation("operations/op-1", OperationState.CANCELLING, false) };
				case "ResolveArtifactAlias":
					return {
						artifact: this.oversizedArtifact
							? { ...artifact(), sizeBytes: BigInt(MAX_MESSAGE_BYTES + 1) }
							: artifact(),
					};
				default:
					throw new ConnectError("unconfigured fake method", Code.Unimplemented);
			}
		})();
		return unaryResponse(method, response);
	}

	async stream<I extends DescMessage, O extends DescMessage>(
		method: DescMethodStreaming<I, O>,
		_signal: AbortSignal | undefined,
		_timeoutMs: number | undefined,
		_header: HeadersInit | undefined,
		_input: AsyncIterable<MessageInitShape<I>>,
		_contextValues?: ContextValues,
	): Promise<StreamResponse<I, O>> {
		this.inputs.push({ method: method.name, value: undefined });
		const values =
			method.name === "WatchOperation"
				? [
						{
							operation: operation("operations/op-1", OperationState.SUCCEEDED, true),
							sequence: 1n,
						},
					]
				: method.name === "DownloadArtifact"
					? [
							{
								artifact: artifact(),
								chunkDigest: artifactDigest,
								complete: true,
								data: artifactContent,
								offset: 0n,
							},
						]
					: [];
		return streamResponse(method, values);
	}
}

const operation = (operationId: string, state: OperationState, done: boolean) => ({
	done,
	etag: "operation-etag-1",
	jobId: "jobs/job-1",
	operationId,
	projectId: "project-1",
	resourceVersion: 7n,
	state,
	tenantId: "tenant-1",
});

const artifact = () => ({
	digest: artifactDigest,
	mediaType: "application/json",
	sizeBytes: BigInt(artifactContent.byteLength),
});

const unaryResponse = <I extends DescMessage, O extends DescMessage>(
	method: DescMethodUnary<I, O>,
	value: unknown,
): UnaryResponse<I, O> => ({
	header: new Headers(),
	message: create(method.output, value as MessageInitShape<O>),
	method,
	service: method.parent,
	stream: false,
	trailer: new Headers(),
});

const streamResponse = <I extends DescMessage, O extends DescMessage>(
	method: DescMethodStreaming<I, O>,
	values: readonly unknown[],
): StreamResponse<I, O> => ({
	header: new Headers(),
	message: (async function* () {
		for (const value of values) yield create(method.output, value as MessageInitShape<O>);
	})(),
	method,
	service: method.parent,
	stream: true,
	trailer: new Headers(),
});

const waitForAbort = async (signal: AbortSignal | undefined): Promise<never> =>
	await new Promise<never>((_resolve, reject) => {
		if (signal?.aborted === true) {
			reject(signal.reason);
			return;
		}
		signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
	});

const setup = (): {
	readonly controller: OperationController;
	readonly delegate: ScenarioTransport;
	readonly recorder: RecordingTransport;
} => {
	const config = createControlPlaneConfig({
		audience: "https://control-plane.test",
		endpoint: "https://control-plane.test:443",
		environment: Environment.Development,
		identity: {
			principalId: "console-service-1",
			projectId: "project-1",
			tenantId: "tenant-1",
		},
		tokenProvider: new StaticTokenProvider(),
	});
	const delegate = new ScenarioTransport();
	const recorder = new RecordingTransport(delegate);
	const client = MindcladeClient.withTransport(
		config,
		recorder,
		new FakeRuntime({ now: Date.now(), requestIds: ["console-request-1", "console-request-2"] }),
	);
	return { controller: new OperationController(client), delegate, recorder };
};

const listCalls = (recorder: RecordingTransport): number =>
	recorder.calls.filter((call) => call.method.endsWith("/ListOperations")).length;

describe("internal console SDK integration", () => {
	test("routes list, get, cancel, watch, and verified artifact workflows", async () => {
		const { controller, delegate, recorder } = setup();
		const page = await controller.firstPage({ timeoutMs: 1_000 });
		assert.equal(page.items[0]?.phase, "running");
		assert.equal(page.nextPageToken, "next-1");
		// Request ID is available on success, not only on failure.
		assert.equal(page.requestId, "console-request-1");
		// One page fetched: the SDK page traverses lazily, on demand.
		assert.equal(listCalls(recorder), 1);
		assert.equal((await controller.get("operations/op-1")).revision, "7");
		assert.equal(
			(
				await controller.cancel(
					"operations/op-1",
					"operation-etag-1",
					"operator request",
					"cancel-operation-1",
				)
			).phase,
			"cancelling",
		);
		const watched = [];
		for await (const update of controller.watch("operations/op-1")) watched.push(update.phase);
		assert.deepEqual(watched, ["succeeded"]);
		const result = await controller.resolveAndDownload("projects/project-1", "latest");
		assert.equal(new TextDecoder().decode(result.content), "verified-result");
		assert.equal(result.digest, artifactDigest);
		assert.deepEqual(
			recorder.calls.map((call) => call.method),
			[
				"/mindclade.internal.job.v1.OperationService/ListOperations",
				"/mindclade.internal.job.v1.OperationService/GetOperation",
				"/mindclade.internal.job.v1.OperationService/CancelOperation",
				"/mindclade.internal.job.v1.OperationService/WatchOperation",
				"/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias",
				"/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact",
			],
		);
		assert.ok(recorder.calls.every((call) => call.headerKeys.includes("authorization")));
		const cancellation = delegate.inputs.find((input) => input.method === "CancelOperation")
			?.value as { context?: { idempotencyKey?: string } };
		assert.equal(cancellation.context?.idempotencyKey, "cancel-operation-1");
	});

	test("traverses the whole cursor through the SDK page instead of a hand-rolled loop", async () => {
		const walked = setup();
		const seen: Array<readonly [string | undefined, string]> = [];
		for await (const view of walked.controller.pages()) {
			seen.push([view.nextPageToken, view.items[0]?.id ?? ""]);
		}
		assert.deepEqual(seen, [
			["next-1", "operations/op-1"],
			[undefined, "operations/op-2"],
		]);
		assert.equal(listCalls(walked.recorder), 2);
		const listed = walked.delegate.inputs
			.filter((input) => input.method === "ListOperations")
			.map((input) => (input.value as { page?: { pageToken?: string } }).page?.pageToken ?? "");
		// The opaque cursor is threaded by the SDK and reaches the server verbatim.
		assert.deepEqual(listed, ["", "next-1"]);

		const collected = setup();
		assert.deepEqual(
			(await collected.controller.listAll()).map((view) => view.id),
			["operations/op-1", "operations/op-2"],
		);
		assert.equal(listCalls(collected.recorder), 2);
	});

	test("forwards traversal budgets to the SDK rather than counting pages", async () => {
		const { controller } = setup();
		// The SDK owns the budget and fails the traversal loudly; the console
		// never truncates a list silently.
		await assert.rejects(
			controller.listAll({ limits: { maxPages: 1 } }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "pagination_limit",
		);
		await assert.rejects(
			controller.firstPage({ limits: { maxItems: 0 } }),
			(reason: unknown) => reason instanceof ValidationError,
		);
	});

	test("bounds an in-memory artifact by the SDK's published message ceiling", async () => {
		const rejected = setup();
		rejected.delegate.oversizedArtifact = true;
		await assert.rejects(
			rejected.controller.resolveAndDownload("projects/project-1", "latest"),
			(reason: unknown) =>
				reason instanceof ValidationError && /console byte limit/.test(reason.message),
		);
		// The bound is checked before any transfer is started.
		assert.ok(!rejected.recorder.calls.some((call) => call.method.endsWith("/DownloadArtifact")));

		const overridden = setup();
		overridden.delegate.oversizedArtifact = true;
		await assert.rejects(
			overridden.controller.resolveAndDownload("projects/project-1", "latest", {
				maximumBytes: MAX_MESSAGE_BYTES + 1,
			}),
			// An explicit override gets past the console bound; the SDK then
			// rejects the short stream against the declared size.
			(reason: unknown) => reason instanceof TransportError,
		);
		assert.ok(overridden.recorder.calls.some((call) => call.method.endsWith("/DownloadArtifact")));
	});

	test("preserves cancellation, deadlines, and sanitized SDK errors", async () => {
		const cancelled = setup();
		const controller = new AbortController();
		controller.abort();
		await assert.rejects(
			cancelled.controller.get("operations/op-1", { signal: controller.signal }),
			(reason: unknown) => reason instanceof CancelledError && reason.stableCode === "cancelled",
		);

		const deadline = setup();
		deadline.delegate.blockGet = true;
		// The SDK deliberately unrefs deadline timers so an abandoned client cannot
		// pin a process. Keep this test process alive while proving the deadline.
		const keepAlive = setTimeout(() => undefined, 100);
		try {
			await assert.rejects(
				deadline.controller.get("operations/op-1", { timeoutMs: 5 }),
				// The TypeScript hierarchy has no deadline class: a client-side
				// deadline is the base MindcladeError, so `kind` is the only
				// discriminator the SDK offers for it.
				(reason: unknown) =>
					reason instanceof MindcladeError && reason.kind === "deadline_exceeded",
			);
		} finally {
			clearTimeout(keepAlive);
		}

		const failed = setup();
		failed.delegate.failGet = true;
		await assert.rejects(failed.controller.get("operations/op-1"), (reason: unknown) => {
			// Discriminated by the SDK error class and its stable code, never by a
			// gRPC status number or a message string.
			assert.ok(reason instanceof AuthorizationError);
			assert.equal(reason.stableCode, "authorization");
			assert.equal(reason.retryable, false);
			assert.doesNotMatch(reason.message, /sensitive remote detail/);
			return true;
		});
	});
});
