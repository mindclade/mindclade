package inference

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

type cursorPayload struct {
	Version       int    `json:"v"`
	Kind          string `json:"kind"`
	Tenant        string `json:"tenant"`
	Project       string `json:"project"`
	OperationName string `json:"operation_name"`
	RequestName   string `json:"request_name"`
	Sequence      uint64 `json:"sequence"`
	ExpiresUnix   int64  `json:"expires_unix"`
}

type CursorCodec struct {
	key []byte
	ttl time.Duration
}

func NewCursorCodec(key []byte, ttl time.Duration) (*CursorCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("inference cursor HMAC key must contain at least 32 bytes")
	}
	if ttl < time.Minute || ttl > 24*time.Hour {
		return nil, errors.New("inference cursor TTL must be between one minute and 24 hours")
	}
	return &CursorCodec{key: append([]byte(nil), key...), ttl: ttl}, nil
}

func (codec *CursorCodec) Encode(identity Identity, operationName, requestName string, sequence uint64, now time.Time) (string, error) {
	if codec == nil || len(codec.key) < 32 || validateIdentity(identity) != nil || operationName == "" || requestName == "" || sequence == 0 || now.IsZero() {
		return "", ErrCursorMalformed
	}
	payload, err := json.Marshal(cursorPayload{Version: 1, Kind: "inference-watch", Tenant: identity.TenantID, Project: identity.ProjectID, OperationName: operationName, RequestName: requestName, Sequence: sequence, ExpiresUnix: now.UTC().Add(codec.ttl).Unix()})
	if err != nil {
		return "", err
	}
	signature := hmac.New(sha256.New, codec.key)
	_, _ = signature.Write([]byte("mindclade.inference-cursor.v1\x00"))
	_, _ = signature.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil)), nil
}

func (codec *CursorCodec) Decode(encoded string, identity Identity, operationName, requestName string, now time.Time) (uint64, error) {
	if codec == nil || len(codec.key) < 32 || encoded == "" || len(encoded) > 4096 || operationName == "" || requestName == "" || now.IsZero() {
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
	signature := hmac.New(sha256.New, codec.key)
	_, _ = signature.Write([]byte("mindclade.inference-cursor.v1\x00"))
	_, _ = signature.Write(payload)
	if !hmac.Equal(signature.Sum(nil), presented) {
		return 0, ErrCursorMalformed
	}
	var cursor cursorPayload
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&cursor); err != nil || cursor.Version != 1 || cursor.Kind != "inference-watch" || cursor.Sequence == 0 || cursor.ExpiresUnix <= 0 {
		return 0, ErrCursorMalformed
	}
	if err = decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return 0, ErrCursorMalformed
	}
	if cursor.Tenant != identity.TenantID || cursor.Project != identity.ProjectID || cursor.OperationName != operationName || cursor.RequestName != requestName {
		return 0, ErrCursorResource
	}
	if !now.UTC().Before(time.Unix(cursor.ExpiresUnix, 0).UTC()) {
		return 0, ErrCursorExpired
	}
	return cursor.Sequence, nil
}
