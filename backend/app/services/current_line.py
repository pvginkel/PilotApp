"""A Session's current line: what its turn in flight is doing (design 2 §9.5, Q5;
DB assertion 221).

The keys: `state`, one of `starting`, `thinking`, `writing` (a main-thread text
block under way), `working` (a tool call without its result yet) and `waiting`
(a sub-agent running); `since`, when that state began, or the latest step did;
`step`, the latest tool call's `tool` and `input`, absent before the first, its
`input` None while it streams in, until the call's line fills it in;
`agent`, the sub-agent's `type` and `description` while `waiting`; `text`, the
latest `server` record's words while `starting`.

The session start sets it from each `server` record it writes while the Session
is `starting`; the send keeps that line, or sets `thinking`; and the relay
rebuilds it from each line it records and from each partial it forwards, as the
line implies; a sub-agent's line implies nothing of the main thread's.
"""

from datetime import datetime
from typing import Any, Literal

type CurrentLine = dict[str, Any]
type LineState = Literal["starting", "thinking", "writing", "working", "waiting"]

_AGENT_TOOLS = ("Task", "Agent")
TOOL_BLOCKS = ("tool_use", "server_tool_use", "mcp_tool_use")
"""The content blocks of an `assistant` line that are a tool call."""
_THINKING_BLOCKS = ("thinking", "redacted_thinking")


def while_starting(text: str, at: datetime) -> CurrentLine:
    """The current line once the session start writes, at `at`, the `server`
    record whose words are `text`."""
    return {"state": "starting", "since": at.isoformat(), "text": text}


def at_send(previous: CurrentLine | None, at: datetime) -> CurrentLine:
    """The current line once a turn is sent at `at`: the session start's line
    kept, else `thinking`."""
    return (
        previous
        if previous is not None
        else {"state": "thinking", "since": at.isoformat()}
    )


def after_line(previous: CurrentLine | None, line: Any, at: datetime) -> CurrentLine:
    """The current line once the line `line` is recorded at `at`; `line` is the
    record's payload."""
    state, step, agent = _implied_by_line(line)
    if state is None:
        if previous is None or previous["state"] == "starting":
            state = "thinking"
        else:
            state = previous["state"]
    return _rebuilt(previous, state, at, step, agent)


def after_partial(
    previous: CurrentLine | None, line: dict[str, Any], at: datetime
) -> CurrentLine | None:
    """The current line once the forwarded partial `line` arrived at `at`; None
    when it leaves the line as it is."""
    state, step = _implied_by_partial(line)
    if state is None:
        return None
    current = _rebuilt(previous, state, at, step, None)
    return None if current == previous else current


def _rebuilt(
    previous: CurrentLine | None,
    state: LineState,
    at: datetime,
    step: dict[str, Any] | None,
    agent: dict[str, Any] | None,
) -> CurrentLine:
    before = previous or {}
    moved = before.get("state") != state or (
        step is not None and not _same_call(before.get("step"), step)
    )
    current: CurrentLine = {
        "state": state,
        "since": at.isoformat() if moved else before["since"],
    }
    step = step or before.get("step")
    if step is not None:
        current["step"] = step
    if state == "waiting":
        agent = agent or before.get("agent")
        if agent is not None:
            current["agent"] = agent
    return current


def _same_call(before: dict[str, Any] | None, step: dict[str, Any]) -> bool:
    """Whether `step` is the step `before`: the same, or the call whose input
    streamed in, its input filled in by its line."""
    return before is not None and (
        before == step or (before["input"] is None and before["tool"] == step["tool"])
    )


def _implied_by_line(
    line: Any,
) -> tuple[LineState | None, dict[str, Any] | None, dict[str, Any] | None]:
    """The state a recorded line implies, and the tool call and sub-agent it
    starts."""
    if not isinstance(line, dict) or line.get("parent_tool_use_id"):
        return None, None, None
    match line.get("type"):
        case "system" if line.get("subtype") == "init":
            return "thinking", None, None
        case "user":
            return "thinking", None, None
        case "assistant":
            message = line.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            blocks = content if isinstance(content, list) else []
            calls = [
                block
                for block in blocks
                if isinstance(block, dict) and block.get("type") in TOOL_BLOCKS
            ]
            if not calls:
                return "thinking", None, None
            call = calls[-1]
            step = {"tool": call.get("name"), "input": call.get("input")}
            if call.get("name") not in _AGENT_TOOLS:
                return "working", step, None
            given = call.get("input")
            given = given if isinstance(given, dict) else {}
            agent = {
                "type": given.get("subagent_type"),
                "description": given.get("description"),
            }
            return "waiting", step, agent
    return None, None, None


def _implied_by_partial(
    line: dict[str, Any],
) -> tuple[LineState | None, dict[str, Any] | None]:
    """The state a forwarded partial implies — a main-thread block's start or
    a text delta — and the tool call whose input starts streaming in, with no
    input yet."""
    event = line.get("event")
    if not isinstance(event, dict):
        return None, None
    if event.get("type") == "content_block_delta":
        return "writing", None
    block = event.get("content_block")
    kind = block.get("type") if isinstance(block, dict) else None
    if kind == "text":
        return "writing", None
    if kind in _THINKING_BLOCKS:
        return "thinking", None
    if isinstance(block, dict) and kind in TOOL_BLOCKS:
        return "working", {"tool": block.get("name"), "input": None}
    return None, None
