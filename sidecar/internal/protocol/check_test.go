package protocol

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"reflect"
	"testing"
	"time"
)

func TestCheckPostsThePathTheHashAndTheWait(t *testing.T) {
	client, requests := serve(t, answerWith(http.StatusOK, map[string]string{"Content-Type": "application/json"},
		`{"checked": true, "errors": [], "homeless_deferrals": []}`))
	hash := Hash([]byte("saved"))
	if _, err := client.Check(context.Background(), "proj/a.md", hash, 1500*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	check := <-requests
	if check.request.Method != http.MethodPost || check.request.URL.Path != "/api/sync/check" {
		t.Errorf("got %s %s", check.request.Method, check.request.URL.Path)
	}
	for name, value := range map[string]string{
		"Authorization":         "Bearer " + token,
		"X-Pilot-Environment":   environment,
		"X-Pilot-Sync-Protocol": "1",
		"Content-Type":          "application/json",
	} {
		if got := check.request.Header.Get(name); got != value {
			t.Errorf("%s: got %q, want %q", name, got, value)
		}
	}
	var body map[string]any
	if err := json.Unmarshal(check.body, &body); err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"path": "proj/a.md", "hash": hash, "wait_seconds": 1.5}; !reflect.DeepEqual(body, want) {
		t.Fatalf("posted %v", body)
	}
}

func TestCheckReadsTheAnswer(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusOK, map[string]string{"Content-Type": "application/json"}, `{
		"checked": false,
		"errors": [
			{"path": "proj/a.md", "kind": "reverted", "line": 3, "message": "reverted"},
			{"path": "proj/plan.json", "kind": "parse", "line": null, "message": "not JSON"}
		],
		"homeless_deferrals": [{"block": "P-4/d2", "document": "proj/a.md", "title": "A", "to": "plan"}]
	}`))
	got, err := client.Check(context.Background(), "proj/a.md", Hash([]byte("x")), 0)
	if err != nil {
		t.Fatal(err)
	}
	line := 3
	want := CheckAnswer{
		Errors: []SaveError{
			{Path: "proj/a.md", Kind: "reverted", Line: &line, Message: "reverted"},
			{Path: "proj/plan.json", Kind: "parse", Message: "not JSON"},
		},
		HomelessDeferrals: []HomelessDeferral{{Block: "P-4/d2", Document: "proj/a.md", Title: "A", To: "plan"}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v", got)
	}
}

func TestCheckReturnsARefusal(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusBadRequest, nil, `[{"loc": ["hash"]}]`))
	_, err := client.Check(context.Background(), "proj/a.md", "nope", 0)
	var refused *StatusError
	if !errors.As(err, &refused) || refused.Status != http.StatusBadRequest {
		t.Fatalf("got %v", err)
	}
}
