package shadow

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/pvginkel/PilotApp/sidecar/internal/protocol"
)

func TestPutRecordsTheBytesAndTheirHash(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := store.Hash("proj/inbox/1-a.md"); ok {
		t.Fatal("a path never synced has a hash")
	}
	if err := store.Put("proj/inbox/1-a.md", []byte("one")); err != nil {
		t.Fatal(err)
	}
	if hash, ok := store.Hash("proj/inbox/1-a.md"); !ok || hash != protocol.Hash([]byte("one")) {
		t.Fatalf("got %q, %v", hash, ok)
	}
	content, err := os.ReadFile(filepath.Join(dir, "proj", "inbox", "1-a.md"))
	if err != nil || string(content) != "one" {
		t.Fatalf("kept %q, %v", content, err)
	}
}

func TestOpenKeepsTheShadowOfTheLastRun(t *testing.T) {
	dir := t.TempDir()
	first, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	for path, content := range map[string]string{"reference.json": "{}", "proj/plan.json": "one", "draft-1/a.md": "a"} {
		if err := first.Put(path, []byte(content)); err != nil {
			t.Fatal(err)
		}
	}
	if err := first.Put("proj/plan.json", []byte("two")); err != nil {
		t.Fatal(err)
	}

	second, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	for path, content := range map[string]string{"reference.json": "{}", "proj/plan.json": "two", "draft-1/a.md": "a"} {
		if hash, ok := second.Hash(path); !ok || hash != protocol.Hash([]byte(content)) {
			t.Errorf("%s: got %q, %v", path, hash, ok)
		}
	}
}

func TestOpenRemovesAWriteCutShort(t *testing.T) {
	dir := t.TempDir()
	cut := filepath.Join(dir, "proj", ".pilot-sync-123")
	if err := os.MkdirAll(filepath.Dir(cut), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cut, []byte("half"), 0o600); err != nil {
		t.Fatal(err)
	}
	store, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := store.Hash("proj/.pilot-sync-123"); ok {
		t.Error("a temp file is in the shadow")
	}
	if _, err := os.Stat(cut); !os.IsNotExist(err) {
		t.Errorf("the temp file is still there: %v", err)
	}
}
