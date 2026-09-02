import { clone, create, type DescMessage, type MessageShape } from "@bufbuild/protobuf";

import {
	type PageRequest,
	PageRequestSchema,
} from "../../../../protocols/generated/typescript/common/v1/pagination_pb.js";
import { MindcladeError } from "./error.js";

/**
 * Traversal budgets. Both are enforced by every auto-paginating list method, so
 * a runaway cursor fails loudly instead of quietly consuming the caller.
 */
export interface PaginationLimits {
	/** Defaults to 100 and may not exceed 1,000. */
	readonly maxPages?: number | undefined;
	/** Defaults to 10,000 and may not exceed 1,000,000. */
	readonly maxItems?: number | undefined;
}

export interface PaginationOptions {
	/** Opaque token passed to the first request without normalization. */
	readonly initialPageToken?: string | undefined;
	readonly limits?: PaginationLimits | undefined;
	/** Also pass this signal to the facade call made by `fetchPage`. */
	readonly signal?: AbortSignal | undefined;
}

export interface PaginationPage<T> {
	readonly items: readonly T[];
	readonly nextPageToken: string;
}

/**
 * Page-level provenance for one fetched page of a list traversal.
 *
 * Named SdkPageInfo rather than PageMetadata because protobuf already owns
 * `mindclade.api.v1.PageMetadata` (`next_page_token`, `snapshot_token`), which is a
 * different contract type. Reusing that name here would be a handwritten wire model.
 */
export interface SdkPageInfo {
	/** Request ID of the RPC that produced this page. */
	readonly requestId: string | undefined;
	/** Opaque token that addressed this page; empty for the first page. */
	readonly pageToken: string;
	/** Opaque token addressing the next page; empty when exhausted. */
	readonly nextPageToken: string;
	/** Zero-based position of this page within the traversal. */
	readonly pageIndex: number;
	/** Page size the caller requested; zero when the server chooses. */
	readonly pageSize: number;
}

/** One page fetch, carrying the generated response and its request identity. */
export interface PageFetch<Response> {
	readonly response: Response;
	readonly requestId: string | undefined;
}

/**
 * Everything an auto-paginating list method must supply. The generated response
 * is preserved verbatim: `items` and `cursor` are read-only projections of it,
 * never a hand-written parallel model.
 */
export interface PageSource<Item, Response> {
	/** Opaque token for the first page, taken verbatim from the caller. */
	readonly pageToken: string;
	/** Page size the caller requested; recorded in {@link SdkPageInfo}. */
	readonly pageSize: number;
	/** Issues one page request, re-running the facade's per-page validation. */
	readonly fetch: (pageToken: string) => Promise<PageFetch<Response>>;
	readonly items: (response: Response) => readonly Item[];
	readonly cursor: (response: Response) => string;
	readonly limits?: PaginationLimits | undefined;
	readonly signal?: AbortSignal | undefined;
}

/**
 * Traversal state shared by every page of one list call: the budgets, the
 * cursors already observed, and the number of pages actually fetched.
 *
 * Internal to the pagination implementation; it is reachable only through the
 * {@link Page} objects a list method returns.
 */
export interface PageChain<Item, Response> {
	readonly source: PageSource<Item, Response>;
	readonly maxPages: number;
	readonly maxItems: number;
	readonly seen: Set<string>;
	pagesFetched: number;
}

/** Internal constructor payload for {@link Page}. */
export interface PageInit<Item, Response> {
	readonly chain: PageChain<Item, Response>;
	readonly response: Response;
	readonly items: readonly Item[];
	readonly metadata: SdkPageInfo;
}

/**
 * One fetched page that also traverses the rest of the cursor transparently.
 *
 * Iterating the page yields items across page boundaries; `nextPage`, `pages`,
 * and `metadata` keep the page-level view for callers that need the cursor. The
 * generated list response stays available, unchanged, as `response`.
 */
export class Page<Item, Response> implements AsyncIterable<Item> {
	/** Items of this page only. */
	readonly items: readonly Item[];
	/** The generated list response for this page, exactly as received. */
	readonly response: Response;
	readonly metadata: SdkPageInfo;

	readonly #chain: PageChain<Item, Response>;
	#next: Promise<Page<Item, Response> | undefined> | undefined;

	constructor(init: PageInit<Item, Response>) {
		this.#chain = init.chain;
		this.items = Object.freeze([...init.items]);
		this.response = init.response;
		this.metadata = init.metadata;
	}

	get hasNextPage(): boolean {
		return this.metadata.nextPageToken !== "";
	}

	/**
	 * Fetches the following page, or resolves to `undefined` at the end of the
	 * cursor. The fetch is memoized, so re-traversal never re-issues an RPC and
	 * never double-charges the page budget.
	 */
	async nextPage(): Promise<Page<Item, Response> | undefined> {
		if (!this.hasNextPage) return undefined;
		this.#next ??= fetchPage(this.#chain, this.metadata.nextPageToken, this.metadata.pageIndex + 1);
		return await this.#next;
	}

	/** Yields this page and every following page. */
	async *pages(): AsyncGenerator<Page<Item, Response>, void, undefined> {
		let page: Page<Item, Response> | undefined = this;
		while (page !== undefined) {
			yield page;
			page = await page.nextPage();
		}
	}

	/** Yields every item of every page, in server order. */
	async *[Symbol.asyncIterator](): AsyncGenerator<Item, void, undefined> {
		let yielded = 0;
		for await (const page of this.pages()) {
			for (const item of page.items) {
				if (yielded >= this.#chain.maxItems) {
					throw MindcladeError.paginationLimit("automatic pagination exceeded its item budget");
				}
				yielded += 1;
				yield item;
			}
		}
	}
}

/**
 * Fetches the first page of a list traversal and binds the shared budget.
 *
 * The caller's opaque token is forwarded to the first request without
 * normalization, repeated cursors fail as a protocol violation, and both
 * budgets are validated before any RPC is issued.
 */
export const listPage = async <Item, Response>(
	source: PageSource<Item, Response>,
): Promise<Page<Item, Response>> => {
	if (typeof source.fetch !== "function")
		throw MindcladeError.invalidArgument("pagination fetch function is required");
	if (typeof source.pageToken !== "string")
		throw MindcladeError.invalidArgument("initial page token must be text");
	const chain: PageChain<Item, Response> = {
		maxItems: paginationBound("pagination max items", source.limits?.maxItems ?? 10_000, 1_000_000),
		maxPages: paginationBound("pagination max pages", source.limits?.maxPages ?? 100, 1_000),
		pagesFetched: 0,
		seen: new Set<string>(source.pageToken === "" ? [] : [source.pageToken]),
		source,
	};
	return await fetchPage(chain, source.pageToken, 0);
};

/**
 * Returns a copy of a generated list request addressed at `pageToken`.
 *
 * The caller's message is never mutated, and an empty token is left absent so
 * the first request reaches the server exactly as the caller wrote it.
 */
export const withPageToken = <Schema extends DescMessage>(
	schema: Schema,
	request: MessageShape<Schema>,
	pageToken: string,
): MessageShape<Schema> => {
	const copy = clone(schema, request);
	if (pageToken === "") return copy;
	const paged = copy as unknown as { page?: PageRequest };
	if (paged.page === undefined) paged.page = create(PageRequestSchema, { pageToken });
	else paged.page.pageToken = pageToken;
	return copy;
};

/**
 * Lazily traverses facade list calls while preserving opaque page tokens.
 * Repeated cursors and caller budgets fail explicitly, so a partial traversal
 * is never presented as complete.
 */
export async function* paginate<T>(
	fetchNextPage: (pageToken: string) => Promise<PaginationPage<T>>,
	options: PaginationOptions = {},
): AsyncGenerator<T, void, undefined> {
	if (typeof fetchNextPage !== "function")
		throw MindcladeError.invalidArgument("pagination fetch function is required");
	const maxPages = paginationBound("pagination max pages", options.limits?.maxPages ?? 100, 1_000);
	const maxItems = paginationBound(
		"pagination max items",
		options.limits?.maxItems ?? 10_000,
		1_000_000,
	);
	const initialPageToken = options.initialPageToken ?? "";
	if (typeof initialPageToken !== "string")
		throw MindcladeError.invalidArgument("initial page token must be text");
	let token = initialPageToken;
	const seen = new Set<string>(token === "" ? [] : [token]);
	let pages = 0;
	let items = 0;
	for (;;) {
		if (options.signal?.aborted === true) throw MindcladeError.cancelled();
		if (pages >= maxPages)
			throw MindcladeError.paginationLimit("automatic pagination exceeded its page budget");
		if (items >= maxItems)
			throw MindcladeError.paginationLimit("automatic pagination exceeded its item budget");
		const page = await fetchNextPage(token);
		pages += 1;
		if (!Array.isArray(page.items) || typeof page.nextPageToken !== "string")
			throw MindcladeError.protocol("list response returned an invalid pagination page");
		if (page.nextPageToken !== "" && seen.has(page.nextPageToken))
			throw MindcladeError.protocol("list response repeated an opaque page token");
		if (page.nextPageToken !== "") seen.add(page.nextPageToken);
		for (const item of page.items) {
			if (items >= maxItems)
				throw MindcladeError.paginationLimit("automatic pagination exceeded its item budget");
			items += 1;
			yield item;
		}
		if (page.nextPageToken === "") return;
		token = page.nextPageToken;
	}
}

const fetchPage = async <Item, Response>(
	chain: PageChain<Item, Response>,
	pageToken: string,
	pageIndex: number,
): Promise<Page<Item, Response>> => {
	const source = chain.source;
	if (source.signal?.aborted === true) throw MindcladeError.cancelled();
	if (chain.pagesFetched >= chain.maxPages)
		throw MindcladeError.paginationLimit("automatic pagination exceeded its page budget");
	const fetched = await source.fetch(pageToken);
	chain.pagesFetched += 1;
	const items = source.items(fetched.response);
	const nextPageToken = source.cursor(fetched.response);
	if (!Array.isArray(items) || typeof nextPageToken !== "string")
		throw MindcladeError.protocol("list response returned an invalid pagination page");
	if (nextPageToken !== "" && chain.seen.has(nextPageToken))
		throw MindcladeError.protocol("list response repeated an opaque page token");
	if (nextPageToken !== "") chain.seen.add(nextPageToken);
	return new Page<Item, Response>({
		chain,
		items,
		metadata: Object.freeze({
			nextPageToken,
			pageIndex,
			pageSize: source.pageSize,
			pageToken,
			requestId: fetched.requestId,
		}),
		response: fetched.response,
	});
};

const paginationBound = (name: string, value: number, maximum: number): number => {
	if (!Number.isInteger(value) || value < 1 || value > maximum)
		throw MindcladeError.invalidArgument(`${name} must be an integer in [1, ${maximum}]`);
	return value;
};
