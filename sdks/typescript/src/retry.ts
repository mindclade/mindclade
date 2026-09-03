import type { CallOptions as ConnectCallOptions } from "@connectrpc/connect";

import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { callHeaders, type PreparedCall } from "./request.js";

export type RetrySafety = "idempotent" | "safe" | "unsafe";

export const invokeUnary = async <Result>(
	core: ClientCore,
	prepared: PreparedCall,
	safety: RetrySafety,
	idempotencyKey: string | undefined,
	invoke: (options: ConnectCallOptions) => Promise<Result>,
): Promise<Result> => {
	if (safety === "idempotent" && idempotencyKey === undefined) {
		throw MindcladeError.invalidArgument("idempotent commands require an idempotency key");
	}
	const attempts = safety === "unsafe" ? 1 : core.config.retry.maxAttempts;
	for (let attempt = 1; attempt <= attempts; attempt += 1) {
		ensureActive(core, prepared);
		const remaining = prepared.deadlineMs - core.runtime.nowMs();
		try {
			return await invoke({
				headers: callHeaders(core.config, prepared, idempotencyKey),
				timeoutMs: remaining,
				...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
			});
		} catch (reason) {
			const error = MindcladeError.from(
				reason,
				prepared.signal,
				core.runtime.nowMs() >= prepared.deadlineMs,
			);
			if (!error.retryable || attempt === attempts) throw error;
			const delay = retryDelay(core, attempt, error.retryAfterMs);
			if (delay >= prepared.deadlineMs - core.runtime.nowMs()) {
				throw MindcladeError.deadlineExceeded();
			}
			await core.runtime.sleep(delay, prepared.signal);
		}
	}
	throw MindcladeError.protocol("retry loop exited unexpectedly");
};

export const retryDelay = (core: ClientCore, attempt: number, retryAfterMs?: number): number => {
	if (retryAfterMs !== undefined) return Math.min(retryAfterMs, core.config.retry.maxBackoffMs);
	const exponential = Math.min(
		core.config.retry.initialBackoffMs * 2 ** Math.max(0, attempt - 1),
		core.config.retry.maxBackoffMs,
	);
	const random = core.runtime.random();
	if (!Number.isFinite(random) || random < 0 || random >= 1) {
		throw MindcladeError.configuration("retry random source must return a value in [0, 1)");
	}
	return Math.floor(random * (exponential + 1));
};

export const ensureActive = (core: ClientCore, prepared: PreparedCall): void => {
	if (prepared.signal?.aborted === true) throw MindcladeError.cancelled();
	if (core.runtime.nowMs() >= prepared.deadlineMs) throw MindcladeError.deadlineExceeded();
};
