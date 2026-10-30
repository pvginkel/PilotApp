"""Token Count, classified by Token Kind, and Turn's cost.

Slice 028, P10: every Turn keeps the tokens it used per kind and the cost its
`result` line reports (DB decision 67, assertions 272, 273 and 275). The Turns
before it keep none.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOKEN_KIND = ("input", "cache_write", "cache_read", "output")


def upgrade() -> None:
    """Upgrade database schema."""
    postgresql.ENUM(*TOKEN_KIND, name="token_kind").create(op.get_bind())
    op.add_column("turns", sa.Column("cost", sa.Numeric(), nullable=True))
    op.create_table(
        "token_counts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "token_kind_code",
            postgresql.ENUM(name="token_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("tokens", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("tokens >= 0", name="ck_token_counts_tokens"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", "token_kind_code"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("token_counts")
    op.drop_column("turns", "cost")
    postgresql.ENUM(name="token_kind").drop(op.get_bind())
