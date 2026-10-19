// Package protocol is the sidecar's end of the sync protocol (design 1 §5.1):
// the routes under /api/sync, each call with the store's bearer, its
// environment's id and the protocol version, and their answers checked as
// the server pins them (backend/tests/api/test_sync.py).
package protocol

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	pathpkg "path"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Version is the protocol version the sidecar speaks, sent as
// X-Pilot-Sync-Protocol on every call. A change to any request or response
// shape of the sync routes bumps it, and the server's SYNC_PROTOCOL_MAX, in
// one commit (design 1 §5.1).
const Version = 1

// callTimeout bounds a call that is not the change stream.
const callTimeout = 30 * time.Second

// errorBodyLimit bounds what of a refusal's body an error carries.
const errorBodyLimit = 4096

// Hash is the protocol's hash of content: its sha256, in lowercase hex
// (design 1 §5.2).
func Hash(content []byte) string {
	sum := sha256.Sum256(content)
	return hex.EncodeToString(sum[:])
}

// ErrNotFound is a 404: the path is of no syncing project.
var ErrNotFound = errors.New("not a path of a syncing project")

// UnsupportedError is a 426: the server serves the versions Min to Max, and
// Version is not among them.
type UnsupportedError struct {
	Min int `json:"min"`
	Max int `json:"max"`
}

func (e *UnsupportedError) Error() string {
	return fmt.Sprintf("the server serves sync protocol %d to %d, not %d", e.Min, e.Max, Version)
}

// StatusError is any other refusal: the status, and the body it came with.
type StatusError struct {
	Status int
	Body   string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("answered %d: %s", e.Status, e.Body)
}

// Client calls the sync routes of the server at its base URL.
type Client struct {
	base        string
	token       string
	environment string
	http        *http.Client
}

// NewClient is a client of the server at base, its URL with no trailing
// slash, as the store environment it names with its bearer.
func NewClient(base, token, environment string) *Client {
	return &Client{base: base, token: token, environment: environment, http: &http.Client{}}
}

// PutAnswer is what a PUT of a file answered.
type PutAnswer struct {
	// Content is the bytes the file must now hold, nil when it holds them
	// already (a 204).
	Content []byte
	// Hash is the hash of the bytes the file holds once answered.
	Hash string
	// Stale says the base hash was not the path's tree hash.
	Stale bool
	// Faults is the count of Save Errors the save raised on the path.
	Faults int
}

// Put saves content as the file at path, base the hash it last synced with,
// "" when it has none: PUT /api/sync/files/<path>.
func (c *Client) Put(ctx context.Context, path string, content []byte, base string) (PutAnswer, error) {
	if base == "" {
		base = "none"
	}
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPut, c.fileURL(path), bytes.NewReader(content))
	if err != nil {
		return PutAnswer{}, fmt.Errorf("PUT %s: %w", path, err)
	}
	request.Header.Set("Content-Type", "application/octet-stream")
	request.Header.Set("X-Pilot-Base-Hash", base)
	answer, err := c.put(request, content)
	if err != nil {
		return PutAnswer{}, fmt.Errorf("PUT %s: %w", path, err)
	}
	return answer, nil
}

func (c *Client) put(request *http.Request, content []byte) (PutAnswer, error) {
	reply, err := c.do(request)
	if err != nil {
		return PutAnswer{}, err
	}
	hash := reply.header.Get("X-Pilot-Hash")
	faults, err := strconv.Atoi(reply.header.Get("X-Pilot-Faults"))
	if err != nil || faults < 0 {
		return PutAnswer{}, fmt.Errorf("answered X-Pilot-Faults %q, not a count", reply.header.Get("X-Pilot-Faults"))
	}
	answer := PutAnswer{Hash: hash, Stale: reply.header.Get("X-Pilot-Stale") == "true", Faults: faults}
	held := content
	switch reply.status {
	case http.StatusOK:
		answer.Content = reply.body
		held = reply.body
	case http.StatusNoContent:
	default:
		return PutAnswer{}, fmt.Errorf("answered %d, neither 200 nor 204", reply.status)
	}
	if hash != Hash(held) {
		return PutAnswer{}, fmt.Errorf("answered %d with X-Pilot-Hash %q, not the hash of the bytes the file holds", reply.status, hash)
	}
	return answer, nil
}

// Get fetches the bytes the file at path must hold: GET
// /api/sync/files/<path>.
func (c *Client) Get(ctx context.Context, path string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, c.fileURL(path), nil)
	if err != nil {
		return nil, fmt.Errorf("GET %s: %w", path, err)
	}
	answer, err := c.do(request)
	if err != nil {
		return nil, fmt.Errorf("GET %s: %w", path, err)
	}
	if answer.status != http.StatusOK {
		return nil, fmt.Errorf("GET %s: answered %d, not 200", path, answer.status)
	}
	if hash := answer.header.Get("X-Pilot-Hash"); hash != Hash(answer.body) {
		return nil, fmt.Errorf("GET %s: answered X-Pilot-Hash %q, not the hash of its bytes", path, hash)
	}
	return answer.body, nil
}

// reply is an answer the server gave: its status, headers and body.
type reply struct {
	status int
	header http.Header
	body   []byte
}

// do sends request and reads the answer whole.
func (c *Client) do(request *http.Request) (reply, error) {
	response, err := c.send(request)
	if err != nil {
		return reply{}, err
	}
	body, err := io.ReadAll(response.Body)
	if err := errors.Join(err, response.Body.Close()); err != nil {
		return reply{}, err
	}
	return reply{status: response.StatusCode, header: response.Header, body: body}, nil
}

// send sends request with the three headers, returning a refusal as its
// error; the answer's body is the caller's to close.
func (c *Client) send(request *http.Request) (*http.Response, error) {
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set("X-Pilot-Environment", c.environment)
	request.Header.Set("X-Pilot-Sync-Protocol", strconv.Itoa(Version))
	response, err := c.http.Do(request)
	if err != nil {
		return nil, err
	}
	if response.StatusCode >= 300 {
		return nil, errors.Join(refusal(response), response.Body.Close())
	}
	return response, nil
}

func refusal(response *http.Response) error {
	body, err := io.ReadAll(io.LimitReader(response.Body, errorBodyLimit))
	if err != nil {
		return fmt.Errorf("answered %d, its body unread: %w", response.StatusCode, err)
	}
	switch response.StatusCode {
	case http.StatusNotFound:
		return ErrNotFound
	case http.StatusUpgradeRequired:
		var unsupported UnsupportedError
		if err := json.Unmarshal(body, &unsupported); err != nil {
			return fmt.Errorf("answered 426 with %q, not the versions it serves: %w", body, err)
		}
		return &unsupported
	}
	return &StatusError{Status: response.StatusCode, Body: string(body)}
}

// ValidPath says whether path is a path of the tree as the protocol speaks
// it: from the tree's root, with forward slashes, clean, and inside the tree.
func ValidPath(path string) bool {
	return path != "." && filepath.IsLocal(path) && pathpkg.Clean(path) == path
}

// validHash says whether hash is a hash as the protocol speaks it.
func validHash(hash string) bool {
	if len(hash) != sha256.Size*2 {
		return false
	}
	for _, r := range hash {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	return true
}

// fileURL is the route of the file at path, each segment escaped.
func (c *Client) fileURL(path string) string {
	segments := strings.Split(path, "/")
	for i, segment := range segments {
		segments[i] = url.PathEscape(segment)
	}
	return c.base + "/api/sync/files/" + strings.Join(segments, "/")
}
