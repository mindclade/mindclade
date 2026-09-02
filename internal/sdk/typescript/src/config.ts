import type { TokenProvider } from "./auth.js";
import { MindcladeError } from "./error.js";

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
}

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

	private constructor(input: ClientConfigInput, endpoint: string) {
		this.environment = input.environment;
		this.identity = Object.freeze({ ...input.identity });
		this.tokenProvider = input.tokenProvider;
		this.endpoint = endpoint;
		this.audience = input.audience ?? endpoint;
		this.defaultTimeoutMs = input.defaultTimeoutMs ?? 20_000;
		this.pollIntervalMs = input.pollIntervalMs ?? 500;
		this.retry = Object.freeze({ ...(input.retry ?? defaultRetry) });
		this.caPem = input.tls?.caPem;
		this.serverName = input.tls?.serverName;
		this.insecureLoopback = input.insecureLoopbackForTesting ?? false;
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

		const endpoint = input.endpoint ?? endpoints[input.environment];
		validateEndpoint(endpoint, input.environment, input.insecureLoopbackForTesting ?? false);
		const insecure = input.insecureLoopbackForTesting ?? false;
		if (insecure && input.tokenProvider !== undefined) {
			throw MindcladeError.configuration("credentials cannot be sent over plaintext transport");
		}
		if (!insecure && input.tokenProvider === undefined) {
			throw MindcladeError.configuration(
				"secure clients require a workload-identity token provider",
			);
		}
		validateMetadata("credential audience", input.audience ?? endpoint, true);
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
		return new ClientConfig(input, endpoint);
	}
}

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
