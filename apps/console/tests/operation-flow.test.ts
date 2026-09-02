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
	Environment,
	FakeRuntime,
	MindcladeClient,
	MindcladeError,
	OperationState,
	RecordingTransport,
	type TokenProvider,
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
				case "ListOperations":
					return {
						operations: [operation(OperationState.RUNNING, false)],
						page: { nextPageToken: "next-1" },
					};
				case "GetOperation":
					return { operation: operation(OperationState.RUNNING, false) };
				case "CancelOperation":
					return { operation: operation(OperationState.CANCELLING, false) };
				case "ResolveArtifactAlias":
					return { artifact: artifact() };
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
				? [{ operation: operation(OperationState.SUCCEEDED, true), sequence: 1n }]
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

const operation = (state: OperationState, done: boolean) => ({
	done,
	etag: "operation-etag-1",
	jobId: "jobs/job-1",
	operationId: "operations/op-1",
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
		new FakeRuntime({ now: Date.now() }),
	);
	return { controller: new OperationController(client), delegate, recorder };
};

describe("internal console SDK integration", () => {
	test("routes list, get, cancel, watch, and verified artifact workflows", async () => {
		const { controller, delegate, recorder } = setup();
		const page = await controller.firstPage({ timeoutMs: 1_000 });
		assert.equal(page.items[0]?.phase, "running");
		assert.equal(page.nextPageToken, "next-1");
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

	test("preserves cancellation, deadlines, and sanitized SDK errors", async () => {
		const cancelled = setup();
		const controller = new AbortController();
		controller.abort();
		await assert.rejects(
			cancelled.controller.get("operations/op-1", { signal: controller.signal }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "cancelled",
		);

		const deadline = setup();
		deadline.delegate.blockGet = true;
		// The SDK deliberately unrefs deadline timers so an abandoned client cannot
		// pin a process. Keep this test process alive while proving the deadline.
		const keepAlive = setTimeout(() => undefined, 100);
		try {
			await assert.rejects(
				deadline.controller.get("operations/op-1", { timeoutMs: 5 }),
				(reason: unknown) =>
					reason instanceof MindcladeError && reason.kind === "deadline_exceeded",
			);
		} finally {
			clearTimeout(keepAlive);
		}

		const failed = setup();
		failed.delegate.failGet = true;
		await assert.rejects(failed.controller.get("operations/op-1"), (reason: unknown) => {
			assert.ok(reason instanceof MindcladeError);
			assert.equal(reason.kind, "remote");
			assert.doesNotMatch(reason.message, /sensitive remote detail/);
			return true;
		});
	});
});
