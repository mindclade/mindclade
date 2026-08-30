from dataclasses import dataclass


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
