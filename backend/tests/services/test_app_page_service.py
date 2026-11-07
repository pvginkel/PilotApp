"""A person's pages of Pilot: a page's beat, its away and its expiry, whether
the person is online, and what the listeners hear of it (F147; DB 303 to 306,
312)."""

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import RecordNotFoundException
from app.models import AppPage, Project, User
from app.models.reference import UserKind
from app.services.app_page_service import (
    EXPIRY_SECONDS,
    AppPageService,
    PresenceEvent,
    ShowingTurned,
    WentOffline,
)
from app.services.container import ServiceContainer
from app.utils.after_commit import (
    clear_after_commit_callbacks,
    run_after_commit_callbacks,
)
from tests.support.supervisor import Supervise, wait_until


class _Heard:
    """The service under test, and what its listener heard."""

    def __init__(self, service: AppPageService) -> None:
        self.service = service
        self.events: list[PresenceEvent] = []
        service.subscribe(self.events.append)


@pytest.fixture
def heard(container: ServiceContainer, supervise: Supervise) -> Iterator[_Heard]:
    supervisor, _ = supervise(container, controller_configured=False)
    clear_after_commit_callbacks()
    yield _Heard(AppPageService(supervisor))
    clear_after_commit_callbacks()


def _commit() -> None:
    """What the transaction's commit runs: its after-commit callbacks."""
    run_after_commit_callbacks()
    clear_after_commit_callbacks()


def _bea(session: Session) -> User:
    bea = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(bea)
    session.flush()
    return bea


def _project(session: Session, person: User) -> Project:
    project = Project(created_by_user_id=person.id)
    session.add(project)
    session.flush()
    return project


def _ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def _page(
    session: Session,
    person: User,
    project: Project | None = None,
    beat_at: datetime | None = None,
) -> AppPage:
    """A page of `person`'s, as an earlier beat left it."""
    page = AppPage(
        user_id=person.id,
        project_id=None if project is None else project.id,
        beat_at=beat_at or _ago(5),
    )
    session.add(page)
    session.flush()
    return page


def _pages(session: Session) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]]:
    session.expire_all()
    return [
        (page.id, page.user_id, page.project_id)
        for page in session.scalars(select(AppPage).order_by(AppPage.beat_at))
    ]


class TestBegin:
    def test_the_first_beat_writes_the_page_showing_its_project(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        began = datetime.now(UTC)

        page_id = heard.service.begin(session, person, project.id)

        page = session.get_one(AppPage, page_id)
        assert (page.user_id, page.project_id) == (person.id, project.id)
        assert began <= page.beat_at <= datetime.now(UTC)

    def test_a_page_showing_no_project_tells_nothing(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        page_id = heard.service.begin(session, person, None)
        _commit()

        assert _pages(session) == [(page_id, person.id, None)]
        assert heard.events == []

    def test_a_project_no_page_of_theirs_showed_comes_to_be_shown(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        heard.service.begin(session, person, project.id)
        _commit()

        assert heard.events == [ShowingTurned(person.id, project.id, shown=True)]

    def test_a_project_another_page_of_theirs_shows_tells_nothing(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project)

        heard.service.begin(session, person, project.id)
        _commit()

        assert heard.events == []

    def test_another_persons_page_on_the_project_is_not_theirs(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        bea = _bea(session)
        _page(session, bea, project)

        heard.service.begin(session, person, project.id)
        _commit()

        assert heard.events == [ShowingTurned(person.id, project.id, shown=True)]

    def test_the_persons_pages_that_count_for_nothing_are_expired_with_it(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project, beat_at=_ago(EXPIRY_SECONDS + 1))

        page_id = heard.service.begin(session, person, None)
        _commit()

        assert _pages(session) == [(page_id, person.id, None)]
        assert heard.events == [ShowingTurned(person.id, project.id, shown=False)]

    def test_an_unknown_project_is_refused_and_nothing_written(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as refused:
            heard.service.begin(session, person, unknown)

        assert str(refused.value) == f"Project {unknown} was not found"
        assert _pages(session) == []


class TestBeat:
    def test_a_beat_sets_when_it_beat_and_the_project_it_shows(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        page = _page(session, person, beat_at=_ago(60))
        began = datetime.now(UTC)

        heard.service.beat(session, person, page.id, project.id)

        session.expire_all()
        beat = session.get_one(AppPage, page.id)
        assert beat.project_id == project.id
        assert began <= beat.beat_at <= datetime.now(UTC)

    def test_a_beat_on_the_same_project_tells_nothing(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        page = _page(session, person, project)

        heard.service.beat(session, person, page.id, project.id)
        _commit()

        assert heard.events == []

    def test_a_page_moving_to_another_project_turns_both(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        other = _project(session, person)
        page = _page(session, person, project)

        heard.service.beat(session, person, page.id, other.id)
        _commit()

        assert heard.events == [
            ShowingTurned(person.id, other.id, shown=True),
            ShowingTurned(person.id, project.id, shown=False),
        ]

    def test_a_page_moving_off_a_project_another_page_shows_tells_nothing(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project)
        page = _page(session, person, project)

        heard.service.beat(session, person, page.id, None)
        _commit()

        assert heard.events == []

    def test_a_page_whose_beat_counts_for_nothing_has_ended(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        page = _page(session, person, project, beat_at=_ago(EXPIRY_SECONDS))

        with pytest.raises(RecordNotFoundException) as refused:
            heard.service.beat(session, person, page.id, project.id)

        assert str(refused.value) == f"App Page {page.id} was not found"

    def test_a_page_its_away_ended_is_not_found(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        page_id = heard.service.begin(session, person, None)
        heard.service.away(session, person, page_id)

        with pytest.raises(RecordNotFoundException):
            heard.service.beat(session, person, page_id, None)

    def test_another_persons_page_is_not_found_and_stays_as_it_was(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        bea = _bea(session)
        page = _page(session, bea)

        with pytest.raises(RecordNotFoundException):
            heard.service.beat(session, person, page.id, project.id)

        assert _pages(session) == [(page.id, bea.id, None)]

    def test_an_unknown_project_is_refused_and_the_page_stays_as_it_was(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        page = _page(session, person, project)

        with pytest.raises(RecordNotFoundException):
            heard.service.beat(session, person, page.id, uuid.uuid4())

        assert _pages(session) == [(page.id, person.id, project.id)]


class TestAway:
    def test_the_away_of_the_last_page_takes_the_person_offline(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        page = _page(session, person, project)

        heard.service.away(session, person, page.id)
        _commit()

        assert _pages(session) == []
        assert heard.events == [
            ShowingTurned(person.id, project.id, shown=False),
            WentOffline(person.id),
        ]

    def test_the_away_of_a_page_beside_another_keeps_the_person_online(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        stays = _page(session, person)
        page = _page(session, person, project)

        heard.service.away(session, person, page.id)
        _commit()

        assert _pages(session) == [(stays.id, person.id, None)]
        assert heard.events == [ShowingTurned(person.id, project.id, shown=False)]

    def test_the_away_beside_a_page_that_counts_for_nothing_takes_them_offline(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        _page(session, person, beat_at=_ago(EXPIRY_SECONDS + 1))
        page = _page(session, person)

        heard.service.away(session, person, page.id)
        _commit()

        assert _pages(session) == []
        assert heard.events == [WentOffline(person.id)]

    def test_a_page_that_has_ended_is_nothing_to_delete(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        stays = _page(session, person)

        heard.service.away(session, person, uuid.uuid4())
        _commit()

        assert _pages(session) == [(stays.id, person.id, None)]
        assert heard.events == []

    def test_another_persons_page_stays(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        bea = _bea(session)
        page = _page(session, bea)

        heard.service.away(session, person, page.id)
        _commit()

        assert _pages(session) == [(page.id, bea.id, None)]
        assert heard.events == []


class TestExpire:
    def test_a_page_whose_beat_is_ninety_seconds_old_is_deleted(
        self,
        session: Session,
        heard: _Heard,
        person: User,
        project: Project,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _page(session, person, project, beat_at=_ago(EXPIRY_SECONDS))

        with caplog.at_level(logging.INFO, "app.services.app_page_service"):
            heard.service.expire(session)
        _commit()

        assert _pages(session) == []
        assert heard.events == [
            ShowingTurned(person.id, project.id, shown=False),
            WentOffline(person.id),
        ]
        assert "1 pages of Pilot expired" in caplog.messages

    def test_a_younger_page_stays_and_keeps_its_person_online(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project, beat_at=_ago(EXPIRY_SECONDS + 30))
        stays = _page(session, person, beat_at=_ago(EXPIRY_SECONDS - 5))

        heard.service.expire(session)
        _commit()

        assert _pages(session) == [(stays.id, person.id, None)]
        assert heard.events == [ShowingTurned(person.id, project.id, shown=False)]

    def test_each_person_whose_last_page_expired_goes_offline(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        bea = _bea(session)
        _page(session, person, beat_at=_ago(EXPIRY_SECONDS + 1))
        _page(session, bea, project, beat_at=_ago(EXPIRY_SECONDS + 1))
        _page(session, bea, project, beat_at=_ago(EXPIRY_SECONDS + 2))

        heard.service.expire(session)
        _commit()

        assert _pages(session) == []
        assert sorted(heard.events, key=repr) == sorted(
            [
                WentOffline(person.id),
                ShowingTurned(bea.id, project.id, shown=False),
                WentOffline(bea.id),
            ],
            key=repr,
        )

    def test_with_nothing_to_expire_nothing_is_told_or_logged(
        self,
        session: Session,
        heard: _Heard,
        person: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _page(session, person)

        with caplog.at_level(logging.INFO, "app.services.app_page_service"):
            heard.service.expire(session)
        _commit()

        assert len(_pages(session)) == 1
        assert heard.events == []
        assert caplog.messages == []


class TestOnline:
    def test_a_page_that_beat_in_the_last_ninety_seconds_has_its_person_online(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        _page(session, person, beat_at=_ago(EXPIRY_SECONDS - 5))

        assert heard.service.online(session, person.id)

    def test_a_page_whose_beat_is_older_counts_for_nothing(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        _page(session, person, beat_at=_ago(EXPIRY_SECONDS))

        assert not heard.service.online(session, person.id)

    def test_with_no_page_the_person_is_offline(
        self, session: Session, heard: _Heard, person: User
    ) -> None:
        _page(session, _bea(session))

        assert not heard.service.online(session, person.id)


class TestShows:
    def test_a_page_of_theirs_on_the_project_shows_it(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project)

        assert heard.service.shows(session, person.id, project.id)

    def test_a_page_on_another_project_or_none_does_not(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, _project(session, person))
        _page(session, person)
        _page(session, _bea(session), project)

        assert not heard.service.shows(session, person.id, project.id)

    def test_a_page_that_counts_for_nothing_does_not(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        _page(session, person, project, beat_at=_ago(EXPIRY_SECONDS))

        assert not heard.service.shows(session, person.id, project.id)


class TestListeners:
    def test_nothing_is_told_before_the_commit_nor_after_a_rollback(
        self, session: Session, heard: _Heard, person: User, project: Project
    ) -> None:
        heard.service.begin(session, person, project.id)

        assert heard.events == []
        clear_after_commit_callbacks()
        _commit()
        assert heard.events == []

    def test_a_listener_that_fails_keeps_the_event_from_no_other(
        self,
        session: Session,
        heard: _Heard,
        person: User,
        project: Project,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def fails(event: PresenceEvent) -> None:
            raise RuntimeError("listener down")

        later: list[PresenceEvent] = []
        heard.service.subscribe(fails)
        heard.service.subscribe(later.append)
        page = _page(session, person, project)

        heard.service.away(session, person, page.id)
        with caplog.at_level(logging.ERROR, "app.services.app_page_service"):
            _commit()

        told = [
            ShowingTurned(person.id, project.id, shown=False),
            WentOffline(person.id),
        ]
        assert heard.events == told
        assert later == told
        assert [
            record.getMessage().startswith("Listener ")
            for record in caplog.records
            if record.name == "app.services.app_page_service"
        ] == [True, True]


class TestTwoProcesses:
    """During a roll two backends run at once (`docs/jobs.md`), and a person's
    pages beat and leave on several devices."""

    def test_two_sweeps_at_once_take_the_person_offline_once(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        heard = _Heard(AppPageService(supervise(container)[0]))
        ada = _committed_ada(container)
        with scoped_session(container) as db:
            db.add(AppPage(user_id=ada, beat_at=_ago(EXPIRY_SECONDS + 1)))

        with scoped_session(container) as db:
            heard.service.expire(db)
            # The other process's sweep, while this one's is not committed.
            _in_thread(lambda: _expire(container, heard.service))
            assert heard.events == []

        assert heard.events == [WentOffline(ada)]
        _expire(container, heard.service)
        assert heard.events == [WentOffline(ada)]
        assert _committed_pages(container) == []

    def test_a_sweep_skips_a_person_a_beat_holds_and_tells_nothing(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        heard = _Heard(AppPageService(supervise(container)[0]))
        ada = _committed_ada(container)
        with scoped_session(container) as db:
            db.add(AppPage(user_id=ada, beat_at=_ago(EXPIRY_SECONDS + 1)))

        with scoped_session(container) as db:
            page_id = heard.service.begin(db, db.get_one(User, ada), None)
            _in_thread(lambda: _expire(container, heard.service))

        assert heard.events == []
        assert [page for page, _ in _committed_pages(container)] == [page_id]

    def test_an_away_waiting_on_another_pages_first_beat_keeps_them_online(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        heard = _Heard(AppPageService(supervise(container)[0]))
        ada = _committed_ada(container)
        with scoped_session(container) as db:
            phone = AppPage(user_id=ada, beat_at=_ago(5))
            db.add(phone)
            db.flush()
            phone_id = phone.id
        away = threading.Thread(
            target=lambda: _away(container, heard.service, ada, phone_id)
        )

        with scoped_session(container) as db:
            desk_id = heard.service.begin(db, db.get_one(User, ada), None)
            away.start()
            # The phone's away waits on Ada's row, which the desktop's first
            # beat holds until it commits.
            wait_until(
                lambda: _waiting_on_a_lock(db) == 1,
                "the away waiting on the person's row",
            )
        away.join(timeout=30)

        assert not away.is_alive()
        assert _committed_pages(container) == [(desk_id, None)]
        assert heard.events == []

    def test_a_first_beat_waiting_on_the_last_away_follows_it_offline(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        heard = _Heard(AppPageService(supervise(container)[0]))
        ada = _committed_ada(container)
        with scoped_session(container) as db:
            phone = AppPage(user_id=ada, beat_at=_ago(5))
            db.add(phone)
            db.flush()
            phone_id = phone.id
        began: list[uuid.UUID] = []
        begin = threading.Thread(
            target=lambda: began.append(_begin(container, heard.service, ada))
        )

        with scoped_session(container) as db:
            heard.service.away(db, db.get_one(User, ada), phone_id)
            begin.start()
            wait_until(
                lambda: _waiting_on_a_lock(db) == 1,
                "the first beat waiting on the person's row",
            )
        begin.join(timeout=30)

        assert not begin.is_alive()
        assert heard.events == [WentOffline(ada)]
        assert _committed_pages(container) == [(began[0], None)]


def _committed_ada(container: ServiceContainer) -> uuid.UUID:
    with scoped_session(container) as db:
        ada = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(ada)
        db.flush()
        return ada.id


def _committed_pages(
    container: ServiceContainer,
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    with scoped_session(container) as db:
        return [
            (page.id, page.project_id)
            for page in db.scalars(select(AppPage).order_by(AppPage.id))
        ]


def _expire(container: ServiceContainer, service: AppPageService) -> None:
    with scoped_session(container) as db:
        service.expire(db)


def _away(
    container: ServiceContainer,
    service: AppPageService,
    user_id: uuid.UUID,
    page_id: uuid.UUID,
) -> None:
    with scoped_session(container) as db:
        service.away(db, db.get_one(User, user_id), page_id)


def _begin(
    container: ServiceContainer, service: AppPageService, user_id: uuid.UUID
) -> uuid.UUID:
    with scoped_session(container) as db:
        return service.begin(db, db.get_one(User, user_id), None)


def _waiting_on_a_lock(db: Session) -> int:
    """The connections to the test's database waiting on a lock, read on a
    connection of its own beside `db`'s."""
    with db.connection().engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )


def _in_thread(run: Callable[[], None]) -> None:
    """`run`, on a thread of its own: another process's transaction, on a
    database session of its own."""
    done: list[bool] = []

    def target() -> None:
        run()
        done.append(True)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=30)
    assert done, "the other process did not finish"
