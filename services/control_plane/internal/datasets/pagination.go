package datasets

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

func (c *PageTokenCodec) encode(token pageToken) (string, error) {
	if c == nil || len(c.key) < 32 {
		return "", errors.New("pagination codec is not configured")
	}
	token.Version = 1
	payload, err := json.Marshal(token)
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, c.key)
	_, _ = mac.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil)), nil
}

func (c *PageTokenCodec) decode(encoded string, expected pageToken) (pageToken, error) {
	if c == nil || len(c.key) < 32 || len(encoded) > 4096 {
		return pageToken{}, ErrInvalidArgument
	}
	parts := strings.Split(encoded, ".")
	if len(parts) != 2 {
		return pageToken{}, ErrInvalidArgument
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return pageToken{}, ErrInvalidArgument
	}
	presented, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return pageToken{}, ErrInvalidArgument
	}
	mac := hmac.New(sha256.New, c.key)
	_, _ = mac.Write(payload)
	if !hmac.Equal(mac.Sum(nil), presented) {
		return pageToken{}, ErrInvalidArgument
	}
	var token pageToken
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&token); err != nil || token.Version != 1 || token.AfterName == "" {
		return pageToken{}, ErrInvalidArgument
	}
	if err = decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return pageToken{}, ErrInvalidArgument
	}
	if token.Kind != expected.Kind || token.Tenant != expected.Tenant || token.Project != expected.Project || token.Parent != expected.Parent || token.Filter != expected.Filter || token.Order != expected.Order {
		return pageToken{}, fmt.Errorf("%w: page token query binding mismatch", ErrInvalidArgument)
	}
	return token, nil
}

func pageLimit(value uint32) (int, error) {
	if value == 0 {
		return defaultPageSize, nil
	}
	if value > maximumPageSize {
		return 0, ErrInvalidArgument
	}
	return int(value), nil
}

func pageTime(value string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, ErrInvalidArgument
	}
	return parsed.UTC(), nil
}
