# The KubeCoder controller

Pilot works the KubeCoder fleet through its controller's API, under a named client credential. It
creates environments of its own from a repository for its work items, takes, renames, resets and
deletes them, starts and stops environments, drives headless Claude Code sessions in them, reads and
writes their files, and follows the fleet on the controller's `/stream`. This page is the client,
the outage, the fleet stream's consumer, the environments started on demand with their shutdown
timer, Pilot's own environments with their delete timer, and the fake the suites run against. The
sessions the client drives are [`sessions.md`](sessions.md), and the threads it all runs on
[`jobs.md`](jobs.md).

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
| `stop_environment(env_id)` | `POST /environments/<id>/stop`, which takes no `wait`: the environment, `stopping` on `202`, `stopped` on `200` |
| `create_environment(repo, name=None)` | `POST /environments {repo, managed: true, name?}`, without `wait`: the environment, `provisioning`, its env id given before its bring-up ends in a running pod; `managed` makes it a managed environment of Pilot's client |
| `reset_environment(env_id)` | `POST /environments/<id>/reset`, without `wait`, of a `stopped` environment only: its folder cleared and its bring-up run again, answered `starting`, ending in a running pod as a start does |
| `rename_environment(env_id, name)` | `POST /environments/<id>/rename {name}`; a blank `name` clears it |
| `delete_environment(env_id)` | `DELETE /environments/<id>`, `202`; one already gone, answered `404`, is deleted |
| `read_file(env_id, path)` | `GET /environments/<id>/file?path=<path>`: a `FileContent(data, sha256)`, the raw bytes and their `KubeCoder-Content-Sha256` |
| `write_file(env_id, path, data)` | `PUT /environments/<id>/file?path=<path>`, the raw body, `204`: the file overwritten whole, or created with the folders it needs, and the SHA-256 of what was written; it sends no `expectedSha256` |
| `list_folder_files(env_id, path)` | `GET /environments/<id>/files?path=…&offset=…&limit=1000`, page by page and folder by folder: every file under the folder, its subfolders' included, in path order, each named through the folder as given, so a link under it is followed as a read follows it |
| `create_headless_session(env_id, HeadlessCreateRequest)` | `POST /environments/<id>/sessions/headless`; a field left None is not sent, its box among them (below) |
| `send_message(env_id, name, message)` | `POST /environments/<id>/sessions/headless/<name>/messages`, `202`: the session is busy with the turn |
| `interrupt(env_id, name)` | `POST /environments/<id>/sessions/headless/<name>/interrupt` |
| `end_session(env_id, name)` | `DELETE /environments/<id>/sessions/<name>`; ending one already gone does nothing |
| `get_session(env_id, name)` | `GET /environments/<id>/sessions/<name>`: the status snapshot, its `status`, `turn` and `session_id` |
| `list_sessions(env_id)` | `GET /environments/<id>/sessions` |
| `read_log(env_id, name, head=None, tail=None)` | `GET /environments/<id>/sessions/headless/<name>/log`: the condensed log's lines |
| `open_response_stream(env_id, name, offset, wait_ms=None)` | `GET /environments/<id>/sessions/headless/<name>/response?format=raw&offset=<n>` |
| `open_fleet_stream()` | `GET /stream` |
| `probe()` | `GET /readyz`, `200`: the gate's probe (below), with a 2 s timeout |

**The box.** A headless create is boxed when it sets `sandbox` true, `sandbox_read_only_cwd`, or a
non-empty `sandbox_writable_dirs` (sent as `sandbox`, `sandboxReadOnlyCwd`, `sandboxWritableDirs`;
false and an empty list are no box). Every turn of a boxed session runs in a kernel-enforced write
scope: `$HOME`, `/tmp`, the cwd, unless `sandbox_read_only_cwd` makes it a read-only root, and each
listed folder, an absolute path of an existing folder, are writable, and every other mount is
read-only; a write outside it fails. The box is built again at each turn's
spawn, so a turn one of whose folders is gone since the create fails there ("spawn failed: sandbox:
scope root <root>: …"), and never runs unboxed. The brain's sessions are boxed
([`sessions.md`](sessions.md)); a work item's are not.

`ControllerEnvironment` holds what Pilot reads of an environment: `env_id`, `name`, `managed_by`
(the client a managed create recorded), `repo`, `status`, `pod` (`started_at`, its `startedAt`, none when unreported; `restart_count`,
`restart_reason`; none while stopped), `setup_running`, and `exempt`, its
`capabilities.capacityExempt.enabled`: the environment stands outside its node's cap. A pod's
`started_at` is its identity: a container's restart in it leaves it as it is, and a new pod has
another.

**Failures.** An answer of `404 not-found`, `409 conflict`, `409 name-conflict` (a name the
fleet holds already: KubeCoder's names are unique across it), `409 session-busy`, `409
admission-blocked` (the node at its cap), `403 namespace-not-whitelisted` (a repository whose owner
the controller does not take), `422 validation-error` (a boxed create's too: a listed folder that
is no absolute path of an existing folder, a cwd that does not exist, or a read-only cwd that is
itself a writable root), `409 capability-unavailable` (a boxed create on a pod composed without the
sandbox profile, until the environment is restarted) or `502 worker-unreachable`, as problem+json
of that type, raises `ControllerProblem`, whose `problem_type` its callers switch on; so do the file
routes' `503 environment-unreadable` (the controller cannot read the environment off its share, its
"try again"), `403 path-outside-work`, `409 not-a-file` (a folder given to `read_file`, a FIFO or a
socket), `409 not-a-directory` (a file given to `list_folder_files`) and `413 file-too-large` (past
`FILE_SIZE_CAP`, 16 MiB each way). Its `cause` reads `the controller answered <status> <type>:
<title>; <detail>`, the controller's reason whole. The file routes answer from the environment's
share, never through its pod, so a stopped environment's files are read and written too; a path
outside `/work` is refused, and so is a write while the controller brings the environment up,
resets or deletes it (`409 conflict`). A call the controller does not
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

`EnvironmentService` (`backend/app/services/environment_service.py`) starts environments, creates,
takes, renames, resets and deletes environments of Pilot's own (below), and arms, clears and runs
the shutdown and delete timers. Pilot stops only what it started. The claim is `server_started_at`,
set when Pilot's own start, create or reset scheduled the bring-up, and `started_pod_at`, the
`pod.startedAt` that bring-up settled on. Nothing stops an environment without the claim, while it
is exempt, or while a Session is `running` or `starting` there. On an environment Pilot did not
create, the claim holds only the pod its start brought up, and the timer stops one only while it
still runs that pod; on one of Pilot's own every pod is Pilot's, and the claim holds whatever pod
runs there. The claim ends with its deadline: `_end_claim` clears `server_started_at`,
`started_pod_at` and `stop_due_at` together.

- `ensure_environment(db, env_id)` makes the Environment row from the controller's own report on
  Pilot's first touch of the environment, in the caller's transaction, and leaves a row that exists
  as it is. `start` makes its row through it, the sync's gate and a brain session's start the
  store's ([`sync.md`](sync.md), [`chats.md`](chats.md)), and `pilot-store`'s copy of outside
  material its source's ([`mcp.md`](mcp.md)); the controller's `404` raises `ControllerProblem`
  `not-found`.
- `start(env_id) -> ControllerEnvironment` brings the environment up and waits until it settles.
  The `start` goes without `wait`, since only then does its answer say whether this call
  scheduled the bring-up: on `202` it commits `server_started_at`, `started_pod_at` none until it
  settles (`Started environment <id>`); on `200` it sets nothing (`Environment <id> was running
  already`). Then `settle(env_id)`, the single `GET` with `wait=settled`, held up to an hour, whose
  pod settles the claim: a claim with no pod yet takes the settled one, the `202`'s, or that of a
  bring-up cut between its `202` and its settle and run again; one with no pod yet ends where the
  environment came to rest (`running`, `error`, `stopped`, `deleting`) with no pod of known start;
  a claim on another pod ends on an environment Pilot did not create, and takes the pod it reads on
  one of Pilot's own. A wait run out before a pod leaves the claim without one. Then it arms the
  shutdown timer. A `running` environment is returned; `409 admission-blocked`, or one that settled
  `error`, `stopped` or `deleting`, raises `EnvironmentStartFailed`; one still settling when the
  wait ran out raises `ExternalServiceException`; a call the controller does not answer raises
  `ControllerUnreachable`. Each of its writes is a transaction of its own. It is safe to repeat: a
  start resumed from its rows calls it as it is. A brain session's start calls it on the store, which
  is exempt, so the store is started on demand and no timer of Pilot's stops it.

**The shutdown timer.** `stop_due_at` is when Pilot stops an environment it started.

- `arm_shutdown_timer(db, env_id)` sets it to now plus `ENVIRONMENT_STOP_AFTER_SECONDS`, renewing
  one already set, when the environment is Pilot's to stop and idle: `server_started_at` set, not
  exempt, and no Session `running` or `starting` there. It reads the Sessions under the Environment
  row's lock, so of two Sessions whose turns end at once, the later call arms it. It runs after a
  bring-up's wait has answered, whatever the environment settled to, after a turn's end commits,
  when a session start fails, and when a Session there is stopped ([`sessions.md`](sessions.md)).
- `clear_shutdown_timer(db, env_id)` clears it, under the same lock, in the transaction that makes
  a Session there `running` or `starting`.
- The timer `environment-shutdown` takes each overdue row `FOR UPDATE SKIP LOCKED`, so a row
  another process's tick holds is skipped, and checks it again. A claim with no pod yet is kept
  while a Session `held` or `starting` there waits to resume its start. One of Pilot's own is then
  stopped, whatever pod runs there (`Stopped environment <id>, due <iso>`; a `404` on the stop,
  `Environment <id> is gone: its shutdown, due <iso>, is cleared`). On any other, a claim with its
  pod reads the environment afresh, with no wait, and calls `stop` holding the lock only while its
  pod's `startedAt` is `started_pod_at`; a pod gone (`404`, or none), another's or with no
  `startedAt` is left running (`Environment <id> no longer runs the pod Pilot's start brought up:
  its claim, due <iso>, ends with no stop`), and a claim with no pod ends with no stop and no call
  (`Environment <id> has no pod of Pilot's start: …`). Each of these ends the claim, one commit per
  row. A refused stop, or a read that fails but for a `404`, raises, and the rows after it wait for
  the next tick. Then it arms every environment Pilot started that is idle, not exempt and unarmed,
  so an arm a restart lost is made within a tick (`Armed the shutdown of environment <id>, due
  <iso>`).

Only the environment service writes the claim; the fleet consumer never writes `server_started_at`
or `started_pod_at`. The tick reads the Sessions as committed.

## Pilot's own environments

An environment is Pilot's own while its row has `server_created_at`: the server created it from its
`repo`, `owner/Name`, for a work item placed by that repository ([`sessions.md`](sessions.md)). Pilot
knows its own from its rows; the create also makes it a managed environment of Pilot's client at the
controller, its `managedBy`, by which the controller's list filters. Pilot takes, renames, resets
and deletes only its own: never an operator's environment of the same repository, the store, or an
environment a work item was placed in by its id.

**Free.** One of Pilot's own is free while it is neither `deleting` nor `gone`, no Session there
is `running`, `starting` or `held`, nor `stopped` or `failed`, and no document a work item's run
registered there is still open: the run's conversation goes on there once each is closed
([`round-trip.md`](round-trip.md)), and the last close's continuation names the environment from
its placement on, so it is never free between the two. A work item that shows Resume keeps
its environment for as long as it does, with no expiry: nothing takes, resets or deletes it, its
project's Finish and Archive included, since Bring back offers the Resume again (D042). The
shutdown timer still stops it, and it holds no slot of the gate's ([`sessions.md`](sessions.md)).
Freedom is derived wherever it is read; no column holds it.

- `take(db, repo)`, in the start's transaction, which commits before any controller call: of the
  free environments of the repository that are `stopped`, `stopping`, or `running` under Pilot's
  claim, the most recently freed, its row locked `FOR UPDATE SKIP LOCKED` and its freedom read
  again once locked, so of two starts the later sees the earlier's Session there; its claim and its
  `delete_due_at` cleared, so that its rows say its bring-up is still to make. One in `error`,
  `provisioning` or `starting`, or running outside Pilot's claim, is passed over; with none left,
  the start creates one. `retake(db, env_id)` takes back a fresh-start Resume's own environment the
  same way, and leaves one `deleting` or `gone`, which the start lets go.
- `create(repo, slug)` creates one, named `slug`, or on a `409 name-conflict` the first of
  `slug-2`, `slug-3`, … the fleet does not hold; `record_created(db, created, repo)` writes its row,
  Pilot's own, its claim taken from the create's `202` (`Created environment <id> from <repo>`). A
  create whose answer was lost before its row costs an environment no tick deletes, listed under
  Pilot's client at the controller. `stop_untaken(env_id)` stops one created for a start that moved
  on, its claim ended, while it is still free under its row's lock (`Stopped environment <id>, which
  no Session took`).
- `name(env_id, slug)` renames a taken one after the taking project as the create names one, after
  the take's commit, and sets the row's name from the answer. The name is the operator's reading
  aid: nothing of Pilot's reads it, and the env chip shows the row as it stands, so that a finished
  item's chip names the project now using that environment, or its id while it is free.
- `reset(env_id)` brings a taken one up in a tree made anew, for a start on a new conversation. The
  controller resets a `stopped` environment only, and its stop takes no `wait`: the stop goes first,
  whatever the row says, answered `200` when it is stopped already, and a `202`'s settle is awaited;
  one settled other than `stopped` raises `EnvironmentStartFailed` ("it settled <status> after its
  stop"). Then `POST …/reset`, whose `409 admission-blocked` raises `EnvironmentStartFailed` ("the
  controller refused its reset: …"). A reset ends in a running pod, as a start does, so no start
  follows it: its `202` takes the claim (`Reset environment <id>`), and `settle` awaits it. A created
  environment needs no reset, and a resume never resets: a work item that continues its
  conversation does so in the tree as its session left it.
- `reclaim(db, env_id)` claims one of Pilot's own that has no claim, for a start that stops or fails
  before its reset, so that the shutdown timer stops it.

**The delete timer.** The timer `environment-delete` (`run_delete_timer`) takes each row `FOR
UPDATE SKIP LOCKED`, a transaction each:

- an overdue `delete_due_at` on one still free is deleted, `DELETE` (a `404` counts as deleted), its
  row kept `gone`, its claim ended and its deadline cleared (`Deleted environment <id>, due <iso>`);
  one no longer free loses its deadline, nothing deleted (`Environment <id> is no longer free: its
  delete, due <iso>, is cleared`);
- then every free one with no deadline, freed since the last tick, has its name cleared at the
  controller and its `delete_due_at` set to now plus `ENVIRONMENT_DELETE_AFTER_SECONDS`, both or
  neither (`Environment <id> is free: its name cleared, its delete due <iso>`); a rename answered
  `404` marks the row `gone`.

An environment is freed by this tick's reading alone: a Session that lets one go calls nothing.

## Settings

| Setting | Default | |
|---|---|---|
| `CONTROLLER_URL` | empty | the controller's base URL; empty runs the app with no controller, and a backend with `FLASK_ENV=production`, as both deployed stages run, refuses to start so |
| `CONTROLLER_TOKEN` | empty | Pilot's named client credential, a secret; with `FLASK_ENV=production` the backend refuses to start without it |
| `CONTROLLER_CA_FILE` | empty | a PEM file of the CAs that verify the controller's certificate; empty leaves it to requests' own trust, and a path that is no file fails the app's start |
| `ENVIRONMENT_STOP_AFTER_SECONDS` | 1800 | how long an environment Pilot started stands idle before its shutdown timer stops it; above 0 |
| `ENVIRONMENT_DELETE_AFTER_SECONDS` | 604800 | how long an environment of Pilot's own stands free before its delete timer deletes it, 7 days; above 0 |

Each deployed stage's are in [`deployment.md`](deployment.md). The dev stack runs with no controller
unless `backend/.env` sets one, as the fleet's live check does against KubeCoder's dev stage
([`slice-test-plan.md`](slice-test-plan.md) §2).

## The fake

`FakeController` (`backend/app/services/fake_controller.py`) is a WSGI app that the real client
reaches by URL. It holds environments and headless sessions with the controller's state machines,
answers with its status codes and problem+json, and serves the response stream and the fleet stream
in its SSE framing: `raw` frames with the offset as their `id:`, and the worker's `result` and
`incomplete`. It serves the file routes, a read, a write and a folder's listing, over each
environment's `files`. An environment's pod has a `startedAt` from its move out of `stopped` until it
stops, in whole seconds and later than every pod's before it. It serves the create, the reset,
the rename and the delete with the controller's refusals in its order, and the list filtered by
`managedBy`, `repo` and `status`. An environment a create makes has an id minted from its
repository, lowercased, each run of other characters than letters and digits a `-`, then `-` and 6
hex digits, and `managedBy` `pilot`, the client its one credential authenticates as. Where it is simpler than the controller: a headless
session's conversation id is minted by its first send, an environment that is not `running` holds
no headless session, `wait=settled` is `wait=ready`, the create and the reset answer at once and
take no `wait`, a delete's teardown ends as it is answered, `deleting` then `gone`, and the node's
cap is a flag, not a count. An environment's `/work` holds files alone, with no link, a folder being
there while a file is under it; a write takes no `expectedSha256` (`422`), and is refused `409
conflict` while the environment reads `provisioning`, `starting` or `deleting`; a reset clears the
tree, a stop keeps it.

A boxed create keeps the worker's rules in its order: its fields' types, then the profile, `409
capability-unavailable` "sandboxing is not enabled for this environment: …" on an environment its
verb `no_sandbox_profile` marks, which no restart clears; then its cwd and each listed folder,
`422 validation-error` "invalid sandbox scope: …" for one that is no absolute path, is not a folder
on the environment's tree or does not exist there; then a read-only cwd that is also a listed
folder. Its tree being `/work` alone, the fake checks no `$HOME` or `/tmp` root, and resolves no
link. So a boxed create needs its cwd on the tree, a file under it, as well as each listed folder.
A send to a boxed session one of whose roots is no longer a folder there is answered `202` and its
turn resolves at once, in error, its result "spawn failed: sandbox: scope root <root>: lstat
<root>: no such file or directory", with no conversation id minted. A session's `box` holds its
roots, none unboxed, and its `create_body` the create's fields as sent.

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
  invented `CONTROLLER_TOKEN`, which the fake checks, and its `STORE_ENVIRONMENT_ID` to
  `playwright-store`, an environment the suite's `chats` fixture puts in the fake
  ([`chats.md`](chats.md)); the `controller` fixture drives it ([`work.md`](work.md)).

A test drives it through its verbs, in process, or over HTTP as `POST <base>/fake/<verb>` with the
verb hyphenated and its keyword arguments as the JSON body: `add_environment`, `remove_environment`,
`set_status`, `set_exempt`, `settle_starts` (what a start or a reset brings the environment to at
once; None holds it `starting`), `settle_creates` (what a create brings its environment to at once,
`running` by default, and that environment's starts and resets after it; None holds it
`provisioning` until `set_status`), `restart` (the pod's containers restart: its restart count moves, its sessions
go, it reads `starting` until `set_status`, and the pod and its `startedAt` stay), `recreate_pod` (a
new pod, with a later `startedAt`, its sessions gone, the environment `starting` until
`set_status`), `unreachable` (`502 worker-unreachable`), `outage` (`on`, `answer`: every call but
the verbs, `/readyz` among them, has its connection closed with no answer, `none`, which needs
werkzeug's server, or an ingress's `502` page, `ingress`, and every open stream ends; `on=False`
answers again), `capped` (with an `env_id`, that environment's start and reset are `409
admission-blocked`; with none, the node's cap, every create too; never an exempt one's),
`not_whitelisted` (a create of a repository of that owner is `403 namespace-not-whitelisted`),
`no_sandbox_profile` (with `env_id`, `on`: that environment's boxed creates are `409
capability-unavailable` until `on=False`),
`unprojectable`, `busy`, `play` (the lines `claude` prints, answered with their offsets), `finish`
(the turn's outcome: `success`, `error`, `interrupted`, `spawn-failure` or `ended`), `write_log`,
`publish_state`, `publish_sessions`, `drop_streams`, `put_file` (a process in the environment
writes the file, whatever its status; over HTTP its `content` is text), `remove_file`, `file_text`
(the file's text, None when there is none: over HTTP a `204`), `unreadable` (the environment's read
and its file routes `503 environment-unreadable`) and `reset`, which forgets everything, an
outage, the node's cap, the refused owners and how creates settle included; it is not the
controller's reset route. `environment()` (its `resets` counting the resets that cleared its
folder, its `files` the bytes by path), `session()`, `sessions()` and `calls` read its state.

The turns a test plays are invented, in `backend/tests/fixtures/raw/turn_text.jsonl`,
`turn_tool.jsonl` and `turn_subagent.jsonl`, read by `raw_turn(name)`: bare `claude` lines in the
shapes of its stream-json, which the fake frames as the controller does. No line of them is a real
session's.
