import { createHash } from "node:crypto";

import { clone, create, equals, toBinary } from "@bufbuild/protobuf";
import { timestampFromDate } from "@bufbuild/protobuf/wkt";
import { Code } from "@connectrpc/connect";

import { CommitArtifactCommandSchema } from "../../../../protocols/generated/typescript/artifact/v1/artifact_commands_pb.js";
import {
	type ArtifactRef,
	ArtifactRefSchema,
} from "../../../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import {
	AbortArtifactUploadRequestSchema,
	type ArtifactStagingReceipt,
	ArtifactStagingReceiptSchema,
	type ArtifactUploadSession,
	ArtifactUploadSessionSchema,
	ArtifactUploadState,
	BeginArtifactUploadRequestSchema,
	CommitArtifactRequestSchema,
	DownloadArtifactRequestSchema,
	FinalizeArtifactUploadRequestSchema,
	GetArtifactUploadRequestSchema,
	QuarantineArtifactUploadRequestSchema,
	ResolveArtifactAliasRequestSchema,
	UploadArtifactChunkRequestSchema,
} from "../../../../protocols/generated/typescript/internal/artifact/v1/artifact_service_pb.js";
import type { ClientCore } from "./core.js";
import { MindcladeError } from "./error.js";
import {
	callHeaders,
	commandContext,
	prepareCall,
	type SdkCallOptions,
	type SubmitOptions,
	validateDuration,
	validateResource,
} from "./request.js";
import { ensureActive, invokeUnary } from "./retry.js";

const DEFAULT_CHUNK_BYTES = 1 << 20;
const MAX_CHUNK_BYTES = 4 << 20;
const DEFAULT_SESSION_TTL_MS = 2 * 60 * 60 * 1_000;
const MAX_SESSION_TTL_MS = 24 * 60 * 60 * 1_000;
const DEFAULT_RECEIPT_TTL_MS = 24 * 60 * 60 * 1_000;
const MAX_RECEIPT_TTL_MS = 7 * 24 * 60 * 60 * 1_000;
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;
const UPLOAD_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export type ArtifactSource = Uint8Array | AsyncIterable<Uint8Array>;
export type ArtifactChunkSink = (chunk: Uint8Array) => void | Promise<void>;

/** Caller-stable transfer policy. Reusing uploadId in a fresh process resumes
 * the durable server session rather than creating a second object. */
export interface ArtifactUploadOptions extends SdkCallOptions {
	readonly uploadId: string;
	readonly chunkBytes?: number;
	readonly sessionTtlMs?: number;
	readonly receiptTtlMs?: number;
}

/** Artifact catalog and generation-pinned transfer helpers over generated
 * Connect clients. No provider URI, credential, or storage token enters this
 * layer. */
export class Artifacts {
	readonly #core: ClientCore;

	constructor(core: ClientCore) {
		this.#core = core;
	}

	/** Resolves a mutable catalog alias to a clone of the generated immutable reference. */
	async resolveAlias(
		parent: string,
		alias: string,
		options: SdkCallOptions = {},
	): Promise<ArtifactRef> {
		validateResource("artifact alias parent", parent);
		validateResource("artifact alias", alias);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(ResolveArtifactAliasRequestSchema, { alias, parent });
		const response = await invokeUnary(this.#core, prepared, "safe", undefined, (call) =>
			this.#core.raw.artifacts.resolveArtifactAlias(request, call),
		);
		if (response.artifact === undefined) {
			throw MindcladeError.protocol("ResolveArtifactAlias response omitted its artifact");
		}
		return clone(ArtifactRefSchema, response.artifact);
	}

	/** Reads clone-safe durable progress for a resumable upload. */
	async getUpload(name: string, options: SdkCallOptions = {}): Promise<ArtifactUploadSession> {
		validateResource("artifact upload name", name);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(GetArtifactUploadRequestSchema, { name });
		const response = await invokeUnary(this.#core, prepared, "safe", undefined, (call) =>
			this.#core.raw.artifacts.getArtifactUpload(request, call),
		);
		return validateUpload(response.upload, undefined, "GetArtifactUpload");
	}

	/** Resumes or begins an upload, appends independently checked contiguous
	 * chunks, re-verifies the complete local source, and finalizes to an opaque
	 * typed staging receipt. */
	async upload(
		artifactValue: ArtifactRef,
		source: ArtifactSource,
		options: ArtifactUploadOptions,
	): Promise<ArtifactStagingReceipt> {
		const artifact = validateArtifact(artifactValue, "artifact upload");
		validateUploadId(options.uploadId);
		const chunkBytes = options.chunkBytes ?? DEFAULT_CHUNK_BYTES;
		if (!Number.isSafeInteger(chunkBytes) || chunkBytes < 1 || chunkBytes > MAX_CHUNK_BYTES) {
			throw MindcladeError.invalidArgument(
				"artifact upload chunk size must be between one byte and four MiB",
			);
		}
		const sessionTtlMs = options.sessionTtlMs ?? DEFAULT_SESSION_TTL_MS;
		const receiptTtlMs = options.receiptTtlMs ?? DEFAULT_RECEIPT_TTL_MS;
		validateTransferDuration("artifact upload session", sessionTtlMs, MAX_SESSION_TTL_MS);
		validateTransferDuration("artifact staging receipt", receiptTtlMs, MAX_RECEIPT_TTL_MS);
		const call = uploadCallOptions(options);
		const parent = projectParent(this.#core);
		const uploadName = `${parent}/artifactUploads/${options.uploadId}`;
		let upload: ArtifactUploadSession;
		try {
			upload = await this.getUpload(uploadName, call);
		} catch (reason) {
			const error = MindcladeError.from(reason, options.signal);
			if (error.code !== Code.NotFound) throw error;
			upload = await this.#beginUpload(parent, artifact, options.uploadId, sessionTtlMs, call);
		}
		upload = validateUpload(upload, artifact, "artifact upload resume");
		if (upload.state === ArtifactUploadState.FINALIZED) {
			return validateReceipt(upload.stagingReceipt, artifact);
		}
		if (upload.state !== ArtifactUploadState.OPEN) {
			throw MindcladeError.invalidArgument("artifact upload session cannot be resumed");
		}

		const reader = new SourceReader(source);
		const fullDigest = createHash("sha256");
		const expectedSize = safeSize(artifact.sizeBytes, "artifact size");
		const prefix = safeSize(upload.committedOffset, "artifact upload resume offset");
		for (let remaining = prefix; remaining > 0; ) {
			const count = Math.min(remaining, DEFAULT_CHUNK_BYTES);
			fullDigest.update(await reader.readExact(count, "resume offset"));
			remaining -= count;
		}

		let offset = prefix;
		while (offset < expectedSize) {
			const data = await reader.readExact(
				Math.min(chunkBytes, expectedSize - offset),
				"declared size",
			);
			fullDigest.update(data);
			const chunkDigest = sha256(data);
			const submit = phaseSubmit(
				options.uploadId,
				`chunk:${upload.nextChunkIndex}:${chunkDigest}`,
				call,
			);
			const prepared = prepareCall(this.#core.config, this.#core.runtime, submit);
			const request = create(UploadArtifactChunkRequestSchema, {
				chunkDigest,
				chunkIndex: upload.nextChunkIndex,
				data,
				etag: upload.etag,
				name: upload.name,
				offset: BigInt(offset),
			});
			request.context = contextWithDigest(
				this.#core,
				prepared,
				submit,
				sha256(toBinary(UploadArtifactChunkRequestSchema, request)),
			);
			const response = await invokeUnary(
				this.#core,
				prepared,
				"idempotent",
				submit.idempotencyKey,
				(rpcOptions) => this.#core.raw.artifacts.uploadArtifactChunk(request, rpcOptions),
			);
			const expectedOffset = offset + data.byteLength;
			const expectedIndex = upload.nextChunkIndex + 1n;
			upload = validateUpload(response.upload, artifact, "UploadArtifactChunk");
			if (
				upload.state !== ArtifactUploadState.OPEN ||
				upload.committedOffset !== BigInt(expectedOffset) ||
				upload.nextChunkIndex !== expectedIndex
			) {
				throw MindcladeError.protocol("artifact upload progress did not advance contiguously");
			}
			offset = expectedOffset;
		}
		await reader.requireEnd();
		if (`sha256:${fullDigest.digest("hex")}` !== artifact.digest) {
			throw MindcladeError.invalidArgument(
				"artifact upload source digest differs from ArtifactRef",
			);
		}
		return await this.#finalizeUpload(upload, artifact, options.uploadId, receiptTtlMs, call);
	}

	/** Permanently aborts an incomplete session under ETag and idempotency protection. */
	async abortUpload(
		name: string,
		etag: string,
		reasonCode: string,
		options: SubmitOptions,
	): Promise<ArtifactUploadSession> {
		return await this.#terminalUpload(
			"abort",
			name,
			etag,
			reasonCode,
			options,
			ArtifactUploadState.ABORTED,
		);
	}

	/** Permanently quarantines a corrupt or policy-rejected session. */
	async quarantineUpload(
		name: string,
		etag: string,
		reasonCode: string,
		options: SubmitOptions,
	): Promise<ArtifactUploadSession> {
		return await this.#terminalUpload(
			"quarantine",
			name,
			etag,
			reasonCode,
			options,
			ArtifactUploadState.QUARANTINED,
		);
	}

	/** Commits a verified opaque staging receipt to the immutable catalog. */
	async commit(receiptValue: ArtifactStagingReceipt, options: SubmitOptions): Promise<ArtifactRef> {
		const receipt = validateReceipt(receiptValue);
		const artifact = receipt.artifact;
		if (artifact === undefined) {
			throw MindcladeError.protocol("artifact staging receipt omitted its artifact");
		}
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const command = create(CommitArtifactCommandSchema, {
			artifact,
			stagingReceiptDigest: receipt.receiptDigest,
		});
		command.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(CommitArtifactCommandSchema, command)),
		);
		const request = create(CommitArtifactRequestSchema, { command });
		const response = await invokeUnary(
			this.#core,
			prepared,
			"idempotent",
			options.idempotencyKey,
			(rpcOptions) => this.#core.raw.artifacts.commitArtifact(request, rpcOptions),
		);
		const committed = validateArtifact(response.artifact, "CommitArtifact response");
		if (!equals(ArtifactRefSchema, committed, artifact)) {
			throw MindcladeError.protocol("CommitArtifact returned a different content identity");
		}
		return committed;
	}

	/** Streams generation-pinned immutable bytes to a caller-owned sink while
	 * validating identity, offsets, chunk digests, terminal size, and full digest. */
	async download(
		artifactValue: ArtifactRef,
		sink: ArtifactChunkSink,
		options: SdkCallOptions = {},
	): Promise<bigint> {
		const artifact = validateArtifact(artifactValue, "artifact download");
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		const request = create(DownloadArtifactRequestSchema, {
			digest: artifact.digest,
			maxChunkBytes: DEFAULT_CHUNK_BYTES,
			offset: 0n,
		});
		const digest = createHash("sha256");
		let offset = 0n;
		let complete = false;
		try {
			const stream = this.#core.raw.artifacts.downloadArtifact(request, {
				headers: callHeaders(this.#core.config, prepared),
				timeoutMs: prepared.deadlineMs - this.#core.runtime.nowMs(),
				...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
			});
			for await (const response of stream) {
				ensureActive(this.#core, prepared);
				if (complete) {
					throw MindcladeError.protocol("artifact download yielded a response after completion");
				}
				const streamed = validateArtifact(response.artifact, "artifact download response");
				if (!equals(ArtifactRefSchema, streamed, artifact) || response.offset !== offset) {
					throw MindcladeError.protocol("artifact download stream changed identity or offset");
				}
				if (response.chunkDigest !== sha256(response.data)) {
					throw MindcladeError.protocol("artifact download chunk digest verification failed");
				}
				const copied = new Uint8Array(response.data);
				await sink(copied);
				digest.update(copied);
				offset += BigInt(copied.byteLength);
				complete = response.complete;
			}
		} catch (reason) {
			throw MindcladeError.from(
				reason,
				prepared.signal,
				this.#core.runtime.nowMs() >= prepared.deadlineMs,
			);
		}
		if (!complete || offset !== artifact.sizeBytes) {
			throw MindcladeError.protocol("artifact download ended before its declared size");
		}
		if (`sha256:${digest.digest("hex")}` !== artifact.digest) {
			throw MindcladeError.protocol("artifact download full digest verification failed");
		}
		return offset;
	}

	async #beginUpload(
		parent: string,
		artifact: ArtifactRef,
		uploadId: string,
		sessionTtlMs: number,
		call: SdkCallOptions,
	): Promise<ArtifactUploadSession> {
		const submit = phaseSubmit(uploadId, "begin", call);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, submit);
		const request = create(BeginArtifactUploadRequestSchema, {
			artifact,
			expireTime: timestampFromDate(new Date(this.#core.runtime.nowMs() + sessionTtlMs)),
			parent,
			uploadId,
		});
		request.context = contextWithDigest(
			this.#core,
			prepared,
			submit,
			sha256(toBinary(BeginArtifactUploadRequestSchema, request)),
		);
		try {
			const response = await invokeUnary(
				this.#core,
				prepared,
				"idempotent",
				submit.idempotencyKey,
				(rpcOptions) => this.#core.raw.artifacts.beginArtifactUpload(request, rpcOptions),
			);
			return validateUpload(response.upload, artifact, "BeginArtifactUpload");
		} catch (reason) {
			const error = MindcladeError.from(reason, call.signal);
			if (error.code !== Code.AlreadyExists && error.code !== Code.Aborted) throw error;
			return await this.getUpload(`${parent}/artifactUploads/${uploadId}`, call);
		}
	}

	async #finalizeUpload(
		upload: ArtifactUploadSession,
		artifact: ArtifactRef,
		uploadId: string,
		receiptTtlMs: number,
		call: SdkCallOptions,
	): Promise<ArtifactStagingReceipt> {
		const submit = phaseSubmit(uploadId, "finalize", call);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, submit);
		const baseMs =
			upload.createTime === undefined ? this.#core.runtime.nowMs() : timestampMs(upload.createTime);
		const request = create(FinalizeArtifactUploadRequestSchema, {
			etag: upload.etag,
			name: upload.name,
			receiptExpireTime: timestampFromDate(new Date(baseMs + receiptTtlMs)),
		});
		request.context = contextWithDigest(
			this.#core,
			prepared,
			submit,
			sha256(toBinary(FinalizeArtifactUploadRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			"idempotent",
			submit.idempotencyKey,
			(rpcOptions) => this.#core.raw.artifacts.finalizeArtifactUpload(request, rpcOptions),
		);
		const finalized = validateUpload(response.upload, artifact, "FinalizeArtifactUpload");
		if (finalized.state !== ArtifactUploadState.FINALIZED) {
			throw MindcladeError.protocol("FinalizeArtifactUpload did not return a finalized session");
		}
		return validateReceipt(response.stagingReceipt, artifact);
	}

	async #terminalUpload(
		transition: "abort" | "quarantine",
		name: string,
		etag: string,
		reasonCode: string,
		options: SubmitOptions,
		expectedState: ArtifactUploadState,
	): Promise<ArtifactUploadSession> {
		validateResource("artifact upload name", name);
		validateResource("artifact upload ETag", etag);
		validateResource("artifact upload reason", reasonCode);
		const prepared = prepareCall(this.#core.config, this.#core.runtime, options);
		if (transition === "abort") {
			const request = create(AbortArtifactUploadRequestSchema, { etag, name, reasonCode });
			request.context = contextWithDigest(
				this.#core,
				prepared,
				options,
				sha256(toBinary(AbortArtifactUploadRequestSchema, request)),
			);
			const response = await invokeUnary(
				this.#core,
				prepared,
				"idempotent",
				options.idempotencyKey,
				(rpcOptions) => this.#core.raw.artifacts.abortArtifactUpload(request, rpcOptions),
			);
			return requireTerminal(response.upload, expectedState, "AbortArtifactUpload");
		}
		const request = create(QuarantineArtifactUploadRequestSchema, { etag, name, reasonCode });
		request.context = contextWithDigest(
			this.#core,
			prepared,
			options,
			sha256(toBinary(QuarantineArtifactUploadRequestSchema, request)),
		);
		const response = await invokeUnary(
			this.#core,
			prepared,
			"idempotent",
			options.idempotencyKey,
			(rpcOptions) => this.#core.raw.artifacts.quarantineArtifactUpload(request, rpcOptions),
		);
		return requireTerminal(response.upload, expectedState, "QuarantineArtifactUpload");
	}
}

class SourceReader {
	readonly #iterator: AsyncIterator<Uint8Array>;
	#pending: Uint8Array<ArrayBufferLike> = new Uint8Array();
	#pendingOffset = 0;
	#ended = false;

	constructor(source: ArtifactSource) {
		this.#iterator = (source instanceof Uint8Array ? singleChunk(source) : source)[
			Symbol.asyncIterator
		]();
	}

	async readExact(length: number, boundary: string): Promise<Uint8Array> {
		const output = new Uint8Array(length);
		let written = 0;
		while (written < length) {
			await this.#refill();
			if (this.#ended) {
				throw MindcladeError.invalidArgument(`artifact upload source ended before its ${boundary}`);
			}
			const count = Math.min(length - written, this.#pending.byteLength - this.#pendingOffset);
			output.set(this.#pending.subarray(this.#pendingOffset, this.#pendingOffset + count), written);
			this.#pendingOffset += count;
			written += count;
		}
		return output;
	}

	async requireEnd(): Promise<void> {
		await this.#refill();
		if (!this.#ended) {
			throw MindcladeError.invalidArgument("artifact upload source exceeds its declared size");
		}
	}

	async #refill(): Promise<void> {
		while (!this.#ended && this.#pendingOffset >= this.#pending.byteLength) {
			const next = await this.#iterator.next();
			if (next.done === true) {
				this.#ended = true;
				this.#pending = new Uint8Array();
				this.#pendingOffset = 0;
				return;
			}
			if (!(next.value instanceof Uint8Array)) {
				throw MindcladeError.invalidArgument("artifact upload source yielded a non-byte chunk");
			}
			this.#pending = next.value;
			this.#pendingOffset = 0;
		}
	}
}

async function* singleChunk(value: Uint8Array): AsyncIterable<Uint8Array> {
	yield value;
}

const validateArtifact = (value: ArtifactRef | undefined, label: string): ArtifactRef => {
	if (
		value === undefined ||
		!SHA256_PATTERN.test(value.digest) ||
		value.mediaType.trim() === "" ||
		value.sizeBytes < 0n ||
		value.uri !== "" ||
		(value.integrityDigest !== "" && value.integrityDigest !== value.digest) ||
		(value.schemaId === "") !== (value.schemaVersion === "")
	) {
		throw MindcladeError.invalidArgument(
			`${label} requires a complete immutable ArtifactRef without a provider URI`,
		);
	}
	return clone(ArtifactRefSchema, value);
};

const validateUpload = (
	value: ArtifactUploadSession | undefined,
	expected: ArtifactRef | undefined,
	method: string,
): ArtifactUploadSession => {
	if (value === undefined) {
		throw MindcladeError.protocol(`${method} response omitted its upload session`);
	}
	validateResource("artifact upload name", value.name);
	const artifact = validateArtifact(value.artifact, `${method} upload`);
	if (expected !== undefined && !equals(ArtifactRefSchema, artifact, expected)) {
		throw MindcladeError.protocol(`${method} returned a different content identity`);
	}
	if (
		value.state === ArtifactUploadState.UNSPECIFIED ||
		!UPLOAD_STATES.has(value.state) ||
		value.committedOffset < 0n ||
		value.committedOffset > artifact.sizeBytes ||
		value.nextChunkIndex < 0n ||
		value.revision <= 0n ||
		value.etag === ""
	) {
		throw MindcladeError.protocol(`${method} returned invalid upload lifecycle metadata`);
	}
	return clone(ArtifactUploadSessionSchema, value);
};

const validateReceipt = (
	value: ArtifactStagingReceipt | undefined,
	expected?: ArtifactRef,
): ArtifactStagingReceipt => {
	if (value === undefined || !SHA256_PATTERN.test(value.receiptDigest)) {
		throw MindcladeError.protocol("artifact staging receipt digest is invalid");
	}
	const artifact = validateArtifact(value.artifact, "artifact staging receipt");
	if (expected !== undefined && !equals(ArtifactRefSchema, artifact, expected)) {
		throw MindcladeError.protocol("artifact staging receipt returned a different content identity");
	}
	if (
		value.verifiedAt === undefined ||
		value.expireTime === undefined ||
		timestampMs(value.expireTime) <= timestampMs(value.verifiedAt)
	) {
		throw MindcladeError.protocol("artifact staging receipt validity interval is invalid");
	}
	return clone(ArtifactStagingReceiptSchema, value);
};

const requireTerminal = (
	value: ArtifactUploadSession | undefined,
	state: ArtifactUploadState,
	method: string,
): ArtifactUploadSession => {
	const upload = validateUpload(value, undefined, method);
	if (upload.state !== state) {
		throw MindcladeError.protocol(`${method} returned an unexpected upload state`);
	}
	return upload;
};

const contextWithDigest = (
	core: ClientCore,
	prepared: ReturnType<typeof prepareCall>,
	options: SubmitOptions,
	digest: string,
) => ({ ...commandContext(core.config, prepared, options), canonicalRequestDigest: digest });

const phaseSubmit = (uploadId: string, phase: string, call: SdkCallOptions): SubmitOptions => ({
	...call,
	idempotencyKey: phaseKey(uploadId, phase),
});

const uploadCallOptions = (options: ArtifactUploadOptions): SdkCallOptions => ({
	...(options.requestId === undefined ? {} : { requestId: options.requestId }),
	...(options.traceId === undefined ? {} : { traceId: options.traceId }),
	...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
	...(options.signal === undefined ? {} : { signal: options.signal }),
});

const phaseKey = (uploadId: string, phase: string): string =>
	`artifact-transfer:${createHash("sha256").update(uploadId).update("\0").update(phase).digest("hex")}`;

const sha256 = (value: Uint8Array): string =>
	`sha256:${createHash("sha256").update(value).digest("hex")}`;

const validateUploadId = (value: string): void => {
	if (!UPLOAD_ID_PATTERN.test(value)) {
		throw MindcladeError.invalidArgument("artifact upload ID is invalid");
	}
};

const validateTransferDuration = (name: string, value: number, maximum: number): void => {
	if (!Number.isSafeInteger(value) || value <= 0 || value > maximum) {
		throw MindcladeError.invalidArgument(`${name} lifetime is outside policy`);
	}
	if (value <= 86_400_000) validateDuration(`${name} lifetime`, value);
};

const projectParent = (core: ClientCore): string => {
	const tenant = core.config.identity.tenantId.startsWith("tenants/")
		? core.config.identity.tenantId
		: `tenants/${core.config.identity.tenantId}`;
	const project = core.config.identity.projectId;
	if (project.startsWith("tenants/")) return project;
	return project.startsWith("projects/") ? `${tenant}/${project}` : `${tenant}/projects/${project}`;
};

const safeSize = (value: bigint, name: string): number => {
	if (value < 0n || value > BigInt(Number.MAX_SAFE_INTEGER)) {
		throw MindcladeError.invalidArgument(`${name} exceeds TypeScript client limits`);
	}
	return Number(value);
};

const timestampMs = (value: { readonly seconds: bigint; readonly nanos: number }): number => {
	const milliseconds = Number(value.seconds) * 1_000 + Math.floor(value.nanos / 1_000_000);
	if (!Number.isSafeInteger(milliseconds)) {
		throw MindcladeError.protocol("protobuf timestamp exceeds TypeScript client limits");
	}
	return milliseconds;
};

const UPLOAD_STATES = new Set<ArtifactUploadState>([
	ArtifactUploadState.OPEN,
	ArtifactUploadState.FINALIZING,
	ArtifactUploadState.FINALIZED,
	ArtifactUploadState.ABORTED,
	ArtifactUploadState.QUARANTINED,
	ArtifactUploadState.EXPIRED,
]);
