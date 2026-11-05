"""Revision 0027: each Turn's own tokens and cost, its conversation's figures
so far taken apart as the relay takes a `result` line apart (DB 275)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Environment, Project, TokenCount, Turn
from app.models.reference import RecordKind, SessionState, TokenKind
from app.services.container import ServiceContainer
from app.services.token_counts import Spent, reported_before, spent
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import raw_turn

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _result_line(name: str) -> dict[str, Any]:
    """The `result` line of the invented turn `name`."""
    (line,) = (
        parsed
        for parsed in map(json.loads, raw_turn(name))
        if parsed["type"] == "result"
    )
    return line


def _tokens(*counts: int) -> dict[TokenKind, int]:
    return dict(
        zip(
            (
                TokenKind.INPUT,
                TokenKind.CACHE_WRITE,
                TokenKind.CACHE_READ,
                TokenKind.OUTPUT,
            ),
            counts,
            strict=True,
        )
    )


TEXT = Spent(_tokens(3, 350, 1200, 11), Decimal("0.0021"))
"""What the invented `turn_text` run reports, a conversation's first."""
RESUMED = Spent(_tokens(6, 470, 2750, 20), Decimal("0.0029"))
"""What the invented `turn_resumed` run reports, `turn_text`'s conversation's
figures so far."""
RESUMED_OWN = Spent(_tokens(3, 120, 1550, 9), Decimal("0.0008"))
"""What `turn_resumed`'s run spent itself."""
CAMP = _result_line("turn_text")["session_id"]
OTHER = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def _upgrade(db: DbSession) -> None:
    """Revision 0027's upgrade, on the test's transaction."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0027")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        revision.module.upgrade()
    db.expire_all()


class _Recorded:
    """Sessions and Turns as the relay recorded them before the revision: a
    Turn's figures its last `result` line's."""

    def __init__(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        self.db = container.db_session()
        self._records = container.session_record_service()
        self._project = project
        self._environment = environment

    def session(self, conversation: str | None) -> models.Session:
        run = models.Session(
            project_id=self._project.id,
            environment_id=self._environment.id,
            kind_code="work",
            cwd="/work/Example",
            conversation_id=conversation,
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.IDLE,
        )
        self.db.add(run)
        self.db.flush()
        return run

    def turn(self, run: models.Session, figures: Spent | None) -> Turn:
        """The Session's next Turn, its figures `figures`; none for a turn
        cut before `claude` printed its `result` line."""
        run.turns += 1
        turn = Turn(
            session_id=run.id,
            seq=run.turns,
            message="Fix the client for v4.",
            started_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
            cost=None if figures is None else figures.cost,
        )
        self.db.add(turn)
        self.db.flush()
        if figures is not None:
            self.db.add_all(
                TokenCount(turn_id=turn.id, token_kind_code=kind, tokens=tokens)
                for kind, tokens in figures.tokens.items()
            )
            self.db.flush()
        return turn

    def printed(self, run: models.Session, *lines: dict[str, Any]) -> Turn:
        """The Session's next Turn, in which `claude` printed `lines`, its
        figures the last line's that reports them, as the relay wrote them."""
        figures = [reported for reported in map(spent, lines) if reported is not None]
        turn = self.turn(run, figures[-1] if figures else None)
        for offset, line in enumerate(lines):
            self._records.append(
                run.id,
                RecordKind.CLAUDE,
                payload=line,
                turn_id=turn.id,
                raw_offset=offset,
                controller_session="claude-1",
            )
        return turn


@pytest.fixture
def recorded(
    container: ServiceContainer, project: Project, environment: Environment
) -> Iterator[_Recorded]:
    clear_after_commit_callbacks()
    yield _Recorded(container, project, environment)
    clear_after_commit_callbacks()


def _figures(db: DbSession, turn: Turn) -> Spent | None:
    """The Turn's Token Counts and cost; None where it has neither."""
    counts = dict(
        db.execute(
            select(TokenCount.token_kind_code, TokenCount.tokens).where(
                TokenCount.turn_id == turn.id
            )
        ).all()
    )
    return Spent(counts, turn.cost) if counts or turn.cost is not None else None


class TestTurnsOwnFigures:
    def test_a_turn_carrying_its_conversation_on_gets_its_own_figures(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        """The conversation spans its Sessions; a turn cut before its
        `result` line is passed over."""
        run = recorded.session(CAMP)
        first = recorded.turn(run, TEXT)
        cut = recorded.turn(run, None)
        resumed = recorded.turn(recorded.session(CAMP), RESUMED)

        _upgrade(session)

        assert _figures(session, first) == TEXT
        assert _figures(session, cut) is None
        assert _figures(session, resumed) == RESUMED_OWN

    def test_a_fresh_total_stays_as_it_is_and_the_next_turn_is_taken_against_it(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        run = recorded.session(CAMP)
        recorded.turn(run, RESUMED)
        fresh = recorded.turn(run, TEXT)
        after = recorded.turn(run, RESUMED)

        _upgrade(session)

        assert _figures(session, fresh) == TEXT
        assert _figures(session, after) == RESUMED_OWN

    def test_another_conversations_turn_is_not_the_turn_before(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        recorded.turn(recorded.session(CAMP), TEXT)
        other = recorded.turn(recorded.session(OTHER), TEXT)
        resumed = recorded.turn(recorded.session(CAMP), RESUMED)

        _upgrade(session)

        assert _figures(session, other) == TEXT
        assert _figures(session, resumed) == RESUMED_OWN

    def test_the_turns_of_a_session_with_no_conversation_stay_as_they_are(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        run = recorded.session(None)
        recorded.turn(run, TEXT)
        second = recorded.turn(run, RESUMED)

        _upgrade(session)

        assert _figures(session, second) == RESUMED

    def test_a_cost_either_turn_lacks_stays_the_turns(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        run = recorded.session(CAMP)
        recorded.turn(run, Spent(TEXT.tokens, None))
        after_none = recorded.turn(run, RESUMED)
        none = recorded.turn(
            run,
            Spent({kind: tokens * 2 for kind, tokens in RESUMED.tokens.items()}, None),
        )

        _upgrade(session)

        assert _figures(session, after_none) == Spent(RESUMED_OWN.tokens, RESUMED.cost)
        assert _figures(session, none) == Spent(RESUMED.tokens, None)

    def test_it_takes_a_turn_apart_as_the_relay_takes_its_line_apart(
        self, session: DbSession, recorded: _Recorded
    ) -> None:
        """What the relay writes for each Turn, its last line that reports
        less the conversation's last before it, is what the revision writes;
        the lines stay as they are."""
        text, resumed = _result_line("turn_text"), _result_line("turn_resumed")
        run = recorded.session(CAMP)
        printed = [
            (run, [text]),
            (run, [{"type": "assistant", "message": {}}]),
            (
                recorded.session(CAMP),
                [
                    {**resumed, "total_cost_usd": 0.0024},
                    resumed,
                    {**resumed, "modelUsage": None},
                ],
            ),
            (run, [{**text, "total_cost_usd": 0.0001}]),
        ]
        turns = [recorded.printed(each, *lines) for each, lines in printed]
        relayed = [
            _relayed(session, turn, lines)
            for turn, (_, lines) in zip(turns, printed, strict=True)
        ]

        _upgrade(session)

        assert [_figures(session, turn) for turn in turns] == relayed
        assert relayed[2] == RESUMED_OWN


def _relayed(db: DbSession, turn: Turn, lines: list[dict[str, Any]]) -> Spent | None:
    """What the relay writes for the Turn whose `claude` printed `lines`: the
    last line's that reports, less the conversation's last before the Turn."""
    reported = [figures for figures in map(spent, lines) if figures is not None]
    return reported[-1].less(reported_before(db, turn.id)) if reported else None
