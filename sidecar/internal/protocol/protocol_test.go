package protocol

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
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
	if _, err := client.Put(context.Background(), "proj/a b#1.md", []byte("after"), base); err != nil {
		t.Fatal(err)
	}
	put := <-requests
	last := put.request
	want := map[string]string{
		"Authorization":         "Bearer " + token,
		"X-Pilot-Environment":   environment,
		"X-Pilot-Sync-Protocol": "1",
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
}

func TestPutSendsNoneWithoutABase(t *testing.T) {
	client, requests := serve(t, acknowledge)
	if _, err := client.Put(context.Background(), "a.md", []byte("x"), ""); err != nil {
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
	answer, err := client.Put(context.Background(), "a.md", []byte("saved"), "")
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
	answer, err := client.Put(context.Background(), "a.md", []byte("saved"), "")
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
		if _, err := client.Put(context.Background(), "a.md", []byte("saved"), ""); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
}

func TestPutRefusesAnAnswerWithoutFaults(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusNoContent, map[string]string{"X-Pilot-Hash": Hash([]byte("saved"))}, ""))
	if _, err := client.Put(context.Background(), "a.md", []byte("saved"), ""); err == nil {
		t.Fatal("no error")
	}
}

func TestPutAnswersARefusal(t *testing.T) {
	client, _ := serve(t, answerWith(http.StatusNotFound, nil, `{"error": "not found"}`))
	if _, err := client.Put(context.Background(), "a.md", []byte("x"), ""); !errors.Is(err, ErrNotFound) {
		t.Errorf("404: got %v", err)
	}

	client, _ = serve(t, answerWith(http.StatusUpgradeRequired, nil, `{"min": 2, "max": 3}`))
	_, err := client.Put(context.Background(), "a.md", []byte("x"), "")
	var unsupported *UnsupportedError
	if !errors.As(err, &unsupported) || unsupported.Min != 2 || unsupported.Max != 3 {
		t.Errorf("426: got %v", err)
	}

	client, _ = serve(t, answerWith(http.StatusUnauthorized, nil, `{"error": "no bearer"}`))
	_, err = client.Put(context.Background(), "a.md", []byte("x"), "")
	var status *StatusError
	if !errors.As(err, &status) || status.Status != http.StatusUnauthorized || status.Body != `{"error": "no bearer"}` {
		t.Errorf("401: got %v", err)
	}
}
