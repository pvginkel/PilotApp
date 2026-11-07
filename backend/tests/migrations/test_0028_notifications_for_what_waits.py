"""Revision 0028: a membership's notification standing while its text is set,
its priority dropped, and a person's alarms one notification on the User, the
alarms table dropped (DB decision 70), over rows as revision 0027 leaves them:
revision 0029's downgrade, then this one's, build 0027's schema in the test's
transaction."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, User
from tests.support.database import violated_constraint

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SENT = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _at_0028(session: Session, person: User, project: Project) -> None:
    """The schema as revision 0028 leaves it, the person and the project
    written first: 0029 taken down, whose downgrade puts back what 0028
    added. No User is read through the model after, whose columns are the
    head's."""
    _run(session, "downgrade", "0029")


def _run(db: Session, step: str, number: str = "0028") -> None:
    """Revision `number`'s `step`, `upgrade` or `downgrade`, on the test's
    transaction; what the session holds is read again after an upgrade, and
    is not to be read after a downgrade, whose columns the models lack."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision(number)
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    if step == "upgrade":
        db.expire_all()


def _types(db: Session) -> set[str]:
    return set(
        db.scalars(
            text(
                "SELECT typname FROM pg_type"
                " WHERE typname IN ('notification_priority', 'condition')"
            )
        )
    )


def _joined(
    db: Session,
    project_id: uuid.UUID,
    person_id: uuid.UUID,
    priority: str | None,
    message: str | None,
    *,
    owed: bool = False,
) -> int:
    """A membership as 0027 records it: at `priority` with `message` while
    one stands."""
    member_id: int = db.scalar(
        text(
            "INSERT INTO project_members (project_id, user_id, joined_at,"
            " notification_priority_code, notification_text, notification_url,"
            " notification_sent_at, notification_owed_at)"
            " VALUES (:project, :person, :sent,"
            " CAST(:priority AS notification_priority), :text, :url, :sent, :owed)"
            " RETURNING id"
        ),
        {
            "project": project_id,
            "person": person_id,
            "sent": _SENT,
            "priority": priority,
            "text": message,
            "url": None
            if message is None
            else f"https://pilot.example.com/projects/{project_id}",
            "owed": _SENT if owed else None,
        },
    )
    return member_id


def _left(db: Session, member_id: int) -> None:
    db.execute(
        text("UPDATE project_members SET left_at = :at WHERE id = :id"),
        {"at": _SENT, "id": member_id},
    )


class TestNotificationsForWhatWaits:
    def test_a_standing_notification_keeps_its_text_and_url_and_loses_its_priority(
        self, session: Session, project: Project, person: User
    ) -> None:
        ids = project.id, person.id
        _run(session, "downgrade")
        idle = _joined(session, *ids, "min", "Not started")
        _left(session, idle)
        asking = _joined(
            session,
            *ids,
            "default",
            "Not started · Decision waiting: Which tent?",
            owed=True,
        )
        _left(session, asking)
        dismissed = _joined(session, *ids, None, None)

        _run(session, "upgrade")

        rows = {
            member.id: member
            for member in session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == project.id)
            )
        }
        assert (rows[idle].notification_text, rows[idle].notification_owed_at) == (
            "Not started",
            None,
        )
        assert (rows[asking].notification_text, rows[asking].notification_owed_at) == (
            "Not started · Decision waiting: Which tent?",
            _SENT,
        )
        assert rows[asking].notification_url == (
            f"https://pilot.example.com/projects/{project.id}"
        )
        assert (
            rows[dismissed].notification_text,
            rows[dismissed].notification_sent_at,
        ) == (None, _SENT)
        assert "notification_priority_code" not in {
            column["name"]
            for column in inspect(session.connection()).get_columns("project_members")
        }

    def test_the_alarms_go_and_no_person_has_one_standing(
        self, session: Session, person: User
    ) -> None:
        person_id = person.id
        _run(session, "downgrade")
        session.execute(
            text(
                "INSERT INTO alarms (user_id, condition_code, standing, sent_at,"
                " owed_at) VALUES (:person, 'outage', true, :sent, NULL),"
                " (:person, 'store_update', false, NULL, :sent)"
            ),
            {"person": person_id, "sent": _SENT},
        )

        _run(session, "upgrade")

        assert not inspect(session.connection()).has_table("alarms")
        assert _types(session) == set()
        assert session.execute(
            text(
                "SELECT alarm_text, alarm_sent_at, alarm_owed_at FROM users"
                " WHERE id = :id"
            ),
            {"id": person_id},
        ).one() == (None, None, None)

    def test_a_standing_notification_needs_its_text_after(
        self, session: Session, project: Project, person: User
    ) -> None:
        """The checks stand on the text in place of the priority."""
        project_id, person_id = project.id, person.id
        _run(session, "downgrade")
        _run(session, "upgrade")
        session.add(
            ProjectMember(
                project_id=project_id,
                user_id=person_id,
                joined_at=_SENT,
                notification_url=f"https://pilot.example.com/projects/{project_id}",
                notification_sent_at=_SENT,
            )
        )

        assert violated_constraint(session) == "ck_project_members_notification"

    def test_the_downgrade_puts_a_standing_notification_at_high(
        self, session: Session, project: Project, person: User
    ) -> None:
        """And drops what the alarm notification last sent, the alarms table
        empty."""
        member = ProjectMember(
            project_id=project.id,
            user_id=person.id,
            joined_at=_SENT,
            notification_text="Which tent?",
            notification_url=f"https://pilot.example.com/projects/{project.id}",
            notification_sent_at=_SENT,
        )
        session.add(member)
        session.execute(
            text(
                "UPDATE users SET alarm_text = 'The week''s usage halt',"
                " alarm_sent_at = :sent WHERE id = :id"
            ),
            {"sent": _SENT, "id": person.id},
        )
        session.flush()

        _run(session, "downgrade")

        assert session.execute(
            text(
                "SELECT notification_priority_code::text, notification_text"
                " FROM project_members WHERE id = :id"
            ),
            {"id": member.id},
        ).one() == ("high", "Which tent?")
        assert session.scalar(text("SELECT count(*) FROM alarms")) == 0
        assert _types(session) == {"notification_priority", "condition"}
        assert not {"alarm_text", "alarm_sent_at", "alarm_owed_at"} & {
            column["name"]
            for column in inspect(session.connection()).get_columns("users")
        }
