# Work items

A work item is a Session Pilot started, standing on its project's timeline: its Item, its Work and
its Session share one id ([`record.md`](record.md)). This page is the work item as the API gives it
and as the screens show it: its status, its live event, its line and its actions on the timeline,
its progress, the time it still takes, its debrief and the debrief's notice, and its session log. What the server does to start it through the gate, stop it and resume it is
[`sessions.md`](sessions.md)'s, and the timeline it stands on [`timeline.md`](timeline.md)'s.

The brain places one with `add_item`, started on add by its repository or in an environment it
names ([`mcp.md`](mcp.md), [`sessions.md`](sessions.md)), and the record's testing route
`POST /api/testing/projects/<id>/work` places one so, on every stage but
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
- `current_line`: `{state, since, step, agent, task, text}`, the Session's current line
  ([`sessions.md`](sessions.md)) with every key present, null where it leaves one out, `step`
  `{tool, input}`, `agent` `{type, description}` and `task`, the background task a `background`
  line waits on, `{type, description}`; null while no turn is in flight;
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
- `note`: Pilot's reason for closing it for good through `stop_work` ([below](#closed-for-good)),
  which its done line carries under its title; null while it is open, after a person's Close and
  after any other close;
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
  state, why}`; empty while it has published none, once it emptied the list, and always for a job;
- `estimate`: the time it still takes, its badge ([below](#the-time-it-still-takes)), null unless
  it is running and shows one;
- `debriefed`: whether it is done and its session gave its debrief ([below](#its-debrief)), which
  the Debrief on its done line opens; false while it is open, for a run that gave none and for a
  job. The read leaves the debrief's text unread: the line shows none of it.

A work item open waits on you while `stopped` or `failed`, a job only until it is retried, and neither
while its nudge is owed, which its project's badge counts ([`projects.md`](projects.md)). It is
done at the end of a turn neither interrupted nor in error ([`sessions.md`](sessions.md)), but for
the turn its environment's restart left it that came back with no text and no tool call, which
fails it (D137), and unless a cooperative usage halt or its project's pause holds then
([`usage.md`](usage.md)), cause
`turn_ended`, by no one, or by
Finish's close, and a job withdrawn before its brief by an Undo or its wait's close, cause
`withdrawn` ([below](#pilots-own-work)); a stopped worker's item closed for good is done
`cancelled` ([below](#closed-for-good)), and leaves the badge. A worker's run and the setup then draw as their done line
([`timeline.md`](timeline.md)); any other job shows its ended mark on the item it follows from, and
a withdrawn job nowhere ([below](#pilots-own-work)).

## Live

A write of a work item's state, its current line, its `started_at`, its `error` or its steps emits
the bus's `WorkMoved(project_id, work_id)` in its transaction, and `ProjectChanged` too when its state moved,
since that moves the project's tab and head (`work_moved`, `backend/app/services/work_status.py`);
equal events of one transaction go out once. A call of the progress tools that changed none of the
steps' codes, labels, whys, kinds, marks, states or order emits none. A Chat's Session has no work item: its state's move
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
  (`role="timer"`). After it, while the work item shows one, the badge of the time it still takes,
  alone, on a line of its own under the head where its row would cut it
  ([below](#the-time-it-still-takes)). Then, with Discuss at the head's end, Session log's icon, in every state, and
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
  "Thinking" never is (operator, 2026-10-31); once the model has ended its own turn on a task it
  left running in the background, "Waiting on a background command", or "Waiting on a background
  task" for a sub-agent, and after a " · " the command's description, as a sub-agent's, with no
  time, which the session log's tail carries (D213). The line is in one colour, the cue's, code in the mono
  face. A call whose input still streams in is its verb alone ("Editing"), and its target joins it
  once the call's line gives it; an empty target is not drawn. "Starting" before a start's first line, and "Waiting for
  Pilot" for a running one with none; "Stopped · <time>", with the cause of a stop made elsewhere
  ("<environment> was stopped", "… is being deleted", "… is gone", "… is in error"), or, for a
  usage halt's hard stop, "Stopped at the week's limit · <time>", "Stopped at the five-hour limit ·
  <time>", or "Stopped at the usage limit · <time>" once neither halt holds, and for a job the
  store's update stopped, "Stopped for Pilot's update · <time>"; "Failed · <error>";
  and nothing once `idle` or `ended`.
- **The row under the line**: the progress button once its run has published steps
  ([below](#its-progress)), then Resume while `stopped` or `failed`, and Close beside it while a
  worker's item is `stopped`, never a failed one's or a job's ([below](#closed-for-good)), each
  disabled while the project is archived, as its head's switch is (D012), the API refusing it until
  Bring back. The setup has no
  Stop or Resume: `stopped` or `failed`, not retried and owed no nudge, it offers Retry there,
  disabled while the project is archived. A tile with none of them has no row. Stop asks
  first in the row's place, the progress button going with the row, "Stop the session? Its turn
  ends where it is; Resume sends it on." on a running item, and "Stop the session? Resume sends it
  on." on one that starts, is held, or is idle with its nudge owed, whose turn is not running
  (`stopQuestion()`), with Stop it and Cancel, which takes the focus; Stop's
  icon pressed again puts the focus back on Cancel, and Esc or Cancel puts it back on Stop's icon.
  The question goes as the item is offered Stop no more, and the row comes back once it goes.
  Close asks first in the row's place too, "Close it for good? It takes no Resume afterwards, and
  what it put to you stays open.", with Close it and Cancel, which takes the focus; Esc or Cancel
  puts the focus back on Close, and the question goes with Close, whichever browser's act took it
  away.

Stop, Resume and Close it (`useStop`, `useResume`, `useClose`, `frontend/src/hooks/use-work-acts.ts`) call
[`sessions.md`](sessions.md)'s routes and write the answer into the cached timeline, only while the
item there is still in a state the act was made from (`moveWork`). A refusal is the query client's
toast in the API's words, and Resume, or the question, stays offered; the keyboard focus, which
the button pressed lost while it was disabled for its act, goes back to it, Resume, Retry, Stop
it or Close it, once it is enabled again, where the focus is then nowhere (`useFocusBack`). Once this browser's Stop it or
Resume lands and swaps the two, the keyboard focus that was on the button that went goes to the
other's resting button, Resume after a Stop and Stop's icon after a Resume (`useHandoff`,
`work.tsx`); a swap another browser's act made, or one after the focus moved elsewhere meanwhile,
moves no focus. Retry (`useRetry`) calls its route the same way, and once this browser's Retry or
Close it lands, the focus that was on it goes to the title of the line that takes the tile's place
(below).

### Closed for good

A stopped work item nobody will resume is closed for good in two ways (D212). A person's Close, beside
Resume (above), calls `POST /api/sessions/<id>/close` ([`sessions.md`](sessions.md)), taken on a
worker's item `stopped`, whoever stopped it. Pilot closes one it replaced through `stop_work` with a
`reason`, in the same act as its stop: one stopped already as it stands, and one a Stop takes,
stopped first by Pilot ([`mcp.md`](mcp.md)); its reason is kept as `work.done_note`
([`record.md`](record.md)). Either way the item is done `cancelled`, by the person or Pilot, with no
Undo, and leaves the badge; its quiet line leads with the cancelled mark and, where Pilot closed
it, carries the reason under its title (`work.note`, [`timeline.md`](timeline.md)). Its Session
stays `stopped`, its nudge owed no more, and holds its environment no more; a Resume of it is
refused, "it is closed for good". Nothing continues its conversation, and its run holds no block.
The documents its run put to a person stay open; those it registered and that await their read are
read once its stopped turn has ended, and are then the person's, and no job follows the close
([`round-trip.md`](round-trip.md)). A failed work item takes no close: it keeps its Resume.

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
([`mcp.md`](mcp.md)): each step a code, the run's name for it, a label, its words on the tile, a
state, `pending`, `active` or `done`, and where the run gives one a why, a short line the
workflow writes on the step that opens a repeat round, saying why the round before did not settle
it. A step also carries, where the run gives them, its kind, its mark and the conversations that
did its work, by which the rounds its driver started are counted on the work item that ran them
([`collection.md`](collection.md#a-launch-of-pilots)), and the step going done its duration, which
the server keeps as the step's timing
once, for the time a running work item still takes ([below](#the-time-it-still-takes)). The server
stamps each step's start and end by its own clock, and with its start whether it stood listed
ahead (`progress_steps`, [`record.md`](record.md)); the status's `progress` carries none of
them, nor a step's kind, mark or conversations. The stamps are the progress shown: a timing's
duration is the run's own measure. Each work item has a
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
highlighted, under the heading "Progress · N of M done", with no notes; a step's why stands under
its label, on a line of its own close under it, a size down and muted, in the text's weight under
a step in progress too, and wraps where it is long, a long path in it breaking anywhere, nothing cutting it. Only the popover shows the
why: the button, its tooltip and the tile's line never do. It opens with its first
active step, or with none its first not started, at the middle of the list's box, as the plan
popover does ([`ui.md`](ui.md)). It follows the list live, opens from the button's left edge,
within the card's margins on a phone, and opens above the button where it does not fit below in
the timeline and has more room there. A press outside it, which does nothing else, or Esc closes
it.

## The time it still takes

A running work item shows how long it still takes, so that when the work ends shows without
asking, and on hover or press the figures behind it. The server estimates it from the list as it
stands and the Step Timings of its steps' kinds, which a run's finished steps and the seed leave
([`mcp.md`](mcp.md)), at every read, and stores none (`work_estimates`,
`backend/app/services/step_estimate.py`). It reads no step's label, matches a step's code only to
its own on the run's other work items' lists, and orders no kinds: a kind is the run's, read as
given.

**A kind's timings** are those of the work item's repo, its `repo` label, else its environment's,
once the repo holds ten timings of the kind, and those of all repos until then; a timing whose
listing is unknown counts in none of it, the ten here and the five below included. The kind's window is
its last `ESTIMATE_WINDOW_STEPS` timings by their end, 20 by default; a step's **price** is the
window's total time divided by the number of its timings that were listed ahead, the mean with the
unlisted repeats in it, not the median; and the **repeats' share** is the price less the mean of
the window's listed timings, never below zero.

**The time left** is the sum of three parts:

- each step not begun, at its kind's price;
- each running step, at the median of what longer steps still took: of the last
  `ESTIMATE_RUNNING_STEPS` timings of its kind, 60 by default, that began as it did, listed ahead or
  not, those that ran at least as long as it has, each less the time it has run; the kind's last 60
  taken whole where fewer than five began as it did or its listing is unknown. They are of the
  timings that had ended when the step began, one that ended at that instant among them, the
  repo's ten and the five counted among them too, so that they hold still while it runs; those that
  end since count in its kind's price alone. Its time run is counted by the server's clock from the
  later of the step's start and the start of the session's running turn, so that a step resumed
  after a stop counts no time it stood;
- the repeats owed: a step listed ahead owes its kind's repeats' share while it runs and, done,
  until the next listed step on the list is done or a step of its kind that was not listed ahead
  has begun after it; with no listed step after it, for as long as a step is left to do. A step
  not begun counts as listed.

**No estimate** stands while the work item's Session is not `running`, a held, starting or idle one
included; once the work item is done, though its Session runs on; while no step is left to do,
none published or every one done; while a step left to do has no kind; while a kind it needs, a
step's left to do or a done step's that still owes its share, has fewer than five timings in all
repos, or a running step's had fewer when it began, however many have ended since; and while a
kind's window holds no listed timing.

**Longer than usual** (D250) is the badge's alert. Once every timing a running step is read against
ran shorter than it has run, the step has outrun its kind: the alert stands with an em dash, "—",
where the time stood, and no time left is given. A running step the workflow marked
([`mcp.md`](mcp.md)) that has outrun nothing turns the badge to the alert too, with the time left
as the estimate gives it, or the alert alone where the work item has no estimate. With no estimate
an outrun step shows nothing; only a marked one does. A marked step that has also outrun its kind
shows the em dash where the work item has an estimate, the alert alone where it has none, and its
sentence says its run marks it either way (D268, [below](#its-figures)).

**The rounding** is the server's (`WorkEstimate.minutes`): under 55 minutes the time left to the
nearest five minutes and at least five, from 55 to 89 an hour, from 90 the nearest hour.

A work item's status carries it as **`estimate`** ([Its status](#its-status)), `{minutes,
longer_than_usual, marked, kind, ran_seconds, step_figures, run_figures}`, as it read when the
status was built (`EstimateSchema`, `backend/app/schemas/timeline.py`): `minutes` the time left as
rounded, 5 to 55 by fives, 60, then whole hours as 120 or 180, null where the badge shows no time;
`longer_than_usual` `outrun` where a running step has outrun its kind, marked or not, `marked`
where the workflow marked one and none has outrun, or null on a badge at rest, where `minutes` is
always set; `marked` whether the workflow marks a running step, outrun or not; `kind` the first
running step's kind as published, null where no step runs or it has none; `ran_seconds` the run's
time so far in whole seconds, as its row of the figures counts it, which the alert's sentence says;
and `step_figures` and `run_figures` the figures' rows ([below](#its-figures)). It is null wherever
the badge shows nothing. `work_status` asks the estimate for the work items whose Session is
`running` alone, and the estimate reads at most four statements, whatever the number of work items,
steps and timings. The three settings are `backend/app/app_config.py`'s and reach every reader
through `StepEstimates`, a singleton of the service container: the 20 and the 60, both counted in
steps, and `ESTIMATE_RUN_SLOW_FACTOR`, the run's slow over its normal, 1.6 by default and at least
1, the 90th percentile of past runs' work over their list's price, set from the backtest each time
it is run.

**The badge** (`Eta`, `work.tsx`; `EtaBadge`, [`ui.md`](ui.md)) stands in the head after the
running time (D248), alone, with no kind and no count of steps after it. Where the head's row wraps
with it in it, it stands on a line of its own under the row, as high as the head's row, the row as
it was (`eta-below`, `timeline.css`), measured on every change of the head's width or its parts; on
a phone always. It opens its figures ([below](#its-figures)) on hover off a phone and on a press,
at rest and as the alert, on a phone spanning the page under it, 8px in from each side and at
most 420px wide; a badge at rest with no row of them to show is words alone, with no hover and no
press. The done line shows none.

**Kept current.** A work item's `estimate` rides its timeline item and each `work_moved`, so a
step's move, a kind and a mark reach its badge with no read of its own. A step of its kind timed or
seeded elsewhere moves it with no event: while any badge shows, the page reads the project's
estimates each minute and writes them over the work items' and the head's
([`projects.md`](projects.md#the-time-its-work-still-takes)), a work item the read does not list
losing its badge.

### Its figures

**The figures** are a table of three columns, *So far*, *Normal* and *Slow*: "this is us, this is
normal, and this is slow". The server computes them with the estimate, at every read, and stores
none (`StepFigures` and `RunFigures`, `step_estimate.py`); the page computes nothing of them, and
no tool of Pilot's MCP server hands them back.

- **A running step's row**, by its kind as published, several running steps a row each in the
  list's order (`step_figures`, `{kind, so_far_minutes, normal_minutes, slow_minutes,
  longest_minutes, timings}`): so far its time run, as the time left counts it; normal the median
  of the timings it is read against, its 60 as they stood when it began; slow their 90th
  percentile, within their range; and their longest, past which the step has outrun its kind and
  the badge turns red, `timings` how many it read, fewer than 60 while those they are drawn from
  hold fewer. A step with no kind, or whose kind had fewer than five timings in all repos when it
  began, has no row. A row stands whatever the time left: on a marked step of a work item with no
  estimate, and on an outrun step, its so far then never under its longest.
- **The run's row** (`run_figures`, `{so_far_minutes, normal_minutes, slow_minutes}`), none of it
  by phases. The run is the work items on the running one's conversation, the running one alone
  where it has none, and its start the start of its first work item's first turn. So far is the
  durations of the Step Timings its work items' finished steps left, the seed's not among them, and
  its running steps' time run. Normal is every step on the running work item's
  list that stood listed ahead, at its kind's price as the timings stood at the run's start, a step
  not listed ahead adding nothing, its cost in the price, so that it holds still while the run goes
  on and grows only as the list gains a step; a begun step whose listing the work item does not
  know, one a continuation's first list brings, takes the listing of the earliest of the run's other
  work items that knows it, and counts as listed where none does. Slow is normal times
  `ESTIMATE_RUN_SLOW_FACTOR`. No run row stands on a list of one step, where a step listed ahead
  has no kind, or where its kind had no price at the run's start.

So far and the longest are to the nearest minute, normal and slow to the nearest minute under an
hour and to the nearest five minutes from one, not by the badge's rounding; the page words them
"18 min", "1 h", "2 h 10 min" (`minutesWords()`, `status-labels.ts`).

**Opened** (`EtaBadge`, [`ui.md`](ui.md)), the badge's pop has on the alert its sentence first;
else, in a project's head, the work item's title ([`projects.md`](projects.md)), and on the work
item nothing; then the table, the run's row last as *The run*; then, muted, a line under it per
running step's row, "Red past 52 min: no code-writer step of the last 60 ran longer."
(`estimateRedLine()`). A badge with no row and no alert opens nothing; an alert with no row opens
its sentence alone.

**The alert's sentence** (`estimateAlertSentence()`) says, on a step the workflow marks, "It has
run 12 min, and its run marks this step as in trouble: it may be stuck.", and otherwise "It has run
12 min, longer than such work usually takes: it may be stuck.", "It" the work item's title in a
project's head. Its time is the run's so far, `ran_seconds`, the run row's *So far* where it
stands, on a list of one step too, and never the Session's clock, which a Resume restarts. A marked
step keeps the marked sentence once it has also outrun its kind (D268): the table already shows the
outrun, its so far past the red line, and only the sentence can say the run marked it, which keeps
its words through a stuck step.

## Its debrief

A worker's run may carry a debrief: the stage session's own account of how the run went, and every
account the run's roles gave, an entry each, in the order given, as a workflow's run gives it in
the turn its loop completes in. Its session hands it over once, before its turn ends, through `pilot-work`'s `register_debrief`
([`mcp.md`](mcp.md)), and the record keeps it as given (`work.debrief` and `debrief_entries`,
[`record.md`](record.md)), with the loop's figures where the workflow gives them
(`work.debrief_figures`), which the pre-ruling pass after the run's turn reads
([below](#pilots-own-work)) and nothing shows. A job has none. The work item shows it once it is done, and the
debrief's notice carries it ([below](#its-debriefs-notice)): nothing of it shows while the item is
open, and a run that gave none shows nothing. Every value in it, a section's
name, a round, a role, a why, is the workflow's, shown as given; Pilot groups and counts the entries
and reads nothing else of the workflow's shape from them (D159).

**`GET /api/items/<id>/debrief`** (`TimelineService.debrief`) answers `{debrief, sections}`: the
stage session's words, and the entries in their sections, `{name, rounds, duration, entries}`,
each entry `{round, role, duration, words, passed, why}`, every value as given. A section is a run
of consecutive entries of one section's name, compared exactly, in the order given, so that the same
name further on starts a section of its own (`debrief_sections`); `rounds` counts the distinct
rounds in it and `duration` sums its entries' times, in whole seconds. It answers `404` for an id
that names no work item, one not done, and one whose session gave no debrief.

**The Debrief** (`DebriefButton`, `components/timeline/debrief-button.tsx`) stands on the done line
of a work item whose `debriefed` is true ([`timeline.md`](timeline.md)): an icon button, the
notebook, "Debrief" its name and its tooltip, shown always and on a phone too, right after the
line's actions shown under the mouse, so that it never moves as they show (D158). The line still
does not expand (D218). It opens the debrief at `/projects/<project>/sessions/<session>/debrief`,
under the session log's address, which the project's route opens where the session log opens and
as the log does ([below](#the-session-log)): off a phone in the log's popover over the tab showing,
replacing the entry, the Debrief pressed again closing it; on a phone as a view pushed over the
tabs. On a phone the session log's view carries the Debrief in its head too, before Discuss, and it
pushes the debrief over the log.

**The debrief** (`DebriefOverlay`, `components/overlay/debrief-overlay.tsx`): its head the notebook
and "Debrief", over the item's title and the time its turn ended, and *Full debrief* at its end;
its body the stage session's words as Markdown, the frame's full width. An address that names no
work item of the project, or one whose read fails, reads "The debrief did not load."

**The full debrief**, behind *Full debrief*, at `…/debrief/full`: off a phone in the same popover,
taller, at most 640px high, the arrow back to the debrief at the left of its head, each move
between the two replacing the entry, and Esc giving the focus back to the line's Debrief; on a
phone a view pushed over the debrief's. Its head is the notebook and "Full debrief" over the item's
title. Its body is first the sections as a table, Section, Rounds and Time: a row per section, its
name on one line, cut short with an ellipsis, the whole name its tooltip, its rounds, bold past one,
and its time; a row clicked, or its name pressed from the keyboard, scrolls the body to its section.
Then the sections, each its name and its entries in the order given, each with its role and its
time: its words as Markdown, its role bold; or its pass or fail, "passed" or "failed", muted, a fail
in the warning's colour; or neither, its role and its time alone, muted. An entry that carries a why
opens its round with a line of its own, "Round N" and the why. A time reads "<1m" under a minute,
then "17m", "1h 40m".

## Its debrief's notice

A debrief may name its `subject`, what it is an account of, as the workflow names it, and says
whether it `completes` that account: false where a later debrief of the same subject completes it,
true where left out ([`mcp.md`](mcp.md)). The `dev` plugin's stages name the slice, `Slice <number>
· <title>`, the planning's debrief not completing it and the run's completing it. Both are kept
with the debrief and never changed (`work.debrief_subject`, `work.debrief_completes`,
[`record.md`](record.md)); a debrief given before Pilot took them has neither.

**Its placing.** A work item whose debrief completes has the debrief's notice placed once the
pre-ruling pass after its turn has ended ([below](#pilots-own-work)), so that Pilot's lines (below)
are in it when it is first seen; or at its close for good ([above](#closed-for-good)), which no
pass follows, in the close's transaction. Every end of the pass places it, in the transaction of
that end or on a loop of its own once it commits, under the project's row held exclusively
(`RecordService.debrief_notice_after_pass`, [`engine.md`](engine.md)):

- its last turn's end, idle or failed, and a start of it that failed, its first turn's or a
  continuation's, before the clarification run of a pass that asked its writer
  (`ClarificationService.pass_ended`, [`round-trip.md`](round-trip.md)); and a reading that decides
  the quota wall missed ([`usage.md`](usage.md));
- a person's Stop and take over of what the pass holds
  ([`round-trip.md`](round-trip.md#stop-and-take-over));
- a turn of it interrupted from outside Pilot, and a stop made elsewhere ([`sessions.md`](sessions.md));
- for a pass the store's update stopped, the end of the job the lift retries, or the lift itself
  for a job whose retry it left to a person ([`store-update.md`](store-update.md)).

A pass that failed or was stopped places it with no lines but those it wrote before; a person's
Retry of the pass finds it placed and writes its lines into it. Finish and Archive, which stop the
pass, place none, nor does any end in a project finished or archived by then.

The notice is an item of the kind `debrief_notice`, a form of its own with no document, created by
Pilot and by no session, taking the timeline's next place, on the work item's plan task, never
urgent and for no one: placed at a pass's end, it follows the pass's own line, and comes before the
clarification run of a pass that asked. Its title is "Debrief · <subject>", or "Debrief · <the work item's title>" for a
debrief that names no subject. It carries that debrief and, where it names a subject, the debrief
of every done work item of the project with the same subject that does not complete and that no
notice carries yet: a slice's planning and its run in one notice, a slice planned twice carrying
both plannings. Each Work it carries names it (`work.debrief_notice_id`), so a debrief is carried
once, and an end that finds its run carried already places none. A debrief that does not complete
places none, nor does one given with no `completes`, since nothing is backfilled; a run that gave
no debrief, and every job, places none.

**The stage's time.** Each work item the notice carries comes with the time its stage took
(`stage_times`, `backend/app/engine/debriefs.py`), read from the record at every read and stored
nowhere: the turns that have ended of the work item and of every work item of the project on its
conversation placed before it, the runs a hand-back continued and the clarification runs among
them, each from its start to its end, summed in the database and rounded once to whole seconds.
The time between two turns, waiting on a person's answers, counts nothing, nor does a turn still
running; a work item whose session has no conversation counts its own turns. A planning and a run
each have a conversation of their own, so a slice planned twice shows three times, each with its
work item's title.

**Pilot's lines.** The pass after the run's turn may write Pilot's lines on its debrief, what it
finds notable in the stage read against the project's journal
([`documents.md`](documents.md#the-handbook-the-journal-and-the-project-document)), through
`pilot-store`'s `write_notable` ([`mcp.md`](mcp.md)): Markdown, kept on the work item
(`work.debrief_notable`), a later call, a Retry's included, replacing them. Lines written before the
notice is placed show once it is; lines written to a work item a notice carries move the notice's
row in `timeline.json` and its box at once. What is notable is the pass's to judge, and
PilotProjects' `pre-rule` skill has a planning's pass write the journal alone, so a notice's lines
are normally its run's.

**Its read.** On the timeline it has `form` `debrief_notice`, `author` Pilot, and `debriefs`, each
work item it carries as `{id, title, ended_at, debrief, stage_time, notable}`, in timeline order,
read from the work item at every read: `ended_at` the time it was done, `stage_time` its stage's
time in whole seconds and `notable` Pilot's lines on its debrief, null where there are none
([`timeline.md`](timeline.md)). Its row in `timeline.json` is an item's row with `notable`, the
lines of each work item it carries that has them, in timeline order, `[]` where none has, and with
no file and none of the debriefs' words ([`projection.md`](projection.md)); `add_item` makes none.

**Its box** (`DebriefNotice`, `components/timeline/debrief-notice.tsx`): its head, the Debrief's
notebook and "Notice" in the kind's place, with the time and Discuss; its title; then each work
item it carries, in timeline order, its title and its stage's time in the full debrief's format
([above](#its-debrief); `took`, `lib/utils/time-format.ts`), the times in a column of their own
beside titles that wrap; then Pilot's lines as Markdown, with no heading of the box's own, each
work item's that has them one under the other in timeline order, nothing saying which work item
they are about, and nothing standing there where the pass wrote none; then *Details*, closed, with
the confirmation's chevron, *Less* once open. Under it stands, per work item in timeline order, a
head with the item's title and the time it was done, its debrief whole as Markdown, and under it
*Full debrief* and *Session log*, which open that item's full debrief ([above](#its-debrief)) and
its session log ([below](#the-session-log)) at their addresses, off a phone in the log's popover
and on a phone as views pushed over the tabs; no line stands beside a work item's part, and its
head is sized halfway between the body's text and the box's title (D246). Under the whole, its
Read. Whether *Details* is open is the page's own and recorded nowhere: it stays open through a
live read of the timeline and an overlay opened over it, and the box is drawn closed after a reload
and after Read and its Undo. It folds as any open item, and Discuss quotes it by its title, the
brain reading Pilot's lines from its row in `timeline.json`.

**Its Read** is a member's alone: Read in the app (`POST /api/items/<id>/read`), or the brain's
`mark` `read` with `for` them, on their word ([`mcp.md`](mcp.md)). It is done `marked` by them,
places no job and is consumed by no session, so its Undo stands, which opens the same notice again.
Pilot never reads one on its own ("Pilot reads a debrief's notice only on a member's word"); Done,
Reviewed and the chat's cancel are refused on it, and Finish closes it as every open item,
`finished`, with no Undo. Read, it is a done line with nothing behind it, as a wait's: its title,
plain, and the time it was read, with Undo and Discuss and no Open, and on a phone a tap on it
opens the menu of its Discuss ([`timeline.md`](timeline.md)).

**It waits on nobody.** The badge, the project's status and its notification leave it out, since
what waits on a person is read by form ([`projects.md`](projects.md)); "N open above" counts it
until it is read ([`timeline.md`](timeline.md)). It holds nothing up: its Read starts no work. What
the pass makes of a debrief for the operator is its lines in it: PilotProjects' `pre-rule` skill
writes no note or notice of a debrief and makes no card of it. The work items' lines and their
Debrief stay as they are.

The plugin's half went out with the slice's run, not after Pilot's promotion (D238): it sends
`subject` and `completes` only to a Pilot whose `register_debrief` lists both, so that a Pilot
without them stores the debrief alone, on its work item, and places no notice, and `figures` only
to a Pilot whose `register_debrief` lists it.

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
  has one, or, for an offer taken, the Pilot Note whose offer it was, and no repository;
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

**The prompt cache.** A job of trigger `setup`, `worker_turn_ended`, `item_done` or `offer_taken` runs on Claude
Code's 5-minute prompt cache (D141): its create's `env` carries `CLAUDE_CODE_PROMPT_CACHE_TTL=5m`
after `PILOT_SESSION`, at its start and at the relay's create of it anew alike, a finished
project's job's too (`FIVE_MINUTE_JOBS`, `backend/app/services/session_scope.py`). Such a job
starts fresh and ends in one turn, so an hour's cache, whose writes cost more than the 5-minute
cache's, buys it nothing. A wait's run, which may resume its previous run's conversation within
`CACHE_EXPIRATION_TTL` (below), a chat and a work item's run carry no such entry and keep Claude
Code's own, the hour on a subscription within its usage limits.

**The triggers.** Five place a job:

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
  which no session added. The chat's close and the save's are consumed on the spot, by the chat's
  Session and by the Session the save is credited to, so that neither offers an Undo after it, as
  after a job's brief (D225, D226).
- **An offer taken**, trigger `offer_taken`, naming the Pilot Note whose offer a member took and no
  trigger item, titled `Starting the work offered on <local id>`: a member's press of the offer of
  Pilot's note on an action ([`timeline.md`](timeline.md#pilots-note-on-an-ask)), placed at the
  taking's instant in the press's transaction, which holds the project's row. Nothing withdraws it,
  a taking being never undone.
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
pause holds no setup. The setup's carries instead, while Create's pause stands, the project paused
and its latest pause Pilot's (D083), never a person's, `Create project paused the project: every
work item you add is held until a person resumes it.` Then the trigger's payload, below, and after
it the project's state and the handbook whole, as the chat's brief carries them, a job's seqs first
([`chats.md`](chats.md#the-projects-state)). By trigger:

- **The setup**: `/plan`, kind `the setup`; `The project was created <stamp> from draft-<number>;
  its folder is now /work/Projects/<slug>.`, `The draft: project.md (the opening item <id> holds
  the words that started it; the draft's copy and what the chat attached hang on it).` and `The
  plan: plan.json, empty.`; its seqs line names the job alone.
- **A worker's turn ended**: `/pre-rule`, kind `a worker's turn ended`, where the run left the pass
  something: a document it registered, one whose read failed included, a debrief its session gave,
  or a block it researched; else `/plan`, under the same kind line and with the same lines, its
  What is next taking them with no pass before it (D244). The work item's line, `The
  work item: "<title>" (<id>)`, its plan task, repository, environment by its id and controller
  session by its name, each that it has, `; its turn ended <stamp>` and ` — the item's last line:
  "<line>"`, the last non-blank line of the text its turn ended with, where there is one and the run
  registered a document; then
  `Registered this run, in the order registered:` and a line per document, `- <path> (<item id>) —
  published` or `— read failed: <reason>`, or `Registered nothing this run.`, which, where the turn
  ended with text, goes on ` Its final message, whole:` and the text, each line quoted with `> `
  (a blank one `>`), the work item's line then leaving its last line out, so that a finding stated
  only in a silent turn's message reaches the pass whole (P-291); then `Attached on the
  work item: 1 file (timeline.json lists it).` or `<N> files (timeline.json lists them).` where some
  are; then, where its session gave its debrief, the stage's full debrief, which the pass reads, an
  exception the operator ruled to what the brain is given (D219), each heading a line of its own:
  `The stage session's debrief, as given:` and its words, the whitespace they end in left off;
  `The debrief's entries, each whole and as given, in the order given, under its section, round,
  role and time:` and per entry `- <section> · round <n> · <role> · <time>`, ending ` · passed` or
  ` · failed` where it has a result, and under it, set in two spaces, `Why this round was needed:
  <why>` where it opens a round and its words, all left out where the debrief has no entry; `The
  loop's figures, as given:` and the figures, where it gave them; `The work items the debrief's
  notice carries, each with the time its stage took, its turns summed:` and `- "<title>" (<id>) —
  <time>` per work item the notice carries, or takes when it is placed, in timeline order
  ([above](#its-debriefs-notice)), a time reading as the full debrief's, `<1m`, `17m`, `1h 40m`;
  and `The project's journal, journal.md, whole:` and its text, or `The project's journal:
  journal.md, empty.`, this the one brief that carries the journal; then,
  where the work item or another on its conversation was given claimed actions, its
  standing naming theirs, so that a continuation's names those of the run it continues and a retry,
  on a conversation of its own, takes them from it (D100), `The claimed actions given to this work
  item, as they stand:` and a line per action in timeline order, `- <path> (<item id>) <local id>
  open, claimed`, `… open, claimed, handed back to the operator: leave it to them` once the run no
  longer holds it ([`round-trip.md`](round-trip.md)), `… open, its claim gone`, or its close as the
  record holds it, a person's Done meanwhile included; then, where the run was given blocks to
  research, its standing naming theirs as a claim's is, `The blocks this work item researched, as
  they stand:` and a line per block in timeline order, `- <path> (<item id>) <local id> open`, `…
  open, handed back to the operator: leave it to them`, `… open, claimed` where it was claimed
  since, or its answer as the record holds it, `Q1 "Two hosts" (by ada)`.
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
  then the full debrief the clarification run's own session gave, with the journal, as a worker's
  turn's brief has them.
  The pass it briefs asks the writer nothing ([`mcp.md`](mcp.md)).
- **An item of Pilot's own is done**: `/plan`, kind `an item of yours is done`; `The item: <path>
  (<item id>), <kind> "<title>"[, task <id>] — <close>.`, the close as the record holds it: a
  one-ask item's block answered or done, by whom and when, its channel and its note as given (a
  confirmation `answered Yes|No by <handle> at <stamp>`, an action `<id> done by …`, an answer an
  option's label, `Agree`, `deferred to <to>`, a question's words quoted, other words quoted with
  `(Other)`); a document's `Done by <handle> at <stamp>; its blocks:` and a line per block; a
  review's `Reviewed by <handle> at <stamp>`. Its return list names the open notes of the item's
  plan task and the plan's own.
- **An offer taken**: `/plan`, kind `an offer of yours was taken`; `The offer, on action <local id>
  of <path> (<item id>), <kind> "<title>"[, task <id>]:`, the action's own section quoted, `> ` a
  line, then `Your note: "<text>"`, `Your suggested answer: "…"` and `Your suggested note: "…"` where
  the note holds them, `Your offer: "…"` and `Taken by <handle> at <stamp>.`; its return list as
  after an item's close, its seqs naming the item the note is on. The plan skill starts the offered
  work as any work item and writes nothing on the block (PilotProjects).
- **A wait's firings**: `/plan`, kind `a wait fired`; the wait's line, what it waits on, since when
  and its task, then `Firings pending, oldest first:` and a line per firing it took
  (their words in [`waits.md`](waits.md)); its return list names the open notes of the wait's task
  and the plan's own.

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
trigger item or Pilot Note, and title, at the project's next place, behind every job already waiting, briefed as it
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
whose turn ended, the item of Pilot's whose close placed it, the wait that fired; and an offer's on
the item its note stands on. Where several
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
  ([`chats.md`](chats.md)), so that a finished work item is discussed from there (D127), and before
  it the Debrief, where the item has one ([above](#its-debrief)).
- **What each turn was sent**: before a turn's reply stands what the server sent it, as Pilot's
  message, "Pilot" and its time under it (`SentMessage`, `.log-sent`), cut after 8 lines with Show
more over the end of the last and, once opened, Show less after its last word, the one pressed
handing the focus to the other (`Clamp`, `components/shared/clamp.tsx`): a work
  item's brief, a continuation's message, a Resume's `continue`, every turn with no author, in a work
  item's log and a job's alike (D150). A turn sent and not yet answered shows its message alone, and
  so does one the gate holds before it is sent, a Resume's, a continuation's or a nudge's.
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
  turn in flight is doing, or "Starting" and "Waiting for Pilot" before its first record. A turn
  whose model has ended its own turn on a task it left running in the background reads "Waiting on
  a background command · <description> · <time>", the time how long the turn has waited since,
  "3 min 20 s" (`activityOf`, `lib/chat/activity.ts`); the worker's nudge and the model's answer to
  it leave it as it is, and the command's call reads as running until the task's notification
  (`isRunning`, `lib/chat/view.ts`). Its dancing
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
a record names a turn the last read did not hold, at each move of the work item's state, whose event
follows the commit that stores a held Turn, and at every open of the log; the log merges the two by
the turn's number.

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
failed" after its steps, the one red in it. Under the mouse a run's line stands in a rounded box,
its border clear away from the mouse so that nothing moves under it, 6px out of the reply's column
on either side; opened, the box stays, round the line and its calls, a divider under the line. Each
text a run's line shows, its words and its count
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
`progress.spec.ts`, the progress button and its popover, a step's why among them,
`full-debrief.spec.ts`, the full debrief, `session-log.spec.ts`, `switch-warning.spec.ts`, `usage-halts.spec.ts`, `hard-stop.spec.ts` and
`nudge.spec.ts`, the usage limits ([`usage.md`](usage.md)), and `registered.spec.ts`, the round trip of a
registered document ([`round-trip.md`](round-trip.md)), with `clarification.spec.ts`, the
clarification run and its reply, `claimed.spec.ts`, a claimed action, and `estimate.spec.ts`, the
badge of the time it still takes, on the work item and the head, its figures, its alert and its
read each minute. The estimate's rules and its figures are pinned in
`backend/tests/services/test_step_estimate.py`, a step's timing in `test_pilot_work_service.py`, the status's `estimate` in `test_timeline_service.py`
and the minute's read in `test_project_service.py` and `backend/tests/api/test_projects.py`, on
`backend/tests/support/estimates.py`'s `ESTIMATES`, `timed` and `listed`. A spec that needs an
estimate publishes a kind's steps pending, then running, then done: a step first published running
on a work item's first list leaves a timing whose listing is unknown, which counts in nothing.
Pilot's jobs are pinned in
`backend/tests/services/test_job_service.py` (their placement, the queue, the triggers, the
withdrawal and Retry), `test_start_gate.py`, `test_brief_service.py` and
`backend/tests/models/test_work.py` (`retried_by`), and where each shows in `TestJobsOn`
(`backend/tests/services/test_working_on.py`); the setup's line, its queue's and Retry's, and the
pause at Create, in `frontend/tests/projects/create-project.spec.ts`; a job on the item it follows
from, its forms, its Retry, an open card's head, the phone's row and a wait menu's, and the job in an
opened document's head and a run's log's, in `frontend/tests/timeline/jobs.spec.ts`; and a withdrawn
job, shown nowhere, in `frontend/tests/timeline/undo.spec.ts`. The session log's popover is pinned in
`session-log.spec.ts`, and what the log shows a turn was sent there too. The debrief's read and its
sections are pinned in `TestDebrief` (`test_timeline_service.py`) and `TestGetItemDebrief`
(`backend/tests/api/test_items.py`), its brief in `test_brief_service.py`; the Debrief on the line
in `timeline.spec.ts`, `frontend/tests/timeline/line-actions.spec.ts` (it never moves as the actions
show) and `phone-items.spec.ts`, and the debrief in the log's popover in `session-log.spec.ts`. The
debrief's notice, its placing and what it carries, its Read and Undo, is pinned in
`TestRecordServiceDebriefNotice` and `TestRecordServiceDebriefNoticeRead`
(`backend/tests/engine/test_record.py`), Pilot's lines in `TestRecordServiceWriteNotable` there, the
work items it carries and their stages' times in `TestOfNotice` and `TestStageTimes`
(`backend/tests/engine/test_debriefs.py`), its read in `TestDebriefNotice` (`test_timeline_service.py`),
and each end of the pass that places it in `TestDebriefNoticeAtThePassEnd`,
`TestDebriefNoticeAtAStopMadeElsewhere` and `TestDebriefNoticeAfterARestart`
(`test_relay_service.py`), `TestPassEndsOffItsTurnsEnd`, `TestQuotaWallsPass` and the take-over's
test (`test_session_start_service.py`), `test_clarification_service.py` and
`test_store_updater.py`; the pass's brief, the full debrief and the journal, in
`test_brief_service.py`. Its box, the stages' times, Pilot's lines and Details, its links, its
Read, Undo and line, its fold and Discuss, the badge and the status leaving it out, and its phone
views are in `frontend/tests/timeline/debrief-notice.spec.ts`, whose specs run the pass after each
work item to its end in the store (`chats.passing`), or hold it open (`chats.pass(project)`),
since the notice waits on it. A spec that reads the badge or the project's status runs Pilot's job
after each worker's turn in the store too, since that job left alone fails to start and waits on a
person.

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
steps as its session's `set_progress` does while its turn runs, and `projects.debrief(work, words,
entries?, {subject?, completes?})` gives its debrief as its session's `register_debrief` does, one
invented entry where none are given (`DebriefEntry` their type), with no subject and completing
where left out, and `projects.writeNotable(work, text)` writes Pilot's lines on it as the pass's
`write_notable` does, with no pass; `projects.seeded(name)` answers the id of a project of the dev
seed, whose address it then knows as a made project's; `projects.register(work, path, toolUseId?)` and
`projects.workerAttach(work, path, {to?, toolUseId?})` make its worker's calls, each its effect
while its turn is in flight, `projects.askWriter(document, [{block, question}])` the pass's
question, and `projects.clarify(document, reply?)` its clarification run, ended with the reply, or
with none started in the writer's environment, where `controller.finish(env, <its session>,
'success', reply)` ends it ([`projects.md`](projects.md)). The `sessionLog` fixture's `steps` reads
a reply's steps in order and `effects` the effects standing on their own. The `timeline` page
object's `item(id).work` reads the open item (`environment`, `running`, `line`, whose `data-state`
is the Session's state, `cue`, `step`, `sessionLog`, `stop`, `row`, `progress`, with
`progressRing` and `progressName`, `steps`, its popover, with `whys`, `resume`, `stopConfirm`,
`retry`), and `item(id).debrief` a done line's Debrief; of an open debrief's notice,
`item(id).stages` the lines of the work items it carries and `item(id).stage(workId)` one of them
(`title`, `time`), `item(id).notable` Pilot's lines, `item(id).debriefDetails` its Details, and,
under it, `item(id).debriefs` the work items' parts and `item(id).carried(workId)` one of them
(`title`, `ended`, `text`, `full`, `sessionLog`); its
`item(id).job` Pilot's job on the item (`root`, with `data-form` its form, `pulse`, `retry`), and
the `sessionLog` fixture the log (`sessionLogAddress()`, `overlay`, the popover or the view), its
head (`head`, `sub`, `close`, the job after a run's turn `job`, a phone's `debrief` and `discuss`)
and what each turn was sent (`sent`, `sentTexts`, `sentEnds`, `sentMore`). The `debrief` fixture
(`DebriefPage`, `tests/support/page-objects/debrief-page.ts`) reads the debrief at
`debriefAddress()` and the full debrief at `fullDebriefAddress()`: the head, the words, `full`, the
table's rows and the sections with their entries. A job's own entry draws nothing:
`timeline.item(jobId).root` has none. A spec placing an
item in a project while a work item's start there still writes waits for that item to run first. The
backends run with `WORK_PARALLELISM_MAX` 10000 and `PROJECT_PARALLELISM_MAX` 3
(`loadAppBackendEnv()`, [`controller.md`](controller.md), which also gives them their store,
[`chats.md`](chats.md)): a worker's specs share a backend and leave work items running, each in
projects of its own, so the slot across every project never closes, and a project's fourth running
or starting work item is held for a slot.
