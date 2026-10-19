# The server's jobs

The backend's long-lived work runs as threads of its own process, under the supervisor
(`backend/app/services/supervisor.py`, the container's `supervisor` singleton): the fleet stream's
consumer, a relay per session with a turn in flight, a start per session coming up, and the timers.
Every job resumes from rows, so nothing drains to completion: a roll or a crash costs a restart of
the job, never its work.

| Name | Kind | Does |
|---|---|---|
| `fleet` | a job with one loop | keeps the Environment rows current from the controller's fleet stream ([`controller.md`](controller.md)) |
| `relay:<session id>` | a loop of the job `relay` | relays a Session's turn in flight into its records ([`sessions.md`](sessions.md)) |
| `start:<session id>` | a loop of the job `start` | brings a `starting` Session up ([`sessions.md`](sessions.md)) |
| `environment-shutdown` | a timer | stops the idle environments Pilot started ([`controller.md`](controller.md)) |
| `relay-watchdog` | a timer | restarts a relay the fleet stream shows stuck ([`sessions.md`](sessions.md)) |

Each needs the controller. With `CONTROLLER_URL` unset (the suites, CI, a dev stack without the
credential), none of them starts, and the log says so once at STARTUP: `No controller configured
(CONTROLLER_URL unset): the jobs and timers that need one do not start (<names>)`. Production
refuses to start without `CONTROLLER_URL` and `CONTROLLER_TOKEN`; the check is in the server's
background start, which the CLI, and so the `migrate` init container, never runs.

## Jobs, loops and timers

A service registers its job or timer on the supervisor when the container builds it, before STARTUP;
a registration after STARTUP raises `InvalidOperationException`.

- **A job**: `register_job(job, *, needs_controller, reconcile=None)`. Its reconcile,
  `Callable[[Session], None]`, runs once at STARTUP in a database session of its own, which commits
  when it returns and rolls back when it raises. The reconciles run in registration order (`fleet`,
  `relay`, `start`) on a thread of the supervisor's, not the lifecycle coordinator's, so the server
  serves while they run. One that raises is logged, and its job's loops start regardless.
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
  registration order (`environment-shutdown`, then `relay-watchdog`), the first round at STARTUP,
  then each round `SCHEDULER_TICK_SECONDS` after the last ended. Each run has a database session of
  its own; one that raises is logged and counted, and the rest of the round runs.

The suite and the CLI never fire STARTUP, so there a requested loop never runs. A test that needs
loops builds a supervisor on a lifecycle coordinator of its own with the `supervise` fixture
(`backend/tests/conftest.py`) and drives the coordinator's `fire_startup()` and `shutdown()`; its
tick is 0.05 s and its backoff 0.05 s to 0.2 s. `backend/tests/support/supervisor.py` has the
helpers to wait on a log line, a metric or a condition.

## Shutdown, and two processes

At PREPARE_SHUTDOWN the supervisor drops the loops still waiting for a reconcile, tells every loop
to stop and closes the I/O each holds; the scheduler finishes the timer it is running. Its shutdown
waiter joins the threads within the coordinator's budget, `GRACEFUL_SHUTDOWN_TIMEOUT` (the
template's setting, 600 s by default, 20 s in production). Every thread is a daemon, so the process
exits at the end of the budget even with a loop still running: whatever it was doing, the next
process resumes from the rows. The pod's timing around it is in [`deployment.md`](deployment.md).

During a roll the old and the new backend overlap, each running every job. That is safe because
each write a job makes is conditional on rows it reads under their lock: a relay, a start and a
send under the Session row's, the shutdown timer under the Environment row's, skipping one another
process holds. The watchdog restarts only this process's relays.

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
