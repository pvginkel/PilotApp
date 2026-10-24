# Work items

A work item is a Session Pilot started, standing on its project's timeline: its Item, its Work and
its Session share one id ([`record.md`](record.md)). This page is the work item as the API gives it
and as the screens show it: its status, its live event, its line and its actions on the timeline,
and its session log. What the server does to start it through the gate, stop it and resume it is
[`sessions.md`](sessions.md)'s, and the timeline it stands on [`timeline.md`](timeline.md)'s.

Nothing in the app places one yet: the record's testing route `POST
/api/testing/projects/<id>/work` does, on every stage but `prd` ([`projects.md`](projects.md)).

## Its status

Every timeline item carries `work`, null for every kind but `work` (`WorkSchema`,
`backend/app/schemas/timeline.py`). One reader builds it, `work_status(db, ids, *, unreachable)` in
`backend/app/services/timeline_service.py`, for the timeline, for Stop's and Resume's answers and
for the live event:

- `state`: its Session's, `held`, `starting`, `running`, `idle`, `stopped`, `failed` or `ended`;
- `current_line`: `{state, since, step, agent, text}`, the Session's current line
  ([`sessions.md`](sessions.md)) with every key present, null where it leaves one out, `step`
  `{tool, input}` and `agent` `{type, description}`; null while no turn is in flight;
- `environment`: `{id, name}`, the env chip and its link;
- `started_at`: the Session's, when the controller confirmed its session or a Resume's turn was
  sent, so that a held or a starting time does not count; null before;
- `error`: only while `failed`, the latest Turn's error, else the Session's: a turn's failure is its
  Turn's, a start's the Session's;
- `autopilot`: the switch's setting its start was briefed under;
- `held_reason`: why the gate holds it as the gate reads now, `paused` or `controller_unreachable`;
  null unless `held`, and while the gate has opened for it and its release is under way;
- `stopped_at` and `stopped_by`, the person who stopped it by Stop, Finish or Archive: only while
  `stopped`, `stopped_by` null when no person did;
- `stopped_cause`: `environment_stopped`, `environment_deleting` or `environment_gone` while it is
  `stopped` with no person's stop, its environment stopped under its turn, read from the session's
  last record; null for a person's stop and for an interrupt made elsewhere.

A work item waits on you while `stopped` or `failed`, which its project's badge counts
([`projects.md`](projects.md)). It is done at the end of a turn neither interrupted nor in error
([`sessions.md`](sessions.md)), cause `turn_ended`, by no one, or by Finish's close, and it then
draws as its done line ([`timeline.md`](timeline.md)).

## Live

A write of a work item's state, its current line, its `started_at` or its `error` emits the bus's
`WorkMoved(project_id, work_id)` in its transaction, and `ProjectChanged` too when its state moved,
since that moves the project's tab and head (`work_moved`, `backend/app/services/work_status.py`);
equal events of one transaction go out once. A Chat's Session has no work item: its state's move
raises `ProjectChanged` alone. A pause and a resume move the reason on the project's held items,
each a `WorkMoved`. `ProjectEventService` sends a `WorkMoved` to every person's connections as the
SSE event `work_moved`, `{project_id, item_id, work}`, `work` read after the commit, and nothing for
a Session with no work item.

`useProjectEvents` (`frontend/src/hooks/use-project-events.ts`) writes each `work_moved`'s `work`
into the item in its project's timeline as read, with no read of its own, and the session log over
it follows. A move heard while that timeline is being read goes over the read once it lands.

## On the timeline

An open work item (`WorkItem`, `frontend/src/components/timeline/work.tsx`) is:

- **Its head**, an item's head ([`timeline.md`](timeline.md)), with the env chip, the environment's
  name linked to KubeCoder's Open by its id (`EnvironmentLink`, [`ui.md`](ui.md)), and, while
  `running` with a `started_at`, "running N min" with a pulse: "under a minute", "12 min", "1 h 5
  min", "3 h", "2 days", counted again every 15 s on the browser's clock.
- **Its title.**
- **Its one line** (`workLine()`, `frontend/src/lib/utils/status-labels.ts`): a held item's reason,
  "Paused" or "Waiting for the controller"; else its current line in the chat's working cue
  (`WorkingCue`), the server's own words while it starts or its environment restarts, "Thinking",
  "Writing", "Working" or "Waiting for the <type> agent", with the latest step beside it, worded as
  the chat words a call, or the sub-agent's description; "Starting" before a start's first line,
  and "Waiting for Pilot" for a running one with none; "Stopped · <time>", with the cause of a stop
  made elsewhere ("<environment> was stopped", "… is being deleted", "… is gone"); "Failed ·
  <error>"; and nothing once `idle` or `ended`.
- **Its actions**, while `running`, `starting` or `held`: Session log, then Stop. Stop asks first in
  the actions' place, "Stop the session? Its turn ends where it is; Resume sends it on.", with Stop
  it and Cancel, which takes the focus; Esc or Cancel puts the focus back on Stop, and the question
  goes as the item leaves those states. While `stopped` or `failed`: Resume, then Session log;
  Resume is disabled while the project is archived, as its head's switch is (D012), the API
  refusing it until Bring back. Otherwise Session log alone.

Stop and Resume (`useStop`, `useResume`, `frontend/src/hooks/use-work-acts.ts`) call
[`sessions.md`](sessions.md)'s routes and write the answer into the cached timeline, only while the
item there is still in a state the act was made from (`moveWork`). A refusal is the query client's
toast in the API's words, and Resume, or the question, stays offered.

## The session log

At `/projects/<project>/sessions/<session>`, the item's id, the project's route opens the session
log in the overlay over the timeline (`SessionLogOverlay`,
`frontend/src/components/overlay/session-log-overlay.tsx`; the overlay is
[`documents.md`](documents.md)'s). An open item's Session log and a done work line's Open go there.
An address that names no work item of the project reads "The session log did not load".

- **Its head**: "Session log", over the item's title, its environment's link and the session's id.
- **Its body**: the session's records rendered as the chat renders a reply, one reply per turn
  (`ReplyBody`), bare in the log's column, 6px in from either side (D002): the text as Markdown, the
  runs of tool calls with their summaries, a sub-agent's card with its own steps, the phantom of the
  text block under way, and a failed turn's error. An earlier turn ends on its time, with " ·
  Stopped" after an interrupted one and " · Failed" after a failed one.
- **Its tail**: while the item is held, starts or runs, the working cue: the held reason, what the
  turn in flight is doing, or "Starting" and "Waiting for Pilot" before its first record. Otherwise
  how it ended (`sessionLogTail()`): "Stopped by you · <time>", "Stopped by <name> · <time>", the
  cause of a stop made elsewhere, "Stopped", "The turn ended · <time>", or "Failed", the error over
  it where the last turn shows none.
- **It follows the item's `work`** as the timeline holds it, live, so that a Resume carries the log
  on, and it sticks to its end while it grows: only the reader's own scrolling up, by the wheel, a
  key or a drag, lets go, and scrolling back down to the end picks it up again (`useStickyBottom`).

The records come through `useChatStream` on `sessionTransport`
(`frontend/src/lib/chat/transport.ts`, `hooks/use-session-transport.ts`): it subscribes a view of
the session on the browser's SSE connection, reads the records by page from the first, then takes
the frames that came meanwhile, a record it got both ways once ([`sessions.md`](sessions.md) has the
routes). A read or a subscribe that fails drops the stream, which reopens after its last record, and
so does a new SSE connection. The stream's `end` ends nothing here: the tail follows `work`.

**The view.** A record outside any Turn, the start's lines, a failed start and a gone session,
falls in the Turn in flight, else in the next one. A Turn ends at its `result`, at a failed send or
start, at its environment stopped under it, or, where it ended with no record, where a later Turn's
records begin; a call or a sub-agent still running then was stopped with it, and draws with no
spinner. A Stop of a held or a starting item ends its Turn with no record. An `isError` result shows
its text as the failure, or "The turn failed." where it has none.

**The chat's view code** is the chat mockup's, carried over for the session log and shared with
the chat to come: `frontend/src/lib/chat/` (the records on the API's record types, `claude`'s lines,
the stream's state, the view, the tool summaries, the activity, quotes, times and the transport),
`frontend/src/components/chat/` (a reply's body and cue, the phantom, the steps, a tool call, a step
line, the delta fade, a quote chip, the working cue and the actions' context), and the hooks
`use-chat-stream`, `use-now` and `use-sticky-bottom`. Its Markdown is the app's one renderer
([`ui.md`](ui.md)).

## Testing it

The status, its event and the routes are pinned in `backend/tests/services/test_work_status.py`,
`test_timeline_service.py`, `test_project_event_service.py`, and
`backend/tests/api/test_sessions.py` and `test_testing_record.py`. The browser suites are
`frontend/tests/work/`: `harness.spec.ts`, `timeline.spec.ts`, `stop-resume.spec.ts`,
`session-log.spec.ts` and `switch-warning.spec.ts`.

Each Playwright backend's controller is the fake it serves itself
([`controller.md`](controller.md)), which the `controller` fixture
(`frontend/tests/support/controller.ts`) drives: `environment({name?, status?})` adds an
environment, `stopped` and named by its unique id unless told, and answers its id; then, by the
environment's id, `play(env, session, lines)` (answering the lines' offsets), `finish(env, session,
outcome?, result?)`, `restart`, `setStatus`, `settleStarts`, `removeEnvironment`, `capped` and
`unreachable`; and `outage(on, answer?)`, returning once the backend reads the controller as asked,
and `dropStreams()`, once the fleet stream has reconnected. After a spec that left the controller
unreachable, the fixture has it answer again. Pilot's headless sessions in an environment are
`claude-1`, `claude-2`, … in the order it creates them, a Resume that re-creates its session making
the next. `rawTurn(name)` reads the backend suite's invented turns. The worker's `conditions`
fixture reads what the gold bar reads, and waits at the worker's start for the backend's first
outage, its fleet stream's refused first open, to end. The fleet stream reconnects on the
supervisor's backoff, up to 30 s, so a spec whose outage must end sets a timeout of its own.

`projects.startWork(project, {environment_id, title, brief, cwd, step?})` places a work item,
answering its id; `projects.work(project, item)` reads its `work`, `projects.records(session,
after?)` its records, and `projects.stop(id)` and `projects.resume(id)` call the routes as the
signed-in person. The `timeline` page object's `item(id).work` reads the open item (`environment`,
`running`, `line`, whose `data-state` is the Session's state, `cue`, `step`, `sessionLog`, `stop`,
`resume`, `stopConfirm`), and the `sessionLog` fixture the log (`sessionLogAddress()`). A spec
placing an item in a project while a work item's start there still writes waits for that item to
run first.
