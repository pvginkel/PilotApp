# The collector

The collector reads the Claude Code transcripts on a fleet's home. It publishes their facts into
Pilot's record, one transcript a call, through the door of [`collection.md`](collection.md), with
the labels the workflow's labeller gives them; it gives Pilot the commits of the repositories the
transcripts name, read from clones of the mirror, and the files' classes; and it serves a
conversation's reading to Pilot's backend. It is a component of PilotApp's own,
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
| `COLLECTOR_LABELLER` | `["python3", "-B", "{install_path}/tools/labeller.py"]` | the command that runs the workflow's labeller, a JSON list, each call's verb appended; `{install_path}` is the folder of the installed `dev@aiworkflow` copy ([below](#the-labeller)) |
| `COLLECTOR_LABELLER_SECONDS` | `60` | the seconds a call of the labeller may take, above 0: past them it is stopped |
| `COLLECTOR_MIRROR_URL` | `http://gitblit.git-sync-prd.svc.cluster.local/r` | where the Gitblit mirror serves the repositories, with no credential ([below](#the-clones)) |
| `COLLECTOR_MIRROR_OWNERS` | `["pvginkel"]` | the owners on the mirror a repository is looked for under, in the order tried, a JSON list |
| `COLLECTOR_MIRROR_SECONDS` | `3600` | the seconds from one read of the clones to the next, above 0 |
| `COLLECTOR_CLONES` | `/tmp/pilot-collector/clones` | the folder the bare clones are kept in, on the collector's own storage |

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
`<session_id>/tool-results/` are not. A sub-agent's `agent-<agent_id>.meta.json`, beside its file,
is its record, read with it ([below](#a-transcripts-facts)). A walk lists every transcript with a
`stat`, a regular file alone, never a pipe or a device of a transcript's name, and follows no
symlink: a sub-agent's file linked into another session's folder is its own session's, and the walk
meets it there. A folder under `projects` that cannot be listed holds no transcript for the walk,
which logs at `WARNING` "The folder <folder> cannot be listed, so no transcript in it is: <why>".

## The walk

A walk (`Walker.walk`, `walk.py`) takes Pilot's inventory and lists the home. Then it publishes in
two turns, one call a transcript:

1. **New or changed**: every transcript the inventory lacks, or holds at another size or time than
   its file's, the most recently changed first.
2. **Behind**: a transcript held at its file's size and time that was read under another version of
   the collector's, or is due its replay at rest, or, where a labeller answers, whose labels Pilot
   holds under another major of the labeller's version than the one answering, or under another
   stamp than the one it would give now ([below](#the-labeller)). A transcript is due its replay at
   rest where its `replayed_size` is short of its `file_size`, appended publications having been
   taken since its last whole one, and its file has not changed for the settling time. This turn
   too goes the most recently changed first. Each of its batches is begun only while the walk's
   interval has not passed since the walk began; the rest wait for the next walk.

Each turn is published in batches of at most 64 transcripts, and past 32,000,000 bytes of files of
its first alone (`_BATCH`, `_BATCH_BYTES`), a batch labelled in one call where a labeller answers
([below](#the-labeller)).

A file's time is compared cut to the microsecond, as Pilot holds it. A transcript Pilot holds and
the home lacks is left alone, and so is what Pilot holds of it. After its last publication the walk
tells Pilot it ended, `POST /api/collector/walks`, whether it published or not
([`collection.md`](collection.md#a-walks-end)). Walks run one after another on one thread, so no two
walk at a time. A walk starts the interval after the start of the one before, or at once after a
walk that took longer; before a first inventory has given the interval, it is 30 s.

**A walk that ends early.** A `401` or a `426` from Pilot is logged at `ERROR`, "The walk ended
early: <why>". No answer, a `409` of another code than `PUBLICATION_NOT_APPENDABLE`,
`TRANSCRIPT_NOT_ADOPTABLE` and `NO_SERVICE_USER`, and any other status the route's table does not
name, a `500` among them, are logged the same at `WARNING`. Each ends the walk where it stands, its
end untold, and the next walk starts over from the inventory. A call waits 10 s to connect and 300 s
for each part of an answer.

**What it sets aside.** Some transcripts are logged at `WARNING` and set aside: one it cannot read,
whatever its read raises, and one Pilot refuses with `400`, `413` or `409` `NO_SERVICE_USER`. A main
thread whose `group` Pilot refuses, `409` `TRANSCRIPT_NOT_ADOPTABLE`, is published again without it,
logged at `WARNING`, "The main thread <session_id> is published with no group: <why>". One whose
labels Pilot refuses is published without them before it is set aside ([below](#the-labeller)). The
line reads "The transcript <session_id>[/<agent_id>], <file>, is set aside until its file changes:
<reason>". The reason is "it cannot be read: <why>", "reading it raised <the error's type>: <its
message>" or "Pilot refused it with <status>: <its answer>". No walk takes it again until its file's
size or time changes. What is set aside is held in memory alone, so a restart logs each once more. A
transcript whose own file went between the listing and its read logs nothing.

**Its line.** A walk that published, set aside or left anything logs one line at `INFO`; any other
walk logs it at `DEBUG`:

```
A walk over 22874 transcripts: 12 published, 9 of them appended and 12 labelled, 0 set aside, 0 left for the next walk, in 0.9 s; the labeller 1.0.1's stamps took 0.45 s
```

It ends "; no labeller's stamps" where no labeller answered them, and then "; Pilot was not told it
ended" where the walk's end was not told. The walk's interval, which bounds its behind turn, leaves
out the time the stamps and their declaration took. After its end a walk reads the clones and has
the Files classed ([below](#the-clones)).

## A transcript's lines

A transcript's file is JSON Lines, a line an object, and a line is read once its newline is
written, within the size the open file has. A line with a `uuid` is one of the thread's chain: it
names the line it follows as `parentUuid` and carries its `timestamp`, its `cwd`, the session's id
and Claude Code's `version`. Claude Code writes some lines before the line they follow. The lines
Claude Code writes beside the chain carry no `uuid`, and of them only the queue's and the requests'
carry a time: the permission mode a process starts under, the queue's operations
(`queue-operation`, an `enqueue` with a prompt's text, a `dequeue`, a `remove` and a `popAll`), a
request and its shape, the last prompt, and the cost line (`cost-state`) a process writes as it
exits.

- A prompt is a `user` line whose `message.content` is its text, with Claude Code's word for its
  source. One that waited in the queue follows its `enqueue` and `dequeue` lines.
- A message Claude takes in the middle of a run is an `attachment` line of type `queued_command`,
  its text its `prompt` and its kind its `commandMode`, `task-notification` or `prompt`. It names
  no source. The queue's `remove` of its text is written before it, after it or not at all.
- A process's first prompt is followed by an `attachment` line of type `instructions`, whose
  `files` list the instruction files it loaded, each its `path` and `content`, the managed one of
  `type` `Managed` among them. From Claude Code 2.1.261 a process's start is also recorded by a
  `prompt_snapshot` attachment, never shown to the model: `systemPrompt`, the system prompt as a
  list of strings holding a marker where Claude Code splits it, and `tools`, which a newer version
  leaves out.
- A request to the model (2.1.300 on) is an `api-request` line, whose `id` each line of its
  response names as `requestRef`; a retry writes a request line again. It names the system prompt
  and the tools it sent, its shape, by `shapeHash`, and the messages it sent: those it kept of the
  ones the request before it sent, `keep`, and those it adds, `tail`. A shape's own line,
  `api-request-shape`, is written once in a file, before the first request that names it, with
  `shape.system` and `shape.tools`.
- A response is one `assistant` line a block, all under its `message.id`. Each line carries the
  response's `usage`, the 5-minute and the 1-hour cache writes apart under `usage.cache_creation`;
  a line before the last can carry fewer output tokens than the last and no `stop_reason`. Where
  the version writes them, its lines name the model asked for, `requestedModel`; the `effort`; the
  skill and the plugin the response acted under, `attributionSkill` and `attributionPlugin`; and
  the API's id of the request, `requestId`. The last line counts the thinking tokens under
  `usage.output_tokens_details`. A response a fallback answered opens with a `fallback` block,
  `from` the model asked for, and a `system` line of subtype `model_refusal_fallback` names the
  request's `requestId` and that `originalModel`.
- A tool's result is a `user` line holding a `tool_result` block that names its request's id,
  with `toolUseResult`, the tool's own record of it: an Edit's and a Write's hold the patch,
  `structuredPatch`, a list of hunks, and a Write's its `type`, `create` or `update`; a Bash call's
  that made a commit, `gitOperation.commit.sha`, where Claude Code records one, and the commit's own
  line in its output, `[<branch> <hash>] <subject>`, unless the command ran quiet. From 2.1.201 a
  denied call's line names how,
  `toolDenialKind`: `permission-rule`, `user-rejected`, or `interrupted` for a call the person
  interrupted. A `PreToolUse` hook's block is an error result opening `PreToolUse:<tool> hook
  error:`.
- What Claude Code injects for the model is an `attachment` line or a `user` line marked `isMeta`.
  An attachment shown to the model carries what it was shown, `rendered`, a list of `{content}`
  (2.1.261 on): a `nested_memory` is an instruction file loaded once the process was under way,
  with its `path` and `content`; an `invoked_skills` shows again the bodies of the skills invoked
  before a compaction, each its `name` and `content`; and the other types shown are reminders,
  each of its own. A skill's body is an `isMeta` line whose `sourceToolUseID` names the `Skill`
  call it expanded, its text opening "Base directory for this skill:" where the skill has a
  folder; one expanded for a command the person typed names no call.
- A compaction is a `system` line of subtype `compact_boundary` that follows no line: its
  `logicalParentUuid` names the line it continues, and its `compactMetadata` holds the `trigger`
  and `preTokens`, a newer version's `postTokens` and `durationMs` too. Its summary is a `user`
  line marked `isCompactSummary`.
- An attempt at a request that failed and is sent again is a `system` line of subtype
  `api_error`, its `error` with a `status`; a request that failed for good is an `assistant` line
  of the `<synthetic>` model marked `isApiErrorMessage`, with `apiErrorStatus`. A response the
  person interrupted is followed by a `user` line holding a text block of exactly `[Request
  interrupted by user]`.
- The Stop hooks run at the end of a prompt's run are a main thread's `system` line of subtype
  `stop_hook_summary` (2.1.250 on): `hookInfos`, each hook's `command` and `durationMs`,
  `hookErrors`, `preventedContinuation`, a newer version's `failedHookErrorIndexes`, and the run's
  `toolUseID`. A hook that reports an error writes an `attachment` of type
  `hook_non_blocking_error`, with its `hookEvent`, its `command` and the run's `toolUseID`.
- A sub-agent's file opens with the task its spawning call gave it, and every line of its chain is
  an `isSidechain` one that carries its `agentId`. Its record, beside the file, names its
  `agentType`, the `description` its spawning call gave it and, from 2.1.144, that call's id,
  `toolUseId`. A fork, a sub-agent of the type `fork`, opens its file with copies of its parent's
  lines, the message that holds the call that started it among them.

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
- **A sub-agent's record.** Its `agent_type`, `description` and `spawned_by` are its record's
  `agentType`, `description` and `toolUseId`, each none where the record or the key is missing: a
  workflow's agent names no call, nor does a sub-agent older than Claude Code 2.1.144. The record
  is read again at every reading of the file, since Claude Code writes it as the sub-agent runs,
  and a record that is no JSON object makes the file unreadable.
- **A fork's copies.** On a fork, a sub-agent whose record's type is `fork`, the lines of the
  message that holds its `toolUseId`, and every line timed at or before the one of them that holds
  the call, are its parent's: a line that follows one of them follows none, and nothing is read off
  them but the working directory, which is the parent's. A fork whose file holds no line of that
  call copies none. A call a fork copied so stands in its parent's thread alone, and Pilot joins
  the sub-agent that call started ([`collection.md`](collection.md#a-publication)).
- **A Launch** (D257, D265), on a main thread, starts at the file's first line with a time, at the
  first such line after a cost line, and at a line that names another version of Claude Code than
  its Launch's. A killed process writes no cost line: the process that follows it under the same
  version joins its Launch, and one under another version starts its own, which opens with the
  lines with a time since the last that named the earlier version, where there are any, as the
  queue's lines a process writes before its first prompt name none. Lines with no time after a cost
  line start none, that line written a second time among them. A Launch none of whose lines names
  a version is not published, and a file where such a Launch received a Prompt is refused.
  - Its `started_at` is its first line's time, and its `ended_at` the time of its last line that
    carries one, the open Launch's the last so far, whatever the times of the lines before. The
    cost line's start and totals are not read.
  - Its components are `claude-code` at the version its lines name, the first that names one, and
    each plugin its process loaded, `plugin:<name>`, at the version first named under the home's
    `plugins/cache/<marketplace>/<name>/<version>/` by a skill's body's base directory, by a body
    an `invoked_skills` attachment shows again, by a snapshot's system prompt, or by the shape a
    Launch's first Call's requests name, which a session started as a plugin's agent has. A path a
    tool's result, the model or a prompt quotes is not read, and no component has a release time,
    which no line records.
- **A Prompt** (D259) is a main thread's `user` line whose source Claude Code names, in Claude
  Code's own word: `promptSource`, `typed`, `sdk`, `system`, `queued` or `suggestion_accepted`.
  Older files name it in other fields. On a line with no `promptSource` that is no `isMeta` one, the
  word is `turnOrigin`'s, else `origin.kind`'s, `human` read as `typed` and `task_notification` or
  `task-notification` as `system`; any other older word is kept as it is. Before Claude Code
  2.1.161 a prompt a person typed or a caller sent names none, and its line alone among those that
  name none carries `permissionMode`: its word is read off the session's `entrypoint`, `sdk` in a
  headless session, `sdk-cli` or another that opens with `sdk`, and `typed` in an interactive one,
  `cli`; any other entry point gives none.
  - Its time is that of the `enqueue` line that holds its text, the queue's first of that text,
    else its own. A `remove` that names a text takes it out of the queue, and a `popAll` and a cost
    line empty it.
  - A message Claude takes in the middle of a run is a Prompt as well: a main thread's
    `queued_command` attachment, a task notification (`commandMode` `task-notification`) read as
    `system` and a person's message (`prompt`) as `queued`. Its time is that of the `enqueue` line
    of its text, the queue's first, or where a `remove` took that out before the attachment was
    written, that of the first of its text the removes took out and none has claimed; else its own.
    It takes its text out of the queue, so a later prompt of that text keeps its own time. A cost
    line drops what the removes took out.
  - Not a Prompt: a line that names no source and is no older prompt, a person's interruption, a
    skill's `isMeta` words, a compaction's summary, a tool's result, a `queued_command` attachment
    of another mode, and the context a hook added, which arrives as an attachment.
- **A Call** is the `assistant` lines under one `message.id` whose model is no `<synthetic>` one,
  placed by the first of them, and follows the Prompt last received before it, where there is one.
  Its model, its `completed_at` and its usage are the last line's, its five token counts read there.
  - Its `sent_at` is the time of the `api-request` line its first line names by `requestRef`,
    among the request lines written since the one the Call before it named: a retry writes a
    request line again, and the Call names the last. It is none in a version that writes no
    request line, and where no such line stands before the Call's first line.
  - Its own choices, each where the version writes it. `requested_model` is the model asked for,
    none where it is the one that answered: the model a fallback left, by a `fallback` block among
    the Call's lines or a `model_refusal_fallback` line that names its `requestId`, else its
    lines' `requestedModel`. `effort`, `attributed_skill` and `attributed_plugin` are the last of
    its lines that names each. `thinking_tokens` is the last line's, a 0 published as 0, and
    `stop_reason` the last line's where it is none of the ordinary ends, `end_turn` and
    `tool_use`: any other end is published as the line names it.
  - Its `predecessor` is the nearest Call up its chain from its first line, and its `compaction`
    the boundary crossed on the way, by its place among the transcript's Compactions, the nearest
    where the chain crosses several. A line follows the one its `parentUuid` names, and a
    compaction's boundary the one its `logicalParentUuid` names. The chain goes on through a line
    wherever the file holds it, before or after, and passes the lines of its own Call and of one
    that began later in the file, so a predecessor is an earlier Call; a Call's chain is read at
    the file's end. A chain that ends at a line that follows none, names a line the file does not
    hold, or turns back on itself reaches no predecessor, and keeps a compaction it crossed.
  - Its `miss_cause` is read where it missed the cache its predecessor left: of the lesser of what
    that one left, the tokens it read from the cache and wrote to it, and the Call's own context,
    more than half was not read from the cache, and that context is at least nine tenths of what
    was left. The cause is the first that holds, in Miss Cause's order: `compaction`, its
    chain crossed one; `model`, the model that answered, or the effort where both name one, is
    another than its predecessor's; `ttl`, it was sent, or where it names no request completed,
    longer after its predecessor completed than what that one left lasts, an hour where it wrote to
    the cache that lasts an hour, else five minutes; `rewind`, its predecessor is not the Call
    before it; `version`, its first line names another version of Claude Code than its
    predecessor's; `system`, its request's `shapeHash` is another than its predecessor's
    request's; `history`, its request kept fewer messages than its predecessor's sent; else
    `unknown`.
  - Its `events`, each on the last Call whose first line stands before the Event's line, else on
    the transcript's first Call: `api_retry`, an `api_error` line, its `error.status` the detail;
    `api_error`, an `isApiErrorMessage` line, its `apiErrorStatus` the detail; and `interrupt`, a
    `user` line holding exactly Claude Code's words for a response the person interrupted. The
    first two are errors. A tool call the person interrupted is its Tool Call's, below.
- **A Compaction** is a `compact_boundary` line, made when it was written: its `trigger` and
  `tokens_before` are its `compactMetadata`'s, and `tokens_after` and `duration_ms` too where the
  version records them.
- **A Tool Call** is a `tool_use` block of a Call's lines, requested at its line's time. Its result
  is the first `tool_result` block that names its id, in a `user` line of the thread. A result that
  names no request of the file is dropped.
  - Its `first_argument` is an Agent call's `description`, which the model writes among its input
    in any order, and any other tool's first of its input that is text, its command, path or query;
    cut to its first line that is not blank. An input with no such text gives none.
  - Its `mcp_server` is the one its name is under, `mcp__<server>__<tool>`.
  - The result gives `returned_at`, `failed` (its `is_error`) and `result_characters`, the
    characters of its text: its string, or its `text` blocks together.
  - `exit_code` is Bash's alone: the `Exit code N` its error opens with. A Bash result that is no
    error reads 0, which is not published, Pilot holding an exit code only where it was not zero.
  - `interrupted` is read where Bash's `toolUseResult.interrupted` is true, and where an error opens,
    past an `Exit code N` line, with Claude Code's words for a person's interruption, `[Request
    interrupted by user for tool use]` or `Interrupted by user`, or its line names the
    `toolDenialKind` `interrupted`.
  - `denial_kind` is read where the result is an error and Claude Code says by what: `hook` where
    it opens `PreToolUse:<the call's tool> hook error:`, whatever its line names; else by the
    `toolDenialKind` its line names, `rule` for `permission-rule` and `person` for
    `user-rejected`, and any other in Claude Code's own word, Pilot adding a code it has not met.
    An `interrupted` is no denial, and a result that only quotes the hook's words is none.
  - `saved_characters` is read where the result opens in one of Claude Code's two wordings for an
    output saved to disk, never where it only quotes them. The first is `<persisted-output>` followed
    by "Output too large (<size>). Full output saved to: <path>". The second is "Error: result (N
    characters) exceeds maximum allowed tokens. Output has been saved to <path>.", where a count of
    lines can follow the characters. The full size is the saved file's characters, the file found
    under `projects` by the path's last four parts. Where that file is gone it is the characters the
    result states, and in the first wording it is then none.
  - Its `file_edits`, a successful Edit's or Write's of the file its input's `file_path` names,
    from the `cwd` its own line names, where a checkout holds it: the checkout's Repository and the
    path within it, a worktree under the checkout's `.claude/worktrees/<name>` the checkout's own.
    An Edit whose record holds the patch counts its `+` and `-` lines, one with none a line diff of
    its old and new text; a Write of a new file counts its content's lines as added, one over a
    file the patch's lines, and with no patch its content's lines as added and none removed. A
    failed call, and any other tool's, edits none.
  - Its `commits`, a successful Bash call's, each `git commit` its command makes, read as the shell
    reads it so far as it is words (`changes.py`): its directory a `-C` of its `git`, else the last
    `cd` before it, else its line's `cwd`, a commit in no checkout none; its subject its message's
    as git's `%s` gives it, the first paragraph with its lines joined by a space, from `-m`,
    `--message`, `-F -`'s here-document or a here-document's `cat`; its hash its own line's in the
    output, else, where the command makes one commit, Claude Code's `gitOperation.commit.sha` where
    that is 7 to 64 hex characters, else a `git log --oneline` after it in its Repository under its
    subject, else, of one commit alone, a `git rev-parse` after it, else none. A commit whose hash
    the reading holds as another's is not held again, a failed call makes none, and a later call's
    `git log --oneline` in the Repository gives its hash to the latest commit made there under that
    subject that showed none.
- **A Hook Run** is each hook a Stop hook's summary names, on a main thread, under the latest
  Prompt before the summary, with its `command` and `duration_ms`. It `failed` where a
  `hook_non_blocking_error` for the Stop event names its command and the summary's `toolUseID`,
  where the summary's `failedHookErrorIndexes` name its place, or where the summary names one hook
  and an error. Its `prevented_end` is the summary's `preventedContinuation`, the same on each of
  its runs. A tool's hooks log no summary, so a Hook Run is a Stop hook's alone.
- **A Call's Context Parts** are what it carried that no earlier Call of its Launch did, each where
  Claude Code records what the model saw: its kind, its `name` where the kind has several, and its
  `characters`.
  - A Launch's first Call, and a sub-agent's first, carries in this order: the `system_prompt` and
    the `tool_schemas`, from the `api-request-shape` line its request's `shapeHash` names, else
    from the Launch's `prompt_snapshot`, each where the line records one, of the system prompt's
    text, a snapshot's split marker aside, and of the tools' schemas as compact JSON; an
    `instruction_file` per file the `instructions` attachment before it lists, named by its path,
    of its content; the parts injected before it, below; and a `prompt` per Prompt the Launch
    received before it, of its characters, on a sub-agent's thread its task, the `user` lines
    before its first Call that are no `isMeta` one.
  - Every Call carries the parts injected before it, in the file's order from the last Call's
    first line, or the Launch's start, to its own. An `instructions` attachment once the Launch's
    first Call has begun, and a shown `nested_memory`, give an `instruction_file` per file, named
    by its path, of its content's characters; a shown `invoked_skills` a `skill_body` per skill,
    named by it, of its content's characters; any other attachment shown a `reminder` named by its
    type, of its `rendered` text's characters. A message taken in the middle of a run is none on a
    main thread, where it is a Prompt, and a `reminder` on a sub-agent's; an attachment never
    shown is none. A skill's body is a `skill_body` of its text's characters, named by the `skill`
    the `Skill` call its `sourceToolUseID` names asked for, none where it names no call or another
    tool's; a compaction's summary is a `compact_summary` of its text's characters.

The reader publishes no label: the labels, a main thread's `group` among them, are the labeller's
([below](#the-labeller)). It hands the labeller the Calls the labeller reads in what it took, the
`message.id` of every assistant line in the order of its first, a `<synthetic>` one and a fork's
copy of its parent's among them, which the facts publish no Call for.

A file the reader cannot turn into a publication raises `UnreadableError` with the reason: a line
that is not one it reads, named by its number, no line that names a working directory, a Launch that
received a Prompt and names no version, a sub-agent's record that is no JSON object, or facts the
publication's shape refuses.

## Whole or appended

A grown transcript is read from its boundary on, its tail, and published appended (D256). The walk
keeps a carry of each transcript it published (`carry.py`), in its memory alone. The carry holds the
file it was built on, the file's size, its time and the collector's version, and where the reading
stood at its **boundary**, the transcript's first Call that is not settled. A Call's facts are
settled once the next Call has begun, and its labels from where the labeller says: the boundary is
the file's last Call, or, where the labeller labelled the reading and named an earlier Call, that
one, and in a file with no Call the place its first would take. A reading keeps where it stood
before each Call's first line for that (`Read.stood`), until its batch is published. Of the reading
there, the carry holds:

- the byte the boundary's first line starts at;
- how many Calls, published Launches, Prompts and Compactions lie before it, from which the
  appended call's four places come ([`collection.md`](collection.md#a-publication));
- the `uuid` of the last line before it that carries one, and where the chain leads from that line
  as the lines before the boundary stand: the Call it reaches and the compaction it crosses, with
  what that Call left the next, all that a cache miss and its cause read of it;
- the ids the lines before it named, as the line they follow or the one a boundary continues,
  that the file held no line of there;
- the request lines written since the last one a Call named, each its id, its time, its shape and
  the messages it kept and sent, and on a request of a Launch's first Call what its shape's line
  records;
- the Events before the transcript's first Call;
- the directory and the environment the file named first;
- the Launch open there, with its start, its version, its end so far, where its lines with a time
  since the last that named a version began, the plugins it named and how many Prompts it
  received, and the latest of those Prompts, with its Hook Runs;
- what the lines before it record of the Context Parts of the boundary's Call where that is its
  Launch's first, or a sub-agent's: a snapshot's lengths, the instruction files and the prompts;
- the Context Parts injected before the boundary's Call;
- the prompts waiting in the queue, each as a digest of its text with its `enqueue` time;
- those a `remove` took out of the queue that no message taken in the middle of a run has claimed,
  held as the queue holds them;
- on a fork's thread, the call that started it, with the message that holds it and that line's
  time;
- the commits made before it whose hash no line has shown, each its making call's id, its
  Repository and its subject, which a later call's `git log` gives a hash;
- where the labeller labelled it, the checkpoint it handed back: the labeller's version and the
  stamp its labels were given under, its boundary's Call and the byte that Call's first line starts
  at, the checkpoint's text, which the collector never reads, that Call's place among the Calls the
  labeller reads, and how far the labeller's numbering of its Segments runs ahead of Pilot's;
- a digest of the file's bytes from the boundary's on, as they were read.

No id of any other line before the boundary is held, and of no Call but the one the chain leads
to: there is no map of the file's ids.

A transcript the inventory holds at exactly what its carry was built on is read from the
boundary's byte on (`read(transcript, settings, carry)`). It is published appended: the Calls from
the boundary on, the Launches that wrote a line from there on, the first of them with its Prompts
from there on and with the components it named before the boundary too, the Compactions made from
there on, and the four places. A Stop hook's summary follows its run's last Call, so its Prompt was
received before the boundary: where one from there on lies on the carry's Prompt, the first
Launch's Prompts open with that one, published again with its Hook Runs, and the boundary names its
place. Where a labeller answers for the transcript, the carry must also hold the checkpoint the
labeller handed back with its last labels, Pilot must hold its labels under that checkpoint's stamp
and the major of its version, and the labeller's stamps must give that stamp under that major now:
the labeller is then handed the Calls from that boundary on with the checkpoint, and the appended
publication carries their labels ([below](#the-labeller)). Every other transcript is published
whole. A transcript that has a carry and is published
whole instead, in the same walk, logs a line at `INFO`: "The transcript <session_id>[/<agent_id>],
<file>, is published whole, not from its boundary on: <reason>". The reasons are:

- "Pilot does not hold it as it was last read";
- "its file is no larger than the one last read", or "its file has other bytes before its old end":
  the bytes from the boundary's to the old end differ from those read then;
- "a line follows one before its boundary that is not the last there", its `parentUuid` naming a
  line that is neither the carry's nor one from the boundary's byte on, written before the
  boundary or later; "a compaction continues a line before its boundary that is not the last
  there", the same of a boundary's `logicalParentUuid`; and "a line before its boundary follows one
  written from it on", a line the carry awaits, since a chain behind the boundary goes on through
  it;
- "a tool's result names a request no line from its boundary on makes", "a skill's body names a
  request no line from its boundary on makes", and "a fallback names a request no Call from its
  boundary on answered";
- "a launch's first request names a shape no line from its boundary on records": a resumed process
  names the shapes an earlier one's lines record;
- "a Stop hook's summary lies on a prompt received before its boundary's launch";
- "its record names another fork's call than the one it was read with", a thread that became a
  fork's or stopped being one among them, and "a fork's line from its boundary on holds the call
  that started it", where the carry was read with no line of it;
- "reading it from its boundary on raised <the error's type>: <its message>";
- "a call shows the hash of a commit made before its boundary", a `git log` from the boundary's
  byte on that names a commit the carry holds with no hash;
- "Pilot refused it appended: <Pilot's reasons>", a `409` `PUBLICATION_NOT_APPENDABLE`, or "Pilot
  refused it appended with <status>: <its answer>", a `400` or a `413`;
- where a labeller answers: "the labeller handed back no checkpoint of its last reading", "Pilot
  does not hold its labels as the labeller last gave them", "the labeller would label it under
  another stamp or major now, which relabels it whole", and "the labeller answered whole: <its
  why>".

A rewrite before the boundary's byte is not seen there. The replay at rest, a whole publication
once the file has settled, follows it. A line that reaches back behind the boundary stays in what is
read until the next Call begins, so every walk that sees the file grow until then publishes it
whole. The second turn of a walk publishes whole without trying the carry. A transcript the
labeller answers `whole` for, or whose appended publication Pilot refuses, is read and labelled
whole once the rest of its batch is published.

**The bound.** The carries are kept up to `COLLECTOR_CARRY_TRANSCRIPTS` transcripts and
`COLLECTOR_CARRY_BYTES` of memory, a carry counted at about 1.5 KB and more for each id, request,
Event, Prompt, Hook Run, file, part, plugin and commit with no hash it holds, and for its
checkpoint. Past either, the carry of the transcript
whose file changed longest ago is forgotten first, and that transcript's next growth costs one
whole publication. A carry stays through a walk Pilot stopped answering, and goes when its
transcript is set aside. The carries are the walker's, read and written on its thread alone.

## The labeller

The labels are the workflow's labeller's, a command the collector runs (`labeller.py`, `Labeller`):
`COLLECTOR_LABELLER` with each call's verb appended, one JSON request on its stdin and one answer on
its stdout, under the labeller's contract 1, each call cut at `COLLECTOR_LABELLER_SECONDS`.
`{install_path}` in the command is the folder of the first `dev@aiworkflow` copy the home's
`plugins/installed_plugins.json` names, its path's last four parts,
`cache/<marketplace>/<plugin>/<version>`, taken under the home's `plugins`; a command that names no
`{install_path}` reads no such file. Nothing of the workflow is in the image: the labeller runs from
the home's copy. A request names the contract and the home as the collector sees it, its `projects`
and its `plugins`. Four verbs are called:

- **`stamps`**, at every walk, one call over every transcript listed: the stamp the labeller would
  give now for each, handed in its conversation with what the inventory gives for that conversation
  ([`collection.md`](collection.md#the-inventory)), a sub-agent's with the `agent_type` its record
  names, and each with the stamp Pilot holds; with the index the last call handed back, which the
  collector keeps in its memory. A conversation on the home that the inventory lacks is handed with
  no Sessions and no Documents. The answer names the labeller's version, a digest of its
  declarations, a digest of its file rules and each transcript's stamp.
- **`vocabularies`**, which the collector declares to Pilot, `PUT /api/collector/vocabularies`
  ([`collection.md`](collection.md#the-labellers-vocabularies)), once after it starts and again
  whenever the stamps come from another version or name another digest of the declarations than
  those it last declared, and before it publishes labels under another version than the one last
  declared. It keeps the labeller's groups, of which a main thread's publication takes the one its
  labels name as its `group`.
- **`label`**, over a batch: each transcript handed as `stamps` hands it, with its file's path, its
  Launches and the Calls the labeller reads in it, to label whole, or from the boundary of the
  checkpoint its carry holds, with that checkpoint ([above](#whole-or-appended)). The answer is a
  line a transcript, its labels with the checkpoint it hands back, the answer `whole`, or an error,
  `unreadable`, `calls_mismatch` or `internal`.
- **`classes`**, the class of each File it is handed ([below](#the-clones)).

A call that gives no answer the collector takes is the labeller not answering: no copy installed, a
refusal (exit 2, an `{"error": {"code", "detail"}}` on stdout), a crash (exit 1), no answer within
the time, or an answer that is not the call's. A `label` call cut short keeps the lines it gave
before the cut.

**The stamps and a relabel.** The stamps are asked after the listing and before the walk's plan,
and a transcript whose labels Pilot holds under another stamp than the one now, or under another
major of the labeller's version than the one answering, is behind and is labelled again whole
(D292): a conversation is relabelled whole only where the labeller's own major version, or its
stamp, differs from what its labels were written under. A minor or a patch of the labeller keeps
the labels Pilot holds, and what is labelled after it is labelled under the new version, which
`labelled_under` holds whole; a plugin release that leaves the labeller's version alone relabels
nothing. The labeller's version is its own, not its plugin's. A walk the labeller does not answer,
or whose vocabularies Pilot refuses, publishes as it would with none, logged at `WARNING` where the
reason is new, "The walk has no labeller's stamps, and publishes no label: <why>", and at `INFO`
"The labeller 1.0.1 answers again" once it does. A sub-agent's `agent_type` is kept by its record's
size, time and inode, so an unchanged record costs a `stat` a walk.

**A batch's labels.** Where the stamps answered, each transcript of a batch the labeller gave a
stamp is read, whole or appended, and the batch is labelled in one `label` call. Each transcript is
published with the labels of the rows its publication holds, the Calls of its own with their Tool
Calls and the Segments they fall in, renumbered from where Pilot holds the first, and of a main
thread its adopted group, under the version the answer names. A reading holds its file's bytes and
where it stood at each Call until its batch is published. A transcript the labeller gives no labels,
an error line or one a cut answer lacks, is logged, "The labeller gave the transcript
<session_id>[/<agent_id>], <file>, no labels: <why>", and published with its facts alone where its
file, the collector's version or the replay at rest made it differ, and left for the next walk,
among those the walk's line counts as left, where only the labeller did. A call that gives no
answer, or is cut short, labels nothing further in the walk, "The labeller labels nothing further in
this walk: <why>".

**Labels Pilot refuses.** Pilot refusing a transcript's labels has the vocabularies declared again,
once a walk, and the labels given again; refused once more, the transcript is published with its
facts alone, logged at `WARNING`, "Pilot refused the labels of the transcript
<session_id>[/<agent_id>], <file>, which are not given again until its file, the labeller's version
or its stamp changes: <why>", and its labels are held back until one of the three changes. What is
refused is in the collector's memory alone.

## The clones

After a walk's end the collector reads the commits of every Repository Pilot holds from bare clones
of the Gitblit mirror, the nightly mirror of the operator's GitHub repositories, which serves them
inside the cluster with no credential (`mirror.py`, `Clones`). A Repository's address is
`<COLLECTOR_MIRROR_URL>/<owner>/<name>.git`, the owners of `COLLECTOR_MIRROR_OWNERS` tried in their
order and the first that holds it cloned into `COLLECTOR_CLONES`, in a folder of its own renamed into
place once whole, so that a clone cut short is never read. A clone held is fetched, every branch as
the mirror has it. A name with a `/`, or `.` or `..`, is never cloned. git runs with no global or
system configuration and no prompt, each call cut at 900 s (`GIT_SECONDS`). A commit's lines show
once the mirror's daily sync has taken its push, and a commit never pushed shows none.

**A read.** Pilot is the cursor: the repositories' answer names what a read of each gave, and the
collector reads every commit of its clone's branches that is not among them, oldest first, all of
them where none is ([`collection.md`](collection.md#a-repositorys-commits)): its whole hash, its
author's time, its subject and its lines per file under git's rename detection, a moved file's on
its new path with the lines changed in it, a deleted file's as removed, a binary file's none, and a
merge commit none. A read goes to Pilot in one call, or past 32,000,000 bytes of commits
(`READ_BYTES`) in several, within Pilot's cap on a request. The clones are read at the first walk
after a start, then at the first walk once `COLLECTOR_MIRROR_SECONDS` have passed since the last
read began; a walk that left transcripts of its behind turn for the next waits for one that did not,
so that a Repository is read once every transcript on the home is published, since Pilot's tie
settles a commit's hash before its subject within one call alone. A transcript left waiting on the
labeller alone does not hold it back. A Repository whose clone cannot be made, fetched or read is
logged at `WARNING` where its reason is new, "The clone of the Repository <name> is not read:
<why>", tried again at the next read, and logged "The clone of the Repository <name> is read again"
once it is. A read ends with "The clones gave Pilot 9 commits in 2 calls, in 1.4 s", at `INFO` where
it gave any.

**The classes.** Then, where the labeller answered the stamps, the collector has it class the Files
Pilot holds with no class, or every File after a start and wherever the stamps' file rules differ
from those it last classed every File under, and gives Pilot every class at once
([`collection.md`](collection.md#the-files-classes)), "412 Files are classed under the labeller
1.0.1's file rules". A walk where nothing changed asks Pilot for no File beyond the knowledge that
none waits. A labeller that gives no classes is asked again at the next walk, and logged where its
reason is new, "No File is classed in this walk: the labeller did not answer: <why>". Classes Pilot refuses have the vocabularies declared
again and are given once more; refused again, no File is classed until the labeller's version or its
file rules change, "No File is classed until the labeller's version or its file rules change:
<why>".

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
  - `user`, a line that arrived as the person's and is no tool's result, with its `writer`, by its
    source as the facts read it, an older prompt's by its session's entry point:
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
1000, the user a fleet's home and its transcripts belong to, and exposes 3503. It installs `git`,
which the clones are made, fetched and read with. Its build fails where that user cannot load the
process. `PilotApp/Build-Main` runs the collector's tests in its stage `Test collector` and builds
the image in `Build pilot-collector image`
([`deployment.md`](deployment.md#how-a-change-gets-to-dev)).

## Testing it

`kc project test --project collector` runs `collector/tests`, which need no service, and
`kc project lint --project collector` its ruff, format check, mypy and vulture. The reader's rules
are pinned in `test_reader.py` and `test_appended.py`, the carry and its bound in `test_carry.py`,
the home in `test_home.py`, the walk's plan in `test_walk.py`, the reading in `test_reading.py`,
its route in `test_serve.py`, the process in `test_main.py`, which asks the running process for
a reading, the labeller's calls in `test_labeller.py`, the clones in `test_mirror.py` and the
settings in `test_settings.py`. `tests/support.py` builds a file's lines for one rule and
`settings()` the settings, inventing the three that have no default. `test_reader.py` also reads
the invented scenario's files, and two of its own, a resumed thread and a nested sub-agent, each as
the builder's whole publication of it but for the `labelling` and the `group`, which the reader
reads none of; `test_labeller.py` labels the scenario's files under the stub labeller as the
builder labels them.

The walk against Pilot's routes is the backend suite's, `backend/tests/collector/test_walk.py`. The
backend's dev group takes the collector by path, so that a walk publishes into a database of its own
per test. Pilot is served by werkzeug's `make_server` on `committed_app`, and the walk runs over the
invented scenario's files written to a home of the test's
([`collection.md`](collection.md#testing-it)), with the stub labeller as its labeller and a folder
of the home's as its mirror, so that a walk's publications carry the builder's labels and group. A
dependency the collector gains is locked twice, in `collector/` and in `backend/`, whose lock names
the collector's dependencies: the backend's `uv sync --locked` fails until both are.
