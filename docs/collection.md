# The collection

Pilot's record holds the facts of the Claude Code transcripts on the fleet's home, a main thread's
and a sub-agent's alike, as a collector reads them off their files and publishes them, one
transcript a call. The collector is a component of Pilot's own, a pod beside each stage's fleet's
home that walks it every 30 s ([`collector.md`](collector.md)). It calls one door of Pilot's, under a
bearer of its own; what it publishes lands in the tables of [`record.md`](record.md#the-tables),
and a group of work done before Pilot that a transcript's label names stands in the record as an
adopted project. Nothing of a transcript's text is published: its facts alone, its sizes, times,
counts and codes. Its text is the collector's to serve, to Pilot's backend alone, as the
conversation's reading ([`collector.md`](collector.md#the-reading)).
No key of those tables reaches a person or a project's members, so a conversation is open to
everyone signed in, the operator's own sessions included.

## The door

The collector's routes are three, under `/api/collector` (`backend/app/api/collector.py`):

- **`GET /api/collector/inventory`**, what Pilot holds, which a walk asks for as it starts
  ([below](#the-inventory));
- **`POST /api/collector/publications`**, one transcript's publication, written in the request's
  transaction (`PublicationService.publish` in `backend/app/services/publication_service.py`);
- **`POST /api/collector/walks`**, a walk's end, which a walk tells after its last publication
  ([below](#a-walks-end)).

Their blueprint is registered on the app, not on the API blueprint, so the OIDC gate never sees
them: the caller is a collector, which signs in to nothing ([`sign-in.md`](sign-in.md)). Every call
passes `PublicationService.admit` first, the blueprint's `before_request`:

- **The bearer.** `Authorization: Bearer <token>`, the setting `COLLECTOR_TOKEN`, compared in
  constant time. While the setting is empty every call is refused.
- **The protocol version.** The call names the version it speaks in `X-Pilot-Collector-Protocol`;
  the server takes `COLLECTOR_PROTOCOL_MIN` to `COLLECTOR_PROTOCOL_MAX`, version 1 alone today. A
  change to a request or response shape of the collector's routes bumps the maximum, and the
  minimum with it where the server cannot serve the old collector.

The bearer is asked for before the version, and both before the body is read. Past them the
inventory answers `200` and a walk's end `204`, with no other answer. A publication's answer is the
call's outcome, and every answer but `204` leaves the record as it was:

| Answer | When | Then |
|---|---|---|
| `204`, no body | Pilot holds the transcript as the call says | |
| `401` | the call does not carry the bearer, and every call while `COLLECTOR_TOKEN` is empty | no call of the collector's is taken until its bearer is the server's |
| `426` `{min, max}` | the version is outside the range, or the call names none | no call is taken until the collector speaks a version in the range |
| `400` | the call does not validate, every fault named at once | the same call is refused again; the collector's other transcripts are not |
| `409` `PUBLICATION_NOT_APPENDABLE` | an appended call does not continue what Pilot holds (below), the reasons in `error` | the collector publishes the transcript whole |
| `409` `TRANSCRIPT_NOT_ADOPTABLE` | the call names a `group` for a transcript a Session of Pilot's ran (below) | the same call is refused again, and the call without its `group` is taken |
| `409` `NO_SERVICE_USER` | the call names a `group` no project holds yet, and the stage has no service user to make its project | the same call is taken once the stage has one |
| `413` | the body is over `MAX_UPLOAD_SIZE_MB`, the app's cap on every request, 50 by default | the same call is refused again |

A `400` has two shapes: a body that is not the call's shape is answered by spectree with
Pydantic's list of errors, each with its `loc`; a call that contradicts itself or the record's
rules for a transcript is answered with the app's envelope, `code` `VALIDATION_FAILED`, its faults
joined in `error`. The count of the calls a whole publication lost is not on the wire: it is the
server's log line (below).

| Setting | Default | |
|---|---|---|
| `COLLECTOR_TOKEN` | empty | the collector's bearer, a secret; empty refuses every call of a collector's |
| `COLLECTOR_WALK_INTERVAL_SECONDS` | `30` | from one walk's start to the next one's, above 0; each inventory hands it to the collector |
| `COLLECTOR_SETTLING_SECONDS` | `600` | how long a transcript's file stands unchanged before its replay at rest, 0 or more; each inventory hands it over |

## The inventory

**`GET /api/collector/inventory`** answers `200` `{walk_interval_seconds, settling_seconds,
transcripts}`, in protocol version 1 (`InventorySchema` in `pilot_collection.inventory`,
`PublicationService.inventory`). It is every transcript Pilot holds, whole at every call, in one
read, ordered by `session_id`, a main thread before its sub-agents'. Each transcript is
`{session_id, agent_id, file_size, file_modified_at, replayed_size, collector}`. `agent_id` is null
on a main thread. `file_size`, `file_modified_at` and `collector`, the version's string, are its
last publication's, which an appended call's `builds_on` names. `file_modified_at` is as Pilot holds
it, to the microsecond. A transcript the home has and the inventory lacks, or holds at another size,
time or version, is one for the collector to publish. One whose `replayed_size` is short of its
`file_size`, its file unchanged for `settling_seconds`, is due its replay at rest, a whole
publication once ([`collector.md`](collector.md#the-walk)). The inventory names no `collected_at`.

## A walk's end

**`POST /api/collector/walks`**, with no body, stamps a Walk at that moment and answers `204`
(`WalkService.end`, `backend/app/services/walk_service.py`). The record keeps the latest 20 Walks,
`walks` (`id`, `ended_at`), pruned at each end. A walk's end that never arrives loses nothing: the
next compares against the last Walk kept. The collector's version is not kept with a Walk: a walk's
end that passed the gate spoke a version Pilot takes.

**Its event.** A walk wrote a row where a Transcript was collected since the Walk before it ended,
`collected_at` at or after that Walk's `ended_at`, or where no Walk ended before and the record
holds a Transcript: every publication Pilot takes writes its Transcript's row. Such a walk's end is
told to every person's connections once the call has committed, as one SSE event:
`collection_changed`, `{"as_of": "<the walk's end, UTC, to the microsecond>"}`
(`CollectionChangedSchema` in `backend/app/schemas/walk.py`, `EVENT_NAME` in `walk_service.py`),
sent to each person by subject as `conditions_changed` is. A walk that wrote nothing raises none, so
one walk raises one event however many transcripts it published. `latest_walk_end(db)` is the
latest Walk's end, how fresh the record's facts of the transcripts are.

**The readiness check** `collector`, in `/health/readyz`, is not critical: Pilot serves its record
without a collector, and a `503` would take the backend out of the Service the collector's own
calls come through. It is `disabled` while `COLLECTOR_TOKEN` is empty, "COLLECTOR_TOKEN is empty".
It is `error` before a first walk, "no walk of the collector's has ended", and once the latest
Walk ended more than two walk intervals ago, "the collector's latest walk ended at <UTC ISO time>,
more than <twice the interval> s before this check", 60 at the default. Otherwise it is `ok`, its `detail` "the collector's latest walk
ended at <UTC ISO time>". So a stage whose backend holds the bearer reads `degraded`, still `200`,
until its collector's first walk ends, and again once its walks stop for two intervals. Readyz
reuses a passing result for 30 s, so the time in `detail` can be that much older than the latest
walk. The check reads on a session of its own under a 2 s `statement_timeout`.

## A publication

One call is one transcript (`PublicationSchema` in `pilot_collection.publication`,
`backend/packages/pilot-collection/`, the shapes the collector and the backend share): Claude
Code's `session_id` of its main thread and, on a sub-agent's thread, its `agent_id`; the file's
size and time; the collector's version that read it; the directory it was first launched in, the
name of the checkout that holds it, and on a main thread the id of the environment it ran in,
each where the file shows it; a sub-agent's `agent_type`, `description` and `spawned_by`, the
`tool_use_id` of the call that started it; a main thread's `group`; then its Launches with the
versions each ran with and the Prompts each received with their Hook Runs, its Compactions, and
its Calls, each with its five token counts, its Tool Calls, its Events and its Context Parts, all
in the file's order. Every model refuses a field it does not know, a time names its offset, and a
file's size is at most 2^53 - 1, the largest integer every JSON reader takes exactly.

A row is named by what the file names it by: a Call by its `message_id`, its `predecessor` by that
Call's, a Tool Call by its `tool_use_id`, and a Prompt and a Compaction a Call follows by their
place among the transcript's, from 1, the Prompts counted through the Launches in order. A Call's
`position` is its place among the transcript's Calls.

**A whole call** is the file as it stands. Pilot then holds what the call says of the transcript
and nothing else, and writes only the rows that differ: a republish of an unchanged file writes
the Transcript's row alone. A row keeps its identity, and whatever Pilot set on it, wherever the
call names the same fact again: a Call by its `message_id`, a Tool Call by its `tool_use_id`, a
Launch by its place among the transcript's Launches, a Prompt, a Hook Run, a Compaction, an Event
and a Context Part by their place under their parent. What Pilot holds that the call no longer
names goes, with what hangs on it: a Call of another `message_id` with its Tool Calls, Events and
Context Parts, a Launch past the call's last with its versions, Prompts and Hook Runs, and every
other row past the last under its parent. Pilot follows the file, a rewritten one included, and
a whole call that loses Calls is logged at `WARNING`, "Transcript <session_id>[/<agent_id>] no
longer has <n> of the calls Pilot held". No call removes a Transcript, an Environment, a
Repository, a Component Version or a reference code: a transcript whose file is gone from the home
stays as Pilot holds it. After a whole call the Transcript's `replayed_size` is its `file_size`.

**An appended call**, one with `appended`, is a file that grew and nothing else. `builds_on` names
the file's size, its time and the collector's version as the publication before it read them, and
`boundary` where what the call carries starts: `call`, the position of its first Call, and
`launch`, `prompt` and `compaction`, the place of its first Launch, of that Launch's first Prompt
and of its first Compaction among the transcript's, each the place the file's next would take
where the call carries none. From those places on Pilot then holds what the call carries, written
as a whole call's rows are, a held Launch the call names again keeping its row and taking its
end; nothing before them is read as the call's or written, and `replayed_size` stays. Its file is
larger than the one it builds on, or the call is a `400`. It is a `409`
`PUBLICATION_NOT_APPENDABLE` unless it continues what Pilot holds: Pilot holds the transcript at
the size, time and collector's version it builds on, holds a row at every place before the
boundary's, the call carries every Launch, Prompt, Compaction and Call Pilot holds from there
on and no Call or Tool Call Pilot holds before, and the call's first Launch, Prompt and Compaction
are the rows Pilot holds at the boundary's places, where it holds one there, told by their
`started_at`, `received_at` and `at` as instants. A call that names another reads, among its
reasons, "the boundary's `launch` is 2, where Pilot holds a launch begun at <UTC ISO time>, and the
call's first was begun at <UTC ISO time>", and the same for `prompt` with "received" and
`compaction` with "made". So an appended write removes nothing but what hangs on a Call or a Prompt
it carries again, and a time the collector reads must read the same at every walk of a file that
only grew, or each growth costs a whole publication.

**The replay at rest** is a whole call of the file Pilot holds, at the `file_size`,
`file_modified_at` and collector's version Pilot holds, part of it taken in appended calls since
the last whole one: `replayed_size` short of `file_size`. Pilot holds no boundary, so a row the
replay writes that differs from what Pilot held is logged at `WARNING`, on
`app.services.publication_service`, with how much of the file was taken in parts and the rows it
wrote by table: "The replay at rest of transcript <session_id>[/<agent_id>], 12888 of its 61000
bytes taken in parts, wrote rows that differ from what Pilot held: calls 1, tool_calls 1". The line
counts the rows changed, added and removed under the Transcript; a row that goes with the one it
hangs on is not counted, nor a Launch's placing under its Session. A whole call of a file that
changed, or read under another version, logs nothing.

**What Pilot first meets.** An Environment the call names that Pilot has no row for is written as
the fleet stream reports it, its name, exemption and state with it. One the stream has not given,
and any while the stream is down, is written named by its id, not exempt and with no
`last_seen_at`: a row no report of the controller's has reached, which the stream's next report and
Pilot's first touch of the environment both make the controller's (D260,
[`controller.md`](controller.md#environments-on-demand)); a Repository by its checkout's name; a Component Version with its release time, which a later call
that gives one sets and one that gives none leaves; a reference code with the code as its name, a
Tool with the `mcp_server` the call gives and an Event Kind with its `is_error`. A reference code
Pilot holds stands as it is, whatever a later call says of it. `collected_at` is the server's clock
as it takes the call.

**A sub-agent's thread** is held with no main thread until its main thread is published, and
joined to it then, whichever comes first. Its `spawned_by` is held on its row as the name of its
spawning call, and the thread is joined to the Tool Call of that `tool_use_id` once exactly one
other thread of its conversation holds one. A spawning Tool Call that goes empties the join and
keeps the name, so the thread is joined again when a later publication brings the call back. The
collector reads the name off the sub-agent's record and publishes no fact of a fork's copies of its
parent's lines, so a call a fork copied is held in its parent's thread alone
([`collector.md`](collector.md#a-transcripts-facts)).

**The conversation's turn.** Publications of one conversation, its main thread's and its
sub-agents', take turns under a transaction's advisory lock, `(247, <a key drawn from the
session_id>)` (`conversation_turn` in `backend/app/services/launch_placement.py`), which the relay
takes too when a Session names the conversation (below).

## A launch of Pilot's

A Launch a Turn of Pilot's started is placed under its Session and that Turn
(`place_launches`, `launch_placement.py`): among the Sessions whose `conversation_id` is the
transcript's `session_id`, under the one whose Turn was sent last at or before the Launch's start,
and under that Turn where it was in flight then. A Launch started after that Turn's end has the
Session and no Turn; one started before every Turn of the conversation has neither. The two facts
arrive in either order, each in a transaction of its own, and both writers place under the
conversation's turn: every publication of a main thread as its write ends, whole or appended, and
the relay when a Session's first line gives it its `conversation_id`
([`sessions.md`](sessions.md)). A Launch is placed once and keeps what it was placed under; a
Launch the file lost goes with it. A transcript is on a project through its Launches' Sessions and
holds no project of its own. A Launch a driver started under a loop session continues a
transcript no Session's `conversation_id` names, and is not placed.

## The adopted project

A main thread's `group`, `{key, name, summary}`, is the workflow's label of the group of work run
before Pilot that the transcript belongs to: its key never changes, and its name and summary are
as they now stand. The transcript is then adopted by the group's adopted project, and by none
where its call names no group, whole or appended: the label is the call's
(`backend/app/services/adoption_service.py`, `AdoptionService.adopt`).

- **Its birth.** Pilot makes the project the first time a publication names the group: in the
  state `adopted`, archived, its `adopted_group` the key, with no slug and no member, created by the
  stage's service user, the first made where there are several, who performs its one transition,
  `adopted` ([`sign-in.md`](sign-in.md#the-service-user)). Its one document is its draft,
  `project.md`, the group's name its title and its summary its body. It has no handbook, no journal, no plan,
  no chat and no item, and it runs no Session.
- **Found again.** A later publication finds the project by the key, under the group's advisory
  lock, `(253, <a key drawn from the group's key>)`, taken after the conversation's turn and never
  before it, so that two publications that first name a group at once make one project. A changed
  name or summary publishes its draft again as the group now stands, which renames the project and
  cuts no version. Nothing removes one.
- **Its refusals**, each before anything is written: a `group` on a sub-agent's thread, a name that
  is not one line or a summary that holds an ask or does not parse, `400`; no project holding the
  group on a stage with no service user, `409` `NO_SERVICE_USER`; a group on a transcript a Session
  of Pilot's ran, `409` `TRANSCRIPT_NOT_ADOPTABLE`. A Session ran the transcript where one runs a
  Launch of it, or names its conversation while no project has adopted it. One adopted before a
  Session named it stays adopted, and its Launches stay off that Session, the server logging it at
  each placement; once a call names no group, the same write places them.

Every transition is refused on an adopted project, Bring back included, and so are Join and Leave;
no request makes an `adopted` transition ([`projects.md`](projects.md)). It is listed with the
archived projects, its row reading "Adopted", and its head has no menu. Being archived, its folder
is not in the store's tree ([`projection.md`](projection.md)).

## Testing it

**The scenario.** `backend/packages/pilot-scenario/`, the package `pilot_scenario` beside the block
DSL's, holds Pilot's one invented scenario and the builder that turns it into what a layer reads,
and imports nothing but the standard library, so that every layer's suite can take it. The backend
depends on it by path, editable, the image installs it, and the backend's pytest runs its tests,
as it does the DSL's ([`block-dsl.md`](block-dsl.md#the-package)). `SCENARIO`, named `supper`, is
in the dev seed's world, the people `ada` and `ben` and the projects `recipe-box` and `bike-log`,
with kinds of work of its own, `errand` and `leg`. Its session `halving` is a Turn of Pilot's on
`recipe-box`, run with the plugin `pantry`, whose skill it loads, with a sub-agent, `counting`, an
API error its request is sent again after, a compaction and a Stop hook; `counting` asks for one
model and another answers, a hook and a permission rule each deny it a call, and its last answer
runs out of tokens. `gears` is Ada's, run by hand on no project, with an instruction file loaded
mid-run, a rewind, a miss past the cache's lifetime, an edit she turns down and two Stop hooks, one
failing, and names the group `bike-log-first-rides`. The model names are the public ones and
everything else is invented. `Builder(SCENARIO, until)` lays the scenario's times back from
`until`: its `publications()` are each thread's whole call as a JSON object, a main thread before
its sub-agents, and its `turns()` the Turns of Pilot's. A conversation's ids are drawn from the
scenario's and the session's names, the same in every build.

**As files.** `files()` gives the scenario as files of a home, each a `HomeFile` with its path from
the home's folder, its bytes and its time. They are each thread's transcript in Claude Code's line
shapes (`pilot_scenario.transcript`, [`collector.md`](collector.md#a-transcripts-lines)), in the
publications' order, each followed by the outputs its results say were saved to disk, under
`<session_id>/tool-results/`, and a sub-agent's by its record, `agent-<agent_id>.meta.json`, so a
reader of every file as a transcript takes the `.jsonl` ones alone. `write(home)` puts them under
`home`, the folder that holds `projects`, each at the time its publication gives. A collector's
reading of them is what `publications()` says, but for the `group`, the labeller's, which no line
carries ([`collector.md`](collector.md#testing-it)). `_facts` in the package's
`tests/test_transcript.py` cuts a publication to what its file's lines and record say, and `_read`
there is an independent reading of the files. The builder's times are cut to the millisecond, as a
line's `timestamp` is. `halving`'s brief is an `sdk` prompt and `gears`' prompts are `typed`;
`gears` interrupts a Bash call; and two results, the sub-agent's grep and the MCP call, are outputs
saved to disk, one in each of Claude Code's wordings. The lines the facts are read off include a
Call's request line and the line of the shape it sent; a Launch's instruction files and what was
injected before a Call; a compaction's boundary and summary; a failed attempt's request and its
error; a denied call's result in Claude Code's words; a Prompt's Stop hooks' summary and a failing
hook's error; and a plugin's skill's body under the plugin's cache at its Launch's version.
The files are generated when a suite runs and never committed.

**Its load.** `POST /api/testing/scenarios` `{projects: {"recipe-box": <a project's id>}}`, one of
the record's testing routes ([`projects.md`](projects.md#testing-it)), loads it, its last moment
the transaction's `now()` (`ScenarioService.load`, `backend/app/services/scenario_service.py`): the
Session of kind `work` and the Turn of Pilot's that ran `halving`, on the project given, ended at
the Turn's end, with no work item, then each thread published whole through
`PublicationService.publish`. It answers `201` `{transcripts}`, in the builder's order, `halving`,
`counting`, `gears`, each `{session_id, agent_id, adopted_by}`, `adopted_by` the adopted project's
`{id, name}` or null. A second load replaces the first: it finds the Session of that
`conversation_id` again and publishes the same transcripts whole, so the record holds the scenario
once, as it was loaded last, and the group's project is found by its key. Another set of projects
than the scenario's that a Turn of Pilot's is on is a `400`, an unknown project a `404`, and a stage
with no service user a `409` `NO_SERVICE_USER`, each writing nothing. A Playwright spec makes the
service user with `people.serviceUser()` and loads it with `projects.loadScenario(id)`
(`frontend/tests/support/`); a backend test takes the `service_user` fixture.

**A walk's end.** `POST /api/testing/walks`, with no body, for a signed-in editor on every stage but
prd, as the record's testing routes are, ends a walk through the same service and answers `201`
`{ended_at, announced}`, `announced` whether its `collection_changed` is sent. A spec that loaded a
scenario posts it and waits for the event; a second post with no load between raises none. On a
stage with a collector, the collector's own walk's end can come between a load and the post. That
end then sends the event, and the post answers `announced: false` and sends none, so a check there
holds the live stream before it loads and takes the event of either end.

**The guards.** `test_the_scenario_has_no_word_of_the_workflow`
(`backend/packages/pilot-scenario/tests/test_scenario.py`) fails on a word of the workflow,
`slice`, `stage` or `phase`, in any string of the scenario. `backend/tests/test_no_transcript_file.py`
fails on a transcript's file in the tree, a `.jsonl` file or one holding a line that carries
`sessionId` and `parentUuid`, read from the repository's root, the folders no commit holds aside:
a transcript in a test is generated when the suite runs, and the six invented stream fixtures of
`backend/tests/fixtures/raw/`, a turn's events as the controller relays them, are the one kind of
JSON Lines file the tree holds.

The door and its three routes are pinned in `backend/tests/api/test_collector.py`, the write in
`tests/services/test_publication_service.py`, the call's shape in `tests/schemas/test_publication.py`,
on the package's import, the walk's end, its event and the readiness check in
`tests/services/test_walk_service.py`, the Walk's revision in `tests/migrations/test_0050_walks.py`,
the placement in `tests/services/test_launch_placement.py`, the adoption in
`tests/services/test_adoption_service.py`, the load in `tests/services/test_scenario_service.py`
and the walks' testing route in `tests/api/test_testing_record.py`. The package `pilot-collection`'s
`tests/test_package.py` pins that it stands without the app, and the builder is pinned in
`pilot-scenario`'s `tests/test_builder.py` and its files in `tests/test_transcript.py`. A collector's
walk against these routes is `tests/collector/test_walk.py` ([`collector.md`](collector.md#testing-it)).
`tests/support/publications.py` makes a call (`whole()`, `sub_agent()`, `appended()`,
`collector_headers()`), `tests/support/transcripts.py` the rows, and `writes()` in
`tests/support/database.py` counts the rows a block writes, by table. The adopted project's row and
head are pinned in `frontend/tests/projects/adopted-project.spec.ts`. The Playwright backends have
no `COLLECTOR_TOKEN` and no collector, so the door refuses every call there.
