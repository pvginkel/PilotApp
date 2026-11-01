"""The operator's update of the store (F144.1; DB Store Update, assertions 276,
279 and 280): made while none is unlifted, its lift asked once, and the jobs
it stopped derived from their stop."""

import threading
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from flask import Flask
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.orm import Session

from app import models
from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import Item, Project, StoreUpdate, User
from app.models.reference import ProjectState, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.store_update_service import (
    stopped_by,
    stopped_for_update,
    unlifted,
    utc_time,
)
from tests.support.store_updates import pilot, stopped_job
from tests.support.supervisor import wait_until

MADE_AT = datetime(2026, 10, 13, 6, 2, 11, tzinfo=UTC)


def _lifted(db: Session, days: int) -> StoreUpdate:
    made_at = MADE_AT - timedelta(days=days)
    lifted = StoreUpdate(made_at=made_at, lifted_at=made_at + timedelta(minutes=2))
    db.add(lifted)
    db.flush()
    return lifted


def _camp(db: Session) -> Project:
    person = User(
        kind_code=UserKind.PERSON,
        subject="subject-ada",
        handle="ada",
        name="Ada Example",
        avatar_slot=1,
    )
    db.add(person)
    db.flush()
    camp = Project(
        created_by_user_id=person.id, state_code=ProjectState.OPEN, slug="camp"
    )
    db.add(camp)
    db.flush()
    return camp


def _matching(db: Session, clause: ColumnElement[bool]) -> set[uuid.UUID]:
    return set(db.scalars(select(models.Session.id).where(clause)))


def _finished_at_stop(db: Session, job: models.Session) -> None:
    """The job's item closed by a Finish at the instant of its stop."""
    line = db.get_one(Item, job.id)
    line.done_at, line.done_cause_code = job.stopped_at, "finished"
    db.flush()


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


class TestStoppedBy:
    """The jobs an update stopped (DB 280): by Pilot from its `made_at` to its
    `lifted_at`, but those a Finish closed at their stop."""

    def test_it_is_each_job_pilot_stopped_from_the_made_at_to_the_lift(
        self, container: ServiceContainer, session: Session
    ) -> None:
        camp = _camp(session)
        update = StoreUpdate(made_at=MADE_AT, lifted_at=MADE_AT + timedelta(minutes=10))
        session.add(update)
        session.flush()
        at_made = stopped_job(container, session, camp, MADE_AT)
        within = stopped_job(container, session, camp, MADE_AT + timedelta(minutes=5))
        stopped_job(container, session, camp, MADE_AT - timedelta(seconds=1))
        stopped_job(container, session, camp, MADE_AT + timedelta(minutes=10))
        by_a_person = session.get_one(User, camp.created_by_user_id)
        stopped_job(
            container, session, camp, MADE_AT + timedelta(minutes=5), by=by_a_person
        )
        work_item = models.Session(
            project_id=camp.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.STOPPED,
            stopped_at=MADE_AT + timedelta(minutes=5),
            stopped_by_user_id=pilot(session).id,
        )
        session.add(work_item)
        session.flush()

        assert _matching(session, stopped_by(update)) == {at_made.id, within.id}

    def test_an_unlifted_update_takes_each_stop_since_its_made_at(
        self, container: ServiceContainer, session: Session
    ) -> None:
        camp = _camp(session)
        update = StoreUpdate(made_at=MADE_AT)
        session.add(update)
        session.flush()
        later = stopped_job(container, session, camp, MADE_AT + timedelta(days=3))

        assert _matching(session, stopped_by(update)) == {later.id}

    def test_a_job_a_finish_closed_at_its_stop_is_not_the_updates(
        self, container: ServiceContainer, session: Session
    ) -> None:
        camp = _camp(session)
        update = StoreUpdate(made_at=MADE_AT)
        session.add(update)
        session.flush()
        finished = stopped_job(container, session, camp, MADE_AT + timedelta(minutes=1))
        _finished_at_stop(session, finished)
        closed_later = stopped_job(
            container, session, camp, MADE_AT + timedelta(minutes=1)
        )
        line = session.get_one(Item, closed_later.id)
        line.done_at = MADE_AT + timedelta(minutes=2)
        line.done_cause_code = "finished"
        session.flush()

        assert _matching(session, stopped_by(update)) == {closed_later.id}


class TestStoppedForUpdate:
    def test_it_is_each_job_some_update_stopped_lifted_or_not(
        self, container: ServiceContainer, session: Session
    ) -> None:
        camp = _camp(session)
        lifted = _lifted(session, 2)
        standing = StoreUpdate(made_at=MADE_AT)
        session.add(standing)
        session.flush()
        assert lifted.lifted_at is not None
        in_lifted = stopped_job(
            container, session, camp, lifted.made_at + timedelta(minutes=1)
        )
        stopped_job(container, session, camp, lifted.lifted_at)
        stopped_job(container, session, camp, MADE_AT - timedelta(hours=1))
        in_standing = stopped_job(
            container, session, camp, MADE_AT + timedelta(minutes=1)
        )
        finished = stopped_job(container, session, camp, MADE_AT + timedelta(minutes=2))
        _finished_at_stop(session, finished)

        assert _matching(session, stopped_for_update()) == {
            in_lifted.id,
            in_standing.id,
        }
