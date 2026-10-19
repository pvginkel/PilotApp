package sidecar

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/config"
	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
	"github.com/pvginkel/PilotApp/sidecar/internal/watch"
)

const (
	token       = "example-token"
	environment = "example-env-1"
)

// put is a PUT the server took.
type put struct {
	path   string
	base   string
	body   string
	header http.Header
}

// answer is how the server answers a PUT: 204 when content is empty, else
// 200 with content; or status alone, a refusal.
type answer struct {
	content string
	status  int
}

// server plays the sync routes' PUT as design 1 §5.1 shapes it, answering
// each with respond, 204 by default, and fails the test on two PUTs of one
// path out at once.
type server struct {
	t       *testing.T
	url     string
	mu      sync.Mutex
	puts    []put
	out     map[string]int
	respond func(put) answer
}

func newServer(t *testing.T) *server {
	s := &server{t: t, out: map[string]int{}, respond: func(put) answer { return answer{} }}
	httpServer := httptest.NewServer(http.HandlerFunc(s.serve))
	t.Cleanup(httpServer.Close)
	s.url = httpServer.URL
	return s
}

func (s *server) answering(respond func(put) answer) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.respond = respond
}

func (s *server) taken() []put {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]put(nil), s.puts...)
}

func (s *server) serve(w http.ResponseWriter, r *http.Request) {
	path, ok := strings.CutPrefix(r.URL.Path, "/api/sync/files/")
	if r.Method != http.MethodPut || !ok {
		s.t.Errorf("unexpected %s %s", r.Method, r.URL)
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	body, err := io.ReadAll(r.Body)
	if err != nil {
		s.t.Error(err)
	}
	taken := put{path: path, base: r.Header.Get("X-Pilot-Base-Hash"), body: string(body), header: r.Header.Clone()}
	s.mu.Lock()
	s.out[path]++
	if s.out[path] > 1 {
		s.t.Errorf("two PUTs of %s out at once", path)
	}
	s.puts = append(s.puts, taken)
	respond := s.respond
	s.mu.Unlock()

	given := respond(taken)

	s.mu.Lock()
	s.out[path]--
	s.mu.Unlock()
	w.Header().Set("X-Pilot-Faults", "0")
	switch {
	case given.status != 0:
		w.WriteHeader(given.status)
	case given.content == "":
		w.Header().Set("X-Pilot-Hash", protocol.Hash(body))
		w.WriteHeader(http.StatusNoContent)
	default:
		w.Header().Set("X-Pilot-Hash", protocol.Hash([]byte(given.content)))
		w.Header().Set("Content-Type", "application/octet-stream")
		_, _ = io.WriteString(w, given.content)
	}
}

// start runs a sidecar on tree and data against s until the test ends, or
// until the stop it answers is called.
func start(t *testing.T, s *server, tree, data string) func() {
	t.Helper()
	sidecar, err := New(configure(s, tree, data), slog.New(slog.NewTextHandler(t.Output(), nil)))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error)
	go func() { done <- sidecar.Run(ctx) }()
	stop := sync.OnceFunc(func() {
		cancel()
		if err := <-done; err != nil {
			t.Error(err)
		}
	})
	t.Cleanup(stop)
	return stop
}

func configure(s *server, tree, data string) config.Config {
	return config.Config{
		PilotURL:      s.url,
		Token:         token,
		EnvironmentID: environment,
		LocalPort:     config.DefaultLocalPort,
		TreeRoot:      tree,
		DataDir:       data,
	}
}

func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	for deadline := time.Now().Add(5 * time.Second); !cond(); time.Sleep(5 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
	}
}

// settle waits long enough for any PUT still to come.
func settle() {
	time.Sleep(4 * watch.Debounce)
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

func read(t *testing.T, name string) string {
	t.Helper()
	content, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return string(content)
}

func hashOf(content string) string {
	return protocol.Hash([]byte(content))
}

func TestPutsAChangedFileWithItsShadowAsTheBase(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "inbox", "1-a.md")
	write(t, file, "zero")
	start(t, s, tree, t.TempDir())

	write(t, file, "one")
	eventually(t, "the first PUT", func() bool { return len(s.taken()) == 1 })
	write(t, file, "two")
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	settle()

	puts := s.taken()
	if len(puts) != 2 {
		t.Fatalf("took %d PUTs", len(puts))
	}
	for i, want := range []put{
		{path: "proj/inbox/1-a.md", base: "none", body: "one"},
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
		if got := puts[0].header.Get(name); got != value {
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
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs, the sidecar's own write sent back", len(puts))
	}
	info, err := os.Stat(file)
	if err != nil || info.Mode().Perm() != 0o640 {
		t.Fatalf("mode %v, %v", info.Mode(), err)
	}

	write(t, file, "edited")
	eventually(t, "the next PUT", func() bool { return len(s.taken()) == 2 })
	if base := s.taken()[1].base; base != hashOf("merged") {
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
	eventually(t, "the first PUT", func() bool { return len(s.taken()) == 1 })
	write(t, file, "second")
	settle()
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs while the first was out", len(puts))
	}
	close(release)
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	settle()

	if second := s.taken()[1]; second.body != "second" || second.base != hashOf("first, merged") {
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
	stop := start(t, s, tree, data)
	write(t, file, "one")
	eventually(t, "the first PUT", func() bool { return len(s.taken()) == 1 })
	settle()
	stop()

	start(t, s, tree, data)
	write(t, file, "one")
	settle()
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs of a file as last synced", len(puts))
	}
	write(t, file, "two")
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	if base := s.taken()[1].base; base != hashOf("one") {
		t.Fatalf("based on %s, not the last run's hash", base)
	}
}

func TestLeavesAFileTheRecordNeverBore(t *testing.T) {
	s := newServer(t)
	s.answering(func(put) answer { return answer{status: http.StatusNotFound} })
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "notes.md")
	write(t, file, "")
	start(t, s, tree, t.TempDir())

	write(t, file, "mine")
	eventually(t, "the first PUT", func() bool { return len(s.taken()) == 1 })
	write(t, file, "still mine")
	eventually(t, "the second PUT", func() bool { return len(s.taken()) == 2 })
	if base := s.taken()[1].base; base != "none" {
		t.Fatalf("based on %s: a refused save is in the shadow", base)
	}
	if got := read(t, file); got != "still mine" {
		t.Fatalf("the file holds %q", got)
	}
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
