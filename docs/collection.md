# The collection

Pilot's record holds the facts of the Claude Code transcripts on the fleet's home, a main thread's
and a sub-agent's alike, and the workflow's labels of them, as a collector reads the facts off their
files, has the workflow's labeller label them, and publishes both, one transcript a call. The
collector is a component of Pilot's own, a pod beside each stage's fleet's home that walks it every
30 s ([`collector.md`](collector.md)). It calls one door of Pilot's, under a bearer of its own; what
it publishes lands in the tables of [`record.md`](record.md#the-tables), a group of work done before
Pilot that a transcript's labels name stands in the record as an adopted project, and a commit a
call made gains its lines from its repository's history. Nothing of a transcript's text is
published: its facts and its labels alone, its sizes, times, counts and codes. Its text is the
collector's to serve, to Pilot's backend alone, as the conversation's reading
([`collector.md`](collector.md#the-reading)). Pilot's code names none of the labeller's values: the
labeller declares its lists, and Pilot stores them as they come.
No key of those tables reaches a person or a project's members, so a conversation is open to
everyone signed in, the operator's own sessions included.

## The door

The collector's routes are eight, under `/api/collector` (`backend/app/api/collector.py`):

- **`GET /api/collector/inventory`**, what Pilot holds, which a walk asks for as it starts
  ([below](#the-inventory));
- **`POST /api/collector/publications`**, one transcript's publication, written in the request's
  transaction (`PublicationService.publish` in `backend/app/services/publication_service.py`);
- **`PUT /api/collector/vocabularies`**, the labeller's lists ([below](#the-labellers-vocabularies));
- **`GET /api/collector/repositories`** and **`POST /api/collector/commits`**, the cursor of the
  repositories' histories and one read of them ([below](#a-repositorys-commits));
- **`GET /api/collector/files`** and **`PUT /api/collector/classes`**, the Files and the classes the
  labeller gives them ([below](#the-files-classes));
- **`POST /api/collector/walks`**, a walk's end, which a walk tells after its last publication
  ([below](#a-walks-end)).

Their blueprint is registered on the app, not on the API blueprint, so the OIDC gate never sees
them: the caller is a collector, which signs in to nothing ([`sign-in.md`](sign-in.md)). Every call
passes `PublicationService.admit` first, the blueprint's `before_request`:

- **The bearer.** `Authorization: Bearer <token>`, the setting `COLLECTOR_TOKEN`, compared in
  constant time. While the setting is empty every call is refused.
- **The protocol version.** The call names the version it speaks in `X-Pilot-Collector-Protocol`;
  the server takes `COLLECTOR_PROTOCOL_MIN` to `COLLECTOR_PROTOCOL_MAX`, 1 to 2 today, and the
  collector speaks 2. A collector of version 1 sends no labelling, which the server takes as a call
  with none. A change to a request or response shape of the collector's routes bumps the maximum,
  and the minimum with it where the server cannot serve the old collector.

The bearer is asked for before the version, and both before the body is read. Past them the
inventory and the repositories answer `200` and a walk's end `204`, with no other answer. A call
that writes, a publication, a declaration, a read or a classing, is one transaction, its answer the
call's outcome, and every answer but `204` leaves the record as it was. A publication's are:

| Answer | When | Then |
|---|---|---|
| `204`, no body | Pilot holds the transcript as the call says | |
| `401` | the call does not carry the bearer, and every call while `COLLECTOR_TOKEN` is empty | no call of the collector's is taken until its bearer is the server's |
| `426` `{min, max}` | the version is outside the range, or the call names none | no call is taken until the collector speaks a version in the range |
| `400` | the call does not validate, every fault named at once | the same call is refused again; the collector's other transcripts are not |
| `409` `PUBLICATION_NOT_APPENDABLE` | an appended call does not continue what Pilot holds, its facts or its labels (below), the reasons in `error` | the collector publishes the transcript whole |
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
transcripts, conversations}` (`InventorySchema` in `pilot_collection.inventory`,
`PublicationService.inventory`), whole at every call. `transcripts` is every transcript Pilot
holds, in one read, ordered by `session_id`, a main thread before its sub-agents'. Each transcript is
`{session_id, agent_id, file_size, file_modified_at, replayed_size, collector, labeller, stamp}`.
`agent_id` is null on a main thread. `file_size`, `file_modified_at` and `collector`, the version's
string, are its last publication's, which an appended call's `builds_on` names. `file_modified_at`
is as Pilot holds it, to the microsecond. `labeller` is the labeller's version its labels were
written under, none while no labelling was published for it, and `stamp` the stamp handed back with
them, none where its last publication carried no labelling ([below](#the-labels)). A transcript the
home has and the inventory lacks, or holds at another size, time or version, is one for the
collector to publish. One whose `replayed_size` is short of its `file_size`, its file unchanged for
`settling_seconds`, is due its replay at rest, a whole publication once
([`collector.md`](collector.md#the-walk)). The inventory names no `collected_at`.

`conversations` is what the labeller is handed with each conversation a Session of Pilot's ran,
collected or not, by `session_id` (`backend/app/services/labeller_context.py`): `{session_id,
sessions, documents}`. Its Sessions come in `created_at` order, each `{id, kind, created_at, brief,
repo, clarification, holds, turns}`: `brief` is the first 400 characters of its first Turn no person
wrote, `repo` its Work's repository, else its project's, `clarification` whether its Work is a
clarification run, `holds` its Holds `{kind, started_at, ended_at}` in the order they started, and
`turns` its Turns `{started_at, cause}` in the order sent. Its Documents, `{id, session,
source_path}`, in the order they were made, are the prose items' documents its Sessions created; a
project's draft, handbook and journal are not handed. The labeller's stamp covers what is handed and
its order, so every list is present at every walk, empty where Pilot holds nothing, and each is read
in an order its rows' own columns fix. A conversation that only a step names, and that no Session of
Pilot's ran, is not handed. The inventory's read is five statements however much the record holds.

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
`tool_use_id` of the call that started it; its `labelling`, the labeller's labels of it, and with
it a main thread's `group` ([below](#the-labels)); then its Launches with the versions each ran with
and the Prompts each received with their Hook Runs, its Compactions, and its Calls, each with its
five token counts, its Tool Calls, each with the commits it made and the files it edited
([below](#commits-and-file-edits)), its Events and its Context Parts, all in the file's order. Every
model refuses a field it does not know, a time names its offset, and a file's size is at most
2^53 - 1, the largest integer every JSON reader takes exactly.

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
Repository, a File, a Component Version or a reference code: a transcript whose file is gone from
the home stays as Pilot holds it. After a whole call the Transcript's `replayed_size` is its
`file_size`.

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
`file_modified_at` and collector's version Pilot holds, part of it taken in appended calls since the
last whole one: `replayed_size` short of `file_size`. Pilot holds no boundary, so a row the replay
writes that differs from what Pilot held is logged at `WARNING`, on
`app.services.publication_service`, with how much of the file was taken in parts and the rows it
wrote by table: "The replay at rest of transcript <session_id>[/<agent_id>], 12888 of its 61000
bytes taken in parts, wrote rows that differ from what Pilot held: calls 1, tool_calls 1". The line
counts the rows changed, added and removed under the Transcript; a row that goes with the one it
hangs on is not counted, nor a Launch's placing under its Session. Where the call's labelling is
under the labeller's version and stamp Pilot held, the labels it changed follow, "…, and labels that
differ: segments 1", or "labels that differ from what Pilot held: …" where no fact differs: under
another version or stamp what the labels improve is no replay's difference. A whole call of a file
that changed, or read under another version, logs nothing.

**What Pilot first meets.** An Environment the call names that Pilot has no row for is written as
the fleet stream reports it, its name, exemption and state with it. One the stream has not given,
and any while the stream is down, is written named by its id, not exempt and with no
`last_seen_at`: a row no report of the controller's has reached, which the stream's next report and
Pilot's first touch of the environment both make the controller's (D260,
[`controller.md`](controller.md#environments-on-demand)); a Repository by its checkout's name, every
one the call names, the transcript's and its commits' and edits', met in one write; a Component
Version with its release time, which a later call
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
takes too when a Session names the conversation, and a work item's `set_progress` when a step newly
names it (below).

## The labeller's vocabularies

**`PUT /api/collector/vocabularies`** takes the labeller's lists whole, as the labeller declares
them (`VocabulariesSchema` in `pilot_collection.vocabularies`, `VocabularyService.declare` in
`backend/app/services/vocabulary_service.py`): `version`, the labeller's own version that declared
them; `lists`, one field per list a label takes its value from, named after the reference entity it
fills, `work_unit_kind`, `unit_outcome`, `rework_kind`, `unit_measure`, `segment_kind`,
`wait_cause`, `call_class`, `avoidable_kind`, `command_class`, `build_result`, `file_class`,
`tool_effect_kind`, `rule`, `ask_category`, `event_kind` and `context_part_kind`; and `nesting`, each
pairing `{inner, outer}` of Work Unit Kinds whose units of `inner` may sit in units of `outer`. A
value is `{code, name, description, position}`, the line that says what it is and its place in its
list from 1, with the fact about its category where its entity has one: a Unit Measure's `unit`,
what it counts; a File Class's `counted`, whether its Files are written work the figures count; a
Rule's `home`, the file that states it; an Event Kind's `is_error`. A list the record has no place
for is no part of the call, so one that names it is a `400`.

After its `204` Pilot holds every list and every nesting as declared, only the values that differ
written. A value the call no longer declares is removed where no row names it, and kept with no
`position` where one does, so a value its list declares now is one with a place; a nesting goes by
the same rule, and a kind whose nesting goes goes in the same call. Of Event Kind and Context Part
Kind the labeller's values are those with a `description`, and the collector's stand as they are: a
code the collector met that the labeller declares takes the labeller's words. Its faults, all named
at once in a `400`'s `error`: a code or a `position` given twice in a list, an Event Kind another
table records, and a nesting given twice or naming a Work Unit Kind the call does not declare. A
`413` is a body over the app's cap. Where a row was written the dashboard's catalogue is dropped
after the commit ([`dashboard.md`](dashboard.md#the-catalogue)). The labeller's version is not
stored with the lists; it is logged with what was written, at `INFO`: "Took the vocabularies of the
labeller 1.0.1: 3 values written, 0 nestings written or removed, 0 values removed and 1 kept with no
place, no longer declared".

## The labels

A publication's `labelling` (`PublishedLabellingSchema` in `pilot_collection.publication`) is the
labeller's answer for its transcript: `version`, the labeller's own version, which is not its
plugin's; `stamp`, its stamp of all it read for the transcript besides the file, the run records,
what Pilot handed with the conversation and what it took from another transcript of the
conversation; `labels`, the transcript's own; and `units`, `test_suites` and `ci_builds`: every Work
Unit the labels name and every one above it, each after the units it sits in and is occasioned by,
every Test Suite a Test Run names and every CI Build a CI Wait names. A label names its row as both
sides compute it: a Launch by its place, `n`, a Call by its `message_id`, a Segment by its
`position` from 1, a Tool Call by its `tool_use_id`, an Event and a Context Part by the Call they are
held on, a Document by the id the inventory handed. Its lists:

- `launches`, the Work Unit each carried out;
- `calls`, each Call's Segment, Call Class, Avoidable Kind and Wait Cause;
- `segments`, each `{position, kind}`, a run of consecutive Calls of one Segment Kind;
- `tool_calls`, each Tool Call's Command Class, its effect, `effect_kind` with its `effect_subject`,
  and the Rules it breached;
- `events` and `context_parts`, the labeller's own, `{call, kind, at, detail}` and `{call, kind,
  name, characters}`;
- `test_runs`, each a Tool Call's or a Work Unit's run of one suite, with its failures;
- `ci_waits`, each Tool Call's wait on a CI Build, by its job and number;
- `documents`, each handed Document's Ask Category, none among them.

A main thread's `group` rides with a labelling alone ([below](#the-adopted-project)).

**A whole call's labelling** replaces every label Pilot holds of the transcript together, and writes
only the rows that differ (`LabelWrite.write`, `backend/app/services/label_write.py`), in the
publication's transaction after its facts: the label columns of its Launches, Calls and Tool Calls,
its Segments, Rule Breaches, labelled Events and Context Parts, Test Runs with their Test Failures,
CI Waits, and on a main thread its Documents' Ask Category. Work Units with their measures, Test
Suites, Tests and CI Builds are written by their keys and never removed: no one transcript's labels
own them. A labelled Event or Context Part keeps its row by its place among its Call's labelled ones,
and a Test Run by its place among its transcript's. The Transcript holds the version as
`labelled_under`, a version of the Component `labeller`, and the stamp as `records_stamp`.

**Facts and labels apart.** An Event or a Context Part is the collector's or the labeller's,
`labelled`, and a publication's facts are the collector's rows alone, so that its facts never remove
or overwrite a label, nor its labels a fact. They meet in one place, the carve (D266): a Call's
labelled Context Parts, a dispatch's digest sections among them, are sections of its opening prompt,
and Pilot stores the Call's first collector part of the kind `prompt` as what the collector counted
less the labelled parts, so that a first Call's parts add up to what it carried once. Labelled parts
that carry more than that prompt's characters, or that stand on a Call with no `prompt` part, are a
`400`; a call with no labelling is held to the labelled parts Pilot holds the same way.

**A call with no labelling**, one no labeller answered for, writes its facts and leaves every label
Pilot holds of the transcript as it stands, its adoption and `labelled_under` included, and its
stamp none, so that the labeller's next answer differs from it. It names no `group`, or is a `400`.

**An appended call's labelling** is the labeller's answer from the publication's own boundary on,
and replaces that alone: the Launches' labels from the boundary's Launch, the Segments from the
labelling's first, the Calls' from the boundary's Call with their Tool Calls', Rule Breaches,
labelled Events and Context Parts and CI Waits, the Test Runs of those Tool Calls, and, on every
answer, the Test Runs of the transcript's Work Units and its Documents' Ask Category; the rest
stands. It is no relabel: it continues the labels Pilot holds (`LabelWrite.gaps`), or the call is
the `409` `PUBLICATION_NOT_APPENDABLE`, its reasons among "Pilot holds its labels under no stamp",
"Pilot holds its labels under another stamp than the labelling's", "Pilot holds its labels under the
labeller's 1.2.0, of another major than the labelling's 2.0.0", and "the labelling's segments start
at 5, and Pilot holds the call before its boundary in segment 3": the labelling's first Segment is
the one the Call before the boundary falls in or the next, the first at a boundary on the first
Call, and none where the Call before falls in none. The Transcript then takes the labelling's
version, a newer minor or patch of the labeller's included, so that all its labels stand under one
stamp and one major (D292, [`collector.md`](collector.md#the-labeller)).

**Its faults**, all named at once in a `400`'s `error`. Against the call itself: a label of a
Launch, a Call or a Tool Call the call does not carry, an appended one's before its boundary among
them; a row labelled twice; Segments that do not run one after another over the Calls in their
order; a Test Run or a CI Wait naming a unit, a suite or a build the labelling does not give, or run
by both or neither of a Tool Call and a unit; a Document on a sub-agent's thread; units out of their
order. Against the record: a value no list holds now, "`call_class` `look`: no value the labeller
declares", so the labeller's vocabularies are declared before a label of them is published; a unit
placed in one whose kind no nesting pairs with its own; a Document Pilot does not hold.

A held Work Unit may take another kind under a later labelling. Another transcript's unit in it that
no nesting then lets sit there sits in none until its own labelling places it again.

## Commits and file edits

A Tool Call carries `commits`, each `{repository, subject, sha}`, a commit it made as its command and
its output show it, in the order its output shows them: the checkout's name, the message's first
line as git's `%s` gives it, and the hash as the call showed it, abbreviated or whole, none where
none showed ([`collector.md`](collector.md#a-transcripts-facts)). It carries `file_edits`, each
`{repository, path, lines_added, lines_removed}`, what a successful Edit or Write changed of a file a
Repository keeps, its path within that checkout. Both are facts of the Tool Call, written with the
publication's other facts, only the rows that differ (`CommitWrite`,
`backend/app/services/commit_write.py`). A Commit held so has no lines; a read of its Repository
completes it ([below](#a-repositorys-commits)). They go with a Tool Call the file no longer names,
but for a Commit a read completed, which stays, with no Tool Call once its call no longer names it.
An appended call writes no commit or edit of a Tool Call before its boundary. A File, a Repository's
and a path, is made the first time a File Edit or a read names it, and never removed.

A commit whose hash names a Commit another Tool Call holds is not held again: a Commit is made by
one Tool Call once, and the server logs it at `WARNING`, "Transcript <session_id>[/<agent_id>]: tool
call <tool_use_id> names the commit <sha> of <repository>, which Pilot holds as another's". One a
read gave first, a Commit no Tool Call holds, is tied to its Tool Call by the rule a read ties by,
whichever of the two arrived first. Its faults, each a `400`: a file edit of a call that is no
successful Edit or Write, one file edited twice by one call, and one commit's hash given twice in
the call.

## A repository's commits

A commit's lines are read from its repository's own history, which the collector keeps a clone of
([`collector.md`](collector.md#the-clones)), and Pilot is the cursor
(`RepositoryService`, `backend/app/services/repository_service.py`):

- **`GET /api/collector/repositories`** answers `200` `{repositories}` (`RepositoriesSchema` in
  `pilot_collection.repositories`): every Repository Pilot holds by name, `{name, read}`, `read`
  the whole hash of every Commit a read of it gave, in hash order. A commit of its history not in
  `read` is one Pilot lacks; a Repository with none is read whole.
- **`POST /api/collector/commits`** `{repository, read_at, commits}`, what one read gave: each
  commit `{sha, made_at, subject, files}`, its whole hash, its author's time, which a rebase keeps,
  its subject as `%s` gives it, and its lines per file, `{path, lines_added, lines_removed}`, none
  for a merge commit; `read_at`, when the lines were read. Its `204`: each commit Pilot does not
  hold as read completes the held Commit the tie gives it, which takes its whole hash, its
  `made_at`, its File Changes and `read_at` as its `lines_read_at`; one the tie gives none is a
  Commit no transcript made. A commit Pilot holds as read already changes nothing. A `400` is a
  Repository Pilot does not hold, a commit given twice, or a file one commit changes twice, and a
  `413` a body over the app's cap, so that a large read comes in several calls. Logged at `INFO`:
  "Read RecipeBox: 12 commits, 3 held already; of the 9 taken, 2 completed the commit of their call
  by its hash and 1 by its subject, and 6 no transcript made".

**The tie** (`tie` in `backend/app/services/commit_tie.py`) is one rule, whichever arrived first: a
read meets the Commits held from calls that no read completed, and a publication the read Commits
no Tool Call holds. A read commit completes the held one whose hash it starts with, the longest
held hash first; else the one whose subject it has and whose call its author's time lies within the
hour of, no more than an hour before the call was requested or after it returned, each held one in
its call's order taking the earliest made. A hash wins over a subject: every hash is settled before
any subject, so that of an amended commit's two calls the one whose hash matches has it. A held
Commit with a hash may still be tied by its subject, which is how a rebased commit, its hash new
and its author's time kept, finds its call. A Commit is tied once.

**The commits' turn** (`commits_turn`, advisory lock 283): a read takes it alone and every
publication beside the others, so that what a read ties no publication holds or removes meanwhile.

## The files' classes

A File's class is the labeller's, from its repository's name and its path alone, the classes the
labeller's declared File Classes, each with whether it counts:

- **`GET /api/collector/files`** answers `200` `{files}` (`FilesSchema` in `pilot_collection.files`),
  every File Pilot holds by its Repository's name and its path, `{repository, path}`, in that
  order; with `unclassed=true`, those with no class. An `unclassed` that is no boolean is a `400`.
- **`PUT /api/collector/classes`** `{classes}`, each `{repository, path, file_class}`: its `204` has
  each File named hold the class named, only those that differed written and their number logged,
  "Took the classes of 412 files: 3 of them differed"; a File the call does not name keeps its
  class. A `400` is a File given twice, one Pilot does not hold, or a class the labeller does not
  declare now; a `413` a body over the app's cap.

## A launch of Pilot's

A Launch a Turn of Pilot's started is placed under its Session and that Turn
(`place_launches`, `launch_placement.py`): among the Sessions whose `conversation_id` is the
transcript's `session_id`, under the one whose Turn was sent last at or before the Launch's start,
and under that Turn where it was in flight then. A Launch started after that Turn's end has the
Session and no Turn; one started before every Turn of the conversation has neither. The two facts
arrive in either order, each in a transaction of its own, and both writers place under the
conversation's turn: every publication of a main thread as its write ends, whole or appended, and
the relay when a Session's first line gives it its `conversation_id`
([`sessions.md`](sessions.md)). A Launch a Turn started is placed once and keeps what it was placed
under; a Launch the file lost goes with it. A transcript is on a project through its Launches'
Sessions and holds no project of its own.

**A round under a continuation** is counted once. A Launch a driver started under a loop session
continues a transcript no Session's `conversation_id` names and a step of the work item that waited
on its loop does, its Step Transcript ([`mcp.md`](mcp.md)): it is placed under the Session created
last before the Launch's start among the Sessions whose steps name that transcript, and under that
Session's Turn in flight then, none between two of them; one started before every such Session has
neither. A continuation's list names the conversation again, so a step done before it stands on
both work items' lists, and the round stays on the work item that was running when its process
started. Such a Launch moves only to a Session created later than the one it stands under, and
before its own start, whose step names its thread, so that it lands under the same Session whichever
Pilot held first, the Launch or the naming; a step that leaves the list moves none. Its writers are
the publication and `set_progress`, which places what Pilot holds of a conversation a step newly
names (`PilotWorkService.set_progress`), each under the conversation's turn. A Session's Turns place
the Launches of a thread its `conversation_id` names, and no step is read for them.

## A Call's cost and caches

**The price file**, `backend/app/prices.csv`, is the models' public list prices, in US dollars per
million tokens: a row a model, a Token Kind nothing is within, the context size in tokens from which
the rate applies, none for the base rate, the rate, and the date from which it applies, at 00:00
UTC; a line that opens with `#` is a comment. A corrected or a new rate is a new row with its own
date, never an edit of a row.

**Its load** (`PriceService.load` in `backend/app/services/price_service.py`, the container's
`price_service`) adds each row the Prices do not hold, and changes and removes none; a row that
gives another rate than a Price held for its model, kind, context size and moment refuses the load
whole, "a rate that changed is a new row with its own date", writing nothing. A model the file names
that Pilot has not met is written. A deploy runs it after the migrations, so a refused load fails
the deploy's `migrate` init container ([`deployment.md`](deployment.md#what-runs)), and so does the
load of the dev seed. A load and the publications take turns (`prices_turn`): a load waits for the
publications in flight and holds off the next until it has committed, so that no Call is priced at
the Prices of before a load and written after it.

**A Model the file does not name** is priced as another, set once, when it is first met
(`priced_as`, `price_as_family`): a dated snapshot, `claude-haiku-4-5-20251001`, as the model it
is a snapshot of where the Prices know that one, else as the newest model of its family the Prices
know, its family the word after `claude-` in its code and the newest the one with the highest
version in its code. A model priced so keeps it until the file names it, when a load drops it.

**A Call's `cost`** is, for each Token Kind it counts tokens of, those tokens at the Price of that
kind for its Model, or the Model it is priced as, with the greatest context size not above its
`context_tokens`, in force at its `completed_at`, the latest one applying from that moment or
before. A Call that counts tokens of a kind no such Price covers has no cost, which the dashboard
reads as unpriced, never as 0; a kind it has no tokens of needs none. One statement says it, for a
publication's Calls before it writes them and for the Calls stored. A load prices again the stored
Calls of each Model whose prices it changed, writing only where the cost differs, and every stored
Call with no cost (`ix_calls_unpriced`). A Turn's own `cost`, as `claude` reported it
([`usage.md`](usage.md#each-turns-tokens)), stays beside the computed one as its cross-check, the
catalogue's `reported_cost`.

**A Call's other caches** (`backend/app/services/call_caches.py`), with its *predecessor* the Call
its `predecessor_id` names:

- `waited_seconds`: from its predecessor's `completed_at` to its own `sent_at`, or to its
  `completed_at` where it has no `sent_at`; none with no predecessor.
- `rewind`: its predecessor is another Call than the one before it by `position`.
- `cache_miss`: with *left* the cache-read and cache-write tokens of its predecessor, and *ref* the
  lesser of *left* and its own `context_tokens`, more than half of *ref* was not read from the
  cache, and its `context_tokens` is at least nine tenths of *left*. A miss is this flag: the
  collector's `miss_cause_code` can stand on a Call that is no miss.
- `past_ttl`: its wait exceeds the lifetime of the cache its predecessor wrote, an hour where it
  wrote a one-hour cache, else five minutes where it wrote a five-minute one; a predecessor that
  wrote none left no lifetime to exceed.
- `launch_id`: its Prompt's Launch, or, on a sub-agent's thread, the Launch of its main thread whose
  start and end hold its `completed_at`, a Launch with no end holding every moment from its start
  on; none where Pilot holds none.

A Call with no predecessor is no rewind, no miss and past no lifetime. A Transcript's
`first_call_at` and `last_call_at` are the `completed_at` of its first and its last Call by
`position`. One statement says them all, for the publication and the deploy alike: a publication
derives them for the Calls it carries before it writes them, sets the Transcript's two times with
its row, and, on a main thread, leaves its sub-agents' Calls in the Launch that now holds them. A
Call a server from before these caches wrote has none, its three flags none together, until a
deploy's step after the migrations derives every such Call and then its Transcript's two times
(`CallCacheService.derive`, the container's `call_cache_service`, through `ix_calls_underived`).
*Took*, a Call's time from its sending to its completion, is no cache: the dashboard reads it at the
query ([`dashboard.md`](dashboard.md#the-answers)).

## The adopted project

A main thread's `group`, `{key, name, summary}`, is the workflow's label of the group of work run
before Pilot that the transcript belongs to, given with a labelling alone: its key never changes,
and its name and summary are as they now stand. The transcript is then adopted by the group's
adopted project, and by none where its labelling names no group, whole or appended: the label is
the labeller's (`backend/app/services/adoption_service.py`, `AdoptionService.adopt`). A call with
no labelling keeps the adoption as it stands ([above](#the-labels)).

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
  Launch of it, or names its conversation, itself or by a step, while no project has adopted it. One adopted before a
  Session named it stays adopted, and its Launches stay off that Session, the server logging it at
  each placement; once a labelling names no group, the same write places them.

Every transition is refused on an adopted project, Bring back included, and so are Join and Leave;
no request makes an `adopted` transition ([`projects.md`](projects.md)). It is listed with the
archived projects, its row reading "Adopted", and its head has no menu. Being archived, its folder
is not in the store's tree ([`projection.md`](projection.md)).

## Testing it

**The scenarios.** `backend/packages/pilot-scenario/`, the package `pilot_scenario` beside the block
DSL's, holds Pilot's invented scenarios, the history drawn from a seed and the builder that turns
each into what a layer reads, and imports nothing but the standard library, so that every layer's suite can take it. The backend
depends on it by path, editable, the image installs it, and the backend's pytest runs its tests,
as it does the DSL's ([`block-dsl.md`](block-dsl.md#the-package)). `SCENARIO`, named `supper`, is
in the dev seed's world, the people `ada` and `ben` and the projects `recipe-box` and `bike-log`,
with kinds of work of its own, `errand` and `leg`: the errand `Scale the recipes` holds the legs
`Halve the stew` and `Halve the dumplings`. Its session `halving` is a Turn of Pilot's on
`recipe-box` that carries out `Halve the stew`, run with the plugin `pantry`, whose skill it loads,
with a sub-agent, `counting`, an API error its request is sent again after, an Edit of
`recipes/stew.md`, a Write of the new `recipes/shopping.md`, a commit of both, "Halve the stew"
(`4be1d2c`), a compaction and a Stop hook; `counting` asks for one
model and another answers, a hook and a permission rule each deny it a call, and its last answer
runs out of tokens. `gears` is Ada's, run by hand on no project, with an instruction file loaded
mid-run, a rewind, a miss past the cache's lifetime, an edit she turns down and two Stop hooks, one
failing, and names the group `bike-log-first-rides`. The model names are the public ones and
everything else is invented.

`TALLY`, named `tally`, is all of it Pilot's work in the same world, so that the projects a load
puts it on hold it whole, and gives each figure of the dashboard a case: a work item's run on
`recipe-box` of two Turns, its brief with a sub-agent and a compaction, its continuation more than
an hour later waiting past the cache's lifetime; between them a Turn each of Ada's and Ben's in the
project's chat; and a job on `bike-log` whose first Call is the one costing more than a dollar. Its
16 Calls and 5 Turns of Pilot's span the 4,040 s before its load, and their figures are pinned
(`TALLY` in `frontend/tests/support/collection.ts`, `backend/tests/dashboard/test_tally.py`).

**The history** (`pilot_scenario.history`) draws days of the fleet's work, each a scenario of the
same script, from a seed and the day's date, so that a day is the same in every history of that
seed that holds it: the dev seed's ([`record.md`](record.md#the-seed)) and the engine's timing
([`dashboard.md`](dashboard.md#the-timing)) are two.

Each session Pilot ran says what Pilot holds of it (`script.Ran`): its project, its Session Kind,
its Turns, each with its start, its cause and its author, and its work item's or job's title or its
chat's kind. `Builder(scenario, until)` lays the scenario's times back from `until`: its
`publications()` are each thread's whole call as a JSON object, a main thread before its
sub-agents, and its `runs()` the sessions of Pilot's. A conversation's ids are drawn from the
scenario's name and the session's, the same in every build.

**As files.** `files()` gives the scenario as files of a home, each a `HomeFile` with its path from
the home's folder, its bytes and its time. They are each thread's transcript in Claude Code's line
shapes (`pilot_scenario.transcript`, [`collector.md`](collector.md#a-transcripts-lines)), in the
publications' order, each followed by the outputs its results say were saved to disk, under
`<session_id>/tool-results/`, and a sub-agent's by its record, `agent-<agent_id>.meta.json`, so a
reader of every file as a transcript takes the `.jsonl` ones alone. `write(home)` puts them under
`home`, the folder that holds `projects`, each at the time its publication gives, and the stub
labeller's run records, `records()`, where the stub reads them under `plugins`. Each of
`publications()` carries the stub's labelling of its thread's file, labelled whole with Pilot
handing nothing, and the group the stub adopts, so that a collector that runs the stub over the
files publishes what `publications()` says ([`collector.md`](collector.md#testing-it)). `_facts` in
the package's `tests/test_transcript.py` cuts a publication to what its file's lines and record say,
and `_read` there is an independent reading of the files. The builder's times are cut to the
millisecond, as a line's `timestamp` is. `halving`'s brief is an `sdk` prompt and `gears`' prompts
are `typed`; `gears` interrupts a Bash call; and two results, the sub-agent's grep and the MCP call,
are outputs saved to disk, one in each of Claude Code's wordings. The lines the facts are read off
include a Call's request line and the line of the shape it sent; a Launch's instruction files and
what was injected before a Call; a compaction's boundary and summary; a failed attempt's request and
its error; a denied call's result in Claude Code's words; a Prompt's Stop hooks' summary and a
failing hook's error; and a plugin's skill's body under the plugin's cache at its Launch's version.
The files are generated when a suite runs and never committed.

**The stub labeller.** `pilot_scenario.labeller`, a file of the standard library alone, is the
command a suite's collector names in place of the workflow's labeller, which no suite reaches:
`labeller.command(*options)`, the verb appended. It speaks the labeller's contract 1, the verbs
`info`, `vocabularies`, `stamps`, `label`, whole and appended, and `classes`, with the contract's
refusals, exit codes and error lines, and writes nothing. Its options are `--version` (default
`VERSION`, `1.0.0`), `--speaks`, the contract it speaks, and `--pause`, the seconds it takes before
each transcript's line of a `label` answer. Its lists, units, file classes and rules are the
scenario's, each a few lines over what a file, the run records and what Pilot handed say, with no
word of the workflow: its Segment Kinds `prep`, `cook` and `simmer`, its six File Classes `recipe`,
`tasting`, `note` and `menu`, counted, and `printout` and `logbook`, not. Its run records are
`records.json` in the folder the request's `home.data` names, else
`<home.plugins>/data/scenario-labeller`, a home without the file holding none: the kinds and their
nesting, the units, the unit each conversation ran, the units' Test Runs and Suites, the groups and
the conversations each adopts, and a repository's own file rules ahead of its starting list.
`Builder.vocabularies()` is the declaration a collector sends ([above](#the-labellers-vocabularies)).

**Its load.** `POST /api/testing/scenarios` `{scenario, projects}`, one of the record's testing
routes ([`projects.md`](projects.md#testing-it)), loads `supper` or `tally` on the projects given
for those the scenario's sessions of Pilot's are on, by the scenario's name of each
(`{"recipe-box": <a project's id>}`), its last moment the transaction's `now()`
(`ScenarioService.load`, `backend/app/services/scenario_service.py`): for each session Pilot ran,
its Session on the project given, over, with its Turns, a run's Work and Item done at its end or a
chat's Chat closed then, then the stub's vocabularies declared and each thread published whole
through `PublicationService.publish`, with the stub's labels. It answers `201` `{transcripts}`, in
the builder's order, each `{session_id, agent_id, adopted_by}`, `adopted_by` the adopted project's
`{id, name}` or null. A load's conversations' ids are drawn from the scenario's name and the
projects it is loaded on, so a second load on the same projects publishes the same transcripts whole
and replaces the first, the record holding it once, as it was loaded last, and a load on other
projects is a scenario of its own beside it; the group's project is found by its key. Another set of
projects than the scenario's is a `400`, an unknown project or a Turn's author the record lacks (the
tally's `ada` and `ben`) a `404`, and a stage with no service user a `409` `NO_SERVICE_USER`, each
writing nothing. The fake collector serves each scenario loaded. A Playwright spec makes the service
user with `people.serviceUser()` and loads a scenario with `collection.loadScenario(scenario,
projects)`, then ends a walk with `collection.walk()` (`frontend/tests/support/collection.ts`); a
backend test takes the `service_user` fixture.

**A walk's end.** `POST /api/testing/walks`, with no body, for a signed-in editor on every stage but
prd, as the record's testing routes are, ends a walk through the same service and answers `201`
`{ended_at, announced}`, `announced` whether its `collection_changed` is sent. A spec that loaded a
scenario posts it and waits for the event; a second post with no load between raises none. On a
stage with a collector, the collector's own walk's end can come between a load and the post. That
end then sends the event, and the post answers `announced: false` and sends none, so a check there
holds the live stream before it loads and takes the event of either end.

**The guards.** `test_the_scenario_has_no_word_of_the_workflow`
(`backend/packages/pilot-scenario/tests/test_scenario.py`) fails on a word of the workflow,
`slice`, `stage` or `phase`, in any string of the scenario, and the histories' places and a day of
each are held to the same words (`backend/tests/support/workflow_words.py`). `backend/tests/test_no_transcript_file.py`
fails on a transcript's file in the tree, a `.jsonl` file or one holding a line that carries
`sessionId` and `parentUuid`, read from the repository's root, the folders no commit holds aside:
a transcript in a test is generated when the suite runs, and the six invented stream fixtures of
`backend/tests/fixtures/raw/`, a turn's events as the controller relays them, are the one kind of
JSON Lines file the tree holds.

The door and its routes are pinned in `backend/tests/api/test_collector.py` and
`tests/api/test_collector_repositories.py`, the write in
`tests/services/test_publication_service.py`, the labels in
`tests/services/test_publication_labels.py`, the vocabularies in
`tests/services/test_vocabulary_service.py`, what the labeller is handed in
`tests/services/test_labeller_context.py`, the commits and edits in
`tests/services/test_commit_write.py`, the tie in `tests/services/test_commit_tie.py`, a read and
the classes in `tests/services/test_repository_service.py`, the call's shapes in
`tests/schemas/test_publication.py` and `test_vocabularies.py`, on the package's import, the walk's
end, its event and the readiness check in `tests/services/test_walk_service.py`, the Walk's revision
in `tests/migrations/test_0050_walks.py`, the placement in
`tests/services/test_launch_placement.py`, the adoption in
`tests/services/test_adoption_service.py`, the load in `tests/services/test_scenario_service.py` and
the walks' testing route in `tests/api/test_testing_record.py`. The package `pilot-collection`'s
`tests/test_package.py` pins that it stands without the app, and the builder is pinned in
`pilot-scenario`'s `tests/test_builder.py`, its files in `tests/test_transcript.py`, the tally and
the history in `tests/test_tally.py` and `tests/test_history.py`, and the stub labeller in
`tests/test_labeller.py`. A collector's walk against these routes is `tests/collector/test_walk.py`
([`collector.md`](collector.md#testing-it)).
`tests/support/publications.py` makes a call (`whole()`, `sub_agent()`, `appended()`,
`collector_headers()`), `tests/support/transcripts.py` the rows, `tests/support/vocabularies.py` and
`labels.py` a declaration and labelled rows in a kitchen's words, `tests/support/repositories.py` a
read, and `writes()` in `tests/support/database.py` counts the rows a block writes, by table. The
cost and the caches are pinned in `tests/services/test_price_service.py`,
`tests/services/test_call_caches.py` and `tests/services/test_quota_week_service.py`, with their
revisions' tests in `tests/migrations/`. The adopted project's row and head are pinned in
`frontend/tests/projects/adopted-project.spec.ts`. A Playwright backend's `COLLECTOR_TOKEN` is the
fake collector's it serves itself ([`dashboard.md`](dashboard.md#testing-it)), so the door takes a
call that carries it; no collector walks there, so its readiness check `collector` reads as it does
where no walk has ended lately ([above](#a-walks-end)).
