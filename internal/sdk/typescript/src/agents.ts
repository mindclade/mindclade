import { createHash } from "node:crypto";
import { clone, create, type MessageInitShape, toBinary } from "@bufbuild/protobuf";
import { timestampDate } from "@bufbuild/protobuf/wkt";

import {
	type AgentDefinition,
	AgentDefinitionSchema,
} from "../../../../protocols/generated/typescript/agent/v1/agent_definition_pb.js";
import {
	type AgentRun,
	AgentRunSchema,
} from "../../../../protocols/generated/typescript/agent/v1/agent_run_pb.js";
import {
	type AgentStep,
	AgentStepSchema,
} from "../../../../protocols/generated/typescript/agent/v1/agent_step_pb.js";
import {
	type ToolReceipt,
	ToolReceiptSchema,
} from "../../../../protocols/generated/typescript/agent/v1/tool_receipt_pb.js";
import type { ResourceRef } from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	CancelAgentRunRequestSchema,
	CommitAgentStepRequestSchema,
	CommitToolReceiptRequestSchema,
	CreateAgentDefinitionRequestSchema,
	GetAgentDefinitionRequestSchema,
	GetAgentRunRequestSchema,
	GetAgentStepRequestSchema,
	ListAgentDefinitionsRequestSchema,
	type ListAgentDefinitionsResponse,
	ListAgentDefinitionsResponseSchema,
	ListAgentRunsRequestSchema,
	type ListAgentRunsResponse,
	ListAgentRunsResponseSchema,
	ListAgentStepsRequestSchema,
	type ListAgentStepsResponse,
	ListAgentStepsResponseSchema,
	StartAgentRunRequestSchema,
	UpdateAgentDefinitionRequestSchema,
} from "../../../../protocols/generated/typescript/internal/agent/v1/agent_service_pb.js";
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
	type PreparedCall,
	prepareCall,
	type SdkCallOptions,
	type SubmitOptions,
} from "./request.js";
import { invokeUnary } from "./retry.js";

const CREATE_DEFINITION = "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition";
const UPDATE_DEFINITION = "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition";
const GET_DEFINITION = "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition";
const LIST_DEFINITIONS = "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions";
const START_RUN = "/mindclade.internal.agent.v1.AgentService/StartAgentRun";
const GET_RUN = "/mindclade.internal.agent.v1.AgentService/GetAgentRun";
const LIST_RUNS = "/mindclade.internal.agent.v1.AgentService/ListAgentRuns";
const CANCEL_RUN = "/mindclade.internal.agent.v1.AgentService/CancelAgentRun";
const GET_STEP = "/mindclade.internal.agent.v1.AgentService/GetAgentStep";
const LIST_STEPS = "/mindclade.internal.agent.v1.AgentService/ListAgentSteps";
const COMMIT_STEP = "/mindclade.internal.agent.v1.AgentService/CommitAgentStep";
const COMMIT_RECEIPT = "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt";
const MAXIMUM_PAGE_SIZE = 200;
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const RESOURCE_ID = /^[a-z][a-z0-9-]{0,62}$/;

/** Generated-type-only facade for bounded agent definitions, durable runs,
 * append-only steps, and immutable execution receipts. */
export class Agents {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async createDefinition(
		input: MessageInitShape<typeof CreateAgentDefinitionRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(CreateAgentDefinitionRequestSchema, input);
		request.parent = projectParent(this.#core, request.parent, "agent definition");
		resourceId("agent definition ID", request.agentDefinitionId);
		if (request.agentDefinition === undefined) {
			throw MindcladeError.invalidArgument("agent definition is required");
		}
		normalizeDefinition(this.#core, request.agentDefinition, true);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(CreateAgentDefinitionRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE_DEFINITION,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.createAgentDefinition(request, call),
		);
		return operation(response.operation, "CreateAgentDefinition");
	}

	async updateDefinition(
		input: MessageInitShape<typeof UpdateAgentDefinitionRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(UpdateAgentDefinitionRequestSchema, input);
		if (
			request.agentDefinition === undefined ||
			request.updateMask === undefined ||
			request.updateMask.paths.length === 0 ||
			request.updateMask.paths.length > 32 ||
			request.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"agent definition update requires a definition, one to 32 mask paths, and an ETag",
			);
		}
		normalizeDefinition(this.#core, request.agentDefinition, false);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(UpdateAgentDefinitionRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			UPDATE_DEFINITION,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.updateAgentDefinition(request, call),
		);
		return operation(response.operation, "UpdateAgentDefinition");
	}

	async getDefinition(
		name: string,
		ifNoneMatch = "",
		options: SdkCallOptions = {},
	): Promise<AgentDefinition> {
		const expected = scopedName(this.#core, name, "agentDefinitions");
		const request = create(GetAgentDefinitionRequestSchema, {
			ifNoneMatch: ifNoneMatch.trim(),
			name: expected,
		});
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_DEFINITION, undefined, (call) =>
			this.#core.raw.agents.getAgentDefinition(request, call),
		);
		if (response.agentDefinition === undefined || response.agentDefinition.name !== expected) {
			throw MindcladeError.protocol("GetAgentDefinition returned an invalid resource identity");
		}
		return clone(AgentDefinitionSchema, response.agentDefinition);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listDefinitions(
		input: MessageInitShape<typeof ListAgentDefinitionsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<AgentDefinition, ListAgentDefinitionsResponse>> {
		const request = create(ListAgentDefinitionsRequestSchema, input);
		request.parent = projectParent(this.#core, request.parent, "agent definition list");
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListAgentDefinitionsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					prepared,
					LIST_DEFINITIONS,
					undefined,
					(call) => this.#core.raw.agents.listAgentDefinitions(paged, call),
				);
				return {
					requestId: prepared.requestId,
					response: clone(ListAgentDefinitionsResponseSchema, response),
				};
			},
			items: (response) => response.agentDefinitions,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async startRun(
		input: MessageInitShape<typeof StartAgentRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(StartAgentRunRequestSchema, input);
		request.parent = projectParent(this.#core, request.parent, "agent run");
		resourceId("agent run ID", request.agentRunId);
		if (request.agentRun?.definition === undefined) {
			throw MindcladeError.invalidArgument(
				"agent run intent and definition reference are required",
			);
		}
		normalizeReference(
			this.#core,
			request.agentRun.definition,
			"agent_definition",
			"agentDefinitions",
		);
		if (request.agentRun.workflowRun !== undefined) {
			normalizeReference(this.#core, request.agentRun.workflowRun, "workflow_run", "workflowRuns");
		}
		if (request.agentRun.budgetReservation === undefined) {
			throw MindcladeError.invalidArgument("agent run budget reservation is required");
		}
		normalizeReference(this.#core, request.agentRun.budgetReservation);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(StartAgentRunRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			START_RUN,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.startAgentRun(request, call),
		);
		return operation(response.operation, "StartAgentRun");
	}

	async getRun(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<AgentRun> {
		const expected = scopedName(this.#core, name, "agentRuns");
		const request = create(GetAgentRunRequestSchema, {
			ifNoneMatch: ifNoneMatch.trim(),
			name: expected,
		});
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_RUN, undefined, (call) =>
			this.#core.raw.agents.getAgentRun(request, call),
		);
		return requiredRun(response.agentRun, expected, "GetAgentRun");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listRuns(
		input: MessageInitShape<typeof ListAgentRunsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<AgentRun, ListAgentRunsResponse>> {
		const request = create(ListAgentRunsRequestSchema, input);
		request.parent = projectParent(this.#core, request.parent, "agent run list");
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListAgentRunsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST_RUNS, undefined, (call) =>
					this.#core.raw.agents.listAgentRuns(paged, call),
				);
				return {
					requestId: prepared.requestId,
					response: clone(ListAgentRunsResponseSchema, response),
				};
			},
			items: (response) => response.agentRuns,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async cancelRun(
		input: MessageInitShape<typeof CancelAgentRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = create(CancelAgentRunRequestSchema, input);
		request.name = scopedName(this.#core, request.name, "agentRuns");
		requiredText("agent run ETag", request.etag, 1024);
		requiredText("agent cancellation reason", request.reason, 1024);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(CancelAgentRunRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CANCEL_RUN,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.cancelAgentRun(request, call),
		);
		return operation(response.operation, "CancelAgentRun");
	}

	async getStep(name: string, options: SdkCallOptions = {}): Promise<AgentStep> {
		const expected = stepName(this.#core, name);
		const request = create(GetAgentStepRequestSchema, { name: expected });
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_STEP, undefined, (call) =>
			this.#core.raw.agents.getAgentStep(request, call),
		);
		if (response.agentStep === undefined || response.agentStep.name !== expected) {
			throw MindcladeError.protocol("GetAgentStep returned an invalid resource identity");
		}
		return clone(AgentStepSchema, response.agentStep);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listSteps(
		input: MessageInitShape<typeof ListAgentStepsRequestSchema>,
		options: ListOptions = {},
	): Promise<Page<AgentStep, ListAgentStepsResponse>> {
		const request = create(ListAgentStepsRequestSchema, input);
		request.parent = scopedName(this.#core, request.parent, "agentRuns");
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListAgentStepsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST_STEPS, undefined, (call) =>
					this.#core.raw.agents.listAgentSteps(paged, call),
				);
				return {
					requestId: prepared.requestId,
					response: clone(ListAgentStepsResponseSchema, response),
				};
			},
			items: (response) => response.agentSteps,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async commitStep(
		input: MessageInitShape<typeof CommitAgentStepRequestSchema>,
		options: SubmitOptions,
	): Promise<readonly [AgentStep, AgentRun]> {
		const request = create(CommitAgentStepRequestSchema, input);
		if (
			request.agentStep?.run === undefined ||
			request.fence === undefined ||
			request.runEtag.trim() === "" ||
			request.expectedNextStepSequence <= 0n ||
			request.agentStep.sequence !== request.expectedNextStepSequence
		) {
			throw MindcladeError.invalidArgument(
				"agent step commit requires a consistent step, fence, run ETag, and next sequence",
			);
		}
		normalizeReference(this.#core, request.agentStep.run, "agent_run", "agentRuns");
		const expectedRun = request.agentStep.run.name;
		const expectedSequence = request.expectedNextStepSequence;
		validateFence(this.#core, request.fence);
		delete request.context;
		const prepared = fencedCall(this.#core, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(CommitAgentStepRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT_STEP,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.commitAgentStep(request, call),
		);
		if (
			response.agentStep === undefined ||
			response.agentRun === undefined ||
			response.agentStep.sequence !== expectedSequence ||
			response.agentStep.run?.name !== expectedRun ||
			response.agentRun.name !== expectedRun
		) {
			throw MindcladeError.protocol("CommitAgentStep returned inconsistent durable state");
		}
		return [clone(AgentStepSchema, response.agentStep), clone(AgentRunSchema, response.agentRun)];
	}

	async commitToolReceipt(
		input: MessageInitShape<typeof CommitToolReceiptRequestSchema>,
		options: SubmitOptions,
	): Promise<readonly [ToolReceipt, AgentRun]> {
		const request = create(CommitToolReceiptRequestSchema, input);
		if (
			request.toolReceipt?.tool === undefined ||
			request.fence === undefined ||
			request.runEtag.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"tool receipt commit requires generated evidence, a fence, and a run ETag",
			);
		}
		const expectedName = scopedName(this.#core, request.toolReceipt.name, "toolReceipts");
		const expectedRun = scopedName(this.#core, request.toolReceipt.agentRunName, "agentRuns");
		stepName(this.#core, request.toolReceipt.agentStepName);
		normalizeReference(this.#core, request.toolReceipt.tool);
		const expectedCall = requiredText("tool receipt call ID", request.toolReceipt.callId, 512);
		validateFence(this.#core, request.fence);
		delete request.context;
		const prepared = fencedCall(this.#core, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			toBinary(CommitToolReceiptRequestSchema, request),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT_RECEIPT,
			options.idempotencyKey,
			(call) => this.#core.raw.agents.commitToolReceipt(request, call),
		);
		if (
			response.toolReceipt === undefined ||
			response.agentRun === undefined ||
			response.toolReceipt.name !== expectedName ||
			response.toolReceipt.callId !== expectedCall ||
			response.agentRun.name !== expectedRun
		) {
			throw MindcladeError.protocol("CommitToolReceipt returned inconsistent durable evidence");
		}
		return [
			clone(ToolReceiptSchema, response.toolReceipt),
			clone(AgentRunSchema, response.agentRun),
		];
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

const projectParent = (core: ClientCore, value: string, label: string): string => {
	const expected = projectName(core);
	if (value.trim() !== "" && value !== expected) {
		throw MindcladeError.invalidArgument(`${label} parent must match the configured project`);
	}
	return expected;
};

const resourceId = (label: string, value: string): string => {
	if (!RESOURCE_ID.test(value)) {
		throw MindcladeError.invalidArgument(
			`${label} must start with a letter and contain at most 63 lowercase letters, digits, or hyphens`,
		);
	}
	return value;
};

const scopedName = (core: ClientCore, value: string, collection: string): string => {
	const prefix = `${projectName(core)}/${collection}/`;
	const identifier = value.startsWith(prefix) ? value.slice(prefix.length) : "";
	if (!RESOURCE_ID.test(identifier)) {
		throw MindcladeError.invalidArgument(`${collection} name is outside the configured project`);
	}
	return value;
};

const stepName = (core: ClientCore, value: string): string => {
	const prefix = `${projectName(core)}/agentRuns/`;
	const remainder = value.startsWith(prefix) ? value.slice(prefix.length) : "";
	const parts = remainder.split("/agentSteps/");
	if (
		parts.length !== 2 ||
		!RESOURCE_ID.test(parts[0] ?? "") ||
		!RESOURCE_ID.test(parts[1] ?? "")
	) {
		throw MindcladeError.invalidArgument(
			"agent step name must be scoped to a configured-project run",
		);
	}
	return value;
};

const normalizeScope = (core: ClientCore, value: { tenantId: string; projectId: string }): void => {
	if (
		(value.tenantId !== "" && value.tenantId !== core.config.identity.tenantId) ||
		(value.projectId !== "" && value.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("resource scope conflicts with client identity");
	}
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};

const normalizeReference = (
	core: ClientCore,
	reference: ResourceRef,
	expectedType?: string,
	collection?: string,
): void => {
	let identifier: string;
	if (collection === undefined) {
		const parent = `${projectName(core)}/`;
		if (!reference.name.startsWith(parent)) {
			throw MindcladeError.invalidArgument("resource reference is outside the configured project");
		}
		identifier = reference.name.slice(reference.name.lastIndexOf("/") + 1);
		resourceId("resource reference ID", identifier);
	} else {
		scopedName(core, reference.name, collection);
		identifier = reference.name.slice(reference.name.lastIndexOf("/") + 1);
	}
	if (reference.resourceId !== "" && reference.resourceId !== identifier) {
		throw MindcladeError.invalidArgument("resource reference ID conflicts with its name");
	}
	reference.resourceId = identifier;
	if (expectedType !== undefined) {
		if (reference.resourceType !== "" && reference.resourceType !== expectedType) {
			throw MindcladeError.invalidArgument("resource reference type conflicts with semantics");
		}
		reference.resourceType = expectedType;
	} else {
		requiredText("resource reference type", reference.resourceType, 256);
	}
	normalizeScope(core, reference);
};

const normalizeDefinition = (
	core: ClientCore,
	definition: AgentDefinition,
	creating: boolean,
): void => {
	if (
		creating &&
		(definition.name !== "" ||
			definition.uid !== "" ||
			definition.revision !== 0n ||
			definition.etag !== "" ||
			definition.tenantId !== "" ||
			definition.projectId !== "" ||
			definition.createTime !== undefined ||
			definition.updateTime !== undefined ||
			definition.deleteTime !== undefined)
	) {
		throw MindcladeError.invalidArgument(
			"server-managed agent definition fields must be unset when creating",
		);
	}
	if (!creating) {
		scopedName(core, definition.name, "agentDefinitions");
		normalizeScope(core, definition);
	}
	if (definition.workflowDefinition === undefined || definition.evaluationSuite === undefined) {
		throw MindcladeError.invalidArgument(
			"agent definition requires workflow and evaluation references",
		);
	}
	normalizeReference(
		core,
		definition.workflowDefinition,
		"workflow_definition",
		"workflowDefinitions",
	);
	normalizeReference(core, definition.evaluationSuite);
	if (definition.eligibleTools.length === 0) {
		throw MindcladeError.invalidArgument("agent definition requires at least one allowlisted tool");
	}
	for (const tool of definition.eligibleTools) normalizeReference(core, tool);
};

const validateFence = (
	core: ClientCore,
	fence: {
		jobId: string;
		runId: string;
		attemptId: string;
		leaseEpoch: bigint;
		deadline?: Parameters<typeof timestampDate>[0];
		tenantId: string;
		projectId: string;
		leaseTokenDigest: string;
	},
): void => {
	requiredText("agent fence job ID", fence.jobId, 2048);
	requiredText("agent fence run ID", fence.runId, 2048);
	requiredText("agent fence attempt ID", fence.attemptId, 2048);
	if (fence.leaseEpoch <= 0n || fence.deadline === undefined) {
		throw MindcladeError.invalidArgument("agent fence requires an epoch and deadline");
	}
	let deadline: number;
	try {
		deadline = timestampDate(fence.deadline).getTime();
	} catch {
		throw MindcladeError.invalidArgument("agent fence deadline is invalid");
	}
	if (!Number.isFinite(deadline) || deadline <= core.runtime.nowMs()) {
		throw MindcladeError.invalidArgument("agent fence is expired or invalid");
	}
	if (!SHA256.test(fence.leaseTokenDigest)) {
		throw MindcladeError.invalidArgument("agent fence lease-token digest is not canonical SHA-256");
	}
	normalizeScope(core, fence);
};

const fencedCall = (core: ClientCore, options: SubmitOptions): PreparedCall => {
	if (options.leaseToken === undefined) {
		throw MindcladeError.invalidArgument("fenced agent commit requires a raw lease token");
	}
	return prepareCall(core.config, core.runtime, options);
};

const requiredText = (label: string, value: string, maximum: number): string => {
	const normalized = value.trim();
	if (
		normalized === "" ||
		normalized.length > maximum ||
		[...normalized].some((character) => character.charCodeAt(0) < 0x20)
	) {
		throw MindcladeError.invalidArgument(`${label} is invalid`);
	}
	return normalized;
};

const validatePage = (size: number | undefined): void => {
	if (size !== undefined && (!Number.isInteger(size) || size < 0 || size > MAXIMUM_PAGE_SIZE)) {
		throw MindcladeError.invalidArgument("agent page size must be between zero and 200");
	}
};

const contextWithDigest = (
	core: ClientCore,
	prepared: PreparedCall,
	options: SubmitOptions,
	bytes: Uint8Array,
) => ({
	...commandContext(core.config, prepared, options),
	canonicalRequestDigest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
});

const operation = (value: Operation | undefined, method: string): Operation => {
	if (value === undefined || value.operationId.trim() === "") {
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	}
	return clone(OperationSchema, value);
};

const requiredRun = (value: AgentRun | undefined, name: string, method: string): AgentRun => {
	if (value === undefined || value.name !== name) {
		throw MindcladeError.protocol(`${method} returned an invalid agent run identity`);
	}
	return clone(AgentRunSchema, value);
};
