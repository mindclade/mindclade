package models

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
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
	Order     string `json:"order"`
	AfterTime string `json:"after_time"`
	AfterName string `json:"after_name"`
}
type PageTokenCodec struct{ key []byte }

func NewPageTokenCodec(key []byte) (*PageTokenCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("pagination HMAC key must contain at least 32 bytes")
	}
	return &PageTokenCodec{key: append([]byte(nil), key...)}, nil
}

func (c *PageTokenCodec) encode(t pageToken) (string, error) {
	if c == nil || len(c.key) < 32 {
		return "", errors.New("pagination codec is not configured")
	}
	t.Version = 1
	p, err := json.Marshal(t)
	if err != nil {
		return "", err
	}
	m := hmac.New(sha256.New, c.key)
	_, _ = m.Write(p)
	return base64.RawURLEncoding.EncodeToString(p) + "." + base64.RawURLEncoding.EncodeToString(m.Sum(nil)), nil
}

func (c *PageTokenCodec) decode(encoded string, expected pageToken) (pageToken, error) {
	if c == nil || len(c.key) < 32 || len(encoded) > 4096 {
		return pageToken{}, ErrInvalidArgument
	}
	parts := strings.Split(encoded, ".")
	if len(parts) != 2 {
		return pageToken{}, ErrInvalidArgument
	}
	p, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return pageToken{}, ErrInvalidArgument
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return pageToken{}, ErrInvalidArgument
	}
	m := hmac.New(sha256.New, c.key)
	_, _ = m.Write(p)
	if !hmac.Equal(m.Sum(nil), sig) {
		return pageToken{}, ErrInvalidArgument
	}
	var t pageToken
	d := json.NewDecoder(bytes.NewReader(p))
	d.DisallowUnknownFields()
	if err = d.Decode(&t); err != nil || t.Version != 1 || t.AfterName == "" {
		return pageToken{}, ErrInvalidArgument
	}
	if err = d.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return pageToken{}, ErrInvalidArgument
	}
	if t.Kind != expected.Kind || t.Tenant != expected.Tenant || t.Project != expected.Project || t.Parent != expected.Parent || t.Filter != expected.Filter || t.Order != expected.Order {
		return pageToken{}, ErrPermissionDenied
	}
	return t, nil
}

func pageLimit(v uint32) (int, error) {
	if v == 0 {
		return defaultPageSize, nil
	}
	if v > maximumPageSize {
		return 0, ErrInvalidArgument
	}
	return int(v), nil
}

func pageTime(v string) (time.Time, error) {
	t, err := time.Parse(time.RFC3339Nano, v)
	if err != nil {
		return time.Time{}, ErrInvalidArgument
	}
	return t.UTC(), nil
}
