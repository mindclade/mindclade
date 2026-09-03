import { createHash } from "node:crypto";
import {
	clone,
	create,
	type DescMessage,
	type MessageInitShape,
	type MessageShape,
	toBinary,
} from "@bufbuild/protobuf";

import type { ArtifactRef } from "../../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import type { ResourceRef } from "../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	CompleteTrialCommandSchema,
	CreateExperimentCommandSchema,
	CreateStudyCommandSchema,
	CreateTrialCommandSchema,
	TransitionExperimentCommandSchema,
	TransitionStudyCommandSchema,
	TransitionTrialCommandSchema,
	UpdateExperimentCommandSchema,
} from "../../../protocols/generated/typescript/experiment/v1/experiment_commands_pb.js";
import {
	type Experiment,
	ExperimentSchema,
} from "../../../protocols/generated/typescript/experiment/v1/experiment_pb.js";
import {
	type Study,
	StudySchema,
} from "../../../protocols/generated/typescript/experiment/v1/study_pb.js";
import {
	type Trial,
	TrialSchema,
} from "../../../protocols/generated/typescript/experiment/v1/trial_pb.js";
import {
	CompleteTrialRequestSchema,
	CreateExperimentRequestSchema,
	CreateStudyRequestSchema,
	CreateTrialRequestSchema,
	GetExperimentRequestSchema,
	GetStudyRequestSchema,
	GetTrialRequestSchema,
	ListExperimentsRequestSchema,
	type ListExperimentsResponse,
	ListStudiesRequestSchema,
	type ListStudiesResponse,
	ListTrialsRequestSchema,
	type ListTrialsResponse,
	TransitionExperimentRequestSchema,
	TransitionStudyRequestSchema,
	TransitionTrialRequestSchema,
	UpdateExperimentRequestSchema,
} from "../../../protocols/generated/typescript/internal/experiment/v1/experiment_service_pb.js";
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

const CREATE = "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment";
const GET = "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment";
const LIST = "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments";
const UPDATE = "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment";
const TRANSITION = "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment";
const CREATE_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy";
const GET_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/GetStudy";
const LIST_STUDIES = "/mindclade.internal.experiment.v1.ExperimentService/ListStudies";
const TRANSITION_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy";
const CREATE_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial";
const GET_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/GetTrial";
const LIST_TRIALS = "/mindclade.internal.experiment.v1.ExperimentService/ListTrials";
const TRANSITION_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial";
const COMPLETE_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial";
const DIGEST = /^sha256:[0-9a-f]{64}$/;
const LEAF = /^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$/;
const REASON = /^[A-Z0-9][A-Z0-9_]{0,127}$/;

/** Private generated-type Experiment, Study, and Trial lifecycle façade. */
export class Experiments {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async create(
		input: MessageInitShape<typeof CreateExperimentCommandSchema>,
		options: SubmitOptions,
	): Promise<Experiment> {
		const command = create(CreateExperimentCommandSchema, input);
		if (
			!LEAF.test(command.experimentId) ||
			command.displayName.trim() === "" ||
			command.displayName.length > 512 ||
			command.kind === 0 ||
			command.subjects.length < 1 ||
			command.subjects.length > 256 ||
			command.policyClassification.trim() === ""
		)
			throw MindcladeError.invalidArgument("experiment creation intent is incomplete");
		validateArtifact(command.intentManifest);
		if (command.usePolicy === undefined)
			throw MindcladeError.invalidArgument("use policy is required");
		normalizeReference(this.#core, command.usePolicy, "use_policy");
		for (const subject of command.subjects) normalizeReference(this.#core, subject, "");
		command.project = projectReference(this.#core);
		const name = `${projectName(this.#core)}/experiments/${command.experimentId}`;
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CreateExperimentCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.createExperiment(
					create(CreateExperimentRequestSchema, { command }),
					call,
				),
		);
		return named(response.experiment, ExperimentSchema, name, "CreateExperiment");
	}

	async get(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<Experiment> {
		const scoped = experimentName(this.#core, name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET, undefined, (call) =>
			this.#core.raw.experiments.getExperiment(
				create(GetExperimentRequestSchema, { name: scoped, ifNoneMatch }),
				call,
			),
		);
		return named(response.experiment, ExperimentSchema, scoped, "GetExperiment");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async list(
		input: MessageInitShape<typeof ListExperimentsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<Experiment, ListExperimentsResponse>> {
		const request = create(ListExperimentsRequestSchema, input);
		const parent = projectName(this.#core);
		const pageSize = request.page?.pageSize ?? 0;
		if (
			(request.parent !== "" && request.parent !== parent) ||
			!Number.isInteger(pageSize) ||
			pageSize < 0 ||
			pageSize > 200
		)
			throw MindcladeError.invalidArgument("experiment list scope or page size is invalid");
		request.parent = parent;
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListExperimentsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST, undefined, (call) =>
					this.#core.raw.experiments.listExperiments(paged, call),
				);
				for (const value of response.experiments) experimentName(this.#core, value.name);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.experiments,
			limits: options.limits,
			pageSize,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async update(
		input: MessageInitShape<typeof UpdateExperimentCommandSchema>,
		options: SubmitOptions,
	): Promise<Experiment> {
		const command = create(UpdateExperimentCommandSchema, input);
		if (command.experiment === undefined || command.updateMask === undefined)
			throw MindcladeError.invalidArgument("experiment update requires state and FieldMask");
		const name = experimentName(this.#core, command.experiment.name);
		const allowed = new Set(["display_name", "labels", "annotations", "policy_classification"]);
		if (
			command.etag === "" ||
			command.etag !== command.experiment.etag ||
			command.updateMask.paths.length < 1 ||
			command.updateMask.paths.length > 4 ||
			command.updateMask.paths.some((value) => !allowed.has(value))
		)
			throw MindcladeError.invalidArgument("experiment update mask or ETag is invalid");
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(UpdateExperimentCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			UPDATE,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.updateExperiment(
					create(UpdateExperimentRequestSchema, { command }),
					call,
				),
		);
		return named(response.experiment, ExperimentSchema, name, "UpdateExperiment");
	}

	async transition(
		input: MessageInitShape<typeof TransitionExperimentCommandSchema>,
		options: SubmitOptions,
	): Promise<Experiment> {
		const command = create(TransitionExperimentCommandSchema, input);
		const name = normalizeRequiredReference(this.#core, command.experiment, "experiment");
		validateTransition(
			command.expectedState,
			command.targetState,
			command.etag,
			command.reasonCode,
		);
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(TransitionExperimentCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			TRANSITION,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.transitionExperiment(
					create(TransitionExperimentRequestSchema, { command }),
					call,
				),
		);
		return named(response.experiment, ExperimentSchema, name, "TransitionExperiment");
	}

	async createStudy(
		input: MessageInitShape<typeof CreateStudyCommandSchema>,
		options: SubmitOptions,
	): Promise<Study> {
		const command = create(CreateStudyCommandSchema, input);
		const parent = normalizeRequiredReference(this.#core, command.experiment, "experiment");
		if (!LEAF.test(command.studyId) || command.type === 0 || command.budget === undefined)
			throw MindcladeError.invalidArgument("study identity, type, and bounded budget are required");
		for (const artifact of [
			command.studyManifest,
			command.baseConfiguration,
			command.searchSpace,
			command.objectiveSpecification,
		])
			validateArtifact(artifact);
		const duration = command.budget.maximumDuration;
		if (
			command.budget.maximumTrials < 1 ||
			command.budget.maximumTrials > 100_000 ||
			command.budget.maximumParallelTrials < 1 ||
			command.budget.maximumParallelTrials > command.budget.maximumTrials ||
			duration === undefined ||
			duration.seconds < 1n ||
			duration.seconds > 31_536_000n
		)
			throw MindcladeError.invalidArgument("study budget is invalid or unbounded");
		const name = `${parent}/studies/${command.studyId}`;
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CreateStudyCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE_STUDY,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.createStudy(create(CreateStudyRequestSchema, { command }), call),
		);
		return named(response.study, StudySchema, name, "CreateStudy");
	}

	async getStudy(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<Study> {
		const scoped = studyName(this.#core, name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_STUDY, undefined, (call) =>
			this.#core.raw.experiments.getStudy(
				create(GetStudyRequestSchema, { name: scoped, ifNoneMatch }),
				call,
			),
		);
		return named(response.study, StudySchema, scoped, "GetStudy");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listStudies(
		input: MessageInitShape<typeof ListStudiesRequestSchema>,
		options: ListOptions = {},
	): Promise<Page<Study, ListStudiesResponse>> {
		const request = create(ListStudiesRequestSchema, input);
		request.parent = experimentName(this.#core, request.parent);
		validatePage(request.page?.pageSize ?? 0);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListStudiesRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST_STUDIES, undefined, (call) =>
					this.#core.raw.experiments.listStudies(paged, call),
				);
				for (const value of response.studies) studyName(this.#core, value.name);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.studies,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async transitionStudy(
		input: MessageInitShape<typeof TransitionStudyCommandSchema>,
		options: SubmitOptions,
	): Promise<Study> {
		const command = create(TransitionStudyCommandSchema, input);
		const name = normalizeRequiredReference(this.#core, command.study, "study");
		validateTransition(
			command.expectedState,
			command.targetState,
			command.etag,
			command.reasonCode,
		);
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(TransitionStudyCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			TRANSITION_STUDY,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.transitionStudy(
					create(TransitionStudyRequestSchema, { command }),
					call,
				),
		);
		return named(response.study, StudySchema, name, "TransitionStudy");
	}

	async createTrial(
		input: MessageInitShape<typeof CreateTrialCommandSchema>,
		options: SubmitOptions,
	): Promise<Trial> {
		const command = create(CreateTrialCommandSchema, input);
		const parent = normalizeRequiredReference(this.#core, command.study, "study");
		if (!LEAF.test(command.trialId) || command.trialNumber < 1)
			throw MindcladeError.invalidArgument("trial ID and positive number are required");
		validateArtifact(command.resolvedConfiguration);
		if (command.execution !== undefined) normalizeReference(this.#core, command.execution, "");
		const name = `${parent}/trials/${command.trialId}`;
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CreateTrialCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			CREATE_TRIAL,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.createTrial(create(CreateTrialRequestSchema, { command }), call),
		);
		return named(response.trial, TrialSchema, name, "CreateTrial");
	}

	async getTrial(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<Trial> {
		const scoped = trialName(this.#core, name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(this.#core, prepared, GET_TRIAL, undefined, (call) =>
			this.#core.raw.experiments.getTrial(
				create(GetTrialRequestSchema, { name: scoped, ifNoneMatch }),
				call,
			),
		);
		return named(response.trial, TrialSchema, scoped, "GetTrial");
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async listTrials(
		input: MessageInitShape<typeof ListTrialsRequestSchema>,
		options: ListOptions = {},
	): Promise<Page<Trial, ListTrialsResponse>> {
		const request = create(ListTrialsRequestSchema, input);
		request.parent = studyName(this.#core, request.parent);
		validatePage(request.page?.pageSize ?? 0);
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListTrialsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(this.#core, prepared, LIST_TRIALS, undefined, (call) =>
					this.#core.raw.experiments.listTrials(paged, call),
				);
				for (const value of response.trials) trialName(this.#core, value.name);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.trials,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async transitionTrial(
		input: MessageInitShape<typeof TransitionTrialCommandSchema>,
		options: SubmitOptions,
	): Promise<Trial> {
		const command = create(TransitionTrialCommandSchema, input);
		const name = normalizeRequiredReference(this.#core, command.trial, "trial");
		validateTransition(
			command.expectedState,
			command.targetState,
			command.etag,
			command.reasonCode,
		);
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(TransitionTrialCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			TRANSITION_TRIAL,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.transitionTrial(
					create(TransitionTrialRequestSchema, { command }),
					call,
				),
		);
		return named(response.trial, TrialSchema, name, "TransitionTrial");
	}

	async completeTrial(
		input: MessageInitShape<typeof CompleteTrialCommandSchema>,
		options: SubmitOptions,
	): Promise<Trial> {
		const command = create(CompleteTrialCommandSchema, input);
		const name = normalizeRequiredReference(this.#core, command.trial, "trial");
		if (
			command.etag.trim() === "" ||
			command.outcome === 0 ||
			command.outcome === 5 ||
			command.evidence.length > 256
		)
			throw MindcladeError.invalidArgument("trial completion intent is invalid");
		if (command.outcome === 2) {
			if (
				command.error?.message.trim() === "" ||
				command.error === undefined ||
				command.resultManifest !== undefined
			)
				throw MindcladeError.invalidArgument("failed trial requires error and no result manifest");
		} else {
			validateArtifact(command.resultManifest);
			if (command.error !== undefined)
				throw MindcladeError.invalidArgument("non-failed trial cannot carry error");
		}
		for (const value of command.evidence)
			if (
				!DIGEST.test(value.digest) ||
				!DIGEST.test(value.subjectDigest) ||
				value.evidenceKind.trim() === "" ||
				(value.policyDigest !== "" && !DIGEST.test(value.policyDigest))
			)
				throw MindcladeError.invalidArgument("trial evidence requires immutable canonical digests");
		delete command.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CompleteTrialCommandSchema, command)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMPLETE_TRIAL,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.experiments.completeTrial(
					create(CompleteTrialRequestSchema, { command }),
					call,
				),
		);
		return named(response.trial, TrialSchema, name, "CompleteTrial");
	}
}

const projectName = (core: ClientCore): string => {
	const tenant = core.config.identity.tenantId.startsWith("tenants/")
		? core.config.identity.tenantId
		: `tenants/${core.config.identity.tenantId}`;
	const project = core.config.identity.projectId;
	return project.startsWith("tenants/")
		? project
		: project.startsWith("projects/")
			? `${tenant}/${project}`
			: `${tenant}/projects/${project}`;
};
const projectReference = (core: ClientCore): ResourceRef => ({
	$typeName: "mindclade.common.v1.ResourceRef",
	resourceType: "project",
	resourceId: core.config.identity.projectId,
	tenantId: core.config.identity.tenantId,
	projectId: core.config.identity.projectId,
	resourceVersion: 0n,
	name: projectName(core),
	etag: "",
});
const hierarchyName = (core: ClientCore, name: string, expected: readonly string[]): string => {
	const tail = name.startsWith(`${projectName(core)}/`)
		? name.slice(projectName(core).length + 1).split("/")
		: [];
	if (
		tail.length !== expected.length * 2 ||
		expected.some(
			(value, index) => tail[index * 2] !== value || !LEAF.test(tail[index * 2 + 1] ?? ""),
		)
	)
		throw MindcladeError.invalidArgument("resource is outside configured scope or malformed");
	return name;
};
const experimentName = (core: ClientCore, name: string): string =>
	hierarchyName(core, name, ["experiments"]);
const studyName = (core: ClientCore, name: string): string =>
	hierarchyName(core, name, ["experiments", "studies"]);
const trialName = (core: ClientCore, name: string): string =>
	hierarchyName(core, name, ["experiments", "studies", "trials"]);
const normalizeRequiredReference = (
	core: ClientCore,
	value: ResourceRef | undefined,
	kind: string,
): string => {
	if (value === undefined) throw MindcladeError.invalidArgument(`${kind} reference is required`);
	normalizeReference(core, value, kind);
	return value.name;
};
const normalizeReference = (core: ClientCore, value: ResourceRef, kind: string): void => {
	const id = value.name.split("/").at(-1) ?? "";
	if (
		!value.name.startsWith(`${projectName(core)}/`) ||
		!LEAF.test(id) ||
		value.resourceVersion < 1n ||
		!DIGEST.test(value.etag) ||
		(kind !== "" && value.resourceType !== "" && value.resourceType !== kind)
	)
		throw MindcladeError.invalidArgument(
			"resource reference conflicts with experiment scope or revision",
		);
	if (kind !== "") value.resourceType = kind;
	value.resourceId = id;
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};
const validateArtifact = (value: ArtifactRef | undefined): void => {
	if (
		value === undefined ||
		!DIGEST.test(value.digest) ||
		(value.integrityDigest !== "" && !DIGEST.test(value.integrityDigest)) ||
		value.mediaType.trim() === "" ||
		value.sizeBytes < 0n
	)
		throw MindcladeError.invalidArgument("immutable artifact reference is invalid");
};
const validateTransition = (
	expected: number,
	target: number,
	etag: string,
	reason: string,
): void => {
	if (
		expected === 0 ||
		target === 0 ||
		expected === target ||
		etag.trim() === "" ||
		!REASON.test(reason)
	)
		throw MindcladeError.invalidArgument("lifecycle transition intent is invalid");
};
const validatePage = (size: number): void => {
	if (!Number.isInteger(size) || size < 0 || size > 200)
		throw MindcladeError.invalidArgument("page size must be an integer between zero and 200");
};
const contextWithDigest = (
	core: ClientCore,
	prepared: ReturnType<typeof prepareCall>,
	options: SubmitOptions,
	digest: string,
) => ({ ...commandContext(core.config, prepared, options), canonicalRequestDigest: digest });
const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;
const named = <Schema extends DescMessage>(
	value: MessageShape<Schema> | undefined,
	schema: Schema,
	expected: string,
	operation: string,
): MessageShape<Schema> => {
	if (value === undefined || !("name" in value) || value.name !== expected)
		throw MindcladeError.protocol(`${operation} response violated durable identity`);
	return clone(schema, value);
};
