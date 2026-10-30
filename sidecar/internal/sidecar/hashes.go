package sidecar

import (
	"io/fs"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// racyWindow is how long after a file's last change its hash is read again
// at every walk, whatever its stat says: a write within the clock's tick of
// the one hashed can leave the file's stat as it was.
const racyWindow = 2 * time.Second

// stamp is what a file's stat says of its bytes. A file that still bears
// the stamp it was hashed under holds the bytes hashed.
type stamp struct {
	size  int64
	mtime int64
	ctime int64
	inode uint64
}

// stampedHash is a file's hash and the stamp it bore when read.
type stampedHash struct {
	stamp stamp
	hash  string
}

// fileHashes are the walks' hashes of the tree's files, by path, so that a
// walk reads only the files whose stamps moved since the last one: a
// release's flush is a walk of its folder after every writing tool call.
type fileHashes struct {
	mu     sync.Mutex
	window time.Duration
	read   func(name string) ([]byte, error)
	byPath map[string]stampedHash
}

func newFileHashes() *fileHashes {
	return &fileHashes{window: racyWindow, read: os.ReadFile, byPath: map[string]stampedHash{}}
}

// hash is the hash of the bytes of name, the file of path that entry walked
// to. It reads the file unless the file bears the stamp of its last hash;
// a hash is kept only for a file last changed more than the window before
// since, the walk's start. A file that is gone answers fs.ErrNotExist.
func (h *fileHashes) hash(path, name string, entry fs.DirEntry, since time.Time) (string, error) {
	info, err := entry.Info()
	if err != nil {
		return "", err
	}
	stat, stamped := info.Sys().(*syscall.Stat_t)
	var current stamp
	if stamped {
		current = stamp{size: info.Size(), mtime: stat.Mtim.Nano(), ctime: stat.Ctim.Nano(), inode: stat.Ino}
	}
	h.mu.Lock()
	kept, ok := h.byPath[path]
	window, read := h.window, h.read
	h.mu.Unlock()
	if stamped && ok && kept.stamp == current {
		return kept.hash, nil
	}
	content, err := read(name)
	if err != nil {
		return "", err
	}
	hash := protocol.Hash(content)
	h.mu.Lock()
	defer h.mu.Unlock()
	if stamped && current.ctime < since.Add(-window).UnixNano() {
		h.byPath[path] = stampedHash{stamp: current, hash: hash}
	} else {
		delete(h.byPath, path)
	}
	return hash, nil
}

// keep forgets the hash of every path under the directory of under, a path
// from the tree's root or "" for the root, that walked, a walk's hashes of
// it, does not hold: a file gone, or one the walk could not read.
func (h *fileHashes) keep(under string, walked map[string]string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for path := range h.byPath {
		if _, found := walked[path]; !found && (under == "" || strings.HasPrefix(path, under+"/")) {
			delete(h.byPath, path)
		}
	}
}
