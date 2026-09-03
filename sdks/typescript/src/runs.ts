import { createHash, timingSafeEqual } from "node:crypto";
import {
	clone,
	create,
	type DescMessage,
	type MessageInitShape,
	type MessageShape,
} from "@bufbuild/protobuf";
import { timestampDate } from "@bufbuild/protobuf/wkt";

import {
	AcquireAttemptLeaseRequestSchema,
	CancelAttemptRequestSchema,
	type CancelAttemptResponse,
	CancelAttemptResponseSchema,
	CommitAttemptRequestSchema,
	type CommitAttemptResponse,
	CommitAttemptResponseSchema,
	GetAttemptRequestSchema,
	GetRunRequestSchema,
	HeartbeatAttemptRequestSchema,
	type HeartbeatAttemptResponse,
	HeartbeatAttemptResponseSchema,
	ListAttemptsRequestSchema,
	type ListAttemptsResponse,
	ListAttemptsResponseSchema,
	ListRunsRequestSchema,
	type ListRunsResponse,
	ListRunsResponseSchema,
	RenewAttemptLeaseRequestSchema,
} from "../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import type { Attempt } from "../../../protocols/generated/typescript/job/v1/attempt_pb.js";
import { AttemptSchema } from "../../../protocols/generated/typescript/job/v1/attempt_pb.js";
import type { LeaseFence } from "../../../protocols/generated/typescript/job/v1/lease_fencing_pb.js";
import { LeaseFenceSchema } from "../../../protocols/generated/typescript/job/v1/lease_fencing_pb.js";
import type { Run } from "../../../protocols/generated/typescript/job/v1/run_pb.js";
import { RunSchema } from "../../../protocols/generated/typescript/job/v1/run_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { digestContext, leaf, resource, resourceId } from "./jobs.js";
import { prepareCall, type SdkCallOptions, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const routes = {
	getRun: "/mindclade.internal.job.v1.RunService/GetRun",
	listRuns: "/mindclade.internal.job.v1.RunService/ListRuns",
	getAttempt: "/mindclade.internal.job.v1.RunService/GetAttempt",
	listAttempts: "/mindclade.internal.job.v1.RunService/ListAttempts",
	acquire: "/mindclade.internal.job.v1.RunService/AcquireAttemptLease",
	renew: "/mindclade.internal.job.v1.RunService/RenewAttemptLease",
	heartbeat: "/mindclade.internal.job.v1.RunService/HeartbeatAttempt",
	cancel: "/mindclade.internal.job.v1.RunService/CancelAttempt",
	commit: "/mindclade.internal.job.v1.RunService/CommitAttempt",
} as const;
const secrets = new WeakMap<LeaseCredential, string>();
const leaseAuthority = Symbol("mindclade lease credential authority");

/** Redacting, non-serializable capability handle. */
export class LeaseCredential {
	constructor(token: string, authority: symbol) {
		if (authority !== leaseAuthority)
			throw MindcladeError.invalidArgument("lease credentials are issued only by acquire");
		if (!/^[\x21-\x7e]{32,4096}$/.test(token))
			throw MindcladeError.protocol("lease credential metadata was invalid");
		secrets.set(this, token);
	}
	toString(): string {
		return "LeaseCredential(<redacted>)";
	}
	toJSON(): string {
		return "LeaseCredential(<redacted>)";
	}
}

export class AttemptLease {
	readonly #attempt: Attempt;
	readonly #fence: LeaseFence;
	readonly credential: LeaseCredential;
	constructor(attempt: Attempt, fence: LeaseFence, credential: LeaseCredential) {
		this.#attempt = clone(AttemptSchema, attempt);
		this.#fence = clone(LeaseFenceSchema, fence);
		this.credential = credential;
	}
	get attempt(): Attempt {
		return clone(AttemptSchema, this.#attempt);
	}
	get fence(): LeaseFence {
		return clone(LeaseFenceSchema, this.#fence);
	}
}

/** Generated Run/Attempt lifecycle and fenced-worker facade. */
export class Runs {
	readonly #core: ClientCore;
	constructor(core: ClientCore) {
		this.#core = core;
	}

	async getRun(name: string, options: SdkCallOptions = {}): Promise<Run> {
		const canonical = resource(this.#core, name, "runs");
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.getRun),
			undefined,
			(o) => this.#core.raw.runs.getRun(create(GetRunRequestSchema, { name: canonical }), o),
		);
		if (
			response.run === undefined ||
			response.run.runId !== canonical ||
			!validRun(this.#core, response.run)
		)
			throw MindcladeError.protocol("GetRun response violated durable identity");
		return clone(RunSchema, response.run);
	}

	async listRuns(
		input: MessageInitShape<typeof ListRunsRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<ListRunsResponse> {
		const request = clone(ListRunsRequestSchema, create(ListRunsRequestSchema, input));
		request.parent = resource(this.#core, request.parent, "jobs");
		const pageSize = request.page?.pageSize ?? 0;
		if (
			!Number.isInteger(pageSize) ||
			pageSize < 0 ||
			pageSize > 200 ||
			request.filter.trim() !== ""
		)
			throw MindcladeError.invalidArgument("run list page or filter is invalid");
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.listRuns),
			undefined,
			(o) => this.#core.raw.runs.listRuns(request, o),
		);
		if (
			response.runs.some((value) => !validRun(this.#core, value) || value.jobId !== request.parent)
		)
			throw MindcladeError.protocol("ListRuns response violated durable identity");
		return clone(ListRunsResponseSchema, response);
	}

	async getAttempt(name: string, options: SdkCallOptions = {}): Promise<Attempt> {
		const canonical = resource(this.#core, name, "attempts");
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.getAttempt),
			undefined,
			(o) =>
				this.#core.raw.runs.getAttempt(create(GetAttemptRequestSchema, { name: canonical }), o),
		);
		if (
			response.attempt === undefined ||
			response.attempt.attemptId !== canonical ||
			!validAttempt(this.#core, response.attempt)
		)
			throw MindcladeError.protocol("GetAttempt response violated durable identity");
		return clone(AttemptSchema, response.attempt);
	}

	async listAttempts(
		input: MessageInitShape<typeof ListAttemptsRequestSchema>,
		options: SdkCallOptions = {},
	): Promise<ListAttemptsResponse> {
		const request = clone(ListAttemptsRequestSchema, create(ListAttemptsRequestSchema, input));
		request.parent = resource(this.#core, request.parent, "runs");
		const pageSize = request.page?.pageSize ?? 0;
		if (!Number.isInteger(pageSize) || pageSize < 0 || pageSize > 200)
			throw MindcladeError.invalidArgument(
				"attempt page size must be an integer between zero and 200",
			);
		const call = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.listAttempts),
			undefined,
			(o) => this.#core.raw.runs.listAttempts(request, o),
		);
		if (
			response.attempts.some(
				(value) => !validAttempt(this.#core, value) || value.runId !== request.parent,
			)
		)
			throw MindcladeError.protocol("ListAttempts response violated durable identity");
		return clone(ListAttemptsResponseSchema, response);
	}

	async acquire(
		input: MessageInitShape<typeof AcquireAttemptLeaseRequestSchema>,
		options: SubmitOptions,
	): Promise<AttemptLease> {
		const request = clone(
			AcquireAttemptLeaseRequestSchema,
			create(AcquireAttemptLeaseRequestSchema, input),
		);
		request.runName = resource(this.#core, request.runName, "runs");
		if (!leaf(request.attemptId) || !validDuration(request.leaseDuration))
			throw MindcladeError.invalidArgument(
				"lease acquisition requires attempt ID and duration from 5 seconds through 15 minutes",
			);
		delete request.context;
		const { leaseToken: ignoredLeaseToken, ...credentialFreeOptions } = options;
		void ignoredLeaseToken;
		const call = prepareCall(this.#core.config, this.#core.runtime, credentialFreeOptions);
		request.context = digestContext(
			this.#core,
			call,
			options,
			AcquireAttemptLeaseRequestSchema,
			request,
		);
		let responseHeaders: Headers | undefined;
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.acquire),
			options.idempotencyKey,
			(o) =>
				this.#core.raw.runs.acquireAttemptLease(request, {
					...o,
					onHeader: (headers) => {
						responseHeaders = headers;
					},
				}),
		);
		const token = responseHeaders?.get("x-mindclade-lease-token") ?? "";
		const credential = captureLeaseCredential(token);
		if (
			response.attempt === undefined ||
			response.fence === undefined ||
			!validLease(this.#core, response.attempt, response.fence) ||
			!tokenMatches(token, response.fence)
		)
			throw MindcladeError.protocol("AcquireAttemptLease response violated lease authority");
		return new AttemptLease(response.attempt, response.fence, credential);
	}

	async renew(
		input: MessageInitShape<typeof RenewAttemptLeaseRequestSchema>,
		credential: LeaseCredential,
		options: SubmitOptions,
	): Promise<AttemptLease> {
		const [request, call, token] = this.#fenced(
			RenewAttemptLeaseRequestSchema,
			input,
			credential,
			options,
			true,
		);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.renew),
			options.idempotencyKey,
			(o) => this.#core.raw.runs.renewAttemptLease(request, o),
		);
		if (
			response.attempt === undefined ||
			response.fence === undefined ||
			!validLease(this.#core, response.attempt, response.fence) ||
			!tokenMatches(token, response.fence)
		)
			throw MindcladeError.protocol("RenewAttemptLease response violated lease authority");
		return new AttemptLease(response.attempt, response.fence, credential);
	}

	async heartbeat(
		input: MessageInitShape<typeof HeartbeatAttemptRequestSchema>,
		credential: LeaseCredential,
		options: SubmitOptions,
	): Promise<HeartbeatAttemptResponse> {
		const [request, call, token] = this.#fenced(
			HeartbeatAttemptRequestSchema,
			input,
			credential,
			options,
			true,
		);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.heartbeat),
			options.idempotencyKey,
			(o) => this.#core.raw.runs.heartbeatAttempt(request, o),
		);
		if (
			response.observedAt === undefined ||
			response.attempt === undefined ||
			response.fence === undefined ||
			!validLease(this.#core, response.attempt, response.fence) ||
			!tokenMatches(token, response.fence)
		)
			throw MindcladeError.protocol("HeartbeatAttempt response violated lease authority");
		return clone(HeartbeatAttemptResponseSchema, response);
	}

	async cancelAttempt(
		input: MessageInitShape<typeof CancelAttemptRequestSchema>,
		credential: LeaseCredential,
		options: SubmitOptions,
	): Promise<CancelAttemptResponse> {
		const [request, call] = this.#fenced(
			CancelAttemptRequestSchema,
			input,
			credential,
			options,
			false,
		);
		if (request.reason.length > 1024 || request.reason.includes("\0"))
			throw MindcladeError.invalidArgument("attempt cancellation reason is invalid");
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.cancel),
			options.idempotencyKey,
			(o) => this.#core.raw.runs.cancelAttempt(request, o),
		);
		if (
			response.attempt === undefined ||
			response.run === undefined ||
			!validAttempt(this.#core, response.attempt) ||
			!validRun(this.#core, response.run) ||
			response.attempt.runId !== response.run.runId ||
			response.attempt.jobId !== response.run.jobId
		)
			throw MindcladeError.protocol("CancelAttempt response violated durable identity");
		return clone(CancelAttemptResponseSchema, response);
	}

	async commitAttempt(
		input: MessageInitShape<typeof CommitAttemptRequestSchema>,
		credential: LeaseCredential,
		options: SubmitOptions,
	): Promise<CommitAttemptResponse> {
		const [request, call] = this.#fenced(
			CommitAttemptRequestSchema,
			input,
			credential,
			options,
			false,
		);
		if (
			request.attempt === undefined ||
			!validAttempt(this.#core, request.attempt) ||
			request.updateMask === undefined ||
			!validMask(request.updateMask.paths) ||
			request.attempt.attemptId !== request.fence?.attemptId ||
			request.attempt.runId !== request.fence.runId ||
			request.attempt.leaseEpoch !== request.fence.leaseEpoch
		)
			throw MindcladeError.invalidArgument(
				"attempt commit does not match current fence or update mask",
			);
		const response = await invokeUnary(
			this.#core,
			call,
			registeredMethodSafety(routes.commit),
			options.idempotencyKey,
			(o) => this.#core.raw.runs.commitAttempt(request, o),
		);
		if (
			response.attempt === undefined ||
			response.run === undefined ||
			!validAttempt(this.#core, response.attempt) ||
			!validRun(this.#core, response.run) ||
			response.attempt.runId !== response.run.runId ||
			response.attempt.jobId !== response.run.jobId
		)
			throw MindcladeError.protocol("CommitAttempt response violated durable identity");
		return clone(CommitAttemptResponseSchema, response);
	}

	#fenced<Schema extends DescMessage>(
		schema: Schema,
		input: MessageInitShape<Schema>,
		credential: LeaseCredential,
		options: SubmitOptions,
		durationRequired: boolean,
	): readonly [MessageShape<Schema>, ReturnType<typeof prepareCall>, string] {
		const token = secrets.get(credential);
		if (token === undefined)
			throw MindcladeError.invalidArgument("a valid lease credential handle is required");
		const request = clone(schema, create(schema, input));
		const typed = request as unknown as {
			context?: unknown;
			fence?: LeaseFence;
			leaseDuration?: { seconds: bigint; nanos: number };
			expectedResourceVersion: bigint;
		};
		if (
			typed.expectedResourceVersion < 1n ||
			typed.fence === undefined ||
			(durationRequired && !validDuration(typed.leaseDuration))
		)
			throw MindcladeError.invalidArgument(
				"fenced mutation requires revision, fence, and bounded duration",
			);
		normalizeFence(this.#core, typed.fence);
		delete typed.context;
		const call = prepareCall(this.#core.config, this.#core.runtime, {
			...options,
			leaseToken: token,
		});
		typed.context = digestContext(this.#core, call, options, schema, request);
		return [request, call, token];
	}
}

const validDuration = (value: { seconds: bigint; nanos: number } | undefined): boolean => {
	if (value === undefined || value.nanos < 0 || value.nanos >= 1_000_000_000) return false;
	const nanos = value.seconds * 1_000_000_000n + BigInt(value.nanos);
	return nanos >= 5_000_000_000n && nanos <= 900_000_000_000n;
};
const validRun = (core: ClientCore, value: Run): boolean =>
	value.tenantId === core.config.identity.tenantId &&
	value.projectId === core.config.identity.projectId &&
	resourceId(value.runId, "runs") &&
	resourceId(value.jobId, "jobs") &&
	value.resourceVersion > 0n &&
	value.state !== 0;
const validAttempt = (core: ClientCore, value: Attempt): boolean =>
	value.tenantId === core.config.identity.tenantId &&
	value.projectId === core.config.identity.projectId &&
	resourceId(value.attemptId, "attempts") &&
	resourceId(value.runId, "runs") &&
	resourceId(value.jobId, "jobs") &&
	value.leaseEpoch > 0n &&
	value.resourceVersion > 0n &&
	value.state !== 0;
const normalizeFence = (core: ClientCore, value: LeaseFence): void => {
	if (
		!resourceId(value.jobId, "jobs") ||
		!resourceId(value.runId, "runs") ||
		!resourceId(value.attemptId, "attempts") ||
		value.leaseEpoch < 1n ||
		!futureTimestamp(core, value.deadline) ||
		!/^sha256:[0-9a-f]{64}$/.test(value.leaseTokenDigest) ||
		!["", core.config.identity.tenantId].includes(value.tenantId) ||
		!["", core.config.identity.projectId].includes(value.projectId)
	)
		throw MindcladeError.invalidArgument("current scoped lease fence is required");
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};
const validLease = (core: ClientCore, attempt: Attempt, fence: LeaseFence): boolean =>
	validAttempt(core, attempt) &&
	fence.tenantId === core.config.identity.tenantId &&
	fence.projectId === core.config.identity.projectId &&
	attempt.jobId === fence.jobId &&
	attempt.runId === fence.runId &&
	attempt.attemptId === fence.attemptId &&
	attempt.leaseEpoch === fence.leaseEpoch &&
	futureTimestamp(core, fence.deadline) &&
	/^sha256:[0-9a-f]{64}$/.test(fence.leaseTokenDigest);
const futureTimestamp = (core: ClientCore, value: LeaseFence["deadline"]): boolean => {
	if (value === undefined) return false;
	try {
		return timestampDate(value).getTime() > core.runtime.nowMs();
	} catch {
		return false;
	}
};
const tokenMatches = (token: string, fence: LeaseFence): boolean => {
	const actual = Buffer.from(`sha256:${createHash("sha256").update(token).digest("hex")}`);
	const expected = Buffer.from(fence.leaseTokenDigest);
	return actual.length === expected.length && timingSafeEqual(actual, expected);
};
const captureLeaseCredential = (token: string): LeaseCredential =>
	new LeaseCredential(token, leaseAuthority);
const validMask = (paths: readonly string[]): boolean =>
	paths.length > 0 &&
	paths.length <= 3 &&
	paths.includes("state") &&
	new Set(paths).size === paths.length &&
	paths.every((value) => ["state", "outputs", "error"].includes(value));
