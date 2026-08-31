package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	grpcAddress := valueOrDefault(os.Getenv("MINDCLADE_GRPC_ADDR"), "127.0.0.1:8081")
	httpAddress := valueOrDefault(os.Getenv("MINDCLADE_HTTP_ADDR"), "127.0.0.1:8080")
	server, err := newRuntime(
		grpcAddress,
		httpAddress,
		os.Getenv("MINDCLADE_BEARER_TOKEN"),
		unavailableTrainingFoundation{},
	)
	if err != nil {
		slog.Error("control plane setup failed", "error", err)
		os.Exit(1)
	}
	signals, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	failed := make(chan error, 1)
	go func() { failed <- server.serve() }()
	select {
	case <-signals.Done():
	case serveErr := <-failed:
		if serveErr != nil {
			slog.Error("control plane stopped unexpectedly", "error", serveErr)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := server.shutdown(ctx); err != nil && !errors.Is(err, context.Canceled) {
		slog.Error("control plane shutdown failed", "error", err)
	}
}

func valueOrDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}
