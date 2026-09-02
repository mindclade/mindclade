package mindcladectl

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/mindclade/mindclade/libs/go/numconv"
)

const (
	defaultCommandTimeout = 2 * time.Minute
	maximumCommandTimeout = 30 * time.Minute
)

// Backend is the narrow application boundary implemented by the private
// Mindclade SDK adapter. It deliberately exposes presentation operations, not
// generated transport clients or persistence/storage providers.
type Backend interface {
	WriteOperation(context.Context, string, bool, io.Writer) error
	CancelOperation(context.Context, string, string, string, string, io.Writer) error
	DownloadArtifact(context.Context, string, io.Writer) error
	WriteExperiment(context.Context, string, io.Writer) error
	ListExperiments(context.Context, uint32, string, io.Writer) error
	Close() error
}

// Application parses bounded administrative commands and applies one total
// deadline across authentication, retries, streaming, and local output.
type Application struct {
	Backend Backend
	Timeout time.Duration
}

// Run executes one command. It never terminates the process, which keeps the
// command path hermetic and cancellation-testable.
func (application Application) Run(ctx context.Context, arguments []string, stdout, stderr io.Writer) error {
	if ctx == nil {
		return errors.New("mindcladectl: context is required")
	}
	if application.Backend == nil {
		return errors.New("mindcladectl: backend is required")
	}
	if stdout == nil || stderr == nil {
		return errors.New("mindcladectl: output streams are required")
	}
	timeout := application.Timeout
	if timeout == 0 {
		timeout = defaultCommandTimeout
	}
	if timeout <= 0 || timeout > maximumCommandTimeout {
		return errors.New("mindcladectl: command timeout must be positive and at most thirty minutes")
	}
	commandContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if len(arguments) == 0 {
		writeUsage(stderr)
		return errors.New("mindcladectl: a command is required")
	}

	switch arguments[0] {
	case "operation":
		return application.runOperation(commandContext, arguments[1:], stdout, stderr)
	case "artifact":
		return application.runArtifact(commandContext, arguments[1:], stdout, stderr)
	case "experiment":
		return application.runExperiment(commandContext, arguments[1:], stdout, stderr)
	case "help", "-h", "--help":
		writeUsage(stdout)
		return nil
	default:
		writeUsage(stderr)
		return fmt.Errorf("mindcladectl: unknown command %q", arguments[0])
	}
}

func (application Application) runExperiment(ctx context.Context, arguments []string, stdout, stderr io.Writer) error {
	if len(arguments) == 0 {
		writeExperimentUsage(stderr)
		return errors.New("mindcladectl: an experiment command is required")
	}
	switch arguments[0] {
	case "get":
		flags := flag.NewFlagSet("experiment get", flag.ContinueOnError)
		flags.SetOutput(stderr)
		if err := flags.Parse(arguments[1:]); err != nil {
			return fmt.Errorf("mindcladectl: parse experiment get: %w", err)
		}
		if flags.NArg() != 1 {
			return errors.New("mindcladectl: experiment get requires exactly one experiment name")
		}
		return application.Backend.WriteExperiment(ctx, flags.Arg(0), stdout)
	case "list":
		flags := flag.NewFlagSet("experiment list", flag.ContinueOnError)
		flags.SetOutput(stderr)
		pageSize := flags.Int("page-size", 50, "bounded page size (1-200)")
		pageToken := flags.String("page-token", "", "opaque continuation token")
		if err := flags.Parse(arguments[1:]); err != nil {
			return fmt.Errorf("mindcladectl: parse experiment list: %w", err)
		}
		if flags.NArg() != 0 || *pageSize < 1 || *pageSize > 200 {
			return errors.New("mindcladectl: experiment list page size must be between 1 and 200")
		}
		boundedPageSize, err := numconv.IntToUint32(*pageSize)
		if err != nil {
			return fmt.Errorf("mindcladectl: convert experiment list page size: %w", err)
		}
		return application.Backend.ListExperiments(ctx, boundedPageSize, *pageToken, stdout)
	default:
		writeExperimentUsage(stderr)
		return fmt.Errorf("mindcladectl: unknown experiment command %q", arguments[0])
	}
}

func (application Application) runOperation(ctx context.Context, arguments []string, stdout, stderr io.Writer) error {
	if len(arguments) == 0 {
		writeOperationUsage(stderr)
		return errors.New("mindcladectl: an operation command is required")
	}
	switch arguments[0] {
	case "get", "wait":
		flags := flag.NewFlagSet("operation "+arguments[0], flag.ContinueOnError)
		flags.SetOutput(stderr)
		if err := flags.Parse(arguments[1:]); err != nil {
			return fmt.Errorf("mindcladectl: parse operation %s: %w", arguments[0], err)
		}
		if flags.NArg() != 1 {
			return fmt.Errorf("mindcladectl: operation %s requires exactly one operation name", arguments[0])
		}
		return application.Backend.WriteOperation(ctx, flags.Arg(0), arguments[0] == "wait", stdout)
	case "cancel":
		flags := flag.NewFlagSet("operation cancel", flag.ContinueOnError)
		flags.SetOutput(stderr)
		etag := flags.String("etag", "", "current operation ETag")
		reason := flags.String("reason", "", "bounded cancellation reason")
		idempotencyKey := flags.String("idempotency-key", "", "stable retry key")
		if len(arguments) < 2 {
			return errors.New("mindcladectl: operation cancel requires NAME, --etag, --reason, and --idempotency-key")
		}
		name := arguments[1]
		if err := flags.Parse(arguments[2:]); err != nil {
			return fmt.Errorf("mindcladectl: parse operation cancel: %w", err)
		}
		if flags.NArg() != 0 || strings.TrimSpace(name) == "" || strings.TrimSpace(*etag) == "" || strings.TrimSpace(*reason) == "" || strings.TrimSpace(*idempotencyKey) == "" {
			return errors.New("mindcladectl: operation cancel requires NAME, --etag, --reason, and --idempotency-key")
		}
		return application.Backend.CancelOperation(ctx, name, *etag, *reason, *idempotencyKey, stdout)
	default:
		writeOperationUsage(stderr)
		return fmt.Errorf("mindcladectl: unknown operation command %q", arguments[0])
	}
}

func (application Application) runArtifact(ctx context.Context, arguments []string, stdout, stderr io.Writer) error {
	if len(arguments) == 0 || arguments[0] != "download" {
		writeArtifactUsage(stderr)
		return errors.New("mindcladectl: artifact download is the supported artifact command")
	}
	flags := flag.NewFlagSet("artifact download", flag.ContinueOnError)
	flags.SetOutput(stderr)
	if err := flags.Parse(arguments[1:]); err != nil {
		return fmt.Errorf("mindcladectl: parse artifact download: %w", err)
	}
	if flags.NArg() != 2 {
		return errors.New("mindcladectl: artifact download requires REF and DESTINATION")
	}
	return downloadAtomically(ctx, application.Backend, flags.Arg(0), flags.Arg(1), stdout)
}

func downloadAtomically(ctx context.Context, backend Backend, reference, destination string, stdout io.Writer) error {
	destination = filepath.Clean(destination)
	if destination == "." || destination == string(filepath.Separator) {
		return errors.New("mindcladectl: artifact destination must be a file path")
	}
	if _, err := os.Lstat(destination); err == nil {
		return fmt.Errorf("mindcladectl: artifact destination already exists: %s", destination)
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("mindcladectl: inspect artifact destination: %w", err)
	}
	parent := filepath.Dir(destination)
	temporary, err := os.CreateTemp(parent, ".mindclade-artifact-*.partial")
	if err != nil {
		return fmt.Errorf("mindcladectl: create artifact staging file: %w", err)
	}
	temporaryName := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryName)
		}
	}()
	if downloadErr := backend.DownloadArtifact(ctx, reference, temporary); downloadErr != nil {
		return downloadErr
	}
	if syncErr := temporary.Sync(); syncErr != nil {
		return fmt.Errorf("mindcladectl: sync artifact staging file: %w", syncErr)
	}
	if closeErr := temporary.Close(); closeErr != nil {
		return fmt.Errorf("mindcladectl: close artifact staging file: %w", closeErr)
	}
	// Link provides atomic create-without-overwrite semantics. Rename would be
	// unsafe here because it replaces an existing destination on Unix.
	if linkErr := os.Link(temporaryName, destination); linkErr != nil {
		return fmt.Errorf("mindcladectl: commit artifact without overwrite: %w", linkErr)
	}
	if removeErr := os.Remove(temporaryName); removeErr != nil {
		return fmt.Errorf("mindcladectl: remove artifact staging link: %w", removeErr)
	}
	committed = true
	_, err = fmt.Fprintf(stdout, "%s\n", destination)
	return err
}

func writeUsage(writer io.Writer) {
	_, _ = io.WriteString(writer, "usage: mindcladectl {operation|artifact|experiment} ...\n")
	writeOperationUsage(writer)
	writeArtifactUsage(writer)
	writeExperimentUsage(writer)
}

func writeOperationUsage(writer io.Writer) {
	_, _ = io.WriteString(writer, "  mindcladectl operation get NAME\n  mindcladectl operation wait NAME\n  mindcladectl operation cancel NAME --etag ETAG --reason REASON --idempotency-key KEY\n")
}

func writeArtifactUsage(writer io.Writer) {
	_, _ = io.WriteString(writer, "  mindcladectl artifact download REF DESTINATION\n")
}

func writeExperimentUsage(writer io.Writer) {
	_, _ = io.WriteString(writer, "  mindcladectl experiment get NAME\n  mindcladectl experiment list [--page-size N] [--page-token TOKEN]\n")
}
