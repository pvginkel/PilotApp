// Command pilot-sync is the store environment's sync sidecar: it keeps the
// tree of Pilot's managed projects a live projection of Pilot's record, in
// both directions (design 1 §5). Its configuration is its environment's;
// internal/config names the variables.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/pvginkel/PilotApp/sidecar/internal/config"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
	"github.com/pvginkel/PilotApp/sidecar/internal/sidecar"
)

func main() {
	os.Exit(run())
}

func run() int {
	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))
	cfg, err := config.FromEnv(os.LookupEnv)
	if err != nil {
		logger.Error("pilot-sync cannot start", "error", err)
		return 1
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	s, err := sidecar.New(cfg, logger)
	if err != nil {
		logger.Error("pilot-sync cannot start", "error", err)
		return 1
	}
	logger.Info("pilot-sync is keeping the tree", "server", cfg.PilotURL, "environment", cfg.EnvironmentID,
		"tree", cfg.TreeRoot, "data", cfg.DataDir, "protocol", protocol.Version)
	if err := s.Run(ctx); err != nil {
		logger.Error("pilot-sync stopped", "error", err)
		return 1
	}
	return 0
}
