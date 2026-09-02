package mindclade

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"golang.org/x/oauth2"
	"google.golang.org/api/idtoken"
)

type oauthTokenProvider struct {
	source oauth2.TokenSource
	cancel context.CancelFunc
}

func newWorkloadIdentityProvider(audience string, refreshTimeout time.Duration) (*oauthTokenProvider, error) {
	// The ID-token source retains its context for future refreshes. Give it a
	// client-owned lifetime; a short startup context would be canceled as soon
	// as New returns and would break later workload-identity refreshes.
	lifetime, cancel := context.WithCancel(context.Background())
	source, err := idtoken.NewTokenSource(
		lifetime,
		audience,
		idtoken.WithHTTPClient(&http.Client{Timeout: refreshTimeout}),
	)
	if err != nil {
		cancel()
		return nil, &Error{Code: CodeUnauthenticated, Message: "workload identity discovery failed"}
	}
	return &oauthTokenProvider{source: oauth2.ReuseTokenSource(nil, source), cancel: cancel}, nil
}

func (provider *oauthTokenProvider) Close() error {
	if provider != nil && provider.cancel != nil {
		provider.cancel()
	}
	return nil
}

func (provider *oauthTokenProvider) Token(ctx context.Context) (Token, error) {
	if err := ctx.Err(); err != nil {
		return Token{}, err
	}
	type result struct {
		token *oauth2.Token
		err   error
	}
	// oauth2.TokenSource has no per-call context parameter. Run acquisition
	// behind the RPC context; the source's HTTP client has the same configured
	// upper bound, so a canceled request cannot retain an unbounded goroutine.
	completed := make(chan result, 1)
	go func() {
		token, err := provider.source.Token()
		completed <- result{token: token, err: err}
	}()
	select {
	case <-ctx.Done():
		return Token{}, ctx.Err()
	case value := <-completed:
		if value.err != nil {
			return Token{}, value.err
		}
		if value.token == nil {
			return Token{}, errors.New("credential source returned no token")
		}
		return Token{AccessToken: value.token.AccessToken, Expiry: value.token.Expiry}, nil
	}
}

type bearerCredentials struct {
	provider TokenProvider
}

func (credentials bearerCredentials) GetRequestMetadata(ctx context.Context, _ ...string) (map[string]string, error) {
	token, err := credentials.provider.Token(ctx)
	if err != nil {
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			return nil, normalizeError(err)
		}
		return nil, &Error{Code: CodeUnauthenticated, Message: "workload identity credential acquisition failed"}
	}
	if strings.TrimSpace(token.AccessToken) == "" {
		return nil, &Error{Code: CodeUnauthenticated, Message: "token provider returned an empty access token"}
	}
	if len(token.AccessToken) > 16*1024 || !isGraphicASCII(token.AccessToken) {
		return nil, &Error{Code: CodeUnauthenticated, Message: "token provider returned an invalid access token"}
	}
	remaining := time.Until(token.Expiry)
	if token.Expiry.IsZero() || remaining <= 30*time.Second {
		return nil, &Error{Code: CodeUnauthenticated, Message: "token provider returned an expired access token"}
	}
	if remaining > 65*time.Minute {
		return nil, &Error{Code: CodeUnauthenticated, Message: "token provider must return a short-lived access token"}
	}
	return map[string]string{"authorization": "Bearer " + token.AccessToken}, nil
}

func isGraphicASCII(value string) bool {
	for index := 0; index < len(value); index++ {
		if value[index] < 0x21 || value[index] > 0x7e {
			return false
		}
	}
	return true
}

func (bearerCredentials) RequireTransportSecurity() bool { return true }
