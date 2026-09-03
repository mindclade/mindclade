package storage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
)

type fakeImmutableBackend struct {
	mu          sync.Mutex
	objects     map[string][]byte
	generations map[string]int64
	createCalls int
	createErr   error
	closed      bool
}

func newFakeImmutableBackend() *fakeImmutableBackend {
	return &fakeImmutableBackend{objects: map[string][]byte{}, generations: map[string]int64{}}
}

func (b *fakeImmutableBackend) Create(_ context.Context, name string, source io.Reader, _ int64, _ uint32) (objectAttributes, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.createCalls++
	if b.createErr != nil {
		return objectAttributes{}, b.createErr
	}
	if _, ok := b.objects[name]; ok {
		return objectAttributes{}, errObjectExists
	}
	content, err := io.ReadAll(source)
	if err != nil {
		return objectAttributes{}, err
	}
	b.generations[name]++
	b.objects[name] = append([]byte(nil), content...)
	return objectAttributes{Size: int64(len(content)), Generation: b.generations[name]}, nil
}

func (b *fakeImmutableBackend) Open(_ context.Context, name string) (io.ReadCloser, objectAttributes, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	content, ok := b.objects[name]
	if !ok {
		return nil, objectAttributes{}, ErrObjectNotFound
	}
	copyContent := append([]byte(nil), content...)
	return io.NopCloser(bytes.NewReader(copyContent)), objectAttributes{Size: int64(len(copyContent)), Generation: b.generations[name]}, nil
}

func (b *fakeImmutableBackend) OpenGeneration(_ context.Context, name string, generation, offset int64) (io.ReadCloser, objectAttributes, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	content, ok := b.objects[name]
	if !ok {
		return nil, objectAttributes{}, ErrObjectNotFound
	}
	if b.generations[name] != generation {
		return nil, objectAttributes{}, ErrGenerationMismatch
	}
	if offset < 0 || offset > int64(len(content)) {
		return nil, objectAttributes{}, ErrSizeMismatch
	}
	copyContent := append([]byte(nil), content[offset:]...)
	return io.NopCloser(bytes.NewReader(copyContent)), objectAttributes{Size: int64(len(content)), Generation: generation}, nil
}

func (b *fakeImmutableBackend) Compose(_ context.Context, name string, sources []objectSource) (objectAttributes, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if _, ok := b.objects[name]; ok {
		return objectAttributes{}, errObjectExists
	}
	content := make([]byte, 0)
	for _, source := range sources {
		value, ok := b.objects[source.name]
		if !ok {
			return objectAttributes{}, ErrObjectNotFound
		}
		if b.generations[source.name] != source.generation {
			return objectAttributes{}, ErrGenerationMismatch
		}
		content = append(content, value...)
	}
	b.generations[name]++
	b.objects[name] = content
	return objectAttributes{Size: int64(len(content)), Generation: b.generations[name]}, nil
}

func (b *fakeImmutableBackend) Delete(_ context.Context, name string, generation int64) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if _, ok := b.objects[name]; !ok {
		return ErrObjectNotFound
	}
	if b.generations[name] != generation {
		return ErrGenerationMismatch
	}
	delete(b.objects, name)
	delete(b.generations, name)
	return nil
}

func (b *fakeImmutableBackend) Close() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.closed = true
	return nil
}

func (b *fakeImmutableBackend) Ready(context.Context) error { return b.createErr }

func testDigest(content []byte) string {
	value := sha256.Sum256(content)
	return "sha256:" + hex.EncodeToString(value[:])
}

func newTestGCSStore(t *testing.T, backend *fakeImmutableBackend, max int64) *GCSObjectStore {
	t.Helper()
	config := GCSConfig{Bucket: "unused-fake", Prefix: "artifacts/v1", StagingDirectory: t.TempDir(), MaxObjectBytes: max, ChunkSize: 256 << 10}
	if err := validateGCSConfig(&config); err != nil {
		t.Fatalf("validate config: %v", err)
	}
	return newGCSObjectStore(backend, config)
}

func TestGCSObjectStoreImmutableIdempotentPutAndVerifiedOpen(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	store := newTestGCSStore(t, backend, 1024)
	content := []byte("authoritative artifact bytes")
	digest := testDigest(content)

	first, err := store.Put(context.Background(), "tenant/customer-visible", digest, int64(len(content)), bytes.NewReader(content))
	if err != nil {
		t.Fatalf("first put: %v", err)
	}
	second, err := store.Put(context.Background(), "tenant/customer-visible", digest, int64(len(content)), bytes.NewReader(content))
	if err != nil {
		t.Fatalf("idempotent retry: %v", err)
	}
	if first != second || first.Generation == 0 || backend.createCalls != 2 {
		t.Fatalf("unexpected idempotent result: first=%+v second=%+v calls=%d", first, second, backend.createCalls)
	}
	for name := range backend.objects {
		if strings.Contains(name, "tenant/customer-visible") || !strings.Contains(name, "/sha256/") || !strings.HasSuffix(name, strings.TrimPrefix(digest, "sha256:")) {
			t.Fatalf("object name is not tenant-safe content addressing: %q", name)
		}
	}
	reader, err := store.Open(context.Background(), first.TenantID, first.Digest)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	read, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("verified read: %v", err)
	}
	if err = reader.Close(); err != nil {
		t.Fatalf("verified close: %v", err)
	}
	if !bytes.Equal(read, content) {
		t.Fatalf("content mismatch: %q", read)
	}
	if err = store.Close(); err != nil || !backend.closed {
		t.Fatalf("close did not reach backend: err=%v closed=%v", err, backend.closed)
	}
	if err = store.Ready(context.Background()); err != nil {
		t.Fatalf("ready: %v", err)
	}
}

func TestGCSObjectStoreFailsClosedBeforePublishingInvalidBytes(t *testing.T) {
	t.Parallel()
	content := []byte("expected")
	tests := []struct {
		name   string
		digest string
		size   int64
		max    int64
		want   error
	}{
		{name: "digest", digest: testDigest([]byte("different")), size: int64(len(content)), max: 1024, want: ErrDigestMismatch},
		{name: "short", digest: testDigest(content), size: int64(len(content) + 1), max: 1024, want: ErrSizeMismatch},
		{name: "long", digest: testDigest(content), size: int64(len(content) - 1), max: 1024, want: ErrSizeMismatch},
		{name: "bounded", digest: testDigest(content), size: int64(len(content)), max: 3, want: ErrObjectTooLarge},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			backend := newFakeImmutableBackend()
			store := newTestGCSStore(t, backend, test.max)
			_, err := store.Put(context.Background(), "tenant-a", test.digest, test.size, bytes.NewReader(content))
			if !errors.Is(err, test.want) {
				t.Fatalf("want %v, got %v", test.want, err)
			}
			if backend.createCalls != 0 || len(backend.objects) != 0 {
				t.Fatalf("invalid bytes reached immutable backend")
			}
		})
	}
}

func TestGCSObjectStoreHonorsCancellationBeforePublishing(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	store := newTestGCSStore(t, backend, 1024)
	content := []byte("cancelled content")
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := store.Put(ctx, "tenant-a", testDigest(content), int64(len(content)), bytes.NewReader(content))
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("want context cancellation, got %v", err)
	}
	if backend.createCalls != 0 || len(backend.objects) != 0 {
		t.Fatal("cancelled bytes reached immutable backend")
	}
}

func TestGCSObjectStoreDetectsExistingAndReadCorruption(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	store := newTestGCSStore(t, backend, 1024)
	content := []byte("trusted bytes")
	digest := testDigest(content)
	name := store.objectName("tenant-a", digest)
	backend.objects[name] = []byte("corrupt bytes")
	backend.generations[name] = 9

	if _, err := store.Put(context.Background(), "tenant-a", digest, int64(len(content)), bytes.NewReader(content)); !errors.Is(err, ErrSizeMismatch) && !errors.Is(err, ErrDigestMismatch) {
		t.Fatalf("retry accepted corrupt existing object: %v", err)
	}
	backend.objects[name] = append([]byte(nil), content...)
	reader, err := store.Open(context.Background(), "tenant-a", digest)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	backend.objects[name] = []byte("changed after open")
	if _, err = io.ReadAll(reader); err != nil {
		t.Fatalf("pinned fake reader should retain opened generation: %v", err)
	}
	if err = reader.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}

	backend.objects[name] = []byte("same-size-bad")
	reader, err = store.Open(context.Background(), "tenant-a", digest)
	if err != nil {
		t.Fatalf("open corrupt: %v", err)
	}
	if _, err = io.ReadAll(reader); !errors.Is(err, ErrDigestMismatch) && !errors.Is(err, ErrSizeMismatch) {
		t.Fatalf("corrupt read was accepted: %v", err)
	}
}

func TestGCSObjectStoreSanitizesProviderErrors(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	backend.createErr = errors.New("provider failure at gs://secret-bucket/private-object?credential=secret")
	store := newTestGCSStore(t, backend, 1024)
	content := []byte("content")
	_, err := store.Put(context.Background(), "tenant-a", testDigest(content), int64(len(content)), bytes.NewReader(content))
	if !errors.Is(err, ErrStorageUnavailable) || strings.Contains(err.Error(), "secret") || strings.Contains(err.Error(), "gs://") {
		t.Fatalf("provider locator or credentials leaked: %v", err)
	}
}

func TestGCSConfigRejectsUnsafeOrUnboundedValues(t *testing.T) {
	t.Parallel()
	for _, config := range []GCSConfig{
		{},
		{Bucket: "bucket", Prefix: "../unsafe"},
		{Bucket: "bucket", MaxObjectBytes: maxGCSObjectBytes + 1},
		{Bucket: "bucket", ChunkSize: 1},
	} {
		if err := validateGCSConfig(&config); err == nil {
			t.Fatalf("accepted invalid config: %+v", config)
		}
	}
}

func TestGCSObjectStoreResumableChunksComposePinnedDownloadAndCleanup(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	store := newTestGCSStore(t, backend, 16<<20)
	parts := [][]byte{[]byte("authoritative "), []byte("transfer "), []byte("bytes")}
	chunks := make([]UploadChunk, 0, len(parts))
	var offset int64
	content := make([]byte, 0)
	for index, part := range parts {
		chunk := UploadChunk{Index: int64(index), Offset: offset, Size: int64(len(part)), Digest: testDigest(part)}
		stored, err := store.PutChunk(context.Background(), "tenant-a", "upload-a", chunk, part)
		if err != nil {
			t.Fatalf("put chunk %d: %v", index, err)
		}
		replayed, err := store.PutChunk(context.Background(), "tenant-a", "upload-a", chunk, part)
		if err != nil || replayed != stored {
			t.Fatalf("replay chunk %d: value=%+v err=%v", index, replayed, err)
		}
		chunks = append(chunks, stored)
		offset += int64(len(part))
		content = append(content, part...)
	}
	object, err := store.Finalize(context.Background(), "tenant-a", "upload-a", chunks, testDigest(content), int64(len(content)))
	if err != nil {
		t.Fatalf("finalize: %v", err)
	}
	replayed, err := store.Finalize(context.Background(), "tenant-a", "upload-a", chunks, testDigest(content), int64(len(content)))
	if err != nil || replayed != object {
		t.Fatalf("replay finalize: value=%+v err=%v", replayed, err)
	}
	reader, err := store.OpenPinned(context.Background(), object, 4)
	if err != nil {
		t.Fatalf("open pinned: %v", err)
	}
	got, err := io.ReadAll(reader)
	if err != nil || reader.Close() != nil || !bytes.Equal(got, content[4:]) {
		t.Fatalf("pinned content mismatch: got=%q err=%v", got, err)
	}
	if err = store.DeleteChunks(context.Background(), "tenant-a", "upload-a", chunks); err != nil {
		t.Fatalf("cleanup: %v", err)
	}
	if _, err = store.OpenPinned(context.Background(), object, 0); err != nil {
		t.Fatalf("final object was removed with chunks: %v", err)
	}
}

func TestGCSObjectStoreTransferRejectsCorruptionAndGenerationDrift(t *testing.T) {
	t.Parallel()
	backend := newFakeImmutableBackend()
	store := newTestGCSStore(t, backend, 1024)
	part := []byte("chunk")
	chunk := UploadChunk{Index: 0, Offset: 0, Size: int64(len(part)), Digest: testDigest(part)}
	if _, err := store.PutChunk(context.Background(), "tenant-a", "upload-a", chunk, []byte("wrong")); !errors.Is(err, ErrDigestMismatch) && !errors.Is(err, ErrSizeMismatch) {
		t.Fatalf("corrupt chunk accepted: %v", err)
	}
	stored, err := store.PutChunk(context.Background(), "tenant-a", "upload-a", chunk, part)
	if err != nil {
		t.Fatal(err)
	}
	stored.Generation++
	if _, err = store.Finalize(context.Background(), "tenant-a", "upload-a", []UploadChunk{stored}, testDigest(part), int64(len(part))); !errors.Is(err, ErrGenerationMismatch) {
		t.Fatalf("stale generation accepted: %v", err)
	}
}
