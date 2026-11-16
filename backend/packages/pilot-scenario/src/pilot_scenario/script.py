"""The words a scenario is written in: its world, its kinds of work and their
units, the sessions that ran them and what happened in each.

A moment is a number of seconds from the scenario's start. A call's name is
what a later call of its thread refers to it by, and reaches no layer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    """The tokens a Call was billed, by the kinds nothing is within."""

    input: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output: int = 0


@dataclass(frozen=True)
class Carried:
    """A part of what a Call carried that no earlier Call of its Launch did."""

    kind: str
    characters: int
    name: str | None = None


@dataclass(frozen=True)
class Occurrence:
    """What occurred at one moment that no other part of the script says: an
    API error."""

    at: int
    kind: str
    is_error: bool
    detail: str | None = None


@dataclass(frozen=True)
class ToolUse:
    """A call of one tool, requested as its Call completed. `took` is the
    seconds to its result, none where none arrived; `spawns` the sub-agent it
    started, by name."""

    tool: str
    argument: str | None = None
    took: int | None = None
    characters: int | None = None
    server: str | None = None
    failed: bool = False
    exit_code: int | None = None
    spawns: str | None = None


@dataclass(frozen=True)
class Call:
    """A request to the model, completed at `at`. `back_to` makes it a
    rewind: the earlier Call, by name, its chain continues from. `miss` is
    the cause of a cache miss."""

    at: int
    tokens: Tokens
    name: str | None = None
    model: str = "claude-opus-4-5"
    effort: str | None = None
    thinking: int | None = None
    skill: str | None = None
    plugin: str | None = None
    miss: str | None = None
    back_to: str | None = None
    tools: tuple[ToolUse, ...] = ()
    occurred: tuple[Occurrence, ...] = ()
    carried: tuple[Carried, ...] = ()


@dataclass(frozen=True)
class Compaction:
    """A compaction of the thread's context, of `before` tokens to `after`."""

    at: int
    trigger: str
    before: int
    after: int | None = None
    took_ms: int | None = None


@dataclass(frozen=True)
class HookRun:
    """A run of one hook command at the end of a Prompt's run."""

    command: str
    took_ms: int
    failed: bool = False
    held: bool = False


@dataclass(frozen=True)
class Prompt:
    """An input a Launch received, with what followed it, in order, and the
    hooks run at its run's end."""

    at: int
    source: str
    characters: int
    steps: tuple[Call | Compaction, ...] = ()
    hooks: tuple[HookRun, ...] = ()


@dataclass(frozen=True)
class Launch:
    """A start of a Claude Code process, under a version of each component
    it ran with, by `(component, version)`. It ends with the last moment of
    what it received."""

    at: int
    versions: tuple[tuple[str, str], ...]
    prompts: tuple[Prompt, ...] = ()


@dataclass(frozen=True)
class SubAgent:
    """A sub-agent's thread of a session, started by the `ToolUse` that
    `spawns` it; `size` is its file's, in bytes."""

    name: str
    type: str
    size: int
    steps: tuple[Call | Compaction, ...]


@dataclass(frozen=True)
class Turn:
    """A Turn of Pilot's that a session ran under: the message Pilot sent it
    on one of the scenario's projects, from `at` to `ended`."""

    project: str
    message: str
    at: int
    ended: int


@dataclass(frozen=True)
class Session:
    """A conversation with Claude Code in one directory, its main thread and
    its sub-agents'. One Pilot ran has its `turn`; one a person ran by hand
    has that `person` and is on no project. `unit` is the unit of work it
    ran; `size` its main thread's file's, in bytes."""

    name: str
    directory: str
    size: int
    launches: tuple[Launch, ...]
    environment: str | None = None
    repository: str | None = None
    turn: Turn | None = None
    person: str | None = None
    unit: str | None = None
    sub_agents: tuple[SubAgent, ...] = ()


@dataclass(frozen=True)
class Unit:
    """A unit of the scenario's work, of one of its kinds; `within` names the
    unit it is a part of, `project` the project of one that is part of
    none."""

    kind: str
    name: str
    project: str | None = None
    within: str | None = None


@dataclass(frozen=True)
class Scenario:
    """A short script in invented words, under the name its conversations'
    ids are drawn from. `kinds` are its kinds of work, the widest first: each
    but the first is a part of the one before it."""

    name: str
    people: tuple[str, ...]
    projects: tuple[str, ...]
    kinds: tuple[str, ...]
    units: tuple[Unit, ...]
    sessions: tuple[Session, ...]
