import { type Operation, OperationState } from "@mindclade/internal-sdk";

export type OperationPhase =
	| "cancelled"
	| "cancelling"
	| "failed"
	| "pending"
	| "running"
	| "succeeded"
	| "unknown";

/** Presentation-only operation state; authoritative transport values remain generated. */
export interface OperationView {
	readonly id: string;
	readonly jobId: string | undefined;
	readonly phase: OperationPhase;
	readonly revision: string;
	readonly terminal: boolean;
	readonly etag: string;
	readonly hasResult: boolean;
}

export const toOperationView = (operation: Operation): OperationView => ({
	etag: operation.etag,
	hasResult: operation.result !== undefined,
	id: operation.operationId,
	jobId: operation.jobId === "" ? undefined : operation.jobId,
	phase: phase(operation.state),
	revision: operation.resourceVersion.toString(10),
	terminal: operation.done,
});

const phase = (state: OperationState): OperationPhase => {
	switch (state) {
		case OperationState.PENDING:
			return "pending";
		case OperationState.RUNNING:
			return "running";
		case OperationState.SUCCEEDED:
			return "succeeded";
		case OperationState.FAILED:
			return "failed";
		case OperationState.CANCELLING:
			return "cancelling";
		case OperationState.CANCELLED:
			return "cancelled";
		case OperationState.UNSPECIFIED:
			return "unknown";
		default:
			return "unknown";
	}
};
