"""A transcript's file read into its publication (F152.3): whole, or from
its boundary on where the file grew (F152.15).

A transcript's file is JSON Lines, a line an object, and a line is read once
its newline is written. The facts are read off the lines in the file's order:

- **The collection record.** The file's size and time are the open file's
  own, the time cut to the microsecond Pilot holds one at, and the bytes read
  are those the size counts.
- **The place.** The working directory is the first line's that carries one,
  and a tool call's the one its line names. The repository is the checkout
  that holds it: the first folder under a checkout root, the roots' `scratch`
  folder aside. The environment is a main
  thread's alone: the id the managed instruction file opens with, in the
  `instructions` attachment that lists the files a process loaded, the first
  where the file names two.
- **A sub-agent's record**, the file beside its own: its type, the
  description its spawning call gave its task and that call's id, the
  record's `agentType`, `description` and `toolUseId`, each none where the
  record or the key is missing. A workflow's agent's names no call, nor
  does one older than Claude Code 2.1.144.
- **A fork's copies.** A fork, a sub-agent whose record's type is `fork`,
  opens its file with copies of its parent's lines, the message that holds
  the call that started it among them. The lines of that message, and every
  line timed at or before the one of them that holds the call, are its
  parent's: no line follows them, and of them the place alone is read, the
  directory the fork runs in as its parent does. A fork whose file holds no
  line of that call copies none.
- **A Launch**, on a main thread, starts at the file's first line with a time
  and at the first such line after a cost line, the line a process writes as
  it exits (DB 586). It ran the version of Claude Code its lines name, the
  first that names one; a Launch none of whose lines names a version is not
  published. A line that names another version is a later process's, one
  that follows a killed one: it starts a Launch, which opens with the lines
  with a time since the last that named the earlier version, where there
  are any, since they name none, as the queue's lines a process writes
  before its first prompt do. A process picked up under the same version
  joins the Launch before it.
- **A Launch's end** is the time of its last line that carries one, the
  open Launch's the last so far, whatever the times of the lines before.
  The cost line's start and totals are not read.
- **A Launch's components**: Claude Code at its version, and each plugin
  its process loaded, `plugin:<name>`, at the version the first of these
  lines names, a plugin's files lying under its cache's
  `plugins/cache/<marketplace>/<name>/<version>/`: a skill's body, or the
  body an `invoked_skills` attachment shows again, by its base directory;
  the system prompt a snapshot records, or the shape the requests of a
  Launch's first Call name, which a session started as a plugin's agent
  has. A path a tool's result, the model or a prompt quotes is not read.
  No line says when a version was released.
- **A Prompt** is a main thread's `user` line whose source Claude Code names:
  `promptSource`, or on a line with none that is no `isMeta` one, the older
  `turnOrigin` or `origin.kind`, read in the newer word where it means the
  same. An older prompt that names none, its line carrying the permission
  mode a prompt's line does, is read by its session's entry point: `sdk` in
  a headless one, `typed` in an interactive one. It was received when its
  `enqueue` line was written, where the queue holds one with its text, else
  at its own time.
- **A message Claude takes in the middle of a run** is a Prompt too: a main
  thread's `queued_command` attachment, a task notification
  (`commandMode` `task-notification`) read as `system` and a person's
  message (`prompt`) as `queued`. It was received when it was queued: its
  text's `enqueue` line, the queue's first of that text, or where a
  `remove` took that one out before the attachment was written, the first
  of that text the removes took out; else at its own time.
- **A Call** is the `assistant` lines under one `message.id`, placed by the
  first of them; its usage, model and completion time are the last one's.
- **A Call's own choices**, what Claude Code records of them, each from the
  version that writes it and none on older lines:
  - the model asked for, where it is not the one that answered: the model a
    fallback left, by a `fallback` block among the Call's or a
    `model_refusal_fallback` line that names the request the Call answered,
    else the lines' `requestedModel`;
  - the effort, and the skill and plugin it acted under: the lines'
    `effort`, `attributionSkill` and `attributionPlugin`;
  - its thinking tokens and how the response ended: the last line's
    `usage.output_tokens_details.thinking_tokens` and `stop_reason`, the
    end published where it was none of the ordinary ones, `end_turn` and
    `tool_use`.
- **A Call's sending time** is the time of the `api-request` line its first
  line names by `requestRef`, among the request lines written since the one
  the Call before it named: a retry writes a request line again, and the
  Call names the last. A Call names none where the version writes none, and
  is sent at none where no such line stands before its first line.
- **A cache miss** (DB 546): a Call missed the cache its predecessor left
  where more than half of the lesser of what that one left, the tokens it
  read from the cache and wrote to it, and the Call's own context was not
  read from the cache, and that context is at least nine tenths of what was
  left. Its cause is the first that holds, in Miss Cause's order:
  - `compaction`, its chain crossed one;
  - `model`, the model that answered or the effort is another than its
    predecessor's;
  - `ttl`, it was sent, or where it names no request it completed, longer
    after its predecessor completed than what that one left lasts: an hour
    where it wrote to the cache that lasts an hour, else five minutes;
  - `rewind`, its predecessor is not the Call before it;
  - `version`, its first line names another version of Claude Code than
    its predecessor's;
  - `system`, its request's `shapeHash`, a digest of the system prompt and
    the tools, is another than its predecessor's request's;
  - `history`, its request kept fewer messages, `keep`, than its
    predecessor's sent, those it kept and its `tail`;
  - else `unknown`.
- **An Event** is on the last Call whose first line stands before its line,
  else on the transcript's first Call:
  - `api_retry`, a `system` line of subtype `api_error`, an error Claude
    Code sends the request again after, its `error.status` the detail;
  - `api_error`, an `isApiErrorMessage` line, the response Claude Code
    wrote itself for a request that failed, its `apiErrorStatus` the
    detail;
  - `interrupt`, a `user` line holding a text block of exactly Claude
    Code's words for a response the person interrupted. A tool call the
    person interrupted is its Tool Call's, below.
- **A Compaction** is a `system` line of subtype `compact_boundary`, made
  when the line was written: `compactMetadata` gives its trigger and the
  tokens before it, and where the version records them the tokens after it
  and how long it took.
- **A Call's chain.** A line follows the one its `parentUuid` names, and a
  compaction's boundary the one its `logicalParentUuid` names. A Call's
  predecessor is the nearest Call up the chain from its first line, and its
  compaction the boundary crossed on the way, the nearest where the chain
  crosses several, by its place among the transcript's. Claude Code writes
  some lines before the line they follow, so a chain goes on through a line
  wherever the file holds it, and passes the lines of its own Call and of
  one that began later in the file: a predecessor is an earlier Call. A
  chain that ends at a line that follows none, names a line the file does
  not hold, or turns back on itself reaches no predecessor, and keeps a
  compaction it crossed.
- **A Tool Call** is a `tool_use` block of a Call's lines, requested at its
  line's time, and its result the first `tool_result` block that names its
  id, in a `user` line of the thread. Its argument is an Agent call's
  description, any other's first of its input that is text, which is its
  command, path or query, cut to its first line that is not blank, and its
  MCP server the one its name is under, `mcp__<server>__<tool>`. The result gives when
  it returned, whether it was an error, and the characters of its text.
  - An exit code is Bash's alone: the `Exit code N` its error opens with,
    and 0 where its result is no error, which is not published: Pilot
    holds an exit code where it was not zero, and refuses a 0.
  - It was interrupted where Bash's own record of the result says so, and
    where an error opens in Claude Code's words for a person's interruption.
  - Its output was saved to disk where the result opens in Claude Code's
    words for that, never where it quotes them. The full size is the saved
    file's characters, the file found under `projects` by the path the
    result names; else the characters the result states; else none.
  - It was denied where its result is an error and Claude Code says by
    what: by a hook, `hook`, where the result opens in Claude Code's words
    for a `PreToolUse` hook's block of that tool, whatever its line names;
    else by the `toolDenialKind` its result's line names, from 2.1.201: a
    permission rule, `rule`, for `permission-rule`, the person, `person`,
    for `user-rejected`, and any other in Claude Code's own word. A
    `toolDenialKind` of `interrupted` is no denial: the person interrupted
    the call.
  - A successful Edit or Write edited the file its input names, from its
    working directory, where a checkout holds it: a File Edit of the
    checkout's Repository and the path within it, a worktree under the
    checkout's `.claude/worktrees` the checkout's own, its lines by
    `changes.py`'s rule.
  - A successful Bash call made the commits its command makes
    (`changes.py`) in a directory a checkout holds, each with its subject
    and the hash its output shows, or a `git log` that follows it in that
    Repository, none where none does; a commit whose hash the reading holds
    as another's is not held again. A later call's `git log` in a Repository
    shows the hash of the latest commit made there under its line's subject
    that showed none. A failed call made none.
- **A Hook Run** is a hook command a Stop hook's summary names, a main
  thread's `system` line of subtype `stop_hook_summary` (2.1.250 on), on
  the latest Prompt before it, with the command's duration. It failed where
  an error the hook reported for the Stop event names its command and the
  summary's `toolUseID`, the summary's `failedHookErrorIndexes` name its
  place, or the summary names one hook and an error. It prevented the end
  where the summary says it prevented the run from going on. A tool's hooks
  log no summary.
- **The Context Parts of a Launch's first Call**, what it carried, each
  where Claude Code records what the model saw; on a sub-agent's thread,
  of its first Call:
  - the system prompt and the tools' schemas, `system_prompt` and
    `tool_schemas`, from the line of the shape its request's `shapeHash`
    names (2.1.300 on), else from the `prompt_snapshot` the Launch wrote
    before it (2.1.261 on, at a file's first Launch), each where the line
    records one: the characters of the system prompt's text, but for a
    snapshot's marker of where Claude Code splits it, and of the tools as
    JSON;
  - each instruction file the `instructions` attachment before it lists,
    an `instruction_file` named by its path, of its content's characters;
  - the parts injected before it, below;
  - each Prompt the Launch received before it, `prompt`, of the Prompt's
    characters: on a sub-agent's thread, its task, the `user` lines before
    its first Call that are no `isMeta` one.
- **The Context Parts injected before a Call**, all of a later Call's, in
  the file's order, from the last Call's first line, or the Launch's start,
  to the Call's own:
  - an attachment shown to the model, the line's `rendered` text (2.1.261
    on): an instruction file loaded once the Launch was under way,
    `nested_memory` or a later `instructions`, an `instruction_file` named
    by its path, of its content's characters; each skill's body an
    `invoked_skills` shows again, a `skill_body` named by its skill, of its
    content's characters; else a `reminder` named by its type, of the
    shown text's characters. A message taken in the middle of a run is no
    part on a main thread, where it is a Prompt, and an attachment never
    shown none;
  - a skill's body, the `isMeta` line whose `sourceToolUseID` names the
    `Skill` call it expanded, or that opens with Claude Code's words for one,
    a `skill_body` of its text's characters, named by the skill that call
    asked for: one expanded for a typed command names no call, and no skill;
  - a compaction's summary, the `isCompactSummary` line, a
    `compact_summary` of its text's characters.

**From the boundary on.** A reading leaves a carry (`carry.py`): where it
stood before the file's last Call, or, where the labeller labelled what it
took, before the first line of the labeller's boundary's Call, which is no
later (F152.15). It keeps where it stood before each Call's first line for
that. Given that carry, a file that grew is read
from the boundary's byte on, and its publication is an appended one: the
Calls from the boundary's on, the Launches that wrote a line from there on,
the first with its Prompts from there on and with the components it named
before the boundary too, the Compactions made from there on, and the four
places the boundary names. A Stop hook's summary follows
its run's last Call, so its Prompt was received before the boundary: where
one from there on lies on that Prompt, the first Launch's Prompts open with
it, published again with its Hook Runs, and the boundary names its place.
Such a reading holds no line before the boundary's byte but the one the
carry names, with where the chain leads from it as the lines before that
byte stand and what the Call it leads to left the next, the request lines
before it written since the last one a Call named, the commits made before
it that showed no hash, the Events before it where no Call is, the latest Prompt before it where the Launch open there
received it, with its Hook Runs, what the lines before it record of the
Context Parts of the boundary's Call where it is its Launch's first, the
Context Parts injected before that Call, and on a fork's thread the call
that started it, with the message that holds it and that line's time where
a line before the boundary does, so it stops, and the file is read whole,
where:

- the file is no larger than the one the carry was built on, or its bytes
  from the boundary's to its old end are other than those read then
  (F152.17);
- a line's `parentUuid`, or a compaction's `logicalParentUuid`, names a
  line that is neither the carry's nor one from the boundary's byte on, a
  tool's result or a skill's body names a request no line from that byte
  on makes, or a fallback's line one no Call from that byte on answered:
  each reaches behind the boundary, or names a line written later;
- a request of a Launch's first Call names a shape no line from the
  boundary's byte on records: a resumed process names the shapes an earlier
  one's lines record;
- a line is one the carry awaits, named by a line before the boundary that
  the file held no line of there: a chain before the boundary goes on
  through it;
- a Stop hook's summary lies on a Prompt received before the Launch open at
  the boundary;
- the record names another fork's call than the one the carry was read
  with, or the thread is no fork's where the carry was read as one, or one
  where it was not;
- a fork's line from the boundary's byte on holds the call that started it,
  where the carry was read with no line of it;
- a `git log` from the boundary's byte on shows the hash of a commit made
  before it, which no line before it showed.
"""

import json
import os
import posixpath
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from pilot_collection.publication import CallTokenKind, PublicationSchema
from pydantic import ValidationError

from pilot_collector import VERSION, changes
from pilot_collector.carry import (
    ROOT,
    Carry,
    Checkpoint,
    Fork,
    Lead,
    Left,
    Occurred,
    Open,
    Opening,
    Part,
    Prompted,
    Ran,
    Requested,
    Shape,
    Standing,
    Unhashed,
    digest,
)
from pilot_collector.home import Transcript, modified_at, record_of, saved_output
from pilot_collector.settings import Settings

CLAUDE_CODE = "claude-code"
"""The Component whose version a Launch's lines carry."""

_COST = "cost-state"
"""The type of the line a process writes as it exits."""

_PLUGIN = "plugin:"
"""What a plugin's Component's code opens with, before the plugin's name."""

_PLUGIN_FOLDER = re.compile(
    r"/plugins/cache/[^/\s]+/(?P<plugin>[^/\s]+)/(?P<version>[^/\s]+)/"
)
"""Where a plugin's files lie at a version: under its marketplace's folder
of the home's cache, a folder per version."""

_COMPACTED = "compact_boundary"
"""The subtype of the `system` line a compaction's boundary is."""

_REQUEST = "api-request"
"""The type of the line a request to the model is."""

_SHAPE = "api-request-shape"
"""The type of the line that records the system prompt and the tools a
request sent, by the `shapeHash` the request names: Claude Code writes it
once in a file, before the first request that names it."""

_SNAPSHOT = "prompt_snapshot"
"""The type of the attachment that records the system prompt and the tools
a process started with, never shown to the model."""

_SPLIT = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
"""The marker a snapshot's system prompt holds where Claude Code splits it,
which no request sends."""

_NESTED = "nested_memory"
"""The type of the attachment that loads an instruction file once a Launch
is under way."""

_INVOKED = "invoked_skills"
"""The type of the attachment that shows again the bodies of the skills
invoked before a compaction."""

_SKILL = "Skill"
"""The tool that loads a skill: Claude Code expands the skill its input
names into the skill's body, a line of its own."""

_SKILL_BODY = "Base directory for this skill:"
"""What a skill's body opens with where its skill has a folder: a typed
command's names no call."""

_FELL_BACK = "model_refusal_fallback"
"""The subtype of the `system` line that records a fallback: the model the
request asked for, and the one that answered it."""

_FALLBACK = "fallback"
"""The type of the block of a response that records the fallback it was
answered by."""

_API_ERROR = "api_error"
"""The subtype of the `system` line that records an API error Claude Code
sends the request again after."""

_INTERRUPTION = "[Request interrupted by user]"
"""The text of the block a `user` line records the person's interruption of
a response with."""

_ERRORS = {"api_retry": True, "api_error": True, "interrupt": False}
"""Whether an Event of each kind the collector reads counts as an error."""

_HOOKED = "stop_hook_summary"
"""The subtype of the `system` line that sums up the Stop hooks run at the
end of a Prompt's run."""

_HOOK_ERROR = "hook_non_blocking_error"
"""The type of the attachment that records an error a hook command
reported."""

_STOP = "Stop"
"""The event a Stop hook runs at."""

_DENIALS = {"permission-rule": "rule", "user-rejected": "person"}
"""The Denial Kind of a tool call by the `toolDenialKind` its result's line
names, where the collector has a word of its own for it."""

_HOOK = "hook"
"""The Denial Kind of a tool call a hook blocked."""

_STOPPED = "interrupted"
"""The `toolDenialKind` of a tool call the person interrupted."""

_FORK = "fork"
"""The type a sub-agent's record names a fork by: a sub-agent started with
a copy of its parent's context."""

_HOUR = timedelta(hours=1)
"""How long what a Call wrote to the cache that lasts an hour lasts."""

_FIVE_MINUTES = timedelta(minutes=5)
"""How long what a Call left in the cache lasts where it wrote nothing to
the cache that lasts an hour."""

_ORDINARY = (None, "end_turn", "tool_use")
"""How a response ends that is no Stop Reason's: a line written before the
end names none."""

SYNTHETIC = "<synthetic>"
"""The model of an `assistant` line Claude Code wrote itself: no response."""

_MANAGED = "Managed"
"""The type of the managed instruction file among those a process loaded."""

_SCRATCH = "scratch"
"""The folder of a checkout root that holds clones that are no repository of
the environment's."""

_WORKTREES = (".claude", "worktrees")
"""Where a checkout holds the worktrees Claude Code makes of it, a folder
each."""

_BASH = "Bash"
"""The tool whose result says how its command exited."""

_CHANGING = frozenset({changes.EDIT, changes.WRITE, _BASH})
"""The tools whose successful call can change a Repository."""

_MCP = "mcp"
"""What the name of an MCP server's tool opens with, before the server."""

_AGENT = "Agent"
"""The tool that starts a sub-agent: what it was given is its task's
description, which the model writes among its input in any order."""

_EXIT = re.compile(r"Exit code (-?\d+)(?:\n|\Z)")
"""How a failed command's result opens."""

_INTERRUPTED = re.compile(
    r"(?:Exit code -?\d+\n)?"
    r"(?:\[Request interrupted by user for tool use\]|Interrupted by user)"
    r"(?:\n|\Z)"
)
"""How the error opens that stands for the result of a tool call the person
interrupted, past a command's exit code."""

_SAVED = re.compile(
    r"<persisted-output>\nOutput too large \([^)\n]*\)\."
    r" Full output saved to: (?P<path>.+)\n"
)
"""How a result opens whose output was saved to disk: the size it gives is
rounded, in bytes."""

_SAVED_STATED = re.compile(
    r"Error: result \((?P<characters>[\d,]+) characters"
    r"(?: across [\d,]+ lines?)?\) exceeds maximum allowed tokens\."
    r" Output has been saved to (?P<path>.+)\.\n"
)
"""How a result opens whose output was saved to disk for its tokens, with
the output's characters."""

_NEWER = {
    "human": "typed",
    "task_notification": "system",
    "task-notification": "system",
}
"""An older field's word for a prompt's source, by the word `promptSource`
has for the same."""

_MID_RUN = "queued_command"
"""The type of the attachment a message Claude takes in the middle of a run
is written as."""

_TAKEN = {"task-notification": "system", "prompt": "queued"}
"""The source of a message taken in the middle of a run, by its
`commandMode`: the word Claude Code has for the same taken at a turn's
start."""

_INTERACTIVE = "cli"
"""The entry point of a session a person types in."""

_HEADLESS = "sdk"
"""What the entry point of a headless session opens with: `sdk-cli`, Claude
Code run with `--print`, and an SDK's."""

_BEFORE = -1
"""The place of a Call before a reading's first line: every Call the
reading takes began later."""

_CACHED = ("cache_write_5m", "cache_write_1h", "cache_read")
"""The Token Kinds of what a Call wrote to the cache and read from it."""

_MALFORMED = (ValueError, KeyError, TypeError, AttributeError)
"""What reading a line the collector does not read raises."""

_USAGE: dict[CallTokenKind, tuple[str, ...]] = {
    "input": ("input_tokens",),
    "cache_write_5m": ("cache_creation", "ephemeral_5m_input_tokens"),
    "cache_write_1h": ("cache_creation", "ephemeral_1h_input_tokens"),
    "cache_read": ("cache_read_input_tokens",),
    "output": ("output_tokens",),
}
"""Where a response's `usage` counts each Token Kind."""


class UnreadableError(Exception):
    """A transcript's file the collector cannot read, with the reason."""


class NotContinuedError(Exception):
    """A transcript's file that does not continue what a carry was built on,
    or whose lines reach behind the carry's boundary, with the reason: it is
    read whole."""


@dataclass(frozen=True)
class Read:
    """A transcript's file as one reading took it."""

    publication: PublicationSchema
    carry: Carry
    """What a reading of the file, grown, continues: where the reading
    stood before its last Call's first line."""
    calls: tuple[str, ...]
    """The Calls the labeller reads in what the reading took (`labeller.md`
    § Names both sides compute): the `message.id` of every assistant line,
    in the order of its first, a line Claude Code wrote itself and a fork's
    copy of its parent's among them, and of the file's last line where it
    parses with no newline yet."""
    stood: dict[str, Standing] = field(default_factory=dict)
    """Where the reading stood before the first line of each Call it took,
    by its `message.id`."""
    content: bytes = field(default=b"", repr=False)
    """The file's bytes the reading took, from the first on."""
    start: int = 0
    """Where in the file the first of them stands."""
    checkpoint: Checkpoint | None = None
    """The labeller's checkpoint the carry the reading continues holds, from
    whose boundary on the labeller labels what it took; none for a whole
    reading, and for one continuing a carry that holds none."""

    def carried(self, checkpoint: Checkpoint | None) -> Carry:
        """What a reading of the file, grown, continues, where the labeller
        labelled what this one took and handed back `checkpoint`: the carry
        stands before the first line of the checkpoint's boundary's Call,
        and holds it. The reading's own carry, with no checkpoint, where
        `checkpoint` is none or names a Call the reading took none of."""
        stands = None if checkpoint is None else self.stood.get(checkpoint.call)
        if stands is None:
            return self.carry
        return replace(
            self.carry,
            stands=stands,
            end=digest(self.content[stands.byte - self.start :]),
            checkpoint=checkpoint,
        )


@dataclass
class _Launch:
    started_at: datetime
    ended_at: datetime
    """The time of its last line taken that carries one."""
    version: str | None = None
    prompts: list[dict[str, Any]] = field(default_factory=list)
    kept: int = 0
    """The Prompts it received before the reading's first line."""
    unnamed: tuple[datetime, datetime] | None = None
    """Where its lines with a time since its last that named a version
    began: its end before them and the first one's time; none where its
    last such line names one, or none of its lines does."""
    plugins: dict[str, str] = field(default_factory=dict)
    """The version of each plugin its process loaded, by the plugin's
    name, in the order its lines first named them."""


@dataclass
class _ToolCall:
    tool: str
    argument: str | None
    requested_at: datetime
    returned_at: datetime | None = None
    failed: bool = False
    exit_code: int | None = None
    interrupted: bool = False
    result_characters: int | None = None
    saved_characters: int | None = None
    denial_kind: str | None = None
    skill: str | None = None
    """The skill a `Skill` call asked for."""
    directory: str | None = None
    """The working directory its line names."""
    given: dict[str, Any] | None = None
    """Its input, where it can change a Repository: an Edit's, a Write's, a
    Bash command's."""
    commits: list[dict[str, Any]] = field(default_factory=list)
    edits: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _Stop:
    """A line the chain up from another line passes: a line of a Call, a
    compaction's boundary, or one named before it was taken, which leads
    nowhere until it is."""

    call: str | None = None
    """The Call the line is of."""
    place: int = _BEFORE
    """That Call's place among the transcript's, from 0."""
    compaction: int | None = None
    """The boundary's place among the transcript's Compactions."""
    above: "_Stop | None" = None
    """The nearest such line up the chain from this one; none where the
    chain ends."""


@dataclass
class _Call:
    place: int
    """Its place among the transcript's Calls, from 0."""
    prompt: int | None
    request: Requested | None
    """The request line its first line names."""
    version: str | None
    """Claude Code's version its first line names."""
    chain: _Stop | None
    """The nearest stop up the chain from the line its first line
    follows."""
    completed_at: datetime
    model: str
    tokens: dict[str, int]
    thinking_tokens: int | None = None
    ended: str | None = None
    """How its last line says the response ended."""
    requested: str | None = None
    """The model its lines say the request asked for."""
    fell_back: str | None = None
    """The model asked for that a fallback left."""
    effort: str | None = None
    skill: str | None = None
    plugin: str | None = None
    tool_calls: dict[str, _ToolCall] = field(default_factory=dict)
    """The tool calls it requested, by Claude's id of the request."""
    events: list[Occurred] = field(default_factory=list)
    """The Events it marks, in the file's order."""
    parts: list[dict[str, Any]] = field(default_factory=list)
    """Its Context Parts."""

    @property
    def requested_model(self) -> str | None:
        """The model asked for, none where it is the one that answered."""
        asked = self.fell_back or self.requested
        return None if asked == self.model else asked

    @property
    def sent_at(self) -> datetime | None:
        return None if self.request is None else self.request.at

    @property
    def left(self) -> Left:
        """What it left the next Call on its chain, as its lines so far
        stand."""
        request = self.request
        return Left(
            place=self.place,
            completed_at=self.completed_at,
            model=self.model,
            effort=self.effort,
            version=self.version,
            cached=sum(self.tokens.get(kind, 0) for kind in _CACHED),
            hour=bool(self.tokens.get("cache_write_1h")),
            shape=None if request is None else request.shape,
            sent=None if request is None else request.sent,
        )


def written_at(line: dict[str, Any]) -> datetime | None:
    """A line's time, none on a line that carries none."""
    stamp = line.get("timestamp")
    return None if stamp is None else datetime.fromisoformat(stamp)


def is_a_tools_result(content: Any) -> bool:
    return isinstance(content, list) and any(
        block["type"] == "tool_result" for block in content
    )


def text_of(content: Any) -> str:
    """The words of a prompt or a result: a string, or the text blocks of a
    list."""
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block["type"] == "text")


def _interrupts(content: Any) -> bool:
    """Whether a `user` line's content records the person's interruption of
    a response."""
    return isinstance(content, list) and any(
        block["type"] == "text" and block["text"] == _INTERRUPTION for block in content
    )


def _status(status: Any) -> str | None:
    """An API error's status as an Event's detail, none where its line gives
    none."""
    return None if status is None else str(status)


def _denial(tool: str, said: str, denied: str | None) -> str | None:
    """The Denial Kind of a call of `tool` whose result is an error saying
    `said`, its line naming `denied` as its `toolDenialKind`: a hook's where
    the result opens in Claude Code's words for a hook's block of the tool,
    whatever its line names; else the kind its line names, in Claude Code's
    own word where the collector has none; none where the line names no kind
    of denial, or the person's interruption."""
    if said.startswith(f"PreToolUse:{tool} hook error:"):
        return _HOOK
    if denied is None or denied == _STOPPED:
        return None
    return _DENIALS.get(denied, denied)


def _prompt(prompt: Prompted) -> dict[str, Any]:
    """A Prompt a carry holds, as a reading takes one."""
    return {
        "received_at": prompt.received_at,
        "source": prompt.source,
        "characters": prompt.characters,
        "hook_runs": [asdict(run) for run in prompt.runs],
    }


def _prompted(prompt: dict[str, Any]) -> Prompted:
    """A Prompt a reading took, as a carry holds one."""
    return Prompted(
        prompt["received_at"],
        prompt["source"],
        prompt["characters"],
        tuple(Ran(**run) for run in prompt["hook_runs"]),
    )


def _plugins(said: str) -> list[tuple[str, str]]:
    """Each plugin and version the text names a folder of under the cache,
    in its order."""
    return [
        (named["plugin"], named["version"]) for named in _PLUGIN_FOLDER.finditer(said)
    ]


def _based(body: str) -> list[tuple[str, str]]:
    """The plugin and version a skill's body names as its base directory,
    where its skill lies under a plugin's cache: none for a body that opens
    otherwise."""
    if not body.startswith(_SKILL_BODY):
        return []
    return _plugins(body.removeprefix(_SKILL_BODY).split("\n", 1)[0] + "/")[:1]


def _schemas(tools: list[Any]) -> int | None:
    """The characters of the tools' schemas as JSON, none where there are
    none."""
    if not tools:
        return None
    return len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))


def _shape(shape: dict[str, Any]) -> Shape:
    """What a request shape's line records the request sent."""
    return Shape(len(text_of(shape["system"])) or None, _schemas(shape["tools"]))


def _snapshot(attachment: dict[str, Any]) -> Shape:
    """What a snapshot records of the system prompt and the tools a process
    started with: a newer version's records no tools."""
    system = sum(len(part) for part in attachment["systemPrompt"] if part != _SPLIT)
    return Shape(system or None, _schemas(attachment.get("tools") or []))


def _opened(
    opening: Opening, request: Requested | None, injected: tuple[Part, ...]
) -> list[dict[str, Any]]:
    """The Context Parts of a Launch's first Call, the lines before it
    recording `opening` and injecting `injected`, its first line naming
    `request`: the system prompt and the tools its request's shape sent,
    else those a snapshot records."""
    shown = None if request is None else request.sends
    if shown is None:
        shown = opening.snapshot
    parts: list[dict[str, Any]] = []
    if shown is not None and shown.system is not None:
        parts.append({"kind": "system_prompt", "characters": shown.system})
    if shown is not None and shown.tools is not None:
        parts.append({"kind": "tool_schemas", "characters": shown.tools})
    parts += [
        {"kind": "instruction_file", "name": path, "characters": characters}
        for path, characters in opening.files
    ]
    parts += [asdict(part) for part in injected]
    parts += [
        {"kind": "prompt", "characters": characters} for characters in opening.prompts
    ]
    return parts


def _shown(attachment: dict[str, Any], rendered: list[Any]) -> tuple[Part, ...]:
    """The Context Parts of an attachment shown to the model as `rendered`,
    but for a Launch's instruction files and a main thread's message."""
    kind = attachment["type"]
    if kind == _NESTED:
        loaded = attachment["content"]
        return (Part("instruction_file", len(loaded["content"]), attachment["path"]),)
    if kind == _INVOKED:
        return tuple(
            Part("skill_body", len(skill["content"]), skill["name"])
            for skill in attachment["skills"]
        )
    characters = sum(len(shown["content"]) for shown in rendered)
    return (Part("reminder", characters, kind),)


def _expands(line: dict[str, Any], content: Any) -> bool:
    """Whether an `isMeta` user line is a skill's body: it names the call
    it expanded, or opens as one that names none."""
    return line.get("sourceToolUseID") is not None or text_of(content).startswith(
        _SKILL_BODY
    )


def _skill(tool: str, given: dict[str, Any]) -> str | None:
    """The skill a `Skill` call asked for; none for another tool."""
    asked = given.get("skill") if tool == _SKILL else None
    return asked if isinstance(asked, str) else None


def _words(text: str) -> bytes:
    """A digest of a prompt's text, a lone surrogate among its characters
    included."""
    return digest(text.encode("utf-8", "surrogatepass"))


def source_of(line: dict[str, Any]) -> str | None:
    """A `user` line's source in Claude Code's word, none where it names
    none and is no older prompt."""
    named: str | None = line.get("promptSource")
    if named is not None:
        return named
    if line.get("isMeta"):
        return None
    older: str | None = line.get("turnOrigin")
    if older is None:
        older = (line.get("origin") or {}).get("kind")
    if older is None:
        return _entered(line)
    return _NEWER.get(older, older)


def _entered(line: dict[str, Any]) -> str | None:
    """The source of an older prompt that names none, by its session's entry
    point: `sdk` in a headless session, `typed` in an interactive one. Before
    Claude Code 2.1.161 a prompt a person typed or a caller sent names no
    source, and its line alone among a `user` line's that name none carries
    the permission mode; none for any other line, and for an entry point
    that is neither."""
    entered = line.get("entrypoint")
    if line.get("permissionMode") is None or not isinstance(entered, str):
        return None
    if entered == _INTERACTIVE:
        return "typed"
    return "sdk" if entered.startswith(_HEADLESS) else None


def _taken_out(
    waiting: tuple[tuple[bytes, datetime], ...], words: bytes
) -> tuple[tuple[tuple[bytes, datetime], ...], datetime | None]:
    """`waiting` with the first prompt of those words taken out, and the
    time that one was queued; `waiting` itself and none where it holds
    none."""
    for place, (queued, at) in enumerate(waiting):
        if queued == words:
            return waiting[:place] + waiting[place + 1 :], at
    return waiting, None


def _argument(tool: str, given: dict[str, Any]) -> str | None:
    """A tool's argument, cut to its first line that is not blank: an Agent
    call's description, none where it has none, and any other tool's first
    of its input that is text."""
    said = (
        given.get("description")
        if tool == _AGENT
        else next((value for value in given.values() if isinstance(value, str)), None)
    )
    if not isinstance(said, str):
        return None
    return next((line for line in said.splitlines() if line.strip()), None)


def _server(tool: str) -> str | None:
    """The MCP server a tool is of, by its name; none for another tool."""
    parts = tool.split("__")
    return parts[1] if len(parts) >= 3 and parts[0] == _MCP else None


def _saved(said: str, projects: Path) -> int | None:
    """The full size of the output a result says was saved to disk: the
    saved file's characters, its bytes read as UTF-8 and one that is none
    counted as a character; the characters the result states where the file
    is gone; none where the result says no such thing, or states none."""
    named = _SAVED.match(said) or _SAVED_STATED.match(said)
    if named is None:
        return None
    on_home = saved_output(projects, named["path"])
    if on_home is not None:
        try:
            return len(on_home.read_bytes().decode(errors="replace"))
        except FileNotFoundError:
            pass
    stated: str | None = named.groupdict().get("characters")
    return None if stated is None else int(stated.replace(",", ""))


class _Thread:
    """One thread's facts as its lines are taken, in the file's order, from
    the line a reading stands before."""

    def __init__(
        self,
        main: bool,
        projects: Path,
        settings: Settings,
        before: Standing,
        fork: Fork | None = None,
    ) -> None:
        self.directory = before.directory
        self.environment = before.environment
        self.launches: list[_Launch] = []
        """The Launches that wrote a line taken, the one open before the
        first among them."""
        self.calls: dict[str, _Call] = {}
        self.compactions: list[dict[str, Any]] = []
        """The Compactions whose boundary was taken."""
        self.stands = replace(before, fork=fork)
        """Where the reading stood before the last Call's first line."""
        self.stood: dict[str, Standing] = {}
        """Where it stood before each Call's first line, by its
        `message.id`."""
        self._fork = fork
        """On a fork's thread, the call that started it: which lines are
        its parent's copies."""
        self._main = main
        self._projects = projects
        self._settings = settings
        self._before = before
        self._exited = before.launch is None
        if before.launch is not None:
            opened = before.launch
            self.launches.append(
                _Launch(
                    opened.started_at,
                    opened.ended_at,
                    opened.version,
                    kept=opened.received,
                    unnamed=opened.unnamed,
                    plugins=dict(opened.plugins),
                )
            )
        self._published = before.launches
        """The Launches that exited and are published."""
        self._prompts = before.prompts
        self._queue = before.queue
        """The prompts waiting in the process's queue, in the order they
        arrived: a digest of each one's text and the time of its `enqueue`
        line."""
        self._removed = before.removed
        """The prompts a `remove` took out of the queue that no message
        taken in the middle of a run has claimed, in the order they were
        taken out, as the queue holds them."""
        self._requested: dict[str, _ToolCall] = {}
        """The tool calls requested, by Claude's id of the request."""
        self._link = before.link
        """The `uuid` of the last line taken that carries one."""
        self._requests = before.requests
        """The request lines taken since the last one a Call named, in the
        file's order."""
        self._latest: _Call | None = None
        """The Call whose first line was taken last."""
        self._early = list(before.events)
        """The Events taken where no Call is, which the transcript's first
        Call marks."""
        self._answering: dict[str, _Call] = {}
        """The Calls taken, by the API's id of the request each answered,
        `requestId`."""
        self._prompt = None if before.prompt is None else _prompt(before.prompt)
        """The latest Prompt taken, else the carry's: the one a Stop hook's
        summary lies on."""
        self._carried = self._prompt
        """The Prompt the carry holds, received before the boundary."""
        self.reopened = False
        """Whether the Prompt the carry holds is published again: a Stop
        hook's summary from the boundary on lies on it."""
        self._failing: dict[str, set[str]] = {}
        """The commands that reported an error at the Stop event, by the
        `toolUseID` of the run of the Stop hooks they are of."""
        self._shapes: dict[str, Shape] = {}
        """What each request shape's line taken records, by its
        `shapeHash`."""
        self.unhashed: list[tuple[Unhashed, dict[str, Any] | None]] = [
            (made, None) for made in before.unhashed
        ]
        """The commits made whose hash no line showed, in the order they
        were made, each with its publication, none for one made before the
        reading's first line."""
        self._shas: set[tuple[str, str]] = set()
        """The Repository and the hash of each commit held."""
        self._agents: dict[str, list[tuple[str, str]]] = {}
        """The plugins and versions each request shape's system prompt
        names under the cache, by its `shapeHash`: a plugin's agent's, where
        the session was started as one."""
        self._opening = before.opening if before.byte or main else Opening()
        """What the lines taken record of the Context Parts of the open
        Launch's first Call, none once it began: on a sub-agent's thread, of
        its first Call."""
        self._injected = before.injected
        """The Context Parts the lines taken injected since the last Call's
        first line, or the open Launch's start, which the next Call
        carries."""
        self._leads: dict[str, _Stop | None] = {}
        """The nearest stop at or up the chain from each line taken, by its
        `uuid`, and from the line the reading stands after."""
        self._awaited: dict[str, _Stop] = {}
        """The lines named that no line taken is yet, in the order they were
        named: the stop each stands for."""
        if before.link is not None:
            led = before.leads
            above = None if led.call is None else _Stop(led.call)
            if led.compaction is not None:
                above = _Stop(compaction=led.compaction, above=above)
            self._leads[before.link] = above

    def take(self, line: dict[str, Any], byte: int) -> None:
        """Take the line that starts at `byte` of the file."""
        kind = line["type"]
        at = written_at(line)
        named = line.get("uuid")
        if named in self._before.awaited:
            raise NotContinuedError(
                "a line before its boundary follows one written from it on"
            )
        if self.directory is None and "cwd" in line:
            self.directory = line["cwd"]
        if self._copied(line, kind, at):
            if named is not None:
                self._leads[named] = None
                self._awaited.pop(named, None)
            return
        chain = self._above(
            line.get("parentUuid"),
            "a line follows one before its boundary that is not the last there",
        )
        answers = (
            kind == "assistant"
            and at is not None
            and line["message"]["model"] != SYNTHETIC
        )
        if answers and line["message"]["id"] not in self.calls:
            self.stands = self.stood[line["message"]["id"]] = self._standing(byte)
        stop = chain
        if answers:
            answered = line["message"]["id"]
            stop = _Stop(answered, self._placed(answered), above=chain)
        elif at is not None and kind == "system" and line.get("subtype") == _COMPACTED:
            stop = self._compacted(line, at)
        if named is not None:
            self._link = named
            self._leads[named] = stop
            awaited = self._awaited.pop(named, None)
            if awaited is not None:
                awaited.above = stop
        if kind == _COST:
            if not self._exited and self.launches[-1].version is not None:
                self._published += 1
            self._exited = True
            self._queue = ()
            self._removed = ()
        elif kind == _SHAPE:
            shape = line["shape"]
            self._shapes[line["shapeHash"]] = _shape(shape)
            self._agents[line["shapeHash"]] = _plugins(text_of(shape["system"]))
        if at is None:
            return
        if self._main:
            self._timed(line.get("version"), at)
        if kind == "assistant":
            if line.get("isApiErrorMessage"):
                self._occurred("api_error", at, _status(line.get("apiErrorStatus")))
            self._answered(line, at, chain)
        elif kind == _REQUEST:
            self._requests += (self._request(line, at),)
        elif kind == "system" and line.get("subtype") == _FELL_BACK:
            self._fell_back(line)
        elif kind == "system" and line.get("subtype") == _API_ERROR:
            self._occurred("api_retry", at, _status(line["error"].get("status")))
        elif kind == "user":
            content = line["message"]["content"]
            if is_a_tools_result(content):
                self._returned(
                    content, line.get("toolUseResult"), line.get("toolDenialKind"), at
                )
            elif _interrupts(content):
                self._occurred("interrupt", at)
            elif line.get("isCompactSummary"):
                self._injected += (Part("compact_summary", len(text_of(content))),)
            elif line.get("isMeta") and _expands(line, content):
                said = text_of(content)
                self._expanded(line.get("sourceToolUseID"), len(said))
                self._loaded(_based(said))
            elif self._main:
                self._prompted(line, content, at)
            elif not line.get("isMeta"):
                self._carries(len(text_of(content)))
        elif kind == "attachment":
            self._attached(line, at)
        elif not self._main:
            return
        elif kind == "queue-operation":
            self._queued(line, at)
        elif kind == "system" and line.get("subtype") == _HOOKED:
            self._hooked(line)

    def _copied(self, line: dict[str, Any], kind: str, at: datetime | None) -> bool:
        """Whether the line, of that kind and written `at`, is a copy of its
        parent's on a fork's thread: a line of the message that holds the
        call that started it, or one timed at or before that call's line."""
        fork = self._fork
        if fork is None or fork.message is None:
            return False
        if kind == "assistant" and line["message"]["id"] == fork.message:
            return True
        return at is not None and fork.at is not None and at <= fork.at

    def _timed(self, version: str | None, at: datetime) -> None:
        """A main thread's line written `at`, naming that version of Claude
        Code where it names one: of the Launch open, else the first of one
        it starts. A line that names another version than the open Launch's
        starts one, which opens with the lines since the last that named the
        earlier version, where there are any."""
        launch = None if self._exited else self.launches[-1]
        started = at
        if launch is not None and _changed(launch.version, version):
            if launch.unnamed is not None:
                launch.ended_at, started = launch.unnamed
            self._published += 1
            launch = None
        if launch is None:
            launch = _Launch(started, started)
            self.launches.append(launch)
            self._exited = False
            self._opening = Opening()
            self._injected = ()
        if version is not None:
            launch.unnamed = None
            launch.version = launch.version or version
        elif launch.version is not None and launch.unnamed is None:
            launch.unnamed = (launch.ended_at, at)
        launch.ended_at = at

    def _loaded(self, plugins: list[tuple[str, str]]) -> None:
        """The plugins the open Launch's process loaded, at those versions:
        each its Launch's at the first version named."""
        if self._main:
            named = self.launches[-1].plugins
            for plugin, version in plugins:
                named.setdefault(plugin, version)

    def _standing(self, byte: int) -> Standing:
        """Where the reading stands before the line that starts at `byte`,
        none of it taken."""
        opened = None if self._exited else self.launches[-1]
        received = 0 if opened is None else opened.kept + len(opened.prompts)
        calls = self._before.calls + len(self.calls)
        return Standing(
            byte=byte,
            calls=calls,
            launches=self._published,
            prompts=self._prompts,
            compactions=self._before.compactions + len(self.compactions),
            link=self._link,
            leads=ROOT
            if self._link is None
            else self._reached(self._leads[self._link], calls),
            awaited=(self._before.awaited if self._before.byte else ())
            + tuple(self._awaited),
            requests=self._requests,
            events=tuple(self._early),
            directory=self.directory,
            environment=self.environment,
            launch=None
            if opened is None
            else Open(
                opened.started_at,
                opened.version,
                received,
                opened.ended_at,
                opened.unnamed,
                tuple(opened.plugins.items()),
            ),
            prompt=None
            if not received or self._prompt is None
            else _prompted(self._prompt),
            opening=self._opening,
            injected=self._injected,
            queue=self._queue,
            removed=self._removed,
            fork=self._fork,
            unhashed=tuple(made for made, _ in self.unhashed),
        )

    def _placed(self, message_id: str) -> int:
        """The place among the transcript's Calls of the one of that id,
        from 0: the next where no line of it was taken."""
        began = self.calls.get(message_id)
        return self._before.calls + len(self.calls) if began is None else began.place

    def _above(self, follows: str | None, behind: str) -> _Stop | None:
        """The nearest stop at or up the chain from the line `follows`
        names: none from no line, and from a line not taken the stop that
        stands for it until it is. A reading from a boundary on stops at
        such a line, which lies `behind` it or is written later."""
        if follows is None:
            return None
        if follows in self._leads:
            return self._leads[follows]
        if self._before.byte:
            raise NotContinuedError(behind)
        return self._awaited.setdefault(follows, _Stop())

    def _reached(self, stop: _Stop | None, place: int) -> Lead:
        """Where the chain leads from `stop` up, for a Call at `place`
        among the transcript's, as the lines taken stand: the nearest Call
        that began before it, and the nearest compaction crossed on the way
        there, or to where the chain ends or turns back on itself."""
        compaction = None
        passed: set[int] = set()
        while stop is not None and id(stop) not in passed:
            if stop.call is not None and stop.place < place:
                return Lead(stop.call, compaction, self._left(stop.call))
            passed.add(id(stop))
            compaction = compaction or stop.compaction
            stop = stop.above
        return Lead(None, compaction)

    def _left(self, message_id: str) -> Left | None:
        """What the Call of that id left the next: a Call taken, or the one
        the chain leads to from the line the reading stands after."""
        call = self.calls.get(message_id)
        return self._before.leads.left if call is None else call.left

    def chain(self, call: _Call) -> Lead:
        """The Call's predecessor, what it left, and the compaction the
        Call's chain crossed."""
        return self._reached(call.chain, call.place)

    def _compacted(self, line: dict[str, Any], at: datetime) -> _Stop:
        """A Compaction, its boundary written `at`: the boundary's stop,
        from which the chain goes on to the line its `logicalParentUuid`
        names."""
        continues = self._above(
            line.get("logicalParentUuid"),
            "a compaction continues a line before its boundary that is not the"
            " last there",
        )
        made = line["compactMetadata"]
        self.compactions.append(
            {
                "at": at,
                "trigger": made["trigger"],
                "tokens_before": made["preTokens"],
                "tokens_after": made.get("postTokens"),
                "duration_ms": made.get("durationMs"),
            }
        )
        place = self._before.compactions + len(self.compactions)
        return _Stop(compaction=place, above=continues)

    def _queued(self, line: dict[str, Any], at: datetime) -> None:
        """A prompt's text is words: content that is none is no prompt's."""
        operation, content = line["operation"], line.get("content")
        if operation == "popAll":
            self._queue = ()
        elif not isinstance(content, str):
            return
        elif operation == "enqueue":
            self._queue += ((_words(content), at),)
        elif operation == "remove":
            words = _words(content)
            self._queue, queued = _taken_out(self._queue, words)
            if queued is not None:
                self._removed += ((words, queued),)

    def _waited(self, text: str) -> datetime | None:
        """Take the first prompt of that text out of the queue: the time
        it arrived, none where the queue holds none."""
        self._queue, queued = _taken_out(self._queue, _words(text))
        return queued

    def _attached(self, line: dict[str, Any], at: datetime) -> None:
        attachment = line["attachment"]
        if attachment["type"] == _SNAPSHOT:
            for said in attachment["systemPrompt"]:
                self._loaded(_plugins(said))
            if self._opening is not None and self._opening.snapshot is None:
                self._opening = replace(self._opening, snapshot=_snapshot(attachment))
        elif attachment["type"] == "instructions":
            loaded = tuple(
                (instructions["path"], len(instructions["content"]))
                for instructions in attachment["files"]
            )
            if self._opening is None:
                self._injected += tuple(
                    Part("instruction_file", characters, path)
                    for path, characters in loaded
                )
            else:
                files = self._opening.files + loaded
                self._opening = replace(self._opening, files=files)
        elif line.get("rendered") and not (
            self._main and attachment["type"] == _MID_RUN
        ):
            self._injected += _shown(attachment, line["rendered"])
        if attachment["type"] == _INVOKED:
            for skill in attachment["skills"]:
                self._loaded(_based(skill["content"]))
        if not self._main:
            return
        if attachment["type"] == _MID_RUN:
            self._taken(attachment, at)
            return
        if attachment["type"] == _HOOK_ERROR:
            if attachment["hookEvent"] == _STOP:
                failing = self._failing.setdefault(attachment["toolUseID"], set())
                failing.add(attachment["command"])
            return
        if self.environment is not None or attachment["type"] != "instructions":
            return
        pattern = self._settings.COLLECTOR_ENVIRONMENT_PATTERN
        for loaded in attachment["files"]:
            if loaded["type"] != _MANAGED:
                continue
            named = pattern.match(loaded["content"])
            if named is not None:
                self.environment = named.group(1)
                return

    def _prompted(self, line: dict[str, Any], content: Any, at: datetime) -> None:
        source = source_of(line)
        if source is None:
            return
        text = text_of(content)
        self._received(source, text, self._waited(text) or at)

    def _taken(self, attachment: dict[str, Any], at: datetime) -> None:
        """A message Claude took in the middle of a run, a Prompt where its
        `commandMode` says which: queued where the queue holds its text, or
        a `remove` took that out before the attachment was written."""
        source = _TAKEN.get(attachment.get("commandMode") or "")
        if source is None:
            return
        text = text_of(attachment["prompt"])
        words = _words(text)
        self._queue, queued = _taken_out(self._queue, words)
        if queued is None:
            self._removed, queued = _taken_out(self._removed, words)
        self._received(source, text, queued or at)

    def _received(self, source: str, text: str, at: datetime) -> None:
        """A Prompt of the Launch open, `text` from `source`, received `at`."""
        self._prompts += 1
        self._prompt = {
            "received_at": at,
            "source": source,
            "characters": len(text),
            "hook_runs": [],
        }
        self.launches[-1].prompts.append(self._prompt)
        self._carries(len(text))

    def _carries(self, characters: int) -> None:
        """A Prompt of that length, or a sub-agent's task, which the open
        Launch's first Call carries where it has not begun."""
        if self._opening is not None:
            prompts = self._opening.prompts + (characters,)
            self._opening = replace(self._opening, prompts=prompts)

    def _expanded(self, source: str | None, characters: int) -> None:
        """A skill's body of that length, expanded for the `Skill` call
        `source` names. A reading from a boundary on stops at one that
        names a call it took no line of, which may lie behind it."""
        asked = None if source is None else self._requested.get(source)
        if source is not None and asked is None and self._before.byte:
            raise NotContinuedError(
                "a skill's body names a request no line from its boundary on makes"
            )
        skill = None if asked is None else asked.skill
        self._injected += (Part("skill_body", characters, skill),)

    def _hooked(self, line: dict[str, Any]) -> None:
        """A Stop hook's summary: a Hook Run of each command it names, on
        the latest Prompt. A reading from a boundary on stops at one that
        lies on a Prompt received before the Launch open there."""
        failing = self._failing.pop(line["toolUseID"], set())
        prompt = self._prompt
        if prompt is None:
            if self._prompts:
                raise NotContinuedError(
                    "a Stop hook's summary lies on a prompt received before its"
                    " boundary's launch"
                )
            return
        if prompt is self._carried and not self.reopened:
            opened = self.launches[0]
            opened.prompts.insert(0, prompt)
            opened.kept -= 1
            self.reopened = True
        hooks = line["hookInfos"]
        errors = bool(line.get("hookErrors"))
        failed = line.get("failedHookErrorIndexes") or []
        for place, hook in enumerate(hooks):
            prompt["hook_runs"].append(
                {
                    "command": hook["command"],
                    "duration_ms": hook["durationMs"],
                    "failed": hook["command"] in failing
                    or place in failed
                    or (errors and len(hooks) == 1),
                    "prevented_end": line.get("preventedContinuation") is True,
                }
            )

    def _answered(
        self, line: dict[str, Any], at: datetime, chain: _Stop | None
    ) -> None:
        """A line of a response, which follows a line `chain` is the
        nearest stop from."""
        message = line["message"]
        if message["model"] == SYNTHETIC:
            return
        usage = message["usage"]
        model, tokens = message["model"], _tokens(usage)
        call = self.calls.get(message["id"])
        if call is None:
            call = _Call(
                self._placed(message["id"]),
                self._prompts or None,
                self._sent(line.get("requestRef")),
                line.get("version"),
                chain,
                at,
                model,
                tokens,
                events=self._early,
            )
            self._early = []
            if self._opening is None:
                call.parts = [asdict(part) for part in self._injected]
            else:
                call.parts = _opened(self._opening, call.request, self._injected)
                self._opening = None
            self._injected = ()
            self._latest = self.calls[message["id"]] = call
            answered = line.get("requestId")
            if answered is not None:
                self._answering.setdefault(answered, call)
        else:
            call.completed_at, call.model, call.tokens = at, model, tokens
        call.thinking_tokens = (usage.get("output_tokens_details") or {}).get(
            "thinking_tokens"
        )
        call.ended = message.get("stop_reason")
        call.requested = _named(line, "requestedModel", call.requested)
        call.effort = _named(line, "effort", call.effort)
        call.skill = _named(line, "attributionSkill", call.skill)
        call.plugin = _named(line, "attributionPlugin", call.plugin)
        for block in message["content"]:
            if block["type"] == _FALLBACK:
                call.fell_back = call.fell_back or block["from"]["model"]
            elif block["type"] == "tool_use" and block["id"] not in self._requested:
                argument = _argument(block["name"], block["input"])
                skill = _skill(block["name"], block["input"])
                asked = _ToolCall(
                    block["name"],
                    argument,
                    at,
                    skill=skill,
                    directory=line.get("cwd"),
                    given=block["input"] if block["name"] in _CHANGING else None,
                )
                self._requested[block["id"]] = call.tool_calls[block["id"]] = asked

    def _fell_back(self, line: dict[str, Any]) -> None:
        """A fallback's record: the model asked for, of the Call that
        answered the request it names. A reading from a boundary on stops
        at one that names no Call it took, which may lie behind it."""
        call = self._answering.get(line["requestId"])
        if call is not None:
            call.fell_back = call.fell_back or line["originalModel"]
        elif self._before.byte:
            raise NotContinuedError(
                "a fallback names a request no Call from its boundary on answered"
            )

    def _request(self, line: dict[str, Any], at: datetime) -> Requested:
        """A request line, written `at`, as the Call that names it reads it:
        on a request of a Launch's first Call, with what its shape's line
        records it sent. A reading from a boundary on stops at one whose
        shape no line it took records, which may lie behind it."""
        shape = line.get("shapeHash")
        sends = None
        if self._opening is not None and shape is not None:
            sends = self._shapes.get(shape)
            if sends is None and self._before.byte:
                raise NotContinuedError(
                    "a launch's first request names a shape no line from its"
                    " boundary on records"
                )
            self._loaded(self._agents.get(shape, []))
        kept = line.get("keep")
        return Requested(
            line["id"],
            at,
            shape,
            kept,
            None if kept is None else kept + len(line.get("tail") or []),
            sends,
        )

    def _sent(self, request: str | None) -> Requested | None:
        """The request line of that `id` among those taken since the last
        one a Call named, which it and those before it are no longer; none
        where none is."""
        for place, asked in enumerate(self._requests):
            if asked.id == request:
                self._requests = self._requests[place + 1 :]
                return asked
        return None

    def _occurred(self, kind: str, at: datetime, detail: str | None = None) -> None:
        """An Event of that kind, on the Call whose first line was taken
        last, else held for the first."""
        event = Occurred(kind, at, detail)
        if self._latest is None:
            self._early.append(event)
        else:
            self._latest.events.append(event)

    def _returned(
        self,
        content: list[dict[str, Any]],
        record: Any,
        denied: str | None,
        at: datetime,
    ) -> None:
        """The results a line carries, each its tool call's where the thread
        requested one of its id that no result has reached; `record` is the
        tool's own record of the result, and `denied` the `toolDenialKind`
        the line names."""
        for block in content:
            if block["type"] != "tool_result":
                continue
            asked = self._requested.get(block["tool_use_id"])
            if asked is None and self._before.byte:
                raise NotContinuedError(
                    "a tool's result names a request no line from its boundary on makes"
                )
            if asked is None or asked.returned_at is not None:
                continue
            said = text_of(block["content"])
            asked.returned_at = at
            asked.failed = block.get("is_error") is True
            asked.result_characters = len(said)
            asked.saved_characters = _saved(said, self._projects)
            if asked.tool == _BASH:
                exited = _EXIT.match(said) if asked.failed else None
                if exited is not None:
                    asked.exit_code = int(exited.group(1))
                elif not asked.failed:
                    asked.exit_code = 0
            asked.interrupted = (
                isinstance(record, dict) and record.get("interrupted") is True
            ) or (
                asked.failed
                and (_INTERRUPTED.match(said) is not None or denied == _STOPPED)
            )
            if asked.failed:
                asked.denial_kind = _denial(asked.tool, said, denied)
            elif asked.given is not None:
                self._changed(block["tool_use_id"], asked, asked.given, record, said)

    def _changed(
        self,
        made_by: str,
        asked: _ToolCall,
        given: dict[str, Any],
        record: Any,
        said: str,
    ) -> None:
        """What a successful call of that id, `given` its input, changed of a
        Repository, its result saying `said` and `record` the tool's own
        record of it."""
        if asked.tool != _BASH:
            kept = _kept(asked.directory, given["file_path"], self._settings)
            if kept is not None:
                added, removed = changes.edited(asked.tool, given, record)
                asked.edits.append(
                    {
                        "repository": kept[0],
                        "path": kept[1],
                        "lines_added": added,
                        "lines_removed": removed,
                    }
                )
        elif "git" in given["command"]:
            command = changes.command(given["command"], asked.directory)
            self._committed(made_by, asked, command, said, record)

    def _committed(
        self,
        made_by: str,
        asked: _ToolCall,
        command: changes.Command,
        said: str,
        record: Any,
    ) -> None:
        """The commits the Bash call of that id made, and the hashes its
        `git log`s show of commits earlier calls made."""
        logs = [
            (place, _repository(directory, self._settings))
            for place, directory in command.logs
            if directory is not None
        ]
        logged = changes.logged(said) if logs else []
        for made in changes.made(command, said, record):
            repository = _repository(made.directory, self._settings)
            if repository is None:
                continue
            sha = made.sha
            if sha is None and any(
                place > made.place and logged_in == repository
                for place, logged_in in logs
            ):
                sha = next(
                    (
                        hashed
                        for hashed, line in logged
                        if changes.names(line, made.subject)
                        and (repository, hashed) not in self._shas
                    ),
                    None,
                )
            if sha is not None and (repository, sha) in self._shas:
                continue
            commit = {"repository": repository, "subject": made.subject, "sha": sha}
            asked.commits.append(commit)
            if sha is None:
                self.unhashed.append(
                    (Unhashed(made_by, repository, made.subject), commit)
                )
            else:
                self._shas.add((repository, sha))
        repositories = {repository for _, repository in logs if repository is not None}
        for hashed, line in logged:
            self._shown(made_by, repositories, hashed, line)

    def _shown(self, made_by: str, repositories: set[str], sha: str, line: str) -> None:
        """A line of a `git log` the call of that id ran in `repositories`:
        the hash of the latest commit another call made in one of them under
        the line's subject that showed none. A reading from a boundary on
        stops at one made before it, which it holds no publication of."""
        for place in range(len(self.unhashed) - 1, -1, -1):
            made, commit = self.unhashed[place]
            if (
                made.made_by == made_by
                or made.repository not in repositories
                or not changes.names(line, made.subject)
            ):
                continue
            if (made.repository, sha) in self._shas:
                return
            if commit is None:
                raise NotContinuedError(
                    "a call shows the hash of a commit made before its boundary"
                )
            commit["sha"] = sha
            self._shas.add((made.repository, sha))
            del self.unhashed[place]
            return


def _checkout(
    path: PurePosixPath, settings: Settings
) -> tuple[str, tuple[str, ...]] | None:
    """The checkout that holds a path, by its name, and the path's parts
    within it; none for a path under no checkout."""
    for root in settings.COLLECTOR_CHECKOUT_ROOTS:
        if path.is_relative_to(root):
            under = path.relative_to(root).parts
            if under and under[0] != _SCRATCH:
                return under[0], under[1:]
            return None
    return None


def _repository(directory: str, settings: Settings) -> str | None:
    """The checkout that holds the working directory, by its name; none for
    a directory under no checkout."""
    held = _checkout(PurePosixPath(directory), settings)
    return None if held is None else held[0]


def _kept(
    directory: str | None, path: str, settings: Settings
) -> tuple[str, str] | None:
    """The checkout that holds the file a call names by `path`, from its
    working directory `directory`, by its name, and the file's path within
    it, a worktree's of the checkout as the checkout's own; none for a file
    under no checkout."""
    if not posixpath.isabs(path):
        if directory is None:
            return None
        path = posixpath.join(directory, path)
    held = _checkout(PurePosixPath(posixpath.normpath(path)), settings)
    if held is None:
        return None
    name, within = held
    if within[:2] == _WORKTREES:
        within = within[3:]
    return (name, "/".join(within)) if within else None


def _resolved(standing: Standing, unhashed: set[Unhashed]) -> Standing:
    """Where a reading stood, with no commit made before it whose hash a
    line the reading took later showed."""
    if all(made in unhashed for made in standing.unhashed):
        return standing
    kept = tuple(made for made in standing.unhashed if made in unhashed)
    return replace(standing, unhashed=kept)


def _changed(was: str | None, now: str | None) -> bool:
    """Whether a fact two Calls name is another on the later one."""
    return bool(was) and bool(now) and was != now


def _missed(left: Left, tokens: dict[str, int]) -> bool:
    """Whether a Call of these tokens missed the cache its predecessor left
    (DB 546)."""
    context = tokens.get("input", 0) + sum(tokens.get(kind, 0) for kind in _CACHED)
    compared = min(left.cached, context)
    unread = compared - tokens.get("cache_read", 0)
    return 2 * unread > compared and 10 * context >= 9 * left.cached


def _cause(call: _Call, chain: Lead) -> str | None:
    """Why the Call missed the cache its predecessor left, the first cause
    that holds in Miss Cause's order; none where it did not miss."""
    left = chain.left
    if left is None or not _missed(left, call.tokens):
        return None
    request = call.request
    if chain.compaction is not None:
        return "compaction"
    if _changed(left.model, call.model) or _changed(left.effort, call.effort):
        return "model"
    if (call.sent_at or call.completed_at) - left.completed_at > (
        _HOUR if left.hour else _FIVE_MINUTES
    ):
        return "ttl"
    if left.place != call.place - 1:
        return "rewind"
    if _changed(left.version, call.version):
        return "version"
    if _changed(left.shape, None if request is None else request.shape):
        return "system"
    kept = None if request is None else request.kept
    if kept and left.sent and kept < left.sent:
        return "history"
    return "unknown"


def _named(line: dict[str, Any], key: str, held: str | None) -> str | None:
    """What the line names under `key`, `held` where it names nothing."""
    named: str | None = line.get(key)
    return held if named is None else named


def _tokens(usage: dict[str, Any]) -> dict[str, int]:
    """A response's tokens by Token Kind, a kind that counts none left
    out."""
    counted: dict[str, int] = {}
    for kind, where in _USAGE.items():
        tokens: Any = usage
        for key in where:
            tokens = tokens[key]
        if tokens:
            counted[kind] = tokens
    return counted


def _launches(thread: _Thread) -> list[dict[str, Any]]:
    launches: list[dict[str, Any]] = []
    for launch in thread.launches:
        if launch.version is None:
            if launch.prompts or launch.kept:
                raise UnreadableError(
                    "a launch received a prompt and none of its lines names"
                    " Claude Code's version"
                )
            continue
        launches.append(
            {
                "started_at": launch.started_at,
                "ended_at": launch.ended_at,
                "components": [
                    {"component": CLAUDE_CODE, "version": launch.version},
                    *(
                        {"component": f"{_PLUGIN}{plugin}", "version": version}
                        for plugin, version in launch.plugins.items()
                    ),
                ],
                "prompts": launch.prompts,
            }
        )
    return launches


def _calls(thread: _Thread) -> list[dict[str, Any]]:
    return [
        {
            "message_id": message_id,
            "prompt": call.prompt,
            "predecessor": (chain := thread.chain(call)).call,
            "compaction": chain.compaction,
            "sent_at": call.sent_at,
            "completed_at": call.completed_at,
            "model": call.model,
            "requested_model": call.requested_model,
            "effort": call.effort,
            "stop_reason": None if call.ended in _ORDINARY else call.ended,
            "thinking_tokens": call.thinking_tokens,
            "attributed_skill": call.skill,
            "attributed_plugin": call.plugin,
            "miss_cause": _cause(call, chain),
            "tokens": call.tokens,
            "tool_calls": [
                {
                    "tool_use_id": tool_use_id,
                    "tool": asked.tool,
                    "mcp_server": _server(asked.tool),
                    "first_argument": asked.argument,
                    "requested_at": asked.requested_at,
                    "returned_at": asked.returned_at,
                    "failed": asked.failed,
                    "exit_code": asked.exit_code or None,
                    "interrupted": asked.interrupted,
                    "denial_kind": asked.denial_kind,
                    "result_characters": asked.result_characters,
                    "saved_characters": asked.saved_characters,
                    "commits": asked.commits,
                    "file_edits": asked.edits,
                }
                for tool_use_id, asked in call.tool_calls.items()
            ],
            "events": [
                {
                    "kind": event.kind,
                    "is_error": _ERRORS[event.kind],
                    "at": event.at,
                    "detail": event.detail,
                }
                for event in call.events
            ],
            "context_parts": call.parts,
        }
        for message_id, call in thread.calls.items()
    ]


def _called(line: Any) -> str | None:
    """The `message.id` of an assistant line, the Call the labeller reads it
    as; none for another line."""
    if not isinstance(line, dict) or line.get("type") != "assistant":
        return None
    message = line.get("message")
    named = message.get("id") if isinstance(message, dict) else None
    return named if isinstance(named, str) and named else None


def _lines(content: bytes) -> list[bytes]:
    """The file's lines, each without its newline; what follows the last
    newline is a line still being written."""
    return content.split(b"\n")[:-1]


def _unreadable(number: int, error: Exception) -> UnreadableError:
    return UnreadableError(
        f"line {number} is not a line the collector reads:"
        f" {type(error).__name__}: {error}"
    )


def _recorded(transcript: Transcript) -> dict[str, Any]:
    """What a sub-agent's record says of how it was started: nothing on a
    main thread, nor where the record is missing.

    Raises:
        UnreadableError: The record is no JSON object.
    """
    path = record_of(transcript)
    if path is None:
        return {}
    try:
        recorded = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}
    except ValueError as error:
        raise UnreadableError(f"its record is no JSON: {error}") from error
    if not isinstance(recorded, dict):
        raise UnreadableError("its record is no JSON object")
    return recorded


def _spawning(content: bytes, spawned_by: str) -> tuple[str, datetime | None] | None:
    """The message whose line among the file's holds the call of that id,
    and that line's time: the first such line's; none where no line holds
    it."""
    named = spawned_by.encode()
    for number, raw in enumerate(_lines(content), start=1):
        if named not in raw:
            continue
        try:
            line = json.loads(raw)
            if line["type"] == "assistant" and any(
                block["type"] == "tool_use" and block["id"] == spawned_by
                for block in line["message"]["content"]
            ):
                return line["message"]["id"], written_at(line)
        except _MALFORMED as error:
            raise _unreadable(number, error) from error
    return None


def read(
    transcript: Transcript, settings: Settings, carry: Carry | None = None
) -> Read:
    """The transcript's publication as its file stands, and the carry the
    reading leaves: whole, or with `carry`, what an earlier reading of the
    file left, appended, read from the carry's boundary on.

    Raises:
        UnreadableError: The file is no transcript the collector reads; the
            message says why.
        NotContinuedError: The file does not continue what `carry` was built
            on, or a line read reaches behind its boundary; the message says
            which.
    """
    before = Standing() if carry is None else carry.stands
    with transcript.path.open("rb") as file:
        status = os.fstat(file.fileno())
        if carry is not None and status.st_size <= carry.file_size:
            raise NotContinuedError("its file is no larger than the one last read")
        file.seek(before.byte)
        content = file.read(status.st_size - before.byte)
    if (
        carry is not None
        and digest(content[: carry.file_size - before.byte]) != carry.end
    ):
        raise NotContinuedError("its file has other bytes before its old end")
    recorded = _recorded(transcript)
    spawned_by = recorded.get("toolUseId")
    forked = (
        spawned_by
        if recorded.get("agentType") == _FORK and isinstance(spawned_by, str)
        else None
    )
    fork = before.fork
    if carry is not None and (None if fork is None else fork.spawned_by) != forked:
        raise NotContinuedError(
            "its record names another fork's call than the one it was read with"
        )
    if forked is not None and (fork is None or fork.message is None):
        spawning = _spawning(content, forked)
        if spawning is not None and before.byte:
            raise NotContinuedError(
                "a fork's line from its boundary on holds the call that started it"
            )
        fork = Fork(forked, *(spawning or (None, None)))
    thread = _Thread(
        transcript.agent_id is None, transcript.projects, settings, before, fork
    )
    byte = before.byte
    called: dict[str, None] = {}
    for number, raw in enumerate(_lines(content), start=1):
        try:
            line = json.loads(raw)
            if not isinstance(line, dict):
                raise TypeError("the line is no object")
            thread.take(line, byte)
        except _MALFORMED as error:
            raise _unreadable(number, error) from error
        named = _called(line)
        if named is not None:
            called.setdefault(named, None)
        byte += len(raw) + 1
    try:
        named = _called(json.loads(content[byte - before.byte :]))
    except ValueError:
        named = None
    if named is not None:
        called.setdefault(named, None)
    if thread.directory is None:
        raise UnreadableError("no line names a working directory")
    facts: dict[str, Any] = {
        "session_id": transcript.session_id,
        "agent_id": transcript.agent_id,
        "file_size": status.st_size,
        "file_modified_at": modified_at(status),
        "collector": {"version": VERSION},
        "working_directory": thread.directory,
        "repository": _repository(thread.directory, settings),
        "environment": thread.environment,
        "agent_type": recorded.get("agentType"),
        "description": recorded.get("description"),
        "spawned_by": spawned_by,
        "launches": _launches(thread),
        "compactions": thread.compactions,
        "calls": _calls(thread),
    }
    if carry is not None:
        facts["appended"] = {
            "builds_on": {
                "file_size": carry.file_size,
                "file_modified_at": carry.file_modified_at,
                "collector": carry.collector,
            },
            "boundary": {
                "call": before.calls + 1,
                "launch": before.launches + 1,
                "prompt": before.prompts + (0 if thread.reopened else 1),
                "compaction": before.compactions + 1,
            },
        }
    try:
        publication = PublicationSchema.model_validate(facts)
    except ValidationError as error:
        raise UnreadableError(f"its facts are no publication: {error}") from error
    unhashed = {made for made, _ in thread.unhashed}
    stands = _resolved(thread.stands, unhashed)
    return Read(
        publication,
        Carry(
            file_size=publication.file_size,
            file_modified_at=publication.file_modified_at,
            collector=VERSION,
            stands=stands,
            end=digest(content[stands.byte - before.byte :]),
        ),
        tuple(called),
        {
            message_id: _resolved(standing, unhashed)
            for message_id, standing in thread.stood.items()
        },
        content,
        before.byte,
        None if carry is None else carry.checkpoint,
    )
