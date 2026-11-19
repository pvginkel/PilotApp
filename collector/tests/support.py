"""Lines in Claude Code's shapes for a file built to pin one rule: each
carries what the reader reads of its kind and no more, and every word in
them is invented."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pilot_collector.home import Transcript

SESSION = "4f0c6a1e-8b2d-4d57-9e3a-71c5d2b8a690"
AGENT = "a3f9c1d27b6e4805c"
DIRECTORY = "/work/Loom"
FOLDER = "-work-Loom"
VERSION = "2.1.317"
MANAGED = "/etc/claude-code/CLAUDE.md"
START = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

type Line = dict[str, Any]


def moment(seconds: float) -> datetime:
    """The time `seconds` after the file's start."""
    return START + timedelta(seconds=seconds)


def stamp(seconds: float) -> str:
    """That time as a line carries one: UTC, to the millisecond."""
    at = moment(seconds)
    return f"{at:%Y-%m-%dT%H:%M:%S}.{at.microsecond // 1000:03}Z"


def beside(kind: str, **fields: Any) -> Line:
    """A line beside the chain: no time, directory or version."""
    return {"type": kind, **fields, "sessionId": SESSION}


def chained(kind: str, seconds: float, **fields: Any) -> Line:
    """A line of the chain, with its time, directory and version."""
    return {
        "type": kind,
        "timestamp": stamp(seconds),
        "cwd": DIRECTORY,
        "sessionId": SESSION,
        "version": VERSION,
    } | fields


def cost() -> Line:
    """The line a process writes as it exits."""
    return beside("cost-state", totalDuration=1_000)


def queue(operation: str, seconds: float, text: str | None = None) -> Line:
    """An operation of the queue's: it carries a time and no version."""
    line = beside("queue-operation", operation=operation, timestamp=stamp(seconds))
    return line if text is None else line | {"content": text}


def user(seconds: float, text: Any = "Warp the loom.", **fields: Any) -> Line:
    """A `user` line saying `text`; `fields` name its source."""
    return chained("user", seconds, message={"role": "user", "content": text}, **fields)


def typed(seconds: float, text: Any = "Warp the loom.") -> Line:
    """A prompt a person typed."""
    return user(seconds, text, promptSource="typed")


def result(seconds: float, tool_use_id: str = "toolu_01") -> Line:
    """A tool's result."""
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": "Done."}
    return user(seconds, [block])


def assistant(
    seconds: float,
    message_id: str = "msg_01",
    model: str = "claude-opus-4-5",
    **spent: int,
) -> Line:
    """A line of the response of that id, its usage `spent` by the kinds a
    publication counts."""
    counted = {
        "input": 0,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "cache_read": 0,
        "output": 0,
    } | spent
    usage = {
        "input_tokens": counted["input"],
        "cache_creation_input_tokens": counted["cache_write_5m"]
        + counted["cache_write_1h"],
        "cache_read_input_tokens": counted["cache_read"],
        "cache_creation": {
            "ephemeral_5m_input_tokens": counted["cache_write_5m"],
            "ephemeral_1h_input_tokens": counted["cache_write_1h"],
        },
        "output_tokens": counted["output"],
    }
    message = {
        "id": message_id,
        "model": model,
        "role": "assistant",
        "content": [{"type": "text", "text": "The warp is on."}],
        "usage": usage,
    }
    return chained("assistant", seconds, message=message)


def loaded(kind: str, content: str, path: str = MANAGED) -> dict[str, str]:
    """An instruction file a process loaded."""
    return {"type": kind, "path": path, "content": content}


def instructions(seconds: float, *files: dict[str, str]) -> Line:
    """The attachment that lists the instruction files a process loaded."""
    attachment = {"type": "instructions", "files": list(files)}
    return chained("attachment", seconds, attachment=attachment)


def content(lines: list[Line]) -> bytes:
    """The lines as a file holds them."""
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


def filed(
    projects: Path, lines: list[Line] | bytes, agent: str | None = None
) -> Transcript:
    """The lines written as a thread's file where Claude Code files it: the
    main thread's or, with `agent`, a sub-agent's."""
    path = projects / FOLDER / f"{SESSION}.jsonl"
    if agent is not None:
        path = projects / FOLDER / SESSION / "subagents" / f"agent-{agent}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lines if isinstance(lines, bytes) else content(lines))
    return Transcript(path, SESSION, agent)
