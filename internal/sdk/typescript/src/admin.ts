import { create, type MessageInitShape } from "@bufbuild/protobuf";

import {
	type AuditExport,
	type AuditQuery,
	type AuditQueryPage,
	AuditQuerySchema,
} from "../../../../protocols/generated/typescript/admin/v1/audit_query_pb.js";
import type { Project } from "../../../../protocols/generated/typescript/admin/v1/project_pb.js";
import type { Tenant } from "../../../../protocols/generated/typescript/admin/v1/tenant_pb.js";
import {
	type ResourceRef,
	ResourceRefSchema,
} from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	CreateProjectRequestSchema,
	ExportAuditRecordsRequestSchema,
	GetAuditExportRequestSchema,
	GetProjectRequestSchema,
	GetTenantRequestSchema,
	ListProjectsRequestSchema,
	type ListProjectsResponse,
	QueryAuditRecordsRequestSchema,
	UpdateProjectRequestSchema,
	UpdateTenantRequestSchema,
} from "../../../../protocols/generated/typescript/internal/admin/v1/admin_service_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { commandContext, prepareCall, type SdkCallOptions, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const GET_TENANT = "/mindclade.internal.admin.v1.AdminService/GetTenant";
const UPDATE_TENANT = "/mindclade.internal.admin.v1.AdminService/UpdateTenant";
const CREATE_PROJECT = "/mindclade.internal.admin.v1.AdminService/CreateProject";
const GET_PROJECT = "/mindclade.internal.admin.v1.AdminService/GetProject";
const LIST_PROJECTS = "/mindclade.internal.admin.v1.AdminService/ListProjects";
const UPDATE_PROJECT = "/mindclade.internal.admin.v1.AdminService/UpdateProject";
const QUERY_AUDIT = "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords";
const EXPORT_AUDIT = "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords";
const GET_EXPORT = "/mindclade.internal.admin.v1.AdminService/GetAuditExport";

/** Tenant, project, and payload-minimized audit facade over generated contracts. */
export class Admin {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async getTenant(
		request: MessageInitShape<typeof GetTenantRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<Tenant> {
		const generated = create(GetTenantRequestSchema, request);
		if (generated.name !== tenantName(this.#core))
			throw MindcladeError.invalidArgument("tenant name does not match client scope");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_TENANT),
			undefined,
			(call) => this.#core.raw.admin.getTenant(generated, call),
		);
		if (response.tenant === undefined)
			throw MindcladeError.protocol("GetTenant response omitted its tenant");
		return response.tenant;
	}

	async updateTenant(
		request: MessageInitShape<typeof UpdateTenantRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(UpdateTenantRequestSchema, request);
		if (
			generated.tenant?.name !== tenantName(this.#core) ||
			generated.updateMask === undefined ||
			generated.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"tenant update requires the configured tenant, a field mask, and etag",
			);
		}
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const context = commandContext(this.#core.config, prepared, options);
		context.projectId = "";
		generated.context = context;
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(UPDATE_TENANT),
			options.idempotencyKey,
			(call) => this.#core.raw.admin.updateTenant(generated, call),
		);
		return requiredOperation(response.operation, "UpdateTenant");
	}

	async createProject(
		request: MessageInitShape<typeof CreateProjectRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(CreateProjectRequestSchema, request);
		const tenant = tenantName(this.#core);
		const projectId = configuredProjectId(this.#core);
		if (
			(generated.parent !== "" && generated.parent !== tenant) ||
			(generated.projectId !== "" && generated.projectId !== projectId) ||
			generated.project === undefined
		) {
			throw MindcladeError.invalidArgument(
				"project creation must target the configured tenant and project",
			);
		}
		generated.parent = tenant;
		generated.projectId = projectId;
		if (generated.project.tenant === undefined) {
			generated.project.tenant = tenantReference(this.#core);
		} else {
			normalizeTenantReference(this.#core, generated.project.tenant);
		}
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(CREATE_PROJECT),
			options.idempotencyKey,
			(call) => this.#core.raw.admin.createProject(generated, call),
		);
		return requiredOperation(response.operation, "CreateProject");
	}

	async getProject(
		request: MessageInitShape<typeof GetProjectRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<Project> {
		const generated = create(GetProjectRequestSchema, request);
		if (generated.name !== projectName(this.#core))
			throw MindcladeError.invalidArgument("project name does not match client scope");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_PROJECT),
			undefined,
			(call) => this.#core.raw.admin.getProject(generated, call),
		);
		if (response.project === undefined)
			throw MindcladeError.protocol("GetProject response omitted its project");
		return response.project;
	}

	async listProjects(
		request: MessageInitShape<typeof ListProjectsRequestSchema> = {},
		options: SdkCallOptions = {},
	): Promise<ListProjectsResponse> {
		const generated = create(ListProjectsRequestSchema, request);
		const parent = tenantName(this.#core);
		if (generated.parent !== "" && generated.parent !== parent)
			throw MindcladeError.invalidArgument("project list parent does not match client scope");
		validatePage(generated.page?.pageSize);
		generated.parent = parent;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(LIST_PROJECTS),
			undefined,
			(call) => this.#core.raw.admin.listProjects(generated, call),
		);
	}

	async updateProject(
		request: MessageInitShape<typeof UpdateProjectRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(UpdateProjectRequestSchema, request);
		if (
			generated.project?.name !== projectName(this.#core) ||
			generated.updateMask === undefined ||
			generated.etag.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"project update requires the configured project, a field mask, and etag",
			);
		}
		delete generated.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		generated.context = commandContext(this.#core.config, prepared, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(UPDATE_PROJECT),
			options.idempotencyKey,
			(call) => this.#core.raw.admin.updateProject(generated, call),
		);
		return requiredOperation(response.operation, "UpdateProject");
	}

	async queryAudit(
		query: MessageInitShape<typeof AuditQuerySchema>,
		options: SdkCallOptions = {},
	): Promise<AuditQueryPage> {
		const generated = create(AuditQuerySchema, query);
		validateAuditQuery(this.#core, generated);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(QUERY_AUDIT),
			undefined,
			(call) =>
				this.#core.raw.admin.queryAuditRecords(
					create(QueryAuditRecordsRequestSchema, { query: generated }),
					call,
				),
		);
		if (response.result === undefined)
			throw MindcladeError.protocol("QueryAuditRecords response omitted its result");
		return response.result;
	}

	async exportAudit(
		query: MessageInitShape<typeof AuditQuerySchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const generated = create(AuditQuerySchema, query);
		validateAuditQuery(this.#core, generated);
		const request = create(ExportAuditRecordsRequestSchema, { query: generated });
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const context = commandContext(this.#core.config, prepared, options);
		if (generated.parent === tenantName(this.#core)) context.projectId = "";
		request.context = context;
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(EXPORT_AUDIT),
			options.idempotencyKey,
			(call) => this.#core.raw.admin.exportAuditRecords(request, call),
		);
		return requiredOperation(response.operation, "ExportAuditRecords");
	}

	async getAuditExport(
		request: MessageInitShape<typeof GetAuditExportRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<AuditExport> {
		const generated = create(GetAuditExportRequestSchema, request);
		generated.name = scopedProjectName(this.#core, generated.name, "auditExports");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_EXPORT),
			undefined,
			(call) => this.#core.raw.admin.getAuditExport(generated, call),
		);
		if (response.auditExport === undefined)
			throw MindcladeError.protocol("GetAuditExport response omitted its export");
		return response.auditExport;
	}
}

const tenantName = (core: ClientCore): string =>
	core.config.identity.tenantId.startsWith("tenants/")
		? core.config.identity.tenantId
		: `tenants/${core.config.identity.tenantId}`;

const projectName = (core: ClientCore): string => {
	const tenant = tenantName(core);
	const project = core.config.identity.projectId;
	if (project.startsWith("tenants/")) return project;
	return project.startsWith("projects/") ? `${tenant}/${project}` : `${tenant}/projects/${project}`;
};

const configuredProjectId = (core: ClientCore): string =>
	projectName(core).slice(projectName(core).lastIndexOf("/") + 1);

const tenantReference = (core: ClientCore): ResourceRef => {
	const name = tenantName(core);
	return create(ResourceRefSchema, {
		name,
		resourceId: name.slice(name.lastIndexOf("/") + 1),
		resourceType: "tenant",
		tenantId: core.config.identity.tenantId,
	});
};

const normalizeTenantReference = (core: ClientCore, reference: ResourceRef): void => {
	const expected = tenantReference(core);
	if (
		reference.name !== expected.name ||
		(reference.resourceType !== "" && reference.resourceType !== "tenant") ||
		(reference.resourceId !== "" && reference.resourceId !== expected.resourceId) ||
		(reference.tenantId !== "" && reference.tenantId !== core.config.identity.tenantId)
	) {
		throw MindcladeError.invalidArgument("tenant reference conflicts with client identity");
	}
	reference.name = expected.name;
	reference.resourceType = expected.resourceType;
	reference.resourceId = expected.resourceId;
	reference.tenantId = expected.tenantId;
	reference.projectId = "";
};

const scopedProjectName = (core: ClientCore, name: string, collection: string): string => {
	const prefix = `${projectName(core)}/${collection}/`;
	const id = name.startsWith(prefix) ? name.slice(prefix.length) : "";
	if (id === "" || id.includes("/"))
		throw MindcladeError.invalidArgument("resource is outside the configured project");
	return name;
};

const validatePage = (size: number | undefined): void => {
	if (size !== undefined && (!Number.isInteger(size) || size < 0 || size > 1000))
		throw MindcladeError.invalidArgument("page size must be an integer between zero and 1000");
};

const validateAuditQuery = (core: ClientCore, query: AuditQuery): void => {
	if (query.parent !== tenantName(core) && query.parent !== projectName(core))
		throw MindcladeError.invalidArgument("audit query parent does not match client scope");
	validatePage(query.page?.pageSize);
	if (query.startTime === undefined || query.endTime === undefined)
		throw MindcladeError.invalidArgument("audit query requires a bounded time range");
	if (
		query.endTime.seconds < query.startTime.seconds ||
		(query.endTime.seconds === query.startTime.seconds &&
			query.endTime.nanos <= query.startTime.nanos)
	) {
		throw MindcladeError.invalidArgument("audit query time range is invalid");
	}
	for (const resource of query.resources) normalizeProjectResource(core, resource);
};

const normalizeProjectResource = (core: ClientCore, resource: ResourceRef): void => {
	const parent = projectName(core);
	if (resource.name !== parent && !resource.name.startsWith(`${parent}/`))
		throw MindcladeError.invalidArgument("audit resource is outside the configured project");
	if (
		(resource.tenantId !== "" && resource.tenantId !== core.config.identity.tenantId) ||
		(resource.projectId !== "" && resource.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("audit resource conflicts with client identity");
	}
	resource.tenantId = core.config.identity.tenantId;
	resource.projectId = core.config.identity.projectId;
};

const requiredOperation = (operation: Operation | undefined, method: string): Operation => {
	if (operation === undefined || operation.operationId.trim() === "")
		throw MindcladeError.protocol(`${method} response omitted its durable operation`);
	return operation;
};
