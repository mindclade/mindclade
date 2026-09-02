import { createHash } from "node:crypto";
import { clone, create, type MessageInitShape, toBinary } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";

import {
	type InferenceRequest,
	InferenceRequestSchema,
} from "../../../../protocols/generated/typescript/inference/v1/inference_request_pb.js";
import {
	type InferenceResult,
	InferenceResultSchema,
} from "../../../../protocols/generated/typescript/inference/v1/inference_result_pb.js";
import {
	type InferenceStreamCursor,
	InferenceStreamCursorSchema,
	type InferenceStreamMessage,
	InferenceStreamMessageSchema,
} from "../../../../protocols/generated/typescript/inference/v1/inference_stream_pb.js";
import {
	CommitInferenceResultRequestSchema,
	GetInferenceRequestRequestSchema,
	GetInferenceResultRequestSchema,
	SubmitInferenceRequestSchema,
	WatchInferenceRequestSchema,
} from "../../../../protocols/generated/typescript/internal/inference/v1/inference_service_pb.js";
import {
	type Operation,
	OperationSchema,
} from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import {
	commandContext,
	type PreparedCall,
	prepareCall,
	type SdkCallOptions,
	type SubmitOptions,
	validateDuration,
	validateResource,
	type WaitOptions,
} from "./request.js";
import { invokeUnary } from "./retry.js";
import { DEFAULT_WAIT_TIMEOUT_MS, watchStream, type WatchSource } from "./watch.js";

const SUBMIT = "/mindclade.internal.inference.v1.InferenceService/SubmitInference";
const GET_REQUEST = "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest";
const GET_RESULT = "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult";
const COMMIT_RESULT = "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult";
const WATCH = "/mindclade.internal.inference.v1.InferenceService/WatchInference";

/** Generated-type-only bounded inference façade. */
export class Inference {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	/** Submits immutable generated inference intent. Authenticated tenant,
	 * project, principal, deadline, and canonical digest replace caller values. */
	async submit(
		input: MessageInitShape<typeof InferenceRequestSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const requestValue = create(InferenceRequestSchema, input);
		validateRequired("inference request name", requestValue.name);
		delete requestValue.context;
		requestValue.tenantId = this.#core.config.identity.tenantId;
		requestValue.projectId = this.#core.config.identity.projectId;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		requestValue.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(InferenceRequestSchema, requestValue)),
		);
		const request = create(SubmitInferenceRequestSchema, { inferenceRequest: requestValue });
		const response = await invokeUnary(
			this.#core,
			prepared,
			SUBMIT,
			options.idempotencyKey,
			(call) => this.#core.raw.inference.submitInference(request, call),
		);
		if (response.operation === undefined) {
			throw MindcladeError.protocol("SubmitInference response omitted its durable operation");
		}
		validateRequired("inference operation", response.operation.operationId);
		return clone(OperationSchema, response.operation);
	}

	/** Reads frozen admitted inference intent. */
	async getRequest(name: string, options: SdkCallOptions = {}): Promise<InferenceRequest> {
		validateRequired("inference request name", name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(GetInferenceRequestRequestSchema, { name });
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET_REQUEST,
			undefined,
			(call) => this.#core.raw.inference.getInferenceRequest(request, call),
		);
		if (response.inferenceRequest === undefined) {
			throw MindcladeError.protocol("GetInferenceRequest response omitted its request");
		}
		return clone(InferenceRequestSchema, response.inferenceRequest);
	}

	/** Reads immutable terminal result and its durable operation. */
	async getResult(
		operationName: string,
		options: SdkCallOptions = {},
	): Promise<readonly [InferenceResult, Operation]> {
		validateRequired("inference operation name", operationName);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(GetInferenceResultRequestSchema, { operationName });
		const response = await invokeUnary(
			this.#core,
			prepared,
			GET_RESULT,
			undefined,
			(call) => this.#core.raw.inference.getInferenceResult(request, call),
		);
		if (response.result === undefined || response.operation === undefined) {
			throw MindcladeError.protocol("GetInferenceResult response omitted its result or operation");
		}
		return [
			clone(InferenceResultSchema, response.result),
			clone(OperationSchema, response.operation),
		];
	}

	/** Publishes immutable generated terminal truth under the current lease
	 * fence, replacing caller command context with authenticated values. */
	async commitResult(
		input: MessageInitShape<typeof CommitInferenceResultRequestSchema>,
		options: SubmitOptions,
	): Promise<readonly [InferenceResult, Operation]> {
		const request = create(CommitInferenceResultRequestSchema, input);
		if (
			request.inferenceRequest === undefined ||
			request.fence === undefined ||
			request.result === undefined ||
			request.requestDigest.trim() === ""
		) {
			throw MindcladeError.invalidArgument(
				"inference request, lease fence, result, and request digest are required",
			);
		}
		delete request.context;
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CommitInferenceResultRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			COMMIT_RESULT,
			options.idempotencyKey,
			(call) => this.#core.raw.inference.commitInferenceResult(request, call),
		);
		if (response.result === undefined || response.operation === undefined) {
			throw MindcladeError.protocol(
				"CommitInferenceResult response omitted its result or operation",
			);
		}
		return [
			clone(InferenceResultSchema, response.result),
			clone(OperationSchema, response.operation),
		];
	}

	/** Streams validated generated updates. Transient disconnects resume only
	 * from the latest server-issued durable cursor; heartbeats never advance it. */
	async *watch(
		operationName: string,
		cursor?: InferenceStreamCursor,
		options: WaitOptions = {},
	): AsyncGenerator<InferenceStreamMessage> {
		validateRequired("inference operation name", operationName);
		const durableCursor =
			cursor === undefined ? undefined : clone(InferenceStreamCursorSchema, cursor);
		validateCursor(durableCursor);
		const waitTimeoutMs = options.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
		validateDuration("inference wait timeout", waitTimeoutMs);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, {
			...options,
			timeoutMs: waitTimeoutMs,
		});
		yield* watchStream(
			this.#core,
			prepared,
			this.#watchSource(operationName, prepared),
			durableCursor,
		);
	}

	/**
	 * Resumes a stream from a durable cursor the server already issued.
	 *
	 * The cursor is mandatory here, which is the whole point: a caller that
	 * holds one wants continuation, not a replay from the beginning.
	 */
	async *resumeWatch(
		operationName: string,
		cursor: InferenceStreamCursor,
		options: WaitOptions = {},
	): AsyncGenerator<InferenceStreamMessage> {
		yield* this.watch(operationName, cursor, options);
	}

	#watchSource(
		operationName: string,
		prepared: PreparedCall,
	): WatchSource<
		InferenceStreamMessage,
		InferenceStreamCursor | undefined,
		{ readonly message?: InferenceStreamMessage }
	> {
		return {
			accept: (response, cursor) => {
				if (response.message === undefined) {
					throw MindcladeError.protocol("inference watch response omitted its message");
				}
				const message = clone(InferenceStreamMessageSchema, response.message);
				return { cursor: acceptMessage(message, cursor), delivery: "yield", value: message };
			},
			incomplete: "stream ended before terminal inference truth",
			open: (cursor, call) =>
				this.#core.raw.inference.watchInference(
					create(WatchInferenceRequestSchema, {
						operationName,
						...(cursor === undefined ? {} : { cursor }),
						deadline: timestampFromDate(new Date(prepared.deadlineMs)),
					}),
					call,
				),
			route: WATCH,
			terminal: (message) =>
				message.update.case === "finalResult" || message.update.case === "failure",
		};
	}

	/** Waits for durable terminal stream truth and then reads the immutable
	 * result from its authoritative unary RPC. */
	async wait(
		operationName: string,
		cursor?: InferenceStreamCursor,
		options: WaitOptions = {},
	): Promise<readonly [InferenceResult, Operation]> {
		const startedAt = this.#core.runtime.nowMs();
		const timeoutMs = options.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
		for await (const message of this.watch(operationName, cursor, options)) {
			if (message.update.case === "failure") {
				throw MindcladeError.protocol("inference watch reported durable failure");
			}
			if (message.update.case === "finalResult") {
				const remaining = timeoutMs - (this.#core.runtime.nowMs() - startedAt);
				if (remaining <= 0) throw MindcladeError.deadlineExceeded();
				return await this.getResult(operationName, callOptions(options, remaining));
			}
		}
		throw MindcladeError.protocol("inference watch ended before durable terminal truth");
	}
}

/** Builds an authoritative generated request without introducing a parallel
 * SDK wire model. */
export const inferenceRequest = (
	input: MessageInitShape<typeof InferenceRequestSchema>,
): InferenceRequest => create(InferenceRequestSchema, input);

const acceptMessage = (
	message: InferenceStreamMessage,
	cursor: InferenceStreamCursor | undefined,
): InferenceStreamCursor => {
	validateRequired("inference stream request name", message.requestName);
	validateRequired("inference stream resume token", message.resumeToken);
	if (message.sequence <= 0n || message.update.case === undefined) {
		throw MindcladeError.protocol("inference watch returned an incomplete message");
	}
	if (message.update.case === "heartbeat") {
		if (
			cursor === undefined ||
			message.requestName !== cursor.requestName ||
			message.sequence !== cursor.afterSequence ||
			message.resumeToken !== cursor.resumeToken
		) {
			throw MindcladeError.protocol("inference heartbeat is not bound to the last durable cursor");
		}
		return cursor;
	}
	if (cursor !== undefined && message.requestName !== cursor.requestName) {
		throw MindcladeError.protocol("inference watch changed request identity");
	}
	const expected = (cursor?.afterSequence ?? 0n) + 1n;
	if (message.sequence !== expected) {
		throw MindcladeError.protocol("inference watch sequence is not contiguous");
	}
	return create(InferenceStreamCursorSchema, {
		afterSequence: message.sequence,
		requestName: message.requestName,
		resumeToken: message.resumeToken,
	});
};

const validateCursor = (cursor: InferenceStreamCursor | undefined): void => {
	if (cursor === undefined) return;
	if (
		cursor.afterSequence <= 0n ||
		cursor.requestName.trim() === "" ||
		cursor.resumeToken.trim() === ""
	) {
		throw MindcladeError.invalidArgument(
			"inference cursor must be a complete server-issued durable cursor",
		);
	}
	validateResource("inference cursor request name", cursor.requestName);
	validateResource("inference cursor token", cursor.resumeToken);
};

const validateRequired = (name: string, value: string): void => {
	if (value.trim() === "") throw MindcladeError.invalidArgument(`${name} is required`);
	validateResource(name, value);
};

const contextWithDigest = (
	core: ClientCore,
	prepared: ReturnType<typeof prepareCall>,
	options: SubmitOptions,
	digest: string,
) => ({ ...commandContext(core.config, prepared, options), canonicalRequestDigest: digest });

const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;

const callOptions = (options: WaitOptions, timeoutMs: number): SdkCallOptions => ({
	...(options.requestId === undefined ? {} : { requestId: options.requestId }),
	...(options.traceId === undefined ? {} : { traceId: options.traceId }),
	...(options.signal === undefined ? {} : { signal: options.signal }),
	timeoutMs,
});
