"""Pilot Note and Send Alert: what a row must hold (DB 616 to 626, 629,
631)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.models import Block, Item, PilotNote, Project, SendAlert, Turn, User
from app.models.reference import TurnCause
from app.services.container import ServiceContainer
from tests.support.database import violated_constraint

CAMP = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""


@pytest.fixture
def turn(session: Session, project_session: models.Session) -> Turn:
    """A Turn of a Session of the project, in flight."""
    turn = Turn(
        session_id=project_session.id,
        seq=1,
        message="Pre-rule.",
        started_at=datetime.now(UTC),
        cause_code=TurnCause.BRIEF,
    )
    session.add(turn)
    session.flush()
    return turn


@pytest.fixture
def camp(
    container: ServiceContainer, project: Project, project_session: models.Session
) -> Item:
    """A decision with one block."""
    return container.document_service().bear_item(
        project, "decision", "Camp plan", project_session, CAMP
    )


def _block(session: Session, item: Item) -> Block:
    return session.scalars(select(Block).where(Block.document_id == item.id)).one()


class TestPilotNote:
    def test_a_note_on_a_block_holds_its_four_and_is_written_at_its_call(
        self, session: Session, camp: Item, turn: Turn
    ) -> None:
        note = PilotNote(
            item_id=camp.id,
            block_id=_block(session, camp).id,
            turn_id=turn.id,
            text="You ruled one tent last week.",
            suggested_answer="Tunnel",
            suggested_note="One tent, as ruled",
        )
        session.add(note)
        session.flush()
        session.refresh(note)

        assert note.created_at is not None
        assert (note.withdrawn_at, note.offer_taken_at) == (None, None)

    def test_a_note_holds_one_of_the_four_at_least(
        self, session: Session, camp: Item, turn: Turn
    ) -> None:
        session.add(
            PilotNote(
                item_id=camp.id, block_id=_block(session, camp).id, turn_id=turn.id
            )
        )

        assert violated_constraint(session) == "ck_pilot_notes_holds"

    @pytest.mark.parametrize(
        "field",
        ["suggested_answer", "suggested_note", "offer"],
    )
    def test_a_note_on_the_item_as_a_whole_holds_text_alone(
        self, session: Session, camp: Item, turn: Turn, field: str
    ) -> None:
        session.add(
            PilotNote(
                item_id=camp.id,
                turn_id=turn.id,
                text="The wrap-up closed E3.",
                **{field: "Dome"},
            )
        )

        assert violated_constraint(session) == "ck_pilot_notes_on_the_item"

    def test_an_offer_taken_names_who_took_it(
        self, session: Session, camp: Item, turn: Turn, person: User
    ) -> None:
        session.add(
            PilotNote(
                item_id=camp.id,
                block_id=_block(session, camp).id,
                turn_id=turn.id,
                offer="Pitch the dome",
                offer_taken_at=datetime.now(UTC),
            )
        )

        assert violated_constraint(session) == "ck_pilot_notes_offer_taken"

    def test_only_a_note_with_an_offer_has_it_taken(
        self, session: Session, camp: Item, turn: Turn, person: User
    ) -> None:
        session.add(
            PilotNote(
                item_id=camp.id,
                block_id=_block(session, camp).id,
                turn_id=turn.id,
                text="You ruled one tent.",
                offer_taken_at=datetime.now(UTC),
                offer_taken_by_user_id=person.id,
            )
        )

        assert violated_constraint(session) == "ck_pilot_notes_offer_taken"

    def test_its_turn_is_one_that_is(self, session: Session, camp: Item) -> None:
        session.add(PilotNote(item_id=camp.id, turn_id=999_999, text="Gone."))

        assert violated_constraint(session) == "pilot_notes_turn_id_fkey"


class TestSendAlert:
    def test_an_alert_awaits_a_block_and_is_written_at_its_call(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        camp: Item,
        turn: Turn,
    ) -> None:
        sent = container.document_service().bear_item(
            project, "decision", "The build", project_session, CAMP
        )
        alert = SendAlert(
            item_id=sent.id,
            awaits_block_id=_block(session, camp).id,
            turn_id=turn.id,
            text="Answer the camp plan first.",
        )
        session.add(alert)
        session.flush()
        session.refresh(alert)

        assert alert.created_at is not None
        assert alert.withdrawn_at is None

    def test_its_awaited_block_is_one_that_is(
        self, session: Session, turn: Turn, item: Item
    ) -> None:
        session.add(
            SendAlert(
                item_id=item.id,
                awaits_block_id=999_999,
                turn_id=turn.id,
                text="Answer it first.",
            )
        )

        assert violated_constraint(session) == "send_alerts_awaits_block_id_fkey"
