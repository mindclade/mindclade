package mindcladectl

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/mindclade/mindclade/internal/sdk/go/mindclade"
	"github.com/mindclade/mindclade/libs/go/numconv"
)

type liveBackend struct {
	client *mindclade.Client
}

// NewLiveBackend creates the production private-SDK adapter. Identity,
// endpoint, audience, TLS, and workload credentials are owned and validated by
// the SDK; this tool never reads cloud provider tokens directly.
func NewLiveBackend() (Backend, error) {
	environment, err := environmentFromString(os.Getenv("MINDCLADE_ENVIRONMENT"))
	if err != nil {
		return nil, err
	}
	client, err := mindclade.New(
		mindclade.WithEnvironment(environment),
		mindclade.WithWorkloadIdentity(),
		mindclade.WithUserAgent("mindcladectl/0.1"),
	)
	if err != nil {
		return nil, err
	}
	return &liveBackend{client: client}, nil
}

func environmentFromString(value string) (mindclade.Environment, error) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "", "development":
		return mindclade.Development, nil
	case "staging":
		return mindclade.Staging, nil
	case "production":
		return mindclade.Production, nil
	default:
		return "", errors.New("mindcladectl: MINDCLADE_ENVIRONMENT must be development, staging, or production")
	}
}

func (backend *liveBackend) WriteOperation(ctx context.Context, name string, wait bool, writer io.Writer) error {
	operation, err := backend.client.Operations.Get(ctx, name)
	if wait && err == nil {
		operation, err = backend.client.Operations.Wait(ctx, name, mindclade.WaitOptions{})
	}
	if err != nil {
		return err
	}
	return writeMessage(writer, operation)
}

func (backend *liveBackend) CancelOperation(ctx context.Context, name, etag, reason, idempotencyKey string, writer io.Writer) error {
	operation, err := backend.client.Operations.Cancel(
		ctx,
		name,
		etag,
		reason,
		mindclade.WithIdempotencyKey(idempotencyKey),
	)
	if err != nil {
		return err
	}
	return writeMessage(writer, operation)
}

func (backend *liveBackend) DownloadArtifact(ctx context.Context, reference string, destination io.Writer) error {
	artifact, err := backend.client.Artifacts.Resolve(ctx, reference)
	if err != nil {
		return err
	}
	return backend.client.Artifacts.Download(ctx, artifact, destination)
}

func (backend *liveBackend) WriteExperiment(ctx context.Context, name string, writer io.Writer) error {
	value, err := backend.client.Experiments.Get(ctx, name, "")
	if err != nil {
		return err
	}
	return writeMessage(writer, value)
}

func (backend *liveBackend) ListExperiments(ctx context.Context, pageSize uint32, pageToken string, writer io.Writer) error {
	boundedPageSize, err := numconv.Uint32ToInt32(pageSize)
	if err != nil {
		return fmt.Errorf("mindcladectl: invalid experiment page size: %w", err)
	}
	value, err := backend.client.Experiments.ListPage(ctx, boundedPageSize, pageToken)
	if err != nil {
		return err
	}
	return writeMessage(writer, value)
}

func (backend *liveBackend) Close() error {
	return backend.client.Close()
}

func writeMessage(writer io.Writer, message interface{ ProtoReflect() protoreflect.Message }) error {
	value, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(message)
	if err != nil {
		return fmt.Errorf("mindcladectl: encode generated response: %w", err)
	}
	value = append(value, '\n')
	if _, err := writer.Write(value); err != nil {
		return fmt.Errorf("mindcladectl: write response: %w", err)
	}
	return nil
}

// CommandTimeoutFromEnvironment validates the one total command budget.
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
