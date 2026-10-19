package config

import (
	"slices"
	"strings"
	"testing"
)

// environment is a lookup over vars that records every name asked.
func environment(vars map[string]string, asked *[]string) func(string) (string, bool) {
	return func(name string) (string, bool) {
		*asked = append(*asked, name)
		value, ok := vars[name]
		return value, ok
	}
}

func catalog() map[string]string {
	return map[string]string{
		"PILOT_URL":                "https://pilot.example.test/",
		"PILOT_SYNC_TOKEN":         "example-token",
		"PILOT_SYNC_LOCAL_PORT":    "3511",
		"KUBECODER_ENVIRONMENT_ID": "example-env-1",
	}
}

func TestFromEnvReadsTheCatalogEntry(t *testing.T) {
	var asked []string
	cfg, err := FromEnv(environment(catalog(), &asked))
	if err != nil {
		t.Fatal(err)
	}
	want := Config{
		PilotURL:      "https://pilot.example.test",
		Token:         "example-token",
		EnvironmentID: "example-env-1",
		LocalPort:     3511,
		TreeRoot:      DefaultTreeRoot,
		DataDir:       DefaultDataDir,
	}
	if cfg != want {
		t.Fatalf("got %+v, want %+v", cfg, want)
	}
}

func TestFromEnvReadsNoOtherVariable(t *testing.T) {
	var asked []string
	if _, err := FromEnv(environment(catalog(), &asked)); err != nil {
		t.Fatal(err)
	}
	slices.Sort(asked)
	want := []string{DataDirVar, EnvironmentIDVar, PilotURLVar, LocalPortVar, TreeRootVar, TokenVar}
	slices.Sort(want)
	if !slices.Equal(slices.Compact(asked), want) {
		t.Fatalf("asked %v, want %v", asked, want)
	}
}

func TestFromEnvDefaultsThePortAndMovesTheDirectories(t *testing.T) {
	vars := catalog()
	delete(vars, "PILOT_SYNC_LOCAL_PORT")
	vars["PILOT_SYNC_TREE_ROOT"] = "/tmp/tree/"
	vars["PILOT_SYNC_DATA_DIR"] = "/tmp/data"
	var asked []string
	cfg, err := FromEnv(environment(vars, &asked))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.LocalPort != DefaultLocalPort || cfg.TreeRoot != "/tmp/tree" || cfg.DataDir != "/tmp/data" {
		t.Fatalf("got %+v", cfg)
	}
}

func TestFromEnvNamesEveryProblem(t *testing.T) {
	var asked []string
	_, err := FromEnv(environment(map[string]string{
		"PILOT_SYNC_LOCAL_PORT": "70000",
		"PILOT_SYNC_TREE_ROOT":  "Projects",
	}, &asked))
	if err == nil {
		t.Fatal("no error")
	}
	for _, name := range []string{PilotURLVar, TokenVar, EnvironmentIDVar, LocalPortVar, TreeRootVar} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("%q does not name %s", err, name)
		}
	}
}

func TestFromEnvRefusesAURLThatIsNotTheServers(t *testing.T) {
	for _, value := range []string{"pilot.example.test", "ftp://pilot.example.test", "https://pilot.example.test/?a=1", "https://user@pilot.example.test"} {
		vars := catalog()
		vars["PILOT_URL"] = value
		var asked []string
		if _, err := FromEnv(environment(vars, &asked)); err == nil || !strings.Contains(err.Error(), PilotURLVar) {
			t.Errorf("%q: got %v", value, err)
		}
	}
}
