import type { MindcladeClient, SdkCallOptions } from "@mindclade/internal-sdk";

/**
 * Follow a durable operation from an acknowledged sequence cursor.
 *
 * The SDK owns reconnection, monotonic sequence validation, deadlines, and
 * cancellation. Persist the last yielded sequence before acknowledging work,
 * then pass it back as `afterSequence` when the consumer restarts.
 */
export function followOperation(
	client: MindcladeClient,
	operationName: string,
	afterSequence = 0n,
	options: SdkCallOptions = {},
): ReturnType<MindcladeClient["operations"]["watch"]> {
	return client.operations.watch(operationName, afterSequence, options);
}
