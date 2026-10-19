// Package config reads pilot-sync's configuration from its environment, by
// the names the store's catalog entry gives it (design 1 §12). It reads no
// other variable: the sidecar runs as whatever uid its pod gives it, with no
// HOME and no passwd entry.
package config

import (
	"errors"
	"fmt"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
)

// The variables pilot-sync reads.
const (
	PilotURLVar      = "PILOT_URL"
	TokenVar         = "PILOT_SYNC_TOKEN"
	LocalPortVar     = "PILOT_SYNC_LOCAL_PORT"
	EnvironmentIDVar = "KUBECODER_ENVIRONMENT_ID"
	TreeRootVar      = "PILOT_SYNC_TREE_ROOT"
	DataDirVar       = "PILOT_SYNC_DATA_DIR"
)

// The defaults of the variables a run may leave unset.
const (
	DefaultLocalPort = 3510
	DefaultTreeRoot  = "/work/Projects"
	DefaultDataDir   = "/var/lib/pilot-sync"
)

// Config is pilot-sync's configuration.
type Config struct {
	// PilotURL is the server's base URL, with no trailing slash.
	PilotURL string
	// Token is the store's bearer.
	Token string
	// EnvironmentID is the store environment's id, sent as
	// X-Pilot-Environment.
	EnvironmentID string
	// LocalPort is the port of the sidecar's own endpoint on localhost.
	LocalPort int
	// TreeRoot is the absolute path of the tree the sidecar keeps.
	TreeRoot string
	// DataDir is the absolute path of the directory its shadow is kept in.
	DataDir string
}

// FromEnv reads the configuration through lookup, os.LookupEnv's shape, and
// names every variable that is missing or malformed in its error.
func FromEnv(lookup func(string) (string, bool)) (Config, error) {
	var problems []error
	required := func(name string) string {
		value, _ := lookup(name)
		if value == "" {
			problems = append(problems, fmt.Errorf("%s is not set", name))
		}
		return value
	}
	optional := func(name, fallback string) string {
		if value, _ := lookup(name); value != "" {
			return value
		}
		return fallback
	}
	directory := func(name, fallback string) string {
		value := optional(name, fallback)
		if !filepath.IsAbs(value) {
			problems = append(problems, fmt.Errorf("%s must be an absolute path, not %q", name, value))
		}
		return filepath.Clean(value)
	}

	cfg := Config{
		PilotURL:      required(PilotURLVar),
		Token:         required(TokenVar),
		EnvironmentID: required(EnvironmentIDVar),
		TreeRoot:      directory(TreeRootVar, DefaultTreeRoot),
		DataDir:       directory(DataDirVar, DefaultDataDir),
	}
	if cfg.PilotURL != "" {
		base, err := parseBase(cfg.PilotURL)
		if err != nil {
			problems = append(problems, fmt.Errorf("%s: %w", PilotURLVar, err))
		}
		cfg.PilotURL = base
	}
	port := optional(LocalPortVar, strconv.Itoa(DefaultLocalPort))
	number, err := strconv.Atoi(port)
	if err != nil || number < 1 || number > 65535 {
		problems = append(problems, fmt.Errorf("%s must be a port number, not %q", LocalPortVar, port))
	}
	cfg.LocalPort = number
	return cfg, errors.Join(problems...)
}

func parseBase(value string) (string, error) {
	parsed, err := url.Parse(value)
	if err != nil {
		return "", err
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", fmt.Errorf("must be an http or https URL, not %q", value)
	}
	if parsed.Host == "" || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.User != nil {
		return "", fmt.Errorf("must be the server's URL with no user, query or fragment, not %q", value)
	}
	return strings.TrimRight(value, "/"), nil
}
