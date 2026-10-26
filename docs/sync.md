# The sync

The store environment's tree ([`projection.md`](projection.md)) is kept a live projection of the
record, in both directions, by `pilot-sync`: a Go sidecar in the store's pod that talks to the
backend's sync routes under `/api/sync`. An agent's save of a file goes up through the engine's
ingest ([`engine.md`](engine.md)), and a file whose tree hash moves in the record is written down.
This page is the protocol and the sidecar as built: the routes in `backend/app/api/sync.py`, with
`SyncService` and `SyncStreamService` behind them, and the Go module in `sidecar/`.
`backend/tests/api/test_sync.py` pins every route's shapes and statuses beside the protocol's
version, and the sidecar's own tests pin its client against those shapes.

## The gate

The routes are registered on the app, outside the signed-in API, so the OIDC gate never sees them:
the bearer is the store. Every call carries three headers, and the blueprint's gate checks them in
this order before anything is read:

| Header | Refused |
|---|---|
| `Authorization: Bearer <token>`, the setting `SYNC_TOKEN` | `401`, and every call while `SYNC_TOKEN` is empty: an empty setting and a wrong bearer answer the same message |
| `X-Pilot-Environment: <id>`, the store environment's KubeCoder id, the setting `STORE_ENVIRONMENT_ID` | `403`, and every call while `STORE_ENVIRONMENT_ID` is empty |
| `X-Pilot-Sync-Protocol: <version>` | `426` with `{"min", "max"}`, the versions the server serves, for a version outside them, a value that is not decimal digits, or none |

A call the gate refuses touches nothing. One it lets through makes the store's Environment row when
there is none. While a controller is configured ([`controller.md`](controller.md)), the row is the
controller's report of the store (`EnvironmentService.ensure_environment`), so its name and its
exemption, PilotProjects' `capacityExempt`, are the fleet's from the row's first moment: the start
job can start the store, and the shutdown timer never stops it. While that row is still to be
made, a call is answered `502`, and makes none, when the controller does not report the store or
cannot be reached. With no controller, the row is named by the store's id and not exempt.

**The protocol version.** The server serves `SYNC_PROTOCOL_MIN` to `SYNC_PROTOCOL_MAX`
(`backend/app/services/sync_service.py`), both 1, and `pilot-sync` speaks `protocol.Version`, 1. A
change to any request or response shape of the routes bumps the sidecar's version and the
server's `SYNC_PROTOCOL_MAX` in one commit.

## The routes

A path is from the tree's root, with forward slashes (`recipe-box/items/4-card-layout.md`). A hash
is the sha256 of a file's bytes in lowercase hex, and a path's tree hash is the hash of what its
file must hold ([`projection.md`](projection.md)). Every route answers the gate's `401`, `403`,
`426` and `502` besides its own statuses.

| Route | Takes | Answers |
|---|---|---|
| `PUT /api/sync/files/<path>` | the file's bytes, at most `SYNC_PUT_MAX_BYTES`; `X-Pilot-Base-Hash`, the hash the sidecar last synced for the path, or `none` | `204` when the file needs no change, `200` with the bytes it must now hold when it does |
| `GET /api/sync/files/<path>` | | `200` with the bytes the path must hold, and `X-Pilot-Hash` |
| `POST /api/sync/manifest` | `{"tree", "shadow"}` | the reconcile, below |
| `GET /api/sync/events` | | the change stream, below |
| `POST /api/sync/check` | `{"path", "hash", "wait_seconds"}` | the check, below |

The put is the engine's ingest of the save, its Save Errors under the store's Environment, by no
session: nothing tells it which of the project's sessions wrote the file. `204`
for a save the merge left as it was and for a held one, `200` with the merged text, the canonical
`plan.json` or a read-only path's rendering. Either answer carries `X-Pilot-Hash`, the hash of what
the file holds once answered, and `X-Pilot-Faults`, the count of Save Errors the save raised on the
path (`0` for none); `X-Pilot-Stale: true` says the base hash was not the path's tree hash. It
answers `400` for a base hash that is missing or is neither `none` nor a hash, and `413` for a body
over the limit. A path of no syncing project is a `404` from either file route: a stray file, a
folder no project has or an archived project's.

Bytes go both ways as `application/octet-stream`. A JSON body without its shape, a hash in it that
is not 64 lowercase hex digits included, is a `400`.

## The change stream

`GET /api/sync/events` is a `text/event-stream` of named events, each with one line of JSON:

- `hello`, first: `{"protocol": {"min": 1, "max": 1}, "manifest_hash": "<hash>"}`. The manifest
  hash is the sha256 of the manifest in path order, each entry its path, a NUL, its tree hash, a
  NUL, `1` for a read-only path or `0`, and a newline.
- `change`, `{"path", "hash"}`: a path's tree hash moved, sent once the transaction that moved it
  has committed (the bus's `TreeHashMoved`, [`engine.md`](engine.md)).
- `manifest`, `{}`: the set of syncing projects changed (the bus's `ManifestChanged`): a project
  archived or brought back ([`projects.md`](projects.md)), and the testing endpoint below.

A `: heartbeat` comment follows `SYNC_HEARTBEAT_SECONDS` without an event. There is no `id:` field
and no replay: the sidecar's hashes are its cursor, and a reconnect reconciles. The stream ends on
the server's `PREPARE_SHUTDOWN`, after which a connect is answered `200` and ends at once with no
`hello`, and when it falls 1000 events behind. Each open stream is a subscriber of the engine's bus
with a queue of its own (`backend/app/services/sync_stream_service.py`).

## The manifest and the reconcile

The manifest is every path the store syncs (`TreeService.manifest()`): `reference.json` at the
tree's root and every path of every project that is not archived — its documents,
`timeline.json`, `chat.md`, `plan.json` and its attachments — each with its tree hash and whether
it is read-only. `reference.json`, `timeline.json`, `chat.md` and the attachments are.

`POST /api/sync/manifest` takes the hash of every file on disk, `tree`, and of every path as the
sidecar last synced it, `shadow`, each a map of path to hash. It answers `{"manifest", "send_up",
"write_down", "delete"}`, each list in path order and a manifest entry `{"path", "hash",
"readonly"}`:

- `write_down`: every manifest path whose tree hash is not the hash on disk, a path not on disk
  included;
- `delete`: every shadow path the manifest does not list;
- `send_up`: every manifest path whose hash on disk is not its shadow's. The sidecar sends those up
  before it asks, so the list is a cross-check, logged as a warning and never acted on.

A file the record never bore is in neither the manifest nor the shadow, so it is in no list, and a
reconcile never removes it. A held document's tree hash is its ingest's, so a file still holding
the held save is not written down. A held `plan.json` is: its rendering is written down canonical,
and its `parse` Save Errors go with the save that raised them, in every environment, with
`ErrorsResolved` (`IngestService.write_down`).

## The check

`POST /api/sync/check` is the hook's check of a file after an agent's edit. It takes the file's
hash on disk once the sidecar has had it acknowledged, and `wait_seconds`, how long the sidecar
waited for that (at least 0). It answers:

- `checked`, whether the server agrees the file holds that hash: the hash the server last
  acknowledged for it (D006). It does for the path's tree hash and, for a document, its
  `ingested_hash`, the latest save the server took, so a document the server rewrote with a `200`
  checks true by the save's hash as well as by the bytes written. A held `plan.json`, whose save is
  stored nowhere, agrees with any hash while its `parse` Save Errors stand. Otherwise, and for a
  path that names nothing, it is false, logged.
- `errors`: the Save Errors of the store's Environment in the file's project folder, `{"path",
  "kind", "line", "message"}`, by path and then in the order raised. The folder is the `<slug>/` or
  `draft-<number>/` the path starts with, when a syncing project has it
  (`TreeService.project_of`); a path under no syncing project's folder, at the tree's root or in an
  archived project's, is answered its own Save Errors alone. A `reverted` one is reported once, to
  its project's check: the statement that reads them deletes them, so another project's check never
  takes it. A `parse` one stands until a clean save of its path.
- `homeless_deferrals`: the deferrals without a home of the file's project, `{"block", "document",
  "title", "to"}`, computed at the check and never stored: a block answered `deferred` in the
  document of one of its done items, deferred to a plan task that is not done or to the plan while
  the project is not finished, that no plan note names, a struck note's reference counting. `block`
  is `<item id>/<local id>`, `document` its path from the tree's root, `title` its item's (null
  while it has none) and `to` the task or `plan`, in item and block order
  (`PlanService.homeless_deferrals(project)`). None for a path under no syncing project's folder.

## Settings and metrics

| Setting | Default | |
|---|---|---|
| `SYNC_TOKEN` | empty | the store's bearer, a secret; empty refuses every call |
| `STORE_ENVIRONMENT_ID` | empty | the store environment's KubeCoder id; empty refuses every call |
| `SYNC_PUT_MAX_BYTES` | 2 MiB | the largest body a put takes |
| `SYNC_HEARTBEAT_SECONDS` | 15 | how long the change stream waits for an event before a heartbeat |

The metrics, on the backend's `/metrics`:

- `pilot_sync_ingest_seconds{kind, outcome}`, a histogram of the time a put spends in the engine:
  `kind` `document`, `plan` or `view` (any read-only path); `outcome` `published`, `held`,
  `reverted` (published with faults) or `readonly`;
- `pilot_sync_faults_total{kind}`: the Save Errors the puts raised, `parse` or `reverted`;
- `pilot_sync_stale_puts_total`: the puts whose base hash was not the path's tree hash;
- `pilot_sync_reconciles_total`: the manifest calls;
- `pilot_sync_hook_wait_seconds`, a histogram of the checks' `wait_seconds`;
- `pilot_sync_stream_connects_total`, and the gauge `pilot_sync_stream_connected`: the streams
  open.

## `pilot-sync`

The sidecar is the Go module in `sidecar/` (`cmd/pilot-sync`, its packages under `internal/`), the
`sidecar` component of `kc project`, whose verbs run in the `go` tool container. Its configuration
is its environment's, and it reads no other variable:

| Variable | |
|---|---|
| `PILOT_URL` | the server's base URL, `http` or `https`; required |
| `PILOT_SYNC_TOKEN` | the store's bearer; required |
| `KUBECODER_ENVIRONMENT_ID` | the environment it runs in, sent as `X-Pilot-Environment`; required |
| `PILOT_SYNC_LOCAL_PORT` | the local check's port; `3510` |
| `PILOT_SYNC_TREE_ROOT` | the tree, an absolute path; `/work/Projects` |
| `PILOT_SYNC_DATA_DIR` | the directory its shadow is kept in, an absolute path; `/var/lib/pilot-sync` |

At start it proves its data directory writable, loads the shadow, makes the tree's root when there
is none, watches every directory of the tree and binds the local port on `127.0.0.1`. A variable
missing or malformed, a data directory it cannot write or a port in use stops it with exit 1 and a
log line naming the cause. It logs to stderr and exits 0 on SIGTERM or SIGINT.

**The shadow** holds, for each path, the bytes the server holds for it as last synced, at
`<data directory>/shadow/<path>`, and their hash; a restart keeps it. A file whose hash is its
shadow's is in sync, so a file the sidecar wrote itself never goes back up.

**Up.** fsnotify watches every directory of the tree, one made later included, and a file's change
is taken once its events have been quiet for 50 ms. A file whose hash is not its shadow's is put
with the shadow's hash as its base, `none` when the shadow has none. A path has one call out at a
time, and four calls run at once across paths, fetches included. The answer goes into the shadow
before anything is written, and a `200`'s bytes are written over the file, with its mode, only while
the file still holds the bytes sent: what the agent wrote meanwhile stays, and goes up next. Every
write is a temp file in the file's directory, named `.pilot-sync-…`, renamed over it. The client
refuses an answer whose `X-Pilot-Hash` is not the hash of the bytes the file then holds. A `404`
leaves the file as it is, with a local note; any other failure is logged, and the next reconcile
sends the file up. A file deleted sends nothing: nothing is deleted going up, and the reconcile
writes a file of the record back down.

**Down.** The sidecar holds the change stream open. It reconciles on every connect, then applies
the events until the stream drops: a path's `change` events are gathered for 100 ms, and the path
is fetched unless the hash is its shadow's, a fetch answered `404`, a path no longer the record's,
left for the reconcile; a `manifest` asks for a reconcile; an event it does not know is logged and
ignored. A drop or any refusal but a `426`, a `401`, a `403` or the gate's `502` among them,
reconnects after 1 s, doubling to 30 s, and back to 1 s once a connection has reconciled. A `426` retries every 60 s, logging the server's
range and its own version.

**The reconcile** runs on every connect, on `manifest`, and when the watch's kernel queue overflows,
once every directory is watched again; its walk of the tree is the rescan.

1. It walks the tree, and every file whose hash is not its shadow's goes up; the reconcile waits for
   each.
2. It posts the tree's hashes and the shadow's to `/api/sync/manifest`.
3. It writes each `write_down` path down, gives every read-only path of the manifest the mode 0444,
   and deletes each `delete` path with the directories that leaves empty.

Bytes that never synced are kept. A file to write down that does not hold its shadow's bytes is
left for its upload, whose answer carries the record's. A file to delete is removed only while it
holds them; otherwise the shadow forgets the path and the file stays, a stray. A reconcile that
fails ends the connection, and the reconnect runs it again. A reconcile asked for while the stream
is down is the connect's.

**Read-only views.** The paths the last manifest marked read-only are views, written 0444; until
the first manifest after a start, no path is. A write that gets through to a view the shadow holds
goes nowhere: the shadow's bytes are written back over it, 0444, with a local note. A view the
shadow does not hold goes up, and the rendering the server answers is written 0444.

## The local check

The sidecar serves the store's hook and `pilot.py` (below) on
`127.0.0.1:<PILOT_SYNC_LOCAL_PORT>`, in `text/plain`:

- `GET /healthz`: `200`, `ok`.
- `GET /check?path=<absolute path>`: the check of a file of the tree after an edit. When the file
  holds its shadow's hash, that hash is posted to `/api/sync/check` at once. Otherwise the check
  waits for the next upload of the file to read it, and posts what that came to: the hash the
  server holds for it (the bytes sent on a `204`, the answer written on a `200`, a view's
  re-projection), or the bytes' own on a `404`. Past 2 s from the call, or when the server cannot be
  reached, it answers `not yet checked: <path>`. A path that is not absolute or not inside the tree
  is a `400`, one with no file a `404`.

The answer is the text for the agent, empty when there is nothing to tell: each Save Error as
`<path>:<line>: <message>` (`<path>: <message>` without a line); then each local note as
`<path>: <note>`; then the deferrals without a home under the heading `Deferrals without a home (no
plan note names these blocks):`, each as `- <block> in <document> (<title>), to: <to>`. The local
notes are what the sidecar knows of a file that the server holds no Save Error for:

- ``not a document of the record — files are born through `add_item` ``, on a file the server
  answered `404`, kept until the file is taken by a put, written down, deleted or gone;
- `a read-only view; re-projected`, on a view whose write was undone, printed by one check.

**The hook** is `pvginkel/PilotProjects`' `.claude/hooks/pilot-sync-check.py`, which its
`.claude/settings.json` runs after every `Edit` and `Write` (`PostToolUse`, a 5 s timeout), so a
session whose project directory is the store's checkout of PilotProjects has it. It reads the tool's
`file_path` and asks nothing for a path outside `/work/Projects/`. For one inside, it calls
`/check?path=` on `127.0.0.1`, at the port its own `PILOT_SYNC_LOCAL_PORT` names or `3510`, the port
both stages' sidecars serve, with a 3 s cap, and hands a non-empty answer to the agent as the tool
result's `additionalContext`. An empty answer, an error status, a refused connection or the cap
adds nothing, and it exits 0 every time, so it never stops a turn. PilotProjects' `kc project test`
runs it against a stand-in for the sidecar.

**`pilot.py`**, PilotProjects' `tools/pilot.py`, the brain's editing script, asks the same check of
each file a verb of it wrote, at the same port with a 5 s cap, and prints the answer. It exits 1
where a Save Error names a file it wrote, 3 where an answer is `not yet checked`, an error status or
none, and 0 otherwise; its `check <path>` asks it alone, for a file written by hand
([`block-dsl.md`](block-dsl.md)).

## The image

`sidecar/Dockerfile` builds `pilot-sync` static (`CGO_ENABLED=0`) on the Go toolchain image the
tests run on, into `scratch` with the CA bundle and `/pilot-sync` as its entrypoint. It sets no
user: the pod's security context gives it the environment's uid, so what it writes the agent can
edit. `kaniko --no-push --context sidecar` builds it here; every green build of `main` pushes it
([`deployment.md`](deployment.md)).

## In the store

`pilot-sync` runs in each stage's store environment, a KubeCoder environment of
`pvginkel/PilotProjects` on the stage's fleet, the one `STORE_ENVIRONMENT_ID` names
([`deployment.md`](deployment.md)). PilotProjects' `.kubecoder/config.yaml` lists the service
`pilot-sync`, and KubeCoder composes the sidecar into the store's pod from its catalog entry,
`controllerConfig.services.pilot-sync` in `pvginkel/KubeCoderDeploy`. Its `chart/values.yaml` holds
what the stages share: `mountWork: true`, so the sidecar sees `/work` and the tree in it;
`dataPath: /var/lib/pilot-sync`, where the shadow is kept for the environment; the bearer,
`PILOT_SYNC_TOKEN`, from the catalog secret `pilot-sync-token`; a 128 MiB memory limit; no security
context, so it runs as the pod's uid; and no ports, since the hook calls it on the pod's own
localhost. Each `config/<stage>/values.yaml` sets the stage's image and its `env` whole:
`PILOT_URL`, `https://pilot-dev.home` or `https://pilot.ginbov.nl`, and `PILOT_SYNC_LOCAL_PORT`
`3510`. KubeCoder gives it `KUBECODER_ENVIRONMENT_ID`. The image has no shell; its log is the
container's, `kubectl logs <store id> -c pilot-sync -n kubecoder-dev`, `-n kubecoder-prd` for
production's store.

## Testing it

- **The backend.** `backend/tests/api/test_sync.py` drives every route. The fixture `fake_sidecar`
  (`backend/tests/support/fake_sidecar.py`) plays `pilot-sync` against the real routes through
  Flask's test client, with the bearer and the environment id the suite's app is configured with,
  and needs the `environment` fixture, the store's. Its `tree` and `shadow` are dicts of path to
  bytes and to hash, and its change stream is open from the start. `write` and `remove` are the
  agent's edits, unseen; `save` writes and uploads, asserting the server took the path; `upload`
  puts one path, a `404` noted as the sidecar notes it; `drain()` applies what the stream carried up
  to its heartbeat (the suite's is 0.01 s), fetching each `change`, one answered `404` left for the
  reconcile as the sidecar leaves it, and reconciling on `manifest`;
  `connect()` reopens the stream and reconciles, `overflow()` reconciles; `check(path)` answers
  whether the server agreed and the text for the agent. The engine's tests use it too.
- **The sidecar.** `kc project test --project sidecar` runs `go test -race ./...`. The tests play
  the routes from an `httptest` server over a record of their own, on a temporary tree and data
  directory, and serve the local check on a free port.
- **Live.** `scripts/sync-live-proof.py` runs the binary against the dev stack
  ([`slice-test-plan.md`](slice-test-plan.md) §2). Two testing endpoints set off there what only
  the record can, and answer `400` `ROUTE_NOT_AVAILABLE` unless the server runs with
  `FLASK_ENV=testing` on a `STAGE` other than `prd`: `POST /api/testing/sync/answer`, `{"path",
  "block", "answer", "user"}`, a person's answer to a block (`user` a handle), answered `{"path",
  "hash"}`, `404` for no such document or person and `409` when the record refuses it; and
  `POST /api/testing/sync/manifest`, which raises `manifest` and answers `204`.
