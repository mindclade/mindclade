import { Code, ConnectError } from "@connectrpc/connect";

import type { ClientCore } from "./core.js";
import { MindcladeError, type RetryState } from "./error.js";
import { metadataKeyNames, observeCall } from "./observability.js";
import { callHeaders, type PreparedCall } from "./request.js";
import { ensureActive, retryableAttempts, retryDelay } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

/**
 * Default total budget for a long-running watch or wait.
 *
 * Defined once for every domain so operations, inference, workflows, and
 * training cannot drift apart on how long a caller is willing to wait.
 */
export const DEFAULT_WAIT_TIMEOUT_MS = 30 * 60 * 1_000;

/** Per-attempt call options handed to a watch source when it opens a stream. */
export interface WatchCall {
	readonly headers: Headers;
	readonly timeoutMs: number;
	readonly signal?: AbortSignal;
}

/**
 * What the watcher does with one received update.
 *
 * `skip` acknowledges nothing and advances no cursor — it is how a domain
 * discards a replayed update after a reconnect. `yield` both advances the
 * acknowledged cursor and delivers a value to the caller.
 */
export type WatchDecision<Value, Cursor> =
	| { readonly delivery: "skip" }
	| { readonly cursor: Cursor; readonly delivery: "yield"; readonly value: Value };

/**
 * The domain-specific half of a resumable watch.
 *
 * Everything generic — reconnection, budget arithmetic, backoff, retry
 * eligibility, cancellation, observability — lives in {@link watchStream}.
 * Everything domain-specific — request shape, identity checks, sequence
 * contiguity, terminality — lives here, so each facade keeps its own contract
 * without re-implementing the loop.
 */
export interface WatchSource<Value, Cursor, Update> {
	/** Fully-qualified route, reported to the observer on every reconnect. */
	readonly route: string;
	/** Opens one server stream positioned immediately after `cursor`. */
	readonly open: (cursor: Cursor, call: WatchCall) => AsyncIterable<Update>;
	/**
	 * Validates one update against the acknowledged cursor. Implementations
	 * throw a sanitized protocol failure when identity or ordering is violated;
	 * such a failure is terminal and is never retried.
	 */
	readonly accept: (update: Update, cursor: Cursor) => WatchDecision<Value, Cursor>;
	/** True when the delivered value is the last one of the stream. */
	readonly terminal: (value: Value) => boolean;
	/** Safe message used when the server ends a stream before a terminal value. */
	readonly incomplete: string;
}

/**
 * The one resumable watcher in the SDK.
 *
 * Reconnection happens only inside the caller's remaining deadline and only
 * from the last *acknowledged* cursor, so a redelivered prefix is skipped
 * rather than yielded twice and a lost suffix is never silently dropped. A
 * delivered update resets the failure count, because progress proves the stream
 * is healthy; retry eligibility, the attempt ceiling, and the backoff schedule
 * are exactly the ones the unary path uses.
 *
 * The generator honours an `AbortSignal` between messages and between
 * reconnects, and it propagates the signal to the underlying stream so an abort
 * mid-message is observed by the transport as well.
 */
export async function* watchStream<Value, Cursor, Update>(
	core: ClientCore,
	prepared: PreparedCall,
	source: WatchSource<Value, Cursor, Update>,
	initialCursor: Cursor,
): AsyncGenerator<Value> {
	let cursor = initialCursor;
	let failures = 0;
	let cumulativeDelayMs = 0;
	// The route is the authority for reconnect eligibility here exactly as it is
	// on the unary path: `safety.ts` stays the only classifier, so a watcher
	// cannot quietly grant itself a retry budget its RPC is not entitled to.
	const attempts = retryableAttempts(core, prepared, registeredMethodSafety(source.route));
	for (;;) {
		ensureActive(core, prepared);
		const remainingMs = Math.max(1, prepared.deadlineMs - core.runtime.nowMs());
		const headers = callHeaders(core.config, prepared, { attempt: failures, remainingMs });
		const startedAt = core.runtime.nowMs();
		try {
			const stream = source.open(cursor, {
				headers,
				timeoutMs: remainingMs,
				...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
			});
			for await (const update of stream) {
				ensureActive(core, prepared);
				const decision = source.accept(update, cursor);
				if (decision.delivery === "skip") continue;
				cursor = decision.cursor;
				// Progress proves the stream is healthy, so the reconnect budget
				// and the delay it has spent both restart from the new cursor.
				failures = 0;
				cumulativeDelayMs = 0;
				yield decision.value;
				if (source.terminal(decision.value)) return;
			}
			throw new ConnectError(source.incomplete, Code.Unavailable);
		} catch (reason) {
			const error = MindcladeError.from(
				reason,
				prepared.signal,
				core.runtime.nowMs() >= prepared.deadlineMs,
				{ clampMs: core.config.retry.maxBackoffMs },
			);
			failures += 1;
			observeCall(core.config, {
				attempt: failures - 1,
				code: error.code,
				elapsedMs: core.runtime.nowMs() - startedAt,
				metadataKeys: metadataKeyNames(headers),
				method: source.route,
				requestId: error.requestId ?? prepared.requestId,
				status: error.kind,
			});
			// Reconnects and delay are reported since the last acknowledged
			// update, which is the burst that actually ended the stream.
			const state = (cause: MindcladeError): RetryState => ({
				attempts: failures,
				cause: cause.kind,
				cumulativeDelayMs,
			});
			if (!error.retryable || failures >= attempts) throw error.withRetryState(state(error));
			const delay = retryDelay(core, failures, error.retryAfterMs);
			if (delay >= prepared.deadlineMs - core.runtime.nowMs()) {
				const expired = MindcladeError.deadlineExceeded();
				throw expired.withRetryState(state(expired));
			}
			await core.runtime.sleep(delay, prepared.signal);
			cumulativeDelayMs += delay;
		}
	}
}
