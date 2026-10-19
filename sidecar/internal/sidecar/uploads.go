package sidecar

import (
	"bytes"
	"context"
	"errors"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sync"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
	"github.com/pvginkel/PilotApp/sidecar/internal/shadow"
)

// parallelPuts bounds the PUTs out at once, across paths; a path has one at
// a time (design 1 §5.3).
const parallelPuts = 4

// uploads sends the tree's files up as they change: a file whose hash is not
// its shadow's goes up with the shadow's hash as its base, and the answer is
// recorded in the shadow and, when it carries bytes, written in place. A
// file the sidecar wrote itself hashes as its shadow, so it never goes up.
type uploads struct {
	root   string
	client *protocol.Client
	shadow *shadow.Store
	logger *slog.Logger
	ctx    context.Context
	cancel context.CancelFunc
	slots  chan struct{}
	wg     sync.WaitGroup

	mu sync.Mutex
	// out holds each path with a PUT out, and whether it changed again
	// since the PUT read it.
	out    map[string]bool
	closed bool
}

func newUploads(root string, client *protocol.Client, store *shadow.Store, logger *slog.Logger) *uploads {
	ctx, cancel := context.WithCancel(context.Background())
	return &uploads{
		root:   root,
		client: client,
		shadow: store,
		logger: logger,
		ctx:    ctx,
		cancel: cancel,
		slots:  make(chan struct{}, parallelPuts),
		out:    map[string]bool{},
	}
}

// changed is told the file at path, from the tree's root, changed.
func (u *uploads) changed(path string) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.closed {
		return
	}
	if _, out := u.out[path]; out {
		u.out[path] = true
		return
	}
	u.out[path] = false
	u.wg.Add(1)
	go u.run(path)
}

// run uploads path until it no longer changed while its PUT was out.
func (u *uploads) run(path string) {
	defer u.wg.Done()
	for {
		u.slots <- struct{}{}
		u.upload(path)
		<-u.slots
		u.mu.Lock()
		again := u.out[path] && !u.closed
		if again {
			u.out[path] = false
		} else {
			delete(u.out, path)
		}
		u.mu.Unlock()
		if !again {
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

func (u *uploads) upload(path string) {
	name := filepath.Join(u.root, filepath.FromSlash(path))
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		// Gone: no delete goes up (design 1 §5.5).
		return
	}
	if err != nil {
		u.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	if !info.Mode().IsRegular() {
		return
	}
	sent, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		return
	}
	if err != nil {
		u.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	base, _ := u.shadow.Hash(path)
	if protocol.Hash(sent) == base {
		return
	}
	answer, err := u.client.Put(u.ctx, path, sent, base)
	switch {
	case err == nil:
	case u.ctx.Err() != nil:
		return
	case errors.Is(err, protocol.ErrNotFound):
		u.logger.Info("not a path of the record: left as it is", "path", path)
		return
	default:
		u.logger.Error("cannot sync a file of the tree", "path", path, "error", err)
		return
	}
	held := sent
	if answer.Content != nil {
		held = answer.Content
	}
	if err := u.shadow.Put(path, held); err != nil {
		u.logger.Error("cannot record a sync", "path", path, "error", err)
		return
	}
	if answer.Content != nil {
		if err := writeAnswer(name, sent, answer.Content, info.Mode().Perm()); err != nil {
			u.logger.Error("cannot write a sync's answer", "path", path, "error", err)
			return
		}
	}
	u.logger.Info("synced", "path", path, "hash", answer.Hash, "rewritten", answer.Content != nil,
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
