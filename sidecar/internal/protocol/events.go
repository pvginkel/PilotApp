package protocol

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// Hello is the change stream's first event.
type Hello struct {
	// Protocol is the range of versions the server serves.
	Protocol struct {
		Min int `json:"min"`
		Max int `json:"max"`
	} `json:"protocol"`
	// ManifestHash is the hash of the manifest as the stream opened.
	ManifestHash string `json:"manifest_hash"`
}

// Event is an event of the change stream after its hello: a Change, a
// ManifestChanged, or an Unknown one.
type Event interface {
	event()
}

// Change is a `change` event: the tree hash of the path moved.
type Change struct {
	Path string `json:"path"`
	Hash string `json:"hash"`
}

// ManifestChanged is a `manifest` event: the set of syncing projects
// changed.
type ManifestChanged struct{}

// Unknown is an event of a name this version does not know.
type Unknown struct {
	Name string
}

func (Change) event()          {}
func (ManifestChanged) event() {}
func (Unknown) event()         {}

// ErrStreamEnded is the change stream's end: the server closed it.
var ErrStreamEnded = errors.New("the change stream ended")

// Stream is the change stream, open, its hello read.
type Stream struct {
	Hello  Hello
	body   io.ReadCloser
	reader *bufio.Reader
}

// Events opens the change stream, GET /api/sync/events, and reads its
// hello. The stream is open until ctx is done or it is closed.
func (c *Client) Events(ctx context.Context) (*Stream, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/api/sync/events", nil)
	if err != nil {
		return nil, fmt.Errorf("GET the change stream: %w", err)
	}
	request.Header.Set("Accept", "text/event-stream")
	response, err := c.send(request) //nolint:bodyclose // the stream's to close: Stream.Close
	if err != nil {
		return nil, fmt.Errorf("GET the change stream: %w", err)
	}
	stream := &Stream{body: response.Body, reader: bufio.NewReader(response.Body)}
	if err := stream.hello(response.StatusCode); err != nil {
		return nil, errors.Join(fmt.Errorf("GET the change stream: %w", err), stream.Close())
	}
	return stream, nil
}

func (s *Stream) hello(status int) error {
	if status != http.StatusOK {
		return fmt.Errorf("answered %d, not 200", status)
	}
	name, data, err := s.frame()
	if err != nil {
		return err
	}
	if name != "hello" {
		return fmt.Errorf("opened with %q, not hello", name)
	}
	if err := json.Unmarshal(data, &s.Hello); err != nil {
		return fmt.Errorf("opened with hello %q: %w", data, err)
	}
	return nil
}

// Next reads the stream's next event, past its heartbeats; ErrStreamEnded
// once the server has closed it.
func (s *Stream) Next() (Event, error) {
	name, data, err := s.frame()
	if err != nil {
		return nil, err
	}
	switch name {
	case "change":
		var change Change
		if err := json.Unmarshal(data, &change); err != nil {
			return nil, fmt.Errorf("sent change %q: %w", data, err)
		}
		if !ValidPath(change.Path) || !validHash(change.Hash) {
			return nil, fmt.Errorf("sent change %q, not a path and a hash", data)
		}
		return change, nil
	case "manifest":
		return ManifestChanged{}, nil
	}
	return Unknown{Name: name}, nil
}

// Close closes the stream.
func (s *Stream) Close() error {
	return s.body.Close()
}

// frame reads the next event: its name and its data, each `data:` line of
// it joined by newlines. A frame is its lines up to a blank one; a line
// opening with a colon is a comment, the heartbeat.
func (s *Stream) frame() (string, []byte, error) {
	var name string
	var data []string
	seen := false
	for {
		line, err := s.reader.ReadString('\n')
		if errors.Is(err, io.EOF) {
			if seen || line != "" {
				return "", nil, io.ErrUnexpectedEOF
			}
			return "", nil, ErrStreamEnded
		}
		if err != nil {
			return "", nil, err
		}
		line = strings.TrimSuffix(strings.TrimSuffix(line, "\n"), "\r")
		if line == "" {
			if seen {
				return name, []byte(strings.Join(data, "\n")), nil
			}
			continue
		}
		if strings.HasPrefix(line, ":") {
			continue
		}
		field, value, _ := strings.Cut(line, ":")
		value = strings.TrimPrefix(value, " ")
		switch field {
		case "event":
			name, seen = value, true
		case "data":
			data, seen = append(data, value), true
		}
	}
}
