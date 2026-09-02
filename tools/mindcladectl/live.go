package mindcladectl

import (
	"context"
	"errors"
	"iter"
	"os"
	"strings"
	"time"

	"github.com/mindclade/mindclade/internal/sdk/go/mindclade"
)

type liveBackend struct {
	client *mindclade.Client
}

// NewLiveBackend creates the production private-SDK adapter. Environment,
// identity, endpoint, audience, TLS, and workload credentials are owned,
// parsed, and validated by the SDK; this tool never reads cloud provider
// tokens directly and no longer parses MINDCLADE_* configuration itself.
func NewLiveBackend() (Backend, error) {
	client, err := mindclade.New(
		// FromEnvironment is the SDK's own MINDCLADE_* reader. Without it the
		// documented tenant, project, principal, endpoint and audience
		// variables were never applied and construction always failed.
		mindclade.FromEnvironment(),
		mindclade.WithWorkloadIdentity(),
		mindclade.WithUserAgent("mindcladectl/0.1"),
	)
	if err != nil {
		return nil, err
	}
	return &liveBackend{client: client}, nil
}

// capture derives a context whose calls record their transport response, so a
// success carries the same request id a failure would. The context accessor is
// used rather than a per-call option because Operations.Wait polls internally
// and only the context-scoped capture reaches those inner calls.
func capture(ctx context.Context) context.Context {
	return mindclade.CaptureResponseMetadata(ctx)
}

func replyFrom(ctx context.Context, message ProtoMessage) Reply {
	response, captured := mindclade.ResponseMetadataFromContext(ctx)
	return Reply{Message: message, Response: response, Captured: captured}
}

func (backend *liveBackend) GetOperation(ctx context.Context, name string, wait bool) (Reply, error) {
	callContext := capture(ctx)
	operation, err := backend.client.Operations.Get(callContext, name)
	if wait && err == nil {
		operation, err = backend.client.Operations.Wait(callContext, name, mindclade.WaitOptions{})
	}
	if err != nil {
		return Reply{}, err
	}
	return replyFrom(callContext, operation), nil
}

func (backend *liveBackend) CancelOperation(ctx context.Context, name, etag, reason, idempotencyKey string) (Reply, error) {
	callContext := capture(ctx)
	operation, err := backend.client.Operations.Cancel(
		callContext,
		name,
		etag,
		reason,
		mindclade.WithIdempotencyKey(idempotencyKey),
	)
	if err != nil {
		return Reply{}, err
	}
	return replyFrom(callContext, operation), nil
}

// DownloadArtifact resolves the reference and hands publication to the SDK.
// DownloadFile downloads into a mode-0600 temporary file in the destination
// directory, verifies and syncs it, then atomically links it into place without
// ever overwriting an existing destination — so the CLI stages nothing itself.
func (backend *liveBackend) DownloadArtifact(ctx context.Context, reference, destination string) (Reply, error) {
	callContext := capture(ctx)
	artifact, err := backend.client.Artifacts.Resolve(callContext, reference)
	if err != nil {
		return Reply{}, err
	}
	if err := backend.client.Artifacts.DownloadFile(callContext, artifact, destination); err != nil {
		return Reply{}, err
	}
	return replyFrom(callContext, nil), nil
}

func (backend *liveBackend) GetExperiment(ctx context.Context, name string) (Reply, error) {
	callContext := capture(ctx)
	value, err := backend.client.Experiments.Get(callContext, name, "")
	if err != nil {
		return Reply{}, err
	}
	return replyFrom(callContext, value), nil
}

// ListExperiments returns the SDK's own experiment page. Page size validation,
// the opaque cursor, the traversal budget and the page walk itself all belong
// to the SDK page; this adapter only projects that page onto the CLI's
// presentation view and runs no page loop.
func (backend *liveBackend) ListExperiments(ctx context.Context, request ListRequest) (Listing, error) {
	callContext := capture(ctx)
	options := []mindclade.RequestOption{mindclade.WithPaginationLimits(request.Limits)}
	page, err := backend.client.Experiments.ListPage(callContext, request.PageSize, request.PageToken, options...)
	if err != nil {
		return Listing{}, err
	}
	response, captured := mindclade.ResponseMetadataFromContext(callContext)
	listing := Listing{
		Page:          page.ListExperimentsResponse,
		NextPageToken: page.PageMetadata().GetNextPageToken(),
		HasNextPage:   page.HasNextPage(),
		Response:      response,
		Captured:      captured,
	}
	if request.AllPages {
		listing.Traverse = traversal(page.All(callContext))
	}
	return listing, nil
}

// traversal adapts the SDK page's typed item sequence to the CLI's
// protobuf-runtime view. The generated item type is never named here, so the
// CLI keeps depending on the SDK facade alone while the SDK's own generated
// messages remain what is rendered.
func traversal[Item ProtoMessage](sequence iter.Seq2[Item, error]) iter.Seq2[ProtoMessage, error] {
	return func(yield func(ProtoMessage, error) bool) {
		for item, err := range sequence {
			if !yield(item, err) {
				return
			}
		}
	}
}

func (backend *liveBackend) Close() error {
	return backend.client.Close()
}

// CommandTimeoutFromEnvironment validates the one total command budget. This is
// the CLI's own variable, not part of the SDK's MINDCLADE_* configuration set:
// per-call deadlines, retries and backoff remain the SDK's.
func CommandTimeoutFromEnvironment() (time.Duration, error) {
	value := strings.TrimSpace(os.Getenv("MINDCLADE_CLI_TIMEOUT"))
	if value == "" {
		return defaultCommandTimeout, nil
	}
	timeout, err := time.ParseDuration(value)
	if err != nil || timeout <= 0 || timeout > maximumCommandTimeout {
		return 0, errors.New("mindcladectl: MINDCLADE_CLI_TIMEOUT must be a positive duration no greater than 30m")
	}
	return timeout, nil
}
