"""The Prices, a Model priced as another, and a Call's cost.

Slice 053 (DB §2.7, Price and Call; §2.11, Model; decisions 79.14 and 79.22;
assertions 547 to 549): `prices`, a rate per Model, Token Kind and context
size from a moment on; `models.priced_as_code`, the Model whose Prices a
Model takes where it has none of its own; and on `calls` the two derived
caches `context_tokens`, which PostgreSQL derives for the Calls stored and
every Call after them, and `cost`.

No Price is written here and no Call is priced: the load of the price file
that follows the revisions writes the Prices, gives each Model stored its
`priced_as` and each Call stored its `cost` (`app/services/price_service.py`).
`ix_calls_unpriced` holds the Calls that load prices at every deploy.

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXT_TOKENS = (
    "input_tokens + cache_write_5m_tokens + cache_write_1h_tokens + cache_read_tokens"
)


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("models", sa.Column("priced_as_code", sa.Text(), nullable=True))
    op.create_foreign_key(
        "models_priced_as_code_fkey", "models", "models", ["priced_as_code"], ["code"]
    )
    op.create_check_constraint(
        "ck_models_priced_as", "models", "priced_as_code <> code"
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("model_code", sa.Text(), nullable=False),
        sa.Column("token_kind_code", sa.Text(), nullable=False),
        sa.Column("above_context", sa.Integer(), nullable=True),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "token_kind_code IN ('input', 'cache_write_5m', 'cache_write_1h',"
            " 'cache_read', 'output')",
            name="ck_prices_kind",
        ),
        sa.CheckConstraint("above_context > 0", name="ck_prices_above_context"),
        sa.CheckConstraint("rate >= 0", name="ck_prices_rate"),
        sa.ForeignKeyConstraint(["model_code"], ["models.code"]),
        sa.ForeignKeyConstraint(["token_kind_code"], ["token_kinds.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_code",
            "token_kind_code",
            "above_context",
            "effective_at",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.add_column(
        "calls",
        sa.Column(
            "context_tokens",
            sa.Integer(),
            sa.Computed(CONTEXT_TOKENS, persisted=True),
            nullable=False,
        ),
    )
    op.add_column("calls", sa.Column("cost", sa.Numeric(), nullable=True))
    op.create_index(
        "ix_calls_unpriced",
        "calls",
        ["id"],
        postgresql_where=sa.text("cost IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema: the Prices go with their table, and each
    Call's cost and each Model's `priced_as` with their columns."""
    op.drop_index("ix_calls_unpriced", table_name="calls")
    op.drop_column("calls", "cost")
    op.drop_column("calls", "context_tokens")
    op.drop_table("prices")
    op.drop_constraint("ck_models_priced_as", "models", type_="check")
    op.drop_constraint("models_priced_as_code_fkey", "models", type_="foreignkey")
    op.drop_column("models", "priced_as_code")
