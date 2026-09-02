import { create, type MessageInitShape } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";

import type { ResourceRef } from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	ActivateUsePolicyRequestSchema,
	CreateUsePolicyRequestSchema,
	EvaluateAuthorizationRequestSchema,
	GetUsePolicyRequestSchema,
	ListUsePoliciesRequestSchema,
	type ListUsePoliciesResponse,
	ResolvePolicySnapshotRequestSchema,
	RevokeUsePolicyRequestSchema,
	UpdateUsePolicyRequestSchema,
} from "../../../../protocols/generated/typescript/internal/policy/v1/policy_service_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { AuthorizationDecision } from "../../../../protocols/generated/typescript/policy/v1/authorization_decision_pb.js";
import type { PolicyReference } from "../../../../protocols/generated/typescript/policy/v1/policy_reference_pb.js";
import type { UsePolicy } from "../../../../protocols/generated/typescript/policy/v1/use_policy_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { commandContext, prepareCall, type SdkCallOptions, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const EVALUATE = "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization";
const CREATE = "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy";
const UPDATE = "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy";
const GET = "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy";
const LIST = "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies";
const ACTIVATE = "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy";
const REVOKE = "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy";
const RESOLVE = "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot";

/** Fail-closed authorization and use-policy facade over generated contracts. */
export class Policies {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async evaluate(
		request: MessageInitShape<typeof EvaluateAuthorizationRequestSchema>,
		options: SubmitOptions,
	): Promise<AuthorizationDecision> {
		const generated = create(EvaluateAuthorizationRequestSchema, request);
		if (
			generated.action.trim() === "" ||
			!/^sha256:[0-9a-f]{64}$/.test(generated.intentDigest) ||
			generated.resource === undefined
		) {
			throw MindcladeError.invalidArgument(
				"authorization evaluation requires an action, resource, and sha256 intent digest",
			);
		}
		normalizeResource(this.#core, generated.resource);
		generated.tenantId = this.#core.config.identity.tenantId;
		generated.projectId = this.#core.config.identity.projectId;
		generated.principalRef = this.#core.config.identity.principalId;
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.deadline = timestampFromDate(new Date(prepared.deadlineMs));
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(EVALUATE),
			options.idempotencyKey,
			(call) => this.#core.raw.policy.evaluateAuthorization(generated, call),
		);
		if (response.decision === undefined)
			throw MindcladeError.protocol("EvaluateAuthorization response omitted its decision");
		return response.decision;
	}

	async create(
		request: MessageInitShape<typeof CreateUsePolicyRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(CreateUsePolicyRequestSchema, request);
		const parent = projectName(this.#core);
		if (
			(generated.parent !== "" && generated.parent !== parent) ||
			!/^[A-Za-z0-9._-]{1,128}$/.test(generated.usePolicyId) ||
			generated.usePolicy === undefined
		) {
			throw MindcladeError.invalidArgument(
				"policy creation requires the configured project, a valid ID, and a policy",
			);
		}
		generated.parent = parent;
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(CREATE),
			options.idempotencyKey,
			(call) => this.#core.raw.policy.createUsePolicy(generated, call),
		);
		return requiredOperation(response.operation, "CreateUsePolicy");
	}

	async update(
		request: MessageInitShape<typeof UpdateUsePolicyRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(UpdateUsePolicyRequestSchema, request);
		if (
			generated.usePolicy === undefined ||
			generated.updateMask === undefined ||
			generated.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument("policy update requires a policy, field mask, and etag");
		}
		policyName(this.#core, generated.usePolicy.name);
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(UPDATE),
			options.idempotencyKey,
			(call) => this.#core.raw.policy.updateUsePolicy(generated, call),
		);
		return requiredOperation(response.operation, "UpdateUsePolicy");
	}

	async get(
		request: MessageInitShape<typeof GetUsePolicyRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<UsePolicy> {
		const generated = create(GetUsePolicyRequestSchema, request);
		generated.name = policyName(this.#core, generated.name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET),
			undefined,
			(call) => this.#core.raw.policy.getUsePolicy(generated, call),
		);
		if (response.usePolicy === undefined)
			throw MindcladeError.protocol("GetUsePolicy response omitted its policy");
		return response.usePolicy;
	}

	async list(
		request: MessageInitShape<typeof ListUsePoliciesRequestSchema> = {},
		options: SdkCallOptions = {},
	): Promise<ListUsePoliciesResponse> {
		const generated = create(ListUsePoliciesRequestSchema, request);
		const parent = projectName(this.#core);
		if (generated.parent !== "" && generated.parent !== parent)
			throw MindcladeError.invalidArgument("policy list parent does not match client scope");
		validatePage(generated.page?.pageSize);
		generated.parent = parent;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST),
			undefined,
			(call) => this.#core.raw.policy.listUsePolicies(generated, call),
		);
	}

	async activate(
		request: MessageInitShape<typeof ActivateUsePolicyRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(ActivateUsePolicyRequestSchema, request);
		generated.name = policyName(this.#core, generated.name);
		if (generated.etag.trim() === "")
			throw MindcladeError.invalidArgument("policy activation requires an etag");
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(ACTIVATE),
			options.idempotencyKey,
			(call) => this.#core.raw.policy.activateUsePolicy(generated, call),
		);
		return requiredOperation(response.operation, "ActivateUsePolicy");
	}

	async revoke(
		request: MessageInitShape<typeof RevokeUsePolicyRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(RevokeUsePolicyRequestSchema, request);
		generated.name = policyName(this.#core, generated.name);
		if (generated.etag.trim() === "" || generated.reasonCode.trim() === "")
			throw MindcladeError.invalidArgument("policy revocation requires an etag and reason code");
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(REVOKE),
			options.idempotencyKey,
			(call) => this.#core.raw.policy.revokeUsePolicy(generated, call),
		);
		return requiredOperation(response.operation, "RevokeUsePolicy");
	}

	async resolveSnapshot(
		request: MessageInitShape<typeof ResolvePolicySnapshotRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<PolicyReference> {
		const generated = create(ResolvePolicySnapshotRequestSchema, request);
		generated.name = policyName(this.#core, generated.name);
		if (generated.effectiveTime === undefined)
			throw MindcladeError.invalidArgument("snapshot resolution requires an effective time");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(RESOLVE),
			undefined,
			(call) => this.#core.raw.policy.resolvePolicySnapshot(generated, call),
		);
		if (response.policySnapshot === undefined)
			throw MindcladeError.protocol("ResolvePolicySnapshot response omitted its snapshot");
		return response.policySnapshot;
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

const policyName = (core: ClientCore, name: string): string => {
	const prefix = `${projectName(core)}/usePolicies/`;
	const id = name.startsWith(prefix) ? name.slice(prefix.length) : "";
	if (!/^[A-Za-z0-9._-]{1,128}$/.test(id))
		throw MindcladeError.invalidArgument("policy is outside the configured project");
	return name;
};

const normalizeResource = (core: ClientCore, resource: ResourceRef): void => {
	const parent = projectName(core);
	if (resource.name !== parent && !resource.name.startsWith(`${parent}/`))
		throw MindcladeError.invalidArgument("resource is outside the configured project");
	if (
		(resource.tenantId !== "" && resource.tenantId !== core.config.identity.tenantId) ||
		(resource.projectId !== "" && resource.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("resource scope conflicts with client identity");
	}
	resource.tenantId = core.config.identity.tenantId;
	resource.projectId = core.config.identity.projectId;
};

const validatePage = (size: number | undefined): void => {
	if (size !== undefined && size > 1000)
		throw MindcladeError.invalidArgument("page size cannot exceed 1000");
};

const requiredOperation = (operation: Operation | undefined, method: string): Operation => {
	if (operation === undefined || operation.operationId.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	return operation;
};
