import type {
	MindcladeClient,
	Operation,
	RawResponse,
	SdkCallOptions,
} from "@mindclade/internal-sdk";

/**
 * Read an operation together with the transport facts of the successful call.
 *
 * `withResponse()` runs the same validated method as `client.operations.get`
 * and additionally reports the call's status, request id, trace id, and the
 * allowlisted response metadata, so a success is exactly as correlatable as a
 * failure: the request id an SDK error would have carried is available when
 * nothing went wrong. Credential-bearing metadata is never exposed, and this
 * example reads no header of its own.
 */
export async function readOperationWithRequestId(
	client: MindcladeClient,
	operationName: string,
	options: SdkCallOptions = {},
): Promise<RawResponse<Operation>> {
	return await client.withResponse().operations.get(operationName, options);
}
