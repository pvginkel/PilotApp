"""The builder: one scenario turned into what a layer reads.

For a collector that is each thread of the scenario's conversations as a
file in Claude Code's line shapes, in a home laid out as the fleet's is, with
the run records the stub labeller reads (`pilot_scenario.labeller`); for the
backend's ingest, those conversations as a collector publishes them under the
stub, one whole publication a thread, in the shape of the collector's call,
the stub's vocabularies as a collector declares them, and the Turns of
Pilot's its sessions ran under, which Pilot's side holds before a collector
reads the transcript.

A publication is what its thread's file says: the file's size and time, and
each fact as the lines carry it. The files hold the lines these facts are
read off: a thread's ids and where it ran, its Launches, each to its last
line with a time and with the plugins whose skills it loaded, its Prompts,
Calls and Tool Calls, a denied call's denial among them, its Compactions, each Call's
place on the chain, the request it answered and those that failed before
it, what Claude Code records of its choices, the Events, the Stop hooks
run at a Prompt's end, and each Call's context parts: on a Launch's first
Call the system prompt and the tools its request's shape sent, the
instruction files and the Prompts received before it, a sub-agent's task,
and on any Call what was injected before it, a compaction's summary among
it. Beside a sub-agent's file lies its record: its type, its description and
the call that started it, a main thread's or another sub-agent's.

A publication's labelling and group are the stub's answer for its thread's
file, labelled whole, with Pilot handing nothing for its conversation: what a
collector publishes under the stub where Pilot holds no Session of it.

A conversation's ids are the scenario's own, the same in every build, so
that a scenario published again is the same conversations again. A build's
last moment falls at `until`, cut to the millisecond a line's time is
written to, the scenario's times laid back from there.
"""

import json
import os
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

from pilot_scenario import labeller
from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    Launch,
    Scenario,
    Session,
    SubAgent,
    ToolUse,
    Unit,
)
from pilot_scenario.transcript import MANAGED, HomeFile, Lines, Spawned, request, text

COLLECTOR = "1.4.0"
"""The version of the collector the publications say read the files."""

_UNKEPT = ("batchable_condition",)
"""The lists the stub declares that the record keeps no place for, which a
collector's declaration leaves out."""

CLAUDE_CODE = "claude-code"
"""The component whose version a Launch's lines carry."""

_PLUGIN = "plugin:"
"""What a plugin's component's code opens with, before the plugin's name."""

_IDS = uuid.UUID("6c1f0e9a-3b5d-4c7e-8f2a-9d4b1e6a7c30")
"""The namespace the conversations' ids are drawn in."""

_EPOCH = datetime.fromtimestamp(0, UTC)

_TASK = text(220)
"""The task an Agent call gives the sub-agent it starts."""

_ERROR = "api_error"
"""The Event Kind of an occurrence that is an error: an interruption is
none."""

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
    moment it was requested at, Claude Code's version and the plugins' its
    process ran, and the thread it is of, by its sub-agent's id, none for
    the main thread, at its depth, the main thread's 0."""

    tool_call: dict[str, Any]
    at: int
    version: str
    plugins: dict[str, str]
    agent: str | None
    depth: int


@dataclass(frozen=True)
class _Built:
    """A thread as it is built: its publication, its files, the transcript's
    first, and the transcript as a collector hands it to the labeller to
    label whole, but for its Calls."""

    publication: dict[str, Any]
    files: list[HomeFile]
    handed: dict[str, Any]
    launch_of: dict[str, int]
    """A main thread's Launch of each Call, by its `message_id`."""


def _given(**facts: Any) -> dict[str, Any]:
    """The facts that are given: a call leaves out what its file does not
    have."""
    return {name: fact for name, fact in facts.items() if fact not in (None, [])}


def _assistants(content: bytes) -> list[str]:
    """The `message.id` of each assistant line of a file, in the order of its
    first: the Calls a collector hands the labeller, a line Claude Code wrote
    itself among them."""
    ids: dict[str, None] = {}
    for raw in content.splitlines():
        line = json.loads(raw)
        if line.get("type") == "assistant":
            ids.setdefault(line["message"]["id"], None)
    return list(ids)


def _moments(steps: Sequence[Step]) -> Iterator[int]:
    """Each moment something of the steps was written at."""
    for step in steps:
        yield step.at
        if isinstance(step, Call):
            yield from (
                step.at + use.took for use in step.tools if use.took is not None
            )
            yield from (occurrence.at for occurrence in step.occurred)
            for retry in step.retried:
                yield from (retry.sent, retry.failed)


_SHAPED = ("system_prompt", "tool_schemas")
"""The Context Part Kinds a request's shape holds."""

_SUMMARY = "compact_summary"
"""The Context Part Kind of a compaction's summary."""


def _summary(later: Sequence[Step], made: int) -> int:
    """The characters of the summary of a compaction, the `made`th since
    the last Call from 0, `later` the steps after it in its Launch: the
    `made`th summary the next Call carries."""
    call = next((step for step in later if isinstance(step, Call)), None)
    summaries = (
        []
        if call is None
        else [part.characters for part in call.carried if part.kind == _SUMMARY]
    )
    if len(summaries) <= made:
        raise ValueError(
            "A compaction's summary is a part of the next Call of its Launch: it"
            " carries a `compact_summary`"
        )
    return summaries[made]


def _injected(call: Call, first: bool) -> list[Carried]:
    """The parts of `call` whose lines are written just before its request:
    all but those of its request's shape, a compaction's summary and, on a
    Launch's first Call, its instruction files. The Call lists its parts as
    their lines are written: on a Launch's first Call the system prompt, the
    tools and the instruction files first, then a compaction's summary, then
    what else was injected."""
    ranks = (
        {"system_prompt": 0, "tool_schemas": 1, "instruction_file": 2, _SUMMARY: 3}
        if first
        else {"system_prompt": 0, "tool_schemas": 0, _SUMMARY: 1}
    )
    order = [ranks.get(part.kind, len(ranks)) for part in call.carried]
    if order != sorted(order):
        raise ValueError(
            "A Call's parts are listed as its lines are written: a Launch's first"
            " Call's system prompt, tools and instruction files first, then a"
            " compaction's summary, then what else was injected"
        )
    held = (*_SHAPED, _SUMMARY, *(("instruction_file",) if first else ()))
    return [part for part in call.carried if part.kind not in held]


def _instruction_files(steps: Iterator[Step]) -> list[tuple[str, int]]:
    """The instruction files the first Call of the steps carries, each its
    path and its characters."""
    first = next((step for step in steps if isinstance(step, Call)), None)
    if first is None:
        return []
    files = []
    for part in first.carried:
        if part.kind != "instruction_file":
            continue
        if part.name is None:
            raise ValueError("An instruction file is named by its path")
        files.append((part.name, part.characters))
    return files


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
    tool call names the one it started, by name; `agent` is the thread's own
    sub-agent's id, none for the main thread, at its `depth`."""

    def __init__(
        self,
        builder: "Builder",
        ids: _Ids,
        lines: Lines,
        agents: Mapping[str, Spawned],
        agent: str | None = None,
        depth: int = 0,
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
        self._agent = agent
        self._depth = depth
        self._named: dict[str, str] = {}
        self._leaves: dict[str, str | None] = {}
        """The chain's last line once each named Call was written, with its
        tools' results."""
        self._crossed: int | None = None
        self._summaries = 0
        """The compactions since the last Call, whose summaries the next
        carries."""
        self._skills: dict[str, str] = {}
        """The latest `Skill` call that asked for each skill: its id, by the
        skill."""
        self.opening: list[int] | None = None
        """The characters of each Prompt received since the Launch began,
        or of a sub-agent's task, none once its first Call carried them."""

    def back(self, step: Step) -> None:
        """Where the step is a rewind, the chain goes on from the Call it
        went back to."""
        if isinstance(step, Call) and step.back_to is not None:
            self.lines.leaf = self._leaves[step.back_to]

    def read(self, step: Step, prompt: int | None, later: Sequence[Step]) -> None:
        """Take the thread's next step, under the Prompt at that place,
        `later` the steps after it in its Launch."""
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
            summary = _summary(later, self._summaries)
            self._summaries += 1
            self.lines.compacted(step, self._builder.when(step.at), summary)
            return
        if sum(part.kind == _SUMMARY for part in step.carried) != self._summaries:
            raise ValueError(
                "A Call carries the summary of each compaction since the Call"
                " before it, and no other"
            )
        self._summaries = 0
        injected = [
            (
                part,
                self._skills.get(part.name or "")
                if part.kind == "skill_body"
                else None,
            )
            for part in _injected(step, self.opening is not None)
        ]
        self.ids.messages += 1
        message_id = f"msg_{self.ids.messages:04}"
        if step.back_to is not None:
            predecessor: str | None = self._named[step.back_to]
        else:
            predecessor = self.calls[-1]["message_id"] if self.calls else None
        if step.name is not None:
            self._named[step.name] = message_id
        tool_calls = [self._tool_call(step, use) for use in step.tools]
        retried = [
            _given(
                kind="api_retry",
                is_error=True,
                at=at(retry.failed),
                detail=None if retry.status is None else str(retry.status),
            )
            for retry in step.retried
        ]
        if retried and self.calls:
            self.calls[-1].setdefault("events", []).extend(retried)
            retried = []
        self.calls.append(
            _given(
                message_id=message_id,
                prompt=prompt,
                predecessor=predecessor,
                compaction=self._crossed,
                sent_at=None if step.sent is None else at(step.sent),
                completed_at=at(step.at),
                model=step.model,
                requested_model=step.requested,
                effort=step.effort,
                stop_reason=step.stop,
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
                events=retried
                + [
                    _given(
                        kind=occurrence.kind,
                        is_error=occurrence.kind == _ERROR,
                        at=at(occurrence.at),
                        detail=occurrence.detail,
                    )
                    for occurrence in step.occurred
                ],
                context_parts=[
                    _given(kind=part.kind, name=part.name, characters=part.characters)
                    for part in step.carried
                ]
                + [
                    {"kind": "prompt", "characters": characters}
                    for characters in self.opening or []
                ],
            )
        )
        self.opening = None
        self._crossed = None
        self._write(
            step, message_id, [call["tool_use_id"] for call in tool_calls], injected
        )
        if step.name is not None:
            self._leaves[step.name] = self.lines.leaf
        for occurrence in step.occurred:
            self.lines.occurred(occurrence, self._builder.when(occurrence.at))

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
            denial_kind=use.denied,
            result_characters=use.characters,
            saved_characters=use.saved,
        )
        if use.spawns is not None:
            self.spawned[use.spawns] = _Spawning(
                tool_call,
                call.at,
                self.lines.version,
                dict(self.lines.plugins),
                self._agent,
                self._depth,
            )
        if use.tool == "Skill" and use.argument is not None:
            self._skills[use.argument] = tool_call["tool_use_id"]
        return tool_call

    def _write(
        self,
        call: Call,
        message_id: str,
        tool_use_ids: list[str],
        injected: list[tuple[Carried, str | None]],
    ) -> None:
        """The Call's lines: what was `injected` before its request, each
        part with the id of the `Skill` call a skill's body expands, written
        as its first request was sent; each attempt at its request that
        failed, its response's, then each result that arrived, in the order
        the tools were requested."""
        when = self._builder.when
        sent = call.retried[0].sent if call.retried else call.sent
        for part, skill in injected:
            self.lines.injected(part, when(call.at if sent is None else sent), skill)
        for attempt, retry in enumerate(call.retried, start=1):
            self.lines.retried(
                call, retry, attempt, when(retry.sent), when(retry.failed)
            )
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
            None if call.sent is None else when(call.sent),
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
        `projects`, each at the time its publication gives, and the stub
        labeller's run records where it reads them under `plugins`."""
        for file in self.files():
            target = home / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.content)
            at = (file.modified_at - _EPOCH) // timedelta(microseconds=1) * 1000
            os.utime(target, ns=(at, at))
        records = home / "plugins" / "data" / labeller.DATA / labeller.RECORDS
        records.parent.mkdir(parents=True, exist_ok=True)
        records.write_text(json.dumps(self.records(), indent=2) + "\n")

    def records(self) -> dict[str, Any]:
        """The stub labeller's run records of the scenario: its kinds of work;
        its units, each named by its key, a unit its session ran with that
        session's times and served, one cut into parts with their count; the
        unit each session ran, by its conversation; and each group with the
        conversations it adopts."""
        units = {unit.name: unit for unit in self.scenario.units}

        def key(unit: Unit) -> str:
            if unit.within is None:
                return f"{unit.project}|{unit.name}"
            return f"{key(units[unit.within])}|{unit.name}"

        ran = {
            session.unit: session
            for session in self.scenario.sessions
            if session.unit is not None
        }
        parts = Counter(unit.within for unit in self.scenario.units)
        rows = []
        for unit in self.scenario.units:
            row: dict[str, Any] = {
                "key": key(unit),
                "kind": unit.kind,
                "title": unit.name,
                "part_of": None if unit.within is None else key(units[unit.within]),
            }
            session = ran.get(unit.name)
            if session is not None:
                moments = list(_session_moments(session))
                row |= {
                    "started_at": self.time(min(moments)),
                    "ended_at": self.time(max(moments)),
                    "outcome": labeller.SERVED,
                }
            if parts[unit.name]:
                row["measures"] = [{"measure": "parts", "amount": parts[unit.name]}]
            rows.append(row)
        groups: dict[str, dict[str, Any]] = {}
        for session in self.scenario.sessions:
            if session.group is None:
                continue
            group = groups.setdefault(
                session.group.key,
                asdict(session.group)
                | {"repository": session.repository, "conversations": []},
            )
            group["conversations"].append(self.conversation(session))
        return {
            "kinds": list(self.scenario.kinds),
            "units": rows,
            "ran": {
                self.conversation(session): key(units[name])
                for name, session in ran.items()
            },
            "groups": list(groups.values()),
        }

    def vocabularies(self) -> dict[str, Any]:
        """The stub labeller's vocabularies of the scenario as a collector
        declares them to Pilot: its version, every list the record keeps and
        the nestings, its groups left out."""
        declared = labeller.vocabularies(self.records())
        return {
            "version": declared["version"],
            "lists": {
                name: values
                for name, values in declared["lists"].items()
                if name not in _UNKEPT
            },
            "nesting": declared["nesting"],
        }

    @cached_property
    def _threads(self) -> list[_Built]:
        built: list[_Built] = []
        for session in self.scenario.sessions:
            main, thread = self._main(session)
            built.append(main)
            spawned = dict(thread.spawned)
            for agent in session.sub_agents:
                if agent.name not in spawned:
                    raise ValueError(
                        "A sub-agent is started by a call of its main thread or of a"
                        f" sub-agent before it: none starts `{agent.name}`"
                    )
                sub_agent, started = self._sub_agent(
                    session, agent, spawned[agent.name], thread.ids
                )
                built.append(sub_agent)
                spawned |= started.spawned
        records = self.records()
        groups = {
            group["key"]: {name: group[name] for name in ("key", "name", "summary")}
            for group in labeller.vocabularies(records)["groups"]
        }
        for each in built:
            self._labelled(each, records, groups)
        return built

    def _labelled(
        self,
        thread: _Built,
        records: Mapping[str, Any],
        groups: Mapping[str, dict[str, Any]],
    ) -> None:
        """Give the thread's publication the stub's labelling of its file,
        labelled whole with nothing handed for its conversation, as a
        collector publishes it. The labeller is handed every Call it reads,
        a line Claude Code wrote itself among them, each in its Launch, the
        one of the Call before it where the publication holds none of its
        own; the labelling holds the labels of the publication's Calls and
        the Segments they fall in, a main thread's adopted group as its
        `group`, and the batchable condition, which the record keeps no
        place for, left out."""
        publication = thread.publication
        content = thread.files[0].content
        held = {call["message_id"] for call in publication["calls"]}
        calls = []
        launch: int | None = None
        for position, message_id in enumerate(_assistants(content), start=1):
            call: dict[str, Any] = {"id": message_id, "position": position}
            if thread.launch_of:
                launch = thread.launch_of.get(message_id, launch or 1)
                call["launch"] = launch
            calls.append(call)
        answer = labeller.label(
            content,
            thread.handed | {"calls": calls},
            {"session_id": publication["session_id"], "sessions": [], "documents": []},
            frozenset(),
            records,
        )
        labels = {
            name: rows
            for name, rows in answer["labels"].items()
            if name != "transcript"
        }
        labels["calls"] = [
            {name: label for name, label in call.items() if name not in _UNKEPT}
            for call in labels["calls"]
            if call["id"] in held
        ]
        named = {call["segment"] for call in labels["calls"]}
        labels["segments"] = [
            segment for segment in labels["segments"] if segment["position"] in named
        ]
        publication["labelling"] = {
            "version": labeller.VERSION,
            "stamp": answer["stamp"],
            "labels": labels,
            "units": answer["units"],
            "test_suites": answer["test_suites"],
            "ci_builds": answer["ci_builds"],
        }
        for transcript in answer["labels"]["transcript"]:
            if transcript["adopted_group"] is not None:
                publication["group"] = groups[transcript["adopted_group"]]

    def _lines(self, session: Session, agent: SubAgent | None = None) -> Lines:
        entrypoint = "sdk-cli" if session.person is None else "cli"
        if agent is None:
            return Lines(self.conversation(session), session.directory, entrypoint)
        named = self.agent(session, agent)
        return Lines(
            self.conversation(session), session.directory, entrypoint, named, agent.type
        )

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
        ends: list[int] = []
        """The count of the thread's Calls by each Launch's end."""
        place = 0
        killed: str | None = None
        for launch in session.launches:
            steps = [step for prompt in launch.prompts for step in prompt.steps]
            taken = 0
            versions = dict(launch.versions)
            if versions[CLAUDE_CODE] == killed:
                raise ValueError(
                    "A process picked up under the version of Claude Code a killed"
                    " one ran joins its Launch: it runs another version"
                )
            lines.launched(
                versions[CLAUDE_CODE],
                {
                    code.removeprefix(_PLUGIN): version
                    for code, version in launch.versions
                    if code.startswith(_PLUGIN)
                },
            )
            thread.opening = []
            loaded = _instruction_files(
                step for prompt in launch.prompts for step in prompt.steps
            )
            if session.environment is not None and MANAGED not in dict(loaded):
                raise ValueError(
                    "A process an environment hosts loads the managed instruction"
                    " file: its Launch's first Call carries it"
                )
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
                if thread.opening is not None:
                    thread.opening.append(prompt.characters)
                if received == 0:
                    lines.instructed(loaded, session.environment, self.when(prompt.at))
                for followed, step in enumerate(prompt.steps):
                    if followed:
                        thread.back(step)
                    taken += 1
                    thread.read(step, place, steps[taken:])
                if prompt.hooks:
                    last = max((prompt.at, *_moments(prompt.steps)))
                    lines.hooked(prompt.hooks, self.when(last))
            unread = [
                code
                for code in versions
                if code != CLAUDE_CODE
                and code.removeprefix(_PLUGIN) not in lines.loaded
            ]
            if unread:
                raise ValueError(
                    "A Launch's components are read off its lines: Claude Code's"
                    " version, and each plugin's a skill of it loaded names; no line"
                    f" names `{unread[0]}`"
                )
            started, ended = launch.prompts[0].at, lines.ended
            assert ended is not None
            killed = versions[CLAUDE_CODE] if launch.killed else None
            if not launch.killed:
                lines.exited(
                    self.when(started),
                    self.when(max(_launch_moments(launch))),
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
                    ended_at=ended.isoformat(),
                    components=[
                        {"component": CLAUDE_CODE, "version": versions[CLAUDE_CODE]},
                        *(
                            {
                                "component": f"{_PLUGIN}{plugin}",
                                "version": lines.plugins[plugin],
                            }
                            for plugin in lines.loaded
                        ),
                    ],
                    prompts=prompts,
                )
            )
            ends.append(len(thread.calls))
        publication, files = self._thread(session, lines, _main_moments(session))
        publication |= _given(
            environment=session.environment,
            launches=launches,
            compactions=thread.compactions,
            calls=thread.calls,
        )
        handed = {
            "agent_id": None,
            "mode": "whole",
            "launches": [
                {"n": n, "started_at": launch["started_at"]}
                for n, launch in enumerate(launches, start=1)
            ],
        }
        launch_of = {
            call["message_id"]: next(
                n for n, end in enumerate(ends, start=1) if position <= end
            )
            for position, call in enumerate(thread.calls, start=1)
        }
        return _Built(publication, files, handed, launch_of), thread

    def _sub_agent(
        self, session: Session, agent: SubAgent, spawning: _Spawning, ids: _Ids
    ) -> tuple[_Built, _Thread]:
        """The sub-agent's thread, named for the tool call that started it,
        and its record; its ids counted on with `ids`, the conversation's."""
        lines = self._lines(session, agent)
        lines.version = spawning.version
        lines.plugins = spawning.plugins
        lines.tasked(_TASK, self.when(spawning.at))
        lines.instructed(
            _instruction_files(iter(agent.steps)),
            session.environment,
            self.when(spawning.at),
        )
        named = self.agent(session, agent)
        thread = _Thread(
            self, ids, lines, self._agents(session), named, spawning.depth + 1
        )
        thread.opening = [len(_TASK)]
        for taken, step in enumerate(agent.steps, start=1):
            thread.back(step)
            thread.read(step, None, agent.steps[taken:])
        publication, (transcript, *saved) = self._thread(
            session, lines, _moments(agent.steps)
        )
        description = spawning.tool_call.get("first_argument")
        record = lines.recorded(
            agent.type,
            description,
            spawning.tool_call["tool_use_id"],
            spawning.agent,
            spawning.depth + 1,
            self.when(spawning.at),
        )
        publication |= _given(
            agent_id=named,
            agent_type=agent.type,
            description=description,
            spawned_by=spawning.tool_call["tool_use_id"],
            compactions=thread.compactions,
            calls=thread.calls,
        )
        handed = {"agent_id": named, "agent_type": agent.type, "mode": "whole"}
        built = _Built(publication, [transcript, record, *saved], handed, {})
        return built, thread
