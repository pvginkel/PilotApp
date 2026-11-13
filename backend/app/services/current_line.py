"""A Session's current line: what its turn in flight is doing (design 2 §9.5, Q5;
DB assertion 221).

The keys: `state`, one of `starting`, `thinking`, `writing` (a main-thread text
block under way), `working` (a tool call without its result yet), `waiting`
(a sub-agent running) and `background` (the model's own turn ended with a task
it left in the background still running); `since`, when that state began, or
the latest step did; `step`, the latest tool call's `tool` and `input`, absent
before the first, its `input` None while it streams in, until the call's line
fills it in; `agent`, the sub-agent's `type` and `description` while `waiting`;
`task`, the `type` and `description` of the background task started last of
those still running, while `background`; `tasks`, the main thread's tasks that
run, each with its `id`, `type`, `description` and whether it is
`backgrounded`, absent while none runs; `text`, the latest `server` record's
words while `starting`.

The session start sets it from each `server` record it writes while the Session
is `starting`; the send keeps that line, or sets `thinking`; and the relay
rebuilds it from each line it records and from each partial it forwards, as the
line implies; a sub-agent's line implies nothing of the main thread's.

A task is `claude`'s own: a `system` `task_started` line starts one, in the
background where its `is_backgrounded` is true or a later `task_updated` line's
patch makes it so, as for a command moved there at its timeout, and its
`task_notification` ends it. `claude`'s `result` line, the model's own turn
ended, is `background` while a backgrounded task runs, the worker holding the
Turn open for it. From there only a tool call's line or its block's start, or
the notification of the last such task, moves the state: the worker's nudge and
the model's answer to it leave it.
"""

from datetime import datetime
from typing import Any, Literal

type CurrentLine = dict[str, Any]
type LineState = Literal[
    "starting", "thinking", "writing", "working", "waiting", "background"
]

_AGENT_TOOLS = ("Task", "Agent")
TOOL_BLOCKS = ("tool_use", "server_tool_use", "mcp_tool_use")
"""The content blocks of an `assistant` line that are a tool call."""
_THINKING_BLOCKS = ("thinking", "redacted_thinking")
_CALL_STATES = ("working", "waiting")
"""The states a tool call's line or its block's start implies."""


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
    tasks = _tasks_after(previous, line)
    state, step, agent = _implied_by_line(line)
    yielded = _ends_the_models_turn(line) or _in_background(previous)
    if yielded and state not in _CALL_STATES and _backgrounded(tasks):
        state = "background"
    elif state is None:
        if previous is None or previous["state"] in ("starting", "background"):
            state = "thinking"
        else:
            state = previous["state"]
    return _rebuilt(previous, state, at, step, agent, tasks)


def after_partial(
    previous: CurrentLine | None, line: dict[str, Any], at: datetime
) -> CurrentLine | None:
    """The current line once the forwarded partial `line` arrived at `at`; None
    when it leaves the line as it is."""
    state, step = _implied_by_partial(line)
    if state is None or (_in_background(previous) and state not in _CALL_STATES):
        return None
    tasks = previous.get("tasks", []) if previous is not None else []
    current = _rebuilt(previous, state, at, step, None, tasks)
    return None if current == previous else current


def _rebuilt(
    previous: CurrentLine | None,
    state: LineState,
    at: datetime,
    step: dict[str, Any] | None,
    agent: dict[str, Any] | None,
    tasks: list[dict[str, Any]],
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
    if state == "background":
        task = _backgrounded(tasks)[-1]
        current["task"] = {"type": task["type"], "description": task["description"]}
    if tasks:
        current["tasks"] = tasks
    return current


def _in_background(line: CurrentLine | None) -> bool:
    return line is not None and line["state"] == "background"


def _backgrounded(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in tasks if task["backgrounded"]]


def _ends_the_models_turn(line: Any) -> bool:
    """Whether `line` is `claude`'s own `result`, which ends the model's turn
    and not the Turn: the worker's `result` frame ends that."""
    return isinstance(line, dict) and line.get("type") == "result"


def _tasks_after(previous: CurrentLine | None, line: Any) -> list[dict[str, Any]]:
    """The main thread's running tasks once `line` is recorded, in the order
    they started."""
    tasks: list[dict[str, Any]] = previous.get("tasks", []) if previous else []
    if not isinstance(line, dict) or line.get("type") != "system":
        return tasks
    task_id = line.get("task_id")
    if not isinstance(task_id, str):
        return tasks
    others = [task for task in tasks if task["id"] != task_id]
    match line.get("subtype"):
        case "task_started" if not line.get("owned_by_subagent"):
            started = {
                "id": task_id,
                "type": line.get("task_type"),
                "description": line.get("description"),
                "backgrounded": line.get("is_backgrounded") is True,
            }
            return [*others, started]
        case "task_updated":
            patch = line.get("patch")
            if isinstance(patch, dict) and patch.get("is_backgrounded") is True:
                return [
                    {**task, "backgrounded": True} if task["id"] == task_id else task
                    for task in tasks
                ]
        case "task_notification":
            return others
    return tasks


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
