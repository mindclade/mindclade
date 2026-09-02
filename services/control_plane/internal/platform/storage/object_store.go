package storage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

var (
	ErrDigestMismatch = errors.New("artifact digest mismatch")
	ErrSizeMismatch   = errors.New("artifact size mismatch")
	ErrFence          = errors.New("artifact reservation fence mismatch")
)

type Object struct {
	TenantID string
	Digest   string
	Size     int64
	// Generation pins the immutable provider version without exposing a URI.
	// Local adapters leave it zero.
	Generation int64
}

// ObjectStore writes immutable bytes outside control-plane transactions.
type ObjectStore interface {
	// Put verifies the caller-supplied digest and exact size before making bytes
	// visible at their immutable content-addressed location.
	Put(context.Context, string, string, int64, io.Reader) (Object, error)
	Open(context.Context, string, string) (io.ReadCloser, error)
	// Verify pins the expected immutable generation and revalidates content.
	Verify(context.Context, Object) error
}

// UploadChunk is private transfer-plane storage metadata. Generation pins the
// immutable provider object used during composition and never crosses an RPC
// boundary.
type UploadChunk struct {
	Index      int64
	Offset     int64
	Size       int64
	Digest     string
	Generation int64
}

// TransferObjectStore is the private byte plane used by resumable artifact
// RPCs. SQL owns session state; this interface owns only immutable GCS bytes.
// Implementations must make PutChunk and Finalize idempotent for identical
// identities and must pin provider generations for compose and download.
type TransferObjectStore interface {
	PutChunk(context.Context, string, string, UploadChunk, []byte) (UploadChunk, error)
	Finalize(context.Context, string, string, []UploadChunk, string, int64) (Object, error)
	OpenPinned(context.Context, Object, int64) (io.ReadCloser, error)
	DeleteChunks(context.Context, string, string, []UploadChunk) error
}

type Reservation struct {
	TenantID string
	Digest   string
	Size     int64
	Fence    uint64
}

type StagedObject struct {
	Reservation Reservation
	Path        string
	Digest      string
	Size        int64
}

// FilesystemCAS is a local immutable CAS test adapter. Paths are private implementation details, never identity.
type FilesystemCAS struct {
	Root string
}

func (s FilesystemCAS) Reserve(tenantID, digest string, size int64, fence uint64) (Reservation, error) {
	if tenantID == "" || !validDigest(digest) || size < 0 || fence == 0 {
		return Reservation{}, ErrFence
	}
	return Reservation{TenantID: tenantID, Digest: digest, Size: size, Fence: fence}, nil
}

func (s FilesystemCAS) Stage(ctx context.Context, reservation Reservation, reader io.Reader) (StagedObject, error) {
	if err := ctx.Err(); err != nil {
		return StagedObject{}, err
	}
	staging := filepath.Join(s.Root, ".staging")
	if err := os.MkdirAll(staging, 0o700); err != nil {
		return StagedObject{}, err
	}
	file, err := os.CreateTemp(staging, "artifact-")
	if err != nil {
		return StagedObject{}, err
	}
	path := file.Name()
	hash := sha256.New()
	size, copyErr := io.Copy(io.MultiWriter(file, hash), reader)
	if syncErr := file.Sync(); copyErr == nil {
		copyErr = syncErr
	}
	if closeErr := file.Close(); copyErr == nil {
		copyErr = closeErr
	}
	if copyErr != nil {
		return StagedObject{}, copyErr
	}
	return StagedObject{Reservation: reservation, Path: path, Digest: "sha256:" + hex.EncodeToString(hash.Sum(nil)), Size: size}, nil
}

func (s FilesystemCAS) Verify(staged StagedObject, reservation Reservation) error {
	if staged.Reservation != reservation {
		return ErrFence
	}
	if staged.Digest != reservation.Digest {
		s.quarantine(staged)
		return ErrDigestMismatch
	}
	if staged.Size != reservation.Size {
		s.quarantine(staged)
		return ErrSizeMismatch
	}
	return nil
}

func (s FilesystemCAS) Finalize(staged StagedObject, reservation Reservation) (Object, error) {
	if err := s.Verify(staged, reservation); err != nil {
		return Object{}, err
	}
	key := strings.TrimPrefix(reservation.Digest, "sha256:")
	directory := filepath.Join(s.Root, "objects", key[:2])
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return Object{}, err
	}
	finalPath := filepath.Join(directory, key)
	if info, err := os.Stat(finalPath); err == nil {
		if info.Size() != reservation.Size {
			s.quarantine(staged)
			return Object{}, ErrSizeMismatch
		}
		return Object{TenantID: reservation.TenantID, Digest: reservation.Digest, Size: reservation.Size}, nil
	}
	if err := os.Rename(staged.Path, finalPath); err != nil {
		return Object{}, err
	}
	// #nosec G304 -- directory is beneath the configured CAS root and keyed by a validated digest.
	directoryHandle, err := os.Open(directory)
	if err != nil {
		return Object{}, err
	}
	err = directoryHandle.Sync()
	closeErr := directoryHandle.Close()
	if err != nil {
		return Object{}, err
	}
	if closeErr != nil {
		return Object{}, closeErr
	}
	return Object{TenantID: reservation.TenantID, Digest: reservation.Digest, Size: reservation.Size}, nil
}

func (s FilesystemCAS) CleanupOrphans(before time.Time) (int, error) {
	staging := filepath.Join(s.Root, ".staging")
	entries, err := os.ReadDir(staging)
	if os.IsNotExist(err) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	removed := 0
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil || !info.ModTime().Before(before) {
			continue
		}
		if err := os.Remove(filepath.Join(staging, entry.Name())); err != nil {
			return removed, err
		}
		removed++
	}
	return removed, nil
}

// Quarantine removes a staged object from the finalize path after semantic
// validation fails. The quarantine remains private implementation state.
func (s FilesystemCAS) Quarantine(staged StagedObject) {
	s.quarantine(staged)
}

func (s FilesystemCAS) quarantine(staged StagedObject) {
	directory := filepath.Join(s.Root, "quarantine")
	if os.MkdirAll(directory, 0o700) != nil {
		return
	}
	_ = os.Rename(staged.Path, filepath.Join(directory, filepath.Base(staged.Path)))
}

func validDigest(digest string) bool {
	if !strings.HasPrefix(digest, "sha256:") || len(digest) != len("sha256:")+64 || digest != strings.ToLower(digest) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(digest, "sha256:"))
	return err == nil
}
