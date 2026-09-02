package mindclade

import (
	"context"
	"errors"
	"testing"
	"time"

	"golang.org/x/oauth2"
)

type blockingOAuthSource struct {
	release <-chan struct{}
}

func (source blockingOAuthSource) Token() (*oauth2.Token, error) {
	<-source.release
	return &oauth2.Token{AccessToken: "eventual-token", Expiry: time.Now().Add(5 * time.Minute)}, nil
}

func TestOAuthTokenProviderHonorsCallerDeadline(t *testing.T) {
	release := make(chan struct{})
	provider := &oauthTokenProvider{source: blockingOAuthSource{release: release}}
	ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
	defer cancel()
	_, err := provider.Token(ctx)
	close(release)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Token error = %v, want context deadline exceeded", err)
	}
}
