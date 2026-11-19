"""A transcript's file read into its reading (F152.13): the conversation as
Pilot's backend is served it, whole.

It is read off the file as `reader.py` reads the facts, so that its calls
are the facts' calls: a line is read once its newline is written, within the
size the open file has; a line with no time is no block's; and

- **a Call** is the `assistant` lines under one `message.id` whose model is
  no synthetic one, placed by the first of them. What it put out is the
  blocks of those lines, in the file's order: its words, its thinking, with
  the text the file has of it, and each tool it requested, once.
- **A tool's result** sits on the tool call it answers: the first
  `tool_result` block that names the request's id, with its text, whether
  it was an error and when it returned. Where the tool's own record of the
  result names an agent, the call started that sub-agent's transcript. A
  result that names no request of the file, or one a result has answered,
  is a block where it stands.
- **What came in** before a Call is every other block since the first line
  of the Call before; what follows the last Call's first line is what
  follows the last Call. A `user` line that is no tool's result is a block
  with who wrote it:
  - a person, where its source is `typed`, `queued` or
    `suggestion_accepted`;
  - a brief, where it is `sdk`;
  - a notice, where it is any other word, and where the line names none
    and is Claude Code's own: an `isMeta` one, a compaction's summary or
    its words for an interruption;
  - a parent agent, where a sub-agent's line names none and is none of
    those, and where its origin is the coordinator;
  - nobody, on a main thread's line that names none and is none of those.
- **An image** in a `user` line is a block after the line's own, and one in
  a result is the result's: its media type and its size, the bytes its
  base64 text stands for.
- **An `assistant` line of a synthetic model** is a block among what came
  in: Claude Code's own words where a response would stand.
- **An `attachment` line** is a block among what came in, with Claude
  Code's word for what it is and its text: its `text`, `content` or
  `prompt`, the first that is words, else what it holds beside its type,
  as JSON, an image block in it said as an image is: by its media type and
  size.
- **A `system` line** is a block among what came in, with its subtype and
  its `content` where that is words.

No other line is read: the queue's, a tool's progress and the lines beside
the chain are not the conversation's.
"""

import json
import os
from datetime import datetime
from typing import Any

from pilot_collection.reading import ReadingSchema

from pilot_collector.home import Transcript, modified_at
from pilot_collector.reader import (
    SYNTHETIC,
    UnreadableError,
    source_of,
    text_of,
    written_at,
)

_WRITERS = {
    "typed": "person",
    "queued": "person",
    "suggestion_accepted": "person",
    "sdk": "brief",
}
"""Who wrote a prompt, by Claude Code's word for its source; a notice where
the word is another."""

_COORDINATOR = "coordinator"
"""The `origin.kind` of a message the agent that steers a sub-agent sent
it."""

_WORDS = ("text", "content", "prompt")
"""Where an attachment holds its words, in the order they are looked for."""

_INTERRUPTED = "[Request interrupted by user"
"""How Claude Code's line for a person's interruption opens."""


def _writer(line: dict[str, Any], said: str, main: bool) -> str | None:
    """Who wrote a `user` line that says `said`, on a main thread or a
    sub-agent's; none where the file does not say."""
    if (line.get("origin") or {}).get("kind") == _COORDINATOR:
        return "parent"
    source = source_of(line)
    if source is not None:
        return _WRITERS.get(source, "notice")
    if (
        line.get("isMeta")
        or line.get("isCompactSummary")
        or said.startswith(_INTERRUPTED)
    ):
        return "notice"
    return None if main else "parent"


def _image(block: dict[str, Any]) -> dict[str, Any]:
    """An image block as the reading says it: the bytes are those its
    base64 text stands for."""
    source = block["source"]
    data: str = source["data"]
    return {
        "media_type": source["media_type"],
        "size": len(data) * 3 // 4 - data.count("=", -2),
    }


def _images(content: Any) -> list[dict[str, Any]]:
    """The images among a line's or a result's blocks, in their order."""
    if isinstance(content, str):
        return []
    return [_image(block) for block in content if block["type"] == "image"]


def _without_bytes(held: Any) -> Any:
    """What an attachment holds, each image block in it said by its media
    type and size."""
    if isinstance(held, list):
        return [_without_bytes(each) for each in held]
    if not isinstance(held, dict):
        return held
    if held.get("type") == "image" and isinstance(held.get("source"), dict):
        return {"type": "image"} | _image(held)
    return {name: _without_bytes(value) for name, value in held.items()}


class _Conversation:
    """One thread's blocks as its lines are taken, in the file's order."""

    def __init__(self, main: bool) -> None:
        self.calls: dict[str, dict[str, Any]] = {}
        """The Calls, by Claude's id of the response."""
        self.pending: list[dict[str, Any]] = []
        """What came in since the last Call's first line."""
        self._main = main
        self._requested: dict[str, dict[str, Any]] = {}
        """The tool calls requested, by Claude's id of the request."""

    def take(self, line: dict[str, Any]) -> None:
        at = written_at(line)
        if at is None:
            return
        if line["type"] == "assistant":
            message = line["message"]
            if message["model"] == SYNTHETIC:
                words = text_of(message["content"])
                self.pending.append({"kind": "synthetic", "at": at, "text": words})
            else:
                self._answered(message, at)
        elif line["type"] == "user":
            self._said(line, at)
        elif line["type"] == "attachment":
            self._attached(line["attachment"], at)
        elif line["type"] == "system":
            said = line.get("content")
            self.pending.append(
                {
                    "kind": "system",
                    "at": at,
                    "subtype": line.get("subtype"),
                    "text": said if isinstance(said, str) else None,
                }
            )

    def _answered(self, message: dict[str, Any], at: datetime) -> None:
        call = self.calls.get(message["id"])
        if call is None:
            call = {"message_id": message["id"], "received": self.pending, "sent": []}
            self.calls[message["id"]] = call
            self.pending = []
        sent: list[dict[str, Any]] = call["sent"]
        for block in message["content"]:
            kind = block["type"]
            if kind == "text":
                sent.append({"kind": "text", "at": at, "text": block["text"]})
            elif kind == "thinking":
                sent.append({"kind": "thinking", "at": at, "text": block["thinking"]})
            elif kind == "tool_use" and block["id"] not in self._requested:
                asked = {
                    "kind": "tool_call",
                    "at": at,
                    "tool_use_id": block["id"],
                    "tool": block["name"],
                    "input": block["input"],
                    "started": None,
                    "result": None,
                }
                self._requested[block["id"]] = asked
                sent.append(asked)

    def _attached(self, attachment: dict[str, Any], at: datetime) -> None:
        holds = {name: value for name, value in attachment.items() if name != "type"}
        said = next(
            (holds[name] for name in _WORDS if isinstance(holds.get(name), str)),
            None,
        )
        self.pending.append(
            {
                "kind": "attachment",
                "at": at,
                "type": attachment["type"],
                "text": json.dumps(_without_bytes(holds), ensure_ascii=False)
                if said is None
                else said,
            }
        )

    def _said(self, line: dict[str, Any], at: datetime) -> None:
        content = line["message"]["content"]
        said = content
        if not isinstance(content, str):
            record = line.get("toolUseResult")
            for block in content:
                if block["type"] == "tool_result":
                    self._returned(block, record, at)
            said = [block for block in content if block["type"] != "tool_result"]
        if not said:
            return
        words = text_of(said)
        writer = _writer(line, words, self._main)
        self.pending.append({"kind": "user", "at": at, "writer": writer, "text": words})
        self.pending += [{"kind": "image", "at": at} | one for one in _images(said)]

    def _returned(self, block: dict[str, Any], record: Any, at: datetime) -> None:
        """A result, on the tool call that asked for it where the thread
        requested one of its id that no result has reached; `record` is the
        tool's own record of the result."""
        result = {
            "at": at,
            "error": block.get("is_error") is True,
            "text": text_of(block["content"]),
            "images": _images(block["content"]),
        }
        asked = self._requested.get(block["tool_use_id"])
        if asked is None or asked["result"] is not None:
            self.pending.append(
                {"kind": "tool_result", "tool_use_id": block["tool_use_id"]} | result
            )
            return
        asked["result"] = result
        if isinstance(record, dict):
            asked["started"] = record.get("agentId")


def reading(transcript: Transcript) -> ReadingSchema:
    """The transcript's reading as its file stands.

    Raises:
        UnreadableError: A line of the file is none the collector reads; the
            message says which and why.
    """
    conversation = _Conversation(transcript.agent_id is None)
    with transcript.path.open("rb") as file:
        status = os.fstat(file.fileno())
        left = status.st_size
        for number, raw in enumerate(file, start=1):
            left -= len(raw)
            if left < 0 or not raw.endswith(b"\n"):
                break
            try:
                line = json.loads(raw)
                if not isinstance(line, dict):
                    raise TypeError("the line is no object")
                conversation.take(line)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise UnreadableError(
                    f"line {number} is not a line the collector reads:"
                    f" {type(error).__name__}: {error}"
                ) from error
    return ReadingSchema.model_validate(
        {
            "session_id": transcript.session_id,
            "agent_id": transcript.agent_id,
            "file_size": status.st_size,
            "file_modified_at": modified_at(status),
            "calls": list(conversation.calls.values()),
            "after": conversation.pending,
        }
    )
