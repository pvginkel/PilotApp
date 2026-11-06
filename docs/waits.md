# Waits

A wait is an item the brain adds to wait on something outside Pilot: a **card wait**, on cards of
the tracker entering one of its states, or a **timed wait**, on its due time. The server only fires
it. A card's change of state the tracker posts, the due time, or a person's request each record a
firing on the wait. The server batches a wait's firings into one run of the brain, which judges
them, then either closes the wait through `mark` with a note or leaves it open. This page is the
waits as built: what fires them, the run, the close, their settings and their testing routes. The
brain's tools are [`mcp.md`](mcp.md)'s, the run as a job of Pilot's own [`work.md`](work.md)'s, and
the wait on the timeline [`timeline.md`](timeline.md)'s.

| Piece | Does |
|---|---|
| `WaitService` (`wait_service.py`) | a wait's add and its close; its firings, a transition's, the due time's and a person's request; the request's rule; the batch's read and hold; a run's take of its firings and the conversation it resumes; what the brain did with each firing |
| `TrackerEventService` (`tracker_event_service.py`) | the tracker-events endpoint's admission and its read, by each tracker's adapter, `youtrack` the one there is |
| `WaitTimer` (`wait_timer.py`) | the timer `wait-due`, which fires the timed waits |
| `WaitBatcher` (`wait_batcher.py`) | the timer `wait-batch`, which places a wait's run |

They are in `backend/app/services/`, and the endpoint in `backend/app/api/tracker_events.py`. The
record is the tables `waits`, `wait_firings` and `card_transitions` ([`record.md`](record.md)).

## A wait

- **A card wait** has `cards`, ticket ids by the deployment's pattern (`TICKET_ID_PATTERN`,
  [`ui.md`](ui.md)), and `states`, the tracker's names. It fires whenever one of its cards enters
  one of its states.
- **A timed wait** has `due_at`. It fires once, when its due time comes.

The brain adds one with `add_item` ([`mcp.md`](mcp.md)), at the project's next place, on the plan
task `step` names. The add refuses an empty list, a card that is no ticket id, a list that names a
card twice or a state twice, case-insensitively, and a due time not ahead. What a wait waits on is
fixed at its add: nothing edits it, and a card to add means closing the wait and adding another.

A wait stays open until the brain's `mark` closes it with a note ([below](#the-close)), or until
Finish's close of the open items, which writes none. A person's Done is refused on it. An open wait
makes its project's status `waiting_on_event`, and it never counts in the badge
([`projects.md`](projects.md)).

## What fires it

Each firing is a row of `wait_firings` on its wait, numbered from 1 within the wait, with its
cause (`transition`, `due` or `requested`) and `fired_at`, the server's time at its record. A firing
is pending until a run takes it. Only an open wait of an open, unarchived project fires: a card's
change while the project is archived or finished fires nothing, and an archived project's overdue
timed wait fires at the first tick after Bring back. Each firing moves the project's
`timeline.json` and raises `project_changed`, so an open timeline shows it at once.

### A card's change of state

**`POST /api/tracker-events/<tracker>`** takes a tracker's delivery. It is registered on the app,
outside the API blueprint, so the OIDC gate never sees it ([`sign-in.md`](sign-in.md)). `youtrack`
is the one tracker; any other name answers `404` and is not counted.

YouTrack's Webhook Triggers app posts every card update, its `issueUpdated` event, to production's
Service at `http://pilot.pilot-prd.svc.cluster.local/api/tracker-events/youtrack` (D129). The app's
configuration lives in the operator's YouTrack configuration, not here, and there is no workflow
rule and no bearer of Pilot's own. Each delivery carries the instance's one shared webhook token in
the header `X-YouTrack-Token`. The backend compares it, in constant time, with
`YOUTRACK_WEBHOOK_TOKEN` and answers `401` to anything else. With the setting empty, every delivery
is refused. Production alone sets it ([`deployment.md`](deployment.md)), so the dev stage's endpoint
refuses every delivery, and a check there delivers through the testing route
([below](#testing-it)).

The `youtrack` adapter reads the body by D129's mapping:

- the card is `id`, its readable id;
- the state it left is `oldValue.name` on the `State` entry of `changedFields`, and none where
  `oldValue` is null;
- the state it entered is `value.name` on that entry;
- when is `updated`, in epoch milliseconds;
- by whom is `updatedBy.login`, and no one where `updatedBy` is null.

A delivery whose `event` is not `issueUpdated`, with no `State` entry, or whose State was emptied
(`value` null) is answered `{"fired": 0}` and dropped. A body that is no JSON object or has no
`event` is refused with `400`. So is a State change with no `id` or `updated`, an `updated` outside
epoch milliseconds, or a State value that is no enum element.

The match runs inside the request. Every open card wait of an open, unarchived project whose `cards`
hold the card, exactly, and whose `states` hold the state entered, case-insensitively, fires once.
Each matching wait is locked and read open before anything is written. The transition is recorded
in `card_transitions` only when a wait fired, with the tracker's time and the server's
`received_at`, and every wait it fired shares one `fired_at`. The reply is `{"fired": n}`, how many
waits fired. The request records the firings and returns; the run comes after, from the batcher.

Nothing reads YouTrack: no poll, no check at add, no recovery of a missed delivery and no dedupe of
a redelivered one. Its one credential is the webhook token. YouTrack's app never retries a post that
failed, so a delivery sent while Pilot is down or restarting is lost. The card wait it was for stays
unfired until one of three things happens: a person presses Check now, the card enters a watched
state again, or a backstop timed wait the brain set comes due (D130).

### The due time

The timer **`wait-due`** runs on every tick. Each open timed wait of an open, unarchived project
whose due time has passed, and that has not yet fired `due`, fires `due` once. The first tick after
a restart fires what came due while no process ran. The timer needs no controller. A timed wait
therefore fires at the first tick after its due time, `SCHEDULER_TICK_SECONDS` apart
([`jobs.md`](jobs.md)).

During a roll two processes run the timer at once. Each fires a wait only under the Wait's row,
which it skips while the other holds it, and checks again under the row that the wait has not fired
`due`. The unique index `uq_wait_firings_due` stands behind both.

### A person's request

**`POST /api/items/<id>/request`** records a `requested` firing by the caller
([`timeline.md`](timeline.md)): *Check now* on a card wait, *Skip wait* on a timed wait. It reads
the wait under its Project's row, held shared, and then the Wait's. It refuses with `409` and the
reason, checked in this order:

1. "its project is archived";
2. "its project is finished";
3. "the wait is done";
4. "Pilot is checking", while a firing of the wait is pending or a run of it is in flight.

An item that is no wait is refused too. The timeline's read gives the same rule as the wait's
`request` (`WaitService.refusals`), which draws the button. Once a timed wait's due time has fired
and the wait is left open, only a request fires it again.

## The run

### The batch

The timer **`wait-batch`** needs the controller and runs after `wait-due` in each round. A wait gets
its run when three things hold:

- the wait is open, and its project is open and unarchived;
- its oldest pending firing is `WAIT_QUIET_WINDOW_SECONDS` old (5 by default);
- no run of the wait is in flight.

The run is one job of Pilot's own, trigger `wait_fired`, its trigger item the wait, titled `Checking
"<wait title>"`, shown on the wait's line or its head, the latest run where there were several
([`work.md`](work.md)). Firings recorded later join it until its brief, and none
extends the window. A firing recorded after its brief waits for the next run, which is placed only
once this one has ended. The window counts from each firing's `fired_at`, so a restart reads the
same rows. The tick is the window's granularity, so a run is placed between the window and one tick
later.

A run is in flight while any of these holds:

- it is held at the gate or queued behind its project's other jobs;
- it is starting, or running, a follow-up turn included;
- its nudge is owed, as for a run the usage limits or the pause halted, or one at the quota wall
  ([`usage.md`](usage.md)).

During a roll each process places a run only under the Project's row, held exclusively, and then the
Wait's, and reads the batch again there. The second process waits for the first to commit, then
finds its run in flight, so a batch gets one run. A run starts through the gate as every job does:
held while its project is paused, and one at a time behind the project's other jobs
([`sessions.md`](sessions.md)).

### Its brief

At its brief the run takes every firing of its wait still pending, under the Wait's row. A firing
recorded before the brief is the run's; one recorded after stays pending for the next run. What
the brain did with each firing is that run's ([below](#what-the-brain-did)).

**A fresh run** gets the full brief: `/plan`, kind `a wait fired`, opening with the frame, the
switch and the pause line, as every job's brief does ([`work.md`](work.md)). Then come the wait's
line, `The wait: "<title>" (<id>), a card wait on <cards> for <states>; waiting since <stamp>; task
<id>.`, which reads `a timed wait due <stamp>` for a timed wait and leaves the task out where the
wait has none. Then `Firings pending, oldest first:` and a line per firing:

- `- <stamp> · <card>: <from> → <to>, by <login>` for a transition, `<card> → <to>` where the tracker
  gave no state left, and with no `, by` where it named no one;
- `- <stamp> · due <stamp> — fired at its due time`;
- `- <stamp> · the operator's request (Check now|Skip wait), by <handle>`.

The brief ends with the open notes of the wait's task and of the plan, and the deferrals without a
home.

**A resumed run.** A run can resume the conversation of the wait's previous run, the latest other
run of the wait that was briefed. It does so when that run's turn ended neither failed nor stopped
(`idle` or `ended`), on a conversation, within `CACHE_EXPIRATION_TTL` before this brief: 3300 s, the
prompt cache's 55 minutes. Its first Turn is then the follow-up alone, with no slash command:
`Another firing of "<title>" since your last run:` and the same firing lines. Its switch is the
previous run's, which the conversation keeps. In every other case the run is fresh.

A previous run that failed or was stopped makes the next run fresh. A resume the controller
refuses fails the run at its create, as any refused create does, and there is no fallback; the next
run is then fresh, so a refused conversation is never tried twice. A Retry is always fresh. It is
briefed with the firings the runs it retries took, which stay theirs, and with any still pending.

### The close

The brain closes a wait with `mark`: `done`, with no `for`, and a `note` saying what it read, when,
and the action it started after ([`mcp.md`](mcp.md)). The close is done cause `marked`, by Pilot,
and the marking Session consumes it on the spot, so it never offers Undo. Its note goes into
`waits.done_note` with the close and never changes. A done wait, or one in an archived project, is
refused. Finish's close writes no note.

A wait's run held before its brief when the wait closes is withdrawn. Its Session is stopped by no
one and never starts, its work item is done `withdrawn` and shows nowhere, the wait showing the run
before it where it had one, and its firings are left untaken. A run already
briefed keeps the firings it took. The close locks that run's Session before the Wait's row, the
brief's own order, so a run briefed first keeps its firings and a run withdrawn takes none. Retry of a wait's run is refused while
its wait is done ("the wait it follows is done") or while another run of the wait is in flight
("another run of the wait it follows is in flight"), the batcher's own rules
([`sessions.md`](sessions.md)).

### What the brain did

The timeline shows, beside each firing, what the brain did with it. This is read from the run that
took the firing, followed through its Retries, and from the wait's close; it is never stored:

- `closed`, where a run of that chain is the Session that marked the wait done;
- `pilots_turn`, Pilot's turn, while the chain's latest run is in flight, or while no run has taken
  the firing and the wait is open;
- `left_open`, once the chain's latest run ended neither failed nor stopped;
- none, once that run failed or was stopped, or where no run took the firing before the wait
  closed.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `YOUTRACK_WEBHOOK_TOKEN` | empty | YouTrack's webhook token, which each delivery carries in `X-YouTrack-Token`; empty refuses every delivery |
| `WAIT_QUIET_WINDOW_SECONDS` | 5 | how old a wait's oldest pending firing is when the batcher places its run; above 0 |
| `CACHE_EXPIRATION_TTL` | 3300 | how long after its previous run's turn ended a wait's run resumes that run's conversation; above 0. An unset `CHAT_CLOSE_TIMEOUT` takes it ([`chats.md`](chats.md)) |

The chart sets only the token, on production ([`deployment.md`](deployment.md)); both stages run
on the other two defaults.

The metrics, on the backend's `/metrics`:

- `pilot_tracker_events_received_total{tracker}`: every delivery to a known tracker;
- `pilot_tracker_events_refused_total{tracker, reason}`: deliveries refused, `token` where the token
  did not verify and `body` where the adapter could not read it;
- `pilot_tracker_waits_fired_total{tracker}`: the card waits the deliveries fired.

A delivery that matches no wait is counted as received and nothing else. The log lines are `<card>
entered '<state>': <n> card waits fired`, `<n> timed waits fired due` and `<n> runs placed for
waits' firings`.

## Testing it

Five of the record's testing routes, open on every stage but `prd` (D027,
[`projects.md`](projects.md)), drive the waits:

- `POST /api/testing/projects/<id>/waits` `{kind, title, cards, states}` or `{kind, title, due_at}`,
  with an optional `placed_at`, adds a wait by the project's session as `add_item` adds one, and
  answers `201` `{id}`. A `placed_at` before now makes the wait read as added then, the add's
  refusals holding as of then: "Due 5 minutes ago" is a `due_at` five minutes back and a
  `placed_at` before it. It answers `400` for a field of the other kind, `404` for an unknown
  project, and `409` for a project with no session, a `placed_at` ahead, or the add's refusal.
- `POST /api/testing/tracker-events/<tracker>` delivers its body as the endpoint takes it, past the
  token and the count of deliveries received, and answers `200` `{fired}`. It answers `400` for a
  body the adapter cannot read and `404` for an unknown tracker. The body is YouTrack's
  `issueUpdated`.
- `POST /api/testing/waits/due` runs the timer's tick now and answers `200` `{fired}`.
- `POST /api/testing/waits/<id>/run` places the wait's run now, as the batcher places it once the
  window has passed, and answers `201` `{id}`, the run's. It answers `409` where no run is due, or
  with no controller or no store environment configured.
- `POST /api/testing/waits/<id>/close` `{note}` closes the open wait as `mark` does, by the wait's
  latest run briefed, else by the project's session, and answers `204`. It answers `409` where the
  wait has no run briefed and its project no session, where the project is archived, or where the
  wait is done.

The backend's tests are `tests/services/test_wait_service.py`, `test_wait_timer.py`,
`test_wait_batcher.py` (on the fake controller: the burst, the window, a firing while the run is
queued and during it, the resume and its follow-up, past the TTL, a refused resume, a wait closed
while its run is queued, two backends), `test_tracker_event_service.py`, `test_brief_service.py`'s
and `test_job_service.py`'s `TestWaitFired`, and `tests/models/test_wait.py`. The routes are tested
in `tests/api/test_tracker_events.py`, the OIDC gate included, `tests/api/test_items.py`'s
`TestRequest` and `tests/api/test_testing_record.py`. The deliveries are invented, in
`tests/support/youtrack.py`.

The browser suite's backends wait a day before the batcher places a run
(`WAIT_QUIET_WINDOW_SECONDS` in `frontend/tests/support/backend-env-extensions.ts`), so a firing
stays pending there until a spec places its run. The `waits` fixture (`frontend/tests/support/waits.ts`)
wraps the routes: `add`, `transition`, `due`, `run` and `close`. A run starts in the fake
controller's store environment, which the `chats` fixture readies, and the fake's `finish` of its
turn leaves its firings `left_open`. The specs are `frontend/tests/timeline/waits.spec.ts`.
