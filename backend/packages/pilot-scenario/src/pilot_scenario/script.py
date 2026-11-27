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
    """What occurred at one moment after a Call that no other part of the
    script says, of an Event Kind Claude Code writes a line of: an API error
    a request failed with for good, `api_error`, its status the `detail`, or
    the person's interruption of the response, `interrupt`. Whether it is an
    error is its kind's, as the line says no more."""

    at: int
    kind: str
    detail: str | None = None


@dataclass(frozen=True)
class Retry:
    """An attempt at a Call's request that failed: sent at `sent`, it met an
    API error of that `status` at `failed`, and Claude Code sent the request
    again."""

    sent: int
    failed: int
    status: int | None = None


@dataclass(frozen=True)
class Committed:
    """A commit a Bash call's command made in its session's directory, under
    that `subject`, its own line in the call's output showing its `sha`."""

    subject: str
    sha: str


@dataclass(frozen=True)
class ToolUse:
    """A call of one tool, requested as its Call completed. `took` is the
    seconds to its result, none where none arrived, and `characters` that
    result's length; `saved` the output's full length where it was saved to
    disk, the result then saying so in Claude Code's words; `interrupted`
    whether the person interrupted a command, which came back with no error;
    `denied` the Denial Kind's code where it was denied before it ran, by a
    permission rule (`rule`), the person (`person`) or a hook (`hook`), its
    result an error in Claude Code's words for that, so `failed`; `spawns`
    the sub-agent it started, by name. `added` and `removed` are the lines a
    successful Edit or Write changed of the file its argument names, which
    its result's patch shows, a Write that `created` its file adding its
    content's lines; `commits` the commits a Bash call's command made, its
    argument."""

    tool: str
    argument: str | None = None
    took: int | None = None
    characters: int | None = None
    server: str | None = None
    failed: bool = False
    exit_code: int | None = None
    interrupted: bool = False
    saved: int | None = None
    denied: str | None = None
    spawns: str | None = None
    added: int = 0
    removed: int = 0
    created: bool = False
    commits: tuple[Committed, ...] = ()


@dataclass(frozen=True)
class Call:
    """A request to the model, completed at `at`. `sent` is the moment the
    request was sent, before its response's first line, where Claude Code
    records it. `requested` is the model the request asked for where a
    fallback had `model` answer it instead, and `stop` how the response
    ended where it was no ordinary end, a Stop Reason's code. `back_to`
    makes it a rewind: the earlier Call, by name, its chain continues from.
    `miss` is the cause of a cache miss. `retried` are the attempts at its
    request that failed before the one it answered. `carried` are its
    Context Parts: on a Launch's first Call its system prompt, its tools and
    its instruction files first, then a compaction's summary, one per
    compaction since the Call before it, then what else was injected before
    it, in the order its lines are written."""

    at: int
    tokens: Tokens
    sent: int | None = None
    name: str | None = None
    model: str = "claude-opus-4-5"
    requested: str | None = None
    stop: str | None = None
    effort: str | None = None
    thinking: int | None = None
    skill: str | None = None
    plugin: str | None = None
    miss: str | None = None
    back_to: str | None = None
    tools: tuple[ToolUse, ...] = ()
    retried: tuple[Retry, ...] = ()
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
    """A run of one hook command at the end of a Prompt's run, a Stop
    hook's: `failed` where it reported an error, `held` where it kept the
    run from ending, which Claude Code records of all a Prompt's hooks at
    once."""

    command: str
    took_ms: int
    failed: bool = False
    held: bool = False


@dataclass(frozen=True)
class Prompt:
    """An input a Launch received, its `source` in Claude Code's word for it
    (`sdk`, `typed`, `queued`, `system` or `suggestion_accepted`), with what
    followed it, in order, and the hooks run at its run's end."""

    at: int
    source: str
    characters: int
    steps: tuple[Call | Compaction, ...] = ()
    hooks: tuple[HookRun, ...] = ()


@dataclass(frozen=True)
class Launch:
    """A start of a Claude Code process, under a version of each component
    it ran with, by `(component, version)`: `claude-code`, and each plugin,
    `plugin:<name>`, a skill of which it loads. It starts as its first
    Prompt arrives, its file's first line with a time, and ends with the
    last line it writes that carries one. One `killed` writes no closing
    line, and the next process runs another version of Claude Code."""

    versions: tuple[tuple[str, str], ...]
    prompts: tuple[Prompt, ...]
    killed: bool = False


@dataclass(frozen=True)
class SubAgent:
    """A sub-agent's thread of a session, started by the `ToolUse` that
    `spawns` it."""

    name: str
    type: str
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
class Group:
    """A group of work done before Pilot ran any: its `key`, which never
    changes, and its name and summary as they now stand."""

    key: str
    name: str
    summary: str


@dataclass(frozen=True)
class Session:
    """A conversation with Claude Code in one directory, its main thread and
    its sub-agents'. One Pilot ran has its `turn`; one a person ran by hand
    has that `person`, is on no project of Pilot's running, and may belong to
    a `group`. `unit` is the unit of work it ran. Its `repository` is the
    checkout its `directory` lies under, and its `environment` the one that
    hosted it, each none where it has none."""

    name: str
    directory: str
    launches: tuple[Launch, ...]
    environment: str | None = None
    repository: str | None = None
    turn: Turn | None = None
    person: str | None = None
    unit: str | None = None
    group: Group | None = None
    sub_agents: tuple[SubAgent, ...] = ()


@dataclass(frozen=True)
class Unit:
    """A unit of the scenario's work, of one of its kinds; `within` names the
    unit it is a part of, `project` the project of one that is part of
    none. `role` is the role that did it, `round` its round among that
    role's, and `rework_kind` the Rework Kind's code where it is work done
    again, each none where it has none."""

    kind: str
    name: str
    project: str | None = None
    within: str | None = None
    role: str | None = None
    round: int | None = None
    rework_kind: str | None = None


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
