package watch

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fsnotify/fsnotify"
)

// reported is what a watch reported: each path, and the file's bytes as
// they were when it was reported.
type reported struct {
	mu    sync.Mutex
	root  string
	paths []string
	seen  map[string][]string
}

func (r *reported) changed(path string) {
	content, _ := os.ReadFile(filepath.Join(r.root, filepath.FromSlash(path)))
	r.mu.Lock()
	defer r.mu.Unlock()
	r.paths = append(r.paths, path)
	r.seen[path] = append(r.seen[path], string(content))
}

func (r *reported) of(path string) []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Clone(r.seen[path])
}

func (r *reported) all() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return slices.Clone(r.paths)
}

// start watches a temp tree with Debounce, laid out by setup first, until
// the test ends.
func start(t *testing.T, setup func(root string)) (string, *reported) {
	t.Helper()
	root := t.TempDir()
	setup(root)
	got := &reported{root: root, seen: map[string][]string{}}
	w, err := New(root, Debounce, got.changed, func() {}, slog.New(slog.NewTextHandler(t.Output(), nil)))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error)
	go func() { done <- w.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		if err := <-done; err != nil {
			t.Error(err)
		}
	})
	return root, got
}

func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	for deadline := time.Now().Add(5 * time.Second); !cond(); time.Sleep(5 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
	}
}

// settle waits long enough for any report still to come.
func settle() {
	time.Sleep(4 * Debounce)
}

func write(t *testing.T, name, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(name), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(name, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestReportsAFileWrittenInTheTree(t *testing.T) {
	root, got := start(t, func(root string) {
		write(t, filepath.Join(root, "proj", "inbox", "1-a.md"), "before")
	})
	write(t, filepath.Join(root, "proj", "inbox", "1-a.md"), "after")
	eventually(t, "the report", func() bool { return len(got.of("proj/inbox/1-a.md")) > 0 })
	settle()
	if seen := got.of("proj/inbox/1-a.md"); !slices.Equal(seen, []string{"after"}) {
		t.Fatalf("reported %q", seen)
	}
}

func TestReportsAFileWrittenInChunksOnceWhole(t *testing.T) {
	root, got := start(t, func(root string) {
		write(t, filepath.Join(root, "proj", "a.md"), "")
	})
	file, err := os.OpenFile(filepath.Join(root, "proj", "a.md"), os.O_WRONLY|os.O_TRUNC, 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, chunk := range []string{"one ", "two ", "three ", "four"} {
		if _, err := file.WriteString(chunk); err != nil {
			t.Fatal(err)
		}
		time.Sleep(Debounce / 10)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	eventually(t, "the report", func() bool { return len(got.of("proj/a.md")) > 0 })
	settle()
	if seen := got.of("proj/a.md"); !slices.Equal(seen, []string{"one two three four"}) {
		t.Fatalf("reported %q", seen)
	}
}

func TestReportsFilesOfDirectoriesMadeLater(t *testing.T) {
	root, got := start(t, func(string) {})
	// Made at once: the file is in the directories before they are watched.
	write(t, filepath.Join(root, "draft-1", "inbox", "deep", "1-a.md"), "a")
	eventually(t, "the first report", func() bool { return len(got.of("draft-1/inbox/deep/1-a.md")) > 0 })
	// Made later: the directories are watched by now.
	write(t, filepath.Join(root, "draft-1", "inbox", "deep", "2-b.md"), "b")
	eventually(t, "the second report", func() bool { return len(got.of("draft-1/inbox/deep/2-b.md")) > 0 })
}

func TestReportsAFileRenamedIntoPlace(t *testing.T) {
	root, got := start(t, func(root string) {
		write(t, filepath.Join(root, "proj", "a.md"), "before")
	})
	write(t, filepath.Join(root, "proj", "a.md.tmp"), "after")
	if err := os.Rename(filepath.Join(root, "proj", "a.md.tmp"), filepath.Join(root, "proj", "a.md")); err != nil {
		t.Fatal(err)
	}
	eventually(t, "the report", func() bool { return slices.Contains(got.of("proj/a.md"), "after") })
}

func TestReportsNoFileOfTheTreeAtTheStartNorATempFile(t *testing.T) {
	root, got := start(t, func(root string) {
		write(t, filepath.Join(root, "proj", "a.md"), "a")
	})
	write(t, filepath.Join(root, "proj", ".pilot-sync-123"), "temp")
	settle()
	if paths := got.all(); len(paths) != 0 {
		t.Fatalf("reported %q", paths)
	}
}

func TestReportsAFileRemoved(t *testing.T) {
	root, got := start(t, func(root string) {
		write(t, filepath.Join(root, "proj", "a.md"), "a")
	})
	if err := os.Remove(filepath.Join(root, "proj", "a.md")); err != nil {
		t.Fatal(err)
	}
	eventually(t, "the report", func() bool { return slices.Contains(got.all(), "proj/a.md") })
}

func TestWatchesTheTreeAgainAndSaysSoOnAnOverflow(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "proj")
	write(t, filepath.Join(dir, "a.md"), "a")
	got := &reported{root: root, seen: map[string][]string{}}
	var overflows atomic.Int32
	w, err := New(root, Debounce, got.changed, func() { overflows.Add(1) }, slog.New(slog.NewTextHandler(t.Output(), nil)))
	if err != nil {
		t.Fatal(err)
	}
	// A directory whose watch the lost events would have set.
	if err := w.notify.Remove(dir); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error)
	go func() { done <- w.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		if err := <-done; err != nil {
			t.Error(err)
		}
	})

	w.notify.Errors <- fsnotify.ErrEventOverflow
	eventually(t, "the overflow told", func() bool { return overflows.Load() == 1 })
	write(t, filepath.Join(dir, "a.md"), "after")
	eventually(t, "the report", func() bool { return slices.Contains(got.of("proj/a.md"), "after") })
}
