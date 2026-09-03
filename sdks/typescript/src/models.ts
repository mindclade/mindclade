import { create, type MessageInitShape } from "@bufbuild/protobuf";

import {
	type ResourceRef,
	ResourceRefSchema,
} from "../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	GetModelReleaseRequestSchema,
	GetModelRequestSchema,
	ListModelReleasesRequestSchema,
	type ListModelReleasesResponse,
	ListModelsRequestSchema,
	type ListModelsResponse,
	PromoteModelReleaseRequestSchema,
	RegisterModelReleaseRequestSchema,
	RegisterModelRequestSchema,
	RevokeModelReleaseRequestSchema,
} from "../../../protocols/generated/typescript/internal/model/v1/model_service_pb.js";
import type { Operation } from "../../../protocols/generated/typescript/operation/v1/operation_pb.js";
import {
	PromoteModelReleaseCommandSchema,
	RegisterModelCommandSchema,
	RegisterModelReleaseCommandSchema,
	RevokeModelReleaseCommandSchema,
} from "../../../protocols/generated/typescript/model/v1/model_commands_pb.js";
import type { Model } from "../../../protocols/generated/typescript/model/v1/model_pb.js";
import type { ModelRelease } from "../../../protocols/generated/typescript/model/v1/model_release_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { commandContext, prepareCall, type SdkCallOptions, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const REGISTER = "/mindclade.internal.model.v1.ModelService/RegisterModel";
const GET = "/mindclade.internal.model.v1.ModelService/GetModel";
const LIST = "/mindclade.internal.model.v1.ModelService/ListModels";
const REGISTER_RELEASE = "/mindclade.internal.model.v1.ModelService/RegisterModelRelease";
const GET_RELEASE = "/mindclade.internal.model.v1.ModelService/GetModelRelease";
const LIST_RELEASES = "/mindclade.internal.model.v1.ModelService/ListModelReleases";
const PROMOTE = "/mindclade.internal.model.v1.ModelService/PromoteModelRelease";
const REVOKE = "/mindclade.internal.model.v1.ModelService/RevokeModelRelease";

/** Private model registry and immutable-release facade over generated contracts. */
export class Models {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async register(
		command: MessageInitShape<typeof RegisterModelCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const parent = projectName(this.#core);
		if (command.project?.name !== undefined && command.project.name !== parent)
			throw MindcladeError.invalidArgument("model project does not match client scope");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(RegisterModelCommandSchema, command);
		delete generated.context;
		generated.project ??= projectRef(this.#core);
		// JavaScript map iteration is not a cross-language canonical encoding.
		// The authoritative service validates this identity context and persists
		// the deterministic request digest it computes from the generated command.
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(REGISTER),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.models.registerModel(
					create(RegisterModelRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "RegisterModel");
	}

	async get(
		request: MessageInitShape<typeof GetModelRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<Model> {
		const generated = create(GetModelRequestSchema, request);
		generated.name = modelName(this.#core, generated.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET),
			undefined,
			(call) => this.#core.raw.models.getModel(generated, call),
		);
		if (response.model === undefined)
			throw MindcladeError.protocol("GetModel response omitted its model");
		return response.model;
	}

	async list(
		request: MessageInitShape<typeof ListModelsRequestSchema> = {},
		options: SdkCallOptions = {},
	): Promise<ListModelsResponse> {
		const generated = create(ListModelsRequestSchema, request);
		const parent = projectName(this.#core);
		if (generated.parent !== "" && generated.parent !== parent)
			throw MindcladeError.invalidArgument("model list parent does not match client scope");
		generated.parent = parent;
		validatePage(generated.page?.pageSize);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST),
			undefined,
			(call) => this.#core.raw.models.listModels(generated, call),
		);
	}

	async registerRelease(
		command: MessageInitShape<typeof RegisterModelReleaseCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.model?.name === undefined)
			throw MindcladeError.invalidArgument("release requires a generated model reference");
		modelName(this.#core, command.model.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(RegisterModelReleaseCommandSchema, command);
		delete generated.context;
		if (generated.model === undefined)
			throw MindcladeError.invalidArgument("release requires a generated model reference");
		normalizeReference(this.#core, generated.model, "model", false);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(REGISTER_RELEASE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.models.registerModelRelease(
					create(RegisterModelReleaseRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "RegisterModelRelease");
	}

	async getRelease(
		request: MessageInitShape<typeof GetModelReleaseRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<ModelRelease> {
		const generated = create(GetModelReleaseRequestSchema, request);
		generated.name = releaseName(this.#core, generated.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_RELEASE),
			undefined,
			(call) => this.#core.raw.models.getModelRelease(generated, call),
		);
		if (response.modelRelease === undefined)
			throw MindcladeError.protocol("GetModelRelease response omitted its release");
		return response.modelRelease;
	}

	async listReleases(
		request: MessageInitShape<typeof ListModelReleasesRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<ListModelReleasesResponse> {
		const generated = create(ListModelReleasesRequestSchema, request);
		generated.parent = modelName(this.#core, generated.parent);
		validatePage(generated.page?.pageSize);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST_RELEASES),
			undefined,
			(call) => this.#core.raw.models.listModelReleases(generated, call),
		);
	}

	async promoteRelease(
		command: MessageInitShape<typeof PromoteModelReleaseCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.modelRelease?.name === undefined)
			throw MindcladeError.invalidArgument(
				"promotion requires a generated model release reference",
			);
		releaseName(this.#core, command.modelRelease.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(PromoteModelReleaseCommandSchema, command);
		delete generated.context;
		if (generated.modelRelease === undefined)
			throw MindcladeError.invalidArgument(
				"promotion requires a generated model release reference",
			);
		normalizeReference(this.#core, generated.modelRelease, "model_release", true);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(PROMOTE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.models.promoteModelRelease(
					create(PromoteModelReleaseRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "PromoteModelRelease");
	}

	async revokeRelease(
		command: MessageInitShape<typeof RevokeModelReleaseCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		if (command.modelRelease?.name === undefined)
			throw MindcladeError.invalidArgument(
				"revocation requires a generated model release reference",
			);
		releaseName(this.#core, command.modelRelease.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generated = create(RevokeModelReleaseCommandSchema, command);
		delete generated.context;
		if (generated.modelRelease === undefined)
			throw MindcladeError.invalidArgument(
				"revocation requires a generated model release reference",
			);
		normalizeReference(this.#core, generated.modelRelease, "model_release", true);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(REVOKE),
			options.idempotencyKey,
			(call) =>
				this.#core.raw.models.revokeModelRelease(
					create(RevokeModelReleaseRequestSchema, { command: generated }),
					call,
				),
		);
		return requiredOperation(response.operation, "RevokeModelRelease");
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
const modelName = (core: ClientCore, name: string): string => scopedName(core, name, false);
const releaseName = (core: ClientCore, name: string): string => scopedName(core, name, true);
const scopedName = (core: ClientCore, name: string, release: boolean): string => {
	const prefix = `${projectName(core)}/models/`;
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
