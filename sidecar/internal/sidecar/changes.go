package sidecar

import (
	"context"
	"sync"
	"time"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

// coalesce is how long a path's change events are gathered before it is
// fetched: every save of a document also moves timeline.json (design 1
// §5.4).
const coalesce = 100 * time.Millisecond

// changes fetches and writes each path the change stream says moved, once
// its events have been gathered for coalesce, unless the hash it moved to is
// the one it last synced: the sidecar's own write echoed back.
type changes struct {
	tree *tree
	ctx  context.Context
	wg   sync.WaitGroup

	mu     sync.Mutex
	moves  map[string]string
	timers map[string]*time.Timer
	closed bool
}

func newChanges(ctx context.Context, t *tree) *changes {
	return &changes{tree: t, ctx: ctx, moves: map[string]string{}, timers: map[string]*time.Timer{}}
}

// moved is told change came on the stream.
func (c *changes) moved(change protocol.Change) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return
	}
	_, gathering := c.moves[change.Path]
	c.moves[change.Path] = change.Hash
	if gathering {
		return
	}
	c.wg.Add(1)
	c.timers[change.Path] = time.AfterFunc(coalesce, func() { c.fetch(change.Path) })
}

func (c *changes) fetch(path string) {
	defer c.wg.Done()
	c.mu.Lock()
	hash := c.moves[path]
	delete(c.moves, path)
	delete(c.timers, path)
	c.mu.Unlock()
	release, ok := c.tree.hold(c.ctx, path)
	if !ok {
		return
	}
	defer release()
	if synced, _ := c.tree.shadow.Hash(path); synced == hash {
		return
	}
	c.tree.download(c.ctx, path)
}

// close fetches nothing more and waits for the fetches out, which end
// promptly once ctx is done.
func (c *changes) close() {
	c.mu.Lock()
	c.closed = true
	for path, timer := range c.timers {
		if timer.Stop() {
			delete(c.moves, path)
			delete(c.timers, path)
			c.wg.Done()
		}
	}
	c.mu.Unlock()
	c.wg.Wait()
}
