"""An invented record for the tests of the dashboard's catalogue, and a read
of it through the catalogue's paths.

`record` writes: a work item's Session with one Turn, whose thread is
collected with three Calls under its Launch, a compaction before the third;
a chat's Session with one Turn and no thread, which stands in; and a thread
no Session ran, with one Call.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.assembly import assemble
from app.dashboard.catalogue import Catalogue, Path
from app.models import (
    Call,
    Chat,
    Event,
    EventKind,
    HookRun,
    LaunchComponent,
    MissCause,
    Project,
    Repository,
    StopReason,
    TokenCount,
    Transcript,
    Turn,
    User,
)
from app.models.reference import ChatKind, SessionState, TurnCause
from tests.support import transcripts
from tests.support.transcripts import CAMP, OTHER, SONNET, STARTED, SUB_AGENT

ZONE = "Europe/Amsterdam"
GAP = timedelta(hours=4)


@dataclass
class Record:
    project: Project
    work: models.Session
    work_turn: Turn
    chat: models.Session
    chat_turn: Turn
    thread: Transcript
    sub_agent: Transcript
    loose: Transcript
    calls: list[Call]


def record(
    db: DbSession,
    person: User,
    project: Project,
    work: models.Session,
) -> Record:
    project.name = "Recipe box"
    work.conversation_id = CAMP
    work_turn = Turn(
        session_id=work.id,
        seq=1,
        message="Scale the recipe.",
        started_at=STARTED - timedelta(minutes=1),
        ended_at=STARTED + timedelta(minutes=9),
        cost=Decimal("2.50"),
        cause_code=TurnCause.BRIEF,
    )
    chat = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd="/work/Store",
        token_hash="2" * 64,
        state_code=SessionState.IDLE,
    )
    db.add_all([work_turn, chat])
    db.flush()
    db.add(
        Chat(
            id=chat.id,
            project_id=project.id,
            session_kind_code="chat",
            kind_code=ChatKind.PROJECT,
        )
    )
    chat_turn = Turn(
        session_id=chat.id,
        seq=1,
        author_user_id=person.id,
        message="How is the scaling going?",
        words="How is the scaling going?",
        started_at=STARTED + timedelta(hours=2),
        ended_at=STARTED + timedelta(hours=2, minutes=3),
        error="The session ended.",
        cost=Decimal("0.75"),
        cause_code=TurnCause.PERSON,
    )
    db.add(chat_turn)
    db.flush()
    db.add_all(
        TokenCount(turn_id=chat_turn.id, token_kind_code=kind, tokens=tokens)
        for kind, tokens in (
            ("input", 100),
            ("cache_write", 2_000),
            ("cache_read", 30_000),
            ("output", 400),
        )
    )

    read_under = transcripts.component_version(db)
    claude_code = transcripts.component_version(db, "claude-code", "2.1.317")
    repository = Repository(name="RecipeBox")
    db.add(repository)
    db.flush()
    thread = transcripts.transcript(
        db,
        read_under,
        repository_id=repository.id,
        environment_id=work.environment_id,
        first_call_at=STARTED + timedelta(minutes=1),
        last_call_at=STARTED + timedelta(minutes=3),
    )
    start = transcripts.launch(db, thread, session_id=work.id, turn_seq=1)
    db.add(
        LaunchComponent(
            launch_id=start.id,
            component_version_id=claude_code.id,
            component_code="claude-code",
        )
    )
    asked = transcripts.prompt(db, start)
    compacted = transcripts.compaction(db, thread)
    transcripts.reference(db, models.Model, SONNET)
    transcripts.reference(db, StopReason, "max_tokens")
    transcripts.reference(db, MissCause, "compaction")
    transcripts.reference(db, EventKind, "api_error", is_error=True)
    first = transcripts.call(
        db,
        thread,
        1,
        prompt_id=asked.id,
        launch_id=start.id,
        cost=Decimal("0.50"),
        rewind=False,
        cache_miss=False,
        past_ttl=False,
        effort="high",
    )
    second = transcripts.call(
        db,
        thread,
        2,
        prompt_id=asked.id,
        launch_id=start.id,
        predecessor_id=first.id,
        sent_at=STARTED + timedelta(minutes=1, seconds=30),
        waited_seconds=30.0,
        cost=Decimal("0.25"),
        rewind=True,
        cache_miss=False,
        past_ttl=True,
        requested_model_code=SONNET,
        stop_reason_code="max_tokens",
    )
    third = transcripts.call(
        db,
        thread,
        3,
        prompt_id=asked.id,
        launch_id=start.id,
        predecessor_id=second.id,
        compaction_id=compacted.id,
        cost=Decimal("1.00"),
        rewind=False,
        cache_miss=True,
        past_ttl=False,
        miss_cause_code="compaction",
    )
    transcripts.tool_call(
        db, first, saved_characters=90_000, returned_at=STARTED + timedelta(minutes=2)
    )
    transcripts.reference(db, models.DenialKind, "rule")
    transcripts.tool_call(
        db, second, tool_use_id="toolu_0002", denial_kind_code="rule", failed=True
    )
    db.add_all(
        [
            Event(
                call_id=first.id,
                kind_code="api_error",
                at=STARTED + timedelta(seconds=90),
                detail="529",
            ),
            HookRun(
                prompt_id=asked.id,
                command="signal_activity.sh",
                duration_ms=151,
                failed=True,
                prevented_end=False,
            ),
        ]
    )

    sub_agent = transcripts.transcript(
        db,
        read_under,
        agent_id=SUB_AGENT,
        main_id=thread.id,
        agent_type="Explore",
        first_call_at=STARTED + timedelta(minutes=2, seconds=30),
        last_call_at=STARTED + timedelta(minutes=2, seconds=30),
    )
    explored = transcripts.call(
        db,
        sub_agent,
        1,
        completed_at=STARTED + timedelta(minutes=2, seconds=30),
        launch_id=start.id,
        cost=Decimal("0.10"),
        rewind=False,
        cache_miss=False,
        past_ttl=False,
    )

    loose = transcripts.transcript(
        db,
        read_under,
        session_id=OTHER,
        first_call_at=STARTED + timedelta(days=1),
        last_call_at=STARTED + timedelta(days=1),
    )
    by_hand = transcripts.call(
        db,
        loose,
        1,
        completed_at=STARTED + timedelta(days=1),
        cost=Decimal("0.05"),
        rewind=False,
        cache_miss=False,
        past_ttl=False,
    )
    db.flush()
    return Record(
        project=project,
        work=work,
        work_turn=work_turn,
        chat=chat,
        chat_turn=chat_turn,
        thread=thread,
        sub_agent=sub_agent,
        loose=loose,
        calls=[first, second, third, explored, by_hand],
    )


def catalogue(db: DbSession, zone: str = ZONE, gap: timedelta = GAP) -> Catalogue:
    return assemble(db, zone, gap)


def read(
    db: DbSession, held: Catalogue, fact: str, *paths: Path, by: Path | None = None
) -> list[tuple[Any, ...]]:
    """What each path reads on every row of the fact, in the order of `by`,
    else of the paths."""
    row = held.row(held.fact(fact))
    columns = [path(row) for path in paths]
    order = [by(row)] if by is not None else columns
    return [
        tuple(found)
        for found in db.execute(
            select(*columns).select_from(row.source()).order_by(*order)
        )
    ]


def named(held: Catalogue, *dimensions: str) -> list[Path]:
    return [held.dimension(key).path for key in dimensions]


@contextmanager
def sent(db: DbSession) -> Iterator[list[str]]:
    """The statements sent on the test's connection while the block runs,
    each as sent."""
    bind = db.get_bind()
    statements: list[str] = []

    def kept(*args: Any) -> None:
        statements.append(args[2])

    event.listen(bind, "before_cursor_execute", kept)
    try:
        yield statements
    finally:
        event.remove(bind, "before_cursor_execute", kept)
