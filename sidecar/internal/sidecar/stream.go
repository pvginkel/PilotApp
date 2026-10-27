package sidecar

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sync"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// The change stream's reconnect (design 1 §5.1, §5.4): after a drop, a wait
// doubling from backoffMin to backoffMax, back to backoffMin once a
// connection has reconciled; after a 426, unsupportedWait.
const (
	backoffMin      = time.Second
	backoffMax      = 30 * time.Second
	unsupportedWait = 60 * time.Second
)

// keep holds the change stream until ctx is done: each connection
// reconciles the tree, then applies the stream's events until it drops.
func (s *Sidecar) keep(ctx context.Context) {
	delay := backoffMin
	for {
		reconciled, err := s.session(ctx)
		if ctx.Err() != nil {
			return
		}
		var wait time.Duration
		var unsupported *protocol.UnsupportedError
		if errors.As(err, &unsupported) {
			wait = unsupportedWait
			s.logger.Error("the server does not serve this sync protocol: retrying",
				"min", unsupported.Min, "max", unsupported.Max, "version", protocol.Version, "in", wait)
		} else {
			if reconciled {
				delay = backoffMin
			}
			wait = delay
			delay = min(delay*2, backoffMax)
			s.logger.Warn("the change stream dropped: reconnecting", "error", err, "in", wait)
		}
		if !s.sleep(ctx, wait) {
			return
		}
	}
}

// session is one connection of the change stream, until it drops or ctx is
// done; reconciled says whether its reconcile on connect ran to its end.
func (s *Sidecar) session(ctx context.Context) (reconciled bool, err error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream, err := s.tree.client.Events(ctx)
	if err != nil {
		return false, err
	}
	s.logger.Info("the change stream is open", "min", stream.Hello.Protocol.Min, "max", stream.Hello.Protocol.Max,
		"manifest_hash", stream.Hello.ManifestHash)
	// What was asked for while away, the reconcile on connect does.
	select {
	case <-s.wanted:
	default:
	}
	changes := newChanges(ctx, s.tree)
	var dropped error
	listened := make(chan struct{})
	go func() {
		dropped = s.listen(stream, changes)
		close(listened)
	}()
	defer func() {
		cancel()
		<-listened
		changes.close()
		err = errors.Join(err, stream.Close())
	}()
	if err := s.reconcile(ctx); err != nil {
		return false, err
	}
	for {
		select {
		case <-ctx.Done():
			return true, nil
		case <-listened:
			return true, dropped
		case <-s.wanted:
			if err := s.reconcile(ctx); err != nil {
				return true, err
			}
		}
	}
}

// listen applies the stream's events until it ends: a change is fetched, a
// manifest event asks for a reconcile.
func (s *Sidecar) listen(stream *protocol.Stream, changes *changes) error {
	for {
		event, err := stream.Next()
		if err != nil {
			return err
		}
		switch event := event.(type) {
		case protocol.Change:
			changes.moved(event)
		case protocol.ManifestChanged:
			s.want()
		case protocol.Unknown:
			s.logger.Info("an event this version does not know: ignored", "event", event.Name)
		}
	}
}

// want asks the session for a reconcile.
func (s *Sidecar) want() {
	select {
	case s.wanted <- struct{}{}:
	default:
	}
}

// overflowed is told the watch lost events: the tree is walked whole and
// reconciled (design 1 §5.8).
func (s *Sidecar) overflowed() {
	s.want()
}

// reconcile makes the tree the record's projection (design 1 §5.5): what
// changed on disk since it synced goes up first; then the tree's hashes and
// the shadow's are posted, the answer's paths are written down, its
// read-only views given the view's mode, and its deletes deleted.
func (s *Sidecar) reconcile(ctx context.Context) error {
	t := s.tree
	disk, err := t.walk("")
	if err != nil {
		return fmt.Errorf("reconcile: walk the tree: %w", err)
	}
	var changed []string
	for path, hash := range disk {
		if synced, _ := t.shadow.Hash(path); synced != hash {
			changed = append(changed, path)
		}
	}
	slices.Sort(changed)
	s.uploads.send(changed)
	if disk, err = t.walk(""); err != nil {
		return fmt.Errorf("reconcile: walk the tree: %w", err)
	}
	answer, err := t.client.Manifest(ctx, disk, t.shadow.Hashes())
	if err != nil {
		return fmt.Errorf("reconcile: %w", err)
	}
	t.listed(answer.Manifest)
	var written sync.WaitGroup
	for _, entry := range answer.WriteDown {
		written.Go(func() {
			release, ok := t.hold(ctx, entry.Path)
			if !ok {
				return
			}
			defer release()
			t.download(ctx, entry.Path)
		})
	}
	written.Wait()
	for _, entry := range answer.Manifest {
		if !entry.Readonly {
			continue
		}
		release, ok := t.hold(ctx, entry.Path)
		if !ok {
			break
		}
		t.protect(entry.Path)
		release()
	}
	for _, path := range answer.Delete {
		release, ok := t.hold(ctx, path)
		if !ok {
			break
		}
		t.remove(path)
		release()
	}
	if ctx.Err() != nil {
		return fmt.Errorf("reconcile: %w", ctx.Err())
	}
	s.logger.Info("reconciled", "sent_up", len(changed), "listed", len(answer.Manifest),
		"written_down", len(answer.WriteDown), "deleted", len(answer.Delete))
	return nil
}
