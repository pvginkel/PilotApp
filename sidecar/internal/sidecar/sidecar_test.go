package sidecar

import (
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

func TestPutsAChangedFileWithItsShadowAsTheBase(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "inbox", "1-a.md")
	write(t, file, "zero")
	start(t, s, tree, t.TempDir())

	write(t, file, "one")
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	write(t, file, "two")
	eventually(t, "the third PUT", func() bool { return len(s.taken()) == 3 })
	settle()

	puts := s.taken()
	if len(puts) != 3 {
		t.Fatalf("took %d PUTs", len(puts))
	}
	for i, want := range []put{
		{path: "proj/inbox/1-a.md", base: "none", body: "zero"},
		{path: "proj/inbox/1-a.md", base: hashOf("zero"), body: "one"},
		{path: "proj/inbox/1-a.md", base: hashOf("one"), body: "two"},
	} {
		if got := puts[i]; got.path != want.path || got.base != want.base || got.body != want.body {
			t.Errorf("PUT %d: got %s %s %q, want %s %s %q", i, got.path, got.base, got.body, want.path, want.base, want.body)
		}
	}
	headers := map[string]string{
		"Authorization":         "Bearer " + token,
		"X-Pilot-Environment":   environment,
		"X-Pilot-Sync-Protocol": strconv.Itoa(protocol.Version),
	}
	for name, value := range headers {
		if got := puts[1].header.Get(name); got != value {
			t.Errorf("%s: got %q, want %q", name, got, value)
		}
	}
}

func TestWritesA200AnswerInPlaceAndNeverSendsItBack(t *testing.T) {
	s := newServer(t)
	s.answering(func(taken put) answer {
		if taken.body == "saved" {
			return answer{content: "merged"}
		}
		return answer{}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	write(t, file, "")
	if err := os.Chmod(file, 0o640); err != nil {
		t.Fatal(err)
	}
	start(t, s, tree, t.TempDir())

	write(t, file, "saved")
	eventually(t, "the answer written", func() bool { return read(t, file) == "merged" })
	settle()
	if puts := s.taken(); len(puts) != 2 {
		t.Fatalf("took %d PUTs, the sidecar's own write sent back", len(puts))
	}
	info, err := os.Stat(file)
	if err != nil || info.Mode().Perm() != 0o640 {
		t.Fatalf("mode %v, %v", info.Mode(), err)
	}

	write(t, file, "edited")
	eventually(t, "the next PUT", func() bool { return len(s.taken()) == 3 })
	if base := s.taken()[2].base; base != hashOf("merged") {
		t.Fatalf("based on %s, not the answer's hash", base)
	}
}

func TestKeepsTheAgentsWriteMadeWhileThePutWasOut(t *testing.T) {
	s := newServer(t)
	release := make(chan struct{})
	s.answering(func(taken put) answer {
		if taken.body != "first" {
			return answer{}
		}
		<-release
		return answer{content: "first, merged"}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	write(t, file, "")
	start(t, s, tree, t.TempDir())

	write(t, file, "first")
	eventually(t, "the first PUT", func() bool { return len(s.taken()) == 2 })
	write(t, file, "second")
	settle()
	if puts := s.taken(); len(puts) != 2 {
		t.Fatalf("took %d PUTs while the first was out", len(puts))
	}
	close(release)
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 3 })
	settle()

	if second := s.taken()[2]; second.body != "second" || second.base != hashOf("first, merged") {
		t.Fatalf("second PUT: %q based on %s", second.body, second.base)
	}
	if got := read(t, file); got != "second" {
		t.Fatalf("the file holds %q", got)
	}
}

func TestKeepsTheShadowAcrossARestart(t *testing.T) {
	s := newServer(t)
	tree, data := t.TempDir(), t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	write(t, file, "")
	first := start(t, s, tree, data)
	write(t, file, "one")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 2 })
	settle()
	first.stop()

	start(t, s, tree, data)
	write(t, file, "one")
	settle()
	if puts := s.taken(); len(puts) != 2 {
		t.Fatalf("took %d PUTs of a file as last synced", len(puts))
	}
	write(t, file, "two")
	eventually(t, "the next PUT", func() bool { return len(s.taken()) == 3 })
	if base := s.taken()[2].base; base != hashOf("one") {
		t.Fatalf("based on %s, not the last run's hash", base)
	}
}

func TestLeavesAFileTheRecordNeverBoreWithANote(t *testing.T) {
	s := newServer(t)
	s.answering(func(put) answer { return answer{status: http.StatusNotFound} })
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "notes.md")
	write(t, file, "")
	running := start(t, s, tree, t.TempDir())
	if note := running.noted("proj/notes.md"); note != strayNote {
		t.Fatalf("noted %q on connect", note)
	}

	write(t, file, "mine")
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	write(t, file, "still mine")
	eventually(t, "the third PUT", func() bool { return len(s.taken()) == 3 })
	if base := s.taken()[2].base; base != "none" {
		t.Fatalf("based on %s: a refused save is in the shadow", base)
	}
	if got := read(t, file); got != "still mine" {
		t.Fatalf("the file holds %q", got)
	}
	if note := running.noted("proj/notes.md"); note != strayNote {
		t.Fatalf("noted %q", note)
	}

	if err := os.Remove(file); err != nil {
		t.Fatal(err)
	}
	eventually(t, "the note gone with the file", func() bool { return running.noted("proj/notes.md") == "" })
}

func TestPutsAFileOfADirectoryMadeLater(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	start(t, s, tree, t.TempDir())

	write(t, filepath.Join(tree, "draft-2", "inbox", "1-a.md"), "new")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	if got := s.taken()[0]; got.path != "draft-2/inbox/1-a.md" || got.body != "new" {
		t.Fatalf("took %s %q", got.path, got.body)
	}
}

func TestRunsWithoutAHome(t *testing.T) {
	t.Setenv("HOME", "")
	if err := os.Unsetenv("HOME"); err != nil {
		t.Fatal(err)
	}
	s := newServer(t)
	tree := t.TempDir()
	start(t, s, tree, t.TempDir())
	write(t, filepath.Join(tree, "proj", "a.md"), "one")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
}

func TestRefusesADataDirectoryItCannotWrite(t *testing.T) {
	s := newServer(t)
	parent := t.TempDir()
	file := filepath.Join(parent, "a-file")
	write(t, file, "")
	readonly := filepath.Join(parent, "read-only")
	if err := os.Mkdir(readonly, 0o555); err != nil {
		t.Fatal(err)
	}
	unwritable := map[string]string{"a file": file, "under a file": filepath.Join(file, "data")}
	if os.Geteuid() != 0 {
		// Root writes a directory whatever its mode.
		unwritable["read-only"] = readonly
	}
	for name, data := range unwritable {
		_, err := New(configure(s, t.TempDir(), data), slog.New(slog.NewTextHandler(t.Output(), nil)))
		if err == nil || !strings.Contains(err.Error(), "cannot write the data directory "+data) {
			t.Errorf("%s: got %v", name, err)
		}
	}
}
