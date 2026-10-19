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

func TestRemoveEmptyDirsStopsAtTheFirstDirectoryInUseAndKeepsTheRoot(t *testing.T) {
	root := t.TempDir()
	deep := filepath.Join(root, "proj", "inbox", "deep")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "proj", "plan.json"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := RemoveEmptyDirs(root, deep); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "proj", "inbox")); !os.IsNotExist(err) {
		t.Errorf("an empty directory is still there: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "proj")); err != nil {
		t.Errorf("a directory in use is gone: %v", err)
	}

	if err := os.Remove(filepath.Join(root, "proj", "plan.json")); err != nil {
		t.Fatal(err)
	}
	if err := RemoveEmptyDirs(root, filepath.Join(root, "proj", "inbox")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "proj")); !os.IsNotExist(err) {
		t.Errorf("an empty directory is still there: %v", err)
	}
	if _, err := os.Stat(root); err != nil {
		t.Errorf("the root is gone: %v", err)
	}
}
