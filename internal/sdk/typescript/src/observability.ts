import { stderr } from "node:process";

import type { Code } from "@connectrpc/connect";

import type { ErrorKind } from "./error.js";

/** Severity of one structured log record, from least to most verbose. */
export type LogLevel = "debug" | "error" | "info" | "warn";

/** Ordered severities, least verbose first. */
export const LOG_LEVELS: readonly LogLevel[] = Object.freeze(["error", "warn", "info", "debug"]);

const rank: Readonly<Record<LogLevel, number>> = Object.freeze({
	debug: 3,
	error: 0,
	info: 2,
	warn: 1,
});

/** Bounded, non-sensitive record fields. Values are scalars, never payloads. */
export type LogFields = Readonly<Record<string, number | string>>;

/**
 * One observed RPC attempt.
 *
 * The event deliberately carries no payload, no credential, no lease token, and
 * no metadata *values*: only the key names are reported, so an observer can see
 * which metadata a call carried without ever seeing what it contained.
 */
export interface ObservedCall {
	/** Fully-qualified route, e.g. `/mindclade.internal.job.v1.OperationService/GetOperation`. */
	readonly method: string;
	/** Zero-based index of the attempt this event describes. */
	readonly attempt: number;
	/** Wall-clock milliseconds spent on this attempt alone. */
	readonly elapsedMs: number;
	/** `"ok"` for a successful attempt, otherwise the sanitized failure kind. */
	readonly status: "ok" | ErrorKind;
	/** Connect status of a failed attempt, when the failure carried one. */
	readonly code: Code | undefined;
	readonly requestId: string | undefined;
	/** Sorted metadata key names only. Never values. */
	readonly metadataKeys: readonly string[];
}

/** Receives one event per RPC attempt and per stream reconnect. */
export interface Observer {
	onCall(event: ObservedCall): void;
}

/** Receives structured records honouring the configured {@link LogLevel}. */
export interface Logger {
	log(level: LogLevel, message: string, fields: LogFields): void;
}

/**
 * Parses `MINDCLADE_LOG`.
 *
 * An unrecognized value returns `undefined` rather than a default, so a typo
 * silently enables nothing instead of silently enabling everything.
 */
export const levelFromEnvironment = (value: string | undefined): LogLevel | undefined => {
	const normalized = (value ?? "").trim().toLowerCase();
	return LOG_LEVELS.find((level) => level === normalized);
};

/**
 * A JSON-lines logger writing to standard error at or below `level`.
 *
 * Standard error is used so log records never contaminate a program's data
 * output, and each record is one line so it survives arbitrary collectors.
 */
export const consoleLogger = (level: LogLevel): Logger => ({
	log(entryLevel, message, fields) {
		if (rank[entryLevel] > rank[level]) return;
		stderr.write(`${JSON.stringify({ level: entryLevel, message, ...fields })}\n`);
	},
});

/** Sorted union of the key names of every supplied metadata block. */
export const metadataKeyNames = (
	...sources: readonly (Headers | undefined)[]
): readonly string[] => {
	const names = new Set<string>();
	for (const source of sources) {
		if (source === undefined) continue;
		for (const name of source.keys()) names.add(name.toLowerCase());
	}
	return Object.freeze([...names].sort());
};

/** The observability seams a {@link ClientConfig} exposes to the call path. */
export interface ObservabilityPolicy {
	readonly observer?: Observer | undefined;
	readonly logger?: Logger | undefined;
	readonly logLevel?: LogLevel | undefined;
}

const DEFAULT_LOG_LEVEL: LogLevel = "warn";

/**
 * Reports one attempt to the configured observer and logger.
 *
 * Observation is strictly advisory: a throwing observer or logger can never
 * change the outcome of the call it observes, and never re-enters the retry
 * loop. The event is frozen before it is handed out so an observer cannot
 * mutate state the SDK still depends on.
 */
export const observeCall = (policy: ObservabilityPolicy, event: ObservedCall): void => {
	const observed: ObservedCall = Object.freeze({
		...event,
		metadataKeys: Object.freeze([...event.metadataKeys]),
	});
	const observer = policy.observer;
	if (observer !== undefined) {
		try {
			observer.onCall(observed);
		} catch {
			// An observer never changes the outcome of the call it observes.
		}
	}
	const logger = policy.logger;
	if (logger === undefined) return;
	const level: LogLevel = observed.status === "ok" ? "debug" : "warn";
	if (rank[level] > rank[policy.logLevel ?? DEFAULT_LOG_LEVEL]) return;
	try {
		logger.log(level, `rpc attempt ${observed.status}`, {
			attempt: observed.attempt,
			elapsed_ms: observed.elapsedMs,
			metadata_keys: observed.metadataKeys.join(","),
			method: observed.method,
			status: observed.status,
			...(observed.code === undefined ? {} : { code: observed.code }),
			...(observed.requestId === undefined ? {} : { request_id: observed.requestId }),
		});
	} catch {
		// A logger never changes the outcome of the call it observes.
	}
};
