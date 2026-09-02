import { create } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { Code, ConnectError } from "@connectrpc/connect";

import {
	CancelOperationRequestSchema,
	GetOperationRequestSchema,
	WatchOperationRequestSchema,
	type WatchOperationResponse,
} from "../../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import {
	type Operation,
	OperationState,
} from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError, OperationFailure } from "./error.js";
import {
	callHeaders,
	commandContext,
	type PreparedCall,
	prepareCall,
	type SdkCallOptions,
	type SubmitOptions,
	validateDuration,
	validateResource,
	type WaitOptions,
} from "./request.js";
import { ensureActive, invokeUnary, retryDelay } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const DEFAULT_WAIT_TIMEOUT_MS = 30 * 60 * 1_000;
const GET_OPERATION = "/mindclade.internal.job.v1.OperationService/GetOperation";
const CANCEL_OPERATION = "/mindclade.internal.job.v1.OperationService/CancelOperation";

export class Operations {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	async get(name: string, options: SdkCallOptions = {}): Promise<Operation> {
		validateResource("operation name", name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		return this.#getPrepared(name, prepared);
	}

	async wait(name: string, options: WaitOptions = {}): Promise<Operation> {
		validateResource("operation name", name);
		const waitTimeoutMs = options.waitTimeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
		const pollIntervalMs = options.pollIntervalMs ?? this.#core.config.pollIntervalMs;
		validateDuration("operation wait timeout", waitTimeoutMs);
		validateDuration("operation poll interval", pollIntervalMs);
		const outer = prepareCall(this.#core.config, this.#core.runtime, {
			...options,
			timeoutMs: waitTimeoutMs,
		});
		while (true) {
			ensureActive(this.#core, outer);
			const operation = await this.#getPrepared(name, outer);
			if (operation.done || isTerminalFailure(operation)) {
				return requireSuccessfulTerminal(operation);
			}
			const remaining = outer.deadlineMs - this.#core.runtime.nowMs();
			await this.#core.runtime.sleep(Math.min(pollIntervalMs, remaining), outer.signal);
		}
	}

	async cancel(
		name: string,
		etag: string,
		reason: string,
		options: SubmitOptions,
	): Promise<Operation> {
		validateResource("operation name", name);
		validateResource("operation ETag", etag);
		validateResource("cancellation reason", reason);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(CancelOperationRequestSchema, {
			context: commandContext(this.#core.config, prepared, options),
			etag,
			name,
			reason,
		});
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(CANCEL_OPERATION),
			options.idempotencyKey,
			(call) => this.#core.raw.operations.cancelOperation(request, call),
		);
		if (response.operation === undefined) {
			throw MindcladeError.protocol("CancelOperation response omitted its operation");
		}
		return response.operation;
	}

	/** Resumable, sequence-validating operation stream. */
	async *watch(
		name: string,
		afterSequence = 0n,
		options: SdkCallOptions = {},
	): AsyncGenerator<WatchOperationResponse> {
		validateResource("operation name", name);
		if (afterSequence < 0n)
			throw MindcladeError.invalidArgument("watch sequence cannot be negative");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		let cursor = afterSequence;
		let failures = 0;
		while (true) {
			ensureActive(this.#core, prepared);
			const request = create(WatchOperationRequestSchema, {
				afterSequence: cursor,
				deadline: timestampFromDate(new Date(prepared.deadlineMs)),
				name,
			});
			try {
				const stream = this.#core.raw.operations.watchOperation(request, {
					headers: callHeaders(this.#core.config, prepared),
					timeoutMs: prepared.deadlineMs - this.#core.runtime.nowMs(),
					...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
				});
				for await (const update of stream) {
					ensureActive(this.#core, prepared);
					if (update.sequence === 0n) {
						throw MindcladeError.protocol("operation watch returned an invalid zero sequence");
					}
					if (update.sequence <= cursor) continue;
					if (update.operation === undefined) {
						throw MindcladeError.protocol("operation watch update omitted its operation");
					}
					if (update.operation.operationId !== "" && update.operation.operationId !== name) {
						throw MindcladeError.protocol("operation watch returned a different operation");
					}
					failures = 0;
					cursor = update.sequence;
					yield update;
					if (update.operation.done || isTerminalFailure(update.operation)) return;
				}
				throw new ConnectError("stream ended before a terminal update", Code.Unavailable);
			} catch (reason) {
				const error = MindcladeError.from(
					reason,
					prepared.signal,
					this.#core.runtime.nowMs() >= prepared.deadlineMs,
				);
				failures += 1;
				if (!error.retryable || failures >= this.#core.config.retry.maxAttempts) throw error;
				const delay = retryDelay(this.#core, failures, error.retryAfterMs);
				if (delay >= prepared.deadlineMs - this.#core.runtime.nowMs()) {
					throw MindcladeError.deadlineExceeded();
				}
				await this.#core.runtime.sleep(delay, prepared.signal);
			}
		}
	}

	async watchUntilDone(
		name: string,
		afterSequence = 0n,
		options: SdkCallOptions = {},
	): Promise<Operation> {
		for await (const update of this.watch(name, afterSequence, options)) {
			if (
				update.operation !== undefined &&
				(update.operation.done || isTerminalFailure(update.operation))
			) {
				return requireSuccessfulTerminal(update.operation);
			}
		}
		throw MindcladeError.protocol("operation watch ended before a terminal revision");
	}

	async #getPrepared(name: string, prepared: PreparedCall): Promise<Operation> {
		const request = create(GetOperationRequestSchema, { ifNoneMatch: "", name });
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(GET_OPERATION),
			undefined,
			(call) => this.#core.raw.operations.getOperation(request, call),
		);
		if (response.operation === undefined) {
			throw MindcladeError.protocol("GetOperation response omitted its operation");
		}
		return response.operation;
	}
}

const isTerminalFailure = (operation: Operation): boolean =>
	operation.error !== undefined ||
	operation.state === OperationState.FAILED ||
	operation.state === OperationState.CANCELLED;

const requireSuccessfulTerminal = (operation: Operation): Operation => {
	if (isTerminalFailure(operation)) {
		throw new OperationFailure(operation);
	}
	if (operation.state !== OperationState.SUCCEEDED) {
		throw MindcladeError.protocol("done operation has a non-terminal-success state");
	}
	return operation;
};
