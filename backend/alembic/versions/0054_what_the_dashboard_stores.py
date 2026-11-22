"""What the dashboard stores.

Slice 053 (DB §2.10 and §2.11; decisions 79.9, 79.10 and 80; assertions 597
to 604): Origin and Favourite Menu, Pilot's own closed lists, enums (DB
§7.2); `saved_views` with its `view_stars`, `dimension_favourites`,
`quick_filters` and `custom_ratios`. A Saved View and a Custom Ratio carry
`system` from their Origin, so that a name is unique among the system's rows
and among a person's (DB 602, §7.7).

The five quick filters the dashboard ships with are written here, once: a
removed one stays removed. Pilot's own system views are written at each
deploy, after the revisions, by `DashboardStoreService.ship`.

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGIN = ("pilot", "workflow", "person")
FAVOURITE_MENU = ("by", "color")
SYSTEM = "origin_code <> 'person'"

QUICK_FILTERS = (
    {
        "code": "past_ttl",
        "label": "Waits past the cache TTL",
        "condition": "past_ttl:1",
        "amount_figure": "miss_cost",
        "note": (
            "The Calls that waited longer than the cache their predecessor "
            "wrote lives; the amount is the cost of those that missed it"
        ),
    },
    {
        "code": "misses",
        "label": "Cache misses",
        "condition": "miss:1",
        "amount_figure": "miss_cost",
        "note": (
            "The Calls that wrote again what their predecessor left cached; "
            "the amount is their cost"
        ),
    },
    {
        "code": "compactions",
        "label": "Compactions",
        "condition": "compaction:1",
        "amount_figure": None,
        "note": "The Calls that follow a compaction of their thread's context",
    },
    {
        "code": "outliers",
        "label": "Outlier rows",
        "condition": "@outliers",
        "amount_figure": None,
        "note": "The By's rows whose first measure is an outlier among them",
    },
    {
        "code": "expensive",
        "label": "Expensive calls",
        "condition": "@items,gt,1,cost.sum",
        "amount_figure": "cost",
        "note": "Each Call that cost more than $1; the amount is their cost",
    },
)


def upgrade() -> None:
    """Upgrade database schema."""
    postgresql.ENUM(*ORIGIN, name="origin").create(op.get_bind())
    postgresql.ENUM(*FAVOURITE_MENU, name="favourite_menu").create(op.get_bind())
    op.create_table(
        "saved_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "origin_code",
            postgresql.ENUM(name="origin", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "system", sa.Boolean(), sa.Computed(SYSTEM, persisted=True), nullable=False
        ),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(origin_code = 'person') = (key IS NULL)", name="ck_saved_views_key"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origin_code", "key"),
        sa.UniqueConstraint("system", "name"),
    )
    op.create_table(
        "view_stars",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("saved_view_id", sa.Uuid(), nullable=False),
        sa.Column("starred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["saved_view_id"], ["saved_views.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "saved_view_id"),
    )
    op.create_index("ix_view_stars_saved_view_id", "view_stars", ["saved_view_id"])
    op.create_table(
        "dimension_favourites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "menu_code",
            postgresql.ENUM(name="favourite_menu", create_type=False),
            nullable=False,
        ),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "menu_code", "dimension"),
    )
    quick_filters = op.create_table(
        "quick_filters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("marks", sa.Boolean(), nullable=False),
        sa.Column("amount_figure", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "condition NOT LIKE '~%'", name="ck_quick_filters_condition"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "custom_ratios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "origin_code",
            postgresql.ENUM(name="origin", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "system", sa.Boolean(), sa.Computed(SYSTEM, persisted=True), nullable=False
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("numerator", sa.Text(), nullable=False),
        sa.Column("denominator", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("origin_code <> 'pilot'", name="ck_custom_ratios_origin"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]*$'", name="ck_custom_ratios_key"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
        sa.UniqueConstraint("system", "name"),
    )
    op.execute(
        quick_filters.insert().values(
            [
                {
                    "id": sa.func.gen_random_uuid(),
                    "marks": False,
                    "saved_at": sa.func.now(),
                    **quick_filter,
                }
                for quick_filter in QUICK_FILTERS
            ]
        )
    )


def downgrade() -> None:
    """Downgrade database schema: everything the dashboard stores is lost."""
    op.drop_table("custom_ratios")
    op.drop_table("quick_filters")
    op.drop_table("dimension_favourites")
    op.drop_index("ix_view_stars_saved_view_id", table_name="view_stars")
    op.drop_table("view_stars")
    op.drop_table("saved_views")
    postgresql.ENUM(name="favourite_menu").drop(op.get_bind())
    postgresql.ENUM(name="origin").drop(op.get_bind())
