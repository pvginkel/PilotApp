# Sessions

A Session is a run of a Claude Code conversation that Pilot drives, headless, in one environment
of the KubeCoder fleet, through the controller ([`controller.md`](controller.md)). Each message
sent to it is a Turn. Everything the session does is a list of Session Records that the server
appends to as the controller's raw response stream comes in, numbered from 1; a browser reads the
list by REST from any record number and follows it live on its SSE connection. This page is the
sessions as built: the start through the gate, what a create is handed, the send, the relay, Stop
and Resume, an environment restarted or stopped under a turn, the current line, the records and
their stream, and the recovery after a restart. A work item is a Session on the timeline, and what
its line and its session log show is [`work.md`](work.md)'s; a project's chat is a Session of the
brain's in the store, and what a message to it does is [`chats.md`](chats.md)'s. The tables are in
[`record.md`](record.md), and the threads the loops run on in [`jobs.md`](jobs.md).

| Service | Does |
|---|---|
| `SessionStartService` (`session_start_service.py`) | a work item placed by repository, or a run's continuation, its Session written `held` or `starting` through the gate and brought up by its start loop in an environment of Pilot's own; a brain session's start, brought up in the store; Stop and Resume |
| `start_gate.py` | `held_reason`, the gate every start passes, and `WorkSlots`, its slot |
| `session_scope.py` | `scoped_create`, what each create of a Session is handed |
| `RelayService` (`relay_service.py`) | the send of a Turn, the relay of each turn into the records, and the interrupt of a turn stopped under it |
| `SessionRecordService` (`session_record_service.py`) | the records' one writer and the one read function |
| `SessionStreamService` (`session_stream_service.py`) | the hub: a Session's live frames on the browsers' connections |
| `RelayWatchdog` (`relay_watchdog.py`) | the relays' restart when the fleet stream shows a turn stuck or its environment stopped |
| `current_line.py` | what a turn in flight is doing, rebuilt from its records |

All are in `backend/app/services/`. The brain's `add_item` places a work item ([`mcp.md`](mcp.md)),
and so does the record's testing route (below); the close that leaves none of a run's registered
documents open places the run's continuation ([`round-trip.md`](round-trip.md)). A person's Resume
carries a stopped or failed work item on, and Stop, the brain's `stop_work`, Finish and Archive
stop one.

## The session start

`start_work(db, project_id, repo, *, title, brief, cwd, plan_task_id=None, agent=None, model=None,
reasoning_effort=None) -> Work` places a work item by repository, `owner/Name`, and writes its
Session's start, in the caller's transaction:

- its Item and its Work, through the engine's `place_work` ([`engine.md`](engine.md)): the Item,
  kind `work`, at the project's next `seq`, titled `title`, on the plan's task `plan_task_id` when
  given, created by its own Session; the Work, its `repo` the repository and its `autopilot` the
  project's switch as it stands. The Item, the Work and the Session share one id;
- the Session, kind `work`, with its `cwd`, `agent`, `model` and `reasoning_effort`, none of them
  defaulted by the server, no Environment until its start provides one, and `token_hash` the sha256
  of a token no one holds, until its create mints the one its controller session carries (below);
- Turn 1, the brief, with no author.

The repository and `cwd` are taken as the placement gives them: the server maps and checks
neither. No controller call is made. It refuses with `InvalidOperationException` when no controller
is configured and in a finished or an archived project ("its project is finished", "… archived"),
and with `RecordNotFoundException` for no such Project or a task not in the plan. The project's row
is read under the lock its Item's birth takes, `next_seq`'s `FOR UPDATE`, so a start and a Finish
or an Archive never interleave, and two starts of one project go one after the other.

Then the gate decides its state. **The gate** (`held_reason(paused=, kind_code=, unreachable=,
filled=)`) holds a start while its project is paused ([`projects.md`](projects.md)), a Chat's never
for the pause; while the controller is unreachable ([`controller.md`](controller.md)); and, a work
item's alone, while no slot is free (below). Where more than one holds, the pause is read first,
then the outage, then the slot. A start the gate holds is `held`: its Turn 1 unsent, no `server`
record, no current line, and no loop run for it. One it lets through is `starting`, takes its slot,
and has its loop run once the transaction commits. A `starting` Session that has an Environment
already, a Resume's, has the environment's shutdown timer cleared in the same transaction, and gets
the `server` record `{"type": "starting", "text": "Starting <environment name>…"}`, in no Turn, and
the current line from it, unless it has its controller session or its rename is still to make (the
start loop, below). The record reads "Preparing <environment name>…" for an environment of Pilot's
own on a new conversation, created or reset.

**The slot.** `WorkSlots` (`start_gate.py`, the container's `work_slots`) counts the Sessions of
kind `work` that are `running` or `starting`; a Chat's and a job's count for none. No slot is free
while those across every project number `WORK_PARALLELISM_MAX` (3 by default), or those of the
work item's project `PROJECT_PARALLELISM_MAX` (unset by default, which is the cross-project
maximum), the cross-project count read first; both are settings of the deployment, above 0. A
start counts under the slot's lock (`WorkSlots.lock`), one transaction-level advisory lock for the
whole app, so of two starts that would take the last slot the second counts once the first has
committed. A held work item reads `held_reason` `slot`, and `held_running` the running
work items of the maximum that closed the gate ([`work.md`](work.md)). A work item's start takes a
slot and its end gives it back: its turn's `result`, its Stop, its failed start, a stop made
elsewhere. Each asks for the release once its transaction commits.

**The lock order.** A start, a Resume and the release take their locks in one order: the Project's
row, the Session's, the slot's lock, then an Environment's. A start that places a work item holds
its Project's row `FOR UPDATE`, as `next_seq` takes it, so its Item's birth asks for no lock
stronger than one it holds; a Resume shares the row. A close that places a continuation holds the
Project's row `FOR UPDATE`, then the Document's, the slot's and an Environment's; a Resume of a
continuation locks the documents it carries after its Session's, before the slot. The start loop's
transactions lock no Project row, so no controller call is made while one is locked.

**The start loop.** Once a `starting` Session's transaction commits, the loop `start:<session id>`
runs the start from the rows, its environment first:

- **None yet**: under the Session's lock, it takes a free environment of Pilot's own made from the
  Work's repository ([`controller.md`](controller.md)), the Session's Environment written in the
  take's transaction, which commits before any controller call (`Session <id> took environment
  <env id>`). A taken one is renamed after the project: its slug, or `<slug>-2`, `<slug>-3`, …
  while the fleet holds that name already, KubeCoder's names being unique across it. Then
  `{"type": "starting", "text": "Preparing <name>…"}` is written, and the environment reset. With
  none free to take, it creates one from the repository, named the same way, and commits its row,
  Pilot's own, with the Session's Environment and the "Preparing <name>…" record before its
  bring-up is waited on; a created one is not reset. One created for a Session that moved on
  meanwhile, stopped or given an environment by another process, is stopped at once and left free.
- **One whose reset is still to make**, a fresh-start Resume's (below): renamed, "Preparing
  <name>…" and reset, as a taken one is.
- **One with a bring-up of Pilot's still to settle**, a create's, a reset's or a start's: that
  settle is awaited, never a second scheduled.
- **Any other**: started ([`controller.md`](controller.md)).

A brain session's environment is the store, `STORE_ENVIRONMENT_ID`, never one of Pilot's own: its
loop writes it under the Session's lock with "Starting <name>…", the store's row made from the
controller's report where Pilot has none yet, then starts the store and awaits its settle
([`chats.md`](chats.md)).

A continuation's start first writes back what the documents it carries still owe, before its
environment is brought up ([`round-trip.md`](round-trip.md)). Then it writes `{"type": "starting",
"text": "Creating the session…"}`, creates the headless session as its scope gives it (below),
Pilot's MCP server handed to it with a token minted for this create ([`mcp.md`](mcp.md)), records
its name as `controller_session` with
`started_at` and the token's sha256 as `token_hash` in one transaction, and sends its latest Turn
(`send_turn`, below), whose `202` starts the relay. A run told to stop after the environment's
bring-up or after the create returns and leaves the Session `starting`, for the next process's
reconcile. One that finds its Session no longer `starting` to send the Turn it began with, stopped
meanwhile, or stopped and resumed, goes no further and sends nothing: a Resume's start is its own
run's.

**The scope.** What a create is handed is derived in one place from the Session's columns, its
kind and its Project, for every create of it alike, the start loop's and the relay's of a gone
controller session (D067): `scoped_create(db, session)`. No column holds it. Its request carries the
Session's `cwd`, `agent`, `model`, `reasoning_effort` and `conversation_id` as `resume`, and its
surface is its kind's ([`record.md`](record.md)): `pilot-work` for a work item. A brain session, a
chat's or a job's, whose kind's surface is `pilot-store`, is boxed: `sandboxReadOnlyCwd`, its cwd
the store repo's root, read-only; `sandboxWritableDirs` its project's folder,
`/work/Projects/<folder>`, the one folder under `/work` it writes; and `PILOT_PROJECT=<that
folder>` in its `env`, which the brain's `pilot.py` reads. While its Project is finished it is
boxed with no folder writable and no surface, so it is handed no server, its `PILOT_PROJECT` kept
([`chats.md`](chats.md)). The Project's state is read afresh at each create; a chat closes whenever
the state it was opened under moves, so no create of an open chat crosses states. The controller
builds the box at every turn's spawn: a folder of it gone since the create fails the turn, which
never runs unboxed ([`controller.md`](controller.md)).

A work item in an environment Pilot did not create, which only the dev stage's database holds,
placed there by the environment's id, is never started there: its start fails with "its
environment is not Pilot's", nothing called, and its Resume is refused so (below).

**Held, then released.** A held Session goes on when the gate opens for it: at the outage's end,
at a `resumed` transition's commit, at a work item's start or end, which moves the slot's count,
and at STARTUP. The loop `start:held` (`release_held()`) takes each held Session in `created_at`
order and, under its lock, while it is still `held` and the gate, read afresh, is open for it, a
work item's slot counted under the slot's lock, moves it to `starting` as above and runs its loop.
A work item it still holds has its line told again ([`work.md`](work.md)), since the outage's turn
or the slot's count may have moved its reason. A held write's commit asks for the release too,
while the outage is off, since the gate may have opened between the write's read and its commit.
The log says `Session <id> is held at its start: <reason>` and `Session <id> goes on from held`.

**A start that meets the outage.** A start one of whose calls the controller does not answer
(`ControllerUnreachable`, [`controller.md`](controller.md)), any call of its environment's
bring-up, the headless session's create and the send among them, goes back to `held` with its rows
as they stand, its last current line kept, and is released from them once the gate opens. The log
says `Session <id> is held: <error>`.

**A start that fails.** Every other `ExternalServiceException` of the start fails the Session: a
refusal of the environment's create (`409 admission-blocked` at the node's cap, `403
namespace-not-whitelisted`, `422 validation-error`), of its rename, its stop, its reset or its
start, of the headless session's create (a boxed one's `422 validation-error` for a folder not on
disk, which a create with a folder to write first meets again for 60 s, [`chats.md`](chats.md), or
`409 capability-unavailable`), the environment settling other than `stopped` after its stop or
other than `running` after its bring-up, a wait running out, a `5xx` the controller answers with its
own problem+json. In one
transaction: the `server` record `{"type": "start-failed", "reason": <error>}` in no Turn, the Turn
it sends ended, the Session `failed` with `error`, its current line cleared, its slot given back,
and its environment, when it has one, handed to the shutdown timer: armed, so that an environment
Pilot started for it is stopped, one whose reset was still to make claimed first, so that the timer
stops it too. The log says `Session <id> failed to start: <error>`. A Turn whose send fails fails
the Session the same way, with its Turn's `send-failed` record (below) instead of a `start-failed`
one. Nothing is retried but by a Resume.

**A run's continuation.** `continue_run(db, project, run_id, released, message)` places the work
item that continues the conversation of the work item `run_id`, in the caller's transaction, the
close's, which holds the project's row: its Item titled as the run, at the project's next `seq`,
its trigger the Item `released` whose close released it; its Work with the run's repository; its
Session in the run's environment from its placement on, with the run's conversation, `cwd`,
`agent`, `model` and effort; its Turn 1 `message`, with no author. It passes the gate as
`start_work`'s does, and refuses as it does in a finished or an archived project, which refuses
the close. Its environment is never reset: the
conversation goes on in the tree as the run left it ([`round-trip.md`](round-trip.md)).

**The testing route.** The record's `POST /api/testing/projects/<id>/work`, open on every stage but
`prd`, places a work item through `start_work` ([`projects.md`](projects.md)), and the fleet's live
check drives it ([`slice-test-plan.md`](slice-test-plan.md) §2). No route starts a Session in an
environment its caller names.

## The send

`RelayService.send(db, session_id, message, *, words=None) -> Turn` sends the Session a new Turn,
`message`, in the caller's transaction; a person's message carries `words`, its author and their
words verbatim, which `message` ends with ([`chats.md`](chats.md)). The controller's send goes
first, and on its `202`, under the Session row's lock:

- the Turn, numbered after the Session's last, with its author and `words` when it has them, and
  its `send` record then;
- the Session `running`, its current line kept when it has one, as the session start's, and else
  `thinking` from the send, and its `turns`, `turn_started_at` and `turn_ended_at` refreshed as the
  latest Turn's;
- the environment's shutdown timer cleared;
- the Session's relay started once the transaction commits.

A send the controller fails before its `202` writes the Turn ended, with `error` the failure's
text, its `send` record when it has an author, and a `server` record `{"type": "send-failed",
"reason": <error>}` in the Turn; the Session's state stays as it was. Two answers are not failures.
A controller session that is gone (`404`) is created again first, under the Session's lock (below),
and the Turn written in flight as on a `202`, unsent: the relay sends it to the new session once the
caller's transaction commits, which commits that session's token's hash with it, so that its first
tool call is admitted; where another process created it again first, the message goes to that one.
And `409 session-busy`, a turn in flight at the controller, raises
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
  stored as its text, and so is one that jsonb refuses: a string holding a `\u0000`, or a lone
  surrogate such as a truncated emoji's `\ud83d`, the line kept whole rather than scrubbed. A line
  at or below the last recorded offset of the same controller session is one the record has, and
  is skipped. While the Session's `conversation_id` is null, a recorded line's `session_id` sets it.
- **The `result` frame ends the Turn**, and nothing else does (D004). In one transaction: the
  `result` record, its payload the frame's data and its offset the stream's last raw frame's; the
  Turn ended, with `error` the result's text (or "The turn ended in an error") when the frame says
  `isError`; with no later Turn in flight, the Session's state (below), no current line and its
  turn caches refreshed; the engine's `turn_ended(session)` ([`engine.md`](engine.md)), and a brain
  session's follow-up turn on the saves it returns still held; and a closed chat's close record,
  where the close came while the turn was in flight ([`chats.md`](chats.md)). Once it
  commits, the environment's shutdown timer is armed if nothing else runs there, and, when the
  turn made a work item done, the documents its run registered are read
  ([`round-trip.md`](round-trip.md)). A `result` whose
  Turn has already ended, through another process's relay, writes nothing.

The Session's state at its turn's end: `stopped` when the turn was interrupted, by no one
(`stopped_at` the end, `stopped_by_user_id` none), even when the frame also says `isError`; a work
item's Session `failed` when its turn ended in error, the error its Turn's (D036); else `idle`, and
a work item done, as the engine's `work_done` makes it: cause `turn_ended`, by no one, at the turn's
end, which a Finish that closed it first leaves as Finish closed it. A Session with no work item
whose turn ended in error is `idle`, the error its Turn's. A Session stopped under the turn keeps
its stop, and its work item is not done. A work item's turn that ends gives its slot back. A brain
session left `idle` with a save of its own still held stays `running` with the server's follow-up
turn, written in flight in that transaction, which the relay sends once it commits; one follow-up
per turn (D065, [`chats.md`](chats.md)).

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
environment as its scope gives it (above), `resume` its `conversation_id` and a token minted for
it, whose hash is the Session's from then; then the `server`
record `{"type": "session-gone", "reason": <error>}` in no Turn, every Turn in flight ended with no
`result`, and `controller_session` the new name. The log says `Session <id> lost controller session
<name>; resumed as <name> in environment <id>`. The relay carries the turn on with a Turn of the
server's own, with no author, which its next round sends: `continue`, or, while the Session has no
conversation, or no Turn of it has gone out, as a continuation's from its placement, the ended
Turn's message again, which the new session would not otherwise know (D037), as Resume picks it
(below). A send that met the `404` has its own Turn sent instead (above). A create that fails
writes nothing of the resume: the relay is run again with backoff, and a send writes its Turn as
failed. In the
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
- `stopped`, `deleting` or `error`, or a `404` on the read, is a stop made elsewhere, which no
  restart reads as (F71; `error`, D043). Under the Session's lock: a `server` record `{"type":
  "environment-stopped", "cause", "reason"}`, its `cause` `environment_stopped`,
  `environment_deleting`, `environment_error` or `environment_gone` and its `reason` "environment
  <id> is stopped", "… is deleting", "… is in error" or the `404`'s, is the Turn's last; every Turn
  in flight ends with no `result`; a `running` Session is `stopped` as a Stop stops it, by no one,
  with no current line, and one stopped already keeps its stop. The documents it was writing are
  let go, as at a turn's end, the environment's shutdown timer is armed, and a work item's slot is
  given back. The log says `Session <id> stopped under its turn: <reason>`.

Resume starts the environment again (below), which is also KubeCoder's way out of `error`. No
column holds the cause: the record that ended the turn is the fact, which the work item's line
reads ([`work.md`](work.md)).

## Stop and Resume

Both are a work item's, by its id, which is its Session's, behind the API's `editor` gate, and
answer `200` with the item's work status as the timeline reads it ([`work.md`](work.md)), or `404`
for an unknown Session.

**`POST /api/sessions/<id>/stop`**, no body (`SessionStartService.stop`), stops it where it is, as
the signed-in person: the Session `stopped`, `stopped_at` now, `stopped_by_user_id` the person, no
current line, its environment, when it has one, handed to the shutdown timer as a failed start's is
(above), and a work item's slot given back. It calls no controller in the transaction. A running Session's Turn stays in flight: once the stop
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
Session has no conversation (D037), so that a failed start's Resume carries its brief, or while no
Turn of it has gone out, so that a continuation's carries its message. Its Session's `error` and
current line are cleared, a write-back the controller refused of a document it carries is owed
again ([`round-trip.md`](round-trip.md)), and it passes the gate as a start does, `held` or `starting`,
under a share lock on the project's row, its slot counted before its environment's row is locked.
A stopped or failed work item keeps its environment meanwhile: no other start takes it, and
nothing resets or deletes it (D042, [`controller.md`](controller.md)).

- **With a conversation to continue**, its start loop sends the Turn to the controller session it
  has; one that is gone, ended, or whose environment is not running (`404`, `409 conflict`) is given
  up first, with a `session-gone` record, and the start goes on from the environment's start, one in
  `error` among them, and a create resuming the conversation. Its environment is never reset, so the
  conversation carries on in the tree as the session left it.
- **With none**, a start that failed before its first line or a held start stopped before it took
  an environment, it is a fresh start: in a headless session of its own, its controller session
  cleared, in its environment taken back, its claim cleared in the Resume's transaction, so that its
  start renames, stops and resets it as it does a taken one. One gone or deleting is let go, and
  the start takes a free one or creates one.

Once the Resume's Turn is sent, its `started_at` is the Session's `started_at`. The item stays one
item. It is a `409` with no controller configured, for a Session that is no work item's, for one
neither stopped nor failed ("its start waits at the gate", "it is starting", "it is running", "its
turn has ended", "its session has ended"), for one in an environment Pilot did not create ("its
environment is not Pilot's"), for one whose stopped turn is still ending, until the interrupt's
`result` is recorded, and in a finished or an archived project.

**Finish, Archive and Reopen** stop every Session of the project running, starting or held, a
Chat's among them, as Stop stops one, by the person, at the transition's instant, before Finish's
close and before the chat's close at Finish and Reopen (`stop_project`,
[`projects.md`](projects.md)); in a finished project, Reopen's stop meets its read-only chat alone (D068). The project's open chat's
Session is locked first, whatever its state, since a message's send moves it under that lock alone
([`chats.md`](chats.md)). The brain's `stop_work` stops a work item as Stop does, by Pilot
([`mcp.md`](mcp.md)).

## The current line

`current_line` on the Session says what its turn in flight is doing, and is null while none is. Its
keys:

- `state`: `starting` (the session start, or its environment restarting under the turn),
  `thinking`, `writing` (a main-thread text block under way), `working` (a tool call without its
  result yet) or `waiting` (a sub-agent running);
- `since`: when that state began, or the latest step did;
- `step`: the latest tool call's `tool` and `input`, absent before the first, its `input` null
  while the call's input streams in;
- `agent`: the sub-agent's `type` and `description`, while `waiting`;
- `text`: the latest `starting` or `restarting` record's words, while `starting`.

The session start sets it from each `starting` record it writes, in that record's transaction. From
a recorded line: a `system` `init` or a main-thread `user` line is `thinking`; a main-thread
`assistant` line is `working` with the step of its last tool call, `waiting` with its `agent` when
that call is `Task` or `Agent`, and `thinking` with no tool call. From a forwarded partial: a text
block's start or a text delta is `writing`, a thinking block's start `thinking`, a tool block's
start `working` with that call as the step, its tool named and its `input` null, which the call's
`assistant` line fills in, keeping the step's `since`. A partial that leaves the line as it is
writes nothing. A sub-agent's line, and any other, keeps the state, a `starting` one becoming
`thinking`. A partial's move takes the Session's lock and writes nothing once the Turn has ended.
The relay moves only a `running` Session's line: one stopped under its turn has none.

## The records

A record is one of four kinds:

| Kind | What it is | Its Turn |
|---|---|---|
| `claude` | a line of the raw response stream, as `claude` printed it, with its controller session and the raw offset after it | the turn it came in |
| `result` | the worker's `result` frame, `{turn, result, isError, interrupted}` as sent, with its controller session and offset | the turn it ended |
| `send` | a person's message, in its place among the lines; its words are the Turn's `words`, and its author the Turn's | the Turn it sent |
| `server` | the server's own line, a JSON object whose `type` says which: `starting`, `start-failed`, `send-failed`, `session-gone`, `restarting`, `environment-stopped`; `effect`, a tool call's ([`mcp.md`](mcp.md)); on a chat's Session, `closed`, its last ([`chats.md`](chats.md)); on the Session that registered a document, `read-failed` and `write-back-refused` ([`round-trip.md`](round-trip.md)) | a `send-failed`, `restarting`, `environment-stopped` or `effect` its Turn's; the others none |

**The writer.** `SessionRecordService.append(session_id, kind, *, payload, turn_id, raw_offset,
controller_session)` is the only one: in the caller's transaction it locks the Session row, reads
the last record, writes the next `seq`, and wakes the Session's hub once the transaction commits.
The lock is held until the transaction ends, so a caller commits one record per transaction. A
transaction that ends a Session's stream (`ended` or `failed`) without writing a record registers
`after_commit(session_stream_service.waker(id))`, or the open views never receive `end`.

**The one read.** `read_records(db, session_id, *, after=0, before=None, kind=None,
payload_type=None, limit, newest_first=False)`, `payload_type` the payload's `type` to filter on, is
the only query of `session_records` in the server. `TestTheOneRead`
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
handle) and `message`, the Turn's `words`.

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
ones, the outage being off in a fresh process; the jobs `read` and `write-back` run what the
registered documents owe ([`round-trip.md`](round-trip.md)). Each run resumes from the rows:

- **Sent or not.** Before it opens the stream, a relay's run reads the controller session's status
  snapshot. The controller has the turn when the session is `busy` or `interrupting`, or its `turn`
  is past the one in the Session's last `result` record of that controller session; otherwise the
  Turn, one written before its send, is sent now, unless the Session was stopped under it, when the
  Turn ends with no `result`. A `409 session-busy` on that send that a second snapshot shows sent is
  another process's send.
- **The start** with no controller session goes on from its environment as its rows have it and
  creates the session again; one with a controller session sends its Turn, the brief or a Resume's,
  unless the controller has it. The rows tell where the environment's bring-up stands: the take and
  a fresh Resume clear the environment's claim in their own transaction, and a create's or a
  reset's `202` sets it, so no claim on Pilot's own is the rename, the stop and the reset still to
  make, and a claim with no pod yet a bring-up whose settle is still to await. A reset whose `202`
  was lost reads as not made and is made again. A start released from `held` after its `202` keeps
  the environment's claim ([`controller.md`](controller.md)). Each write the start makes is conditional on the Session
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
(`test_sessions.py`, `test_testing_record.py`), on the fake controller
([`controller.md`](controller.md)): a test plays a turn's lines with `play` and ends it with
`finish`, and calls the relay's run on its own session once the fake holds the turn. The tests that
run a loop from STARTUP, a start through its turn to the shutdown timer's stop included, build their
services on `committed_app` with the `supervise` fixture ([`jobs.md`](jobs.md)). The races of the
lock order, a Resume against a start, two starts in one project and two starts in two projects
against the last slot, run on `committed_app` too (`TestLockOrder`), with the threads and lock waits
of `backend/tests/support/locks.py`. The autouse
`controller_outage` fixture gives each test an outage of its own, off. The stream's tests open test
connections on the connection manager and read the frames queued on them.
