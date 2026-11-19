"""A transcript's file read into its whole publication (F152.3).

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
  same. It was received when its `enqueue` line was written, where the queue
  holds one with its text, else at its own time.
- **A Call** is the `assistant` lines under one `message.id`, placed by the
  first of them; its usage, model and completion time are the last one's.

Tool Calls, and the facts slices 051 and 052 read, are not read here.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from pilot_collection.publication import CallTokenKind, PublicationSchema
from pydantic import ValidationError

from pilot_collector import VERSION
from pilot_collector.home import Transcript
from pilot_collector.settings import Settings

CLAUDE_CODE = "claude-code"
"""The Component whose version a Launch's lines carry."""

_EPOCH = datetime.fromtimestamp(0, UTC)

_COST = "cost-state"
"""The type of the line a process writes as it exits."""

_SYNTHETIC = "<synthetic>"
"""The model of an `assistant` line Claude Code wrote itself: no response."""

_MANAGED = "Managed"
"""The type of the managed instruction file among those a process loaded."""

_SCRATCH = "scratch"
"""The folder of a checkout root that holds clones that are no repository of
the environment's."""

_NEWER = {
    "human": "typed",
    "task_notification": "system",
    "task-notification": "system",
}
"""An older field's word for a prompt's source, by the word `promptSource`
has for the same."""

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


@dataclass
class _Launch:
    started_at: datetime
    version: str | None = None
    prompts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Call:
    prompt: int | None
    completed_at: datetime
    model: str
    tokens: dict[str, int]


def _time(line: dict[str, Any]) -> datetime | None:
    """A line's time, none on a line that carries none."""
    stamp = line.get("timestamp")
    return None if stamp is None else datetime.fromisoformat(stamp)


def _is_a_tools_result(content: Any) -> bool:
    return isinstance(content, list) and any(
        block["type"] == "tool_result" for block in content
    )


def _text(content: Any) -> str:
    """The words of a prompt: a string, or the text blocks of a list."""
    if isinstance(content, str):
        return content
    return "".join(block["text"] for block in content if block["type"] == "text")


def _source(line: dict[str, Any]) -> str | None:
    """A `user` line's source in Claude Code's word, none where it names
    none."""
    named: str | None = line.get("promptSource")
    if named is not None:
        return named
    if line.get("isMeta"):
        return None
    older: str | None = line.get("turnOrigin")
    if older is None:
        older = (line.get("origin") or {}).get("kind")
    if older is None:
        return None
    return _NEWER.get(older, older)


class _Thread:
    """One thread's facts as its lines are taken, in the file's order."""

    def __init__(self, main: bool, settings: Settings) -> None:
        self.directory: str | None = None
        self.environment: str | None = None
        self.launches: list[_Launch] = []
        self.calls: dict[str, _Call] = {}
        self._main = main
        self._settings = settings
        self._exited = True
        self._prompts = 0
        self._queue: list[tuple[str, datetime]] = []
        """The prompts waiting in the process's queue, in the order they
        arrived: each one's text and the time of its `enqueue` line."""

    def take(self, line: dict[str, Any]) -> None:
        if self.directory is None and "cwd" in line:
            self.directory = line["cwd"]
        kind = line["type"]
        if kind == _COST:
            self._exited = True
            self._queue.clear()
        at = _time(line)
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
        elif not self._main:
            return
        elif kind == "queue-operation":
            self._queued(line, at)
        elif kind == "attachment":
            self._attached(line["attachment"])
        elif kind == "user":
            self._prompted(line, at)

    def _queued(self, line: dict[str, Any], at: datetime) -> None:
        operation, content = line["operation"], line.get("content")
        if operation == "popAll":
            self._queue.clear()
        elif content is None:
            return
        elif operation == "enqueue":
            self._queue.append((content, at))
        elif operation == "remove":
            self._waited(content)

    def _waited(self, text: str) -> datetime | None:
        """Take the first prompt of that text out of the queue: the time
        it arrived, none where the queue holds none."""
        for place, (queued, at) in enumerate(self._queue):
            if queued == text:
                del self._queue[place]
                return at
        return None

    def _attached(self, attachment: dict[str, Any]) -> None:
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

    def _prompted(self, line: dict[str, Any], at: datetime) -> None:
        content = line["message"]["content"]
        if _is_a_tools_result(content):
            return
        source = _source(line)
        if source is None:
            return
        text = _text(content)
        self._prompts += 1
        self.launches[-1].prompts.append(
            {
                "received_at": self._waited(text) or at,
                "source": source,
                "characters": len(text),
            }
        )

    def _answered(self, message: dict[str, Any], at: datetime) -> None:
        if message["model"] == _SYNTHETIC:
            return
        model, tokens = message["model"], _tokens(message["usage"])
        call = self.calls.get(message["id"])
        if call is None:
            prompt = self._prompts or None
            self.calls[message["id"]] = _Call(prompt, at, model, tokens)
        else:
            call.completed_at, call.model, call.tokens = at, model, tokens


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
            if launch.prompts:
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


def _lines(content: bytes) -> list[bytes]:
    """The file's lines, each without its newline; what follows the last
    newline is a line still being written."""
    return content.split(b"\n")[:-1]


def read(transcript: Transcript, settings: Settings) -> PublicationSchema:
    """The transcript's whole publication, as its file stands.

    Raises:
        UnreadableError: The file is no transcript the collector reads; the
            message says why.
    """
    with transcript.path.open("rb") as file:
        status = os.fstat(file.fileno())
        content = file.read(status.st_size)
    thread = _Thread(transcript.agent_id is None, settings)
    for number, raw in enumerate(_lines(content), start=1):
        try:
            line = json.loads(raw)
            if not isinstance(line, dict):
                raise TypeError("the line is no object")
            thread.take(line)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise UnreadableError(
                f"line {number} is not a line the collector reads:"
                f" {type(error).__name__}: {error}"
            ) from error
    if thread.directory is None:
        raise UnreadableError("no line names a working directory")
    try:
        return PublicationSchema.model_validate(
            {
                "session_id": transcript.session_id,
                "agent_id": transcript.agent_id,
                "file_size": status.st_size,
                "file_modified_at": _EPOCH
                + timedelta(microseconds=status.st_mtime_ns // 1000),
                "collector": {"version": VERSION},
                "working_directory": thread.directory,
                "repository": _repository(thread.directory, settings),
                "environment": thread.environment,
                "launches": _launches(thread),
                "calls": [
                    {
                        "message_id": message_id,
                        "prompt": call.prompt,
                        "completed_at": call.completed_at,
                        "model": call.model,
                        "tokens": call.tokens,
                    }
                    for message_id, call in thread.calls.items()
                ],
            }
        )
    except ValidationError as error:
        raise UnreadableError(f"its facts are no publication: {error}") from error
