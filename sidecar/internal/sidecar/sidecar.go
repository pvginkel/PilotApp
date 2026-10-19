// Package sidecar is pilot-sync: the store's tree kept a live projection of
// the record, in both directions (design 1 §5).
package sidecar

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/config"
	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
	"github.com/pvginkel/PilotApp/sidecar/internal/shadow"
	"github.com/pvginkel/PilotApp/sidecar/internal/watch"
)

// Sidecar is pilot-sync, ready to run.
type Sidecar struct {
	tree    *tree
	watcher *watch.Watcher
	uploads *uploads
	logger  *slog.Logger
	// wanted holds a reconcile asked for and not yet run.
	wanted chan struct{}
	// sleep waits d, false when ctx is done first.
	sleep func(ctx context.Context, d time.Duration) bool
}

// New readies the sidecar cfg configures: its data directory proven
// writable, its shadow loaded from it, and its tree, made when there is
// none, watched.
func New(cfg config.Config, logger *slog.Logger) (*Sidecar, error) {
	if err := probe(cfg.DataDir); err != nil {
		return nil, fmt.Errorf("cannot write the data directory %s: %w", cfg.DataDir, err)
	}
	store, err := shadow.Open(filepath.Join(cfg.DataDir, "shadow"))
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(cfg.TreeRoot, 0o755); err != nil {
		return nil, fmt.Errorf("cannot make the tree %s: %w", cfg.TreeRoot, err)
	}
	t := newTree(cfg.TreeRoot, protocol.NewClient(cfg.PilotURL, cfg.Token, cfg.EnvironmentID), store, logger)
	s := &Sidecar{tree: t, uploads: newUploads(t), logger: logger, wanted: make(chan struct{}, 1), sleep: sleep}
	if s.watcher, err = watch.New(cfg.TreeRoot, watch.Debounce, s.uploads.changed, s.overflowed, logger); err != nil {
		return nil, err
	}
	return s, nil
}

// Run keeps the tree until ctx is done, then abandons the calls still out.
func (s *Sidecar) Run(ctx context.Context) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	kept := make(chan struct{})
	go func() {
		s.keep(ctx)
		close(kept)
	}()
	err := s.watcher.Run(ctx)
	cancel()
	s.uploads.close()
	<-kept
	return err
}

func sleep(ctx context.Context, d time.Duration) bool {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-ctx.Done():
		return false
	}
}

// probe makes dir when there is none and writes a file in it, so a data
// directory the sidecar cannot write stops it at the start.
func probe(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	file, err := os.CreateTemp(dir, files.TempPrefix+"probe-*")
	if err != nil {
		return err
	}
	return errors.Join(file.Close(), os.Remove(file.Name()))
}
