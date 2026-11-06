"""The phone's notifications only for what waits on a person.

Slice 035, P3 (DB decision 70): a Project Member's notification stands while
its text is set, at one priority, so Notification Priority goes with its
column; a person's alarms are one notification, its last send on the User
(`alarm_text`, `alarm_sent_at`, `alarm_owed_at`), so Alarm goes, and with it
Condition and the key of User's that its rows referenced. A notification
standing at the upgrade keeps its text and `url`, which the reconcile compares
with what the member should see. What the alarms left standing on a phone,
under each condition's code, nothing dismisses.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_PRIORITY = ("min", "default", "high")
CONDITION = ("outage", "store_update", "week_halt", "five_hour_halt")

_USERS_AGENT = (
    "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
    " AND notification_token IS NULL AND avatar_slot IS NULL"
    " AND alarm_text IS NULL AND alarm_sent_at IS NULL"
    " AND alarm_owed_at IS NULL)"
)
_USERS_AGENT_0027 = (
    "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
    " AND notification_token IS NULL AND avatar_slot IS NULL)"
)


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint("ck_project_members_notification_sent", "project_members")
    op.drop_constraint("ck_project_members_notification", "project_members")
    op.drop_column("project_members", "notification_priority_code")
    op.create_check_constraint(
        "ck_project_members_notification",
        "project_members",
        "(notification_text IS NULL) = (notification_url IS NULL)",
    )
    op.create_check_constraint(
        "ck_project_members_notification_sent",
        "project_members",
        "notification_text IS NULL OR notification_sent_at IS NOT NULL",
    )

    op.drop_index("ix_alarms_owed_at", table_name="alarms")
    op.drop_table("alarms")
    op.drop_constraint("users_id_kind_code_key", "users")
    bind = op.get_bind()
    postgresql.ENUM(name="condition").drop(bind)
    postgresql.ENUM(name="notification_priority").drop(bind)

    op.add_column("users", sa.Column("alarm_text", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("alarm_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("alarm_owed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_users_agent", "users")
    op.create_check_constraint("ck_users_agent", "users", _USERS_AGENT)
    op.create_check_constraint(
        "ck_users_alarm_sent",
        "users",
        "alarm_text IS NULL OR alarm_sent_at IS NOT NULL",
    )
    op.create_index(
        "ix_users_alarm_owed_at",
        "users",
        ["alarm_owed_at"],
        postgresql_where=sa.text("alarm_owed_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema: a standing notification at `high`, the one
    priority a submit has gone at since; the alarms table empty, a person's
    alarm notification standing until the revision before submits each
    condition's own."""
    op.drop_index("ix_users_alarm_owed_at", table_name="users")
    op.drop_constraint("ck_users_alarm_sent", "users")
    op.drop_constraint("ck_users_agent", "users")
    op.create_check_constraint("ck_users_agent", "users", _USERS_AGENT_0027)
    for column in ("alarm_owed_at", "alarm_sent_at", "alarm_text"):
        op.drop_column("users", column)

    bind = op.get_bind()
    postgresql.ENUM(*NOTIFICATION_PRIORITY, name="notification_priority").create(bind)
    postgresql.ENUM(*CONDITION, name="condition").create(bind)
    op.create_unique_constraint("users_id_kind_code_key", "users", ["id", "kind_code"])
    op.create_table(
        "alarms",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_kind_code",
            postgresql.ENUM(name="user_kind", create_type=False),
            server_default="person",
            nullable=False,
        ),
        sa.Column(
            "condition_code",
            postgresql.ENUM(name="condition", create_type=False),
            nullable=False,
        ),
        sa.Column("standing", sa.Boolean(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("user_kind_code = 'person'", name="ck_alarms_person"),
        sa.CheckConstraint(
            "NOT standing OR sent_at IS NOT NULL", name="ck_alarms_standing_sent"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "user_kind_code"], ["users.id", "users.kind_code"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "condition_code"),
    )
    op.create_index(
        "ix_alarms_owed_at",
        "alarms",
        ["owed_at"],
        postgresql_where=sa.text("owed_at IS NOT NULL"),
    )

    op.drop_constraint("ck_project_members_notification_sent", "project_members")
    op.drop_constraint("ck_project_members_notification", "project_members")
    op.add_column(
        "project_members",
        sa.Column(
            "notification_priority_code",
            postgresql.ENUM(name="notification_priority", create_type=False),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE project_members SET notification_priority_code = 'high'"
        " WHERE notification_text IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_project_members_notification",
        "project_members",
        "(notification_priority_code IS NULL) = (notification_text IS NULL)"
        " AND (notification_priority_code IS NULL) = (notification_url IS NULL)",
    )
    op.create_check_constraint(
        "ck_project_members_notification_sent",
        "project_members",
        "notification_priority_code IS NULL OR notification_sent_at IS NOT NULL",
    )
