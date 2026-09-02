import type { Transport } from "@connectrpc/connect";
import { Admin } from "./admin.js";
import { Agents } from "./agents.js";
import { Approvals } from "./approvals.js";
import { Artifacts } from "./artifacts.js";
import type { ClientConfig } from "./config.js";
import type { ClientCore } from "./core.js";
import { Datasets } from "./datasets.js";
import { clientConfigFromEnvironment, type EnvironmentOverrides } from "./environment.js";
import { MindcladeError } from "./error.js";
import { Evaluations } from "./evaluations.js";
import { Experiments } from "./experiments.js";
import { Inference } from "./inference.js";
import { Jobs } from "./jobs.js";
import { Models } from "./models.js";
import { Operations } from "./operations.js";
import { Policies } from "./policies.js";
import { RawInternalClients } from "./raw.js";
import { createResponseCapture, rawResponse, type WithResponse } from "./response.js";
import { Runs } from "./runs.js";
import { defaultRuntime, type Runtime } from "./runtime.js";
import { Training } from "./training.js";
import { AuthenticatedTransport, createNodeTransport } from "./transport.js";
import { Workflows } from "./workflows.js";

/**
 * Namespace constructors, keyed by the accessor they are published under.
 *
 * `withResponse()` rebuilds a namespace over a per-call core so that two
 * concurrent raw-response calls never share one capture.
 */
const namespaceFactories = {
	admin: (core: ClientCore) => new Admin(core),
	agents: (core: ClientCore) => new Agents(core),
	approvals: (core: ClientCore) => new Approvals(core),
	artifacts: (core: ClientCore) => new Artifacts(core),
	datasets: (core: ClientCore) => new Datasets(core),
	evaluations: (core: ClientCore) => new Evaluations(core),
	experiments: (core: ClientCore) => new Experiments(core),
	inference: (core: ClientCore) => new Inference(core),
	jobs: (core: ClientCore) => new Jobs(core),
	models: (core: ClientCore) => new Models(core),
	operations: (core: ClientCore) => new Operations(core),
	policies: (core: ClientCore) => new Policies(core),
	runs: (core: ClientCore) => new Runs(core),
	training: (core: ClientCore) => new Training(core),
	workflows: (core: ClientCore) => new Workflows(core),
} as const;

/** Ergonomic namespaces published on the client and by `withResponse()`. */
export type ErgonomicNamespace = keyof typeof namespaceFactories;

/** The `withResponse()` projection of every ergonomic namespace. */
export type RawResponseNamespaces = {
	readonly [Namespace in ErgonomicNamespace]: WithResponse<MindcladeClient[Namespace]>;
};

/** Private internal SDK facade. */
export class MindcladeClient {
	readonly raw: RawInternalClients;
	readonly training: Training;
	readonly operations: Operations;
	readonly artifacts: Artifacts;
	readonly datasets: Datasets;
	readonly evaluations: Evaluations;
	readonly experiments: Experiments;
	readonly models: Models;
	readonly inference: Inference;
	readonly jobs: Jobs;
	readonly policies: Policies;
	readonly runs: Runs;
	readonly admin: Admin;
	readonly agents: Agents;
	readonly workflows: Workflows;
	readonly approvals: Approvals;

	readonly #core: ClientCore;

	private constructor(config: ClientConfig, delegate: Transport, runtime: Runtime) {
		const transport = new AuthenticatedTransport(delegate, config, runtime);
		this.raw = new RawInternalClients(transport);
		const core: ClientCore = { config, raw: this.raw, runtime };
		this.#core = core;
		this.training = new Training(core);
		this.operations = new Operations(core);
		this.artifacts = new Artifacts(core);
		this.datasets = new Datasets(core);
		this.evaluations = new Evaluations(core);
		this.experiments = new Experiments(core);
		this.models = new Models(core);
		this.inference = new Inference(core);
		this.jobs = new Jobs(core);
		this.policies = new Policies(core);
		this.runs = new Runs(core);
		this.admin = new Admin(core);
		this.agents = new Agents(core);
		this.workflows = new Workflows(core);
		this.approvals = new Approvals(core);
	}

	/**
	 * Returns every ergonomic namespace re-projected so each promise-returning
	 * method resolves to the value together with its sanitized transport
	 * envelope: status, request ID, trace ID, and the allowlisted response
	 * metadata. Credential-bearing metadata is never exposed, and `raw` is not
	 * projected because raw generated calls stay unwrapped and unretried.
	 */
	withResponse(): RawResponseNamespaces {
		const core = this.#core;
		const namespaces: Record<string, unknown> = {};
		for (const [name, factory] of Object.entries(namespaceFactories)) {
			namespaces[name] = new Proxy(Object.create(null) as object, {
				get: (_target, property) => {
					if (typeof property !== "string") return undefined;
					return (...args: unknown[]): Promise<unknown> => {
						const capture = createResponseCapture();
						const instance = factory({ ...core, capture }) as unknown as Record<
							string,
							((...called: unknown[]) => Promise<unknown>) | undefined
						>;
						const method = instance[property];
						if (typeof method !== "function") {
							return Promise.reject(
								MindcladeError.invalidArgument(`${name} has no raw-response method by that name`),
							);
						}
						return Promise.resolve(method.apply(instance, args)).then((value) =>
							rawResponse(value, capture),
						);
					};
				},
			});
		}
		return Object.freeze(namespaces) as RawResponseNamespaces;
	}

	/** Creates a production Connect-Node client with secure transport defaults. */
	static connect(config: ClientConfig): MindcladeClient {
		return new MindcladeClient(config, createNodeTransport(config), defaultRuntime);
	}

	/**
	 * Creates a client from the process environment.
	 *
	 * This is the only environment-reading entry point in the SDK: the ordinary
	 * constructor never consults an ambient variable, and no credential is ever
	 * read from the environment — a token provider is supplied in code through
	 * `overrides`.
	 */
	static fromEnvironment(overrides: EnvironmentOverrides = {}): MindcladeClient {
		return MindcladeClient.connect(clientConfigFromEnvironment(overrides));
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
