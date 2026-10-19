// Package watch reports the files of a tree that changed, each once its
// events have been quiet for the debounce. fsnotify has no CLOSE_WRITE, so the
// quiet after Write, Create and Rename is what tells a file written whole
// from one still being written (design 1 §14).
package watch

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"

	"github.com/pvginkel/PilotApp/sidecar/internal/files"
)

// Debounce is how long a file's events must be quiet before its change is
// reported (design 1 §5.6: at most 50 ms of the hook's budget).
const Debounce = 50 * time.Millisecond

// Watcher watches every directory of a tree, those made after it started
// included.
type Watcher struct {
	root    string
	delay   time.Duration
	changed func(path string)
	logger  *slog.Logger
	notify  *fsnotify.Watcher

	mu     sync.Mutex
	timers map[string]*time.Timer
}

// New watches every directory of the tree at root, an absolute path. Once
// Run runs, a file's change is reported to changed by its path from root,
// with forward slashes, after delay with no further event on it. A file in a
// directory made later is reported; one already in the tree is not.
func New(root string, delay time.Duration, changed func(path string), logger *slog.Logger) (*Watcher, error) {
	notify, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, fmt.Errorf("watch %s: %w", root, err)
	}
	w := &Watcher{
		root:    root,
		delay:   delay,
		changed: changed,
		logger:  logger,
		notify:  notify,
		timers:  map[string]*time.Timer{},
	}
	if err := w.add(root, false); err != nil {
		return nil, errors.Join(fmt.Errorf("watch %s: %w", root, err), notify.Close())
	}
	return w, nil
}

// Run reports changes until ctx is done, then stops watching; a change not
// yet reported then is dropped.
func (w *Watcher) Run(ctx context.Context) (err error) {
	defer func() { err = errors.Join(err, w.stop()) }()
	for {
		select {
		case <-ctx.Done():
			return nil
		case event, ok := <-w.notify.Events:
			if !ok {
				return errors.New("the watch ended")
			}
			w.event(event)
		case err, ok := <-w.notify.Errors:
			if !ok {
				return errors.New("the watch ended")
			}
			w.logger.Error("the watch reported an error", "error", err)
		}
	}
}

func (w *Watcher) event(event fsnotify.Event) {
	if files.IsTemp(filepath.Base(event.Name)) {
		return
	}
	if event.Has(fsnotify.Create) {
		if info, err := os.Lstat(event.Name); err == nil && info.IsDir() {
			if err := w.add(event.Name, true); err != nil {
				w.logger.Error("cannot watch a new directory", "dir", event.Name, "error", err)
			}
			return
		}
	}
	if event.Has(fsnotify.Create) || event.Has(fsnotify.Write) || event.Has(fsnotify.Rename) {
		w.touch(event.Name)
	}
}

// add watches dir and every directory under it, reporting each file in them
// when report is set. A directory is watched before it is read, so a file made
// in it meanwhile is in the listing or in an event.
func (w *Watcher) add(dir string, report bool) error {
	return filepath.WalkDir(dir, func(name string, entry fs.DirEntry, err error) error {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		switch {
		case entry.IsDir():
			if err := w.notify.Add(name); err != nil && !errors.Is(err, fs.ErrNotExist) {
				return err
			}
		case report && entry.Type().IsRegular() && !files.IsTemp(entry.Name()):
			w.touch(name)
		}
		return nil
	})
}

// touch (re)starts the debounce of the file at name.
func (w *Watcher) touch(name string) {
	path := filepath.ToSlash(strings.TrimPrefix(strings.TrimPrefix(name, w.root), string(filepath.Separator)))
	w.mu.Lock()
	defer w.mu.Unlock()
	if timer, ok := w.timers[path]; ok {
		timer.Stop()
	}
	var timer *time.Timer
	timer = time.AfterFunc(w.delay, func() {
		w.mu.Lock()
		current := w.timers[path] == timer
		if current {
			delete(w.timers, path)
		}
		w.mu.Unlock()
		if current {
			w.changed(path)
		}
	})
	w.timers[path] = timer
}

func (w *Watcher) stop() error {
	w.mu.Lock()
	for path, timer := range w.timers {
		timer.Stop()
		delete(w.timers, path)
	}
	w.mu.Unlock()
	return w.notify.Close()
}
