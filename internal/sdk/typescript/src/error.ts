import { Code, ConnectError } from "@connectrpc/connect";

import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import { OperationState } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";

export type ErrorKind =
	| "already_exists"
	| "authentication"
	| "cancelled"
	| "configuration"
	| "deadline_exceeded"
	| "invalid_argument"
	| "protocol"
	| "remote"
	| "transport";

const retryableCodes = new Set<Code>([
	Code.Unavailable,
	Code.ResourceExhausted,
	Code.Aborted,
	Code.DeadlineExceeded,
]);

/** Sanitized, machine-actionable SDK failure. */
export class MindcladeError extends Error {
	readonly kind: ErrorKind;
	readonly code: Code | undefined;
	readonly requestId: string | undefined;
	readonly retryable: boolean;
	readonly retryAfterMs: number | undefined;

	constructor(options: {
		readonly kind: ErrorKind;
		readonly safeMessage: string;
		readonly code?: Code;
		readonly requestId?: string;
		readonly retryable?: boolean;
		readonly retryAfterMs?: number;
	}) {
		const suffix = options.requestId === undefined ? "" : ` (request_id=${options.requestId})`;
		super(`mindclade: ${options.kind}: ${options.safeMessage}${suffix}`);
		this.name = "MindcladeError";
		this.kind = options.kind;
		this.code = options.code;
		this.requestId = options.requestId;
		this.retryable = options.retryable ?? false;
		this.retryAfterMs = options.retryAfterMs;
	}

	static configuration(message: string): MindcladeError {
		return new MindcladeError({ kind: "configuration", safeMessage: message });
	}

	static invalidArgument(message: string): MindcladeError {
		return new MindcladeError({ kind: "invalid_argument", safeMessage: message });
	}

	static alreadyExists(message: string): MindcladeError {
		return new MindcladeError({
			kind: "already_exists",
			safeMessage: message,
			code: Code.AlreadyExists,
		});
	}

	static transport(message: string): MindcladeError {
		return new MindcladeError({ kind: "transport", safeMessage: message });
	}

	static authentication(message = "credential provider failed"): MindcladeError {
		return new MindcladeError({ kind: "authentication", safeMessage: message });
	}

	static protocol(message: string): MindcladeError {
		return new MindcladeError({ kind: "protocol", safeMessage: message });
	}

	static cancelled(): MindcladeError {
		return new MindcladeError({
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

	static from(reason: unknown, signal?: AbortSignal, deadlineExpired = false): MindcladeError {
		if (reason instanceof MindcladeError) return reason;
		if (deadlineExpired) return MindcladeError.deadlineExceeded();
		if (signal?.aborted === true) return MindcladeError.cancelled();

		const error = ConnectError.from(reason);
		const requestId =
			safeHeader(error.metadata, "x-request-id") ?? safeHeader(error.metadata, "request-id");
		const retryAfterMs = retryAfter(error.metadata);
		const kind: ErrorKind =
			error.code === Code.Canceled
				? "cancelled"
				: error.code === Code.DeadlineExceeded
					? "deadline_exceeded"
					: error.code === Code.Unauthenticated
						? "authentication"
						: "remote";
		return new MindcladeError({
			kind,
			safeMessage: safeCodeMessage(error.code),
			code: error.code,
			...(requestId === undefined ? {} : { requestId }),
			retryable: retryableCodes.has(error.code),
			...(retryAfterMs === undefined ? {} : { retryAfterMs }),
		});
	}
}

/** A durable terminal operation failure retaining the authoritative generated resource. */
export class OperationFailure extends MindcladeError {
	readonly operation!: Operation;

	constructor(operation: Operation) {
		super({
			kind: operation.state === OperationState.CANCELLED ? "cancelled" : "remote",
			safeMessage: "operation reached a failed terminal state",
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

const safeHeader = (headers: Headers, name: string): string | undefined => {
	const value = headers.get(name);
	if (value === null || !isVisibleAscii(value, 512)) return undefined;
	return value;
};

const retryAfter = (headers: Headers): number | undefined => {
	const value = headers.get("retry-after-ms");
	if (value === null || !/^\d+$/.test(value)) return undefined;
	const parsed = Number(value);
	if (!Number.isSafeInteger(parsed) || parsed < 0) return undefined;
	return Math.min(parsed, 30_000);
};

export const isRetryableCode = (code: Code | undefined): boolean =>
	code !== undefined && retryableCodes.has(code);

const isVisibleAscii = (value: string, limit: number): boolean =>
	value.length > 0 &&
	value.length <= limit &&
	[...value].every((character) => {
		const code = character.charCodeAt(0);
		return code >= 0x21 && code <= 0x7e;
	});

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
