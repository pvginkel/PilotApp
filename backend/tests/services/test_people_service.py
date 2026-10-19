"""PeopleService: the person on the record, born at the handle step (F137)."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from flask import Flask
from sqlalchemy import Engine, func, select
from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException, ValidationException
from app.extensions import db
from app.models import User
from app.models.reference import UserKind
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.people_service import (
    PeopleService,
    handle_prefill,
    initials,
    token_name,
)


def _auth(
    subject: str = "subject-ben",
    name: str | None = "Ben Example",
    email: str | None = "ben@example.com",
) -> AuthContext:
    return AuthContext(subject=subject, email=email, name=name, roles={"editor"})


def _people(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.kind_code == UserKind.PERSON)
    )


def _add_person(session: Session, handle: str, avatar_slot: int) -> User:
    person = User(
        kind_code=UserKind.PERSON,
        subject=f"subject-{handle}",
        handle=handle,
        name=handle.title(),
        avatar_slot=avatar_slot,
    )
    session.add(person)
    session.flush()
    return person


@pytest.fixture
def people(container: ServiceContainer) -> PeopleService:
    return container.people_service()


class TestInitials:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Ada Example", "AE"),
            ("Pieter van Ginkel", "PG"),
            ("Mariska van den Berg", "MB"),
            ("Ronald McDonald", "RM"),
            ("Émile Zola", "ÉZ"),
            ("Local Admin", "LA"),
        ],
    )
    def test_the_first_two_capitals(self, name: str, expected: str) -> None:
        assert initials(name) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Madonna", "M"),
            ("Ada lovelace", "AL"),
            ("ada", "A"),
            ("jan-piet", "JP"),
            ("r2-d2", "RD"),
            ("---", "-"),
        ],
    )
    def test_a_name_with_fewer_capitals_still_gives_initials(
        self, name: str, expected: str
    ) -> None:
        assert initials(name) == expected


class TestHandlePrefill:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Pieter van Ginkel", "pieter"),
            ("Local Admin", "local"),
            ("Jean-Luc Picard", "jean-luc"),
            ("Émile Zola", "emile"),
            ("O'Brien", "obrien"),
            ("Straße", "strasse"),
            ("R2D2 Unit", "r2d2"),
        ],
    )
    def test_the_names_first_word_made_to_fit(self, name: str, expected: str) -> None:
        assert handle_prefill(name) == expected

    def test_a_word_with_nothing_that_fits_gives_none(self) -> None:
        assert handle_prefill("李雷 Example") == ""

    def test_no_name_gives_none(self) -> None:
        assert handle_prefill(None) == ""


class TestTokenName:
    def test_the_tokens_name_trimmed(self) -> None:
        assert token_name(_auth(name="  Ben Example ")) == "Ben Example"

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_a_missing_or_blank_name_is_none(self, name: str | None) -> None:
        assert token_name(_auth(name=name)) is None


class TestPeopleService:
    def test_find_is_none_before_the_handle(self, people: PeopleService) -> None:
        assert people.find(_auth()) is None

    def test_find_is_the_callers_row(self, people: PeopleService, person: User) -> None:
        assert people.find(_auth(subject="subject-ada")) is person

    def test_a_first_sign_in_writes_nothing(
        self, people: PeopleService, session: Session
    ) -> None:
        assert people.record_sign_in(_auth()) is None
        assert _people(session) == 0

    def test_a_later_sign_in_refreshes_the_row(
        self, people: PeopleService, person: User
    ) -> None:
        before = datetime.now(UTC)

        signed_in = people.record_sign_in(
            _auth(subject="subject-ada", name="Ada Lovelace", email="ada@example.org")
        )

        assert signed_in is person
        assert (person.handle, person.name, person.email) == (
            "ada",
            "Ada Lovelace",
            "ada@example.org",
        )
        assert person.last_seen_at is not None
        assert person.last_seen_at >= before

    @pytest.mark.parametrize("name", [None, "  "])
    def test_a_sign_in_without_a_name_keeps_the_records(
        self, people: PeopleService, person: User, name: str | None
    ) -> None:
        people.record_sign_in(_auth(subject="subject-ada", name=name))

        assert person.name == "Ada Example"

    def test_a_sign_in_without_an_email_clears_it(
        self, people: PeopleService, person: User
    ) -> None:
        person.email = "ada@example.com"

        people.record_sign_in(_auth(subject="subject-ada", email=None))

        assert person.email is None

    def test_choosing_the_handle_puts_the_person_on_the_record(
        self, people: PeopleService, session: Session
    ) -> None:
        before = datetime.now(UTC)

        person = people.choose_handle(_auth(), "ben")

        session.expire(person)
        assert person.kind_code == UserKind.PERSON
        assert (person.subject, person.handle, person.name, person.email) == (
            "subject-ben",
            "ben",
            "Ben Example",
            "ben@example.com",
        )
        assert person.avatar_slot == 1
        assert person.last_seen_at is not None
        assert person.last_seen_at >= before
        assert person.created_at is not None

    @pytest.mark.parametrize("name", [None, " "])
    def test_without_a_name_the_handle_is_the_name(
        self, people: PeopleService, name: str | None
    ) -> None:
        person = people.choose_handle(_auth(name=name, email=None), "ben")

        assert (person.name, person.email) == ("ben", None)

    def test_the_lowest_free_slot_is_taken(
        self, people: PeopleService, session: Session
    ) -> None:
        _add_person(session, "ada", 1)
        _add_person(session, "cleo", 3)

        assert people.choose_handle(_auth(), "ben").avatar_slot == 2
        assert (
            people.choose_handle(_auth(subject="subject-dan"), "dan").avatar_slot == 4
        )

    @pytest.mark.parametrize(
        "handle", ["Ada", "ada lovelace", "ada_l", "ádá", "ada\n", "ada.example", ""]
    )
    def test_a_handle_out_of_the_pattern_is_refused(
        self, people: PeopleService, session: Session, handle: str
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            people.choose_handle(_auth(), handle)

        assert raised.value.message == (
            f"Cannot choose the handle {handle!r} because a handle holds only "
            "lower-case letters, digits and hyphens"
        )
        assert _people(session) == 0

    @pytest.mark.parametrize("handle", ["a", "ada-2", "9-lives", "-"])
    def test_letters_digits_and_hyphens_are_taken(
        self, people: PeopleService, handle: str
    ) -> None:
        assert people.choose_handle(_auth(), handle).handle == handle

    def test_agent_is_refused_as_pilots(
        self, people: PeopleService, session: Session
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            people.choose_handle(_auth(), "agent")

        assert (
            raised.value.message
            == "Cannot choose the handle 'agent' because it is Pilot's"
        )
        assert _people(session) == 0

    def test_another_persons_handle_is_refused(
        self, people: PeopleService, person: User, session: Session
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            people.choose_handle(_auth(), "ada")

        assert raised.value.message == (
            "Cannot choose the handle 'ada' because another person has it"
        )
        assert _people(session) == 1

    def test_the_handle_never_changes(
        self, people: PeopleService, person: User, session: Session
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            people.choose_handle(_auth(subject="subject-ada"), "ada-lovelace")

        assert raised.value.message == (
            "Cannot choose the handle 'ada-lovelace' because your handle is 'ada' "
            "already, and a handle never changes"
        )
        assert person.handle == "ada"
        assert _people(session) == 1

    def test_require_person_is_the_callers_row(
        self, people: PeopleService, person: User
    ) -> None:
        assert people.require_person(_auth(subject="subject-ada"), "join it") is person

    def test_require_person_refuses_one_without_a_handle(
        self, people: PeopleService
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            people.require_person(_auth(), "join the project")

        assert raised.value.message == (
            "Cannot join the project because you have not chosen your handle yet"
        )


def _choose(container: ServiceContainer, subject: str, handle: str) -> int | None:
    with scoped_session(container):
        return (
            container.people_service().choose_handle(_auth(subject), handle).avatar_slot
        )


def _await_a_lock_wait(engine: Engine) -> None:
    """Return once a session of the database waits on a lock."""
    with engine.connect() as watcher:
        for _ in range(200):
            waiting = watcher.execute(
                sql(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar()
            if waiting:
                return
            time.sleep(0.05)
    raise AssertionError("The second chooser never waited for the first")


class TestChoosersAtOnce:
    """Two people choosing at once: the second waits for the first's commit,
    then reads what it wrote."""

    @pytest.fixture
    def engine(self, committed_app: Flask) -> Engine:
        with committed_app.app_context():
            return db.engine

    def test_they_never_share_a_slot(
        self, committed_app: Flask, engine: Engine
    ) -> None:
        container = committed_app.container

        with ThreadPoolExecutor(max_workers=1) as pool:
            with scoped_session(container):
                first = container.people_service().choose_handle(
                    _auth("subject-ada"), "ada"
                )
                assert first.avatar_slot == 1
                second = pool.submit(_choose, container, "subject-ben", "ben")
                _await_a_lock_wait(engine)

            assert second.result(timeout=10) == 2

    def test_they_never_share_a_handle(
        self, committed_app: Flask, engine: Engine
    ) -> None:
        container = committed_app.container

        with ThreadPoolExecutor(max_workers=1) as pool:
            with scoped_session(container):
                container.people_service().choose_handle(_auth("subject-ada"), "ada")
                second = pool.submit(_choose, container, "subject-ben", "ada")
                _await_a_lock_wait(engine)

            with pytest.raises(InvalidOperationException) as raised:
                second.result(timeout=10)

        assert raised.value.cause == "another person has it"
