# The collector

The collector reads the Claude Code transcripts on a fleet's home. It publishes their facts into
Pilot's record, one transcript a call, through the door of [`collection.md`](collection.md), and
it serves a conversation's reading to Pilot's backend. It is a component of PilotApp's own,
`collector/`: a uv project in Python beside the backend's code (D255), with its own `uv.lock`,
the package `pilot_collector` and the image `registry:5000/pilot-collector`. Each stage runs it as
a pod of its own beside the stage's fleet's home ([`deployment.md`](deployment.md#what-runs)).
What it carries between walks is in its memory alone, and Pilot is the cursor: a restart is an
ordinary walk.

The shapes it shares with the backend, the publication's, the inventory's and the reading's, are
the package `pilot-collection` (`backend/packages/pilot-collection/`), which needs pydantic alone.
The collector takes that package by path, and its tests take the invented scenario's,
`pilot-scenario`, the same way ([`collection.md`](collection.md#testing-it)).

## The process

`python -m pilot_collector`, the script `pilot-collector` (`__main__.py`), walks the home on its
main thread and serves the readings on a thread beside it. It runs until SIGTERM or SIGINT, which a
walk obeys before its next publication. It logs "The readings are served on port <port>" before its
first walk. A setting that does not validate ends it at its start, as does a port that is taken, and
a home with no `projects` folder ends it at its first walk.

| Setting | Default | |
|---|---|---|
| `COLLECTOR_PILOT_URL` | none | where Pilot's backend answers, with no path: the `/api/collector` routes are under it |
| `COLLECTOR_TOKEN` | none | the bearer, the backend's `COLLECTOR_TOKEN`, at least one character: the collector's calls carry it, and a call for a reading is refused without it |
| `COLLECTOR_HOME` | none | the fleet's home as the collector sees it: the folder that holds `projects`, Claude Code's `.claude` |
| `COLLECTOR_PORT` | `3503` | the port the readings are served on; `0` takes one that is free |
| `COLLECTOR_ENVIRONMENT_PATTERN` | `# Environment: (\S+)` | the regular expression the managed instruction file opens with on a hosted session; its first group is the environment's id |
| `COLLECTOR_CHECKOUT_ROOTS` | `["/work"]` | the directories an environment's repositories are checked out under, each an absolute path, as a JSON list |
| `COLLECTOR_CARRY_TRANSCRIPTS` | `2500` | how many transcripts' carries are kept between walks ([below](#whole-or-appended)) |
| `COLLECTOR_CARRY_BYTES` | `64000000` | the bytes of memory the carries are kept within |

Each is read from the environment variable of its name (`Settings`, `settings.py`). The walk's
interval and the settling time are Pilot's, and each inventory hands them over
([`collection.md`](collection.md#the-inventory)).

## The home

A transcript is a thread's file under the home's `projects` (`home.py`). A main thread's file is
`<folder>/<session_id>.jsonl`, the folder named for the directory the conversation began in, each
character that is no letter or digit a `-`. A sub-agent's is
`<folder>/<session_id>/subagents/agent-<agent_id>.jsonl`, and one a workflow started lies deeper,
under `subagents/workflows/<workflow>/`. The ids are the path's. Nothing else under `projects` is a
transcript: a workflow's `journal.jsonl`, a sub-agent's `.meta.json` and the outputs saved under
`<session_id>/tool-results/` are not. A walk lists every transcript with a `stat` and follows no
symlink: a sub-agent's file linked into another session's folder is its own session's, and the walk
meets it there.

## The walk

A walk (`Walker.walk`, `walk.py`) takes Pilot's inventory and lists the home. Then it publishes in
two turns, one call a transcript:

1. **New or changed**: every transcript the inventory lacks, or holds at another size or time than
   its file's, the most recently changed first.
2. **Behind**: a transcript held at its file's size and time that was read under another version of
   the collector's, or is due its replay at rest. A transcript is due it where its `replayed_size`
   is short of its `file_size`, appended publications having been taken since its last whole one,
   and its file has not changed for the settling time. This turn too goes the most recently changed
   first. Each publication is begun only while the walk's interval has not passed since the walk
   began; the rest wait for the next walk.

A file's time is compared cut to the microsecond, as Pilot holds it. A transcript Pilot holds and
the home lacks is left alone, and so is what Pilot holds of it. After its last publication the walk
tells Pilot it ended, `POST /api/collector/walks`, whether it published or not
([`collection.md`](collection.md#a-walks-end)). Walks run one after another on one thread, so no two
walk at a time. A walk starts the interval after the start of the one before, or at once after a
walk that took longer; before a first inventory has given the interval, it is 30 s.

**A walk that ends early.** A `401` or a `426` from Pilot is logged at `ERROR`, "The walk ended early:
<why>". No answer, a `409` other than `PUBLICATION_NOT_APPENDABLE`, and any other status the route's
table does not name, a `500` among them, are logged the same at `WARNING`. Each ends the walk where
it stands, its end untold, and the next walk starts over from the inventory. A call waits 10 s to
connect and 300 s for each part of an answer.

**What it sets aside.** Some transcripts are logged at `WARNING` and set aside: one it cannot read,
whatever its read raises, and one Pilot refuses with `400` or `413`. The line reads "The transcript
<session_id>[/<agent_id>], <file>, is set aside until its file changes: <reason>". The reason is
"it cannot be read: <why>", "reading it raised <the error's type>: <its message>" or "Pilot refused
it with <status>: <its answer>". No walk takes it again until its file's size or time changes. What
is set aside is held in memory alone, so a restart logs each once more. A transcript whose own file
went between the listing and its read logs nothing.

**Its line.** A walk that published, set aside or left anything logs one line at `INFO`; any other
walk logs it at `DEBUG`:

```
A walk over 22874 transcripts: 12 published, 9 of them appended, 0 set aside, 0 left for the next walk, in 0.4 s
```

The line ends "; Pilot was not told it ended" where the walk's end was not told.

## A transcript's lines

A transcript's file is JSON Lines, a line an object, and a line is read once its newline is
written, within the size the open file has. A line with a `uuid` is one of the thread's chain: it
names the line it follows as `parentUuid` and carries its `timestamp`, its `cwd`, the session's id
and Claude Code's `version`. The lines Claude Code writes beside the chain carry no `uuid`, and of
them only the queue's carry a time: the permission mode a process starts under, the queue's
operations (`queue-operation`, an `enqueue` with a prompt's text, a `dequeue`, a `remove` and a
`popAll`), the last prompt, and the cost line (`cost-state`) a process writes as it exits.

- A prompt is a `user` line whose `message.content` is its text, with Claude Code's word for its
  source. One that waited in the queue follows its `enqueue` and `dequeue` lines.
- A process's first prompt is followed by an `attachment` line of type `instructions`, whose
  `files` list the instruction files it loaded, the managed one of `type` `Managed` among them.
- A response is one `assistant` line a block, all under its `message.id`. Each line carries the
  response's `usage`, the 5-minute and the 1-hour cache writes apart under `usage.cache_creation`;
  a line before the last can carry fewer output tokens than the last and no `stop_reason`.
- A tool's result is a `user` line holding a `tool_result` block that names its request's id,
  with `toolUseResult`, the tool's own record of it.
- A sub-agent's file opens with the task its spawning call gave it, and every line of its chain is
  an `isSidechain` one that carries its `agentId`.

## A transcript's facts

`read(transcript, settings)` in `reader.py` turns one file into its whole publication, a
`PublicationSchema` ([`collection.md`](collection.md#a-publication)); the module's docstring has
each rule in full. The facts are read off the lines in the file's order:

- **The collection record.** The file's size and time are the open file's own, the time cut to the
  microsecond, and the collector's version is `VERSION`. A line still being written counts in the
  size and is not read.
- **The place.** The working directory is the first line's that carries one; a file with none is
  refused. The repository is the checkout that holds it: the first folder under a checkout root,
  the roots' `scratch` folder aside, a worktree under it included. Any other directory has none, and
  a session that moves stays its first directory's. The environment is a main thread's alone: the
  id the pattern finds at the start of the managed file's text, in the `instructions` attachment,
  the first where the file names two.
- **A Launch** (D257), on a main thread, starts at the file's first line with a time and at the
  first such line after a cost line. A killed process writes no cost line, so the process that
  follows it joins its Launch. Lines with no time after a cost line start none, that line written a
  second time among them. Its `started_at` is its first line's time, and its one component is
  `claude-code` at the version its lines name, the first that names one. A Launch none of whose
  lines names a version is not published, and a file where such a Launch received a Prompt is
  refused.
- **A Prompt** (D259) is a main thread's `user` line whose source Claude Code names, in Claude
  Code's own word: `promptSource`, `typed`, `sdk`, `system`, `queued` or `suggestion_accepted`.
  Older files name it in other fields. On a line with no `promptSource` that is no `isMeta` one, the
  word is `turnOrigin`'s, else `origin.kind`'s, `human` read as `typed` and `task_notification` or
  `task-notification` as `system`; any other older word is kept as it is.
  - Its time is that of the `enqueue` line that holds its text, the queue's first of that text,
    else its own. A `remove` that names a text takes it out of the queue, and a `popAll` and a cost
    line empty it.
  - Not a Prompt: a line that names no source, a person's interruption, a skill's `isMeta` words, a
    compaction's summary, a tool's result, a `queued_command` attachment, and the context a hook
    added, which arrives as an attachment.
- **A Call** is the `assistant` lines under one `message.id` whose model is no `<synthetic>` one,
  placed by the first of them, and follows the Prompt last received before it, where there is one.
  Its model, its `completed_at` and its usage are the last line's, its five token counts read there.
- **A Tool Call** is a `tool_use` block of a Call's lines, requested at its line's time. Its result
  is the first `tool_result` block that names its id, in a `user` line of the thread. A result that
  names no request of the file is dropped.
  - Its `first_argument` is the first of its input that is text, cut to its first line that is not
    blank; an input with no text gives none.
  - Its `mcp_server` is the one its name is under, `mcp__<server>__<tool>`.
  - The result gives `returned_at`, `failed` (its `is_error`) and `result_characters`, the
    characters of its text: its string, or its `text` blocks together.
  - `exit_code` is Bash's alone: the `Exit code N` its error opens with. A Bash result that is no
    error reads 0, which is not published, Pilot holding an exit code only where it was not zero.
  - `interrupted` is read where Bash's `toolUseResult.interrupted` is true, and where an error opens,
    past an `Exit code N` line, with Claude Code's words for a person's interruption, `[Request
    interrupted by user for tool use]` or `Interrupted by user`.
  - `saved_characters` is read where the result opens in one of Claude Code's two wordings for an
    output saved to disk, never where it only quotes them. The first is `<persisted-output>` followed
    by "Output too large (<size>). Full output saved to: <path>". The second is "Error: result (N
    characters) exceeds maximum allowed tokens. Output has been saved to <path>.", where a count of
    lines can follow the characters. The full size is the saved file's characters, the file found
    under `projects` by the path's last four parts. Where that file is gone it is the characters the
    result states, and in the first wording it is then none.

The reader publishes none of the file's other facts: a sub-agent's type, description and spawning
call, a Launch's end and its other components, hook runs, compactions, a Call's sending time, stop
reason, predecessor and attribution, events, context parts and the labels.

A file the reader cannot turn into a publication raises `UnreadableError` with the reason: a line
that is not one it reads, named by its number, no line that names a working directory, a Launch that
received a Prompt and names no version, or facts the publication's shape refuses.

## Whole or appended

A grown transcript is read from its boundary on, its tail, and published appended (D256). The walk
keeps a carry of each transcript it published (`carry.py`), in its memory alone. The carry holds the
file it was built on, the file's size, its time and the collector's version, and where the reading
stood at its **boundary**, the transcript's first Call that is not settled. A Call's facts are
settled once the next Call has begun, so the boundary is the file's last Call, and in a file with no
Call the place its first would take. Of the reading there, the carry holds:

- the byte the boundary's first line starts at;
- how many Calls, published Launches and Prompts lie before it, from which the appended call's four
  places come ([`collection.md`](collection.md#a-publication));
- the `uuid` of the last line before it that carries one;
- the directory and the environment the file named first;
- the Launch open there, with its start, its version and its Prompts so far;
- the prompts waiting in the queue, each as a digest of its text with its `enqueue` time;
- a digest of the file's bytes from the boundary's on, as they were read.

No other id of a line before the boundary is held: there is no map of the file's ids.

A transcript the inventory holds at exactly what its carry was built on is read from the
boundary's byte on (`read(transcript, settings, carry)`). It is published appended: the Calls from
the boundary on, the Launches that wrote a line from there on, the first of them with its Prompts
from there on, and the four places. Every other transcript is published whole. A transcript that has
a carry and is published whole instead, in the same walk, logs a line at `INFO`: "The transcript
<session_id>[/<agent_id>], <file>, is published whole, not from its boundary on: <reason>". The
reasons are:

- "Pilot does not hold it as it was last read";
- "its file is no larger than the one last read", or "its file has other bytes before its old end":
  the bytes from the boundary's to the old end differ from those read then;
- "a line follows one before its boundary that is not the last there", its `parentUuid` naming
  another line before the boundary's byte than the carry's;
- "a tool's result names a request no line from its boundary on makes";
- "reading it from its boundary on raised <the error's type>: <its message>";
- "Pilot refused it appended: <Pilot's reasons>", a `409` `PUBLICATION_NOT_APPENDABLE`, or "Pilot
  refused it appended with <status>: <its answer>", a `400` or a `413`.

A rewrite before the boundary's byte is not seen there. The replay at rest, a whole publication
once the file has settled, follows it. A line that reaches back behind the boundary stays in what is
read until the next Call begins, so every walk that sees the file grow until then publishes it
whole. The second turn of a walk publishes whole without trying the carry.

**The bound.** The carries are kept up to `COLLECTOR_CARRY_TRANSCRIPTS` transcripts and
`COLLECTOR_CARRY_BYTES` of memory, a carry counted at about 1 KB. Past either, the carry of the
transcript whose file changed longest ago is forgotten first, and that transcript's next growth costs
one whole publication. A carry stays through a walk Pilot stopped answering, and goes when its
transcript is set aside. The carries are the walker's, read and written on its thread alone.

## The reading

The collector serves a conversation's reading to Pilot's backend, its only caller, never its file
(`serve.py`, `reading.py`). `GET /readings/<session_id>` is a main thread's reading and
`GET /readings/<session_id>/<agent_id>` a sub-agent's, on `COLLECTOR_PORT`, served by waitress.
A call carries the collector's bearer and names the reading's version in `X-Pilot-Reading-Version`,
1 alone today (`READING_MIN` to `READING_MAX`). It is answered, in this order:

| Answer | When |
|---|---|
| `401` | the call does not carry the bearer |
| `426` `{min, max}` | it names no version, or one outside the range (`ReadingVersionRangeSchema`) |
| `404` `TRANSCRIPT_GONE` | the home has no file a walk lists under those ids; a `404` without the code is a path that is no reading's |
| `304` | `If-None-Match` names the file's validator: the file was found and nothing of it read |
| `200` | the reading, as JSON, gzip-compressed whatever the call accepts, sent in parts with no length |

The validator is the file's size and time, the `ETag` of a `200` and a `304`:
`"<bytes>-<microseconds since 1970>"`, never a date. A file the collector cannot read is a plain
`500`, with nothing of the reading sent. The reading is built whole and then compressed 64 KB at a
time.

**The reading's shape** is `ReadingSchema` in `pilot_collection.reading`. It is one Transcript,
whole: its ids, `file_size` and `file_modified_at` as the reading was read, `calls`, and `after`,
what follows the last Call. A Call is `{message_id, received, sent}`: what came in before it, since
the first line of the Call before, and what it put out. Its calls are the facts' Calls, read by the
same rules, with each block's kind, the time of the line it stood in and its full text. No image's
bytes are carried:

- **What came in**, in `received` and `after`:
  - `user`, a line that arrived as the person's and is no tool's result, with its `writer`:
    - `person` for a source `typed`, `queued` or `suggestion_accepted`;
    - `brief` for `sdk`;
    - `notice` for any other word, and for a line that names none and is Claude Code's own: an
      `isMeta` one, a compaction's summary or its words for an interruption;
    - `parent` on a sub-agent's line that names none and is none of those, or whose origin is the
      coordinator;
    - none on a main thread's line that names none and is none of those.
  - `image`, after the line's own block, by its `media_type` and `size`, the bytes its base64 text
    stands for.
  - `synthetic`, an `assistant` line of the `<synthetic>` model: Claude Code's own words where a
    response would stand.
  - `attachment`, with Claude Code's word for it, `type`, and its text: its `text`, `content` or
    `prompt`, the first that is words, else what it holds as JSON. An image in it is said by its
    media type and size.
  - `system`, with its `subtype` and its `content` where that is words.
  - `tool_result`, a result that names no request of the file, or one a result already answered,
    where it stands.
- **What a Call put out**, in `sent`:
  - `text`;
  - `thinking`, with the text the file has of it;
  - `tool_call`, once per request, with its `tool_use_id`, `tool`, `input` as the file holds it,
    and `result`, `{at, error, text, images}` or none. `started` is the `agent_id` of the
    sub-agent's Transcript the call started in this conversation, where the tool's own record of
    the result names one.

No other line is read: the queue's, a tool's progress and the lines beside the chain are not the
conversation's. A transcript is found by its ids as a walk lists it, a `stat` in each folder of
`projects` or a listing of the session's `subagents`, so "not changed" reads nothing of the file.

## Its image

`collector/Dockerfile` builds `registry:5000/pilot-collector` on the backend's build and runtime
images, with the repository's root as its build context, since the packages the collector takes by
path lie under `backend/packages/`. The root `.dockerignore` is an allow-list that keeps that
context to what the file copies. The image holds the environment alone, at `/app/.venv`, synced
`--locked --no-dev --no-editable`. It runs `python -m pilot_collector` under `tini` as uid and gid
1000, the user a fleet's home and its transcripts belong to, and exposes 3503. Its build fails where
that user cannot load the process. `PilotApp/Build-Main` runs the collector's tests in its stage
`Test collector` and builds the image in `Build pilot-collector image`
([`deployment.md`](deployment.md#how-a-change-gets-to-dev)).

## Testing it

`kc project test --project collector` runs `collector/tests`, which need no service, and
`kc project lint --project collector` its ruff, format check, mypy and vulture. The reader's rules
are pinned in `test_reader.py` and `test_appended.py`, the carry and its bound in `test_carry.py`,
the home in `test_home.py`, the walk's plan in `test_walk.py`, the reading in `test_reading.py`,
its route in `test_serve.py` and the process in `test_main.py`, which asks the running process for
a reading. `tests/support.py` builds a file's lines for one rule and `settings()` the settings,
inventing the three that have no default.

The walk against Pilot's routes is the backend suite's, `backend/tests/collector/test_walk.py`.
The backend's dev group takes the collector by path, so that a walk publishes into a database of
its own per test. Pilot is served by werkzeug's `make_server` on `committed_app`, and the walk runs
over the invented scenario's files written to a home of the test's
([`collection.md`](collection.md#testing-it)). A dependency the collector gains is locked twice, in
`collector/` and in `backend/`, whose lock names the collector's dependencies: the backend's
`uv sync --locked` fails until both are.
