package training

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"
)

const (
	defaultPageSize = 50
	maximumPageSize = 200
)

type pageToken struct {
	Version   int    `json:"v"`
	Kind      string `json:"kind"`
	Tenant    string `json:"tenant"`
	Project   string `json:"project"`
	Parent    string `json:"parent,omitempty"`
	Filter    string `json:"filter,omitempty"`
	Order     string `json:"order,omitempty"`
	AfterTime string `json:"after_time,omitempty"`
	AfterID   uint64 `json:"after_id,omitempty"`
	AfterName string `json:"after_name"`
}

type PageTokenCodec struct{ key []byte }

type operationCursor struct {
	Version  int    `json:"v"`
	Kind     string `json:"kind"`
	Name     string `json:"name"`
	Revision uint64 `json:"revision"`
}

func NewPageTokenCodec(key []byte) (*PageTokenCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("pagination HMAC key must contain at least 32 bytes")
	}
	return &PageTokenCodec{key: append([]byte(nil), key...)}, nil
}

func (c *PageTokenCodec) encode(token pageToken) (string, error) {
	if c == nil || len(c.key) < 32 {
		return "", errors.New("pagination codec is not configured")
	}
	token.Version = 1
	payload, err := json.Marshal(token)
	if err != nil {
		return "", err
	}
	signature := hmac.New(sha256.New, c.key)
	_, _ = signature.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil)), nil
}

func (c *PageTokenCodec) decode(encoded string, expected pageToken) (pageToken, error) {
	if c == nil || len(c.key) < 32 {
		return pageToken{}, errors.New("pagination codec is not configured")
	}
	parts := strings.Split(encoded, ".")
	if len(parts) != 2 || len(encoded) > 4096 {
		return pageToken{}, fmt.Errorf("%w: malformed page token", ErrInvalidArgument)
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return pageToken{}, fmt.Errorf("%w: malformed page token", ErrInvalidArgument)
	}
	presented, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return pageToken{}, fmt.Errorf("%w: malformed page token", ErrInvalidArgument)
	}
	signature := hmac.New(sha256.New, c.key)
	_, _ = signature.Write(payload)
	if !hmac.Equal(signature.Sum(nil), presented) {
		return pageToken{}, fmt.Errorf("%w: invalid page token signature", ErrInvalidArgument)
	}
	var token pageToken
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&token); err != nil || token.Version != 1 || token.AfterName == "" {
		return pageToken{}, fmt.Errorf("%w: invalid page token payload", ErrInvalidArgument)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return pageToken{}, fmt.Errorf("%w: trailing page token payload", ErrInvalidArgument)
	}
	if token.Kind != expected.Kind || token.Tenant != expected.Tenant || token.Project != expected.Project || token.Parent != expected.Parent || token.Filter != expected.Filter || token.Order != expected.Order {
		return pageToken{}, fmt.Errorf("%w: page token query binding mismatch", ErrInvalidArgument)
	}
	return token, nil
}

// EncodeOperationCursor creates a tamper-evident cursor bound to the exact
// canonical public operation name and the last durably observed revision.
func (c *PageTokenCodec) EncodeOperationCursor(name string, revision uint64) (string, error) {
	if c == nil || len(c.key) < 32 || name == "" || revision == 0 {
		return "", ErrCursorMalformed
	}
	payload, err := json.Marshal(operationCursor{Version: 1, Kind: "operation-watch", Name: name, Revision: revision})
	if err != nil {
		return "", err
	}
	signature := hmac.New(sha256.New, c.key)
	_, _ = signature.Write([]byte("mindclade.operation-cursor.v1\x00"))
	_, _ = signature.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil)), nil
}

// DecodeOperationCursor distinguishes malformed/tampered cursors from valid
// cursors presented for a different operation without trusting caller text.
func (c *PageTokenCodec) DecodeOperationCursor(encoded, expectedName string) (uint64, error) {
	if c == nil || len(c.key) < 32 || encoded == "" || expectedName == "" || len(encoded) > 4096 {
		return 0, ErrCursorMalformed
	}
	parts := strings.Split(encoded, ".")
	if len(parts) != 2 {
		return 0, ErrCursorMalformed
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return 0, ErrCursorMalformed
	}
	presented, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return 0, ErrCursorMalformed
	}
	signature := hmac.New(sha256.New, c.key)
	_, _ = signature.Write([]byte("mindclade.operation-cursor.v1\x00"))
	_, _ = signature.Write(payload)
	if !hmac.Equal(signature.Sum(nil), presented) {
		return 0, ErrCursorMalformed
	}
	var cursor operationCursor
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&cursor); err != nil || cursor.Version != 1 || cursor.Kind != "operation-watch" || cursor.Name == "" || cursor.Revision == 0 {
		return 0, ErrCursorMalformed
	}
	if err = decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return 0, ErrCursorMalformed
	}
	if cursor.Name != expectedName {
		return 0, ErrCursorResource
	}
	return cursor.Revision, nil
}

func pageLimit(requested uint32) (int, error) {
	if requested == 0 {
		return defaultPageSize, nil
	}
	if requested > maximumPageSize {
		return 0, fmt.Errorf("%w: page_size exceeds %d", ErrInvalidArgument, maximumPageSize)
	}
	return int(requested), nil
}

func parsePageTime(value string) (time.Time, error) {
	if value == "" {
		return time.Time{}, nil
	}
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, fmt.Errorf("%w: invalid page time", ErrInvalidArgument)
	}
	return parsed.UTC(), nil
}
