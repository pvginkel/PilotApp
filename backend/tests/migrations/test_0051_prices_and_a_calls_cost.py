"""Revision 0051: the Calls stored gain their `context_tokens`, and its
downgrade takes the Prices, each Call's cost and each Model's `priced_as`."""

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import Call, Model
from tests.support import transcripts
from tests.support.revisions import run_revision

COLUMNS = text(
    "SELECT table_name || '.' || column_name FROM information_schema.columns"
    " WHERE (table_name, column_name) IN (('calls', 'cost'),"
    " ('calls', 'context_tokens'), ('models', 'priced_as_code'))"
    " ORDER BY 1"
)


def _stored(db: DbSession) -> int:
    """A Call stored, of a Model priced as another, with its cost."""
    transcripts.reference(db, Model, "claude-opus-9", priced_as_code="claude-opus-5-5")
    thread = transcripts.transcript(db, transcripts.component_version(db))
    return transcripts.call(
        db, thread, 1, model_code="claude-opus-9", cost=Decimal("0.0812")
    ).id


class TestTheDowngrade:
    def test_the_prices_a_calls_cost_and_a_models_priced_as_go(
        self, session: DbSession
    ) -> None:
        call_id = _stored(session)

        run_revision(session, "0051", "downgrade")

        assert session.scalar(text("SELECT to_regclass('prices')")) is None
        assert session.scalars(COLUMNS).all() == []
        assert session.scalars(
            text("SELECT model_code FROM calls WHERE id = :id"), {"id": call_id}
        ).all() == ["claude-opus-9"]


class TestTheUpgrade:
    def test_a_stored_call_gains_its_context_tokens_and_no_cost(
        self, session: DbSession
    ) -> None:
        call_id = _stored(session)
        run_revision(session, "0051", "downgrade")

        run_revision(session, "0051", "upgrade")

        assert session.scalars(COLUMNS).all() == [
            "calls.context_tokens",
            "calls.cost",
            "models.priced_as_code",
        ]
        # 1,204 read fresh, 3,310 written to the cache and 48,112 read from it.
        assert session.execute(
            select(Call.context_tokens, Call.cost).where(Call.id == call_id)
        ).all() == [(52_626, None)]
        assert session.scalars(
            select(Model.priced_as_code).where(Model.code == "claude-opus-9")
        ).all() == [None]
        assert session.scalar(text("SELECT count(*) FROM prices")) == 0
