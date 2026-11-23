"""The time a running work item still takes (F156.4 to F156.7): an estimate
from the steps its run publishes and the Step Timings of their kinds.

The time left is the sum of three parts. A step not begun counts at its
kind's price: the total time of the kind's window, its last timings by their
end, divided by the number of them that were listed ahead, so the mean with
the unlisted repeats in it. A running step counts at the median of what
longer steps still took: of the last timings of its kind that began as it
did, listed ahead or not, those that ran at least as long as it has, each
less the time it has run; the kind's last timings taken whole where fewer
than `FEW` began as it did or its listing is unknown. Those it is read
against are of the timings that had ended when it began, so that they hold
still while it runs (F156.5), and they give its row of the figures on hover
or press (F156.13). And a step listed ahead owes the repeats' share of its
kind's price, the price less the mean of the window's listed timings, while
it runs and, done, until the next listed step on the list is done or an
unlisted step of its kind has begun after it.

A kind's timings are the repo's own once the repo holds `OWN` of the kind,
all repos' until then, for the price and the running step alike, a running
step's counted among those that had ended when it began. A timing whose
listing is unknown counts in none of it.

Nothing here reads a step's code or label, or orders two kinds (F92.13), and
no estimate is stored (F156.10).
"""

import math
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from statistics import fmean, median, quantiles

from sqlalchemy import (
    Boolean,
    DateTime,
    Text,
    column,
    func,
    literal,
    literal_column,
    select,
    true,
    values,
)
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
class StepFigures:
    """A running step's row of the figures on hover or press (F156.13): its
    time run, and the normal, the slow and the longest of the timings it is
    read against, of those of its kind that had ended when it began."""

    kind: str
    """Its kind, as published."""
    so_far_seconds: float
    """The time it has run, as the time left counts it (F156.5)."""
    normal_seconds: float
    """The median of the timings' durations."""
    slow_seconds: float
    """Their 90th percentile."""
    longest_seconds: int
    """The longest of them, past which the badge turns red (F156.7)."""
    timings: int
    """How many timings it is read against: the setting's number, fewer
    while its kind's history holds fewer."""

    @property
    def so_far_minutes(self) -> int:
        """`so_far_seconds` as the table words it."""
        return _clock_minutes(self.so_far_seconds)

    @property
    def normal_minutes(self) -> int:
        """`normal_seconds` as the table words it."""
        return _usual_minutes(self.normal_seconds)

    @property
    def slow_minutes(self) -> int:
        """`slow_seconds` as the table words it."""
        return _usual_minutes(self.slow_seconds)

    @property
    def longest_minutes(self) -> int:
        """`longest_seconds` as the line under the table words it."""
        return _clock_minutes(self.longest_seconds)


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
    step_figures: tuple[StepFigures, ...]
    """The row of each running step, in the list's order, of those whose
    kind had at least `FEW` timings in all repos when it began."""

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


def _clock_minutes(seconds: float) -> int:
    """A time run as the figures word it (F156.13): to the nearest
    minute."""
    return _nearest(seconds / 60)


def _usual_minutes(seconds: float) -> int:
    """A normal or a slow time as the figures word it (F156.13): to the
    nearest minute under an hour, to the nearest five minutes from one."""
    minutes = seconds / 60
    if minutes < 60:
        return _nearest(minutes)
    return _nearest(minutes / 5) * 5


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
    `running` the number of those that had ended when a running step began
    that it is read against."""
    runs = {run.id: run for run in _runs(db, work_ids)}
    # At least `OWN` of each listing, so that the ten and the five are counted
    # off rows the settings do not cut.
    figures = _figures(db, list(runs.values()), max(window, running, OWN))
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
    reads, and `running`, the number of those that had ended when a running
    step began that it is read against."""

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
        """The kinds whose prices the estimate reads; none where a step
        left to do has no kind."""
        kinds = set(self.owing)
        for step in self.left:
            if step.kind_code is None:
                return None
            kinds.add(step.kind_code)
        return kinds

    @cached_property
    def active(self) -> list[ProgressStep]:
        """The running steps, in the list's order."""
        return [step for step in self.steps if step.state_code == ProgressState.ACTIVE]

    def began(self, step: ProgressStep) -> "_Read | None":
        """The read of the timings the running `step` is read against, those
        of its kind that had ended when it began; none where it has no
        kind."""
        if step.kind_code is None:
            return None
        assert step.started_at is not None
        return _Read(step.kind_code, self.repo, step.started_at)

    @cached_property
    def reads(self) -> set["_Read"]:
        """The reads of the timings the estimate makes: each kind it prices
        as its timings stand, none where it prices nothing, and each running
        step's kind as they stood when it began."""
        reads = {_Read(kind, self.repo, None) for kind in self.kinds or ()}
        for step in self.active:
            began = self.began(step)
            if began is not None:
                reads.add(began)
        return reads

    def ran(self, step: ProgressStep, now: datetime) -> float:
        """The seconds the running `step` has run at `now`, by Pilot's clock,
        from the later of its start and the start of the running turn."""
        assert step.started_at is not None
        since = max(step.started_at, self.turn_started_at or step.started_at)
        return max(0.0, (now - since).total_seconds())


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
class _Read:
    """A kind's timings as a repo's runs read them: the repo's own where
    `repo` names one, all repos' where it is none; those that had ended by
    `as_of`, every one where it is none."""

    kind: str
    repo: str | None
    as_of: datetime | None

    @property
    def everywhere(self) -> "_Read":
        """The same read in all repos."""
        return _Read(self.kind, None, self.as_of)


def _in_order(reads: Iterable[_Read]) -> list[_Read]:
    """`reads` in one order, whatever the order given."""
    return sorted(
        reads,
        key=lambda read: (
            read.kind,
            read.repo or "",
            math.inf if read.as_of is None else read.as_of.timestamp(),
        ),
    )


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

    def against(self, listed: bool | None, running: int) -> tuple[_Timing, ...]:
        """The timings a running step whose listing is `listed` is read
        against: the last `running` that began as it did, the kind's last
        taken whole where fewer than `FEW` began as it did."""
        alike = tuple(timing for timing in self.timings if timing.listed is listed)
        return (alike if len(alike) >= FEW else self.timings)[:running]


_Figures = dict[_Read, _Kind | None]
"""The timings of each read, none for a kind with fewer than `FEW` in all
repos."""


def _figures(db: Session, runs: Sequence[_Run], last: int) -> _Figures:
    asked = {read for run in runs for read in run.reads}
    own = _last(db, _in_order(read for read in asked if read.repo is not None), last)
    apart = {read for read in asked if len(own.get(read, ())) < OWN}
    every = _last(db, _in_order({read.everywhere for read in apart}), last)
    figures: _Figures = {}
    for read in asked:
        timings = every[read.everywhere] if read in apart else own[read]
        figures[read] = _Kind(timings) if len(timings) >= FEW else None
    return figures


def _last(
    db: Session, reads: Sequence[_Read], last: int
) -> dict[_Read, tuple[_Timing, ...]]:
    """The last timings of each read, the newest first: the `last` that were
    listed ahead and the `last` that were not. `reads` name a repo each, or
    none does.

    A kind's listed and unlisted timings are read apart, so that each read
    ends at its `last` rows of an index, however long the kind's history
    and however few of them the repo's, of one listing or ended by its
    `as_of`.
    """
    if not reads:
        return {}
    kinds = (
        func.unnest(
            literal([read.kind for read in reads], ARRAY(Text)),
            literal([read.repo for read in reads], ARRAY(Text)),
            literal([read.as_of for read in reads], ARRAY(DateTime(timezone=True))),
        )
        .table_valued(
            column("kind", Text),
            column("repo", Text),
            column("as_of", DateTime(timezone=True)),
            with_ordinality="read",
        )
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
            # A timing that ended at the instant a step began had ended when
            # it began: one publication ends a step and begins the next.
            StepTiming.ended_at
            <= func.coalesce(kinds.c.as_of, literal_column("'infinity'")),
        )
        .order_by(StepTiming.ended_at.desc(), StepTiming.id.desc())
        .limit(last)
    )
    if reads[0].repo is not None:
        of_kind = of_kind.where(StepTiming.repo == kinds.c.repo)
    timings = of_kind.lateral("timings")
    found: dict[_Read, list[tuple[datetime, int, _Timing]]] = {
        read: [] for read in reads
    }
    for row in db.execute(
        select(kinds.c.read, timings)
        .select_from(kinds)
        .join(began, true())
        .join(timings, true())
    ):
        found[reads[row.read - 1]].append(
            (row.ended_at, row.id, _Timing(row.duration, row.listed_ahead))
        )
    return {
        read: tuple(
            timing
            for *_, timing in sorted(
                rows, key=lambda row: (row[0], row[1]), reverse=True
            )
        )
        for read, rows in found.items()
    }


def _estimate(
    run: _Run, figures: _Figures, *, now: datetime, window: int, running: int
) -> WorkEstimate | None:
    active = run.active
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
        step_figures=tuple(
            row
            for step in active
            if (row := _row(run, step, figures, now=now, running=running)) is not None
        ),
    )


def _against(
    run: _Run, step: ProgressStep, figures: _Figures, running: int
) -> tuple[_Timing, ...] | None:
    """The timings the running `step` is read against, of those of its kind
    that had ended when it began; none where its kind had fewer than `FEW`
    in all repos then, or it has none."""
    began = run.began(step)
    of_kind = None if began is None else figures[began]
    return None if of_kind is None else of_kind.against(step.listed_ahead, running)


def _row(
    run: _Run, step: ProgressStep, figures: _Figures, *, now: datetime, running: int
) -> StepFigures | None:
    """The running `step`'s row of the figures; none where it is read against
    nothing."""
    against = _against(run, step, figures, running)
    if against is None:
        return None
    assert step.kind_code is not None
    durations = [timing.duration for timing in against]
    return StepFigures(
        kind=step.kind_code,
        so_far_seconds=run.ran(step, now),
        normal_seconds=median(durations),
        slow_seconds=quantiles(durations, n=10, method="inclusive")[-1],
        longest_seconds=max(durations),
        timings=len(durations),
    )


def _left(
    run: _Run, figures: _Figures, *, now: datetime, window: int, running: int
) -> tuple[float | None, bool]:
    """The seconds a run still takes, none where it has no estimate, and
    whether a running step has outrun every timing it is read against, in
    which case no time is left to give either. A running step whose kind had
    fewer than `FEW` timings in all repos when it began leaves no estimate."""
    kinds = run.kinds
    if kinds is None:
        return None, False
    priced: dict[str, tuple[float, float]] = {}
    for kind in kinds:
        timings = figures[_Read(kind, run.repo, None)]
        price = None if timings is None else timings.price(window)
        if price is None:
            return None, False
        priced[kind] = price
    seconds = 0.0
    for step in run.left:
        assert step.kind_code is not None
        if step.state_code == ProgressState.PENDING:
            seconds += priced[step.kind_code][0]
            continue
        against = _against(run, step, figures, running)
        if against is None:
            return None, False
        ran = run.ran(step, now)
        still = [timing.duration - ran for timing in against if timing.duration >= ran]
        if not still:
            return None, True
        seconds += median(still)
    for kind in run.owing:
        seconds += priced[kind][1]
    return seconds, False
