import { type ArtifactRef, type MindcladeClient, MindcladeError } from "@mindclade/internal-sdk";

import { type OperationView, toOperationView } from "./operation-types.js";

const DEFAULT_ARTIFACT_LIMIT = 16 * 1024 * 1024;

export interface ConsoleRequestOptions {
	readonly signal?: AbortSignal;
	readonly timeoutMs?: number;
}

export interface OperationPageView {
	readonly items: readonly OperationView[];
	readonly nextPageToken: string | undefined;
}

export interface ResolvedArtifactView {
	readonly digest: string;
	readonly mediaType: string;
	readonly content: Uint8Array;
}

/** Internal console data source backed only by the private SDK facade. */
export class OperationController {
	readonly #client: MindcladeClient;

	constructor(client: MindcladeClient) {
		this.#client = client;
	}

	async firstPage(options: ConsoleRequestOptions = {}): Promise<OperationPageView> {
		const response = await this.#client.operations.list(undefined, options);
		return {
			items: response.operations.map(toOperationView),
			nextPageToken: response.page?.nextPageToken === "" ? undefined : response.page?.nextPageToken,
		};
	}

	async get(name: string, options: ConsoleRequestOptions = {}): Promise<OperationView> {
		return toOperationView(await this.#client.operations.get(name, options));
	}

	async cancel(
		name: string,
		etag: string,
		reason: string,
		idempotencyKey: string,
		options: ConsoleRequestOptions = {},
	): Promise<OperationView> {
		return toOperationView(
			await this.#client.operations.cancel(name, etag, reason, {
				...options,
				idempotencyKey,
			}),
		);
	}

	async *watch(
		name: string,
		afterSequence = 0n,
		options: ConsoleRequestOptions = {},
	): AsyncGenerator<OperationView> {
		for await (const update of this.#client.operations.watch(name, afterSequence, options)) {
			if (update.operation !== undefined) yield toOperationView(update.operation);
		}
	}

	async resolveAndDownload(
		parent: string,
		alias: string,
		options: ConsoleRequestOptions & { readonly maximumBytes?: number } = {},
	): Promise<ResolvedArtifactView> {
		const artifact = await this.#client.artifacts.resolveAlias(parent, alias, options);
		const maximum = options.maximumBytes ?? DEFAULT_ARTIFACT_LIMIT;
		validateArtifactBound(artifact, maximum);
		const chunks: Uint8Array[] = [];
		let length = 0;
		await this.#client.artifacts.download(
			artifact,
			(chunk) => {
				length += chunk.byteLength;
				if (length > maximum) {
					throw MindcladeError.invalidArgument("artifact stream exceeded the console byte limit");
				}
				chunks.push(chunk);
			},
			options,
		);
		const content = new Uint8Array(length);
		let offset = 0;
		for (const chunk of chunks) {
			content.set(chunk, offset);
			offset += chunk.byteLength;
		}
		return { content, digest: artifact.digest, mediaType: artifact.mediaType };
	}
}

const validateArtifactBound = (artifact: ArtifactRef, maximum: number): void => {
	if (!Number.isSafeInteger(maximum) || maximum <= 0 || maximum > 1024 * 1024 * 1024) {
		throw MindcladeError.invalidArgument("console artifact byte limit is invalid");
	}
	if (artifact.sizeBytes < 0n || artifact.sizeBytes > BigInt(maximum)) {
		throw MindcladeError.invalidArgument("artifact exceeds the console byte limit");
	}
};
