"""A custom ratio's format, the person's pick.

Slice 054 (DB §2.10 and §2.11; decision 86; assertions 638 to 640): Number
Format, Pilot's own closed list, an enum (DB §7.2), and
`custom_ratios.format_code`, which a person's ratio has and a loaded one has
not.

A person's ratio made before this revision is given the format its two
measures gave it at each read until now, so that it reads as it did: a share
where the figures of both sides have one format, else its numerator's
figure's, by the figures' formats as `app/dashboard/measures.py` holds them
at this revision. A loaded ratio keeps that rule at each read and has none.

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMBER_FORMAT = ("usd", "tokens", "count", "seconds", "share")
FORMAT = "(origin_code = 'person') = (format_code IS NOT NULL)"

FIGURE_FORMATS = {
    "cost": "usd",
    "tokens": "tokens",
    "calls": "count",
    "misses": "count",
    "miss_cost": "usd",
    "past_ttl": "count",
    "compactions": "count",
    "rewinds": "count",
    "ctx": "tokens",
    "waited": "seconds",
    "took": "seconds",
    "turns": "count",
    "turn_time": "seconds",
    "failed_turns": "count",
    "reported_cost": "usd",
    "events": "count",
    "error_events": "count",
}
"""Each figure's format at this revision, by its key."""

PERSONS = sa.text(
    "SELECT id, numerator, denominator FROM custom_ratios WHERE origin_code = 'person'"
)
PICK = sa.text(
    "UPDATE custom_ratios SET format_code = CAST(:format AS number_format)"
    " WHERE id = :id"
)


def _figure(side: str) -> str:
    """The figure a side names: a stored side is in its normal form,
    `<figure>.<aggregate>…`."""
    return side.split(".", 1)[0]


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    postgresql.ENUM(*NUMBER_FORMAT, name="number_format").create(bind)
    op.add_column(
        "custom_ratios",
        sa.Column(
            "format_code",
            postgresql.ENUM(name="number_format", create_type=False),
            nullable=True,
        ),
    )
    for ratio in bind.execute(PERSONS).mappings().all():
        above = FIGURE_FORMATS[_figure(ratio["numerator"])]
        below = FIGURE_FORMATS[_figure(ratio["denominator"])]
        bind.execute(
            PICK, {"id": ratio["id"], "format": "share" if above == below else above}
        )
    op.create_check_constraint("ck_custom_ratios_format", "custom_ratios", FORMAT)


def downgrade() -> None:
    """Downgrade database schema: the formats a person picked are lost."""
    op.drop_constraint("ck_custom_ratios_format", "custom_ratios", type_="check")
    op.drop_column("custom_ratios", "format_code")
    postgresql.ENUM(name="number_format").drop(op.get_bind())
