import assert from "node:assert/strict";
import process from "node:process";
import { describe, test } from "node:test";

import {
	Code,
	ConnectError,
	createRouterTransport,
	type Interceptor,
	type Transport,
} from "@connectrpc/connect";

import { OperationService } from "../../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { OperationState } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import {
	AccessToken,
	ClientConfig,
	clientConfigFromEnvironment,
	consoleLogger,
	Environment,
	type EnvironmentSource,
	FakeRuntime,
	isReservedMetadata,
	type LogFields,
	type Logger,
	type LogLevel,
	levelFromEnvironment,
	MAX_MESSAGE_BYTES,
	MindcladeClient,
	MindcladeError,
	type ObservedCall,
	type Observer,
	platformMetadata,
	RECOGNISED_ENVIRONMENT_VARIABLES,
	RESERVED_REQUEST_METADATA,
	SDK_VERSION,
	type TokenProvider,
} from "../src/index.js";

const OPERATION = "operations/op-config";

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

const identity = {
	principalId: "principals/worker-1",
	projectId: "projects/p-1",
	tenantId: "tenants/t-1",
};

class FakeTokenProvider implements TokenProvider {
	readonly #runtime: FakeRuntime;

	constructor(runtime: FakeRuntime = new FakeRuntime()) {
		this.#runtime = runtime;
	}

	async getToken(_audience: string, signal: AbortSignal): Promise<AccessToken> {
		if (signal.aborted) throw signal.reason;
		return new AccessToken("short-lived-test-token", this.#runtime.nowMs() + 3_600_000);
	}
}

class RecordingObserver implements Observer {
	readonly events: ObservedCall[] = [];

	onCall(event: ObservedCall): void {
		this.events.push(event);
	}
}

class RecordingLogger implements Logger {
	readonly records: Array<{
		readonly level: LogLevel;
		readonly message: string;
		readonly fields: LogFields;
	}> = [];

	log(level: LogLevel, message: string, fields: LogFields): void {
		this.records.push({ fields, level, message });
	}
}

const loopback = (input: Partial<Parameters<typeof ClientConfig.create>[0]> = {}): ClientConfig =>
	ClientConfig.create({
		endpoint: "http://127.0.0.1:9443",
		environment: Environment.Local,
		identity,
		insecureLoopbackForTesting: true,
		...input,
	});

/** Answers `GetOperation` and hands the request metadata back to the test. */
const capturingTransport = (headers: Headers[], failFirst = false): Transport =>
	testTransport((router) => {
		router.service(OperationService, {
			getOperation(_request, context) {
				headers.push(new Headers(context.requestHeader));
				if (failFirst && headers.length === 1) {
					throw new ConnectError("transient", Code.Unavailable);
				}
				return {
					operation: { done: true, operationId: OPERATION, state: OperationState.SUCCEEDED },
				};
			},
		});
	});

const environmentSource = (
	overrides: Readonly<Record<string, string>> = {},
): EnvironmentSource => ({
	MINDCLADE_ENVIRONMENT: "local",
	MINDCLADE_PRINCIPAL_ID: "principals/worker-1",
	MINDCLADE_PROJECT_ID: "projects/p-1",
	MINDCLADE_TENANT_ID: "tenants/t-1",
	...overrides,
});

describe("configuration, escape hatches, and observability", () => {
	test("fromEnvironment is the only environment-reading path and reads no credential", () => {
		assert.deepEqual(
			[...RECOGNISED_ENVIRONMENT_VARIABLES],
			[
				"MINDCLADE_AUDIENCE",
				"MINDCLADE_ENDPOINT",
				"MINDCLADE_ENVIRONMENT",
				"MINDCLADE_LOG",
				"MINDCLADE_PRINCIPAL_ID",
				"MINDCLADE_PROJECT_ID",
				"MINDCLADE_TENANT_ID",
			],
		);
		for (const name of RECOGNISED_ENVIRONMENT_VARIABLES) {
			assert.equal(/token|secret|key|credential|password/i.test(name), false);
		}

		const config = clientConfigFromEnvironment({
			env: environmentSource({
				MINDCLADE_API_KEY: "must-never-be-read",
				MINDCLADE_ENDPOINT: "http://127.0.0.1:9443",
				MINDCLADE_LOG: "DEBUG",
				MINDCLADE_TOKEN: "must-never-be-read",
			}),
			insecureLoopbackForTesting: true,
		});
		assert.equal(config.environment, Environment.Local);
		assert.equal(config.endpoint, "http://127.0.0.1:9443");
		assert.equal(config.identity.tenantId, "tenants/t-1");
		assert.equal(config.logLevel, "debug");
		assert.notEqual(config.logger, undefined);
		// A credential can only ever arrive through an explicitly constructed provider.
		assert.equal(config.tokenProvider, undefined);
		assert.equal(JSON.stringify(config).includes("must-never-be-read"), false);
	});

	test("fromEnvironment rejects an unknown environment and a missing identity", () => {
		assert.throws(
			() =>
				clientConfigFromEnvironment({ env: environmentSource({ MINDCLADE_ENVIRONMENT: "prod" }) }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "configuration",
		);
		const incomplete = { ...environmentSource() } as Record<string, string | undefined>;
		delete incomplete.MINDCLADE_TENANT_ID;
		assert.throws(
			() => clientConfigFromEnvironment({ env: incomplete }),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "configuration",
		);
	});

	test("the ordinary constructor never consults the process environment", () => {
		const saved = process.env.MINDCLADE_ENDPOINT;
		process.env.MINDCLADE_ENDPOINT = "http://127.0.0.1:1/";
		try {
			const config = ClientConfig.create({
				environment: Environment.Development,
				identity,
				tokenProvider: new FakeTokenProvider(),
			});
			assert.equal(config.endpoint, "https://control-plane.development.mindclade.internal:443");
		} finally {
			if (saved === undefined) delete process.env.MINDCLADE_ENDPOINT;
			else process.env.MINDCLADE_ENDPOINT = saved;
		}
	});

	test("MindcladeClient.fromEnvironment builds a usable client", () => {
		const client = MindcladeClient.fromEnvironment({
			env: environmentSource({ MINDCLADE_ENDPOINT: "http://127.0.0.1:9443" }),
			insecureLoopbackForTesting: true,
		});
		assert.ok(client instanceof MindcladeClient);
		assert.equal(typeof client.operations.watch, "function");
	});

	test("custom metadata reaches the wire and credential-bearing names are refused", async () => {
		const headers: Headers[] = [];
		const client = MindcladeClient.withTransport(
			loopback({ metadata: { "x-deploy-channel": "canary" } }),
			capturingTransport(headers),
			new FakeRuntime(),
		);
		await client.operations.get(OPERATION);
		assert.equal(headers[0]?.get("x-deploy-channel"), "canary");

		for (const name of ["authorization", "x-mindclade-lease-token", "x-secret-key", "Cookie"]) {
			assert.throws(
				() => loopback({ metadata: { [name]: "value" } }),
				(reason: unknown) => reason instanceof MindcladeError && reason.kind === "configuration",
				`${name} must be refused`,
			);
		}
		for (const name of RESERVED_REQUEST_METADATA) {
			assert.ok(isReservedMetadata(name.toUpperCase()));
			assert.throws(() => loopback({ metadata: { [name]: "forged" } }));
		}
	});

	test("interceptors observe correlation metadata but never a credential", async () => {
		const seen: Array<readonly string[]> = [];
		const runtime = new FakeRuntime();
		const forging: Interceptor = (next) => async (request) => {
			seen.push([...request.header.keys()].sort());
			request.header.set("authorization", "Bearer forged-by-interceptor");
			request.header.set("x-interceptor-note", "observed");
			return await next(request);
		};
		const headers: Headers[] = [];
		const client = MindcladeClient.withTransport(
			ClientConfig.create({
				environment: Environment.Development,
				identity,
				interceptors: [forging],
				tokenProvider: new FakeTokenProvider(runtime),
			}),
			capturingTransport(headers),
			runtime,
		);
		await client.operations.get(OPERATION);

		assert.equal(seen.length, 1);
		assert.ok(seen[0]?.includes("x-request-id"));
		// Credential injection runs below the interceptor chain.
		assert.equal(seen[0]?.includes("authorization"), false);
		// A decoration an interceptor adds does reach the wire...
		assert.equal(headers[0]?.get("x-interceptor-note"), "observed");
		// ...but a forged credential is stripped and replaced by the SDK's own.
		assert.notEqual(headers[0]?.get("authorization"), "Bearer forged-by-interceptor");
		assert.match(headers[0]?.get("authorization") ?? "", /short-lived-test-token/);
	});

	test("x-mindclade-sdk carries bounded structured platform facts", async () => {
		const headers: Headers[] = [];
		await MindcladeClient.withTransport(
			loopback(),
			capturingTransport(headers),
			new FakeRuntime(),
		).operations.get(OPERATION);
		const value = headers[0]?.get("x-mindclade-sdk") ?? "";
		assert.equal(value, platformMetadata(false));
		assert.match(
			value,
			new RegExp(
				`^mindclade-internal-typescript-sdk/${SDK_VERSION.replace(/\./g, "\\.")};` +
					"lang=typescript;os=[A-Za-z0-9._-]+;arch=[A-Za-z0-9._-]+;" +
					"runtime=[A-Za-z0-9._-]+;runtime_version=[A-Za-z0-9._-]+$",
			),
		);
		assert.ok(value.length <= 512);

		const omitted: Headers[] = [];
		await MindcladeClient.withTransport(
			loopback({ omitPlatformMetadata: true }),
			capturingTransport(omitted),
			new FakeRuntime(),
		).operations.get(OPERATION);
		assert.equal(
			omitted[0]?.get("x-mindclade-sdk"),
			`mindclade-internal-typescript-sdk/${SDK_VERSION};lang=typescript`,
		);
	});

	test("the observer records key names only, never values", async () => {
		const observer = new RecordingObserver();
		const logger = new RecordingLogger();
		const runtime = new FakeRuntime({ randomValues: [0] });
		const headers: Headers[] = [];
		const client = MindcladeClient.withTransport(
			loopback({ logLevel: "debug", logger, observer }),
			capturingTransport(headers, true),
			runtime,
		);
		await client.operations.get(OPERATION, { leaseToken: "super-secret-lease" });

		assert.equal(observer.events.length, 2);
		const [failed, succeeded] = observer.events;
		assert.equal(failed?.method, "/mindclade.internal.job.v1.OperationService/GetOperation");
		assert.equal(failed?.attempt, 0);
		assert.equal(failed?.status, "remote");
		assert.equal(failed?.code, Code.Unavailable);
		assert.equal(succeeded?.attempt, 1);
		assert.equal(succeeded?.status, "ok");
		assert.equal(succeeded?.code, undefined);
		assert.equal(succeeded?.requestId, "test-request-id");
		assert.ok(succeeded?.metadataKeys.includes("x-mindclade-lease-token"));
		assert.ok(succeeded?.metadataKeys.includes("x-mindclade-retry-count"));
		assert.deepEqual(
			[...(succeeded?.metadataKeys ?? [])],
			[...(succeeded?.metadataKeys ?? [])].sort(),
		);
		// Never a value: not the lease token, not a credential, not a payload.
		const serialized = JSON.stringify(observer.events);
		assert.equal(serialized.includes("super-secret-lease"), false);
		assert.equal(serialized.includes("authorization"), false);
		assert.equal(serialized.includes(OPERATION), false);

		assert.equal(logger.records.length, 2);
		assert.deepEqual(
			logger.records.map((record) => record.level),
			["warn", "debug"],
		);
		const logged = JSON.stringify(logger.records);
		assert.equal(logged.includes("super-secret-lease"), false);
		assert.match(String(logger.records[1]?.fields.metadata_keys), /x-mindclade-lease-token/);
		assert.equal(
			logger.records[1]?.fields.method,
			"/mindclade.internal.job.v1.OperationService/GetOperation",
		);
	});

	test("a throwing observer never changes the outcome of the call", async () => {
		const client = MindcladeClient.withTransport(
			loopback({
				observer: {
					onCall() {
						throw new Error("observers must not be able to fail a call");
					},
				},
			}),
			capturingTransport([]),
			new FakeRuntime(),
		);
		assert.equal((await client.operations.get(OPERATION)).operationId, OPERATION);
	});

	test("MINDCLADE_LOG parsing and the default logger honour the level", () => {
		assert.equal(levelFromEnvironment("DEBUG"), "debug");
		assert.equal(levelFromEnvironment("  warn "), "warn");
		assert.equal(levelFromEnvironment("verbose"), undefined);
		assert.equal(levelFromEnvironment(undefined), undefined);

		const lines: string[] = [];
		const original = process.stderr.write.bind(process.stderr);
		process.stderr.write = ((chunk: string) => {
			lines.push(String(chunk));
			return true;
		}) as typeof process.stderr.write;
		try {
			const logger = consoleLogger("warn");
			logger.log("debug", "dropped", { method: "x" });
			logger.log("warn", "kept", { method: "x" });
		} finally {
			process.stderr.write = original;
		}
		assert.equal(lines.length, 1);
		assert.deepEqual(JSON.parse(lines[0] ?? "{}"), {
			level: "warn",
			message: "kept",
			method: "x",
		});
	});

	test("the message-size ceiling matches every other mindclade SDK", () => {
		assert.equal(MAX_MESSAGE_BYTES, 8 * 1_024 * 1_024);
	});
});
