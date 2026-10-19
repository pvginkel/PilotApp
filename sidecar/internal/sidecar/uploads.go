package sidecar

import (
	"bytes"
	"context"
	"errors"
	"io/fs"
	"os"
	"sync"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// uploads sends the tree's files up as they change: a file whose hash is not
// its shadow's goes up with the shadow's hash as its base, and the answer is
// recorded in the shadow and, when it carries bytes, written in place. A
// file the sidecar wrote itself hashes as its shadow, so it never goes up.
type uploads struct {
	tree   *tree
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup

	mu     sync.Mutex
	out    map[string]*pending
	closed bool
}

// pending is a path being sent up: whether it changed since its PUT read it,
// and the callers of send waiting for the next PUT to read it.
type pending struct {
	again   bool
	waiting []*sync.WaitGroup
}

func newUploads(t *tree) *uploads {
	ctx, cancel := context.WithCancel(context.Background())
	return &uploads{tree: t, ctx: ctx, cancel: cancel, out: map[string]*pending{}}
}

// changed is told the file at path, from the tree's root, changed.
func (u *uploads) changed(path string) {
	u.queue(path, nil)
}

// send sends each of paths up and waits until each has been read after the
// call, and sent or found in sync.
func (u *uploads) send(paths []string) {
	var done sync.WaitGroup
	for _, path := range paths {
		u.queue(path, &done)
	}
	done.Wait()
}

func (u *uploads) queue(path string, done *sync.WaitGroup) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.closed {
		return
	}
	entry, out := u.out[path]
	if !out {
		entry = &pending{}
		u.out[path] = entry
		u.wg.Add(1)
		go u.run(path, entry)
	}
	entry.again = true
	if done != nil {
		done.Add(1)
		entry.waiting = append(entry.waiting, done)
	}
}

// run sends path up until it no longer changed while its PUT was out.
func (u *uploads) run(path string, entry *pending) {
	defer u.wg.Done()
	for {
		u.mu.Lock()
		waiting := entry.waiting
		entry.waiting = nil
		next := entry.again && !u.closed
		entry.again = false
		if !next {
			delete(u.out, path)
		}
		u.mu.Unlock()
		if next {
			u.upload(path)
		}
		for _, done := range waiting {
			done.Done()
		}
		if !next {
			return
		}
	}
}

// close takes no more changes, abandons the PUTs out and waits for them.
func (u *uploads) close() {
	u.mu.Lock()
	u.closed = true
	u.mu.Unlock()
	u.cancel()
	u.wg.Wait()
}

// upload sends the file of path up, unless it is in sync.
func (u *uploads) upload(path string) {
	t := u.tree
	release, ok := t.hold(u.ctx, path)
	if !ok {
		return
	}
	defer release()
	name := t.name(path)
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		// Gone: no delete goes up (design 1 §5.5).
		t.notes.clear(path)
		return
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	if !info.Mode().IsRegular() {
		return
	}
	sent, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		t.notes.clear(path)
		return
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	base, _ := t.shadow.Hash(path)
	if protocol.Hash(sent) == base {
		return
	}
	answer, err := t.client.Put(u.ctx, path, sent, base)
	switch {
	case err == nil:
	case u.ctx.Err() != nil:
		return
	case errors.Is(err, protocol.ErrNotFound):
		t.notes.note(path, strayNote)
		t.logger.Info("not a path of the record: left as it is", "path", path)
		return
	default:
		// Left for the next reconcile, whose first step sends it up.
		t.logger.Error("cannot sync a file of the tree", "path", path, "error", err)
		return
	}
	held := sent
	if answer.Content != nil {
		held = answer.Content
	}
	if err := t.shadow.Put(path, held); err != nil {
		t.logger.Error("cannot record a sync", "path", path, "error", err)
		return
	}
	t.notes.clear(path)
	if answer.Content != nil {
		if err := writeAnswer(name, sent, answer.Content, info.Mode().Perm()); err != nil {
			t.logger.Error("cannot write a sync's answer", "path", path, "error", err)
			return
		}
	}
	t.logger.Info("synced", "path", path, "hash", answer.Hash, "rewritten", answer.Content != nil,
		"stale", answer.Stale, "faults", answer.Faults)
}

// writeAnswer writes answer over the file at name while it still holds
// sent. What the agent wrote while the PUT was out is newer than the answer:
// it stays, and goes up next with the answer's hash as its base.
func writeAnswer(name string, sent, answer []byte, mode fs.FileMode) error {
	now, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if !bytes.Equal(now, sent) {
		return nil
	}
	return files.Write(name, answer, mode)
}
