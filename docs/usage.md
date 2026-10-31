# Usage limits

Pilot watches the subscription's usage app-wide, as KubeCoder's controller reads it, and holds
**work items alone** at its limits: a project's chat and Pilot's own jobs, the brain's work in the
store, run under any limit, small in volume and mostly a person's own doing. This page is the
limits as built: the reading, the week's and the five-hour halts and their settings, the week's
overrule, what a halt does to running work, a run halted or paused at its turn's end, the nudge,
the quota wall, and each turn's tokens. The halts show on the gold bar ([`ui.md`](ui.md)), a held
or stopped work item's line says why ([`work.md`](work.md)), the tables are in
[`record.md`](record.md), and the loops and timers run as [`jobs.md`](jobs.md) says.

| Service | Does |
|---|---|
| `UsageService` (`usage_service.py`) | the readings off the fleet stream, recorded |
| `UsageHalts` (`usage_halts.py`) | the halts and the week's overrule, decided from the latest reading |
| `UsageWatcher` (`usage_halts.py`) | decides them again at each reading, overrule and tick, and moves what a turn moves |
| `QuotaOverruleService` (`quota_overrule_service.py`) | a person's overrule |
| `HaltFileService` (`halt_file_service.py`) | the halt file |
| `quota_wall.py` | the quota wall: how it is told, and when there is quota again |
| `token_counts.py` | each turn's tokens and cost |

All are in `backend/app/services/`. The hard stop and the nudge are `SessionStartService`'s
([`sessions.md`](sessions.md)).

## The reading

The controller polls the subscription's usage and serves the reading as the fleet stream's `usage`
frame (`UsageFrame`, [`controller.md`](controller.md)): `{takenAt, stale, staleReason, windows:
[{window, share, resetsAt}]}`, a window `five_hour` or `seven_day`, its `share` a fraction of its
quota that may pass 1, a window the endpoint left out missing, and, before the poll's first answer,
`takenAt` null and no window. The stream sends it first on every connect, then at each change of
anything but `takenAt`; Pilot does not call the controller's `GET /usage`. Each stage reads the
controller it runs on, `CONTROLLER_URL` ([`deployment.md`](deployment.md)).

The fleet consumer hands every `usage` frame to `UsageService.receive`. A reading with figures is
recorded, a `usage_readings` row with a `window_shares` row per window, when its `takenAt` is not
older than the latest recorded and its figures or `stale` differ from that one's, so a reconnect's
seed is not recorded again. A reading with no figures leaves the latest as it is. The comparison and
the insert run under `LOCK TABLE usage_readings IN EXCLUSIVE MODE`, which stamps `received_at` too,
so two backends overlapping in a roll record a reading once. The latest recorded, by `id`, is the
one the halts read; why a reading is stale is the log's alone. Each reading recorded is told to the
watcher once its commit is done.

Each reading received logs one line: `Usage reading <n> recorded, taken at <time>: <figures>`, with
`; stale (<reason>)` for a stale one, `… unchanged since the latest recorded`, `… older than the
latest recorded …: ignored`, or `Usage reading without figures (<reason>): the latest recorded
stands`. The gauge `pilot_usage_reading_age_seconds`, per process, is 0 while the figures it last
received are fresh, the seconds since their `takenAt` while they are stale, and NaN before the
first reading with figures.

## The halts

Two halts, decided from the latest reading and never stored (`UsageHalts`):

- **The week's halt** holds while the reading's `seven_day` share is at or over `WEEK_FIRST_LIMIT`
  and no overrule holds (below).
- **The five-hour halt** holds while its `five_hour` share is at or over `FIVE_HOUR_LIMIT`; a limit
  of 0 holds none. It has no overrule.

A window the reading leaves out holds no halt, none holds before the first reading, and a window of
a stale reading counts as reset one minute past its `resetsAt`, the margin for clock skew: its halt
lifts then, until a reading decides again. Either halt holds a work item's start at the gate, ahead
of every other reason, the week's named while both hold (`held_reason` `week_halt` or
`five_hour_halt`, [`sessions.md`](sessions.md)); a chat's start and a job's go on.

A halt began at the receipt of the first reading of the unbroken run of readings that hold it: a
reading that leaves its window out or puts it under the limit breaks the run, and so does a stale
one past its minute before the next one came. The week's halt held again at an overrule's end began
at that end. It is derived from the readings, so a restart keeps it.

| Setting | Default | |
|---|---|---|
| `WEEK_FIRST_LIMIT` | 0.90 | the week's share at or over which the week's halt holds; above 0, at most 1 |
| `WEEK_ALLOWANCE` | 0.05 | what an allowance adds to the week's share for its target; above 0, at most 1 |
| `WEEK_SECOND_LIMIT` | 0.98 | the allowance's highest target, and the week's share at or over which run-out is offered in its place; above 0, at most 1 |
| `FIVE_HOUR_LIMIT` | 0.75 | the five-hour share at or over which the five-hour halt holds; 0 holds none; at most 1 |
| `WEEK_HALT` | `cooperative_stop` | what the week's halt does to the work items: `no_new_work`, `cooperative_stop` or `hard_stop` |
| `FIVE_HOUR_HALT` | `cooperative_stop` | what the five-hour halt does to them, the same three values |

The backend refuses to start with a first limit over the second. The deployment's chart sets none of
them, so both stages run these defaults ([`deployment.md`](deployment.md)).

**The watcher** (`UsageWatcher`) decides the halts again at each reading recorded, once its commit
is done; at each overrule made, once its request commits; and on every tick of the timer
`usage-halts`, which finds a stale window's minute passed, the design's one clock. Each decision
first ends the overrule the latest reading has spent (below). At a halt's turn, on or off, and at an
overrule made, it asks the gate again (`release_held`), sweeps the halt files, sends the nudges
owed and tells the conditions; at a reading recorded while a halt holds, and at an overrule's end,
it tells the conditions too, since the figures have moved; at a reading recorded while a turn at
the quota wall owes its nudge, it sends the nudges; and at every decision while a hard-stop halt
holds and a work item's Session is `running`, it asks for the hard stop. An effect that fails is
logged and keeps no other from running. Each process decides from the same readings, and the halts
it last told of are its own, none at its start, so a halt that holds at a start is told at the
first tick. A turn logs `The week's halt holds: work items' starts are held` or `The five-hour halt
lifted: held work items go on`, and an overrule's end `Quota overrule <id> (<kind>) ended: …`.

Each halt that holds is a condition of the conditions service, `week_halt` and `five_hour_halt`,
after the outage, the week's first, with its `since`, its `share`, the reading's `taken_at` and
whether it is `stale`, and the week's with the overrule it offers (`GET /api/conditions`,
[`ui.md`](ui.md)); the alarms take them by their codes ([`notifications.md`](notifications.md)).
A halt's line gives the reading's age, "as of <time>", only while the reading is stale (D102): the
frame goes out only when something but `takenAt` changes, so a fresh reading's `takenAt` is its
figures' last change, and the reading itself is current to within the poll.

## The overrule

The week's halt offers one overrule at a time, anyone's to make: under the second limit **the
allowance**, its target the week's share plus `WEEK_ALLOWANCE`, summed in decimal so that a reading
at the target reaches it, at most the second limit; at or over the second limit **run-out**, its
target the wall, the whole quota. At the wall, a week's share of 1 or over, it offers none: nothing
runs there, and a run-out made there would be spent at the watcher's next decision, the halt back at
once (D101). The five-hour halt offers none.

**`POST /api/quota-overrules`** `{kind}`, `allowance` or `run_out`, behind the API's `editor` gate
(`QuotaOverruleService.make`), makes it as the signed-in person and answers `201` `{id, kind,
target, made_at}`, `target` a fraction for the allowance and null for run-out. It answers `400` for
a kind that is no overrule's, and `409` when the caller has no handle, an overrule holds already,
the week's halt does not hold, the week's share is at the wall, or it offers the other kind ("Cannot
add the week's allowance because …", "Cannot run out the week's quota because …"): the person gets
the kind they clicked or nothing.
The make locks `quota_overrules` in SHARE ROW EXCLUSIVE mode, so makes go one at a time, and
`usage_readings` in SHARE mode, so that a reading's receipt and a make order as their commits. Once
the make commits, the watcher lifts the week's halt: the gate is asked again, the nudges owed are
sent and the conditions told.

An overrule holds until the server writes its `ended_at`, once, at the first decision whose latest
reading spends it: its week share at or over the target, 1 for run-out; its week share lower than
the reading before it that carries the week, a reset used, credits added or the week's turn, when it
was received after the overrule was made; or, stale, its week a minute past its `resetsAt`. The
week's halt then holds again if the share is at or over the first limit, and a new overrule takes
its target from there.

## What a halt does to running work

Each window's halt setting says it, the three on one mechanism:

- **`no_new_work`**: the gate holds the work items' starts, and the running ones go on.
- **`cooperative_stop`**: as `no_new_work`, and the halt file written where a work item runs, a
  request to the session's own tooling to end its turn early, which Pilot does not wait on; the run
  is then not done at its turn's end (below).
- **`hard_stop`**: as `no_new_work`, and every running work item stopped.

**The halt file**, `/work/.quota-limit-halt-requested`, written empty (`HaltFileService`), is
wanted in an environment where a work item's Session is `running` under a usage halt whose setting
is the cooperative stop, or under its project's pause ([`projects.md`](projects.md)), and nowhere
else: never for a job's Session or a chat's, so never in the store. Two projects sharing an
environment share its file, and so do a halt and a pause: it goes once nothing holds it there.
`environments.halt_requested_at` says the file may be there: set and committed before the write
goes out, cleared once the delete is answered, so that a write the controller made but whose answer
never came is deleted too. What is owed is read from the rows: an environment whose column is unset
where the file is wanted, or set where it is not. Each is settled by a loop of its own,
`halt-file:<env id>`, under the Environment's row lock, reading again after each write or delete
until nothing is owed; it writes the file wherever it is wanted, whatever the column says, and a
delete the controller answers `404` counts as done. A call the controller does not answer, or
refuses, its `409 conflict` while it works on the tree among the refusals, raises, and the loop
runs again after its backoff. A pause or a resume, a halt's turn, and a work item's run's start
or end, which moves the slots (`WorkSlots`), ask, once committed, for the sweep, the loop `halt-file`, which starts the loop
of every environment owed. The timer `halt-file` sweeps on every tick, and so finds a work item the
gate let through just before a halt or a pause; the job's reconcile at STARTUP settles every
environment owed or whose column is set.

**The hard stop.** While a halt whose setting is the hard stop holds, every decision of the watcher
that finds a work item's Session `running` asks for the loop `start:hard-stop`
(`SessionStartService.stop_halted`): each such Session, in `created_at` order and under its lock
while it still runs and such a halt still holds, is stopped as Stop stops one
([`sessions.md`](sessions.md)), by Pilot, its `nudge_owed_at` the stop's time. So a work item the
gate let through before the halt, or running at a restart, is stopped at the next decision, the
tick at the latest. A `starting` one is left to send its turn first, and a held one stays held. Its
line names the halt that holds it now ([`work.md`](work.md)); it waits on nobody, and its nudge
carries it on.

## A run halted or paused at its turn's end

A work item's turn that ends neither interrupted nor in error makes it done
([`sessions.md`](sessions.md)), unless the halt file is wanted for it then: a usage halt whose
setting is the cooperative stop holds, or its project is paused (`RelayService._halted`). Such a run
is not done (D097): its Session `idle`, its item open, its `nudge_owed_at` its turn's end, and a
clarification run's reply recorded then, its turn's final text, which no later turn replaces
([`round-trip.md`](round-trip.md)). Nothing of its end follows yet, neither the read of the
documents it registered nor the job after its turn. Once nothing holds it, the nudge continues the
same run, and the run is done, its documents read and the job after its turn placed, at its first
normal turn end with neither holding. Under `no_new_work` no file is written and a normal end is
done; a job's turn ends as it always does, done, with no nudge.

While its nudge is owed, the item waits on nobody, and its line says what holds the nudge, in a
held start's words, or "Waiting for its nudge" once nothing does, and so does its session log,
under "The turn ended · <time>" ([`work.md`](work.md)). Stop and
Resume refuse it, as they refuse any Session that is `idle`. It keeps its environment: no other
start takes it ([`controller.md`](controller.md)).

## The nudge

A Session's `nudge_owed_at` is set where its run is to be carried on once there is quota again, or
once its project is resumed: a work item the hard stop stopped (`stopped`), one halted or paused at
its turn's end (`idle`), and a work item or a job whose turn died at the quota wall (`failed`,
below). A chat's Session is never owed one (D096): a turn that fails there shows so, and the person
sends again.

`SessionStartService.send_nudges()` asks for the loop `start:nudges`. Its run first settles each
wall a reading decided missed (below); then it takes each Session whose nudge is owed and that
nothing holds, in the order they were owed: its item open; its project neither finished, archived
nor paused, a setup's nudge going through the pause as the gate lets the setup's start; a work
item's with no usage halt holding; and one at the wall once a reading confirmed it and there is
quota again. Each, under its project's row and then its own lock, read again there, is carried on as
a Resume carries one on (`_carry_on`): a Turn of the server's own with the nudge's words, or the
ended Turn's message while the Session has no conversation, its `error` cleared and its nudge owed
no more, through the gate, `held` or `starting`, a job held behind its project's jobs before it. A
Session whose stopped turn is still ending waits for the next run.

| Owed to | Its words |
|---|---|
| a work item the hard stop stopped, in a paused project too | "Pilot stopped this session at the subscription quota's usage limit, and there is quota again. This is a nudge to allow you to complete any outstanding work, if any." |
| one found ended while its project was paused, as its project's transitions read at `nudge_owed_at` | "The project was paused, and it has been resumed. This is a nudge to allow you to complete any outstanding work, if any." |
| every other: one halted at its turn's end, one at the quota wall | "The subscription quota ran out. This is a nudge to allow you to complete any outstanding work, if any." |

The nudges are asked for at a halt's turn and at an overrule made, at a resume's commit
([`projects.md`](projects.md)), at each reading recorded while a turn at the wall owes its nudge, at
STARTUP, by the start job's reconcile, and by the timer `nudges` on every tick while a nudge owed is
held by nothing or a wall decided missed still owes one. A person's Resume of a hard-stopped work
item clears its nudge owed, its own continuation standing in for it: one continuation, never two.
Finish closes an item whose nudge is owed with its other open items, and its nudge never goes;
Archive keeps it owed, and Bring back lets it go.

## The quota wall

Pilot does nothing when the quota runs out: the session's turn dies at the wall, Claude refusing
it, and ends in error. A work item's or a job's turn that ends in error is at the wall when both
signals tell it (D098, `quota_wall.py`):

- **The turn's own recorded stream shows it**: a `rate_limit_event` line whose window, the one its
  `rateLimitType` names or one of its `unifiedWindows`, has the `status` `rejected`; or a `result`
  line with `is_error` whose `api_error_status` is `429` or whose text says "limit reached" or "hit
  your limit".
- **A reading confirms it**: a window's share at or over 1 in the reading at the turn's end, the
  latest received by then, or in the next one received after it.

The relay marks the Session `failed`, as any work item's turn ended in error is, with its
`nudge_owed_at` its end from the moment its stream shows the wall, so the wait for the deciding
reading holds across a restart. A Session `failed` with its nudge owed is not at its end (D099): it
waits on nobody, out of the project's badge, waiting-on-you and the notification's priority; a job
offers no Retry, which is refused "it waits for its nudge at the quota wall"
([`work.md`](work.md)); and a pass puts no question to the writer, its clarification run placed
only when the run its nudge continues ends ([`round-trip.md`](round-trip.md)). Its nudge goes once
a reading confirmed the wall and there is quota again: no window of the latest reading at or over 1,
a stale one's counting as reset a minute past its `resetsAt`; a work item's with every usage halt
lifted as well. A turn ended at the five-hour wall is nudged so too, once a reading shows the
window reset or its stale reading is past that minute, with no setting or control that holds it for
a person to let it go on (D095). A job's nudge is its run's one continuation, and one whose start
fails puts its pass's questions to the writer once that failure commits.

A reading received after the one at the turn's end that does not confirm the wall, the one at the
end not confirming it either, decides the wall **missed**, a per-model limit, which Pilot does not
track, among the causes. The nudges' loop then clears its nudge owed first, and it is the failed end
it is: a work item waits on the person for a Resume, a job offers Retry, and a pass's questions go
to the writer, unless its project is finished or archived. So a session is never nudged into a wall
that will not lift, turn after turn.

## Each turn's tokens

Every Turn of every Session, a work item's, a job's and a chat's alike, keeps the tokens its run
used and the cost it reports (`token_counts.py`): a `token_counts` row per Token Kind, `input`,
`cache_write`, `cache_read` and `output`, and the Turn's `cost`, in US dollars as Claude reports it,
notional on a subscription ([`record.md`](record.md)). They are read from `claude`'s own `result`
line, which the relay records as it records every line ([`sessions.md`](sessions.md)), in the
transaction that records it: its `modelUsage`, each model the run called with its counts, summed
over the models from `inputTokens`, `cacheCreationInputTokens`, `cacheReadInputTokens` and
`outputTokens`, a count it leaves out being 0, and its `total_cost_usd`. `modelUsage` counts every
call of the run, a sub-agent's included, where the line's `usage` counts the main thread's alone.
KubeCoder runs a fresh `claude` for each turn, so a turn's figures are its own and never include
the turns before it.

One run can print several `result` lines, a backgrounded task waking it again among the causes, each
carrying the run's figures so far: each line recorded writes the counts and the cost in place of an
earlier line's, so the last one's stand. A turn whose run ends by answering KubeCoder's nudge, the
worker's word to a run that left a background task running at its result, keeps the figures from
before that nudge: the worker leaves the nudge turn's lines, its `result` line included, out of the
raw file the relay reads, and the controller's result frame carries no usage, so its calls are not
counted. A line whose `modelUsage` is not a map of per-model counts,
each a non-negative integer, writes nothing, and a `total_cost_usd` that is no finite non-negative
number leaves `cost` null: the relay never fails on what `claude` printed. A turn cut short with no
`result` line keeps none. Nothing in the API or the app shows them; they are read with a query of
`token_counts` joined to `turns`.

## Testing it

The backend pins the reading in `backend/tests/services/test_usage_service.py`,
`backend/tests/models/test_usage.py` and `test_fleet_consumer.py`; the halts, the watcher and the
overrule's ends in `test_usage_halts.py`; the overrule in `test_quota_overrule_service.py`,
`backend/tests/api/test_quota_overrules.py` and `backend/tests/models/test_quota_overrule.py`; the
halt file in `test_halt_file_service.py`; the wall in `test_quota_wall.py`; the hard stop, the nudge
and the wall's nudge in `test_session_start_service.py`; a halted end, the wall's end and the tokens
in `test_relay_service.py`, with `test_token_counts.py`; and the gate's halts in
`test_start_gate.py`. The fake controller serves the reading as a test sets it
([`controller.md`](controller.md)), and `backend/tests/fixtures/raw/turn_wall.jsonl` is an invented
turn at the wall.

The browser suites are `frontend/tests/shell/gold-bar.spec.ts` and `quota-overrule.spec.ts`, and
`frontend/tests/work/usage-halts.spec.ts`, `hard-stop.spec.ts` and `nudge.spec.ts`; a setup at the
wall is in `frontend/tests/projects/create-project.spec.ts`. The `controller` fixture's
`usage({seven_day?, five_hour?})` has the fake's poll answer with those shares, taken now, a window
given none left out, and returns once the backend's halts are those the shares make at the default
limits (`conditions.halts(codes)`); after a spec that moved them, `restore()` puts both shares at
0.1, under every limit, which also ends an overrule the spec left holding.
`fileText(env, '/work/.quota-limit-halt-requested')` reads the halt file, `""` while it is written
and null once deleted. Playwright's backends run the five-hour halt as the hard stop and the week's
as the cooperative stop (`loadAppBackendEnv()`, [`controller.md`](controller.md)).
