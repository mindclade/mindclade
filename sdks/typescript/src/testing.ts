import type {
	DescMessage,
	DescMethodStreaming,
	DescMethodUnary,
	MessageInitShape,
} from "@bufbuild/protobuf";
import type { ContextValues, StreamResponse, Transport, UnaryResponse } from "@connectrpc/connect";

import type { Runtime } from "./runtime.js";

export interface RecordedTransportCall {
	readonly headerKeys: readonly string[];
	readonly method: string;
	readonly streaming: boolean;
	readonly timeoutMs: number | undefined;
}

/** Payload-free recorder that can wrap any Connect router/transport and all services. */
export class RecordingTransport implements Transport {
	readonly calls: RecordedTransportCall[] = [];
	readonly #delegate: Transport;

	constructor(delegate: Transport) {
		this.#delegate = delegate;
	}

	async unary<I extends DescMessage, O extends DescMessage>(
		method: DescMethodUnary<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: MessageInitShape<I>,
		contextValues?: ContextValues,
	): Promise<UnaryResponse<I, O>> {
		this.#record(method.parent.typeName, method.name, false, timeoutMs, header);
		return await this.#delegate.unary(method, signal, timeoutMs, header, input, contextValues);
	}

	async stream<I extends DescMessage, O extends DescMessage>(
		method: DescMethodStreaming<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: AsyncIterable<MessageInitShape<I>>,
		contextValues?: ContextValues,
	): Promise<StreamResponse<I, O>> {
		this.#record(method.parent.typeName, method.name, true, timeoutMs, header);
		return await this.#delegate.stream(method, signal, timeoutMs, header, input, contextValues);
	}

	#record(
		service: string,
		method: string,
		streaming: boolean,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
	): void {
		this.calls.push({
			headerKeys: [...new Headers(header).keys()].sort(),
			method: `/${service}/${method}`,
			streaming,
			timeoutMs,
		});
	}
}

/** Deterministic runtime used with an injected Connect router transport. */
export class FakeRuntime implements Runtime {
	now: number;
	readonly randomValues: number[];
	readonly sleeps: number[] = [];
	readonly requestIds: string[];

	constructor(
		options: {
			readonly now?: number;
			readonly randomValues?: readonly number[];
			readonly requestIds?: readonly string[];
		} = {},
	) {
		this.now = options.now ?? 1_800_000_000_000;
		this.randomValues = [...(options.randomValues ?? [0.5])];
		this.requestIds = [...(options.requestIds ?? ["test-request-id"])];
	}

	nowMs(): number {
		return this.now;
	}

	random(): number {
		return this.randomValues.shift() ?? 0.5;
	}

	requestId(): string {
		return this.requestIds.shift() ?? "test-request-id";
	}

	async sleep(milliseconds: number, signal?: AbortSignal): Promise<void> {
		if (signal?.aborted === true) throw signal.reason;
		this.sleeps.push(milliseconds);
		this.now += milliseconds;
	}
}
