package protocol

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// CheckAnswer is the check's answer of a project folder (design 1 §5.6).
type CheckAnswer struct {
	// Errors is the Save Errors under the folder, in path order.
	Errors []SaveError `json:"errors"`
	// HomelessDeferrals is the folder's project's deferrals without a home,
	// none for a folder of no syncing project.
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

// Check posts the hook's check of the project folder folder, from the
// tree's root, after the sidecar's flush of it took waited: POST
// /api/sync/check.
func (c *Client) Check(ctx context.Context, folder string, waited time.Duration) (CheckAnswer, error) {
	body, err := json.Marshal(map[string]any{"folder": folder, "wait_seconds": waited.Seconds()})
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", folder, err)
	}
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/sync/check", bytes.NewReader(body))
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", folder, err)
	}
	request.Header.Set("Content-Type", "application/json")
	answer, err := c.do(request)
	if err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: %w", folder, err)
	}
	var checked CheckAnswer
	if err := json.Unmarshal(answer.body, &checked); err != nil {
		return CheckAnswer{}, fmt.Errorf("POST the check of %s: answered %q: %w", folder, answer.body, err)
	}
	return checked, nil
}
