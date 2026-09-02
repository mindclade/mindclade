import type { CallOptions as ConnectCallOptions } from "@connectrpc/connect";

import type { ClientCore } from "./core.js";
import { MindcladeError, type RetryState } from "./error.js";
import { callHeaders, type PreparedCall, type RetryAttemptState } from "./request.js";

/**
 * Retry eligibility of a single route.
 *
 * - `safe`: a read that may be repeated freely.
 * - `idempotent`: a mutation whose request embeds a `CommandContext`, so the
 *   control plane collapses duplicates.
 * - `unsafe`: never retried implicitly; retried only under the explicitly named
 *   `withUnsafeRetryOfNonIdempotent` override.
 * - `never`: never retried, override or not.
 */
export type RetrySafety = "idempotent" | "never" | "safe" | "unsafe";

export type { RetryAttemptState } from "./request.js";

/**
 * Attempt ceiling for one call. The client policy is the default, a per-request
 * `maxAttempts` narrows or widens it within the validated bound, and the safety
 * class decides whether more than one attempt is permitted at all.
 */
export const retryableAttempts = (
	core: ClientCore,
	prepared: PreparedCall,
	safety: RetrySafety,
): number => {
	if (safety === "never") return 1;
	const configured = prepared.maxAttempts ?? core.config.retry.maxAttempts;
	if (safety === "unsafe") {
		return prepared.unsafeRetryOfNonIdempotent === undefined ? 1 : configured;
	}
	return configured;
};

/**
 * Issues one unary RPC under the SDK's single retry policy.
 *
 * When the core carries a response capture, the headers and trailers of
 * the attempt that finally answers are recorded there, which is the plumbing
 * `withResponse()` and the lease-token facades read.
 *
 * The prepared deadline is a total budget: every attempt, every backoff, and
 * the credential acquisition performed by the transport are spent from it. Each
 * attempt advertises its zero-based position and the budget that remains, and
 * the failure that finally escapes carries the observable retry outcome.
 */
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
	const attempts = retryableAttempts(core, prepared, safety);
	let issued = 0;
	let cumulativeDelayMs = 0;
	for (;;) {
		ensureActive(core, prepared);
		const remainingMs = prepared.deadlineMs - core.runtime.nowMs();
		const position: RetryAttemptState = { attempt: issued, remainingMs };
		const trailers = new Headers();
		const capture = core.capture;
		issued += 1;
		try {
			return await invoke({
				headers: callHeaders(core.config, prepared, position, idempotencyKey),
				timeoutMs: remainingMs,
				onHeader: (received) => {
					if (capture !== undefined) capture.headers = received;
				},
				onTrailer: (received) => {
					for (const [name, value] of received) trailers.set(name, value);
					if (capture !== undefined) capture.trailers = received;
				},
				...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
			});
		} catch (reason) {
			const error = MindcladeError.from(
				reason,
				prepared.signal,
				core.runtime.nowMs() >= prepared.deadlineMs,
				{ clampMs: core.config.retry.maxBackoffMs, trailers },
			);
			const state = (cause: MindcladeError): RetryState => ({
				attempts: issued,
				cause: cause.kind,
				cumulativeDelayMs,
			});
			if (!error.retryable || issued >= attempts) throw error.withRetryState(state(error));
			const delay = retryDelay(core, issued, error.retryAfterMs);
			if (delay >= prepared.deadlineMs - core.runtime.nowMs()) {
				const expired = MindcladeError.deadlineExceeded();
				throw expired.withRetryState(state(expired));
			}
			await core.runtime.sleep(delay, prepared.signal);
			cumulativeDelayMs += delay;
		}
	}
};

/**
 * Full jitter: uniform in `[0, min(cap, base * 2^n)]`.
 *
 * A server-pinned `retry-after-ms` is honoured exactly rather than jittered,
 * because it is an instruction and not an estimate; it is still clamped to the
 * configured maximum backoff so a hostile or broken server cannot park a caller.
 */
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
