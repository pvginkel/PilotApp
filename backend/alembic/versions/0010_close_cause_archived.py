"""Close Cause's `archived`.

Slice 023, P1: Archive closes the chat open then, `archived` (F128.1; DB
decision 60, assertion 245).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26

"""

from collections.abc import Sequence

from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSE_CAUSE = ("timeout", "created", "finished", "reopened")


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute("ALTER TYPE close_cause ADD VALUE 'archived'")


def downgrade() -> None:
    """Downgrade database schema: the enum rebuilt without `archived`, which
    PostgreSQL drops no value of in place; a chat closed `archived` fails the
    cast."""
    op.execute("ALTER TYPE close_cause RENAME TO close_cause_0010")
    postgresql.ENUM(*CLOSE_CAUSE, name="close_cause").create(op.get_bind())
    op.execute(
        "ALTER TABLE chats ALTER COLUMN close_cause_code"
        " TYPE close_cause USING close_cause_code::text::close_cause"
    )
    op.execute("DROP TYPE close_cause_0010")
