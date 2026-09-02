import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, test } from "node:test";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { AgentService } from "../../../../protocols/generated/typescript/internal/agent/v1/agent_service_pb.js";
import {
	ClientConfig,
	Environment,
	FakeRuntime,
	MindcladeClient,
	MindcladeError,
} from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const DEFINITION = `${PARENT}/agentDefinitions/definition-1`;
const RUN = `${PARENT}/agentRuns/run-1`;
const STEP = `${RUN}/agentSteps/step-1`;
const RECEIPT = `${PARENT}/toolReceipts/receipt-1`;

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
	identity: {
		principalId: "principals/worker-1",
		projectId: "projects/p-1",
		tenantId: "tenants/t-1",
	},
	insecureLoopbackForTesting: true,
});

const reference = (resourceType: string, collection: string, resourceId: string) => ({
	name: `${PARENT}/${collection}/${resourceId}`,
	resourceId,
	resourceType,
});

const definition = (name = "") => ({
	eligibleTools: [reference("tool", "tools", "tool-1")],
	evaluationSuite: reference("evaluation_suite", "evaluationSuites", "evaluation-1"),
	name,
	workflowDefinition: reference("workflow_definition", "workflowDefinitions", "workflow-1"),
});

const tokenDigest = (token: string): string =>
	`sha256:${createHash("sha256").update(token).digest("hex")}`;

describe("Agent generated-contract facade", () => {
	test("covers all 12 RPCs with identity, idempotency, pagination, and fenced metadata", async () => {
		const methods: string[] = [];
		const contexts: Array<{
			tenantId: string;
			projectId: string;
			principalId: string;
			digest: string;
		}> = [];
		const headers: Headers[] = [];
		const capture = (method: string, request: unknown, requestHeaders: Headers): void => {
			const command = request as {
				readonly context?: {
					readonly tenantId: string;
					readonly projectId: string;
					readonly principalId: string;
					readonly canonicalRequestDigest: string;
				};
			};
			methods.push(method);
			headers.push(new Headers(requestHeaders));
			if (command.context !== undefined) {
				contexts.push({
					digest: command.context.canonicalRequestDigest,
					principalId: command.context.principalId,
					projectId: command.context.projectId,
					tenantId: command.context.tenantId,
				});
			}
		};
		const transport = testTransport((router) => {
			router.service(AgentService, {
				createAgentDefinition(request, context) {
					capture("CreateAgentDefinition", request, context.requestHeader);
					assert.equal(request.parent, PARENT);
					return { operation: { operationId: "operations/create-definition" } };
				},
				updateAgentDefinition(request, context) {
					capture("UpdateAgentDefinition", request, context.requestHeader);
					return { operation: { operationId: "operations/update-definition" } };
				},
				getAgentDefinition(request, context) {
					capture("GetAgentDefinition", request, context.requestHeader);
					return { agentDefinition: { name: request.name } };
				},
				listAgentDefinitions(request, context) {
					capture("ListAgentDefinitions", request, context.requestHeader);
					assert.equal(request.page?.pageToken, "opaque-definition");
					return { page: { nextPageToken: "next-definition" } };
				},
				startAgentRun(request, context) {
					capture("StartAgentRun", request, context.requestHeader);
					return { operation: { operationId: "operations/start-run" } };
				},
				getAgentRun(request, context) {
					capture("GetAgentRun", request, context.requestHeader);
					return { agentRun: { name: request.name } };
				},
				listAgentRuns(request, context) {
					capture("ListAgentRuns", request, context.requestHeader);
					assert.equal(request.page?.pageToken, "opaque-run");
					return { page: { nextPageToken: "next-run" } };
				},
				cancelAgentRun(request, context) {
					capture("CancelAgentRun", request, context.requestHeader);
					return { operation: { operationId: "operations/cancel-run" } };
				},
				getAgentStep(request, context) {
					capture("GetAgentStep", request, context.requestHeader);
					return { agentStep: { name: request.name } };
				},
				listAgentSteps(request, context) {
					capture("ListAgentSteps", request, context.requestHeader);
					assert.equal(request.page?.pageToken, "opaque-step");
					return { page: { nextPageToken: "next-step" } };
				},
				commitAgentStep(request, context) {
					capture("CommitAgentStep", request, context.requestHeader);
					if (request.agentStep?.run === undefined) throw new Error("missing test step");
					const acceptedStep = request.agentStep;
					const acceptedRun = request.agentStep.run;
					return {
						agentRun: { name: RUN },
						agentStep: {
							name: STEP,
							run: acceptedRun,
							sequence: acceptedStep.sequence,
						},
					};
				},
				commitToolReceipt(request, context) {
					capture("CommitToolReceipt", request, context.requestHeader);
					if (request.toolReceipt === undefined) throw new Error("missing test receipt");
					return { agentRun: { name: RUN }, toolReceipt: request.toolReceipt };
				},
			});
		});
		const runtime = new FakeRuntime({ now: 1_800_000_000_000 });
		const client = MindcladeClient.withTransport(config, transport, runtime);

		const createInput = {
			agentDefinition: definition(),
			agentDefinitionId: "definition-1",
			context: { principalId: "forged" },
		};
		const originalCreate = structuredClone(createInput);
		assert.equal(
			(
				await client.agents.createDefinition(createInput, {
					idempotencyKey: "create-definition-1",
				})
			).operationId,
			"operations/create-definition",
		);
		assert.deepEqual(createInput, originalCreate);
		await client.agents.updateDefinition(
			{
				agentDefinition: definition(DEFINITION),
				etag: "etag-1",
				updateMask: { paths: ["purpose"] },
			},
			{ idempotencyKey: "update-definition-1" },
		);
		assert.equal((await client.agents.getDefinition(DEFINITION)).name, DEFINITION);
		assert.equal(
			(
				await client.agents.listDefinitions({
					page: { pageSize: 10, pageToken: "opaque-definition" },
				})
			).page?.nextPageToken,
			"next-definition",
		);
		await client.agents.startRun(
			{
				agentRun: {
					budgetReservation: reference("budget_reservation", "budgetReservations", "budget-1"),
					definition: reference("agent_definition", "agentDefinitions", "definition-1"),
				},
				agentRunId: "run-1",
			},
			{ idempotencyKey: "start-run-1" },
		);
		assert.equal((await client.agents.getRun(RUN)).name, RUN);
		assert.equal(
			(
				await client.agents.listRuns({
					page: { pageSize: 10, pageToken: "opaque-run" },
				})
			).page?.nextPageToken,
			"next-run",
		);
		await client.agents.cancelRun(
			{ etag: "etag-2", name: RUN, reason: "operator request" },
			{ idempotencyKey: "cancel-run-1" },
		);
		assert.equal((await client.agents.getStep(STEP)).name, STEP);
		assert.equal(
			(
				await client.agents.listSteps({
					page: { pageSize: 10, pageToken: "opaque-step" },
					parent: RUN,
				})
			).page?.nextPageToken,
			"next-step",
		);

		const leaseToken = "scheduler-issued-agent-token";
		const fence = {
			attemptId: "attempts/attempt-1",
			deadline: timestampFromDate(new Date(runtime.nowMs() + 60_000)),
			jobId: "jobs/job-1",
			leaseEpoch: 1n,
			leaseTokenDigest: tokenDigest(leaseToken),
			runId: "runs/run-1",
		};
		const [step, run] = await client.agents.commitStep(
			{
				agentStep: {
					run: reference("agent_run", "agentRuns", "run-1"),
					sequence: 1n,
				},
				expectedNextStepSequence: 1n,
				fence,
				runEtag: "etag-3",
			},
			{ idempotencyKey: "commit-step-1", leaseToken },
		);
		assert.deepEqual([step.name, run.name], [STEP, RUN]);
		const [receipt, receiptRun] = await client.agents.commitToolReceipt(
			{
				fence,
				runEtag: "etag-4",
				toolReceipt: {
					agentRunName: RUN,
					agentStepName: STEP,
					callId: "call-1",
					name: RECEIPT,
					tool: reference("tool", "tools", "tool-1"),
				},
			},
			{ idempotencyKey: "commit-receipt-1", leaseToken },
		);
		assert.deepEqual([receipt.name, receiptRun.name], [RECEIPT, RUN]);

		assert.deepEqual(methods, [
			"CreateAgentDefinition",
			"UpdateAgentDefinition",
			"GetAgentDefinition",
			"ListAgentDefinitions",
			"StartAgentRun",
			"GetAgentRun",
			"ListAgentRuns",
			"CancelAgentRun",
			"GetAgentStep",
			"ListAgentSteps",
			"CommitAgentStep",
			"CommitToolReceipt",
		]);
		assert.equal(contexts.length, 6);
		assert.ok(
			contexts.every(
				(context) =>
					context.tenantId === "tenants/t-1" &&
					context.projectId === "projects/p-1" &&
					context.principalId === "principals/worker-1" &&
					/^sha256:[0-9a-f]{64}$/.test(context.digest),
			),
		);
		assert.ok(headers.slice(0, 10).every((value) => !value.has("x-mindclade-lease-token")));
		assert.equal(headers[10]?.get("x-mindclade-lease-token"), leaseToken);
		assert.equal(headers[11]?.get("x-mindclade-lease-token"), leaseToken);
	});

	test("rejects unfenced worker commits and oversized pages before transport", async () => {
		const client = MindcladeClient.withTransport(
			config,
			testTransport(() => undefined),
			new FakeRuntime({ now: 1_800_000_000_000 }),
		);
		await assert.rejects(
			client.agents.commitStep(
				{
					agentStep: {
						run: reference("agent_run", "agentRuns", "run-1"),
						sequence: 1n,
					},
					expectedNextStepSequence: 1n,
					fence: {
						attemptId: "attempts/attempt-1",
						deadline: timestampFromDate(new Date(1_800_000_060_000)),
						jobId: "jobs/job-1",
						leaseEpoch: 1n,
						leaseTokenDigest: tokenDigest("token"),
						runId: "runs/run-1",
					},
					runEtag: "etag-1",
				},
				{ idempotencyKey: "commit-step-1" },
			),
			(reason: unknown) => reason instanceof MindcladeError && reason.kind === "invalid_argument",
		);
		await assert.rejects(
			client.agents.listSteps({ parent: RUN, page: { pageSize: 201 } }),
			MindcladeError,
		);
	});
});
