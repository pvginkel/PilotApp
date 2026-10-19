# Sessions

A Session is a run of a Claude Code conversation that Pilot drives, headless, in one environment
of the KubeCoder fleet, through the controller ([`controller.md`](controller.md)). Each message
sent to it is a Turn. Everything the session does is a list of Session Records that the server
appends to as the controller's raw response stream comes in, numbered from 1; a browser reads the
list by REST from any record number and follows it live on its SSE connection. This page is the
sessions as built: the start, the send, the relay, the current line, the records and their stream,
and the recovery after a restart. The tables are in [`record.md`](record.md), and the threads the
loops run on in [`jobs.md`](jobs.md).

| Service | Does |
|---|---|
| `SessionStartService` (`session_start_service.py`) | a Session written `starting`, then brought up by its start loop |
| `RelayService` (`relay_service.py`) | the send of a Turn, and the relay of each turn into the records |
| `SessionRecordService` (`session_record_service.py`) | the records' one writer and the one read function |
| `SessionStreamService` (`session_stream_service.py`) | the hub: a Session's live frames on the browsers' connections |
| `RelayWatchdog` (`relay_watchdog.py`) | the relays' restart when the fleet stream shows a turn stuck |
| `current_line.py` | what a turn in flight is doing, rebuilt from its records |

All are in `backend/app/services/`. Nothing outside testing mode starts a Session or sends it a
Turn: the session start is called by the testing route below alone.

## The session start

`start_session(db, project_id, env_id, *, kind_code, cwd, brief, options=None) -> Session` writes,
in the caller's transaction:

- the Environment row, on Pilot's first touch of the environment;
- the Session, `starting`, with `options` (`SessionOptions(agent, model, reasoning_effort,
  resume)`), `resume` as its `conversation_id`, and `token_hash` the sha256 of a token minted for
  it and not kept;
- Turn 1, the brief, with no author;
- the `server` record `{"type": "starting", "text": "Starting <environment name>…"}`, in no Turn,
  and the current line from it;
- the environment's shutdown timer cleared.

It refuses with `InvalidOperationException` when no controller is configured,
`RecordNotFoundException` for no such Project, and `ControllerProblem` `not-found` for an
environment the controller lacks. Once the transaction commits, the loop `start:<session id>` runs
the start from the rows: it starts the environment ([`controller.md`](controller.md)), writes
`{"type": "starting", "text": "Creating the session…"}`, creates the headless session with the
Session's `cwd`, `agent`, `model`, `reasoning_effort` and `conversation_id` as `resume`, records its
name as `controller_session` with `started_at`, and sends the brief (`send_turn`, below), whose
`202` starts the relay. A run told to stop after the environment's start or after the create
returns and leaves the Session `starting`, for the next process's reconcile.

**A start that fails.** Every `ExternalServiceException` of the environment's start or of the create
(a refusal, the environment settling other than `running`, the wait running out, a transport error)
fails the Session, in one transaction: the `server` record `{"type": "start-failed", "reason":
<error>}` in no Turn, the brief's Turn ended, the Session `failed` with `error`, its current line
cleared, and the environment's shutdown timer armed, so an environment Pilot started for it is
stopped. The log says `Session <id> failed to start: <error>`. A brief whose send fails fails the
Session the same way, with its Turn's `send-failed` record (below) instead of a `start-failed` one.
Nothing is retried.

**The testing route.** `POST /api/testing/sessions` `{project_id, environment_id, cwd, brief,
agent?, model?, reasoning_effort?, resume?}` starts a `work` Session and answers `201 {id}`: `400`
for a body that does not validate, `404` for no such Project, `409` with no controller configured,
`502` for an environment the controller lacks or a controller that failed. It answers `400`
`ROUTE_NOT_AVAILABLE` unless the server runs with `FLASK_ENV=testing` on a `STAGE` other than
`prd`, and is how the fleet's live check starts its turn ([`slice-test-plan.md`](slice-test-plan.md)
§2).

## The send

`RelayService.send(db, session_id, message, *, author_user_id=None) -> Turn` sends the Session a new
Turn, a person's message when it has an author, in the caller's transaction. The controller's send
goes first, and on its `202`, under the Session row's lock:

- the Turn, numbered after the Session's last, and its `send` record when it has an author;
- the Session `running`, its current line kept when it has one, as the session start's, and else
  `thinking` from the send, and its `turns`, `turn_started_at` and `turn_ended_at` refreshed as the
  latest Turn's;
- the environment's shutdown timer cleared;
- the Session's relay started once the transaction commits.

A send the controller fails before its `202` writes the Turn ended, with `error` the failure's
text, its `send` record when it has an author, and a `server` record `{"type": "send-failed",
"reason": <error>}` in the Turn; the Session's state stays as it was. Two answers are not failures:
a controller session that is gone (`404`) is resumed first (below) and the message sent to the one
that replaces it, and `409 session-busy`, a turn in flight at the controller, raises
`InvalidOperationException` and writes nothing, starting the Session's relay if this process runs
none. A Session with no controller session raises `InvalidOperationException`.

`send_turn(db, turn_id) -> Turn` sends a Turn written before its send, as the brief is, and moves
its `started_at` to the send. It first asks the controller whether it has the turn already (the
check below), and leaves alone a Turn whose send another process's commit made `running`.

## The relay

The loop `relay:<session id>` relays the Session's turn in flight. Its run reads the Session
`running` and its latest Turn with no `ended_at`, and returns at once when there is none. It opens
the response stream at the raw offset of the Session's last `claude` or `result` record when that
record is of the Session's current controller session, and at 0 otherwise, and takes each frame in
order:

- **A `stream_event` line is never a record.** A main-thread `content_block_start`, or a
  `content_block_delta` whose delta is a `text_delta`, is forwarded to the Session's hub as a
  `partial`, and moves the current line's state when it changes it; every other, a sub-agent's
  among them, is dropped.
- **Every other line is a `claude` record**, a blank or non-JSON one included, in a transaction of
  its own that rebuilds the current line. A line that is not a JSON object is stored as its text. A
  line at or below the last recorded offset of the same controller session is one the record has,
  and is skipped. While the Session's `conversation_id` is null, a recorded line's `session_id`
  sets it.
- **The `result` frame ends the Turn**, and nothing else does (D004). In one transaction: the
  `result` record, its payload the frame's data and its offset the stream's last raw frame's; the
  Turn ended, with `error` the result's text (or "The turn ended in an error") when the frame says
  `isError`; the Session `idle`, or `stopped` when the turn was interrupted, with no current line,
  and its turn caches refreshed; and the engine's `turn_ended(session)` ([`engine.md`](engine.md)).
  Once it commits, the environment's
  shutdown timer is armed if nothing else runs there. A `result` whose Turn has already ended,
  through another process's relay, writes nothing.

A send the controller accepted once the previous turn's `result` was out can commit before that
turn's end does. That turn's end then keeps the Session `running`, its current line the next Turn's
(`thinking` from its start), and the relay runs once more for the next Turn. An earlier Turn still
open at a turn's end lost its `result` to a later send, since the controller holds a turn's result
only until the next send: it ends with that turn, with no `result` record, and its lines after the
cut are recorded under the later Turn.

A stream that drops, or is silent for 60 s, raises, and the supervisor runs the relay again with
backoff, reopening at the last committed offset. A `409 conflict` (the environment not running)
waits for the environment to settle, `GET ?wait=settled` 10 s at a time, and carries on once it is
`running`; one that settles otherwise raises, and the relay is run again with backoff.

**Resuming a controller session that is gone.** A `404` on the stream or the send is the
controller session gone, as a pod restart leaves it. Under the Session's lock, and only while the
Session still has that controller session: a headless session is created in the same environment
with the Session's options and `resume` its `conversation_id`; then the `server` record
`{"type": "session-gone", "reason": <error>}` in no Turn, every Turn in flight ended with no
`result`, and `controller_session` the new name. The log says `Session <id> lost controller session
<name>; resumed as <name> in environment <id>`. The relay carries the turn on with a Turn of the
server's own, `continue`, with no author, which its next round sends; a send that met the `404`
sends its own message instead. A create that fails writes nothing of the resume: the relay is run
again with backoff, and a send writes its Turn as failed.

## The current line

`current_line` on the Session says what its turn in flight is doing, and is null while none is. Its
keys:

- `state`: `starting` (the session start), `thinking`, `writing` (a main-thread text block under
  way), `working` (a tool call without its result yet) or `waiting` (a sub-agent running);
- `since`: when that state began, or the latest step did;
- `step`: the latest tool call's `tool` and `input`, absent before the first;
- `agent`: the sub-agent's `type` and `description`, while `waiting`;
- `text`: the latest `server` record's words, while `starting`.

The session start sets it from each `starting` record it writes, in that record's transaction. From
a recorded line: a `system` `init` or a main-thread `user` line is `thinking`; a main-thread
`assistant` line is `working` with the step of its last tool call, `waiting` with its `agent` when
that call is `Task` or `Agent`, and `thinking` with no tool call. From a forwarded partial: a text
block's start or a text delta is `writing`, a thinking block's start `thinking`, a tool block's
start `working`. A sub-agent's line, and any other, keeps the state, a `starting` one becoming
`thinking`. A partial's move takes the Session's lock and writes nothing once the Turn has ended.

## The records

A record is one of four kinds:

| Kind | What it is | Its Turn |
|---|---|---|
| `claude` | a line of the raw response stream, as `claude` printed it, with its controller session and the raw offset after it | the turn it came in |
| `result` | the worker's `result` frame, `{turn, result, isError, interrupted}` as sent, with its controller session and offset | the turn it ended |
| `send` | a person's message, in its place among the lines; its words and author are the Turn's | the Turn it sent |
| `server` | the server's own line, a JSON object whose `type` says which: `starting`, `start-failed`, `send-failed`, `session-gone` | a `send-failed` its Turn's; the others none |

**The writer.** `SessionRecordService.append(session_id, kind, *, payload, turn_id, raw_offset,
controller_session)` is the only one: in the caller's transaction it locks the Session row, reads
the last record, writes the next `seq`, and wakes the Session's hub once the transaction commits.
The lock is held until the transaction ends, so a caller commits one record per transaction. A
transaction that ends a Session's stream (`ended` or `failed`) without writing a record registers
`after_commit(session_stream_service.waker(id))`, or the open views never receive `end`.

**The one read.** `read_records(db, session_id, *, after=0, before=None, kind=None, limit,
newest_first=False)` is the only query of `session_records` in the server. `TestTheOneRead`
(`backend/tests/services/test_session_record_service.py`) holds the code to it and to the one
writer: it fails on code in `app/` outside the read function that names `SessionRecord`, other than
in an annotation, or the table in a string, and on a `SessionRecord(...)` made outside `append`.
`last_record` and `stream_position` (the controller session and offset to resume at) read through
it.

## The stream

A browser follows a Session on the one SSE connection it holds, `/api/sse/stream?request_id=<id>`
([`sign-in.md`](sign-in.md)), and reads its history by REST. A view subscribes first, then reads the
records by page: what it subscribed after comes live, what came before it reads, and a record it
gets both ways is the same `seq`. The routes are behind the API's `editor` gate, and each answers
`404` for an unknown Session.

- `GET /api/sessions/<id>/records?after=<seq>&limit=<n>` answers `{records, ended}`: the records
  after `after` (0 by default), at most `limit` (200 by default, 1 to 1,000), in order. `ended` is
  true when the page holds the last record and the Session is `ended` or `failed`.
- `POST /api/sessions/<id>/stream` `{request_id, view}` opens a view of the Session's live frames on
  the caller's connection: `204`; `409` `NOT_CONNECTED` when this process holds no connection under
  `request_id`, the browser's stream being on another pod or just dropped, to retry; `403` for
  another user's connection.
- `DELETE /api/sessions/<id>/stream`, the same body, closes the view, `204`, and the connection
  leaves the Session's channel once it holds no view of it; `403` for another user's connection, and
  a request id with no connection answers `204`.

A record has one shape on the pages and in the live frames: `seq`, `at`, `turn` (its Turn's
number, null outside one) and `kind`; then a `claude` record's `payload` (the line's JSON, or its
text) and `raw_offset`, a `result` or `server` record's `payload`, a `send` record's `author` (a
handle) and `message`.

The live frames travel as the SSE event `session`, `{session, frame, data}`, on the channel
`session:<id>`:

- `record`: a record, in the shape above;
- `partial`: a forwarded `stream_event` line, as `claude` printed it;
- `end`, with no `data`: once, after the last record, when the Session is `ended` or `failed`.

**The hub.** Only the process that holds a connection delivers to it. Each process keeps a hub per
Session that one of its connections has a view of, with a cursor: the last record it pushed, at
first the Session's last record when the hub was made. A wake carries no record: the hub reads the
records after its cursor through the one read and pushes them in order, so each is pushed once and
after its commit, whichever wake comes first. A partial is pushed after the records before it. A
connection that goes, or is replaced, drops its views.

## Recovery

At STARTUP the job `relay`'s reconcile runs the relay of every Session `running` with a Turn in
flight (`Resuming the relay of session <id>`), and the job `start`'s the start of every Session
still `starting` (`Resuming the start of session <id>`). Each run resumes from the rows:

- **Sent or not.** Before it opens the stream, a relay's run reads the controller session's status
  snapshot. The controller has the turn when the session is `busy` or `interrupting`, or its `turn`
  is past the one in the Session's last `result` record of that controller session; otherwise the
  Turn, one written before its send, is sent now. A `409 session-busy` on that send that a second
  snapshot shows sent is another process's send.
- **The start** with no controller session starts the environment and creates the session again;
  one with a controller session sends the brief, unless the controller has it. Each write the start
  makes is conditional on the Session still being `starting`, under its lock, so a second process
  running the same start changes nothing the first wrote; a headless session the second created is
  left to the controller.

**The watchdog.** The timer `relay-watchdog` reads the fleet consumer's latest state
([`controller.md`](controller.md)) for every `running` Session with a controller session, and
restarts the relay when the fleet stream says its turn is no longer running: its controller session
not `working`, or the environment `running` with no such session, on two ticks in a row; or the
environment's pod restart count moved since the last tick, at once. A restart closes the relay's
stream (`Supervisor.interrupt_loop`), on this process's open relays only, and the run reopens it,
which delivers the buffered `result` of a turn that ended, carries on with one that did not, or
meets the session gone and resumes it. The log says `Restarted the relay of session <id>: <cause>`.
The watchdog ends no Turn: the fleet stream carries no turn event, so the `result` frame is the end
of a turn and the fleet stream only its watchdog (D004).

## Metrics

- `pilot_records_written_total{kind}`: the records written, by kind.
- `pilot_relays_running`, a gauge: the turns this process is relaying now.
- `pilot_partials_forwarded_total`: the partials forwarded to the hubs.
- `pilot_stream_views`, a gauge: the open views on this process's connections.

## Testing it

The tests are in `backend/tests/services/` (`test_session_start_service.py`,
`test_relay_service.py`, `test_relay_watchdog.py`, `test_current_line.py`,
`test_session_record_service.py`, `test_session_stream_service.py`) and `backend/tests/api/`
(`test_sessions.py`, `test_testing_sessions.py`), on the fake controller
([`controller.md`](controller.md)): a test plays a turn's lines with `play` and ends it with
`finish`, and calls the relay's run on its own session once the fake holds the turn. The tests that
run a loop from STARTUP, a start through its turn to the shutdown timer's stop included, build their
services on `committed_app` with the `supervise` fixture ([`jobs.md`](jobs.md)). The stream's tests
open test connections on the connection manager and read the frames queued on them.
