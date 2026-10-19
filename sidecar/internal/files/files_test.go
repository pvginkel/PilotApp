package files

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWriteReplacesTheFileWithItsMode(t *testing.T) {
	dir := t.TempDir()
	name := filepath.Join(dir, "a.md")
	if err := os.WriteFile(name, []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Write(name, []byte("new"), 0o444); err != nil {
		t.Fatal(err)
	}
	content, err := os.ReadFile(name)
	if err != nil || string(content) != "new" {
		t.Fatalf("got %q, %v", content, err)
	}
	info, err := os.Stat(name)
	if err != nil || info.Mode().Perm() != 0o444 {
		t.Fatalf("got %v, %v", info.Mode(), err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("left %v, %v", entries, err)
	}
}

func TestWriteLeavesNoTempFileWhenTheRenameFails(t *testing.T) {
	dir := t.TempDir()
	// A rename over a non-empty directory fails.
	name := filepath.Join(dir, "a.md")
	if err := os.MkdirAll(filepath.Join(name, "inside"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Write(name, []byte("new"), 0o644); err == nil {
		t.Fatal("no error")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 || entries[0].Name() != "a.md" {
		t.Fatalf("left %v, %v", entries, err)
	}
}

func TestIsTemp(t *testing.T) {
	if !IsTemp(".pilot-sync-123") || IsTemp("a.md") || IsTemp(".pilot-syncing") {
		t.Fatal("IsTemp names the wrong files")
	}
}
