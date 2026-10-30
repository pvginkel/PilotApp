"""The standing notification's facts and the alarms.

Slice 029, P1: Project Member's notification columns, classified by
Notification Priority (DB decision 51); User's `alarms` switch and Alarm, one
per User and Condition (DB decision 55, Condition's values decision 66); the
owed columns' indexes for the retries (DB §7.6). Pilot holds no Alarm (DB
assertion 238): an Alarm's key carries its User's kind.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_PRIORITY = ("min", "default", "high")
CONDITION = ("outage", "week_halt", "five_hour_halt")


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    postgresql.ENUM(*NOTIFICATION_PRIORITY, name="notification_priority").create(bind)
    postgresql.ENUM(*CONDITION, name="condition").create(bind)

    op.add_column(
        "users",
        sa.Column("alarms", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_unique_constraint(None, "users", ["id", "kind_code"])

    op.add_column(
        "project_members",
        sa.Column(
            "notification_priority_code",
            postgresql.ENUM(name="notification_priority", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "project_members", sa.Column("notification_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "project_members", sa.Column("notification_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "project_members",
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_members",
        sa.Column("notification_owed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_project_members_notification_owed_at",
        "project_members",
        ["notification_owed_at"],
        postgresql_where=sa.text("notification_owed_at IS NOT NULL"),
    )

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


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_alarms_owed_at", table_name="alarms")
    op.drop_table("alarms")
    op.drop_index(
        "ix_project_members_notification_owed_at", table_name="project_members"
    )
    op.drop_constraint("ck_project_members_notification_sent", "project_members")
    op.drop_constraint("ck_project_members_notification", "project_members")
    for column in (
        "notification_owed_at",
        "notification_sent_at",
        "notification_url",
        "notification_text",
        "notification_priority_code",
    ):
        op.drop_column("project_members", column)
    op.drop_constraint("users_id_kind_code_key", "users")
    op.drop_column("users", "alarms")
    bind = op.get_bind()
    postgresql.ENUM(name="condition").drop(bind)
    postgresql.ENUM(name="notification_priority").drop(bind)
