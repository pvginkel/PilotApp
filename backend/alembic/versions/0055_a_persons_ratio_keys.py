"""A person's ratio keys.

Slice 053 (DB 602): a Custom Ratio a person made has its `key` from a space
no built-in or loaded ratio's key is in, so that no release and no load takes
it: the keys that begin `person_`, and those alone.

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-22

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY_SPACE = "(origin_code = 'person') = starts_with(key, 'person_')"


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_check_constraint("ck_custom_ratios_key_space", "custom_ratios", KEY_SPACE)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint("ck_custom_ratios_key_space", "custom_ratios", type_="check")
