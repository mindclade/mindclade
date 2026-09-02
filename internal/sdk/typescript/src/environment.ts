import { env as processEnv } from "node:process";

import type { Interceptor } from "@connectrpc/connect";

import type { TokenProvider } from "./auth.js";
import {
	ClientConfig,
	type ClientConfigInput,
	Environment,
	type Identity,
	type RetryPolicy,
} from "./config.js";
import { MindcladeError } from "./error.js";
import { consoleLogger, levelFromEnvironment, type Logger, type Observer } from "./observability.js";

/**
 * The complete set of environment variables the SDK reads.
 *
 * There is deliberately no credential variable and there never will be: a
 * credential reaches the SDK only through an explicitly constructed
 * {@link TokenProvider}. Anything else in the process environment is ignored,
 * including variables that merely look credential-shaped.
 */
export const RECOGNISED_ENVIRONMENT_VARIABLES: readonly string[] = Object.freeze([
	"MINDCLADE_AUDIENCE",
	"MINDCLADE_ENDPOINT",
	"MINDCLADE_ENVIRONMENT",
	"MINDCLADE_LOG",
	"MINDCLADE_PRINCIPAL_ID",
	"MINDCLADE_PROJECT_ID",
	"MINDCLADE_TENANT_ID",
]);

/** A read-only view of a process environment. */
export type EnvironmentSource = Readonly<Record<string, string | undefined>>;

/**
 * Values supplied in code rather than read from the environment.
 *
 * Every seam that cannot be expressed as a string lives here — the token
 * provider above all — so the environment stays a source of *addressing*, not
 * of authority.
 */
export interface EnvironmentOverrides {
	/** Overrides individual identity fields; anything omitted is read from the environment. */
	readonly identity?: Partial<Identity>;
	readonly tokenProvider?: TokenProvider;
	readonly endpoint?: string;
	readonly audience?: string;
	readonly defaultTimeoutMs?: number;
	readonly pollIntervalMs?: number;
	readonly retry?: RetryPolicy;
	readonly metadata?: Readonly<Record<string, string>>;
	readonly interceptors?: readonly Interceptor[];
	readonly observer?: Observer;
	/** Replaces the default `MINDCLADE_LOG`-driven standard-error logger. */
	readonly logger?: Logger;
	readonly omitPlatformMetadata?: boolean;
	readonly tls?: ClientConfigInput["tls"];
	readonly insecureLoopbackForTesting?: boolean;
	/** Environment to read. Defaults to the process environment. */
	readonly env?: EnvironmentSource;
}

const environments: Readonly<Record<string, Environment>> = Object.freeze({
	development: Environment.Development,
	local: Environment.Local,
	production: Environment.Production,
	staging: Environment.Staging,
});

const required = (source: EnvironmentSource, name: string, supplied: string | undefined): string => {
	const value = supplied ?? source[name];
	if (value === undefined || value.trim() === "") {
		throw MindcladeError.configuration(`${name} is required to configure a client`);
	}
	return value.trim();
};

const optional = (source: EnvironmentSource, name: string): string | undefined => {
	const value = source[name];
	return value === undefined || value.trim() === "" ? undefined : value.trim();
};

/**
 * Builds a validated {@link ClientConfig} from the process environment.
 *
 * This is the one and only place in the package that reads the environment.
 * The ordinary `ClientConfig.create` constructor stays environment-free, so a
 * client is never silently reconfigured by an ambient variable.
 */
export const clientConfigFromEnvironment = (
	overrides: EnvironmentOverrides = {},
): ClientConfig => {
	const source: EnvironmentSource = overrides.env ?? processEnv;
	const name = required(source, "MINDCLADE_ENVIRONMENT", undefined).toLowerCase();
	const environment = environments[name];
	if (environment === undefined) {
		throw MindcladeError.configuration(
			"MINDCLADE_ENVIRONMENT must be development, staging, production, or local",
		);
	}
	const identity: Identity = {
		principalId: required(source, "MINDCLADE_PRINCIPAL_ID", overrides.identity?.principalId),
		projectId: required(source, "MINDCLADE_PROJECT_ID", overrides.identity?.projectId),
		tenantId: required(source, "MINDCLADE_TENANT_ID", overrides.identity?.tenantId),
	};
	const endpoint = overrides.endpoint ?? optional(source, "MINDCLADE_ENDPOINT");
	const audience = overrides.audience ?? optional(source, "MINDCLADE_AUDIENCE");
	const logLevel = levelFromEnvironment(source.MINDCLADE_LOG);
	const logger = overrides.logger ?? (logLevel === undefined ? undefined : consoleLogger(logLevel));
	return ClientConfig.create({
		environment,
		identity,
		...(endpoint === undefined ? {} : { endpoint }),
		...(audience === undefined ? {} : { audience }),
		...(overrides.tokenProvider === undefined ? {} : { tokenProvider: overrides.tokenProvider }),
		...(overrides.defaultTimeoutMs === undefined
			? {}
			: { defaultTimeoutMs: overrides.defaultTimeoutMs }),
		...(overrides.pollIntervalMs === undefined ? {} : { pollIntervalMs: overrides.pollIntervalMs }),
		...(overrides.retry === undefined ? {} : { retry: overrides.retry }),
		...(overrides.metadata === undefined ? {} : { metadata: overrides.metadata }),
		...(overrides.interceptors === undefined ? {} : { interceptors: overrides.interceptors }),
		...(overrides.observer === undefined ? {} : { observer: overrides.observer }),
		...(logger === undefined ? {} : { logger }),
		...(logLevel === undefined ? {} : { logLevel }),
		...(overrides.omitPlatformMetadata === undefined
			? {}
			: { omitPlatformMetadata: overrides.omitPlatformMetadata }),
		...(overrides.tls === undefined ? {} : { tls: overrides.tls }),
		...(overrides.insecureLoopbackForTesting === undefined
			? {}
			: { insecureLoopbackForTesting: overrides.insecureLoopbackForTesting }),
	});
};
