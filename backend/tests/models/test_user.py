"""User: Pilot's row, written by the revisions, and what a row must hold;
Alarm, what Pilot last sent a person for a Condition."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Alarm, User
from app.models.reference import Condition, UserKind
from tests.support.database import violated_constraint

_SENT = datetime(2026, 10, 12, 14, 2, tzinfo=UTC)


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


class TestAlarm:
    def test_an_alarm_is_written(self, session: Session, person: User) -> None:
        alarm = Alarm(
            user_id=person.id,
            condition_code=Condition.OUTAGE,
            standing=True,
            sent_at=_SENT,
        )
        session.add(alarm)
        session.flush()
        session.refresh(alarm)

        assert alarm.id is not None
        assert alarm.user_kind_code == UserKind.PERSON
        assert alarm.owed_at is None

    def test_a_person_holds_one_per_condition_of_each(
        self, session: Session, person: User
    ) -> None:
        session.add_all(
            Alarm(
                user_id=person.id,
                condition_code=condition,
                standing=True,
                sent_at=_SENT,
            )
            for condition in Condition
        )
        session.flush()

        assert set(
            session.scalars(
                select(Alarm.condition_code).where(Alarm.user_id == person.id)
            )
        ) == set(Condition)

    def test_a_second_alarm_for_a_condition_is_refused(
        self, session: Session, person: User
    ) -> None:
        session.add_all(
            Alarm(
                user_id=person.id,
                condition_code=Condition.WEEK_HALT,
                standing=False,
                sent_at=_SENT,
            )
            for _ in range(2)
        )

        assert violated_constraint(session) == "alarms_user_id_condition_code_key"

    def test_pilot_holds_none(self, session: Session) -> None:
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        session.add(
            Alarm(
                user_id=pilot.id,
                condition_code=Condition.OUTAGE,
                standing=True,
                sent_at=_SENT,
            )
        )

        assert violated_constraint(session) == "alarms_user_id_user_kind_code_fkey"

    def test_an_alarm_names_a_person_s_kind(
        self, session: Session, person: User
    ) -> None:
        session.add(
            Alarm(
                user_id=person.id,
                user_kind_code=UserKind.AGENT,
                condition_code=Condition.OUTAGE,
                standing=False,
            )
        )

        assert violated_constraint(session) == "ck_alarms_person"

    def test_a_standing_alarm_was_sent(self, session: Session, person: User) -> None:
        session.add(
            Alarm(user_id=person.id, condition_code=Condition.OUTAGE, standing=True)
        )

        assert violated_constraint(session) == "ck_alarms_standing_sent"

    def test_a_first_submit_that_failed_is_owed(
        self, session: Session, person: User
    ) -> None:
        alarm = Alarm(
            user_id=person.id,
            condition_code=Condition.FIVE_HOUR_HALT,
            standing=False,
            owed_at=_SENT,
        )
        session.add(alarm)
        session.flush()

        assert (alarm.standing, alarm.sent_at, alarm.owed_at) == (False, None, _SENT)
