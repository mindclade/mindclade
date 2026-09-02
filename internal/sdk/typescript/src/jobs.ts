import { createHash } from "node:crypto";
import {
	clone,
	create,
	type DescMessage,
	type MessageInitShape,
	type MessageShape,
	toBinary,
} from "@bufbuild/protobuf";

import {
	CancelJobRequestSchema,
	GetJobRequestSchema,
	ListJobsRequestSchema,
	type ListJobsResponse,
	ListJobsResponseSchema,
	RequestJobRequestSchema,
} from "../../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { RequestJobCommandSchema } from "../../../../protocols/generated/typescript/job/v1/job_commands_pb.js";
import type { Job } from "../../../../protocols/generated/typescript/job/v1/job_pb.js";
import { JobSchema } from "../../../../protocols/generated/typescript/job/v1/job_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import { OperationSchema } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
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

const REQUEST = "/mindclade.internal.job.v1.JobService/RequestJob";
const GET = "/mindclade.internal.job.v1.JobService/GetJob";
const LIST = "/mindclade.internal.job.v1.JobService/ListJobs";
const CANCEL = "/mindclade.internal.job.v1.JobService/CancelJob";
const DIGEST = /^sha256:[0-9a-f]{64}$/;

/** Durable-job facade over authoritative generated JobService types. */
export class Jobs {
	readonly #core: ClientCore;
	constructor(core: ClientCore) {
		this.#core = core;
	}

	async request(
		input: MessageInitShape<typeof RequestJobCommandSchema>,
		options: SubmitOptions,
	): Promise<readonly [Job, Operation]> {
		const command = clone(RequestJobCommandSchema, create(RequestJobCommandSchema, input));
		if (
			!leaf(command.jobKind) ||
			!artifact(command.configuration) ||
			(command.input !== undefined && !artifact(command.input)) ||
			(command.requestedJobId !== "" && !leaf(command.requestedJobId))
		) {
			throw MindcladeError.invalidArgument(
				"job request requires valid kind, optional ID, and content-addressed configuration",
			);
		}
		delete command.context;
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		command.context = digestContext(this.#core, call, options, RequestJobCommandSchema, command);
		const response = await invokeUnary(
			this.#core,
			call,
			REQUEST,
			options.idempotencyKey,
			(callOptions) =>
				this.#core.raw.jobs.requestJob(create(RequestJobRequestSchema, { command }), callOptions),
		);
		if (
			response.job === undefined ||
			response.operation === undefined ||
			!validJob(this.#core, response.job) ||
			!validOperation(this.#core, response.operation) ||
			response.job.operationId !== response.operation.operationId ||
			response.operation.jobId !== response.job.jobId
		) {
			throw MindcladeError.protocol("RequestJob response violated durable identity");
		}
		return [clone(JobSchema, response.job), clone(OperationSchema, response.operation)];
	}

	async get(name: string, ifNoneMatch = "", options: SdkCallOptions = {}): Promise<Job> {
		const canonical = resource(this.#core, name, "jobs");
		if (ifNoneMatch.length > 512 || /[\0\r\n]/.test(ifNoneMatch))
			throw MindcladeError.invalidArgument("job cache validator is invalid");
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			call,
			GET,
			undefined,
			(callOptions) =>
				this.#core.raw.jobs.getJob(
					create(GetJobRequestSchema, { name: canonical, ifNoneMatch }),
					callOptions,
				),
		);
		if (
			response.job === undefined ||
			response.job.jobId !== canonical ||
			!validJob(this.#core, response.job)
		)
			throw MindcladeError.protocol("GetJob response violated durable identity");
		return clone(JobSchema, response.job);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async list(
		input: MessageInitShape<typeof ListJobsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<Job, ListJobsResponse>> {
		const request = clone(ListJobsRequestSchema, create(ListJobsRequestSchema, input));
		const parent = project(this.#core);
		const pageSize = request.page?.pageSize ?? 0;
		if (
			(request.parent !== "" && request.parent !== parent) ||
			!Number.isInteger(pageSize) ||
			pageSize < 0 ||
			pageSize > 200 ||
			request.filter.trim() !== "" ||
			!["", "job_id"].includes(request.orderBy)
		)
			throw MindcladeError.invalidArgument("job list scope, page, filter, or order is invalid");
		request.parent = parent;
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListJobsRequestSchema, request, pageToken);
				const call = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					call,
					LIST,
					undefined,
					(callOptions) => this.#core.raw.jobs.listJobs(paged, callOptions),
				);
				if (response.jobs.some((value) => !validJob(this.#core, value)))
					throw MindcladeError.protocol("ListJobs response escaped configured scope");
				return { requestId: call.requestId, response: clone(ListJobsResponseSchema, response) };
			},
			items: (response) => response.jobs,
			limits: options.limits,
			pageSize,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async cancel(
		input: MessageInitShape<typeof CancelJobRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const request = clone(CancelJobRequestSchema, create(CancelJobRequestSchema, input));
		request.name = resource(this.#core, request.name, "jobs");
		if (
			request.etag.trim() === "" ||
			request.etag.length > 512 ||
			/[\0\r\n]/.test(request.etag) ||
			request.reason.length > 4096 ||
			request.reason.includes("\0")
		)
			throw MindcladeError.invalidArgument(
				"job cancellation requires a valid ETag and bounded reason",
			);
		delete request.context;
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = digestContext(this.#core, call, options, CancelJobRequestSchema, request);
		const response = await invokeUnary(
			this.#core,
			call,
			CANCEL,
			options.idempotencyKey,
			(callOptions) => this.#core.raw.jobs.cancelJob(request, callOptions),
		);
		if (
			response.operation === undefined ||
			response.operation.jobId !== request.name ||
			!validOperation(this.#core, response.operation)
		)
			throw MindcladeError.protocol("CancelJob response violated durable identity");
		return clone(OperationSchema, response.operation);
	}
}

export const project = (core: ClientCore): string =>
	`tenants/${core.config.identity.tenantId.replace(/^tenants\//, "")}/projects/${core.config.identity.projectId.replace(/^projects\//, "")}`;
export const resource = (core: ClientCore, input: string, collection: string): string => {
	const value = input.trim();
	if (leaf(value)) return `${collection}/${value}`;
	const compact = new RegExp(`^${collection}/([^/]+)$`).exec(value);
	if (compact !== null && leaf(compact[1] ?? "")) return value;
	const prefix = `${project(core)}/${collection}/`;
	if (value.startsWith(prefix) && leaf(value.slice(prefix.length)))
		return `${collection}/${value.slice(prefix.length)}`;
	throw MindcladeError.invalidArgument(`${collection} resource is outside configured scope`);
};
export const leaf = (value: string): boolean => /^[A-Za-z0-9_.-]{1,255}$/.test(value.trim());
const artifact = (value: { digest: string; mediaType: string } | undefined): boolean =>
	value !== undefined && DIGEST.test(value.digest) && value.mediaType.trim() !== "";
const validJob = (core: ClientCore, value: Job): boolean =>
	value.tenantId === core.config.identity.tenantId &&
	value.projectId === core.config.identity.projectId &&
	resourceId(value.jobId, "jobs") &&
	resourceId(value.operationId, "operations") &&
	value.resourceVersion > 0n &&
	value.state !== 0;
const validOperation = (core: ClientCore, value: Operation): boolean =>
	value.tenantId === core.config.identity.tenantId &&
	value.projectId === core.config.identity.projectId &&
	resourceId(value.operationId, "operations") &&
	value.resourceVersion > 0n &&
	value.state !== 0;
export const resourceId = (value: string, collection: string): boolean =>
	new RegExp(`^${collection}/[A-Za-z0-9_.-]{1,255}$`).test(value);
export const digestContext = <Schema extends DescMessage>(
	core: ClientCore,
	call: ReturnType<typeof prepareCall>,
	options: SubmitOptions,
	schema: Schema,
	request: MessageShape<Schema>,
) => {
	const context = commandContext(core.config, call, options);
	context.canonicalRequestDigest = `sha256:${createHash("sha256").update(toBinary(schema, request)).digest("hex")}`;
	return context;
};
