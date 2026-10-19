package sidecar

import (
	"context"
	"errors"
	"io/fs"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"sync"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
	"github.com/pvginkel/PilotApp/sidecar/internal/shadow"
)

// parallelCalls bounds the calls out at once that send a file up or fetch
// one; a path has one at a time (design 1 §5.3).
const parallelCalls = 4

// The local notes the hook prints.
const (
	// strayNote is on a file the record never bore (design 1 §5.5, D10).
	strayNote = "not a document of the record — files are born through `add_item`"
	// revertNote is on a read-only view a write got through to (design 1 §8).
	revertNote = "a read-only view; re-projected"
)

// viewMode is the mode of a read-only view (design 1 §8).
const viewMode fs.FileMode = 0o444

// tree is the store's tree as the sidecar keeps it: the files under its
// root, the shadow of each as it last synced, the local notes on them, the
// read-only views among them, and the server they sync with.
type tree struct {
	root   string
	client *protocol.Client
	shadow *shadow.Store
	notes  *notes
	logger *slog.Logger
	slots  chan struct{}
	locks  *pathLocks

	mu       sync.Mutex
	readonly map[string]bool
}

func newTree(root string, client *protocol.Client, store *shadow.Store, logger *slog.Logger) *tree {
	return &tree{
		root:     root,
		client:   client,
		shadow:   store,
		notes:    &notes{byPath: map[string]note{}},
		logger:   logger,
		slots:    make(chan struct{}, parallelCalls),
		locks:    &pathLocks{held: map[string]*pathLock{}},
		readonly: map[string]bool{},
	}
}

// listed takes the read-only views of manifest, every path the store syncs.
// Until the first manifest is listed, no path is a view.
func (t *tree) listed(manifest []protocol.Entry) {
	readonly := map[string]bool{}
	for _, entry := range manifest {
		if entry.Readonly {
			readonly[entry.Path] = true
		}
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	t.readonly = readonly
}

// view says whether path is a read-only view, as the last manifest listed
// it.
func (t *tree) view(path string) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.readonly[path]
}

// name is the file of path, a path from the tree's root.
func (t *tree) name(path string) string {
	return filepath.Join(t.root, filepath.FromSlash(path))
}

// path is the path from the tree's root of the file at name, an absolute
// path; false when name is not a file of the tree.
func (t *tree) path(name string) (string, bool) {
	if !filepath.IsAbs(name) {
		return "", false
	}
	rel, err := filepath.Rel(t.root, name)
	if err != nil {
		return "", false
	}
	path := filepath.ToSlash(rel)
	return path, protocol.ValidPath(path)
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

// walk hashes every file of the tree, by path. A file it cannot read is
// left out, as its upload leaves it: it costs its own path only.
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
		rel, err := filepath.Rel(t.root, name)
		if err != nil {
			return err
		}
		path := filepath.ToSlash(rel)
		content, err := os.ReadFile(name)
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err != nil {
			t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
			return nil
		}
		hashes[path] = protocol.Hash(content)
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
// first, so the watch's echo of the write hashes as synced; a read-only view
// is written with the view's mode. A file holding bytes that never synced
// keeps them: they go up, and the answer carries the record's. A read-only
// view the shadow holds sends nothing up (upload), so a write to it is
// written over and noted as its revert is. The caller holds path.
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
	view := t.view(path)
	_, synced := t.shadow.Hash(path)
	reverted := unsynced && view && synced
	if unsynced && !reverted {
		t.logger.Info("changed on disk since it synced: left for its upload", "path", path)
		return
	}
	if view {
		mode = viewMode
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
	if reverted {
		t.notes.once(path, revertNote)
		t.logger.Info("a read-only view was written: re-projected", "path", path)
	}
	t.logger.Info("written down", "path", path, "hash", protocol.Hash(content))
}

// revert writes the bytes path last synced with over the file of path, a
// read-only view a write got through to, with the view's mode, and notes it
// for the next check; nothing goes up (design 1 §8). It answers the hash the
// file then holds, "" when it could not. The caller holds path.
func (t *tree) revert(path string) string {
	content, err := t.shadow.Read(path)
	if err == nil {
		err = files.Write(t.name(path), content, viewMode)
	}
	if err != nil {
		t.logger.Error("cannot re-project a read-only view", "path", path, "error", err)
		return ""
	}
	t.notes.once(path, revertNote)
	t.logger.Info("a read-only view was written: re-projected", "path", path)
	return protocol.Hash(content)
}

// protect gives the file of path, a read-only view, the view's mode when it
// has another. The caller holds path.
func (t *tree) protect(path string) {
	name := t.name(path)
	info, err := os.Lstat(name)
	if errors.Is(err, fs.ErrNotExist) {
		return
	}
	if err != nil {
		t.logger.Error("cannot read a file of the tree", "path", path, "error", err)
		return
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() == viewMode {
		return
	}
	if err := os.Chmod(name, viewMode); err != nil {
		t.logger.Error("cannot make a read-only view read-only", "path", path, "error", err)
		return
	}
	t.logger.Info("made read-only", "path", path)
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
	byPath map[string]note
}

// note is a local note: its text, and whether the check that prints it ends
// it.
type note struct {
	text string
	once bool
}

// keep notes text on path until it is cleared.
func (n *notes) keep(path, text string) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.byPath[path] = note{text: text}
}

// once notes text on path until a check prints it.
func (n *notes) once(path, text string) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.byPath[path] = note{text: text, once: true}
}

// clear ends the note kept on path; a note made once stays until printed.
func (n *notes) clear(path string) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if !n.byPath[path].once {
		delete(n.byPath, path)
	}
}

// print is every note as the hook prints it, `<path>: <note>`, in path
// order; a note made once is printed once.
func (n *notes) print() []string {
	n.mu.Lock()
	defer n.mu.Unlock()
	lines := make([]string, 0, len(n.byPath))
	for _, path := range slices.Sorted(maps.Keys(n.byPath)) {
		lines = append(lines, path+": "+n.byPath[path].text)
		if n.byPath[path].once {
			delete(n.byPath, path)
		}
	}
	return lines
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
