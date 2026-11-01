"""The operator's update of the store (F144.1; DB Store Update, assertions 276
and 279): made while none is unlifted, its lift asked once."""

import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import StoreUpdate
from app.services.container import ServiceContainer
from app.services.store_update_service import unlifted, utc_time
from tests.support.supervisor import wait_until

MADE_AT = datetime(2026, 10, 13, 6, 2, 11, tzinfo=UTC)


def _lifted(db: Session, days: int) -> StoreUpdate:
    made_at = MADE_AT - timedelta(days=days)
    lifted = StoreUpdate(made_at=made_at, lifted_at=made_at + timedelta(minutes=2))
    db.add(lifted)
    db.flush()
    return lifted


class TestUtcTime:
    def test_it_reads_a_time_in_utc_to_the_second(self) -> None:
        at = datetime(
            2026, 10, 13, 8, 2, 11, 640000, tzinfo=timezone(timedelta(hours=2))
        )

        assert utc_time(at) == "2026-10-13 06:02:11 UTC"


class TestUnlifted:
    def test_it_is_none_while_every_update_is_lifted(self, session: Session) -> None:
        _lifted(session, 2)

        assert unlifted(session) is None

    def test_it_is_the_update_not_lifted_yet(self, session: Session) -> None:
        _lifted(session, 2)
        standing = StoreUpdate(made_at=MADE_AT)
        session.add(standing)
        session.flush()

        assert unlifted(session) is standing


class TestMake:
    def test_it_makes_an_update_with_no_phase_written(
        self, container: ServiceContainer, session: Session
    ) -> None:
        before = datetime.now(UTC)

        made = container.store_update_service().make()

        assert session.scalars(select(StoreUpdate)).one() is made
        assert before <= made.made_at <= datetime.now(UTC)
        assert (
            made.stopped_at,
            made.reset_at,
            made.reconciled_at,
            made.lift_requested_at,
            made.lifted_at,
            made.error,
        ) == (None, None, None, None, None, None)

    def test_it_is_made_beside_the_lifted_ones(
        self, container: ServiceContainer, session: Session
    ) -> None:
        _lifted(session, 2)
        _lifted(session, 1)

        made = container.store_update_service().make()

        assert unlifted(session) is made

    def test_it_is_refused_while_an_update_is_unlifted(
        self, container: ServiceContainer, session: Session
    ) -> None:
        session.add(StoreUpdate(made_at=MADE_AT, stopped_at=MADE_AT))
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            container.store_update_service().make()

        assert refused.value.message == (
            "Cannot update the store because an update is under way since "
            "2026-10-13 06:02:11 UTC"
        )
        assert session.scalar(select(func.count()).select_from(StoreUpdate)) == 1


class TestRequestLift:
    def test_it_asks_the_lift_of_the_unlifted_update(
        self, container: ServiceContainer, session: Session
    ) -> None:
        _lifted(session, 1)
        standing = StoreUpdate(made_at=MADE_AT, stopped_at=MADE_AT)
        session.add(standing)
        session.flush()
        before = datetime.now(UTC)

        asked = container.store_update_service().request_lift()

        assert asked is standing
        assert asked.lift_requested_at is not None
        assert before <= asked.lift_requested_at <= datetime.now(UTC)
        assert asked.lifted_at is None

    def test_a_second_ask_leaves_the_firsts_time(
        self, container: ServiceContainer, session: Session
    ) -> None:
        first = MADE_AT + timedelta(minutes=5)
        session.add(StoreUpdate(made_at=MADE_AT, lift_requested_at=first))
        session.flush()

        asked = container.store_update_service().request_lift()

        assert asked.lift_requested_at == first

    @pytest.mark.parametrize("lifted_days", [[], [1]])
    def test_it_is_refused_while_no_update_is_under_way(
        self, container: ServiceContainer, session: Session, lifted_days: list[int]
    ) -> None:
        for days in lifted_days:
            _lifted(session, days)

        with pytest.raises(InvalidOperationException) as refused:
            container.store_update_service().request_lift()

        assert refused.value.message == (
            "Cannot lift the store's update because no update is under way"
        )


class TestGet:
    def test_it_reads_the_update_as_its_row_stands(
        self, container: ServiceContainer, session: Session
    ) -> None:
        update = _lifted(session, 1)

        assert container.store_update_service().get(update.id) is update


def _waiting_on(container: ServiceContainer, table: str) -> int:
    # A session of its own: the caller may be inside a `scoped_session`.
    db: Session = container.session_maker()()
    try:
        return (
            db.scalar(
                text(
                    "SELECT count(*) FROM pg_locks l JOIN pg_class c"
                    " ON c.oid = l.relation"
                    " WHERE c.relname = :table AND NOT l.granted"
                ),
                {"table": table},
            )
            or 0
        )
    finally:
        db.close()


class TestConcurrentMakes:
    def test_of_two_at_once_one_is_made_and_the_other_refused(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container
        refusals: list[str] = []

        def make() -> None:
            try:
                with scoped_session(container):
                    container.store_update_service().make()
            except InvalidOperationException as refused:
                refusals.append(refused.cause)

        holder: Session = container.session_maker()()
        holder.execute(text("LOCK TABLE store_updates IN SHARE ROW EXCLUSIVE MODE"))
        threads = [threading.Thread(target=make) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            wait_until(
                lambda: _waiting_on(container, "store_updates") == 2, "both waiting"
            )
        finally:
            holder.rollback()
            holder.close()
        for thread in threads:
            thread.join()

        assert len(refusals) == 1
        assert refusals[0].startswith("an update is under way since ")
        with scoped_session(container) as db:
            assert db.scalar(select(func.count()).select_from(StoreUpdate)) == 1
