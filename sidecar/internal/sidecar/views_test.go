package sidecar

import (
	"io/fs"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// writeOver replaces the file at name with content as `sed -i` does: a new
// file renamed over it, whatever its mode.
func writeOver(t *testing.T, name, content string) {
	t.Helper()
	tmp := filepath.Join(filepath.Dir(name), "sed-tmp")
	write(t, tmp, content)
	if err := os.Rename(tmp, name); err != nil {
		t.Fatal(err)
	}
}

func modeOf(t *testing.T, name string) fs.FileMode {
	t.Helper()
	info, err := os.Stat(name)
	if err != nil {
		t.Fatal(err)
	}
	return info.Mode().Perm()
}

func TestProjectsAReadOnlyViewMode0444(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	at := func(path string) string { return filepath.Join(tree, filepath.FromSlash(path)) }
	s.view("proj/timeline.json", "[]")
	s.view("reference.json", "{}")
	s.record("proj/inbox/1-a.md", "one")
	running := start(t, s, tree, t.TempDir())

	for path, want := range map[string]fs.FileMode{
		"proj/timeline.json": 0o444, "reference.json": 0o444, "proj/inbox/1-a.md": 0o644,
	} {
		if got := modeOf(t, at(path)); got != want {
			t.Errorf("%s: mode %v, want %v", path, got, want)
		}
	}

	// A record move rewrites the view read-only.
	s.view("proj/timeline.json", "[1]")
	running.stream.send(t, change("proj/timeline.json", "[1]"))
	eventually(t, "the view rewritten", func() bool { return holds(at("proj/timeline.json"), "[1]") })
	if got := modeOf(t, at("proj/timeline.json")); got != 0o444 {
		t.Errorf("rewritten with mode %v", got)
	}

	// A reconcile makes a view whose mode was changed read-only again.
	if err := os.Chmod(at("reference.json"), 0o644); err != nil {
		t.Fatal(err)
	}
	running.stream.send(t, manifest)
	eventually(t, "the view made read-only", func() bool { return modeOf(t, at("reference.json")) == 0o444 })
	if puts := s.taken(); len(puts) != 0 {
		t.Fatalf("took %v", puts)
	}
}

func TestWritesA200AnswerForAViewTheShadowDoesNotHoldMode0444(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	view := filepath.Join(tree, "reference.json")
	s.view("reference.json", "{}")
	// The reconcile lists the view and writes nothing down: the shadow does
	// not hold it.
	s.amending(func(_ posted, answered protocol.Reconciled) protocol.Reconciled {
		answered.WriteDown = []protocol.Entry{}
		return answered
	})
	s.answering(func(put) answer { return answer{content: "{}"} })
	running := start(t, s, tree, t.TempDir())

	write(t, view, `{"edited": true}`)
	eventually(t, "the projection written", func() bool { return holds(view, "{}") })
	if got := modeOf(t, view); got != 0o444 {
		t.Errorf("written with mode %v", got)
	}
	if puts := s.taken(); len(puts) != 1 || puts[0].base != "none" {
		t.Fatalf("took %v, not the view with no base", puts)
	}
	if running.synced("reference.json") != hashOf("{}") {
		t.Error("the shadow not updated")
	}
}

func TestRevertsAWriteToAReadOnlyViewAndNotesItOnce(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	view := filepath.Join(tree, "proj", "timeline.json")
	document := filepath.Join(tree, "proj", "inbox", "1-a.md")
	s.view("proj/timeline.json", "[]")
	s.record("proj/inbox/1-a.md", "one")
	running := start(t, s, tree, t.TempDir())

	writeOver(t, view, `["edited"]`)
	eventually(t, "the view reverted", func() bool { return holds(view, "[]") })
	if got := modeOf(t, view); got != 0o444 {
		t.Errorf("reverted with mode %v", got)
	}
	settle()
	if puts := s.taken(); len(puts) != 0 {
		t.Fatalf("took %v: a view sent up", puts)
	}
	if note := running.noted("proj/timeline.json"); note != revertNote {
		t.Fatalf("noted %q", note)
	}

	// The record moves the view: the note stays for the hook.
	s.view("proj/timeline.json", "[1]")
	running.stream.send(t, change("proj/timeline.json", "[1]"))
	eventually(t, "the view rewritten", func() bool { return holds(view, "[1]") })
	write(t, document, "two")
	if got := running.report(t, "proj"); got != "proj/timeline.json: "+revertNote+"\n" {
		t.Fatalf("printed %q", got)
	}
	if got := running.report(t, "proj"); got != "" {
		t.Fatalf("printed %q the second time", got)
	}
}

func TestAReleaseRevertsAViewWrittenInsideItsHoldAndPrintsTheNote(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	view := filepath.Join(tree, "proj", "timeline.json")
	root := filepath.Join(tree, "reference.json")
	s.view("proj/timeline.json", "[]")
	s.view("reference.json", "{}")
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	writeOver(t, view, `["edited"]`)
	writeOver(t, root, `{"edited": true}`)
	if got := running.release(t, "proj", chat); got != "proj/timeline.json: "+revertNote+"\n" {
		t.Fatalf("printed %q", got)
	}
	if !holds(view, "[]") {
		t.Fatalf("the view holds %q", read(t, view))
	}
	// The tree's root is no project folder: a view there is reverted, and its
	// note printed by no folder's release.
	eventually(t, "the root's view reverted", func() bool { return holds(root, "{}") })
	if note := running.noted("reference.json"); note != revertNote {
		t.Fatalf("noted %q", note)
	}
	if got := running.report(t, "proj"); got != "" {
		t.Fatalf("printed %q", got)
	}
	settle()
	if puts := s.taken(); len(puts) != 0 {
		t.Fatalf("took %v: a view sent up", puts)
	}
}

func TestWritesARecordMoveOverAWriteToAReadOnlyView(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	view := filepath.Join(tree, "reference.json")
	s.view("reference.json", "{}")
	running := start(t, s, tree, t.TempDir())

	// The agent writes the view while its move is fetched.
	fetching, written := make(chan struct{}), make(chan struct{})
	var once sync.Once
	s.fetches(func(string) {
		once.Do(func() {
			close(fetching)
			select {
			case <-written:
			case <-s.quit:
			}
		})
	})
	s.view("reference.json", `{"v": 2}`)
	running.stream.send(t, change("reference.json", `{"v": 2}`))
	<-fetching
	writeOver(t, view, `{"edited": true}`)
	close(written)

	eventually(t, "the move written", func() bool { return holds(view, `{"v": 2}`) })
	settle()
	if !holds(view, `{"v": 2}`) {
		t.Fatalf("the view holds %q", read(t, view))
	}
	if got := modeOf(t, view); got != 0o444 {
		t.Errorf("written with mode %v", got)
	}
	if puts := s.taken(); len(puts) != 0 {
		t.Fatalf("took %v: a view sent up", puts)
	}
	if note := running.noted("reference.json"); note != revertNote {
		t.Fatalf("noted %q", note)
	}
}
