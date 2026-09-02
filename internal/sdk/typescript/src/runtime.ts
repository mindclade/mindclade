import { randomInt, randomUUID } from "node:crypto";

import { MindcladeError } from "./error.js";

export interface Runtime {
	nowMs(): number;
	random(): number;
	requestId(): string;
	sleep(milliseconds: number, signal?: AbortSignal): Promise<void>;
}

/**
 * Jitter is drawn from the platform CSPRNG rather than `Math.random`, so
 * co-scheduled clients cannot be nudged into a shared retry phase, and the
 * source stays injectable through {@link Runtime} for deterministic tests.
 */
const CRYPTO_RANDOM_RANGE = 2 ** 47;

export const defaultRuntime: Runtime = {
	nowMs: Date.now,
	random: () => randomInt(0, CRYPTO_RANDOM_RANGE) / CRYPTO_RANDOM_RANGE,
	requestId: randomUUID,
	sleep: async (milliseconds, signal) => {
		if (signal?.aborted === true) throw MindcladeError.cancelled();
		await new Promise<void>((resolve, reject) => {
			const timer = setTimeout(() => {
				signal?.removeEventListener("abort", abort);
				resolve();
			}, milliseconds);
			const abort = (): void => {
				clearTimeout(timer);
				reject(MindcladeError.cancelled());
			};
			signal?.addEventListener("abort", abort, { once: true });
		});
	},
};
