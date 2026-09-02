import {
  decodeDocument,
  type Configuration,
} from "../../../../protocols/generated/typescript/schema/v1/bindings.js";

export type ConfigValue =
  | boolean
  | number
  | string
  | readonly ConfigValue[]
  | { readonly [key: string]: ConfigValue };
export interface ConfigLayer {
  readonly precedence: number;
  readonly source: string;
  readonly values: Readonly<Record<string, ConfigValue>>;
}
export interface Resolution {
  readonly values: Readonly<Record<string, ConfigValue>>;
  readonly provenance: Readonly<Record<string, string>>;
  readonly redacted: Readonly<Record<string, ConfigValue>>;
}
const isObjectMap = (value: ConfigValue): value is { readonly [key: string]: ConfigValue } =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const ordered = (value: ConfigValue): ConfigValue => {
  if (Array.isArray(value)) return value.map(ordered);
  if (!isObjectMap(value)) return value;
  const entries = Object.entries(value).sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  return Object.fromEntries(entries.map(([key, entry]) => [key, ordered(entry)]));
};
export const resolve = (
  layers: readonly ConfigLayer[],
  sensitive: ReadonlySet<string>,
): Resolution => {
  const sorted = [...layers].sort((a, b) => a.precedence - b.precedence);
  if (
    sorted.some((layer, index) => index > 0 && layer.precedence === sorted[index - 1]?.precedence)
  )
    throw new Error("configuration precedence must be unique");
  const values: Record<string, ConfigValue> = {};
  const provenance: Record<string, string> = {};
  for (const layer of sorted)
    for (const [key, value] of Object.entries(layer.values)) {
      values[key] = ordered(value);
      provenance[key] = layer.source;
    }
  const redacted = Object.fromEntries(
    Object.entries(values).map(([key, value]) => [
      key,
      sensitive.has(key) ? { redacted: true } : value,
    ]),
  );
  return {
    values: ordered(values) as Record<string, ConfigValue>,
    provenance: ordered(provenance) as Record<string, string>,
    redacted: ordered(redacted) as Record<string, ConfigValue>,
  };
};

/**
 * Validate and narrow a durable configuration document through the generated
 * JSON Schema binding. Configuration resolution remains handwritten behavior;
 * the persisted document shape is not redefined here.
 */
export const validateConfigurationDocument = (document: unknown): Configuration =>
  decodeDocument("configuration", document);
