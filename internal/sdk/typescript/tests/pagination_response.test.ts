import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { DatasetService } from "../../../../protocols/generated/typescript/internal/dataset/v1/dataset_service_pb.js";
import { ExperimentService } from "../../../../protocols/generated/typescript/internal/experiment/v1/experiment_service_pb.js";
import {
	ClientConfig,
	Environment,
	FakeRuntime,
	isCredentialBearing,
	MindcladeClient,
	MindcladeError,
	Page,
	SAFE_RESPONSE_METADATA,
} from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const dataset = (id: string) => ({ name: `${PARENT}/datasets/${id}` });
const digest = (seed: string): string => `sha256:${seed.repeat(64)}`;

const testTransport = (routes: Parameters<typeof createRouterTransport>[0]): Transport => {
	const delegate = createRouterTransport(routes);
	return {
		unary(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.unary(method, signal, undefined, header, input, contextValues);
		},
		stream(method, signal, _timeoutMs, header, input, contextValues) {
			return delegate.stream(method, signal, undefined, header, input, contextValues);
		},
	};
};

const config = ClientConfig.create({
	endpoint: "http://127.0.0.1:9443",
	environment: Environment.Local,
	identity: { principalId: "principal-1", projectId: "p-1", tenantId: "t-1" },
	insecureLoopbackForTesting: true,
});

/** Two pages: `dataset-1`/`dataset-2`, then `dataset-3` and an exhausted cursor. */
const twoPageDatasets =
	(tokens: string[]): Parameters<typeof createRouterTransport>[0] =>
	(router) => {
		router.service(DatasetService, {
			listDatasets(request) {
				const token = request.page?.pageToken ?? "";
				tokens.push(token);
				if (token === "") {
					return {
						datasets: [dataset("dataset-1"), dataset("dataset-2")],
						page: { nextPageToken: "opaque cursor two" },
					};
				}
				return { datasets: [dataset("dataset-3")], page: { nextPageToken: "" } };
			},
		});
	};

const clientFor = (routes: Parameters<typeof createRouterTransport>[0]): MindcladeClient =>
	MindcladeClient.withTransport(config, testTransport(routes), new FakeRuntime());

describe("auto-pagination", () => {
	test("a list method returns a page that iterates every item across the cursor", async () => {
		const tokens: string[] = [];
		const client = clientFor(twoPageDatasets(tokens));
		const page = await client.datasets.list();
		assert.ok(page instanceof Page);
		const names: string[] = [];
		for await (const value of page) names.push(value.name);
		assert.deepEqual(names, [
			`${PARENT}/datasets/dataset-1`,
			`${PARENT}/datasets/dataset-2`,
			`${PARENT}/datasets/dataset-3`,
		]);
		assert.deepEqual(tokens, ["", "opaque cursor two"]);
	});

	test("the caller's opaque token reaches the first request without normalization", async () => {
		const tokens: string[] = [];
		const client = clientFor((router) => {
			router.service(DatasetService, {
				listDatasets(request) {
					tokens.push(request.page?.pageToken ?? "");
					return { datasets: [dataset("dataset-1")], page: { nextPageToken: "" } };
				},
			});
		});
		const page = await client.datasets.list({ page: { pageToken: " padded token " } });
		assert.deepEqual(tokens, [" padded token "]);
		assert.equal(page.metadata.pageToken, " padded token ");
	});

	test("page-level access exposes the cursor and stops at the end of the traversal", async () => {
		const tokens: string[] = [];
		const client = clientFor(twoPageDatasets(tokens));
		const first = await client.datasets.list({ page: { pageSize: 2 } });
		assert.equal(first.hasNextPage, true);
		assert.equal(first.metadata.pageIndex, 0);
		assert.equal(first.metadata.pageToken, "");
		assert.equal(first.metadata.nextPageToken, "opaque cursor two");
		assert.equal(first.metadata.pageSize, 2);
		assert.equal(first.metadata.requestId, "test-request-id");
		assert.equal(first.items.length, 2);
		assert.equal(first.response.page?.nextPageToken, "opaque cursor two");

		const second = await first.nextPage();
		assert.ok(second !== undefined);
		assert.equal(second.metadata.pageIndex, 1);
		assert.equal(second.metadata.pageToken, "opaque cursor two");
		assert.equal(second.hasNextPage, false);
		assert.equal(await second.nextPage(), undefined);

		const sizes: number[] = [];
		for await (const observed of first.pages()) sizes.push(observed.items.length);
		assert.deepEqual(sizes, [2, 1]);
		// The second page was memoized, so re-traversal issued no further RPC.
		assert.deepEqual(tokens, ["", "opaque cursor two"]);
	});

	test("the item budget fails closed instead of presenting a partial traversal", async () => {
		const client = clientFor(twoPageDatasets([]));
		const page = await client.datasets.list({}, { limits: { maxItems: 1 } });
		const names: string[] = [];
		await assert.rejects(
			async () => {
				for await (const value of page) names.push(value.name);
			},
			(error: unknown) => {
				assert.ok(error instanceof MindcladeError);
				assert.equal(error.kind, "pagination_limit");
				return true;
			},
		);
		assert.deepEqual(names, [`${PARENT}/datasets/dataset-1`]);
	});

	test("the page budget fails closed before the next request is issued", async () => {
		const tokens: string[] = [];
		const client = clientFor(twoPageDatasets(tokens));
		const page = await client.datasets.list({}, { limits: { maxPages: 1 } });
		await assert.rejects(
			async () => {
				for await (const _ of page) {
					// Drain until the budget refuses the second page.
				}
			},
			(error: unknown) => {
				assert.ok(error instanceof MindcladeError);
				assert.equal(error.kind, "pagination_limit");
				return true;
			},
		);
		assert.deepEqual(tokens, [""]);
	});

	test("budgets outside the hard caps are rejected before any request", async () => {
		const tokens: string[] = [];
		const client = clientFor(twoPageDatasets(tokens));
		await assert.rejects(
			client.datasets.list({}, { limits: { maxPages: 1_001 } }),
			/pagination max pages/,
		);
		await assert.rejects(
			client.datasets.list({}, { limits: { maxItems: 1_000_001 } }),
			/pagination max items/,
		);
		assert.deepEqual(tokens, []);
	});

	test("a repeated opaque cursor is reported as a protocol violation", async () => {
		const client = clientFor((router) => {
			router.service(DatasetService, {
				listDatasets() {
					return { datasets: [dataset("dataset-1")], page: { nextPageToken: "loop" } };
				},
			});
		});
		const page = await client.datasets.list();
		await assert.rejects(
			async () => {
				for await (const _ of page) {
					// Drain until the repeated cursor is detected.
				}
			},
			(error: unknown) => {
				assert.ok(error instanceof MindcladeError);
				assert.equal(error.kind, "protocol");
				return true;
			},
		);
	});

	test("cancellation is observed between pages", async () => {
		const tokens: string[] = [];
		const controller = new AbortController();
		const client = clientFor(twoPageDatasets(tokens));
		const page = await client.datasets.list({}, { signal: controller.signal });
		controller.abort();
		await assert.rejects(page.nextPage(), (error: unknown) => {
			assert.ok(error instanceof MindcladeError);
			assert.equal(error.kind, "cancelled");
			return true;
		});
		assert.deepEqual(tokens, [""]);
	});

	test("per-page response validation re-runs for every fetched page", async () => {
		const client = clientFor((router) => {
			router.service(ExperimentService, {
				listExperiments(request) {
					const token = request.page?.pageToken ?? "";
					if (token === "") {
						return {
							experiments: [
								{ etag: digest("e"), name: `${PARENT}/experiments/experiment-1`, revision: 1n },
							],
							page: { nextPageToken: "second" },
						};
					}
					return {
						experiments: [
							{
								etag: digest("e"),
								name: "tenants/t-9/projects/p-9/experiments/experiment-2",
								revision: 1n,
							},
						],
						page: { nextPageToken: "" },
					};
				},
			});
		});
		const page = await client.experiments.list();
		assert.equal(page.items.length, 1);
		await assert.rejects(
			async () => {
				for await (const _ of page) {
					// Drain until the second page escapes the configured project.
				}
			},
			(error: unknown) => {
				assert.ok(error instanceof MindcladeError);
				assert.equal(error.kind, "invalid_argument");
				return true;
			},
		);
	});
});

describe("raw responses", () => {
	const envelopeRoutes: Parameters<typeof createRouterTransport>[0] = (router) => {
		router.service(DatasetService, {
			getDataset(request, context) {
				context.responseHeader.set("x-request-id", "server-request-id");
				context.responseHeader.set("x-trace-id", "server-trace-id");
				context.responseHeader.set("x-mindclade-sdk", "control-plane/9.9");
				context.responseHeader.set("authorization", "Bearer super-secret-value");
				context.responseHeader.set("x-mindclade-lease-token", "lease-secret-value");
				context.responseHeader.set("set-cookie", "session=secret-value");
				context.responseHeader.set("x-unlisted-header", "not-allowlisted");
				return { dataset: { name: request.name } };
			},
			listDatasets(request) {
				const token = request.page?.pageToken ?? "";
				if (token === "") {
					return {
						datasets: [dataset("dataset-1")],
						page: { nextPageToken: "opaque cursor two" },
					};
				}
				return { datasets: [dataset("dataset-2")], page: { nextPageToken: "" } };
			},
		});
	};

	test("withResponse exposes status, identifiers, and allowlisted metadata only", async () => {
		const client = clientFor(envelopeRoutes);
		const name = `${PARENT}/datasets/dataset-1`;
		const raw = await client.withResponse().datasets.get({ name });
		assert.equal(raw.value.name, name);
		assert.equal(raw.status.ok, true);
		assert.equal(raw.status.code, undefined);
		assert.equal(raw.requestId, "server-request-id");
		assert.equal(raw.traceId, "server-trace-id");
		assert.equal(raw.metadata.get("x-mindclade-sdk"), "control-plane/9.9");
		for (const key of raw.metadata.keys()) assert.ok(SAFE_RESPONSE_METADATA.includes(key));
	});

	test("withResponse never surfaces credential-bearing metadata", async () => {
		const client = clientFor(envelopeRoutes);
		const raw = await client.withResponse().datasets.get({
			name: `${PARENT}/datasets/dataset-1`,
		});
		for (const key of raw.metadata.keys()) assert.equal(isCredentialBearing(key), false);
		assert.equal(raw.metadata.has("authorization"), false);
		assert.equal(raw.metadata.has("x-mindclade-lease-token"), false);
		assert.equal(raw.metadata.has("set-cookie"), false);
		assert.equal(raw.metadata.has("x-unlisted-header"), false);
		assert.doesNotMatch(JSON.stringify([...raw.metadata]), /super-secret-value|lease-secret-value/);
	});

	test("withResponse wraps a list method without losing the page behaviour", async () => {
		const client = clientFor(envelopeRoutes);
		const raw = await client.withResponse().datasets.list();
		assert.ok(raw.value instanceof Page);
		assert.equal(raw.value.hasNextPage, true);
		const names: string[] = [];
		for await (const value of raw.value) names.push(value.name);
		assert.deepEqual(names, [`${PARENT}/datasets/dataset-1`, `${PARENT}/datasets/dataset-2`]);
	});

	test("an unknown raw-response method is rejected rather than silently ignored", async () => {
		const client = clientFor(envelopeRoutes);
		const namespace = client.withResponse().datasets as unknown as Record<
			string,
			() => Promise<unknown>
		>;
		const call = namespace.notAMethod as (() => Promise<unknown>) | undefined;
		assert.equal(typeof call, "function");
		await assert.rejects(
			async () => await (call as () => Promise<unknown>)(),
			/raw-response method/,
		);
	});

	test("the credential denylist screens every credential-shaped metadata name", () => {
		for (const name of [
			"authorization",
			"Proxy-Authorization",
			"cookie",
			"set-cookie",
			"x-api-key",
			"x-goog-api-key",
			"x-mindclade-lease-token",
			"x-service-token",
			"client_secret",
			"db-password",
			"x-signing-credential",
		]) {
			assert.equal(isCredentialBearing(name), true, name);
		}
		for (const name of SAFE_RESPONSE_METADATA) assert.equal(isCredentialBearing(name), false, name);
	});
});
