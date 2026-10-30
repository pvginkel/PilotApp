"""Quota Overrule: what a row must hold (DB 179, 267)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models import QuotaOverrule, User
from app.models.reference import OverruleKind
from tests.support.database import violated_constraint

MADE_AT = datetime(2026, 10, 6, 18, 10, tzinfo=UTC)


def _overrule(
    person: User,
    kind: OverruleKind,
    target: float | None,
    *,
    ended_at: datetime | None = None,
) -> QuotaOverrule:
    return QuotaOverrule(
        kind_code=kind,
        made_by_user_id=person.id,
        made_at=MADE_AT,
        target=target,
        ended_at=ended_at,
    )


class TestQuotaOverrule:
    def test_an_allowance_has_its_target_and_a_run_out_none(
        self, session: DbSession, person: User
    ) -> None:
        session.add_all(
            [
                _overrule(
                    person,
                    OverruleKind.ALLOWANCE,
                    0.96,
                    ended_at=MADE_AT + timedelta(hours=15),
                ),
                _overrule(person, OverruleKind.RUN_OUT, None),
            ]
        )

        session.flush()

    def test_an_allowance_without_a_target_is_refused(
        self, session: DbSession, person: User
    ) -> None:
        session.add(_overrule(person, OverruleKind.ALLOWANCE, None))

        assert violated_constraint(session) == "ck_quota_overrules_target"

    def test_a_run_out_with_a_target_is_refused(
        self, session: DbSession, person: User
    ) -> None:
        session.add(_overrule(person, OverruleKind.RUN_OUT, 1.0))

        assert violated_constraint(session) == "ck_quota_overrules_target"

    def test_at_most_one_holds(self, session: DbSession, person: User) -> None:
        session.add(_overrule(person, OverruleKind.ALLOWANCE, 0.96))
        session.flush()

        session.add(_overrule(person, OverruleKind.RUN_OUT, None))

        assert violated_constraint(session) == "uq_quota_overrules_holding"

    def test_spent_ones_stand_beside_the_one_that_holds(
        self, session: DbSession, person: User
    ) -> None:
        for hours in (1, 2):
            session.add(
                _overrule(
                    person,
                    OverruleKind.ALLOWANCE,
                    0.96,
                    ended_at=MADE_AT + timedelta(hours=hours),
                )
            )
        session.add(_overrule(person, OverruleKind.RUN_OUT, None))

        session.flush()
