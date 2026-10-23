package protocol

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// CheckAnswer is the check's answer (design 1 §5.6).
type CheckAnswer struct {
	// Checked says whether the server agrees the file holds the hash posted.
	Checked bool `json:"checked"`
	// Errors is the Save Errors of the file's project folder, in path order,
	// or the file's own under no syncing project's folder.
	Errors []SaveError `json:"errors"`
	// HomelessDeferrals is the file's project's deferrals without a home,
	// none under no syncing project's folder.
	HomelessDeferrals []HomelessDeferral `json:"homeless_deferrals"`
}

// SaveError is the engine's verdict on a save it took: `parse`, the save is
// held; `reverted`, a record-owned line was restored.
type SaveError struct {
	Path string `json:"path"`
	Kind string `json:"kind"`
	// Line is the line of the save the error is on, nil when it has none.
	Line    *int   `json:"line"`
	Message string `json:"message"`
}

// HomelessDeferral is a deferred block no plan note names.
type HomelessDeferral struct {
	// Block is `<item id>/<local id>`.
	Block    string `json:"block"`
	Document string `json:"document"`
	Title    string `json:"title"`
	// To is the task the block is deferred to, or `plan`.
	To string `json:"to"`
}

// Check posts the hook's check of the file at path, holding hash, after the
// sidecar waited waited for its ack: POST /api/sync/check.
func (c *Client) Check(ctx context.Context, path, hash string, waited time.Duration) (CheckAnswer, error) {
	body, err := json.Marshal(map[string]any{"path": path, "hash": hash, "wait_seconds": waited.Seconds()})
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", path, err)
	}
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/sync/check", bytes.NewReader(body))
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", path, err)
	}
	request.Header.Set("Content-Type", "application/json")
	answer, err := c.do(request)
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", path, err)
	}
	var checked CheckAnswer
	if err := json.Unmarshal(answer.body, &checked); err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: answered %q: %w", path, answer.body, err)
	}
	return checked, nil
}
