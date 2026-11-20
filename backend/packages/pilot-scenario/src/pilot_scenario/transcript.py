"""A thread's file in Claude Code's line shapes (F122.3): the lines a
collector reads its facts off, written as the builder reads the script.

A transcript's file is JSON Lines. A line with a `uuid` is one of the
thread's chain: it names the line it follows as `parentUuid` and carries its
time, the directory, the session's id and Claude Code's version. The lines
Claude Code writes beside the chain carry no `uuid`, and of them the queue's
alone a time: the permission mode a process starts under, the queue's
operations, the last prompt, and the cost line a process writes as it exits.

- A prompt is a `user` line whose `message.content` is its text, with
  `promptSource`, Claude Code's word for its source. One that waited in the
  queue follows its `enqueue` and `dequeue` lines, and the `enqueue` has its
  text and the time it arrived.
- A process's first prompt is followed by an `attachment` line of type
  `instructions`, whose `files` list the instruction files it loaded: the
  managed one opens `# Environment: <id>`.
- A response is one `assistant` line a block, all under its `message.id`.
  Each carries the response's `usage`; the lines before the last carry fewer
  output tokens than it and no `stop_reason`.
- A tool's result is a `user` line holding one `tool_result` block that names
  its request's id, with `toolUseResult`, the tool's own record of it.
- A sub-agent's file opens with the task its spawning call gave it, and every
  line of its chain is a `isSidechain` one that carries its `agentId`.

The shapes are Claude Code's; every word in them is invented.
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pilot_scenario.script import Call, ToolUse

SESSION_HOME = "/home/ubuntu/.claude"
"""The home as a session's own process names it: where a result's text says
its output was saved, wherever the home is mounted for a reader."""

MANAGED = "/etc/claude-code/CLAUDE.md"
"""The managed instruction file, whose first line names the environment."""

_IDS = uuid.UUID("0b7d4a52-9c1e-4f38-a6d5-3e8f1c2b7a94")
"""The namespace the lines' ids are drawn in."""

_WORDS = "Stir the pot and taste the broth before the salt goes in. "

_BETWEEN = timedelta(milliseconds=40)
"""The time from one line of a response to its next."""

_ORIGINS = {
    "sdk": "sdk",
    "typed": "human",
    "queued": "human",
    "suggestion_accepted": "human",
    "system": "task_notification",
}
"""`turnOrigin`, the older field a prompt's line says its source in beside
`promptSource`, by the source."""

_QUEUED = {"sdk", "queued", "system"}
"""The sources whose prompts wait in the queue before they are taken."""


@dataclass(frozen=True)
class HomeFile:
    """A file of the home: its path from the home's folder, what it holds
    and the time it was last written."""

    path: str
    content: bytes
    modified_at: datetime


@dataclass(frozen=True)
class Spawned:
    """A sub-agent as the tool call that started it names it."""

    agent_id: str
    type: str


def folder(directory: str) -> str:
    """The folder of the home's `projects` that a conversation begun in
    `directory` is filed under."""
    return re.sub(r"[^A-Za-z0-9]", "-", directory)


def stamp(moment: datetime) -> str:
    """A time as a line carries one: UTC, to the millisecond."""
    at = moment.astimezone(UTC)
    return f"{at:%Y-%m-%dT%H:%M:%S}.{at.microsecond // 1000:03}Z"


def text(length: int) -> str:
    """Invented words, `length` characters of them."""
    if length < 0:
        raise ValueError(
            "A result is shorter than Claude Code's own words around it: it "
            f"needs {-length} more characters"
        )
    return (_WORDS * (length // len(_WORDS) + 1))[:length]


def _kilobytes(size: int) -> str:
    """A size as Claude Code says one a result was too large at."""
    return f"{round(size / 1024, 1):g}KB"


class Lines:
    """One thread's lines in the file's order, the conversation's main
    thread's or, with `agent`, a sub-agent's."""

    def __init__(
        self,
        conversation: str,
        directory: str,
        entrypoint: str,
        agent: str | None = None,
    ) -> None:
        self.version = ""
        """Claude Code's version the lines are written under."""
        self.leaf: str | None = None
        """The chain's last line, which the next one follows."""
        self.saved: list[HomeFile] = []
        """The outputs saved to disk, each a file beside the transcript's."""
        self._conversation = conversation
        self._directory = directory
        self._entrypoint = entrypoint
        self._agent = agent
        self._lines: list[dict[str, Any]] = []
        self._prompts = 0

    @property
    def path(self) -> str:
        """The file's path from the home's folder."""
        filed = f"projects/{folder(self._directory)}/{self._conversation}"
        if self._agent is None:
            return f"{filed}.jsonl"
        return f"{filed}/subagents/agent-{self._agent}.jsonl"

    def content(self) -> bytes:
        """The file as it stands."""
        return b"".join(
            json.dumps(line, separators=(",", ":")).encode() + b"\n"
            for line in self._lines
        )

    def _id(self, of: str) -> str:
        named = f"{self._conversation}/{self._agent}/{of}/{len(self._lines)}"
        return str(uuid.uuid5(_IDS, named))

    def _beside(self, kind: str, **fields: Any) -> None:
        """A line beside the chain."""
        self._lines.append({"type": kind, **fields, "sessionId": self._conversation})

    def _chained(self, kind: str, at: datetime, **fields: Any) -> str:
        """The chain's next line, which follows its leaf; its id."""
        line: dict[str, Any] = {
            "parentUuid": self.leaf,
            "isSidechain": self._agent is not None,
        }
        if self._agent is not None:
            line["agentId"] = self._agent
        self.leaf = self._id("line")
        line |= fields
        line |= {
            "type": kind,
            "uuid": self.leaf,
            "timestamp": stamp(at),
            "userType": "external",
            "entrypoint": self._entrypoint,
            "cwd": self._directory,
            "sessionId": self._conversation,
            "version": self.version,
            "gitBranch": "main",
        }
        self._lines.append(line)
        return self.leaf

    def launched(self, version: str) -> None:
        """A process of that version of Claude Code starts."""
        self.version = version
        mode = "default" if self._entrypoint == "cli" else "bypassPermissions"
        self._beside("permission-mode", permissionMode=mode)

    def prompted(self, source: str, characters: int, at: datetime) -> None:
        """A prompt of that source and length arrives."""
        prompt = text(characters)
        if source in _QUEUED:
            self._beside(
                "queue-operation",
                operation="enqueue",
                timestamp=stamp(at),
                content=prompt,
            )
            self._beside("queue-operation", operation="dequeue", timestamp=stamp(at))
        fields: dict[str, Any] = {
            "promptId": self._id("prompt"),
            "message": {"role": "user", "content": prompt},
            "promptSource": source,
            "turnOrigin": _ORIGINS[source],
            "turnPosition": {"turnIndex": self._prompts, "promptIndex": 0},
        }
        if source != "sdk":
            fields["origin"] = {"kind": _ORIGINS[source].replace("_", "-")}
        self._prompts += 1
        self._chained("user", at, **fields)

    def tasked(self, task: str, at: datetime) -> None:
        """A sub-agent is given its task."""
        self._chained(
            "user",
            at,
            promptId=self._id("prompt"),
            message={"role": "user", "content": task},
        )

    def instructed(self, environment: str | None, at: datetime) -> None:
        """The instruction files a process loaded: the managed one where an
        environment hosts it, and the project's."""
        files = [
            {
                "type": "Project",
                "path": f"{self._directory}/CLAUDE.md",
                "content": f"# House rules\n\n{text(180)}\n",
            }
        ]
        if environment is not None:
            managed = {
                "type": "Managed",
                "path": MANAGED,
                "content": f"# Environment: {environment}\n\n{text(240)}\n",
            }
            files.insert(0, managed)
        self._chained(
            "attachment", at, attachment={"type": "instructions", "files": files}
        )

    def called(
        self,
        call: Call,
        message_id: str,
        requests: list[dict[str, Any]],
        at: datetime,
    ) -> list[str]:
        """A response that completed at `at`, a line a block: its thinking,
        its words and each of `requests`, its `tool_use` blocks. The ids of
        the requests' lines."""
        blocks: list[dict[str, Any]] = []
        if call.thinking is not None:
            signature = uuid.uuid5(_IDS, f"{message_id}/thinking").hex * 4
            blocks.append({"type": "thinking", "thinking": "", "signature": signature})
        blocks.append({"type": "text", "text": text(96)})
        final = len(blocks) if requests else len(blocks) - 1
        blocks += requests
        spent = call.tokens
        usage = {
            "input_tokens": spent.input,
            "cache_creation_input_tokens": spent.cache_write_5m + spent.cache_write_1h,
            "cache_read_input_tokens": spent.cache_read,
            "cache_creation": {
                "ephemeral_5m_input_tokens": spent.cache_write_5m,
                "ephemeral_1h_input_tokens": spent.cache_write_1h,
            },
            "output_tokens": spent.output,
            "service_tier": "standard",
        }
        written: list[str] = []
        for place, block in enumerate(blocks):
            last = place == len(blocks) - 1
            message = {
                "model": call.model,
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "content": [block],
                "stop_reason": ("tool_use" if requests else "end_turn")
                if last
                else None,
                "stop_sequence": None,
                "usage": usage
                if last
                else usage | {"output_tokens": spent.output // 4},
            }
            written.append(
                self._chained(
                    "assistant",
                    at - _BETWEEN * max(0, final - place),
                    message=message,
                    requestId=f"req_{message_id.removeprefix('msg_')}",
                )
            )
        return written[len(blocks) - len(requests) :]

    def returned(
        self,
        use: ToolUse,
        tool_use_id: str,
        request: str,
        at: datetime,
        spawned: Spawned | None = None,
        task: str | None = None,
    ) -> None:
        """The result of the tool call whose request is the line `request`
        arrives, `use.characters` long."""
        saved = None
        if use.saved is not None:
            named = (
                tool_use_id
                if use.server is None
                else f"mcp-{use.server}-{use.tool.rsplit('__', 1)[-1]}-{tool_use_id}"
            )
            saved = (
                f"projects/{folder(self._directory)}/{self._conversation}"
                f"/tool-results/{named}.txt"
            )
            self.saved.append(HomeFile(saved, text(use.saved).encode(), at))
        result = _result(use, saved)
        block: dict[str, Any] = {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": [{"type": "text", "text": result}]
            if use.tool == "Agent"
            else result,
        }
        if use.failed or use.tool == "Bash":
            block["is_error"] = use.failed
        self.leaf = request
        self._chained(
            "user",
            at,
            promptId=self._id("prompt"),
            message={"role": "user", "content": [block]},
            toolUseResult=_record(use, result, saved, spawned, task),
            sourceToolAssistantUUID=request,
        )

    def exited(self, started: datetime, ended: datetime, calls: list[Call]) -> None:
        """The process exits: its last prompt and its cost line."""
        self._beside("last-prompt", lastPrompt=text(64), leafUuid=self.leaf)
        models: dict[str, dict[str, int]] = {}
        for call in calls:
            spent, counted = call.tokens, models.setdefault(call.model, {})
            for name, tokens in (
                ("inputTokens", spent.input),
                ("outputTokens", spent.output),
                ("cacheReadInputTokens", spent.cache_read),
                (
                    "cacheCreationInputTokens",
                    spent.cache_write_5m + spent.cache_write_1h,
                ),
            ):
                counted[name] = counted.get(name, 0) + tokens
        self._beside(
            "cost-state",
            startTime=(started - datetime.fromtimestamp(0, UTC))
            // timedelta(milliseconds=1),
            totalDuration=(ended - started) // timedelta(milliseconds=1),
            totalLinesAdded=0,
            totalLinesRemoved=0,
            hasUnknownModelCost=False,
            modelUsage=models,
        )


def request(
    use: ToolUse, tool_use_id: str, spawned: Spawned | None, task: str | None
) -> dict[str, Any]:
    """A `tool_use` block: the request of one tool, its argument the first
    of its input, an Agent call's its description, written after its
    type."""
    asked: dict[str, Any]
    if use.argument is None:
        asked = {}
    elif use.tool == "Bash":
        asked = {"command": use.argument, "description": text(32)}
    elif use.tool == "Read":
        asked = {"file_path": use.argument}
    elif use.tool == "Edit":
        asked = {
            "file_path": use.argument,
            "old_string": text(24),
            "new_string": text(40),
            "replace_all": False,
        }
    elif use.tool == "Agent":
        asked = {
            "subagent_type": "general-purpose" if spawned is None else spawned.type,
            "description": use.argument,
            "prompt": task,
        }
    else:
        asked = {"query": use.argument}
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": use.tool,
        "input": asked,
        "caller": {"type": "direct"},
    }


def _result(use: ToolUse, saved: str | None) -> str:
    """The result the model was given, `use.characters` long: Claude Code's
    own words where the output was saved to disk or a command failed, and
    invented ones."""
    length = use.characters or 0
    head, foot = "", ""
    if saved is not None and use.saved is not None:
        path = f"{SESSION_HOME}/{saved}"
        if use.server is None:
            head = (
                f"<persisted-output>\nOutput too large ({_kilobytes(use.saved)})."
                f" Full output saved to: {path}\n\nPreview (first 2KB):\n"
            )
            foot = "\n...\n</persisted-output>"
        else:
            head = (
                f"Error: result ({use.saved:,} characters) exceeds maximum allowed"
                f" tokens. Output has been saved to {path}.\n"
            )
    elif use.failed and use.exit_code is not None:
        head = f"Exit code {use.exit_code}\n"
    return head + text(length - len(head) - len(foot)) + foot


def _record(
    use: ToolUse,
    result: str,
    saved: str | None,
    spawned: Spawned | None,
    task: str | None,
) -> Any:
    """`toolUseResult`, the tool's own record of its result."""
    if use.failed:
        return f"Error: {result}"
    if use.tool == "Bash":
        record: dict[str, Any] = {
            "stdout": result,
            "stderr": "",
            "interrupted": use.interrupted,
            "isImage": False,
            "noOutputExpected": False,
        }
        if saved is not None and use.saved is not None:
            record |= {
                "persistedOutputPath": f"{SESSION_HOME}/{saved}",
                "persistedOutputSize": use.saved,
            }
        return record
    if use.tool == "Read":
        lines = result.count("\n") + 1
        return {
            "type": "text",
            "file": {
                "filePath": use.argument,
                "content": result,
                "numLines": lines,
                "startLine": 1,
                "totalLines": lines,
            },
        }
    if use.tool == "Edit":
        return {
            "filePath": use.argument,
            "oldString": text(24),
            "newString": text(40),
            "originalFile": None,
            "structuredPatch": [],
            "userModified": False,
            "replaceAll": False,
        }
    if use.tool == "Agent" and spawned is not None:
        return {
            "status": "completed",
            "prompt": task,
            "agentId": spawned.agent_id,
            "agentType": spawned.type,
            "content": [{"type": "text", "text": result}],
            "totalDurationMs": (use.took or 0) * 1000,
        }
    return result
