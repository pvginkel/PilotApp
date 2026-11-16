"""The builder: one scenario turned into what a layer reads.

For the backend's ingest that is the scenario's conversations as a collector
publishes them, one whole publication a thread, in the shape of the
collector's call (protocol version 1), and the Turns of Pilot's its sessions
ran under, which Pilot's side holds before a collector reads the transcript.

A conversation's ids are the scenario's own, the same in every build, so
that a scenario published again is the same conversations again. A build's
last moment falls at `until`, the scenario's times laid back from there.
"""

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
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

COLLECTOR = "1.0.0"
"""The version of the collector the publications say read the files."""

_IDS = uuid.UUID("6c1f0e9a-3b5d-4c7e-8f2a-9d4b1e6a7c30")
"""The namespace the conversations' ids are drawn in."""

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
    yield launch.at
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


class _Thread:
    """One thread's Calls and Compactions as its steps are read, in the
    file's order, each named and placed as a collector names and places
    them."""

    def __init__(self, builder: "Builder") -> None:
        self.calls: list[dict[str, Any]] = []
        self.compactions: list[dict[str, Any]] = []
        self.spawned: dict[str, dict[str, Any]] = {}
        """The tool call that started each sub-agent, by the sub-agent's
        name."""
        self._builder = builder
        self._tool_calls = 0
        self._named: dict[str, str] = {}
        self._crossed: int | None = None

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
        message_id = f"msg_{len(self.calls) + 1:04}"
        if step.back_to is not None:
            predecessor: str | None = self._named[step.back_to]
        else:
            predecessor = self.calls[-1]["message_id"] if self.calls else None
        if step.name is not None:
            self._named[step.name] = message_id
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
                tool_calls=[self._tool_call(step, use) for use in step.tools],
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

    def _tool_call(self, call: Call, use: ToolUse) -> dict[str, Any]:
        at = self._builder.time
        self._tool_calls += 1
        tool_call = _given(
            tool_use_id=f"toolu_{self._tool_calls:04}",
            tool=use.tool,
            mcp_server=use.server,
            first_argument=use.argument,
            requested_at=at(call.at),
            returned_at=None if use.took is None else at(call.at + use.took),
            failed=use.failed,
            exit_code=use.exit_code,
            interrupted=False,
            result_characters=use.characters,
        )
        if use.spawns is not None:
            self.spawned[use.spawns] = tool_call
        return tool_call


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
        published: list[dict[str, Any]] = []
        for session in self.scenario.sessions:
            main, thread = self._main(session)
            published.append(main)
            published.extend(
                self._sub_agent(session, agent, thread) for agent in session.sub_agents
            )
        return published

    def _file(
        self, session: Session, size: int, moments: Iterator[int]
    ) -> dict[str, Any]:
        """What every thread of the session's says of its file and of where
        it ran."""
        return _given(
            session_id=self.conversation(session),
            file_size=size,
            file_modified_at=self.time(max(moments)),
            collector={"version": COLLECTOR},
            working_directory=session.directory,
            repository=session.repository,
        )

    def _main(self, session: Session) -> tuple[dict[str, Any], _Thread]:
        thread = _Thread(self)
        launches: list[dict[str, Any]] = []
        place = 0
        for launch in session.launches:
            prompts: list[dict[str, Any]] = []
            for prompt in launch.prompts:
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
                for step in prompt.steps:
                    thread.read(step, place)
            launches.append(
                _given(
                    started_at=self.time(launch.at),
                    ended_at=self.time(max(_launch_moments(launch))),
                    components=[
                        {"component": component, "version": version}
                        for component, version in launch.versions
                    ],
                    prompts=prompts,
                )
            )
        publication = self._file(session, session.size, _main_moments(session))
        publication |= _given(
            environment=session.environment,
            group=None if session.group is None else asdict(session.group),
            launches=launches,
            compactions=thread.compactions,
            calls=thread.calls,
        )
        return publication, thread

    def _sub_agent(
        self, session: Session, agent: SubAgent, main: _Thread
    ) -> dict[str, Any]:
        """The sub-agent's thread, named for the tool call of the main
        thread that started it."""
        thread = _Thread(self)
        for step in agent.steps:
            thread.read(step, None)
        spawning = main.spawned[agent.name]
        publication = self._file(session, agent.size, _moments(agent.steps))
        publication |= _given(
            agent_id=self.agent(session, agent),
            agent_type=agent.type,
            description=spawning.get("first_argument"),
            spawned_by=spawning["tool_use_id"],
            compactions=thread.compactions,
            calls=thread.calls,
        )
        return publication
