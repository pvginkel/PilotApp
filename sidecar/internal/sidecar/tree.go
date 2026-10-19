package sidecar

import (
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

// parallelCalls bounds the calls out at once that send a file up or fetch
// one; a path has one at a time (design 1 §5.3).
const parallelCalls = 4

// strayNote is the local note on a file the record never bore (design 1
// §5.5, D10).
const strayNote = "not a document of the record — files are born through `add_item`"

// tree is the store's tree as the sidecar keeps it: the files under its
// root, the shadow of each as it last synced, the local notes on them, and
// the server they sync with.
type tree struct {
	root   string
	client *protocol.Client
	shadow *shadow.Store
	notes  *notes
	logger *slog.Logger
	slots  chan struct{}
	locks  *pathLocks
}

func newTree(root string, client *protocol.Client, store *shadow.Store, logger *slog.Logger) *tree {
	return &tree{
		root:   root,
		client: client,
		shadow: store,
		notes:  &notes{byPath: map[string]string{}},
		logger: logger,
		slots:  make(chan struct{}, parallelCalls),
		locks:  &pathLocks{held: map[string]*pathLock{}},
	}
}

// name is the file of path, a path from the tree's root.
func (t *tree) name(path string) string {
	return filepath.Join(t.root, filepath.FromSlash(path))
}

// hold takes a call's slot and path's lock, false when ctx is done first;
// release gives both back. A call with the lock never waits for a slot.
func (t *tree) hold(ctx context.Context, path string) (release func(), ok bool) {
	select {
	case t.slots <- struct{}{}:
	case <-ctx.Done():
		return nil, false
	}
	unlock := t.locks.lock(path)
	return func() {
		unlock()
		<-t.slots
	}, true
}

// walk hashes every file of the tree, by path.
func (t *tree) walk() (map[string]string, error) {
	hashes := map[string]string{}
	err := filepath.WalkDir(t.root, func(name string, entry fs.DirEntry, err error) error {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		if !entry.Type().IsRegular() || files.IsTemp(entry.Name()) {
			return nil
		}
		content, err := os.ReadFile(name)
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(t.root, name)
		if err != nil {
			return err
		}
		hashes[filepath.ToSlash(rel)] = protocol.Hash(content)
		return nil
	})
	return hashes, err
}

// unsynced says whether the file of path holds bytes that never synced, and
// the mode to write it with: a file that is not there holds none, and is
// written 0644.
func (t *tree) unsynced(path string) (bool, fs.FileMode, error) {
	name := t.name(path)
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		return false, 0o644, nil
	}
	if err != nil {
		return false, 0, err
	}
	if !info.Mode().IsRegular() {
		return false, 0, errors.New("not a file")
	}
	content, err := os.ReadFile(name)
	if errors.Is(err, fs.ErrNotExist) {
		return false, 0o644, nil
	}
	if err != nil {
		return false, 0, err
	}
	synced, _ := t.shadow.Hash(path)
	return protocol.Hash(content) != synced, info.Mode().Perm(), nil
}

// download fetches the bytes path must hold and writes them, the shadow
// first, so the watch's echo of the write hashes as synced. A file holding
// bytes that never synced keeps them: they go up, and the answer carries the
// record's. The caller holds path.
func (t *tree) download(ctx context.Context, path string) {
	content, err := t.client.Get(ctx, path)
	switch {
	case err == nil:
	case ctx.Err() != nil:
		return
	case errors.Is(err, protocol.ErrNotFound):
		t.logger.Info("no longer a path of the record: left for the reconcile", "path", path)
		return
	default:
		t.logger.Error("cannot fetch a file of the record", "path", path, "error", err)
		return
	}
	unsynced, mode, err := t.unsynced(path)
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	if unsynced {
		t.logger.Info("changed on disk since it synced: left for its upload", "path", path)
		return
	}
	name := t.name(path)
	if err := os.MkdirAll(filepath.Dir(name), 0o755); err != nil {
		t.logger.Error("cannot write a file of the record", "path", path, "error", err)
		return
	}
	if err := t.shadow.Put(path, content); err != nil {
		t.logger.Error("cannot record a sync", "path", path, "error", err)
		return
	}
	if err := files.Write(name, content, mode); err != nil {
		t.logger.Error("cannot write a file of the record", "path", path, "error", err)
		return
	}
	t.notes.clear(path)
	t.logger.Info("written down", "path", path, "hash", protocol.Hash(content))
}

// remove deletes the file of path, which the record no longer lists, and
// every directory that leaves empty; the shadow forgets path. Only what the
// shadow holds is deleted: a file holding bytes that never synced stays, a
// file the record never bore. The caller holds path.
func (t *tree) remove(path string) {
	if _, ok := t.shadow.Hash(path); !ok {
		t.logger.Info("never synced: left as it is", "path", path)
		return
	}
	unsynced, _, err := t.unsynced(path)
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	if err := t.shadow.Delete(path); err != nil {
		t.logger.Error("cannot record a sync", "path", path, "error", err)
		return
	}
	if unsynced {
		t.logger.Info("changed on disk since it synced: left as it is", "path", path)
		return
	}
	name := t.name(path)
	if err := os.Remove(name); err != nil && !errors.Is(err, fs.ErrNotExist) {
		t.logger.Error("cannot delete a file of the tree", "path", path, "error", err)
		return
	}
	t.notes.clear(path)
	if err := files.RemoveEmptyDirs(t.root, filepath.Dir(name)); err != nil {
		t.logger.Error("cannot delete a directory of the tree", "path", path, "error", err)
	}
	t.logger.Info("deleted", "path", path)
}

// notes are the local notes the hook prints, by path: what the sidecar
// knows of a file that the server holds no Save Error for.
type notes struct {
	mu     sync.Mutex
	byPath map[string]string
}

func (n *notes) note(path, text string) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.byPath[path] = text
}

func (n *notes) clear(path string) {
	n.mu.Lock()
	defer n.mu.Unlock()
	delete(n.byPath, path)
}

// pathLocks holds a lock per path, so the file of a path and its shadow are
// read, sent, fetched and written by one goroutine at a time.
type pathLocks struct {
	mu   sync.Mutex
	held map[string]*pathLock
}

type pathLock struct {
	mu    sync.Mutex
	users int
}

func (l *pathLocks) lock(path string) (unlock func()) {
	l.mu.Lock()
	entry := l.held[path]
	if entry == nil {
		entry = &pathLock{}
		l.held[path] = entry
	}
	entry.users++
	l.mu.Unlock()
	entry.mu.Lock()
	return func() {
		entry.mu.Unlock()
		l.mu.Lock()
		defer l.mu.Unlock()
		entry.users--
		if entry.users == 0 {
			delete(l.held, path)
		}
	}
}
