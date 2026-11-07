"""Revision 0029: web push in place of the bridge (DB decision 74): Push
Subscription and App Page added, a member's Item Sightings in place of what
their membership's notification last sent, and a person's alarms on when they
were last shown the conditions in place of what their alarm notification last
sent, over rows as revision 0028 leaves them: the revision's downgrade builds
0028's schema in the test's transaction."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AppPage,
    Item,
    ItemSighting,
    Project,
    ProjectMember,
    PushSubscription,
    User,
)
from app.models.reference import UserKind
from tests.support.database import violated_constraint

_BACKEND_DIR = Path(__file__).resolve().parents[2]
PHONE = "https://push.example.com/send/phone-of-ada"
_SENT = datetime(2026, 11, 6, 9, 30, tzinfo=UTC)
_ALARM_COLUMNS = {"alarm_text", "alarm_sent_at", "alarm_owed_at"}
_NOTIFICATION_COLUMNS = {
    "notification_text",
    "notification_url",
    "notification_owed_at",
}


def _run(db: Session, step: str) -> None:
    """Revision 0029's `step`, `upgrade` or `downgrade`, on the test's
    transaction; what the session holds is read again after an upgrade."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0029")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    if step == "upgrade":
        db.expire_all()


def _subscription(person: User, endpoint: str = PHONE) -> PushSubscription:
    return PushSubscription(user_id=person.id, endpoint=endpoint, p256dh="p", auth="a")


class TestWebPush:
    def test_the_upgrade_adds_no_subscription_for_any_person(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        assert not inspect(session.connection()).has_table("push_subscriptions")

        _run(session, "upgrade")

        assert session.scalars(select(PushSubscription)).all() == []
        session.add(_subscription(person))
        session.flush()
        row = session.scalars(select(PushSubscription)).one()
        assert (row.user_id, row.endpoint, row.created_at is not None) == (
            person.id,
            PHONE,
            True,
        )

    def test_an_endpoint_is_one_subscriptions(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        session.add(_subscription(person))
        session.flush()
        session.add(_subscription(person))

        assert violated_constraint(session) == "push_subscriptions_endpoint_key"

    def test_the_subscriptions_are_read_per_person(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")

        indexes = inspect(session.connection()).get_indexes("push_subscriptions")

        assert {
            "name": "ix_push_subscriptions_user_id",
            "column_names": ["user_id"],
        } in [
            {"name": index["name"], "column_names": index["column_names"]}
            for index in indexes
        ]

    def test_the_upgrade_adds_no_page_for_any_person(
        self, session: Session, person: User, project: Project
    ) -> None:
        _run(session, "downgrade")
        assert not inspect(session.connection()).has_table("app_pages")

        _run(session, "upgrade")

        assert session.scalars(select(AppPage)).all() == []
        session.add(
            AppPage(user_id=person.id, project_id=project.id, beat_at=datetime.now(UTC))
        )
        session.add(AppPage(user_id=person.id, beat_at=datetime.now(UTC)))
        session.flush()
        assert sorted(
            str(page.project_id) for page in session.scalars(select(AppPage))
        ) == sorted([str(project.id), "None"])

    def test_a_page_is_one_persons_and_shows_a_project_that_is(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        session.add(
            AppPage(
                user_id=person.id, project_id=uuid.uuid4(), beat_at=datetime.now(UTC)
            )
        )

        assert violated_constraint(session) == "app_pages_project_id_fkey"

    def test_the_pages_are_read_per_person_and_by_their_beat(
        self, session: Session, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")

        indexes = inspect(session.connection()).get_indexes("app_pages")

        assert sorted(
            (index["name"], tuple(index["column_names"])) for index in indexes
        ) == [
            ("ix_app_pages_beat_at", ("beat_at",)),
            ("ix_app_pages_user_id", ("user_id",)),
        ]

    def test_the_downgrade_drops_the_subscriptions_and_the_pages(
        self, session: Session, person: User
    ) -> None:
        session.add(_subscription(person))
        session.add(AppPage(user_id=person.id, beat_at=datetime.now(UTC)))
        session.flush()

        _run(session, "downgrade")

        assert not inspect(session.connection()).has_table("push_subscriptions")
        assert not inspect(session.connection()).has_table("app_pages")
        assert (
            session.connection()
            .exec_driver_sql("SELECT count(*) FROM users WHERE id = %s", (person.id,))
            .scalar()
            == 1
        )


def _refused(db: Session, statement: str, params: dict[str, object]) -> str:
    """The name of the constraint `statement` violates, run as SQL."""
    with pytest.raises(IntegrityError) as raised:
        db.execute(text(statement), params)
    return raised.value.orig.diag.constraint_name


def _user_columns(db: Session) -> set[str]:
    return {column["name"] for column in inspect(db.connection()).get_columns("users")}


class TestAlarmSeenAt:
    def test_the_upgrade_drops_what_the_alarm_last_sent_and_shows_nobody_anything(
        self, session: Session, person: User
    ) -> None:
        """What a submit left standing on a phone, nothing dismisses."""
        person_id = person.id
        _run(session, "downgrade")
        session.execute(
            text(
                "UPDATE users SET alarm_text = 'The week''s usage halt',"
                " alarm_sent_at = :sent, alarm_owed_at = :sent WHERE id = :id"
            ),
            {"sent": _SENT, "id": person_id},
        )

        _run(session, "upgrade")

        assert not _ALARM_COLUMNS & _user_columns(session)
        assert session.get_one(User, person_id).alarm_seen_at is None
        assert "ix_users_alarm_owed_at" not in {
            index["name"]
            for index in inspect(session.connection()).get_indexes("users")
        }

    def test_when_a_person_was_last_shown_the_conditions_is_written_after(
        self, session: Session, person: User
    ) -> None:
        """No check reads what the alarm notification last sent any more."""
        _run(session, "downgrade")
        _run(session, "upgrade")
        person.alarm_seen_at = _SENT
        session.flush()
        session.refresh(person)

        assert person.alarm_seen_at == _SENT

    def test_pilot_is_shown_none_after(self, session: Session) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        pilot.alarm_seen_at = _SENT

        assert violated_constraint(session) == "ck_users_agent"

    def test_the_downgrade_leaves_no_alarm_standing_and_its_checks_back(
        self, session: Session, person: User
    ) -> None:
        person.alarm_seen_at = _SENT
        session.flush()
        person_id = person.id

        _run(session, "downgrade")

        columns = _user_columns(session)
        assert _ALARM_COLUMNS <= columns
        assert "alarm_seen_at" not in columns
        assert session.execute(
            text(
                "SELECT alarm_text, alarm_sent_at, alarm_owed_at FROM users"
                " WHERE id = :id"
            ),
            {"id": person_id},
        ).one() == (None, None, None)
        assert "ix_users_alarm_owed_at" in {
            index["name"]
            for index in inspect(session.connection()).get_indexes("users")
        }
        assert (
            _refused(
                session,
                "UPDATE users SET alarm_text = 'The week''s usage halt' WHERE id = :id",
                {"id": person_id},
            )
            == "ck_users_alarm_sent"
        )

    def test_after_the_downgrade_pilot_is_sent_none(self, session: Session) -> None:
        _run(session, "downgrade")

        constraint = _refused(
            session,
            "UPDATE users SET alarm_sent_at = :sent WHERE kind_code = 'agent'",
            {"sent": _SENT},
        )

        assert constraint == "ck_users_agent"


def _member_columns(db: Session) -> set[str]:
    return {
        column["name"]
        for column in inspect(db.connection()).get_columns("project_members")
    }


def _member_checks(db: Session) -> set[str]:
    return {
        check["name"]
        for check in inspect(db.connection()).get_check_constraints("project_members")
    }


def _member_indexes(db: Session) -> set[str]:
    return {
        index["name"]
        for index in inspect(db.connection()).get_indexes("project_members")
    }


def _member(db: Session, project: Project, person: User) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id,
        user_id=person.id,
        joined_at=_SENT,
        notification_sent_at=_SENT,
    )
    db.add(member)
    db.flush()
    return member


class TestItemSighting:
    def test_the_upgrade_drops_what_each_membership_last_sent_and_shows_nothing(
        self, session: Session, project: Project, person: User
    ) -> None:
        """What a submit left standing on a phone, nothing dismisses; when it
        went out stays, for the two seconds."""
        project_id, person_id = project.id, person.id
        _run(session, "downgrade")
        member_id = session.scalar(
            text(
                "INSERT INTO project_members (project_id, user_id, joined_at,"
                " notification_text, notification_url, notification_sent_at,"
                " notification_owed_at)"
                " VALUES (:project, :person, :sent, 'Which tent?', :url, :sent,"
                " :sent) RETURNING id"
            ),
            {
                "project": project_id,
                "person": person_id,
                "sent": _SENT,
                "url": f"https://pilot.example.com/projects/{project_id}",
            },
        )

        _run(session, "upgrade")

        assert not _NOTIFICATION_COLUMNS & _member_columns(session)
        assert not {
            "ck_project_members_notification",
            "ck_project_members_notification_sent",
        } & _member_checks(session)
        assert "ix_project_members_notification_owed_at" not in _member_indexes(session)
        assert session.get_one(ProjectMember, member_id).notification_sent_at == _SENT
        assert session.scalars(select(ItemSighting)).all() == []

    def test_a_member_is_shown_an_item_after(
        self, session: Session, project: Project, person: User, item: Item
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=item.id))
        session.flush()

        assert session.execute(
            select(ItemSighting.member_id, ItemSighting.item_id)
        ).all() == [(member.id, item.id)]

    def test_a_sighting_is_of_an_item_that_is(
        self, session: Session, project: Project, person: User
    ) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=uuid.uuid4()))

        assert violated_constraint(session) == "item_sightings_item_id_fkey"

    def test_the_downgrade_drops_the_sightings_and_leaves_no_notification_standing(
        self, session: Session, project: Project, person: User, item: Item
    ) -> None:
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=item.id))
        session.flush()
        member_id = member.id

        _run(session, "downgrade")

        assert not inspect(session.connection()).has_table("item_sightings")
        assert _NOTIFICATION_COLUMNS <= _member_columns(session)
        assert session.execute(
            text(
                "SELECT notification_text, notification_url, notification_sent_at,"
                " notification_owed_at FROM project_members WHERE id = :id"
            ),
            {"id": member_id},
        ).one() == (None, None, _SENT, None)
        assert "ix_project_members_notification_owed_at" in _member_indexes(session)
        assert (
            _refused(
                session,
                "UPDATE project_members SET notification_text = 'Which tent?'"
                " WHERE id = :id",
                {"id": member_id},
            )
            == "ck_project_members_notification"
        )

    def test_after_the_downgrade_a_standing_notification_was_sent(
        self, session: Session, project: Project, person: User
    ) -> None:
        project_id, person_id = project.id, person.id
        _run(session, "downgrade")

        constraint = _refused(
            session,
            "INSERT INTO project_members (project_id, user_id, joined_at,"
            " notification_text, notification_url)"
            " VALUES (:project, :person, :sent, 'Which tent?', :url)",
            {
                "project": project_id,
                "person": person_id,
                "sent": _SENT,
                "url": f"https://pilot.example.com/projects/{project_id}",
            },
        )

        assert constraint == "ck_project_members_notification_sent"
