package sidecar

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"maps"
	"net"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// The release's bounds: its flush waits at most flushCap for the folder's
// files to go up, and its check at most checkCap for the server's answer.
// The hook's own cap on the call is above the two together.
const (
	flushCap = 5 * time.Second
	checkCap = 5 * time.Second
)

// homelessHeading is the heading the hook prints the deferrals without a
// home under (design 1 §5.6 step 4).
const homelessHeading = "Deferrals without a home (no plan note names these blocks):"

// local is the sidecar's own endpoint on localhost, for the store's hooks:
// POST /lock, POST /release and GET /healthz. Every request's context is
// ctx's, so it ends with the sidecar.
func (s *Sidecar) local(ctx context.Context) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /lock", s.lock)
	mux.HandleFunc("POST /release", s.release)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		text(w, http.StatusOK, "ok\n")
	})
	return &http.Server{Handler: mux, BaseContext: func(net.Listener) context.Context { return ctx }}
}

// hookCall is the body of a hook's /lock and /release, JSON.
type hookCall struct {
	// Project is the project's folder, absolute: the session's
	// PILOT_PROJECT.
	Project string `json:"project"`
	// Session is the brain session's Session: its PILOT_SESSION.
	Session string `json:"session"`
	// Pid is the session's Claude process, which takes and gives back a
	// hold.
	Pid int `json:"pid"`
	// All, on a release instead of a pid, gives back every hold the
	// session has: its turn's end.
	All bool `json:"all"`
}

// lock takes a hold of the write lock of the call's project folder for its
// session, before a tool call that can write the tree: 200 once it is held;
// 409 with "another session is writing; try again" once another session
// held it for the wait; 400 for a call that is not a lock.
func (s *Sidecar) lock(w http.ResponseWriter, r *http.Request) {
	call, folder, ok := s.hookCall(w, r)
	if !ok {
		return
	}
	if call.All || call.Pid <= 0 {
		text(w, http.StatusBadRequest, "a lock names the pid that holds it\n")
		return
	}
	began := time.Now()
	err := s.tree.writers.take(r.Context(), folder, call.Session, call.Pid)
	switch {
	case errors.Is(err, errBusy):
		s.logger.Info("not locked: another session is writing", "folder", folder, "session", call.Session,
			"pid", call.Pid, "waited", time.Since(began))
		text(w, http.StatusConflict, err.Error()+"\n")
		return
	case errors.Is(err, errNoProcess):
		text(w, http.StatusBadRequest, fmt.Sprintf("no running process %d\n", call.Pid))
		return
	case err != nil:
		return
	}
	if r.Context().Err() != nil {
		// The hook is gone: no tool call runs on this hold.
		s.tree.writers.release(folder, call.Session, call.Pid)
		return
	}
	s.logger.Info("locked", "folder", folder, "session", call.Session, "pid", call.Pid, "waited", time.Since(began))
	text(w, http.StatusOK, "")
}

// release is the check after a tool call that can write the tree (design 1
// §5.6): every file of the call's project folder whose bytes are not those
// it last synced goes up as the save of the session holding the lock (flush);
// the server's check of the folder is asked; and then the hold is given
// back, the pid's one or, with all, every one the session has. It answers
// 200 with what the hook prints, whatever the session held. With the query
// check=false it asks no check and prints no note, so that the resets and
// the notes printed once stay for the next release that reads them, and it
// answers empty: the release of a stop whose answer reaches no agent.
func (s *Sidecar) release(w http.ResponseWriter, r *http.Request) {
	call, folder, ok := s.hookCall(w, r)
	if !ok {
		return
	}
	if call.All == (call.Pid > 0) {
		text(w, http.StatusBadRequest, "a release names the pid whose hold it gives back, or all\n")
		return
	}
	checking := r.URL.Query().Get("check") != "false"
	began := time.Now()
	unchecked := s.flush(r.Context(), folder)
	waited := time.Since(began)
	var answer protocol.CheckAnswer
	var err error
	if checking {
		answer, err = s.check(r.Context(), folder, waited)
	}
	if call.All {
		s.tree.writers.releaseAll(folder, call.Session)
	} else {
		s.tree.writers.release(folder, call.Session, call.Pid)
	}
	if r.Context().Err() != nil {
		return
	}
	if !checking {
		s.logger.Info("released unchecked", "folder", folder, "session", call.Session, "waited", waited,
			"unflushed", len(unchecked))
		text(w, http.StatusOK, "")
		return
	}
	if err != nil {
		s.logger.Error("cannot check a project folder", "folder", folder, "error", err)
		unchecked = append(unchecked, folder+"/")
	} else {
		s.logger.Info("checked", "folder", folder, "session", call.Session, "waited", waited,
			"errors", len(answer.Errors), "homeless_deferrals", len(answer.HomelessDeferrals), "unflushed", len(unchecked))
	}
	text(w, http.StatusOK, render(answer, s.tree.notes.print(folder), unchecked))
}

// hookCall reads a hook's call and the project folder it names, from the
// tree's root; false once it has answered 400.
func (s *Sidecar) hookCall(w http.ResponseWriter, r *http.Request) (hookCall, string, bool) {
	var call hookCall
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&call); err != nil {
		text(w, http.StatusBadRequest, fmt.Sprintf("not a hook's call: %v\n", err))
		return hookCall{}, "", false
	}
	folder, ok := s.tree.path(call.Project)
	if !ok || strings.Contains(folder, "/") {
		text(w, http.StatusBadRequest, fmt.Sprintf("not a project folder of the tree %s: %q\n", s.tree.root, call.Project))
		return hookCall{}, "", false
	}
	if call.Session == "" {
		text(w, http.StatusBadRequest, "a hook's call names its session\n")
		return hookCall{}, "", false
	}
	return call, folder, true
}

// flush sends up every file of folder whose bytes are not those it last
// synced, but a stray file still holding the bytes the server refused, and
// waits, until flushCap after the call or ctx's end, for each to be read
// after the call and sent, or found in sync. Those that were not by then, or
// whose send came to nothing, it leaves unsent as the saves of the session
// that held the lock as it read them, and answers in path order.
func (s *Sidecar) flush(ctx context.Context, folder string) []string {
	disk, err := s.tree.walk(folder)
	if err != nil {
		s.logger.Error("cannot walk a project folder", "folder", folder, "error", err)
		return []string{folder + "/"}
	}
	holder := s.tree.writers.holder(folder)
	settling := map[string]<-chan string{}
	for path, hash := range disk {
		if synced, _ := s.tree.shadow.Hash(path); synced != hash && !s.tree.notes.refused(path, hash) {
			settling[path] = s.uploads.settle(path)
		}
	}
	timer := time.NewTimer(flushCap)
	defer timer.Stop()
	expired := false
	left := map[string]string{}
	for _, path := range slices.Sorted(maps.Keys(settling)) {
		var hash string
		var settled bool
		if expired {
			select {
			case hash = <-settling[path]:
				settled = true
			default:
			}
		} else {
			select {
			case hash = <-settling[path]:
				settled = true
			case <-timer.C:
				expired = true
			case <-ctx.Done():
				expired = true
			}
		}
		if !settled || hash == "" {
			left[path] = disk[path]
		}
	}
	s.tree.leave(left, holder)
	return slices.Sorted(maps.Keys(left))
}

// check is the server's check of folder, at most checkCap.
func (s *Sidecar) check(ctx context.Context, folder string, waited time.Duration) (protocol.CheckAnswer, error) {
	ctx, cancel := context.WithTimeout(ctx, checkCap)
	defer cancel()
	return s.tree.client.Check(ctx, folder, waited)
}

// render is the hook's text of answer, the local notes and the paths not
// yet checked, each line ended by a newline: each error `<path>:<line>:
// <message>`, or `<path>: <message>` with no line, in the answer's order;
// then the notes; then each path not yet checked, `not yet checked:
// <path>`; then the deferrals without a home under their heading, each `-
// <block> in <document> (<title>), to: <to>`. Nothing at all is empty.
func render(answer protocol.CheckAnswer, notes, unchecked []string) string {
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
	for _, path := range unchecked {
		lines.WriteString("not yet checked: " + path + "\n")
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
