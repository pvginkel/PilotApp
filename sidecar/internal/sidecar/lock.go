package sidecar

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// The write lock's bounds: a session waits at most lockWait for the lock
// another holds, looking every lockPoll whether that one's process is gone.
const (
	lockWait = 60 * time.Second
	lockPoll = time.Second
)

// errBusy refuses a lock another session held past the wait.
var errBusy = errors.New("another session is writing; try again")

// errNoProcess refuses a lock for a process that is not running.
var errNoProcess = errors.New("no such process")

// writeLocks holds the write lock of each project folder: the brain session
// that holds it, for the length of each of its tool calls that can write
// the tree, and every save of the folder while it is held is that
// session's. A session takes it again while it holds it, its sub-agents'
// calls included; it goes once the session's last hold is released, or
// once every process holding it is gone.
type writeLocks struct {
	// proc is where each holder's process is looked up: /proc/<pid>/stat.
	proc   string
	logger *slog.Logger

	mu       sync.Mutex
	wait     time.Duration
	poll     time.Duration
	byFolder map[string]*writeLock
	// freed is closed, and replaced, whenever a lock goes.
	freed chan struct{}
}

// writeLock is a folder's lock: the session holding it, and its holds by
// the pid of the process that took them.
type writeLock struct {
	session string
	holds   map[int]*processHolds
}

// processHolds is one process's holds of a lock: how many, and the start
// time the process had when it took the first, so that a pid the kernel
// gave another process since holds nothing.
type processHolds struct {
	started string
	count   int
}

func newWriteLocks(proc string, logger *slog.Logger) *writeLocks {
	return &writeLocks{
		proc: proc, logger: logger, wait: lockWait, poll: lockPoll,
		byFolder: map[string]*writeLock{}, freed: make(chan struct{}),
	}
}

// take gives session, through its process pid, a hold of folder's lock,
// once no other session holds it: errBusy after the wait, errNoProcess
// for a pid of no running process, or ctx's error when it ends first.
func (l *writeLocks) take(ctx context.Context, folder, session string, pid int) error {
	started, ok := l.started(pid)
	if !ok {
		return errNoProcess
	}
	l.mu.Lock()
	timer := time.NewTimer(l.wait)
	ticker := time.NewTicker(l.poll)
	l.mu.Unlock()
	defer timer.Stop()
	defer ticker.Stop()
	for {
		l.mu.Lock()
		lock := l.live(folder)
		if lock == nil || lock.session == session {
			if lock == nil {
				lock = &writeLock{session: session, holds: map[int]*processHolds{}}
				l.byFolder[folder] = lock
			}
			held := lock.holds[pid]
			if held == nil {
				held = &processHolds{started: started}
				lock.holds[pid] = held
			}
			held.count++
			l.mu.Unlock()
			return nil
		}
		freed := l.freed
		l.mu.Unlock()
		select {
		case <-freed:
		case <-ticker.C:
		case <-timer.C:
			return errBusy
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// release gives back one hold of folder's lock that session took through
// pid; a hold it does not have is nothing to give back.
func (l *writeLocks) release(folder, session string, pid int) {
	l.mu.Lock()
	defer l.mu.Unlock()
	lock := l.byFolder[folder]
	if lock == nil || lock.session != session || lock.holds[pid] == nil {
		return
	}
	lock.holds[pid].count--
	if lock.holds[pid].count == 0 {
		delete(lock.holds, pid)
	}
	if len(lock.holds) == 0 {
		l.free(folder)
	}
}

// releaseAll gives back every hold of folder's lock that session has.
func (l *writeLocks) releaseAll(folder, session string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if lock := l.byFolder[folder]; lock != nil && lock.session == session {
		l.free(folder)
	}
}

// holder is the session holding folder's lock, "" when none does.
func (l *writeLocks) holder(folder string) string {
	l.mu.Lock()
	defer l.mu.Unlock()
	if lock := l.live(folder); lock != nil {
		return lock.session
	}
	return ""
}

// live is folder's lock once the holds of every process gone are dropped,
// nil when none is left. The caller holds mu.
func (l *writeLocks) live(folder string) *writeLock {
	lock := l.byFolder[folder]
	if lock == nil {
		return nil
	}
	for pid, held := range lock.holds {
		if started, ok := l.started(pid); !ok || started != held.started {
			l.logger.Warn("a writer's process is gone: its holds of the lock dropped",
				"folder", folder, "session", lock.session, "pid", pid, "holds", held.count)
			delete(lock.holds, pid)
		}
	}
	if len(lock.holds) == 0 {
		l.free(folder)
		return nil
	}
	return lock
}

// free lets folder's lock go and wakes every session waiting for a lock.
// The caller holds mu.
func (l *writeLocks) free(folder string) {
	delete(l.byFolder, folder)
	close(l.freed)
	l.freed = make(chan struct{})
}

// started is the start time of the running process pid, the 22nd field of
// its stat (proc(5)); false when there is none, or it has exited and not
// been reaped.
func (l *writeLocks) started(pid int) (string, bool) {
	if pid <= 0 {
		return "", false
	}
	stat, err := os.ReadFile(filepath.Join(l.proc, strconv.Itoa(pid), "stat"))
	if err != nil {
		return "", false
	}
	// The command, the second field, is in parentheses and may hold spaces
	// and parentheses itself; the fields after its last `)` are plain.
	end := bytes.LastIndexByte(stat, ')')
	if end < 0 {
		return "", false
	}
	fields := strings.Fields(string(stat[end+1:]))
	if len(fields) < 20 || fields[0] == "Z" || fields[0] == "X" {
		return "", false
	}
	return fields[19], true
}
