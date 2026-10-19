# The KubeCoder controller

Pilot works the KubeCoder fleet through its controller's API, under a named client credential. It
starts and stops existing environments, drives headless Claude Code sessions in them, and follows
the fleet on the controller's `/stream`; it creates no environment. This page is the client, the
fleet stream's consumer, the environments started on demand with their shutdown timer, and the
fake the suites run against. The sessions the client drives are [`sessions.md`](sessions.md), and
the threads it all runs on [`jobs.md`](jobs.md).

## The client

`ControllerClient` (`backend/app/services/controller_client.py`) is the container's
`controller_client` singleton, built at the server's start when `CONTROLLER_URL` is set. Every call
carries `Authorization: Bearer <CONTROLLER_TOKEN>` and verifies the controller's certificate
against `CONTROLLER_CA_FILE` when that is set, and against requests' own trust otherwise.

| Call | The controller's route |
|---|---|
| `list_environments()` | `GET /environments`: the environments, and those it could not describe (`unprojectable`) |
| `get_environment(env_id, wait=None, wait_ms=3_600_000)` | `GET /environments/<id>`; with `wait` (`ready` or `settled`), held until it is there, reads `error`, `stopped` or `deleting`, or `waitMs` runs out |
| `start_environment(env_id)` | `POST /environments/<id>/start`, without `wait`: a `StartOutcome(environment, started)`, `started` true on `202` (this call scheduled the bring-up) and false on `200` (it was running) |
| `stop_environment(env_id)` | `POST /environments/<id>/stop` |
| `create_headless_session(env_id, HeadlessCreateRequest)` | `POST /environments/<id>/sessions/headless`; a field left None is not sent |
| `send_message(env_id, name, message)` | `POST /environments/<id>/sessions/headless/<name>/messages`, `202`: the session is busy with the turn |
| `interrupt(env_id, name)` | `POST /environments/<id>/sessions/headless/<name>/interrupt` |
| `end_session(env_id, name)` | `DELETE /environments/<id>/sessions/<name>`; ending one already gone does nothing |
| `get_session(env_id, name)` | `GET /environments/<id>/sessions/<name>`: the status snapshot, its `status`, `turn` and `session_id` |
| `list_sessions(env_id)` | `GET /environments/<id>/sessions` |
| `read_log(env_id, name, head=None, tail=None)` | `GET /environments/<id>/sessions/headless/<name>/log`: the condensed log's lines |
| `open_response_stream(env_id, name, offset, wait_ms=None)` | `GET /environments/<id>/sessions/headless/<name>/response?format=raw&offset=<n>` |
| `open_fleet_stream()` | `GET /stream` |

`ControllerEnvironment` holds what Pilot reads of an environment: `env_id`, `name`, `repo`,
`status`, `pod` (`restart_count`, `restart_reason`; none while stopped), `setup_running`, and
`exempt`, its `capabilities.capacityExempt.enabled`: the environment stands outside its node's cap.

**Failures.** An answer of `404 not-found`, `409 conflict`, `409 session-busy`, `409
admission-blocked` or `502 worker-unreachable`, as problem+json of that type, raises
`ControllerProblem`, whose `problem_type` its callers switch on. Any other failure, another status,
no answer or an answer that does not parse, raises a plain `ExternalServiceException`.
`ControllerProblem` is one too, so a request that lets either through is answered `502`. A call
waits 10 s to connect and 30 s for its answer, plus the wait it asked for.

**The streams** are `ControllerStream`s, iterated once: `with client.open_…() as stream: for frame
in stream`. A stream silent for 60 s (`STREAM_READ_TIMEOUT_SECONDS`; the controller's keepalive is
every 20 s), a transport error, or a server that ends the stream before its terminal frame raises
`ExternalServiceException`. `stream.close()`, from any thread, wakes a read blocked on it, and the
iteration ends without raising.

- The response stream's frames: `RawFrame(offset, line)`, a line of the session's raw file as
  `claude` printed it, verbatim, blank and non-JSON lines included, and `offset` the byte offset
  after it, which resumes the stream after the line; `ResultFrame(turn, result, is_error,
  interrupted, payload)`, the worker's end of the turn, which carries no offset; and, with
  `wait_ms` only, `IncompleteFrame(status)`. The stream is opened after the send's `202`: the
  controller holds a turn's result until the next send, so a stream opened before it delivers the
  previous turn's.
- The fleet stream's frames: `StateFrame(environment)`, `GoneFrame(env_id)` and
  `SessionsFrame(env_id, sessions)`, an environment's whole session set, each a `SessionView`
  (`name`, `title`, `state`, `mode`, `working`, `session_id`). The other channels' frames are not
  Pilot's and are skipped unread.

**Readiness.** The client registers the `controller` check, not critical, on the controller's own
`/readyz`, with a 2 s timeout. That route asks for no bearer, so the check shows that the
controller answers, not that the credential works; the fleet stream's connect shows that.

## The fleet stream

`FleetConsumer` (`backend/app/services/fleet_consumer.py`) is the job `fleet`, its one loop started
by its reconcile at STARTUP. On every connect it opens `/stream`, then lists the environments,
applies the list, and then the frames in order: the state channel opens with no snapshot, and a list
applied after a `gone` frame would bring the departed environment back. A drop raises, and the
supervisor connects again with backoff.

It keeps the Environment rows Pilot has current, and creates none. A report sets `name` (the
environment id while the controller has none), `last_state` (the controller's `status`),
`last_seen_at` (when Pilot applied it) and `exempt`, and clears `stop_due_at` when it reports the
environment exempt. A `gone` frame sets `last_state` `gone` alone, as does a connect's list for a
row it neither describes nor names as unprojectable. In memory it keeps each environment's latest
state and session set, `environment(env_id)` and `sessions(env_id)`, each None while the stream is
down and for an environment it has not reported; the relays' watchdog reads them
([`sessions.md`](sessions.md)).

The gauge `pilot_fleet_stream_connected` is 1 while the stream is open, and each connect logs
`Fleet stream connected; <n> environments listed`.

## Environments on demand

`EnvironmentService` (`backend/app/services/environment_service.py`) starts environments, and arms,
clears and runs their shutdown timer. Pilot stops only what it started: `server_started_at` says
that it did, and nothing stops an environment while that is unset, while it is exempt, or while a
Session is `running` or `starting` there.

- `ensure_environment(db, env_id)` makes the Environment row from the controller's own report on
  Pilot's first touch of the environment, in the caller's transaction, and leaves a row that exists
  as it is. A Session's row needs it; the controller's `404` raises `ControllerProblem`
  `not-found`.
- `start(env_id) -> ControllerEnvironment` brings the environment up and waits until it settles.
  The `start` goes without `wait`, since only then does its answer say whether this call
  scheduled the bring-up: on `202` it commits `server_started_at` (`Started environment <id>`), on
  `200` it sets nothing (`Environment <id> was running already`). Then the single `GET` with
  `wait=settled`, held up to an hour, after which it arms the shutdown timer. A `running`
  environment is returned; `409 admission-blocked`, or one that settled `error`, `stopped` or
  `deleting`, raises `EnvironmentStartFailed`; one still settling when the wait ran out raises
  `ExternalServiceException`. Each of its writes is a transaction of its own.

**The shutdown timer.** `stop_due_at` is when Pilot stops an environment it started.

- `arm_shutdown_timer(db, env_id)` sets it to now plus `ENVIRONMENT_STOP_AFTER_SECONDS`, renewing
  one already set, when the environment is Pilot's to stop and idle: `server_started_at` set, not
  exempt, and no Session `running` or `starting` there. It reads the Sessions under the Environment
  row's lock, so of two Sessions whose turns end at once, the later call arms it. It runs after a
  start's wait has answered, whatever the environment settled to, after a turn's end commits, and
  when a session start fails.
- `clear_shutdown_timer(db, env_id)` clears it, under the same lock, in the transaction that makes
  a Session there `running` or `starting`.
- The timer `environment-shutdown` takes each overdue row `FOR UPDATE SKIP LOCKED`, so a row
  another process's tick holds is skipped, checks it again, and calls `stop` holding the lock; then
  it clears `stop_due_at` and `server_started_at`, a `404` included (`Environment <id> is gone: its
  shutdown, due <iso>, is cleared`), one commit per row (`Stopped environment <id>, due <iso>`). A
  refused stop raises, and the rows after it wait for the next tick. Then it arms every environment
  Pilot started that is idle, not exempt and unarmed, so an arm a restart lost is made within a
  tick (`Armed the shutdown of environment <id>, due <iso>`).

Only the timer's stop clears `server_started_at`. The tick reads the Sessions as committed.

## Settings

| Setting | Default | |
|---|---|---|
| `CONTROLLER_URL` | empty | the controller's base URL; empty runs the app with no controller, and production refuses to start so |
| `CONTROLLER_TOKEN` | empty | Pilot's named client credential, a secret; production refuses to start without it |
| `CONTROLLER_CA_FILE` | empty | a PEM file of the CAs that verify the controller's certificate; empty leaves it to requests' own trust, and a path that is no file fails the app's start |
| `ENVIRONMENT_STOP_AFTER_SECONDS` | 1800 | how long an environment Pilot started stands idle before its shutdown timer stops it; above 0 |

Production's are in [`deployment.md`](deployment.md). The dev stack runs with no controller unless
`backend/.env` sets one, as the fleet's live check does against KubeCoder's dev stage
([`slice-test-plan.md`](slice-test-plan.md) §2).

## The fake

`FakeController` (`backend/app/services/fake_controller.py`) is a WSGI app that the real client
reaches by URL. It holds environments and headless sessions with the controller's state machines,
answers with its status codes and problem+json, and serves the response stream and the fleet stream
in its SSE framing: `raw` frames with the offset as their `id:`, and the worker's `result` and
`incomplete`. Where it is simpler than the controller: a headless session's conversation id is
minted by its first send, an environment that is not `running` holds no headless session, and
`wait=settled` is `wait=ready`.

- **Under pytest**, the fixture `fake_controller` serves it on a free port of 127.0.0.1
  (`ServedFakeController`, `backend/tests/support/fake_controller.py`; over HTTPS with
  `tls=invent_ca(dir)`, from `backend/tests/support/tls.py`), and `controller_client` (or
  `committed_controller_client`, for `committed_app`) makes the real client on it the container's.
  `client_of(container, fake)` does the same for any served fake, a subclass that hooks a route
  included.
- **For Playwright**, it is mounted at `/api/testing/controller/<path>`
  (`backend/app/api/testing_controller.py`), which answers `400` `ROUTE_NOT_AVAILABLE` unless the
  server runs with `FLASK_ENV=testing` on a `STAGE` other than `prd`: a backend whose
  `CONTROLLER_URL` is its own `/api/testing/controller` drives the fake with no process added.
  Playwright's backends run with no controller.

A test drives it through its verbs, in process, or over HTTP as `POST <base>/fake/<verb>` with the
verb hyphenated and its keyword arguments as the JSON body: `add_environment`,
`remove_environment`, `set_status`, `set_exempt`, `settle_starts` (what a start brings the
environment to at once; None holds it `starting`), `restart` (the pod's restart count moves, its
sessions go), `unreachable`, `capped` (a start is `409 admission-blocked`, never an exempt one's),
`unprojectable`, `busy`, `play` (the lines `claude` prints, answered with their offsets), `finish`
(the turn's outcome: `success`, `error`, `interrupted`, `spawn-failure` or `ended`), `write_log`,
`publish_state`, `publish_sessions`, `drop_streams` and `reset`. `environment()`, `session()`,
`sessions()` and `calls` read its state.

The turns a test plays are invented, in `backend/tests/fixtures/raw/turn_text.jsonl`,
`turn_tool.jsonl` and `turn_subagent.jsonl`, read by `raw_turn(name)`: bare `claude` lines in the
shapes of its stream-json, which the fake frames as the controller does. No line of them is a real
session's.
