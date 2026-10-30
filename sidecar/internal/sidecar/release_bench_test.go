package sidecar

import (
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

// The hooks' benchmarks run on a project folder of the size a project
// reaches: benchDocuments documents and benchAttachments attachments, read-only
// views each of the record's largest, 16 MiB, all in sync. Each writing tool
// call of a brain session is one lock and one release:
//
//	go test -run '^$' -bench . ./internal/sidecar
const (
	benchDocuments       = 200
	benchDocumentBytes   = 4 << 10
	benchAttachments     = 4
	benchAttachmentBytes = 16 << 20
)

// inSync is a sidecar running against s, its tree's project folder proj
// written down from the record and in sync, logging nothing.
func inSync(b *testing.B) started {
	b.Helper()
	s := newServer(b)
	var paths []string
	for i := range benchDocuments {
		path := fmt.Sprintf("proj/items/%d-document.md", i+1)
		s.record(path, strings.Repeat(fmt.Sprintf("document %d\n", i+1), benchDocumentBytes/12))
		paths = append(paths, path)
	}
	for i := range benchAttachments {
		path := fmt.Sprintf("proj/attachments/%d-attachment.bin", i+1)
		s.view(path, strings.Repeat(fmt.Sprintf("attachment %d\n", i+1), benchAttachmentBytes/14))
		paths = append(paths, path)
	}
	sidecar, err := New(configure(s, b.TempDir(), b.TempDir()), slog.New(slog.DiscardHandler))
	if err != nil {
		b.Fatal(err)
	}
	stop := run(b, sidecar)
	opened := s.accept(b)
	running := started{sidecar: sidecar, stop: stop, stream: opened}
	eventually(b, "the folder written down", func() bool {
		for _, path := range paths {
			if running.synced(path) == "" {
				return false
			}
		}
		return true
	})
	// A file changed within the window is read at every walk: past it, as
	// a folder is between a session's tool calls that leave it as it is.
	time.Sleep(racyWindow + 100*time.Millisecond)
	return running
}

// BenchmarkLock is a hook's lock of a folder no session holds, its hold
// given back between calls.
func BenchmarkLock(b *testing.B) {
	running := inSync(b)
	body := running.hook(b, "proj", chat, pid(os.Getpid()))
	for b.Loop() {
		if status, _, text := running.call(b, "/lock", body); status != http.StatusOK {
			b.Fatalf("lock answered %d %q", status, text)
		}
		running.sidecar.tree.writers.release("proj", chat, os.Getpid())
	}
}

// BenchmarkRelease is a hook's release of the folder after a tool call that
// wrote nothing: its flush, which finds every file in sync, and its check.
func BenchmarkRelease(b *testing.B) {
	running := inSync(b)
	for b.Loop() {
		if text := running.report(b, "proj"); text != "" {
			b.Fatalf("printed %q", text)
		}
	}
}
