import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type {
	AccessToken,
	EnvironmentSource,
	Operation,
	RawResponse,
	SdkCallOptions,
	TokenProvider,
} from "@mindclade/internal-sdk";
import { MindcladeClient, MindcladeError } from "@mindclade/internal-sdk";

import { clientFromEnvironment } from "./configure_client.js";
import { readOperationWithRequestId } from "./read_request_id.js";

class FakeRawOperations {
	readonly calls: Array<{
		readonly name: string;
		readonly options: SdkCallOptions;
	}> = [];

	async get(name: string, options: SdkCallOptions): Promise<RawResponse<Operation>> {
		this.calls.push({ name, options });
		return {
			metadata: new Map([["x-request-id", "request-7"]]),
			requestId: "request-7",
			status: { code: undefined, ok: true },
			traceId: "trace-7",
			value: { operationId: "operations/op-1" } as unknown as Operation,
		};
	}
}

class FakeTokenProvider implements TokenProvider {
	async getToken(): Promise<AccessToken> {
		throw new Error("the example never issues an RPC, so no token is minted");
	}
}

const completeEnvironment: EnvironmentSource = {
	MINDCLADE_ENVIRONMENT: "development",
	MINDCLADE_PRINCIPAL_ID: "principal-1",
	MINDCLADE_PROJECT_ID: "project-1",
	MINDCLADE_TENANT_ID: "tenant-1",
};

describe("readOperationWithRequestId", () => {
	test("reports the request id of a successful call and forwards the call verbatim", async () => {
		const operations = new FakeRawOperations();
		const client = {
			withResponse: () => ({ operations }),
		} as unknown as MindcladeClient;
		const raw = await readOperationWithRequestId(client, "operations/op-1", {
			timeoutMs: 5_000,
		});
		assert.equal(raw.requestId, "request-7");
		assert.equal(raw.traceId, "trace-7");
		assert.equal(raw.status.ok, true);
		assert.equal(raw.value.operationId, "operations/op-1");
		assert.deepEqual(operations.calls, [
			{ name: "operations/op-1", options: { timeoutMs: 5_000 } },
		]);
	});
});

describe("clientFromEnvironment", () => {
	test("builds a client from the supplied environment without reading a credential", () => {
		const client = clientFromEnvironment(new FakeTokenProvider(), {
			...completeEnvironment,
			MINDCLADE_ENDPOINT: "https://control-plane.example.internal:443",
		});
		assert.ok(client instanceof MindcladeClient);
		assert.equal(typeof client.operations.get, "function");
	});

	test("surfaces a missing variable as the SDK's own configuration error", () => {
		const { MINDCLADE_TENANT_ID: _omitted, ...incomplete } = completeEnvironment;
		assert.throws(
			() => clientFromEnvironment(new FakeTokenProvider(), incomplete),
			(reason: unknown) =>
				reason instanceof MindcladeError && /MINDCLADE_TENANT_ID/.test(reason.safeMessage),
		);
	});
});
