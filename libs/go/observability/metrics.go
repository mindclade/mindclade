package observability

import (
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
)

// MaximumMetricAttributes is the per-metric attribute ceiling the Go and Python
// conventions already shared before this package emitted anything.
const MaximumMetricAttributes = 16

// metricNamePattern matches the TypeScript sibling's rule so a metric name is
// spelled identically whichever runtime declares it.
var metricNamePattern = regexp.MustCompile(`^[a-z][a-z0-9_.-]{0,127}$`)

// ForbiddenMetricLabels is the A25.10 cardinality budget expressed as a denylist.
// A25 line 23 states it directly: do not put unbounded IDs, artifact digests,
// sample identities, sequences, or customer identifiers into metric labels. Each
// of these is either unbounded or per-request, so one of them turns a single
// metric into a time series per call.
//
// tenant_id is deliberately absent. Tenants are supplied as an explicit startup
// allowlist, so tenant cardinality is bounded and known before the process
// serves traffic, which is exactly the condition A25.10 requires of a label.
var ForbiddenMetricLabels = map[string]string{
	"request_id":      "one series per request",
	"trace_id":        "one series per trace",
	"span_id":         "one series per span",
	"correlation_id":  "one series per command",
	"causation_id":    "one series per command",
	"idempotency_key": "one series per command",
	"principal":       "unbounded principal identity",
	"principal_id":    "unbounded principal identity",
	"subject":         "unbounded subject identity",
	"digest":          "unbounded artifact digest",
	"etag":            "one series per revision",
	"uid":             "unbounded resource identity",
	"name":            "unbounded resource identity",
	"resource_name":   "unbounded resource identity",
	"sequence":        "unbounded sequence position",
	"offset":          "unbounded stream position",
	"user":            "customer identity",
	"email":           "customer identity",
}

// ErrForbiddenLabel reports an attribute the cardinality budget refuses.
var ErrForbiddenLabel = errors.New("forbidden metric label")

// Metric is the declarative value form retained from the pre-instrumentation
// package. It is the shape a caller validates before recording.
type Metric struct {
	Name       string
	Attributes map[string]string
	Value      float64
}

// Validate enforces the name pattern, the attribute ceiling, the cardinality
// budget, and value finiteness. The Rust sibling already rejected non-finite
// values; Go accepted NaN and infinity, which corrupt a histogram silently.
func (m Metric) Validate() error {
	if !metricNamePattern.MatchString(m.Name) {
		return fmt.Errorf("invalid metric name: %q", m.Name)
	}
	if len(m.Attributes) > MaximumMetricAttributes {
		return fmt.Errorf(
			"metric %s declares %d attributes, above the ceiling of %d",
			m.Name, len(m.Attributes), MaximumMetricAttributes,
		)
	}
	if math.IsNaN(m.Value) || math.IsInf(m.Value, 0) {
		return fmt.Errorf("metric %s has a non-finite value", m.Name)
	}
	return ValidateLabels(m.Name, sortedKeys(m.Attributes))
}

// ValidateLabels applies the cardinality budget to a label set. It is exported so
// instrumentation can be checked at construction time rather than on every record.
func ValidateLabels(metricName string, labels []string) error {
	for _, label := range labels {
		key := strings.ToLower(strings.TrimSpace(label))
		if reason, forbidden := ForbiddenMetricLabels[key]; forbidden {
			return fmt.Errorf(
				"%w: metric %s label %q gives %s",
				ErrForbiddenLabel, metricName, label, reason,
			)
		}
	}
	return nil
}

func sortedKeys(values map[string]string) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// Attributes converts a validated label set into OpenTelemetry attributes.
// It returns an error rather than dropping a forbidden label, so an unsafe
// instrument fails loudly at the call site instead of emitting a narrower series
// than the author believed they were recording.
func Attributes(metricName string, labels map[string]string) ([]attribute.KeyValue, error) {
	if len(labels) > MaximumMetricAttributes {
		return nil, fmt.Errorf(
			"metric %s declares %d attributes, above the ceiling of %d",
			metricName, len(labels), MaximumMetricAttributes,
		)
	}
	if err := ValidateLabels(metricName, sortedKeys(labels)); err != nil {
		return nil, err
	}
	converted := make([]attribute.KeyValue, 0, len(labels))
	for _, key := range sortedKeys(labels) {
		converted = append(converted, attribute.String(key, labels[key]))
	}
	return converted, nil
}

// Meter returns the named meter for a component. Every instrument in the estate
// is created through this so the instrumentation scope is uniform.
func Meter(component string) metric.Meter { return otel.Meter(component) }

// Counter constructs a monotonic counter, refusing a name or label set the
// conventions forbid.
func Counter(component, name, description, unit string, labels ...string) (metric.Int64Counter, error) {
	if !metricNamePattern.MatchString(name) {
		return nil, fmt.Errorf("invalid metric name: %q", name)
	}
	if err := ValidateLabels(name, labels); err != nil {
		return nil, err
	}
	return Meter(component).Int64Counter(
		name,
		metric.WithDescription(description),
		metric.WithUnit(unit),
	)
}

// Histogram constructs a distribution instrument under the same rules. A25.9
// requires a unit on every metric, so it is a required argument rather than an
// option.
func Histogram(component, name, description, unit string, labels ...string) (metric.Float64Histogram, error) {
	if !metricNamePattern.MatchString(name) {
		return nil, fmt.Errorf("invalid metric name: %q", name)
	}
	if err := ValidateLabels(name, labels); err != nil {
		return nil, err
	}
	return Meter(component).Float64Histogram(
		name,
		metric.WithDescription(description),
		metric.WithUnit(unit),
	)
}

// Gauge constructs an asynchronous gauge for a value that is observed rather than
// accumulated, such as queue depth.
func Gauge(component, name, description, unit string, labels ...string) (metric.Int64ObservableGauge, error) {
	if !metricNamePattern.MatchString(name) {
		return nil, fmt.Errorf("invalid metric name: %q", name)
	}
	if err := ValidateLabels(name, labels); err != nil {
		return nil, err
	}
	return Meter(component).Int64ObservableGauge(
		name,
		metric.WithDescription(description),
		metric.WithUnit(unit),
	)
}
