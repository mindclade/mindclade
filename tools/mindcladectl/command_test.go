package mindcladectl

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"iter"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/mindclade/mindclade/internal/sdk/go/mindclade"
)

type recordedCall struct {
	kind           string
	name           string
	etag           string
	reason         string
	idempotencyKey string
	destination    string
	wait           bool
	hasDeadline    bool
	list           ListRequest
}

// message builds a protobuf-runtime message that stands in for the generated
// message an SDK call returns. It is a well-known runtime type, not a
// hand-written parallel model of any protocol resource.
func message(t *testing.T, label string) ProtoMessage {
	t.Helper()
	value, err := structpb.NewStruct(map[string]any{"name": label})
	if err != nil {
		t.Fatalf("structpb.NewStruct: %v", err)
	}
	return value
}

// sdkError obtains a real, fully-populated error from the SDK hierarchy by
// driving the SDK's own classifier. The Go SDK exports no constructor for its
// typed errors and their zero values are unusable (the embedded carrier is
// nil), so the only consumer-reachable classifier is Paginate's normalization
// of a fetch failure. The status value is INPUT to the SDK; the CLI itself
// never inspects a gRPC status.
func sdkError(t *testing.T, code codes.Code) error {
	t.Helper()
	for _, err := range mindclade.Paginate(
		context.Background(),
		"",
		mindclade.PaginationLimits{},
		func(context.Context, string) (mindclade.Page[ProtoMessage], error) {
			return mindclade.Page[ProtoMessage]{}, status.Error(code, "server-authored detail")
		},
	) {
		if err != nil {
			return err
		}
	}
	t.Fatalf("Paginate yielded no classified error for %v", code)
	return nil
}

type fakeBackend struct {
	calls    []recordedCall
	err      error
	block    bool
	reply    Reply
	listing  Listing
	listErr  error
	response mindclade.ResponseMetadata
	captured bool
}

func (backend *fakeBackend) record(ctx context.Context, call recordedCall) {
	_, call.hasDeadline = ctx.Deadline()
	backend.calls = append(backend.calls, call)
}

func (backend *fakeBackend) respond(message ProtoMessage) Reply {
	reply := backend.reply
	if reply.Message == nil {
		reply.Message = message
	}
	if !reply.Captured {
		reply.Response, reply.Captured = backend.response, backend.captured
	}
	return reply
}

func (backend *fakeBackend) GetOperation(ctx context.Context, name string, wait bool) (Reply, error) {
	backend.record(ctx, recordedCall{kind: "operation", name: name, wait: wait})
	if backend.block {
		<-ctx.Done()
		return Reply{}, ctx.Err()
	}
	if backend.err != nil {
		return Reply{}, backend.err
	}
	return backend.respond(nil), nil
}

func (backend *fakeBackend) CancelOperation(ctx context.Context, name, etag, reason, key string) (Reply, error) {
	backend.record(ctx, recordedCall{kind: "cancel", name: name, etag: etag, reason: reason, idempotencyKey: key})
	if backend.err != nil {
		return Reply{}, backend.err
	}
	return backend.respond(nil), nil
}

func (backend *fakeBackend) DownloadArtifact(ctx context.Context, reference, destination string) (Reply, error) {
	backend.record(ctx, recordedCall{kind: "download", name: reference, destination: destination})
	if backend.err != nil {
		return Reply{}, backend.err
	}
	return backend.respond(nil), nil
}

func (backend *fakeBackend) GetExperiment(ctx context.Context, name string) (Reply, error) {
	backend.record(ctx, recordedCall{kind: "experiment-get", name: name})
	if backend.err != nil {
		return Reply{}, backend.err
	}
	return backend.respond(nil), nil
}

func (backend *fakeBackend) ListExperiments(ctx context.Context, request ListRequest) (Listing, error) {
	backend.record(ctx, recordedCall{kind: "experiment-list", name: request.PageToken, etag: strconv.FormatInt(int64(request.PageSize), 10), list: request})
	if backend.listErr != nil {
		return Listing{}, backend.listErr
	}
	if backend.err != nil {
		return Listing{}, backend.err
	}
	listing := backend.listing
	if !listing.Captured {
		listing.Response, listing.Captured = backend.response, backend.captured
	}
	return listing, nil
}

func (*fakeBackend) Close() error { return nil }

func TestApplicationRoutesBoundedSDKWorkflows(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want recordedCall
	}{
		{name: "get", args: []string{"operation", "get", "operations/op-1"}, want: recordedCall{kind: "operation", name: "operations/op-1"}},
		{name: "wait", args: []string{"operation", "wait", "operations/op-1"}, want: recordedCall{kind: "operation", name: "operations/op-1", wait: true}},
		{name: "cancel", args: []string{"operation", "cancel", "operations/op-1", "--etag", "etag-1", "--reason", "operator-request", "--idempotency-key", "cancel-op-1"}, want: recordedCall{kind: "cancel", name: "operations/op-1", etag: "etag-1", reason: "operator-request", idempotencyKey: "cancel-op-1"}},
		{name: "download", args: []string{"artifact", "download", "recipes/current", "/tmp/recipe.json"}, want: recordedCall{kind: "download", name: "recipes/current", destination: "/tmp/recipe.json"}},
		{name: "experiment-get", args: []string{"experiment", "get", "tenants/t-1/projects/p-1/experiments/e-1"}, want: recordedCall{kind: "experiment-get", name: "tenants/t-1/projects/p-1/experiments/e-1"}},
		{name: "experiment-list", args: []string{"experiment", "list", "--page-size", "25", "--page-token", "opaque"}, want: recordedCall{kind: "experiment-list", name: "opaque", etag: "25"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			backend := &fakeBackend{}
			var stdout, stderr bytes.Buffer
			application := Application{Backend: backend, Timeout: time.Second}
			if err := application.Run(context.Background(), test.args, &stdout, &stderr); err != nil {
				t.Fatalf("Run: %v", err)
			}
			if len(backend.calls) != 1 {
				t.Fatalf("calls = %#v", backend.calls)
			}
			got := backend.calls[0]
			if got.kind != test.want.kind || got.name != test.want.name || got.etag != test.want.etag || got.reason != test.want.reason || got.idempotencyKey != test.want.idempotencyKey || got.destination != test.want.destination || got.wait != test.want.wait || !got.hasDeadline {
				t.Fatalf("call = %#v, want %#v with deadline", got, test.want)
			}
		})
	}
}

func TestApplicationPropagatesCancellationAndBackendErrors(t *testing.T) {
	t.Run("cancellation", func(t *testing.T) {
		backend := &fakeBackend{block: true}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		err := (Application{Backend: backend, Timeout: time.Second}).Run(ctx, []string{"operation", "get", "operations/op-1"}, io.Discard, io.Discard)
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context cancellation", err)
		}
	})
	t.Run("backend", func(t *testing.T) {
		failure := errors.New("safe sdk failure")
		backend := &fakeBackend{err: failure}
		err := (Application{Backend: backend, Timeout: time.Second}).Run(context.Background(), []string{"operation", "get", "operations/op-1"}, io.Discard, io.Discard)
		if !errors.Is(err, failure) {
			t.Fatalf("error = %v, want backend error", err)
		}
	})
}

// TestArtifactDownloadDelegatesPublicationToTheSDK pins the removal of the
// CLI's own staging/link/no-clobber reimplementation: the destination path is
// forwarded verbatim to the SDK, nothing is staged locally, and the SDK's
// conflict error is what an existing destination produces.
func TestArtifactDownloadDelegatesPublicationToTheSDK(t *testing.T) {
	directory := t.TempDir()
	destination := directory + "/artifact.bin"
	backend := &fakeBackend{}
	var stdout, stderr bytes.Buffer
	application := Application{Backend: backend, Timeout: time.Second}
	arguments := []string{"artifact", "download", "recipes/current", destination}
	if err := application.Run(context.Background(), arguments, &stdout, &stderr); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(backend.calls) != 1 || backend.calls[0].destination != destination {
		t.Fatalf("calls = %#v, want the destination path forwarded to the SDK", backend.calls)
	}
	if stdout.String() != destination+"\n" {
		t.Fatalf("stdout = %q", stdout.String())
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatalf("ReadDir: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("CLI staged files of its own: %v", entries)
	}
	conflict := sdkError(t, codes.AlreadyExists)
	refusing := &fakeBackend{err: conflict}
	err = (Application{Backend: refusing, Timeout: time.Second}).Run(context.Background(), arguments, io.Discard, io.Discard)
	var conflictError *mindclade.ConflictError
	if !errors.As(err, &conflictError) {
		t.Fatalf("error = %v, want the SDK conflict for an existing destination", err)
	}
	if code := ExitCodeFor(err); code != ExitConflict {
		t.Fatalf("exit code = %d, want %d", code, ExitConflict)
	}
}

func TestCommandValidationFailsBeforeCallingSDK(t *testing.T) {
	backend := &fakeBackend{}
	application := Application{Backend: backend, Timeout: time.Second}
	for _, arguments := range [][]string{
		{},
		{"unknown"},
		{"operation", "cancel", "operations/op-1", "--etag", "etag-1"},
		{"artifact", "download", "only-one-argument"},
		{"experiment", "list", "positional"},
		{"experiment", "list", "--page-size", "-1"},
		{"experiment", "list", "--max-items", "5"},
		{"experiment", "list", "--all", "--page-token", "opaque"},
	} {
		if err := application.Run(context.Background(), arguments, io.Discard, io.Discard); err == nil {
			t.Fatalf("arguments %q unexpectedly succeeded", arguments)
		}
	}
	if len(backend.calls) != 0 {
		t.Fatalf("invalid commands reached backend: %#v", backend.calls)
	}
}

// TestExperimentListSinglePageReportsTheSDKCursor pins the default listing
// shape: the SDK page's own generated response is the unit of output and the
// opaque cursor is reported for resumption rather than reconstructed.
func TestExperimentListSinglePageReportsTheSDKCursor(t *testing.T) {
	backend := &fakeBackend{listing: Listing{
		Page:          message(t, "page-1"),
		NextPageToken: "opaque-next",
		HasNextPage:   true,
	}}
	var stdout, stderr bytes.Buffer
	application := Application{Backend: backend, Timeout: time.Second}
	if err := application.Run(context.Background(), []string{"experiment", "list"}, &stdout, &stderr); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(stdout.String(), `"name":"page-1"`) {
		t.Fatalf("stdout = %q, want the generated page response", stdout.String())
	}
	if !strings.Contains(stderr.String(), "--page-token opaque-next") {
		t.Fatalf("stderr = %q, want the opaque cursor reported", stderr.String())
	}
	if got := backend.calls[0].list; got.AllPages || got.PageToken != "" || got.PageSize != 50 {
		t.Fatalf("list request = %#v", got)
	}
}

// TestExperimentListAllUsesTheSDKPageTraversal pins that --all walks the SDK
// page's own item sequence, and that the traversal budget the operator asked
// for is handed to the SDK as PaginationLimits rather than enforced by a
// consumer-side page loop.
func TestExperimentListAllUsesTheSDKPageTraversal(t *testing.T) {
	items := []ProtoMessage{message(t, "e-1"), message(t, "e-2"), message(t, "e-3")}
	backend := &fakeBackend{listing: Listing{
		Page:        message(t, "page-1"),
		HasNextPage: true,
		Traverse: func(yield func(ProtoMessage, error) bool) {
			for _, item := range items {
				if !yield(item, nil) {
					return
				}
			}
		},
	}}
	var stdout, stderr bytes.Buffer
	application := Application{Backend: backend, Timeout: time.Second}
	arguments := []string{"experiment", "list", "--all", "--max-pages", "7", "--max-items", "70"}
	if err := application.Run(context.Background(), arguments, &stdout, &stderr); err != nil {
		t.Fatalf("Run: %v", err)
	}
	lines := strings.Split(strings.TrimSuffix(stdout.String(), "\n"), "\n")
	if len(lines) != 3 {
		t.Fatalf("stdout = %q, want one line per traversed item", stdout.String())
	}
	for index, want := range []string{"e-1", "e-2", "e-3"} {
		if !strings.Contains(lines[index], `"name":"`+want+`"`) {
			t.Fatalf("line %d = %q, want %q", index, lines[index], want)
		}
	}
	if strings.Contains(stdout.String(), "page-1") {
		t.Fatalf("stdout = %q, want items rather than the page envelope under --all", stdout.String())
	}
	got := backend.calls[0].list
	if !got.AllPages || got.Limits != (mindclade.PaginationLimits{MaxPages: 7, MaxItems: 70}) {
		t.Fatalf("list request = %#v, want the SDK traversal budget forwarded", got)
	}
}

// TestExperimentListAllSurfacesTraversalErrors pins that a failure reported
// part-way through the SDK traversal ends the command instead of being retried
// or swallowed; retry remains the SDK's.
func TestExperimentListAllSurfacesTraversalErrors(t *testing.T) {
	failure := sdkError(t, codes.Unavailable)
	backend := &fakeBackend{listing: Listing{
		Page: message(t, "page-1"),
		Traverse: func(yield func(ProtoMessage, error) bool) {
			if !yield(message(t, "e-1"), nil) {
				return
			}
			var zero ProtoMessage
			yield(zero, failure)
		},
	}}
	var stdout bytes.Buffer
	err := (Application{Backend: backend, Timeout: time.Second}).Run(
		context.Background(), []string{"experiment", "list", "--all"}, &stdout, io.Discard,
	)
	var retryable *mindclade.RetryableServiceError
	if !errors.As(err, &retryable) {
		t.Fatalf("error = %v, want the SDK traversal failure", err)
	}
	if !strings.Contains(stdout.String(), `"name":"e-1"`) {
		t.Fatalf("stdout = %q, want the items emitted before the failure", stdout.String())
	}
	if code := ExitCodeFor(err); code != ExitUnavailable {
		t.Fatalf("exit code = %d, want %d", code, ExitUnavailable)
	}
}

// TestSuccessfulOperationReportsTheRequestID pins request-id-on-success: the
// identity the SDK captured through its raw-response accessor reaches the
// operator on stderr, and stdout stays the machine-readable generated message.
func TestSuccessfulOperationReportsTheRequestID(t *testing.T) {
	for _, arguments := range [][]string{
		{"operation", "get", "operations/op-1"},
		{"operation", "wait", "operations/op-1"},
		{"operation", "cancel", "operations/op-1", "--etag", "e1", "--reason", "operator-request", "--idempotency-key", "k1"},
	} {
		backend := &fakeBackend{
			reply: Reply{
				Message:  message(t, "operations/op-1"),
				Response: mindclade.ResponseMetadata{Status: mindclade.Code("ok"), RequestID: "req-77", TraceID: "trace-88"},
				Captured: true,
			},
		}
		var stdout, stderr bytes.Buffer
		if err := (Application{Backend: backend, Timeout: time.Second}).Run(context.Background(), arguments, &stdout, &stderr); err != nil {
			t.Fatalf("Run %q: %v", arguments, err)
		}
		if !strings.Contains(stderr.String(), "request_id=req-77") || !strings.Contains(stderr.String(), "trace_id=trace-88") || !strings.Contains(stderr.String(), "status=ok") {
			t.Fatalf("stderr = %q, want the captured transport identity", stderr.String())
		}
		if strings.Contains(stdout.String(), "req-77") {
			t.Fatalf("stdout = %q, want the identity kept out of the machine-readable stream", stdout.String())
		}
		if !strings.Contains(stdout.String(), `"name":"operations/op-1"`) {
			t.Fatalf("stdout = %q, want the generated operation", stdout.String())
		}
	}
}

func TestUncapturedResponseReportsNoIdentity(t *testing.T) {
	backend := &fakeBackend{reply: Reply{Message: message(t, "operations/op-1")}}
	var stdout, stderr bytes.Buffer
	if err := (Application{Backend: backend, Timeout: time.Second}).Run(
		context.Background(), []string{"operation", "get", "operations/op-1"}, &stdout, &stderr,
	); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stderr.Len() != 0 {
		t.Fatalf("stderr = %q, want nothing when the call never reached the transport", stderr.String())
	}
}

// TestExitCodeDiscriminatesTheSDKErrorHierarchy pins that every published SDK
// error class reaches a distinct operator-visible outcome through errors.As.
func TestExitCodeDiscriminatesTheSDKErrorHierarchy(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want int
	}{
		{name: "nil", err: nil, want: ExitSuccess},
		{name: "authentication", err: sdkError(t, codes.Unauthenticated), want: ExitUnauthenticated},
		{name: "authorization", err: sdkError(t, codes.PermissionDenied), want: ExitPermissionDenied},
		{name: "validation", err: sdkError(t, codes.InvalidArgument), want: ExitInvalidRequest},
		{name: "out-of-range", err: sdkError(t, codes.OutOfRange), want: ExitInvalidRequest},
		{name: "not-found", err: sdkError(t, codes.NotFound), want: ExitNotFound},
		{name: "conflict", err: sdkError(t, codes.Aborted), want: ExitConflict},
		{name: "already-exists", err: sdkError(t, codes.AlreadyExists), want: ExitConflict},
		{name: "failed-precondition", err: sdkError(t, codes.FailedPrecondition), want: ExitConflict},
		{name: "quota", err: sdkError(t, codes.ResourceExhausted), want: ExitThrottled},
		{name: "retryable", err: sdkError(t, codes.Unavailable), want: ExitUnavailable},
		{name: "transport", err: sdkError(t, codes.Internal), want: ExitUnavailable},
		{name: "unimplemented", err: sdkError(t, codes.Unimplemented), want: ExitUnavailable},
		{name: "cancelled", err: sdkError(t, codes.Canceled), want: ExitCancelled},
		{name: "sdk-deadline", err: sdkError(t, codes.DeadlineExceeded), want: ExitDeadlineExceeded},
		{name: "operation-failed", err: &mindclade.OperationError{}, want: ExitOperationFailed},
		{name: "wrapped", err: fmt.Errorf("mindcladectl: %w", sdkError(t, codes.NotFound)), want: ExitNotFound},
		{name: "context-deadline", err: context.DeadlineExceeded, want: ExitDeadlineExceeded},
		{name: "context-cancelled", err: context.Canceled, want: ExitCancelled},
		{name: "local", err: errors.New("mindcladectl: parse artifact download"), want: ExitFailure},
	}
	seen := map[int]string{}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := ExitCodeFor(test.err); got != test.want {
				t.Fatalf("ExitCodeFor(%v) = %d, want %d", test.err, got, test.want)
			}
		})
		seen[test.want] = test.name
	}
	// Every declared exit code except ExitUsage, which belongs to the process
	// entry point rather than to a command failure, must be reachable.
	if len(seen) != 12 {
		t.Fatalf("distinct exit codes = %d (%v), want every SDK error class discriminated", len(seen), seen)
	}
	if _, reachable := seen[ExitUsage]; reachable {
		t.Fatal("ExitUsage must not be produced by SDK error classification")
	}
}

// TestErrorDiagnosticsComeFromTheSDKHierarchy pins that the operator-facing
// failure detail is read back through the SDK error contract rather than
// re-derived, and that a non-SDK failure prints nothing.
func TestErrorDiagnosticsComeFromTheSDKHierarchy(t *testing.T) {
	var buffer bytes.Buffer
	WriteErrorDiagnostics(&buffer, errors.New("a local parse failure"))
	if buffer.Len() != 0 {
		t.Fatalf("diagnostics = %q, want nothing for a non-SDK failure", buffer.String())
	}
	sdkError := &mindclade.Error{
		Code:                mindclade.CodeResourceExhausted,
		Message:             "quota exhausted",
		RequestID:           "req-9",
		TraceID:             "trace-9",
		OperationID:         "op-9",
		Retry:               mindclade.RetryAfterReconciliation,
		RetryAfter:          2 * time.Second,
		Attempts:            4,
		CumulativeDelay:     900 * time.Millisecond,
		ConflictRevision:    "etag-9",
		DiagnosticReference: "runbook/quota",
		Quota:               &mindclade.QuotaState{Subject: "training-gpu", Remaining: 0},
	}
	buffer.Reset()
	WriteErrorDiagnostics(&buffer, fmt.Errorf("mindcladectl: %w", sdkError))
	rendered := buffer.String()
	for _, want := range []string{
		"code=resource_exhausted", "retry=after_reconciliation", "request_id=req-9", "trace_id=trace-9",
		"operation_id=op-9", "retry_after=2s", "revision=etag-9", "attempts=4", "retry_delay=900ms",
		"quota_subject=training-gpu", "quota_remaining=0", "diagnostic=runbook/quota",
	} {
		if !strings.Contains(rendered, want) {
			t.Fatalf("diagnostics = %q, want %q", rendered, want)
		}
	}
	if strings.Contains(rendered, "quota exhausted") {
		t.Fatalf("diagnostics = %q, want structured detail only", rendered)
	}
}

// TestPaginationLimitsAreTheSDKType pins that the CLI never invents its own
// traversal budget: what --max-pages/--max-items produce is the SDK's own
// PaginationLimits, whose zero value selects the SDK defaults.
func TestPaginationLimitsAreTheSDKType(t *testing.T) {
	backend := &fakeBackend{listing: Listing{Page: message(t, "page-1"), Traverse: emptyTraversal()}}
	if err := (Application{Backend: backend, Timeout: time.Second}).Run(
		context.Background(), []string{"experiment", "list", "--all"}, io.Discard, io.Discard,
	); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got := backend.calls[0].list.Limits; got != (mindclade.PaginationLimits{}) {
		t.Fatalf("limits = %#v, want the SDK defaults left unset", got)
	}
}

func emptyTraversal() iter.Seq2[ProtoMessage, error] {
	return func(func(ProtoMessage, error) bool) {}
}
