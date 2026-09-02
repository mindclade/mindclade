package storage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path"
	"sort"
	"strings"
	"time"

	gcs "cloud.google.com/go/storage"
	"google.golang.org/api/googleapi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	defaultMaxObjectBytes int64 = 1 << 30
	maxGCSObjectBytes     int64 = 5 * 1024 * 1024 * 1024 * 1024
	defaultGCSChunkSize         = 8 << 20
)

var (
	ErrObjectTooLarge     = errors.New("artifact object exceeds configured limit")
	ErrObjectNotFound     = errors.New("artifact object not found")
	ErrGenerationMismatch = errors.New("artifact object generation mismatch")
	ErrStorageUnavailable = errors.New("artifact object storage unavailable")
	errObjectExists       = errors.New("immutable artifact object already exists")
)

// GCSConfig contains storage behavior only. Authentication is intentionally
// absent: NewGCSObjectStore always uses Application Default Credentials so
// production workloads use Workload Identity rather than credential files.
type GCSConfig struct {
	Bucket           string
	Prefix           string
	StagingDirectory string
	MaxObjectBytes   int64
	ChunkSize        int
	ChunkRetryLimit  time.Duration
}

type objectAttributes struct {
	Size       int64
	Generation int64
}

type objectSource struct {
	name       string
	generation int64
}

type immutableBackend interface {
	Create(context.Context, string, io.Reader, int64, uint32) (objectAttributes, error)
	Open(context.Context, string) (io.ReadCloser, objectAttributes, error)
	OpenGeneration(context.Context, string, int64, int64) (io.ReadCloser, objectAttributes, error)
	Compose(context.Context, string, []objectSource) (objectAttributes, error)
	Delete(context.Context, string, int64) error
	Ready(context.Context) error
	Close() error
}

// GCSObjectStore is an immutable, tenant-partitioned content-addressed store.
// Provider bucket names and object names never cross this package boundary.
type GCSObjectStore struct {
	backend          immutableBackend
	prefix           string
	stagingDirectory string
	maxObjectBytes   int64
}

var (
	_ ObjectStore         = (*GCSObjectStore)(nil)
	_ TransferObjectStore = (*GCSObjectStore)(nil)
)

// NewGCSObjectStore constructs a production adapter using ADC/keyless
// identity. It performs no cloud mutation until Put is called.
func NewGCSObjectStore(ctx context.Context, config GCSConfig) (*GCSObjectStore, error) {
	if err := validateGCSConfig(&config); err != nil {
		return nil, err
	}
	client, err := gcs.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("initialize artifact object storage: %w", safeStorageError(err))
	}
	return newGCSObjectStore(&gcsBackend{
		client:          client,
		bucket:          client.Bucket(config.Bucket),
		chunkSize:       config.ChunkSize,
		chunkRetryLimit: config.ChunkRetryLimit,
	}, config), nil
}

func newGCSObjectStore(backend immutableBackend, config GCSConfig) *GCSObjectStore {
	return &GCSObjectStore{
		backend: backend, prefix: strings.Trim(config.Prefix, "/"),
		stagingDirectory: config.StagingDirectory, maxObjectBytes: config.MaxObjectBytes,
	}
}

func validateGCSConfig(config *GCSConfig) error {
	if config == nil || strings.TrimSpace(config.Bucket) == "" || strings.ContainsAny(config.Bucket, "\x00\r\n") {
		return errors.New("artifact object storage bucket is required")
	}
	prefix := strings.Trim(config.Prefix, "/")
	unsafeSegment := false
	for _, segment := range strings.Split(prefix, "/") {
		unsafeSegment = unsafeSegment || segment == "." || segment == ".."
	}
	if unsafeSegment || strings.Contains(prefix, "//") || strings.ContainsAny(prefix, "\x00\r\n") {
		return errors.New("artifact object storage prefix is invalid")
	}
	if config.MaxObjectBytes == 0 {
		config.MaxObjectBytes = defaultMaxObjectBytes
	}
	if config.MaxObjectBytes < 1 || config.MaxObjectBytes > maxGCSObjectBytes {
		return errors.New("artifact object size limit must be positive and no greater than 5 TiB")
	}
	if config.ChunkSize == 0 {
		config.ChunkSize = defaultGCSChunkSize
	}
	if config.ChunkSize < 256<<10 || config.ChunkSize%(256<<10) != 0 {
		return errors.New("artifact object chunk size must be a positive multiple of 256 KiB")
	}
	if config.ChunkRetryLimit == 0 {
		config.ChunkRetryLimit = 10 * time.Minute
	}
	if config.ChunkRetryLimit < time.Second || config.ChunkRetryLimit > time.Hour {
		return errors.New("artifact object chunk retry limit must be between one second and one hour")
	}
	return nil
}

func (s *GCSObjectStore) Close() error {
	if s == nil || s.backend == nil {
		return nil
	}
	return s.backend.Close()
}

// Ready verifies that the workload identity can address the configured bucket
// without creating or modifying any object.
func (s *GCSObjectStore) Ready(ctx context.Context) error {
	if s == nil || s.backend == nil {
		return ErrStorageUnavailable
	}
	return safeStorageError(s.backend.Ready(ctx))
}

func (s *GCSObjectStore) Put(ctx context.Context, tenantID, digest string, expectedSize int64, source io.Reader) (Object, error) {
	if s == nil || s.backend == nil || source == nil || !validTenantObjectScope(tenantID) || !validDigest(digest) || expectedSize < 0 {
		return Object{}, errors.New("artifact object put requires tenant, digest, size, and source")
	}
	if expectedSize > s.maxObjectBytes {
		return Object{}, ErrObjectTooLarge
	}
	file, crc, err := s.spoolVerified(ctx, source, digest, expectedSize)
	if err != nil {
		return Object{}, err
	}
	defer func() {
		name := file.Name()
		_ = file.Close()
		_ = os.Remove(name)
	}()

	objectName := s.objectName(tenantID, digest)
	created, err := s.backend.Create(ctx, objectName, file, expectedSize, crc)
	attrs := created
	if errors.Is(err, errObjectExists) {
		attrs, err = s.verifyRemote(ctx, objectName, digest, expectedSize)
	} else if err == nil {
		attrs, err = s.verifyRemote(ctx, objectName, digest, expectedSize)
		if err == nil && created.Generation > 0 && attrs.Generation != created.Generation {
			err = ErrGenerationMismatch
		}
	}
	if err != nil {
		return Object{}, safeStorageError(err)
	}
	if attrs.Generation <= 0 {
		return Object{}, ErrGenerationMismatch
	}
	return Object{TenantID: tenantID, Digest: digest, Size: expectedSize, Generation: attrs.Generation}, nil
}

func (s *GCSObjectStore) Verify(ctx context.Context, object Object) error {
	if s == nil || s.backend == nil || !validTenantObjectScope(object.TenantID) || !validDigest(object.Digest) || object.Size < 0 || object.Size > s.maxObjectBytes || object.Generation <= 0 {
		return errors.New("artifact object verification requires tenant, digest, size, and generation")
	}
	attrs, err := s.verifyRemote(ctx, s.objectName(object.TenantID, object.Digest), object.Digest, object.Size)
	if err != nil {
		return safeStorageError(err)
	}
	if attrs.Generation != object.Generation {
		return ErrGenerationMismatch
	}
	return nil
}

func (s *GCSObjectStore) Open(ctx context.Context, tenantID, digest string) (io.ReadCloser, error) {
	if s == nil || s.backend == nil || !validTenantObjectScope(tenantID) || !validDigest(digest) {
		return nil, errors.New("artifact object open requires tenant and digest")
	}
	reader, attrs, err := s.backend.Open(ctx, s.objectName(tenantID, digest))
	if err != nil {
		return nil, safeStorageError(err)
	}
	if attrs.Size < 0 || attrs.Size > s.maxObjectBytes {
		_ = reader.Close()
		return nil, ErrObjectTooLarge
	}
	return newVerifyingReadCloser(reader, digest, attrs.Size), nil
}

// PutChunk writes one immutable, independently verified upload chunk to a
// private staging prefix. Replaying the same chunk identity is safe; conflicting
// bytes fail closed during verification.
func (s *GCSObjectStore) PutChunk(ctx context.Context, tenantID, sessionID string, chunk UploadChunk, data []byte) (UploadChunk, error) {
	if s == nil || s.backend == nil || !validTenantObjectScope(tenantID) || !validSessionID(sessionID) || chunk.Index < 0 || chunk.Offset < 0 || chunk.Size <= 0 || chunk.Size != int64(len(data)) || !validDigest(chunk.Digest) || chunk.Size > s.maxObjectBytes {
		return UploadChunk{}, errors.New("artifact chunk requires valid scope, identity, offset, digest, and bytes")
	}
	digest := sha256.Sum256(data)
	if "sha256:"+hex.EncodeToString(digest[:]) != chunk.Digest {
		return UploadChunk{}, ErrDigestMismatch
	}
	checksum := crc32.Checksum(data, crc32.MakeTable(crc32.Castagnoli))
	name := s.chunkName(tenantID, sessionID, chunk)
	attrs, err := s.backend.Create(ctx, name, strings.NewReader(string(data)), chunk.Size, checksum)
	if errors.Is(err, errObjectExists) {
		attrs, err = s.verifyRemote(ctx, name, chunk.Digest, chunk.Size)
	} else if err == nil {
		attrs, err = s.verifyRemote(ctx, name, chunk.Digest, chunk.Size)
	}
	if err != nil {
		return UploadChunk{}, safeStorageError(err)
	}
	if attrs.Generation <= 0 {
		return UploadChunk{}, ErrGenerationMismatch
	}
	chunk.Generation = attrs.Generation
	return chunk, nil
}

// Finalize composes generation-pinned chunks into the immutable CAS object.
// Compose fan-in is bounded to GCS's 32-source limit and intermediate objects
// are deterministic, private, and deleted after the final object is verified.
func (s *GCSObjectStore) Finalize(ctx context.Context, tenantID, sessionID string, chunks []UploadChunk, digest string, size int64) (Object, error) {
	if s == nil || s.backend == nil || !validTenantObjectScope(tenantID) || !validSessionID(sessionID) || !validDigest(digest) || size < 0 || size > s.maxObjectBytes || (len(chunks) == 0) != (size == 0) {
		return Object{}, errors.New("artifact finalize requires scope, chunks, digest, and size")
	}
	if size == 0 {
		finalName := s.objectName(tenantID, digest)
		attrs, err := s.backend.Create(ctx, finalName, strings.NewReader(""), 0, 0)
		if errors.Is(err, errObjectExists) {
			attrs, err = s.verifyRemote(ctx, finalName, digest, 0)
		} else if err == nil {
			attrs, err = s.verifyRemote(ctx, finalName, digest, 0)
		}
		if err != nil {
			return Object{}, safeStorageError(err)
		}
		return Object{TenantID: tenantID, Digest: digest, Size: 0, Generation: attrs.Generation}, nil
	}
	ordered := append([]UploadChunk(nil), chunks...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Index < ordered[j].Index })
	var offset int64
	sources := make([]objectSource, 0, len(ordered))
	for index, chunk := range ordered {
		if chunk.Index != int64(index) || chunk.Offset != offset || chunk.Size <= 0 || !validDigest(chunk.Digest) || chunk.Generation <= 0 {
			return Object{}, ErrSizeMismatch
		}
		offset += chunk.Size
		sources = append(sources, objectSource{name: s.chunkName(tenantID, sessionID, chunk), generation: chunk.Generation})
	}
	if offset != size {
		return Object{}, ErrSizeMismatch
	}
	intermediates := make([]objectSource, 0)
	level := 0
	for len(sources) > 32 {
		next := make([]objectSource, 0, (len(sources)+31)/32)
		for start := 0; start < len(sources); start += 32 {
			end := start + 32
			if end > len(sources) {
				end = len(sources)
			}
			name := s.composeName(tenantID, sessionID, level, start/32)
			attrs, err := s.backend.Compose(ctx, name, sources[start:end])
			if errors.Is(err, errObjectExists) {
				reader, existing, openErr := s.backend.Open(ctx, name)
				if openErr == nil {
					_ = reader.Close()
				}
				attrs, err = existing, openErr
			}
			if err != nil || attrs.Generation <= 0 {
				return Object{}, safeStorageError(err)
			}
			source := objectSource{name: name, generation: attrs.Generation}
			next = append(next, source)
			intermediates = append(intermediates, source)
		}
		sources = next
		level++
	}
	finalName := s.objectName(tenantID, digest)
	attrs, err := s.backend.Compose(ctx, finalName, sources)
	if errors.Is(err, errObjectExists) {
		attrs, err = s.verifyRemote(ctx, finalName, digest, size)
	} else if err == nil {
		attrs, err = s.verifyRemote(ctx, finalName, digest, size)
	}
	for _, temporary := range intermediates {
		_ = s.backend.Delete(context.WithoutCancel(ctx), temporary.name, temporary.generation)
	}
	if err != nil {
		return Object{}, safeStorageError(err)
	}
	if attrs.Generation <= 0 {
		return Object{}, ErrGenerationMismatch
	}
	return Object{TenantID: tenantID, Digest: digest, Size: size, Generation: attrs.Generation}, nil
}

func (s *GCSObjectStore) OpenPinned(ctx context.Context, object Object, offset int64) (io.ReadCloser, error) {
	if s == nil || s.backend == nil || !validTenantObjectScope(object.TenantID) || !validDigest(object.Digest) || object.Size < 0 || object.Size > s.maxObjectBytes || object.Generation <= 0 || offset < 0 || offset > object.Size {
		return nil, errors.New("artifact pinned open requires valid object and offset")
	}
	reader, attrs, err := s.backend.OpenGeneration(ctx, s.objectName(object.TenantID, object.Digest), object.Generation, offset)
	if err != nil {
		return nil, safeStorageError(err)
	}
	if attrs.Generation != object.Generation || attrs.Size != object.Size {
		_ = reader.Close()
		return nil, ErrGenerationMismatch
	}
	return reader, nil
}

func (s *GCSObjectStore) DeleteChunks(ctx context.Context, tenantID, sessionID string, chunks []UploadChunk) error {
	if s == nil || s.backend == nil || !validTenantObjectScope(tenantID) || !validSessionID(sessionID) {
		return errors.New("artifact chunk cleanup requires valid scope")
	}
	var failed bool
	for _, chunk := range chunks {
		if chunk.Generation <= 0 {
			continue
		}
		if err := s.backend.Delete(ctx, s.chunkName(tenantID, sessionID, chunk), chunk.Generation); err != nil && !errors.Is(err, ErrObjectNotFound) {
			failed = true
		}
	}
	if failed {
		return ErrStorageUnavailable
	}
	return nil
}

func (s *GCSObjectStore) spoolVerified(ctx context.Context, source io.Reader, digest string, expectedSize int64) (*os.File, uint32, error) {
	file, err := os.CreateTemp(s.stagingDirectory, "mindclade-artifact-")
	if err != nil {
		return nil, 0, errors.New("create bounded artifact staging file")
	}
	cleanup := func() {
		name := file.Name()
		_ = file.Close()
		_ = os.Remove(name)
	}
	hash := sha256.New()
	checksum := crc32.New(crc32.MakeTable(crc32.Castagnoli))
	limited := &io.LimitedReader{R: contextReader{ctx: ctx, reader: source}, N: expectedSize + 1}
	written, copyErr := io.Copy(io.MultiWriter(file, hash, checksum), limited)
	if copyErr != nil {
		cleanup()
		if contextErr := ctx.Err(); contextErr != nil {
			return nil, 0, contextErr
		}
		return nil, 0, errors.New("stage artifact bytes")
	}
	if contextErr := ctx.Err(); contextErr != nil {
		cleanup()
		return nil, 0, contextErr
	}
	if written != expectedSize {
		cleanup()
		return nil, 0, ErrSizeMismatch
	}
	actualDigest := "sha256:" + hex.EncodeToString(hash.Sum(nil))
	if actualDigest != digest {
		cleanup()
		return nil, 0, ErrDigestMismatch
	}
	if err = file.Sync(); err != nil {
		cleanup()
		return nil, 0, errors.New("sync artifact staging file")
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		cleanup()
		return nil, 0, errors.New("rewind artifact staging file")
	}
	return file, checksum.Sum32(), nil
}

type contextReader struct {
	ctx    context.Context //nolint:containedctx // io.Reader has no context parameter; this adapter checks the caller context before every read.
	reader io.Reader
}

func (r contextReader) Read(buffer []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(buffer)
}

func (s *GCSObjectStore) verifyRemote(ctx context.Context, objectName, digest string, expectedSize int64) (objectAttributes, error) {
	reader, attrs, err := s.backend.Open(ctx, objectName)
	if err != nil {
		return objectAttributes{}, err
	}
	verified := newVerifyingReadCloser(reader, digest, expectedSize)
	if attrs.Size != expectedSize {
		_ = verified.Close()
		return objectAttributes{}, ErrSizeMismatch
	}
	_, err = io.Copy(io.Discard, verified)
	closeErr := verified.Close()
	if err != nil {
		return objectAttributes{}, err
	}
	if closeErr != nil {
		return objectAttributes{}, closeErr
	}
	return attrs, nil
}

func (s *GCSObjectStore) objectName(tenantID, digest string) string {
	tenantHash := sha256.Sum256([]byte(tenantID))
	digestHex := strings.TrimPrefix(digest, "sha256:")
	parts := []string{"tenants", hex.EncodeToString(tenantHash[:]), "sha256", digestHex[:2], digestHex}
	if s.prefix != "" {
		parts = append([]string{s.prefix}, parts...)
	}
	return path.Join(parts...)
}

func (s *GCSObjectStore) chunkName(tenantID, sessionID string, chunk UploadChunk) string {
	tenantHash := sha256.Sum256([]byte(tenantID))
	sessionHash := sha256.Sum256([]byte(sessionID))
	parts := []string{"staging", hex.EncodeToString(tenantHash[:]), hex.EncodeToString(sessionHash[:]), "chunks", fmt.Sprintf("%012d-%s", chunk.Index, strings.TrimPrefix(chunk.Digest, "sha256:"))}
	if s.prefix != "" {
		parts = append([]string{s.prefix}, parts...)
	}
	return path.Join(parts...)
}

func (s *GCSObjectStore) composeName(tenantID, sessionID string, level, group int) string {
	tenantHash := sha256.Sum256([]byte(tenantID))
	sessionHash := sha256.Sum256([]byte(sessionID))
	parts := []string{"staging", hex.EncodeToString(tenantHash[:]), hex.EncodeToString(sessionHash[:]), "compose", fmt.Sprintf("%04d-%08d", level, group)}
	if s.prefix != "" {
		parts = append([]string{s.prefix}, parts...)
	}
	return path.Join(parts...)
}

func validTenantObjectScope(tenantID string) bool {
	return tenantID != "" && len(tenantID) <= 255 && strings.TrimSpace(tenantID) == tenantID && !strings.ContainsAny(tenantID, "\x00\r\n")
}

func validSessionID(value string) bool {
	if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n/") {
		return false
	}
	return true
}

type verifyingReadCloser struct {
	reader         io.ReadCloser
	hash           hashWriter
	expectedDigest string
	expectedSize   int64
	read           int64
	verified       bool
	terminal       error
}

type hashWriter interface {
	Write([]byte) (int, error)
	Sum([]byte) []byte
}

func newVerifyingReadCloser(reader io.ReadCloser, digest string, size int64) *verifyingReadCloser {
	return &verifyingReadCloser{reader: reader, hash: sha256.New(), expectedDigest: digest, expectedSize: size}
}

func (r *verifyingReadCloser) Read(buffer []byte) (int, error) {
	if r.terminal != nil {
		return 0, r.terminal
	}
	count, err := r.reader.Read(buffer)
	if count > 0 {
		r.read += int64(count)
		_, _ = r.hash.Write(buffer[:count])
		if r.read > r.expectedSize {
			r.terminal = ErrSizeMismatch
			return count, r.terminal
		}
	}
	if errors.Is(err, io.EOF) {
		r.terminal = r.verify()
		if r.terminal != nil {
			return count, r.terminal
		}
	}
	return count, err
}

func (r *verifyingReadCloser) verify() error {
	if r.verified {
		return nil
	}
	r.verified = true
	if r.read != r.expectedSize {
		return ErrSizeMismatch
	}
	if "sha256:"+hex.EncodeToString(r.hash.Sum(nil)) != r.expectedDigest {
		return ErrDigestMismatch
	}
	return nil
}

func (r *verifyingReadCloser) Close() error {
	if !r.verified && r.terminal == nil {
		_, r.terminal = io.Copy(io.Discard, r)
	}
	closeErr := r.reader.Close()
	if r.terminal != nil {
		return r.terminal
	}
	return closeErr
}

type gcsBackend struct {
	client          *gcs.Client
	bucket          *gcs.BucketHandle
	chunkSize       int
	chunkRetryLimit time.Duration
}

func (b *gcsBackend) Create(ctx context.Context, objectName string, source io.Reader, size int64, crc uint32) (objectAttributes, error) {
	handle := b.bucket.Object(objectName).If(gcs.Conditions{DoesNotExist: true})
	writer := handle.NewWriter(ctx)
	writer.ChunkSize = b.chunkSize
	writer.ChunkRetryDeadline = b.chunkRetryLimit
	writer.ContentType = "application/octet-stream"
	writer.CacheControl = "no-store"
	writer.CRC32C = crc
	writer.SendCRC32C = true
	if _, err := io.Copy(writer, source); err != nil {
		_ = writer.Close()
		return objectAttributes{}, classifyGCSError(err)
	}
	if err := writer.Close(); err != nil {
		return objectAttributes{}, classifyGCSError(err)
	}
	attrs := writer.Attrs()
	if attrs == nil {
		return objectAttributes{}, ErrStorageUnavailable
	}
	return objectAttributes{Size: attrs.Size, Generation: attrs.Generation}, nil
}

func (b *gcsBackend) Open(ctx context.Context, objectName string) (io.ReadCloser, objectAttributes, error) {
	reader, err := b.bucket.Object(objectName).NewReader(ctx)
	if err != nil {
		return nil, objectAttributes{}, classifyGCSError(err)
	}
	return reader, objectAttributes{Size: reader.Attrs.Size, Generation: reader.Attrs.Generation}, nil
}

func (b *gcsBackend) OpenGeneration(ctx context.Context, objectName string, generation, offset int64) (io.ReadCloser, objectAttributes, error) {
	reader, err := b.bucket.Object(objectName).Generation(generation).NewRangeReader(ctx, offset, -1)
	if err != nil {
		return nil, objectAttributes{}, classifyGCSError(err)
	}
	return reader, objectAttributes{Size: reader.Attrs.Size, Generation: reader.Attrs.Generation}, nil
}

func (b *gcsBackend) Compose(ctx context.Context, objectName string, sources []objectSource) (objectAttributes, error) {
	if len(sources) < 1 || len(sources) > 32 {
		return objectAttributes{}, ErrStorageUnavailable
	}
	handles := make([]*gcs.ObjectHandle, 0, len(sources))
	for _, source := range sources {
		handles = append(handles, b.bucket.Object(source.name).Generation(source.generation))
	}
	attrs, err := b.bucket.Object(objectName).If(gcs.Conditions{DoesNotExist: true}).ComposerFrom(handles...).Run(ctx)
	if err != nil {
		return objectAttributes{}, classifyGCSError(err)
	}
	return objectAttributes{Size: attrs.Size, Generation: attrs.Generation}, nil
}

func (b *gcsBackend) Delete(ctx context.Context, objectName string, generation int64) error {
	return classifyGCSError(b.bucket.Object(objectName).Generation(generation).Delete(ctx))
}

func (b *gcsBackend) Ready(ctx context.Context) error {
	_, err := b.bucket.Attrs(ctx)
	return classifyGCSError(err)
}

func (b *gcsBackend) Close() error { return b.client.Close() }

func classifyGCSError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	if errors.Is(err, gcs.ErrObjectNotExist) || status.Code(err) == codes.NotFound {
		return ErrObjectNotFound
	}
	if status.Code(err) == codes.AlreadyExists || status.Code(err) == codes.FailedPrecondition {
		return errObjectExists
	}
	var apiError *googleapi.Error
	if errors.As(err, &apiError) {
		switch apiError.Code {
		case 404:
			return ErrObjectNotFound
		case 409, 412:
			return errObjectExists
		}
	}
	return ErrStorageUnavailable
}

func safeStorageError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, context.Canceled):
		return context.Canceled
	case errors.Is(err, context.DeadlineExceeded):
		return context.DeadlineExceeded
	case errors.Is(err, ErrObjectNotFound):
		return ErrObjectNotFound
	case errors.Is(err, ErrDigestMismatch):
		return ErrDigestMismatch
	case errors.Is(err, ErrSizeMismatch):
		return ErrSizeMismatch
	case errors.Is(err, ErrObjectTooLarge):
		return ErrObjectTooLarge
	case errors.Is(err, ErrGenerationMismatch):
		return ErrGenerationMismatch
	default:
		return ErrStorageUnavailable
	}
}
