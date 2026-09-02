import type { Interceptor } from "@connectrpc/connect";

import type { TokenProvider } from "./auth.js";
import { MindcladeError } from "./error.js";
import { LOG_LEVELS, type LogLevel, type Logger, type Observer } from "./observability.js";
import { isCredentialBearing } from "./response.js";

export const Environment = {
	Development: "development",
	Local: "local",
	Production: "production",
	Staging: "staging",
} as const;

export type Environment = (typeof Environment)[keyof typeof Environment];

const endpoints: Readonly<Record<Environment, string>> = {
	[Environment.Local]: "https://127.0.0.1:9443",
	[Environment.Development]: "https://control-plane.development.mindclade.internal:443",
	[Environment.Staging]: "https://control-plane.staging.mindclade.internal:443",
	[Environment.Production]: "https://control-plane.production.mindclade.internal:443",
};

export interface Identity {
	readonly tenantId: string;
	readonly projectId: string;
	readonly principalId: string;
}

export interface RetryPolicy {
	readonly maxAttempts: number;
	readonly initialBackoffMs: number;
	readonly maxBackoffMs: number;
}

export interface ClientConfigInput {
	readonly environment: Environment;
	readonly identity: Identity;
	readonly tokenProvider?: TokenProvider;
	readonly endpoint?: string;
	readonly audience?: string;
	readonly defaultTimeoutMs?: number;
	readonly pollIntervalMs?: number;
	readonly retry?: RetryPolicy;
	readonly tls?: {
		readonly caPem?: string;
		readonly serverName?: string;
	};
	readonly insecureLoopbackForTesting?: boolean;
	/**
	 * Caller-supplied request metadata applied to every call. Credential-bearing
	 * and SDK-owned names are rejected: this seam adds context, it never
	 * re-authenticates a request nor rewrites its identity.
	 */
	readonly metadata?: Readonly<Record<string, string>>;
	/**
	 * Connect interceptors wrapped around every call. They observe and may
	 * decorate requests, but they run *above* credential injection, so they can
	 * neither read nor forge the `authorization` header.
	 */
	readonly interceptors?: readonly Interceptor[];
	/** Receives one event per RPC attempt and per stream reconnect. */
	readonly observer?: Observer;
	/** Receives structured records at or below {@link ClientConfigInput.logLevel}. */
	readonly logger?: Logger;
	/** Verbosity ceiling for {@link ClientConfigInput.logger}. Defaults to `warn`. */
	readonly logLevel?: LogLevel;
	/** Withholds operating system, architecture, and runtime facts from `x-mindclade-sdk`. */
	readonly omitPlatformMetadata?: boolean;
}

/**
 * Request metadata the SDK owns.
 *
 * Custom metadata may not set these: correlation, tenancy expectations, retry
 * position, and SDK identity are computed per call and must not be forgeable
 * through configuration.
 */
export const RESERVED_REQUEST_METADATA: readonly string[] = Object.freeze([
	"idempotency-key",
	"x-mindclade-expected-principal",
	"x-mindclade-expected-project",
	"x-mindclade-expected-tenant",
	"x-mindclade-retry-count",
	"x-mindclade-sdk",
	"x-mindclade-timeout-ms",
	"x-mindclade-worker-id",
	"x-request-id",
	"x-trace-id",
]);

const reserved: ReadonlySet<string> = new Set(RESERVED_REQUEST_METADATA);

/** True when the SDK computes this metadata name itself. */
export const isReservedMetadata = (name: string): boolean =>
	reserved.has(name.trim().toLowerCase());

const METADATA_NAME = /^[a-z0-9][a-z0-9._-]*$/;

/**
 * Validates and normalizes caller-supplied request metadata.
 *
 * Names are lowercased so the denylist cannot be bypassed by casing, and the
 * same credential denylist that screens response metadata screens this
 * direction too.
 */
const normalizeMetadata = (
	input: Readonly<Record<string, string>> | undefined,
): Readonly<Record<string, string>> => {
	const metadata: Record<string, string> = {};
	for (const [rawName, value] of Object.entries(input ?? {})) {
		const name = rawName.trim().toLowerCase();
		if (!METADATA_NAME.test(name) || name.length > 128) {
			throw MindcladeError.configuration(
				"custom metadata names must be lowercase ASCII tokens of at most 128 characters",
			);
		}
		if (isCredentialBearing(name)) {
			throw MindcladeError.configuration(
				`custom metadata may not carry credentials: ${name} is credential-bearing`,
			);
		}
		if (isReservedMetadata(name)) {
			throw MindcladeError.configuration(`custom metadata may not set the SDK-owned ${name}`);
		}
		validateMetadata(`custom metadata ${name}`, value, true);
		metadata[name] = value;
	}
	return Object.freeze(metadata);
};

const defaultRetry: RetryPolicy = {
	maxAttempts: 4,
	initialBackoffMs: 100,
	maxBackoffMs: 2_000,
};

/** Immutable, validated runtime policy. */
export class ClientConfig {
	readonly environment: Environment;
	readonly identity: Identity;
	readonly tokenProvider: TokenProvider | undefined;
	readonly endpoint: string;
	readonly audience: string;
	readonly defaultTimeoutMs: number;
	readonly pollIntervalMs: number;
	readonly retry: RetryPolicy;
	readonly caPem: string | undefined;
	readonly serverName: string | undefined;
	readonly insecureLoopback: boolean;
	readonly metadata: Readonly<Record<string, string>>;
	readonly interceptors: readonly Interceptor[];
	readonly observer: Observer | undefined;
	readonly logger: Logger | undefined;
	readonly logLevel: LogLevel;
	readonly omitPlatformMetadata: boolean;

	private constructor(input: ClientConfigInput, endpoint: string, audience: string) {
		this.environment = input.environment;
		this.identity = Object.freeze({ ...input.identity });
		this.tokenProvider = input.tokenProvider;
		this.endpoint = endpoint;
		this.audience = audience;
		this.defaultTimeoutMs = input.defaultTimeoutMs ?? 20_000;
		this.pollIntervalMs = input.pollIntervalMs ?? 500;
		this.retry = Object.freeze({ ...(input.retry ?? defaultRetry) });
		this.caPem = input.tls?.caPem;
		this.serverName = input.tls?.serverName;
		this.insecureLoopback = input.insecureLoopbackForTesting ?? false;
		this.metadata = normalizeMetadata(input.metadata);
		this.interceptors = Object.freeze([...(input.interceptors ?? [])]);
		this.observer = input.observer;
		this.logger = input.logger;
		this.logLevel = input.logLevel ?? "warn";
		this.omitPlatformMetadata = input.omitPlatformMetadata ?? false;
		Object.freeze(this);
	}

	static create(input: ClientConfigInput): ClientConfig {
		if (!(input.environment in endpoints)) {
			throw MindcladeError.configuration("unknown environment");
		}
		validateMetadata("tenant ID", input.identity.tenantId, true);
		validateMetadata("project ID", input.identity.projectId, true);
		validateMetadata("principal ID", input.identity.principalId, true);
		validateDuration("default timeout", input.defaultTimeoutMs ?? 20_000);
		validateDuration("poll interval", input.pollIntervalMs ?? 500);
		validateRetry(input.retry ?? defaultRetry);
		normalizeMetadata(input.metadata);
		if (input.logLevel !== undefined && !LOG_LEVELS.includes(input.logLevel)) {
			throw MindcladeError.configuration("log level must be error, warn, info, or debug");
		}

		const endpoint = input.endpoint ?? endpoints[input.environment];
		validateEndpoint(endpoint, input.environment, input.insecureLoopbackForTesting ?? false);
		const audience = input.audience ?? canonicalHttpsOrigin(endpoint);
		const insecure = input.insecureLoopbackForTesting ?? false;
		if (insecure && input.tokenProvider !== undefined) {
			throw MindcladeError.configuration("credentials cannot be sent over plaintext transport");
		}
		if (!insecure && input.tokenProvider === undefined) {
			throw MindcladeError.configuration(
				"secure clients require a workload-identity token provider",
			);
		}
		validateMetadata("credential audience", audience, true);
		if (input.tls?.serverName !== undefined) {
			validateMetadata("TLS server name", input.tls.serverName, true);
			if (/[/@:]/.test(input.tls.serverName)) {
				throw MindcladeError.configuration("TLS server name must be a DNS name");
			}
		}
		if (input.tls?.caPem !== undefined) {
			if (input.tls.caPem.length === 0 || input.tls.caPem.length > 1_048_576) {
				throw MindcladeError.configuration("custom CA PEM must contain at most one mebibyte");
			}
		}
		return new ClientConfig(input, endpoint, audience);
	}
}

const canonicalHttpsOrigin = (endpoint: string): string => {
	const url = new URL(endpoint);
	return `https://${url.host}`;
};

const validateEndpoint = (value: string, environment: Environment, insecure: boolean): void => {
	if (value.trim() !== value || /[\r\n]/.test(value)) {
		throw MindcladeError.configuration("endpoint is not canonical");
	}
	let url: URL;
	try {
		url = new URL(value);
	} catch {
		throw MindcladeError.configuration("endpoint is not a valid absolute URL");
	}
	if (
		url.username !== "" ||
		url.password !== "" ||
		(url.pathname !== "" && url.pathname !== "/") ||
		url.search !== "" ||
		url.hash !== ""
	) {
		throw MindcladeError.configuration(
			"endpoint cannot contain credentials, path, query, or fragment",
		);
	}
	if (url.protocol === "https:") {
		if (insecure) {
			throw MindcladeError.configuration("plaintext test mode requires an HTTP loopback endpoint");
		}
		return;
	}
	const loopback =
		url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
	if (url.protocol !== "http:" || environment !== Environment.Local || !insecure || !loopback) {
		throw MindcladeError.configuration(
			"plaintext transport is restricted to explicit Local loopback tests",
		);
	}
};

/**
 * One attempt ceiling for the whole SDK. Client policy and per-request
 * overrides are validated against the identical bound so a caller cannot widen
 * the retry budget past what the configuration layer would accept.
 */
export const validateAttempts = (name: string, value: number): void => {
	if (!Number.isInteger(value) || value < 1 || value > 8) {
		throw MindcladeError.invalidArgument(`${name} must be an integer between one and eight`);
	}
};

const validateRetry = (policy: RetryPolicy): void => {
	if (!Number.isInteger(policy.maxAttempts) || policy.maxAttempts < 1 || policy.maxAttempts > 8) {
		throw MindcladeError.configuration("retry attempts must be between one and eight");
	}
	if (
		!Number.isFinite(policy.initialBackoffMs) ||
		policy.initialBackoffMs <= 0 ||
		!Number.isFinite(policy.maxBackoffMs) ||
		policy.maxBackoffMs < policy.initialBackoffMs ||
		policy.maxBackoffMs > 30_000
	) {
		throw MindcladeError.configuration("retry backoff must be positive and monotonically bounded");
	}
};

const validateDuration = (name: string, value: number): void => {
	if (!Number.isFinite(value) || value <= 0 || value > 86_400_000) {
		throw MindcladeError.configuration(`${name} must be positive and at most twenty-four hours`);
	}
};

export const validateMetadata = (name: string, value: string, required: boolean): void => {
	if (required && value.length === 0) {
		throw MindcladeError.invalidArgument(`${name} cannot be empty`);
	}
	if (
		value.length > 512 ||
		[...value].some((character) => {
			const code = character.charCodeAt(0);
			return code < 0x21 || code > 0x7e;
		})
	) {
		throw MindcladeError.invalidArgument(
			`${name} must contain at most 512 visible ASCII characters`,
		);
	}
};
