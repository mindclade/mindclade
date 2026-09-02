import {
	type ArtifactRef,
	MAX_MESSAGE_BYTES,
	type MindcladeClient,
	MindcladeError,
	type PaginationLimits,
} from "@mindclade/internal-sdk";

import { type OperationView, toOperationView } from "./operation-types.js";

/**
 * Default ceiling for an artifact the console buffers in memory.
 *
 * `MAX_MESSAGE_BYTES` (8 MiB) is the only byte contract the SDK publishes, and
 * it documents itself as the point past which "payloads travel as artifacts,
 * never as inline protobuf". Downloads are streamed in SDK-chosen chunks, so
 * that ceiling does not bound a transfer — which is exactly why the previous
 * 16 MiB literal was misleading: it read like a transport fact and was neither
 * enforced nor derived from one. The console needs a memory budget of its own,
 * so it adopts the SDK's published ceiling instead of inventing a second
 * number: a response the platform would refuse to carry inline is not one the
 * console should silently materialise in a server process. Callers that
 * genuinely need more pass `maximumBytes` and own that decision explicitly.
 */
const DEFAULT_ARTIFACT_LIMIT = MAX_MESSAGE_BYTES;

/** Hard ceiling on an explicit `maximumBytes` override. Console-owned policy. */
const MAX_ARTIFACT_LIMIT = 1024 * 1024 * 1024;

export interface ConsoleRequestOptions {
	readonly signal?: AbortSignal;
	readonly timeoutMs?: number;
}

/**
 * List options. Traversal is the SDK's job, so the console only forwards the
 * page and item budgets rather than counting pages itself.
 */
export interface ConsoleListOptions extends ConsoleRequestOptions {
	readonly limits?: PaginationLimits;
}

/**
 * Presentation projection of one SDK page. The generated list response is not
 * restated here: every field is read off the SDK page that produced it.
 */
export interface OperationPageView {
	readonly items: readonly OperationView[];
	readonly nextPageToken: string | undefined;
	/** Request ID of the RPC that served this page, present on success too. */
	readonly requestId: string | undefined;
}

export interface ResolvedArtifactView {
	readonly digest: string;
	readonly mediaType: string;
	readonly content: Uint8Array;
}

/** The SDK's operation page type, named without restating its shape. */
type OperationPage = Awaited<ReturnType<MindcladeClient["operations"]["list"]>>;

/** Internal console data source backed only by the private SDK facade. */
export class OperationController {
	readonly #client: MindcladeClient;

	constructor(client: MindcladeClient) {
		this.#client = client;
	}

	/** The first page only. The cursor is the SDK's opaque token, untouched. */
	async firstPage(options: ConsoleListOptions = {}): Promise<OperationPageView> {
		return toOperationPageView(await this.#client.operations.list(undefined, options));
	}

	/**
	 * Every page in cursor order. The SDK fetches and budgets each page; the
	 * console never threads a page token or counts pages of its own.
	 */
	async *pages(options: ConsoleListOptions = {}): AsyncGenerator<OperationPageView> {
		const first = await this.#client.operations.list(undefined, options);
		for await (const page of first.pages()) yield toOperationPageView(page);
	}

	/**
	 * Every operation across the whole cursor, bounded by the SDK's traversal
	 * budgets (100 items per page and 10,000 items by default). Exceeding a
	 * budget surfaces as an SDK error rather than a silently truncated list.
	 */
	async listAll(options: ConsoleListOptions = {}): Promise<readonly OperationView[]> {
		const views: OperationView[] = [];
		for await (const operation of await this.#client.operations.list(undefined, options)) {
			views.push(toOperationView(operation));
		}
		return views;
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
		// The SDK verifies chunk digests, offsets, terminal size, and the full
		// digest; it does not cap how much a server may stream before that final
		// check, so the console keeps its own running guard on the bytes it is
		// holding in memory.
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

const toOperationPageView = (page: OperationPage): OperationPageView => ({
	items: page.items.map(toOperationView),
	nextPageToken: page.metadata.nextPageToken === "" ? undefined : page.metadata.nextPageToken,
	requestId: page.metadata.requestId,
});

/**
 * Enforces the console's in-memory budget only. Structural validity of the
 * generated `ArtifactRef` — digest shape, non-negative size, absent provider
 * URI — is the SDK's, and is not re-checked here.
 */
const validateArtifactBound = (artifact: ArtifactRef, maximum: number): void => {
	if (!Number.isSafeInteger(maximum) || maximum <= 0 || maximum > MAX_ARTIFACT_LIMIT) {
		throw MindcladeError.invalidArgument("console artifact byte limit is invalid");
	}
	if (artifact.sizeBytes > BigInt(maximum)) {
		throw MindcladeError.invalidArgument("artifact exceeds the console byte limit");
	}
};
