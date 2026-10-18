"""People, projects, sessions and the reference entities.

DB §2.1's User, Project, Project Member, Project Transition, Plan Task and
Plan Note; DB §2.3's Environment and Session; DB §2.4's 23 reference entities,
nineteen enums and four tables with their rows; and Pilot's `agent` User.

Revision ID: 0001
Revises:
Create Date: 2026-10-18

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS: dict[str, tuple[str, ...]] = {
    "user_kind": ("person", "agent"),
    "overrule_kind": ("add_five", "to_the_end"),
    "project_state": ("draft", "open", "finished"),
    "transition_kind": (
        "opened",
        "finished",
        "reopened",
        "archived",
        "brought_back",
        "autopilot_on",
        "autopilot_off",
    ),
    "document_role": ("draft", "handbook"),
    "version_cause": ("born", "registered", "turn", "done"),
    "error_kind": ("parse", "reverted"),
    "block_kind": ("decision", "question", "action"),
    "answer_channel": ("app", "chat", "recommended", "autopilot"),
    "work_trigger": ("setup", "worker_turn_ended", "item_done", "wait_fired"),
    "firing_cause": ("transition", "due", "requested"),
    "sync_outcome": ("pulled", "rebased", "skipped"),
    "attachment_source": ("file", "draft"),
    "session_state": ("starting", "running", "idle", "stopped", "ended", "failed"),
    "line_kind": ("log", "message", "server"),
    "chat_kind": ("definition", "project"),
    "close_cause": ("timeout", "created"),
    "effect_kind": (
        "added",
        "answered",
        "marked",
        "stopped",
        "finished",
        "attached",
        "registered",
    ),
    "task_status": ("pending", "in_progress", "done"),
}

ITEM_KINDS = [
    {"code": "opening", "name": "Opening", "form": "prose", "icon": "message"},
    {"code": "decision", "name": "Decision", "form": "prose", "icon": "ask"},
    {"code": "confirmation", "name": "Confirmation", "form": "prose", "icon": "shield"},
    {"code": "question", "name": "Question", "form": "prose", "icon": "ask"},
    {"code": "action", "name": "Action", "form": "prose", "icon": "hand"},
    {"code": "notice", "name": "Notice", "form": "prose", "icon": "info"},
    {"code": "document", "name": "Document", "form": "prose", "icon": "file"},
    {"code": "review", "name": "Review", "form": "prose", "icon": "book"},
    {"code": "work", "name": "Work", "form": "work", "icon": "terminal"},
    {"code": "card_wait", "name": "Card wait", "form": "wait", "icon": "ticket"},
    {"code": "timed_wait", "name": "Timed wait", "form": "wait", "icon": "hourglass"},
]

DONE_CAUSES = [
    {"code": "answered", "name": "Answered", "undo_offered": True},
    {"code": "marked", "name": "Marked", "undo_offered": True},
    {"code": "settled", "name": "Settled", "undo_offered": True},
    {"code": "turn_ended", "name": "Turn ended", "undo_offered": False},
    {"code": "finished", "name": "Finished", "undo_offered": False},
]

CONFIRMATION_REASONS = [
    {
        "code": "auto-pilot-off",
        "name": "Auto pilot off",
        "asks_under_autopilot": False,
        "description": (
            "A granted act (a push that deploys, a prd apply or promotion, an operator"
            " action Pilot can run), asked only while auto pilot is off."
        ),
    },
    {
        "code": "rider",
        "name": "Rider",
        "asks_under_autopilot": False,
        "description": (
            "A push with riders, other commits going out with it, asked only while"
            " auto pilot is off."
        ),
    },
    {
        "code": "irreversible",
        "name": "Irreversible",
        "asks_under_autopilot": True,
        "description": "An irreversible act, of the kept column: asked under auto pilot too.",
    },
    {
        "code": "product-hold",
        "name": "Product hold",
        "asks_under_autopilot": True,
        "description": "A product hold, of the kept column: asked under auto pilot too.",
    },
    {
        "code": "self-approval",
        "name": "Self-approval",
        "asks_under_autopilot": True,
        "description": "Self-approval, of the kept column: asked under auto pilot too.",
    },
]

SESSION_KINDS = [
    {"code": "chat", "name": "Chat", "surface": "pilot-store", "on_timeline": False},
    {"code": "work", "name": "Work", "surface": "pilot-work", "on_timeline": True},
    {"code": "job", "name": "Job", "surface": "pilot-store", "on_timeline": True},
]


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _timestamp(name: str, *, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created_at() -> sa.Column[datetime]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind)

    _create_reference_tables()
    _create_people_and_projects()
    _create_environments_and_sessions()
    _create_plan()

    # Pilot itself: one row, never a member, never signs in (DB decision 18).
    op.execute(
        "INSERT INTO users (id, kind_code, handle, name)"
        " VALUES (gen_random_uuid(), 'agent', 'agent', 'Pilot')"
    )


def _create_reference_tables() -> None:
    item_kinds = op.create_table(
        "item_kinds",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "form IN ('prose', 'work', 'wait')", name="ck_item_kinds_form"
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    done_causes = op.create_table(
        "done_causes",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("undo_offered", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    confirmation_reasons = op.create_table(
        "confirmation_reasons",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asks_under_autopilot", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    session_kinds = op.create_table(
        "session_kinds",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("on_timeline", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "surface IN ('pilot-store', 'pilot-work')", name="ck_session_kinds_surface"
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.bulk_insert(item_kinds, ITEM_KINDS)
    op.bulk_insert(done_causes, DONE_CAUSES)
    op.bulk_insert(confirmation_reasons, CONFIRMATION_REASONS)
    op.bulk_insert(session_kinds, SESSION_KINDS)


def _create_people_and_projects() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind_code", _enum("user_kind"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("notification_token", sa.Text(), nullable=True),
        sa.Column("avatar_slot", sa.Integer(), nullable=True),
        _created_at(),
        _timestamp("last_seen_at"),
        sa.CheckConstraint("handle ~ '^[a-z0-9-]+$'", name="ck_users_handle"),
        sa.CheckConstraint(
            "(kind_code = 'agent') = (handle = 'agent')", name="ck_users_agent_handle"
        ),
        sa.CheckConstraint(
            "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
            " AND notification_token IS NULL AND avatar_slot IS NULL)",
            name="ck_users_agent",
        ),
        sa.CheckConstraint(
            "kind_code <> 'person' OR (subject IS NOT NULL AND avatar_slot IS NOT NULL)",
            name="ck_users_person",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
        sa.UniqueConstraint("handle"),
        sa.UniqueConstraint("avatar_slot"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "state_code", _enum("project_state"), server_default="draft", nullable=False
        ),
        sa.Column("archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("autopilot", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ticket", sa.Text(), nullable=True),
        sa.Column("repo", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9-]+$' AND slug NOT LIKE 'draft-%'", name="ck_projects_slug"
        ),
        sa.CheckConstraint(
            "(state_code = 'draft') = (slug IS NULL)", name="ck_projects_draft_slug"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "project_members",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _timestamp("joined_at", nullable=False),
        _timestamp("left_at"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_project_members_open",
        "project_members",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )
    op.create_table(
        "project_transitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind_code", _enum("transition_kind"), nullable=False),
        _timestamp("at", nullable=False),
        sa.Column("by_user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_transitions_project_at", "project_transitions", ["project_id", "at"]
    )


def _create_environments_and_sessions() -> None:
    op.create_table(
        "environments",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _timestamp("server_started_at"),
        _timestamp("stop_due_at"),
        sa.Column("exempt", sa.Boolean(), nullable=False),
        sa.Column("last_state", sa.Text(), nullable=True),
        _timestamp("last_seen_at"),
        _timestamp("halt_requested_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_environments_stop_due_at",
        "environments",
        ["stop_due_at"],
        postgresql_where=sa.text("stop_due_at IS NOT NULL"),
    )
    op.create_index(
        "ix_environments_halt_requested_at",
        "environments",
        ["halt_requested_at"],
        postgresql_where=sa.text("halt_requested_at IS NOT NULL"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Text(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("controller_session", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("reasoning_effort", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("state_code", _enum("session_state"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("turns", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        _timestamp("started_at"),
        _timestamp("turn_started_at"),
        _timestamp("turn_ended_at"),
        _timestamp("stopped_at"),
        sa.Column("stopped_by_user_id", sa.Uuid(), nullable=True),
        _timestamp("ended_at"),
        _timestamp("nudge_owed_at"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"]),
        sa.ForeignKeyConstraint(["kind_code"], ["session_kinds.code"]),
        sa.ForeignKeyConstraint(["stopped_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_state_code", "sessions", ["state_code"])
    op.create_index("uq_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index(
        "ix_sessions_nudge_owed_at",
        "sessions",
        ["nudge_owed_at"],
        postgresql_where=sa.text("nudge_owed_at IS NOT NULL"),
    )


def _create_plan() -> None:
    op.create_table(
        "plan_tasks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status_code", _enum("task_status"), nullable=False),
        _timestamp("removed_at"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(position IS NULL) = (removed_at IS NOT NULL)",
            name="ck_plan_tasks_position",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id", "task_id"),
    )
    op.create_table(
        "plan_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_task_id", sa.Text(), nullable=True),
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _created_at(),
        _timestamp("deleted_at"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "plan_task_id"],
            ["plan_tasks.project_id", "plan_tasks.task_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_plan_notes_open_note_id",
        "plan_notes",
        ["project_id", "note_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_plan_notes_open_plan_task",
        "plan_notes",
        ["project_id", "plan_task_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    for table in (
        "plan_notes",
        "plan_tasks",
        "sessions",
        "environments",
        "project_transitions",
        "project_members",
        "projects",
        "users",
        "session_kinds",
        "confirmation_reasons",
        "done_causes",
        "item_kinds",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind)
