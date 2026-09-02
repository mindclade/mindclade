import type { ClientConfig } from "./config.js";
import type { RawInternalClients } from "./raw.js";
import type { ResponseCapture } from "./response.js";
import type { Runtime } from "./runtime.js";

export interface ClientCore {
	readonly config: ClientConfig;
	readonly raw: RawInternalClients;
	readonly runtime: Runtime;
	/**
	 * Sink filled by the retry loop with the successful attempt's headers and
	 * trailers. Present only on the derived cores `withResponse()` and the
	 * facades that need response metadata for their own contract install.
	 */
	readonly capture?: ResponseCapture | undefined;
}
