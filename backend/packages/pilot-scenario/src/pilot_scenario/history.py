"""A history of Pilot's record: days of the fleet's work, each a scenario of
the scenario's own script, in its invented words, drawn from a seed and the
day.

A day is drawn from the history's seed and its date, so that a day is the
same in every history of that seed that holds it, and a larger history is a
smaller one with earlier days before it. Its moment 0 is its local midnight
in the engine's default zone (`ZONE`), so that a build of it
(`Day.builder`) writes each Call at the time of day it was drawn at.

Its shape is the fleet's as `architecture.md` *The sizes* has it, at the
Calls a day the history is drawn at: about thirty Calls a transcript, fewer
at the weekend, a third of the conversations with sub-agents, nearly half of
them Pilot's own. A conversation of Pilot's is a work item's run, a job, a
chat or a conversation from outside it (`script.Ran`), in its project's
checkout or, but for a run, in Pilot's store; one in every thirty or so is
never collected, its Turns standing in with the tokens its Calls would have
billed (`Day.standing`). One by hand is a person's, on no project of
Pilot's running, of a group of work done before Pilot ran any now and then
where its project has one.
"""

import hashlib
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pilot_scenario.builder import Builder, last_moment
from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    Group,
    HookRun,
    Launch,
    Occurrence,
    Prompt,
    Ran,
    Scenario,
    Session,
    SubAgent,
    Tokens,
    ToolUse,
    Turn,
)
from pilot_scenario.transcript import MANAGED

WEEKEND = 0.6
"""The share of a weekday's Calls a day at the weekend holds."""

ZONE = ZoneInfo("Europe/Amsterdam")
"""The zone a day's hours are drawn in, the engine's default."""

PEOPLE = (("ada", "Ada Example"), ("ben", "Ben Example"))
"""The people who work by hand and write to Pilot's chats, by handle and
name: the dev seed's."""

STORE = "/work/Larder"
"""Where Pilot's chats and jobs run: its store, by an invented name."""

STORE_ENVIRONMENT = "pilot-larder-4b7d21"

ERRANDS = (
    "Halve the stew",
    "Sort the spices",
    "Oil the chain",
    "Map the beds",
    "Count the seeds",
    "Tune the kites",
    "Plan the rota",
    "Read the tides",
    "Label the jars",
    "Mend the lines",
)
"""What Pilot's conversations are about, their work items' titles."""

_MODELS = (
    (
        date(2026, 6, 1),
        ("claude-opus-4-5", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    ),
    (date.max, ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")),
)
"""The models of a day, the largest, the middle and the smallest, by the day
before which they ran: the public ones."""

_TOOLS = (
    ("Read", 30),
    ("Edit", 18),
    ("Bash", 20),
    ("Grep", 12),
    ("Glob", 6),
    ("Write", 6),
    ("mcp__pantry__list_recipes", 4),
    ("WebFetch", 4),
)

_TTL = {"5m": 300, "1h": 3_600}

_TASK = "Find where the {word} are counted"

_SKILL = "pantry:scaling"
"""The skill a work Launch loads, which is what names its plugin."""


@dataclass(frozen=True)
class Place:
    """One of a history's projects, by the scenario's name of it, with the
    checkout its work runs in, its share of the work, the words its work is
    about, and the group a conversation by hand on it may be of."""

    slug: str
    name: str
    repository: str
    weight: int
    words: tuple[str, ...]
    group: Group | None = None

    @property
    def directory(self) -> str:
        return f"/work/{self.repository}"


@dataclass(frozen=True)
class Day:
    """A day of a history: its scenario, its Calls, and the conversations of
    Pilot's never collected, by their sessions' names, with the tokens their
    Turns stand in with."""

    day: date
    scenario: Scenario
    calls: int
    standing: dict[str, Tokens]
    start: datetime

    def builder(self) -> Builder:
        """The day built at its own times."""
        return Builder.starting(self.scenario, self.start)

    def before(self, moment: datetime) -> "Day":
        """The day with only the conversations that ended before `moment`."""
        sessions = tuple(
            session
            for session in self.scenario.sessions
            if self.start + timedelta(seconds=last_moment(session)) < moment
        )
        return replace(
            self,
            scenario=replace(self.scenario, sessions=sessions),
            calls=sum(_calls(session) for session in sessions),
            standing={
                name: tokens
                for name, tokens in self.standing.items()
                if name in {session.name for session in sessions}
            },
        )


@dataclass(frozen=True)
class History:
    """How a history is drawn: from `seed`, about `calls_a_day` Calls on a
    weekday, on the projects `places`, its scenarios named `name/<day>`, so
    that their conversations' ids are its own, a conversation's main thread
    drawn with `longest` Calls at most. With `long_calls`, a Wednesday opens
    on a conversation by hand whose main thread has that many Calls."""

    name: str
    seed: int
    calls_a_day: int
    places: tuple[Place, ...]
    long_calls: int | None = None
    longest: int = 1_500

    def target(self, day: date) -> int:
        """The Calls a day is drawn to hold, at least: its share of
        `calls_a_day`, give or take a quarter."""
        rng = random.Random(f"{self.seed}/{day.isoformat()}/target")
        share = WEEKEND if day.weekday() >= 5 else (7 - 2 * WEEKEND) / 5
        return round(self.calls_a_day * share * rng.uniform(0.75, 1.25))

    def days(self, calls: int, last: date) -> list[date]:
        """The days a history of `calls` Calls holds, ending on `last`: back
        from it until their targets reach `calls`."""
        held: list[date] = []
        total = 0
        day = last
        while total < calls:
            held.append(day)
            total += self.target(day)
            day -= timedelta(days=1)
        return held

    def draw(self, day: date, calls: int | None = None) -> Day:
        """A day of the history, drawn from its seed: its `target`'s Calls
        at least, or the `calls` given."""
        drawn = _Drawn(day, self.seed)
        rng = drawn.rng
        goal = self.target(day) if calls is None else calls
        sessions: list[Session] = []
        standing: dict[str, Tokens] = {}
        calls = 0
        while calls < goal:
            name = f"s{len(sessions):04}"
            place = rng.choices(self.places, [p.weight for p in self.places])[0]
            long = self.long_calls if day.weekday() == 2 and not sessions else None
            pilot = long is None and rng.random() < 0.45
            main_calls = (
                long if long is not None else drawn.lognormal(26, 0.9, 1, self.longest)
            )
            agents: list[SubAgent] = []
            start = drawn.hour(pilot)
            large, middle, _ = drawn.models
            model = large if rng.random() < 0.8 else middle
            if pilot:
                session, stands_in = self._pilots(
                    drawn, name, place, start, main_calls, model, agents, sessions
                )
                if stands_in:
                    standing[name] = billed(session)
            else:
                session = self._by_hand(
                    drawn, name, place, start, main_calls, model, agents
                )
            sessions.append(session)
            calls += main_calls + sum(
                1 for agent in agents for step in agent.steps if isinstance(step, Call)
            )
        scenario = Scenario(
            name=f"{self.name}/{day.isoformat()}",
            people=tuple(p for p, _ in PEOPLE),
            projects=tuple(p.slug for p in self.places),
            kinds=("errand",),
            units=(),
            sessions=tuple(sessions),
        )
        midnight = datetime.combine(day, datetime.min.time(), ZONE).astimezone(UTC)
        return Day(day, scenario, calls, standing, midnight)

    def _pilots(
        self,
        drawn: "_Drawn",
        name: str,
        place: Place,
        start: int,
        main_calls: int,
        model: str,
        agents: list[SubAgent],
        sessions: list[Session],
    ) -> tuple[Session, bool]:
        """One of Pilot's conversations, and whether it stands in."""
        rng = drawn.rng
        kind = rng.choices(("work", "job", "chat", "conversation"), (55, 20, 20, 5))[0]
        turns = rng.choices((1, 2, 3), (70, 20, 10))[0] if kind != "job" else 1
        spans = _spans(rng, main_calls, turns)
        launches = []
        runs: list[tuple[str, int, int, str | None]] = []
        at = start
        for n, span in enumerate(spans):
            cuts = _prompt_cuts(rng, span, 15, 60) if rng.random() < 0.1 else []
            skilled = kind == "work" and span >= 2 and n == 0
            parts, ended = drawn.thread(
                at + 4,
                span,
                place,
                model,
                "1h",
                cuts,
                agents,
                "high",
                skilled=skilled,
            )
            prompts = []
            for p, steps in enumerate(parts):
                hooks = (
                    HookRun(
                        "tidy_up.sh",
                        took_ms=rng.randint(80, 400),
                        failed=rng.random() < 0.03,
                    ),
                )
                first = next(s.at for s in steps)
                prompts.append(
                    Prompt(
                        at=drawn.moments.at(first - 2),
                        source="sdk" if p == 0 else "queued",
                        characters=rng.randint(200, 4_000),
                        steps=tuple(steps),
                        hooks=hooks,
                    )
                )
            launches.append(
                Launch(versions=_versions(drawn, skilled), prompts=tuple(prompts))
            )
            cause = (
                "person"
                if kind in ("chat", "conversation")
                else "brief"
                if n == 0
                else rng.choice(("continuation", "resume", "nudge"))
            )
            author = rng.choice(PEOPLE)[0] if cause == "person" else None
            runs.append((cause, at, drawn.moments.at(ended + 1), author))
            at = ended + drawn.lognormal(1_800, 1.0, 120, 6 * 3_600)
        stands_in = rng.random() < 0.03
        chat = (
            ("definition" if rng.random() < 0.15 else "project")
            if kind == "chat"
            else None
        )
        trigger = (
            rng.choice(("worker_turn_ended", "item_done", "wait_fired", "setup"))
            if kind == "job"
            else None
        )
        title = f"{rng.choice(ERRANDS)} {len(sessions) + 1}"
        in_store = kind != "work"
        session = Session(
            name=name,
            directory=STORE if in_store else place.directory,
            environment=STORE_ENVIRONMENT if in_store else environment("pilot", place),
            repository=None if in_store else place.repository,
            ran=Ran(
                project=place.slug,
                turns=tuple(
                    Turn(title, started, ended, cause, author)
                    for cause, started, ended, author in runs
                ),
                kind=kind,
                title=title if kind in ("work", "job") else None,
                trigger=trigger,
                chat=chat,
            ),
            launches=tuple(launches),
            sub_agents=tuple(agents),
        )
        return session, stands_in

    def _by_hand(
        self,
        drawn: "_Drawn",
        name: str,
        place: Place,
        start: int,
        main_calls: int,
        model: str,
        agents: list[SubAgent],
    ) -> Session:
        """A conversation a person ran by hand."""
        rng = drawn.rng
        person = "ada" if rng.random() < 0.6 else "ben"
        launch_count = rng.choices((1, 2, 3), (85, 10, 5))[0]
        spans = _spans(rng, main_calls, launch_count)
        launches = []
        at = start
        for span in spans:
            cuts = _prompt_cuts(rng, span, 2, 12)
            parts, ended = drawn.thread(
                at + 4, span, place, model, "5m", cuts, agents, None, rewinds=True
            )
            prompts = []
            for steps in parts:
                first = next(s.at for s in steps)
                prompts.append(
                    Prompt(
                        at=drawn.moments.at(first - 3),
                        source="typed",
                        characters=rng.randint(20, 1_200),
                        steps=tuple(steps),
                        hooks=(
                            (
                                HookRun(
                                    "lint.sh",
                                    rng.randint(200, 3_000),
                                    rng.random() < 0.05,
                                ),
                            )
                            if rng.random() < 0.2
                            else ()
                        ),
                    )
                )
            launches.append(
                Launch(
                    versions=((("claude-code", drawn.version)),),
                    prompts=tuple(prompts),
                )
            )
            at = ended + drawn.lognormal(3_600, 1.0, 300, 8 * 3_600)
        return Session(
            name=name,
            directory=place.directory,
            environment=environment(person, place),
            repository=place.repository,
            person=person,
            group=place.group
            if place.group is not None and rng.random() < 0.05
            else None,
            launches=tuple(launches),
            sub_agents=tuple(agents),
        )


def environment(person: str, place: Place) -> str:
    """The environment `person` works on `place` in, Pilot's by `pilot`."""
    digest = hashlib.sha256(f"{person}/{place.slug}".encode()).hexdigest()[:6]
    return f"{person}-{place.repository.lower()}-{digest}"


def models(day: date) -> tuple[str, str, str]:
    """The models of `day`, the largest, the middle and the smallest."""
    return next(models for before, models in _MODELS if day < before)


def _version(day: date) -> str:
    """Claude Code's version on a day: a release every three days."""
    return f"2.1.{(day - date(2025, 1, 1)).days // 3}"


@dataclass
class _Moments:
    """The last moment anything of a day was written at."""

    last: int = 0

    def at(self, moment: int) -> int:
        self.last = max(self.last, moment)
        return moment


class _Drawn:
    """A day's conversations, drawn one at a time from the day's seed."""

    def __init__(self, day: date, seed: int) -> None:
        self.day = day
        self.rng = random.Random(f"{seed}/{day.isoformat()}")
        self.moments = _Moments()
        self.models = models(day)
        self.version = _version(day)

    def lognormal(self, median: float, sigma: float, low: int, high: int) -> int:
        return max(low, min(high, round(median * math.exp(self.rng.gauss(0, sigma)))))

    def hour(self, pilots: bool) -> int:
        """A conversation's start, in seconds from the day's local midnight."""
        weights = [1] * 7 + [4, 8, 10, 10, 8, 6, 8, 10, 10, 8, 5, 4, 6, 7, 6, 4, 2]
        if pilots:
            weights = [w + 2 for w in weights]
        hour = self.rng.choices(range(24), weights)[0]
        return hour * 3_600 + self.rng.randrange(3_600)

    def tools(self, at: int, place: Place) -> tuple[ToolUse, ...]:
        count = self.rng.choices((0, 1, 2, 3), (25, 55, 15, 5))[0]
        uses = []
        for _ in range(count):
            tool = self.rng.choices([t for t, _ in _TOOLS], [w for _, w in _TOOLS])[0]
            word = self.rng.choice(place.words)
            failed = self.rng.random() < 0.04
            saved = (
                self.lognormal(60_000, 0.6, 30_001, 400_000)
                if self.rng.random() < 0.005
                else None
            )
            # A saved output's result holds Claude Code's words around its
            # preview, a thousand characters and more.
            low = 1_000 if saved is not None else 20
            uses.append(
                ToolUse(
                    tool,
                    f"python {word}.py" if tool == "Bash" else f"{word}/{word}.md",
                    took=self.lognormal(2, 1.0, 1, 600) if tool == "Bash" else 1,
                    characters=self.lognormal(1_200, 1.1, low, 60_000),
                    server="pantry" if tool.startswith("mcp__") else None,
                    failed=failed,
                    exit_code=1 if failed and tool == "Bash" else None,
                    saved=saved,
                )
            )
        return tuple(uses)

    def thread(
        self,
        at: int,
        calls: int,
        place: Place,
        model: str,
        ttl: str,
        prompts: Sequence[int],
        agents: list[SubAgent] | None,
        effort: str | None,
        rewinds: bool = False,
        skilled: bool = False,
    ) -> tuple[list[list[Call | Compaction]], int]:
        """A thread's steps from `at`, cut into prompts after the Calls
        `prompts` counts, each prompt's steps after a person's pause where
        there is more than one; and its last moment. A Call of the main
        thread, where `agents` is given, may start a sub-agent, which then
        runs until its result. With `rewinds`, a prompt may take the one
        before it back, its first Call going on from the first of that."""
        rng = self.rng
        cuts = set(prompts)
        context = rng.randint(18_000, 60_000)
        parts: list[list[Call | Compaction]] = [[]]
        previous: int | None = None
        crossed = False
        first = True
        key = "cache_write_5m" if ttl == "5m" else "cache_write_1h"
        for n in range(calls):
            back_to: str | None = None
            if n in cuts and parts[-1]:
                parts.append([])
                at += self.lognormal(90, 1.3, 5, 4 * 3_600)
                if rewinds and len(parts) > 2 and rng.random() < 0.05:
                    back_to = f"p{len(parts) - 2}"
            at += self.lognormal(8, 0.8, 1, 900)
            if rng.random() < 0.02:
                at += rng.randint(300, 3_600)
            new = self.lognormal(1_500, 1.0, 10, 40_000)
            miss: str | None = None
            if crossed:
                miss = "compaction"
            elif back_to is not None:
                miss = "rewind"
            elif previous is not None and at - previous > _TTL[ttl]:
                miss = "ttl"
            lost = miss is not None or (previous is not None and rng.random() < 0.01)
            if previous is None or lost:
                tokens = Tokens(
                    input=rng.randint(3, 40), output=0, **{key: context + new}
                )
            else:
                tokens = Tokens(
                    input=rng.randint(3, 40), cache_read=context, output=0, **{key: new}
                )
            output = self.lognormal(260, 0.9, 12, 16_000)
            tokens = replace(tokens, output=output)
            context += new + output
            uses = self.tools(at, place)
            if (
                agents is not None
                and n < calls - 1
                and rng.random() < 0.02
                and len(agents) < 4
            ):
                name = f"a{len(agents)}"
                steps, ended = self.agent(at + 1, place)
                agents.append(
                    SubAgent(
                        name, rng.choice(("Explore", "general-purpose")), tuple(steps)
                    )
                )
                word = rng.choice(place.words)
                uses = (
                    *uses,
                    ToolUse(
                        "Agent",
                        _TASK.format(word=word),
                        took=ended - at,
                        characters=self.lognormal(1_800, 0.7, 100, 20_000),
                        spawns=name,
                    ),
                )
            if skilled and n == 0:
                uses = (*uses, ToolUse("Skill", _SKILL, took=1, characters=31))
            occurred: tuple[Occurrence, ...] = ()
            if rng.random() < 0.003:
                occurred = (
                    Occurrence(
                        at=self.moments.at(at + rng.randint(1, 9)),
                        kind="api_error",
                        detail=rng.choice(("529", "500", "429")),
                    ),
                )
            carried: tuple[Carried, ...] = ()
            if first:
                carried = (
                    Carried("system_prompt", rng.randint(8_000, 10_000)),
                    Carried("tool_schemas", rng.randint(30_000, 50_000)),
                    Carried("instruction_file", rng.randint(2_000, 9_000), MANAGED),
                )
                first = False
            elif crossed:
                carried = (Carried("compact_summary", context),)
            if skilled and n == 1:
                carried = (*carried, Carried("skill_body", 4_300, _SKILL))
            parts[-1].append(
                Call(
                    at=self.moments.at(at),
                    skill=_SKILL if skilled and n == 1 else None,
                    plugin="pantry" if skilled and n == 1 else None,
                    sent=self.moments.at(at - 1) if carried else None,
                    name=f"p{len(parts)}" if rewinds and not parts[-1] else None,
                    back_to=back_to,
                    model=model,
                    effort=effort,
                    thinking=self.lognormal(200, 1.0, 1, 8_000)
                    if rng.random() < 0.3
                    else None,
                    miss=miss,
                    tokens=tokens,
                    tools=uses,
                    occurred=occurred,
                    carried=carried,
                )
            )
            previous = at
            crossed = False
            took = max((use.took or 0 for use in uses), default=0)
            self.moments.at(at + took)
            at += took
            if context > 160_000 and n < calls - 1:
                after = rng.randint(15_000, 30_000)
                took_ms = rng.randint(20_000, 60_000)
                at += 1
                parts[-1].append(
                    Compaction(
                        at=self.moments.at(at),
                        trigger="auto",
                        before=context,
                        after=after,
                        took_ms=took_ms,
                    )
                )
                at += took_ms // 1_000
                context = after
                crossed = True
        return parts, self.moments.at(at)

    def agent(self, at: int, place: Place) -> tuple[list[Call | Compaction], int]:
        small = self.models[2] if self.rng.random() < 0.6 else self.models[1]
        calls = self.lognormal(8, 0.8, 1, 200)
        parts, ended = self.thread(at, calls, place, small, "5m", (), None, None)
        return parts[0], ended


def _prompt_cuts(rng: random.Random, calls: int, low: int, high: int) -> list[int]:
    cuts = []
    n = rng.randint(low, high)
    while n < calls:
        cuts.append(n)
        n += rng.randint(low, high)
    return cuts


def _add(one: Tokens, other: Tokens) -> Tokens:
    return Tokens(
        input=one.input + other.input,
        cache_write_5m=one.cache_write_5m + other.cache_write_5m,
        cache_write_1h=one.cache_write_1h + other.cache_write_1h,
        cache_read=one.cache_read + other.cache_read,
        output=one.output + other.output,
    )


def _versions(drawn: _Drawn, skilled: bool) -> tuple[tuple[str, str], ...]:
    versions: tuple[tuple[str, str], ...] = (("claude-code", drawn.version),)
    if skilled:
        versions += (("plugin:pantry", f"0.3.{drawn.day.month}"),)
    return versions


def _spans(rng: random.Random, calls: int, parts: int) -> list[int]:
    """`calls` cut into `parts` spans of one Call or more."""
    parts = max(1, min(parts, calls))
    cuts = sorted(rng.sample(range(1, calls), parts - 1)) if parts > 1 else []
    edges = [0, *cuts, calls]
    return [b - a for a, b in zip(edges, edges[1:], strict=False)]


def _steps(session: Session) -> list[Sequence[Call | Compaction]]:
    return [
        *(p.steps for launch in session.launches for p in launch.prompts),
        *(agent.steps for agent in session.sub_agents),
    ]


def _calls(session: Session) -> int:
    return sum(isinstance(step, Call) for steps in _steps(session) for step in steps)


def billed(session: Session) -> Tokens:
    """The tokens the session's Calls were billed, its sub-agents' among
    them."""
    tokens = Tokens()
    for steps in _steps(session):
        for step in steps:
            if isinstance(step, Call):
                tokens = _add(tokens, step.tokens)
    return tokens
