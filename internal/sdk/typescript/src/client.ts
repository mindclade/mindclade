import type { Transport } from "@connectrpc/connect";
import { Admin } from "./admin.js";
import { Agents } from "./agents.js";
import { Approvals } from "./approvals.js";
import { Artifacts } from "./artifacts.js";
import type { ClientConfig } from "./config.js";
import type { ClientCore } from "./core.js";
import { Datasets } from "./datasets.js";
import { Evaluations } from "./evaluations.js";
import { Inference } from "./inference.js";
import { Models } from "./models.js";
import { Operations } from "./operations.js";
import { Policies } from "./policies.js";
import { RawInternalClients } from "./raw.js";
import { defaultRuntime, type Runtime } from "./runtime.js";
import { Training } from "./training.js";
import { AuthenticatedTransport, createNodeTransport } from "./transport.js";
import { Workflows } from "./workflows.js";

/** Private internal SDK facade. */
export class MindcladeClient {
	readonly raw: RawInternalClients;
	readonly training: Training;
	readonly operations: Operations;
	readonly artifacts: Artifacts;
	readonly datasets: Datasets;
	readonly evaluations: Evaluations;
	readonly models: Models;
	readonly inference: Inference;
	readonly policies: Policies;
	readonly admin: Admin;
	readonly agents: Agents;
	readonly workflows: Workflows;
	readonly approvals: Approvals;

	private constructor(config: ClientConfig, delegate: Transport, runtime: Runtime) {
		const transport = new AuthenticatedTransport(delegate, config, runtime);
		this.raw = new RawInternalClients(transport);
		const core: ClientCore = { config, raw: this.raw, runtime };
		this.training = new Training(core);
		this.operations = new Operations(core);
		this.artifacts = new Artifacts(core);
		this.datasets = new Datasets(core);
		this.evaluations = new Evaluations(core);
		this.models = new Models(core);
		this.inference = new Inference(core);
		this.policies = new Policies(core);
		this.admin = new Admin(core);
		this.agents = new Agents(core);
		this.workflows = new Workflows(core);
		this.approvals = new Approvals(core);
	}

	/** Creates a production Connect-Node client with secure transport defaults. */
	static connect(config: ClientConfig): MindcladeClient {
		return new MindcladeClient(config, createNodeTransport(config), defaultRuntime);
	}

	/** Injects a transport and deterministic runtime for hermetic tests or
	 * in-process service adapters. Auth and metadata policy still apply. */
	static withTransport(
		config: ClientConfig,
		transport: Transport,
		runtime: Runtime = defaultRuntime,
	): MindcladeClient {
		return new MindcladeClient(config, transport, runtime);
	}
}
