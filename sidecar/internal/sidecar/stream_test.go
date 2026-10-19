package sidecar

import (
	"context"
	"net/http"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

func TestReconcilesOnConnectSendingUpThenWritingDownAndDeleting(t *testing.T) {
	s := newServer(t)
	tree, data := t.TempDir(), t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.record("proj/a.md", "one")
	s.record("proj/timeline.json", "[]")
	s.record("old/inbox/b.md", "bee")
	first := start(t, s, tree, data)
	for path, content := range map[string]string{"proj/a.md": "one", "proj/timeline.json": "[]", "old/inbox/b.md": "bee"} {
		if !holds(at(path), content) || first.synced(path) != hashOf(content) {
			t.Errorf("%s: not written down on the first connect", path)
		}
	}
	first.stop()

	// While the sidecar is away the record moves on, and the agent writes.
	s.record("proj/a.md", "two")
	s.record("old/inbox/b.md", "")
	s.record("draft-2/inbox/1-c.md", "new")
	write(t, at("proj/inbox/2-d.md"), "the agent's")
	running := start(t, s, tree, data)

	puts := s.taken()
	if len(puts) != 1 || puts[0].path != "proj/inbox/2-d.md" || puts[0].base != "none" {
		t.Fatalf("took %v, not the agent's file with no base", puts)
	}
	posted := s.manifests()[1]
	if posted.Tree["proj/inbox/2-d.md"] != hashOf("the agent's") || posted.Shadow["proj/inbox/2-d.md"] != hashOf("the agent's") {
		t.Errorf("posted %v: the file sent up before the manifest", posted)
	}
	if posted.Shadow["old/inbox/b.md"] != hashOf("bee") || posted.Tree["proj/a.md"] != hashOf("one") {
		t.Errorf("posted %v: not the tree and the shadow as they stood", posted)
	}
	eventually(t, "the reconcile written down", func() bool {
		return holds(at("proj/a.md"), "two") && holds(at("draft-2/inbox/1-c.md"), "new")
	})
	eventually(t, "the reconcile's delete", func() bool { return !exists(at("old")) })
	for path, want := range map[string]string{
		"proj/a.md": hashOf("two"), "draft-2/inbox/1-c.md": hashOf("new"), "old/inbox/b.md": "",
	} {
		if got := running.synced(path); got != want {
			t.Errorf("%s: synced %q, want %q", path, got, want)
		}
	}
	if !holds(at("proj/timeline.json"), "[]") || !holds(at("proj/inbox/2-d.md"), "the agent's") {
		t.Error("a file in sync was touched")
	}
}

func TestDeletesOnlyWhatTheShadowHolds(t *testing.T) {
	s := newServer(t)
	tree, data := t.TempDir(), t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.record("gone/b.md", "bee")
	s.record("gone/c.md", "sea")
	start(t, s, tree, data).stop()

	// The project is archived while the agent, away, edits one of its files
	// and writes two of its own.
	s.record("gone/b.md", "")
	s.record("gone/c.md", "")
	write(t, at("gone/c.md"), "sea, edited")
	write(t, at("gone/notes.md"), "mine")
	write(t, at("proj/notes.md"), "mine")
	stray := map[string]bool{"gone/c.md": true, "gone/notes.md": true, "proj/notes.md": true}
	s.answering(func(taken put) answer {
		if stray[taken.path] {
			return answer{status: http.StatusNotFound}
		}
		return answer{}
	})
	s.amending(func(_ posted, answered protocol.Reconciled) protocol.Reconciled {
		answered.Delete = append(answered.Delete, "proj/notes.md")
		return answered
	})
	running := start(t, s, tree, data)

	eventually(t, "the synced file deleted", func() bool { return !exists(at("gone/b.md")) })
	for path, content := range map[string]string{"gone/c.md": "sea, edited", "gone/notes.md": "mine", "proj/notes.md": "mine"} {
		if !holds(at(path), content) {
			t.Errorf("%s: deleted, its bytes never synced", path)
		}
		if note := running.noted(path); note != strayNote {
			t.Errorf("%s: noted %q", path, note)
		}
	}
	for _, path := range []string{"gone/b.md", "gone/c.md"} {
		if hash := running.synced(path); hash != "" {
			t.Errorf("%s: still in the shadow", path)
		}
	}
}

func TestNeverWritesDownOverBytesThatNeverSynced(t *testing.T) {
	s := newServer(t)
	tree, data := t.TempDir(), t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	s.record("proj/a.md", "one")
	start(t, s, tree, data).stop()

	write(t, file, "the agent's")
	s.record("proj/a.md", "two")
	s.answering(func(put) answer { return answer{status: http.StatusServiceUnavailable} })
	running := start(t, s, tree, data)
	running.stream.send(t, change("proj/a.md", "two"))
	settle()
	if got := read(t, file); got != "the agent's" {
		t.Fatalf("the file holds %q", got)
	}

	// The next reconcile sends up what the last could not.
	s.answering(func(put) answer { return answer{} })
	running.stream.send(t, manifest)
	eventually(t, "the PUT again", func() bool { return len(s.taken()) == 2 })
	if again := s.taken()[1]; again.body != "the agent's" || again.base != hashOf("one") {
		t.Fatalf("took %q based on %s", again.body, again.base)
	}
}

func TestFetchesAMovedPathOnceItsChangesCoalesce(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.record("proj/a.md", "one")
	running := start(t, s, tree, t.TempDir())

	// The record has moved past both of a.md's changes: a fetch per change
	// would GET it twice, the second change's hash not the first fetch's.
	s.record("proj/a.md", "four")
	s.record("proj/timeline.json", "[3]")
	for _, frame := range []string{
		change("proj/a.md", "two"), heartbeat, change("proj/timeline.json", "[3]"), change("proj/a.md", "three"),
	} {
		running.stream.send(t, frame)
	}
	eventually(t, "the moved paths written", func() bool {
		return holds(at("proj/a.md"), "four") && holds(at("proj/timeline.json"), "[3]")
	})
	settle()
	fetched := s.fetched()
	if got := countOf(fetched, "proj/a.md"); got != 2 {
		t.Errorf("fetched proj/a.md %d times: %v", got, fetched)
	}
	if running.synced("proj/a.md") != hashOf("four") {
		t.Error("the shadow not updated")
	}
}

func TestIgnoresTheEchoOfItsOwnWrite(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	release := make(chan struct{})
	s.answering(func(taken put) answer {
		if taken.body == "saved" {
			<-release
			return answer{content: "merged"}
		}
		return answer{}
	})
	running := start(t, s, tree, t.TempDir())

	write(t, file, "saved")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	// The save's commit is on the stream before its answer is back.
	running.stream.send(t, change("proj/a.md", "merged"))
	time.Sleep(2 * coalesce)
	close(release)
	eventually(t, "the answer written", func() bool { return holds(file, "merged") })
	running.stream.send(t, change("proj/a.md", "merged"))
	settle()
	if fetched := s.fetched(); len(fetched) != 0 {
		t.Fatalf("fetched %v, its own write", fetched)
	}
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs", len(puts))
	}
}

func TestReconcilesOnAManifestEvent(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.record("draft-3/inbox/1-a.md", "draft")
	running := start(t, s, tree, t.TempDir())

	// Create project: the draft's folder moves to the project's slug.
	s.record("draft-3/inbox/1-a.md", "")
	s.record("thetvdb/inbox/1-a.md", "draft")
	running.stream.send(t, manifest)
	eventually(t, "the folder moved", func() bool {
		return holds(at("thetvdb/inbox/1-a.md"), "draft") && !exists(at("draft-3"))
	})
	if posts := len(s.manifests()); posts != 2 {
		t.Fatalf("posted %d manifests", posts)
	}
}

func TestRescansTheTreeOnAnOverflow(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.record("proj/a.md", "one")
	running := start(t, s, tree, t.TempDir())

	s.record("proj/b.md", "bee")
	running.sidecar.overflowed()
	eventually(t, "the rescan's write", func() bool { return holds(at("proj/b.md"), "bee") })
	posted := s.manifests()
	if len(posted) != 2 || posted[1].Tree["proj/a.md"] != hashOf("one") {
		t.Fatalf("posted %v, not the tree walked", posted)
	}
}

func TestReconnectsWithBackoffAndReconciles(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	s.opens(func(attempt int) (int, string) {
		switch {
		case attempt == 4:
			// A server shutting down: 200, and the stream ends with no hello.
			return http.StatusOK, ""
		case attempt <= 7:
			return http.StatusServiceUnavailable, `{"error": "unavailable"}`
		}
		return 0, ""
	})
	sidecar, _ := newSidecar(t, s, tree, t.TempDir())
	next := sleeps(t, sidecar)
	run(t, sidecar)

	for i, want := range []time.Duration{
		time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second, 16 * time.Second, 30 * time.Second, 30 * time.Second,
	} {
		if got := next(); got != want {
			t.Errorf("wait %d: %v, want %v", i, got, want)
		}
	}
	opened := s.accept(t)
	eventually(t, "the reconcile on connect", func() bool { return len(s.manifests()) == 1 })
	settle()
	s.record("proj/a.md", "while away")
	opened.drop()
	if got := next(); got != time.Second {
		t.Errorf("waited %v after a connection that reconciled", got)
	}
	s.accept(t)
	eventually(t, "the reconcile on reconnect", func() bool {
		return len(s.manifests()) == 2 && holds(filepath.Join(tree, "proj", "a.md"), "while away")
	})
}

func TestWaitsAMinuteOnA426(t *testing.T) {
	s := newServer(t)
	s.opens(func(attempt int) (int, string) {
		switch attempt {
		case 1:
			return http.StatusUpgradeRequired, `{"min": 2, "max": 3}`
		case 2:
			return http.StatusServiceUnavailable, `{"error": "unavailable"}`
		}
		return 0, ""
	})
	sidecar, logged := newSidecar(t, s, t.TempDir(), t.TempDir())
	next := sleeps(t, sidecar)
	run(t, sidecar)

	if got := next(); got != time.Minute {
		t.Errorf("waited %v after a 426", got)
	}
	if !strings.Contains(logged.String(), "min=2 max=3 version=1") {
		t.Errorf("logged %q, not the two numbers", logged.String())
	}
	if got := next(); got != time.Second {
		t.Errorf("waited %v after the first drop", got)
	}
	s.accept(t)
	eventually(t, "the reconcile on connect", func() bool { return len(s.manifests()) == 1 })
}

// sleeps makes sidecar's waits the test's: each is answered as the test
// takes it, at once.
func sleeps(t *testing.T, sidecar *Sidecar) func() time.Duration {
	waits := make(chan time.Duration)
	sidecar.sleep = func(ctx context.Context, d time.Duration) bool {
		select {
		case waits <- d:
			return true
		case <-ctx.Done():
			return false
		}
	}
	return func() time.Duration {
		t.Helper()
		select {
		case d := <-waits:
			return d
		case <-time.After(5 * time.Second):
			t.Fatal("timed out waiting for a wait")
			return 0
		}
	}
}

func countOf(paths []string, path string) int {
	return len(slices.DeleteFunc(slices.Clone(paths), func(p string) bool { return p != path }))
}
