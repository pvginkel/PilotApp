package sidecar

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// checkCap bounds how long a check waits for the file's hash to be acked
// (design 1 §5.6); the hook's own cap on the call is 3 s.
const checkCap = 2 * time.Second

// homelessHeading is the heading the hook prints the deferrals without a
// home under (design 1 §5.6 step 4).
const homelessHeading = "Deferrals without a home (no plan note names these blocks):"

// local is the sidecar's own endpoint on localhost, for the hook: GET
// /check?path=<absolute path> and GET /healthz. Every request's context is
// ctx's, so it ends with the sidecar.
func (s *Sidecar) local(ctx context.Context) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /check", s.check)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		text(w, http.StatusOK, "ok\n")
	})
	return &http.Server{Handler: mux, BaseContext: func(net.Listener) context.Context { return ctx }}
}

// check answers the hook's check of the file the query's path names (design
// 1 §5.6): once the file's hash on disk is acked, at most checkCap after the
// call, the server's check of that hash, as the hook prints it; past the
// cap, that it is not yet checked.
func (s *Sidecar) check(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	name := r.URL.Query().Get("path")
	path, ok := s.tree.path(name)
	if !ok {
		text(w, http.StatusBadRequest, fmt.Sprintf("not a file of the tree %s: %q\n", s.tree.root, name))
		return
	}
	hash, err := s.acked(r.Context(), path, started)
	if errors.Is(err, fs.ErrNotExist) {
		text(w, http.StatusNotFound, fmt.Sprintf("no file at %s\n", name))
		return
	}
	if err != nil {
		s.logger.Error("cannot check a file of the tree", "path", path, "error", err)
		text(w, http.StatusInternalServerError, err.Error()+"\n")
		return
	}
	if r.Context().Err() != nil {
		return
	}
	waited := time.Since(started)
	if hash == "" {
		s.logger.Info("not yet checked", "path", path, "waited", waited)
		text(w, http.StatusOK, "not yet checked: "+path+"\n")
		return
	}
	answer, err := s.tree.client.Check(r.Context(), path, hash, waited)
	if r.Context().Err() != nil {
		return
	}
	if err != nil {
		s.logger.Error("cannot check a file of the tree", "path", path, "error", err)
		text(w, http.StatusOK, "not yet checked: "+path+"\n")
		return
	}
	s.logger.Info("checked", "path", path, "hash", hash, "waited", waited, "agreed", answer.Checked,
		"errors", len(answer.Errors), "homeless_deferrals", len(answer.HomelessDeferrals))
	text(w, http.StatusOK, render(answer, s.tree.notes.print()))
}

// acked waits, until checkCap after started, for the file of path as it is
// on disk to be acked, and answers the hash it is checked with: the file's
// own when the shadow holds it, or else what the first pass of its upload to
// read it after the call came to (uploads.upload); "" when the cap or ctx
// ended first, or the pass came to nothing.
func (s *Sidecar) acked(ctx context.Context, path string, started time.Time) (string, error) {
	content, err := os.ReadFile(s.tree.name(path))
	if err != nil {
		return "", err
	}
	hash := protocol.Hash(content)
	if synced, _ := s.tree.shadow.Hash(path); synced == hash {
		return hash, nil
	}
	timer := time.NewTimer(checkCap - time.Since(started))
	defer timer.Stop()
	select {
	case settled := <-s.uploads.settle(path):
		return settled, nil
	case <-timer.C:
		return "", nil
	case <-ctx.Done():
		return "", nil
	}
}

// render is the hook's text of answer and the local notes, each line ended
// by a newline: each error `<path>:<line>: <message>`, or `<path>: <message>`
// with no line, in the answer's order; then the notes; then the deferrals
// without a home under their heading, each `- <block> in <document>
// (<title>), to: <to>`. Nothing at all is empty.
func render(answer protocol.CheckAnswer, notes []string) string {
	var lines strings.Builder
	for _, saveError := range answer.Errors {
		if saveError.Line == nil {
			fmt.Fprintf(&lines, "%s: %s\n", saveError.Path, saveError.Message)
		} else {
			fmt.Fprintf(&lines, "%s:%d: %s\n", saveError.Path, *saveError.Line, saveError.Message)
		}
	}
	for _, note := range notes {
		lines.WriteString(note + "\n")
	}
	if len(answer.HomelessDeferrals) > 0 {
		lines.WriteString(homelessHeading + "\n")
		for _, deferral := range answer.HomelessDeferrals {
			fmt.Fprintf(&lines, "- %s in %s (%s), to: %s\n", deferral.Block, deferral.Document, deferral.Title, deferral.To)
		}
	}
	return lines.String()
}

func text(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}
