"""User: Pilot's row, written by the revisions, and what a row must hold,
when a person was last shown the conditions that alarm among it, and a
service user's (DB 338)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import User
from app.models.reference import UserKind
from tests.support.database import violated_constraint

_SEEN = datetime(2026, 10, 12, 14, 2, tzinfo=UTC)


def _person(**overrides: object) -> User:
    values: dict[str, object] = {
        "kind_code": UserKind.PERSON,
        "subject": "subject-grace",
        "handle": "grace",
        "name": "Grace Example",
        "avatar_slot": 2,
    }
    values.update(overrides)
    return User(**values)


class TestUser:
    def test_the_revisions_write_pilot(self, session: Session) -> None:
        agents = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).all()

        assert len(agents) == 1
        pilot = agents[0]
        assert (pilot.handle, pilot.name) == ("agent", "Pilot")
        assert pilot.subject is None
        assert pilot.email is None
        assert pilot.avatar_slot is None
        assert pilot.created_at is not None

    def test_a_person_is_written(self, session: Session) -> None:
        person = _person(email="grace@example.com")
        session.add(person)
        session.flush()
        session.refresh(person)

        assert person.id is not None
        assert person.created_at is not None
        assert person.last_seen_at is None
        assert person.alarms is True

    def test_the_database_turns_the_alarms_on(self, session: Session) -> None:
        """A row the revisions or raw SQL write has the switch on (F142.1)."""
        session.execute(
            text(
                "INSERT INTO users (id, kind_code, subject, handle, name, avatar_slot)"
                " VALUES (gen_random_uuid(), 'person', 'subject-hal', 'hal',"
                " 'Hal Example', 3)"
            )
        )

        alarms = session.scalars(select(User.alarms).where(User.handle == "hal")).one()
        assert alarms is True

    def test_a_second_agent_is_refused(self, session: Session) -> None:
        session.add(User(kind_code=UserKind.AGENT, handle="pilot-two", name="Pilot"))

        assert violated_constraint(session) == "ck_users_agent_handle"

    def test_pilot_has_no_sign_in_and_no_palette_slot(self, session: Session) -> None:
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        pilot.email = "pilot@example.com"

        assert violated_constraint(session) == "ck_users_agent"

    def test_no_person_takes_the_agent_handle(self, session: Session) -> None:
        session.add(_person(handle="agent"))

        assert violated_constraint(session) == "ck_users_agent_handle"

    # Each breaks one rule: a capital, then an underscore.
    @pytest.mark.parametrize("handle", ["Grace-e", "grace_e"])
    def test_a_handle_is_lower_case_letters_digits_and_hyphens(
        self, session: Session, handle: str
    ) -> None:
        session.add(_person(handle=handle))

        assert violated_constraint(session) == "ck_users_handle"

    def test_a_handle_is_unique(self, session: Session, person: User) -> None:
        session.add(_person(handle=person.handle))

        assert violated_constraint(session) == "users_handle_key"

    def test_a_subject_is_unique(self, session: Session, person: User) -> None:
        session.add(_person(subject=person.subject))

        assert violated_constraint(session) == "users_subject_key"

    def test_an_avatar_slot_is_unique(self, session: Session, person: User) -> None:
        session.add(_person(avatar_slot=person.avatar_slot))

        assert violated_constraint(session) == "users_avatar_slot_key"

    def test_a_person_signs_in_with_a_subject(self, session: Session) -> None:
        session.add(_person(subject=None))

        assert violated_constraint(session) == "ck_users_person"

    def test_a_person_holds_an_avatar_slot(self, session: Session) -> None:
        session.add(_person(avatar_slot=None))

        assert violated_constraint(session) == "ck_users_person"


class TestUserAlarm:
    def test_a_person_has_been_shown_no_condition_at_first(
        self, session: Session, person: User
    ) -> None:
        session.refresh(person)

        assert person.alarm_seen_at is None

    def test_when_they_were_last_shown_the_conditions_is_written(
        self, session: Session, person: User
    ) -> None:
        person.alarm_seen_at = _SEEN
        session.flush()
        session.refresh(person)

        assert person.alarm_seen_at == _SEEN

    def test_pilot_is_shown_none(self, session: Session) -> None:
        """Pilot has no alarm (DB 238)."""
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        pilot.alarm_seen_at = _SEEN

        assert violated_constraint(session) == "ck_users_agent"


def _service_user(**overrides: object) -> User:
    values: dict[str, object] = {
        "kind_code": UserKind.SERVICE,
        "subject": "subject-fleet",
        "handle": "fleet",
        "name": "KubeCoder fleet",
    }
    values.update(overrides)
    return User(**values)


class TestServiceUser:
    def test_the_revisions_write_none(self, session: Session) -> None:
        assert (
            session.scalars(
                select(User).where(User.kind_code == UserKind.SERVICE)
            ).all()
            == []
        )

    def test_a_service_user_is_written(self, session: Session) -> None:
        service_user = _service_user()
        session.add(service_user)
        session.flush()
        session.refresh(service_user)

        assert service_user.id is not None
        assert service_user.created_at is not None
        assert (
            service_user.email,
            service_user.avatar_slot,
            service_user.alarm_seen_at,
            service_user.last_seen_at,
        ) == (None, None, None, None)

    @pytest.mark.parametrize(
        "broken",
        [
            pytest.param({"subject": None}, id="no subject"),
            pytest.param({"email": "fleet@example.com"}, id="an email"),
            pytest.param({"avatar_slot": 4}, id="a palette slot"),
            pytest.param({"alarm_seen_at": _SEEN}, id="a showing of the alarms"),
        ],
    )
    def test_it_holds_its_clients_subject_and_nothing_of_a_person(
        self, session: Session, broken: dict[str, object]
    ) -> None:
        session.add(_service_user(**broken))

        assert violated_constraint(session) == "ck_users_service"

    def test_it_never_takes_the_agent_handle(self, session: Session) -> None:
        session.add(_service_user(handle="agent"))

        assert violated_constraint(session) == "ck_users_agent_handle"

    def test_its_subject_is_no_other_users(
        self, session: Session, person: User
    ) -> None:
        session.add(_service_user(subject=person.subject))

        assert violated_constraint(session) == "users_subject_key"
