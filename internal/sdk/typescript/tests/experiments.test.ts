import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { createRouterTransport, type Transport } from "@connectrpc/connect";

import { ExperimentService } from "../../../../protocols/generated/typescript/internal/experiment/v1/experiment_service_pb.js";
import {
	ClientConfig,
	Environment,
	ExperimentKind,
	ExperimentState,
	FakeRuntime,
	MindcladeClient,
	StudyState,
	StudyType,
	TrialOutcome,
	TrialState,
} from "../src/index.js";

const PARENT = "tenants/t-1/projects/p-1";
const EXPERIMENT = `${PARENT}/experiments/experiment-1`;
const STUDY = `${EXPERIMENT}/studies/study-1`;
const TRIAL = `${STUDY}/trials/trial-1`;
const digest = (seed: string): string => `sha256:${seed.repeat(64)}`;
const artifact = (seed: string) => ({
	digest: digest(seed),
	integrityDigest: digest(seed),
	mediaType: "application/json",
	sizeBytes: 7n,
});
const reference = (resourceType: string, name: string) => ({
	resourceType,
	resourceId: name.split("/").at(-1) ?? "",
	tenantId: "t-1",
	projectId: "p-1",
	resourceVersion: 1n,
	name,
	etag: digest("e"),
});
const experiment = () => ({ name: EXPERIMENT, revision: 1n, etag: digest("e") });
const study = () => ({ name: STUDY, revision: 1n, etag: digest("e") });
const trial = () => ({ name: TRIAL, revision: 1n, etag: digest("e") });

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

describe("Experiment generated-contract facade", () => {
	test("routes all fourteen RPCs with bounded scope and authoritative command context", async () => {
		const calls: string[] = [];
		const contexts: string[] = [];
		const capture = (name: string, request: unknown): void => {
			calls.push(name);
			const command = (request as { command?: { context?: { canonicalRequestDigest: string } } })
				.command;
			if (command?.context !== undefined) contexts.push(command.context.canonicalRequestDigest);
		};
		const transport = testTransport((router) =>
			router.service(ExperimentService, {
				createExperiment(request, context) {
					assert.ok(context.requestHeader.has("x-request-id"));
					assert.equal(context.requestHeader.has("x-mindclade-request-id"), false);
					capture("CreateExperiment", request);
					return { experiment: experiment() };
				},
				getExperiment(request) {
					capture("GetExperiment", request);
					return { experiment: { name: request.name } };
				},
				listExperiments(request) {
					capture("ListExperiments", request);
					assert.equal(request.parent, PARENT);
					return { experiments: [experiment()], page: { nextPageToken: "next" } };
				},
				updateExperiment(request) {
					capture("UpdateExperiment", request);
					return { experiment: experiment() };
				},
				transitionExperiment(request) {
					capture("TransitionExperiment", request);
					return { experiment: experiment() };
				},
				createStudy(request) {
					capture("CreateStudy", request);
					return { study: study() };
				},
				getStudy(request) {
					capture("GetStudy", request);
					return { study: { name: request.name } };
				},
				listStudies(request) {
					capture("ListStudies", request);
					return { studies: [study()], page: { nextPageToken: "next" } };
				},
				transitionStudy(request) {
					capture("TransitionStudy", request);
					return { study: study() };
				},
				createTrial(request) {
					capture("CreateTrial", request);
					return { trial: trial() };
				},
				getTrial(request) {
					capture("GetTrial", request);
					return { trial: { name: request.name } };
				},
				listTrials(request) {
					capture("ListTrials", request);
					return { trials: [trial()], page: { nextPageToken: "next" } };
				},
				transitionTrial(request) {
					capture("TransitionTrial", request);
					return { trial: trial() };
				},
				completeTrial(request) {
					capture("CompleteTrial", request);
					return { trial: trial() };
				},
			}),
		);
		const sdk = MindcladeClient.withTransport(config, transport, new FakeRuntime());
		await sdk.experiments.create(
			{
				experimentId: "experiment-1",
				displayName: "Experiment",
				kind: ExperimentKind.SCIENTIFIC,
				intentManifest: artifact("a"),
				subjects: [reference("dataset", `${PARENT}/datasets/dataset-1`)],
				usePolicy: reference("use_policy", `${PARENT}/policies/policy-1`),
				policyClassification: "internal",
			},
			{ idempotencyKey: "experiment-create" },
		);
		assert.equal((await sdk.experiments.get(EXPERIMENT)).name, EXPERIMENT);
		assert.equal(
			(await sdk.experiments.list({ page: { pageSize: 10, pageToken: "opaque" } })).page
				?.nextPageToken,
			"next",
		);
		await sdk.experiments.update(
			{
				experiment: { ...experiment(), displayName: "Updated" },
				updateMask: { paths: ["display_name"] },
				etag: digest("e"),
			},
			{ idempotencyKey: "experiment-update" },
		);
		await sdk.experiments.transition(
			{
				experiment: reference("experiment", EXPERIMENT),
				expectedState: ExperimentState.DRAFT,
				targetState: ExperimentState.ACTIVE,
				etag: digest("e"),
				reasonCode: "INTENT_APPROVED",
			},
			{ idempotencyKey: "experiment-transition" },
		);
		await sdk.experiments.createStudy(
			{
				experiment: reference("experiment", EXPERIMENT),
				studyId: "study-1",
				type: StudyType.SCIENTIFIC,
				studyManifest: artifact("b"),
				baseConfiguration: artifact("c"),
				searchSpace: artifact("d"),
				objectiveSpecification: artifact("f"),
				budget: {
					maximumTrials: 8,
					maximumParallelTrials: 2,
					maximumDuration: { seconds: 3600n, nanos: 0 },
				},
			},
			{ idempotencyKey: "study-create" },
		);
		assert.equal((await sdk.experiments.getStudy(STUDY)).name, STUDY);
		assert.equal(
			(await sdk.experiments.listStudies({ parent: EXPERIMENT, page: { pageSize: 10 } })).page
				?.nextPageToken,
			"next",
		);
		await sdk.experiments.transitionStudy(
			{
				study: reference("study", STUDY),
				expectedState: StudyState.CREATED,
				targetState: StudyState.RUNNING,
				etag: digest("e"),
				reasonCode: "ADMISSION_OPEN",
			},
			{ idempotencyKey: "study-transition" },
		);
		await sdk.experiments.createTrial(
			{
				study: reference("study", STUDY),
				trialId: "trial-1",
				trialNumber: 1,
				resolvedConfiguration: artifact("1"),
			},
			{ idempotencyKey: "trial-create" },
		);
		assert.equal((await sdk.experiments.getTrial(TRIAL)).name, TRIAL);
		assert.equal(
			(await sdk.experiments.listTrials({ parent: STUDY, page: { pageSize: 10 } })).page
				?.nextPageToken,
			"next",
		);
		await sdk.experiments.transitionTrial(
			{
				trial: reference("trial", TRIAL),
				expectedState: TrialState.CREATED,
				targetState: TrialState.ADMITTED,
				etag: digest("e"),
				reasonCode: "CAPACITY_GRANTED",
			},
			{ idempotencyKey: "trial-transition" },
		);
		await sdk.experiments.completeTrial(
			{
				trial: reference("trial", TRIAL),
				outcome: TrialOutcome.SUCCEEDED,
				resultManifest: artifact("2"),
				etag: digest("e"),
			},
			{ idempotencyKey: "trial-complete" },
		);
		assert.deepEqual(calls, [
			"CreateExperiment",
			"GetExperiment",
			"ListExperiments",
			"UpdateExperiment",
			"TransitionExperiment",
			"CreateStudy",
			"GetStudy",
			"ListStudies",
			"TransitionStudy",
			"CreateTrial",
			"GetTrial",
			"ListTrials",
			"TransitionTrial",
			"CompleteTrial",
		]);
		assert.equal(contexts.length, 8);
		assert.ok(contexts.every((value) => /^sha256:[0-9a-f]{64}$/.test(value)));
	});

	test("rejects cross-project names and oversized pages before transport", async () => {
		const sdk = MindcladeClient.withTransport(
			config,
			testTransport(() => undefined),
			new FakeRuntime(),
		);
		await assert.rejects(
			sdk.experiments.get("tenants/other/projects/other/experiments/nope"),
			/configured scope/,
		);
		await assert.rejects(sdk.experiments.list({ page: { pageSize: 201 } }), /page size/);
	});
});
