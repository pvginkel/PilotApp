# Work items

A work item is a Session Pilot started, standing on its project's timeline: its Item, its Work and
its Session share one id ([`record.md`](record.md)). This page is the work item as the API gives it
and as the screens show it: its status, its live event, its line and its actions on the timeline,
and its session log. What the server does to start it through the gate, stop it and resume it is
[`sessions.md`](sessions.md)'s, and the timeline it stands on [`timeline.md`](timeline.md)'s.

The brain places one with `add_item`, started on add by its repository ([`mcp.md`](mcp.md)), and the
record's testing route `POST /api/testing/projects/<id>/work` places one so, on every stage but
`prd` ([`projects.md`](projects.md)). The app places one itself as a run's continuation:
the close that leaves none of the documents a work item's run registered open places the work item
that continues its conversation, titled as the run, on its plan task while the plan still has it,
after the answered items, and the end of a pre-ruling pass that asked the writer places the
clarification run that puts its questions to the run's writer, on that run's conversation
([`round-trip.md`](round-trip.md)). Create project, a worker's turn end and a person's close of an
item of Pilot's own place the jobs of Pilot's own ([below](#pilots-own-work)).

## Its status

Every timeline item carries `work`, null for every kind but `work` (`WorkSchema`,
`backend/app/schemas/timeline.py`). One reader builds it, `work_status(db, ids, *, unreachable)` in
`backend/app/services/timeline_service.py`, for the timeline, for Stop's and Resume's answers and
for the live event:

- `state`: its Session's, `held`, `starting`, `running`, `idle`, `stopped`, `failed` or `ended`;
- `current_line`: `{state, since, step, agent, text}`, the Session's current line
  ([`sessions.md`](sessions.md)) with every key present, null where it leaves one out, `step`
  `{tool, input}` and `agent` `{type, description}`; null while no turn is in flight;
- `environment`: `{id, name}`, the env chip and its link, as the Environment's row stands: null
  until its start has one; a done item's names the project that took the environment after it, or
  its id while it is free ([`controller.md`](controller.md));
- `started_at`: the Session's, when the controller confirmed its session or a Resume's turn was
  sent, so that a held or a starting time does not count; null before;
- `error`: only while `failed`, the latest Turn's error, else the Session's: a turn's failure is its
  Turn's, a start's the Session's;
- `autopilot`: the switch's setting its start was briefed under;
- `held_reason`: why the gate holds it as the gate reads now, `paused`, `controller_unreachable`,
  `slot`, a job's `queue`, or a worker's run's `conversation`, another run on the conversation it
  resumes; null unless `held`, and while the gate has opened for it and its
  release is under way;
- `held_running`: while it is held for a slot, the running work items of the maximum that closed
  the gate, across every project or its project's own ([`sessions.md`](sessions.md)); else null;
- `stopped_at` and `stopped_by`, the person who stopped it by Stop, Finish or Archive: only while
  `stopped`, `stopped_by` null when no person did;
- `stopped_cause`: `environment_stopped`, `environment_deleting`, `environment_error` or
  `environment_gone` while it is `stopped` with no person's stop, its environment stopped under its
  turn or settled in error, read from the session's last record; null for a person's stop and for
  an interrupt made elsewhere;
- `pilots_own`: whether it is Pilot's own work, a job ([below](#pilots-own-work)), false for a
  worker's run;
- `retried`: `{id, at}`, the job a person's Retry of this one placed and when; null while it is not
  retried, and always for a worker's run.

A work item waits on you while `stopped` or `failed`, a job only until it is retried, which its
project's badge counts ([`projects.md`](projects.md)). It is done at the end of a turn neither
interrupted nor in error ([`sessions.md`](sessions.md)), cause `turn_ended`, by no one, or by
Finish's close, and a job withdrawn before its brief by an Undo, cause `withdrawn`
([below](#pilots-own-work)); it then draws as its done line ([`timeline.md`](timeline.md)).

## Live

A write of a work item's state, its current line, its `started_at` or its `error` emits the bus's
`WorkMoved(project_id, work_id)` in its transaction, and `ProjectChanged` too when its state moved,
since that moves the project's tab and head (`work_moved`, `backend/app/services/work_status.py`);
equal events of one transaction go out once. A Chat's Session has no work item: its state's move
raises `ProjectChanged` alone. A pause and a resume move the reason on the project's held items,
each a `WorkMoved`, and the release of the held starts tells every work item it still holds,
since the outage's turn or the slot's count may have moved its reason. `ProjectEventService` sends a `WorkMoved` to every person's connections as the
SSE event `work_moved`, `{project_id, item_id, work}`, `work` read after the commit, and nothing for
a Session with no work item.

`useProjectEvents` (`frontend/src/hooks/use-project-events.ts`) writes each `work_moved`'s `work`
into the item in its project's timeline as read, with no read of its own, and the session log over
it follows. A move heard while that timeline is being read goes over the read once it lands.

## On the timeline

An open work item (`WorkItem`, `frontend/src/components/timeline/work.tsx`) is:

- **Its head**, an item's head ([`timeline.md`](timeline.md)), with the env chip once its start has
  an environment, but for Pilot's own work, the environment's name linked to KubeCoder's Open by its
  id (`EnvironmentLink`, [`ui.md`](ui.md)), and, while `running` with a `started_at`, "running N
  min" with a pulse: "under a minute", "12 min", "1 h 5 min", "3 h", "2 days", counted again every
  15 s on the browser's clock.
- **Its title.**
- **Its one line** (`workLine()`, `frontend/src/lib/utils/status-labels.ts`): a held item's reason,
  "Paused", "Waiting for the controller", "Waiting for a slot · N running", "Waiting for the job
  before it" or "Waiting for the run before it"; else its current line
  in the chat's working cue (`WorkingCue`), the server's own words while it starts ("Preparing
  <environment>", "Starting <environment>", "Creating the session", the trailing "…" left out) or
  its environment restarts, "Thinking", "Writing", "Working" or "Waiting for the <type> agent", with
  the latest step beside it, worded as the chat words a call, or the sub-agent's description. A
  call whose input still streams in is its verb alone ("Editing"), and its target joins it once the
  call's line gives it; an empty target is not drawn. "Starting" before a start's first line, and "Waiting for
  Pilot" for a running one with none; "Stopped · <time>", with the cause of a stop made elsewhere
  ("<environment> was stopped", "… is being deleted", "… is gone", "… is in error"); "Failed ·
  <error>"; and nothing once `idle` or `ended`. A retried job's line has a second under it, "Retried
  as a new job below · <time>".
- **Its actions**, while `running`, `starting` or `held`: Session log, then Stop. Stop asks first in
  the actions' place, "Stop the session? Its turn ends where it is; Resume sends it on.", with Stop
  it and Cancel, which takes the focus; Esc or Cancel puts the focus back on Stop, and the question
  goes as the item leaves those states. While `stopped` or `failed`: Resume, then Session log;
  Resume is disabled while the project is archived, as its head's switch is (D012), the API
  refusing it until Bring back. Pilot's own work has no Stop or Resume: a job `stopped` or `failed`
  and not retried offers Retry, then Session log, Retry disabled while the project is archived.
  Otherwise Session log alone.

Stop and Resume (`useStop`, `useResume`, `frontend/src/hooks/use-work-acts.ts`) call
[`sessions.md`](sessions.md)'s routes and write the answer into the cached timeline, only while the
item there is still in a state the act was made from (`moveWork`). A refusal is the query client's
toast in the API's words, and Resume, or the question, stays offered. Once this browser's Stop it or
Resume lands and swaps the two, the keyboard focus that was on the button that went goes to the
other's resting button, Resume after a Stop and Stop after a Resume (`useHandoff`, `work.tsx`); a
swap another browser's act made, or one after the focus moved elsewhere meanwhile, moves no focus.
Retry (`useRetry`) calls its route the same way, and once this browser's Retry lands, the focus that
was on it goes to Session log.

## Pilot's own work

A background job of Pilot's own is a work item too (`JobService`,
`backend/app/services/job_service.py`): a fresh brain session in the store for each trigger, ending
with its turn. It is placed in its caller's transaction, under the project's row held exclusively,
at its trigger's instant:

- its Session is kind `job`, in the store repo's root, on the brain's model and effort
  ([`chats.md`](chats.md)), `held`, with no Turn, its `created_at` the trigger's instant;
- its Work has the trigger that started it, the Item that set it off as its trigger item where it
  has one, and no repository;
- its Item is next on the timeline.

It starts through the gate as a chat does (`start_brain`, [`sessions.md`](sessions.md)): held while
its project is paused, the setup's never, a Retry's included, and while another job of its project
is before it, so that a project's jobs
run one at a time in the order their triggers came, the chat beside them; taking no slot; boxed to
the project's folder with `pilot-store` handed to it, and its create made again for a bounded time
while that folder is not on disk. Its brief is composed as it leaves the gate, from the record as it
then stands (below). Its item is done at its last turn's end, the follow-up's where it gets one
([`chats.md`](chats.md)), and its project's next job goes on then. Neither a person's Stop or Resume
nor the brain's `stop_work` takes it ([`sessions.md`](sessions.md)); Finish and Archive stop it as
they stop every session. One job is placed per trigger, never one for several.

**The triggers.** Three place a job:

- **The setup**: Create project places it after the opening, titled "Setting up the project",
  trigger `setup`, and the setup runs under the pause Create writes, so the work items it places
  are held, each "Paused", until a person resumes the project ([`projects.md`](projects.md)).
- **A worker's turn ended**, trigger `worker_turn_ended`, its trigger item the run: after every
  worker's turn that ends neither interrupted nor in error, a continuation's and a clarification
  run's included, whether or not it registered documents, once the turn-end read has settled every
  document the run registered ([`round-trip.md`](round-trip.md)). A run that registered nothing has
  it placed in its turn end's own transaction; one that did, in the transaction of the read that
  leaves none of its documents awaiting it, a failed read settling too. It is titled `Pre-ruling
  <places>`, each registered document's place `<folder>/<seq>` in the order registered, joined "a, b
  and c", or "Deciding what is next" for a run that registered nothing. One per run, and none in a
  finished or archived project; a Stop, a failed turn or an environment stopped under the session
  places none.
- **An item of Pilot's own is done**, trigger `item_done`, its trigger item the item, titled
  "Deciding what is next": a person's close of an item a session of Pilot's own added, a chat's or a
  job's, in the close's transaction ([`engine.md`](engine.md)): answered, Done, an action's Done,
  Reviewed. A notice's Read, Pilot's own Done, Finish's close, a registered document's close, an
  item a worker's session added and the archive question, which no session added, place none.

**The briefs** (`BriefService.job`), each Markdown, its blocks a blank line apart, a line that does
not hold left out, open with the skill line and the frame, `Pilot's brief · <kind> · project
"<name>" · /work/Projects/<folder> · <UTC stamp>`, the stamp the brief's own and the name left out
where the project has none, then the switch's line, as the chat's brief words
it, and, for a trigger that came while the project was paused, `Paused <stamp> to <stamp>: this
job's trigger happened while the project was paused; the record moved on meanwhile.`, that pause
from its start to the resume that let the job go on, which the setup's never carries, since the
pause holds no setup. Then by trigger:

- **The setup**: `/plan`, kind `the setup`; `The project was created <stamp> from draft-<number>;
  its folder is now /work/Projects/<slug>.`, `The draft: project.md (the opening item <id> holds
  the words that started it; the draft's copy and what the chat attached hang on it).` and `The
  plan: plan.json, empty.`. No notes.
- **A worker's turn ended**: `/pre-rule`, kind `a worker's turn ended`; the work item's line, `The
  work item: "<title>" (<id>)`, its plan task, repository, environment by its id and controller
  session by its name, each that it has, `; its turn ended <stamp>` and ` — the item's last line:
  "<line>"`, the last non-blank line of the text its turn ended with, where there is one; then
  `Registered this run, in the order registered:` and a line per document, `- <path> (<item id>) —
  published` or `— read failed: <reason>`, or `Registered nothing this run.`; then `Attached on the
  work item: 1 file (timeline.json lists it).` or `<N> files (timeline.json lists them).` where some
  are; then, where the work item was given claimed actions, its standing naming theirs, `The claimed
  actions given to this work item, as they stand:` and a line per action in timeline order, `-
  <path> (<item id>) <local id> open, claimed`, `… open, its claim gone`, or its close as the record
  holds it, a person's Done meanwhile included; then every open plan note by summary and the
  deferrals without a home, as the chat's brief has them ([`chats.md`](chats.md)).
- **The writer answered**, the job after a clarification run's turn, trigger `worker_turn_ended`,
  its trigger item the run ([`round-trip.md`](round-trip.md)): `/pre-rule`, kind `the writer
  answered`; `The clarification run: "<title>" (<id>), of the work item "<title>" (<id>)[, task
  <id>]; its turn ended <stamp>.`, the work item whose conversation it resumed; then per document
  the pass asked about, in timeline order, `Asked <stamp> on <path> (<item id>):`, a line per
  question, `- <local id>: <question>`, the block named `<local id> "<heading>"` where it has a
  section of its own, and the writer's answer as the document records it: `The writer's answer, as
  recorded on the document:` and `- <local id>: <part>` per block, its further lines indented two
  spaces; or `The writer's answer, as recorded on the document, whole — the reply did not keep the
  asked headings:` and the reply quoted, `> ` a line; or `The writer's answer: none — the run's turn
  ended with no text.`. Then the files attached on the run and what it registered, as a worker's
  turn's brief has them, and `This pass asks nothing: what is still unclear is the operator's, the
  clarification beside the ask.`, after `Registered this run: nothing.` where it registered nothing;
  then the open notes and the deferrals without a home. The pass it briefs asks the writer nothing
  ([`mcp.md`](mcp.md)).
- **An item of Pilot's own is done**: `/plan`, kind `an item of yours is done`; `The item: <path>
  (<item id>), <kind> "<title>"[, task <id>] — <close>.`, the close as the record holds it: a
  one-ask item's block answered or done, by whom and when, its channel and its note as given (a
  confirmation `answered Yes|No by <handle> at <stamp>`, an action `<id> done by …`, an answer an
  option's label, `Agree`, `deferred to <to>`, a question's words quoted, other words quoted with
  `(Other)`); a document's `Done by <handle> at <stamp>; its blocks:` and a line per block; a
  review's `Reviewed by <handle> at <stamp>`; then the open notes of the item's plan task and the
  plan's own, and the deferrals without a home.

The brief is the job's first Turn, written as it moves to `starting` ([`sessions.md`](sessions.md)):
at its placement, at its trigger's instant, when the gate lets it through then; else by the release
that moves it. The `item_done` job's brief consumes its item, which takes Undo from it
([`engine.md`](engine.md)).

**An Undo before the brief.** An Undo of the item while its `item_done` job is still held before its
brief, behind the project's other jobs or held by the pause, withdraws the job (D079): its Session
`stopped` by no one, with no Turn, and its work item done, cause `withdrawn`, by no one, offering no
Undo; the next close of the item places a new job. With the project idle the job is briefed in the
close's own transaction, so the item's Undo shows only while the job waits.

**Retry.** A job `failed` or `stopped`, whoever stopped it, its work item open, offers Retry (D078,
`POST /api/sessions/<id>/retry`, [`sessions.md`](sessions.md)): a fresh job for the same trigger,
trigger item and title, at the project's next place, behind every job already waiting, briefed as it
starts from the record as it then stands. Its brief reads its trigger's instant from the first job
of its chain, so a retried setup still says when the project was created, and an `item_done`
retry's brief consumes the item only if the job it retries did not. What the failed job wrote is
in the store and the record, and the new job's brief does not say so: a retried setup's reads as
Create's, `The plan: plan.json, empty.` included. The one retried is marked retried by the new
job before that one starts: it keeps its state, its open item and its session log, offers Retry no
more, and leaves the badge. A person has to press it: the server retries no job on its own. A job
withdrawn by an Undo, done, never ran, and takes no Retry.

On the timeline, a job's `pilots_own` is true. Its line has its session log, and neither the env
chip, the store's once its start takes it, nor Stop or Resume. Its session log's head names no
environment. A failed or stopped job shows so, offers Retry, and its project's badge counts it until
it is retried. A withdrawn job's done line says "Withdrawn by an Undo" under its title
(`workClosedLabel`).

## The session log

At `/projects/<project>/sessions/<session>`, the item's id, the project's route opens the session
log in the overlay over the timeline (`SessionLogOverlay`,
`frontend/src/components/overlay/session-log-overlay.tsx`; the overlay is
[`documents.md`](documents.md)'s). An open item's Session log and a done work line's Open go there.
An address that names no work item of the project reads "The session log did not load".

- **Its head**: "Session log", over the item's title, its environment's link once its start has
  one, but for Pilot's own work, and the session's id; and Discuss, quoting the work item into the
  chat ([`chats.md`](chats.md)).
- **Its body**: the session's records rendered as the chat renders a reply, one reply per turn
  (`ReplyBody`), bare in the log's column, 6px in from either side (D002): the text as Markdown, the
  runs of tool calls with their summaries, a sub-agent's card with its own steps, the phantom of the
  text block under way, a failed turn's error, each effect of the session's calls, and the server's
  word on a document the session registered, as a notice: "Could not read <path> because <reason>"
  for a read that failed at its run's end, "Could not write <path> back because <reason>" for a
  write-back the controller refused ([`round-trip.md`](round-trip.md)). A call that changed the
  record is its effect line in its own place, never inside a run of calls, a check before `<verb> ·
  <label>`, "Registered · inbox/3" or "Attached · <title>" ([`mcp.md`](mcp.md)) (`EffectLine`,
  `components/chat/tool-call.tsx`); its click goes to its block's address, else its item's
  ([`timeline.md`](timeline.md)), a draft's ask to the ask in the Draft tab, as a quote's chip does
  ([`ui.md`](ui.md)). An earlier turn ends on its time, with " · Stopped" after an interrupted one
  and " · Failed" after a failed one.
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

**The view.** A record outside any Turn, the start's lines, a failed start and a gone session, falls
in the Turn in flight, else in the next one. A Turn ends at its `result`, at a failed send or start,
at its environment stopped under it, or, where it ended with no record, where a later Turn's records
begin. A `read-failed` or `write-back-refused` record is written after the run's last Turn ended,
and stands at that Turn's end; a call or a sub-agent still running then was stopped with it, and
draws with no spinner. A Stop of a held or a starting item ends its Turn with no record. An
`isError` result shows its text as the failure, or "The turn failed." where it has none. An effect
stands on the call whose tool-use id it names, whether its record was written before or after the
call's `assistant` line: one whose call's line has not come yet waits for it, so a streamed log
shows it on its own first and then on its call, and one whose call no record shows, with no
tool-use id, is a step of its own in its record's place (`buildChatView`,
`frontend/src/lib/chat/view.ts`).

**The chat's view code** is the chat mockup's, shared by the session log and the Chat tab
([`chats.md`](chats.md)): `frontend/src/lib/chat/` (the records on the API's record types,
`claude`'s lines, the stream's state, the view, the tool summaries, the activity, quotes, times and
the transport), `frontend/src/components/chat/` (a reply's body and cue, the phantom, the steps, a
tool call, a step line, the delta fade, a quote chip and the working cue, beside the Chat tab's own
pieces), and the hooks `use-chat-stream`, `use-now`, `use-sticky-bottom` and `use-open-quote`. Its
Markdown is the app's one renderer ([`ui.md`](ui.md)).

## Testing it

The status, its event and the routes are pinned in `backend/tests/services/test_work_status.py`,
`test_timeline_service.py`, `test_project_event_service.py`, and
`backend/tests/api/test_sessions.py` and `test_testing_record.py`. The browser suites are
`frontend/tests/work/`: `harness.spec.ts`, `timeline.spec.ts`, `stop-resume.spec.ts`,
`session-log.spec.ts`, `switch-warning.spec.ts` and `registered.spec.ts`, the round trip of a
registered document ([`round-trip.md`](round-trip.md)), with `clarification.spec.ts`, the
clarification run and its reply, and `claimed.spec.ts`, a claimed action. Pilot's jobs are pinned in
`backend/tests/services/test_job_service.py` (their placement, the queue, the triggers, the
withdrawal and Retry), `test_start_gate.py`, `test_brief_service.py` and
`backend/tests/models/test_work.py` (`retried_by`); the setup's line, its queue's and Retry's, and
the pause at Create, in `frontend/tests/projects/create-project.spec.ts`, and a withdrawn job's in
`frontend/tests/timeline/undo.spec.ts`.

Each Playwright backend's controller is the fake it serves itself
([`controller.md`](controller.md)), which the `controller` fixture
(`frontend/tests/support/controller.ts`) drives. Its environments are those Pilot's starts create in
it, each read from its work item (`projects.environment`, below); by the environment's id,
`play(env, session, lines)` (answering the lines' offsets), `finish(env, session, outcome?,
result?)`, `restart`, `setStatus`, `settleStarts`, `removeEnvironment` and `unreachable`; then
`capped(on?)`, the node at its cap, refusing creates, starts and resets; `settleCreates(status)`,
what a create brings its environment to, null holding it `provisioning`; `outage(on, answer?)`,
returning once the backend reads the controller as asked; and `dropStreams()`, once the fleet stream
has reconnected; `addEnvironment(env, repo, {exempt?})` puts an environment in the fake, as the
`chats` fixture puts the store ([`chats.md`](chats.md)), and `sessions(env)` and `sessionViews(env)`
read its headless sessions; and the files of an environment as a process in it writes them,
`putFile(env, path, content)`, `removeFile(env, path)` and `fileText(env, path)`, null where there
is none. The fake's verbs that act on every environment hold across a worker's specs, so the
fixture's teardown (`restore()`) undoes an outage, the node's cap and held creates that a spec left.
Pilot's headless sessions in an environment are `claude-1`, `claude-2`, … in the order it creates
them, a Resume that re-creates its session making the next. `rawTurn(name)` reads the backend
suite's invented turns. The worker's `conditions` fixture reads what the gold bar reads, and waits
at the worker's start for the backend's first outage, its fleet stream's refused first open, to end.
The fleet stream reconnects on the supervisor's backoff, up to 30 s, so a spec whose outage must end
sets a timeout of its own.

Every project Create opens is paused, so a spec that creates one and starts work in it resumes it
first (`projects.transition(id, 'resumed')`). `projects.startWork(project, {title, brief, cwd,
step?, claims?})` places a work item by `projects.repo`, a repository of the spec's own
(`example/Example-<unique>`), so that its start takes no environment an earlier spec of the worker
left free, and answers its id; `projects.environment(project, item)` waits for the environment its
start took or created and answers its `{id, name}`, the name the project's slug (`slugOf(project)`,
the testing route's), `-2` for a second at once; `projects.work(project, item)` reads its `work`,
`projects.records(session, after?)` its records, and `projects.stop(id)` and `projects.resume(id)`
call the routes as the signed-in person; `projects.register(work, path, toolUseId?)` and
`projects.workerAttach(work, path, {to?, toolUseId?})` make its worker's calls, each its effect
while its turn is in flight, `projects.askWriter(document, [{block, question}])` the pass's
question, and `projects.clarify(document, reply?)` its clarification run, ended with the reply, or
with none started in the writer's environment, where `controller.finish(env, <its session>,
'success', reply)` ends it ([`projects.md`](projects.md)). The `sessionLog` fixture's `steps` reads
a reply's steps in order and `effects` the effects standing on their own. The `timeline` page
object's `item(id).work` reads the open item (`environment`, `running`, `line`, whose `data-state`
is the Session's state, `cue`, `step`, `sessionLog`, `stop`, `resume`, `stopConfirm`, `retry`), and
the `sessionLog` fixture the log (`sessionLogAddress()`) and its head's `discuss`. A spec placing an
item in a project while a work item's start there still writes waits for that item to run first. The
backends run with `WORK_PARALLELISM_MAX` 10000 and `PROJECT_PARALLELISM_MAX` 3
(`loadAppBackendEnv()`, [`controller.md`](controller.md), which also gives them their store,
[`chats.md`](chats.md)): a worker's specs share a backend and leave work items running, each in
projects of its own, so the slot across every project never closes, and a project's fourth running
or starting work item is held for a slot.
