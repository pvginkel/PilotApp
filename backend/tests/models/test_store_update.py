"""Store Update: what a row must hold (DB 276)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models import StoreUpdate
from tests.support.database import violated_constraint

MADE_AT = datetime(2026, 10, 13, 6, 2, 11, tzinfo=UTC)


class TestStoreUpdate:
    def test_an_update_holds_its_phases_and_its_error(self, session: DbSession) -> None:
        session.add(
            StoreUpdate(
                made_at=MADE_AT,
                stopped_at=MADE_AT + timedelta(seconds=13),
                reset_at=MADE_AT + timedelta(seconds=61),
                reconciled_at=MADE_AT + timedelta(seconds=79),
                lifted_at=MADE_AT + timedelta(seconds=80),
            )
        )
        session.add(
            StoreUpdate(
                made_at=MADE_AT + timedelta(days=2),
                stopped_at=MADE_AT + timedelta(days=2, seconds=1),
                error="the store's reset settled error: its setup failed",
            )
        )

        session.flush()

    def test_at_most_one_is_unlifted(self, session: DbSession) -> None:
        session.add(StoreUpdate(made_at=MADE_AT))
        session.flush()

        session.add(StoreUpdate(made_at=MADE_AT + timedelta(minutes=1)))

        assert violated_constraint(session) == "uq_store_updates_unlifted"

    def test_lifted_ones_stand_beside_the_unlifted_one(
        self, session: DbSession
    ) -> None:
        for days in (1, 2):
            made_at = MADE_AT + timedelta(days=days)
            session.add(
                StoreUpdate(made_at=made_at, lifted_at=made_at + timedelta(minutes=2))
            )
        session.add(StoreUpdate(made_at=MADE_AT + timedelta(days=3)))

        session.flush()
