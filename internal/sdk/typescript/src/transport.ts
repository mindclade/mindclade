import type {
	DescMessage,
	DescMethodStreaming,
	DescMethodUnary,
	MessageInitShape,
} from "@bufbuild/protobuf";
import type { ContextValues, StreamResponse, Transport, UnaryResponse } from "@connectrpc/connect";
import { createGrpcTransport } from "@connectrpc/connect-node";
import type { AccessToken } from "./auth.js";
import type { ClientConfig } from "./config.js";
import { MindcladeError } from "./error.js";
import type { Runtime } from "./runtime.js";

/** Creates the official native-gRPC Node transport used by the Go runtime. */
export const createNodeTransport = (config: ClientConfig): Transport => {
	const url = new URL(config.endpoint);
	const nodeOptions =
		config.caPem === undefined && config.serverName === undefined
			? undefined
			: {
					rejectUnauthorized: true,
					...(config.caPem === undefined ? {} : { ca: config.caPem }),
					...(config.serverName === undefined ? {} : { servername: config.serverName }),
				};
	if (url.protocol === "http:") {
		return createGrpcTransport({
			baseUrl: config.endpoint,
			defaultTimeoutMs: config.defaultTimeoutMs,
			readMaxBytes: 16 * 1_024 * 1_024,
			useBinaryFormat: true,
			writeMaxBytes: 16 * 1_024 * 1_024,
		});
	}
	return createGrpcTransport({
		baseUrl: config.endpoint,
		defaultTimeoutMs: config.defaultTimeoutMs,
		readMaxBytes: 16 * 1_024 * 1_024,
		useBinaryFormat: true,
		writeMaxBytes: 16 * 1_024 * 1_024,
		...(nodeOptions === undefined ? {} : { nodeOptions }),
	});
};

/** Applies auth, tenant expectations, generated correlation IDs, and a total
 * deadline to both ergonomic and raw generated clients. */
export class AuthenticatedTransport implements Transport {
	readonly #delegate: Transport;
	readonly #config: ClientConfig;
	readonly #runtime: Runtime;

	constructor(delegate: Transport, config: ClientConfig, runtime: Runtime) {
		this.#delegate = delegate;
		this.#config = config;
		this.#runtime = runtime;
	}

	async unary<I extends DescMessage, O extends DescMessage>(
		method: DescMethodUnary<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: MessageInitShape<I>,
		contextValues?: ContextValues,
	): Promise<UnaryResponse<I, O>> {
		const deadline = deadlineSignal(signal, timeoutMs ?? this.#config.defaultTimeoutMs);
		const started = this.#runtime.nowMs();
		try {
			const headers = await this.#headers(header, deadline.signal);
			const remaining = Math.max(1, deadline.timeoutMs - (this.#runtime.nowMs() - started));
			return await this.#delegate.unary(
				method,
				deadline.signal,
				remaining,
				headers,
				input,
				contextValues,
			);
		} finally {
			deadline.dispose();
		}
	}

	async stream<I extends DescMessage, O extends DescMessage>(
		method: DescMethodStreaming<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: AsyncIterable<MessageInitShape<I>>,
		contextValues?: ContextValues,
	): Promise<StreamResponse<I, O>> {
		const deadline = deadlineSignal(signal, timeoutMs ?? this.#config.defaultTimeoutMs);
		const started = this.#runtime.nowMs();
		try {
			const headers = await this.#headers(header, deadline.signal);
			const remaining = Math.max(1, deadline.timeoutMs - (this.#runtime.nowMs() - started));
			const response = await this.#delegate.stream(
				method,
				deadline.signal,
				remaining,
				headers,
				input,
				contextValues,
			);
			return {
				...response,
				message: finalize(response.message, deadline.dispose),
			};
		} catch (error) {
			deadline.dispose();
			throw error;
		}
	}

	async #headers(initial: HeadersInit | undefined, signal: AbortSignal): Promise<Headers> {
		const headers = new Headers(initial);
		if (!headers.has("x-request-id")) headers.set("x-request-id", this.#runtime.requestId());
		if (!headers.has("x-trace-id")) headers.set("x-trace-id", headers.get("x-request-id") ?? "");
		headers.set("x-mindclade-sdk", "mindclade-internal-typescript-sdk/0.1");
		headers.set("x-mindclade-expected-tenant", this.#config.identity.tenantId);
		headers.set("x-mindclade-expected-project", this.#config.identity.projectId);
		headers.set("x-mindclade-expected-principal", this.#config.identity.principalId);
		const provider = this.#config.tokenProvider;
		if (provider !== undefined) {
			let token: AccessToken;
			try {
				token = await withAbort(provider.getToken(this.#config.audience, signal), signal);
			} catch {
				if (signal.aborted) throw abortReason(signal);
				throw MindcladeError.authentication();
			}
			headers.set("authorization", token.authorizationHeader(this.#runtime.nowMs()));
		}
		return headers;
	}
}

const deadlineSignal = (
	parent: AbortSignal | undefined,
	timeoutMs: number,
): { readonly signal: AbortSignal; readonly timeoutMs: number; readonly dispose: () => void } => {
	const controller = new AbortController();
	const abort = (): void => controller.abort(parent?.reason);
	if (parent?.aborted === true) abort();
	else parent?.addEventListener("abort", abort, { once: true });
	const timer = setTimeout(() => controller.abort(MindcladeError.deadlineExceeded()), timeoutMs);
	timer.unref();
	return {
		signal: controller.signal,
		timeoutMs,
		dispose: () => {
			clearTimeout(timer);
			parent?.removeEventListener("abort", abort);
		},
	};
};

const withAbort = async <T>(promise: Promise<T>, signal: AbortSignal): Promise<T> => {
	if (signal.aborted) throw abortReason(signal);
	let onAbort = (): void => undefined;
	const aborted = new Promise<never>((_resolve, reject) => {
		onAbort = () => reject(abortReason(signal));
		signal.addEventListener("abort", onAbort, { once: true });
	});
	try {
		return await Promise.race([promise, aborted]);
	} finally {
		signal.removeEventListener("abort", onAbort);
	}
};

const abortReason = (signal: AbortSignal): MindcladeError =>
	signal.reason instanceof MindcladeError ? signal.reason : MindcladeError.cancelled();

const finalize = async function* <T>(
	source: AsyncIterable<T>,
	dispose: () => void,
): AsyncGenerator<T> {
	try {
		yield* source;
	} finally {
		dispose();
	}
};
