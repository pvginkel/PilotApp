"""The timing's history (F154.9): Pilot's record at a size of Calls, in the
scenario's invented words, drawn from a fixed seed.

    DATABASE_URL=… uv run python -m tools.timing.history --calls 630000

A day of the history is a scenario of the scenario's own script
(`pilot_scenario.script`), its conversations drawn from the day's seed,
`SEED` and the day, so that a day is the same in every history that holds
it, and a larger history is a smaller one with earlier days before it. The
scenario's builder turns the day into publications, which the app's own
publication writes (`PublicationService.publish`), as a collector's are, so
that a Call's cost, its caches and its Launch's placement are the
publication's. What Pilot holds of its own conversations is written before
them, as the scenario's load writes it (`ScenarioService`): a Session of each
of Pilot's, with its Turns, and its work item or its chat; a few are never
collected, their Turns standing in with their own cost and tokens.

Its shape is the fleet's as `architecture.md` *The sizes* has it: some nine
thousand Calls a day (`CALLS_A_DAY`), fewer at the weekend, about thirty a
transcript, a third of the conversations with sub-agents. A day already
written, its first conversation published, is skipped, so a history is
grown by running the command again with more Calls. A day is one
transaction, tried again where another worker wrote a vocabulary's row or
adopted a group first. A conversation that names a group takes the group's
adoption lock until the day's transaction ends, so a day publishes those
last, in the order of their groups' keys (`in_lock_order`): two days written
at once take the locks in one order, and hold them only for the day's last
publications. The days are written by `--workers` processes, and the record
is vacuumed and analysed at the end, as autovacuum would leave it.
"""

import argparse
import hashlib
import math
import multiprocessing
import random
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pilot_collection.publication import PublicationSchema
from pilot_scenario import Builder
from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    Group,
    HookRun,
    Launch,
    Occurrence,
    Prompt,
    Scenario,
    Session,
    SubAgent,
    Tokens,
    ToolUse,
    Turn,
)
from psycopg.errors import DeadlockDetected, UniqueViolation
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Chat,
    Environment,
    Item,
    Project,
    TokenCount,
    Transcript,
    User,
    Work,
)
from app.models import (
    Launch as LaunchRow,
)
from app.models import Session as AgentSession
from app.models import (
    Turn as TurnRow,
)
from app.models.call import Call as CallRow
from app.models.reference import (
    ChatKind,
    CloseCause,
    ProjectState,
    SessionState,
    TurnCause,
    UserKind,
    WorkTrigger,
)

SEED = 53
"""The history's seed: a day's conversations are drawn from it and the day."""

CALLS_A_DAY = 9_000
"""A weekday's Calls on average; a day at the weekend has `WEEKEND` of it."""

WEEKEND = 0.6

ZONE = ZoneInfo("Europe/Amsterdam")
"""The zone a day's hours are drawn in, the engine's default."""

ATTEMPTS = 5
"""How often a day's transaction is tried: another worker's may write a
vocabulary's row, an environment or an adopted group's project first, or
deadlock on one with it."""

LONG_CALLS = 1_200
"""The main thread's Calls of the long conversation every Wednesday has,
whose calls the timing reads."""


@dataclass(frozen=True)
class Place:
    """One of the history's projects, with the checkout its work runs in."""

    slug: str
    name: str
    repository: str
    weight: int
    words: tuple[str, ...]

    @property
    def directory(self) -> str:
        return f"/work/{self.repository}"


PLACES = (
    Place("recipe-box", "Recipe box", "RecipeBox", 30, ("stew", "dumplings", "spice")),
    Place("bike-log", "Bike log", "BikeLog", 20, ("gears", "chain", "rides")),
    Place("garden-plan", "Garden plan", "GardenPlan", 12, ("beds", "seeds", "frost")),
    Place("seed-swap", "Seed swap", "SeedSwap", 10, ("packets", "swaps", "beans")),
    Place("tide-table", "Tide table", "TideTable", 10, ("tides", "moon", "harbour")),
    Place("kite-shop", "Kite shop", "KiteShop", 8, ("kites", "spars", "lines")),
    Place("choir-rota", "Choir rota", "ChoirRota", 6, ("rota", "hymns", "altos")),
    Place("map-room", "Map room", "MapRoom", 4, ("maps", "trails", "legend")),
)

PEOPLE = (("ada", "Ada Example"), ("ben", "Ben Example"))

STORE = "/work/Larder"
"""Where Pilot's chats and jobs run: its store, by an invented name."""

STORE_ENVIRONMENT = "pilot-larder-4b7d21"

GROUPS = (
    Group(
        key="bike-log-first-rides",
        name="Bike log: the first rides",
        summary="The gear tables and ride notes Ada kept by hand.",
    ),
    Group(
        key="recipe-box-first-batches",
        name="Recipe box: the first batches",
        summary="The recipes Ben scaled by hand before the box held them.",
    ),
)

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


def _models(day: date) -> tuple[str, str, str]:
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


@dataclass
class _Run:
    """A Turn of Pilot's as the day plans it: its Launch's span."""

    cause: TurnCause
    started: int
    ended: int
    author: str | None = None


@dataclass
class _Pilots:
    """One of Pilot's conversations as the day plans it: its Session's kind,
    its project and its Turns; never collected where `standing_in`."""

    kind: str
    place: Place
    runs: list[_Run]
    standing_in: bool
    chat: ChatKind | None = None
    trigger: WorkTrigger | None = None
    title: str | None = None
    tokens: Tokens = field(default_factory=Tokens)


@dataclass
class Day:
    """A day of the history: its scenario, its Calls, and what Pilot holds
    of its own conversations, by the conversation's session's name."""

    day: date
    scenario: Scenario
    calls: int
    pilots: dict[str, _Pilots]
    start: datetime

    def until(self, moments: int) -> datetime:
        return self.start + timedelta(seconds=moments)


def target(day: date) -> int:
    """The Calls a day is drawn to hold, at least: its share of
    `CALLS_A_DAY`, give or take a quarter."""
    rng = random.Random(f"{SEED}/{day.isoformat()}/target")
    share = WEEKEND if day.weekday() >= 5 else (7 - 2 * WEEKEND) / 5
    return round(CALLS_A_DAY * share * rng.uniform(0.75, 1.25))


class _Drawn:
    """A day's conversations, drawn one at a time from the day's seed."""

    def __init__(self, day: date) -> None:
        self.day = day
        self.rng = random.Random(f"{SEED}/{day.isoformat()}")
        self.moments = _Moments()
        self.models = _models(day)
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
                    Carried("instruction_file", rng.randint(2_000, 9_000), "CLAUDE.md"),
                )
                first = False
            parts[-1].append(
                Call(
                    at=self.moments.at(at),
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
            if context > 160_000:
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


def _reported(tokens: Tokens) -> Decimal:
    """What a Turn's process reports it cost, at the largest model's rates."""
    usd = (
        tokens.input * 5
        + tokens.cache_write_5m * 6.25
        + tokens.cache_write_1h * 10
        + tokens.cache_read * 0.5
        + tokens.output * 25
    ) / 1_000_000
    return Decimal(f"{usd:.6f}")


def _add(one: Tokens, other: Tokens) -> Tokens:
    return Tokens(
        input=one.input + other.input,
        cache_write_5m=one.cache_write_5m + other.cache_write_5m,
        cache_write_1h=one.cache_write_1h + other.cache_write_1h,
        cache_read=one.cache_read + other.cache_read,
        output=one.output + other.output,
    )


def _environment(person: str, place: Place) -> str:
    digest = hashlib.sha256(f"{person}/{place.slug}".encode()).hexdigest()[:6]
    return f"{person}-{place.repository.lower()}-{digest}"


def draw(day: date, calls: int | None = None) -> Day:
    """A day of the history, drawn from its seed: its `target`'s Calls at
    least, or the `calls` given."""
    drawn = _Drawn(day)
    rng = drawn.rng
    goal = target(day) if calls is None else calls
    sessions: list[Session] = []
    pilots: dict[str, _Pilots] = {}
    calls = 0
    while calls < goal:
        name = f"s{len(sessions):04}"
        place = rng.choices(PLACES, [p.weight for p in PLACES])[0]
        long = day.weekday() == 2 and not sessions
        pilot = not long and rng.random() < 0.45
        main_calls = LONG_CALLS if long else drawn.lognormal(26, 0.9, 1, 1_500)
        agents: list[SubAgent] = []
        start = drawn.hour(pilot)
        large, middle, _ = drawn.models
        model = large if rng.random() < 0.8 else middle
        if pilot:
            kind = rng.choices(
                ("work", "job", "chat", "conversation"), (55, 20, 20, 5)
            )[0]
            turns = rng.choices((1, 2, 3), (70, 20, 10))[0] if kind != "job" else 1
            spans = _spans(rng, main_calls, turns)
            launches = []
            runs = []
            at = start
            for n, span in enumerate(spans):
                cuts = _prompt_cuts(rng, span, 15, 60) if rng.random() < 0.1 else []
                parts, ended = drawn.thread(
                    at + 4, span, place, model, "1h", cuts, agents, "high"
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
                    Launch(versions=_versions(drawn, kind), prompts=tuple(prompts))
                )
                cause = (
                    TurnCause.PERSON
                    if kind in ("chat", "conversation")
                    else TurnCause.BRIEF
                    if n == 0
                    else rng.choice(
                        (TurnCause.CONTINUATION, TurnCause.RESUME, TurnCause.NUDGE)
                    )
                )
                author = rng.choice(PEOPLE)[0] if cause is TurnCause.PERSON else None
                runs.append(_Run(cause, at, drawn.moments.at(ended + 1), author))
                at = ended + drawn.lognormal(1_800, 1.0, 120, 6 * 3_600)
            plan = _Pilots(
                kind=kind,
                place=place,
                runs=runs,
                standing_in=rng.random() < 0.03,
                chat=(
                    (ChatKind.DEFINITION if rng.random() < 0.15 else ChatKind.PROJECT)
                    if kind == "chat"
                    else None
                ),
                trigger=(
                    rng.choice(
                        (
                            WorkTrigger.WORKER_TURN_ENDED,
                            WorkTrigger.ITEM_DONE,
                            WorkTrigger.WAIT_FIRED,
                            WorkTrigger.SETUP,
                        )
                    )
                    if kind == "job"
                    else None
                ),
                title=f"{rng.choice(ERRANDS)} {len(sessions) + 1}",
            )
            in_store = kind != "work"
            session = Session(
                name=name,
                directory=STORE if in_store else place.directory,
                environment=STORE_ENVIRONMENT
                if in_store
                else _environment("pilot", place),
                repository=None if in_store else place.repository,
                turn=Turn(
                    place.slug, plan.title or "", runs[0].started, runs[-1].ended
                ),
                launches=tuple(launches),
                sub_agents=tuple(agents),
            )
            if plan.standing_in:
                plan.tokens = _tokens(session)
            pilots[name] = plan
        else:
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
            session = Session(
                name=name,
                directory=place.directory,
                environment=_environment(person, place),
                repository=place.repository,
                person=person,
                group=GROUPS[0 if place.slug == "bike-log" else 1]
                if place.slug in ("bike-log", "recipe-box") and rng.random() < 0.05
                else None,
                launches=tuple(launches),
                sub_agents=tuple(agents),
            )
        sessions.append(session)
        calls += main_calls + sum(
            1 for agent in agents for step in agent.steps if isinstance(step, Call)
        )
    scenario = Scenario(
        name=f"timing/{day.isoformat()}",
        people=tuple(p for p, _ in PEOPLE),
        projects=tuple(p.slug for p in PLACES),
        kinds=("errand",),
        units=(),
        sessions=tuple(sessions),
    )
    midnight = datetime.combine(day, datetime.min.time(), ZONE).astimezone(UTC)
    return Day(day, scenario, calls, pilots, midnight)


def _versions(drawn: _Drawn, kind: str) -> tuple[tuple[str, str], ...]:
    versions: tuple[tuple[str, str], ...] = (("claude-code", drawn.version),)
    if kind == "work":
        versions += (("plugin:pantry", f"0.3.{drawn.day.month}"),)
    return versions


def _spans(rng: random.Random, calls: int, parts: int) -> list[int]:
    """`calls` cut into `parts` spans of one Call or more."""
    parts = max(1, min(parts, calls))
    cuts = sorted(rng.sample(range(1, calls), parts - 1)) if parts > 1 else []
    edges = [0, *cuts, calls]
    return [b - a for a, b in zip(edges, edges[1:], strict=False)]


def _tokens(session: Session) -> Tokens:
    tokens = Tokens()
    for steps in (
        *(p.steps for launch in session.launches for p in launch.prompts),
        *(agent.steps for agent in session.sub_agents),
    ):
        for step in steps:
            if isinstance(step, Call):
                tokens = _add(tokens, step.tokens)
    return tokens


class _Writer:
    """Writes a day into the record through the app's publication, on `db`,
    in the app's container."""

    def __init__(self, container: object, db: DbSession) -> None:
        self.container = container
        self.db = db
        self.people = self._people()
        self.projects = self._projects()

    def _people(self) -> dict[str, uuid.UUID]:
        users: dict[str, uuid.UUID] = {}
        for slot, (handle, name) in enumerate((*PEOPLE, ("fleet", "KubeCoder fleet"))):
            service = handle == "fleet"
            self.db.execute(
                pg_insert(User)
                .values(
                    kind_code=UserKind.SERVICE if service else UserKind.PERSON,
                    handle=handle,
                    name=name,
                    subject=f"example-{handle}",
                    avatar_slot=None if service else slot + 1,
                )
                .on_conflict_do_nothing(index_elements=["handle"])
            )
            users[handle] = self.db.scalars(
                select(User.id).where(User.handle == handle)
            ).one()
        return users

    def _projects(self) -> dict[str, uuid.UUID]:
        projects: dict[str, uuid.UUID] = {}
        for place in PLACES:
            found = self.db.scalars(
                select(Project.id).where(Project.slug == place.slug)
            ).first()
            if found is None:
                project = Project(
                    slug=place.slug,
                    name=place.name,
                    state_code=ProjectState.OPEN,
                    repo=place.repository,
                    created_by_user_id=self.people["ada"],
                    created_at=datetime(2025, 1, 2, 9, tzinfo=UTC),
                )
                self.db.add(project)
                self.db.flush()
                found = project.id
            projects[place.slug] = found
        self.db.commit()
        return projects

    def written(self, day: Day) -> bool:
        """Whether the day's first conversation that is collected is
        published."""
        builder = Builder(day.scenario, day.start)
        first = builder.conversation(
            next(
                session
                for session in day.scenario.sessions
                if session.name not in day.pilots
                or not day.pilots[session.name].standing_in
            )
        )
        held = select(Transcript.id).where(Transcript.session_id == first).limit(1)
        return self.db.execute(held).first() is not None

    def write(self, day: Day) -> None:
        moments = max(
            moment
            for session in day.scenario.sessions
            for moment in _all_moments(session)
        )
        builder = Builder(day.scenario, day.until(moments))
        assert builder.when(0) == day.start
        sessions: list[uuid.UUID] = []
        standing: set[str] = set()
        for session in day.scenario.sessions:
            plan = day.pilots.get(session.name)
            if plan is None:
                continue
            sessions.append(self._pilots(builder, day, session, plan))
            if plan.standing_in:
                standing.add(builder.conversation(session))
        publication = self.container.publication_service()  # type: ignore[attr-defined]
        for published in in_lock_order(builder.publications()):
            if published["session_id"] in standing:
                continue
            publication.publish(PublicationSchema.model_validate(published))
        self._reported(sessions)
        self.db.commit()

    def _pilots(
        self, builder: Builder, day: Day, session: Session, plan: _Pilots
    ) -> uuid.UUID:
        conversation = builder.conversation(session)
        if session.environment is not None:
            self.db.execute(
                pg_insert(Environment)
                .values(id=session.environment, name=session.environment, exempt=False)
                .on_conflict_do_nothing(index_elements=["id"])
            )
        project = self.projects[plan.place.slug]
        started = builder.when(plan.runs[0].started)
        ended = builder.when(plan.runs[-1].ended)
        row = AgentSession(
            project_id=project,
            environment_id=session.environment,
            kind_code=plan.kind,
            cwd=session.directory,
            conversation_id=conversation,
            token_hash=hashlib.sha256(conversation.encode()).hexdigest(),
            state_code=SessionState.ENDED,
            turns=len(plan.runs),
            created_at=started - timedelta(seconds=5),
            started_at=started,
            turn_started_at=builder.when(plan.runs[-1].started),
            turn_ended_at=ended,
            ended_at=ended,
        )
        self.db.add(row)
        self.db.flush()
        if plan.kind in ("work", "job"):
            seq = (day.day - date(2025, 1, 1)).days * 1_000 + int(session.name[1:]) + 1
            self.db.add(
                Item(
                    id=row.id,
                    project_id=project,
                    seq=seq,
                    kind_code="work",
                    title=plan.title,
                    created_at=started - timedelta(seconds=5),
                    created_by_session_id=row.id,
                    done_at=ended,
                    done_cause_code="finished",
                )
            )
            self.db.flush()
            self.db.add(
                Work(
                    id=row.id,
                    project_id=project,
                    session_kind_code=plan.kind,
                    trigger_code=plan.trigger,
                    repo=session.repository,
                    autopilot=False,
                )
            )
        elif plan.kind == "chat":
            self.db.add(
                Chat(
                    id=row.id,
                    project_id=project,
                    session_kind_code="chat",
                    kind_code=plan.chat,
                    closed_at=ended,
                    close_cause_code=CloseCause.FINISHED,
                )
            )
        for seq, run in enumerate(plan.runs, start=1):
            author = None if run.author is None else self.people[run.author]
            turn = TurnRow(
                session_id=row.id,
                seq=seq,
                message=plan.title or "",
                author_user_id=author,
                words=None if author is None else plan.title,
                started_at=builder.when(run.started),
                ended_at=builder.when(run.ended),
                cause_code=run.cause,
            )
            self.db.add(turn)
            if plan.standing_in:
                self.db.flush()
                share = Tokens(
                    input=plan.tokens.input // len(plan.runs),
                    cache_write_1h=plan.tokens.cache_write_1h // len(plan.runs),
                    cache_read=plan.tokens.cache_read // len(plan.runs),
                    output=plan.tokens.output // len(plan.runs),
                )
                turn.cost = _reported(share)
                for kind, tokens in (
                    ("input", share.input),
                    ("cache_write", share.cache_write_1h),
                    ("cache_read", share.cache_read),
                    ("output", share.output),
                ):
                    self.db.add(
                        TokenCount(turn_id=turn.id, token_kind_code=kind, tokens=tokens)
                    )
        self.db.flush()
        return row.id

    def _reported(self, sessions: list[uuid.UUID]) -> None:
        """Each collected Turn's own reported cost: its Calls' computed one,
        short by what a killed process would not report."""
        if not sessions:
            return
        spent = (
            select(
                LaunchRow.session_id,
                LaunchRow.turn_seq,
                (func.sum(CallRow.cost) * 0.98).label("cost"),
            )
            .join(CallRow, CallRow.launch_id == LaunchRow.id)
            .where(LaunchRow.session_id.in_(sessions))
            .group_by(LaunchRow.session_id, LaunchRow.turn_seq)
            .subquery()
        )
        self.db.execute(
            update(TurnRow)
            .where(
                TurnRow.session_id == spent.c.session_id,
                TurnRow.seq == spent.c.turn_seq,
            )
            .values(cost=spent.c.cost)
        )


def in_lock_order(publications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`publications` with each conversation's threads together, the
    conversations that name a group last, by the group's key, the others in
    their order."""
    conversations: dict[str, list[dict[str, Any]]] = {}
    for published in publications:
        conversations.setdefault(published["session_id"], []).append(published)

    def group(threads: list[dict[str, Any]]) -> tuple[bool, str]:
        named = threads[0].get("group")
        return named is not None, "" if named is None else named["key"]

    return [
        published
        for threads in sorted(conversations.values(), key=group)
        for published in threads
    ]


def _all_moments(session: Session) -> Iterator[int]:
    if session.turn is not None:
        yield session.turn.at
        yield session.turn.ended
    for launch in session.launches:
        for prompt in launch.prompts:
            yield prompt.at
            yield from _step_moments(prompt.steps)
    for agent in session.sub_agents:
        yield from _step_moments(agent.steps)


def _step_moments(steps: Sequence[Call | Compaction]) -> Iterator[int]:
    for step in steps:
        yield step.at
        if isinstance(step, Call):
            yield from (
                step.at + use.took for use in step.tools if use.took is not None
            )
            yield from (occurrence.at for occurrence in step.occurred)


def days(calls: int, last: date) -> list[date]:
    """The days a history of `calls` Calls holds, ending on `last`: back
    from it until their targets reach `calls`."""
    held: list[date] = []
    total = 0
    day = last
    while total < calls:
        held.append(day)
        total += target(day)
        day -= timedelta(days=1)
    return held


def _work(days_to_write: list[date], worker: int) -> None:
    from app import create_app

    app = create_app(skip_background_services=True)
    with app.app_context():
        container = app.container
        db = container.db_session()
        writer = _Writer(container, db)
        for day in days_to_write:
            drawn = draw(day)
            if writer.written(drawn):
                print(f"{day}: written already", flush=True)
                continue
            began = time.perf_counter()
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    writer.write(drawn)
                    break
                except (IntegrityError, OperationalError) as error:
                    db.rollback()
                    raced = isinstance(error.orig, UniqueViolation | DeadlockDetected)
                    if not raced or attempt == ATTEMPTS:
                        raise
            print(
                f"{day}: {drawn.calls} calls, {len(drawn.scenario.sessions)} "
                f"conversations, {time.perf_counter() - began:.1f} s (worker {worker})",
                flush=True,
            )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--calls", type=int, required=True)
    parser.add_argument(
        "--last",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() - timedelta(days=1),
        help="the history's last day, yesterday by default",
    )
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    held = days(args.calls, args.last)
    print(f"{len(held)} days, {held[-1]} to {held[0]}", flush=True)
    shares = [held[n :: args.workers] for n in range(args.workers)]
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        pool.starmap(_work, [(share, n) for n, share in enumerate(shares)])
    from app import create_app

    app = create_app(skip_background_services=True)
    with app.app_context():
        engine = app.container.db_session().get_bind()
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text("VACUUM (ANALYZE)"))
    print("vacuumed and analysed", flush=True)


if __name__ == "__main__":
    main()
