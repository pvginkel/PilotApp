# The KubeCoder controller

Pilot works the KubeCoder fleet through its controller's API, under a named client credential. It
starts and stops existing environments, drives headless Claude Code sessions in them, and follows
the fleet on the controller's `/stream`; it creates no environment. This page is the client, the
outage, the fleet stream's consumer, the environments started on demand with their shutdown timer,
and the fake the suites run against. The sessions the client drives are
[`sessions.md`](sessions.md), and the threads it all runs on [`jobs.md`](jobs.md).

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
| `probe()` | `GET /readyz`, `200`: the gate's probe (below), with a 2 s timeout |

`ControllerEnvironment` holds what Pilot reads of an environment: `env_id`, `name`, `repo`,
`status`, `pod` (`started_at`, its `startedAt`, none when unreported; `restart_count`,
`restart_reason`; none while stopped), `setup_running`, and `exempt`, its
`capabilities.capacityExempt.enabled`: the environment stands outside its node's cap. A pod's
`started_at` is its identity: a container's restart in it leaves it as it is, and a new pod has
another.

**Failures.** An answer of `404 not-found`, `409 conflict`, `409 session-busy`, `409
admission-blocked` or `502 worker-unreachable`, as problem+json of that type, raises
`ControllerProblem`, whose `problem_type` its callers switch on. A call the controller does not
answer, a connection error, a timeout, or a 5xx without the controller's own problem+json (an
ingress's page in front of it), raises `ControllerUnreachable` and turns the outage on (below). Any
other failure, another status or an answer that does not parse, raises a plain
`ExternalServiceException`. Both are one too, so a request that lets any of them through is
answered `502`. A call waits 10 s to connect and 30 s for its answer, plus the wait it asked for.

**The streams** are `ControllerStream`s, iterated once: `with client.open_…() as stream: for frame
in stream`. A stream silent for 60 s (`STREAM_READ_TIMEOUT_SECONDS`; the controller's keepalive is
every 20 s), a transport error, or a server that ends the stream before its terminal frame raises
`ExternalServiceException`; a stream that drops once its call was answered turns nothing on. `stream.close()`, from any thread, wakes a read blocked on it, and the
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
controller answers, not that the credential works; the fleet stream's connect shows that. The check
turns no outage on.

## The outage

`ControllerOutage` (`backend/app/services/controller_outage.py`) is whether the controller answers,
as this process last met it: the process's own state, never a row, off in a fresh process, so each
pod of a roll holds its own. It turns **on** at a call the client raises `ControllerUnreachable`
for, any call, and while the fleet stream is down, its open failing or its drop (below). It turns
**off** at the fleet stream's reconnect, and at the probe's answer while the fleet stream is up. A
5xx that carries the controller's own problem+json, `502 worker-unreachable` among them, is the
controller answering about one environment or one call, and turns nothing on (D035): a relay meeting
one runs again with backoff, and a start meeting one fails ([`sessions.md`](sessions.md)). The
controller's own `/readyz` `503` is JSON, not problem+json, so the probe reads it as unreachable.

**The probe** is the timer `controller-probe`: while the outage holds, `probe()` each tick, whose
`200` turns it off unless the fleet stream is down; one that fails logs at debug and keeps it on.

While it holds, the gate holds every start ([`sessions.md`](sessions.md)); a running turn's relay
passes no gate and re-polls as it would. Each turn of it logs `The controller is unreachable:
starts are held` or `The controller answers again: held starts go on`, and its listeners run in
the thread that turned it: the start service releases the held starts at the off, and
`ConditionService` sends the conditions to the browsers, the gold bar's (`GET /api/conditions`,
[`ui.md`](ui.md)).

## The fleet stream

`FleetConsumer` (`backend/app/services/fleet_consumer.py`) is the job `fleet`, its one loop started
by its reconcile at STARTUP. On every connect it opens `/stream`, then lists the environments,
applies the list, and then the frames in order: the state channel opens with no snapshot, and a list
applied after a `gone` frame would bring the departed environment back. A drop raises, and the
supervisor connects again with backoff, from 1 s doubling to 30 s. A failure to open or a drop
turns the outage on and holds it on; a connect's list applied turns it off.

It keeps the Environment rows Pilot has current, and creates none. A report sets `name` (the
environment id while the controller has none), `last_state` (the controller's `status`),
`last_seen_at` (when Pilot applied it) and `exempt`, and clears `stop_due_at` when it reports the
environment exempt. A `gone` frame sets `last_state` `gone` alone, as does a connect's list for a
row it neither describes nor names as unprojectable. In memory it keeps each environment's latest
state and session set, `environment(env_id)` and `sessions(env_id)`, each None while the stream is
down and for an environment it has not reported; the relays' watchdog reads them
([`sessions.md`](sessions.md)). It writes no Session, and of the claim (below) only `stop_due_at`,
which a report of the environment exempt clears.

The gauge `pilot_fleet_stream_connected` is 1 while the stream is open, and each connect logs
`Fleet stream connected; <n> environments listed`.

## Environments on demand

`EnvironmentService` (`backend/app/services/environment_service.py`) starts environments, and arms,
clears and runs their shutdown timer. Pilot stops only what it started, and only the pod its start
brought up. The claim is `server_started_at`, set when Pilot's own start scheduled the bring-up,
and `started_pod_at`, the `pod.startedAt` that bring-up settled on. Nothing stops an environment
without the claim, while it is exempt, or while a Session is `running` or `starting` there, and the
timer stops one only while it still runs the claim's pod. The claim ends with its deadline:
`_end_claim` clears `server_started_at`, `started_pod_at` and `stop_due_at` together.

- `ensure_environment(db, env_id)` makes the Environment row from the controller's own report on
  Pilot's first touch of the environment, in the caller's transaction, and leaves a row that exists
  as it is. A Session's row needs it, and the sync's gate makes the store's row through it
  ([`sync.md`](sync.md)); the controller's `404` raises `ControllerProblem` `not-found`.
  `ensure_for_start(db, env_id)` is the same for a start the gate may hold: while the controller
  does not answer, it makes the row by the id alone, named by it and exempt, so that the timer arms
  nothing there until the fleet stream's report gives its columns.
- `start(env_id) -> ControllerEnvironment` brings the environment up and waits until it settles.
  The `start` goes without `wait`, since only then does its answer say whether this call
  scheduled the bring-up: on `202` it commits `server_started_at`, `started_pod_at` none until it
  settles (`Started environment <id>`); on `200` it sets nothing (`Environment <id> was running
  already`). Then the single `GET` with `wait=settled`, held up to an hour, whose pod settles the
  claim: a claim with no pod yet takes the settled one, the `202`'s, or that of a start cut between
  its `202` and its settle and run again, whose `200` keeps the claim; one with no pod yet ends
  where the environment came to rest (`running`, `error`, `stopped`, `deleting`) with no pod of
  known start; a claim on another pod ends. A wait run out before a pod leaves the claim without
  one. Then it arms the shutdown timer. A `running` environment is returned; `409
  admission-blocked`, or one that settled `error`, `stopped` or `deleting`, raises
  `EnvironmentStartFailed`; one still settling when the wait ran out raises
  `ExternalServiceException`; a call the controller does not answer raises
  `ControllerUnreachable`. Each of its writes is a transaction of its own. It is safe to repeat:
  a start resumed from its rows calls it as it is.

**The shutdown timer.** `stop_due_at` is when Pilot stops an environment it started.

- `arm_shutdown_timer(db, env_id)` sets it to now plus `ENVIRONMENT_STOP_AFTER_SECONDS`, renewing
  one already set, when the environment is Pilot's to stop and idle: `server_started_at` set, not
  exempt, and no Session `running` or `starting` there. It reads the Sessions under the Environment
  row's lock, so of two Sessions whose turns end at once, the later call arms it. It runs after a
  start's wait has answered, whatever the environment settled to, after a turn's end commits, when
  a session start fails, and when a Session there is stopped ([`sessions.md`](sessions.md)).
- `clear_shutdown_timer(db, env_id)` clears it, under the same lock, in the transaction that makes
  a Session there `running` or `starting`.
- The timer `environment-shutdown` takes each overdue row `FOR UPDATE SKIP LOCKED`, so a row
  another process's tick holds is skipped, and checks it again. A claim with its pod reads the
  environment afresh, with no wait, and calls `stop` holding the lock only while its pod's
  `startedAt` is `started_pod_at` (`Stopped environment <id>, due <iso>`; a `404` on the stop,
  `Environment <id> is gone: its shutdown, due <iso>, is cleared`). A pod gone (`404`, or none),
  another's or with no `startedAt` is left running (`Environment <id> no longer runs the pod
  Pilot's start brought up: its claim, due <iso>, ends with no stop`). A claim with no pod ends
  with no stop and no call (`Environment <id> has no pod of Pilot's start: …`), unless a Session
  `held` or `starting` there waits to resume its start, which keeps it. Each of these ends the
  claim, one commit per row. A refused stop, or a read that fails but for a `404`, raises, and the
  rows after it wait for the next tick. Then it arms every environment Pilot started that is
  idle, not exempt and unarmed, so an arm a restart lost is made within a tick (`Armed the shutdown
  of environment <id>, due <iso>`).

Only the tick and a settled start end the claim; the fleet consumer never writes
`server_started_at` or `started_pod_at`. The tick reads the Sessions as committed.

## Settings

| Setting | Default | |
|---|---|---|
| `CONTROLLER_URL` | empty | the controller's base URL; empty runs the app with no controller, and a backend with `FLASK_ENV=production`, as both deployed stages run, refuses to start so |
| `CONTROLLER_TOKEN` | empty | Pilot's named client credential, a secret; with `FLASK_ENV=production` the backend refuses to start without it |
| `CONTROLLER_CA_FILE` | empty | a PEM file of the CAs that verify the controller's certificate; empty leaves it to requests' own trust, and a path that is no file fails the app's start |
| `ENVIRONMENT_STOP_AFTER_SECONDS` | 1800 | how long an environment Pilot started stands idle before its shutdown timer stops it; above 0 |

Each deployed stage's are in [`deployment.md`](deployment.md). The dev stack runs with no controller
unless `backend/.env` sets one, as the fleet's live check does against KubeCoder's dev stage
([`slice-test-plan.md`](slice-test-plan.md) §2).

## The fake

`FakeController` (`backend/app/services/fake_controller.py`) is a WSGI app that the real client
reaches by URL. It holds environments and headless sessions with the controller's state machines,
answers with its status codes and problem+json, and serves the response stream and the fleet stream
in its SSE framing: `raw` frames with the offset as their `id:`, and the worker's `result` and
`incomplete`. An environment's pod has a `startedAt` from its move out of `stopped` until it
stops, in whole seconds and later than every pod's before it. Where it is simpler than the
controller: a headless session's conversation id is minted by its first send, an environment that
is not `running` holds no headless session, and `wait=settled` is `wait=ready`.

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
  Playwright's backends do: `loadAppBackendEnv()`
  (`frontend/tests/support/backend-env-extensions.ts`) sets each one's `CONTROLLER_URL` so, with an
  invented `CONTROLLER_TOKEN`, which the fake checks, and the suite's `controller` fixture drives it
  ([`work.md`](work.md)).

A test drives it through its verbs, in process, or over HTTP as `POST <base>/fake/<verb>` with the
verb hyphenated and its keyword arguments as the JSON body: `add_environment`, `remove_environment`,
`set_status`, `set_exempt`, `settle_starts` (what a start brings the environment to at once; None
holds it `starting`), `restart` (the pod's containers restart: its restart count moves, its sessions
go, it reads `starting` until `set_status`, and the pod and its `startedAt` stay), `recreate_pod` (a
new pod, with a later `startedAt`, its sessions gone, the environment `starting` until
`set_status`), `unreachable` (`502 worker-unreachable`), `outage` (`on`, `answer`: every call but
the verbs, `/readyz` among them, has its connection closed with no answer, `none`, which needs
werkzeug's server, or an ingress's `502` page, `ingress`, and every open stream ends; `on=False`
answers again), `capped` (a start is `409 admission-blocked`, never an exempt one's),
`unprojectable`, `busy`, `play` (the lines `claude` prints, answered with their offsets), `finish`
(the turn's outcome: `success`, `error`, `interrupted`, `spawn-failure` or `ended`), `write_log`,
`publish_state`, `publish_sessions`, `drop_streams` and `reset`, which ends an outage too.
`environment()`, `session()`, `sessions()` and `calls` read its state.

The turns a test plays are invented, in `backend/tests/fixtures/raw/turn_text.jsonl`,
`turn_tool.jsonl` and `turn_subagent.jsonl`, read by `raw_turn(name)`: bare `claude` lines in the
shapes of its stream-json, which the fake frames as the controller does. No line of them is a real
session's.
