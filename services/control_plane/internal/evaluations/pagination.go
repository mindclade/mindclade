package evaluations

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

type pageToken struct {
	Version   int    `json:"v"`
	Kind      string `json:"kind"`
	Tenant    string `json:"tenant"`
	Project   string `json:"project"`
	Filter    string `json:"filter,omitempty"`
	Order     string `json:"order,omitempty"`
	AfterTime string `json:"after_time,omitempty"`
	AfterName string `json:"after_name"`
}

type PageTokenCodec struct{ key []byte }

func NewPageTokenCodec(key []byte) (*PageTokenCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("evaluation pagination HMAC key must contain at least 32 bytes")
	}
	return &PageTokenCodec{key: append([]byte(nil), key...)}, nil
}

func (codec *PageTokenCodec) encode(value pageToken) (string, error) {
	if codec == nil || len(codec.key) < 32 {
		return "", errors.New("evaluation pagination codec is not configured")
	}
	value.Version = 1
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	signature := hmac.New(sha256.New, codec.key)
	_, _ = signature.Write([]byte("mindclade.evaluation-page.v1\x00"))
	_, _ = signature.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil)), nil
}

func (codec *PageTokenCodec) decode(encoded string, expected pageToken) (pageToken, error) {
	if codec == nil || len(codec.key) < 32 || len(encoded) > 4096 {
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
	signature := hmac.New(sha256.New, codec.key)
	_, _ = signature.Write([]byte("mindclade.evaluation-page.v1\x00"))
	_, _ = signature.Write(payload)
	if !hmac.Equal(signature.Sum(nil), presented) {
		return pageToken{}, ErrInvalidArgument
	}
	var value pageToken
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&value); err != nil || value.Version != 1 || value.AfterName == "" {
		return pageToken{}, ErrInvalidArgument
	}
	if err = decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return pageToken{}, ErrInvalidArgument
	}
	if value.Kind != expected.Kind || value.Tenant != expected.Tenant || value.Project != expected.Project || value.Filter != expected.Filter || value.Order != expected.Order {
		return pageToken{}, fmt.Errorf("%w: page token query binding mismatch", ErrInvalidArgument)
	}
	return value, nil
}

func parsePageTime(value string) (time.Time, error) {
	if value == "" {
		return time.Time{}, nil
	}
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return time.Time{}, ErrInvalidArgument
	}
	return parsed.UTC(), nil
}
