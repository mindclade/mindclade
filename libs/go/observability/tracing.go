// Package observability carries the Go half of the shared telemetry conventions
// required by Appendix A25. It owns context propagation, the structured log
// vocabulary, and the bounded-cardinality metric surface. It deliberately emits
// nothing on its own: per A25.5 the authority order is durable state, then
// events, then telemetry, so a telemetry failure must never be able to change
// business state.
//
// A18.28 places this wiring in servicekit for Go services. servicekit's
// lifecycle, health and shutdown files are declared at activation wave 4 and
// must not be created early, so the conventions live here at wave 1 and move
// when that wave activates.
package observability

import (
	"context"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	oteltrace "go.opentelemetry.io/otel/trace"
)

type (
	traceKey      struct{}
	requestKey    struct{}
	TraceID       string
	RequestID     string
	CorrelationID string
)

// TraceIDLength and SpanIDLength are the W3C trace-context hex widths. The Rust
// and TypeScript siblings validate these; the Go package did not, which let a
// malformed identifier reach a log line where the other languages would refuse
// it. Divergence between the four packages is itself a defect.
const (
	TraceIDLength = 32
	SpanIDLength  = 16
)

// ValidTraceID reports whether id is lowercase hex of the W3C width and is not
// the all-zero identifier, which the specification reserves as "no trace".
func ValidTraceID(id string) bool { return validHex(id, TraceIDLength) }

// ValidSpanID applies the same rule at span width.
func ValidSpanID(id string) bool { return validHex(id, SpanIDLength) }

func validHex(value string, width int) bool {
	if len(value) != width {
		return false
	}
	zero := true
	for i := 0; i < len(value); i++ {
		c := value[i]
		switch {
		case c >= '0' && c <= '9':
			zero = zero && c == '0'
		case c >= 'a' && c <= 'f':
			zero = false
		default:
			return false
		}
	}
	return !zero
}

// WithTrace binds a trace identifier to the context. An identifier that is not a
// valid W3C trace ID is rejected rather than stored, so a downstream reader
// never has to decide whether what it found is trustworthy.
func WithTrace(c context.Context, id TraceID) context.Context {
	if !ValidTraceID(string(id)) {
		return c
	}
	return context.WithValue(c, traceKey{}, id)
}

// TraceFrom returns the bound trace identifier. It prefers an active OpenTelemetry
// span, so a trace started by the gRPC or HTTP instrumentation is reported even
// when nothing called WithTrace.
func TraceFrom(c context.Context) (TraceID, bool) {
	if span := oteltrace.SpanContextFromContext(c); span.HasTraceID() {
		return TraceID(span.TraceID().String()), true
	}
	v, ok := c.Value(traceKey{}).(TraceID)
	return v, ok && v != ""
}

// WithRequestID binds the CommandContext request identifier. Unlike the trace ID
// this is an opaque application value, so it is bounded rather than pattern-checked.
func WithRequestID(c context.Context, id RequestID) context.Context {
	if id == "" || len(id) > 128 {
		return c
	}
	return context.WithValue(c, requestKey{}, id)
}

// RequestIDFrom returns the bound request identifier.
func RequestIDFrom(c context.Context) (RequestID, bool) {
	v, ok := c.Value(requestKey{}).(RequestID)
	return v, ok && v != ""
}

// Propagator is the wire format for trace context across RPC and event
// boundaries, which §7.13 requires. W3C trace context plus baggage is the
// OpenTelemetry default and the only format the other three language runtimes
// are specified to read.
func Propagator() propagation.TextMapPropagator {
	return propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	)
}

// InstallPropagator sets the process-wide propagator. Call it once during
// startup, before any client or server is constructed.
func InstallPropagator() { otel.SetTextMapPropagator(Propagator()) }

// NormalizeTraceID lowercases and trims a trace identifier received from an
// untrusted header before validation, matching how the gateway accepts x-trace-id.
func NormalizeTraceID(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}
