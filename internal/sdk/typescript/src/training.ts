import { create, type MessageInitShape } from "@bufbuild/protobuf";
import { CreateTrainingRunRequestSchema } from "../../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import type { Operation } from "../../../../protocols/generated/typescript/job/v1/operation_pb.js";
import { CreateTrainingRunCommandSchema } from "../../../../protocols/generated/typescript/training/v1/training_commands_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import { commandContext, prepareCall, type SubmitOptions } from "./request.js";
import { invokeUnary } from "./retry.js";
import { registeredMethodSafety } from "./safety.js";

const CREATE_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun";

export class Training {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	/** Submits generated scientific intent and returns its durable operation. */
	async submit(
		command: MessageInitShape<typeof CreateTrainingRunCommandSchema>,
		options: SubmitOptions,
	): Promise<Operation> {
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const generatedCommand = create(CreateTrainingRunCommandSchema, {
			...command,
			context: commandContext(this.#core.config, prepared, options),
		});
		const request = create(CreateTrainingRunRequestSchema, { command: generatedCommand });
		const response = await invokeUnary(
			this.#core,
			prepared,
			registeredMethodSafety(CREATE_TRAINING_RUN),
			options.idempotencyKey,
			(call) => this.#core.raw.training.createTrainingRun(request, call),
		);
		if (response.operation === undefined) {
			throw MindcladeError.protocol("CreateTrainingRun response omitted its operation");
		}
		return response.operation;
	}
}
