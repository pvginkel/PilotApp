"""A person's overrule of the week's usage halt (F135.2; DB Quota Overrule,
assertions 179 and 267): the allowance under the second limit, run-out at it,
made only while the week's halt holds and only as it offers, one at a time."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import QuotaOverrule, UsageReading, User, WindowShare
from app.models.reference import OverruleKind, UsageWindow, UserKind
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.usage_halts import overrule
from tests.support.supervisor import wait_until

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""

NEWCOMER = AuthContext(
    subject="subject-newcomer", email=None, name="Nia Newcomer", roles={"editor"}
)
"""A person at their first sign-in, with no handle yet."""

ALLOWANCE = OverruleKind.ALLOWANCE
RUN_OUT = OverruleKind.RUN_OUT

RECEIVED_AT = datetime(2026, 10, 6, 18, tzinfo=UTC)


def _record(
    db: Session, *, week: float | None, five_hour: float | None = 0.1
) -> UsageReading:
    """A fresh Usage Reading, with a Window Share for each window given one."""
    reading = UsageReading(taken_at=RECEIVED_AT, received_at=RECEIVED_AT, stale=False)
    db.add(reading)
    db.flush()
    for window, share in (
        (UsageWindow.SEVEN_DAY, week),
        (UsageWindow.FIVE_HOUR, five_hour),
    ):
        if share is not None:
            db.add(
                WindowShare(
                    reading_id=reading.id,
                    window_code=window,
                    share=share,
                    resets_at=RECEIVED_AT + timedelta(days=1),
                )
            )
    db.flush()
    return reading


class _Watcher:
    """The usage watcher, as a made overrule calls it."""

    def __init__(self) -> None:
        self.overruled_calls = 0

    def overruled(self) -> None:
        self.overruled_calls += 1


@pytest.fixture
def watcher(container: ServiceContainer) -> _Watcher:
    watcher = _Watcher()
    container.usage_watcher.override(providers.Object(watcher))
    return watcher


@pytest.fixture
def make(
    container: ServiceContainer, watcher: _Watcher
) -> Callable[..., QuotaOverrule]:
    """Make an overrule, uncommitted: a refusal leaves the test's rows."""

    def made(kind: OverruleKind, auth: AuthContext = ADA) -> QuotaOverrule:
        return container.quota_overrule_service().make(auth, kind)

    return made


class TestMake:
    def test_the_allowance_targets_the_share_plus_the_allowance_and_lifts_the_halt(
        self,
        container: ServiceContainer,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _record(session, week=0.91)
        before = datetime.now(UTC)

        with scoped_session(container):
            made = container.quota_overrule_service().make(ADA, ALLOWANCE)

        assert made.kind_code is ALLOWANCE
        assert made.target == 0.96
        assert made.made_by_user_id == person.id
        assert before <= made.made_at <= datetime.now(UTC)
        assert made.ended_at is None
        assert overrule(session) is made
        assert container.usage_halts().holding(session) == ()
        # Told once the commit is done.
        assert watcher.overruled_calls == 1

    def test_nothing_is_told_before_the_commit(
        self,
        session: Session,
        person: User,
        watcher: _Watcher,
        make: Callable[..., QuotaOverrule],
    ) -> None:
        _record(session, week=0.91)

        make(ALLOWANCE)

        assert watcher.overruled_calls == 0

    @pytest.mark.parametrize("week", [0.95, 0.9799])
    def test_the_allowances_target_is_held_to_the_second_limit(
        self,
        session: Session,
        person: User,
        make: Callable[..., QuotaOverrule],
        week: float,
    ) -> None:
        _record(session, week=week)

        assert make(ALLOWANCE).target == 0.98

    @pytest.mark.parametrize("week", [0.98, 1.04])
    def test_run_out_at_or_over_the_second_limit_has_no_target(
        self,
        session: Session,
        person: User,
        make: Callable[..., QuotaOverrule],
        week: float,
    ) -> None:
        _record(session, week=week)

        made = make(RUN_OUT)

        assert (made.kind_code, made.target) == (RUN_OUT, None)

    @pytest.mark.parametrize(
        ("week", "five_hour"),
        [(0.89, 0.1), (None, 0.1), (0.5, 0.9)],
        ids=["under-the-first-limit", "the-week-left-out", "the-five-hours-alone"],
    )
    def test_it_is_refused_while_the_weeks_halt_does_not_hold(
        self,
        session: Session,
        person: User,
        make: Callable[..., QuotaOverrule],
        week: float | None,
        five_hour: float,
    ) -> None:
        _record(session, week=week, five_hour=five_hour)

        with pytest.raises(InvalidOperationException) as refused:
            make(ALLOWANCE)

        assert refused.value.message == (
            "Cannot add the week's allowance because the week's halt does not hold"
        )

    def test_it_is_refused_before_the_first_reading(
        self, person: User, make: Callable[..., QuotaOverrule]
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            make(RUN_OUT)

        assert refused.value.message == (
            "Cannot run out the week's quota because the week's halt does not hold"
        )

    def test_it_is_refused_while_another_holds(
        self,
        session: Session,
        person: User,
        make: Callable[..., QuotaOverrule],
    ) -> None:
        _record(session, week=0.91)
        make(ALLOWANCE)

        with pytest.raises(InvalidOperationException) as refused:
            make(ALLOWANCE)

        assert refused.value.message == (
            "Cannot add the week's allowance because an overrule holds already"
        )

    @pytest.mark.parametrize(
        ("week", "kind", "message"),
        [
            (
                0.98,
                ALLOWANCE,
                "Cannot add the week's allowance because the week's share is at "
                "the second limit, where only run-out is offered",
            ),
            (
                0.97,
                RUN_OUT,
                "Cannot run out the week's quota because the week's share is "
                "under the second limit, where the allowance is offered",
            ),
        ],
    )
    def test_the_kind_the_halt_does_not_offer_is_refused(
        self,
        session: Session,
        person: User,
        make: Callable[..., QuotaOverrule],
        week: float,
        kind: OverruleKind,
        message: str,
    ) -> None:
        _record(session, week=week)

        with pytest.raises(InvalidOperationException) as refused:
            make(kind)

        assert refused.value.message == message
        assert overrule(session) is None

    def test_a_caller_without_a_handle_is_refused(
        self, session: Session, make: Callable[..., QuotaOverrule]
    ) -> None:
        _record(session, week=0.91)

        with pytest.raises(InvalidOperationException) as refused:
            make(ALLOWANCE, NEWCOMER)

        assert refused.value.message == (
            "Cannot add the week's allowance because you have not chosen your "
            "handle yet"
        )


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


@pytest.fixture
def committed(committed_app: Flask) -> ServiceContainer:
    """A container on a database of its own, with Ada and the week halted at
    0.91, committed, and the watcher a stand-in."""
    container: ServiceContainer = committed_app.container
    container.usage_watcher.override(providers.Object(_Watcher()))
    with scoped_session(container) as db:
        db.add(
            User(
                kind_code=UserKind.PERSON,
                subject=ADA.subject,
                handle="ada",
                name="Ada Example",
                avatar_slot=1,
            )
        )
        _record(db, week=0.91)
    return container


class TestConcurrentMakes:
    def test_of_two_at_once_one_is_made_and_the_other_refused(
        self, committed: ServiceContainer
    ) -> None:
        refusals: list[str] = []

        def make() -> None:
            try:
                with scoped_session(committed):
                    committed.quota_overrule_service().make(ADA, ALLOWANCE)
            except InvalidOperationException as refused:
                refusals.append(refused.message)

        holder: Session = committed.session_maker()()
        holder.execute(text("LOCK TABLE quota_overrules IN SHARE ROW EXCLUSIVE MODE"))
        threads = [threading.Thread(target=make) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            wait_until(
                lambda: _waiting_on(committed, "quota_overrules") == 2, "both waiting"
            )
        finally:
            holder.rollback()
            holder.close()
        for thread in threads:
            thread.join()

        assert refusals == [
            "Cannot add the week's allowance because an overrule holds already"
        ]
        with scoped_session(committed) as db:
            assert db.scalar(select(func.count()).select_from(QuotaOverrule)) == 1
