# Pilot's MCP server

Pilot hands its own MCP server to every headless session it creates, one of two surfaces by the
session's kind. A work item's session gets `pilot-work`: `register_document`, a decision document
it wrote, put to a person on the project's timeline; `attach_file`, the material that backs one,
copied into the record; `set_progress` and `set_progress_step`, the steps its run goes through,
shown on its tile; and `register_debrief`, its run's debrief, shown behind the done work item's
Debrief and in its subject's debrief's notice. The brain's sessions, a project's chat, a conversation and the server's jobs, get
`pilot-store`, the one door to the record beyond the project's folder: `add_item`, `attach_file`,
`answer`, `mark`, `cancel_ask`, `stop_work`, `finish` and `ask_writer`. Each tool is one REST call to the backend
under the session's bearer, which names the session's project, environment and work item, so the
tools take none of them, and each call that changed the record is its effect, a line in the
session's records where the call ran, but for the steps and the debrief, which write none. What becomes of a registered document, its read at the run's
end, its write-back and the run's continuation, is [`round-trip.md`](round-trip.md)'s; the chat
the brain's tools serve is [`chats.md`](chats.md)'s.

Beside the two, the same process serves `pilot-projects`, the projects surface, to any session of
KubeCoder's production fleet, Pilot's own included: tools that read the projects Pilot manages,
their items and their files, `start_project`, which starts a draft, and the tools of a conversation
with Pilot about one ([`conversations.md`](conversations.md)). Its callers present one
shared token, and its tools call the API's own routes under `/api/` as Pilot's service user
([below](#the-projects-surface)).

## The process

`backend/pilot_mcp/` is a package beside `app/` that imports nothing of it. `python -m pilot_mcp`,
the backend image's second entry point, serves it with uvicorn: FastMCP, of `mcp` 1, over
Streamable HTTP, `pilot-work` at `/mcp` and `pilot-store` at `/mcp/store`, two servers both named
`pilot`, and `pilot-projects` at `/mcp/projects`, named for what it serves so that no session holds
two servers of one name, in one app, stateless, so the process holds nothing between calls but the
service user's token, with the DNS-rebinding protection off, since its boundary is the bearer and
not the `Host` header the front door names it by. `pilot-work`'s instructions tell the session to
write each document under `/work`, register it, attach what backs it and end its turn without
waiting for the answers (`server.py`'s `WORK_INSTRUCTIONS`); `pilot-store`'s say that its tools act on the one project `$PILOT_PROJECT`
names, only while the session's turn runs, how an item and a block are named, and that a call the
record refuses changes nothing (`STORE_INSTRUCTIONS`); `pilot-projects`' say what the surface is,
Pilot and its projects, that its tools read a project, its documents and its items, start one, and
talk to Pilot about one, and ask the session to load the skill `kubecoder:pilot-usage` before it uses them
(`PROJECTS_INSTRUCTIONS`).

- **The bearer gate** (`server.py`, `BearerRequired`): a request with no `Authorization: Bearer
  <token>` is a `401` (`AUTHENTICATION_REQUIRED`), but for `GET /health/healthz` and
  `/health/readyz`, which answer `{"status": "ok"}` without one, the process's own readiness alone.
  The gate checks no token: any bearer is admitted to `initialize` and `tools/list`, and a tool call
  carries it to its route, which decides. A request to `/mcp/projects` meets the projects surface's
  door before it ([below](#the-projects-surface)).
- **The tools** (`tools.py`) refuse what their routes would refuse, an empty path, a `to` that is
  not a uuid, a step whose code, label or why is empty or too long, too many steps, or a debrief
outside its limits, before calling.
  Each then makes one call to `<PILOT_MCP_API_URL>/tools/pilot-work/<route>` or `…/tools/pilot-store/<route>`
  (`api.py`, `PilotWorkApi` and `PilotStoreApi`), a `POST`, or the steps' `PUT` and `PATCH`, with the
  call's `Authorization` header as it came, and the call's tool-use id, which Claude Code sends with
  every `tools/call` as `_meta["claudecode/toolUseId"]`, as the header `Tool-Use-Id` where it gave
  one, but for the steps' tools, which record no effect to name it, waiting 5 s to connect and 300 s
  for the answer. An error answer is a `ToolError` of the route's
  `error`, the reason whole, which the session reads as "Error executing tool <name>: <reason>";
  one that is not the API's envelope, as spectree's own validation answer or something other than
  the API at the URL writes, is "Pilot's API answered <status> <reason phrase>, not its error
  envelope"; an API that does not answer is "Cannot call pilot-work because Pilot's API at <url>
  did not answer (<error>)", `pilot-store` for the brain's.
- **The surface** is what the session reads: each tool's description, its parameters' and its
  answer's, and the server's instructions, pinned word for word in
  `backend/tests/pilot_mcp/test_server.py` (`WORK_SURFACE`, `WORK_INSTRUCTIONS`, `STORE_SURFACE`,
  `STORE_INSTRUCTIONS`, `PROJECTS_SURFACE`, `PROJECTS_INSTRUCTIONS`). A change to them is a change
  to a contract ([`change-discipline.md`](change-discipline.md)).

| Setting | Default | |
|---|---|---|
| `PILOT_MCP_API_URL` | `http://localhost:3501` | the backend, as the pod's loopback reaches it |
| `PILOT_MCP_HOST`, `PILOT_MCP_PORT` | `0.0.0.0`, 3502 | where it listens |
| `PILOT_MCP_LOG_LEVEL` | `INFO` | |
| `PILOT_MCP_PROJECTS_TOKEN` | none | the projects surface's shared token, its callers' bearer |
| `PILOT_MCP_TOKEN_URL` | none | the token endpoint of the service user's Keycloak client |
| `PILOT_MCP_SERVICE_CLIENT_ID`, `PILOT_MCP_SERVICE_CLIENT_SECRET` | none | that client |

The last four are the projects surface's: while one of them is unset or empty, the surface refuses
every call and the rest of the process serves. It needs no database or `FLASK_ENV`. In each stage's
pod it is the container `mcp`, behind its own intranet host, the surface's settings from the stage's
Secrets ([`deployment.md`](deployment.md)). The dev stack runs none: `Procfile.dev`
starts the backend and Vite alone.

## Handed to every session

`PilotServer` (`backend/app/services/pilot_server.py`, the container's `pilot_server`) hands the
server to each headless create Pilot makes, a start's and a relay's re-create of a gone controller
session alike, at the endpoint of the surface the create's scope names (`scoped_create`,
[`sessions.md`](sessions.md)): `pilot-work`, a work item's, at `MCP_SERVER_URL`, and
`pilot-store`, a chat's, a conversation's and a job's, at `<MCP_SERVER_URL>/store`, never both:

- it mints a token, `secrets.token_urlsafe(32)`, and appends `PILOT_TOKEN=<token>` to the create's
  `env`, then `PILOT_MCP_URL=<the endpoint>`, so that a process the session runs can call a tool
  with no MCP client (below);
- it appends one inline entry to the create's `mcpConfig`: `{"mcpServers": {"pilot": {"type":
  "http", "url": <the endpoint>, "headers": {"Authorization": "Bearer ${PILOT_TOKEN}"}}}}`, which
  `claude` expands from the environment the controller spawns it in, so the token is in neither
  argv nor a file, and in no row, log line or record of Pilot's;
- it leaves `strictMcpConfig` unset, so the session keeps its environment's own servers,
  `pilot-projects` among them where the environment registers it.

A create whose scope names no surface, a finished project's chat's ([`chats.md`](chats.md)), is
handed neither variable nor the entry, so no bearer reaches either surface's routes from it; a
token's hash is minted for it all the same. A worker's tools are `mcp__pilot__register_document`,
`mcp__pilot__attach_file`, `mcp__pilot__set_progress`, `mcp__pilot__set_progress_step` and
`mcp__pilot__register_debrief`, the
brain's `mcp__pilot__add_item` and the rest. The token's
sha256 is the Session's `token_hash`, written in the transaction that records the create's
controller session, so a bearer resolves to the Session whose controller session carries it; a
Session placed and not yet created holds the hash of a token no one has ([`record.md`](record.md)).
Every create mints anew: a session created again, by a Resume or after its pod restarted, carries a
token of its own, and the old one names nothing once the new one's hash is written. A Resume that
sends its Turn to the controller session it has creates nothing, so that session keeps the `env`
of its last create.

**A tool called with no MCP client.** A process the session runs, a script, calls a tool with one
JSON-RPC `tools/call` POSTed to `$PILOT_MCP_URL`, no `initialize` before it, since the server is
stateless, under `Authorization: Bearer $PILOT_TOKEN`, `Accept: application/json,
text/event-stream` and `Content-Type: application/json`. The answer is an event stream whose
`data:` line is the JSON-RPC response, `set_progress`'s list in its `result.structuredContent`. The
transport refuses a POST whose `Accept` does not name both types, `406`, and one whose
`Content-Type` is not JSON, `400` "Invalid Content-Type header".

`MCP_SERVER_URL` is `pilot-work`'s endpoint as a session reaches it, an `http` or `https` address,
`pilot-store`'s under it. Empty, a create carries neither variable nor the entry. A backend with
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
stopped, or of one that has ended, adds nothing to the record. A call that reads its Session with
no turn running is read again once a send under way has committed (`turn_running`,
`backend/app/services/pilot_server.py`): the gate waits for the Session's send lock shared, which
the start loop's send holds from before the controller's call to its commit, then takes the
project's row `FOR UPDATE`, which a chat's send holds shared to its commit, in a savepoint it
rolls back, so it holds neither after ([`sessions.md`](sessions.md)). So a call the turn makes as
soon as the controller has accepted it reads the Session `running`; one with no send under way is
refused. Both gates read it so. An answer outside 2xx is
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

### `set_progress(steps)` and `set_progress_step(code, state)`

The session's own work item's list of steps ([`work.md`](work.md)), each `{code, label, state,
why}`: `code` the run's name for the step, unique in the list, `label` its words on the tile,
`state` `pending`, `active` or `done`, and `why`, a short line shown under the label in the
popover, which a run gives the step that opens a repeat round to say why the round before did not
settle it, null where it gave none.

- **`PUT /tools/pilot-work/progress`** `{steps: [{code, label, state?, why?}]}` replaces the list,
  in the call's order: a code already on it keeps its row, and its state where its step gives
  none; a new code starts `pending`, or in the state it gives; a code left out goes; and `[]`
  removes the list. Each step's label and why are as the call gives them, so a step given without
  a why has none, whatever it had.
- **`PATCH /tools/pilot-work/progress`** `{code, state}` moves one step, every step keeping its
  place; a code not on the list is a `404` "Progress step <code> was not found".

Both answer `200` `{steps}`, the list as it stands, in order. A body outside the limits, an empty
code, label or why, a code over 64 characters, a label or a why over 120, a list over 100 steps
(`MAX_STEP_CODE`, `MAX_STEP_LABEL`, `MAX_STEP_WHY` and `MAX_STEPS` in
`backend/app/schemas/pilot_work.py`, which `pilot_mcp/api.py` mirrors), a state outside the three
or a field the step does not have, is a `400`, and a repeated code a `409`, nothing changed. The server's clock stamps a step's start when it first goes `active` or
`done`, never changed after, and its end each time it goes `done`, cleared when it leaves `done`; a
step set to the state it is in is left as it is. Each call holds the Session's row, `FOR NO KEY
UPDATE`, and refuses with the gate's `403` unless its turn still runs, so two calls on one list,
a script's and the agent's, are served one after the other, each answering the list its own change
left. No call writes an effect. One that changed the steps' codes, labels, whys, states or order
moves the work item's status ([`work.md`](work.md)); one that changed none of them sends nothing.

### `register_debrief(debrief, entries, subject?, completes?)`

The session's own work item's debrief ([`work.md`](work.md#its-debrief)), handed over once, before
its turn ends: `debrief`, the stage session's own account of how the run went, and `entries`, every
account of the run in order, each `{section, round, role, duration, words?, passed?, why?}`: the
name of the part of the run it ran in, its round of that part, whose account it is, its turn's time
in whole seconds, at most one of its words and `passed`, a pass or a fail in their place, and, on an
entry that opens a round past the first, that round's why. Every value is the workflow's: Pilot
stores it as given and shows it as given, and reads nothing of the workflow's shape from it (D159).
With them go `subject`, what the debrief is an account of, as the workflow names it, at most 120
characters, compared whole within the project, shown in the debrief's notice's title and read for
nothing else, and `completes`, true where left out, false where a later debrief of the same subject
completes it: one subject's debriefs come together in one notice, placed at the done of the work
item whose debrief completes it ([`work.md`](work.md#its-debriefs-notice)).

**`POST /tools/pilot-work/debrief`** `{debrief, entries, subject?, completes?}` answers `201` `{entries}`, the number
stored, the entries numbered from 1 in the call's order (`PilotWorkService.register_debrief`). A
body outside the limits is a `400` naming each fault, nothing stored: a debrief empty, blank or over
16,000 characters; no entries or over 500; an empty section, role, words or why; a section or a why
over 120 characters, a role over 64, words over 4,000; a round under 1 or a duration under 0, or
either not an integer, or a `passed` that is not a boolean; both words and `passed`; a subject
empty, blank or over 120 characters; a `completes` that is not a boolean, or false without a
subject; a field the call or an entry does not have (`MAX_DEBRIEF` to `MAX_DEBRIEF_SUBJECT` in
`backend/app/schemas/pilot_work.py`, which `pilot_mcp/api.py` mirrors). A second call is a `409`,
"it has its debrief already", nothing changed. The call holds the Session's row as the steps' calls
do and refuses with the gate's `403` unless its turn still runs, so a second call made at once
waits for the first and is refused. It writes no effect and no line in the session's records, moves
nothing and sends nothing: the work item shows its debrief once its turn has ended it done, and
that done places the debrief's notice where the debrief completes ([`work.md`](work.md)), and the store's tree carries none of it ([`projection.md`](projection.md)).
The tool sends no tool-use id, since no effect needs it.

## The brain's routes

`backend/app/api/pilot_store.py`, the blueprint `pilot_store` at `/tools/pilot-store/`, stands
where `pilot_work` does: on the app, outside `/api/` and the OIDC gate, reached by the pod's
loopback alone. Its gate is `PilotStoreService.admit`
(`backend/app/services/pilot_store_service.py`): `401` as `pilot-work`'s, and `403` for a work
item's Session ("… is a work session, not a chat's or a job's") and for a chat's, a conversation's
or a job's whose turn is not running, read as `pilot-work`'s gate reads it, a send under way waited for, so a bearer
acts only while its turn does. A call acts on the bearer's project
alone: an item, a block or an attachment of another project is a `404` "… was not found". `for`
names a person by their handle, `404` "Person <handle> was not found" for one no person has, Pilot's
`agent` and a service user's included. Every write locks the Project's row first, the order Finish
takes, then the Session's, before any Document's, the order a store save of the brain's takes the
project's row, its Session's and its Document's in ([`engine.md`](engine.md)). A refusal of the record's is a `409` with the reason, the
record unchanged, and a controller that does not answer or refuses for a reason of its own a `502`.

- **`add_item(item)`**, `POST …/items`, answers `201` `{id, path, state, held, effect}`. `item` is
  one object in `timeline.json`'s shape ([`projection.md`](projection.md)): `kind` (`decision`,
  `question`, `action`, `notice`, `document`, `review`, `work`, `card_wait` or `timed_wait`),
  `title`, `step` and `attachments`, then a prose item's `markdown`, `urgent`, `for` and `summary`,
  a work item's `repo` (`owner/Name`) or `environment`, an environment's id, `cwd`, `brief`, `agent`, `model`, `reasoning_effort`,
  `claims`, the blocks' ids, `<item id>/<local id>`, of the claimed actions it does, and
  `researches`, the ids of the blocks it checks a fact for, which the pass left open, a card wait's
  `cards` and `states`, or a timed wait's `due_at`, a time with its offset. A field the kind does not
  take, a work item without its `title`, `cwd` or `brief`, one that names both or neither of `repo`
  and `environment` ("a work item names exactly one of `repo` and `environment`"), and a wait
  without its `title` and its own fields, are refused. A wait is recorded as given and fixed from then on: an
  empty list ("its `cards` list is empty"), a card that is no ticket id ("`sr-1` is no ticket id,
  `<pattern>`"), a list naming a card twice or a state twice, case-insensitively, and a due time
  not ahead ("its due time, <UTC>, is not ahead") are refused ([`waits.md`](waits.md)). A prose item is born in the record with its
  file, empty without `markdown` (`bear_item`, [`engine.md`](engine.md)): the call's `title` written
  into its front matter where that gives none, and `step`, `urgent`, `for` and `summary` where it
  gives none of its own (`with_facts`, [`block-dsl.md`](block-dsl.md)); its text is read first as a
  save of it is, and one with a fault is refused, each fault with its line, nothing minted: one with
  no title either way, and a block whose `by` names a person, whose answer is `answer`'s, after the
  add. `path` is a prose item's file, absolute. A work item is placed and started on add
  ([`sessions.md`](sessions.md)): by its `repo`, in an environment of Pilot's own its start makes or
  takes from it, or by its `environment`, in that environment as it stands, which Pilot never
  makes, takes, renames or resets, and starts when it is stopped. A placement by `environment` asks
  the controller for the environment before any lock and writes Pilot's row of it where there is
  none: one the controller does not have is a `404`, "Environment <id> was not found", and the
  store's a `409`, "it is the store's environment, where no work item runs". It runs in the `cwd`
  the brain gives, on its `agent`, `model` and `reasoning_effort`; its first turn is the brain's `brief`, a
  blank line, then the server's lines under `From Pilot:`: ``- This work item serves plan task <id>
  "<title>": write `step: <id>` into the front matter of every document you register.``, `- Auto
  pilot is on: the grants above hold for this session.` or `- Auto pilot is off: the grants above
  ask the operator first for this session.`, then `- The project's handbook:` and the handbook
  verbatim, each line that holds. `state` is its Session's, `starting` or `held`, and `held` why the
  gate holds it, `week_halt` or `five_hour_halt` ([`usage.md`](usage.md)), `paused`,
  `controller_unreachable` or `slot`, for the brain to say so. Each of
  `claims` names the work item for a claimed action, an open action of a registered document of the
  project or of an item of Pilot's own of it (D224), checked before the start and written after it,
  so a refused claim starts nothing: each
  stays open, held through that work item's run ([`round-trip.md`](round-trip.md)), its line naming
  the work item named for it last, and the job after that work item's turn names it for its `done`
  ([`engine.md`](engine.md)); an item of Pilot's own is done, with no Undo, once the `done` of its
  last open block is written. A claim's item not of the project, or a block its document lacks, is
  a `404`; an item that is neither a registered document nor an item of Pilot's own ("… is neither
  a registered document nor an item of Pilot's own: Pilot claims an action of a worker's document
  or of its own item"), is done or not yet read, a block that is no action or is answered, and one
  named twice, a `409`. Each of `researches` names the work item for a block
  of an open registered document of the project with neither an answer, a claim's included, nor a
  `done`, checked and written as a claim is: each is held through that work item's run, its line
  naming the work item named for it last, and the job after its turn names it for the pass to route
  on what the work found. Its refusals are a claim's, but for an item of Pilot's own, refused as any
  item that is no registered document ("… is no registered document: Pilot researches a block of a
  worker's document"), and for the block's kind, which is any: "block <id> of <path> is answered"
  and "… is done" among them. Each of
  `attachments` is an attachment of the project by its id, hung on the new item, or outside
  material, `<environment>:<path>`, copied in as `attach_file` copies it, a batch per source, every
  source's files under the caps of one call, hung in their order. The effect is "Added · <kind's
  name> · <title>", with one `attached` beside it per attachment hung.
- **`attach_file(source, to?)`**, `POST …/attachments`, answers `201` `{ids, effect}`: the material
  at `source`, `<environment>:<path>` in any environment the controller has, read as the worker's
  `attach_file` reads its own, a file or a folder's every file, one batch hung on the item `to`
  names. In a draft's definition chat, a `to` left out hangs the batch on nothing, until Create
  project hangs it on the opening ([`projects.md`](projects.md)); anywhere else it is refused, "it
  names no item to hang on: give `to`". An environment the controller does not have is a `404`
  "Environment <id> was not found". Its effect is the worker's call's, "Attached · …", naming no
  item for a batch hung on nothing.
- **`answer(block, value, for, note?, to?)`**, `POST …/answers`, answers `200` `{effect}`: the
  person's answer to the block, `<item id>/<local id>`, recorded on their behalf as the record's own
  answer, `via` `chat`, with `note`, and `to` the task or `plan` a `deferred` returns at
  ([`engine.md`](engine.md)). "Answered · <local id> · <title>". An answer that closes an item of
  Pilot's own places no job after it: the chat's own turn carries the ruling out (D139), and the
  item is consumed on the spot by the chat's Session, so it offers no Undo (D225). A block of
  a draft's `project.md` is `project.md/<local id>`, which only that draft's definition chat
  answers, its title the draft's, else `project.md`; anywhere else it is a `409`. Its answer takes
  no Undo, the draft having no item.
- **`mark(item, mark, for?, note?)`**, `POST …/marks`, answers `200` `{effect}`: `done` on a
  document, with its recommendations, `read` on a notice or a debrief's notice, `reviewed` on a
  review, for the person `for` names, given through the chat as `answer` is, so that no job follows
  it, and a `done` or a `reviewed` on an item of Pilot's own is consumed by the chat's Session, with no Undo after it
  (D225), where a `read` keeps its Undo; without `for`, Pilot's own Done on a document it settled whole, and on a registered
  document of one block, whatever its kind, once that block is answered or deferred, a claimed
  action counting once its `done` is written; `read` and `reviewed` refused. A registered
  document's Done writes its answers back and continues its run once none of the run's documents is
  open ([`round-trip.md`](round-trip.md)). An open wait is closed by Pilot's own `done` alone, with
  no `for` and with its `note`, what was read and when and the action started after it: cause
  `marked`, consumed on the spot by the calling session, so it offers no Undo, the note kept as the
  wait's ([`waits.md`](waits.md)). A wait's `done` without a `note` ("a wait's `done` takes a
  `note`: …"), with `for`, or as `read` or `reviewed`, and a `note` on any other item, are
  refused.
  "Marked done · <title>", "Marked read · …", "Marked reviewed · …".
- **`cancel_ask(item, for)`**, `POST …/cancellations`, answers `200` `{effect}`: an open ask a
  session of Pilot's own added through `add_item`, a decision, a confirmation, a question, an action
  or a document, called off on the word of the person `for` names, by handle, both required (D209): done
  `cancelled` by them, its blocks as they stand, with no Undo and no job after it, its line led by
  the cancelled mark ([`engine.md`](engine.md)'s `call_off`). The server takes it from any Session of
  Pilot's own, as it takes `answer` and `mark` with `for`; that a person said so is the brain's to
  know, and its chat skill gives the cancel to an ask that no longer applies and the `No` to a
  confirmation the person refuses. Refused with the reason, nothing closed: a document a work item's
  run registered, which the Cancel on its page calls off and so ends its run (D210) ("a document a work item's run registered is called off by the Cancel on its page,
  which ends that run"), a notice ("a notice asks nothing, and takes its Read"), a work item, a
  wait or a debrief's notice ("a <kind> item is no ask"), an item no session of Pilot's own added ("it is no ask Pilot
  added"), a done one, an archived project's, an item not of the session's project, and a `for`
  that names no person or names Pilot. "Cancelled · <title>".
- **`stop_work(item, reason?)`**, `POST …/stops`, answers `200` `{effect}`: the work item's Session
  stopped by Pilot as a Stop stops one ([`sessions.md`](sessions.md)), one idle with its nudge owed
  among them, its turn ended under a usage halt or the project's pause, as its served description
  says; refused for an item that is no work item, for Pilot's own work, a job ("it is Pilot's own
  work"), and for a Session neither running, starting, held nor idle with its nudge owed, "it is
  stopped already" among them. "Stopped · <title>". With `reason`, a string that is not empty, a
  line its done line carries, the work item is closed for good in the same act, one Pilot replaced:
  one stopped already as it stands, and one a Stop takes stopped first, by Pilot; it is done
  `cancelled` by Pilot, the reason its Work's `done_note`, and takes no Resume and no Undo
  ([`work.md`](work.md)). The documents its run put to a person stay open. Refused with a reason: a
  failed item ("it has failed, and keeps its Resume"), one closed already ("it is closed for good"),
  one done otherwise ("it is done"), one whose turn ended ("its turn has ended"), a job ("it is
  Pilot's own work") and an archived project's ("its project is archived"). "Closed · <title>".
- **`finish(archive=false)`**, `POST …/finish` `{archive}`, answers `200` `{effect}`: the project
  finished by Pilot as Finish finishes it ([`projects.md`](projects.md)), refused but in an open
  project. With `archive`, on the operator's Finish and archive, the project is archived in the
  same act and no archive question is put, the archive the person's whose word the call carries
  out (there). A body that is not `{archive?}` is a `400`. Its effect, "Finished · <project>", or
  "Finished and archived · <project>" with `archive`, is written first: the transition then stops the brain's own Session among
  the rest, whose turn the interrupt ends once the call commits.
- **`ask_writer(block, question)`**, `POST …/writer-questions`, answers `201` `{blocks}`: the
  pre-ruling pass's question to the writer of a registered document about one of its blocks, the
  block's id, `<item id>/<local id>`, naming its document as `answer`'s does, with no argument of
  its own for the document (D084), stored verbatim as a Writer Question of the job's Turn in flight,
  once a block. A chat's call is a `403`; a blank question, an item that is no registered document
  or is done, a block answered or asked about already, and a call in the job after a clarification
  run or in a pass whose run another pass asked about, one round per worker turn, are refused: "the
  writer has answered the questions of the pass before it: this pass asks nothing" and "another pass
  of the same run asked its writer already: one round per worker turn". When the pass's job ends,
  its questions go to the writer in one clarification run ([`round-trip.md`](round-trip.md)). It
  changes no ask, so it writes no effect: the asked block's head says that Pilot asked its writer
  ([`timeline.md`](timeline.md)), `blocks` the local ids it is asked about in the document's order,
  and each question is counted, `pilot_pass_questions_total{project}`.

## Effects

Each call of the worker's or the brain's that changed the record writes its Effects, but the
progress tools' (`EffectService`,
`backend/app/services/effect_service.py`), one per change, by kind: `added`, `answered`, `marked`,
`stopped`, `finished`, `attached` and `registered`, each naming the item, the block or the
attachment it changed. They are of the session's Turn in flight, placed in its records by one
`server` record of that Turn, written under the Session's lock in the call's transaction:
`{"type": "effect", "toolUseId": <id or null>, "effect": {"verb", "label", "itemId"?,
"blockId"?}}`, the line as shown, `<verb> · <label>`, the item it goes to (an attachment's, the item
it hangs on, none for a draft's batch hung on nothing) and the block in it, `<item id>/<local id>`,
or a draft's `project.md/<local id>` with no item. A call that changed nothing writes none;
one whose Session has no Turn in flight writes none either, its changes standing, and the log says
so. A view puts the line on the call whose tool-use id it names, whether the effect's record was
written before or after the call's `assistant` line, and one whose call no record shows in its
record's place: a work item's session log ([`work.md`](work.md)), the Chat tab and `chat.md`
([`chats.md`](chats.md)), and the Conversations tab ([`conversations.md`](conversations.md)). A block's latest `answered` effect whose call ran in a chat is where
*In the chat* goes, the block's `in_chat` ([`timeline.md`](timeline.md)).

## The projects surface

`pilot-projects` is any session's: its tools read the projects Pilot manages, their items and their
files, start a draft, and talk to Pilot about one, for a session in any environment that holds the surface's token, which
every environment of KubeCoder's production fleet does ([`deployment.md`](deployment.md#secrets)).
Nothing of it is a session's of Pilot's: it takes no session's bearer, and its calls write no
effect.

- **The door** (`server.py`, `ProjectsDoor`), outermost, before the bearer gate: a request to
  `/mcp/projects` or under it is let in only with the surface's shared token as its bearer,
  compared in constant time, and any other is a `401` (`AUTHENTICATION_REQUIRED`), "Cannot call
  Pilot's projects because the request does not carry their token". The token is one value for
  both stages (D207), so a session pointed at dev's surface sends what it sends production's
  ([`deployment.md`](deployment.md)); the API never sees it. While one of the surface's four
  settings is unset or empty, the server is not mounted and the door answers every request to it
  `503` (`SERVICE_UNAVAILABLE`), "Cannot call Pilot's projects because this Pilot is not set up to
  serve them", while the two other servers and the probes serve on; the process logs "The projects
  surface refuses every call: <settings> unset" at its start.
- **The credential** (`credential.py`, `ServiceCredential`). Behind the door no tool calls under the
  caller's bearer (D207): each makes one call to the API's own routes under `/api/`, at
  `PILOT_MCP_API_URL`, under a client-credentials token of the stage's service-user client, minted
  at `PILOT_MCP_TOKEN_URL` from `PILOT_MCP_SERVICE_CLIENT_ID` and `PILOT_MCP_SERVICE_CLIENT_SECRET`,
  held, and minted again 30 s before it expires; calls that come at once wait for one mint. The
  token passes the API's sign-in gate as a person's does and names the service user's row by its
  subject ([`sign-in.md`](sign-in.md)). A token endpoint that does not answer, refuses the client
  or answers no token is the tool's error, "Cannot call Pilot because its sign-in service …", which
  never carries the secret; the API's refusal is the tool's error, its `error` whole, as the other
  surfaces' are, and an API that does not answer is "Cannot call pilot-projects because Pilot's API
  at <url> did not answer (<error>)".
- **The caller** (`api.py`, `Caller`): the call's `X-Pilot-Environment` and `X-Pilot-Session`, the
  id of the environment it calls from and its session's name there, an empty one none. Both travel
  on to the API's route under the same names. The plus's create names the environment in a call's
  brief ([`projects.md`](projects.md)); a conversation is the environment's, and keeps the
  session's name ([`conversations.md`](conversations.md)).

A tool's `project` is a project's id or its folder, `draft-<number>` while it is a draft and its
slug once created; a draft's folder does not survive Create project, so a session holds a draft by
its id. Each tool is one call (`tools.py`, `register_projects_tools`; `api.py`,
`PilotProjectsApi`):

| Tool | Route | Answers |
|---|---|---|
| `list_projects(archived?)` | `GET /api/projects` | `{projects}`, a row per project, `{id, folder, name, state, status}`, the unarchived ones, or with `archived` the archived alone, in the order they were started |
| `get_project(project)` | `GET /api/projects/head?address=` | `{id, folder, name, state, archived, status, autopilot, members, progress, running_work, open_items, url}`: the members by handle, each running work item `{seq, title, environment}`, and no step, note or file |
| `list_items(project, open?, kind?, offset, limit)` | `GET /api/projects/items?address=` | `{items, totalCount, limitHit}`: a row per item in `seq` order, `{seq, kind, title, path, created_at, done_cause, for, urgent}`, a field that is none or false left out; the open items alone unless `open` is false, of `kind` alone where one is given |
| `list_files(path?, offset, limit)` | `GET /api/tree/entries?path=` | `{files: [{path, isDirectory}], totalCount, limitHit}`, folders first |
| `find_files(path_pattern, offset, limit)` | `GET /api/tree/matches?pattern=` | `{pattern, files, totalCount, limitHit}`, the paths in path order |
| `read_file(path, start_line?, end_line?, tail_lines?)` | `GET /api/tree/text?path=` | `{content, sha256, totalCount, limitHit, lineCut}` |
| `start_project(brief, title?, for?)` | `POST /api/projects` `{words, title?, for?}` | `{id, folder, url}`, the draft |
| `start_conversation(project, text)` | `POST /api/conversations` `{address, words}` | the conversation, its first turn running |
| `send(conversation, text)` | `POST /api/conversations/<id>/messages` `{words}` | `{turn}`, the message's Turn's `seq` |
| `get_response(conversation, wait_ms?)` | `GET /api/conversations/<id>`, then `GET …/response` | `{turn, state, text}`, held (below) |
| `get_conversation(conversation)` | `GET /api/conversations/<id>` | the conversation |
| `list_conversations(project?)` | `GET /api/conversations[?address=]` | `{conversations}`, the calling environment's, in the order they opened |
| `interrupt(conversation)` | `POST /api/conversations/<id>/interrupt` | the conversation |
| `end_conversation(conversation)` | `POST /api/conversations/<id>/end` | the conversation, closed |

The routes answer a list whole and the process pages it (`_page`): `offset`, and a `limit` of 100
by default and 1,000 at most for `list_items` and `list_files`, 50 and 200 for `find_files`, a
larger one clamped; `totalCount` counts every row and `limitHit` says whether more remain. The file
tools are KubeCoder's fleet adapter's one for one, their defaults, caps, answers, ranges, tails and
glob, with no `env`, paths from the root of the projects' files, and no `skipped` or `truncated`
in `find_files`' answer, which count the folders a walk of a disk did not enter. What they read, and
their refusals, are [`projection.md`](projection.md#read-by-path)'s; `list_items`' `path` runs from
the same root, `<folder>/items/…`, so that `read_file` takes it as it is, and an item with no file,
a work item, a wait or a debrief's notice, has none.

A project's `state` is `draft` until Create project, then `open`, and `finished` once finished, or
`adopted` for one that stands for a group of work run before Pilot, archived from its birth and
never opened, which `list_projects` lists with `archived` alone and whose folder no file tool reaches
([`collection.md`](collection.md#the-adopted-project)).

`start_project` takes the brief in the session's own words, verbatim the first message of the
draft's definition chat, a one-line `title` and a person's handle as `for`, and no auto pilot
switch: the draft is the plus's create by a call, its creator the service user, and runs nothing
until a person presses Create project ([`projects.md`](projects.md)). A `for` that names no person
is the API's `404`, and a call while Pilot updates its store the API's `409` ("Pilot is updating");
neither starts anything.

### A conversation

The conversation's tools are KubeCoder's session tools one for one, on a conversation with Pilot
about a project ([`conversations.md`](conversations.md)): `start_conversation`, `send`,
`get_response`, `get_conversation`, `list_conversations`, `interrupt` and `end_conversation`. Each
but `get_response` is one call. A conversation is answered as `{id, project, environment, session,
opened_at, closed_at, close_cause, turns, running}`, the API's answer with `project_id` as `project`
and `in_flight` as `running`, and `close_cause` one of the five a conversation closes with. Where a
KubeCoder tool answers a handle or `{}`, the opening, the read, the interrupt and the end answer the
conversation, so that the end of one closed already says how it closed. A send whose Turn has an
`error`, the controller having failed it, is the `send` tool's error, its reason whole.

**`get_response`** alone holds its call, in the MCP process (`PilotProjectsApi.get_response`,
`backend/pilot_mcp/api.py`): no route of the API waits, so no thread and no database connection of
the API is held for it. It holds until no turn of the conversation is in flight or `wait_ms` is
over, `WAIT_MS_DEFAULT`, 900000 (15 min), where the call gives none, and `WAIT_MS_MAX`, 3600000
(60 min), at most, a larger ask clamped and a negative one refused; 0 answers at once. Meanwhile it
asks `GET /api/conversations/<id>` where the conversation stands every `POLL_SECONDS`, 2 s, each
ask answered at once under a 20 s timeout, and once no turn is in flight, or the wait is over, reads
the reply once from `GET …/response`; a reply read `running` before the wait is over, a turn
started between the ask and the read, is waited on. Every `PROGRESS_SECONDS`, 30 s, read after an
ask, it reports progress on the call's own event stream, the seconds waited of the wait's, "Pilot's
turn is still running", so that a client that ends a call silent for 300 s, as Claude Code does,
keeps it; a caller that sends no `progressToken` is sent none. A caller that goes away ends the
held call with its transport, as the MCP SDK cancels a call in flight there. A held call cut
otherwise, by a restart of a proxy or of Pilot, is called again, and the reply says where the turn
stands.

**The words are the outside's.** A session anywhere in the fleet reads the surface, so every tool's
description names "project(s) Pilot manages" before its first comma, and no word of the surface,
its instructions, its descriptions, its parameters or its answers, names the brain, the store, the
record or the tree (`TestTheProjectsSurface`). What the tools do not say, the map of a project's
folder and which file answers which question, is the skill `kubecoder:pilot-usage` in
KubeCoderConfig's `kubecoder` plugin, kept as the tree and the tools are
([`slice-doc-plan.md`](slice-doc-plan.md)).

**Reaching it.** The surface is at `https://<mcp.host>/mcp/projects`, `pilot-mcp.home` on production
and `pilot-dev-mcp.home` on dev ([`deployment.md`](deployment.md)). A session reaches it through
the fleet's shared `~/.claude.json`, whose entry is the operator's to write: production's surface
unless the environment's `PILOT_PROJECTS_URL` names dev's, the environment's `PILOT_PROJECTS_TOKEN`
as its bearer, and the two caller headers from the environment's id and its session's name. Pilot's
own sessions keep it beside their own server, since Pilot leaves `strictMcpConfig` unset (above).

## Testing it

The server is pinned in `backend/tests/pilot_mcp/`: a real MCP client drives the app in process
(`backend/tests/support/pilot_mcp.py`), its API calls answered by the test app's own routes in the
test's session, and `test_main.py` runs `python -m pilot_mcp` as a process, with the projects
surface's settings and without them. The projects surface is `TestTheProjectsSurface` and
`TestTheProjectsDoor` in `test_server.py`, each tool's served schema and words `PROJECTS_SURFACE`
there, and its tools `TestListProjects` to `TestGetResponse` in `test_tools.py`, a held
`get_response` on the API client's clock, the suite's `SteppedClock`
(`backend/tests/support/pilot_mcp.py`), whose sleep takes no time, through the OIDC app's gate under a token the fake endpoint, `TokenEndpoint`,
signs with the suite's key; the credential is `test_credential.py`, the settings `test_config.py`,
and the tree's routes `tests/api/test_tree.py` and `tests/services/test_tree_read_service.py`. The injection is
`tests/services/test_pilot_server.py`, with the creates in `test_session_start_service.py` and
`test_relay_service.py`, whose `_services(..., mcp_url=)` and `_relay_service(..., mcp_url=)` build
services that inject; the suite's default settings set no URL, so other creates carry neither.
`TestAScriptsCall` (`tests/pilot_mcp/test_server.py`) pins a script's lone `tools/call` as the
transport admits it. The routes are `tests/api/test_pilot_work.py`, whose
`test_the_surface_is_five_routes_outside_the_api` holds the blueprint's rules, and `tests/services/test_pilot_work_service.py`, the brain's
`tests/api/test_pilot_store.py`, whose `test_the_surface_is_eight_routes_outside_the_api` holds
its blueprint's rules, and `tests/services/test_pilot_store_service.py`, each tool's served schema
`STORE_SURFACE` in `tests/pilot_mcp/test_server.py`, the scope
`tests/services/test_session_scope.py`, the effects `tests/services/test_effect_service.py`; the
copies `tests/engine/test_attachments.py`. The fake controller serves the file routes
([`controller.md`](controller.md)), and the record's testing routes `POST
/api/testing/items/<id>/registrations`, `…/worker-attachments`, `…/progress` and `…/debrief`
register a document, attach a file, replace the list of steps and give the debrief as the worker's
tools do, and `…/writer-questions` asks a document's writer as the pass does
([`projects.md`](projects.md)). `frontend/tests/infrastructure/nginx.spec.ts` pins that the UI's
nginx forwards no path under `/tools/`, whatever its extension.
