"""Token Kind a table, with `within` and a cache write's two lifetimes.

Token Kind gains a fact about the category, the coarser kind a finer one is
part of, and so becomes a table; `cache_write_5m` and `cache_write_1h` are
within `cache_write` (DB decision 79.5, §7.2, assertions 425, 426 and 547). A
Turn's Token Counts keep their rows and their four kinds.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TURN_KINDS = ("input", "cache_write", "cache_read", "output")


def upgrade() -> None:
    """Upgrade database schema."""
    token_kinds = op.create_table(
        "token_kinds",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("within_code", sa.Text(), nullable=True),
        sa.CheckConstraint("within_code <> code", name="ck_token_kinds_within"),
        sa.ForeignKeyConstraint(["within_code"], ["token_kinds.code"]),
        sa.PrimaryKeyConstraint("code"),
    )
    op.bulk_insert(
        token_kinds,
        [
            {"code": "input", "name": "Input", "within_code": None},
            {"code": "cache_write", "name": "Cache write", "within_code": None},
            {"code": "cache_read", "name": "Cache read", "within_code": None},
            {"code": "output", "name": "Output", "within_code": None},
            {
                "code": "cache_write_5m",
                "name": "Cache write, five minutes",
                "within_code": "cache_write",
            },
            {
                "code": "cache_write_1h",
                "name": "Cache write, one hour",
                "within_code": "cache_write",
            },
        ],
    )
    op.alter_column(
        "token_counts",
        "token_kind_code",
        type_=sa.Text(),
        postgresql_using="token_kind_code::text",
    )
    op.create_foreign_key(
        "token_counts_token_kind_code_fkey",
        "token_counts",
        "token_kinds",
        ["token_kind_code"],
        ["code"],
    )
    op.create_check_constraint(
        "ck_token_counts_kind",
        "token_counts",
        "token_kind_code IN ('input', 'cache_write', 'cache_read', 'output')",
    )
    postgresql.ENUM(name="token_kind").drop(op.get_bind())


def downgrade() -> None:
    """Downgrade database schema."""
    postgresql.ENUM(*TURN_KINDS, name="token_kind").create(op.get_bind())
    op.drop_constraint("ck_token_counts_kind", "token_counts", type_="check")
    op.drop_constraint(
        "token_counts_token_kind_code_fkey", "token_counts", type_="foreignkey"
    )
    op.alter_column(
        "token_counts",
        "token_kind_code",
        type_=postgresql.ENUM(name="token_kind", create_type=False),
        postgresql_using="token_kind_code::token_kind",
    )
    op.drop_table("token_kinds")
