package observability

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
	"time"
)

// LogEnvironmentVariable selects the level, matching the variable the Go, Python
// and TypeScript SDKs already read so one setting governs the whole estate.
const LogEnvironmentVariable = "MINDCLADE_LOG"

// ForbiddenLogFields refuses the payload classes A25.4 prohibits from telemetry:
// raw biological sequences, structure payloads, model weights, credentials and
// signed URLs, restricted dataset contents, and full user prompts. The SDKs
// achieve this by construction — they can only ever log metadata key names — but
// a service handler takes arbitrary attributes, so the rule needs a guard here.
//
// A field named in this list is replaced with a redaction marker rather than
// dropped, so a reviewer reading the log can see that something was withheld.
var ForbiddenLogFields = map[string]struct{}{
	"authorization": {}, "access_token": {}, "id_token": {}, "refresh_token": {},
	"token": {}, "secret": {}, "password": {}, "credential": {}, "credentials": {},
	"signed_url": {}, "presigned_url": {}, "private_key": {}, "lease_token": {},
	"sequence_data": {}, "structure": {}, "weights": {}, "checkpoint_bytes": {},
	"prompt": {}, "payload": {}, "response_body": {}, "request_body": {},
}

// RedactionMarker replaces a forbidden field's value.
const RedactionMarker = "[redacted]"

// Level reports the configured level. The second result is false when logging is
// disabled outright, which the SDKs spell "off" or "none" — an unrecognised value
// disables logging rather than silently defaulting, so a typo cannot quietly
// widen what is emitted.
func Level() (slog.Level, bool) {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(LogEnvironmentVariable))) {
	case "debug":
		return slog.LevelDebug, true
	case "", "info":
		return slog.LevelInfo, true
	case "warn", "warning":
		return slog.LevelWarn, true
	case "error":
		return slog.LevelError, true
	case "off", "none":
		return slog.LevelError, false
	default:
		return slog.LevelError, false
	}
}

// contextHandler binds correlation identifiers from the context onto every record
// and applies the redaction guard. Correlation is read at emit time rather than
// required at each call site, because a call site that has to remember is a call
// site that will eventually forget.
type contextHandler struct {
	inner     slog.Handler
	component string
}

func (h contextHandler) Enabled(c context.Context, level slog.Level) bool {
	return h.inner.Enabled(c, level)
}

func (h contextHandler) Handle(c context.Context, record slog.Record) error {
	enriched := slog.NewRecord(
		record.Time.UTC(),
		record.Level,
		record.Message,
		record.PC,
	)
	enriched.AddAttrs(slog.String("component", h.component))
	if trace, ok := TraceFrom(c); ok {
		enriched.AddAttrs(slog.String("trace_id", string(trace)))
	}
	if request, ok := RequestIDFrom(c); ok {
		enriched.AddAttrs(slog.String("request_id", string(request)))
	}
	record.Attrs(func(attr slog.Attr) bool {
		enriched.AddAttrs(redact(attr))
		return true
	})
	return h.inner.Handle(c, enriched)
}

func (h contextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	guarded := make([]slog.Attr, 0, len(attrs))
	for _, attr := range attrs {
		guarded = append(guarded, redact(attr))
	}
	return contextHandler{inner: h.inner.WithAttrs(guarded), component: h.component}
}

func (h contextHandler) WithGroup(name string) slog.Handler {
	return contextHandler{inner: h.inner.WithGroup(name), component: h.component}
}

func redact(attr slog.Attr) slog.Attr {
	if _, forbidden := ForbiddenLogFields[strings.ToLower(attr.Key)]; forbidden {
		return slog.String(attr.Key, RedactionMarker)
	}
	return attr
}

// NewHandler builds the estate's structured handler: JSON lines with UTC
// timestamps, carrying the component and whatever correlation the context holds.
func NewHandler(writer io.Writer, level slog.Level, component string) slog.Handler {
	return contextHandler{
		component: component,
		inner: slog.NewJSONHandler(writer, &slog.HandlerOptions{
			Level: level,
			ReplaceAttr: func(_ []string, attr slog.Attr) slog.Attr {
				if attr.Key == slog.TimeKey {
					return slog.String("timestamp", attr.Value.Time().UTC().Format(time.RFC3339Nano))
				}
				return attr
			},
		}),
	}
}

// Install makes the structured handler the process default. Services call this
// once at startup; until they do, Go's default text handler is what emits, which
// is neither structured nor correlated.
//
// When logging is disabled the default is set to a handler that discards, so a
// call site never has to check whether logging is on.
func Install(component string) {
	level, enabled := Level()
	if !enabled {
		slog.SetDefault(slog.New(slog.NewJSONHandler(io.Discard, &slog.HandlerOptions{
			Level: slog.LevelError + 1,
		})))
		return
	}
	slog.SetDefault(slog.New(NewHandler(os.Stderr, level, component)))
}
