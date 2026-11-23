"""The estimate of the time a running work item still takes, for the tests
of what carries it: the settings' defaults, a kind's past timings and a
work item's list."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models import ProgressStep, StepKind, StepTiming
from app.models.reference import ProgressState
from app.services.step_estimate import StepEstimates

ESTIMATES = StepEstimates(window=20, running=60, slow_factor=1.6)
"""The estimate under the settings' defaults."""


def _kind(db: DbSession, kind: str) -> None:
    if db.get(StepKind, kind) is None:
        db.add(StepKind(code=kind, name=kind))
        db.flush()


def timed(
    db: DbSession, work_id: uuid.UUID, kind: str, minutes: int, *, count: int = 10
) -> None:
    """`count` Step Timings of `kind` on the Work, in no repo, each `minutes`
    long and listed ahead, one a day over the days before today: a step of
    the kind is priced at `minutes` in every repo, and a running one of them
    still takes `minutes` less the time it has run."""
    _kind(db, kind)
    today = datetime.now(UTC)
    db.add_all(
        StepTiming(
            work_id=work_id,
            kind_code=kind,
            ended_at=today - timedelta(days=older),
            duration=minutes * 60,
            listed_ahead=True,
            code=f"timed-{kind}-{older}",
        )
        for older in range(1, count + 1)
    )
    db.flush()


def listed(
    db: DbSession,
    work_id: uuid.UUID,
    kind: str,
    *,
    running: float | None = None,
    pending: int = 0,
    marked: bool | None = None,
) -> None:
    """The Work's list, of steps of `kind`: one that began `running` minutes
    ago, listed ahead and carrying the workflow's mark as `marked`, where
    `running` is given, then `pending` steps not begun."""
    _kind(db, kind)
    steps = []
    if running is not None:
        steps.append(
            ProgressStep(
                work_id=work_id,
                code="running",
                label="The step that runs",
                state_code=ProgressState.ACTIVE,
                started_at=datetime.now(UTC) - timedelta(minutes=running),
                kind_code=kind,
                listed_ahead=True,
                marked=marked,
            )
        )
    steps.extend(
        ProgressStep(
            work_id=work_id,
            code=f"pending-{number}",
            label=f"A step not begun, {number}",
            state_code=ProgressState.PENDING,
            kind_code=kind,
        )
        for number in range(1, pending + 1)
    )
    for position, step in enumerate(steps, start=1):
        step.position = position
    db.add_all(steps)
    db.flush()
