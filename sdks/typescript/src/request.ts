import { timestampFromDate } from "@bufbuild/protobuf/wkt";

import type { CommandContext } from "../../../protocols/generated/typescript/common/v1/command_context_pb.js";
import type { ClientConfig } from "./config.js";
import { validateAttempts, validateMetadata } from "./config.js";
import { MindcladeError } from "./error.js";
import type { PaginationLimits } from "./pagination.js";
import { platformMetadata } from "./platform.js";
import type { Runtime } from "./runtime.js";

export type {
	PaginationLimits,
	PaginationOptions,
	PaginationPage,
} from "./pagination.js";
export { paginate } from "./pagination.js";

/**
 * Explicit, named permission to retry an RPC the safety table classifies as
 * non-idempotent. There is deliberately no bare boolean: the only way to obtain
 * the token is {@link withUnsafeRetryOfNonIdempotent}, which forces the caller
 * to record why duplicate execution is acceptable for their call.
 */
export interface UnsafeRetryOfNonIdempotent {
	readonly justification: string;
	readonly acknowledged: true;
}

/**
 * Mints the named override that allows an `unsafe` RPC to be retried.
 * Routes pinned by `isNeverRetryable` ignore the token entirely.
 */
export const withUnsafeRetryOfNonIdempotent = (
	justification: string,
): UnsafeRetryOfNonIdempotent => {
	validateJustification(justification);
	return Object.freeze({ acknowledged: true as const, justification });
};

export interface SdkCallOptions {
	readonly requestId?: string;
	readonly traceId?: string;
	/** Total budget across every attempt, backoff, and credential acquisition. */
	readonly timeoutMs?: number;
	readonly signal?: AbortSignal;
	/** Per-request attempt ceiling, one to eight, overriding the client policy. */
	readonly maxAttempts?: number;
	/** Named permission to retry a non-idempotent RPC. Never a bare boolean. */
	readonly unsafeRetryOfNonIdempotent?: UnsafeRetryOfNonIdempotent;
	/** Raw fenced worker identity carried only as transport metadata. */
	readonly workerId?: string;
	/** Sensitive lease capability carried only as transport metadata. */
	readonly leaseToken?: string;
}

/** Per-attempt retry position advertised to the server on every attempt. */
export interface RetryAttemptState {
	/** Zero-based index of the attempt being issued. */
	readonly attempt: number;
	/** Milliseconds left in the caller's total budget when the attempt starts. */
	readonly remainingMs: number;
}

export interface SubmitOptions extends SdkCallOptions {
	readonly idempotencyKey: string;
	readonly correlationId?: string;
	readonly causationId?: string;
	readonly cancellationTokenId?: string;
}

export interface WaitOptions extends SdkCallOptions {
	readonly waitTimeoutMs?: number;
	readonly pollIntervalMs?: number;
}

/** Options accepted by every auto-paginating list method. */
export interface ListOptions extends SdkCallOptions {
	/** Page and item budgets for the transparent traversal. */
	readonly limits?: PaginationLimits | undefined;
}

export interface PreparedCall {
	readonly requestId: string;
	readonly traceId: string;
	readonly deadlineMs: number;
	readonly signal: AbortSignal | undefined;
	readonly maxAttempts: number | undefined;
	readonly unsafeRetryOfNonIdempotent: UnsafeRetryOfNonIdempotent | undefined;
	readonly workerId: string | undefined;
	readonly leaseToken: string | undefined;
}

export const prepareCall = (
	config: ClientConfig,
	runtime: Runtime,
	options: SdkCallOptions,
): PreparedCall => {
	const timeoutMs = options.timeoutMs ?? config.defaultTimeoutMs;
	validateDuration("call timeout", timeoutMs);
	const requestId = options.requestId ?? runtime.requestId();
	const traceId = options.traceId ?? requestId;
	validateMetadata("request ID", requestId, true);
	validateMetadata("trace ID", traceId, true);
	if (options.workerId !== undefined) validateMetadata("worker ID", options.workerId, true);
	if (options.leaseToken !== undefined) validateLeaseToken(options.leaseToken);
	if (options.maxAttempts !== undefined) validateAttempts("call max attempts", options.maxAttempts);
	if (options.unsafeRetryOfNonIdempotent !== undefined) {
		validateUnsafeRetryOverride(options.unsafeRetryOfNonIdempotent);
	}
	return {
		requestId,
		traceId,
		deadlineMs: runtime.nowMs() + timeoutMs,
		signal: options.signal,
		maxAttempts: options.maxAttempts,
		unsafeRetryOfNonIdempotent: options.unsafeRetryOfNonIdempotent,
		workerId: options.workerId,
		leaseToken: options.leaseToken,
	};
};

export const callHeaders = (
	config: ClientConfig,
	call: PreparedCall,
	retry: RetryAttemptState,
	idempotencyKey?: string,
): Headers => {
	const headers = new Headers({
		"x-mindclade-sdk": platformMetadata(config.omitPlatformMetadata),
		"x-mindclade-expected-tenant": config.identity.tenantId,
		"x-mindclade-expected-project": config.identity.projectId,
		"x-mindclade-expected-principal": config.identity.principalId,
		"x-request-id": call.requestId,
		"x-trace-id": call.traceId,
		"x-mindclade-retry-count": String(Math.max(0, Math.floor(retry.attempt))),
		"x-mindclade-timeout-ms": String(Math.max(1, Math.floor(retry.remainingMs))),
	});
	if (idempotencyKey !== undefined) {
		validateMetadata("idempotency key", idempotencyKey, true);
		headers.set("idempotency-key", idempotencyKey);
	}
	if (call.workerId !== undefined) headers.set("x-mindclade-worker-id", call.workerId);
	if (call.leaseToken !== undefined) headers.set("x-mindclade-lease-token", call.leaseToken);
	return headers;
};

export const commandContext = (
	config: ClientConfig,
	call: PreparedCall,
	options: SubmitOptions,
): CommandContext => {
	validateSubmitOptions(options);
	return {
		$typeName: "mindclade.common.v1.CommandContext",
		requestId: call.requestId,
		idempotencyKey: options.idempotencyKey,
		principalId: config.identity.principalId,
		traceId: call.traceId,
		deadline: timestampFromDate(new Date(call.deadlineMs)),
		// Canonical command identity is computed and materialized by the
		// control plane over the received generated message.
		canonicalRequestDigest: "",
		tenantId: config.identity.tenantId,
		projectId: config.identity.projectId,
		correlationId: checkedOptional("correlation ID", options.correlationId),
		causationId: checkedOptional("causation ID", options.causationId),
		cancellationTokenId: checkedOptional("cancellation token ID", options.cancellationTokenId),
	};
};

export const validateSubmitOptions = (options: SubmitOptions): void => {
	validateMetadata("idempotency key", options.idempotencyKey, true);
};

export const validateResource = (name: string, value: string): void =>
	validateMetadata(name, value, true);

export const validateDuration = (name: string, value: number): void => {
	if (!Number.isFinite(value) || value <= 0 || value > 86_400_000) {
		throw MindcladeError.invalidArgument(`${name} must be positive and at most twenty-four hours`);
	}
};

const checkedOptional = (name: string, value: string | undefined): string => {
	if (value === undefined) return "";
	validateMetadata(name, value, true);
	return value;
};

const validateUnsafeRetryOverride = (override: UnsafeRetryOfNonIdempotent): void => {
	if (override.acknowledged !== true) {
		throw MindcladeError.invalidArgument(
			"unsafe retry of a non-idempotent RPC must be acknowledged explicitly",
		);
	}
	validateJustification(override.justification);
};

/** Justifications are prose, so a single space is allowed where metadata forbids it. */
const validateJustification = (value: string): void => {
	if (
		value.length === 0 ||
		value.length > 256 ||
		[...value].some((character) => {
			const code = character.charCodeAt(0);
			return code < 0x20 || code > 0x7e;
		})
	) {
		throw MindcladeError.invalidArgument(
			"unsafe retry justification must contain one to 256 printable ASCII characters",
		);
	}
};

const validateLeaseToken = (value: string): void => {
	if (
		value.length === 0 ||
		value.length > 4096 ||
		[...value].some((character) => {
			const code = character.charCodeAt(0);
			return code < 0x21 || code > 0x7e;
		})
	) {
		throw MindcladeError.invalidArgument(
			"lease token must contain at most 4096 visible ASCII characters",
		);
	}
};
