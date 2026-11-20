"""A transcript's file read into its publication (F152.3): whole, or from
its boundary on where the file grew (F152.15).

A transcript's file is JSON Lines, a line an object, and a line is read once
its newline is written. The facts are read off the lines in the file's order:

- **The collection record.** The file's size and time are the open file's
  own, the time cut to the microsecond Pilot holds one at, and the bytes read
  are those the size counts.
- **The place.** The working directory is the first line's that carries one.
  The repository is the checkout that holds it: the first folder under a
  checkout root, the roots' `scratch` folder aside. The environment is a main
  thread's alone: the id the managed instruction file opens with, in the
  `instructions` attachment that lists the files a process loaded, the first
  where the file names two.
- **A Launch**, on a main thread, starts at the file's first line with a time
  and at the first such line after a cost line, the line a process writes as
  it exits (DB 586). It ran the version of Claude Code its lines name, the
  first that names one; a Launch none of whose lines names a version is not
  published.
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

The facts slices 051 and 052 read are not read here.

**From the boundary on.** A reading leaves a carry (`carry.py`): where it
stood before the file's last Call. Given that carry, a file that grew is read
from the boundary's byte on, and its publication is an appended one: the
Calls from the boundary's on, the Launches that wrote a line from there on,
the first with its Prompts from there on, and the four places the boundary
names. Such a reading holds no line before the boundary's byte but the one
the carry names, so it stops, and the file is read whole, where:

- the file is no larger than the one the carry was built on, or its bytes
  from the boundary's to its old end are other than those read then
  (F152.17);
- a line's `parentUuid` names a line before the boundary's byte that is not
  the carry's, or a tool's result names a request no line from that byte on
  makes: either reaches behind the boundary.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pilot_collection.publication import CallTokenKind, PublicationSchema
from pydantic import ValidationError

from pilot_collector import VERSION
from pilot_collector.carry import Carry, Open, Standing, digest
from pilot_collector.home import Transcript, modified_at, saved_output
from pilot_collector.settings import Settings

CLAUDE_CODE = "claude-code"
"""The Component whose version a Launch's lines carry."""

_COST = "cost-state"
"""The type of the line a process writes as it exits."""

SYNTHETIC = "<synthetic>"
"""The model of an `assistant` line Claude Code wrote itself: no response."""

_MANAGED = "Managed"
"""The type of the managed instruction file among those a process loaded."""

_SCRATCH = "scratch"
"""The folder of a checkout root that holds clones that are no repository of
the environment's."""

_BASH = "Bash"
"""The tool whose result says how its command exited."""

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
    """What a reading of the file, grown, continues."""


@dataclass
class _Launch:
    started_at: datetime
    version: str | None = None
    prompts: list[dict[str, Any]] = field(default_factory=list)
    kept: int = 0
    """The Prompts it received before the reading's first line."""


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


@dataclass
class _Call:
    prompt: int | None
    completed_at: datetime
    model: str
    tokens: dict[str, int]
    tool_calls: dict[str, _ToolCall] = field(default_factory=dict)
    """The tool calls it requested, by Claude's id of the request."""


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
        self, main: bool, projects: Path, settings: Settings, before: Standing
    ) -> None:
        self.directory = before.directory
        self.environment = before.environment
        self.launches: list[_Launch] = []
        """The Launches that wrote a line taken, the one open before the
        first among them."""
        self.calls: dict[str, _Call] = {}
        self.stands = before
        """Where the reading stood before the last Call's first line."""
        self._main = main
        self._projects = projects
        self._settings = settings
        self._before = before
        self._exited = before.launch is None
        if before.launch is not None:
            opened = before.launch
            self.launches.append(
                _Launch(opened.started_at, opened.version, kept=opened.received)
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
        self._linked: set[str] = set()
        """The `uuid` of every line taken."""

    def take(self, line: dict[str, Any], byte: int) -> None:
        """Take the line that starts at `byte` of the file."""
        kind = line["type"]
        at = written_at(line)
        named = line.get("uuid")
        if self._before.byte:
            follows = line.get("parentUuid")
            if not (
                follows is None
                or follows == self._before.link
                or follows in self._linked
            ):
                raise NotContinuedError(
                    "a line follows one before its boundary that is not the last there"
                )
            if named is not None:
                self._linked.add(named)
        if (
            kind == "assistant"
            and at is not None
            and line["message"]["model"] != SYNTHETIC
            and line["message"]["id"] not in self.calls
        ):
            self.stands = self._standing(byte)
        if named is not None:
            self._link = named
        if self.directory is None and "cwd" in line:
            self.directory = line["cwd"]
        if kind == _COST:
            if not self._exited and self.launches[-1].version is not None:
                self._published += 1
            self._exited = True
            self._queue = ()
            self._removed = ()
        if at is None:
            return
        if self._main:
            if self._exited:
                self.launches.append(_Launch(at))
                self._exited = False
            launch = self.launches[-1]
            if launch.version is None:
                launch.version = line.get("version")
        if kind == "assistant":
            self._answered(line["message"], at)
        elif kind == "user":
            content = line["message"]["content"]
            if is_a_tools_result(content):
                self._returned(content, line.get("toolUseResult"), at)
            elif self._main:
                self._prompted(line, content, at)
        elif not self._main:
            return
        elif kind == "queue-operation":
            self._queued(line, at)
        elif kind == "attachment":
            self._attached(line["attachment"], at)

    def _standing(self, byte: int) -> Standing:
        """Where the reading stands before the line that starts at `byte`,
        none of it taken."""
        opened = None if self._exited else self.launches[-1]
        return Standing(
            byte=byte,
            calls=self._before.calls + len(self.calls),
            launches=self._published,
            prompts=self._prompts,
            link=self._link,
            directory=self.directory,
            environment=self.environment,
            launch=None
            if opened is None
            else Open(
                opened.started_at, opened.version, opened.kept + len(opened.prompts)
            ),
            queue=self._queue,
            removed=self._removed,
        )

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

    def _attached(self, attachment: dict[str, Any], at: datetime) -> None:
        if attachment["type"] == _MID_RUN:
            self._taken(attachment, at)
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
        self.launches[-1].prompts.append(
            {"received_at": at, "source": source, "characters": len(text)}
        )

    def _answered(self, message: dict[str, Any], at: datetime) -> None:
        if message["model"] == SYNTHETIC:
            return
        model, tokens = message["model"], _tokens(message["usage"])
        call = self.calls.get(message["id"])
        if call is None:
            call = _Call(self._prompts or None, at, model, tokens)
            self.calls[message["id"]] = call
        else:
            call.completed_at, call.model, call.tokens = at, model, tokens
        for block in message["content"]:
            if block["type"] == "tool_use" and block["id"] not in self._requested:
                argument = _argument(block["name"], block["input"])
                asked = _ToolCall(block["name"], argument, at)
                self._requested[block["id"]] = call.tool_calls[block["id"]] = asked

    def _returned(
        self, content: list[dict[str, Any]], record: Any, at: datetime
    ) -> None:
        """The results a line carries, each its tool call's where the thread
        requested one of its id that no result has reached; `record` is the
        tool's own record of the result."""
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
            ) or (asked.failed and _INTERRUPTED.match(said) is not None)


def _repository(directory: str, settings: Settings) -> str | None:
    """The checkout that holds the working directory, by its name; none for
    a directory under no checkout."""
    path = PurePosixPath(directory)
    for root in settings.COLLECTOR_CHECKOUT_ROOTS:
        if path.is_relative_to(root):
            under = path.relative_to(root).parts
            if under and under[0] != _SCRATCH:
                return under[0]
            return None
    return None


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
                "components": [{"component": CLAUDE_CODE, "version": launch.version}],
                "prompts": launch.prompts,
            }
        )
    return launches


def _calls(thread: _Thread) -> list[dict[str, Any]]:
    return [
        {
            "message_id": message_id,
            "prompt": call.prompt,
            "completed_at": call.completed_at,
            "model": call.model,
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
                    "result_characters": asked.result_characters,
                    "saved_characters": asked.saved_characters,
                }
                for tool_use_id, asked in call.tool_calls.items()
            ],
        }
        for message_id, call in thread.calls.items()
    ]


def _lines(content: bytes) -> list[bytes]:
    """The file's lines, each without its newline; what follows the last
    newline is a line still being written."""
    return content.split(b"\n")[:-1]


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
    thread = _Thread(transcript.agent_id is None, transcript.projects, settings, before)
    byte = before.byte
    for number, raw in enumerate(_lines(content), start=1):
        try:
            line = json.loads(raw)
            if not isinstance(line, dict):
                raise TypeError("the line is no object")
            thread.take(line, byte)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise UnreadableError(
                f"line {number} is not a line the collector reads:"
                f" {type(error).__name__}: {error}"
            ) from error
        byte += len(raw) + 1
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
        "launches": _launches(thread),
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
                "prompt": before.prompts + 1,
                "compaction": 1,
            },
        }
    try:
        publication = PublicationSchema.model_validate(facts)
    except ValidationError as error:
        raise UnreadableError(f"its facts are no publication: {error}") from error
    stands = thread.stands
    return Read(
        publication,
        Carry(
            file_size=publication.file_size,
            file_modified_at=publication.file_modified_at,
            collector=VERSION,
            stands=stands,
            end=digest(content[stands.byte - before.byte :]),
        ),
    )
