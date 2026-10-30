# The server's jobs

The backend's long-lived work runs as threads of its own process, under the supervisor
(`backend/app/services/supervisor.py`, the container's `supervisor` singleton): the fleet stream's
consumer, a relay per session with a turn in flight, an interrupt per turn stopped under it, a start
per session coming up, the release of the held ones, the usage halts' hard stop and the nudges, the
halt file's writes and deletes, the reads and the write-backs of the documents a work item's run
registered, the standing notifications' and the alarms' sends, and the timers.
Every job resumes from rows, so nothing drains to completion: a roll or a crash costs a restart of
the job, never its work.

| Name | Kind | Does |
|---|---|---|
| `fleet` | a job with one loop | keeps the Environment rows current from the controller's fleet stream ([`controller.md`](controller.md)) |
| `relay:<session id>` | a loop of the job `relay` | relays a Session's turn in flight into its records ([`sessions.md`](sessions.md)) |
| `interrupt:<session id>` | a loop of the job `interrupt` | asks the controller's interrupt of a turn stopped under it ([`sessions.md`](sessions.md)) |
| `start:<session id>` | a loop of the job `start` | brings a `starting` Session up ([`sessions.md`](sessions.md)) |
| `start:held` | a loop of the job `start` | moves the held Sessions on once the gate opens for them ([`sessions.md`](sessions.md)) |
| `start:hard-stop` | a loop of the job `start` | stops every running work item while a usage halt whose setting is the hard stop holds ([`usage.md`](usage.md)) |
| `start:nudges` | a loop of the job `start` | sends the nudges owed that nothing holds any more, after settling each quota wall a reading decided missed ([`usage.md`](usage.md)) |
| `halt-file` | a loop of the job `halt-file` | the sweep: starts the loop of every environment whose halt file is owed a write or a delete ([`usage.md`](usage.md)) |
| `halt-file:<env id>` | a loop of the job `halt-file` | writes or deletes the halt file in the environment until it is as the rows want it ([`usage.md`](usage.md)) |
| `read:<session id>` | a loop of the job `read` | reads the documents a work item's ended run registered, and publishes each or fails its read ([`round-trip.md`](round-trip.md)) |
| `write-back:<session id>` | a loop of the job `write-back` | writes a run's closed registered documents back to their files ([`round-trip.md`](round-trip.md)) |
| `usage-halts` | a timer | decides the usage halts again, for a stale reading's window past its reset ([`usage.md`](usage.md)) |
| `halt-file` | a timer | sweeps the halt files ([`usage.md`](usage.md)) |
| `environment-shutdown` | a timer | stops the idle environments Pilot started ([`controller.md`](controller.md)) |
| `environment-delete` | a timer | clears the name of a free environment of Pilot's own, and deletes one that stays free ([`controller.md`](controller.md)) |
| `chat-close` | a timer | closes the project chats that have stood quiet past their timeout ([`chats.md`](chats.md)) |
| `relay-watchdog` | a timer | restarts a relay the fleet stream shows stuck or stopped ([`sessions.md`](sessions.md)) |
| `controller-probe` | a timer | while the controller is unreachable, asks whether it answers ([`controller.md`](controller.md)) |
| `nudges` | a timer | asks for `start:nudges` while a nudge owed is held by nothing, or a wall decided missed still owes one ([`usage.md`](usage.md)) |
| `notification:<project id>` | a loop of the job `notification` | brings each member's standing notification of the project to what the record says ([`notifications.md`](notifications.md)) |
| `notification-clear:<n>` | a loop of the job `notification-clear` | dismisses, once each, a person's project notifications through the token they just cleared ([`notifications.md`](notifications.md)) |
| `alarm` | a job with one loop | brings every person's alarms to the conditions that hold ([`notifications.md`](notifications.md)) |
| `alarm-clear:<n>` | a loop of the job `alarm-clear` | dismisses, once each, a person's alarms through the token they just cleared ([`notifications.md`](notifications.md)) |
| `notification-retry` | a timer | asks for the reconcile of each project with a notification owed past its retry ([`notifications.md`](notifications.md)) |
| `alarm-retry` | a timer | asks for the alarms' reconcile when the alarms due have turned, or while one is owed past its retry ([`notifications.md`](notifications.md)) |

Each but the notifications', the alarms' and the timers `usage-halts` and `nudges` needs the
controller. With `CONTROLLER_URL` unset (the
backend suite, a dev stack without the credential), none of them starts, and the log says so once at
STARTUP: `No controller configured (CONTROLLER_URL unset): the jobs and timers that need one do not
start (<names>)`. Production refuses to start without `CONTROLLER_URL` and `CONTROLLER_TOKEN`; the
check is in the server's background start, which the CLI, and so the `migrate` init container, never
runs. The notifications' and the alarms' need the notification bridge instead: with
`NOTIFICATION_BRIDGE_URL` unset (the backend suite, the dev stack), none of them is registered, and
production refuses to start so.

## Jobs, loops and timers

A service registers its job or timer on the supervisor when the container builds it, before STARTUP;
a registration after STARTUP raises `InvalidOperationException`.

- **A job**: `register_job(job, *, needs_controller, reconcile=None)`. Its reconcile,
  `Callable[[Session], None]`, runs once at STARTUP in a database session of its own, which commits
  when it returns and rolls back when it raises. The reconciles run in registration order (`fleet`,
  `halt-file`, `read`, `relay`, `interrupt`, `start`, `write-back`, `notification`, `alarm`) on a thread of the
  supervisor's, not the lifecycle coordinator's, so the server serves while they run. One that
  raises is logged, and its job's loops start regardless.
- **A loop**: `start_loop(job, run, key=None, *, again=False) -> bool` runs `run(handle)` on a
  daemon thread named `job` or `job:key`, one live loop per name. A loop requested before its job's
  reconcile has run waits for it. A request for a name with a live or waiting loop does nothing, a
  loop past its last action whose thread has not yet ended included; with `again`, a request for a
  live loop has it run `run` once more after the current run returns. It returns False for a
  request that did nothing, at and after PREPARE_SHUTDOWN, and for a job that needs the controller
  when none is configured.
- **A run that returns** ends its loop, on purpose. **One that raises** is run again after 1 s, the
  delay doubling to 30 s, and back to 1 s after a run that lasted 30 s or more. Nothing is run again
  once the loop is told to stop.
- **The handle**: `handle.stopping`; `handle.wait(seconds)`, True if the loop was told to stop;
  `with handle.holding(stream):`, which closes the stream when the loop is told to stop, or at once
  if it already was. A closed controller stream's iteration ends without raising, and the run then
  returns. `interrupt_loop(job, key=None) -> bool` closes what a live loop's run holds without
  stopping the loop, and is True when it closed something.
- **A timer**: `register_timer(timer, run, *, needs_controller)`. The scheduler runs the timers in
  registration order (`usage-halts`, `halt-file`, `environment-shutdown`, `environment-delete`,
  `chat-close`, `relay-watchdog`, `controller-probe`, `nudges`, `notification-retry`, then
  `alarm-retry`), the first round at STARTUP, then
  each round `SCHEDULER_TICK_SECONDS` after the last ended. Each run has a database session of its
  own; one that raises is logged and counted, and the rest of the round runs.

The suite and the CLI never fire STARTUP, so there a requested loop never runs. A test that needs
loops builds a supervisor on a lifecycle coordinator of its own with the `supervise` fixture
(`backend/tests/conftest.py`) and drives the coordinator's `fire_startup()` and `shutdown()`; its
tick is 0.05 s and its backoff 0.05 s to 0.2 s. `backend/tests/support/supervisor.py` has the
helpers to wait on a log line, a metric or a condition.

## Shutdown, and two processes

At PREPARE_SHUTDOWN the supervisor drops the loops still waiting for a reconcile, tells every loop
to stop and closes the I/O each holds; the scheduler finishes the timer it is running. Its shutdown
waiter joins the threads within the coordinator's budget, `GRACEFUL_SHUTDOWN_TIMEOUT` (the
template's setting, 600 s by default, 20 s in both deployed stages). Every thread is a daemon, so
the process exits at the end of the budget even with a loop still running: whatever it was doing,
the next process resumes from the rows. The pod's timing around it is in
[`deployment.md`](deployment.md).

During a roll the old and the new backend overlap, each running every job. That is safe because each
write a job makes is conditional on rows it reads under their lock: a relay, a start, the release of
a held one, the hard stop, a nudge and a send under the Session row's, the shutdown and delete
timers, a start's take and the halt file's write or delete under the Environment row's and the
chat-close timer under a chat's Session's, skipping one another process holds, and a read's or a
write-back's take
under the Project's, the Session's and the Document's rows, re-checked there. A notification's or an
alarm's sends take turns under an advisory lock of their own, and each write is dropped when the
person's token changed meanwhile. A usage reading is recorded under a lock of its table, so once,
and an overrule's end is written once, by whichever process's decision gets there first
([`usage.md`](usage.md)). The watchdog restarts only this process's relays.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `SCHEDULER_TICK_SECONDS` | 10 | the wait between two rounds of the timers; above 0 |
| `GRACEFUL_SHUTDOWN_TIMEOUT` | 600 | the lifecycle coordinator's budget for its shutdown waiters, the supervisor's included |

The metrics, on the backend's `/metrics`:

- `pilot_job_up{job}`, a gauge: the job's loops running now; one waiting out its backoff is not.
- `pilot_job_restarts_total{job}`: the restarts of the job's loops after one raised.
- `pilot_timer_runs_total{timer, outcome}`: each timer's runs, `ok` or `error`.

The log lines: `Loop <name> started`, `Loop <name> raised; restarting in <n> s` with its traceback,
`Loop <name> runs again`, `Loop <name> ended`, `Reconciling job <job>`, `Timer <name> raised`, and
`Supervisor stopping <n> loops` at PREPARE_SHUTDOWN.
