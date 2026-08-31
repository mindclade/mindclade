export interface TraceContext {
  readonly traceId: string;
  readonly spanId: string;
}
const trace = /^[0-9a-f]{32}$/;
const span = /^[0-9a-f]{16}$/;
export const traceContext = (traceId: string, spanId: string): TraceContext => {
  if (!trace.test(traceId) || !span.test(spanId))
    throw new Error("trace identifiers must be lowercase hexadecimal");
  return Object.freeze({ traceId, spanId });
};
export interface MetricValue {
  readonly name: string;
  readonly value: number;
}
export const metricValue = (name: string, value: number): MetricValue => {
  if (!/^[a-z][a-z0-9_.-]{0,127}$/.test(name) || !Number.isFinite(value))
    throw new Error("metric value is invalid");
  return Object.freeze({ name, value });
};
