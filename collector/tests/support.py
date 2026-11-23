"""Lines in Claude Code's shapes for a file built to pin one rule: each
carries what the reader reads of its kind and no more, and every word in
them is invented."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pilot_collector.home import Transcript
from pilot_collector.settings import Settings

SESSION = "4f0c6a1e-8b2d-4d57-9e3a-71c5d2b8a690"
AGENT = "a3f9c1d27b6e4805c"
DIRECTORY = "/work/Loom"
FOLDER = "-work-Loom"
VERSION = "2.1.317"
MANAGED = "/etc/claude-code/CLAUDE.md"
START = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
BODY = "Base directory for this skill: /loom/skills/weave\n\nWeave tight."
"""A skill's body."""

type Line = dict[str, Any]


def settings(**given: Any) -> Settings:
    """The collector's settings, those with no default invented and
    `given` over them."""
    named: dict[str, Any] = {
        "COLLECTOR_PILOT_URL": "http://pilot.invalid",
        "COLLECTOR_TOKEN": "an-invented-collector-token",
        "COLLECTOR_HOME": "/home/ubuntu/.claude",
    }
    return Settings(**(named | given))


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


def request(seconds: float, named: str = "request-1", **asked: Any) -> Line:
    """The line of a request to the model, sent at `seconds`: the lines of
    its response name it by its `id`, `named`; `asked` is what it says it
    sent, its `shapeHash`, `keep` and `tail`."""
    line = beside("api-request", id=named, timestamp=stamp(seconds), version=VERSION)
    return line | asked


def shaped(
    seconds: float,
    named: str = "shape-1",
    system: tuple[str, ...] = ("You weave.",),
    tools: tuple[dict[str, Any], ...] = (),
) -> Line:
    """The line of the shape `named` that requests name as `shapeHash`: the
    text blocks of the system prompt they send and their tools."""
    return beside(
        "api-request-shape",
        shapeHash=named,
        timestamp=stamp(seconds),
        version=VERSION,
        shape={"system": [words(said) for said in system], "tools": list(tools)},
    )


def snapshot(
    seconds: float, *system: str, tools: list[dict[str, Any]] | None = None
) -> Line:
    """The snapshot of the system prompt and, where a version records them,
    the tools a process started with."""
    attachment: dict[str, Any] = {
        "type": "prompt_snapshot",
        "systemPrompt": list(system),
    }
    if tools is not None:
        attachment["tools"] = tools
    return chained("attachment", seconds, attachment=attachment)


def sent(line: Line, named: str = "request-1") -> Line:
    """A line of a response that names the request line `named`."""
    return line | {"requestRef": named}


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


def taken(seconds: float, text: Any, mode: str = "prompt") -> Line:
    """A message Claude took in the middle of a run, `text` of the kind
    `mode` names."""
    attachment = {"type": "queued_command", "prompt": text, "commandMode": mode}
    return chained("attachment", seconds, attachment=attachment)


def result(
    seconds: float,
    tool_use_id: str = "toolu_01",
    said: Any = "Done.",
    error: bool | None = None,
    record: Any = None,
) -> Line:
    """A tool's result saying `said`: in error or not where the tool says
    which, with `record`, the tool's own record of it, where it keeps one."""
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": said}
    if error is not None:
        block["is_error"] = error
    line = user(seconds, [block])
    return line if record is None else line | {"toolUseResult": record}


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


def denied(line: Line, kind: str) -> Line:
    """A result's line that names the kind of its call's denial,
    `toolDenialKind`."""
    return line | {"toolDenialKind": kind}


def hooked(
    seconds: float,
    *commands: str,
    run: str = "hooks-1",
    errors: tuple[str, ...] = (),
    prevented: bool = False,
    **fields: Any,
) -> Line:
    """The summary of the run `run` of the Stop hooks: each of `commands`
    ran 10 ms and one more per its place, with the `errors` they reported;
    `fields` are what a newer version adds, `failedHookErrorIndexes`."""
    hooks = [
        {"command": command, "durationMs": 10 + place}
        for place, command in enumerate(commands)
    ]
    return chained(
        "system",
        seconds,
        subtype="stop_hook_summary",
        hookCount=len(hooks),
        hookInfos=hooks,
        hookErrors=list(errors),
        hookAdditionalContext=[],
        preventedContinuation=prevented,
        stopReason="",
        hasOutput=bool(errors),
        level="suggestion",
        toolUseID=run,
        **fields,
    )


def hook_failed(
    seconds: float, command: str, run: str = "hooks-1", event: str = "Stop"
) -> Line:
    """The error a hook `command` reported at `event`, in the run `run`."""
    attachment = {
        "type": "hook_non_blocking_error",
        "hookName": event,
        "toolUseID": run,
        "hookEvent": event,
        "stderr": "The shuttle jammed.",
        "stdout": "",
        "exitCode": 1,
        "command": command,
        "durationMs": 12,
    }
    return chained("attachment", seconds, attachment=attachment)


def requesting(
    seconds: float,
    tool_use_id: str = "toolu_01",
    tool: str = "Bash",
    given: dict[str, Any] | None = None,
    message_id: str = "msg_01",
) -> Line:
    """A line of the response of that id that requests a tool, `given` its
    input."""
    line = assistant(seconds, message_id, output=3)
    line["message"]["content"] = [
        {
            "type": "tool_use",
            "id": tool_use_id,
            "name": tool,
            "input": {"command": "ls looms"} if given is None else given,
        }
    ]
    return line


def answering(seconds: float, message_id: str, *blocks: dict[str, Any]) -> Line:
    """A line of the response of that id that holds `blocks`."""
    line = assistant(seconds, message_id, output=3)
    line["message"]["content"] = list(blocks)
    return line


def fallback(asked: str, answered: str = "claude-opus-4-5") -> dict[str, Any]:
    """The block a response opens with that a fallback answered: the model
    `asked` for, and the one that `answered`."""
    return {"type": "fallback", "from": {"model": asked}, "to": {"model": answered}}


def fell_back(
    seconds: float, request_id: str, asked: str, answered: str = "claude-opus-4-5"
) -> Line:
    """The line that records a fallback: the request of that `requestId`
    asked for one model, and another answered it."""
    return chained(
        "system",
        seconds,
        subtype="model_refusal_fallback",
        requestId=request_id,
        originalModel=asked,
        fallbackModel=answered,
        level="warning",
    )


def finished(line: Line, thinking: int, ended: str | None) -> Line:
    """A line of a response that counts `thinking` tokens of thinking, and
    says how the response `ended`."""
    line["message"]["usage"]["output_tokens_details"] = {"thinking_tokens": thinking}
    line["message"]["stop_reason"] = ended
    return line


def retried(seconds: float, status: int | None = 529, attempt: int = 1) -> Line:
    """The line of an API error of that `status` that Claude Code sends the
    request again after, the `attempt`th."""
    error: dict[str, Any] = {"message": "The loom is overloaded."}
    if status is not None:
        error["status"] = status
    return chained(
        "system",
        seconds,
        subtype="api_error",
        level="error",
        error=error,
        retryInMs=600,
        retryAttempt=attempt,
        maxRetries=10,
    )


def erred(seconds: float, status: int | None = 529) -> Line:
    """The response Claude Code writes itself for a request that failed for
    good with an API error of that `status`."""
    return synthetic(seconds, "API Error: the loom is overloaded.") | {
        "isApiErrorMessage": True,
        "apiErrorStatus": status,
        "error": "server_error",
    }


def interruption(seconds: float) -> Line:
    """The line that records the person's interruption of a response."""
    return user(seconds, [words("[Request interrupted by user]")])


def synthetic(seconds: float, said: str) -> Line:
    """A line Claude Code wrote itself where a response would stand."""
    line = assistant(seconds, "msg_synthetic", "<synthetic>")
    line["message"]["content"] = [{"type": "text", "text": said}]
    return line


def words(said: str) -> dict[str, str]:
    """A block of text."""
    return {"type": "text", "text": said}


def image(size: int, media_type: str = "image/png") -> dict[str, Any]:
    """A block holding an image of `size` invented bytes."""
    data = base64.b64encode(bytes(place % 251 for place in range(size))).decode()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def too_large(path: str, size: str) -> str:
    """A result in Claude Code's words for an output too large for it, saved
    at `path`: it gives a rounded `size` and the output's first part."""
    return (
        f"<persisted-output>\nOutput too large ({size}). Full output saved to:"
        f" {path}\n\nPreview (first 2KB):\ntwill\nsatin\n...\n</persisted-output>"
    )


def over_the_tokens(path: str, stated: str) -> str:
    """A result in Claude Code's words for an output over the tokens a
    result may hold, saved at `path`: `stated` is its size as the result
    gives it, in characters and, on some versions, lines."""
    return (
        f"Error: result ({stated}) exceeds maximum allowed tokens. Output has"
        f" been saved to {path}.\nFormat: Plain text\n"
    )


def boundary(
    seconds: float, trigger: str = "auto", before: int = 90_000, **made: int
) -> Line:
    """A compaction's boundary: `made` is what a newer version adds to its
    record, `postTokens` and `durationMs`."""
    record = {"trigger": trigger, "preTokens": before} | made
    return chained(
        "system", seconds, subtype="compact_boundary", compactMetadata=record
    )


def summary(seconds: float) -> Line:
    """The summary a compaction leaves, which follows its boundary."""
    return user(seconds, "The loom so far: warped, not yet threaded.") | {
        "isCompactSummary": True
    }


def attached(
    seconds: float, kind: str, shown: str | None = None, **fields: Any
) -> Line:
    """An attachment of that type, with the text the model was `shown` where
    it was shown any: an older version records none."""
    line = chained("attachment", seconds, attachment={"type": kind, **fields})
    return line if shown is None else line | {"rendered": [{"content": shown}]}


def nested(seconds: float, path: str, content: str) -> Line:
    """An instruction file loaded once a Launch was under way."""
    loaded = {"path": path, "type": "Project", "content": content}
    shown = f"Contents of {path}:\n\n{content}"
    return attached(seconds, "nested_memory", shown, path=path, content=loaded)


def invoked(seconds: float, *skills: tuple[str, str]) -> Line:
    """The bodies of the skills invoked before a compaction, shown again:
    each skill's name and body."""
    shown = "The skills invoked before:\n" + "\n".join(body for _, body in skills)
    held = [
        {"name": name, "path": f"plugin:{name}", "content": body}
        for name, body in skills
    ]
    return attached(seconds, "invoked_skills", shown, skills=held)


def expanded(seconds: float, source: str | None = "toolu_01") -> Line:
    """A skill's body as Claude Code expands it, for the `Skill` call
    `source` names, where one does."""
    line = user(seconds, [words(BODY)]) | {"isMeta": True}
    return line if source is None else line | {"sourceToolUseID": source}


def loaded(kind: str, content: str, path: str = MANAGED) -> dict[str, str]:
    """An instruction file a process loaded."""
    return {"type": kind, "path": path, "content": content}


def instructions(seconds: float, *files: dict[str, str]) -> Line:
    """The attachment that lists the instruction files a process loaded."""
    attachment = {"type": "instructions", "files": list(files)}
    return chained("attachment", seconds, attachment=attachment)


def linked(lines: list[Line], name: str = "line") -> list[Line]:
    """The lines as a chain: each that has a time and is neither an
    operation of the queue's, a request nor a request's shape is named by a
    `uuid`, `name` and its place among them, and follows the one before; the
    first follows none, and neither does a compaction's boundary, which names
    the one before as its `logicalParentUuid`."""
    chain: list[Line] = []
    last: str | None = None
    for line in lines:
        if "timestamp" not in line or line["type"] in (
            "queue-operation",
            "api-request",
            "api-request-shape",
        ):
            chain.append(line)
            continue
        named = f"{name}-{sum('uuid' in each for each in chain) + 1}"
        if line.get("subtype") == "compact_boundary":
            follows = {"parentUuid": None, "logicalParentUuid": last}
        else:
            follows = {"parentUuid": last}
        chain.append(line | {"uuid": named} | follows)
        last = named
    return chain


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
    return Transcript(projects, path, SESSION, agent)


def saved(projects: Path, name: str, content: bytes, session: str = SESSION) -> str:
    """An output saved to disk under that conversation's folder; its path as
    a result names it, on the session's own home."""
    path = projects / FOLDER / session / "tool-results" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return f"/home/ubuntu/.claude/projects/{FOLDER}/{session}/tool-results/{name}"
