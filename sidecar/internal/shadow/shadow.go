// Package shadow is the sidecar's record of each path of the tree as it last
// synced it: the bytes the server holds for the path, kept in a directory of
// their own under the data directory so a restart keeps them, and their
// hash.
//
// The hash is the bytes' own: a sync answer's X-Pilot-Hash is the hash of the
// bytes the file holds once answered (design 1 §5.2), which the protocol
// client checks.
package shadow

import (
	"errors"
	"fmt"
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"sync"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// Store is the shadow, safe for concurrent use. Paths are the tree's: from
// its root, with forward slashes.
type Store struct {
	dir    string
	mu     sync.Mutex
	hashes map[string]string
}

// Open loads the shadow kept in dir, making dir if it has none.
func Open(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("open the shadow: %w", err)
	}
	store := &Store{dir: dir, hashes: map[string]string{}}
	err := filepath.WalkDir(dir, func(name string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		if files.IsTemp(entry.Name()) {
			// A write cut short before its rename.
			return os.Remove(name)
		}
		content, err := os.ReadFile(name)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, name)
		if err != nil {
			return err
		}
		store.hashes[filepath.ToSlash(rel)] = protocol.Hash(content)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("open the shadow: %w", err)
	}
	return store, nil
}

// Hash is the hash path last synced with, and whether it has synced.
func (s *Store) Hash(path string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	hash, ok := s.hashes[path]
	return hash, ok
}

// Put records content as what the server holds for path.
func (s *Store) Put(path string, content []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	name := filepath.Join(s.dir, filepath.FromSlash(path))
	err := os.MkdirAll(filepath.Dir(name), 0o755)
	if err == nil {
		err = files.Write(name, content, 0o644)
	}
	if err != nil {
		return fmt.Errorf("record %s in the shadow: %w", path, err)
	}
	s.hashes[path] = protocol.Hash(content)
	return nil
}

// Read is the bytes path last synced with.
func (s *Store) Read(path string) ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	content, err := os.ReadFile(filepath.Join(s.dir, filepath.FromSlash(path)))
	if err != nil {
		return nil, fmt.Errorf("read %s in the shadow: %w", path, err)
	}
	return content, nil
}

// Hashes is every path the shadow holds, with the hash it last synced.
func (s *Store) Hashes() map[string]string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return maps.Clone(s.hashes)
}

// Delete forgets path, and every directory of the shadow it leaves empty.
func (s *Store) Delete(path string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	name := filepath.Join(s.dir, filepath.FromSlash(path))
	if err := os.Remove(name); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("forget %s in the shadow: %w", path, err)
	}
	delete(s.hashes, path)
	return files.RemoveEmptyDirs(s.dir, filepath.Dir(name))
}
