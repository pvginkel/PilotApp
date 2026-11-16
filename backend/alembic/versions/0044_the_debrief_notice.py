"""A Work's debrief subject, whether it completes it, and the Debrief Notice
that carries it; Item Kind `debrief_notice`, a fourth form.

DB decision 82, assertions 606 to 613: a debrief names what it is an
account of and whether it completes that account, given once with it; the
server's Debrief Notice, an Item with no Document, created by Pilot alone,
carries one subject's debriefs, each carried Work naming it under a key that
holds its Item's kind. A debrief given before this revision has neither
field, and no notice ever carries it.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATED_BY = (
    "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
    " AND (created_by_user_id IS NULL"
    " OR kind_code IN ('opening', 'archive_question'{}))"
)
_DEBRIEF_FIELDS = (
    "(debrief IS NOT NULL"
    " OR (debrief_subject IS NULL AND debrief_completes IS NULL))"
    " AND (debrief_completes IS NOT FALSE OR debrief_subject IS NOT NULL)"
)
_DEBRIEF_NOTICE = (
    "(debrief_notice_id IS NULL) = (debrief_notice_kind_code IS NULL)"
    " AND (debrief_notice_kind_code IS NULL"
    " OR (debrief_notice_kind_code = 'debrief_notice'"
    " AND debrief_completes IS NOT NULL))"
)
_NOTICE_KEY = "work_debrief_notice_id_debrief_notice_kind_code_fkey"


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint("ck_item_kinds_form", "item_kinds", type_="check")
    op.create_check_constraint(
        "ck_item_kinds_form",
        "item_kinds",
        "form IN ('prose', 'work', 'wait', 'debrief_notice')",
    )
    op.execute(
        "INSERT INTO item_kinds (code, name, form, icon)"
        " VALUES ('debrief_notice', 'Debrief notice', 'debrief_notice', 'notebook')"
    )
    op.drop_constraint("ck_items_created_by", "items", type_="check")
    op.create_check_constraint(
        "ck_items_created_by", "items", _CREATED_BY.format(", 'debrief_notice'")
    )

    op.add_column("work", sa.Column("debrief_subject", sa.Text(), nullable=True))
    op.add_column("work", sa.Column("debrief_completes", sa.Boolean(), nullable=True))
    op.add_column("work", sa.Column("debrief_notice_id", sa.Uuid(), nullable=True))
    op.add_column(
        "work", sa.Column("debrief_notice_kind_code", sa.Text(), nullable=True)
    )
    op.create_check_constraint("ck_work_debrief_fields", "work", _DEBRIEF_FIELDS)
    op.create_check_constraint("ck_work_debrief_notice", "work", _DEBRIEF_NOTICE)
    op.create_foreign_key(
        _NOTICE_KEY,
        "work",
        "items",
        ["debrief_notice_id", "debrief_notice_kind_code"],
        ["id", "kind_code"],
    )
    op.create_index(
        "ix_work_debrief_uncarried",
        "work",
        ["project_id", "debrief_subject"],
        postgresql_where=sa.text(
            "debrief_notice_id IS NULL AND debrief_subject IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade database schema: every debrief's subject and completion is
    lost, and a placed Debrief Notice fails it."""
    op.drop_index("ix_work_debrief_uncarried", table_name="work")
    op.drop_constraint(_NOTICE_KEY, "work", type_="foreignkey")
    op.drop_constraint("ck_work_debrief_notice", "work", type_="check")
    op.drop_constraint("ck_work_debrief_fields", "work", type_="check")
    op.drop_column("work", "debrief_notice_kind_code")
    op.drop_column("work", "debrief_notice_id")
    op.drop_column("work", "debrief_completes")
    op.drop_column("work", "debrief_subject")

    op.drop_constraint("ck_items_created_by", "items", type_="check")
    op.create_check_constraint("ck_items_created_by", "items", _CREATED_BY.format(""))
    op.execute("DELETE FROM item_kinds WHERE code = 'debrief_notice'")
    op.drop_constraint("ck_item_kinds_form", "item_kinds", type_="check")
    op.create_check_constraint(
        "ck_item_kinds_form", "item_kinds", "form IN ('prose', 'work', 'wait')"
    )
