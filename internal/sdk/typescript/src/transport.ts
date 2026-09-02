import {
	create,
	type DescMessage,
	type DescMethodStreaming,
	type DescMethodUnary,
	type MessageInitShape,
	type MessageShape,
} from "@bufbuild/protobuf";
import type {
	ContextValues,
	Interceptor,
	StreamRequest,
	StreamResponse,
	Transport,
	UnaryRequest,
	UnaryResponse,
} from "@connectrpc/connect";
import { createContextValues } from "@connectrpc/connect";
import { createGrpcTransport } from "@connectrpc/connect-node";
import type { AccessToken } from "./auth.js";
import { type ClientConfig, isReservedMetadata, validateMetadata } from "./config.js";
import { MindcladeError } from "./error.js";
import { platformMetadata } from "./platform.js";
import { isCredentialBearing } from "./response.js";
import type { Runtime } from "./runtime.js";

/**
 * Message-size ceiling, identical in every mindclade SDK.
 *
 * Payloads larger than this travel as artifacts, never as inline protobuf, so
 * the ceiling is a contract rather than a tuning knob.
 */
export const MAX_MESSAGE_BYTES = 8 * 1_024 * 1_024;

/**
 * Credential-bearing request metadata the SDK strips before every hop.
 *
 * Authentication is owned by the configured workload-identity provider. The
 * strip runs even in Local plaintext mode so the raw generated escape hatch
 * cannot leak a credential over an unencrypted transport, and it runs again
 * below the interceptor chain so an interceptor cannot forge one.
 */
const strippedCredentialHeaders: readonly string[] = Object.freeze([
	"authorization",
	"proxy-authorization",
	"cookie",
	"x-api-key",
	"x-goog-api-key",
]);

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
			readMaxBytes: MAX_MESSAGE_BYTES,
			useBinaryFormat: true,
			writeMaxBytes: MAX_MESSAGE_BYTES,
		});
	}
	return createGrpcTransport({
		baseUrl: config.endpoint,
		defaultTimeoutMs: config.defaultTimeoutMs,
		readMaxBytes: MAX_MESSAGE_BYTES,
		useBinaryFormat: true,
		writeMaxBytes: MAX_MESSAGE_BYTES,
		...(nodeOptions === undefined ? {} : { nodeOptions }),
	});
};

/**
 * Innermost layer: strips caller and interceptor credentials, then injects the
 * workload identity.
 *
 * It sits *below* the interceptor chain deliberately. Credential injection is
 * not an interceptable concern: an interceptor can neither observe the token
 * the SDK obtained nor substitute one of its own.
 */
class CredentialTransport implements Transport {
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
		const started = this.#runtime.nowMs();
		const headers = await this.#authorize(header, signal);
		return await this.#delegate.unary(
			method,
			signal,
			this.#remaining(timeoutMs, started),
			headers,
			input,
			contextValues,
		);
	}

	async stream<I extends DescMessage, O extends DescMessage>(
		method: DescMethodStreaming<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: AsyncIterable<MessageInitShape<I>>,
		contextValues?: ContextValues,
	): Promise<StreamResponse<I, O>> {
		const started = this.#runtime.nowMs();
		const headers = await this.#authorize(header, signal);
		return await this.#delegate.stream(
			method,
			signal,
			this.#remaining(timeoutMs, started),
			headers,
			input,
			contextValues,
		);
	}

	/** Credential acquisition is spent from the caller's budget, not added to it. */
	#remaining(timeoutMs: number | undefined, started: number): number | undefined {
		if (timeoutMs === undefined) return undefined;
		return Math.max(1, timeoutMs - (this.#runtime.nowMs() - started));
	}

	async #authorize(
		initial: HeadersInit | undefined,
		signal: AbortSignal | undefined,
	): Promise<Headers> {
		const headers = safeHeaders(initial);
		for (const name of strippedCredentialHeaders) headers.delete(name);
		const provider = this.#config.tokenProvider;
		if (provider === undefined) return headers;
		const active = signal ?? neverAborted();
		let token: AccessToken;
		try {
			token = await withAbort(provider.getToken(this.#config.audience, active), active);
		} catch {
			if (active.aborted) throw abortReason(active);
			throw MindcladeError.authentication();
		}
		headers.set("authorization", token.authorizationHeader(this.#runtime.nowMs()));
		return headers;
	}
}

type AnyRequest = StreamRequest | UnaryRequest;
type AnyResponse = StreamResponse | UnaryResponse;
type AnyFn = (request: AnyRequest) => Promise<AnyResponse>;

/**
 * Applies the configured Connect interceptors around one invocation.
 *
 * The first interceptor in the array is the outermost layer, matching the
 * ordering Connect itself documents.
 */
const chain = (next: AnyFn, interceptors: readonly Interceptor[]): AnyFn => {
	let applied = next;
	for (let index = interceptors.length - 1; index >= 0; index -= 1) {
		const interceptor = interceptors[index];
		if (interceptor !== undefined) applied = interceptor(applied) as AnyFn;
	}
	return applied;
};

const neverAborted = (): AbortSignal => new AbortController().signal;

/**
 * The caller's escape hatch: user-supplied Connect interceptors.
 *
 * `applyInterceptors` is not part of the package's public surface, so the chain
 * is built here. Interceptors see the request the SDK composed — correlation
 * IDs, tenancy expectations, custom metadata — but never a credential, because
 * the credential layer runs beneath them.
 */
class InterceptingTransport implements Transport {
	readonly #delegate: Transport;
	readonly #interceptors: readonly Interceptor[];
	readonly #endpoint: string;

	constructor(delegate: Transport, config: ClientConfig) {
		this.#delegate = delegate;
		this.#interceptors = config.interceptors;
		this.#endpoint = config.endpoint.replace(/\/+$/, "");
	}

	async unary<I extends DescMessage, O extends DescMessage>(
		method: DescMethodUnary<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: MessageInitShape<I>,
		contextValues?: ContextValues,
	): Promise<UnaryResponse<I, O>> {
		if (this.#interceptors.length === 0) {
			return await this.#delegate.unary(method, signal, timeoutMs, header, input, contextValues);
		}
		const request: UnaryRequest<I, O> = {
			contextValues: contextValues ?? createContextValues(),
			header: safeHeaders(header),
			message: create(method.input, input),
			method,
			requestMethod: "POST",
			service: method.parent,
			signal: signal ?? neverAborted(),
			stream: false,
			url: this.#url(method.parent.typeName, method.name),
		};
		const invoke: AnyFn = async (intercepted) =>
			await this.#delegate.unary(
				method,
				signal,
				timeoutMs,
				intercepted.header,
				(intercepted as UnaryRequest<I, O>).message,
				intercepted.contextValues,
			);
		return (await chain(invoke, this.#interceptors)(request)) as UnaryResponse<I, O>;
	}

	async stream<I extends DescMessage, O extends DescMessage>(
		method: DescMethodStreaming<I, O>,
		signal: AbortSignal | undefined,
		timeoutMs: number | undefined,
		header: HeadersInit | undefined,
		input: AsyncIterable<MessageInitShape<I>>,
		contextValues?: ContextValues,
	): Promise<StreamResponse<I, O>> {
		if (this.#interceptors.length === 0) {
			return await this.#delegate.stream(method, signal, timeoutMs, header, input, contextValues);
		}
		const request: StreamRequest<I, O> = {
			contextValues: contextValues ?? createContextValues(),
			header: safeHeaders(header),
			message: normalize(method.input, input),
			method,
			requestMethod: "POST",
			service: method.parent,
			signal: signal ?? neverAborted(),
			stream: true,
			url: this.#url(method.parent.typeName, method.name),
		};
		const invoke: AnyFn = async (intercepted) =>
			await this.#delegate.stream(
				method,
				signal,
				timeoutMs,
				intercepted.header,
				(intercepted as StreamRequest<I, O>).message,
				intercepted.contextValues,
			);
		return (await chain(invoke, this.#interceptors)(request)) as StreamResponse<I, O>;
	}

	#url(service: string, method: string): string {
		return `${this.#endpoint}/${service}/${method}`;
	}
}

const normalize = async function* <I extends DescMessage>(
	schema: I,
	source: AsyncIterable<MessageInitShape<I>>,
): AsyncGenerator<MessageShape<I>> {
	for await (const message of source) yield create(schema, message);
};

/**
 * Outermost layer: correlation IDs, tenancy expectations, SDK identity, custom
 * metadata, and the total call deadline.
 *
 * Composition, from the caller inwards:
 * metadata -> user interceptors -> credential injection -> Connect transport.
 */
export class AuthenticatedTransport implements Transport {
	readonly #delegate: Transport;
	readonly #config: ClientConfig;
	readonly #runtime: Runtime;

	constructor(delegate: Transport, config: ClientConfig, runtime: Runtime) {
		this.#delegate = new InterceptingTransport(
			new CredentialTransport(delegate, config, runtime),
			config,
		);
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
			const headers = this.#headers(header);
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
			const headers = this.#headers(header);
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

	#headers(initial: HeadersInit | undefined): Headers {
		const headers = safeHeaders(initial);
		for (const name of strippedCredentialHeaders) headers.delete(name);
		for (const [name, value] of Object.entries(this.#config.metadata)) {
			if (isCredentialBearing(name)) {
				throw MindcladeError.invalidArgument(
					`custom metadata may not carry credentials: ${name}`,
				);
			}
			if (isReservedMetadata(name)) {
				throw MindcladeError.invalidArgument(`custom metadata may not set the SDK-owned ${name}`);
			}
			headers.set(name, value);
		}
		if (!headers.has("x-request-id")) headers.set("x-request-id", this.#runtime.requestId());
		const requestId = headers.get("x-request-id") ?? "";
		validateMetadata("request ID", requestId, true);
		if (!headers.has("x-trace-id")) headers.set("x-trace-id", requestId);
		validateMetadata("trace ID", headers.get("x-trace-id") ?? "", true);
		headers.set("x-mindclade-sdk", platformMetadata(this.#config.omitPlatformMetadata));
		headers.set("x-mindclade-expected-tenant", this.#config.identity.tenantId);
		headers.set("x-mindclade-expected-project", this.#config.identity.projectId);
		headers.set("x-mindclade-expected-principal", this.#config.identity.principalId);
		return headers;
	}
}

const safeHeaders = (initial: HeadersInit | undefined): Headers => {
	try {
		return new Headers(initial);
	} catch {
		throw MindcladeError.invalidArgument("request metadata is invalid");
	}
};

const deadlineSignal = (
	parent: AbortSignal | undefined,
	timeoutMs: number,
): { readonly signal: AbortSignal; readonly timeoutMs: number; readonly dispose: () => void } => {
	if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > 86_400_000) {
		throw MindcladeError.invalidArgument(
			"call timeout must be positive and at most twenty-four hours",
		);
	}
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
