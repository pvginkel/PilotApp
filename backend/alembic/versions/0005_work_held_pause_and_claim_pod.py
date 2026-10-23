"""Work, the held start, the pause and the claim's pod.

DB §2.2's Work, the extension table of Item and Session on their shared id
(DB §7.3); Session State's `held`, Transition Kind's `paused` and `resumed`,
and Project's `paused` (DB decision 53); Environment's `started_pod_at` (DB
decision 54).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_STATE = ("starting", "running", "idle", "stopped", "ended", "failed")
TRANSITION_KIND = (
    "opened",
    "finished",
    "reopened",
    "archived",
    "brought_back",
    "autopilot_on",
    "autopilot_off",
)


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the index on held Sessions reads `held`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE session_state ADD VALUE 'held' BEFORE 'starting'")
        op.execute("ALTER TYPE transition_kind ADD VALUE 'paused'")
        op.execute("ALTER TYPE transition_kind ADD VALUE 'resumed'")

    op.add_column(
        "projects",
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "environments",
        sa.Column("started_pod_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(None, "items", ["project_id", "id"])
    op.create_unique_constraint(None, "sessions", ["project_id", "id", "kind_code"])
    op.create_index(
        "ix_sessions_held",
        "sessions",
        ["created_at"],
        postgresql_where=sa.text("state_code = 'held'"),
    )
    op.create_table(
        "work",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_kind_code", sa.Text(), nullable=False),
        sa.Column(
            "trigger_code",
            postgresql.ENUM(name="work_trigger", create_type=False),
            nullable=True,
        ),
        sa.Column("trigger_item_id", sa.Uuid(), nullable=True),
        sa.Column("autopilot", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "session_kind_code IN ('work', 'job')", name="ck_work_session_kind"
        ),
        sa.CheckConstraint(
            "(session_kind_code = 'job') = (trigger_code IS NOT NULL)",
            name="ck_work_trigger",
        ),
        sa.CheckConstraint("trigger_item_id <> id", name="ck_work_trigger_item"),
        sa.ForeignKeyConstraint(["project_id", "id"], ["items.project_id", "items.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "trigger_item_id"], ["items.project_id", "items.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("work")
    op.drop_index("ix_sessions_held", table_name="sessions")
    op.drop_constraint("sessions_project_id_id_kind_code_key", "sessions")
    op.drop_constraint("items_project_id_id_key", "items")
    op.drop_column("environments", "started_pod_at")
    op.drop_column("projects", "paused")
    _without_values("session_state", SESSION_STATE, "sessions", "state_code")
    _without_values(
        "transition_kind", TRANSITION_KIND, "project_transitions", "kind_code"
    )


def _without_values(
    name: str, values: tuple[str, ...], table: str, column: str
) -> None:
    """The enum rebuilt with `values` alone; PostgreSQL drops no value in place."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_0005")
    postgresql.ENUM(*values, name=name).create(op.get_bind())
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column}"
        f" TYPE {name} USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {name}_0005")
