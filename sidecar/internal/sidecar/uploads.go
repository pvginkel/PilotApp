package sidecar

import (
	"bytes"
	"context"
	"errors"
	"io/fs"
	"os"
	"sync"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// The retry of an upload whose PUT failed for a reason that can pass
// (protocol.Transient): after a wait doubling from retryMin to retryMax, back
// to retryMin once a pass of the path ends otherwise.
const (
	retryMin = time.Second
	retryMax = 30 * time.Second
)

// uploads sends the tree's files up as they change: a file whose hash is not
// its shadow's goes up with the shadow's hash as its base, as the save of
// the session its bytes are (tree.writer), and the answer is recorded in
// the shadow and, when it carries bytes, written in place. A
// file the sidecar wrote itself hashes as its shadow, so it never goes up; a
// read-only view written is reverted, and never goes up. A PUT that failed
// for a reason that can pass is made again until the file lands or is in
// sync; any other failure is left for the next reconcile.
type uploads struct {
	tree   *tree
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
	// after is the wait before a retry: time.After, or a test's.
	after func(time.Duration) <-chan time.Time

	mu  sync.Mutex
	out map[string]*pending
	// failed holds each path whose last PUT failed, but for a stray's 404:
	// the changes waiting to go up.
	failed map[string]bool
	closed bool
}

// pending is a path being sent up: whether it changed since its PUT read it,
// the callers waiting for the next pass to read it, each told the hash
// that pass came to (upload), and woken, signalled as a change sets again,
// so that the change ends a wait before a retry.
type pending struct {
	again   bool
	waiting []func(settled string)
	woken   chan struct{}
}

func newUploads(t *tree) *uploads {
	ctx, cancel := context.WithCancel(context.Background())
	return &uploads{
		tree: t, ctx: ctx, cancel: cancel, after: time.After, out: map[string]*pending{}, failed: map[string]bool{},
	}
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
		entry = &pending{woken: make(chan struct{}, 1)}
		u.out[path] = entry
		u.wg.Add(1)
		go u.run(path, entry)
	}
	entry.again = true
	select {
	case entry.woken <- struct{}{}:
	default:
	}
	if told != nil {
		entry.waiting = append(entry.waiting, told)
	}
}

// run sends path up until it no longer changed while its PUT was out, and
// again after a wait while its last PUT failed for a reason that can pass.
func (u *uploads) run(path string, entry *pending) {
	defer u.wg.Done()
	wait := retryMin
	for {
		u.mu.Lock()
		waiting := entry.waiting
		entry.waiting = nil
		next := entry.again && !u.closed
		entry.again = false
		select {
		case <-entry.woken:
		default:
		}
		if !next {
			delete(u.out, path)
		}
		u.mu.Unlock()
		var settled string
		var err error
		if next {
			settled, err = u.upload(path)
			u.left(path, err, wait)
		}
		for _, told := range waiting {
			told(settled)
		}
		if !next {
			return
		}
		if !protocol.Transient(err) {
			wait = retryMin
			continue
		}
		u.pause(entry, wait)
		wait = min(wait*2, retryMax)
	}
}

// pause waits d before the next pass of entry's path, unless a change of the
// path or the uploads' close ends the wait first.
func (u *uploads) pause(entry *pending, d time.Duration) {
	select {
	case <-u.after(d):
		u.mu.Lock()
		entry.again = true
		u.mu.Unlock()
	case <-entry.woken:
	case <-u.ctx.Done():
	}
}

// left records whether a pass of path left its bytes waiting to go up, err
// the pass's PUT failure, nil when it had none, and logs it: the failure,
// with the wait before its retry when it can pass, or the end of a wait to
// go up.
func (u *uploads) left(path string, err error, wait time.Duration) {
	u.mu.Lock()
	failed := u.failed[path]
	if err != nil {
		u.failed[path] = true
	} else {
		delete(u.failed, path)
	}
	count := len(u.failed)
	u.mu.Unlock()
	logger := u.tree.logger
	switch {
	case protocol.Transient(err):
		logger.Warn("cannot sync a file of the tree: retrying", "path", path, "error", err, "in", wait,
			"pending", count)
	case err != nil:
		logger.Error("cannot sync a file of the tree", "path", path, "error", err, "pending", count)
	case failed:
		logger.Info("no longer waiting to go up", "path", path, "pending", count)
	}
}

// pending is how many changes wait to go up: the paths whose last PUT
// failed, but for a stray's 404.
func (u *uploads) pending() int {
	u.mu.Lock()
	defer u.mu.Unlock()
	return len(u.failed)
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
// neither. Its error is the PUT's failure, which leaves the bytes waiting to
// go up; nil when the PUT was not made, landed, or was a stray's 404.
func (u *uploads) upload(path string) (string, error) {
	t := u.tree
	release, ok := t.hold(u.ctx, path)
	if !ok {
		return "", nil
	}
	defer release()
	file, ok := t.read(path)
	if !ok {
		return "", nil
	}
	sent := file.content
	base, synced := t.shadow.Hash(path)
	if file.hash == base {
		t.unsent.sent(path, base)
		return base, nil
	}
	view := t.view(path)
	if view && synced {
		return t.revert(path), nil
	}
	answer, err := t.client.Put(u.ctx, path, sent, base, file.session)
	switch {
	case err == nil:
	case u.ctx.Err() != nil:
		return "", nil
	case errors.Is(err, protocol.ErrNotFound):
		t.notes.stray(path, file.hash)
		t.logger.Info("not a path of the record: left as it is", "path", path)
		return file.hash, nil
	default:
		return "", err
	}
	held := sent
	if answer.Content != nil {
		held = answer.Content
	}
	if err := t.shadow.Put(path, held); err != nil {
		t.logger.Error("cannot record a sync", "path", path, "error", err)
		return "", nil
	}
	t.unsent.sent(path, file.hash)
	t.notes.clear(path)
	if answer.Content != nil {
		mode := file.mode
		if view {
			mode = viewMode
		}
		if err := writeAnswer(t.name(path), sent, answer.Content, mode); err != nil {
			t.logger.Error("cannot write a sync's answer", "path", path, "error", err)
			return "", nil
		}
	}
	t.logger.Info("synced", "path", path, "hash", answer.Hash, "session", file.session, "rewritten", answer.Content != nil,
		"stale", answer.Stale, "faults", answer.Faults)
	return answer.Hash, nil
}

// onDisk is a file of the tree as an upload read it: its bytes, their hash,
// its mode and the session the bytes are a save of.
type onDisk struct {
	content []byte
	hash    string
	mode    fs.FileMode
	session string
}

// read is the file of path as it is on disk, false when there is none to
// send: gone, not a regular file, or unreadable.
func (t *tree) read(path string) (onDisk, bool) {
	t.leaving.RLock()
	defer t.leaving.RUnlock()
	name := t.name(path)
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		// Gone: no delete goes up (design 1 §5.5).
		t.gone(path)
		return onDisk{}, false
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return onDisk{}, false
	}
	if !info.Mode().IsRegular() {
		return onDisk{}, false
	}
	content, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		t.gone(path)
		return onDisk{}, false
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return onDisk{}, false
	}
	hash := protocol.Hash(content)
	return onDisk{content: content, hash: hash, mode: info.Mode().Perm(), session: t.writer(path, hash)}, true
}

// gone forgets what the tree knows of the file of path but its shadow: its
// notes and what a release left unsent there.
func (t *tree) gone(path string) {
	t.notes.clear(path)
	t.unsent.forget(path)
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
