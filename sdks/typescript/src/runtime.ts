import { randomUUID } from "node:crypto";

import { MindcladeError } from "./error.js";

export interface Runtime {
	nowMs(): number;
	random(): number;
	requestId(): string;
	sleep(milliseconds: number, signal?: AbortSignal): Promise<void>;
}

export const defaultRuntime: Runtime = {
	nowMs: Date.now,
	random: Math.random,
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
