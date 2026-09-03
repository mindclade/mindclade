import http from "node:http";

import { AccessToken, type TokenProvider } from "./auth.js";
import { MindcladeError } from "./error.js";

const METADATA_HOST = "169.254.169.254";
const MAX_TOKEN_BYTES = 32 * 1_024;
const DEFAULT_EXCHANGE_TIMEOUT_MS = 10_000;

/** Narrow exchange seam; production uses the fixed GCP metadata identity endpoint. */
export interface GcpIdentityTokenExchange {
	exchange(audience: string, signal: AbortSignal): Promise<string>;
}

/** Options for the production GCP workload-identity provider. */
export interface GcpWorkloadIdentityOptions {
	readonly exchangeTimeoutMs?: number;
	/** Test-only exchange seam. Omit in production. */
	readonly exchange?: GcpIdentityTokenExchange;
}

/**
 * Audience-bound GCP workload identity with bounded exchange, per-audience
 * caching, and singleflight refresh. Provider failures never expose response
 * bodies or credential details.
 */
export class GcpWorkloadIdentityProvider implements TokenProvider {
	readonly #exchange: GcpIdentityTokenExchange;
	readonly #exchangeTimeoutMs: number;
	readonly #cache = new Map<string, AccessToken>();
	readonly #inFlight = new Map<string, Promise<AccessToken>>();

	constructor(options: GcpWorkloadIdentityOptions = {}) {
		const timeout = options.exchangeTimeoutMs ?? DEFAULT_EXCHANGE_TIMEOUT_MS;
		if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 30_000) {
			throw MindcladeError.configuration(
				"GCP credential exchange timeout must be in (0, 30000] ms",
			);
		}
		this.#exchangeTimeoutMs = timeout;
		this.#exchange = options.exchange ?? new GcpMetadataIdentityExchange();
	}

	async getToken(audience: string, signal: AbortSignal): Promise<AccessToken> {
		validateAudience(audience);
		if (signal.aborted) throw MindcladeError.cancelled();
		const cached = this.#cache.get(audience);
		if (cached !== undefined) {
			try {
				cached.authorizationHeader(Date.now());
				return cached;
			} catch {
				this.#cache.delete(audience);
			}
		}

		let refresh = this.#inFlight.get(audience);
		if (refresh === undefined) {
			refresh = this.#refresh(audience);
			this.#inFlight.set(audience, refresh);
		}
		return await awaitWithAbort(refresh, signal);
	}

	async #refresh(audience: string): Promise<AccessToken> {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), this.#exchangeTimeoutMs);
		timer.unref();
		try {
			const encoded = await this.#exchange.exchange(audience, controller.signal);
			const token = tokenFromJwt(encoded, audience);
			this.#cache.set(audience, token);
			return token;
		} catch {
			throw MindcladeError.authentication("GCP workload-identity exchange failed");
		} finally {
			clearTimeout(timer);
			this.#inFlight.delete(audience);
		}
	}
}

class GcpMetadataIdentityExchange implements GcpIdentityTokenExchange {
	async exchange(audience: string, signal: AbortSignal): Promise<string> {
		const path = `/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(audience)}&format=full`;
		return await new Promise<string>((resolve, reject) => {
			const request = http.request(
				{
					headers: { "Metadata-Flavor": "Google" },
					host: METADATA_HOST,
					method: "GET",
					path,
					signal,
				},
				(response) => {
					if (response.statusCode !== 200 || response.headers["metadata-flavor"] !== "Google") {
						response.resume();
						reject(new Error("metadata identity endpoint rejected the request"));
						return;
					}
					const chunks: Buffer[] = [];
					let size = 0;
					response.on("data", (chunk: Buffer) => {
						size += chunk.length;
						if (size > MAX_TOKEN_BYTES) {
							request.destroy(new Error("metadata identity response exceeded its bound"));
							return;
						}
						chunks.push(chunk);
					});
					response.on("end", () => resolve(Buffer.concat(chunks).toString("utf8").trim()));
				},
			);
			request.on("error", reject);
			request.end();
		});
	}
}

const tokenFromJwt = (encoded: string, audience: string): AccessToken => {
	if (encoded.length === 0 || encoded.length > MAX_TOKEN_BYTES) {
		throw new Error("identity token is empty or oversized");
	}
	const parts = encoded.split(".");
	if (parts.length !== 3 || parts[1] === undefined) throw new Error("identity token is malformed");
	const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8")) as unknown;
	if (
		typeof payload !== "object" ||
		payload === null ||
		!("exp" in payload) ||
		typeof payload.exp !== "number" ||
		!Number.isSafeInteger(payload.exp)
	) {
		throw new Error("identity token expiry is malformed");
	}
	const tokenAudience = "aud" in payload ? payload.aud : undefined;
	const audienceMatches =
		typeof tokenAudience === "string"
			? tokenAudience === audience
			: Array.isArray(tokenAudience) &&
				tokenAudience.length > 0 &&
				tokenAudience.every((value) => typeof value === "string") &&
				tokenAudience.some((value) => value === audience);
	if (!audienceMatches) throw new Error("identity token audience does not match");
	const expiresAtMs = payload.exp * 1_000;
	if (!Number.isSafeInteger(expiresAtMs)) throw new Error("identity token expiry is out of range");
	const token = new AccessToken(encoded, expiresAtMs);
	token.authorizationHeader(Date.now());
	return token;
};

const validateAudience = (audience: string): void => {
	if (
		audience.length === 0 ||
		audience.length > 2_048 ||
		[...audience].some((character) => {
			const code = character.charCodeAt(0);
			return code < 0x21 || code > 0x7e;
		})
	) {
		throw MindcladeError.configuration("GCP credential audience is invalid");
	}
};

const awaitWithAbort = async <T>(promise: Promise<T>, signal: AbortSignal): Promise<T> => {
	if (signal.aborted) throw MindcladeError.cancelled();
	let abort = (): void => undefined;
	const cancelled = new Promise<never>((_resolve, reject) => {
		abort = () => reject(MindcladeError.cancelled());
		signal.addEventListener("abort", abort, { once: true });
	});
	try {
		return await Promise.race([promise, cancelled]);
	} finally {
		signal.removeEventListener("abort", abort);
	}
};
