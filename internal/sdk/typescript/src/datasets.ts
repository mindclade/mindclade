import { create, type MessageInitShape } from "@bufbuild/protobuf";

import {
	type ResourceRef,
	ResourceRefSchema,
} from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	CreateDatasetCommandSchema,
	PublishDatasetReleaseCommandSchema,
	RevokeDatasetReleaseCommandSchema,
	UpdateDatasetCommandSchema,
} from "../../../../protocols/generated/typescript/dataset/v1/dataset_commands_pb.js";
import type { Dataset } from "../../../../protocols/generated/typescript/dataset/v1/dataset_pb.js";
import type { DatasetRelease } from "../../../../protocols/generated/typescript/dataset/v1/dataset_release_pb.js";
import {
	CreateDatasetRequestSchema,
	GetDatasetReleaseRequestSchema,
	GetDatasetRequestSchema,
	ListDatasetReleasesRequestSchema,
	type ListDatasetReleasesResponse,
	ListDatasetsRequestSchema,
	type ListDatasetsResponse,
	PublishDatasetReleaseRequestSchema,
	RevokeDatasetReleaseRequestSchema,
	UpdateDatasetRequestSchema,
} from "../../../../protocols/generated/typescript/internal/dataset/v1/dataset_service_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { commandContext, prepareCall, type SdkCallOptions, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const CREATE = "/mindclade.internal.dataset.v1.DatasetService/CreateDataset";
const GET = "/mindclade.internal.dataset.v1.DatasetService/GetDataset";
const LIST = "/mindclade.internal.dataset.v1.DatasetService/ListDatasets";
const UPDATE = "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset";
const PUBLISH = "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease";
const REVOKE = "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease";
const GET_RELEASE = "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease";
const LIST_RELEASES = "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases";

/** Private Dataset lifecycle facade. Every request and response is generated. */
export class Datasets {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async create(
		command: MessageInitShape<typeof CreateDatasetCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const parent = projectName(this.#core);
		if (command.project?.name !== undefined && command.project.name !== parent) {
			throw MindcladeError.invalidArgument("dataset project does not match client scope");
		}
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(CreateDatasetCommandSchema, command);
		delete generated.context;
		generated.project ??= projectRef(this.#core);
		// JavaScript map iteration is not a cross-language canonical encoding.
		// The authoritative service validates this identity context and persists
		// the deterministic request digest it computes from the generated command.
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(CREATE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.datasets.createDataset(
					create(CreateDatasetRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "CreateDataset");
	}

	async get(
		request: MessageInitShape<typeof GetDatasetRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<Dataset> {
		const generated = create(GetDatasetRequestSchema, request);
		generated.name = datasetName(this.#core, generated.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET),
			undefined,
			(call) => this.#core.raw.datasets.getDataset(generated, call),
		);
		if (response.dataset === undefined)
			throw MindcladeError.protocol("GetDataset response omitted its dataset");
		return response.dataset;
	}

	async list(
		request: MessageInitShape<typeof ListDatasetsRequestSchema> = {},
		options: SdkCallOptions = {},
	): Promise<ListDatasetsResponse> {
		const generated = create(ListDatasetsRequestSchema, request);
		const parent = projectName(this.#core);
		if (generated.parent !== "" && generated.parent !== parent)
			throw MindcladeError.invalidArgument("dataset list parent does not match client scope");
		generated.parent = parent;
		validatePage(generated.page?.pageSize);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST),
			undefined,
			(call) => this.#core.raw.datasets.listDatasets(generated, call),
		);
	}

	async update(
		command: MessageInitShape<typeof UpdateDatasetCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.dataset?.name === undefined)
			throw MindcladeError.invalidArgument("update requires a generated dataset");
		datasetName(this.#core, command.dataset.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(UpdateDatasetCommandSchema, command);
		delete generated.context;
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(UPDATE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.datasets.updateDataset(
					create(UpdateDatasetRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "UpdateDataset");
	}

	async publishRelease(
		command: MessageInitShape<typeof PublishDatasetReleaseCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.dataset?.name === undefined)
			throw MindcladeError.invalidArgument("publication requires a generated dataset reference");
		datasetName(this.#core, command.dataset.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(PublishDatasetReleaseCommandSchema, command);
		delete generated.context;
		if (generated.dataset === undefined)
			throw MindcladeError.invalidArgument("publication requires a generated dataset reference");
		normalizeReference(this.#core, generated.dataset, "dataset", false);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(PUBLISH),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.datasets.publishDatasetRelease(
					create(PublishDatasetReleaseRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "PublishDatasetRelease");
	}

	async revokeRelease(
		command: MessageInitShape<typeof RevokeDatasetReleaseCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.datasetRelease?.name === undefined)
			throw MindcladeError.invalidArgument(
				"revocation requires a generated dataset release reference",
			);
		releaseName(this.#core, command.datasetRelease.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(RevokeDatasetReleaseCommandSchema, command);
		delete generated.context;
		if (generated.datasetRelease === undefined)
			throw MindcladeError.invalidArgument(
				"revocation requires a generated dataset release reference",
			);
		normalizeReference(this.#core, generated.datasetRelease, "dataset_release", true);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(REVOKE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.datasets.revokeDatasetRelease(
					create(RevokeDatasetReleaseRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "RevokeDatasetRelease");
	}

	async getRelease(
		request: MessageInitShape<typeof GetDatasetReleaseRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<DatasetRelease> {
		const generated = create(GetDatasetReleaseRequestSchema, request);
		generated.name = releaseName(this.#core, generated.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_RELEASE),
			undefined,
			(call) => this.#core.raw.datasets.getDatasetRelease(generated, call),
		);
		if (response.datasetRelease === undefined)
			throw MindcladeError.protocol("GetDatasetRelease response omitted its release");
		return response.datasetRelease;
	}

	async listReleases(
		request: MessageInitShape<typeof ListDatasetReleasesRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<ListDatasetReleasesResponse> {
		const generated = create(ListDatasetReleasesRequestSchema, request);
		generated.parent = datasetName(this.#core, generated.parent);
		validatePage(generated.page?.pageSize);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST_RELEASES),
			undefined,
			(call) => this.#core.raw.datasets.listDatasetReleases(generated, call),
		);
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
const projectRef = (core: ClientCore) =>
	create(ResourceRefSchema, {
		resourceType: "project",
		resourceId: core.config.identity.projectId,
		tenantId: core.config.identity.tenantId,
		projectId: core.config.identity.projectId,
		name: projectName(core),
	});

const datasetName = (core: ClientCore, name: string): string => scopedName(core, name, false);
const releaseName = (core: ClientCore, name: string): string => scopedName(core, name, true);
const scopedName = (core: ClientCore, name: string, release: boolean): string => {
	const prefix = `${projectName(core)}/datasets/`;
	if (!name.startsWith(prefix))
		throw MindcladeError.invalidArgument("resource is outside the configured project");
	const suffix = name.slice(prefix.length);
	const valid = release ? /^[^/]+\/releases\/[^/]+$/.test(suffix) : /^[^/]+$/.test(suffix);
	if (!valid) throw MindcladeError.invalidArgument("resource name is invalid");
	return name;
};
const normalizeReference = (
	core: ClientCore,
	reference: ResourceRef,
	resourceType: string,
	release: boolean,
): void => {
	const name = scopedName(core, reference.name, release);
	const resourceId = name.slice(name.lastIndexOf("/") + 1);
	if (
		(reference.resourceType !== "" && reference.resourceType !== resourceType) ||
		(reference.resourceId !== "" && reference.resourceId !== resourceId) ||
		(reference.tenantId !== "" && reference.tenantId !== core.config.identity.tenantId) ||
		(reference.projectId !== "" && reference.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument(
			"resource reference does not match the configured project",
		);
	}
	reference.resourceType = resourceType;
	reference.resourceId = resourceId;
	reference.tenantId = core.config.identity.tenantId;
	reference.projectId = core.config.identity.projectId;
};
const validatePage = (size: number | undefined): void => {
	if (size !== undefined && (!Number.isInteger(size) || size < 0 || size > 1000))
		throw MindcladeError.invalidArgument("page size must be an integer between zero and 1000");
};
const requiredOperation = (operation: Operation | undefined, method: string): Operation => {
	if (operation === undefined || operation.operationId.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	return operation;
};
