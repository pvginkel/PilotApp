"""The quota wall (F135.3; the ruling on the wall, 2026-10-30; DB 232, 266).

A turn dies at the quota wall when Claude refuses it for the subscription's
quota; Pilot does nothing there (decision 66). A work item's or a job's
Session found ended so owes the nudge, sent once there is quota again; a
Chat's never does. Two signals tell the wall, both required. The turn's own
recorded stream shows it: a `rate_limit_event` line that gives a window the
`status` `rejected` (design 4 §2), or the `result` line's limit error, an
error the API answered `429` or Claude words as a limit reached. And a reading
confirms it: a window's share at or over 1 in the Usage Reading at the turn's
end, the latest received by then, or in the next one after it.

The Session's `nudge_owed_at` is its turn's end from the moment its stream
shows the wall, so the wait for the deciding reading holds across a restart:
a `failed` Session with its nudge owed is at the wall, its nudge sent once a
reading confirmed the wall and there is quota again. A reading after the end
that confirms it not, the one at the end confirming it not either, decides
the wall missed: no nudge is owed, and the failed end it is follows then
(`SessionStartService`). Of the readings, `id` gives the order in which they
were received.

There is quota again when no window of the latest reading is at or over 1, a
stale reading's window counting as reset a minute past its `resets_at`
(F135.8; DB 266).
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, SQLColumnExpression, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import SessionRecord, UsageReading, WindowShare
from app.models.reference import RecordKind
from app.services.usage_halts import LIFT_AFTER, WALL
from app.services.usage_service import latest

REJECTED = "rejected"
"""A window's `status` once Claude refuses its calls."""

_LIMIT_STATUS = 429

_LIMIT_WORDS = re.compile(r"\blimit reached\b|\bhit your limit\b", re.IGNORECASE)
"""Claude's words for a usage limit reached, as its `result` line gives
them."""

_SIGNS = ("rate_limit_event", "result")
"""The `type`s of the lines that may show the wall."""


def shows_wall(line: Any) -> bool:
    """Whether the raw line `claude` printed shows the wall: a
    `rate_limit_event` whose window, the one `rateLimitType` names or one of
    `unifiedWindows`, is `rejected`, or a `result` line's limit error."""
    if not isinstance(line, dict):
        return False
    if line.get("type") == "rate_limit_event":
        info = line.get("rate_limit_info")
        if not isinstance(info, dict):
            return False
        windows = info.get("unifiedWindows")
        statuses = [info.get("status")]
        if isinstance(windows, dict):
            statuses += [
                window.get("status")
                for window in windows.values()
                if isinstance(window, dict)
            ]
        return REJECTED in statuses
    if line.get("type") == "result" and line.get("is_error") is True:
        words = line.get("result")
        return line.get("api_error_status") == _LIMIT_STATUS or (
            isinstance(words, str) and _LIMIT_WORDS.search(words) is not None
        )
    return False


def turn_shows_wall(db: Session, session_id: uuid.UUID, turn_id: int) -> bool:
    """Whether the Turn's recorded stream shows the wall (`shows_wall`)."""
    lines: Sequence[Any] = db.scalars(
        select(SessionRecord.payload).where(
            SessionRecord.session_id == session_id,
            SessionRecord.turn_id == turn_id,
            SessionRecord.kind_code == RecordKind.CLAUDE,
            SessionRecord.payload["type"].astext.in_(_SIGNS),
        )
    ).all()
    return any(shows_wall(line) for line in lines)


def confirmed(at: SQLColumnExpression[datetime | None]) -> ColumnElement[bool]:
    """Whether a reading confirms the wall a turn ended at `at`: a window's
    share at or over 1 in the reading at `at` or the next one after it."""
    return (
        select(WindowShare.id)
        .where(
            or_(
                WindowShare.reading_id == _reading_at(at),
                WindowShare.reading_id == _reading_after(at),
            ),
            WindowShare.share >= WALL,
        )
        .correlate_except(WindowShare)
        .exists()
    )


def decided(at: SQLColumnExpression[datetime | None]) -> ColumnElement[bool]:
    """Whether the readings have decided the wall a turn ended at `at`: one
    was received after the reading at `at`. Undecided, the wall waits on the
    next reading unless the one at `at` confirms it."""
    return _reading_after(at).is_not(None)


def quota_back(db: Session) -> bool:
    """Whether there is quota again: no window of the latest reading at or
    over 1, a stale one's past its minute counting as reset; True before the
    first reading."""
    usage = latest(db)
    if usage is None:
        return True
    now = datetime.now(UTC)
    return not any(
        figure.share >= WALL
        and not (usage.stale and now >= figure.resets_at + LIFT_AFTER)
        for figure in usage.windows.values()
    )


# Each subquery reads a Usage Reading of its own and correlates whatever else
# it meets, the Session whose `nudge_owed_at` is `at` among it, at any depth:
# left to itself, SQLAlchemy correlates only to the select around it.


def _reading_at(
    at: SQLColumnExpression[datetime | None],
) -> ColumnElement[int | None]:
    reading = aliased(UsageReading)
    return (
        select(func.max(reading.id))
        .where(reading.received_at <= at)
        .correlate_except(reading)
        .scalar_subquery()
    )


def _reading_after(
    at: SQLColumnExpression[datetime | None],
) -> ColumnElement[int | None]:
    reading = aliased(UsageReading)
    return (
        select(func.min(reading.id))
        .where(reading.id > func.coalesce(_reading_at(at), 0))
        .correlate_except(reading)
        .scalar_subquery()
    )
