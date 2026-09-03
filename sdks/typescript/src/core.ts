import type { ClientConfig } from "./config.js";
import type { RawInternalClients } from "./raw.js";
import type { Runtime } from "./runtime.js";

export interface ClientCore {
	readonly config: ClientConfig;
	readonly raw: RawInternalClients;
	readonly runtime: Runtime;
}
