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
// file the sidecar wrote itself hashes as its shadow, so it never goes up; a
// read-only view written is reverted, and never goes up.
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
// and the callers waiting for the next pass to read it, each told the hash
// that pass came to (upload).
type pending struct {
	again   bool
	waiting []func(settled string)
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
		done.Add(1)
		u.queue(path, func(string) { done.Done() })
	}
	done.Wait()
}

// settle sends path up and answers, once a pass has read it after the call,
// the hash that pass came to (upload).
func (u *uploads) settle(path string) <-chan string {
	settled := make(chan string, 1)
	u.queue(path, func(hash string) { settled <- hash })
	return settled
}

// queue has path sent up, and told, when it is not nil, the hash of the next
// pass to read it.
func (u *uploads) queue(path string, told func(settled string)) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.closed {
		if told != nil {
			told("")
		}
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
	if told != nil {
		entry.waiting = append(entry.waiting, told)
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
		var settled string
		if next {
			settled = u.upload(path)
		}
		for _, told := range waiting {
			told(settled)
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

// upload sends the file of path up unless it is in sync, or reverts it, a
// read-only view the shadow holds. It answers the hash the file is checked
// with: the hash the server holds for the bytes it read — theirs, those of
// the answer written in place, or the view's re-projected — or theirs when
// the server refused the path as none of the record's; "" when it came to
// neither.
func (u *uploads) upload(path string) string {
	t := u.tree
	release, ok := t.hold(u.ctx, path)
	if !ok {
		return ""
	}
	defer release()
	name := t.name(path)
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		// Gone: no delete goes up (design 1 §5.5).
		t.notes.clear(path)
		return ""
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return ""
	}
	if !info.Mode().IsRegular() {
		return ""
	}
	sent, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		t.notes.clear(path)
		return ""
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return ""
	}
	base, synced := t.shadow.Hash(path)
	if protocol.Hash(sent) == base {
		return base
	}
	view := t.view(path)
	if view && synced {
		return t.revert(path)
	}
	answer, err := t.client.Put(u.ctx, path, sent, base)
	switch {
	case err == nil:
	case u.ctx.Err() != nil:
		return ""
	case errors.Is(err, protocol.ErrNotFound):
		t.notes.keep(path, strayNote)
		t.logger.Info("not a path of the record: left as it is", "path", path)
		return protocol.Hash(sent)
	default:
		// Left for the next reconcile, whose first step sends it up.
		t.logger.Error("cannot sync a file of the tree", "path", path, "error", err)
		return ""
	}
	held := sent
	if answer.Content != nil {
		held = answer.Content
	}
	if err := t.shadow.Put(path, held); err != nil {
		t.logger.Error("cannot record a sync", "path", path, "error", err)
		return ""
	}
	t.notes.clear(path)
	if answer.Content != nil {
		mode := info.Mode().Perm()
		if view {
			mode = viewMode
		}
		if err := writeAnswer(name, sent, answer.Content, mode); err != nil {
			t.logger.Error("cannot write a sync's answer", "path", path, "error", err)
			return ""
		}
	}
	t.logger.Info("synced", "path", path, "hash", answer.Hash, "rewritten", answer.Content != nil,
		"stale", answer.Stale, "faults", answer.Faults)
	return answer.Hash
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
