"""The time a running work item still takes (F156.4 to F156.7): an estimate
from the steps its run publishes and the Step Timings of their kinds.

The time left is the sum of three parts. A step not begun counts at its
kind's price: the total time of the kind's window, its last timings by their
end, divided by the number of them that were listed ahead, so the mean with
the unlisted repeats in it. A running step counts at the median of what
longer steps still took: of the last timings of its kind that began as it
did, listed ahead or not, those that ran at least as long as it has, each
less the time it has run; the kind's last timings taken whole where fewer
than `FEW` began as it did or its listing is unknown. And a step listed
ahead owes the repeats' share of its kind's price, the price less the mean
of the window's listed timings, while it runs and, done, until the next
listed step on the list is done or an unlisted step of its kind has begun
after it.

A kind's timings are the repo's own once the repo holds `OWN` of the kind,
all repos' until then, for the price and the running step alike. A timing
whose listing is unknown counts in none of it.

Nothing here reads a step's code or label, or orders two kinds (F92.13), and
no estimate is stored (F156.10).
"""

import math
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from statistics import fmean, median

from sqlalchemy import Boolean, Text, column, func, literal, select, true, values
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, aliased

from app.models import Item, ProgressStep, StepTiming
from app.models import Session as AgentSession
from app.models.reference import ProgressState, SessionState
from app.models.step import repo_of_work
from app.schemas.timeline import LongerThanUsual

FEW = 5
"""The timings below which a kind gives no estimate, counted in all repos,
and below which the timings that began as the running step did give way to
the kind's last ones whole."""

OWN = 10
"""The timings of a kind at which a repo's own are read in all repos'
place."""


@dataclass(frozen=True)
class WorkEstimate:
    """What a running work item's badge shows."""

    work_id: uuid.UUID
    seconds: float | None
    """The time left as the rules sum it, which `minutes` rounds and
    `project_estimate` compares; none where none shows."""
    longer_than_usual: LongerThanUsual | None
    kind: str | None
    """The kind of the first running step on the list, as published; none
    where no step runs or it has none."""
    ran_seconds: int | None
    """The seconds since the work item's run began, which its line's running
    time counts from; none while its Session has no start."""

    @property
    def minutes(self) -> int | None:
        """The time left as the badge words it (F156.8): to the nearest five
        minutes and at least five under 55 minutes, 60 to 89 minutes, and to
        the nearest hour from 90."""
        if self.seconds is None:
            return None
        minutes = self.seconds / 60
        if minutes < 55:
            return max(5, _nearest(minutes / 5) * 5)
        if minutes < 90:
            return 60
        return _nearest(minutes / 60) * 60


def _nearest(figure: float) -> int:
    """The nearest whole number, a half upward."""
    return math.floor(figure + 0.5)


def project_estimate(estimates: Iterable[WorkEstimate]) -> WorkEstimate | None:
    """The estimate a project's head shows, of its running work items': one
    longer than usual where any is, a step outrun before a step marked, else
    the marked one with the most time left; otherwise the one with the most
    time left. Of two alike, the first given."""
    shown = list(estimates)
    alerts = [each for each in shown if each.longer_than_usual is not None]
    for each in alerts:
        if each.longer_than_usual is LongerThanUsual.OUTRUN:
            return each
    return max(
        alerts or shown,
        key=lambda each: -1.0 if each.seconds is None else each.seconds,
        default=None,
    )


def work_estimates(
    db: Session,
    work_ids: Collection[uuid.UUID],
    *,
    now: datetime,
    window: int,
    running: int,
) -> dict[uuid.UUID, WorkEstimate]:
    """What the badge of each work item among `work_ids` shows at `now`, in
    their order; one that shows nothing is left out: one whose Session is
    not `running`, one that is done, one with no step left to do, and one
    with no estimate whose running steps the workflow has not marked.
    `window` is the number of a kind's last timings its price reads,
    `running` the number a running step is read against."""
    runs = {run.id: run for run in _runs(db, work_ids)}
    figures = _figures(db, list(runs.values()), max(window, running))
    estimates = {}
    for work_id in work_ids:
        if work_id not in runs:
            continue
        estimate = _estimate(
            runs[work_id], figures, now=now, window=window, running=running
        )
        if estimate is not None:
            estimates[work_id] = estimate
    return estimates


class StepEstimates:
    """The estimate under its two settings, both counted in steps
    (F156.10): `window`, the number of a kind's last timings its price
    reads, and `running`, the number a running step is read against."""

    def __init__(self, window: int, running: int) -> None:
        self._window = window
        self._running = running

    def of(
        self, db: Session, work_ids: Collection[uuid.UUID], now: datetime
    ) -> dict[uuid.UUID, WorkEstimate]:
        """`work_estimates` of `work_ids` at `now`."""
        return work_estimates(
            db, work_ids, now=now, window=self._window, running=self._running
        )


@dataclass(frozen=True)
class _Run:
    """An open work item whose Session runs, with its list in order."""

    id: uuid.UUID
    started_at: datetime | None
    turn_started_at: datetime | None
    repo: str | None
    steps: tuple[ProgressStep, ...]

    @cached_property
    def left(self) -> list[ProgressStep]:
        """The steps left to do: those not begun and those running."""
        return [step for step in self.steps if step.state_code != ProgressState.DONE]

    @cached_property
    def owing(self) -> list[str]:
        """The kind of each step that owes its kind's repeats' share: one
        listed ahead while it runs and, done, until the next listed step on
        the list is done or an unlisted step of its kind has begun after it;
        with no listed step after it, for as long as a step is left to do."""
        repeats: dict[str, datetime] = {}
        for step in self.steps:
            if step.kind_code is None or step.started_at is None:
                continue
            if step.listed_ahead is False:
                last = repeats.get(step.kind_code, step.started_at)
                repeats[step.kind_code] = max(last, step.started_at)
        owing = []
        after: ProgressStep | None = None
        for step in reversed(self.steps):
            if step.started_at is None:
                # Not begun, it stands pending on the list, listed ahead:
                # its `listed_ahead` is written with its first start.
                after = step
                continue
            if not step.listed_ahead:
                continue
            if step.kind_code is not None and self._owes(
                step, step.started_at, after, repeats.get(step.kind_code)
            ):
                owing.append(step.kind_code)
            after = step
        return owing

    @staticmethod
    def _owes(
        step: ProgressStep,
        began: datetime,
        after: ProgressStep | None,
        repeat: datetime | None,
    ) -> bool:
        """Whether a step listed ahead, which began at `began`, owes: `after`
        is the next listed step on the list, `repeat` the last start of an
        unlisted step of its kind."""
        if step.state_code != ProgressState.DONE:
            return step.state_code == ProgressState.ACTIVE
        if repeat is not None and repeat > began:
            return False
        return after is None or after.state_code != ProgressState.DONE

    @cached_property
    def kinds(self) -> set[str] | None:
        """The kinds whose timings the estimate reads; none where a step
        left to do has no kind."""
        kinds = set(self.owing)
        for step in self.left:
            if step.kind_code is None:
                return None
            kinds.add(step.kind_code)
        return kinds


def _runs(db: Session, work_ids: Collection[uuid.UUID]) -> list[_Run]:
    """Those of `work_ids` that are open, whose Session is `running` and has
    a step left to do, each with its whole list."""
    if not work_ids:
        return []
    run = aliased(AgentSession)
    rows = db.execute(
        select(
            run.id,
            run.started_at,
            run.turn_started_at,
            repo_of_work(run.id).scalar_subquery().label("repo"),
        )
        .join(Item, Item.id == run.id)
        .where(
            run.id.in_(list(work_ids)),
            run.state_code == SessionState.RUNNING,
            Item.done_at.is_(None),
        )
    ).all()
    if not rows:
        return []
    steps: dict[uuid.UUID, list[ProgressStep]] = {}
    for step in db.scalars(
        select(ProgressStep)
        .where(ProgressStep.work_id.in_([row.id for row in rows]))
        .order_by(ProgressStep.work_id, ProgressStep.position)
    ):
        steps.setdefault(step.work_id, []).append(step)
    runs = [
        _Run(
            row.id,
            row.started_at,
            row.turn_started_at,
            row.repo,
            tuple(steps.get(row.id, ())),
        )
        for row in rows
    ]
    return [run for run in runs if run.left]


@dataclass(frozen=True)
class _Timing:
    duration: int
    listed: bool


@dataclass(frozen=True)
class _Kind:
    """A kind's last timings, the newest first: the repo's own or all
    repos'."""

    timings: tuple[_Timing, ...]

    def price(self, window: int) -> tuple[float, float] | None:
        """A listed step's price and its repeats' share; none where the
        window holds no timing that was listed ahead."""
        last = self.timings[:window]
        listed = [timing.duration for timing in last if timing.listed]
        if not listed:
            return None
        price = sum(timing.duration for timing in last) / len(listed)
        return price, max(0.0, price - fmean(listed))

    def still(self, listed: bool | None, ran: float, running: int) -> list[float]:
        """What the timings a running step is read against still took once
        they had run `ran` seconds, those that ran no longer left out."""
        alike = [timing for timing in self.timings if timing.listed is listed]
        against = alike if len(alike) >= FEW else self.timings
        return [
            timing.duration - ran
            for timing in against[:running]
            if timing.duration >= ran
        ]


_Figures = dict[tuple[str, str | None], _Kind | None]
"""The timings of each kind a repo's runs read, none for a kind with fewer
than `FEW` in all repos."""


def _figures(db: Session, runs: Sequence[_Run], last: int) -> _Figures:
    asked = {(kind, run.repo) for run in runs for kind in run.kinds or ()}
    own = _last(db, sorted(pair for pair in asked if pair[1] is not None), last)
    apart = {pair for pair in asked if len(own.get(pair, ())) < OWN}
    every = _last(
        db, [(kind, None) for kind in sorted({kind for kind, _ in apart})], last
    )
    figures: _Figures = {}
    for pair in asked:
        timings = every[pair[0], None] if pair in apart else own[pair]
        figures[pair] = _Kind(timings) if len(timings) >= FEW else None
    return figures


def _last(
    db: Session, pairs: Sequence[tuple[str, str | None]], last: int
) -> dict[tuple[str, str | None], tuple[_Timing, ...]]:
    """The last timings of each kind, the newest first: the `last` that were
    listed ahead and the `last` that were not, a repo's own where the pair
    names one. `pairs` name a repo each, or none does.

    A kind's listed and unlisted timings are read apart, so that each read
    ends at its `last` rows of an index, however long the kind's history
    and however few of them the repo's or of one listing.
    """
    if not pairs:
        return {}
    kinds = (
        func.unnest(
            literal([kind for kind, _ in pairs], ARRAY(Text)),
            literal([repo for _, repo in pairs], ARRAY(Text)),
        )
        .table_valued(column("kind", Text), column("repo", Text))
        .render_derived(name="kinds")
    )
    began = values(column("listed", Boolean), name="began").data([(True,), (False,)])
    of_kind = (
        select(
            StepTiming.ended_at,
            StepTiming.id,
            StepTiming.duration,
            StepTiming.listed_ahead,
        )
        .where(
            StepTiming.kind_code == kinds.c.kind,
            StepTiming.listed_ahead == began.c.listed,
        )
        .order_by(StepTiming.ended_at.desc(), StepTiming.id.desc())
        .limit(last)
    )
    if pairs[0][1] is not None:
        of_kind = of_kind.where(StepTiming.repo == kinds.c.repo)
    timings = of_kind.lateral("timings")
    found: dict[tuple[str, str | None], list[tuple[datetime, int, _Timing]]] = {
        pair: [] for pair in pairs
    }
    for row in db.execute(
        select(kinds.c.kind, kinds.c.repo, timings)
        .select_from(kinds)
        .join(began, true())
        .join(timings, true())
    ):
        found[row.kind, row.repo].append(
            (row.ended_at, row.id, _Timing(row.duration, row.listed_ahead))
        )
    return {
        pair: tuple(
            timing
            for *_, timing in sorted(
                rows, key=lambda row: (row[0], row[1]), reverse=True
            )
        )
        for pair, rows in found.items()
    }


def _estimate(
    run: _Run, figures: _Figures, *, now: datetime, window: int, running: int
) -> WorkEstimate | None:
    active = [step for step in run.steps if step.state_code == ProgressState.ACTIVE]
    seconds, outrun = _left(run, figures, now=now, window=window, running=running)
    longer = None
    if outrun:
        longer = LongerThanUsual.OUTRUN
    elif any(step.marked for step in active):
        longer = LongerThanUsual.MARKED
    if seconds is None and longer is None:
        return None
    return WorkEstimate(
        work_id=run.id,
        seconds=seconds,
        longer_than_usual=longer,
        kind=active[0].kind_code if active else None,
        ran_seconds=(
            None
            if run.started_at is None
            else max(0, int((now - run.started_at).total_seconds()))
        ),
    )


def _left(
    run: _Run, figures: _Figures, *, now: datetime, window: int, running: int
) -> tuple[float | None, bool]:
    """The seconds a run still takes, none where it has no estimate, and
    whether a running step has outrun every timing it is read against, in
    which case no time is left to give either."""
    kinds = run.kinds
    if kinds is None:
        return None, False
    priced: dict[str, tuple[_Kind, float, float]] = {}
    for kind in kinds:
        timings = figures[kind, run.repo]
        price = None if timings is None else timings.price(window)
        if timings is None or price is None:
            return None, False
        priced[kind] = (timings, *price)
    seconds = 0.0
    for step in run.left:
        assert step.kind_code is not None
        of_kind, cost, _ = priced[step.kind_code]
        if step.state_code == ProgressState.PENDING:
            seconds += cost
            continue
        assert step.started_at is not None
        since = max(step.started_at, run.turn_started_at or step.started_at)
        ran = max(0.0, (now - since).total_seconds())
        still = of_kind.still(step.listed_ahead, ran, running)
        if not still:
            return None, True
        seconds += median(still)
    for kind in run.owing:
        seconds += priced[kind][2]
    return seconds, False
