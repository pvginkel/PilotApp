package sidecar

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"maps"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// The brain sessions the tests' hooks call for.
const (
	chat = "0b8f2c4e-1d3a-4e5f-8a6b-7c9d0e1f2a3b"
	job  = "5d7e9f1a-2b3c-4d5e-8f6a-9b0c1d2e3f4a"
)

// noProcess is a pid above the kernel's highest, so of no process.
const noProcess = 1 << 30

// post is a hook's call of the sidecar's local route with body: its
// status, its Content-Type and its text.
func (s started) post(route, body string) (int, string, string, error) {
	request, err := http.NewRequestWithContext(context.Background(), http.MethodPost,
		"http://"+s.sidecar.listener.Addr().String()+route, strings.NewReader(body))
	if err != nil {
		return 0, "", "", err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return 0, "", "", err
	}
	text, err := io.ReadAll(response.Body)
	if err := errors.Join(err, response.Body.Close()); err != nil {
		return 0, "", "", err
	}
	return response.StatusCode, response.Header.Get("Content-Type"), string(text), nil
}

// call is post, its error the test's.
func (s started) call(t testing.TB, route, body string) (int, string, string) {
	t.Helper()
	status, contentType, text, err := s.post(route, body)
	if err != nil {
		t.Fatal(err)
	}
	return status, contentType, text
}

// hook is the body of a hook's call for session in folder, a project
// folder of the tree, with fields beside the project and the session.
func (s started) hook(t testing.TB, folder, session string, fields map[string]any) string {
	t.Helper()
	body := map[string]any{"project": filepath.Join(s.sidecar.tree.root, folder), "session": session}
	maps.Copy(body, fields)
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	return string(encoded)
}

// pid is a hold of this process's.
func pid(of int) map[string]any { return map[string]any{"pid": of} }

// lock is a hook's lock of folder for session by pid, answered 200.
func (s started) lock(t testing.TB, folder, session string, by int) {
	t.Helper()
	if status, _, text := s.call(t, "/lock", s.hook(t, folder, session, pid(by))); status != http.StatusOK || text != "" {
		t.Fatalf("lock answered %d %q", status, text)
	}
}

// locking is a hook's lock of folder for session by this process, sent at
// once: its status once it is answered.
func (s started) locking(t *testing.T, folder, session string) <-chan int {
	body := s.hook(t, folder, session, pid(os.Getpid()))
	answered := make(chan int, 1)
	go func() {
		status, _, text, err := s.post("/lock", body)
		if err != nil {
			t.Error(err)
		}
		if status != http.StatusOK {
			t.Logf("lock answered %d %q", status, text)
		}
		answered <- status
	}()
	return answered
}

// release is a hook's release of the hold of folder session took by this
// process, answered 200: its text.
func (s started) release(t testing.TB, folder, session string) string {
	t.Helper()
	status, contentType, text := s.call(t, "/release", s.hook(t, folder, session, pid(os.Getpid())))
	if status != http.StatusOK || contentType != "text/plain; charset=utf-8" {
		t.Fatalf("release answered %d %s %q", status, contentType, text)
	}
	return text
}

// report is the release of a session that holds nothing: the check of
// folder alone.
func (s started) report(t testing.TB, folder string) string {
	t.Helper()
	return s.release(t, folder, "a-session-holding-nothing")
}

// bound sets the lock's wait and how often a waiter looks for a gone
// holder.
func (s started) bound(wait, poll time.Duration) {
	writers := s.sidecar.tree.writers
	writers.mu.Lock()
	defer writers.mu.Unlock()
	writers.wait, writers.poll = wait, poll
}

func waits(t *testing.T, answered <-chan int, what string) {
	t.Helper()
	select {
	case status := <-answered:
		t.Fatalf("answered %d %s", status, what)
	case <-time.After(200 * time.Millisecond):
	}
}

func granted(t *testing.T, answered <-chan int, within time.Duration) {
	t.Helper()
	select {
	case status := <-answered:
		if status != http.StatusOK {
			t.Fatalf("answered %d", status)
		}
	case <-time.After(within):
		t.Fatalf("still waiting after %v", within)
	}
}

// sessionOf is the session a PUT carried, "" when it carried none.
func sessionOf(taken put) string {
	if values, sent := taken.header["X-Pilot-Session"]; sent {
		return strings.Join(values, ",")
	}
	return ""
}

func TestALockWaitsWhileAnotherSessionHoldsIt(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	waiting := running.locking(t, "proj", job)
	// Another project folder's lock is another lock.
	running.lock(t, "other", job, os.Getpid())
	waits(t, waiting, "while another session held the lock")

	running.release(t, "proj", chat)
	granted(t, waiting, time.Second)
}

func TestALockIsRefusedOnceAnotherSessionHeldItForTheWait(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())
	wait := 300 * time.Millisecond
	running.bound(wait, 20*time.Millisecond)

	running.lock(t, "proj", chat, os.Getpid())
	began := time.Now()
	status, _, text := running.call(t, "/lock", running.hook(t, "proj", job, pid(os.Getpid())))
	if status != http.StatusConflict || text != "another session is writing; try again\n" {
		t.Fatalf("answered %d %q", status, text)
	}
	if waited := time.Since(began); waited < wait || waited > wait+time.Second {
		t.Fatalf("answered after %v", waited)
	}
	// The refused session holds nothing: the holder's release frees the lock.
	running.release(t, "proj", chat)
	running.lock(t, "proj", chat, os.Getpid())
}

func TestALockWhoseHoldersProcessIsGoneIsBrokenByTheNextOneWaiting(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	sidecar, logged := newSidecar(t, s, tree, t.TempDir())
	run(t, sidecar)
	running := started{sidecar: sidecar, stream: s.accept(t)}
	running.bound(5*time.Second, 20*time.Millisecond)
	holder := exec.CommandContext(t.Context(), "sleep", "60")
	if err := holder.Start(); err != nil {
		t.Fatal(err)
	}

	running.lock(t, "proj", chat, holder.Process.Pid)
	waiting := running.locking(t, "proj", job)
	waits(t, waiting, "while the holder's process ran")
	if err := holder.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	_ = holder.Wait()

	granted(t, waiting, time.Second)
	if !strings.Contains(logged.String(), "a writer's process is gone") {
		t.Fatal("the broken lock not logged")
	}
}

func TestALockIsTakenAgainByItsHolderAndGoesWithItsLastHold(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	// A sub-agent's call of the holder's, while its first still writes.
	running.lock(t, "proj", chat, os.Getpid())
	waiting := running.locking(t, "proj", job)

	running.release(t, "proj", chat)
	waits(t, waiting, "while the holder held its second hold")
	running.release(t, "proj", chat)
	granted(t, waiting, time.Second)
}

func TestAReleaseOfAllGivesBackEveryHoldOfTheSession(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	running.lock(t, "proj", chat, os.Getpid())
	waiting := running.locking(t, "proj", job)
	// A release by a session that holds nothing gives back nothing.
	running.report(t, "proj")
	waits(t, waiting, "once a session holding nothing released")

	status, _, text := running.call(t, "/release", running.hook(t, "proj", chat, map[string]any{"all": true}))
	if status != http.StatusOK {
		t.Fatalf("answered %d %q", status, text)
	}
	granted(t, waiting, time.Second)
	if checks := s.checked(); len(checks) != 2 {
		t.Fatalf("posted %d checks", len(checks))
	}
}

func TestASaveWhileTheLockIsHeldIsTheHoldersAndNoneOtherwise(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "inbox", "1-a.md"), "one")
	write(t, filepath.Join(tree, "other", "inbox", "1-b.md"), "two")
	eventually(t, "both PUTs", func() bool { return len(s.taken()) == 2 })
	running.release(t, "proj", chat)
	write(t, filepath.Join(tree, "proj", "inbox", "1-a.md"), "three")
	eventually(t, "the third PUT", func() bool { return len(s.taken()) == 3 })
	settle()

	got := map[string]string{}
	for _, taken := range s.taken() {
		got[taken.body] = sessionOf(taken)
	}
	if want := map[string]string{"one": chat, "two": "", "three": ""}; !maps.Equal(got, want) {
		t.Fatalf("the PUTs carried %v, want %v", got, want)
	}
}

func TestAReleaseFlushesWhatIsOnDiskBeforeItsHoldGoes(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	// The release comes inside the watch's debounce: what it sends up, it
	// reads from disk.
	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "inbox", "1-a.md"), "written")
	write(t, filepath.Join(tree, "proj", "plan.json"), "{}")
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	puts := s.taken()
	if len(puts) != 2 {
		t.Fatalf("took %d PUTs by the release's answer", len(puts))
	}
	for _, taken := range puts {
		if sessionOf(taken) != chat {
			t.Errorf("%s: carried %q, not the holder's", taken.path, sessionOf(taken))
		}
	}
	checks := s.checked()
	if len(checks) != 1 || checks[0].Folder != "proj" || checks[0].WaitSeconds < 0 ||
		checks[0].WaitSeconds >= flushCap.Seconds() {
		t.Fatalf("posted %+v", checks)
	}
	settle()
	if puts := s.taken(); len(puts) != 2 {
		t.Fatalf("took %v: sent again after the release", puts[2:])
	}
}

func TestAReleaseWaitsForASaveOutAndItsAnswer(t *testing.T) {
	s := newServer(t)
	answered := make(chan struct{})
	s.answering(func(taken put) answer {
		if taken.body != "saved" {
			return answer{}
		}
		<-answered
		return answer{content: "merged"}
	})
	tree := t.TempDir()
	file := filepath.Join(tree, "proj", "plan.json")
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, file, "saved")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	go func() {
		time.Sleep(100 * time.Millisecond)
		close(answered)
	}()
	began := time.Now()
	if got := running.release(t, "proj", chat); got != "" {
		t.Fatalf("printed %q", got)
	}
	if waited := time.Since(began); waited >= flushCap {
		t.Fatalf("waited %v, the cap out", waited)
	}
	if !holds(file, "merged") {
		t.Fatalf("the file holds %q", read(t, file))
	}
	settle()
	if puts := s.taken(); len(puts) != 1 {
		t.Fatalf("took %d PUTs", len(puts))
	}
}

func TestAReleaseNamesWhatItsFlushCouldNotSend(t *testing.T) {
	s := newServer(t)
	stuck := make(chan struct{})
	defer close(stuck)
	s.answering(func(taken put) answer {
		switch taken.path {
		case "proj/a.md":
			<-stuck
		case "proj/b.md":
			return answer{status: http.StatusInternalServerError}
		}
		return answer{}
	})
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "a.md"), "saved")
	eventually(t, "the PUT", func() bool { return len(s.taken()) == 1 })
	write(t, filepath.Join(tree, "proj", "b.md"), "refused")
	write(t, filepath.Join(tree, "proj", "c.md"), "taken")
	began := time.Now()
	got := running.release(t, "proj", chat)
	waited := time.Since(began)

	if got != "not yet checked: proj/a.md\nnot yet checked: proj/b.md\n" {
		t.Fatalf("printed %q", got)
	}
	if waited < flushCap || waited > flushCap+time.Second {
		t.Fatalf("answered after %v", waited)
	}
	if checks := s.checked(); len(checks) != 1 || checks[0].WaitSeconds < flushCap.Seconds() {
		t.Fatalf("posted %+v", checks)
	}
	// The hold went with the release, whatever its flush came to.
	running.lock(t, "proj", job, os.Getpid())
}

func TestASaveItsReleaseCouldNotSendGoesUpAsTheReleasersUnderTheNextHolder(t *testing.T) {
	s := newServer(t)
	stuck := make(chan struct{})
	s.answering(func(taken put) answer {
		if strings.HasSuffix(taken.body, "first") {
			<-stuck
		}
		return answer{}
	})
	tree := t.TempDir()
	kept, rewritten := filepath.Join(tree, "proj", "a.md"), filepath.Join(tree, "proj", "c.md")
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, kept, "a first")
	write(t, rewritten, "c first")
	eventually(t, "both PUTs", func() bool { return len(s.taken()) == 2 })
	write(t, kept, "a second")
	write(t, rewritten, "c second")
	if got := running.release(t, "proj", chat); got != "not yet checked: proj/a.md\nnot yet checked: proj/c.md\n" {
		t.Fatalf("printed %q", got)
	}
	running.lock(t, "proj", job, os.Getpid())
	// Written over before its pass read it: the chat's bytes never go up.
	write(t, rewritten, "c third")
	close(stuck)
	eventually(t, "the late PUTs", func() bool { return len(s.taken()) == 4 })
	write(t, kept, "a third")
	if got := running.release(t, "proj", job); got != "" {
		t.Fatalf("printed %q", got)
	}
	settle()

	got := map[string]string{}
	for _, taken := range s.taken() {
		got[taken.body] = sessionOf(taken)
	}
	want := map[string]string{
		"a first": chat, "c first": chat, "a second": chat, "c third": job, "a third": job,
	}
	if !maps.Equal(got, want) {
		t.Fatalf("the PUTs carried %v, want %v", got, want)
	}
}

func TestAReleasePrintsTheErrorsThenItsFoldersNotesThenTheDeferrals(t *testing.T) {
	s := newServer(t)
	s.answering(func(taken put) answer {
		if taken.path == "proj/notes.md" || taken.path == "draft-2/zz.md" {
			return answer{status: http.StatusNotFound}
		}
		return answer{}
	})
	line := 31
	s.answeringChecks(func(check checkPost) protocol.CheckAnswer {
		if check.Folder != "proj" {
			return protocol.CheckAnswer{}
		}
		return protocol.CheckAnswer{
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
	write(t, filepath.Join(tree, "draft-2", "zz.md"), "another project's")
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "inbox", "4-b.md"), "edited")
	want := "proj/inbox/4-b.md:31: `answer:` is the record's, line 31 reverted\n" +
		"proj/plan.json: not JSON\n" +
		"proj/notes.md: " + strayNote + "\n" +
		homelessHeading + "\n" +
		"- P-4/d2 in proj/inbox/4-b.md (The importer), to: T-7\n" +
		"- P-5/d1 in proj/inbox/5-c.md (The export), to: plan\n"
	if got := running.release(t, "proj", chat); got != want {
		t.Fatalf("printed\n%s\nwant\n%s", got, want)
	}
	if got := running.report(t, "proj"); got != want {
		t.Fatalf("printed\n%s\nthe second time", got)
	}
	if got := running.report(t, "draft-2"); got != "draft-2/zz.md: "+strayNote+"\n" {
		t.Fatalf("printed %q for the other folder", got)
	}
	for i, check := range s.checked() {
		if want := []string{"proj", "proj", "draft-2"}[i]; check.Folder != want {
			t.Errorf("check %d: posted %+v, not %s's", i, check, want)
		}
	}
}

func TestAReleaseOfAStrayFilePrintsItsNoteAndLeavesIt(t *testing.T) {
	s := newServer(t)
	s.answering(func(put) answer { return answer{status: http.StatusNotFound} })
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	file := filepath.Join(tree, "proj", "notes.md")
	running.lock(t, "proj", chat, os.Getpid())
	write(t, file, "mine")
	if got := running.release(t, "proj", chat); got != "proj/notes.md: "+strayNote+"\n" {
		t.Fatalf("printed %q", got)
	}
	if !holds(file, "mine") {
		t.Fatal("a stray file was touched")
	}
}

func TestAReleaseTheServerCannotCheckSaysSo(t *testing.T) {
	s := newServer(t)
	s.refusingChecks(http.StatusInternalServerError)
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())

	running.lock(t, "proj", chat, os.Getpid())
	write(t, filepath.Join(tree, "proj", "inbox", "1-a.md"), "saved")
	if got := running.release(t, "proj", chat); got != "not yet checked: proj/\n" {
		t.Fatalf("printed %q", got)
	}
	running.lock(t, "proj", job, os.Getpid())
}

func TestAHookCallThatIsNotOneIs400AndTakesNothing(t *testing.T) {
	s := newServer(t)
	tree := t.TempDir()
	running := start(t, s, tree, t.TempDir())
	body := func(project string, fields map[string]any) string {
		call := map[string]any{"project": project, "session": chat, "pid": os.Getpid()}
		maps.Copy(call, fields)
		encoded, err := json.Marshal(call)
		if err != nil {
			t.Fatal(err)
		}
		return string(encoded)
	}
	project := filepath.Join(tree, "proj")
	both := []string{"/lock", "/release"}
	for _, bad := range []struct {
		routes []string
		body   string
	}{
		{both, "not JSON"},
		{both, body(project, map[string]any{"path": "a.md"})},
		{both, body("proj", nil)},
		{both, body(tree, nil)},
		{both, body(filepath.Join(project, "inbox"), nil)},
		{both, body(filepath.Join(filepath.Dir(tree), "elsewhere"), nil)},
		{both, body(tree+"/../elsewhere", nil)},
		{both, body(project, map[string]any{"session": ""})},
		{[]string{"/lock"}, body(project, map[string]any{"pid": 0})},
		{[]string{"/lock"}, body(project, map[string]any{"pid": noProcess})},
		{[]string{"/lock"}, body(project, map[string]any{"all": true})},
		{[]string{"/release"}, body(project, map[string]any{"pid": 0})},
		{[]string{"/release"}, body(project, map[string]any{"all": true})},
	} {
		for _, route := range bad.routes {
			if status, _, text := running.call(t, route, bad.body); status != http.StatusBadRequest {
				t.Errorf("%s %s: answered %d %q", route, bad.body, status, text)
			}
		}
	}
	if checks := s.checked(); len(checks) != 0 {
		t.Fatalf("posted %+v", checks)
	}
	running.lock(t, "proj", job, os.Getpid())
}

func TestHealthzAnswers(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())
	request, err := http.NewRequestWithContext(context.Background(), http.MethodGet,
		"http://"+running.sidecar.listener.Addr().String()+"/healthz", nil)
	if err != nil {
		t.Fatal(err)
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	var text bytes.Buffer
	_, err = text.ReadFrom(response.Body)
	if err := errors.Join(err, response.Body.Close()); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK || text.String() != "ok\n" {
		t.Fatalf("answered %d %q", response.StatusCode, text.String())
	}
}

func TestRefusesALocalPortInUse(t *testing.T) {
	s := newServer(t)
	running := start(t, s, t.TempDir(), t.TempDir())
	cfg := configure(s, t.TempDir(), t.TempDir())
	cfg.LocalPort = running.sidecar.listener.Addr().(*net.TCPAddr).Port
	_, err := New(cfg, slog.New(slog.NewTextHandler(t.Output(), nil)))
	if err == nil || !strings.Contains(err.Error(), "cannot serve the hooks' endpoint") {
		t.Fatalf("got %v", err)
	}
}
