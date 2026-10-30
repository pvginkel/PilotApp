"""Quota Overrule, and Overrule Kind's values renamed.

Slice 028, P4: a person lifts the week's usage halt with an overrule, the
allowance or run-out, at most one holding at a time; Overrule Kind's
`add_five` and `to_the_end` become `allowance` and `run_out` (DB decision 66,
assertions 179, 267 and 268).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMED = (("add_five", "allowance"), ("to_the_end", "run_out"))


def upgrade() -> None:
    """Upgrade database schema."""
    for old, new in RENAMED:
        op.execute(f"ALTER TYPE overrule_kind RENAME VALUE '{old}' TO '{new}'")
    op.create_table(
        "quota_overrules",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "kind_code",
            postgresql.ENUM(name="overrule_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("made_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target", sa.Double(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind_code = 'allowance') = (target IS NOT NULL)",
            name="ck_quota_overrules_target",
        ),
        sa.ForeignKeyConstraint(["made_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_quota_overrules_holding",
        "quota_overrules",
        [sa.text("(ended_at IS NULL)")],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("uq_quota_overrules_holding", table_name="quota_overrules")
    op.drop_table("quota_overrules")
    for old, new in RENAMED:
        op.execute(f"ALTER TYPE overrule_kind RENAME VALUE '{new}' TO '{old}'")
