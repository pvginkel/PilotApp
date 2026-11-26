"""Revision 0056: a custom ratio's format (DB 640), each person's ratio made
before it given the format its two measures gave it, a loaded one none; and
its downgrade, which takes the column, its check and the enum."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tests.support.revisions import run_revision

SAVED_AT = datetime(2026, 11, 22, 9, 30, tzinfo=UTC)
INSERT = text(
    "INSERT INTO custom_ratios"
    " (id, origin_code, key, name, numerator, denominator, saved_at)"
    " VALUES (:id, :origin, :key, :name, :numerator, :denominator, :saved_at)"
)


def _columns(db: DbSession) -> set[str]:
    return {
        column["name"]
        for column in inspect(db.connection()).get_columns("custom_ratios")
    }


def _number_format(db: DbSession) -> int | None:
    return db.scalar(
        text("SELECT count(*) FROM pg_type WHERE typname = 'number_format'")
    )


def _ratio(
    db: DbSession, origin: str, key: str, numerator: str, denominator: str
) -> None:
    """A ratio as it stood before the revision, with no format."""
    db.execute(
        INSERT,
        {
            "id": uuid.uuid4(),
            "origin": origin,
            "key": key,
            "name": key,
            "numerator": numerator,
            "denominator": denominator,
            "saved_at": SAVED_AT,
        },
    )


@pytest.fixture
def before(session: DbSession) -> DbSession:
    """The schema as revision 0055 left it."""
    run_revision(session, "0056", "downgrade")
    return session


class TestTheUpgrade:
    def test_a_persons_ratio_reads_as_it_did_and_a_loaded_one_has_none(
        self, before: DbSession
    ) -> None:
        """A share where the figures of both sides have one format, else its
        numerator's figure's."""
        _ratio(before, "person", "person_per_call", "cost.sum", "calls.count")
        _ratio(before, "person", "person_per_turn", "calls.count", "turns.count")
        _ratio(
            before,
            "person",
            "person_writer_share",
            "cost.sum(source=chat|pilot)",
            "reported_cost.sum",
        )
        _ratio(before, "person", "person_wait", "waited.sum", "calls.count.phase")
        _ratio(before, "person", "person_ctx", "ctx.max", "cost.sum")
        _ratio(before, "workflow", "per_phase", "cost.sum", "calls.count.phase")

        run_revision(before, "0056", "upgrade")

        assert dict(
            before.execute(text("SELECT key, format_code FROM custom_ratios")).all()
        ) == {
            "person_per_call": "usd",
            "person_per_turn": "share",
            "person_writer_share": "share",
            "person_wait": "seconds",
            "person_ctx": "tokens",
            "per_phase": None,
        }

    def test_a_persons_ratio_with_no_format_is_refused(self, before: DbSession) -> None:
        run_revision(before, "0056", "upgrade")

        with pytest.raises(IntegrityError) as raised:
            _ratio(before, "person", "person_per_call", "cost.sum", "calls.count")

        assert raised.value.orig.diag.constraint_name == "ck_custom_ratios_format"


class TestTheDowngrade:
    def test_it_takes_the_column_and_the_enum(self, before: DbSession) -> None:
        assert "format_code" not in _columns(before)
        assert _number_format(before) == 0

        run_revision(before, "0056", "upgrade")

        assert "format_code" in _columns(before)
        assert _number_format(before) == 1
