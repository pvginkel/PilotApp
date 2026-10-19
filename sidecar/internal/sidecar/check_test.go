package sidecar

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// get is the hook's call of the sidecar's local route, path and query
// included: its status, its Content-Type and its text.
func (s started) get(route string) (int, string, string, error) {
	request, err := http.NewRequestWithContext(context.Background(), http.MethodGet,
		"http://"+s.sidecar.listener.Addr().String()+route, nil)
	if err != nil {
		return 0, "", "", err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return 0, "", "", err
	}
	body, err := io.ReadAll(response.Body)
	if err := errors.Join(err, response.Body.Close()); err != nil {
		return 0, "", "", err
	}
	return response.StatusCode, response.Header.Get("Content-Type"), string(body), nil
}

// call is get, its error the test's.
func (s started) call(t *testing.T, route string) (int, string, string) {
	t.Helper()
	status, contentType, text, err := s.get(route)
	if err != nil {
		t.Fatal(err)
	}
	return status, contentType, text
}

// check is the hook's check of the file at name, answered 200: its text.
func (s started) check(t *testing.T, name string) string {
	t.Helper()
	status, _, text := s.call(t, "/check?path="+url.QueryEscape(name))
	if status != http.StatusOK {
		t.Fatalf("answered %d: %q", status, text)
	}
	return text
}

func TestCheckOfACleanSavePostsItsHashAndPrintsNothing(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "inbox", "1-a.md")
	running := start(t, s, tree, t.TempDir())

	write(t, file, "saved")
	status, contentType, text := running.call(t, "/check?path="+url.QueryEscape(file))
	if status != http.StatusOK || contentType != "text/plain; charset=utf-8" || text != "" {
		t.Fatalf("answered %d %s %q", status, contentType, text)
	}
	checks := s.checked()
	if len(checks) != 1 {
		t.Fatalf("posted %d checks", len(checks))
	}
	if got := checks[0]; got.Path != "proj/inbox/1-a.md" || got.Hash != hashOf("saved") ||
		got.WaitSeconds < 0 || got.WaitSeconds >= checkCap.Seconds() {
		t.Fatalf("posted %+v", got)
	}
	settle()
	if puts := s.taken(); len(puts) != 1 || puts[0].body != "saved" {
		t.Fatalf("took %v", puts)
	}
}

func TestCheckPrintsTheErrorsThenTheNotesThenTheDeferrals(t *testing.T) {
	s := newServer(t)
	s.answering(func(taken put) answer {
		if taken.path == "proj/notes.md" || taken.path == "draft-2/zz.md" {
			return answer{status: http.StatusNotFound}
		}
		return answer{}
	})
	line := 31
	s.answeringChecks(func(checkPost) protocol.CheckAnswer {
		return protocol.CheckAnswer{
			Checked: true,
			Errors: []protocol.SaveError{
				{Path: "proj/inbox/4-b.md", Kind: "reverted", Line: &line, Message: "`answer:` is the record's, line 31 reverted"},
				{Path: "proj/plan.json", Kind: "parse", Message: "not JSON"},
			},
			HomelessDeferrals: []protocol.HomelessDeferral{
				{Block: "P-4/d2", Document: "proj/inbox/4-b.md", Title: "The importer", To: "T-7"},
				{Block: "P-5/d1", Document: "proj/inbox/5-c.md", Title: "The export", To: "plan"},
			},
		}
	})
	tree := t.TempDir()
	write(t, filepath.Join(tree, "proj", "notes.md"), "mine")
	write(t, filepath.Join(tree, "draft-2", "zz.md"), "mine too")
	running := start(t, s, tree, t.TempDir())

	file := filepath.Join(tree, "proj", "inbox", "4-b.md")
	write(t, file, "edited")
	want := "proj/inbox/4-b.md:31: `answer:` is the record's, line 31 reverted\n" +
		"proj/plan.json: not JSON\n" +
		"draft-2/zz.md: " + strayNote + "\n" +
		"proj/notes.md: " + strayNote + "\n" +
		homelessHeading + "\n" +
		"- P-4/d2 in proj/inbox/4-b.md (The importer), to: T-7\n" +
		"- P-5/d1 in proj/inbox/5-c.md (The export), to: plan\n"
	if got := running.check(t, file); got != want {
		t.Fatalf("printed\n%s\nwant\n%s", got, want)
	}
	if got := running.check(t, file); got != want {
		t.Fatalf("printed\n%s\nthe second time", got)
	}
}

func TestCheckOfAStrayFilePrintsItsNote(t *testing.T) {
	s := newServer(t)
	s.answering(func(put) answer { return answer{status: http.StatusNotFound} })
	s.answeringChecks(func(checkPost) protocol.CheckAnswer { return protocol.CheckAnswer{} })
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	file := filepath.Join(tree, "proj", "notes.md")
	write(t, file, "mine")
	began := time.Now()
	if got := running.check(t, file); got != "proj/notes.md: "+strayNote+"\n" {
		t.Fatalf("printed %q", got)
	}
	if waited := time.Since(began); waited >= checkCap {
		t.Fatalf("waited %v, the cap out", waited)
	}
	if checks := s.checked(); len(checks) != 1 || checks[0].Hash != hashOf("mine") {
		t.Fatalf("posted %+v", checks)
	}
	if !holds(file, "mine") {
		t.Fatal("a stray file was touched")
	}
}

func TestCheckOfAFileRewrittenFromA200AnswerPostsTheAnswersHash(t *testing.T) {
	s := newServer(t)
	release := make(chan struct{})
	s.answering(func(taken put) answer {
		if taken.body != "saved" {
			return answer{}
		}
		<-release
		return answer{content: "merged"}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "plan.json")
	running := start(t, s, tree, t.TempDir())

	// The hook calls while the save is out: the check waits for its answer,
	// not the cap.
	write(t, file, "saved")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	go func() {
		time.Sleep(100 * time.Millisecond)
		close(release)
	}()
	began := time.Now()
	if got := running.check(t, file); got != "" {
		t.Fatalf("printed %q", got)
	}
	if waited := time.Since(began); waited >= checkCap {
		t.Fatalf("waited %v, the cap out", waited)
	}
	if !holds(file, "merged") {
		t.Fatalf("the file holds %q", read(t, file))
	}
	// The hook calls once the answer is written: the file's hash is acked.
	running.check(t, file)
	checks := s.checked()
	if len(checks) != 2 {
		t.Fatalf("posted %d checks", len(checks))
	}
	for i, got := range checks {
		if got.Path != "proj/plan.json" || got.Hash != hashOf("merged") {
			t.Errorf("check %d: posted %+v, not the answer's hash", i, got)
		}
	}
	if checks[1].WaitSeconds >= checks[0].WaitSeconds {
		t.Errorf("waited %vs once the answer was written", checks[1].WaitSeconds)
	}
	settle()
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs", len(puts))
	}
}

func TestCheckGivesUpAtTheCapWhileTheSyncGoesOn(t *testing.T) {
	s := newServer(t)
	release := make(chan struct{})
	defer close(release)
	s.answering(func(taken put) answer {
		if taken.path == "proj/a.md" {
			<-release
		}
		return answer{}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "a.md")
	running := start(t, s, tree, t.TempDir())

	write(t, file, "saved")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	type checked struct {
		text   string
		waited time.Duration
	}
	done := make(chan checked)
	go func() {
		began := time.Now()
		status, _, text, err := running.get("/check?path=" + url.QueryEscape(file))
		if err != nil || status != http.StatusOK {
			t.Errorf("answered %d, %v", status, err)
		}
		done <- checked{text, time.Since(began)}
	}()
	// Another file syncs while the check waits.
	write(t, filepath.Join(tree, "proj", "b.md"), "other")
	eventually(t, "the other file's PUT", func() bool { return len(s.taken()) == 2 })

	got := <-done
	if got.text != "not yet checked: proj/a.md\n" {
		t.Fatalf("printed %q", got.text)
	}
	if got.waited < checkCap || got.waited > checkCap+time.Second {
		t.Fatalf("answered after %v", got.waited)
	}
	if checks := s.checked(); len(checks) != 0 {
		t.Fatalf("posted %+v past the cap", checks)
	}
}

func TestCheckRefusesWhatIsNotAFileOfTheTree(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	for name, want := range map[string]int{
		"":                                      http.StatusBadRequest,
		"proj/a.md":                             http.StatusBadRequest,
		tree:                                    http.StatusBadRequest,
		filepath.Dir(tree) + "/elsewhere.md":    http.StatusBadRequest,
		tree + "/../elsewhere.md":               http.StatusBadRequest,
		filepath.Join(tree, "proj", "none.md"):  http.StatusNotFound,
		filepath.Join(tree, "proj", "..", "x"):  http.StatusNotFound,
		filepath.Join(tree, "proj", "a b#1.md"): http.StatusNotFound,
	} {
		if status, _, text := running.call(t, "/check?path="+url.QueryEscape(name)); status != want {
			t.Errorf("%q: answered %d %q, want %d", name, status, text, want)
		}
	}
	if checks := s.checked(); len(checks) != 0 {
		t.Fatalf("posted %+v", checks)
	}
}

func TestHealthzAnswers(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())
	if status, _, text := running.call(t, "/healthz"); status != http.StatusOK || text != "ok\n" {
		t.Fatalf("answered %d %q", status, text)
	}
}

func TestRefusesALocalPortInUse(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())
	cfg := configure(s, t.TempDir(), t.TempDir())
	cfg.LocalPort = running.sidecar.listener.Addr().(*net.TCPAddr).Port
	_, err := New(cfg, slog.New(slog.NewTextHandler(t.Output(), nil)))
	if err == nil || !strings.Contains(err.Error(), "cannot serve the hook's check") {
		t.Fatalf("got %v", err)
	}
}
