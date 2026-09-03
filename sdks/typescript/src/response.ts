import type { Code } from "@connectrpc/connect";

import type { ClientCore } from "./core.js";

/** Transport-level outcome of a completed call. */
export interface ResponseStatus {
	/** True for a call that completed without a Connect error. */
	readonly ok: boolean;
	/**
	 * Connect status of a failed call. Success carries no code because the
	 * Connect status enumeration has no `OK` member.
	 */
	readonly code: Code | undefined;
}

/** A successful result together with its sanitized transport envelope. */
export interface RawResponse<Value> {
	/** The ergonomic value the plain method would have returned. */
	readonly value: Value;
	readonly status: ResponseStatus;
	readonly requestId: string | undefined;
	readonly traceId: string | undefined;
	/** Allowlisted response metadata only; never credential-bearing. */
	readonly metadata: ReadonlyMap<string, string>;
}

/**
 * The response metadata an SDK caller may observe.
 *
 * This list is normative and identical in the Go, Python, Rust, and TypeScript
 * internal SDKs. It is an allowlist rather than a denylist so a new server
 * header can never become visible by accident, and every entry is additionally
 * screened by {@link isCredentialBearing} before it is exposed.
 *
 * `grpc-message` is deliberately absent: it carries remote free text, which the
 * sanitization contract forbids surfacing.
 */
export const SAFE_RESPONSE_METADATA: readonly string[] = Object.freeze([
	"x-request-id",
	"x-trace-id",
	"x-mindclade-sdk",
	"x-mindclade-should-retry",
	"retry-after-ms",
	"x-mindclade-retry-count",
]);

/**
 * Metadata names that may never cross the SDK boundary in either direction.
 *
 * The same denylist screens allowlisted response metadata and caller-supplied
 * request metadata, so a credential cannot be read out of a response nor
 * smuggled into a request through the escape hatches.
 */
const credentialNames: ReadonlySet<string> = new Set([
	"authorization",
	"proxy-authorization",
	"cookie",
	"set-cookie",
	"x-api-key",
	"x-goog-api-key",
	"x-mindclade-lease-token",
]);

const credentialPattern = /token|secret|key|credential|password/i;

/** True when a metadata name is, or could carry, a credential. */
export const isCredentialBearing = (name: string): boolean => {
	const normalized = name.trim().toLowerCase();
	return credentialNames.has(normalized) || credentialPattern.test(normalized);
};

/**
 * Mutable sink filled by the retry loop with the headers and trailers of the
 * attempt that finally succeeded. Internal: callers observe it only through the
 * immutable {@link RawResponse} the `withResponse()` facade returns.
 */
export interface ResponseCapture {
	headers: Headers | undefined;
	trailers: Headers | undefined;
}

export const createResponseCapture = (): ResponseCapture => ({
	headers: undefined,
	trailers: undefined,
});

/**
 * Returns the capture already installed on a core, or installs a private one.
 *
 * A facade that needs response metadata for its own contract — the lease token
 * `Runs.acquire` reads, for instance — uses this instead of overriding
 * `onHeader` itself, so a caller's `withResponse()` capture is never displaced.
 */
export const captureFor = (
	core: ClientCore,
): { readonly capture: ResponseCapture; readonly core: ClientCore } => {
	if (core.capture !== undefined) return { capture: core.capture, core };
	const capture = createResponseCapture();
	return { capture, core: { ...core, capture } };
};

/** Projects a captured envelope onto the caller-visible raw response. */
export const rawResponse = <Value>(value: Value, capture: ResponseCapture): RawResponse<Value> => {
	const metadata = safeResponseMetadata(capture);
	return Object.freeze({
		metadata,
		requestId: metadata.get("x-request-id"),
		status: Object.freeze({ code: undefined, ok: true }),
		traceId: metadata.get("x-trace-id"),
		value,
	});
};

/**
 * Reduces a captured envelope to the allowlisted, non-credential, bounded
 * subset. Trailers win over headers because the retry trailers are only ever
 * sent at the end of a call.
 */
export const safeResponseMetadata = (capture: ResponseCapture): ReadonlyMap<string, string> => {
	const safe = new Map<string, string>();
	for (const name of SAFE_RESPONSE_METADATA) {
		if (isCredentialBearing(name)) continue;
		const value = capture.trailers?.get(name) ?? capture.headers?.get(name);
		if (value === null || value === undefined || !isBoundedVisibleAscii(value)) continue;
		safe.set(name, value);
	}
	return safe;
};

const isBoundedVisibleAscii = (value: string): boolean =>
	value.length > 0 &&
	value.length <= 512 &&
	[...value].every((character) => {
		const code = character.charCodeAt(0);
		return code >= 0x21 && code <= 0x7e;
	});

/**
 * The raw-response projection of one ergonomic namespace.
 *
 * Only promise-returning methods are projected: server-streaming watchers
 * return async iterables whose envelope is observed per reconnect, not once.
 */
export type WithResponse<Namespace> = {
	readonly [Method in keyof Namespace as Namespace[Method] extends (
		...args: never[]
	) => Promise<unknown>
		? Method
		: never]: Namespace[Method] extends (...args: infer Args) => Promise<infer Result>
		? (...args: Args) => Promise<RawResponse<Result>>
		: never;
};
