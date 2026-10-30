package sidecar

import (
	"os"
	"path/filepath"
	"slices"
	"sync"
	"testing"
	"time"
)

// readsOf has the tree's walks keep the hash of a file changed window before
// them, and count the files they read: what they read since it was last
// asked, by path from the tree's root, in the order read.
func (s started) readsOf(window time.Duration) func() []string {
	var mu sync.Mutex
	var read []string
	hashes := s.sidecar.tree.hashes
	hashes.mu.Lock()
	defer hashes.mu.Unlock()
	hashes.window = window
	hashes.read = func(name string) ([]byte, error) {
		path, _ := s.sidecar.tree.path(name)
		mu.Lock()
		read = append(read, path)
		mu.Unlock()
		return os.ReadFile(name)
	}
	return func() []string {
		mu.Lock()
		defer mu.Unlock()
		taken := read
		read = nil
		return taken
	}
}

func TestAReleaseReadsOnlyTheFilesWhoseStampsMoved(t *testing.T) {
	s := newServer(t)
	s.record("proj/a.md", "aaaa")
	s.record("proj/b.md", "bbbb")
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())
	eventually(t, "the folder written down", func() bool {
		return running.synced("proj/a.md") != "" && running.synced("proj/b.md") != ""
	})
	reads := running.readsOf(20 * time.Millisecond)
	// Past the window and the clock's tick: the files' stamps are kept.
	time.Sleep(50 * time.Millisecond)

	running.lock(t, "proj", chat, os.Getpid())
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	if got := reads(); !slices.Equal(got, []string{"proj/a.md", "proj/b.md"}) {
		t.Fatalf("the first release read %v", got)
	}

	running.lock(t, "proj", chat, os.Getpid())
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	if got := reads(); len(got) != 0 {
		t.Fatalf("the release of an unchanged folder read %v", got)
	}

	// A rewrite of the same size, inside the watch's debounce: the release
	// reads it again, and sends it up itself.
	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "a.md"), "AAAA")
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	if got := reads(); !slices.Equal(got, []string{"proj/a.md"}) {
		t.Fatalf("the release after a rewrite read %v", got)
	}
	puts := s.taken()
	if len(puts) != 1 || puts[0].path != "proj/a.md" || puts[0].body != "AAAA" || sessionOf(puts[0]) != chat {
		t.Fatalf("took %+v by the release's answer", puts)
	}
}

func TestAReleaseReadsAFileChangedWithinTheWindowEveryTime(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	running := start(t, s, tree, t.TempDir())
	reads := running.readsOf(racyWindow)
	write(t, file, "aaaa")
	eventually(t, "the save", func() bool { return running.synced("proj/a.md") == hashOf("aaaa") })

	// A rewrite of the same size within the clock's tick of the one read
	// can leave the file's stamp as it was: a file changed this recently is
	// read at every release, unchanged or not.
	for range 2 {
		running.lock(t, "proj", chat, os.Getpid())
		if got := running.release(t, "proj", chat); got != "" {
			t.Fatalf("printed %q", got)
		}
		if got := reads(); !slices.Equal(got, []string{"proj/a.md"}) {
			t.Fatalf("the release of an unchanged folder read %v", got)
		}
	}

	running.lock(t, "proj", chat, os.Getpid())
	write(t, file, "AAAA")
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	if got := reads(); !slices.Equal(got, []string{"proj/a.md"}) {
		t.Fatalf("the release after a rewrite read %v", got)
	}
	puts := s.taken()
	if len(puts) != 2 || puts[1].body != "AAAA" || sessionOf(puts[1]) != chat {
		t.Fatalf("took %+v", puts)
	}
}
