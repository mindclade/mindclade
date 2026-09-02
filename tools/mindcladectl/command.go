package mindcladectl

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"iter"
	"strings"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/mindclade/mindclade/internal/sdk/go/mindclade"
	"github.com/mindclade/mindclade/libs/go/numconv"
)

const (
	defaultCommandTimeout = 2 * time.Minute
	maximumCommandTimeout = 30 * time.Minute
)

// Exit codes discriminate the SDK error hierarchy for operators and scripts.
// Every code above ExitUsage is produced from a typed SDK error reached with
// errors.As; the CLI never inspects a gRPC status and never invents a failure
// class the SDK does not already publish.
const (
	ExitSuccess          = 0
	ExitFailure          = 1
	ExitUsage            = 2
	ExitUnauthenticated  = 3
	ExitPermissionDenied = 4
	ExitInvalidRequest   = 5
	ExitNotFound         = 6
	ExitConflict         = 7
	ExitThrottled        = 8
	ExitUnavailable      = 9
	ExitOperationFailed  = 10
	ExitCancelled        = 11
	ExitDeadlineExceeded = 12
)

// ProtoMessage is the protobuf-runtime view of a generated message the SDK
// returned. The CLI renders SDK results structurally so it never names — and
// never imports — a generated protocol package, while the SDK's own generated
// return values remain the authoritative model. It is deliberately not a
// parallel wire type: nothing here redeclares a protocol resource.
type ProtoMessage interface{ ProtoReflect() protoreflect.Message }

// Reply is one SDK response together with the transport identity the SDK
// captured for it. Response carries the request id that is now available on
// success as well as on failure, through the SDK's raw-response accessor;
// Captured reports whether the call actually reached the transport.
type Reply struct {
	Message  ProtoMessage
	Response mindclade.ResponseMetadata
	Captured bool
}

// ListRequest is the bounded listing intent parsed from the command line. The
// page cursor stays opaque and the traversal budget is expressed in the SDK's
// own PaginationLimits, which the SDK enforces; the CLI runs no page loop of
// its own.
type ListRequest struct {
	PageSize  int32
	PageToken string
	AllPages  bool
	Limits    mindclade.PaginationLimits
}

// Listing is the CLI's presentation view of one SDK list page. It carries the
// SDK page's own generated response, its own opaque cursor and its own
// traversal sequence rather than restating any of them: Traverse is the SDK
// page's All, already bound to the caller's context and budget.
type Listing struct {
	Page          ProtoMessage
	NextPageToken string
	HasNextPage   bool
	Traverse      iter.Seq2[ProtoMessage, error]
	Response      mindclade.ResponseMetadata
	Captured      bool
}

// Backend is the narrow application boundary implemented by the private
// Mindclade SDK adapter. It deliberately exposes presentation operations, not
// generated transport clients or persistence/storage providers.
type Backend interface {
	GetOperation(ctx context.Context, name string, wait bool) (Reply, error)
	CancelOperation(ctx context.Context, name, etag, reason, idempotencyKey string) (Reply, error)
	DownloadArtifact(ctx context.Context, reference, destination string) (Reply, error)
	GetExperiment(ctx context.Context, name string) (Reply, error)
	ListExperiments(ctx context.Context, request ListRequest) (Listing, error)
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
		reply, err := application.Backend.GetExperiment(ctx, flags.Arg(0))
		if err != nil {
			return err
		}
		return writeReply(stdout, stderr, reply)
	case "list":
		request, err := parseListRequest(arguments[1:], stderr)
		if err != nil {
			return err
		}
		listing, err := application.Backend.ListExperiments(ctx, request)
		if err != nil {
			return err
		}
		return writeListing(ctx, stdout, stderr, listing, request.AllPages)
	default:
		writeExperimentUsage(stderr)
		return fmt.Errorf("mindcladectl: unknown experiment command %q", arguments[0])
	}
}

// parseListRequest builds the bounded listing intent. It applies no page-size
// ceiling of its own: the page-size contract belongs to the SDK, which rejects
// an out-of-range size as a ValidationError, and duplicating the bound here
// would let the two drift apart. The conversions below are width guards, not a
// second contract.
func parseListRequest(arguments []string, stderr io.Writer) (ListRequest, error) {
	flags := flag.NewFlagSet("experiment list", flag.ContinueOnError)
	flags.SetOutput(stderr)
	pageSize := flags.Int("page-size", 50, "bounded page size the SDK validates")
	pageToken := flags.String("page-token", "", "opaque continuation token")
	allPages := flags.Bool("all", false, "traverse every page through the SDK page under its traversal budget")
	maxPages := flags.Int("max-pages", 0, "traversal page budget for --all (0 selects the SDK default)")
	maxItems := flags.Int("max-items", 0, "traversal item budget for --all (0 selects the SDK default)")
	if err := flags.Parse(arguments); err != nil {
		return ListRequest{}, fmt.Errorf("mindcladectl: parse experiment list: %w", err)
	}
	if flags.NArg() != 0 {
		return ListRequest{}, errors.New("mindcladectl: experiment list takes no positional arguments")
	}
	if *maxPages < 0 || *maxItems < 0 {
		return ListRequest{}, errors.New("mindcladectl: experiment list traversal budgets must not be negative")
	}
	if !*allPages && (*maxPages != 0 || *maxItems != 0) {
		return ListRequest{}, errors.New("mindcladectl: --max-pages and --max-items require --all")
	}
	if *allPages && *pageToken != "" {
		return ListRequest{}, errors.New("mindcladectl: --all traverses from the first page and cannot take --page-token")
	}
	boundedPageSize, err := boundedInt32(*pageSize)
	if err != nil {
		return ListRequest{}, fmt.Errorf("mindcladectl: convert experiment list page size: %w", err)
	}
	return ListRequest{
		PageSize:  boundedPageSize,
		PageToken: *pageToken,
		AllPages:  *allPages,
		Limits:    mindclade.PaginationLimits{MaxPages: *maxPages, MaxItems: *maxItems},
	}, nil
}

// boundedInt32 narrows a parsed flag to the width the SDK list surface takes.
// It rejects a negative or oversized value before the call rather than letting
// it wrap; the value range itself is still the SDK's contract to enforce.
func boundedInt32(value int) (int32, error) {
	unsigned, err := numconv.IntToUint32(value)
	if err != nil {
		return 0, err
	}
	return numconv.Uint32ToInt32(unsigned)
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
		reply, err := application.Backend.GetOperation(ctx, flags.Arg(0), arguments[0] == "wait")
		if err != nil {
			return err
		}
		return writeReply(stdout, stderr, reply)
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
		reply, err := application.Backend.CancelOperation(ctx, name, *etag, *reason, *idempotencyKey)
		if err != nil {
			return err
		}
		return writeReply(stdout, stderr, reply)
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
	destination := flags.Arg(1)
	if strings.TrimSpace(destination) == "" {
		return errors.New("mindcladectl: artifact destination must be a file path")
	}
	// Verified download, atomic no-clobber publication and staging cleanup are
	// the SDK's DownloadFile contract. The CLI stages nothing of its own.
	reply, err := application.Backend.DownloadArtifact(ctx, flags.Arg(0), destination)
	if err != nil {
		return err
	}
	writeResponseIdentity(stderr, reply.Response, reply.Captured)
	_, err = fmt.Fprintf(stdout, "%s\n", destination)
	return err
}

// writeReply renders one SDK result: the generated message on stdout, and the
// transport identity the SDK reported for the call on stderr, so a successful
// operation can be correlated with a server log line without polluting the
// machine-readable stream.
func writeReply(stdout, stderr io.Writer, reply Reply) error {
	writeResponseIdentity(stderr, reply.Response, reply.Captured)
	if reply.Message == nil {
		return nil
	}
	return writeMessage(stdout, reply.Message)
}

// writeListing renders a page or a whole traversal. The single-page form keeps
// the generated list response as the unit of output; --all streams one
// generated item per line from the SDK page's own traversal.
func writeListing(ctx context.Context, stdout, stderr io.Writer, listing Listing, allPages bool) error {
	writeResponseIdentity(stderr, listing.Response, listing.Captured)
	if !allPages {
		if listing.HasNextPage {
			_, _ = fmt.Fprintf(stderr, "mindcladectl: more results available; resume with --page-token %s\n", listing.NextPageToken)
		}
		if listing.Page == nil {
			return nil
		}
		return writeMessage(stdout, listing.Page)
	}
	if listing.Traverse == nil {
		return errors.New("mindcladectl: backend returned no page traversal")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	for item, err := range listing.Traverse {
		if err != nil {
			return err
		}
		if item == nil {
			continue
		}
		if err := writeMessage(stdout, item); err != nil {
			return err
		}
	}
	return nil
}

// writeResponseIdentity reports the request id, trace id and status the SDK
// captured for a call. It is the success-path counterpart to the request id
// carried on every SDK error.
func writeResponseIdentity(writer io.Writer, response mindclade.ResponseMetadata, captured bool) {
	if !captured || writer == nil {
		return
	}
	fields := make([]string, 0, 3)
	if response.Status != "" {
		fields = append(fields, fmt.Sprintf("status=%s", response.Status))
	}
	if response.RequestID != "" {
		fields = append(fields, fmt.Sprintf("request_id=%s", response.RequestID))
	}
	if response.TraceID != "" {
		fields = append(fields, fmt.Sprintf("trace_id=%s", response.TraceID))
	}
	if len(fields) == 0 {
		return
	}
	_, _ = fmt.Fprintf(writer, "mindcladectl: %s\n", strings.Join(fields, " "))
}

func writeMessage(writer io.Writer, message ProtoMessage) error {
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

// ExitCodeFor classifies one command failure with errors.As against the SDK
// error hierarchy. The CLI reads only what the SDK publishes: it never inspects
// a gRPC status code and never adds a failure class of its own.
func ExitCodeFor(err error) int {
	if err == nil {
		return ExitSuccess
	}
	// A deadline classifies as the SDK's residual TransportError, so the one
	// distinction the typed hierarchy does not draw is taken from the SDK's own
	// transport-neutral Code on the base carrier — never from a gRPC status.
	var base *mindclade.Error
	if errors.As(err, &base) && base != nil && base.Code == mindclade.CodeDeadlineExceeded {
		return ExitDeadlineExceeded
	}
	var (
		authentication *mindclade.AuthenticationError
		authorization  *mindclade.AuthorizationError
		validation     *mindclade.ValidationError
		notFound       *mindclade.NotFoundError
		conflict       *mindclade.ConflictError
		rateLimit      *mindclade.RateLimitError
		quota          *mindclade.QuotaError
		retryable      *mindclade.RetryableServiceError
		operation      *mindclade.OperationFailedError
		cancelled      *mindclade.CancelledError
		transport      *mindclade.TransportError
	)
	switch {
	case errors.As(err, &authentication):
		return ExitUnauthenticated
	case errors.As(err, &authorization):
		return ExitPermissionDenied
	case errors.As(err, &validation):
		return ExitInvalidRequest
	case errors.As(err, &notFound):
		return ExitNotFound
	case errors.As(err, &conflict):
		return ExitConflict
	case errors.As(err, &rateLimit), errors.As(err, &quota):
		return ExitThrottled
	case errors.As(err, &retryable):
		return ExitUnavailable
	case errors.As(err, &operation):
		return ExitOperationFailed
	case errors.As(err, &cancelled):
		return ExitCancelled
	case errors.As(err, &transport):
		// TransportError is the SDK's residual class: a dial or stream failure,
		// an unknown method, reported data loss, or an unclassified fault.
		return ExitUnavailable
	case errors.Is(err, context.DeadlineExceeded):
		return ExitDeadlineExceeded
	case errors.Is(err, context.Canceled):
		return ExitCancelled
	default:
		// A local failure that never reached the SDK: argument parsing, or a
		// filesystem fault in the CLI's own output path.
		return ExitFailure
	}
}

// WriteErrorDiagnostics renders the safe structured detail the SDK attached to
// a failure. Every field is read back through the SDK error hierarchy, which
// has already sanitized it; the CLI adds no server-authored text of its own.
func WriteErrorDiagnostics(writer io.Writer, err error) {
	var sdkError mindclade.MindcladeError
	if writer == nil || !errors.As(err, &sdkError) {
		return
	}
	fields := []string{
		fmt.Sprintf("code=%s", sdkError.ErrorCode()),
		fmt.Sprintf("retry=%s", sdkError.Retryability()),
	}
	requestID, traceID := sdkError.RequestIdentity()
	if requestID != "" {
		fields = append(fields, fmt.Sprintf("request_id=%s", requestID))
	}
	if traceID != "" {
		fields = append(fields, fmt.Sprintf("trace_id=%s", traceID))
	}
	if operationID := sdkError.OperationIdentity(); operationID != "" {
		fields = append(fields, fmt.Sprintf("operation_id=%s", operationID))
	}
	if retryAfter, hinted := sdkError.RetryAfterHint(); hinted {
		fields = append(fields, fmt.Sprintf("retry_after=%s", retryAfter))
	}
	if revision := sdkError.Revision(); revision != "" {
		fields = append(fields, fmt.Sprintf("revision=%s", revision))
	}
	if attempts, cumulative := sdkError.RetryOutcome(); attempts > 0 {
		fields = append(fields, fmt.Sprintf("attempts=%d", attempts), fmt.Sprintf("retry_delay=%s", cumulative))
	}
	if quota := sdkError.QuotaTelemetry(); quota != nil && quota.Subject != "" {
		fields = append(fields, fmt.Sprintf("quota_subject=%s", quota.Subject), fmt.Sprintf("quota_remaining=%d", quota.Remaining))
	}
	if diagnostic := sdkError.Diagnostic(); diagnostic != "" {
		fields = append(fields, fmt.Sprintf("diagnostic=%s", diagnostic))
	}
	_, _ = fmt.Fprintf(writer, "mindcladectl: %s\n", strings.Join(fields, " "))
	fieldViolations, preconditionViolations := sdkError.Violations()
	for _, violation := range fieldViolations {
		_, _ = fmt.Fprintf(writer, "mindcladectl: field %s: %s\n", violation.GetField(), violation.GetDescription())
	}
	for _, violation := range preconditionViolations {
		_, _ = fmt.Fprintf(writer, "mindcladectl: precondition %s on %s: %s\n", violation.GetType(), violation.GetSubject(), violation.GetDescription())
	}
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
	_, _ = io.WriteString(writer, "  mindcladectl experiment get NAME\n  mindcladectl experiment list [--page-size N] [--page-token TOKEN]\n  mindcladectl experiment list --all [--max-pages N] [--max-items N]\n")
}
