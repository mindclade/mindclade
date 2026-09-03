import { createHash } from "node:crypto";
import {
	clone,
	create,
	type DescMessage,
	type MessageInitShape,
	type MessageShape,
	toBinary,
} from "@bufbuild/protobuf";
import { timestampDate, timestampFromDate } from "@bufbuild/protobuf/wkt";
import {
	CancelTrainingRunRequestSchema,
	CommitCheckpointRequestSchema,
	CommitTrainingProgressRequestSchema,
	CompleteTrainingRunRequestSchema,
	CreateTrainingRunRequestSchema,
	GetCheckpointRequestSchema,
	GetTrainingRunRequestSchema,
	ListCheckpointsRequestSchema,
	type ListCheckpointsResponse,
	ListTrainingRunsRequestSchema,
	type ListTrainingRunsResponse,
	PrepareCheckpointRequestSchema,
	ResumeTrainingAttemptRequestSchema,
	StartTrainingAttemptRequestSchema,
	WatchTrainingRunRequestSchema,
	type WatchTrainingRunResponse,
} from "../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import {
	type Operation,
	OperationSchema,
} from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import {
	type Checkpoint,
	CheckpointSchema,
} from "../../../protocols/generated/typescript/training/v1/checkpoint_pb.js";
import {
	CancelTrainingRunCommandSchema,
	type CommitCheckpointCommand,
	CommitCheckpointCommandSchema,
	type CommitTrainingProgressCommand,
	CommitTrainingProgressCommandSchema,
	type CompleteTrainingRunCommand,
	CompleteTrainingRunCommandSchema,
	CreateTrainingRunCommandSchema,
	type PrepareCheckpointCommand,
	PrepareCheckpointCommandSchema,
	type ResumeTrainingAttemptCommand,
	ResumeTrainingAttemptCommandSchema,
	type StartTrainingAttemptCommand,
	StartTrainingAttemptCommandSchema,
} from "../../../protocols/generated/typescript/training/v1/training_commands_pb.js";
import {
	type TrainingProgress,
	TrainingProgressSchema,
} from "../../../protocols/generated/typescript/training/v1/training_progress_pb.js";
import {
	type TrainingRun,
	TrainingRunSchema,
	TrainingRunState,
} from "../../../protocols/generated/typescript/training/v1/training_run_pb.js";
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

const SERVICE = "/mindclade.internal.training.v1.TrainingService";
const CREATE = `${SERVICE}/CreateTrainingRun`;
const GET = `${SERVICE}/GetTrainingRun`;
const LIST = `${SERVICE}/ListTrainingRuns`;
const START = `${SERVICE}/StartTrainingAttempt`;
const RESUME = `${SERVICE}/ResumeTrainingAttempt`;
const COMMIT_PROGRESS = `${SERVICE}/CommitTrainingProgress`;
const PREPARE_CHECKPOINT = `${SERVICE}/PrepareCheckpoint`;
const COMMIT_CHECKPOINT = `${SERVICE}/CommitCheckpoint`;
const COMPLETE = `${SERVICE}/CompleteTrainingRun`;
const CANCEL = `${SERVICE}/CancelTrainingRun`;
const GET_CHECKPOINT = `${SERVICE}/GetCheckpoint`;
const LIST_CHECKPOINTS = `${SERVICE}/ListCheckpoints`;
const MAXIMUM_PAGE_SIZE = 200;
const WATCH = `${SERVICE}/WatchTrainingRun`;
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const RESOURCE_ID = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/;
const TERMINAL = new Set<TrainingRunState>([
	TrainingRunState.COMPLETED,
	TrainingRunState.FAILED,
	TrainingRunState.CANCELLED,
]);

/** A generated snapshot returned by the resumable training watch. */
export interface TrainingUpdate {
	readonly run: TrainingRun;
	readonly progress?: TrainingProgress;
	readonly sequence: bigint;
	readonly observedAt?: WatchTrainingRunResponse["observedAt"];
}

/**
 * A durable training failure retaining the generated run without exposing its
 * structured failure payload through `Error.message` or JSON serialization.
 *
 * The mirror of `WorkflowRunFailure`, so the two long-running domains fail the
 * same way and a caller can handle both with one `catch`.
 */
export class TrainingRunFailure extends MindcladeError {
	readonly run!: TrainingRun;

	constructor(run: TrainingRun) {
		super({
			kind: run.state === TrainingRunState.CANCELLED ? "cancelled" : "remote",
			safeMessage: "training run reached a non-success terminal state",
		});
		this.name = "TrainingRunFailure";
		Object.defineProperty(this, "run", {
			configurable: false,
			enumerable: false,
			value: clone(TrainingRunSchema, run),
			writable: false,
		});
	}
}

/** Generated-type-only durable training facade. */
export class Training {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async submit(
		input: MessageInitShape<typeof CreateTrainingRunCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		ensureUnfenced(options);
		const command = create(CreateTrainingRunCommandSchema, input);
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CreateTrainingRunCommandSchema,
			command,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.training.createTrainingRun(
					create(CreateTrainingRunRequestSchema, { command }),
					call,
				),
		);
		return requiredOperation(response.operation, "CreateTrainingRun");
	}

	async get(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<TrainingRun> {
		ensureUnfenced(options);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET, undefined, (call) =>
			this.#core.raw.training.getTrainingRun(
				create(GetTrainingRunRequestSchema, {
					ifNoneMatch: ifNoneMatch.trim(),
					name: scopedRunName(this.#core, name),
				}),
				call,
			),
		);
		return requiredRun(response.trainingRun, "GetTrainingRun");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listRuns(
		input: MessageInitShape<typeof ListTrainingRunsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<TrainingRun, ListTrainingRunsResponse>> {
		ensureUnfenced(options);
		const request = create(ListTrainingRunsRequestSchema, input);
		request.parent = normalizedParent(this.#core, request.parent);
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListTrainingRunsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST, undefined, (call) =>
					this.#core.raw.training.listTrainingRuns(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.trainingRuns,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async startAttempt(
		input: MessageInitShape<typeof StartTrainingAttemptCommandSchema>,
		options: SubmitOptions,
	): Promise<TrainingRun> {
		const command = create(StartTrainingAttemptCommandSchema, input);
		prepareFencedCommand(this.#core, command, options, false);
		return await this.#trainingMutation(
			START,
			"StartTrainingAttempt",
			StartTrainingAttemptCommandSchema,
			command,
			options,
			(call) =>
				this.#core.raw.training.startTrainingAttempt(
					create(StartTrainingAttemptRequestSchema, { command }),
					call,
				),
		);
	}

	async resumeAttempt(
		input: MessageInitShape<typeof ResumeTrainingAttemptCommandSchema>,
		options: SubmitOptions,
	): Promise<TrainingRun> {
		const command = create(ResumeTrainingAttemptCommandSchema, input);
		prepareFencedCommand(this.#core, command, options, true);
		return await this.#trainingMutation(
			RESUME,
			"ResumeTrainingAttempt",
			ResumeTrainingAttemptCommandSchema,
			command,
			options,
			(call) =>
				this.#core.raw.training.resumeTrainingAttempt(
					create(ResumeTrainingAttemptRequestSchema, { command }),
					call,
				),
		);
	}

	async commitProgress(
		input: MessageInitShape<typeof CommitTrainingProgressCommandSchema>,
		options: SubmitOptions,
	): Promise<readonly [TrainingProgress, TrainingRun]> {
		const command = create(CommitTrainingProgressCommandSchema, input);
		prepareNamedFencedCommand(this.#core, command, options);
		if (
			command.progress === undefined ||
			command.progress.trainingRunName !== command.trainingRunName ||
			command.progress.progressRevision <= 0n
		) {
			throw MindcladeError.invalidArgument("training progress commit requires generated progress");
		}
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CommitTrainingProgressCommandSchema,
			command,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT_PROGRESS,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.training.commitTrainingProgress(
					create(CommitTrainingProgressRequestSchema, { command }),
					call,
				),
		);
		if (response.progress === undefined || response.trainingRun === undefined) {
			throw MindcladeError.protocol("CommitTrainingProgress response omitted durable state");
		}
		if (
			response.progress.trainingRunName !== command.trainingRunName ||
			response.trainingRun.name !== command.trainingRunName
		) {
			throw MindcladeError.protocol("CommitTrainingProgress returned inconsistent durable state");
		}
		return [
			clone(TrainingProgressSchema, response.progress),
			clone(TrainingRunSchema, response.trainingRun),
		] as const;
	}

	async prepareCheckpoint(
		input: MessageInitShape<typeof PrepareCheckpointCommandSchema>,
		options: SubmitOptions,
	): Promise<Checkpoint> {
		const command = create(PrepareCheckpointCommandSchema, input);
		prepareNamedFencedCommand(this.#core, command, options);
		if (
			command.snapshotEpoch <= 0n ||
			command.logicalStateDescriptor === undefined ||
			command.committedProgress === undefined ||
			command.committedProgress.trainingRunName !== command.trainingRunName
		) {
			throw MindcladeError.invalidArgument(
				"checkpoint preparation requires an epoch, state descriptor, and progress",
			);
		}
		const checkpoint = await this.#checkpointMutation(
			PREPARE_CHECKPOINT,
			"PrepareCheckpoint",
			PrepareCheckpointCommandSchema,
			command,
			options,
			(call) =>
				this.#core.raw.training.prepareCheckpoint(
					create(PrepareCheckpointRequestSchema, { command }),
					call,
				),
		);
		if (
			checkpoint.trainingRunName !== command.trainingRunName ||
			checkpoint.snapshotEpoch !== command.snapshotEpoch
		) {
			throw MindcladeError.protocol("PrepareCheckpoint returned inconsistent checkpoint identity");
		}
		return checkpoint;
	}

	async commitCheckpoint(
		input: MessageInitShape<typeof CommitCheckpointCommandSchema>,
		options: SubmitOptions,
	): Promise<readonly [Checkpoint, TrainingRun]> {
		const command = create(CommitCheckpointCommandSchema, input);
		prepareNamedFencedCommand(this.#core, command, options);
		if (
			command.snapshotEpoch <= 0n ||
			command.checkpointManifest === undefined ||
			command.logicalStateDescriptor === undefined ||
			command.committedProgress === undefined ||
			command.committedProgress.trainingRunName !== command.trainingRunName ||
			command.verificationEvidence === undefined ||
			command.committedAt === undefined
		) {
			throw MindcladeError.invalidArgument(
				"checkpoint commit requires an epoch and immutable manifest",
			);
		}
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			CommitCheckpointCommandSchema,
			command,
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT_CHECKPOINT,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.training.commitCheckpoint(
					create(CommitCheckpointRequestSchema, { command }),
					call,
				),
		);
		const checkpoint = requiredCheckpoint(response.checkpoint, "CommitCheckpoint");
		const run = requiredRun(response.trainingRun, "CommitCheckpoint");
		if (
			checkpoint.trainingRunName !== command.trainingRunName ||
			checkpoint.snapshotEpoch !== command.snapshotEpoch ||
			run.name !== command.trainingRunName
		) {
			throw MindcladeError.protocol("CommitCheckpoint returned inconsistent durable state");
		}
		return [checkpoint, run] as const;
	}

	async complete(
		input: MessageInitShape<typeof CompleteTrainingRunCommandSchema>,
		options: SubmitOptions,
	): Promise<TrainingRun> {
		const command = create(CompleteTrainingRunCommandSchema, input);
		prepareNamedFencedCommand(this.#core, command, options);
		if (command.classification === 0 || command.completedAt === undefined) {
			throw MindcladeError.invalidArgument(
				"training completion requires terminal classification and completion time",
			);
		}
		return await this.#trainingMutation(
			COMPLETE,
			"CompleteTrainingRun",
			CompleteTrainingRunCommandSchema,
			command,
			options,
			(call) =>
				this.#core.raw.training.completeTrainingRun(
					create(CompleteTrainingRunRequestSchema, { command }),
					call,
				),
		);
	}

	async cancel(
		input: MessageInitShape<typeof CancelTrainingRunCommandSchema>,
		options: SubmitOptions,
	): Promise<TrainingRun> {
		ensureUnfenced(options);
		const command = create(CancelTrainingRunCommandSchema, input);
		command.trainingRunName = scopedRunName(this.#core, command.trainingRunName);
		if (
			command.etag.trim() === "" ||
			command.reason.trim() === "" ||
			command.reason.length > 1024
		) {
			throw MindcladeError.invalidArgument(
				"training cancellation requires an ETag and bounded reason",
			);
		}
		return await this.#trainingMutation(
			CANCEL,
			"CancelTrainingRun",
			CancelTrainingRunCommandSchema,
			command,
			options,
			(call) =>
				this.#core.raw.training.cancelTrainingRun(
					create(CancelTrainingRunRequestSchema, { command }),
					call,
				),
		);
	}

	async getCheckpoint(name: string, options: SdkCallOptions = {}): Promise<Checkpoint> {
		ensureUnfenced(options);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_CHECKPOINT, undefined, (call) =>
			this.#core.raw.training.getCheckpoint(
				create(GetCheckpointRequestSchema, {
					name: scopedCheckpointName(this.#core, name),
				}),
				call,
			),
		);
		return requiredCheckpoint(response.checkpoint, "GetCheckpoint");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listCheckpoints(
		input: MessageInitShape<typeof ListCheckpointsRequestSchema>,
		options: ListOptions = {},
	): Promise<Page<Checkpoint, ListCheckpointsResponse>> {
		ensureUnfenced(options);
		const request = create(ListCheckpointsRequestSchema, input);
		request.parent = scopedRunName(this.#core, request.parent);
		validatePage(request.page?.pageSize);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListCheckpointsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					prepared,
					LIST_CHECKPOINTS,
					undefined,
					(call) => this.#core.raw.training.listCheckpoints(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.checkpoints,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	/** Streams strictly contiguous durable updates and resumes after transient failures. */
	async *watch(
		name: string,
		afterSequence = 0n,
		options: WaitOptions = {},
	): AsyncGenerator<TrainingUpdate> {
		ensureUnfenced(options);
		const runName = scopedRunName(this.#core, name);
		if (afterSequence < 0n) {
			throw MindcladeError.invalidArgument("training watch cursor cannot be negative");
		}
		const total = options.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
		const prepared = prepareCall(
			this.#core.config,
			this.#core.runtime,
			callOptions(options, total),
		);
		yield* watchStream(this.#core, prepared, this.#watchSource(runName, prepared), afterSequence);
	}

	/** Resumes a watch from a sequence the caller already accepted. */
	async *resumeWatch(
		name: string,
		afterSequence: bigint,
		options: WaitOptions = {},
	): AsyncGenerator<TrainingUpdate> {
		if (afterSequence <= 0n) {
			throw MindcladeError.invalidArgument(
				"resuming a training watch requires a positive accepted sequence",
			);
		}
		yield* this.watch(name, afterSequence, options);
	}

	/**
	 * Waits for durable terminal training truth.
	 *
	 * The counterpart of `Workflows.wait` and `Operations.wait`: a successful
	 * terminal run is returned, and a failed or cancelled one is raised as a
	 * {@link TrainingRunFailure} rather than handed back for the caller to
	 * re-inspect.
	 */
	async wait(name: string, afterSequence = 0n, options: WaitOptions = {}): Promise<TrainingRun> {
		for await (const update of this.watch(name, afterSequence, options)) {
			if (!TERMINAL.has(update.run.state)) continue;
			if (update.run.state !== TrainingRunState.COMPLETED) {
				throw new TrainingRunFailure(update.run);
			}
			return update.run;
		}
		throw MindcladeError.protocol("training watch ended before terminal durable state");
	}

	#watchSource(
		runName: string,
		prepared: PreparedCall,
	): WatchSource<TrainingUpdate, bigint, WatchTrainingRunResponse> {
		return {
			accept: (response, cursor) => {
				const run = requiredRun(response.trainingRun, "WatchTrainingRun");
				if (run.name !== runName || response.sequence !== cursor + 1n) {
					throw MindcladeError.protocol(
						"training watch returned an invalid identity or non-contiguous sequence",
					);
				}
				return {
					cursor: response.sequence,
					delivery: "yield",
					value: {
						run,
						...(response.progress === undefined
							? {}
							: { progress: clone(TrainingProgressSchema, response.progress) }),
						sequence: response.sequence,
						...(response.observedAt === undefined ? {} : { observedAt: response.observedAt }),
					},
				};
			},
			incomplete: "training stream ended before terminal state",
			open: (cursor, call) =>
				this.#core.raw.training.watchTrainingRun(
					create(WatchTrainingRunRequestSchema, {
						afterSequence: cursor,
						deadline: timestampFromDate(new Date(prepared.deadlineMs)),
						name: runName,
					}),
					call,
				),
			route: WATCH,
			terminal: (update) => TERMINAL.has(update.run.state),
		};
	}

	async #trainingMutation<CommandDesc extends DescMessage>(
		route: string,
		method: string,
		schema: CommandDesc,
		command: MessageShape<CommandDesc>,
		options: SubmitOptions,
		invoke: (
			call: Parameters<ClientCore["raw"]["training"]["getTrainingRun"]>[1],
		) => Promise<{ trainingRun?: TrainingRun }>,
	): Promise<TrainingRun> {
		delete (command as { context?: unknown }).context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		(command as { context?: unknown }).context = contextWithDigest(
			this.#core,
			prepared,
			options,
			schema,
			command,
		);
		const response = await invokeUnary(this.#core, prepared, route, options.idempotencyKey, invoke);
		return requiredRun(response.trainingRun, method);
	}

	async #checkpointMutation<CommandDesc extends DescMessage>(
		route: string,
		method: string,
		schema: CommandDesc,
		command: MessageShape<CommandDesc>,
		options: SubmitOptions,
		invoke: (
			call: Parameters<ClientCore["raw"]["training"]["getTrainingRun"]>[1],
		) => Promise<{ checkpoint?: Checkpoint }>,
	): Promise<Checkpoint> {
		delete (command as { context?: unknown }).context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		(command as { context?: unknown }).context = contextWithDigest(
			this.#core,
			prepared,
			options,
			schema,
			command,
		);
		const response = await invokeUnary(this.#core, prepared, route, options.idempotencyKey, invoke);
		return requiredCheckpoint(response.checkpoint, method);
	}
}

const prepareFencedCommand = (
	core: ClientCore,
	command: StartTrainingAttemptCommand | ResumeTrainingAttemptCommand,
	options: SubmitOptions,
	requiresCheckpoint: boolean,
): void => {
	ensureFenced(options);
	if (command.trainingRun === undefined || command.fence === undefined) {
		throw MindcladeError.invalidArgument("training attempt requires a run reference and fence");
	}
	normalizeReference(core, command.trainingRun, "training_run", "trainingRuns");
	if (requiresCheckpoint) {
		const resume = command as ResumeTrainingAttemptCommand;
		if (resume.checkpoint === undefined)
			throw MindcladeError.invalidArgument("training resume requires a checkpoint reference");
		normalizeReference(core, resume.checkpoint, "checkpoint", "checkpoints");
	}
	validateFence(core, command.fence);
	if (
		command.deadline === undefined ||
		timestampDate(command.deadline).getTime() <= core.runtime.nowMs()
	) {
		throw MindcladeError.invalidArgument("training attempt deadline must be in the future");
	}
};

const prepareNamedFencedCommand = (
	core: ClientCore,
	command:
		| CommitTrainingProgressCommand
		| PrepareCheckpointCommand
		| CommitCheckpointCommand
		| CompleteTrainingRunCommand,
	options: SubmitOptions,
): void => {
	ensureFenced(options);
	command.trainingRunName = scopedRunName(core, command.trainingRunName);
	if (command.fence === undefined)
		throw MindcladeError.invalidArgument("training mutation requires a lease fence");
	validateFence(core, command.fence);
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
		throw MindcladeError.invalidArgument("training lease fence is incomplete");
	}
	let deadline: Date;
	try {
		deadline = timestampDate(fence.deadline);
	} catch {
		throw MindcladeError.invalidArgument("training lease fence deadline is invalid");
	}
	if (!Number.isFinite(deadline.getTime()) || deadline.getTime() <= core.runtime.nowMs()) {
		throw MindcladeError.invalidArgument("training lease fence is expired");
	}
	const tenant = bare(core.config.identity.tenantId, "tenants");
	const project = bare(core.config.identity.projectId, "projects");
	if (
		(fence.tenantId !== "" && bare(fence.tenantId, "tenants") !== tenant) ||
		(fence.projectId !== "" && bare(fence.projectId, "projects") !== project)
	) {
		throw MindcladeError.invalidArgument("training lease fence conflicts with client identity");
	}
	fence.tenantId = tenant;
	fence.projectId = project;
};

const normalizeReference = (
	core: ClientCore,
	reference: {
		name: string;
		resourceId: string;
		resourceType: string;
		tenantId: string;
		projectId: string;
	},
	type: string,
	collection: string,
): void => {
	const name =
		collection === "checkpoints"
			? scopedCheckpointName(core, reference.name)
			: scopedRunName(core, reference.name);
	const id = name.slice(name.lastIndexOf("/") + 1);
	if (reference.resourceId !== "" && reference.resourceId !== id)
		throw MindcladeError.invalidArgument("training resource reference ID is inconsistent");
	if (reference.resourceType !== "" && reference.resourceType !== type)
		throw MindcladeError.invalidArgument("training resource reference type is inconsistent");
	reference.name = name;
	reference.resourceId = id;
	reference.resourceType = type;
	reference.tenantId = bare(core.config.identity.tenantId, "tenants");
	reference.projectId = bare(core.config.identity.projectId, "projects");
};

const requiredOperation = (value: Operation | undefined, method: string): Operation => {
	if (value === undefined || value.operationId.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	return clone(OperationSchema, value);
};

const requiredRun = (value: TrainingRun | undefined, method: string): TrainingRun => {
	if (value === undefined || value.name.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its training run`);
	return clone(TrainingRunSchema, value);
};

const requiredCheckpoint = (value: Checkpoint | undefined, method: string): Checkpoint => {
	if (value === undefined || value.name.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its checkpoint`);
	return clone(CheckpointSchema, value);
};

const projectName = (core: ClientCore): string => {
	const tenant = core.config.identity.tenantId.startsWith("tenants/")
		? core.config.identity.tenantId
		: `tenants/${core.config.identity.tenantId}`;
	const project = core.config.identity.projectId;
	if (project.startsWith("tenants/")) return project;
	return project.startsWith("projects/") ? `${tenant}/${project}` : `${tenant}/projects/${project}`;
};

const normalizedParent = (core: ClientCore, parent: string): string => {
	const expected = projectName(core);
	if (parent !== "" && parent !== expected)
		throw MindcladeError.invalidArgument("training parent does not match client scope");
	return expected;
};

const scopedRunName = (core: ClientCore, name: string): string =>
	scopedName(core, name, "trainingRuns");

const scopedCheckpointName = (core: ClientCore, name: string): string => {
	const prefix = `${projectName(core)}/trainingRuns/`;
	if (!name.startsWith(prefix))
		throw MindcladeError.invalidArgument("checkpoint resource is outside client scope");
	const suffix = name.slice(prefix.length).split("/");
	if (
		suffix.length !== 3 ||
		!RESOURCE_ID.test(suffix[0] ?? "") ||
		suffix[1] !== "checkpoints" ||
		!RESOURCE_ID.test(suffix[2] ?? "")
	) {
		throw MindcladeError.invalidArgument("checkpoint resource name is invalid");
	}
	return name;
};

const scopedName = (core: ClientCore, name: string, collection: string): string => {
	const prefix = `${projectName(core)}/${collection}/`;
	const id = name.startsWith(prefix) ? name.slice(prefix.length) : "";
	if (!RESOURCE_ID.test(id))
		throw MindcladeError.invalidArgument(`${collection} resource is outside client scope`);
	return name;
};

const validatePage = (size: number | undefined): void => {
	if (size !== undefined && (!Number.isInteger(size) || size < 0 || size > MAXIMUM_PAGE_SIZE))
		throw MindcladeError.invalidArgument(
			"training page size must be an integer between zero and 200",
		);
};

const ensureUnfenced = (options: SdkCallOptions): void => {
	if (options.workerId !== undefined || options.leaseToken !== undefined)
		throw MindcladeError.invalidArgument(
			"worker and lease credentials are accepted only by fenced training mutations",
		);
};

const ensureFenced = (options: SdkCallOptions): void => {
	if (options.workerId === undefined || options.leaseToken === undefined)
		throw MindcladeError.invalidArgument(
			"fenced training mutations require worker identity and a scheduler-issued lease token",
		);
};

const contextWithDigest = <Desc extends DescMessage>(
	core: ClientCore,
	prepared: PreparedCall,
	options: SubmitOptions,
	schema: Desc,
	message: MessageShape<Desc>,
) => ({
	...commandContext(core.config, prepared, options),
	canonicalRequestDigest: `sha256:${createHash("sha256").update(toBinary(schema, message)).digest("hex")}`,
});

const callOptions = (options: WaitOptions, timeoutMs: number): SdkCallOptions => ({
	...(options.requestId === undefined ? {} : { requestId: options.requestId }),
	...(options.traceId === undefined ? {} : { traceId: options.traceId }),
	...(options.signal === undefined ? {} : { signal: options.signal }),
	timeoutMs: Math.min(timeoutMs, options.timeoutMs ?? timeoutMs),
});

const bare = (value: string, collection: string): string =>
	value.startsWith(`${collection}/`) ? value.slice(collection.length + 1) : value;
