"""The timing's history (F154.9): Pilot's record at a size of Calls, in the
scenario's invented words, drawn from a fixed seed.

    DATABASE_URL=… uv run python -m tools.timing.history --calls 630000

A day of the history is the scenario package's (`pilot_scenario.history`),
drawn from `SEED` and the day at the fleet's size, some nine thousand Calls
a weekday (`HISTORY`), each Wednesday opening on a long conversation by hand
whose calls the timing reads. The scenario's builder turns the day into
publications, labelled by the stub labeller, which the app's own
publication writes
(`PublicationService.publish`), as a collector's are, the stub's
vocabularies declared first, so that a Call's cost, its caches, its
Launch's placement and its labels are the publication's. What Pilot holds
of its own conversations is written before them, as the scenario's load
writes it (`ScenarioService`): a Session of each of Pilot's, with its
Turns, and its work item or its chat; those never collected stand in with
their Turns' own cost and tokens.

Each work session of Pilot's carries out a leg of its project's errand of
the day, in a stop of one of its trips, a porter's in the trip itself
(`KINDS`, `NESTING`), in one of the `ROLES`, its round the role's count in
the errand, a later round now and then work cooked again; a role's legs run
on the model its configuration gives for each four weeks (`configured`), so
that a role's configuration changes between its units (`draw`). They are
drawn from a seed of their own, so the rest of a day is the package's.

A day already written, its first conversation published, is skipped, so a
history is grown by running the command again with more Calls. A day is one
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
import multiprocessing
import random
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pilot_collection.publication import PublicationSchema
from pilot_collection.vocabularies import VocabulariesSchema
from pilot_scenario import Builder, labeller
from pilot_scenario.history import PEOPLE, Day, History, Place, models
from pilot_scenario.script import Call, Group, Launch, Session, Tokens, Unit
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
"""A weekday's Calls on average."""

ATTEMPTS = 5
"""How often a day's transaction is tried: another worker's may write a
vocabulary's row, an environment or an adopted group's project first, or
deadlock on one with it."""

LONG_CALLS = 1_200
"""The main thread's Calls of the long conversation every Wednesday has,
whose calls the timing reads."""

FIRST_RIDES = Group(
    key="bike-log-first-rides",
    name="Bike log: the first rides",
    summary="The gear tables and ride notes Ada kept by hand.",
)

FIRST_BATCHES = Group(
    key="recipe-box-first-batches",
    name="Recipe box: the first batches",
    summary="The recipes Ben scaled by hand before the box held them.",
)

PLACES = (
    Place(
        "recipe-box",
        "Recipe box",
        "RecipeBox",
        30,
        ("stew", "dumplings", "spice"),
        FIRST_BATCHES,
    ),
    Place(
        "bike-log", "Bike log", "BikeLog", 20, ("gears", "chain", "rides"), FIRST_RIDES
    ),
    Place("garden-plan", "Garden plan", "GardenPlan", 12, ("beds", "seeds", "frost")),
    Place("seed-swap", "Seed swap", "SeedSwap", 10, ("packets", "swaps", "beans")),
    Place("tide-table", "Tide table", "TideTable", 10, ("tides", "moon", "harbour")),
    Place("kite-shop", "Kite shop", "KiteShop", 8, ("kites", "spars", "lines")),
    Place("choir-rota", "Choir rota", "ChoirRota", 6, ("rota", "hymns", "altos")),
    Place("map-room", "Map room", "MapRoom", 4, ("maps", "trails", "legend")),
)

HISTORY = History(
    name="timing",
    seed=SEED,
    calls_a_day=CALLS_A_DAY,
    places=PLACES,
    long_calls=LONG_CALLS,
)


KINDS = ("errand", "trip", "stop", "leg", "tidy", "check")
"""The kinds of work, the widest first: a project's errand of the day, its
trips, a trip's stops, the legs Pilot's work sessions carry out, a trip's
tidying and the check of a stop or a trip."""

NESTING = (
    ("trip", "errand"),
    ("stop", "trip"),
    ("leg", "stop"),
    ("leg", "trip"),
    ("tidy", "trip"),
    ("check", "stop"),
    ("check", "trip"),
)
"""Each pairing of kinds, inner in outer: the `dev` labeller's seven of its
six kinds in the history's words (its `labeller.md`, `nesting`), the widest
three steps up from a leg in a stop."""

LEGS_A_STOP = 3
"""The legs of a stop, a trip's first stop filled first."""

STOPS_A_TRIP = 3
"""The stops of a trip, an errand's first trip filled first."""

ROLES = (("cook", 60), ("taster", 30), ("porter", 10))
"""The roles a leg is done in, by weight."""

PORTER = "porter"
"""The role whose legs sit in their trip, in no stop."""

_LARGEST = {"cook": 0.8, "taster": 0.5, "porter": 0.2}
"""How often a role's configuration is the day's largest model, else the
middle one."""

CONFIGURED_DAYS = 28
"""How long a role's configuration stands before it is drawn again."""

REWORK = 0.25
"""The share of a role's later rounds in an errand that are work cooked
again."""


def configured(role: str, day: date) -> str:
    """The model a role's legs run on that day: the day's largest or its
    middle one, drawn for each `CONFIGURED_DAYS` from the role and the
    stretch."""
    large, middle, _ = models(day)
    stretch = day.toordinal() // CONFIGURED_DAYS
    rng = random.Random(f"{SEED}/{role}/{stretch}")
    return large if rng.random() < _LARGEST[role] else middle


def errand(place: Place, day: date) -> str:
    """The name of a project's errand of a day, which its work sessions'
    legs are parts of."""
    return f"{place.name} errands of {day.isoformat()}"


def trip(place: Place, day: date, leg: int) -> str:
    """The name of the trip of a project's errand of a day that its `leg`th
    leg, counted from 0, is a part of."""
    return f"{errand(place, day)}, trip {leg // (LEGS_A_STOP * STOPS_A_TRIP) + 1}"


def stop(place: Place, day: date, leg: int) -> str:
    """The name of the stop of its trip that a project's `leg`th leg of a
    day, counted from 0, is a part of."""
    within = leg % (LEGS_A_STOP * STOPS_A_TRIP) // LEGS_A_STOP + 1
    return f"{trip(place, day, leg)}, stop {within}"


def draw(day: date, calls: int | None = None) -> Day:
    """A day of the history, `HISTORY`'s, its work sessions each carrying
    out a leg: its role drawn from the day's seed of units, its main
    thread's Calls run on the role's configuration."""
    drawn = HISTORY.draw(day, calls)
    rng = random.Random(f"{SEED}/{day.isoformat()}/units")
    places = {place.slug: place for place in PLACES}
    legs: dict[str, list[Unit]] = {}
    sessions: list[Session] = []
    for session in drawn.scenario.sessions:
        ran = session.ran
        if ran is None or ran.kind != "work":
            sessions.append(session)
            continue
        assert ran.title is not None
        role = rng.choices([r for r, _ in ROLES], [w for _, w in ROLES])[0]
        place = places[ran.project]
        done = legs.setdefault(place.slug, [])
        round_ = 1 + sum(unit.role == role for unit in done)
        done.append(
            Unit(
                "leg",
                ran.title,
                within=(trip if role == PORTER else stop)(place, day, len(done)),
                role=role,
                round=round_,
                rework_kind=labeller.RECOOKED
                if round_ > 1 and rng.random() < REWORK
                else None,
            )
        )
        sessions.append(
            replace(
                session,
                unit=ran.title,
                launches=_run_on(session.launches, configured(role, day)),
            )
        )
    scenario = replace(
        drawn.scenario,
        kinds=KINDS,
        units=tuple(
            unit
            for place in PLACES
            if place.slug in legs
            for unit in _units(place, day, legs[place.slug])
        ),
        sessions=tuple(sessions),
        nesting=NESTING,
    )
    return replace(drawn, scenario=scenario)


def _run_on(launches: Sequence[Launch], model: str) -> tuple[Launch, ...]:
    """`launches` with every Call of theirs on `model`."""
    return tuple(
        replace(
            launch,
            prompts=tuple(
                replace(
                    prompt,
                    steps=tuple(
                        replace(step, model=model) if isinstance(step, Call) else step
                        for step in prompt.steps
                    ),
                )
                for prompt in launch.prompts
            ),
        )
        for launch in launches
    )


def _units(place: Place, day: date, legs: Sequence[Unit]) -> Iterator[Unit]:
    """A project's units of a day, each after the one it is a part of: its
    errand, its legs, and the trips and stops they sit in."""
    yield Unit("errand", errand(place, day), project=place.slug)
    seen: set[str] = set()
    for n, leg in enumerate(legs):
        placed = [("trip", trip(place, day, n), errand(place, day))]
        if leg.role != PORTER:
            placed.append(("stop", stop(place, day, n), trip(place, day, n)))
        for kind, name, within in placed:
            if name not in seen:
                seen.add(name)
                yield Unit(kind, name, within=within)
        yield leg


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
        first = day.builder().conversation(
            next(
                session
                for session in day.scenario.sessions
                if session.name not in day.standing
            )
        )
        held = select(Transcript.id).where(Transcript.session_id == first).limit(1)
        return self.db.execute(held).first() is not None

    def write(self, day: Day) -> None:
        builder = day.builder()
        sessions: list[uuid.UUID] = []
        standing: set[str] = set()
        for session in day.scenario.sessions:
            if session.ran is None:
                continue
            sessions.append(self._pilots(builder, day, session))
            if session.name in day.standing:
                standing.add(builder.conversation(session))
        self.container.vocabulary_service().declare(  # type: ignore[attr-defined]
            VocabulariesSchema.model_validate(builder.vocabularies())
        )
        publication = self.container.publication_service()  # type: ignore[attr-defined]
        for published in in_lock_order(builder.publications()):
            if published["session_id"] in standing:
                continue
            publication.publish(PublicationSchema.model_validate(published))
        self._reported(sessions)
        self.db.commit()

    def _pilots(self, builder: Builder, day: Day, session: Session) -> uuid.UUID:
        ran = session.ran
        assert ran is not None
        conversation = builder.conversation(session)
        if session.environment is not None:
            self.db.execute(
                pg_insert(Environment)
                .values(id=session.environment, name=session.environment, exempt=False)
                .on_conflict_do_nothing(index_elements=["id"])
            )
        project = self.projects[ran.project]
        started = builder.when(ran.turns[0].at)
        ended = builder.when(ran.turns[-1].ended)
        row = AgentSession(
            project_id=project,
            environment_id=session.environment,
            kind_code=ran.kind,
            cwd=session.directory,
            conversation_id=conversation,
            token_hash=hashlib.sha256(conversation.encode()).hexdigest(),
            state_code=SessionState.ENDED,
            turns=len(ran.turns),
            created_at=started - timedelta(seconds=5),
            started_at=started,
            turn_started_at=builder.when(ran.turns[-1].at),
            turn_ended_at=ended,
            ended_at=ended,
        )
        self.db.add(row)
        self.db.flush()
        if ran.title is not None:
            seq = (day.day - date(2025, 1, 1)).days * 1_000 + int(session.name[1:]) + 1
            self.db.add(
                Item(
                    id=row.id,
                    project_id=project,
                    seq=seq,
                    kind_code="work",
                    title=ran.title,
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
                    session_kind_code=ran.kind,
                    trigger_code=None
                    if ran.trigger is None
                    else WorkTrigger(ran.trigger),
                    repo=session.repository,
                    autopilot=False,
                )
            )
        elif ran.chat is not None:
            self.db.add(
                Chat(
                    id=row.id,
                    project_id=project,
                    session_kind_code="chat",
                    kind_code=ChatKind(ran.chat),
                    closed_at=ended,
                    close_cause_code=CloseCause.FINISHED,
                )
            )
        tokens = day.standing.get(session.name)
        for seq, sent in enumerate(ran.turns, start=1):
            author = None if sent.author is None else self.people[sent.author]
            turn = TurnRow(
                session_id=row.id,
                seq=seq,
                message=sent.message,
                author_user_id=author,
                words=None if author is None else sent.message,
                started_at=builder.when(sent.at),
                ended_at=builder.when(sent.ended),
                cause_code=TurnCause(sent.cause),
            )
            self.db.add(turn)
            if tokens is not None:
                self.db.flush()
                share = Tokens(
                    input=tokens.input // len(ran.turns),
                    cache_write_1h=tokens.cache_write_1h // len(ran.turns),
                    cache_read=tokens.cache_read // len(ran.turns),
                    output=tokens.output // len(ran.turns),
                )
                turn.cost = _reported(share)
                for kind, count in (
                    ("input", share.input),
                    ("cache_write", share.cache_write_1h),
                    ("cache_read", share.cache_read),
                    ("output", share.output),
                ):
                    self.db.add(
                        TokenCount(turn_id=turn.id, token_kind_code=kind, tokens=count)
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
    held = HISTORY.days(args.calls, args.last)
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
