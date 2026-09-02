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
		return 2
	}
	defer func() {
		if closeErr := backend.Close(); closeErr != nil {
			_, _ = fmt.Fprintf(os.Stderr, "mindcladectl: close private SDK: %v\n", closeErr)
		}
	}()
	timeout, err := mindcladectl.CommandTimeoutFromEnvironment()
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		return 2
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	application := mindcladectl.Application{Backend: backend, Timeout: timeout}
	if err := application.Run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
