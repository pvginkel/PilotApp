# Sessions

A Session is a run of a Claude Code conversation that Pilot drives, headless, in one environment
of the KubeCoder fleet, through the controller ([`controller.md`](controller.md)). Each message
sent to it is a Turn. Everything the session does is a list of Session Records that the server
appends to as the controller's raw response stream comes in, numbered from 1; a browser reads the
list by REST from any record number and follows it live on its SSE connection. This page is the
sessions as built: the start through the gate, the send, the relay, Stop and Resume, an
environment restarted or stopped under a turn, the current line, the records and their stream, and
the recovery after a restart. A work item is a Session on the timeline, and what its line and its
session log show is [`work.md`](work.md)'s. The tables are in [`record.md`](record.md), and the
threads the loops run on in [`jobs.md`](jobs.md).

| Service | Does |
|---|---|
| `SessionStartService` (`session_start_service.py`) | a Session written `held` or `starting` through the gate, brought up by its start loop; a work item placed with it; Stop and Resume |
| `start_gate.py` | `held_reason`, the gate every start passes |
| `RelayService` (`relay_service.py`) | the send of a Turn, the relay of each turn into the records, and the interrupt of a turn stopped under it |
| `SessionRecordService` (`session_record_service.py`) | the records' one writer and the one read function |
| `SessionStreamService` (`session_stream_service.py`) | the hub: a Session's live frames on the browsers' connections |
| `RelayWatchdog` (`relay_watchdog.py`) | the relays' restart when the fleet stream shows a turn stuck or its environment stopped |
| `current_line.py` | what a turn in flight is doing, rebuilt from its records |

All are in `backend/app/services/`. Only the testing routes start a Session (below); nothing in the
app places a work item yet. A person's Resume carries a stopped or failed work item on, and Stop,
Finish and Archive stop one.

## The session start

`start_session(db, project_id, env_id, *, kind_code, cwd, brief, options=None) -> Session` writes,
in the caller's transaction:

- the Environment row, on Pilot's first touch of the environment: from the controller's report,
  or, while the controller does not answer, by its id alone, named by it and exempt, until the fleet
  stream reports it ([`controller.md`](controller.md));
- the Session, with `options` (`SessionOptions(agent, model, reasoning_effort, resume)`), `resume`
  as its `conversation_id`, and `token_hash` the sha256 of a token minted for it and not kept;
- Turn 1, the brief, with no author.

Then the gate decides its state. **The gate** (`held_reason(paused=, kind_code=, unreachable=)`)
holds a start while its project is paused ([`projects.md`](projects.md)), a Chat's never for the
pause, and while the controller is unreachable ([`controller.md`](controller.md)), the pause read
first where both hold. A start the gate holds is `held`: its Turn 1 unsent, no `server` record, no
current line, the shutdown timer untouched, and no loop run for it. One it lets through is
`starting`, and in the same transaction gets the `server` record `{"type": "starting", "text":
"Starting <environment name>…"}`, in no Turn, the current line from it, and the environment's
shutdown timer cleared.

It refuses with `InvalidOperationException` when no controller is configured, and for a `work` or
`job` Session in a finished or an archived project ("its project is finished", "… archived"), the
project's row read under a share lock so that a start and a Finish or an Archive never interleave;
`RecordNotFoundException` for no such Project; and `ControllerProblem` `not-found` for an
environment the controller lacks. Once a `starting` Session's transaction commits, the loop
`start:<session id>` runs the start from the rows: it starts the environment
([`controller.md`](controller.md)), writes `{"type": "starting", "text": "Creating the session…"}`,
creates the headless session with the Session's `cwd`, `agent`, `model`, `reasoning_effort` and
`conversation_id` as `resume`, records its name as `controller_session` with `started_at`, and
sends its latest Turn (`send_turn`, below), whose `202` starts the relay. A run told to stop
after the environment's start or after the create returns and leaves the Session `starting`, for
the next process's reconcile; one that finds its Session no longer `starting`, stopped meanwhile,
sends nothing.

**A work item.** `start_work(db, project_id, env_id, *, title, brief, cwd, plan_task_id=None) ->
Work` is `start_session`'s `work` start with its work item: the engine's `place_work`
([`engine.md`](engine.md)) writes the Item, kind `work`, at the project's next `seq`, titled
`title`, on the plan's task `plan_task_id` when given, created by its own Session, and the Work,
its `autopilot` the project's switch as it stands. The Item, the Work and the Session share one
id. A task not in the plan is a `RecordNotFoundException`.

**Held, then released.** A held Session goes on when the gate opens for it: at the outage's end,
at a `resumed` transition's commit, and at STARTUP. The loop `start:held` (`release_held()`)
takes each held Session in `created_at` order and, under its lock, while it is still `held` and
the gate, read afresh, is open for it, moves it to `starting` as above, the "Starting
<environment name>…" record left out for one that has its controller session, and runs its loop.
A held write's commit asks for it too, while the outage is off, since the gate may have opened
between the write's read and its commit. The log says `Session <id> is held at its start:
<reason>` and `Session <id> goes on from held`.

**A start that meets the outage.** A start one of whose calls the controller does not answer
(`ControllerUnreachable`, [`controller.md`](controller.md)), the environment's start, its settled
read, the create and the send among them, goes back to `held` with its rows as they stand, its last
current line kept, and is released from them once the gate opens. The log says `Session <id> is
held: <error>`.

**A start that fails.** Every other `ExternalServiceException` of the environment's start or of
the create (a refusal, the environment settling other than `running`, the wait running out, a `5xx`
the controller answers with its own problem+json) fails the Session, in one transaction: the
`server` record `{"type": "start-failed", "reason": <error>}` in no Turn, the Turn it sends ended,
the Session `failed` with `error`, its current line cleared, and the environment's shutdown timer
armed, so an environment Pilot started for it is stopped. The log says `Session <id> failed to
start: <error>`. A Turn whose send fails fails the Session the same way, with its Turn's
`send-failed` record (below) instead of a `start-failed` one. Nothing is retried but by a Resume.

**The testing routes.** `POST /api/testing/sessions` `{project_id, environment_id, cwd, brief,
agent?, model?, reasoning_effort?, resume?}` starts a `work` Session with no work item and answers
`201 {id}`, the Session `starting`, or `held` while the gate is closed: `400` for a body that does
not validate, `404` for no such Project, `409` with no controller configured or a finished or an
archived project, `502` for an environment the controller lacks or a controller that failed. It
answers `400` `ROUTE_NOT_AVAILABLE` unless the server runs with `FLASK_ENV=testing` on a `STAGE`
other than `prd`, and is how the fleet's live check starts its turn
([`slice-test-plan.md`](slice-test-plan.md) §2). The record's `POST
/api/testing/projects/<id>/work`, open on every stage but `prd`, places a work item through
`start_work` ([`projects.md`](projects.md)).

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
that replaces it; and `409 session-busy`, a turn in flight at the controller, raises
`InvalidOperationException` "a turn is in flight" and writes nothing (D034). While the record has a
Turn in flight, that refusal also starts the Session's relay if this process runs none; with none in
flight it starts no relay, and a lost turn's lines land under the next Turn, as a drop's do. A
Session with no controller session raises `InvalidOperationException`.

`send_turn(db, turn_id) -> Turn` sends a Turn written before its send, as the brief and a
Resume's are, and moves its `started_at` to the send. It first asks the controller whether it has
the turn already (the check below), and leaves alone a Turn whose send another process's commit
made `running`. A controller that does not answer raises `ControllerUnreachable` and writes
nothing. A Turn a Stop ended while its send went out is put back in flight, since the controller
has it: its relay records it, and its turn is interrupted.

## The relay

The loop `relay:<session id>` relays the Session's turn in flight. Its run reads the Session
`running`, or `stopped` under its turn, and its latest Turn with no `ended_at`, and returns at once
when there is none. It opens the response stream at the raw offset of the Session's last `claude`
or `result` record when that record is of the Session's current controller session, and at 0
otherwise, and takes each frame in order:

- **A `stream_event` line is never a record.** A main-thread `content_block_start`, or a
  `content_block_delta` whose delta is a `text_delta`, is forwarded to the Session's hub as a
  `partial`, and moves a running Session's current line's state when it changes it; every other, a
  sub-agent's among them, is dropped.
- **Every other line is a `claude` record**, a blank or non-JSON one included, in a transaction of
  its own that rebuilds a running Session's current line. A line that is not a JSON object is
  stored as its text. A line at or below the last recorded offset of the same controller session
  is one the record has, and is skipped. While the Session's `conversation_id` is null, a recorded
  line's `session_id` sets it.
- **The `result` frame ends the Turn**, and nothing else does (D004). In one transaction: the
  `result` record, its payload the frame's data and its offset the stream's last raw frame's; the
  Turn ended, with `error` the result's text (or "The turn ended in an error") when the frame says
  `isError`; with no later Turn in flight, the Session's state (below), no current line and its
  turn caches refreshed; and the engine's `turn_ended(session)` ([`engine.md`](engine.md)). Once it
  commits, the environment's shutdown timer is armed if nothing else runs there. A `result` whose
  Turn has already ended, through another process's relay, writes nothing.

The Session's state at its turn's end: `stopped` when the turn was interrupted, by no one
(`stopped_at` the end, `stopped_by_user_id` none), even when the frame also says `isError`; a work
item's Session `failed` when its turn ended in error, the error its Turn's (D036); else `idle`, and
a work item done, as the engine's `work_done` makes it: cause `turn_ended`, by no one, at the turn's
end, which a Finish that closed it first leaves as Finish closed it. A Session with no work item,
a Chat's or the testing route's, whose turn ended in error is `idle`, the error its Turn's. A
Session stopped under the turn keeps its stop, and its work item is not done.

A send the controller accepted once the previous turn's `result` was out can commit before that
turn's end does. That turn's end then keeps the Session `running`, its current line the next Turn's
(`thinking` from its start), and the relay runs once more for the next Turn. An earlier Turn still
open at a turn's end lost its `result` to a later send, since the controller holds a turn's result
only until the next send: it ends with that turn, with no `result` record, and its lines after the
cut are recorded under the later Turn.

A stream that drops, or is silent for 60 s, raises, and the supervisor runs the relay again with
backoff, reopening at the last committed offset.

**Resuming a controller session that is gone.** A `404` on the stream or the send is the
controller session gone, as a pod restart leaves it. Under the Session's lock, and only while the
Session still has that controller session: a headless session is created in the same
environment with the Session's options and `resume` its `conversation_id`; then the `server`
record `{"type": "session-gone", "reason": <error>}` in no Turn, every Turn in flight ended with no
`result`, and `controller_session` the new name. The log says `Session <id> lost controller session
<name>; resumed as <name> in environment <id>`. The relay carries the turn on with a Turn of the
server's own, with no author, which its next round sends: `continue`, or, while the Session has no
conversation, the ended Turn's message again, which the new session would not otherwise know
(D037). A send that met the `404` sends its own message instead. A create that fails writes nothing
of the resume: the relay is run again with backoff, and a send writes its Turn as failed. In the
relay, a create answered `404` is the environment gone, a stop made elsewhere (below).

## An environment restarted or stopped under the turn

A `409 conflict` on the stream or the send is the environment not running. The relay reads it at
once, then waits for it to settle, `GET ?wait=settled` 10 s at a time, and acts on what it reads:

- `running`: it carries on, the controller session resumed if the restart swept it (above).
- `provisioning` or `starting`, as a restart reads: a running Session's current line goes
  `starting` with the `text` "<environment name> is restarting…", and a `server` record `{"type":
  "restarting", "text": …}` in the Turn in flight is written, once. The resume's Turn moves the
  line on to `thinking`, and a session that survived moves it at its next line.
- `stopping`: it waits on.
- `stopped` or `deleting`, or a `404` on the read, is a stop made elsewhere, which no restart reads
  as (F71). Under the Session's lock: a `server` record `{"type": "environment-stopped", "cause",
  "reason"}`, its `cause` `environment_stopped`, `environment_deleting` or `environment_gone`, is
  the Turn's last; every Turn in flight ends with no `result`; a `running` Session is `stopped` as
  a Stop stops it, by no one, with no current line, and one stopped already keeps its stop. The
  documents it was writing are let go, as at a turn's end, and the environment's shutdown timer is
  armed. The log says `Session <id> stopped under its turn: <reason>`.
- Anything else, `error` among them, raises, and the relay is run again with backoff.

Resume starts the environment again (below). No column holds the cause: the record that ended the
turn is the fact, which the work item's line reads ([`work.md`](work.md)).

## Stop and Resume

Both are a work item's, by its id, which is its Session's, behind the API's `editor` gate, and
answer `200` with the item's work status as the timeline reads it ([`work.md`](work.md)), or `404`
for an unknown Session.

**`POST /api/sessions/<id>/stop`**, no body (`SessionStartService.stop`), stops it where it is, as
the signed-in person: the Session `stopped`, `stopped_at` now, `stopped_by_user_id` the person, no
current line, and the environment's shutdown timer armed if nothing else runs or starts there. It
calls no controller in the transaction. A running Session's Turn stays in flight: once the stop
commits, the loop `interrupt:<id>` asks the controller's interrupt, and the relay records the turn
to the `result` the interrupt brings, its lines arriving, its line and state unmoved, its work item
not done. A controller that does not answer the interrupt lets the turn run out; a controller
session or an environment that is gone has no turn to interrupt, and the relay ends that Turn with
no `result` (a `session-gone` record where its controller session is gone), as it does a turn the
controller never got. A held or starting Session's Turn ends at the stop, unsent, and its start
sends nothing more, unless its send was already going out: that Turn is put back in flight and
interrupted (`send_turn`, above). It is a `409` for a Session that is no work item's, for one
neither running, starting nor held ("its turn has ended", "it is stopped already", "it has failed",
"its session has ended"), and for a caller with no handle.

**`POST /api/sessions/<id>/resume`**, no body (`SessionStartService.resume`), carries a stopped or
failed work item on: a Turn of the server's own, `continue`, or the latest Turn's message while the
Session has no conversation (D037), so that a failed start's Resume carries its brief. Its Session's
`error` and current line are cleared, and it passes the gate as a start does, `held` or `starting`,
under a share lock on the project's row. Its start loop sends the Turn to the controller session
it has; one that is gone, ended, or whose environment is not running (`404`, `409 conflict`) is
given up first, with a `session-gone` record, and the start goes on from the environment's start
and a create resuming the conversation. Once the Resume's Turn is sent, its `started_at` is the
Session's `started_at`. The item stays one item. It is a `409` with no controller configured, for
a Session that is no work item's, for one neither stopped nor failed ("its start waits at the
gate", "it is starting", "it is running", "its turn has ended", "its session has ended"), for one
whose stopped turn is still ending, until the interrupt's `result` is recorded, and in a finished
or an archived project.

**Finish and Archive** stop every Session of the project running, starting or held, a Chat's
among them, as Stop stops one, by the person, at the transition's instant, before Finish's close
(`stop_project`, [`projects.md`](projects.md)).

## The current line

`current_line` on the Session says what its turn in flight is doing, and is null while none is. Its
keys:

- `state`: `starting` (the session start, or its environment restarting under the turn),
  `thinking`, `writing` (a main-thread text block under way), `working` (a tool call without its
  result yet) or `waiting` (a sub-agent running);
- `since`: when that state began, or the latest step did;
- `step`: the latest tool call's `tool` and `input`, absent before the first;
- `agent`: the sub-agent's `type` and `description`, while `waiting`;
- `text`: the latest `starting` or `restarting` record's words, while `starting`.

The session start sets it from each `starting` record it writes, in that record's transaction. From
a recorded line: a `system` `init` or a main-thread `user` line is `thinking`; a main-thread
`assistant` line is `working` with the step of its last tool call, `waiting` with its `agent` when
that call is `Task` or `Agent`, and `thinking` with no tool call. From a forwarded partial: a text
block's start or a text delta is `writing`, a thinking block's start `thinking`, a tool block's
start `working`. A sub-agent's line, and any other, keeps the state, a `starting` one becoming
`thinking`. A partial's move takes the Session's lock and writes nothing once the Turn has ended.
The relay moves only a `running` Session's line: one stopped under its turn has none.

## The records

A record is one of four kinds:

| Kind | What it is | Its Turn |
|---|---|---|
| `claude` | a line of the raw response stream, as `claude` printed it, with its controller session and the raw offset after it | the turn it came in |
| `result` | the worker's `result` frame, `{turn, result, isError, interrupted}` as sent, with its controller session and offset | the turn it ended |
| `send` | a person's message, in its place among the lines; its words and author are the Turn's | the Turn it sent |
| `server` | the server's own line, a JSON object whose `type` says which: `starting`, `start-failed`, `send-failed`, `session-gone`, `restarting`, `environment-stopped` | a `send-failed`, `restarting` or `environment-stopped` its Turn's; the others none |

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

At STARTUP the job `relay`'s reconcile runs the relay of every Session `running`, or `stopped`,
with a Turn in flight (`Resuming the relay of session <id>`); the job `interrupt`'s asks the
interrupt of every Session stopped with a Turn in flight; and the job `start`'s runs the start of
every Session still `starting` (`Resuming the start of session <id>`), then the release of the held
ones, the outage being off in a fresh process. Each run resumes from the rows:

- **Sent or not.** Before it opens the stream, a relay's run reads the controller session's status
  snapshot. The controller has the turn when the session is `busy` or `interrupting`, or its `turn`
  is past the one in the Session's last `result` record of that controller session; otherwise the
  Turn, one written before its send, is sent now, unless the Session was stopped under it, when the
  Turn ends with no `result`. A `409 session-busy` on that send that a second snapshot shows sent is
  another process's send.
- **The start** with no controller session starts the environment and creates the session again;
  one with a controller session sends its Turn, the brief or a Resume's, unless the controller has
  it. A start released from `held` after its `202` keeps the environment's claim
  ([`controller.md`](controller.md)). Each write the start makes is conditional on the Session
  still being `starting`, under its lock, so a second process running the same start changes
  nothing the first wrote; a headless session the second created is left to the controller.

**The watchdog.** The timer `relay-watchdog` reads the fleet consumer's latest state
([`controller.md`](controller.md)) for every Session with a controller session that is `running`,
or stopped with a Turn in flight, and restarts its relay when the fleet stream says its turn is no
longer running: its controller session not `working`, or the environment `running` with no such
session, on two ticks in a row; or, at once, the environment's pod restart count moved since the
last tick, or the environment reported `stopping`, `stopped` or `deleting`. A restart closes the
relay's stream (`Supervisor.interrupt_loop`), on this process's open relays only, and the run
reopens it, which delivers the buffered `result` of a turn that ended, carries on with one that did
not, meets the session gone and resumes it, or meets the environment stopped and stops the Session.
The log says `Restarted the relay of session <id>: <cause>`. The watchdog ends no Turn and writes
no Session: the fleet stream carries no turn event, so the `result` frame is the end of a turn and
the fleet stream only its watchdog (D004).

## Metrics

- `pilot_records_written_total{kind}`: the records written, by kind.
- `pilot_relays_running`, a gauge: the turns this process is relaying now.
- `pilot_partials_forwarded_total`: the partials forwarded to the hubs.
- `pilot_stream_views`, a gauge: the open views on this process's connections.

## Testing it

The tests are in `backend/tests/services/` (`test_session_start_service.py`, `test_start_gate.py`,
`test_relay_service.py`, `test_relay_watchdog.py`, `test_current_line.py`,
`test_session_record_service.py`, `test_session_stream_service.py`) and `backend/tests/api/`
(`test_sessions.py`, `test_testing_sessions.py`, `test_testing_record.py`), on the fake controller
([`controller.md`](controller.md)): a test plays a turn's lines with `play` and ends it with
`finish`, and calls the relay's run on its own session once the fake holds the turn. The tests that
run a loop from STARTUP, a start through its turn to the shutdown timer's stop included, build their
services on `committed_app` with the `supervise` fixture ([`jobs.md`](jobs.md)). The autouse
`controller_outage` fixture gives each test an outage of its own, off. The stream's tests open test
connections on the connection manager and read the frames queued on them.
