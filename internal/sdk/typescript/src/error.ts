import { clone } from "@bufbuild/protobuf";
import { Code, ConnectError } from "@connectrpc/connect";

import {
	ErrorCode,
	type ErrorDetail,
	ErrorDetailSchema,
	type FieldViolation,
	FieldViolationSchema,
	type PreconditionViolation,
	PreconditionViolationSchema,
	RetryClass,
} from "../../../../protocols/generated/typescript/common/v1/error_detail_pb.js";
import type { ResourceRef } from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import { OperationState } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";

export type ErrorKind =
	| "already_exists"
	| "authentication"
	| "cancelled"
	| "configuration"
	| "deadline_exceeded"
	| "invalid_argument"
	| "pagination_limit"
	| "protocol"
	| "remote"
	| "transport";

/**
 * Stable, language-independent classification of an SDK failure. The value is
 * pinned to the concrete error class and never derived from remote text, so it
 * is safe to switch on and safe to log.
 */
export type StableErrorCode =
	| "authentication"
	| "authorization"
	| "cancelled"
	| "conflict"
	| "not_found"
	| "operation_failed"
	| "quota"
	| "rate_limit"
	| "retryable_service"
	| "transport"
	| "unclassified"
	| "validation";

/** Response trailer through which a server overrides retry eligibility. */
export const SHOULD_RETRY_TRAILER = "x-mindclade-should-retry";
/** Response trailer carrying a server-pinned backoff in whole milliseconds. */
export const RETRY_AFTER_TRAILER = "retry-after-ms";
/** Canonical request-correlation metadata key. The legacy alias is retired. */
export const REQUEST_ID_HEADER = "x-request-id";
/** Canonical trace-correlation metadata key. */
export const TRACE_ID_HEADER = "x-trace-id";

const DEFAULT_RETRY_AFTER_CLAMP_MS = 30_000;

const retryableCodes = new Set<Code>([
	Code.Unavailable,
	Code.ResourceExhausted,
	Code.Aborted,
	Code.DeadlineExceeded,
]);

/** Observable outcome of the retry loop that produced a terminal failure. */
export interface RetryState {
	/** Attempts actually issued, including the one that failed terminally. */
	readonly attempts: number;
	/** Total backoff actually slept between those attempts. */
	readonly cumulativeDelayMs: number;
	/** Kind of the failure that ended the loop. */
	readonly cause: ErrorKind;
}

/** Sanitized projection of a resource-exhaustion subject. Derived, not a wire type. */
export interface QuotaState {
	readonly subject: string;
	readonly limit: string;
	readonly description: string;
}

/** Sanitized projection of a fencing/lease precondition. Derived, not a wire type. */
export interface FenceState {
	readonly subject: string;
	readonly description: string;
}

export interface MindcladeErrorOptions {
	readonly kind: ErrorKind;
	readonly safeMessage: string;
	readonly code?: Code | undefined;
	readonly requestId?: string | undefined;
	readonly traceId?: string | undefined;
	readonly operationId?: string | undefined;
	readonly retryable?: boolean | undefined;
	readonly retryAfterMs?: number | undefined;
	readonly fieldViolations?: readonly FieldViolation[] | undefined;
	readonly preconditionViolations?: readonly PreconditionViolation[] | undefined;
	readonly quota?: QuotaState | undefined;
	readonly fence?: FenceState | undefined;
	readonly conflictRevision?: string | undefined;
	readonly diagnosticReference?: string | undefined;
	readonly retry?: RetryState | undefined;
}

/** Additional, already-captured context for classifying a transport failure. */
export interface ErrorContext {
	/** Response trailers captured for the failing attempt. */
	readonly trailers?: Headers | undefined;
	/** Upper bound applied to a server-pinned `retry-after-ms`. */
	readonly clampMs?: number | undefined;
}

const emptyFieldViolations: readonly FieldViolation[] = Object.freeze([]);
const emptyPreconditionViolations: readonly PreconditionViolation[] = Object.freeze([]);

/** Sanitized, machine-actionable SDK failure. */
export class MindcladeError extends Error {
	/** Stable classification of the concrete subclass. */
	static readonly stableCode: StableErrorCode = "unclassified";

	readonly kind: ErrorKind;
	readonly stableCode: StableErrorCode;
	readonly safeMessage: string;
	readonly code: Code | undefined;
	readonly requestId: string | undefined;
	readonly traceId: string | undefined;
	readonly operationId: string | undefined;
	readonly retryable: boolean;
	readonly retryAfterMs: number | undefined;
	readonly fieldViolations: readonly FieldViolation[];
	readonly preconditionViolations: readonly PreconditionViolation[];
	readonly quota: QuotaState | undefined;
	readonly fence: FenceState | undefined;
	readonly conflictRevision: string | undefined;
	readonly diagnosticReference: string | undefined;
	readonly retry: RetryState | undefined;

	constructor(options: MindcladeErrorOptions) {
		const suffix = options.requestId === undefined ? "" : ` (request_id=${options.requestId})`;
		super(`mindclade: ${options.kind}: ${options.safeMessage}${suffix}`);
		this.name = new.target.name;
		this.kind = options.kind;
		this.stableCode = (new.target as typeof MindcladeError).stableCode;
		this.safeMessage = options.safeMessage;
		this.code = options.code;
		this.requestId = options.requestId;
		this.traceId = options.traceId;
		this.operationId = options.operationId;
		this.retryable = options.retryable ?? false;
		this.retryAfterMs = options.retryAfterMs;
		this.fieldViolations = options.fieldViolations ?? emptyFieldViolations;
		this.preconditionViolations = options.preconditionViolations ?? emptyPreconditionViolations;
		this.quota = options.quota;
		this.fence = options.fence;
		this.conflictRevision = options.conflictRevision;
		this.diagnosticReference = options.diagnosticReference;
		this.retry = options.retry === undefined ? undefined : Object.freeze({ ...options.retry });
	}

	/**
	 * Returns an equivalent error of the same class carrying the observable
	 * outcome of the retry loop. The receiver is never mutated, so an error the
	 * caller already holds cannot be rewritten behind its back.
	 */
	withRetryState(retry: RetryState): this {
		const copy = Object.create(Object.getPrototypeOf(this) as object) as this;
		Object.defineProperties(copy, Object.getOwnPropertyDescriptors(this));
		Object.defineProperty(copy, "retry", {
			configurable: true,
			enumerable: true,
			value: Object.freeze({ ...retry }),
			writable: false,
		});
		return copy;
	}

	static configuration(message: string): MindcladeError {
		return new MindcladeError({ kind: "configuration", safeMessage: message });
	}

	static invalidArgument(message: string): ValidationError {
		return new ValidationError({ kind: "invalid_argument", safeMessage: message });
	}

	static alreadyExists(message: string): ConflictError {
		return new ConflictError({
			kind: "already_exists",
			safeMessage: message,
			code: Code.AlreadyExists,
		});
	}

	static paginationLimit(message: string): QuotaError {
		return new QuotaError({
			kind: "pagination_limit",
			safeMessage: message,
			code: Code.ResourceExhausted,
		});
	}

	static transport(message: string): TransportError {
		return new TransportError({ kind: "transport", safeMessage: message });
	}

	static authentication(message = "credential provider failed"): AuthenticationError {
		return new AuthenticationError({ kind: "authentication", safeMessage: message });
	}

	static protocol(message: string): TransportError {
		return new TransportError({ kind: "protocol", safeMessage: message });
	}

	static cancelled(): CancelledError {
		return new CancelledError({
			kind: "cancelled",
			safeMessage: "request was cancelled",
			code: Code.Canceled,
		});
	}

	static deadlineExceeded(): MindcladeError {
		return new MindcladeError({
			kind: "deadline_exceeded",
			safeMessage: "request deadline exceeded",
			code: Code.DeadlineExceeded,
		});
	}

	static from(
		reason: unknown,
		signal?: AbortSignal,
		deadlineExpired = false,
		context: ErrorContext = {},
	): MindcladeError {
		if (reason instanceof MindcladeError) return reason;
		if (deadlineExpired) return MindcladeError.deadlineExceeded();
		if (signal?.aborted === true) return MindcladeError.cancelled();

		const error = ConnectError.from(reason);
		const trailers = context.trailers;
		const requestId =
			safeHeader(trailers, REQUEST_ID_HEADER) ?? safeHeader(error.metadata, REQUEST_ID_HEADER);
		const traceId =
			safeHeader(trailers, TRACE_ID_HEADER) ?? safeHeader(error.metadata, TRACE_ID_HEADER);
		const clampMs = context.clampMs ?? DEFAULT_RETRY_AFTER_CLAMP_MS;
		const detail = error.findDetails(ErrorDetailSchema)[0];
		const trailerRetryAfterMs =
			retryAfter(trailers, clampMs) ?? retryAfter(error.metadata, clampMs);
		const retryAfterMs = trailerRetryAfterMs ?? detailRetryAfterMs(detail, clampMs);
		const trailerOverride = shouldRetryOverride(trailers) ?? shouldRetryOverride(error.metadata);
		const retryable = shouldRetry({
			code: error.code,
			trailerOverride,
			retryClass: detail?.retryClass,
		});
		const violations = sanitizedViolations(detail);
		const subject = subjectName(detail?.subject);
		const options: MindcladeErrorOptions = {
			kind: kindForCode(error.code),
			safeMessage: safeCodeMessage(error.code),
			code: error.code,
			requestId,
			traceId,
			retryable,
			retryAfterMs,
			fieldViolations: violations.fields,
			preconditionViolations: violations.preconditions,
			quota: quotaState(error.code, detail, subject, violations.preconditions),
			fence: fenceState(violations.preconditions, subject),
			conflictRevision: conflictRevision(detail?.subject),
			diagnosticReference: sanitizeText(detail?.errorId),
			operationId: operationSubject(detail?.subject),
		};
		const Constructor = errorClassFor(error.code, detail, retryAfterMs !== undefined);
		return new Constructor(options);
	}
}

/** The credential could not be established or was rejected by the server. */
export class AuthenticationError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "authentication";
}

/** The authenticated principal is not permitted to perform the operation. */
export class AuthorizationError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "authorization";
}

/** The request was rejected before any durable effect, locally or remotely. */
export class ValidationError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "validation";
}

/** A concurrent revision, uniqueness, or ordering constraint was violated. */
export class ConflictError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "conflict";
}

/** The addressed resource does not exist within the caller's scope. */
export class NotFoundError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "not_found";
}

/** The server asked the caller to slow down and supplied a retry-after budget. */
export class RateLimitError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "rate_limit";
}

/** A durable allocation ceiling was reached; retrying alone will not help. */
export class QuotaError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "quota";
}

/** The service is temporarily unable to serve the request. */
export class RetryableServiceError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "retryable_service";
}

/** The caller or the server cancelled the request. */
export class CancelledError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "cancelled";
}

/** The failure happened below the application protocol, or in the SDK's framing. */
export class TransportError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "transport";
}

/** A durable terminal operation failure retaining the authoritative generated resource. */
export class OperationFailedError extends MindcladeError {
	static override readonly stableCode: StableErrorCode = "operation_failed";

	readonly operation!: Operation;

	constructor(operation: Operation) {
		super({
			kind: operation.state === OperationState.CANCELLED ? "cancelled" : "remote",
			safeMessage: "operation reached a failed terminal state",
			...(operation.operationId === "" ? {} : { operationId: operation.operationId }),
		});
		this.name = "OperationFailure";
		Object.defineProperty(this, "operation", {
			configurable: false,
			enumerable: false,
			value: operation,
			writable: false,
		});
	}
}

/** Historical name retained for callers that predate the error hierarchy. */
export { OperationFailedError as OperationFailure };

/**
 * The single retry-eligibility predicate for the whole SDK.
 *
 * Precedence is explicit: an `x-mindclade-should-retry` trailer wins in both
 * directions, a `RETRY_CLASS_NEVER` server classification then forbids a retry,
 * and otherwise eligibility is decided by the fixed retryable-status set.
 */
export const shouldRetry = (input: {
	readonly code: Code | undefined;
	readonly trailerOverride?: boolean | undefined;
	readonly retryClass?: RetryClass | undefined;
}): boolean => {
	if (input.trailerOverride !== undefined) return input.trailerOverride;
	if (input.retryClass === RetryClass.NEVER) return false;
	return input.code !== undefined && retryableCodes.has(input.code);
};

/** Thin alias over {@link shouldRetry} for status-only callers. */
export const isRetryableCode = (code: Code | undefined): boolean => shouldRetry({ code });

/** Reads the strict `x-mindclade-should-retry` server override, if present. */
export const shouldRetryOverride = (headers: Headers | undefined): boolean | undefined => {
	const value = headers?.get(SHOULD_RETRY_TRAILER);
	if (value === "true") return true;
	if (value === "false") return false;
	return undefined;
};

/** Reads `retry-after-ms`, clamped to the caller's maximum backoff. */
export const retryAfterMsFrom = (
	headers: Headers | undefined,
	clampMs: number,
): number | undefined => retryAfter(headers, clampMs);

const safeHeader = (headers: Headers | undefined, name: string): string | undefined => {
	const value = headers?.get(name);
	if (value === null || value === undefined || !isVisibleAscii(value, 512)) return undefined;
	return value;
};

const retryAfter = (headers: Headers | undefined, clampMs: number): number | undefined => {
	const value = headers?.get(RETRY_AFTER_TRAILER);
	if (value === null || value === undefined || !/^\d+$/.test(value)) return undefined;
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed) || parsed < 0) return undefined;
	return Math.min(parsed, clampMs);
};

const detailRetryAfterMs = (
	detail: ErrorDetail | undefined,
	clampMs: number,
): number | undefined => {
	const duration = detail?.retryAfter;
	if (duration === undefined) return undefined;
	const milliseconds = Number(duration.seconds) * 1_000 + Math.floor(duration.nanos / 1_000_000);
	if (!Number.isSafeInteger(milliseconds) || milliseconds < 0) return undefined;
	return Math.min(milliseconds, clampMs);
};

const isVisibleAscii = (value: string, limit: number): boolean =>
	value.length > 0 &&
	value.length <= limit &&
	[...value].every((character) => {
		const code = character.charCodeAt(0);
		return code >= 0x21 && code <= 0x7e;
	});

/**
 * Accepts bounded single-line printable ASCII only. Multi-line text, control
 * characters, and oversized blobs are dropped rather than truncated, so a stack
 * trace or a provider dump can never reach a typed field.
 */
const sanitizeText = (value: string | undefined, limit = 512): string | undefined => {
	if (value === undefined || value.length === 0 || value.length > limit) return undefined;
	for (const character of value) {
		const code = character.charCodeAt(0);
		if (code < 0x20 || code > 0x7e) return undefined;
	}
	return value;
};

const sanitizedViolations = (
	detail: ErrorDetail | undefined,
): {
	readonly fields: readonly FieldViolation[];
	readonly preconditions: readonly PreconditionViolation[];
} => {
	if (detail === undefined) {
		return { fields: emptyFieldViolations, preconditions: emptyPreconditionViolations };
	}
	const fields = detail.fieldViolations.map((violation) => {
		const copy = clone(FieldViolationSchema, violation);
		copy.field = sanitizeText(violation.field) ?? "";
		copy.description = sanitizeText(violation.description) ?? "";
		return Object.freeze(copy);
	});
	const preconditions = detail.preconditionViolations.map((violation) => {
		const copy = clone(PreconditionViolationSchema, violation);
		copy.type = sanitizeText(violation.type) ?? "";
		copy.subject = sanitizeText(violation.subject) ?? "";
		copy.description = sanitizeText(violation.description) ?? "";
		return Object.freeze(copy);
	});
	return { fields: Object.freeze(fields), preconditions: Object.freeze(preconditions) };
};

const subjectName = (subject: ResourceRef | undefined): string => {
	if (subject === undefined) return "";
	const name = sanitizeText(subject.name);
	if (name !== undefined) return name;
	const type = sanitizeText(subject.resourceType);
	const id = sanitizeText(subject.resourceId);
	if (type === undefined || id === undefined) return "";
	return `${type}/${id}`;
};

const operationSubject = (subject: ResourceRef | undefined): string | undefined => {
	if (subject === undefined || subject.resourceType !== "operation") return undefined;
	const name = subjectName(subject);
	return name === "" ? undefined : name;
};

const conflictRevision = (subject: ResourceRef | undefined): string | undefined => {
	if (subject === undefined) return undefined;
	const etag = sanitizeText(subject.etag);
	if (etag !== undefined) return etag;
	return subject.resourceVersion > 0n ? String(subject.resourceVersion) : undefined;
};

const quotaState = (
	code: Code,
	detail: ErrorDetail | undefined,
	subject: string,
	preconditions: readonly PreconditionViolation[],
): QuotaState | undefined => {
	const exhausted =
		code === Code.ResourceExhausted || detail?.code === ErrorCode.RESOURCE_EXHAUSTED;
	if (!exhausted) return undefined;
	const violation = preconditions.find((entry) => /quota|limit|rate/i.test(entry.type));
	return Object.freeze({
		subject:
			violation?.subject !== undefined && violation.subject !== "" ? violation.subject : subject,
		limit: violation?.type ?? "",
		description: violation?.description ?? "",
	});
};

const fenceState = (
	preconditions: readonly PreconditionViolation[],
	subject: string,
): FenceState | undefined => {
	const violation = preconditions.find((entry) => /fence|lease/i.test(entry.type));
	if (violation === undefined) return undefined;
	return Object.freeze({
		subject: violation.subject === "" ? subject : violation.subject,
		description: violation.description,
	});
};

const kindForCode = (code: Code): ErrorKind => {
	switch (code) {
		case Code.Canceled:
			return "cancelled";
		case Code.DeadlineExceeded:
			return "deadline_exceeded";
		case Code.AlreadyExists:
			return "already_exists";
		case Code.Unauthenticated:
			return "authentication";
		case Code.InvalidArgument:
			return "invalid_argument";
		default:
			return "remote";
	}
};

type MindcladeErrorConstructor = new (options: MindcladeErrorOptions) => MindcladeError;

const errorClassFor = (
	code: Code,
	detail: ErrorDetail | undefined,
	hasRetryAfter: boolean,
): MindcladeErrorConstructor => {
	if (detail?.code === ErrorCode.POLICY_DENIED) return AuthorizationError;
	if (detail?.code === ErrorCode.CONFLICT) return ConflictError;
	switch (code) {
		case Code.Unauthenticated:
			return AuthenticationError;
		case Code.PermissionDenied:
			return AuthorizationError;
		case Code.InvalidArgument:
		case Code.OutOfRange:
			return ValidationError;
		case Code.Aborted:
		case Code.AlreadyExists:
			return ConflictError;
		case Code.NotFound:
			return NotFoundError;
		case Code.ResourceExhausted:
			return hasRetryAfter ? RateLimitError : QuotaError;
		case Code.Unavailable:
		case Code.Internal:
		case Code.DataLoss:
		case Code.DeadlineExceeded:
			return RetryableServiceError;
		case Code.Canceled:
			return CancelledError;
		case Code.Unimplemented:
			return TransportError;
		default:
			return MindcladeError;
	}
};

const safeCodeMessage = (code: Code): string => {
	switch (code) {
		case Code.Canceled:
			return "remote request was cancelled";
		case Code.InvalidArgument:
			return "remote request was invalid";
		case Code.DeadlineExceeded:
			return "remote request deadline exceeded";
		case Code.NotFound:
			return "requested resource was not found";
		case Code.AlreadyExists:
			return "resource already exists";
		case Code.PermissionDenied:
			return "permission was denied";
		case Code.ResourceExhausted:
			return "remote service is resource constrained";
		case Code.FailedPrecondition:
			return "remote precondition failed";
		case Code.Aborted:
			return "remote transaction was aborted";
		case Code.OutOfRange:
			return "request was outside the supported range";
		case Code.Unimplemented:
			return "remote method is not implemented";
		case Code.Internal:
			return "remote service failed internally";
		case Code.Unavailable:
			return "remote service is unavailable";
		case Code.DataLoss:
			return "remote service reported data loss";
		case Code.Unauthenticated:
			return "authentication failed";
		case Code.Unknown:
			return "remote request failed";
		default:
			return "remote request failed";
	}
};
