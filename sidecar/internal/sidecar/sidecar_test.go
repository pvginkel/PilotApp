package sidecar

import (
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

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

// P-28: a change a reconcile could not get up goes up once the server takes
// it again, with the change stream open, heartbeats alone on it and nothing
// else moving.
func TestRetriesAnUploadAReconcileCouldNotSendUntilItLands(t *testing.T) {
	s := newServer(t)
	tree, data := t.TempDir(), t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	s.record("proj/a.md", "one")
	start(t, s, tree, data).stop()

	write(t, file, "the agent's")
	var down atomic.Bool
	down.Store(true)
	s.answering(func(put) answer {
		if down.Load() {
			return answer{status: http.StatusServiceUnavailable}
		}
		return answer{}
	})
	var waits *retries
	running := startWith(t, s, tree, data, func(sidecar *Sidecar) { waits = retrying(sidecar) })
	want := []time.Duration{
		time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second, 16 * time.Second, 30 * time.Second, 30 * time.Second,
	}
	for i := range want {
		eventually(t, "the wait before a retry", func() bool { return len(waits.begun()) == i+1 })
		if got := running.health(t); got != "ok\nconnected: true\npending: 1\n" {
			t.Fatalf("answered %q while the change waits", got)
		}
		running.stream.send(t, heartbeat)
		waits.end(t)
	}
	eventually(t, "the wait before the last retry", func() bool { return len(waits.begun()) == len(want)+1 })
	down.Store(false)
	running.stream.send(t, heartbeat)
	waits.end(t)
	eventually(t, "the change landed", func() bool { return running.synced("proj/a.md") == hashOf("the agent's") })
	settle()

	if got := waits.begun(); !slices.Equal(got[:len(want)], want) || got[len(want)] != retryMax {
		t.Errorf("waited %v", got)
	}
	puts := s.taken()
	// The reconcile's, then one at the end of each wait.
	if len(puts) != len(want)+2 {
		t.Fatalf("took %d PUTs", len(puts))
	}
	for _, again := range puts {
		if again.body != "the agent's" || again.base != hashOf("one") {
			t.Fatalf("took %q based on %s", again.body, again.base)
		}
	}
	if posts := s.manifests(); len(posts) != 2 {
		t.Errorf("posted %d manifests: a reconcile sent it up", len(posts))
	}
	if got := running.health(t); got != "ok\nconnected: true\npending: 0\n" {
		t.Errorf("answered %q once it landed", got)
	}
	logged := running.logged.String()
	for _, line := range []string{
		`msg="cannot sync a file of the tree: retrying" path=proj/a.md error="PUT proj/a.md: answered 503: " in=1s pending=1`,
		`msg="no longer waiting to go up" path=proj/a.md pending=0`,
	} {
		if !strings.Contains(logged, line) {
			t.Errorf("logged no %s", line)
		}
	}
}

func TestAChangeWhileAnUploadWaitsToRetryGoesUpAtOnce(t *testing.T) {
	s := newServer(t)
	s.answering(func(taken put) answer {
		if taken.body == "first" {
			return answer{status: http.StatusBadGateway}
		}
		return answer{}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	var waits *retries
	running := startWith(t, s, tree, t.TempDir(), func(sidecar *Sidecar) { waits = retrying(sidecar) })

	write(t, file, "first")
	eventually(t, "the wait before a retry", func() bool { return len(waits.begun()) == 1 })
	write(t, file, "second")
	eventually(t, "the change landed", func() bool { return running.synced("proj/a.md") == hashOf("second") })
	settle()
	if puts := s.taken(); len(puts) != 2 || puts[1].body != "second" || puts[1].base != "none" {
		t.Fatalf("took %+v", puts)
	}
	if got := waits.begun(); len(got) != 1 {
		t.Fatalf("waited %v", got)
	}
	if got := running.health(t); got != "ok\nconnected: true\npending: 0\n" {
		t.Fatalf("answered %q", got)
	}
}

// V13: a save a retry gets up goes up as the session whose save its bytes
// are, whoever holds the lock by then.
func TestARetriedUploadGoesUpAsTheSaveOfItsSession(t *testing.T) {
	s := newServer(t)
	var down atomic.Bool
	down.Store(true)
	s.answering(func(put) answer {
		if down.Load() {
			return answer{status: http.StatusInternalServerError}
		}
		return answer{}
	})
	tree := t.TempDir()
	var waits *retries
	running := startWith(t, s, tree, t.TempDir(), func(sidecar *Sidecar) { waits = retrying(sidecar) })

	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "a.md"), "the chat's")
	eventually(t, "the wait before a retry", func() bool { return len(waits.begun()) == 1 })
	began := time.Now()
	if got := running.release(t, "proj", chat); got != "not yet checked: proj/a.md\n" {
		t.Fatalf("printed %q", got)
	}
	if waited := time.Since(began); waited > time.Second {
		t.Fatalf("the release's flush waited %v, for the wait to retry", waited)
	}
	eventually(t, "the next wait before a retry", func() bool { return len(waits.begun()) == 2 })
	running.lock(t, "proj", job, os.Getpid())

	down.Store(false)
	waits.end(t)
	eventually(t, "the change landed", func() bool { return running.synced("proj/a.md") == hashOf("the chat's") })
	puts := s.taken()
	if len(puts) != 3 {
		t.Fatalf("took %d PUTs", len(puts))
	}
	for _, taken := range puts {
		if session := sessionOf(taken); session != chat {
			t.Errorf("a PUT carried %q, not the chat's session", session)
		}
	}
}

// V14: a PUT the server can never take is not made again, and stays pending;
// a path of no record is a stray, not pending.
func TestRetriesNoUploadTheServerCanNeverTake(t *testing.T) {
	s := newServer(t)
	s.answering(func(taken put) answer {
		switch {
		case taken.path == "proj/notes.md":
			return answer{status: http.StatusNotFound}
		case taken.body == "too big":
			return answer{status: http.StatusRequestEntityTooLarge}
		}
		return answer{}
	})
	tree := t.TempDir()
	big := filepath.Join(tree, "proj", "a.md")
	var waits *retries
	running := startWith(t, s, tree, t.TempDir(), func(sidecar *Sidecar) { waits = retrying(sidecar) })

	write(t, big, "too big")
	write(t, filepath.Join(tree, "proj", "notes.md"), "mine")
	eventually(t, "both PUTs", func() bool { return len(s.taken()) == 2 })
	settle()
	if puts := s.taken(); len(puts) != 2 {
		t.Fatalf("took %d PUTs", len(puts))
	}
	if got := waits.begun(); len(got) != 0 {
		t.Fatalf("waited %v to retry", got)
	}
	if got := running.health(t); got != "ok\nconnected: true\npending: 1\n" {
		t.Fatalf("answered %q", got)
	}
	if line := `msg="cannot sync a file of the tree" path=proj/a.md error="PUT proj/a.md: answered 413: " pending=1`; !strings.Contains(running.logged.String(), line) {
		t.Errorf("logged no %s", line)
	}

	write(t, big, "smaller")
	eventually(t, "the edit landed", func() bool { return running.synced("proj/a.md") == hashOf("smaller") })
	if got := running.health(t); got != "ok\nconnected: true\npending: 0\n" {
		t.Fatalf("answered %q once the edit landed", got)
	}
}

func TestAStopEndsAWaitToRetry(t *testing.T) {
	s := newServer(t)
	s.answering(func(put) answer { return answer{status: http.StatusServiceUnavailable} })
	tree := t.TempDir()
	var waits *retries
	running := startWith(t, s, tree, t.TempDir(), func(sidecar *Sidecar) { waits = retrying(sidecar) })
	write(t, filepath.Join(tree, "proj", "a.md"), "one")
	eventually(t, "the wait before a retry", func() bool { return len(waits.begun()) == 1 })

	stopped := make(chan struct{})
	go func() {
		running.stop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(5 * time.Second):
		t.Fatal("still running past the stop, its wait to retry under way")
	}
}
