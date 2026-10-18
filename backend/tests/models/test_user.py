"""User: Pilot's row, written by the revisions, and what a row must hold."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.reference import UserKind
from tests.support.database import violated_constraint


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
        assert pilot.notification_token is None
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

    def test_a_handle_is_lower_case_letters_digits_and_hyphens(
        self, session: Session
    ) -> None:
        session.add(_person(handle="Grace_E"))

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
