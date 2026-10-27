package sidecar

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// fakeProc is a /proc holding the processes the test runs.
type fakeProc string

// run has pid run in state, since started.
func (p fakeProc) run(t *testing.T, pid int, state, started string) {
	t.Helper()
	// The fields of proc(5)'s stat: the pid, the command, the state, the
	// eighteen from the parent to the timer, the start time, the 22nd, and
	// two of those after it.
	stat := fmt.Sprintf("%d (claude (main) x) %s %s%s 4096 0\n", pid, state, strings.Repeat("0 ", 18), started)
	write(t, filepath.Join(string(p), strconv.Itoa(pid), "stat"), stat)
}

// end has pid exit, reaped.
func (p fakeProc) end(t *testing.T, pid int) {
	t.Helper()
	if err := os.RemoveAll(filepath.Join(string(p), strconv.Itoa(pid))); err != nil {
		t.Fatal(err)
	}
}

func newLocks(t *testing.T) (*writeLocks, fakeProc) {
	t.Helper()
	proc := fakeProc(t.TempDir())
	return newWriteLocks(string(proc), slog.New(slog.NewTextHandler(t.Output(), nil))), proc
}

func take(t *testing.T, locks *writeLocks, folder, session string, pid int) {
	t.Helper()
	if err := locks.take(context.Background(), folder, session, pid); err != nil {
		t.Fatalf("%s by %d: %v", session, pid, err)
	}
}

func TestStartedIsTheStartTimeOfARunningProcess(t *testing.T) {
	locks, proc := newLocks(t)
	proc.run(t, 10, "S", "8841")
	proc.run(t, 11, "T", "8842")
	proc.run(t, 12, "Z", "8843")
	proc.run(t, 13, "X", "8844")

	for pid, want := range map[int]string{10: "8841", 11: "8842"} {
		if started, ok := locks.started(pid); !ok || started != want {
			t.Errorf("%d: got %q, %v", pid, started, ok)
		}
	}
	for _, pid := range []int{12, 13, 14, 0, -1} {
		if started, ok := locks.started(pid); ok {
			t.Errorf("%d: started %q, not a running process", pid, started)
		}
	}
	real := newWriteLocks("/proc", locks.logger)
	if _, ok := real.started(os.Getpid()); !ok {
		t.Fatal("this process is not running")
	}
}

func TestATakeWaitsForTheLockToGoThenTakesIt(t *testing.T) {
	locks, proc := newLocks(t)
	proc.run(t, 10, "S", "1")
	proc.run(t, 20, "S", "2")
	take(t, locks, "proj", chat, 10)

	taken := make(chan error, 1)
	go func() { taken <- locks.take(context.Background(), "proj", job, 20) }()
	select {
	case err := <-taken:
		t.Fatalf("took the lock another session held: %v", err)
	case <-time.After(100 * time.Millisecond):
	}
	locks.release("proj", chat, 10)
	select {
	case err := <-taken:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("still waiting once the lock went")
	}
	if got := locks.holder("proj"); got != job {
		t.Fatalf("held by %q", got)
	}
}

func TestATakeEndsWithItsContext(t *testing.T) {
	locks, proc := newLocks(t)
	proc.run(t, 10, "S", "1")
	take(t, locks, "proj", chat, 10)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	if err := locks.take(ctx, "proj", job, 10); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("got %v", err)
	}
	if got := locks.holder("proj"); got != chat {
		t.Fatalf("held by %q", got)
	}
}

func TestAProcessGoneOrItsPidReusedHoldsNothing(t *testing.T) {
	for name, gone := range map[string]func(fakeProc, *testing.T){
		"exited": func(p fakeProc, t *testing.T) { p.end(t, 10) },
		"zombie": func(p fakeProc, t *testing.T) { p.run(t, 10, "Z", "1") },
		"reused": func(p fakeProc, t *testing.T) { p.run(t, 10, "S", "7") },
	} {
		t.Run(name, func(t *testing.T) {
			locks, proc := newLocks(t)
			proc.run(t, 10, "S", "1")
			take(t, locks, "proj", chat, 10)
			gone(proc, t)
			if got := locks.holder("proj"); got != "" {
				t.Fatalf("held by %q", got)
			}
			proc.run(t, 20, "S", "2")
			take(t, locks, "proj", job, 20)
		})
	}
}

func TestAGoneProcessesHoldsGoAndTheSessionsOthersStay(t *testing.T) {
	locks, proc := newLocks(t)
	proc.run(t, 10, "S", "1")
	proc.run(t, 11, "S", "1")
	take(t, locks, "proj", chat, 10)
	take(t, locks, "proj", chat, 11)

	proc.end(t, 10)
	if got := locks.holder("proj"); got != chat {
		t.Fatalf("held by %q", got)
	}
	locks.release("proj", chat, 11)
	if got := locks.holder("proj"); got != "" {
		t.Fatalf("held by %q", got)
	}
}

func TestAReleaseGivesBackOnlyAHoldOfItsSessionAndPid(t *testing.T) {
	locks, proc := newLocks(t)
	proc.run(t, 10, "S", "1")
	take(t, locks, "proj", chat, 10)
	take(t, locks, "proj", chat, 10)

	locks.release("proj", job, 10)
	locks.release("proj", chat, 11)
	locks.release("other", chat, 10)
	locks.releaseAll("proj", job)
	locks.release("proj", chat, 10)
	if got := locks.holder("proj"); got != chat {
		t.Fatalf("held by %q with a hold left", got)
	}
	locks.release("proj", chat, 10)
	if got := locks.holder("proj"); got != "" {
		t.Fatalf("held by %q", got)
	}
}

func TestBytesLeftUnsentStayTheirFirstSessionsUntilTheyGoUpOrAreGone(t *testing.T) {
	left := &unsent{byPath: map[string]unsentSave{}}
	writer := func(path, hash string) string {
		t.Helper()
		session, ok := left.writer(path, hash)
		if !ok {
			return "none"
		}
		return session
	}

	// Left again by the next holder's release, they stay the chat's.
	left.leave("proj/a.md", "h1", "chat")
	left.leave("proj/a.md", "h1", "job")
	if got := writer("proj/a.md", "h1"); got != "chat" {
		t.Fatalf("h1 is %s's", got)
	}
	// Read as other bytes, they are gone from disk, and forgotten.
	if got := writer("proj/a.md", "h2"); got != "none" {
		t.Fatalf("h2 is %s's", got)
	}
	if got := writer("proj/a.md", "h1"); got != "none" {
		t.Fatalf("h1, written again, is %s's", got)
	}

	left.leave("proj/b.md", "h1", "")
	left.sent("proj/b.md", "h2")
	if got := writer("proj/b.md", "h1"); got != "" {
		t.Fatalf("b's h1 is %s's, after other bytes went up", got)
	}
	left.sent("proj/b.md", "h1")
	if got := writer("proj/b.md", "h1"); got != "none" {
		t.Fatalf("b's h1 is %s's, once it went up", got)
	}

	left.leave("proj/c.md", "h1", "chat")
	left.forget("proj/c.md")
	if got := writer("proj/c.md", "h1"); got != "none" {
		t.Fatalf("c's h1 is %s's, once c was gone", got)
	}
}
