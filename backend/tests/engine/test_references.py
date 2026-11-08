"""The reference rows the reads look up, kept for the process's life."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app.engine.references import Reason, References
from app.models.reference import ConfirmationReason
from tests.support.statements import sent


def _looked_up_twice(
    session: DbSession, lookup: Callable[[], Any]
) -> tuple[Any, list[str], list[str]]:
    """The lookup's value, and the statements its first and its second call
    sent, the session's loaded rows dropped before each."""
    session.expunge_all()
    with sent(session) as first:
        value = lookup()
    session.expunge_all()
    with sent(session) as again:
        assert lookup() == value
    return value, first.texts, again.texts


class TestReferences:
    @pytest.mark.parametrize(
        ("code", "form"),
        [("decision", "prose"), ("work", "work"), ("timed_wait", "wait")],
    )
    def test_a_kinds_form_is_read_on_its_first_lookup_alone(
        self, session: DbSession, code: str, form: str
    ) -> None:
        references = References()

        value, first, again = _looked_up_twice(
            session, lambda: references.form(session, code)
        )

        assert value == form
        assert (len(first), again) == (1, [])

    @pytest.mark.parametrize(
        ("code", "offered"), [("marked", True), ("finished", False)]
    )
    def test_whether_a_cause_offers_undo_is_read_on_its_first_lookup_alone(
        self, session: DbSession, code: str, offered: bool
    ) -> None:
        references = References()

        value, first, again = _looked_up_twice(
            session, lambda: references.undo_offered(session, code)
        )

        assert value is offered
        assert (len(first), again) == (1, [])

    def test_a_reason_is_read_on_its_first_lookup_alone(
        self, session: DbSession
    ) -> None:
        references = References()

        value, first, again = _looked_up_twice(
            session, lambda: references.reason(session, "rider")
        )

        row = session.get_one(ConfirmationReason, "rider")
        assert value == Reason(
            code="rider",
            name=row.name,
            description=row.description,
            asks_under_autopilot=row.asks_under_autopilot,
        )
        assert (len(first), again) == (1, [])

    def test_each_code_is_read_on_its_own_first_lookup(
        self, session: DbSession
    ) -> None:
        references = References()
        references.form(session, "decision")

        _, first, again = _looked_up_twice(
            session, lambda: references.form(session, "notice")
        )

        assert (len(first), again) == (1, [])
