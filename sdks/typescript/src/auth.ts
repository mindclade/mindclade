import { MindcladeError } from "./error.js";

const REFRESH_SKEW_MS = 30_000;
const MAX_TOKEN_LIFETIME_MS = 65 * 60 * 1_000;

/** Short-lived credential with a non-enumerable private secret. */
export class AccessToken {
	readonly #value: string;
	readonly expiresAtMs: number;

	constructor(value: string, expiresAt: Date | number) {
		if (
			value.length === 0 ||
			value.length > 16 * 1_024 ||
			![...value].every((character) => {
				const code = character.charCodeAt(0);
				return code >= 0x21 && code <= 0x7e;
			})
		) {
			throw MindcladeError.authentication("credential provider returned an invalid token");
		}
		const expiry = expiresAt instanceof Date ? expiresAt.getTime() : expiresAt;
		if (!Number.isFinite(expiry)) {
			throw MindcladeError.authentication("credential provider returned an invalid expiry");
		}
		this.#value = value;
		this.expiresAtMs = expiry;
	}

	authorizationHeader(nowMs: number): string {
		const remaining = this.expiresAtMs - nowMs;
		if (remaining <= REFRESH_SKEW_MS) {
			throw MindcladeError.authentication("credential provider returned an expired token");
		}
		if (remaining > MAX_TOKEN_LIFETIME_MS) {
			throw MindcladeError.authentication("credential provider must return a short-lived token");
		}
		return `Bearer ${this.#value}`;
	}

	toString(): string {
		return "AccessToken(<redacted>)";
	}

	toJSON(): string {
		return "AccessToken(<redacted>)";
	}
}

/** Injectable workload-identity exchange and refresh boundary. */
export interface TokenProvider {
	getToken(audience: string, signal: AbortSignal): Promise<AccessToken>;
}
