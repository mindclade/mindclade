import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, test } from "node:test";
import { create, toBinary } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { Code, ConnectError, createRouterTransport, type Transport } from "@connectrpc/connect";

import {
	ApprovalService,
	WorkflowService,
} from "../../../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";
import {
	ApprovalBindingSchema,
	ApprovalDecisionValue,
} from "../../../../protocols/generated/typescript/workflow/v1/approval_pb.js";
import { WorkflowRunState } from "../../../../protocols/generated/typescript/workflow/v1/workflow_run_pb.js";
import { MindcladeClient } from "../src/client.js";
import { ClientConfig, Environment } from "../src/config.js";
import { MindcladeError } from "../src/error.js";
import { FakeRuntime, RecordingTransport } from "../src/testing.js";
import { WorkflowRunFailure } from "../src/workflows.js";

const PARENT = "tenants/t-1/projects/p-1";
const DEFINITION = `${PARENT}/workflowDefinitions/definition-1`;
const RUN = `${PARENT}/workflowRuns/run-1`;
const APPROVAL = `${PARENT}/approvalRequests/approval-1`;
const RECEIPT = `${PARENT}/approvalReceipts/receipt-1`;
const TOKEN = "scheduler-issued-lease-token";

const config = ClientConfig.create({
	endpoint: "http://127.0.0.1:9443",
	environment: Environment.Local,
	identity: {
		principalId: "principals/worker-1",
		projectId: "projects/p-1",
		tenantId: "tenants/t-1",
	},
	insecureLoopbackForTesting: true,
	retry: { initialBackoffMs: 1, maxAttempts: 4, maxBackoffMs: 4 },
});

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

const sha256 = (value: Uint8Array | string): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;

const binding = () => {
	const value = create(ApprovalBindingSchema, {
		action: "workflow.transition",
		intentDigest: sha256("intent"),
		parametersDigest: sha256("parameters"),
		riskClass: "bounded",
	});
	value.bindingDigest = sha256(toBinary(ApprovalBindingSchema, value));
	return value;
};

const makeClient = (
	delegate: Transport,
	runtime: FakeRuntime,
): [MindcladeClient, RecordingTransport] => {
	const recorded = new RecordingTransport(delegate);
	return [MindcladeClient.withTransport(config, recorded, runtime), recorded];
};

describe("Workflow and Approval generated-contract facades", () => {
	test("cover every RPC with scope, identity, idempotency, fencing, and watch resume", async () => {
		const runtime = new FakeRuntime({
			now: 1_800_000_000_000,
			randomValues: [0, 0, 0, 0],
			requestIds: Array.from({ length: 32 }, (_, index) => `request-${index + 1}`),
		});
		const methods = new Set<string>();
		const commandContexts: Array<{
			canonicalRequestDigest: string;
			principalId: string;
			projectId: string;
			tenantId: string;
		}> = [];
		const leaseHeaders: Array<string | null> = [];
		let watchCalls = 0;
		const durableBinding = binding();
		const operation = { operationId: "operations/workflow-test" };
		const delegate = testTransport((router) => {
			router.service(WorkflowService, {
				createWorkflowDefinition(request, context) {
					methods.add("CreateWorkflowDefinition");
					assert.equal(request.parent, PARENT);
					assert.equal(request.workflowDefinition?.tenantId, "tenants/t-1");
					assert.equal(request.workflowDefinition?.projectId, "projects/p-1");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { operation };
				},
				updateWorkflowDefinition(request, context) {
					methods.add("UpdateWorkflowDefinition");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { operation };
				},
				getWorkflowDefinition(request) {
					methods.add("GetWorkflowDefinition");
					return { workflowDefinition: { name: request.name } };
				},
				listWorkflowDefinitions(request) {
					methods.add("ListWorkflowDefinitions");
					assert.equal(request.page?.pageToken, "opaque-definition");
					return { page: { nextPageToken: "next-definition" } };
				},
				startWorkflowRun(request, context) {
					methods.add("StartWorkflowRun");
					assert.equal(request.workflowRun?.definition?.resourceType, "workflow_definition");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { operation };
				},
				getWorkflowRun(request) {
					methods.add("GetWorkflowRun");
					return {
						workflowRun: {
							name: request.name,
							state: WorkflowRunState.RUNNING,
							transitionSequence: 1n,
						},
					};
				},
				listWorkflowRuns(request) {
					methods.add("ListWorkflowRuns");
					assert.equal(request.page?.pageToken, "opaque-run");
					return { page: { nextPageToken: "next-run" } };
				},
				cancelWorkflowRun(request, context) {
					methods.add("CancelWorkflowRun");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return { operation };
				},
				commitWorkflowTransition(request, context) {
					methods.add("CommitWorkflowTransition");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return {
						workflowRun: {
							name: request.workflowRun?.name ?? "",
							transitionSequence: request.expectedTransitionSequence + 1n,
						},
					};
				},
				async *watchWorkflowRun(request) {
					methods.add("WatchWorkflowRun");
					watchCalls += 1;
					if (request.afterTransitionSequence === 0n) {
						yield {
							workflowRun: {
								name: RUN,
								state: WorkflowRunState.RUNNING,
								transitionSequence: 1n,
							},
						};
						throw new ConnectError("retry watch", Code.Unavailable);
					}
					yield {
						workflowRun: {
							name: RUN,
							state: WorkflowRunState.SUCCEEDED,
							transitionSequence: request.afterTransitionSequence + 1n,
						},
					};
				},
			});
			router.service(ApprovalService, {
				requestApproval(request, context) {
					methods.add("RequestApproval");
					assert.ok(request.approvalRequest?.context !== undefined);
					if (request.approvalRequest?.context !== undefined) {
						commandContexts.push(request.approvalRequest.context);
					}
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return {
						approvalRequest: {
							...request.approvalRequest,
							name: APPROVAL,
						},
					};
				},
				getApprovalRequest(request) {
					methods.add("GetApprovalRequest");
					return { approvalRequest: { binding: durableBinding, name: request.name } };
				},
				listApprovalRequests(request) {
					methods.add("ListApprovalRequests");
					assert.equal(request.page?.pageToken, "opaque-approval");
					return { page: { nextPageToken: "next-approval" } };
				},
				decideApproval(request, context) {
					methods.add("DecideApproval");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return {
						approvalReceipt: {
							binding: durableBinding,
							decidedAt: timestampFromDate(new Date(runtime.nowMs())),
							decision: request.decision,
							name: RECEIPT,
							reasonCode: request.reasonCode,
							receiptDigest: sha256("receipt"),
							request: { name: request.name },
							safeReason: request.safeReason,
						},
					};
				},
				consumeApproval(request, context) {
					methods.add("ConsumeApproval");
					if (request.context !== undefined) commandContexts.push(request.context);
					leaseHeaders.push(context.requestHeader.get("x-mindclade-lease-token"));
					return {
						approvalReceipt: {
							binding: { ...durableBinding, bindingDigest: request.bindingDigest },
							consumedAt: timestampFromDate(new Date(runtime.nowMs())),
							consumedByCallId: request.callId,
							name: request.receiptName,
							receiptDigest: sha256("receipt"),
						},
					};
				},
			});
		});
		const [client, recorded] = makeClient(delegate, runtime);
		const { approvals, workflows } = client;

		await workflows.createDefinition(
			{ workflowDefinition: {}, workflowDefinitionId: "definition-1" },
			{ idempotencyKey: "create-definition" },
		);
		await workflows.updateDefinition(
			{
				etag: "etag-definition",
				updateMask: { paths: ["display_name"] },
				workflowDefinition: { name: DEFINITION },
			},
			{ idempotencyKey: "update-definition" },
		);
		assert.equal((await workflows.getDefinition(DEFINITION)).name, DEFINITION);
		assert.equal(
			(await workflows.listDefinitions({ page: { pageToken: "opaque-definition" } })).metadata
				.nextPageToken,
			"next-definition",
		);
		await workflows.startRun(
			{
				workflowRun: { definition: { name: DEFINITION } },
				workflowRunId: "run-1",
			},
			{ idempotencyKey: "start-run" },
		);
		assert.equal((await workflows.getRun(RUN)).name, RUN);
		assert.equal(
			(await workflows.listRuns({ page: { pageToken: "opaque-run" } })).metadata.nextPageToken,
			"next-run",
		);
		await workflows.cancelRun(
			{ etag: "etag-run", name: RUN, reason: "operator request" },
			{ idempotencyKey: "cancel-run" },
		);
		const committed = await workflows.commitTransition(
			{
				etag: "etag-run",
				expectedTransitionSequence: 1n,
				fence: {
					attemptId: "attempts/attempt-1",
					deadline: timestampFromDate(new Date(runtime.nowMs() + 60_000)),
					jobId: "jobs/job-1",
					leaseEpoch: 1n,
					leaseTokenDigest: sha256(TOKEN),
					runId: "runs/run-1",
				},
				workflowRun: { name: RUN },
			},
			{ idempotencyKey: "commit-transition", leaseToken: TOKEN },
		);
		assert.equal(committed.transitionSequence, 2n);
		const watched = [];
		for await (const run of workflows.watch(RUN, 0n, { waitTimeoutMs: 5_000 })) {
			watched.push(run.transitionSequence);
		}
		assert.deepEqual(watched, [1n, 2n]);
		assert.equal(
			(await workflows.wait(RUN, 1n, { waitTimeoutMs: 5_000 })).state,
			WorkflowRunState.SUCCEEDED,
		);

		const approval = await approvals.request(
			{ binding: durableBinding, requestedByPrincipalRef: "forged" },
			{ idempotencyKey: "request-approval" },
		);
		assert.equal(approval.name, APPROVAL);
		assert.equal(approval.requestedByPrincipalRef, "principals/worker-1");
		assert.equal((await approvals.get(APPROVAL)).name, APPROVAL);
		assert.equal(
			(await approvals.list({ page: { pageToken: "opaque-approval" } })).metadata.nextPageToken,
			"next-approval",
		);
		const receipt = await approvals.decide(
			{
				decision: ApprovalDecisionValue.APPROVE,
				etag: "etag-approval",
				name: APPROVAL,
				reasonCode: "approved",
				safeReason: "independent review complete",
			},
			{ idempotencyKey: "decide-approval" },
		);
		assert.equal(receipt.name, RECEIPT);
		assert.equal(
			(
				await approvals.consume(
					{
						bindingDigest: durableBinding.bindingDigest,
						callId: "call-1",
						receiptName: RECEIPT,
					},
					{ idempotencyKey: "consume-approval" },
				)
			).consumedByCallId,
			"call-1",
		);

		for (const method of [
			"CreateWorkflowDefinition",
			"UpdateWorkflowDefinition",
			"GetWorkflowDefinition",
			"ListWorkflowDefinitions",
			"StartWorkflowRun",
			"GetWorkflowRun",
			"ListWorkflowRuns",
			"CancelWorkflowRun",
			"CommitWorkflowTransition",
			"WatchWorkflowRun",
			"RequestApproval",
			"GetApprovalRequest",
			"ListApprovalRequests",
			"DecideApproval",
			"ConsumeApproval",
		]) {
			assert.equal(methods.has(method), true, `missing ${method}`);
		}
		assert.equal(watchCalls, 3);
		assert.equal(commandContexts.length, 8);
		assert.ok(
			commandContexts.every(
				(context) =>
					context.tenantId === "tenants/t-1" &&
					context.projectId === "projects/p-1" &&
					context.principalId === "principals/worker-1" &&
					/^sha256:[0-9a-f]{64}$/.test(context.canonicalRequestDigest),
			),
		);
		assert.equal(leaseHeaders.filter((header) => header !== null).length, 1);
		assert.equal(
			leaseHeaders.find((header) => header !== null),
			TOKEN,
		);
		assert.ok(recorded.calls.some((call) => call.method.endsWith("/WatchWorkflowRun")));
	});

	test("rejects invalid scope, pagination, and missing lease before transport", async () => {
		const runtime = new FakeRuntime();
		const [client, recorded] = makeClient(
			testTransport(() => undefined),
			runtime,
		);
		const { approvals, workflows } = client;
		await assert.rejects(
			workflows.getRun("tenants/other/projects/other/workflowRuns/run-1"),
			(error: unknown) => error instanceof MindcladeError && error.kind === "invalid_argument",
		);
		await assert.rejects(
			approvals.list({ page: { pageSize: 201 } }),
			(error: unknown) => error instanceof MindcladeError && error.kind === "invalid_argument",
		);
		await assert.rejects(
			workflows.commitTransition(
				{
					etag: "etag",
					fence: {
						attemptId: "attempt-1",
						deadline: timestampFromDate(new Date(runtime.nowMs() + 60_000)),
						jobId: "job-1",
						leaseEpoch: 1n,
						leaseTokenDigest: sha256(TOKEN),
						runId: "run-1",
					},
					workflowRun: { name: RUN },
				},
				{ idempotencyKey: "missing-lease" },
			),
			(error: unknown) => error instanceof MindcladeError && error.kind === "invalid_argument",
		);
		assert.equal(recorded.calls.length, 0);
	});

	test("wait returns a typed, non-enumerating generated terminal failure", async () => {
		const runtime = new FakeRuntime();
		const delegate = testTransport((router) => {
			router.service(WorkflowService, {
				async *watchWorkflowRun(request) {
					yield {
						workflowRun: {
							failure: { message: "not serialized" },
							name: RUN,
							state: WorkflowRunState.FAILED,
							transitionSequence: request.afterTransitionSequence + 1n,
						},
					};
				},
			});
		});
		const [client] = makeClient(delegate, runtime);
		const { workflows } = client;
		await assert.rejects(workflows.wait(RUN, 0n, { waitTimeoutMs: 5_000 }), (error: unknown) => {
			assert.ok(error instanceof WorkflowRunFailure);
			assert.equal(error.run.state, WorkflowRunState.FAILED);
			assert.equal(JSON.stringify(error).includes("not serialized"), false);
			return true;
		});
	});
});
