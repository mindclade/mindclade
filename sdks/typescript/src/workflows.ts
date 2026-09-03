import { createHash } from "node:crypto";
import {
	clone,
	create,
	type DescMessage,
	type MessageInitShape,
	type MessageShape,
	toBinary,
} from "@bufbuild/protobuf";
import { timestampDate } from "@bufbuild/protobuf/wkt";
import type { ResourceRef } from "../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	CancelWorkflowRunRequestSchema,
	CommitWorkflowTransitionRequestSchema,
	CreateWorkflowDefinitionRequestSchema,
	GetWorkflowDefinitionRequestSchema,
	GetWorkflowRunRequestSchema,
	ListWorkflowDefinitionsRequestSchema,
	type ListWorkflowDefinitionsResponse,
	ListWorkflowRunsRequestSchema,
	type ListWorkflowRunsResponse,
	StartWorkflowRunRequestSchema,
	UpdateWorkflowDefinitionRequestSchema,
	WatchWorkflowRunRequestSchema,
} from "../../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";
import {
	type Operation,
	OperationSchema,
} from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import {
	type WorkflowDefinition,
	WorkflowDefinitionSchema,
} from "../../../protocols/generated/typescript/workflow/v1/workflow_definition_pb.js";
import {
	type WorkflowRun,
	WorkflowRunSchema,
	WorkflowRunState,
} from "../../../protocols/generated/typescript/workflow/v1/workflow_run_pb.js";
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
	type WaitOptions,
} from "./request.js";
import { invokeUnary } from "./retry.js";
import { DEFAULT_WAIT_TIMEOUT_MS, type WatchSource, watchStream } from "./watch.js";

const CREATE = "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition";
const UPDATE = "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition";
const GET_DEFINITION = "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition";
const LIST_DEFINITIONS = "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions";
const START = "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun";
const GET_RUN = "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun";
const LIST_RUNS = "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns";
const CANCEL = "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun";
const COMMIT = "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition";
const MAXIMUM_PAGE_SIZE = 200;
const WATCH = "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun";
const RESOURCE_ID = /^[A-Za-z0-9._-]{1,128}$/;
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const TERMINAL = new Set<WorkflowRunState>([
	WorkflowRunState.SUCCEEDED,
	WorkflowRunState.FAILED,
	WorkflowRunState.CANCELLED,
	WorkflowRunState.EXPIRED,
]);

/** A durable workflow failure retaining a generated resource without exposing
 * its structured failure payload through Error.message or JSON serialization. */
export class WorkflowRunFailure extends MindcladeError {
	readonly run!: WorkflowRun;

	constructor(run: WorkflowRun) {
		super({
			kind: run.state === WorkflowRunState.CANCELLED ? "cancelled" : "remote",
			safeMessage: "workflow run reached a non-success terminal state",
		});
		this.name = "WorkflowRunFailure";
		Object.defineProperty(this, "run", {
			configurable: false,
			enumerable: false,
			value: clone(WorkflowRunSchema, run),
			writable: false,
		});
	}
}

/** Generated-type-only durable workflow facade. */
export class Workflows {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async createDefinition(
		input: MessageInitShape<typeof CreateWorkflowDefinitionRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		ensureUnfenced(options);
		const request = create(CreateWorkflowDefinitionRequestSchema, input);
		request.parent = normalizeParent(this.#core, request.parent);
		validateId("workflow definition ID", request.workflowDefinitionId);
		if (request.workflowDefinition === undefined) {
			throw MindcladeError.invalidArgument("workflow creation requires a generated definition");
		}
		const expectedName = `${request.parent}/workflowDefinitions/${request.workflowDefinitionId}`;
		normalizeDefinition(this.#core, request.workflowDefinition, expectedName, true);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CreateWorkflowDefinitionRequestSchema,
			request,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE,
			options.idempotencyKey,
			(call) => this.#core.raw.workflows.createWorkflowDefinition(request, call),
		);
		return requiredOperation(response.operation, "CreateWorkflowDefinition");
	}

	async updateDefinition(
		input: MessageInitShape<typeof UpdateWorkflowDefinitionRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		ensureUnfenced(options);
		const request = create(UpdateWorkflowDefinitionRequestSchema, input);
		if (
			request.workflowDefinition === undefined ||
			request.updateMask === undefined ||
			request.updateMask.paths.length === 0 ||
			request.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"workflow update requires a generated definition, field mask, and ETag",
			);
		}
		normalizeDefinition(this.#core, request.workflowDefinition, undefined, false);
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			UpdateWorkflowDefinitionRequestSchema,
			request,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			UPDATE,
			options.idempotencyKey,
			(call) => this.#core.raw.workflows.updateWorkflowDefinition(request, call),
		);
		return requiredOperation(response.operation, "UpdateWorkflowDefinition");
	}

	async getDefinition(
		name: string,
		ifNoneMatch = "",
		options: SdkCallOptions = {},
	): Promise<WorkflowDefinition> {
		ensureUnfenced(options);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(GetWorkflowDefinitionRequestSchema, {
			ifNoneMatch: ifNoneMatch.trim(),
			name: scopedName(this.#core, name, "workflowDefinitions"),
		});
		const response = await invokeUnary(this.#core, prepared, GET_DEFINITION, undefined, (call) =>
			this.#core.raw.workflows.getWorkflowDefinition(request, call),
		);
		if (response.workflowDefinition === undefined) {
			throw MindcladeError.protocol("GetWorkflowDefinition response omitted its definition");
		}
		return clone(WorkflowDefinitionSchema, response.workflowDefinition);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listDefinitions(
		input: MessageInitShape<typeof ListWorkflowDefinitionsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<WorkflowDefinition, ListWorkflowDefinitionsResponse>> {
		ensureUnfenced(options);
		const request = create(ListWorkflowDefinitionsRequestSchema, input);
		request.parent = normalizeParent(this.#core, request.parent);
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListWorkflowDefinitionsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					prepared,
					LIST_DEFINITIONS,
					undefined,
					(call) => this.#core.raw.workflows.listWorkflowDefinitions(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.workflowDefinitions,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async startRun(
		input: MessageInitShape<typeof StartWorkflowRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		ensureUnfenced(options);
		const request = create(StartWorkflowRunRequestSchema, input);
		request.parent = normalizeParent(this.#core, request.parent);
		validateId("workflow run ID", request.workflowRunId);
		if (request.workflowRun === undefined || request.workflowRun.definition === undefined) {
			throw MindcladeError.invalidArgument(
				"workflow start requires a generated run and definition",
			);
		}
		normalizeRun(this.#core, request.workflowRun, undefined, true);
		normalizeReference(
			this.#core,
			request.workflowRun.definition,
			"workflow_definition",
			"workflowDefinitions",
		);
		if (request.workflowRun.agentRun !== undefined) {
			normalizeReference(this.#core, request.workflowRun.agentRun, "agent_run", "agentRuns");
		}
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			StartWorkflowRunRequestSchema,
			request,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			START,
			options.idempotencyKey,
			(call) => this.#core.raw.workflows.startWorkflowRun(request, call),
		);
		return requiredOperation(response.operation, "StartWorkflowRun");
	}

	async getRun(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<WorkflowRun> {
		ensureUnfenced(options);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(GetWorkflowRunRequestSchema, {
			ifNoneMatch: ifNoneMatch.trim(),
			name: scopedName(this.#core, name, "workflowRuns"),
		});
		const response = await invokeUnary(this.#core, prepared, GET_RUN, undefined, (call) =>
			this.#core.raw.workflows.getWorkflowRun(request, call),
		);
		return requiredRun(response.workflowRun, "GetWorkflowRun");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listRuns(
		input: MessageInitShape<typeof ListWorkflowRunsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<WorkflowRun, ListWorkflowRunsResponse>> {
		ensureUnfenced(options);
		const request = create(ListWorkflowRunsRequestSchema, input);
		request.parent = normalizeParent(this.#core, request.parent);
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListWorkflowRunsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST_RUNS, undefined, (call) =>
					this.#core.raw.workflows.listWorkflowRuns(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.workflowRuns,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async cancelRun(
		input: MessageInitShape<typeof CancelWorkflowRunRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		ensureUnfenced(options);
		const request = create(CancelWorkflowRunRequestSchema, input);
		request.name = scopedName(this.#core, request.name, "workflowRuns");
		if (
			request.etag.trim() === "" ||
			request.reason.trim() === "" ||
			request.reason.length > 1024
		) {
			throw MindcladeError.invalidArgument(
				"workflow cancellation requires an ETag and bounded reason",
			);
		}
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CancelWorkflowRunRequestSchema,
			request,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CANCEL,
			options.idempotencyKey,
			(call) => this.#core.raw.workflows.cancelWorkflowRun(request, call),
		);
		return requiredOperation(response.operation, "CancelWorkflowRun");
	}

	async commitTransition(
		input: MessageInitShape<typeof CommitWorkflowTransitionRequestSchema>,
		options: SubmitOptions,
	): Promise<WorkflowRun> {
		if (options.leaseToken === undefined) {
			throw MindcladeError.invalidArgument(
				"fenced workflow transition requires a scheduler-issued lease token",
			);
		}
		const request = create(CommitWorkflowTransitionRequestSchema, input);
		if (request.workflowRun === undefined || request.fence === undefined) {
			throw MindcladeError.invalidArgument(
				"workflow transition requires a generated run and lease fence",
			);
		}
		normalizeRun(this.#core, request.workflowRun, undefined, false);
		validateFence(this.#core, request.fence);
		if (request.etag.trim() === "") {
			throw MindcladeError.invalidArgument("workflow transition requires an ETag");
		}
		const expectedName = request.workflowRun.name;
		const expectedSequence = request.expectedTransitionSequence + 1n;
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CommitWorkflowTransitionRequestSchema,
			request,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT,
			options.idempotencyKey,
			(call) => this.#core.raw.workflows.commitWorkflowTransition(request, call),
		);
		const run = requiredRun(response.workflowRun, "CommitWorkflowTransition");
		if (run.name !== expectedName || run.transitionSequence !== expectedSequence) {
			throw MindcladeError.protocol("CommitWorkflowTransition returned inconsistent durable state");
		}
		return run;
	}

	/** Streams contiguous durable revisions and reconnects from the last accepted
	 * transition sequence under one total deadline. */
	async *watch(
		name: string,
		afterTransitionSequence = 0n,
		options: WaitOptions = {},
	): AsyncGenerator<WorkflowRun> {
		ensureUnfenced(options);
		const runName = scopedName(this.#core, name, "workflowRuns");
		if (afterTransitionSequence < 0n) {
			throw MindcladeError.invalidArgument("workflow watch cursor cannot be negative");
		}
		const total = options.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
		const prepared = prepareCall(
			this.#core.config,
			this.#core.runtime,
			callOptions(options, total),
		);
		yield* watchStream(this.#core, prepared, this.#watchSource(runName), afterTransitionSequence);
	}

	/** Resumes a watch from a transition sequence the caller already accepted. */
	async *resumeWatch(
		name: string,
		afterTransitionSequence: bigint,
		options: WaitOptions = {},
	): AsyncGenerator<WorkflowRun> {
		if (afterTransitionSequence <= 0n) {
			throw MindcladeError.invalidArgument(
				"resuming a workflow watch requires a positive accepted transition sequence",
			);
		}
		yield* this.watch(name, afterTransitionSequence, options);
	}

	#watchSource(
		runName: string,
	): WatchSource<WorkflowRun, bigint, { readonly workflowRun?: WorkflowRun }> {
		return {
			accept: (response, cursor) => {
				const run = requiredRun(response.workflowRun, "WatchWorkflowRun");
				if (run.name !== runName || run.transitionSequence !== cursor + 1n) {
					throw MindcladeError.protocol(
						"workflow watch returned an invalid identity or non-contiguous sequence",
					);
				}
				return { cursor: run.transitionSequence, delivery: "yield", value: run };
			},
			incomplete: "workflow stream ended before terminal durable state",
			open: (cursor, call) =>
				this.#core.raw.workflows.watchWorkflowRun(
					create(WatchWorkflowRunRequestSchema, {
						afterTransitionSequence: cursor,
						name: runName,
					}),
					call,
				),
			route: WATCH,
			terminal: (run) => TERMINAL.has(run.state),
		};
	}

	async wait(
		name: string,
		afterTransitionSequence = 0n,
		options: WaitOptions = {},
	): Promise<WorkflowRun> {
		for await (const run of this.watch(name, afterTransitionSequence, options)) {
			if (!TERMINAL.has(run.state)) continue;
			if (run.state !== WorkflowRunState.SUCCEEDED) throw new WorkflowRunFailure(run);
			return run;
		}
		throw MindcladeError.protocol("workflow watch ended before terminal durable state");
	}
}

const normalizeDefinition = (
	core: ClientCore,
	definition: WorkflowDefinition,
	expectedName: string | undefined,
	allowEmptyName: boolean,
): void => {
	if (definition.name !== "") {
		const normalized = scopedName(core, definition.name, "workflowDefinitions");
		if (expectedName !== undefined && normalized !== expectedName) {
			throw MindcladeError.invalidArgument("workflow definition name does not match its ID");
		}
	} else if (!allowEmptyName) {
		throw MindcladeError.invalidArgument("workflow definition name is required");
	}
	normalizeScope(core, definition);
	for (const reference of definition.eligibleTools) normalizeReference(core, reference);
};

const normalizeRun = (
	core: ClientCore,
	run: WorkflowRun,
	expectedName: string | undefined,
	allowEmptyName: boolean,
): void => {
	if (run.name !== "") {
		const normalized = scopedName(core, run.name, "workflowRuns");
		if (expectedName !== undefined && normalized !== expectedName) {
			throw MindcladeError.invalidArgument("workflow run name does not match its ID");
		}
	} else if (!allowEmptyName) {
		throw MindcladeError.invalidArgument("workflow run name is required");
	}
	normalizeScope(core, run);
};

const normalizeScope = (core: ClientCore, value: { tenantId: string; projectId: string }): void => {
	if (
		(value.tenantId !== "" && value.tenantId !== core.config.identity.tenantId) ||
		(value.projectId !== "" && value.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("workflow resource scope conflicts with client identity");
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
	const name =
		collection === undefined
			? sameProjectResource(core, reference.name)
			: scopedName(core, reference.name, collection);
	const resourceId = name.slice(name.lastIndexOf("/") + 1);
	if (reference.resourceId !== "" && reference.resourceId !== resourceId) {
		throw MindcladeError.invalidArgument("resource reference ID does not match its name");
	}
	if (expectedType !== undefined) {
		if (reference.resourceType !== "" && reference.resourceType !== expectedType) {
			throw MindcladeError.invalidArgument("resource reference type does not match its use");
		}
		reference.resourceType = expectedType;
	} else if (reference.resourceType.trim() === "") {
		throw MindcladeError.invalidArgument("resource reference type is required");
	}
	reference.resourceId = resourceId;
	normalizeScope(core, reference);
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
	if (
		fence.jobId.trim() === "" ||
		fence.runId.trim() === "" ||
		fence.attemptId.trim() === "" ||
		fence.leaseEpoch <= 0n ||
		fence.deadline === undefined ||
		!SHA256.test(fence.leaseTokenDigest)
	) {
		throw MindcladeError.invalidArgument("workflow lease fence is incomplete");
	}
	let deadline: Date;
	try {
		deadline = timestampDate(fence.deadline);
	} catch {
		throw MindcladeError.invalidArgument("workflow lease fence deadline is invalid");
	}
	if (!Number.isFinite(deadline.getTime()) || deadline.getTime() <= core.runtime.nowMs()) {
		throw MindcladeError.invalidArgument("workflow lease fence is expired");
	}
	normalizeScope(core, fence);
};

const requiredOperation = (operation: Operation | undefined, method: string): Operation => {
	if (operation === undefined || operation.operationId.trim() === "") {
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	}
	return clone(OperationSchema, operation);
};

const requiredRun = (run: WorkflowRun | undefined, method: string): WorkflowRun => {
	if (run === undefined) throw MindcladeError.protocol(`${method} response omitted its run`);
	return clone(WorkflowRunSchema, run);
};

const normalizeParent = (core: ClientCore, parent: string): string => {
	const expected = projectName(core);
	if (parent !== "" && parent !== expected) {
		throw MindcladeError.invalidArgument("workflow parent does not match client scope");
	}
	return expected;
};

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
	if (!RESOURCE_ID.test(id)) {
		throw MindcladeError.invalidArgument(`${collection} resource is outside client scope`);
	}
	return name;
};

const sameProjectResource = (core: ClientCore, name: string): string => {
	const prefix = `${projectName(core)}/`;
	if (!name.startsWith(prefix) || name.slice(prefix.length).split("/").length !== 2) {
		throw MindcladeError.invalidArgument("resource reference is outside client scope");
	}
	validateId("resource reference ID", name.slice(name.lastIndexOf("/") + 1));
	return name;
};

const validateId = (label: string, value: string): void => {
	if (!RESOURCE_ID.test(value)) throw MindcladeError.invalidArgument(`${label} is invalid`);
};

const validatePage = (size: number | undefined): void => {
	if (size !== undefined && (!Number.isInteger(size) || size < 0 || size > MAXIMUM_PAGE_SIZE)) {
		throw MindcladeError.invalidArgument(
			"workflow page size must be an integer between zero and 200",
		);
	}
};

const ensureUnfenced = (options: SdkCallOptions): void => {
	if (options.leaseToken !== undefined || options.workerId !== undefined) {
		throw MindcladeError.invalidArgument(
			"worker and lease credentials are accepted only by fenced workflow transitions",
		);
	}
};

const contextWithDigest = <Desc extends DescMessage>(
	core: ClientCore,
	prepared: PreparedCall,
	options: SubmitOptions,
	schema: Desc,
	message: MessageShape<Desc>,
) => ({
	...commandContext(core.config, prepared, options),
	canonicalRequestDigest: sha256(toBinary(schema, message)),
});

const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;

const callOptions = (options: WaitOptions, timeoutMs: number): SdkCallOptions => ({
	...(options.requestId === undefined ? {} : { requestId: options.requestId }),
	...(options.traceId === undefined ? {} : { traceId: options.traceId }),
	...(options.signal === undefined ? {} : { signal: options.signal }),
	timeoutMs: Math.min(timeoutMs, options.timeoutMs ?? timeoutMs),
});
