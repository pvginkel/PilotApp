"""Web push in place of the notification bridge.

Slice 038 (DB decision 74): Push Subscription, one browser's registration with
its push service, through which a person's notifications are pushed to it;
App Page, a page of Pilot its person is active in, whose beat says they are
online; Item Sighting, a member's having been shown an item that waits on
them, none until their first push or page of the project, in place of what
their membership's notification last sent through the bridge; and a person's
alarms on when they were last shown the conditions (`alarm_seen_at`), none
until their first alarm push or going offline, in place of what their alarm
notification last sent. Nothing dismisses what the bridge left standing.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USERS_AGENT = (
    "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
    " AND notification_token IS NULL AND avatar_slot IS NULL"
    " AND alarm_seen_at IS NULL)"
)
_USERS_AGENT_0028 = (
    "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
    " AND notification_token IS NULL AND avatar_slot IS NULL"
    " AND alarm_text IS NULL AND alarm_sent_at IS NULL"
    " AND alarm_owed_at IS NULL)"
)


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table(
        "app_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_pages_user_id", "app_pages", ["user_id"])
    op.create_index("ix_app_pages_beat_at", "app_pages", ["beat_at"])
    op.drop_index("ix_users_alarm_owed_at", table_name="users")
    op.drop_constraint("ck_users_alarm_sent", "users")
    op.drop_constraint("ck_users_agent", "users")
    for column in ("alarm_owed_at", "alarm_sent_at", "alarm_text"):
        op.drop_column("users", column)
    op.add_column(
        "users", sa.Column("alarm_seen_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint("ck_users_agent", "users", _USERS_AGENT)
    op.drop_index(
        "ix_project_members_notification_owed_at", table_name="project_members"
    )
    op.drop_constraint("ck_project_members_notification_sent", "project_members")
    op.drop_constraint("ck_project_members_notification", "project_members")
    for column in ("notification_owed_at", "notification_url", "notification_text"):
        op.drop_column("project_members", column)
    op.create_table(
        "item_sightings",
        sa.Column("member_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["member_id"], ["project_members.id"]),
        sa.PrimaryKeyConstraint("member_id", "item_id"),
    )


def downgrade() -> None:
    """Downgrade database schema: what each member was shown dropped, their
    notification standing nowhere, and when each person was last shown the
    conditions dropped, their alarm notification standing nowhere, which
    revision 0028's reconcile submits through their token while something
    waits on them or a condition is due; the browsers' subscriptions and the
    pages dropped, which its notifications, through the bridge, never read."""
    op.drop_table("item_sightings")
    op.add_column(
        "project_members", sa.Column("notification_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "project_members", sa.Column("notification_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "project_members",
        sa.Column("notification_owed_at", sa.DateTime(timezone=True), nullable=True),
    )
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
    op.create_index(
        "ix_project_members_notification_owed_at",
        "project_members",
        ["notification_owed_at"],
        postgresql_where=sa.text("notification_owed_at IS NOT NULL"),
    )
    op.drop_constraint("ck_users_agent", "users")
    op.drop_column("users", "alarm_seen_at")
    op.add_column("users", sa.Column("alarm_text", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("alarm_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("alarm_owed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint("ck_users_agent", "users", _USERS_AGENT_0028)
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
    op.drop_index("ix_app_pages_beat_at", table_name="app_pages")
    op.drop_index("ix_app_pages_user_id", table_name="app_pages")
    op.drop_table("app_pages")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
