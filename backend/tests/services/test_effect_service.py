"""A tool call's Effects, placed by one `server` record of the Turn the call
ran in (F41; DB assertions 133 to 142, 215, 216; design 2 §10)."""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import RecordNotFoundException
from app.models import Block, Document, Effect, Item, Turn
from app.models.reference import BlockKind, EffectKind, RecordKind
from app.services.container import ServiceContainer
from app.services.effect_service import EFFECT, Change, EffectLine, EffectService
from app.services.session_record_service import read_records

TOOL_USE_ID = "toolu_01ABC"


@pytest.fixture
def effects(container: ServiceContainer) -> EffectService:
    return container.effect_service()


def _turn(db: DbSession, run: models.Session, seq: int, ended: bool = False) -> Turn:
    now = datetime.now(UTC)
    turn = Turn(
        session_id=run.id,
        seq=seq,
        message=f"Turn {seq}",
        started_at=now,
        ended_at=now if ended else None,
    )
    db.add(turn)
    db.flush()
    return turn


def _effects(db: DbSession) -> list[tuple[int, int, EffectKind, uuid.UUID | None]]:
    return [
        (effect.turn_id, effect.record_id, effect.kind_code, effect.item_id)
        for effect in db.scalars(select(Effect).order_by(Effect.id))
    ]


class TestRecord:
    def test_the_calls_effects_are_placed_by_one_record_of_the_turn_in_flight(
        self,
        session: DbSession,
        effects: EffectService,
        project_session: models.Session,
        item: Item,
    ) -> None:
        _turn(session, project_session, 1, ended=True)
        turn = _turn(session, project_session, 2)
        line = EffectLine("Marked read", "Which colour for the badge?", item.id)

        record = effects.record(
            project_session.id,
            TOOL_USE_ID,
            line,
            [Change(EffectKind.MARKED, item_id=item.id)],
        )

        assert record is not None
        [stored] = read_records(session, project_session.id, limit=10)
        assert (stored.record.id, stored.record.kind_code, stored.turn) == (
            record.id,
            RecordKind.SERVER,
            2,
        )
        assert stored.record.payload == {
            "type": EFFECT,
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Marked read",
                "label": "Which colour for the badge?",
                "itemId": str(item.id),
            },
        }
        assert _effects(session) == [(turn.id, record.id, EffectKind.MARKED, item.id)]

    def test_a_call_that_changed_several_things_has_one_line(
        self,
        session: DbSession,
        effects: EffectService,
        project_session: models.Session,
        item: Item,
    ) -> None:
        turn = _turn(session, project_session, 1)

        record = effects.record(
            project_session.id,
            TOOL_USE_ID,
            EffectLine("Stopped", "Fixing the client", item.id),
            [
                Change(EffectKind.STOPPED, item_id=item.id),
                Change(EffectKind.FINISHED),
            ],
        )

        assert record is not None
        assert len(read_records(session, project_session.id, limit=10)) == 1
        assert _effects(session) == [
            (turn.id, record.id, EffectKind.STOPPED, item.id),
            (turn.id, record.id, EffectKind.FINISHED, None),
        ]

    def test_the_line_names_the_block_it_goes_to_and_no_id_it_lacks(
        self,
        session: DbSession,
        effects: EffectService,
        project_session: models.Session,
        draft_document: Document,
    ) -> None:
        """A draft's Block has no Item (DB §2.3, Effect)."""
        turn = _turn(session, project_session, 1)
        block = Block(
            document_id=draft_document.id,
            local_id="Q1",
            position=1,
            kind_code=BlockKind.QUESTION,
        )
        session.add(block)
        session.flush()
        block_id = f"{draft_document.id}/Q1"

        answered = effects.record(
            project_session.id,
            None,
            EffectLine("Answered", "Q1 · Which environment?", block_id=block_id),
            [Change(EffectKind.ANSWERED, block_id=block.id)],
        )
        finished = effects.record(
            project_session.id,
            None,
            EffectLine("Finished", "MyDownloads"),
            [Change(EffectKind.FINISHED)],
        )

        assert answered is not None
        assert finished is not None
        assert [
            stored.record.payload
            for stored in read_records(session, project_session.id, limit=10)
        ] == [
            {
                "type": EFFECT,
                "toolUseId": None,
                "effect": {
                    "verb": "Answered",
                    "label": "Q1 · Which environment?",
                    "blockId": block_id,
                },
            },
            {
                "type": EFFECT,
                "toolUseId": None,
                "effect": {"verb": "Finished", "label": "MyDownloads"},
            },
        ]
        assert [
            (effect.record_id, effect.kind_code, effect.block_id)
            for effect in session.scalars(select(Effect).order_by(Effect.id))
        ] == [
            (answered.id, EffectKind.ANSWERED, block.id),
            (finished.id, EffectKind.FINISHED, None),
        ]
        assert {effect.turn_id for effect in session.scalars(select(Effect))} == {
            turn.id
        }

    def test_a_call_that_changed_nothing_records_nothing(
        self,
        session: DbSession,
        effects: EffectService,
        project_session: models.Session,
    ) -> None:
        _turn(session, project_session, 1)

        record = effects.record(
            project_session.id,
            TOOL_USE_ID,
            EffectLine("Attached", "survey, 0 files"),
            [],
        )

        assert record is None
        assert read_records(session, project_session.id, limit=10) == []
        assert _effects(session) == []

    def test_a_call_with_no_turn_in_flight_records_nothing(
        self,
        session: DbSession,
        effects: EffectService,
        project_session: models.Session,
        item: Item,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A call that finds its Session with no Turn in flight: no Turn to
        record under."""
        _turn(session, project_session, 1, ended=True)

        with caplog.at_level(logging.WARNING, logger="app.services.effect_service"):
            record = effects.record(
                project_session.id,
                TOOL_USE_ID,
                EffectLine("Registered", "inbox/1", item.id),
                [Change(EffectKind.REGISTERED, item_id=item.id)],
            )

        assert record is None
        assert read_records(session, project_session.id, limit=10) == []
        assert _effects(session) == []
        assert caplog.messages == [
            f"Session {project_session.id} changed the record with no turn in"
            " flight: Registered · inbox/1, no effect recorded"
        ]

    def test_an_unknown_session_is_refused(self, effects: EffectService) -> None:
        with pytest.raises(RecordNotFoundException):
            effects.record(
                uuid.uuid4(),
                TOOL_USE_ID,
                EffectLine("Finished", "x"),
                [Change(EffectKind.FINISHED)],
            )
