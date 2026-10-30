"""Tests of the quota wall: its sign in a turn's own stream, the readings'
verdict on it, and the quota back (F135.3; the ruling on the wall; DB 232,
266; V24)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import literal, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Turn, UsageReading, WindowShare
from app.models.reference import RecordKind, UsageWindow
from app.services.container import ServiceContainer
from app.services.quota_wall import (
    confirmed,
    decided,
    quota_back,
    shows_wall,
    turn_shows_wall,
)
from tests.support.fake_controller import raw_turn

AT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
"""A turn's end."""

LIMIT = "Weekly limit reached ∙ resets Jan 4, 12am"


def _event(
    status: str = "allowed",
    *,
    five_hour: str | None = "allowed",
    seven_day: str | None = "allowed",
    unified: bool = True,
) -> dict[str, Any]:
    """A `rate_limit_event` line in today's shape (design 4 §2): its windows'
    `status` as given, None leaving a window's out, as September's shape
    did; without `unified`, no `unifiedWindows` at all."""
    windows: dict[str, Any] = {
        "five_hour": {"utilization": 0.62, "resetsAt": 1893456000},
        "seven_day": {"utilization": 0.98, "resetsAt": 1893715200},
    }
    for window, window_status in (("five_hour", five_hour), ("seven_day", seven_day)):
        if window_status is not None:
            windows[window]["status"] = window_status
    info: dict[str, Any] = {
        "status": status,
        "resetsAt": 1893456000,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "overageDisabledReason": "org_level_disabled",
        "isUsingOverage": False,
    }
    if unified:
        info["unifiedWindows"] = windows
    return {"type": "rate_limit_event", "rate_limit_info": info}


def _result(words: str, *, is_error: bool = True, status: int | None = None) -> Any:
    line: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": words,
    }
    if status is not None:
        line["api_error_status"] = status
    return line


class TestShowsWall:
    @pytest.mark.parametrize(
        "line",
        [
            _event(seven_day="rejected"),
            _event(five_hour="rejected"),
            _event("rejected", unified=False),
            _result("API Error: 429", status=429),
            _result(LIMIT),
            _result("You've hit your limit · resets 3am (Europe/Amsterdam)"),
            _result("Claude AI usage limit reached|1893715200"),
        ],
        ids=[
            "the week rejected",
            "the five hours rejected",
            "the event's own window rejected",
            "a 429",
            "a limit reached",
            "a limit hit",
            "a usage limit reached",
        ],
    )
    def test_a_window_rejected_or_the_results_limit_error_shows_it(
        self, line: Any
    ) -> None:
        assert shows_wall(line)

    @pytest.mark.parametrize(
        "line",
        [
            _event(),
            _event(seven_day="allowed_warning"),
            _event(five_hour=None, seven_day=None),
            _event(unified=False),
            {"type": "rate_limit_event"},
            _result("The tests failed."),
            _result("Not found", status=404),
            _result(LIMIT, is_error=False, status=429),
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": LIMIT}]},
            },
            "not json",
            None,
        ],
        ids=[
            "the overage alone rejected",
            "a warning",
            "no window's status",
            "no window",
            "no info",
            "another error",
            "another status",
            "no error",
            "an assistant's words",
            "a blank line",
            "nothing",
        ],
    )
    def test_any_other_line_shows_none(self, line: Any) -> None:
        assert not shows_wall(line)

    def test_the_invented_turn_at_the_wall_shows_it_by_its_event_and_its_result(
        self,
    ) -> None:
        lines = [json.loads(line) for line in raw_turn("turn_wall")]

        assert [line["type"] for line in lines if shows_wall(line)] == [
            "rate_limit_event",
            "result",
        ]

    @pytest.mark.parametrize("name", ["turn_text", "turn_tool", "turn_subagent"])
    def test_the_invented_turns_that_end_well_show_none(self, name: Any) -> None:
        assert not any(shows_wall(json.loads(line)) for line in raw_turn(name))


def _turn(db: DbSession, run: models.Session, seq: int) -> Turn:
    turn = Turn(session_id=run.id, seq=seq, message="Rename the badge", started_at=AT)
    db.add(turn)
    db.flush()
    return turn


class TestTurnShowsWall:
    def test_it_reads_the_turns_own_claude_lines_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project_session: models.Session,
    ) -> None:
        records = container.session_record_service()
        first, second = (
            _turn(session, project_session, 1),
            _turn(session, project_session, 2),
        )
        offset = 0
        for turn, name in ((first, "turn_text"), (second, "turn_wall")):
            for line in raw_turn(name):
                offset += len(line) + 1
                if json.loads(line)["type"] == "stream_event":
                    # Never a record (DB 218).
                    continue
                records.append(
                    project_session.id,
                    RecordKind.CLAUDE,
                    payload=json.loads(line),
                    turn_id=turn.id,
                    raw_offset=offset,
                    controller_session="claude-1",
                )
        third = _turn(session, project_session, 3)
        records.append(
            project_session.id,
            RecordKind.SERVER,
            payload=_result(LIMIT),
            turn_id=third.id,
        )

        assert [
            turn_shows_wall(session, project_session.id, turn.id)
            for turn in (first, second, third)
        ] == [False, True, False]


def _reading(
    db: DbSession,
    received_at: datetime,
    *,
    week: float,
    five_hour: float = 0.1,
    stale: bool = False,
    resets_at: datetime | None = None,
) -> None:
    """A Usage Reading received at `received_at` with these shares, each
    window's reset at `resets_at`, a day after it by default."""
    reading = UsageReading(taken_at=received_at, received_at=received_at, stale=stale)
    db.add(reading)
    db.flush()
    db.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=share,
            resets_at=resets_at or received_at + timedelta(days=1),
        )
        for window, share in (
            (UsageWindow.SEVEN_DAY, week),
            (UsageWindow.FIVE_HOUR, five_hour),
        )
    )
    db.flush()


def _verdict(db: DbSession) -> tuple[bool | None, bool | None]:
    """Whether the readings confirm a wall the turn ending at AT met, and
    whether they have decided it."""
    return (
        db.scalar(select(confirmed(literal(AT)))),
        db.scalar(select(decided(literal(AT)))),
    )


MINUTE = timedelta(minutes=1)


class TestVerdict:
    """The reading at the turn's end, the latest received by then, or the next
    one after it confirms the wall at a window's share at or over 1; the one
    after decides it."""

    @pytest.mark.parametrize(
        ("readings", "verdict"),
        [
            ([], (False, False)),
            ([(-MINUTE, 1.0, 0.1)], (True, False)),
            ([(timedelta(0), 1.02, 0.1)], (True, False)),
            ([(-MINUTE, 0.5, 1.0)], (True, False)),
            ([(-MINUTE, 0.95, 0.1)], (False, False)),
            ([(-MINUTE, 0.95, 0.1), (MINUTE, 1.0, 0.1)], (True, True)),
            ([(MINUTE, 1.0, 0.1)], (True, True)),
            ([(-MINUTE, 0.95, 0.1), (MINUTE, 0.96, 0.1)], (False, True)),
            (
                [(-MINUTE, 0.95, 0.1), (MINUTE, 0.96, 0.1), (2 * MINUTE, 1.0, 0.1)],
                (False, True),
            ),
            ([(-2 * MINUTE, 1.0, 0.1), (-MINUTE, 0.5, 0.1)], (False, False)),
        ],
        ids=[
            "no reading",
            "at its end",
            "received at its end",
            "the five hours at its end",
            "undecided",
            "the next one",
            "the first one after none",
            "missed",
            "a later one counts not",
            "an earlier one counts not",
        ],
    )
    def test_the_reading_at_the_end_or_the_next_one_decides(
        self,
        session: DbSession,
        readings: list[tuple[timedelta, float, float]],
        verdict: tuple[bool, bool],
    ) -> None:
        for offset, week, five_hour in readings:
            _reading(session, AT + offset, week=week, five_hour=five_hour)

        assert _verdict(session) == verdict


class TestQuotaBack:
    def test_with_no_reading_yet_nothing_is_out(self, session: DbSession) -> None:
        assert quota_back(session)

    @pytest.mark.parametrize(
        ("week", "five_hour", "back"),
        [(0.99, 0.98, True), (1.0, 0.1, False), (0.5, 1.02, False)],
    )
    def test_a_window_at_or_over_its_whole_quota_holds_it_out(
        self, session: DbSession, week: float, five_hour: float, back: bool
    ) -> None:
        now = datetime.now(UTC)
        _reading(session, now - MINUTE, week=1.0, five_hour=1.0)
        _reading(session, now, week=week, five_hour=five_hour)

        assert quota_back(session) is back

    @pytest.mark.parametrize(
        ("reset_ago", "back"),
        [(timedelta(seconds=30), False), (timedelta(minutes=2), True)],
    )
    def test_a_stale_window_counts_reset_a_minute_past_its_reset(
        self, session: DbSession, reset_ago: timedelta, back: bool
    ) -> None:
        """F135.8; DB 266."""
        now = datetime.now(UTC)
        _reading(
            session,
            now - timedelta(hours=1),
            week=1.0,
            five_hour=1.0,
            stale=True,
            resets_at=now - reset_ago,
        )

        assert quota_back(session) is back
