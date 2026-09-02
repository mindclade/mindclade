import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { MindcladeClient, SdkCallOptions } from "@mindclade/internal-sdk";

import { followOperation } from "./follow_operation.js";

class FakeOperations {
	readonly calls: Array<{
		readonly name: string;
		readonly cursor: bigint;
		readonly options: SdkCallOptions;
	}> = [];

	async *watch(
		name: string,
		afterSequence: bigint,
		options: SdkCallOptions,
	): AsyncGenerator<{ readonly sequence: bigint }> {
		this.calls.push({ cursor: afterSequence, name, options });
		yield { sequence: afterSequence + 1n };
		yield { sequence: afterSequence + 2n };
	}
}

describe("followOperation", () => {
	test("passes the durable resume cursor, deadline, and cancellation to the SDK", async () => {
		const operations = new FakeOperations();
		const client = { operations } as unknown as MindcladeClient;
		const cancellation = new AbortController();
		const sequences: bigint[] = [];
		for await (const update of followOperation(client, "operations/op-1", 41n, {
			signal: cancellation.signal,
			timeoutMs: 5_000,
		})) {
			sequences.push(update.sequence);
		}
		assert.deepEqual(sequences, [42n, 43n]);
		assert.deepEqual(operations.calls, [
			{
				cursor: 41n,
				name: "operations/op-1",
				options: { signal: cancellation.signal, timeoutMs: 5_000 },
			},
		]);
	});
});
