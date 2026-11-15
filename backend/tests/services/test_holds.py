"""A Session's Holds as the gate's reads turn them (DB §2.5, Hold; assertions
360 to 362 and 559): one open at a time, of the kind of the gate's reason."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Hold
from app.models.reference import HoldKind
from app.schemas.timeline import HeldReason
from app.services.holds import KINDS, turn_hold
from app.services.start_gate import Held

AT = datetime(2026, 11, 12, 16, 25, tzinfo=UTC)
LATER = AT + timedelta(hours=5, minutes=31)


def _holds(
    db: DbSession, run: models.Session
) -> list[tuple[HoldKind, datetime, datetime | None]]:
    """The Session's Holds, in the order written."""
    db.expire_all()
    return [
        (hold.kind_code, hold.started_at, hold.ended_at)
        for hold in db.scalars(
            select(Hold).where(Hold.session_id == run.id).order_by(Hold.id)
        )
    ]


class TestKinds:
    def test_each_of_the_gates_reasons_has_a_kind_of_its_own(self) -> None:
        assert set(KINDS) == set(HeldReason)
        assert sorted(KINDS.values()) == sorted(HoldKind)

    def test_the_record_keeps_its_own_codes_for_the_pause_and_the_outage(self) -> None:
        assert {
            reason.value: kind.value
            for reason, kind in KINDS.items()
            if reason.value != kind.value
        } == {"paused": "pause", "controller_unreachable": "outage"}


class TestTurnHold:
    @pytest.mark.parametrize("reason", list(HeldReason))
    def test_a_reason_with_no_hold_open_starts_one_of_its_kind(
        self, session: DbSession, project_session: models.Session, reason: HeldReason
    ) -> None:
        turn_hold(session, project_session, Held(reason), AT)

        assert _holds(session, project_session) == [(KINDS[reason], AT, None)]

    def test_the_slots_count_is_not_the_holds(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_hold(session, project_session, Held(HeldReason.SLOT, 3), AT)
        turn_hold(session, project_session, Held(HeldReason.SLOT, 2), LATER)

        assert _holds(session, project_session) == [(HoldKind.SLOT, AT, None)]

    def test_the_reason_read_again_keeps_the_hold_it_opened(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_hold(session, project_session, Held(HeldReason.PAUSED), AT)

        turn_hold(session, project_session, Held(HeldReason.PAUSED), LATER)

        assert _holds(session, project_session) == [(HoldKind.PAUSE, AT, None)]

    def test_another_reason_ends_the_hold_and_starts_the_next_at_the_same_moment(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_hold(session, project_session, Held(HeldReason.PAUSED), AT)

        turn_hold(session, project_session, Held(HeldReason.WEEK_HALT), LATER)

        assert _holds(session, project_session) == [
            (HoldKind.PAUSE, AT, LATER),
            (HoldKind.WEEK_HALT, LATER, None),
        ]

    def test_no_reason_ends_the_open_hold(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_hold(session, project_session, Held(HeldReason.SLOT, 3), AT)

        turn_hold(session, project_session, None, LATER)

        assert _holds(session, project_session) == [(HoldKind.SLOT, AT, LATER)]

    def test_no_reason_with_no_hold_open_writes_nothing(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_hold(session, project_session, None, AT)

        assert _holds(session, project_session) == []

    def test_a_reason_back_after_its_hold_ended_starts_another(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        """DB 559: two Holds of one Session and one kind, never overlapping."""
        turn_hold(session, project_session, Held(HeldReason.PAUSED), AT)
        turn_hold(session, project_session, None, LATER)

        turn_hold(
            session,
            project_session,
            Held(HeldReason.PAUSED),
            LATER + timedelta(hours=1),
        )

        assert _holds(session, project_session) == [
            (HoldKind.PAUSE, AT, LATER),
            (HoldKind.PAUSE, LATER + timedelta(hours=1), None),
        ]

    @pytest.mark.parametrize("held", [None, Held(HeldReason.CONTROLLER_UNREACHABLE)])
    def test_an_instant_read_before_the_hold_started_ends_it_where_it_started(
        self,
        session: DbSession,
        project_session: models.Session,
        held: Held | None,
    ) -> None:
        """The caller's instant may precede the Session's lock, under which
        the Hold was since written: it then ends the moment it started, and
        the next starts there."""
        turn_hold(session, project_session, Held(HeldReason.PAUSED), LATER)

        turn_hold(session, project_session, held, AT)

        assert _holds(session, project_session) == [
            (HoldKind.PAUSE, LATER, LATER),
            *([] if held is None else [(HoldKind.OUTAGE, LATER, None)]),
        ]

    def test_each_session_has_its_own(
        self,
        session: DbSession,
        project_session: models.Session,
    ) -> None:
        """A pause that holds three Sessions is three Holds."""
        others = [
            models.Session(
                project_id=project_session.project_id,
                kind_code="work",
                cwd="/work/Example",
                token_hash=str(digit) * 64,
                state_code=project_session.state_code,
            )
            for digit in (2, 3)
        ]
        session.add_all(others)
        session.flush()

        for run in (project_session, *others):
            turn_hold(session, run, Held(HeldReason.PAUSED), AT)
        turn_hold(session, others[0], None, LATER)

        assert [_holds(session, run) for run in (project_session, *others)] == [
            [(HoldKind.PAUSE, AT, None)],
            [(HoldKind.PAUSE, AT, LATER)],
            [(HoldKind.PAUSE, AT, None)],
        ]
