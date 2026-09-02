import { arch, platform, versions } from "node:process";

/**
 * Single source of SDK identity.
 *
 * The name and version stamped into `x-mindclade-sdk` are defined here and
 * nowhere else, so the request path, the transport, and the packaging metadata
 * cannot drift apart.
 */
export const SDK_NAME = "mindclade-internal-typescript-sdk";
/** Kept equal to the `version` field of this package's `package.json`. */
export const SDK_VERSION = "0.1.0";

const MAX_COMPONENT_LENGTH = 32;
const MAX_METADATA_LENGTH = 512;

/**
 * Reduces one platform fact to a bounded, non-identifying token.
 *
 * Anything outside the conservative token alphabet is dropped rather than
 * escaped, so a hostile or exotic runtime string can never widen the metadata
 * value or smuggle a separator into it.
 */
const component = (value: string | undefined): string => {
	const cleaned = (value ?? "").replace(/[^A-Za-z0-9._-]/g, "");
	return cleaned.length === 0 ? "unknown" : cleaned.slice(0, MAX_COMPONENT_LENGTH);
};

const runtimeVersions = versions as Readonly<Record<string, string | undefined>>;

const runtimeName = (): string => {
	if (typeof runtimeVersions.bun === "string") return "bun";
	if (typeof runtimeVersions.deno === "string") return "deno";
	return "node";
};

const runtimeVersion = (): string | undefined => runtimeVersions[runtimeName()] ?? versions.node;

/**
 * The identity-only form used when the caller opts out of platform metadata.
 * Language stays because it selects the server-side compatibility contract; it
 * is a property of the SDK, not of the machine running it.
 */
const identity = `${SDK_NAME}/${SDK_VERSION};lang=typescript`;

/**
 * Structured platform metadata.
 *
 * Semicolons rather than spaces separate the fields so the whole value passes
 * the SDK's visible-ASCII metadata rule unchanged in every language.
 */
const structured = [
	identity,
	`os=${component(platform)}`,
	`arch=${component(arch)}`,
	`runtime=${component(runtimeName())}`,
	`runtime_version=${component(runtimeVersion())}`,
].join(";");

const bounded = (value: string): boolean =>
	value.length > 0 &&
	value.length <= MAX_METADATA_LENGTH &&
	[...value].every((character) => {
		const code = character.charCodeAt(0);
		return code >= 0x21 && code <= 0x7e;
	});

const platformValue = bounded(structured) ? structured : identity;

/**
 * Returns the value of the `x-mindclade-sdk` request metadata.
 *
 * With `omit` the value collapses to SDK name, version, and language; the
 * operating system, architecture, and runtime facts are withheld.
 */
export const platformMetadata = (omit = false): string => (omit ? identity : platformValue);
