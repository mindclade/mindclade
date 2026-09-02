package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/mindclade/mindclade/tools/mindcladectl"
)

func main() {
	os.Exit(run())
}

func run() int {
	backend, err := mindcladectl.NewLiveBackend()
	if err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "mindcladectl: initialize private SDK: %v\n", err)
		mindcladectl.WriteErrorDiagnostics(os.Stderr, err)
		// Configuration the SDK rejected stays a usage failure; a credential
		// failure during identity discovery is already an SDK error class and
		// keeps its own code.
		if code := mindcladectl.ExitCodeFor(err); code != mindcladectl.ExitFailure {
			return code
		}
		return mindcladectl.ExitUsage
	}
	defer func() {
		if closeErr := backend.Close(); closeErr != nil {
			_, _ = fmt.Fprintf(os.Stderr, "mindcladectl: close private SDK: %v\n", closeErr)
		}
	}()
	timeout, err := mindcladectl.CommandTimeoutFromEnvironment()
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		return mindcladectl.ExitUsage
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	application := mindcladectl.Application{Backend: backend, Timeout: timeout}
	if err := application.Run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		// The exit code is derived from the SDK error hierarchy, so an operator
		// or a wrapping script can tell a policy denial from a throttle from a
		// transient service fault without scraping the message.
		mindcladectl.WriteErrorDiagnostics(os.Stderr, err)
		return mindcladectl.ExitCodeFor(err)
	}
	return mindcladectl.ExitSuccess
}
