import { createHash, timingSafeEqual } from "node:crypto";
import { clone, create, type MessageInitShape, toBinary } from "@bufbuild/protobuf";

import type { ResourceRef } from "../../../../protocols/generated/typescript/common/v1/resource_reference_pb.js";
import {
	ConsumeApprovalRequestSchema,
	DecideApprovalRequestSchema,
	GetApprovalRequestRequestSchema,
	ListApprovalRequestsRequestSchema,
	type ListApprovalRequestsResponse,
	RequestApprovalRequestSchema,
} from "../../../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";
import {
	ApprovalBindingSchema,
	ApprovalDecisionValue,
	type ApprovalReceipt,
	ApprovalReceiptSchema,
	type ApprovalRequest,
	ApprovalRequestSchema,
} from "../../../../protocols/generated/typescript/workflow/v1/approval_pb.js";
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

const REQUEST = "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval";
const GET = "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest";
const LIST = "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests";
const DECIDE = "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval";
const CONSUME = "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval";
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const RESOURCE_ID = /^[A-Za-z0-9._-]{1,128}$/;
const MAXIMUM_PAGE_SIZE = 200;

/** Exact-intent approval and immutable receipt facade over generated contracts. */
export class Approvals {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async request(
		input: MessageInitShape<typeof ApprovalRequestSchema>,
		options: SubmitOptions,
	): Promise<ApprovalRequest> {
		ensureUnfenced(options);
		const approval = create(ApprovalRequestSchema, input);
		if (approval.binding === undefined) {
			throw MindcladeError.invalidArgument("approval request requires a generated binding");
		}
		if (approval.name !== "") scopedName(this.#core, approval.name, "approvalRequests");
		normalizeScope(this.#core, approval);
		approval.requestedByPrincipalRef = this.#core.config.identity.principalId;
		if (approval.binding.tool !== undefined) normalizeReference(this.#core, approval.binding.tool);
		for (const decision of approval.policyDecisions) {
			if (decision.resource !== undefined) normalizeReference(this.#core, decision.resource);
		}
		verifyBinding(approval.binding);
		delete approval.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		approval.context = {
			...commandContext(this.#core.config, prepared, options),
			canonicalRequestDigest: sha256(toBinary(ApprovalRequestSchema, approval)),
		};
		const expectedBinding = approval.binding.bindingDigest;
		const response = await invokeUnary(
			this.#core,
			prepared,
			REQUEST,
			options.idempotencyKey,
			(call) =>
				this.#core.raw.approvals.requestApproval(
					create(RequestApprovalRequestSchema, { approvalRequest: approval }),
					call,
				),
		);
		if (response.approvalRequest === undefined) {
			throw MindcladeError.protocol("RequestApproval response omitted its request");
		}
		const created = clone(ApprovalRequestSchema, response.approvalRequest);
		scopedName(this.#core, created.name, "approvalRequests");
		if (
			created.binding === undefined ||
			!safeEqual(created.binding.bindingDigest, expectedBinding)
		) {
			throw MindcladeError.protocol("RequestApproval returned inconsistent durable intent");
		}
		return created;
	}

	async get(name: string, options: SdkCallOptions = {}): Promise<ApprovalRequest> {
		ensureUnfenced(options);
		const request = create(GetApprovalRequestRequestSchema, {
			name: scopedName(this.#core, name, "approvalRequests"),
		});
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET,
			undefined,
			(call) => this.#core.raw.approvals.getApprovalRequest(request, call),
		);
		if (response.approvalRequest === undefined) {
			throw MindcladeError.protocol("GetApprovalRequest response omitted its request");
		}
		return clone(ApprovalRequestSchema, response.approvalRequest);
	}

	/** Returns the first page, which also iterates the whole cursor. */
	async list(
		input: MessageInitShape<typeof ListApprovalRequestsRequestSchema> = {},
		options: ListOptions = {},
	): Promise<Page<ApprovalRequest, ListApprovalRequestsResponse>> {
		ensureUnfenced(options);
		const request = create(ListApprovalRequestsRequestSchema, input);
		request.parent = normalizeParent(this.#core, request.parent);
		if (
			request.page !== undefined &&
			(!Number.isInteger(request.page.pageSize) ||
				request.page.pageSize < 0 ||
				request.page.pageSize > MAXIMUM_PAGE_SIZE)
		) {
			throw MindcladeError.invalidArgument(
				"approval page size must be an integer between zero and 200",
			);
		}
		return await listPage({
			cursor: (response) => response.page?.nextPageToken ?? "",
			fetch: async (pageToken) => {
				const paged = withPageToken(ListApprovalRequestsRequestSchema, request, pageToken);
				const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
				const response = await invokeUnary(
					this.#core,
					prepared,
					LIST,
					undefined,
					(call) => this.#core.raw.approvals.listApprovalRequests(paged, call),
				);
				return { requestId: prepared.requestId, response };
			},
			items: (response) => response.approvalRequests,
			limits: options.limits,
			pageSize: request.page?.pageSize ?? 0,
			pageToken: request.page?.pageToken ?? "",
			signal: options.signal,
		});
	}

	async decide(
		input: MessageInitShape<typeof DecideApprovalRequestSchema>,
		options: SubmitOptions,
	): Promise<ApprovalReceipt> {
		ensureUnfenced(options);
		const request = create(DecideApprovalRequestSchema, input);
		request.name = scopedName(this.#core, request.name, "approvalRequests");
		if (
			request.etag.trim() === "" ||
			request.decision === ApprovalDecisionValue.UNSPECIFIED ||
			request.reasonCode.trim() === "" ||
			request.safeReason.length > 2048
		) {
			throw MindcladeError.invalidArgument(
				"approval decision requires an ETag, decision, reason code, and bounded safe reason",
			);
		}
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = {
			...commandContext(this.#core.config, prepared, options),
			canonicalRequestDigest: sha256(toBinary(DecideApprovalRequestSchema, request)),
		};
		const response = await invokeUnary(
			this.#core,
			prepared,
			DECIDE,
			options.idempotencyKey,
			(call) => this.#core.raw.approvals.decideApproval(request, call),
		);
		return validateDecisionReceipt(this.#core, request, response.approvalReceipt);
	}

	async consume(
		input: MessageInitShape<typeof ConsumeApprovalRequestSchema>,
		options: SubmitOptions,
	): Promise<ApprovalReceipt> {
		ensureUnfenced(options);
		const request = create(ConsumeApprovalRequestSchema, input);
		request.receiptName = scopedName(this.#core, request.receiptName, "approvalReceipts");
		if (
			!SHA256.test(request.bindingDigest) ||
			request.callId.trim() === "" ||
			request.callId.length > 1024
		) {
			throw MindcladeError.invalidArgument(
				"approval consumption requires a binding digest and bounded call ID",
			);
		}
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = {
			...commandContext(this.#core.config, prepared, options),
			canonicalRequestDigest: sha256(toBinary(ConsumeApprovalRequestSchema, request)),
		};
		const response = await invokeUnary(
			this.#core,
			prepared,
			CONSUME,
			options.idempotencyKey,
			(call) => this.#core.raw.approvals.consumeApproval(request, call),
		);
		const receipt = response.approvalReceipt;
		if (
			receipt === undefined ||
			receipt.name !== request.receiptName ||
			receipt.consumedAt === undefined ||
			receipt.consumedByCallId !== request.callId ||
			receipt.binding === undefined ||
			!safeEqual(receipt.binding.bindingDigest, request.bindingDigest) ||
			!SHA256.test(receipt.receiptDigest)
		) {
			throw MindcladeError.protocol("ConsumeApproval returned an inconsistent receipt");
		}
		return clone(ApprovalReceiptSchema, receipt);
	}
}

const verifyBinding = (binding: ReturnType<typeof create<typeof ApprovalBindingSchema>>): void => {
	if (
		!SHA256.test(binding.intentDigest) ||
		!SHA256.test(binding.parametersDigest) ||
		!SHA256.test(binding.bindingDigest)
	) {
		throw MindcladeError.invalidArgument("approval binding requires canonical SHA-256 digests");
	}
	const unsigned = clone(ApprovalBindingSchema, binding);
	const supplied = unsigned.bindingDigest;
	unsigned.bindingDigest = "";
	if (!safeEqual(supplied, sha256(toBinary(ApprovalBindingSchema, unsigned)))) {
		throw MindcladeError.invalidArgument(
			"approval binding digest does not match its generated payload",
		);
	}
};

const validateDecisionReceipt = (
	core: ClientCore,
	request: ReturnType<typeof create<typeof DecideApprovalRequestSchema>>,
	receipt: ApprovalReceipt | undefined,
): ApprovalReceipt => {
	if (
		receipt === undefined ||
		receipt.request === undefined ||
		receipt.binding === undefined ||
		receipt.decidedAt === undefined ||
		receipt.request.name !== request.name ||
		receipt.decision !== request.decision ||
		receipt.reasonCode !== request.reasonCode ||
		receipt.safeReason !== request.safeReason ||
		!SHA256.test(receipt.receiptDigest)
	) {
		throw MindcladeError.protocol("DecideApproval returned an inconsistent receipt");
	}
	scopedName(core, receipt.name, "approvalReceipts");
	normalizeReference(core, receipt.request, "approval_request", "approvalRequests");
	return clone(ApprovalReceiptSchema, receipt);
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
		throw MindcladeError.invalidArgument("approval reference ID does not match its name");
	}
	if (expectedType !== undefined) {
		if (reference.resourceType !== "" && reference.resourceType !== expectedType) {
			throw MindcladeError.invalidArgument("approval reference type does not match its use");
		}
		reference.resourceType = expectedType;
	} else if (reference.resourceType.trim() === "") {
		throw MindcladeError.invalidArgument("approval reference type is required");
	}
	reference.resourceId = resourceId;
	normalizeScope(core, reference);
};

const normalizeScope = (core: ClientCore, value: { tenantId: string; projectId: string }): void => {
	if (
		(value.tenantId !== "" && value.tenantId !== core.config.identity.tenantId) ||
		(value.projectId !== "" && value.projectId !== core.config.identity.projectId)
	) {
		throw MindcladeError.invalidArgument("approval resource scope conflicts with client identity");
	}
	value.tenantId = core.config.identity.tenantId;
	value.projectId = core.config.identity.projectId;
};

const normalizeParent = (core: ClientCore, parent: string): string => {
	const expected = projectName(core);
	if (parent !== "" && parent !== expected) {
		throw MindcladeError.invalidArgument("approval parent does not match client scope");
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
	const relative = name.startsWith(prefix) ? name.slice(prefix.length) : "";
	const parts = relative.split("/");
	if (parts.length !== 2 || !RESOURCE_ID.test(parts[1] ?? "")) {
		throw MindcladeError.invalidArgument("approval reference is outside client scope");
	}
	return name;
};

const ensureUnfenced = (options: SdkCallOptions): void => {
	if (options.leaseToken !== undefined || options.workerId !== undefined) {
		throw MindcladeError.invalidArgument(
			"worker and lease credentials are not accepted by approval RPCs",
		);
	}
};

const safeEqual = (left: string, right: string): boolean => {
	const first = Buffer.from(left, "utf8");
	const second = Buffer.from(right, "utf8");
	return first.length === second.length && timingSafeEqual(first, second);
};

const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;
