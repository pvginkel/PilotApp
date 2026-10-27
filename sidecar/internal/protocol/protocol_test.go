package protocol

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

const (
	token       = "example-token"
	environment = "example-env-1"
)

// served is a request the server took, with its body.
type served struct {
	request *http.Request
	body    []byte
}

// serve is a client of a server answering every call with answer, and the
// requests it took.
func serve(t *testing.T, answer func(w http.ResponseWriter, r *http.Request, body []byte)) (*Client, <-chan served) {
	t.Helper()
	requests := make(chan served, 8)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
		}
		requests <- served{r.Clone(context.Background()), body}
		answer(w, r, body)
	}))
	t.Cleanup(server.Close)
	return NewClient(server.URL, token, environment), requests
}

func answerWith(status int, headers map[string]string, body string) func(http.ResponseWriter, *http.Request, []byte) {
	return func(w http.ResponseWriter, _ *http.Request, _ []byte) {
		for name, value := range headers {
			w.Header().Set(name, value)
		}
		w.WriteHeader(status)
		_, _ = io.WriteString(w, body)
	}
}

// acknowledge answers 204, the save's own hash and no faults.
func acknowledge(w http.ResponseWriter, r *http.Request, sent []byte) {
	answerWith(http.StatusNoContent, map[string]string{"X-Pilot-Hash": Hash(sent), "X-Pilot-Faults": "0"}, "")(w, r, sent)
}

func TestHashIsTheSha256InLowercaseHex(t *testing.T) {
	if got := Hash([]byte("abc")); got != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatal(got)
	}
}

func TestPutSendsTheThreeHeadersAndTheBase(t *testing.T) {
	client, requests := serve(t, acknowledge)
	base := Hash([]byte("before"))
	if _, err := client.Put(context.Background(), "proj/a b#1.md", []byte("after"), base, ""); err != nil {
		t.Fatal(err)
	}
	put := <-requests
	last := put.request
	want := map[string]string{
		"Authorization":         "Bearer " + token,
		"X-Pilot-Environment":   environment,
		"X-Pilot-Sync-Protocol": "2",
		"X-Pilot-Base-Hash":     base,
		"Content-Type":          "application/octet-stream",
	}
	for name, value := range want {
		if got := last.Header.Get(name); got != value {
			t.Errorf("%s: got %q, want %q", name, got, value)
		}
	}
	if last.Method != http.MethodPut || last.URL.EscapedPath() != "/api/sync/files/proj/a%20b%231.md" {
		t.Errorf("got %s %s", last.Method, last.URL.EscapedPath())
	}
	if string(put.body) != "after" {
		t.Errorf("sent %q", put.body)
	}
	if _, sent := last.Header["X-Pilot-Session"]; sent {
		t.Errorf("sent X-Pilot-Session %q with no session", last.Header.Get("X-Pilot-Session"))
	}
}

func TestPutSendsTheSessionHoldingTheLock(t *testing.T) {
	client, requests := serve(t, acknowledge)
	session := "0f5b3c1e-6a2d-4f8e-9b7a-3c1d2e4f5a6b"
	if _, err := client.Put(context.Background(), "proj/a.md", []byte("x"), "", session); err != nil {
		t.Fatal(err)
	}
	if got := (<-requests).request.Header.Get("X-Pilot-Session"); got != session {
		t.Fatalf("got %q", got)
	}
}

func TestPutSendsNoneWithoutABase(t *testing.T) {
	client, requests := serve(t, acknowledge)
	if _, err := client.Put(context.Background(), "a.md", []byte("x"), "", ""); err != nil {
		t.Fatal(err)
	}
	if got := (<-requests).request.Header.Get("X-Pilot-Base-Hash"); got != "none" {
		t.Fatalf("got %q", got)
	}
}

func TestPutReadsA204(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusNoContent, map[string]string{
		"X-Pilot-Hash": Hash([]byte("saved")), "X-Pilot-Faults": "2", "X-Pilot-Stale": "true",
	}, ""))
	answer, err := client.Put(context.Background(), "a.md", []byte("saved"), "", "")
	if err != nil {
		t.Fatal(err)
	}
	if answer.Content != nil || answer.Hash != Hash([]byte("saved")) || !answer.Stale || answer.Faults != 2 {
		t.Fatalf("got %+v", answer)
	}
}

func TestPutReadsA200(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusOK, map[string]string{
		"X-Pilot-Hash": Hash([]byte("merged")), "X-Pilot-Faults": "1", "Content-Type": "application/octet-stream",
	}, "merged"))
	answer, err := client.Put(context.Background(), "a.md", []byte("saved"), "", "")
	if err != nil {
		t.Fatal(err)
	}
	if string(answer.Content) != "merged" || answer.Hash != Hash([]byte("merged")) || answer.Stale || answer.Faults != 1 {
		t.Fatalf("got %+v", answer)
	}
}

func TestPutRefusesAHashThatIsNotTheFiles(t *testing.T) {
	for name, answer := range map[string]func(http.ResponseWriter, *http.Request, []byte){
		"204": answerWith(http.StatusNoContent, map[string]string{"X-Pilot-Hash": Hash([]byte("other")), "X-Pilot-Faults": "0"}, ""),
		"200": answerWith(http.StatusOK, map[string]string{"X-Pilot-Hash": Hash([]byte("saved")), "X-Pilot-Faults": "0"}, "merged"),
	} {
		client, _ := serve(t, answer)
		if _, err := client.Put(context.Background(), "a.md", []byte("saved"), "", ""); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

func TestPutRefusesAnAnswerWithoutFaults(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusNoContent, map[string]string{"X-Pilot-Hash": Hash([]byte("saved"))}, ""))
	if _, err := client.Put(context.Background(), "a.md", []byte("saved"), "", ""); err == nil {
		t.Fatal("no error")
	}
}

func TestPutAnswersARefusal(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusNotFound, nil, `{"error": "not found"}`))
	if _, err := client.Put(context.Background(), "a.md", []byte("x"), "", ""); !errors.Is(err, ErrNotFound) {
		t.Errorf("404: got %v", err)
	}

	client, _ = serve(t, answerWith(http.StatusUpgradeRequired, nil, `{"min": 3, "max": 4}`))
	_, err := client.Put(context.Background(), "a.md", []byte("x"), "", "")
	var unsupported *UnsupportedError
	if !errors.As(err, &unsupported) || unsupported.Min != 3 || unsupported.Max != 4 {
		t.Errorf("426: got %v", err)
	}

	client, _ = serve(t, answerWith(http.StatusUnauthorized, nil, `{"error": "no bearer"}`))
	_, err = client.Put(context.Background(), "a.md", []byte("x"), "", "")
	var status *StatusError
	if !errors.As(err, &status) || status.Status != http.StatusUnauthorized || status.Body != `{"error": "no bearer"}` {
		t.Errorf("401: got %v", err)
	}
}

func TestGetAnswersTheBytesTheFileMustHold(t *testing.T) {
	client, requests := serve(t, answerWith(http.StatusOK, map[string]string{
		"X-Pilot-Hash": Hash([]byte("record")), "Content-Type": "application/octet-stream",
	}, "record"))
	content, err := client.Get(context.Background(), "proj/a b.md")
	if err != nil || string(content) != "record" {
		t.Fatalf("got %q, %v", content, err)
	}
	got := (<-requests).request
	if got.Method != http.MethodGet || got.URL.EscapedPath() != "/api/sync/files/proj/a%20b.md" || got.Header.Get("Authorization") != "Bearer "+token {
		t.Errorf("got %s %s", got.Method, got.URL.EscapedPath())
	}
}

func TestGetRefusesAHashThatIsNotTheBytesAndAnswersA404(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusOK, map[string]string{"X-Pilot-Hash": Hash([]byte("other"))}, "record"))
	if _, err := client.Get(context.Background(), "a.md"); err == nil {
		t.Error("no error for a hash not the bytes'")
	}
	client, _ = serve(t, answerWith(http.StatusNotFound, nil, `{"error": "not found"}`))
	if _, err := client.Get(context.Background(), "a.md"); !errors.Is(err, ErrNotFound) {
		t.Errorf("404: got %v", err)
	}
}

func TestManifestPostsBothMapsAndReadsTheFourLists(t *testing.T) {
	hash := Hash([]byte("a"))
	client, requests := serve(t, answerWith(http.StatusOK, map[string]string{"Content-Type": "application/json"},
		`{"manifest": [{"path": "proj/a.md", "hash": "`+hash+`", "readonly": false},
		  {"path": "reference.json", "hash": "`+hash+`", "readonly": true}],
		 "send_up": ["proj/a.md"], "write_down": [{"path": "reference.json", "hash": "`+hash+`", "readonly": true}],
		 "delete": ["draft-1/a.md"]}`))
	answer, err := client.Manifest(context.Background(), map[string]string{"proj/a.md": hash}, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := Reconciled{
		Manifest:  []Entry{{Path: "proj/a.md", Hash: hash}, {Path: "reference.json", Hash: hash, Readonly: true}},
		SendUp:    []string{"proj/a.md"},
		WriteDown: []Entry{{Path: "reference.json", Hash: hash, Readonly: true}},
		Delete:    []string{"draft-1/a.md"},
	}
	if !reflect.DeepEqual(answer, want) {
		t.Errorf("got %+v", answer)
	}
	posted := <-requests
	if got := string(posted.body); got != `{"shadow":{},"tree":{"proj/a.md":"`+hash+`"}}` {
		t.Errorf("posted %s", got)
	}
	if posted.request.Method != http.MethodPost || posted.request.URL.Path != "/api/sync/manifest" ||
		posted.request.Header.Get("Content-Type") != "application/json" || posted.request.Header.Get("X-Pilot-Sync-Protocol") != "2" {
		t.Errorf("got %s %s %v", posted.request.Method, posted.request.URL.Path, posted.request.Header)
	}
}

func TestManifestRefusesAPathOutsideTheTreeOrABadHash(t *testing.T) {
	for name, body := range map[string]string{
		"a path up":       `{"delete": ["../etc/passwd"]}`,
		"an absolute one": `{"write_down": [{"path": "/etc/passwd", "hash": "` + Hash(nil) + `", "readonly": false}]}`,
		"a bad hash":      `{"manifest": [{"path": "a.md", "hash": "ABC", "readonly": false}]}`,
	} {
		client, _ := serve(t, answerWith(http.StatusOK, nil, body))
		if _, err := client.Manifest(context.Background(), nil, nil); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

func TestValidPathIsATreePathAsTheProtocolSpeaksIt(t *testing.T) {
	for path, want := range map[string]bool{
		"proj/inbox/1-a.md": true, "reference.json": true, "draft-1/attachments/x/a b.png": true,
		"": false, ".": false, "..": false, "../a.md": false, "/a.md": false, "a//b.md": false, "a/./b.md": false,
		"a/../b.md": false, "a/": false,
	} {
		if got := ValidPath(path); got != want {
			t.Errorf("%q: got %v", path, got)
		}
	}
}

// streamOf serves the change stream as body, after a 200.
func streamOf(t *testing.T, body string) (*Stream, error) {
	t.Helper()
	client, requests := serve(t, answerWith(http.StatusOK, map[string]string{"Content-Type": "text/event-stream"}, body))
	stream, err := client.Events(context.Background())
	request := (<-requests).request
	if request.Method != http.MethodGet || request.URL.Path != "/api/sync/events" || request.Header.Get("X-Pilot-Environment") != environment {
		t.Errorf("got %s %s", request.Method, request.URL.Path)
	}
	if stream != nil {
		t.Cleanup(func() { _ = stream.Close() })
	}
	return stream, err
}

func TestEventsReadsHelloThenEachEventPastTheHeartbeats(t *testing.T) {
	hash := Hash([]byte("a"))
	stream, err := streamOf(t, "event: hello\ndata: {\"protocol\": {\"min\": 1, \"max\": 2}, \"manifest_hash\": \""+hash+"\"}\n\n"+
		": heartbeat\n\n"+
		"event: change\ndata: {\"path\": \"proj/a.md\", \"hash\": \""+hash+"\"}\n\n"+
		": heartbeat\n\n: heartbeat\n\n"+
		"event: manifest\ndata: {}\n\n"+
		"event: later\ndata: {\"what\": 1}\n\n")
	if err != nil {
		t.Fatal(err)
	}
	if stream.Hello.Protocol.Min != 1 || stream.Hello.Protocol.Max != 2 || stream.Hello.ManifestHash != hash {
		t.Errorf("hello: got %+v", stream.Hello)
	}
	for i, want := range []Event{Change{Path: "proj/a.md", Hash: hash}, ManifestChanged{}, Unknown{Name: "later"}} {
		got, err := stream.Next()
		if err != nil || got != want {
			t.Errorf("event %d: got %#v, %v", i, got, err)
		}
	}
	if _, err := stream.Next(); !errors.Is(err, ErrStreamEnded) {
		t.Errorf("at the end: got %v", err)
	}
}

func TestEventsRefusesAStreamWithoutHello(t *testing.T) {
	for name, body := range map[string]string{
		"ended at once": "",
		"no hello":      "event: manifest\ndata: {}\n\n",
		"cut short":     "event: hello\ndata: {\"protocol\"",
	} {
		if _, err := streamOf(t, body); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

func TestEventsEndsOnAChangeThatIsNotAPathAndAHash(t *testing.T) {
	stream, err := streamOf(t, "event: hello\ndata: {\"protocol\": {\"min\": 1, \"max\": 1}, \"manifest_hash\": \""+Hash(nil)+"\"}\n\n"+
		"event: change\ndata: {\"path\": \"../a.md\", \"hash\": \""+Hash(nil)+"\"}\n\n")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := stream.Next(); err == nil {
		t.Error("no error")
	}
}

func TestEventsAnswersARefusal(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusUpgradeRequired, nil, `{"min": 3, "max": 4}`))
	_, err := client.Events(context.Background())
	var unsupported *UnsupportedError
	if !errors.As(err, &unsupported) || unsupported.Min != 3 || unsupported.Max != 4 {
		t.Errorf("426: got %v", err)
	}
	client, _ = serve(t, answerWith(http.StatusForbidden, nil, `{"error": "not the store"}`))
	var status *StatusError
	if _, err := client.Events(context.Background()); !errors.As(err, &status) || status.Status != http.StatusForbidden {
		t.Errorf("403: got %v", err)
	}
}
