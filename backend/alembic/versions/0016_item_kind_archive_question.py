"""Item Kind's `archive_question`, created by Pilot.

Slice 026, P7: after any finish, the server puts one question under the end
divider, "Archive the project?", a prose item of its own kind, fixed at birth,
created by Pilot and by no session (F5.6; DB decision 65, assertions 161, 263
to 265).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute(
        "INSERT INTO item_kinds (code, name, form, icon)"
        " VALUES ('archive_question', 'Archive question', 'prose', 'archive')"
    )
    op.drop_constraint("ck_items_created_by", "items", type_="check")
    op.create_check_constraint(
        "ck_items_created_by",
        "items",
        "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
        " AND (created_by_user_id IS NULL"
        " OR kind_code IN ('opening', 'archive_question'))",
    )


def downgrade() -> None:
    """Downgrade database schema: an archive question fails the check."""
    op.drop_constraint("ck_items_created_by", "items", type_="check")
    op.create_check_constraint(
        "ck_items_created_by",
        "items",
        "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
        " AND (created_by_user_id IS NULL OR kind_code = 'opening')",
    )
    op.execute("DELETE FROM item_kinds WHERE code = 'archive_question'")
