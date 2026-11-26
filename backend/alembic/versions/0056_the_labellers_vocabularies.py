"""The labeller's vocabularies.

Slice 052 (DB §2.11, "the labeller's"; decisions 79.12 and 79.40, assertion
585): a table per reference entity of the labeller's, its code, its name, its
line and its place in its list, with the fact about its category where it has
one; Work Unit Kind Nesting (§2.8); and Event Kind and Context Part Kind
taking the labeller's values beside the collector's, with their line and
their place. No revision writes a row: a collector's declaration does.

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-26

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LISTS: dict[str, dict[str, type[sa.types.TypeEngine[Any]]]] = {
    "work_unit_kinds": {},
    "unit_outcomes": {},
    "rework_kinds": {},
    "unit_measures": {"unit": sa.Text},
    "segment_kinds": {},
    "wait_causes": {},
    "call_classes": {},
    "avoidable_kinds": {},
    "command_classes": {},
    "build_results": {},
    "file_classes": {"counted": sa.Boolean},
    "tool_effect_kinds": {},
    "rules": {"home": sa.Text},
    "ask_categories": {},
}
"""The labeller's own reference entities' tables, with the fact about the
category each holds beyond its code, name, line and place."""

BESIDE = ("event_kinds", "context_part_kinds")
"""The collector's reference entities that take the labeller's values too."""


def _place(table: str) -> tuple[sa.Constraint, ...]:
    return (
        sa.UniqueConstraint(
            "position",
            name=f"uq_{table}_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("position >= 1", name=f"ck_{table}_position"),
    )


def upgrade() -> None:
    """Upgrade database schema."""
    for table, facts in LISTS.items():
        op.create_table(
            table,
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=True),
            *(sa.Column(fact, kind(), nullable=False) for fact, kind in facts.items()),
            sa.PrimaryKeyConstraint("code"),
            *_place(table),
        )
    op.create_table(
        "work_unit_kind_nestings",
        sa.Column("inner_code", sa.Text(), nullable=False),
        sa.Column("outer_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["inner_code"], ["work_unit_kinds.code"]),
        sa.ForeignKeyConstraint(["outer_code"], ["work_unit_kinds.code"]),
        sa.PrimaryKeyConstraint("inner_code", "outer_code"),
    )
    for table in BESIDE:
        op.add_column(table, sa.Column("description", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("position", sa.Integer(), nullable=True))
        op.create_unique_constraint(
            f"uq_{table}_position",
            table,
            ["position"],
            deferrable=True,
            initially="DEFERRED",
        )
        op.create_check_constraint(f"ck_{table}_position", table, "position >= 1")
        op.create_check_constraint(
            f"ck_{table}_described",
            table,
            "position IS NULL OR description IS NOT NULL",
        )


def downgrade() -> None:
    """Downgrade database schema: the labeller's lists are lost, and its
    values of Event Kind and Context Part Kind keep their code and name."""
    for table in reversed(BESIDE):
        op.drop_constraint(f"ck_{table}_described", table, type_="check")
        op.drop_constraint(f"ck_{table}_position", table, type_="check")
        op.drop_constraint(f"uq_{table}_position", table, type_="unique")
        op.drop_column(table, "position")
        op.drop_column(table, "description")
    op.drop_table("work_unit_kind_nestings")
    for table in reversed(LISTS):
        op.drop_table(table)
