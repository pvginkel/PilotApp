"""The builder: one scenario turned into what a layer reads.

For a collector that is each thread of the scenario's conversations as a
file in Claude Code's line shapes, in a home laid out as the fleet's is; for
the backend's ingest, those conversations as a collector publishes them, one
whole publication a thread, in the shape of the collector's call (protocol
version 1), and the Turns of Pilot's its sessions ran under, which Pilot's
side holds before a collector reads the transcript.

A publication is what its thread's file says: the file's size and time, and
each fact as the lines carry it. The files hold the lines the facts of the
collector's first build are read off: a thread's ids and where it ran, its
Launches, Prompts, Calls and Tool Calls. No line is written for a hook run,
a compaction, an event or a context part, which the publications carry
alone.

A conversation's ids are the scenario's own, the same in every build, so
that a scenario published again is the same conversations again. A build's
last moment falls at `until`, cut to the millisecond a line's time is
written to, the scenario's times laid back from there.
"""

import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

from pilot_scenario.script import (
    Call,
    Compaction,
    Launch,
    Scenario,
    Session,
    SubAgent,
    ToolUse,
)
from pilot_scenario.transcript import HomeFile, Lines, Spawned, request, text

COLLECTOR = "1.3.0"
"""The version of the collector the publications say read the files."""

CLAUDE_CODE = "claude-code"
"""The component whose version a Launch's lines carry."""

_IDS = uuid.UUID("6c1f0e9a-3b5d-4c7e-8f2a-9d4b1e6a7c30")
"""The namespace the conversations' ids are drawn in."""

_EPOCH = datetime.fromtimestamp(0, UTC)

_TASK = text(220)
"""The task an Agent call gives the sub-agent it starts."""

type Step = Call | Compaction


@dataclass(frozen=True)
class SentTurn:
    """A Turn of Pilot's a session of the scenario ran under: the message
    sent to the conversation of that id of Claude Code's, on one of the
    scenario's projects, in the session's directory and environment."""

    project: str
    conversation: str
    directory: str
    environment: str | None
    message: str
    sent_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class _Spawning:
    """The tool call that started a sub-agent: as it is published, the
    moment it was requested at and Claude Code's version its process ran."""

    tool_call: dict[str, Any]
    at: int
    version: str


@dataclass(frozen=True)
class _Built:
    """A thread as it is built: its publication and its files, the
    transcript's first."""

    publication: dict[str, Any]
    files: list[HomeFile]


def _given(**facts: Any) -> dict[str, Any]:
    """The facts that are given: a call leaves out what its file does not
    have."""
    return {name: fact for name, fact in facts.items() if fact not in (None, [])}


def _moments(steps: Sequence[Step]) -> Iterator[int]:
    """Each moment something of the steps was written at."""
    for step in steps:
        yield step.at
        if isinstance(step, Call):
            yield from (
                step.at + use.took for use in step.tools if use.took is not None
            )
            yield from (occurrence.at for occurrence in step.occurred)


def _launch_moments(launch: Launch) -> Iterator[int]:
    for prompt in launch.prompts:
        yield prompt.at
        yield from _moments(prompt.steps)


def _main_moments(session: Session) -> Iterator[int]:
    for launch in session.launches:
        yield from _launch_moments(launch)


def _session_moments(session: Session) -> Iterator[int]:
    if session.turn is not None:
        yield session.turn.at
        yield session.turn.ended
    yield from _main_moments(session)
    for agent in session.sub_agents:
        yield from _moments(agent.steps)


@dataclass
class _Ids:
    """How many messages and tool calls a conversation's threads have
    named, counted through all of them, as Claude's own ids never repeat
    across a conversation's threads."""

    messages: int = 0
    tool_calls: int = 0


class _Thread:
    """One thread's Calls and Compactions as its steps are read, in the
    file's order, each named and placed as a collector names and places
    them, and its file's lines as they are written; its ids counted on with
    `ids`, the conversation's. `agents` are the session's sub-agents as a
    tool call names the one it started, by name."""

    def __init__(
        self,
        builder: "Builder",
        ids: _Ids,
        lines: Lines,
        agents: Mapping[str, Spawned],
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.compactions: list[dict[str, Any]] = []
        self.spawned: dict[str, _Spawning] = {}
        """The tool call that started each sub-agent, by the sub-agent's
        name."""
        self.lines = lines
        self._builder = builder
        self.ids = ids
        self._agents = agents
        self._named: dict[str, str] = {}
        self._leaves: dict[str, str | None] = {}
        """The chain's last line once each named Call was written, with its
        tools' results."""
        self._crossed: int | None = None

    def back(self, step: Step) -> None:
        """Where the step is a rewind, the chain goes on from the Call it
        went back to."""
        if isinstance(step, Call) and step.back_to is not None:
            self.lines.leaf = self._leaves[step.back_to]

    def read(self, step: Step, prompt: int | None) -> None:
        """Take the thread's next step, under the Prompt at that place."""
        at = self._builder.time
        if isinstance(step, Compaction):
            self.compactions.append(
                _given(
                    at=at(step.at),
                    trigger=step.trigger,
                    tokens_before=step.before,
                    tokens_after=step.after,
                    duration_ms=step.took_ms,
                )
            )
            self._crossed = len(self.compactions)
            return
        self.ids.messages += 1
        message_id = f"msg_{self.ids.messages:04}"
        if step.back_to is not None:
            predecessor: str | None = self._named[step.back_to]
        else:
            predecessor = self.calls[-1]["message_id"] if self.calls else None
        if step.name is not None:
            self._named[step.name] = message_id
        tool_calls = [self._tool_call(step, use) for use in step.tools]
        self.calls.append(
            _given(
                message_id=message_id,
                prompt=prompt,
                predecessor=predecessor,
                compaction=self._crossed,
                completed_at=at(step.at),
                model=step.model,
                effort=step.effort,
                thinking_tokens=step.thinking,
                attributed_skill=step.skill,
                attributed_plugin=step.plugin,
                miss_cause=step.miss,
                tokens={
                    kind: tokens
                    for kind, tokens in asdict(step.tokens).items()
                    if tokens
                },
                tool_calls=tool_calls,
                events=[
                    _given(
                        kind=occurrence.kind,
                        is_error=occurrence.is_error,
                        at=at(occurrence.at),
                        detail=occurrence.detail,
                    )
                    for occurrence in step.occurred
                ],
                context_parts=[
                    _given(kind=part.kind, name=part.name, characters=part.characters)
                    for part in step.carried
                ],
            )
        )
        self._crossed = None
        self._write(step, message_id, [call["tool_use_id"] for call in tool_calls])
        if step.name is not None:
            self._leaves[step.name] = self.lines.leaf

    def _tool_call(self, call: Call, use: ToolUse) -> dict[str, Any]:
        at = self._builder.time
        self.ids.tool_calls += 1
        tool_call = _given(
            tool_use_id=f"toolu_{self.ids.tool_calls:04}",
            tool=use.tool,
            mcp_server=use.server,
            first_argument=use.argument,
            requested_at=at(call.at),
            returned_at=None if use.took is None else at(call.at + use.took),
            failed=use.failed,
            exit_code=use.exit_code,
            interrupted=use.interrupted,
            result_characters=use.characters,
            saved_characters=use.saved,
        )
        if use.spawns is not None:
            self.spawned[use.spawns] = _Spawning(tool_call, call.at, self.lines.version)
        return tool_call

    def _write(self, call: Call, message_id: str, tool_use_ids: list[str]) -> None:
        """The Call's lines: its response's, then each result that arrived,
        in the order the tools were requested."""
        when = self._builder.when
        asked = []
        for use, tool_use_id in zip(call.tools, tool_use_ids, strict=True):
            spawned = None if use.spawns is None else self._agents[use.spawns]
            task = _TASK if use.tool == "Agent" else None
            asked.append((use, tool_use_id, spawned, task))
        requests = self.lines.called(
            call,
            message_id,
            [request(*one) for one in asked],
            when(call.at),
        )
        for (use, tool_use_id, spawned, task), line in zip(
            asked, requests, strict=True
        ):
            if use.took is not None:
                self.lines.returned(
                    use, tool_use_id, line, when(call.at + use.took), spawned, task
                )


class Builder:
    """A scenario as it stands at one moment, built for each layer that
    reads it."""

    def __init__(self, scenario: Scenario, until: datetime) -> None:
        self.scenario = scenario
        last = max(
            moment
            for session in scenario.sessions
            for moment in _session_moments(session)
        )
        until = until.replace(microsecond=until.microsecond // 1000 * 1000)
        self._start = until - timedelta(seconds=last)

    def when(self, moment: int) -> datetime:
        """The time of a moment of the scenario in this build."""
        return self._start + timedelta(seconds=moment)

    def time(self, moment: int) -> str:
        """That time as a call writes one."""
        return self.when(moment).isoformat()

    def conversation(self, session: Session) -> str:
        """Claude Code's id of the session's main thread."""
        return str(uuid.uuid5(_IDS, f"{self.scenario.name}/{session.name}"))

    def agent(self, session: Session, agent: SubAgent) -> str:
        """Claude Code's id of the session's sub-agent."""
        named = f"{self.scenario.name}/{session.name}/{agent.name}"
        return uuid.uuid5(_IDS, named).hex[:17]

    def turns(self) -> list[SentTurn]:
        """The Turns of Pilot's the scenario's sessions ran under, in the
        sessions' order."""
        return [
            SentTurn(
                project=session.turn.project,
                conversation=self.conversation(session),
                directory=session.directory,
                environment=session.environment,
                message=session.turn.message,
                sent_at=self.when(session.turn.at),
                ended_at=self.when(session.turn.ended),
            )
            for session in self.scenario.sessions
            if session.turn is not None
        ]

    def publications(self) -> list[dict[str, Any]]:
        """Each thread of the scenario as a collector publishes its file
        whole: a session's main thread, then its sub-agents'."""
        return [thread.publication for thread in self._threads]

    def files(self) -> list[HomeFile]:
        """The scenario as files of a home: each thread's transcript, in
        the publications' order, each followed by the outputs its results
        say were saved to disk."""
        return [file for thread in self._threads for file in thread.files]

    def write(self, home: Path) -> None:
        """Write the scenario's files under `home`, the folder that holds
        `projects`, each at the time its publication gives."""
        for file in self.files():
            target = home / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.content)
            at = (file.modified_at - _EPOCH) // timedelta(microseconds=1) * 1000
            os.utime(target, ns=(at, at))

    @cached_property
    def _threads(self) -> list[_Built]:
        built: list[_Built] = []
        for session in self.scenario.sessions:
            main, thread = self._main(session)
            built.append(main)
            built.extend(
                self._sub_agent(session, agent, thread) for agent in session.sub_agents
            )
        return built

    def _lines(self, session: Session, agent: str | None = None) -> Lines:
        entrypoint = "sdk-cli" if session.person is None else "cli"
        return Lines(self.conversation(session), session.directory, entrypoint, agent)

    def _agents(self, session: Session) -> dict[str, Spawned]:
        return {
            agent.name: Spawned(self.agent(session, agent), agent.type)
            for agent in session.sub_agents
        }

    def _thread(
        self, session: Session, lines: Lines, moments: Iterator[int]
    ) -> tuple[dict[str, Any], list[HomeFile]]:
        """What every thread of the session's says of its file and of where
        it ran, and the thread's files."""
        content = lines.content()
        modified = max(moments)
        publication = _given(
            session_id=self.conversation(session),
            file_size=len(content),
            file_modified_at=self.time(modified),
            collector={"version": COLLECTOR},
            working_directory=session.directory,
            repository=session.repository,
        )
        transcript = HomeFile(lines.path, content, self.when(modified))
        return publication, [transcript, *lines.saved]

    def _main(self, session: Session) -> tuple[_Built, _Thread]:
        lines = self._lines(session)
        thread = _Thread(self, _Ids(), lines, self._agents(session))
        launches: list[dict[str, Any]] = []
        place = 0
        for launch in session.launches:
            lines.launched(dict(launch.versions)[CLAUDE_CODE])
            prompts: list[dict[str, Any]] = []
            for received, prompt in enumerate(launch.prompts):
                place += 1
                prompts.append(
                    _given(
                        received_at=self.time(prompt.at),
                        source=prompt.source,
                        characters=prompt.characters,
                        hook_runs=[
                            {
                                "command": hook.command,
                                "duration_ms": hook.took_ms,
                                "failed": hook.failed,
                                "prevented_end": hook.held,
                            }
                            for hook in prompt.hooks
                        ],
                    )
                )
                if prompt.steps:
                    thread.back(prompt.steps[0])
                lines.prompted(prompt.source, prompt.characters, self.when(prompt.at))
                if received == 0:
                    lines.instructed(session.environment, self.when(prompt.at))
                for followed, step in enumerate(prompt.steps):
                    if followed:
                        thread.back(step)
                    thread.read(step, place)
            started, ended = launch.prompts[0].at, max(_launch_moments(launch))
            lines.exited(
                self.when(started),
                self.when(ended),
                [
                    step
                    for prompt in launch.prompts
                    for step in prompt.steps
                    if isinstance(step, Call)
                ],
            )
            launches.append(
                _given(
                    started_at=self.time(started),
                    ended_at=self.time(ended),
                    components=[
                        {"component": component, "version": version}
                        for component, version in launch.versions
                    ],
                    prompts=prompts,
                )
            )
        publication, files = self._thread(session, lines, _main_moments(session))
        publication |= _given(
            environment=session.environment,
            group=None if session.group is None else asdict(session.group),
            launches=launches,
            compactions=thread.compactions,
            calls=thread.calls,
        )
        return _Built(publication, files), thread

    def _sub_agent(self, session: Session, agent: SubAgent, main: _Thread) -> _Built:
        """The sub-agent's thread, named for the tool call of the main
        thread that started it."""
        spawning = main.spawned[agent.name]
        lines = self._lines(session, self.agent(session, agent))
        lines.version = spawning.version
        lines.tasked(_TASK, self.when(spawning.at))
        lines.instructed(session.environment, self.when(spawning.at))
        thread = _Thread(self, main.ids, lines, {})
        for step in agent.steps:
            thread.back(step)
            thread.read(step, None)
        publication, files = self._thread(session, lines, _moments(agent.steps))
        publication |= _given(
            agent_id=self.agent(session, agent),
            agent_type=agent.type,
            description=spawning.tool_call.get("first_argument"),
            spawned_by=spawning.tool_call["tool_use_id"],
            compactions=thread.compactions,
            calls=thread.calls,
        )
        return _Built(publication, files)
