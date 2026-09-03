import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { EvaluationService } from "../../../protocols/generated/typescript/internal/evaluation/v1/evaluation_service_pb.js";
import { ClientConfig, Environment, FakeRuntime, MindcladeClient } from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const RUN = `${PARENT}/evaluationRuns/evaluation-1`;
const RESULT = `${PARENT}/evaluationResults/result-1`;
const DECISION = `${PARENT}/promotionDecisions/decision-1`;
const MODEL_RELEASE = `${PARENT}/models/model-1/releases/v1`;
const digest = (character: string): string => `sha256:${character.repeat(64)}`;

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

const artifact = (kind: string) => ({
	artifactKind: kind,
	digest: digest("a"),
	integrityDigest: digest("b"),
	mediaType: "application/json",
	sizeBytes: 42n,
});
const reference = (resourceType: string, resourceId: string, name: string) => ({
	name,
	resourceId,
	resourceType,
});
const run = () => ({ name: RUN });
const result = () => ({
	name: RESULT,
	resultDigest: digest("d"),
	run: reference("evaluation_run", "evaluation-1", RUN),
	runDigest: digest("c"),
});
const decision = () => ({
	candidateDigest: digest("e"),
	candidateRelease: reference("model_release", "v1", MODEL_RELEASE),
	decisionDigest: digest("f"),
	evaluationResults: [reference("evaluation_result", "result-1", RESULT)],
	name: DECISION,
});

describe("Evaluation generated-contract facade", () => {
	test("covers all eight RPCs with scope, exact intent, and fenced metadata", async () => {
		const calls: string[] = [];
		const contexts: Array<{ digest: string; principal: string; project: string; tenant: string }> =
			[];
		let commitLease: string | null = null;
		const capture = (method: string, request: unknown): void => {
			calls.push(method);
			const command = request as {
				readonly context?: {
					readonly canonicalRequestDigest: string;
					readonly principalId: string;
					readonly projectId: string;
					readonly tenantId: string;
				};
			};
			if (command.context !== undefined)
				contexts.push({
					digest: command.context.canonicalRequestDigest,
					principal: command.context.principalId,
					project: command.context.projectId,
					tenant: command.context.tenantId,
				});
		};
		const transport = testTransport((router) => {
			router.service(EvaluationService, {
				createEvaluationRun(request) {
					capture("CreateEvaluationRun", request);
					assert.equal(request.parent, PARENT);
					return { operation: { operationId: "operations/create" } };
				},
				getEvaluationRun(request) {
					capture("GetEvaluationRun", request);
					return { evaluationRun: { name: request.name } };
				},
				listEvaluationRuns(request) {
					capture("ListEvaluationRuns", request);
					assert.equal(request.page?.pageToken, "opaque");
					return { page: { nextPageToken: "next" } };
				},
				cancelEvaluationRun(request) {
					capture("CancelEvaluationRun", request);
					return { operation: { operationId: "operations/cancel" } };
				},
				commitEvaluationResult(request, context) {
					capture("CommitEvaluationResult", request);
					commitLease = context.requestHeader.get("x-mindclade-lease-token");
					return { evaluationRun: run(), result: result() };
				},
				getEvaluationResult(request) {
					capture("GetEvaluationResult", request);
					return { result: { name: request.name } };
				},
				createPromotionDecision(request) {
					capture("CreatePromotionDecision", request);
					assert.equal(request.promotionDecision?.decidedByPrincipalRef, "principals/worker-1");
					return { operation: { operationId: "operations/decision" } };
				},
				getPromotionDecision(request) {
					capture("GetPromotionDecision", request);
					return { promotionDecision: { name: request.name } };
				},
			});
		});
		const client = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await client.evaluations.createRun(
			{
				datasets: [artifact("dataset")],
				evaluationRunId: "evaluation-1",
				inferenceProtocol: artifact("protocol"),
				modelRelease: reference("model_release", "v1", MODEL_RELEASE),
				snapshot: artifact("snapshot"),
				suite: artifact("suite"),
			},
			{ idempotencyKey: "create-evaluation" },
		);
		assert.equal((await client.evaluations.getRun(RUN)).name, RUN);
		assert.equal(
			(await client.evaluations.listRuns({ page: { pageSize: 10, pageToken: "opaque" } })).metadata
				.nextPageToken,
			"next",
		);
		await client.evaluations.cancelRun(
			{ etag: "etag", name: RUN, reason: "operator request" },
			{ idempotencyKey: "cancel-evaluation" },
		);
		await client.evaluations.commitResult(
			{
				etag: "etag",
				evaluationRun: reference("evaluation_run", "evaluation-1", RUN),
				fence: {
					attemptId: "attempts/a-1",
					deadline: timestampFromDate(new Date(1_800_001_000_000)),
					jobId: "jobs/j-1",
					leaseEpoch: 1n,
					leaseTokenDigest: digest("1"),
					runId: "runs/r-1",
				},
				result: result(),
			},
			{ idempotencyKey: "commit-evaluation", leaseToken: "opaque-lease-capability" },
		);
		assert.equal((await client.evaluations.getResult(RESULT)).name, RESULT);
		await client.evaluations.createPromotionDecision(
			{ promotionDecision: decision() },
			{ idempotencyKey: "create-decision" },
		);
		assert.equal((await client.evaluations.getPromotionDecision(DECISION)).name, DECISION);
		assert.equal(calls.length, 8);
		assert.equal(contexts.length, 4);
		assert.ok(
			contexts.every(
				(value) =>
					value.tenant === "tenants/t-1" &&
					value.project === "projects/p-1" &&
					value.principal === "principals/worker-1" &&
					/^sha256:[0-9a-f]{64}$/.test(value.digest),
			),
		);
		assert.equal(commitLease, "opaque-lease-capability");
	});
});
