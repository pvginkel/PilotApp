"""Each Turn's own tokens and cost.

Slice 039, P4: a Turn that resumed a conversation holds the conversation's
figures so far, as its `result` line reports them. Each is rewritten to its
own: its figures less those of the conversation's previous Turn that has Token
Counts, the conversation spanning its Sessions; as they are where any of them
is below that Turn's, a fresh total (DB assertion 275). Before this revision a
Turn's figures are its last `result` line's, and the lines stay in the session
records as they are.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-05

"""

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    figures: dict[int, tuple[dict[str, int], Decimal | None]] = {}
    conversations: dict[str, list[int]] = {}
    # Indexed, not unpacked: mypy reads a textual row's unpacking as `object`.
    for row in bind.execute(
        sa.text(
            "SELECT t.id, s.conversation_id, t.cost, c.token_kind_code, c.tokens"
            " FROM turns t JOIN sessions s ON s.id = t.session_id"
            " JOIN token_counts c ON c.turn_id = t.id"
            " WHERE s.conversation_id IS NOT NULL"
            " ORDER BY t.id"
        )
    ):
        turn_id = row[0]
        if turn_id not in figures:
            figures[turn_id] = ({}, row[2])
            conversations.setdefault(row[1], []).append(turn_id)
        figures[turn_id][0][row[3]] = row[4]
    counts: list[dict[str, object]] = []
    costs: list[dict[str, object]] = []
    for turns in conversations.values():
        for before, turn_id in pairwise(turns):
            own, cost = figures[turn_id]
            before_counts, before_cost = figures[before]
            if any(count < before_counts[kind] for kind, count in own.items()) or (
                cost is not None and before_cost is not None and cost < before_cost
            ):
                continue
            counts.extend(
                {"turn": turn_id, "kind": kind, "tokens": count - before_counts[kind]}
                for kind, count in own.items()
            )
            if cost is not None and before_cost is not None:
                costs.append({"turn": turn_id, "cost": cost - before_cost})
    if counts:
        bind.execute(
            sa.text(
                "UPDATE token_counts SET tokens = :tokens"
                " WHERE turn_id = :turn AND token_kind_code = CAST(:kind AS token_kind)"
            ),
            counts,
        )
    if costs:
        bind.execute(sa.text("UPDATE turns SET cost = :cost WHERE id = :turn"), costs)


def downgrade() -> None:
    """Downgrade database schema: nothing; the Turns keep their own figures,
    and the conversation's figures so far stay in their `result` lines."""
