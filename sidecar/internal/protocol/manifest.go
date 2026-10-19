package protocol

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
)

// Entry is a path of the manifest: its tree hash, what the file must hold,
// and whether it is a read-only view.
type Entry struct {
	Path     string `json:"path"`
	Hash     string `json:"hash"`
	Readonly bool   `json:"readonly"`
}

// Reconciled is the manifest reconcile's answer, each list in path order.
type Reconciled struct {
	// Manifest is every path the store syncs.
	Manifest []Entry `json:"manifest"`
	// SendUp is every path of the manifest changed on disk since it synced:
	// the server's cross-check, never acted on.
	SendUp []string `json:"send_up"`
	// WriteDown is every path of the manifest the file on disk does not
	// hold, each fetched by Get, its hash as the reconcile saw it.
	WriteDown []Entry `json:"write_down"`
	// Delete is every path synced that the manifest no longer lists.
	Delete []string `json:"delete"`
}

// Manifest posts the tree's hashes as they stand on disk and as they last
// synced, each by path: POST /api/sync/manifest (design 1 §5.5 step 2).
func (c *Client) Manifest(ctx context.Context, tree, shadow map[string]string) (Reconciled, error) {
	// A nil map is JSON's null, which the server refuses: both are objects.
	body, err := json.Marshal(map[string]map[string]string{"tree": orEmpty(tree), "shadow": orEmpty(shadow)})
	if err != nil {
		return Reconciled{}, fmt.Errorf("POST the manifest: %w", err)
	}
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/sync/manifest", bytes.NewReader(body))
	if err != nil {
		return Reconciled{}, fmt.Errorf("POST the manifest: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	answer, err := c.do(request)
	if err != nil {
		return Reconciled{}, fmt.Errorf("POST the manifest: %w", err)
	}
	var reconciled Reconciled
	if err := json.Unmarshal(answer.body, &reconciled); err != nil {
		return Reconciled{}, fmt.Errorf("POST the manifest: answered %q: %w", answer.body, err)
	}
	if err := reconciled.check(); err != nil {
		return Reconciled{}, fmt.Errorf("POST the manifest: %w", err)
	}
	return reconciled, nil
}

// check refuses an answer that names a path outside the tree or a hash the
// protocol does not speak.
func (r Reconciled) check() error {
	for _, entries := range [][]Entry{r.Manifest, r.WriteDown} {
		for _, entry := range entries {
			if !ValidPath(entry.Path) || !validHash(entry.Hash) {
				return fmt.Errorf("answered the entry %q %q, not a path and a hash", entry.Path, entry.Hash)
			}
		}
	}
	for _, paths := range [][]string{r.SendUp, r.Delete} {
		for _, path := range paths {
			if !ValidPath(path) {
				return fmt.Errorf("answered %q, not a path of the tree", path)
			}
		}
	}
	return nil
}

func orEmpty(hashes map[string]string) map[string]string {
	if hashes == nil {
		return map[string]string{}
	}
	return hashes
}
