# Pilot's MCP server

Pilot hands its own MCP server to every headless session it creates, and a work item's session
calls Pilot through it: `register_document`, a decision document it wrote, put to a person on the
project's timeline, and `attach_file`, the material that backs one, copied into the record. Each
tool is one REST call to the backend under the session's bearer, which names the session's project,
environment and work item, so the tools take none of them. What becomes of a registered document,
its read at the run's end, its write-back and the run's continuation, is
[`round-trip.md`](round-trip.md)'s.

## The process

`backend/pilot_mcp/` is a package beside `app/` that imports nothing of it. `python -m pilot_mcp`,
the backend image's second entry point, serves it with uvicorn: FastMCP, of `mcp` 1, over
Streamable HTTP at `/mcp`, stateless, so the process holds nothing between calls, with the
DNS-rebinding protection off, since its boundary is the bearer and not the `Host` header the front
door names it by. The server is `pilot`, and its instructions tell the session to write each
document under `/work`, register it, attach what backs it and end its turn without waiting for the
answers (`server.py`'s `INSTRUCTIONS`).

- **The bearer gate** (`server.py`, `BearerRequired`): a request with no `Authorization: Bearer
  <token>` is a `401` (`AUTHENTICATION_REQUIRED`), but for `GET /health/healthz` and
  `/health/readyz`, which answer `{"status": "ok"}` without one, the process's own readiness alone.
  The gate checks no token: any bearer is admitted to `initialize` and `tools/list`, and a tool call
  carries it to its route, which decides.
- **The tools** (`tools.py`) refuse what their routes would refuse, an empty path or a `to` that is
  not a uuid, before calling. Each then makes one `POST <PILOT_MCP_API_URL>/tools/pilot-work/<route>`
  (`api.py`, `PilotWorkApi`) with the call's `Authorization` header as it came, waiting 5 s to
  connect and 300 s for the answer. An error answer is a `ToolError` of the route's `error`, the
  reason whole, which the session reads as "Error executing tool <name>: <reason>"; an API that does
  not answer is "Cannot call pilot-work because Pilot's API at <url> did not answer (<error>)".
- **The surface** is what the session reads: each tool's description, its parameters' and its
  answer's, and the server's instructions, pinned word for word in
  `backend/tests/pilot_mcp/test_server.py` (`SURFACE`, `INSTRUCTIONS`). A change to them is a change
  to a contract ([`change-discipline.md`](change-discipline.md)).

| Setting | Default | |
|---|---|---|
| `PILOT_MCP_API_URL` | `http://localhost:3501` | the backend, as the pod's loopback reaches it |
| `PILOT_MCP_HOST`, `PILOT_MCP_PORT` | `0.0.0.0`, 3502 | where it listens |
| `PILOT_MCP_LOG_LEVEL` | `INFO` | |

It needs no database, Secret or `FLASK_ENV`. In each stage's pod it is the container `mcp`, behind
its own intranet host ([`deployment.md`](deployment.md)). The dev stack runs none: `Procfile.dev`
starts the backend and Vite alone.

## Handed to every session

`PilotServer` (`backend/app/services/pilot_server.py`, the container's `pilot_server`) hands the
server at `MCP_SERVER_URL` to each headless create Pilot makes, a start's and a relay's re-create of
a gone controller session alike ([`sessions.md`](sessions.md)):

- it mints a token, `secrets.token_urlsafe(32)`, and appends `PILOT_TOKEN=<token>` to the create's
  `env`;
- it appends one inline entry to the create's `mcpConfig`: `{"mcpServers": {"pilot": {"type":
  "http", "url": <MCP_SERVER_URL>, "headers": {"Authorization": "Bearer ${PILOT_TOKEN}"}}}}`, which
  `claude` expands from the environment the controller spawns it in, so the token is in neither
  argv nor a file, and in no row, log line or record of Pilot's;
- it leaves `strictMcpConfig` unset, so the session keeps its environment's own servers.

A worker's tools are `mcp__pilot__register_document` and `mcp__pilot__attach_file`. The token's
sha256 is the Session's `token_hash`, written in the transaction that records the create's
controller session, so a bearer resolves to the Session whose controller session carries it; a
Session placed and not yet created holds the hash of a token no one has ([`record.md`](record.md)).
Every create mints anew: a session created again, by a Resume or after its pod restarted, carries a
token of its own, and the old one names nothing once the new one's hash is written.

`MCP_SERVER_URL` is the endpoint as a session reaches it, an `http` or `https` address. Empty, a
create carries neither the token nor the entry. A backend with `FLASK_ENV=production`, as both
deployed stages run, refuses to start without it ("MCP_SERVER_URL must be set in production"), a
check of the server's background start, which the CLI never runs.
Only the sessions Pilot creates are handed it: an interactive session, or one another client of the
controller creates, never sees Pilot's tools.

## The worker's routes

`backend/app/api/pilot_work.py`, the blueprint `pilot_work` at `/tools/pilot-work/`, is registered
on the app (`register_root_blueprints`), not on the API's blueprint, so the OIDC gate never sees it;
and it is outside `/api/`, the one prefix the UI's nginx forwards, so neither stage's site reaches it
and only the pod's loopback does, where the MCP server calls it (D048). Every call passes its gate
first, `PilotWorkService.admit` (`backend/app/services/pilot_work_service.py`): the bearer's sha256
matched against `sessions.token_hash`, `401` with no bearer or one no Session has, and `403` for a
Session whose kind's surface is not `pilot-work` or that is no work item's. An answer outside 2xx is
the API's error envelope, its `error` the reason whole. A controller that does not answer, or that
refuses for a reason of its own, is a `502`.

### `register_document(path)`

`POST /tools/pilot-work/documents` `{path}` answers `{id}`, the document's item. The file at `path`,
an absolute path in the session's environment, is read through the controller at once, a stopped
environment's too, and read as the record reads a worker's text, its decoding's faults, its own and
those against the record ([`engine.md`](engine.md)). A path outside `/work`, nothing there, a
folder, a file over 16 MiB or a text with faults is refused, `409` "Cannot register document <path>
because …", each fault with its line where it has one (`line N: …; …`), and nothing is minted, so
the worker fixes the file while its turn still runs and registers it again (D044). The read is made
before any lock is taken.

A file that reads clean registers its document: `201` for one minted, a review on the project's
timeline at its next place, with no text until the end of the run ([`round-trip.md`](round-trip.md));
`200` for the one the session registered from that path already, which a second call reads and
checks again all the same. The path is kept as given, not normalised. The continuation that resumes
the conversation is a session of its own, so its registration of a revised file mints a new item,
and the answered one stays as it was closed.

### `attach_file(path, to?)`

`POST /tools/pilot-work/attachments` `{path, to?}` answers `201` `{ids}`, one attachment per file.
`to` is the item the material backs, an item of the session's project, usually the id
`register_document` answered; without it, the session's own work item. One that names no item of
the project, another project's included, is a `404` "Item <id> was not found".

The path is read through the controller now, in the session's environment: a file is one
attachment, named by the path's last segment; a folder, the read's `409 not-a-file`, is listed, and
every file under it, its subfolders' and what a link under it leads to included, is one attachment,
named by its path relative to the folder, in path order. They are one batch, the project's next,
hung after the item's own attachments (`AttachService.attach`, `backend/app/engine/attachments.py`),
each with its source, the environment and the path it was read from, and `copied_at` the
transaction's time. A file's type comes from its extension by Python's own table, else
`text/plain; charset=utf-8` where its bytes are UTF-8, else `application/octet-stream`; its title is
a Markdown file's own (its front matter's `title`, else its first heading), else its file name. A
copy is never refreshed: what the worker changes in the file later is not seen.

A call that cannot copy every file it names attaches nothing and is a `409` with the reason: a path
outside `/work`, nothing there, neither a file nor a folder (a FIFO, a socket), a file over 16 MiB,
a link loop, a folder of more than 1000 files (`MAX_CALL_FILES`, counted on its listing before any
read) or files over 64 MiB together (`MAX_CALL_SIZE`). Every read is made before the project's row
is locked, and the bytes are held until the call commits. An empty folder attaches nothing and
answers `[]`.

## Testing it

The server is pinned in `backend/tests/pilot_mcp/`: a real MCP client drives the app in process
(`backend/tests/support/pilot_mcp.py`), its API calls answered by the test app's own routes in the
test's session, and `test_main.py` runs `python -m pilot_mcp` as a process. The injection is
`tests/services/test_pilot_server.py`, with the creates in `test_session_start_service.py` and
`test_relay_service.py`, whose `_services(..., mcp_url=)` and `_relay_service(..., mcp_url=)` build
services that inject; the suite's default settings set no URL, so other creates carry neither. The
routes are `tests/api/test_pilot_work.py`, whose `test_the_surface_is_one_route_outside_the_api`
holds the blueprint's rules, and `tests/services/test_pilot_work_service.py`; the copies
`tests/engine/test_attachments.py`. The fake controller serves the file routes
([`controller.md`](controller.md)), and the record's testing route
`POST /api/testing/items/<id>/registrations` registers a document as the tool does
([`projects.md`](projects.md)). `frontend/tests/infrastructure/nginx.spec.ts` pins that the UI's
nginx forwards no path under `/tools/`, whatever its extension.
