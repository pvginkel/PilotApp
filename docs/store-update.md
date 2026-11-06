# The store's update

The store's update brings the store environment onto PilotProjects' `main` while Pilot runs. One
command makes an app-wide hold on the store's work. The server then stops the store's running jobs
and chats, resets the store, waits for its sidecar's first manifest, retries the jobs it stopped
and lifts the hold. A PilotProjects change reaches a store this way ([`deployment.md`](deployment.md)).
This page is the update as built: the command, the hold, the sequence, the retry and the testing
route. The gate it holds starts at is [`sessions.md`](sessions.md)'s, the store's reset
[`controller.md`](controller.md)'s, and the manifest [`sync.md`](sync.md)'s.

| Piece | Does |
|---|---|
| `update-store` (`backend/app/store_update_cli.py`) | the command, run as D135 says ([`slice-test-plan.md`](slice-test-plan.md)): makes an update or asks its lift, and prints each phase |
| `StoreUpdateService` (`store_update_service.py`) | makes an update and asks its lift, writing the row and nothing else; `unlifted(db)`, the hold |
| `StoreUpdater` (`store_updater.py`) | the job and the timer `store-update`, which run the update's sequence from its row |

The two services are in `backend/app/services/`. The record is the table `store_updates`
([`record.md`](record.md)).

## The command

```bash
kubectl --context prd -n pilot-prd exec deploy/pilot -c backend -- python -m app.cli update-store
```

The command runs inside the stage's backend container, `-n pilot-dev` on the dev stage. It makes an
update and waits until the server lifts it, printing each phase once, as the server first writes
it. Times are in UTC, to the second:

- `Update made at <time>: Pilot's chats and jobs are held.`
- `The store's chats and jobs stopped at <time>.`
- `The store reset and running again at <time>.`
- `The store's tree written down again at <time>.`
- `Lift asked at <time>: the server skips what remains, retries what the update stopped and lifts
  the hold.`, once a lift is asked;
- what the lift did with the jobs the update stopped: `Retried 2 jobs; 1 left to a person's Retry:
  <title> in <project> (<refusal>).`, or `Retried 1 job.`, and no line when the update stopped no
  job whose item was open;
- `Lifted at <time>: Pilot's chats and jobs go on.`

The row's `error` prints each time it appears anew: `The update's last attempt failed, the server
tries again: <error>`. The command reads the row every 2 s. The retry line is read as of
`lifted_at`. A job counts as retried when a Retry was placed for it by then, a person's under the
hold included. A job counts as left when its item was open then and no retry was placed. The
reason in brackets is Retry's refusal as it reads at the print.

- **`--no-wait`** returns once the update is made, or the lift asked.
- **`--lift`** asks the server to lift the update under way: to skip the phases it has not
  reached, retry what the update stopped, and lift the hold. A second ask keeps the first's time.

A refusal goes to stderr, and the command exits 1. A second make is refused "Cannot update the
store because an update is under way since <time>", followed by "`update-store --lift` asks the
server to lift it.". A lift with no update is refused "Cannot lift the store's update because no
update is under way".

The command writes the row and nothing else. The CLI builds the app without its background
services, so it tells no one. The server takes the row up from the record at its timer's next
tick.

## The hold

An update not yet lifted is the hold, and at most one stands (`uq_store_updates_unlifted`). A make
locks the table, so of two makes at once the second is refused. The hold stands from the make's
commit:

- **At the gate**, a job's start and a Chat's are held, `held_reason` `store_update`. The update is
  read after the pause and before the outage. The setup is held too, though the pause lets it
  through. A work item's start, Resume and nudge go on: a worker's run is in an environment of its
  own and never touches the store ([`sessions.md`](sessions.md)). A held job's session log reads "Waiting
  for Pilot's update" in its tail, and so does the setup's line ([`work.md`](work.md)).
- **A job's owed nudge** is not sent until the lift ([`usage.md`](usage.md)).
- **A message to a project's chat** is refused `409` "Cannot send a message to Pilot in <project>
  because Pilot is updating", and the composer keeps the words ([`chats.md`](chats.md)). A send
  that began before the make lands with its chat's start held.
- **The gold bar** shows the condition `store_update` from `made_at`, after the outage and before
  the halts: the badge "Pilot is updating since <time>", the line "Pilot is updating its store
  since <time>. No chat answers and no job of Pilot's starts until it is done; work items go on."
  ([`ui.md`](ui.md)). Its alarm is due at once, at `default` priority
  ([`notifications.md`](notifications.md)).

The make tells no one. The timer tells the conditions when the unlifted update is not the one this
process last told of, and the lift tells them at its commit. So the gold bar shows the update
within a tick.

## The sequence

The job `store-update` runs the unlifted update's sequence on one loop, from the row's columns.
Each phase is a transaction of its own that locks the row. Each writes its column once, in order,
while the column is unwritten and no lift is asked:

1. **`stopped_at`.** Every job's and Chat's Session `running` or `starting` is stopped by Pilot,
   one by one, in `created_at` order, as Stop stops one (`SessionStartService.stop_for_update`,
   [`sessions.md`](sessions.md)). A turn in flight is interrupted once its stop commits. A start
   under way ends its Turn unsent. A Chat stays open with its conversation, and a held Session stays
   held. The update then waits up to 60 s, reading every 0.5 s, for the turns those stops
   interrupted to end. Past the wait, the store's stop ends what is left, as a stop made elsewhere
   does. A Session gone `running` or `starting` since, one whose gate read came before the make's
   commit, is stopped before the column is written. The log says `The store's update <id>:
   stopped <n> sessions`.
2. **`reset_at`.** The store's Environment row is made first where Pilot has none. Then
   `EnvironmentService.reset` gets the store by `STORE_ENVIRONMENT_ID` alone: it stops the store,
   resets it and brings it up. The reset clones PilotProjects' `main` again and empties the
   sidecar's data, its shadow with it ([`controller.md`](controller.md)). The column is written once
   the reset returns with the store running (`The store's update <id>: reset the store <env id>`).
   The step takes a turn across processes, an advisory lock (`advisory_turn`, key `279`, `0`). In
   a roll's overlap, a second process waits for the first's reset and then finds `reset_at`
   written, rather than stopping the store the first is bringing up. Some failures are the
   controller's own answer: a refusal, a settle other than `running`, any other. Each is written to
   the row's `error` and raised, so the supervisor's backoff makes the next attempt, which clears
   it. A call the controller does not answer writes no `error`.
3. **`reconciled_at`.** This is the sync's column: the store's sidecar posts a manifest with an
   empty shadow, a fresh sidecar's, while `stopped_at` is set and neither `reconciled_at` nor a lift
   is ([`sync.md`](sync.md)). The loop ends while the update waits for it, and runs again at that
   commit (`The store's update <id>: its tree reconciled`). The sidecar may post before the reset
   returns, so the column can come before `reset_at`.
4. **`lifted_at`.** Some jobs the update stopped have an open item and no Work retrying them. Each
   is retried once, in the order the jobs were made, by a person's Retry (`JobService.retry`,
   [`sessions.md`](sessions.md)). Each retry is a transaction of its own under the row's lock:
   - the retry is placed as Retry places one, behind the project's held jobs (`retried <id>`);
   - a refusal is logged, and the job's Retry is left to a person (`left <id> to a person's Retry:
     <reason>`);
   - a stopped turn still ending, which Retry refuses too, holds the lift to a later run (`lifts
     once <id>'s stopped turn ends`).

   Once `lifted_at` commits (`lifted`), the held starts are released, the nudges sent and the
   conditions told. Under the hold, a retry is held as any job's start is.

A lift asked goes to step 4 from wherever the sequence stands. The job's reconcile at STARTUP and
the timer `store-update`, on every tick, start the loop while an update is unlifted and not waiting
for the sync. A roll, a crash or an outage costs a restart of the sequence and never a phase: the
next process meets the columns the last one wrote, and a reset cut before `reset_at` is made again.
The job needs the controller ([`jobs.md`](jobs.md)). With none configured, no loop runs, so
nothing runs the sequence, the lift included.

**The jobs it stopped** are derived from their stop, never linked: a job's Session stopped by Pilot
at or after the update's `made_at` and, once lifted, before its `lifted_at`. A job whose item a
Finish closed at that stop's instant does not count, since Finish stops what it closes, and
neither does one a person took over meanwhile, its stop then the person's
([`round-trip.md`](round-trip.md)). Until the lift, a job it stopped is still in flight for what
Pilot works on: the documents its pass goes over stay Pilot's. A chat is
not retried: it stays the open one, and the next message after the lift goes to it
([`chats.md`](chats.md)).
A stopped job shows stopped on the item it follows from, the setup's line reading "Stopped for
Pilot's update · <time>", and its session log ends "Stopped by Pilot for its update · <time>". Once
retried, the item shows the retry's job in its place, and the setup's line has "Retried as a new job
below" under it ([`work.md`](work.md)).

## Testing it

**`POST /api/testing/store-update`** `{lift?}` is one of the record's testing routes, open on
every stage but `prd` ([`projects.md`](projects.md)). With no `lift` it makes an update as the
command does, `201`. With `{"lift": true}` it asks the unlifted update's lift, `200`. It answers
`409` in the service's words for what the command refuses, and `400` for an invalid body and on
`prd`. Each answer is the row as it stood at the request: `id`, `made_at`, `stopped_at`,
`reset_at`, `reconciled_at`, `lift_requested_at`, `lifted_at` and `error`. The route wakes nothing:
the server takes the row up at its timer's next tick, `SCHEDULER_TICK_SECONDS` after the last. On
`pilot-dev` it is how a check updates the dev store ([`slice-test-plan.md`](slice-test-plan.md)
§4 step 7).

In the browser suite the worker's backend runs the update on its fake controller, whose reset
clears the fake store's tree. No sidecar posts a manifest there, so an update stands at the
reconcile until its lift. The `storeUpdate` fixture (`frontend/tests/support/store-update.ts`)
gives:

- `make()`, which puts the store in the fake first: with none, the reset fails `not-found`, and
  the supervisor's backoff delays the lift past a spec's wait;
- `reset()`, which returns once the reset has cleared the tree;
- `lift()`, which returns once the condition is gone.

The fixture also lifts an update a spec left standing. The specs wait two ticks, `TICKS_MS`. The
cases are `tests/shell/gold-bar.spec.ts` (the condition before the week's halt),
`tests/chat/composer.spec.ts` (a message refused, its words kept) and
`tests/work/store-update.spec.ts` (a held job's button and its log's cue, a stopped job's and its log's tail, its retry in its place
at the lift). The backend's are
`tests/services/test_store_updater.py`, `test_store_update_service.py`, `tests/test_cli.py`
`TestUpdateStore` and `tests/api/test_testing_record.py` `TestCreateStoreUpdate`.
