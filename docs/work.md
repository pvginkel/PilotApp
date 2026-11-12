# Work items

A work item is a Session Pilot started, standing on its project's timeline: its Item, its Work and
its Session share one id ([`record.md`](record.md)). This page is the work item as the API gives it
and as the screens show it: its status, its live event, its line and its actions on the timeline,
its progress, and its session log. What the server does to start it through the gate, stop it and resume it is
[`sessions.md`](sessions.md)'s, and the timeline it stands on [`timeline.md`](timeline.md)'s.

The brain places one with `add_item`, started on add by its repository ([`mcp.md`](mcp.md)), and the
record's testing route `POST /api/testing/projects/<id>/work` places one so, on every stage but
`prd` ([`projects.md`](projects.md)). The app places one itself as a run's continuation:
the close that leaves none of the documents a work item's run registered open places the work item
that continues its conversation, titled as the run, on its plan task while the plan still has it,
after the answered items, and the end of a pre-ruling pass that asked the writer places the
clarification run that puts its questions to the run's writer, on that run's conversation
([`round-trip.md`](round-trip.md)). Create project, a worker's turn end, a person's close in the
app of an item of Pilot's own and a wait's firings place the jobs of Pilot's own
([below](#pilots-own-work)).

## Its status

Every timeline item carries `work`, null for every kind but `work` (`WorkSchema`,
`backend/app/schemas/timeline.py`). One reader builds it, `work_status(db, ids, *, unreachable)` in
`backend/app/services/timeline_service.py`, for the timeline, for Stop's and Resume's answers and
for the live event:

- `state`: its Session's, `held`, `starting`, `running`, `idle`, `stopped`, `failed` or `ended`;
- `current_line`: `{state, since, step, agent, text}`, the Session's current line
  ([`sessions.md`](sessions.md)) with every key present, null where it leaves one out, `step`
  `{tool, input}` and `agent` `{type, description}`; null while no turn is in flight;
- `environment`: `{id, name}`, the env chip and the session log's link, as the Environment's row stands: null
  until its start has one; a done item's names the project that took the environment after it, or
  its id while it is free ([`controller.md`](controller.md));
- `started_at`: the Session's, when the controller confirmed its session or a Resume's turn was
  sent, so that a held or a starting time does not count; null before;
- `error`: only while `failed`, the latest Turn's error, else the Session's: a turn's failure is its
  Turn's, a start's the Session's;
- `autopilot`: the switch's setting its start was briefed under;
- `held_reason`: why the gate holds it as the gate reads now, a worker's run's `week_halt` or
  `five_hour_halt` ([`usage.md`](usage.md)), `paused`, a job's `store_update`
  ([`store-update.md`](store-update.md)), `controller_unreachable`, `slot`, a job's `queue`, or a
  worker's run's `conversation`, another run on the conversation it resumes; while it is `idle` with
  its nudge owed, what holds that nudge, a usage halt, `paused` or a job's `store_update`; null in any other
  state, while the gate has opened for it and its release is under way, and while nothing holds its
  nudge;
- `held_running`: while it is held for a slot, the running work items of the maximum that closed
  the gate, across every project or its project's own ([`sessions.md`](sessions.md)); else null;
- `stopped_at` and `stopped_by`, who stopped it by Stop, Finish or Archive, or Pilot, through its
  `stop_work`, a usage halt's hard stop or the store's update: only while `stopped`, `stopped_by`
  null when no one did;
- `stopped_cause`: `environment_stopped`, `environment_deleting`, `environment_error` or
  `environment_gone` while it is `stopped` with no person's stop, its environment stopped under its
  turn or settled in error, read from the session's last record; for a usage halt's hard stop, its
  nudge owed, the halt that holds it now, `week_halt` or `five_hour_halt`, or `usage_limit` once
  neither does; for a job the store's update stopped, `store_update`, read from its stop, the
  update standing or lifted; null for a person's stop and for an interrupt made elsewhere;
- `pilots_own`: whether it is Pilot's own work, a job ([below](#pilots-own-work)), false for a
  worker's run;
- `setup`: whether it is the setup, the job Create project placed, or a Retry of it, the one job
  with a line of its own ([below](#pilots-own-work));
- `retried`: `{id, at}`, the job a Retry of this one placed and when, a person's or the store's
  update's at its lift; null while it is not retried, and always for a worker's run;
- `nudge_owed`: whether a nudge is owed to it, which carries it on once nothing holds it
  ([`usage.md`](usage.md)): hard-stopped, `stopped`; halted or paused at its turn's end, `idle` and
  not done; or at the quota wall, `failed`;
- `progress`: the steps its run published ([below](#its-progress)), in order, each `{code, label,
  state}`; empty while it has published none, once it emptied the list, and always for a job.

A work item waits on you while `stopped` or `failed`, a job only until it is retried, and neither
while its nudge is owed, which its project's badge counts ([`projects.md`](projects.md)). It is
done at the end of a turn neither interrupted nor in error ([`sessions.md`](sessions.md)), but for
the turn its environment's restart left it that came back with no text and no tool call, which
fails it (D137), and unless a cooperative usage halt or its project's pause holds then
([`usage.md`](usage.md)), cause
`turn_ended`, by no one, or by
Finish's close, and a job withdrawn before its brief by an Undo or its wait's close, cause
`withdrawn` ([below](#pilots-own-work)). A worker's run and the setup then draw as their done line
([`timeline.md`](timeline.md)); any other job shows its ended mark on the item it follows from, and
a withdrawn job nowhere ([below](#pilots-own-work)).

## Live

A write of a work item's state, its current line, its `started_at`, its `error` or its steps emits
the bus's `WorkMoved(project_id, work_id)` in its transaction, and `ProjectChanged` too when its state moved,
since that moves the project's tab and head (`work_moved`, `backend/app/services/work_status.py`);
equal events of one transaction go out once. A call of the progress tools that changed none of the
steps' codes, labels, states or order emits none. A Chat's Session has no work item: its state's move
raises `ProjectChanged` alone. A pause and a resume move the reason on the project's held items
and those whose nudge is owed, each a `WorkMoved`, and the release of the held starts tells every work item it still holds,
since the outage's turn or the slot's count may have moved its reason. `ProjectEventService` sends a `WorkMoved` to every person's connections as the
SSE event `work_moved`, `{project_id, item_id, work}`, `work` read after the commit, and nothing for
a Session with no work item.

`useProjectEvents` (`frontend/src/hooks/use-project-events.ts`) writes each `work_moved`'s `work`
into the item in its project's timeline as read, and into each item's `job` and `after_turn` that is
the same job (`moveWork`), with no read of its own, and the session log follows. A move heard while that timeline is being read goes over the read once it lands.

## On the timeline

An open work item, a worker's run or the setup (`WorkItem`,
`frontend/src/components/timeline/work.tsx`), is the following; every other job shows on the item it
follows from ([below](#pilots-own-work)):

- **Its head**, an item's head ([`timeline.md`](timeline.md)), with the env chip once its start has
  an environment, but for Pilot's own work: the environment's name in the mono face, going nowhere,
  its full name the tooltip (D168); at 600px and below its server icon alone, a button named after
  the environment, whose tap opens the shared `Popover` under it with the full name, closed by a tap
  outside it, which does nothing else ([`ui.md`](ui.md)), Esc or the icon. Then, while its run is under way, `starting`, `running`, or `held`
  with nothing holding it any more, a pulse, from its start, while it says "Preparing
  <environment>" or "Creating the session": on the timeline the work item's one motion (D167).
  Beside it, once `running` with a `started_at`, the running time, the figure alone, kept on one
  line: "0m", "12m", "1h 5m", past six hours "7h", past two days "2d", counted again every 15 s by
  the wall clock and at once as the page comes back into view (`useNow`), so that a page that
  lived through a suspend keeps time. "Running for 1h 5m" is its tooltip and its accessible name
  (`role="timer"`). Then, with Discuss at the head's end, Session log's icon, in every state, and
  Stop's, its square red, while `running`, `starting` or `held`, or `idle` with its nudge owed
  (D169): icon buttons with no label, "Session log" and "Stop" their tooltips and their accessible
  names.
- **Its title.**
- **Its one line** (`workLine()`, `frontend/src/lib/utils/status-labels.ts`): a held item's reason,
  "Halted at the week's limit", "Halted at the five-hour limit", "Paused", "Waiting for Pilot's
  update", "Waiting for the controller", "Waiting for a slot · N running", "Waiting for the job before it" or "Waiting for
  the run before it"; an `idle` item whose nudge is owed, what holds the nudge in the same words, or
  "Waiting for its nudge" once nothing does; else its current line
  in the chat's working cue (`WorkingCue`), standing still in every state, its dancing dots not
  drawn (`animate={false}`), its icon the state's (D167): the server's own words while it starts
  ("Preparing <environment>", "Starting <environment>", "Creating the session", the trailing "…" left
  out) or its environment restarts; the call it runs alone, in the phase's place, worded as the chat
  words a running call ([`chats.md`](chats.md)), "Reading `…/Example/README.md`", a command's
  description, "Asking kubecoder-fleet start session · <environment>", or "Working" while it names none;
  "Thinking" and "Writing" alone; "Waiting for the <type> agent" and, after a " · ", the
  sub-agent's description, which at 600px and below stands on a line of its own under the cue, the
  " · " dropped, indented to its text, so that each line is cut at most once and a phase as short as
  "Thinking" never is (operator, 2026-10-31). The line is in one colour, the cue's, code in the mono
  face. A call whose input still streams in is its verb alone ("Editing"), and its target joins it
  once the call's line gives it; an empty target is not drawn. "Starting" before a start's first line, and "Waiting for
  Pilot" for a running one with none; "Stopped · <time>", with the cause of a stop made elsewhere
  ("<environment> was stopped", "… is being deleted", "… is gone", "… is in error"), or, for a
  usage halt's hard stop, "Stopped at the week's limit · <time>", "Stopped at the five-hour limit ·
  <time>", or "Stopped at the usage limit · <time>" once neither halt holds, and for a job the
  store's update stopped, "Stopped for Pilot's update · <time>"; "Failed · <error>";
  and nothing once `idle` or `ended`.
- **The row under the line**: the progress button once its run has published steps
  ([below](#its-progress)), then Resume while `stopped` or `failed`, disabled while the project is
  archived, as its head's switch is (D012), the API refusing it until Bring back. The setup has no
  Stop or Resume: `stopped` or `failed`, not retried and owed no nudge, it offers Retry there,
  disabled while the project is archived. A tile with none of them has no row. Stop asks
  first in the row's place, the progress button going with the row, "Stop the session? Its turn
  ends where it is; Resume sends it on." on a running item, and "Stop the session? Resume sends it
  on." on one that starts, is held, or is idle with its nudge owed, whose turn is not running
  (`stopQuestion()`), with Stop it and Cancel, which takes the focus; Stop's
  icon pressed again puts the focus back on Cancel, and Esc or Cancel puts it back on Stop's icon.
  The question goes as the item is offered Stop no more, and the row comes back once it goes.

Stop and Resume (`useStop`, `useResume`, `frontend/src/hooks/use-work-acts.ts`) call
[`sessions.md`](sessions.md)'s routes and write the answer into the cached timeline, only while the
item there is still in a state the act was made from (`moveWork`). A refusal is the query client's
toast in the API's words, and Resume, or the question, stays offered; the keyboard focus, which
the button pressed lost while it was disabled for its act, goes back to it, Resume, Retry or Stop
it, once it is enabled again, where the focus is then nowhere (`useFocusBack`). Once this browser's Stop it or
Resume lands and swaps the two, the keyboard focus that was on the button that went goes to the
other's resting button, Resume after a Stop and Stop's icon after a Resume (`useHandoff`,
`work.tsx`); a swap another browser's act made, or one after the focus moved elsewhere meanwhile,
moves no focus. Retry (`useRetry`) calls its route the same way, and once this browser's Retry
lands, the focus that was on it goes to the title of the line that takes the tile's place (below).

**A retried setup** stays open on the record, not done (D078), and reads as its line (D190)
(`DoneLine`, `item.tsx`), quiet as a done work item's: an orange triangle in its kind's icon's place
(`--warning-text`), "Retried as a new job" its tooltip; its title, the link to its session log;
Open and Discuss under the mouse, and no Undo; and when it was retried as its time (`retriedOf()`,
`hooks/use-timeline.ts`). On a phone a tap on it opens its log, as on a done work line. Its
article reads `data-state` `retried`. Its session log's tail keeps how it stopped or failed and
adds under it "Retried as a new job · <time>", the words a link that opens the retry's log in this
one's place.

## Its progress

A work item's run says which steps it goes through, so that where it stands shows on its tile
without its log. Its session publishes them while its turn runs, through `pilot-work`'s
`set_progress`, the whole list in order, and `set_progress_step`, one step's state
([`mcp.md`](mcp.md)): each step a code, the run's name for it, a label, its words on the tile, and
a state, `pending`, `active` or `done`. The server stamps each step's start and end by its own
clock (`progress_steps`, [`record.md`](record.md)); the API carries neither. Each work item has a
list of its own: Stop and Resume keep it, and a continuation, a work item of its own, starts with
none ([`round-trip.md`](round-trip.md)). A job has none: its session is given `pilot-store`.

A change of the list moves the work item's `progress` through `work_moved` ([Live](#live)), and
nothing else: it writes no effect, so the session log shows no line for it, only the call where the
session's agent made one; no notification shows it, so a change of it sends nothing
([`notifications.md`](notifications.md)); and the store's tree does not carry it
([`projection.md`](projection.md)).

**The progress button** (`Progress`, `work.tsx`) leads the row under the line on every open work
item whose list is not empty, whatever its state, an `idle` one whose nudge is owed included, its
line what holds the nudge or "Waiting for its nudge" (D122); never on the done line. It goes once the list is emptied. It is the plan's step button over the run's steps
(`StepsButton`, [`ui.md`](ui.md); [`projects.md`](projects.md)): the donut of the steps `done`,
`active` and the rest, drawn as the plan's done, in progress and the rest, and beside it the first
active step's label, ", …" after it while more are active, or with none active "Not started", "N of
M done" or "All steps done"; its tooltip is "N of M steps done", then " · in progress: a; b" while
any step is active. It stands first in the row, so an open popover stays open across a Stop or a
Resume. On a phone the label stays beside the donut. The donut and the label's capitals stand at
the button's middle, as the head's step button's do, a top margin on its donut under
`.progress-anchor` setting the button's baseline.

**Its popover**, "Progress", lists the steps in order, a done one ticked and every active one
highlighted, under the heading "Progress · N of M done", with no notes. It opens with its first
active step, or with none its first not started, at the middle of the list's box, as the plan
popover does ([`ui.md`](ui.md)). It follows the list live, opens from the button's left edge,
within the card's margins on a phone, and opens above the button where it does not fit below in
the timeline and has more room there. A press outside it, which does nothing else, or Esc closes
it.

## Pilot's own work

A background job of Pilot's own is a work item too (`JobService`,
`backend/app/services/job_service.py`): a brain session in the store for each trigger, ending
with its turn, fresh but for a wait's run that resumes its previous run's conversation
(below). It is placed in its caller's transaction, under the project's row held exclusively,
at its trigger's instant:

- its Session is kind `job`, in the store repo's root, on the brain's model and effort
  ([`chats.md`](chats.md)), `held`, with no Turn, its `created_at` the trigger's instant; on the
  5-minute prompt cache, but for a wait's run (below);
- its Work has the trigger that started it, the Item that set it off as its trigger item where it
  has one, and no repository;
- its Item takes the timeline's next place, where only the setup draws a line of its own (below).

It starts through the gate as a chat does (`start_brain`, [`sessions.md`](sessions.md)): held while
its project is paused, the setup's never, a Retry's included, while the store's update is unlifted,
the setup's too ([`store-update.md`](store-update.md)), and while another job of its project
is before it, so that a project's jobs
run one at a time in the order their triggers came, the chat beside them; taking no slot; boxed to
the project's folder with `pilot-store` handed to it, and its create made again for a bounded time
while that folder is not on disk. Its brief is composed as it leaves the gate, from the record as it
then stands (below). Its item is done at its last turn's end, the follow-up's where it gets one
([`chats.md`](chats.md)), and its project's next job goes on then. Neither a person's Stop or Resume
nor the brain's `stop_work` takes it ([`sessions.md`](sessions.md)); Finish and Archive stop it as
they stop every session, and the store's update while it runs or starts. One job is placed per
trigger, never one for several; a wait's run is one trigger, however many firings it takes.

**The prompt cache.** A job of trigger `setup`, `worker_turn_ended` or `item_done` runs on Claude
Code's 5-minute prompt cache (D141): its create's `env` carries `CLAUDE_CODE_PROMPT_CACHE_TTL=5m`
after `PILOT_SESSION`, at its start and at the relay's create of it anew alike, a finished
project's job's too (`FIVE_MINUTE_JOBS`, `backend/app/services/session_scope.py`). Such a job
starts fresh and ends in one turn, so an hour's cache, whose writes cost more than the 5-minute
cache's, buys it nothing. A wait's run, which may resume its previous run's conversation within
`CACHE_EXPIRATION_TTL` (below), a chat and a work item's run carry no such entry and keep Claude
Code's own, the hour on a subscription within its usage limits.

**The triggers.** Four place a job:

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
  "Deciding what is next": a person's close in the app of an item a session of Pilot's own added, a
  chat's or a job's, in the close's transaction ([`engine.md`](engine.md)): answered, Done, an
  action's Done, Reviewed. A close the chat records on a person's behalf places none, the chat's own
  turn carrying the ruling out (D139), and neither do a notice's Read, Pilot's own Done, Pilot's
  close of an item of its own at the save that writes its last open block's `done` (D138), Finish's
  close, a registered document's close, an item a worker's session added and the archive question,
  which no session added.
- **A wait's firings**, trigger `wait_fired`, its trigger item the wait, titled `Checking "<wait
  title>"`: placed by the batcher once the wait's oldest pending firing is the quiet window old and
  no run of the wait is in flight, taking at its brief every firing still pending
  ([`waits.md`](waits.md)).

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
  are; then, where the work item or another on its conversation was given claimed actions, its
  standing naming theirs, so that a continuation's names those of the run it continues and a retry,
  on a conversation of its own, takes them from it (D100), `The claimed actions given to this work
  item, as they stand:` and a line per action in timeline order, `- <path> (<item id>) <local id>
  open, claimed`, `… open, claimed, handed back to the operator: leave it to them` once the run no
  longer holds it ([`round-trip.md`](round-trip.md)), `… open, its claim gone`, or its close as the
  record holds it, a person's Done meanwhile included; then, where the run was given blocks to
  research, its standing naming theirs as a claim's is, `The blocks this work item researched, as
  they stand:` and a line per block in timeline order, `- <path> (<item id>) <local id> open`, `…
  open, handed back to the operator: leave it to them`, `… open, claimed` where it was claimed
  since, or its answer as the record holds it, `Q1 "Two hosts" (by ada)`; then every open plan note
  by summary and the deferrals without a home, as the chat's brief has them
  ([`chats.md`](chats.md)).
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
- **A wait's firings**: `/plan`, kind `a wait fired`; the wait's line, what it waits on, since when
  and its task, then `Firings pending, oldest first:` and a line per firing it took
  (their words in [`waits.md`](waits.md)); then the open notes of the wait's task and the plan's own,
  and the deferrals without a home.

The brief is the job's first Turn, written as it moves to `starting` ([`sessions.md`](sessions.md)):
at its placement, at its trigger's instant, when the gate lets it through then; else by the release
that moves it. The `item_done` job's brief consumes its item, which takes Undo from it
([`engine.md`](engine.md)).

**An Undo before the brief.** An Undo of the item while its `item_done` job is still held before its
brief, behind the project's other jobs or held by the pause, withdraws the job (D079): its Session
`stopped` by no one, with no Turn, and its work item done, cause `withdrawn`, by no one, offering no
Undo; the next close of the item places a new job. With the project idle the job is briefed in the
close's own transaction, so the item's Undo shows only while the job waits.

**A wait's run.** A wait's close by the brain's `mark` withdraws its run held before its brief, as
an Undo withdraws a job, its firings left untaken. A run within `CACHE_EXPIRATION_TTL` of its
wait's previous run's turn's end, that run's turn ended neither failed nor stopped, resumes its
conversation: its first Turn is the follow-up alone, `Another firing of "<title>" since your last
run:` and the firing lines, under the switch that run's brief stated, which the conversation keeps.
Past it, after a run that failed or was stopped, and for a Retry, the run is fresh, with the full
brief. A resume the controller refuses fails the run at its create ([`waits.md`](waits.md)).

**Retry.** A job `failed` or `stopped`, whoever stopped it, its work item open, offers Retry (D078,
`POST /api/sessions/<id>/retry`, [`sessions.md`](sessions.md)): a fresh job for the same trigger,
trigger item and title, at the project's next place, behind every job already waiting, briefed as it
starts from the record as it then stands. Its brief reads its trigger's instant from the first job
of its chain, so a retried setup still says when the project was created, and an `item_done`
retry's brief consumes the item only if the job it retries did not. What the failed job wrote is
in the store and the record, and the new job's brief does not say so: a retried setup's reads as
Create's, `The plan: plan.json, empty.` included. The one retried is marked retried by the new
job before that one starts: it keeps its state, its open item and its session log, offers Retry no
more, and leaves the badge; a retried setup reads as its line ([above](#on-the-timeline)). A person has to press it, but at the store's update's lift, which
retries each job the update stopped once ([`store-update.md`](store-update.md)). A job
withdrawn by an Undo, done, never ran, and takes no Retry; nor does a job whose turn died at the
quota wall while its nudge is owed, which is not at its end until the run its nudge continues ends
(D099, [`usage.md`](usage.md)); nor a wait's run whose wait is done or has another run in flight. A
wait's run retried is briefed fresh with the firings the runs it retries took, and with any still
pending.

**On the timeline**, a job's `pilots_own` is true, and no job draws a line of its own but the setup
and its Retries, `setup` true (`isLine`, `frontend/src/hooks/use-timeline.ts`): every other job
keeps its entry in `items`, where its session log finds it, and shows on the item it follows from,
as that item's `job` ([`timeline.md`](timeline.md)). A pass shows on each document it pre-rules,
the pass after the writer's reply included; any other job on its trigger item: the worker's run
whose turn ended, the item of Pilot's whose close placed it, the wait that fired. Where several
stand on one item, the latest placed shows, a Retry over the job it retries; where the latest was
withdrawn, the one before it, so that a withdrawn job shows nowhere. A worker's run carries besides,
as `after_turn`, the job after its turn, its latest Retry where it was retried, wherever that job
shows (`jobs_on`, `backend/app/services/working_on.py`).

The job draws in one of three forms (`frontend/src/components/timeline/job.tsx`, `jobForm()` in
`status-labels.ts`), each opening its session log, whose tail says what they have no room for: why
it is held, the stop's cause, the error.

- **Under way**, while it is held, starts or runs, or its turn ended owing its nudge: a ghost
  button, the pulsing dot, Pilot's avatar and the job's title (`JobButton`).
- **Failed or stopped**: the same button with no dot, in the destructive colour, "<title> · Failed"
  or "<title> · Stopped", and Retry beside it while the job offers it (`offersRetry`), disabled
  while the project is archived. Pressed from the keyboard, Retry puts the focus on the job's button
  once it lands, the one the retry's job then draws in.
- **Ended**: Pilot's mark without the avatar's circle, an icon button (`JobMark`).

A done line draws the ended mark first among its actions, shown with them, and the other forms at
its end before the time, shown always; on a phone it draws no mark, and the other forms take a row
under its title. An open card's head draws the job after its time; an opened document's head and a
worker's run's session log's draw it among their buttons ([`documents.md`](documents.md), below); a
phone's menu of a wait's line offers it as a row before Discuss. The line of an item Pilot is
working on draws none: its one button is the pass's ([`timeline.md`](timeline.md)).

A job has neither the env chip, the store's once its start takes it, nor Stop or Resume. A pass's
job, and the job after the writer's reply, stops through Stop and take over on a document it goes
over, by the person, and the lift never retries it ([`round-trip.md`](round-trip.md)). Its session
log's head names no environment. A failed or stopped job offers Retry, and its project's badge counts
it, until it is retried.

## The session log

At `/projects/<project>/sessions/<session>`, under the project's address
([`projects.md`](projects.md)), the item's id, the project's route opens the session
log (`SessionLogOverlay`, `frontend/src/components/overlay/session-log-overlay.tsx`, on
[`documents.md`](documents.md)'s `Overlay`). An open item's Session log, a done work line's Open and
its title, and a job's button or mark go there, on a phone a tap on the done line
([`timeline.md`](timeline.md)). An address that names no work item of the project reads "The session
log did not load".

**Off a phone it is a popover** (`sheet pop`, a dialog) over the tab showing, the timeline or a
document's (D147), in one place and of one size whichever item it opens from: 90% of the column's
text width, centred on it, between the stage's top and bottom, at most 560px high. It does not
scroll with what lies under it, which keeps its scroll and is not `inert`. Its cross,
Esc and a press outside it close it, and so does a click on a link to its own address, so that the
button that opened it closes it; a press anywhere else outside it closes it and then does what it
does, so that a line's title or a job's button opening another log shows that log in its place. At
the log's address the tab under it is the one the project's tab line showed last, which the close
goes to, replacing the entry, the focus going back to what opened it without scrolling. **On a
phone** it is a view pushed over the tabs, or over the view it opened from.

- **Its head**: "Session log", the session's id its tooltip (`Session <id>`), over the item's title
  and, but for Pilot's own work, a dot and its environment's link once its start has one (D147). A
  worker's run's head carries the job after its turn, its `after_turn`, in whichever form it stands
  ([above](#pilots-own-work)), and that job's log then takes its place, on a phone pushed over it.
  The popover has no Discuss; the view on a phone has, quoting the work item into the chat
  ([`chats.md`](chats.md)), so that a finished work item is discussed from there (D127).
- **What each turn was sent**: before a turn's reply stands what the server sent it, as Pilot's
  message, "Pilot" and its time under it (`SentMessage`, `.log-sent`), cut after 8 lines with Show
more over the end of the last and, once opened, Show less after its last word, the one pressed
handing the focus to the other (`Clamp`, `components/shared/clamp.tsx`): a work
  item's brief, a continuation's message, a Resume's `continue`, every turn with no author, in a work
  item's log and a job's alike (D150). A turn sent and not yet answered shows its message alone.
- **Its body**: the session's records rendered as the chat renders a reply, one reply per turn
  (`ReplyBody`), each under what it was sent, bare in the log's column, 6px in from either side (D002): the text as Markdown, the
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
  or one stopped before it was sent, and " · Failed" after a failed one.
- **Its tail**: while the item is held, starts or runs, the working cue: the held reason, what the
  turn in flight is doing, or "Starting" and "Waiting for Pilot" before its first record. Its dancing
  dots run while a turn runs or comes up, and stand still, its icon and words kept, while the gate
  holds the start and while a nudge is owed. Otherwise
  how it ended (`sessionLogTail()`): "Stopped by you · <time>", "Stopped by <name> · <time>",
  "Stopped by Pilot at the usage limit · <time>" after a usage halt's hard stop, "Stopped by Pilot
  for its update · <time>" after the store's update's stop, the cause of a stop
  made elsewhere, "Stopped", "The turn ended · <time>", or "Failed", the error over
  it where the last turn shows none. A run whose turn ended under a halt or a pause, its nudge owed,
  shows under "The turn ended · <time>" what its line shows, what holds the nudge or "Waiting for
  its nudge" (`nudgeCue()`).
- **It follows the item's `work`** as the timeline holds it, live, so that a Resume carries the log
  on, and it sticks to its end while it grows and while its view gets shorter: only the reader's
  own scrolling up, by the wheel, a key or a drag, lets go, and scrolling back down to the end
  picks it up again (`useStickyBottom`, as the chat's, [`chats.md`](chats.md)).

The records come through `useChatStream` on `sessionTransport`
(`frontend/src/lib/chat/transport.ts`, `hooks/use-session-transport.ts`): it subscribes a view of
the session on the browser's SSE connection, reads the records by page from the first, then takes
the frames that came meanwhile, a record it got both ways once ([`sessions.md`](sessions.md) has the
routes). A read or a subscribe that fails drops the stream, which reopens after its last record, and
so does a new SSE connection. The stream's `end` ends nothing here: the tail follows `work`. What
each turn was sent is read apart, from `GET /api/sessions/<id>/turns` (`useSessionTurns`,
`hooks/use-session-turns.ts`), since no record carries a server's turn's message, and read again once
a record names a turn the last read did not hold; the log merges the two by the turn's number.

**The view.** A record outside any Turn, the start's lines, a failed start and a gone session, falls
in the Turn in flight, else in the next one. A Turn ends at its `result`, at a failed send or start,
at its environment stopped under it, or, where it ended with no record, where a later Turn's records
begin. A `read-failed` or `write-back-refused` record is written after the run's last Turn ended,
and stands at that Turn's end; a call or a sub-agent still running then was stopped with it, and
draws with no spinner. A Stop of a held or a starting item ends its Turn with a `server` record
`{"type": "stopped-unsent"}`, its last ([`sessions.md`](sessions.md)), and the Turn ends
" · Stopped", as an interrupted one does. An
`isError` result shows its text as the failure, or "The turn failed." where it has none. An effect
stands on the call whose tool-use id it names, whether its record was written before or after the
call's `assistant` line: one whose call's line has not come yet waits for it, so a streamed log
shows it on its own first and then on its call, and one whose call no record shows, with no
tool-use id, is a step of its own in its record's place (`buildChatView`,
`frontend/src/lib/chat/view.ts`).

**A step line** (`summarizeTool`, `frontend/src/lib/chat/tools.ts`, drawn by `StepWords`) is in one
colour, its step line's in the chat and the session log and the cue's in a work item's line, a
failed one red throughout; what it names as code, a command without a description, a path, a glob
or an environment's name, is set in the mono face, and a search's pattern keeps its quotes. A
call's line opens on its verb, so that a running one reads as a status alone: "Reading
`…/chat/tools.ts`", "Asking kubecoder-fleet start session · <environment>", "Using Skill",
"Starting the Explore agent", and once done "Read …", "Asked …", "Used …". A call on an MCP server
reads "Asking <server> <tool's words>", the server named as configured and none renamed (D204); Pilot's
own server, `pilot`, keeps verbs of its own ("Adding an item", "Recording an answer"), a worker's
`set_progress` reading "Publishing its steps" and `set_progress_step` "Moving a step", and a tool of
it with no verb of its own "Using <tool>". A command's description, the
model's own sentence, stands alone, without a verb, and so does an agent's, its type after it,
"Find the chat's cue · Explore agent", its card's head in the chat and the session log too. A run
of calls is one line in its usual colour, "Ran 3 commands, used a tool, used gitblit 4 times · 8
steps", an MCP server's calls counted under its own name, "used youtrack once", Pilot's as "changed
the record N times" and a worker's progress calls as "updated its steps N times"; its failures "· N
failed" after its steps, the one red in it. Each text a run's line shows, its words and its count
of steps, stands at least 200 ms: once the text differs from the one shown, the line waits 200 ms
and shows the text as it then is, the wait never starting over, so that a call that came and went
within it never shows (`useHeld`, `hooks/use-held.ts`); its failures change at once. A running
call's spinner shows once that call has run a second (D203), counted in the page from when it first shows
the call running, on the call's own line, its run's line and an agent's card alike: a quick call
shows its icon throughout, the next call waits a second of its own, and the spinner goes at once.
A line stands 24px high, code in its words or not, its code's mono span set within the line's
height; its icon, as the working cue's, stands on the middle of its words' capitals.

**The chat's view code** is the chat mockup's, shared by the session log and the Chat tab
([`chats.md`](chats.md)): `frontend/src/lib/chat/` (the records on the API's record types,
`claude`'s lines, the stream's state, the view, the tool summaries, the activity, quotes, times and
the transport), `frontend/src/components/chat/` (a reply's body and cue, the phantom, the steps, a
tool call, a step line, the delta fade, a quote chip and the working cue, beside the Chat tab's own
pieces), and the hooks `use-chat-stream`, `use-now`, `use-sticky-bottom`, `use-own-growth`, `use-held` and
`use-open-quote`. Its
Markdown is the app's one renderer ([`ui.md`](ui.md)).

## Testing it

The status, its event and the routes are pinned in `backend/tests/services/test_work_status.py`,
`test_timeline_service.py`, `test_project_event_service.py`, and
`backend/tests/api/test_sessions.py` and `test_testing_record.py`. The browser suites are
`frontend/tests/work/`: `harness.spec.ts`, `timeline.spec.ts`, `stop-resume.spec.ts`,
`progress.spec.ts`, the progress button and its popover, `session-log.spec.ts`, `switch-warning.spec.ts`, `usage-halts.spec.ts`, `hard-stop.spec.ts` and
`nudge.spec.ts`, the usage limits ([`usage.md`](usage.md)), and `registered.spec.ts`, the round trip of a
registered document ([`round-trip.md`](round-trip.md)), with `clarification.spec.ts`, the
clarification run and its reply, and `claimed.spec.ts`, a claimed action. Pilot's jobs are pinned in
`backend/tests/services/test_job_service.py` (their placement, the queue, the triggers, the
withdrawal and Retry), `test_start_gate.py`, `test_brief_service.py` and
`backend/tests/models/test_work.py` (`retried_by`), and where each shows in `TestJobsOn`
(`backend/tests/services/test_working_on.py`); the setup's line, its queue's and Retry's, and the
pause at Create, in `frontend/tests/projects/create-project.spec.ts`; a job on the item it follows
from, its forms, its Retry, an open card's head, the phone's row and a wait menu's, and the job in an
opened document's head and a run's log's, in `frontend/tests/timeline/jobs.spec.ts`; and a withdrawn
job, shown nowhere, in `frontend/tests/timeline/undo.spec.ts`. The session log's popover is pinned in
`session-log.spec.ts`, and what the log shows a turn was sent there too.

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
A headless session in an environment takes the lowest free name of `claude-1`, `claude-2`, …, as
KubeCoder's do, so a session created anew, by a Resume or after a restart, can get the old one's
name back. `rawTurn(name)` reads the backend
suite's invented turns. The worker's `conditions` fixture reads what the gold bar reads, and waits
at the worker's start for the backend's first outage, its fleet stream's refused first open, to end.
The fleet stream reconnects on the supervisor's backoff, up to 30 s, so a spec whose outage must end
sets a timeout of its own.

Every project Create opens is paused, so a spec that creates one and starts work in it resumes it
first (`projects.transition(id, 'resumed')`). `projects.startWork(project, {title, brief, cwd,
step?, claims?, researches?})` places a work item by `projects.repo`, a repository of the spec's own
(`example/Example-<unique>`), so that its start takes no environment an earlier spec of the worker
left free, and answers its id; `projects.environment(project, item)` waits for the environment its
start took or created and answers its `{id, name}`, the name the project's slug (`slugOf(project)`,
the testing route's), `-2` for a second at once; `projects.work(project, item)` reads its `work`,
`projects.records(session, after?)` its records, and `projects.stop(id)` and `projects.resume(id)`
call the routes as the signed-in person; `projects.setProgress(work, steps)` replaces its list of
steps as its session's `set_progress` does while its turn runs; `projects.register(work, path, toolUseId?)` and
`projects.workerAttach(work, path, {to?, toolUseId?})` make its worker's calls, each its effect
while its turn is in flight, `projects.askWriter(document, [{block, question}])` the pass's
question, and `projects.clarify(document, reply?)` its clarification run, ended with the reply, or
with none started in the writer's environment, where `controller.finish(env, <its session>,
'success', reply)` ends it ([`projects.md`](projects.md)). The `sessionLog` fixture's `steps` reads
a reply's steps in order and `effects` the effects standing on their own. The `timeline` page
object's `item(id).work` reads the open item (`environment`, `running`, `line`, whose `data-state`
is the Session's state, `cue`, `step`, `sessionLog`, `stop`, `row`, `progress`, with
`progressRing` and `progressName`, `steps`, its popover, `resume`, `stopConfirm`, `retry`), its
`item(id).job` Pilot's job on the item (`root`, with `data-form` its form, `pulse`, `retry`), and
the `sessionLog` fixture the log (`sessionLogAddress()`, `overlay`, the popover or the view), its
head (`head`, `sub`, `close`, the job after a run's turn `job`, a phone's `discuss`) and what each
turn was sent (`sent`, `sentTexts`, `sentEnds`, `sentMore`). A job's own entry draws nothing:
`timeline.item(jobId).root` has none. A spec placing an
item in a project while a work item's start there still writes waits for that item to run first. The
backends run with `WORK_PARALLELISM_MAX` 10000 and `PROJECT_PARALLELISM_MAX` 3
(`loadAppBackendEnv()`, [`controller.md`](controller.md), which also gives them their store,
[`chats.md`](chats.md)): a worker's specs share a backend and leave work items running, each in
projects of its own, so the slot across every project never closes, and a project's fourth running
or starting work item is held for a slot.
