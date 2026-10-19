package sidecar

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
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

// posted is a manifest the server took.
type posted struct {
	Tree   map[string]string `json:"tree"`
	Shadow map[string]string `json:"shadow"`
}

// checkPost is a check the server took.
type checkPost struct {
	Path        string  `json:"path"`
	Hash        string  `json:"hash"`
	WaitSeconds float64 `json:"wait_seconds"`
}

// server plays the sync routes as design 1 §5.1 shapes them, over a record
// of its own: files, path to the bytes it must hold, those in views
// read-only. A PUT is answered with respond, 204 by default, and the record
// takes what it answered; a GET answers the record once fetching is told of
// it; a manifest is answered
// by design 1 §5.5's rule over the record, amended by reconciling; a check
// is answered by checking, its path agreed and no error by default; the
// change stream is accepted unless opening answers its attempt otherwise,
// and each one accepted is handed to the test on streams. Two PUTs of one
// path out at once fail the test.
type server struct {
	t       *testing.T
	url     string
	quit    chan struct{}
	streams chan *stream

	mu          sync.Mutex
	files       map[string]string
	views       map[string]bool
	puts        []put
	checks      []checkPost
	gets        []string
	posts       []posted
	connects    int
	out         map[string]int
	respond     func(put) answer
	reconciling func(posted, protocol.Reconciled) protocol.Reconciled
	checking    func(checkPost) protocol.CheckAnswer
	opening     func(attempt int) (status int, body string)
	fetching    func(path string)
}

// stream is a change stream the server holds open: the test sends it
// frames, and drops it.
type stream struct {
	frames  chan string
	dropped chan struct{}
}

func newServer(t *testing.T) *server {
	s := &server{
		t:       t,
		quit:    make(chan struct{}),
		streams: make(chan *stream, 16),
		files:   map[string]string{},
		views:   map[string]bool{},
		out:     map[string]int{},
		respond: func(put) answer { return answer{} },
		checking: func(checkPost) protocol.CheckAnswer {
			return protocol.CheckAnswer{Checked: true, Errors: []protocol.SaveError{}, HomelessDeferrals: []protocol.HomelessDeferral{}}
		},
		opening:  func(int) (int, string) { return 0, "" },
		fetching: func(string) {},
	}
	httpServer := httptest.NewServer(http.HandlerFunc(s.serve))
	t.Cleanup(httpServer.Close)
	// Runs before the server closes, which waits for the streams to end.
	t.Cleanup(func() { close(s.quit) })
	s.url = httpServer.URL
	return s
}

func (s *server) answering(respond func(put) answer) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.respond = respond
}

func (s *server) amending(reconciling func(posted, protocol.Reconciled) protocol.Reconciled) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.reconciling = reconciling
}

func (s *server) answeringChecks(checking func(checkPost) protocol.CheckAnswer) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.checking = checking
}

// fetches is told of each GET, by path, before it is answered.
func (s *server) fetches(fetching func(path string)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.fetching = fetching
}

// opens answers the change stream's attempts, each counted from 1: a status
// and a body, or 0 to open it.
func (s *server) opens(opening func(attempt int) (int, string)) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.opening = opening
}

// record sets what path must hold; "" removes it from the record.
func (s *server) record(path, content string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if content == "" {
		delete(s.files, path)
		delete(s.views, path)
		return
	}
	s.files[path] = content
}

// view sets what path, a read-only view, must hold.
func (s *server) view(path, content string) {
	s.record(path, content)
	s.mu.Lock()
	defer s.mu.Unlock()
	s.views[path] = true
}

func (s *server) taken() []put {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.puts)
}

func (s *server) fetched() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.gets)
}

func (s *server) manifests() []posted {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.posts)
}

func (s *server) checked() []checkPost {
	s.mu.Lock()
	defer s.mu.Unlock()
	return slices.Clone(s.checks)
}

// accept is the change stream the server opens next.
func (s *server) accept(t *testing.T) *stream {
	t.Helper()
	select {
	case opened := <-s.streams:
		return opened
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for the change stream")
		return nil
	}
}

func (c *stream) send(t *testing.T, frame string) {
	t.Helper()
	select {
	case c.frames <- frame:
	case <-time.After(5 * time.Second):
		t.Fatal("timed out sending on the change stream")
	}
}

func (c *stream) drop() {
	close(c.dropped)
}

func (s *server) serve(w http.ResponseWriter, r *http.Request) {
	path, file := strings.CutPrefix(r.URL.Path, "/api/sync/files/")
	switch {
	case file && r.Method == http.MethodPut:
		s.put(w, r, path)
	case file && r.Method == http.MethodGet:
		s.get(w, path)
	case r.URL.Path == "/api/sync/manifest" && r.Method == http.MethodPost:
		s.manifest(w, r)
	case r.URL.Path == "/api/sync/events" && r.Method == http.MethodGet:
		s.events(w, r)
	case r.URL.Path == "/api/sync/check" && r.Method == http.MethodPost:
		s.check(w, r)
	default:
		s.t.Errorf("unexpected %s %s", r.Method, r.URL)
		w.WriteHeader(http.StatusInternalServerError)
	}
}

func (s *server) put(w http.ResponseWriter, r *http.Request, path string) {
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
	switch {
	case given.status != 0:
	case given.content == "":
		s.files[path] = string(body)
	default:
		s.files[path] = given.content
	}
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

func (s *server) get(w http.ResponseWriter, path string) {
	s.mu.Lock()
	s.gets = append(s.gets, path)
	fetching := s.fetching
	s.mu.Unlock()
	fetching(path)
	s.mu.Lock()
	content, ok := s.files[path]
	s.mu.Unlock()
	if !ok {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	w.Header().Set("X-Pilot-Hash", protocol.Hash([]byte(content)))
	w.Header().Set("Content-Type", "application/octet-stream")
	_, _ = io.WriteString(w, content)
}

func (s *server) manifest(w http.ResponseWriter, r *http.Request) {
	var body posted
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Tree == nil || body.Shadow == nil {
		s.t.Errorf("posted a manifest that is not {tree, shadow}: %v", err)
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	s.mu.Lock()
	s.posts = append(s.posts, body)
	reconciling := s.reconciling
	answered := s.rule(body)
	s.mu.Unlock()
	if reconciling != nil {
		answered = reconciling(body, answered)
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(answered); err != nil {
		s.t.Error(err)
	}
}

// rule is design 1 §5.5 step 2's over the record. The caller holds mu.
func (s *server) rule(body posted) protocol.Reconciled {
	answered := protocol.Reconciled{
		Manifest: []protocol.Entry{}, SendUp: []string{}, WriteDown: []protocol.Entry{}, Delete: []string{},
	}
	for _, path := range slices.Sorted(maps.Keys(s.files)) {
		entry := protocol.Entry{Path: path, Hash: protocol.Hash([]byte(s.files[path])), Readonly: s.views[path]}
		answered.Manifest = append(answered.Manifest, entry)
		if body.Tree[path] != entry.Hash {
			answered.WriteDown = append(answered.WriteDown, entry)
		}
		if disk, ok := body.Tree[path]; ok && body.Shadow[path] != disk {
			answered.SendUp = append(answered.SendUp, path)
		}
	}
	for path := range body.Shadow {
		if _, ok := s.files[path]; !ok {
			answered.Delete = append(answered.Delete, path)
		}
	}
	slices.Sort(answered.Delete)
	return answered
}

func (s *server) check(w http.ResponseWriter, r *http.Request) {
	var body checkPost
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		s.t.Errorf("posted a check that is not {path, hash, wait_seconds}: %v", err)
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	s.mu.Lock()
	s.checks = append(s.checks, body)
	checking := s.checking
	s.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(checking(body)); err != nil {
		s.t.Error(err)
	}
}

func (s *server) events(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	s.connects++
	status, body := s.opening(s.connects)
	s.mu.Unlock()
	if status != 0 {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.WriteHeader(http.StatusOK)
	opened := &stream{frames: make(chan string), dropped: make(chan struct{})}
	frame := hello
	for {
		if _, err := io.WriteString(w, frame); err != nil {
			return
		}
		w.(http.Flusher).Flush()
		if frame == hello {
			s.streams <- opened
		}
		select {
		case frame = <-opened.frames:
		case <-opened.dropped:
			return
		case <-r.Context().Done():
			return
		case <-s.quit:
			return
		}
	}
}

// The change stream's frames, as the server writes them.
var (
	hello     = "event: hello\ndata: {\"protocol\": {\"min\": 1, \"max\": 1}, \"manifest_hash\": \"" + hashOf("manifest") + "\"}\n\n"
	manifest  = "event: manifest\ndata: {}\n\n"
	heartbeat = ": heartbeat\n\n"
)

func change(path, content string) string {
	return fmt.Sprintf("event: change\ndata: {\"path\": %q, \"hash\": %q}\n\n", path, hashOf(content))
}

// logs is what a sidecar logged, kept as it is written to the test's output.
type logs struct {
	mu      sync.Mutex
	out     io.Writer
	written bytes.Buffer
}

func (l *logs) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.written.Write(p)
	return l.out.Write(p)
}

func (l *logs) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.written.String()
}

// newSidecar is a sidecar of tree and data against s, not yet running, and
// what it logs.
func newSidecar(t *testing.T, s *server, tree, data string) (*Sidecar, *logs) {
	t.Helper()
	logged := &logs{out: t.Output()}
	sidecar, err := New(configure(s, tree, data), slog.New(slog.NewTextHandler(logged, nil)))
	if err != nil {
		t.Fatal(err)
	}
	return sidecar, logged
}

// run runs sidecar until the test ends, or until the stop it answers is
// called.
func run(t *testing.T, sidecar *Sidecar) func() {
	t.Helper()
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

// started is a sidecar running until the test ends, or until stop is
// called, and the change stream it holds.
type started struct {
	sidecar *Sidecar
	stop    func()
	stream  *stream
}

// start runs a sidecar on tree and data against s, once its reconcile on
// connect is done.
func start(t *testing.T, s *server, tree, data string) started {
	t.Helper()
	sidecar, _ := newSidecar(t, s, tree, data)
	before := len(s.manifests())
	stop := run(t, sidecar)
	opened := s.accept(t)
	eventually(t, "the reconcile on connect", func() bool { return len(s.manifests()) > before })
	settle()
	return started{sidecar: sidecar, stop: stop, stream: opened}
}

// noted is the local note on path, "" when there is none.
func (s started) noted(path string) string {
	notes := s.sidecar.tree.notes
	notes.mu.Lock()
	defer notes.mu.Unlock()
	return notes.byPath[path].text
}

// synced is the hash path last synced with, "" when it has not.
func (s started) synced(path string) string {
	hash, _ := s.sidecar.tree.shadow.Hash(path)
	return hash
}

func configure(s *server, tree, data string) config.Config {
	return config.Config{
		PilotURL:      s.url,
		Token:         token,
		EnvironmentID: environment,
		// A port the kernel picks, free.
		LocalPort: 0,
		TreeRoot:  tree,
		DataDir:   data,
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

// settle waits long enough for any call still to come.
func settle() {
	time.Sleep(coalesce + 4*watch.Debounce)
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

// holds says whether the file at name holds content.
func holds(name, content string) bool {
	got, err := os.ReadFile(name)
	return err == nil && string(got) == content
}

func exists(name string) bool {
	_, err := os.Lstat(name)
	return err == nil
}

func hashOf(content string) string {
	return protocol.Hash([]byte(content))
}
