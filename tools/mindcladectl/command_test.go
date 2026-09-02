package mindcladectl

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

type recordedCall struct {
	kind           string
	name           string
	etag           string
	reason         string
	idempotencyKey string
	wait           bool
	hasDeadline    bool
}

type fakeBackend struct {
	calls []recordedCall
	err   error
	data  []byte
	block bool
}

func (backend *fakeBackend) WriteOperation(ctx context.Context, name string, wait bool, writer io.Writer) error {
	_, hasDeadline := ctx.Deadline()
	backend.calls = append(backend.calls, recordedCall{kind: "operation", name: name, wait: wait, hasDeadline: hasDeadline})
	if backend.block {
		<-ctx.Done()
		return ctx.Err()
	}
	if backend.err != nil {
		return backend.err
	}
	_, _ = io.WriteString(writer, "{}\n")
	return nil
}

func (backend *fakeBackend) CancelOperation(ctx context.Context, name, etag, reason, key string, writer io.Writer) error {
	_, hasDeadline := ctx.Deadline()
	backend.calls = append(backend.calls, recordedCall{kind: "cancel", name: name, etag: etag, reason: reason, idempotencyKey: key, hasDeadline: hasDeadline})
	if backend.err != nil {
		return backend.err
	}
	_, _ = io.WriteString(writer, "{}\n")
	return nil
}

func (backend *fakeBackend) DownloadArtifact(ctx context.Context, reference string, writer io.Writer) error {
	_, hasDeadline := ctx.Deadline()
	backend.calls = append(backend.calls, recordedCall{kind: "download", name: reference, hasDeadline: hasDeadline})
	if backend.err != nil {
		return backend.err
	}
	_, err := writer.Write(backend.data)
	return err
}

func (backend *fakeBackend) WriteExperiment(ctx context.Context, name string, writer io.Writer) error {
	_, hasDeadline := ctx.Deadline()
	backend.calls = append(backend.calls, recordedCall{kind: "experiment-get", name: name, hasDeadline: hasDeadline})
	_, _ = io.WriteString(writer, "{}\n")
	return backend.err
}

func (backend *fakeBackend) ListExperiments(ctx context.Context, pageSize uint32, pageToken string, writer io.Writer) error {
	_, hasDeadline := ctx.Deadline()
	backend.calls = append(backend.calls, recordedCall{kind: "experiment-list", name: pageToken, etag: strconv.FormatUint(uint64(pageSize), 10), hasDeadline: hasDeadline})
	_, _ = io.WriteString(writer, "{}\n")
	return backend.err
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
			if got.kind != test.want.kind || got.name != test.want.name || got.etag != test.want.etag || got.reason != test.want.reason || got.idempotencyKey != test.want.idempotencyKey || got.wait != test.want.wait || !got.hasDeadline {
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

func TestArtifactDownloadIsAtomicAndDoesNotOverwrite(t *testing.T) {
	directory := t.TempDir()
	destination := filepath.Join(directory, "artifact.bin")
	backend := &fakeBackend{data: []byte("verified-content")}
	var stdout bytes.Buffer
	application := Application{Backend: backend, Timeout: time.Second}
	arguments := []string{"artifact", "download", "recipes/current", destination}
	if err := application.Run(context.Background(), arguments, &stdout, io.Discard); err != nil {
		t.Fatalf("Run: %v", err)
	}
	// #nosec G304 -- destination is constructed beneath the test-owned TempDir.
	content, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(content) != "verified-content" || stdout.String() != destination+"\n" {
		t.Fatalf("content/output = %q / %q", content, stdout.String())
	}
	if err := application.Run(context.Background(), arguments, io.Discard, io.Discard); err == nil {
		t.Fatal("second download overwrote an existing artifact")
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
	} {
		if err := application.Run(context.Background(), arguments, io.Discard, io.Discard); err == nil {
			t.Fatalf("arguments %q unexpectedly succeeded", arguments)
		}
	}
	if len(backend.calls) != 0 {
		t.Fatalf("invalid commands reached backend: %#v", backend.calls)
	}
}
