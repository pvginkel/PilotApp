# The collection

Pilot's record holds the facts of the Claude Code transcripts on the fleet's home, a main thread's
and a sub-agent's alike, as a collector reads them off their files and publishes them, one
transcript a call. A collector calls one door of Pilot's, under a bearer of its own; what it
publishes lands in the tables of [`record.md`](record.md#the-tables), and a group of work
done before Pilot that a transcript's label names stands in the record as an adopted project.
Nothing of a transcript's text is published: its facts alone, its sizes, times, counts and codes.
No key of those tables reaches a person or a project's members, so a conversation is open to
everyone signed in, the operator's own sessions included.

## The door

**`POST /api/collector/publications`** takes one transcript's publication and writes it in the
request's transaction (`backend/app/api/collector.py`, `PublicationService.publish` in
`backend/app/services/publication_service.py`). The route is registered on the app, not on the
API blueprint, so the OIDC gate never sees it: the caller is a collector, which signs in to
nothing ([`sign-in.md`](sign-in.md)). Every call passes `PublicationService.admit` first, the
blueprint's `before_request`:

- **The bearer.** `Authorization: Bearer <token>`, the setting `COLLECTOR_TOKEN`, compared in
  constant time. While the setting is empty every call is refused.
- **The protocol version.** The call names the version it speaks in `X-Pilot-Collector-Protocol`;
  the server takes `COLLECTOR_PROTOCOL_MIN` to `COLLECTOR_PROTOCOL_MAX`, version 1 alone today. A
  change to a request or response shape of the collector's routes bumps the maximum, and the
  minimum with it where the server cannot serve the old collector.

The bearer is asked for before the version, and both before the body is read. Each answer is the
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

## A publication

One call is one transcript (`PublicationSchema`, `backend/app/schemas/publication.py`): Claude
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
boundary's, and the call carries every Launch, Prompt, Compaction and Call Pilot holds from there
on and no Call or Tool Call Pilot holds before. So an appended write removes nothing but what
hangs on a Call or a Prompt it carries again.

**What Pilot first meets.** An Environment the call names that Pilot has no row for is written
named by its id, until the fleet stream reports it ([`controller.md`](controller.md)); a
Repository by its checkout's name; a Component Version with its release time, which a later call
that gives one sets and one that gives none leaves; a reference code with the code as its name, a
Tool with the `mcp_server` the call gives and an Event Kind with its `is_error`. A reference code
Pilot holds stands as it is, whatever a later call says of it. `collected_at` is the server's clock
as it takes the call.

**A sub-agent's thread** is held with no main thread until its main thread is published, and
joined to it then, whichever comes first. Its `spawned_by` is held on its row as the name of its
spawning call, and the thread is joined to the Tool Call of that `tool_use_id` once exactly one
other thread of its conversation holds one. A spawning Tool Call that goes empties the join and
keeps the name, so the thread is joined again when a later publication brings the call back.

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
  `project.md`, the group's name its title and its summary its body. It has no handbook, no plan,
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
`recipe-box`, with a sub-agent, `counting`, an API error and a compaction; `gears` is Ada's, run by
hand on no project, with a rewind and a miss past the cache's lifetime, and names the group
`bike-log-first-rides`. The model names are the public ones and everything else is invented.
`Builder(SCENARIO, until)` lays the scenario's times back from `until`: its `publications()` are
each thread's whole call as a JSON object, a main thread before its sub-agents, and its `turns()`
the Turns of Pilot's. A conversation's ids are drawn from the scenario's and the session's names,
the same in every build.

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

**The guards.** `test_the_scenario_has_no_word_of_the_workflow`
(`backend/packages/pilot-scenario/tests/test_scenario.py`) fails on a word of the workflow,
`slice`, `stage` or `phase`, in any string of the scenario. `backend/tests/test_no_transcript_file.py`
fails on a transcript's file in the tree, a `.jsonl` file or one holding a line that carries
`sessionId` and `parentUuid`, read from the repository's root, the folders no commit holds aside:
a transcript in a test is generated when the suite runs, and the six invented stream fixtures of
`backend/tests/fixtures/raw/`, a turn's events as the controller relays them, are the one kind of
JSON Lines file the tree holds.

The door is pinned in `backend/tests/api/test_collector.py`, the write in
`tests/services/test_publication_service.py`, the call's shape in `tests/schemas/test_publication.py`,
the placement in `tests/services/test_launch_placement.py`, the adoption in
`tests/services/test_adoption_service.py`, the load in `tests/services/test_scenario_service.py`
and the builder in the package's `tests/test_builder.py`. `tests/support/publications.py` makes a
call (`whole()`, `sub_agent()`, `appended()`, `collector_headers()`), `tests/support/transcripts.py`
the rows, and `writes()` in `tests/support/database.py` counts the rows a block writes, by table.
The adopted project's row and head are pinned in `frontend/tests/projects/adopted-project.spec.ts`.
The Playwright backends have no `COLLECTOR_TOKEN`, so the door refuses every call there.
