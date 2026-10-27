# Pilot's MCP server

Pilot hands its own MCP server to every headless session it creates, one of two surfaces by the
session's kind. A work item's session gets `pilot-work`: `register_document`, a decision document
it wrote, put to a person on the project's timeline, and `attach_file`, the material that backs
one, copied into the record. The brain's sessions, a project's chat and the server's jobs, get
`pilot-store`, the one door to the record beyond the project's folder: `add_item`, `attach_file`,
`answer`, `mark`, `stop_work`, `finish` and `ask_writer`. Each tool is one REST call to the backend
under the session's bearer, which names the session's project, environment and work item, so the
tools take none of them, and each call that changed the record is its effect, a line in the
session's records where the call ran. What becomes of a registered document, its read at the run's
end, its write-back and the run's continuation, is [`round-trip.md`](round-trip.md)'s; the chat
the brain's tools serve is [`chats.md`](chats.md)'s.

## The process

`backend/pilot_mcp/` is a package beside `app/` that imports nothing of it. `python -m pilot_mcp`,
the backend image's second entry point, serves it with uvicorn: FastMCP, of `mcp` 1, over
Streamable HTTP, `pilot-work` at `/mcp` and `pilot-store` at `/mcp/store`, two servers both named
`pilot` in one app, stateless, so the process holds nothing between calls, with the DNS-rebinding
protection off, since its boundary is the bearer and not the `Host` header the front door names it
by. `pilot-work`'s instructions tell the session to write each document under `/work`, register
it, attach what backs it and end its turn without waiting for the answers (`server.py`'s
`WORK_INSTRUCTIONS`); `pilot-store`'s say that its tools act on the one project `$PILOT_PROJECT`
names, only while the session's turn runs, how an item and a block are named, and that a call the
record refuses changes nothing (`STORE_INSTRUCTIONS`).

- **The bearer gate** (`server.py`, `BearerRequired`): a request with no `Authorization: Bearer
  <token>` is a `401` (`AUTHENTICATION_REQUIRED`), but for `GET /health/healthz` and
  `/health/readyz`, which answer `{"status": "ok"}` without one, the process's own readiness alone.
  The gate checks no token: any bearer is admitted to `initialize` and `tools/list`, and a tool call
  carries it to its route, which decides.
- **The tools** (`tools.py`) refuse what their routes would refuse, an empty path or a `to` that is
  not a uuid, before calling. Each then makes one `POST <PILOT_MCP_API_URL>/tools/pilot-work/<route>`
  or `…/tools/pilot-store/<route>` (`api.py`, `PilotWorkApi` and `PilotStoreApi`) with the call's
  `Authorization` header as it came, and the call's tool-use id, which Claude Code sends with every
  `tools/call` as `_meta["claudecode/toolUseId"]`, as the header `Tool-Use-Id` where it gave one,
  waiting 5 s to connect and 300 s for the answer. An error answer is a `ToolError` of the route's
  `error`, the reason whole, which the session reads as "Error executing tool <name>: <reason>";
  one that is not the API's envelope, as spectree's own validation answer or something other than
  the API at the URL writes, is "Pilot's API answered <status> <reason phrase>, not its error
  envelope"; an API that does not answer is "Cannot call pilot-work because Pilot's API at <url>
  did not answer (<error>)", `pilot-store` for the brain's.
- **The surface** is what the session reads: each tool's description, its parameters' and its
  answer's, and the server's instructions, pinned word for word in
  `backend/tests/pilot_mcp/test_server.py` (`WORK_SURFACE`, `WORK_INSTRUCTIONS`, `STORE_SURFACE`,
  `STORE_INSTRUCTIONS`). A change to them is a change to a contract
  ([`change-discipline.md`](change-discipline.md)).

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
server to each headless create Pilot makes, a start's and a relay's re-create of a gone controller
session alike, at the endpoint of the surface the create's scope names (`scoped_create`,
[`sessions.md`](sessions.md)): `pilot-work`, a work item's, at `MCP_SERVER_URL`, and
`pilot-store`, a chat's and a job's, at `<MCP_SERVER_URL>/store`, never both:

- it mints a token, `secrets.token_urlsafe(32)`, and appends `PILOT_TOKEN=<token>` to the create's
  `env`;
- it appends one inline entry to the create's `mcpConfig`: `{"mcpServers": {"pilot": {"type":
  "http", "url": <the endpoint>, "headers": {"Authorization": "Bearer ${PILOT_TOKEN}"}}}}`, which
  `claude` expands from the environment the controller spawns it in, so the token is in neither
  argv nor a file, and in no row, log line or record of Pilot's;
- it leaves `strictMcpConfig` unset, so the session keeps its environment's own servers.

A create whose scope names no surface, a finished project's chat's ([`chats.md`](chats.md)), is
handed neither the token nor the entry, so no bearer reaches either surface's routes from it; a
token's hash is minted for it all the same. A worker's tools are `mcp__pilot__register_document`
and `mcp__pilot__attach_file`, the brain's `mcp__pilot__add_item` and the rest. The token's
sha256 is the Session's `token_hash`, written in the transaction that records the create's
controller session, so a bearer resolves to the Session whose controller session carries it; a
Session placed and not yet created holds the hash of a token no one has ([`record.md`](record.md)).
Every create mints anew: a session created again, by a Resume or after its pod restarted, carries a
token of its own, and the old one names nothing once the new one's hash is written.

`MCP_SERVER_URL` is `pilot-work`'s endpoint as a session reaches it, an `http` or `https` address,
`pilot-store`'s under it. Empty, a create carries neither the token nor the entry. A backend with
`FLASK_ENV=production`, as both deployed stages run, refuses to start without it ("MCP_SERVER_URL
must be set in production"), a check of the server's background start, which the CLI never runs.
Only the sessions Pilot creates are handed it: an interactive session, or one another client of the
controller creates, never sees Pilot's tools.

## The worker's routes

`backend/app/api/pilot_work.py`, the blueprint `pilot_work` at `/tools/pilot-work/`, is registered
on the app (`register_root_blueprints`), not on the API's blueprint, so the OIDC gate never sees it;
and it is outside `/api/`, the one prefix the UI's nginx forwards, so neither stage's site reaches it
and only the pod's loopback does, where the MCP server calls it (D048). Every call passes its gate
first, `PilotWorkService.admit` (`backend/app/services/pilot_work_service.py`): the bearer's sha256
matched against `sessions.token_hash`, `401` with no bearer or one no Session has, and `403` for a
Session whose kind's surface is not `pilot-work` or that is no work item's, and for one whose turn
is not running, "Cannot call pilot-work because session <id> has no turn running", as `pilot-store`'s
gate answers: a bearer acts only while its turn does, so the bearer of a run Finish or Archive
stopped, or of one that has ended, adds nothing to the record. An answer outside 2xx is
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
before any lock is taken. Under the project's row lock its `seq` takes, the Session is read again,
and one no longer running is refused with the gate's `403`, nothing minted: Finish and Archive stop
the project's Sessions under that row, so a call that waited on it for either registers nothing in
the project they closed.

A file that reads clean registers its document: `201` for one minted, a review on the project's
timeline at its next place, with no text until the end of the run ([`round-trip.md`](round-trip.md));
`200` for the one the session registered from that path already, which a second call reads and
checks again all the same. The path is kept as given, not normalised. The continuation that resumes
the conversation is a session of its own, so its registration of a revised file mints a new item,
and the answered one stays as it was closed. A call that mints is the effect "Registered ·
inbox/<seq>", the document's folder and its item's number, since no title stands before the read
(below).

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
answers `[]`. A call that attached is the effect "Attached · <title>" for one file, "Attached ·
<folder>, <n> files" for more.

## The brain's routes

`backend/app/api/pilot_store.py`, the blueprint `pilot_store` at `/tools/pilot-store/`, stands
where `pilot_work` does: on the app, outside `/api/` and the OIDC gate, reached by the pod's
loopback alone. Its gate is `PilotStoreService.admit`
(`backend/app/services/pilot_store_service.py`): `401` as `pilot-work`'s, and `403` for a work
item's Session ("… is a work session, not a chat's or a job's") and for a chat's or a job's whose
turn is not running, so a bearer acts only while its turn does. A call acts on the bearer's project
alone: an item, a block or an attachment of another project is a `404` "… was not found". `for`
names a person by their handle, `404` "Person <handle> was not found" for one no person has, Pilot's
`agent` included. Every write locks the Project's row first and the Session's for the effect after,
the order Finish takes. A refusal of the record's is a `409` with the reason, the record unchanged,
and a controller that does not answer or refuses for a reason of its own a `502`.

- **`add_item(item)`**, `POST …/items`, answers `201` `{id, path, state, held, effect}`. `item` is
  one object in `timeline.json`'s shape ([`projection.md`](projection.md)): `kind` (`decision`,
  `question`, `action`, `notice`, `document`, `review` or `work`; `card_wait` and `timed_wait` are
  refused, "Pilot takes no waits yet"), `title`, `step` and `attachments`, then a prose item's
  `markdown`, `urgent`, `for` and `summary`, or a work item's `repo` (`owner/Name`), `cwd`, `brief`,
  `agent`, `model` and `reasoning_effort`. A field the kind does not take, and a work item without
  its `title`, `repo`, `cwd` or `brief`, are refused. A prose item is born in the record with its
  file, empty without `markdown` (`bear_item`, [`engine.md`](engine.md)): the call's `title` written
  into its front matter where that gives none, and `step`, `urgent`, `for` and `summary` where it
  gives none of its own (`with_facts`, [`block-dsl.md`](block-dsl.md)); its text is read first as a
  save of it is, and one with a fault is refused, each fault with its line, nothing minted: one with
  no title either way, and a block whose `by` names a person, whose answer is `answer`'s, after the
  add. `path` is a prose item's file, absolute. A work item is placed and started on add by its
  repository, as every work item's start is ([`sessions.md`](sessions.md)), in the `cwd` the brain
  gives, on its `agent`, `model` and `reasoning_effort`; its first turn is the brain's `brief`, a
  blank line, then the server's lines under `From Pilot:`: ``- This work item serves plan task <id>
  "<title>": write `step: <id>` into the front matter of every document you register.``, `- Auto
  pilot is on: the grants above hold for this session.` or `- Auto pilot is off: the grants above
  ask the operator first for this session.`, then `- The project's handbook:` and the handbook
  verbatim, each line that holds. `state` is its Session's, `starting` or `held`, and `held` why the
  gate holds it, `paused`, `controller_unreachable` or `slot`, for the brain to say so. Each of
  `attachments` is an attachment of the project by its id, hung on the new item, or outside
  material, `<environment>:<path>`, copied in as `attach_file` copies it, a batch per source, every
  source's files under the caps of one call, hung in their order. The effect is "Added · <kind's
  name> · <title>", with one `attached` beside it per attachment hung.
- **`attach_file(source, to)`**, `POST …/attachments`, answers `201` `{ids, effect}`: the material
  at `source`, `<environment>:<path>` in any environment the controller has, read as the worker's
  `attach_file` reads its own, a file or a folder's every file, one batch hung on the item `to`
  names. Without `to` it is refused, "it names no item to hang on: give `to`"; an environment the
  controller does not have is a `404` "Environment <id> was not found". Its effect is the worker's
  call's, "Attached · …".
- **`answer(block, value, for, note?, to?)`**, `POST …/answers`, answers `200` `{effect}`: the
  person's answer to the block, `<item id>/<local id>`, recorded on their behalf as the record's own
  answer, `via` `chat`, with `note`, and `to` the task or `plan` a `deferred` returns at
  ([`engine.md`](engine.md)). "Answered · <local id> · <title>".
- **`mark(item, mark, for?)`**, `POST …/marks`, answers `200` `{effect}`: `done` on a document,
  with its recommendations, `read` on a notice, `reviewed` on a review, for the person `for` names;
  without `for`, Pilot's own Done on a document it settled whole, and `read` and `reviewed` refused.
  "Marked done · <title>", "Marked read · …", "Marked reviewed · …".
- **`stop_work(item)`**, `POST …/stops`, answers `200` `{effect}`: the work item's Session stopped
  by Pilot as a Stop stops one ([`sessions.md`](sessions.md)), refused for an item that is no work
  item and for a Session neither running, starting nor held. "Stopped · <title>".
- **`finish()`**, `POST …/finish`, answers `200` `{effect}`: the project finished by Pilot as
  Finish finishes it ([`projects.md`](projects.md)), refused but in an open project. Its effect,
  "Finished · <project>", is written first: the transition then stops the brain's own Session among
  the rest, whose turn the interrupt ends once the call commits.
- **`ask_writer(document, block, question)`**, `POST …/writer-questions`, answers `201` `{blocks}`:
  the pre-ruling pass's question to the writer of a registered document about one of its blocks,
  stored verbatim as a Writer Question of the job's Turn in flight, once a block. A chat's call is a
  `403`; a blank question, an item that is no registered document or is done, a block not of it,
  answered or asked about already are refused. It changes no ask, so it writes no effect: the
  document's line says that Pilot asked its writer ([`timeline.md`](timeline.md)), `blocks` the
  local ids it is asked about in the document's order, and each question is counted,
  `pilot_pass_questions_total{project}`.

## Effects

Each call that changed the record writes its Effects (`EffectService`,
`backend/app/services/effect_service.py`), one per change, by kind: `added`, `answered`, `marked`,
`stopped`, `finished`, `attached` and `registered`, each naming the item, the block or the
attachment it changed. They are of the session's Turn in flight, placed in its records by one
`server` record of that Turn, written under the Session's lock in the call's transaction:
`{"type": "effect", "toolUseId": <id or null>, "effect": {"verb", "label", "itemId"?,
"blockId"?}}`, the line as shown, `<verb> · <label>`, the item it goes to (an attachment's, the item
it hangs on) and the block in it, `<item id>/<local id>`. A call that changed nothing writes none;
one whose Session has no Turn in flight writes none either, its changes standing, and the log says
so. A view puts the line on the call whose tool-use id it names, whether the effect's record was
written before or after the call's `assistant` line, and one whose call no record shows in its
record's place: a work item's session log ([`work.md`](work.md)), the Chat tab and `chat.md`
([`chats.md`](chats.md)). A block's latest `answered` effect whose call ran in a chat is where
*In the chat* goes, the block's `in_chat` ([`timeline.md`](timeline.md)).

## Testing it

The server is pinned in `backend/tests/pilot_mcp/`: a real MCP client drives the app in process
(`backend/tests/support/pilot_mcp.py`), its API calls answered by the test app's own routes in the
test's session, and `test_main.py` runs `python -m pilot_mcp` as a process. The injection is
`tests/services/test_pilot_server.py`, with the creates in `test_session_start_service.py` and
`test_relay_service.py`, whose `_services(..., mcp_url=)` and `_relay_service(..., mcp_url=)` build
services that inject; the suite's default settings set no URL, so other creates carry neither. The
routes are `tests/api/test_pilot_work.py`, whose `test_the_surface_is_one_route_outside_the_api`
holds the blueprint's rules, and `tests/services/test_pilot_work_service.py`, the brain's
`tests/api/test_pilot_store.py` and `tests/services/test_pilot_store_service.py`, the scope
`tests/services/test_session_scope.py`, the effects `tests/services/test_effect_service.py`; the
copies `tests/engine/test_attachments.py`. The fake controller serves the file routes
([`controller.md`](controller.md)), and the record's testing routes `POST
/api/testing/items/<id>/registrations` and `…/worker-attachments` register a document and attach a
file as the worker's tools do, and `…/writer-questions` asks a document's writer as the pass does
([`projects.md`](projects.md)). `frontend/tests/infrastructure/nginx.spec.ts` pins that the UI's
nginx forwards no path under `/tools/`, whatever its extension.
