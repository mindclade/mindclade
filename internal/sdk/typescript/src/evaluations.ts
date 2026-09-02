import { createHash } from "node:crypto";
import { clone, create, type MessageInitShape, toBinary } from "@bufbuild/protobuf";

import type { ArtifactRef } from "../../../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import type { ResourceRef } from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	type EvaluationResult,
	EvaluationResultSchema,
} from "../../../../protocols/generated/typescript/evaluation/v1/evaluation_result_pb.js";
import {
	type EvaluationRun,
	EvaluationRunSchema,
} from "../../../../protocols/generated/typescript/evaluation/v1/evaluation_run_pb.js";
import {
	type PromotionDecision,
	PromotionDecisionSchema,
} from "../../../../protocols/generated/typescript/evaluation/v1/promotion_decision_pb.js";
import {
	CancelEvaluationRunRequestSchema,
	CommitEvaluationResultRequestSchema,
	CreateEvaluationRunRequestSchema,
	CreatePromotionDecisionRequestSchema,
	GetEvaluationResultRequestSchema,
	GetEvaluationRunRequestSchema,
	GetPromotionDecisionRequestSchema,
	ListEvaluationRunsRequestSchema,
	type ListEvaluationRunsResponse,
} from "../../../../protocols/generated/typescript/internal/evaluation/v1/evaluation_service_pb.js";
import type { LeaseFence } from "../../../../protocols/generated/typescript/job/v1/lease_fencing_pb.js";
import {
	type Operation,
	OperationSchema,
} from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { listPage, type Page, withPageToken } from "./pagination.js";
import {
	commandContext,
	type ListOptions,
	prepareCall,
	type SdkCallOptions,
	type SubmitOptions,
} from "./request.js";
import { invokeUnary } from "./retry.js";

const CREATE = "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun";
const GET_RUN = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun";
const LIST = "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns";
const CANCEL = "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun";
const COMMIT = "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult";
const GET_RESULT = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult";
const CREATE_DECISION =
	"/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision";
const GET_DECISION = "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision";
const DIGEST = /^sha256:[0-9a-f]{64}$/;

/** Generated-type-only evaluation execution and evidence-governance facade. */
export class Evaluations {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async createRun(
		input: MessageInitShape<typeof CreateEvaluationRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(CreateEvaluationRunRequestSchema, input);
		const parent = projectName(this.#core);
		if (
			(request.parent !== "" && request.parent !== parent) ||
			!validId(request.evaluationRunId) ||
			request.datasets.length < 1 ||
			request.datasets.length > 256
		) {
			throw MindcladeError.invalidArgument(
				"evaluation creation requires configured scope, a valid ID, and bounded datasets",
			);
		}
		validateArtifact(request.suite, "evaluation suite");
		validateArtifact(request.snapshot, "evaluation snapshot");
		validateArtifact(request.inferenceProtocol, "inference protocol");
		for (const dataset of request.datasets) validateArtifact(dataset, "evaluation dataset");
		if (request.modelRelease === undefined)
			throw MindcladeError.invalidArgument("evaluation model release is required");
		normalizeReference(this.#core, request.modelRelease, "model_release", "/models/");
		request.parent = parent;
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CreateEvaluationRunRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE,
			options.idempotencyKey,
			(call) => this.#core.raw.evaluations.createEvaluationRun(request, call),
		);
		return requiredOperation(response.operation, "CreateEvaluationRun");
	}

	async getRun(
		name: string,
		ifNoneMatch = "",
		options: SdkCallOptions = {},
	): Promise<EvaluationRun> {
		const scoped = scopedName(this.#core, name, "evaluationRuns");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET_RUN,
			undefined,
			(call) =>
				this.#core.raw.evaluations.getEvaluationRun(
					create(GetEvaluationRunRequestSchema, { name: scoped, ifNoneMatch }),
					call,
				),
		);
		if (response.evaluationRun === undefined || response.evaluationRun.name !== scoped)
			throw MindcladeError.protocol("GetEvaluationRun response violated resource identity");
		return clone(EvaluationRunSchema, response.evaluationRun);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listRuns(
		input: MessageInitShape<typeof ListEvaluationRunsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<EvaluationRun, ListEvaluationRunsResponse>> {
		const request = create(ListEvaluationRunsRequestSchema, input);
		const parent = projectName(this.#core);
		const pageSize = request.page?.pageSize ?? 0;
		if (
			(request.parent !== "" && request.parent !== parent) ||
			!Number.isInteger(pageSize) ||
			pageSize < 0 ||
			pageSize > 200
		)
			throw MindcladeError.invalidArgument("evaluation list scope or page size is invalid");
		request.parent = parent;
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListEvaluationRunsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					prepared,
					LIST,
					undefined,
					(call) => this.#core.raw.evaluations.listEvaluationRuns(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.evaluationRuns,
			limits: options.limits,
			pageSize,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async cancelRun(
		input: MessageInitShape<typeof CancelEvaluationRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(CancelEvaluationRunRequestSchema, input);
		request.name = scopedName(this.#core, request.name, "evaluationRuns");
		if (request.etag.trim() === "" || request.reason.trim() === "")
			throw MindcladeError.invalidArgument("evaluation cancellation requires an etag and reason");
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CancelEvaluationRunRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CANCEL,
			options.idempotencyKey,
			(call) => this.#core.raw.evaluations.cancelEvaluationRun(request, call),
		);
		return requiredOperation(response.operation, "CancelEvaluationRun");
	}

	async commitResult(
		input: MessageInitShape<typeof CommitEvaluationResultRequestSchema>,
		options: SubmitOptions,
	): Promise<readonly [EvaluationResult, EvaluationRun]> {
		const request = create(CommitEvaluationResultRequestSchema, input);
		if (
			request.evaluationRun === undefined ||
			request.fence === undefined ||
			request.result === undefined ||
			request.result.run === undefined ||
			request.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument("evaluation result commit is incomplete");
		}
		if (options.leaseToken === undefined)
			throw MindcladeError.invalidArgument(
				"fenced evaluation result commit requires a lease token",
			);
		normalizeReference(this.#core, request.evaluationRun, "evaluation_run", "/evaluationRuns/");
		normalizeReference(this.#core, request.result.run, "evaluation_run", "/evaluationRuns/");
		request.result.name = scopedName(this.#core, request.result.name, "evaluationResults");
		if (
			request.result.run.name !== request.evaluationRun.name ||
			!DIGEST.test(request.result.runDigest) ||
			!DIGEST.test(request.result.resultDigest)
		) {
			throw MindcladeError.invalidArgument("evaluation result identity or digest is invalid");
		}
		normalizeFence(this.#core, request.fence);
		const resultName = request.result.name;
		const runName = request.evaluationRun.name;
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CommitEvaluationResultRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT,
			options.idempotencyKey,
			(call) => this.#core.raw.evaluations.commitEvaluationResult(request, call),
		);
		if (
			response.result === undefined ||
			response.evaluationRun === undefined ||
			response.result.name !== resultName ||
			response.evaluationRun.name !== runName
		) {
			throw MindcladeError.protocol("CommitEvaluationResult response violated durable identity");
		}
		return [
			clone(EvaluationResultSchema, response.result),
			clone(EvaluationRunSchema, response.evaluationRun),
		];
	}

	async getResult(name: string, options: SdkCallOptions = {}): Promise<EvaluationResult> {
		const scoped = scopedName(this.#core, name, "evaluationResults");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET_RESULT,
			undefined,
			(call) =>
				this.#core.raw.evaluations.getEvaluationResult(
					create(GetEvaluationResultRequestSchema, { name: scoped }),
					call,
				),
		);
		if (response.result === undefined || response.result.name !== scoped)
			throw MindcladeError.protocol("GetEvaluationResult response violated resource identity");
		return clone(EvaluationResultSchema, response.result);
	}

	async createPromotionDecision(
		input: MessageInitShape<typeof CreatePromotionDecisionRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(CreatePromotionDecisionRequestSchema, input);
		const decision = request.promotionDecision;
		if (
			decision === undefined ||
			decision.candidateRelease === undefined ||
			!DIGEST.test(decision.candidateDigest) ||
			!DIGEST.test(decision.decisionDigest) ||
			decision.evaluationResults.length === 0
		) {
			throw MindcladeError.invalidArgument("promotion decision evidence or digest is invalid");
		}
		decision.name = scopedName(this.#core, decision.name, "promotionDecisions");
		normalizeReference(this.#core, decision.candidateRelease, "model_release", "/models/");
		for (const result of decision.evaluationResults)
			normalizeReference(this.#core, result, "evaluation_result", "/evaluationResults/");
		for (const policy of decision.policyDecisions) {
			if (
				(policy.tenantId !== "" && policy.tenantId !== this.#core.config.identity.tenantId) ||
				(policy.projectId !== "" && policy.projectId !== this.#core.config.identity.projectId)
			) {
				throw MindcladeError.invalidArgument(
					"promotion policy evidence conflicts with client scope",
				);
			}
			policy.tenantId = this.#core.config.identity.tenantId;
			policy.projectId = this.#core.config.identity.projectId;
		}
		decision.decidedByPrincipalRef = this.#core.config.identity.principalId;
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CreatePromotionDecisionRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE_DECISION,
			options.idempotencyKey,
			(call) => this.#core.raw.evaluations.createPromotionDecision(request, call),
		);
		return requiredOperation(response.operation, "CreatePromotionDecision");
	}

	async getPromotionDecision(
		name: string,
		options: SdkCallOptions = {},
	): Promise<PromotionDecision> {
		const scoped = scopedName(this.#core, name, "promotionDecisions");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET_DECISION,
			undefined,
			(call) =>
				this.#core.raw.evaluations.getPromotionDecision(
					create(GetPromotionDecisionRequestSchema, { name: scoped }),
					call,
				),
		);
		if (response.promotionDecision === undefined || response.promotionDecision.name !== scoped)
			throw MindcladeError.protocol("GetPromotionDecision response violated resource identity");
		return clone(PromotionDecisionSchema, response.promotionDecision);
	}
}

const projectName = (core: ClientCore): string => {
	const tenant = core.config.identity.tenantId.startsWith("tenants/")
		? core.config.identity.tenantId
		: `tenants/${core.config.identity.tenantId}`;
	const project = core.config.identity.projectId;
	if (project.startsWith("tenants/")) return project;
	return project.startsWith("projects/") ? `${tenant}/${project}` : `${tenant}/projects/${project}`;
};

const scopedName = (core: ClientCore, name: string, collection: string): string => {
	const prefix = `${projectName(core)}/${collection}/`;
	const id = name.startsWith(prefix) ? name.slice(prefix.length) : "";
	if (!validId(id)) throw MindcladeError.invalidArgument("resource is outside configured scope");
	return name;
};

const normalizeReference = (
	core: ClientCore,
	value: ResourceRef,
	resourceType: string,
	requiredPath: string,
): void => {
	const parent = projectName(core);
	const id = value.name.split("/").at(-1) ?? "";
	if (
		!value.name.startsWith(`${parent}/`) ||
		!value.name.includes(requiredPath) ||
		!validId(id) ||
		(value.resourceType !== "" && value.resourceType !== resourceType) ||
		(value.resourceId !== "" && value.resourceId !== id) ||
		(value.tenantId !== "" && value.tenantId !== core.config.identity.tenantId) ||
		(value.projectId !== "" && value.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("resource reference conflicts with evaluation intent");
	}
	value.resourceType = resourceType;
	value.resourceId = id;
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};

const validateArtifact = (value: ArtifactRef | undefined, label: string): void => {
	if (
		value === undefined ||
		!DIGEST.test(value.digest) ||
		(value.integrityDigest !== "" && !DIGEST.test(value.integrityDigest)) ||
		value.mediaType.trim() === "" ||
		value.sizeBytes < 0n
	) {
		throw MindcladeError.invalidArgument(`${label} is invalid`);
	}
};

const normalizeFence = (core: ClientCore, value: LeaseFence): void => {
	const deadlineMs =
		value.deadline === undefined
			? 0
			: Number(value.deadline.seconds) * 1_000 + Math.floor(value.deadline.nanos / 1_000_000);
	if (
		value.jobId === "" ||
		value.runId === "" ||
		value.attemptId === "" ||
		value.leaseEpoch <= 0n ||
		!DIGEST.test(value.leaseTokenDigest) ||
		deadlineMs <= core.runtime.nowMs() ||
		(value.tenantId !== "" && value.tenantId !== core.config.identity.tenantId) ||
		(value.projectId !== "" && value.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("evaluation lease fence is invalid or expired");
	}
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};

const contextWithDigest = (
	core: ClientCore,
	prepared: ReturnType<typeof prepareCall>,
	options: SubmitOptions,
	digest: string,
) => ({ ...commandContext(core.config, prepared, options), canonicalRequestDigest: digest });

const requiredOperation = (operation: Operation | undefined, method: string): Operation => {
	if (operation === undefined || operation.operationId.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	return clone(OperationSchema, operation);
};

const validId = (value: string): boolean => /^[A-Za-z0-9._-]{1,128}$/.test(value);
const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;
