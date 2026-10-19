// Package files writes a file whole: a temp file in its directory, renamed
// over it, so a reader sees the old bytes or the new and never a part.
package files

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// TempPrefix opens the name of every temp file pilot-sync writes. A file so
// named is the sidecar's own, never a file of the tree.
const TempPrefix = ".pilot-sync-"

// IsTemp says whether name, a file's base name, is one of pilot-sync's temp
// files.
func IsTemp(name string) bool {
	return strings.HasPrefix(name, TempPrefix)
}

// Write replaces the file at path, whose directory exists, with content and
// mode.
func Write(path string, content []byte, mode fs.FileMode) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), TempPrefix+"*")
	if err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	_, writeErr := tmp.Write(content)
	err = errors.Join(writeErr, tmp.Chmod(mode), tmp.Close())
	if err == nil {
		err = os.Rename(tmp.Name(), path)
	}
	if err != nil {
		return fmt.Errorf("write %s: %w", path, errors.Join(err, os.Remove(tmp.Name())))
	}
	return nil
}
