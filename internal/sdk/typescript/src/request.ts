import { timestampFromDate } from "@bufbuild/protobuf/wkt";

import type { CommandContext } from "../../../../protocols/generated/typescript/common/v1/command_context_pb.js";
import type { ClientConfig } from "./config.js";
import { validateMetadata } from "./config.js";
import { MindcladeError } from "./error.js";
import type { Runtime } from "./runtime.js";

export interface SdkCallOptions {
	readonly requestId?: string;
	readonly traceId?: string;
	readonly timeoutMs?: number;
	readonly signal?: AbortSignal;
	/** Raw fenced worker identity carried only as transport metadata. */
	readonly workerId?: string;
	/** Sensitive lease capability carried only as transport metadata. */
	readonly leaseToken?: string;
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

export interface PreparedCall {
	readonly requestId: string;
	readonly traceId: string;
	readonly deadlineMs: number;
	readonly signal: AbortSignal | undefined;
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
	return {
		requestId,
		traceId,
		deadlineMs: runtime.nowMs() + timeoutMs,
		signal: options.signal,
		workerId: options.workerId,
		leaseToken: options.leaseToken,
	};
};

export const callHeaders = (
	config: ClientConfig,
	call: PreparedCall,
	idempotencyKey?: string,
): Headers => {
	const headers = new Headers({
		"x-mindclade-sdk": "mindclade-internal-typescript-sdk/0.1",
		"x-mindclade-expected-tenant": config.identity.tenantId,
		"x-mindclade-expected-project": config.identity.projectId,
		"x-mindclade-expected-principal": config.identity.principalId,
		"x-request-id": call.requestId,
		"x-trace-id": call.traceId,
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
