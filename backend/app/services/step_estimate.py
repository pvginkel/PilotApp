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

The run's row of the figures is the whole run's: its work items, those on the
running one's conversation, the running one alone where it has none. Its
time so far is their Step Timings and its running steps' time run, which the
alert's sentence says too; its normal every step on the list listed ahead at
its kind's price as the timings stood at the run's start, its first work
item's first turn, so that it grows only as the list gains a step; its slow
normal times a set factor (F156.13).

A kind's timings are read at two levels. The price, and the repeats' share
with it, reads the repo's own once the repo's window holds one listed ahead,
all repos' until then; a running step is read against the repo's own once
the repo holds `OWN` of the kind, all repos' until then, counted among those
that had ended when it began. A kind with fewer than `FEW` in all repos
gives neither. A timing whose listing is unknown counts in none of it.

Nothing here reads a step's code or label, a code only matched to its own
in the run's other work items' lists, or orders two kinds (F92.13), and no
estimate is stored (F156.10).
"""

import math
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from statistics import fmean, median, quantiles
from typing import Any

from sqlalchemy import (
    Boolean,
    ColumnElement,
    Row,
    Select,
    Subquery,
    column,
    func,
    literal_column,
    null,
    or_,
    select,
    true,
    union,
    union_all,
    values,
)
from sqlalchemy.orm import Session, aliased

from app.models import Item, ProgressStep, StepTiming, Turn
from app.models import Session as AgentSession
from app.models.reference import ProgressState, SessionState
from app.models.step import repo_of_work
from app.schemas.timeline import LongerThanUsual

FEW = 5
"""The timings below which a kind gives no estimate, counted in all repos,
and below which the timings that began as the running step did give way to
the kind's last ones whole."""

OWN = 10
"""The timings of a kind at which a running step is read against its
repo's own in all repos' place."""


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
    while those it is drawn from hold fewer: its kind's, its repo's own or
    those that began as it did."""

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
class RunFigures:
    """The run's row of the figures on hover or press (F156.13): its time so
    far, and the normal and the slow of its list, priced as the timings stood
    at its start, none of it by phases."""

    so_far_seconds: float
    """The durations of the Step Timings of the run's work items and its
    running steps' time run."""
    normal_seconds: float
    """Each step on its list listed ahead at its kind's price, as the
    timings stood at the run's start; a step not listed ahead adds nothing,
    its cost in the price."""
    slow_seconds: float
    """`normal_seconds` times the run's slow factor."""

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


@dataclass(frozen=True)
class WorkEstimate:
    """What a running work item's badge shows."""

    work_id: uuid.UUID
    seconds: float | None
    """The time left as the rules sum it, which `minutes` rounds and
    `project_estimate` compares; none where none shows."""
    longer_than_usual: LongerThanUsual | None
    marked: bool
    """Whether the workflow marks a running step, which the alert's sentence
    then says, outrun or not (F156.14)."""
    kind: str | None
    """The kind of the first running step on the list, as published; none
    where no step runs or it has none."""
    ran_seconds: int
    """The time the run has taken so far, in whole seconds, as its row of
    the figures counts it, which the alert's sentence says (F156.14)."""
    step_figures: tuple[StepFigures, ...]
    """The row of each running step, in the list's order, of those whose
    kind had at least `FEW` timings in all repos when it began."""
    run_figures: RunFigures | None
    """The run's row; none on a list of one step or one with no step
    listed ahead, and none where a step listed ahead has no kind or its kind
    had no price at the run's start."""

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
    slow_factor: float,
) -> dict[uuid.UUID, WorkEstimate]:
    """What the badge of each work item among `work_ids` shows at `now`, in
    their order; one that shows nothing is left out: one whose Session is
    not `running`, one that is done, one with no step left to do, and one
    with no estimate whose running steps the workflow has not marked.
    `window` is the number of a kind's last timings its price reads,
    `running` the number of those that had ended when a running step began
    that it is read against, `slow_factor` what the run's normal is
    multiplied by for its slow."""
    # At least `OWN` of each listing, so that the ten and the five are counted
    # off rows the settings do not cut.
    read, timings = _read(db, work_ids, max(window, running, OWN))
    figures = _figures(read, timings, window)
    runs = {run.id: run for run in read}
    estimates = {}
    for work_id in work_ids:
        if work_id not in runs:
            continue
        estimate = _estimate(
            runs[work_id],
            figures,
            now=now,
            window=window,
            running=running,
            slow_factor=slow_factor,
        )
        if estimate is not None:
            estimates[work_id] = estimate
    return estimates


class StepEstimates:
    """The estimate under its settings (F156.10): `window`, the number of a
    kind's last timings its price reads, and `running`, the number of those
    that had ended when a running step began that it is read against, both
    counted in steps; and `slow_factor`, what the run's normal is multiplied
    by for its slow (F156.13)."""

    def __init__(self, window: int, running: int, slow_factor: float) -> None:
        self._window = window
        self._running = running
        self._slow_factor = slow_factor

    def of(
        self, db: Session, work_ids: Collection[uuid.UUID], now: datetime
    ) -> dict[uuid.UUID, WorkEstimate]:
        """`work_estimates` of `work_ids` at `now`."""
        return work_estimates(
            db,
            work_ids,
            now=now,
            window=self._window,
            running=self._running,
            slow_factor=self._slow_factor,
        )


@dataclass(frozen=True)
class _Step:
    """A step of a run's list, as the estimate reads it."""

    code: str
    state_code: ProgressState
    kind_code: str | None
    started_at: datetime | None
    listed_ahead: bool | None
    marked: bool | None


@dataclass(frozen=True)
class _Run:
    """An open work item whose Session runs, with its list in order, and
    what its run holds beside: the work items on its conversation, the work
    item alone where it has none."""

    id: uuid.UUID
    turn_started_at: datetime | None
    repo: str | None
    steps: tuple[_Step, ...]
    started: datetime | None
    """The run's start: the start of its first work item's first turn."""
    timed: int
    """The seconds of the Step Timings its run's work items wrote."""
    listings: dict[str, bool]
    """Whether the run's other work items listed a step ahead, by its code,
    where one knows: the earliest that does."""

    @cached_property
    def left(self) -> list[_Step]:
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
        after: _Step | None = None
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
        step: _Step,
        began: datetime,
        after: _Step | None,
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
    def active(self) -> list[_Step]:
        """The running steps, in the list's order."""
        return [step for step in self.steps if step.state_code == ProgressState.ACTIVE]

    def began(self, step: _Step) -> "_Read | None":
        """The read of the timings the running `step` is read against, those
        of its kind that had ended when it began; none where it has no
        kind."""
        if step.kind_code is None:
            return None
        assert step.started_at is not None
        return _Read(step.kind_code, self.repo, step.started_at)

    @cached_property
    def priced(self) -> list[str] | None:
        """The kind of each step the run's normal prices, those on the list
        listed ahead; none on a list of one step, or where the run has no
        start or such a step has no kind."""
        if len(self.steps) < 2 or self.started is None:
            return None
        kinds = []
        for step in self.steps:
            if not self._listed(step):
                continue
            if step.kind_code is None:
                return None
            kinds.append(step.kind_code)
        return kinds

    def _listed(self, step: _Step) -> bool:
        """Whether `step` stood on the run's list ahead: as its listing says,
        a step never begun standing pending; a begun one whose listing this
        work item does not know, one a continuation's first list brings, as
        the run's other work items listed it, and listed where none knows."""
        if step.listed_ahead is not None:
            return step.listed_ahead
        if step.started_at is None:
            return True
        return self.listings.get(step.code, True)

    @cached_property
    def reads(self) -> set["_Read"]:
        """The reads of the timings the estimate makes: each kind it prices
        as its timings stand, none where it prices nothing, each running
        step's kind as they stood when it began, and each kind the run's
        normal prices as they stood at the run's start."""
        reads = {_Read(kind, self.repo, None) for kind in self.kinds or ()}
        for step in self.active:
            began = self.began(step)
            if began is not None:
                reads.add(began)
        reads.update(_Read(kind, self.repo, self.started) for kind in self.priced or ())
        return reads

    def ran(self, step: _Step, now: datetime) -> float:
        """The seconds the running `step` has run at `now`, by Pilot's clock,
        from the later of its start and the start of the running turn."""
        assert step.started_at is not None
        since = max(step.started_at, self.turn_started_at or step.started_at)
        return max(0.0, (now - since).total_seconds())

    def so_far(self, now: datetime) -> float:
        """The seconds the run has taken at `now`: its work items' Step
        Timings and its running steps' time run."""
        return self.timed + sum(self.ran(step, now) for step in self.active)


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


@dataclass(frozen=True)
class _Timing:
    duration: int
    listed: bool


@dataclass(frozen=True)
class _Kind:
    """A kind's last timings at a read, the newest first, at the level of
    each use: the repo's own or all repos'."""

    priced: tuple[_Timing, ...]
    """Those its price reads: the repo's own where its window holds one
    listed ahead, all repos' where it holds none."""
    read_against: tuple[_Timing, ...]
    """Those a running step is read against: the repo's own where the repo
    holds `OWN` of them, all repos' until then."""

    def price(self, window: int) -> tuple[float, float] | None:
        """A listed step's price and its repeats' share; none where the
        window holds no timing that was listed ahead."""
        last = self.priced[:window]
        listed = [timing.duration for timing in last if timing.listed]
        if not listed:
            return None
        price = sum(timing.duration for timing in last) / len(listed)
        return price, max(0.0, price - fmean(listed))

    def against(self, listed: bool | None, running: int) -> tuple[_Timing, ...]:
        """The timings a running step whose listing is `listed` is read
        against: the last `running` that began as it did, the kind's last
        taken whole where fewer than `FEW` began as it did."""
        timings = self.read_against
        alike = tuple(timing for timing in timings if timing.listed is listed)
        return (alike if len(alike) >= FEW else timings)[:running]


_Figures = dict[_Read, _Kind | None]
"""The timings of each read, none for a kind with fewer than `FEW` in all
repos."""


def _lists(timings: tuple[_Timing, ...], window: int) -> bool:
    """Whether the window of `timings` holds one that was listed ahead."""
    return any(timing.listed for timing in timings[:window])


_Timings = dict[_Read, tuple[_Timing, ...]]
"""The last timings of each read, the newest first: the `last` that were
listed ahead and the `last` that were not."""


def _figures(runs: Sequence[_Run], timings: _Timings, window: int) -> _Figures:
    figures: _Figures = {}
    for read in {read for run in runs for read in run.reads}:
        mine = () if read.repo is None else timings[read]
        everywhere = timings[read.everywhere]
        figures[read] = (
            _Kind(
                priced=mine if _lists(mine, window) else everywhere,
                read_against=mine if len(mine) >= OWN else everywhere,
            )
            if len(everywhere) >= FEW
            else None
        )
    return figures


_READ_LENGTH = 5_700
"""The longest `_read()` compiles to for PostgreSQL: one statement over 2,000
characters, kept whole so that an estimate reads one snapshot of the
record."""


def _read(
    db: Session, work_ids: Collection[uuid.UUID], last: int
) -> tuple[list[_Run], _Timings]:
    """Those of `work_ids` that are open, whose Session is `running` and has
    a step left to do, each with its whole list and its run's start, its
    Step Timings and its other work items' listings; and the last timings of
    every read its estimate can make, in its repo's own and in all repos',
    each kind on its list as they stand, as they stood at its start and as
    they stood when each running step began.

    One statement, so that an estimate reads one snapshot of the record: a
    progress write commits a list's steps and the Step Timings of those it
    ends at once, and statements of their own read on either side of the
    commit.
    """
    if not work_ids:
        return [], {}
    run, part = aliased(AgentSession), aliased(AgentSession)
    # A Session with no conversation is a run of its own.
    of_run = or_(part.id == run.id, part.conversation_id == run.conversation_id)
    started = (
        select(func.min(Turn.started_at))
        .select_from(Turn)
        .join(part, part.id == Turn.session_id)
        .where(of_run)
        .scalar_subquery()
    )
    # A seeded timing hangs on the Work that ran the seed: only the live
    # ones, which hold their step's code, are the run's.
    timed = (
        select(func.coalesce(func.sum(StepTiming.duration), 0))
        .select_from(StepTiming)
        .join(part, part.id == StepTiming.work_id)
        .where(of_run, StepTiming.code.is_not(None))
        .scalar_subquery()
    )
    running = (
        select(
            run.id,
            run.conversation_id,
            run.turn_started_at,
            repo_of_work(run.id).scalar_subquery().label("repo"),
            started.label("started"),
            timed.label("timed"),
        )
        .join(Item, Item.id == run.id)
        .where(
            run.id.in_(list(work_ids)),
            run.state_code == SessionState.RUNNING,
            Item.done_at.is_(None),
        )
        .cte("runs")
    )
    # The runs' work items, and the others on their conversations.
    member = aliased(AgentSession)
    members = union(
        select(running.c.id, running.c.conversation_id),
        select(member.id, member.conversation_id).join(
            running, running.c.conversation_id == member.conversation_id
        ),
    ).subquery("members")
    steps = (
        select(
            ProgressStep.work_id,
            ProgressStep.code,
            ProgressStep.position,
            ProgressStep.state_code,
            ProgressStep.kind_code,
            ProgressStep.started_at,
            ProgressStep.listed_ahead,
            ProgressStep.marked,
            members.c.conversation_id.label("conversation"),
            Item.seq,
        )
        .join(members, members.c.id == ProgressStep.work_id)
        .join(Item, Item.id == ProgressStep.work_id)
        .where(
            or_(
                ProgressStep.work_id.in_(select(running.c.id)),
                ProgressStep.listed_ahead.is_not(None),
            )
        )
        .cte("steps")
    )
    own_steps = steps.join(running, running.c.id == steps.c.work_id)
    kind = steps.c.kind_code.label("kind")
    reads = union(
        select(kind, running.c.repo, null().label("as_of")).select_from(own_steps),
        select(kind, running.c.repo, steps.c.started_at)
        .select_from(own_steps)
        .where(steps.c.state_code == ProgressState.ACTIVE),
        select(kind, running.c.repo, running.c.started).select_from(own_steps),
    ).cte("reads")
    known = reads.c.kind.is_not(None)
    own = select(reads).where(known, reads.c.repo.is_not(None)).subquery("own")
    every = (
        select(reads.c.kind, reads.c.as_of).where(known).distinct().subquery("every")
    )
    rows = union_all(
        select(
            steps.c.work_id,
            steps.c.code,
            steps.c.state_code,
            steps.c.kind_code,
            steps.c.started_at,
            steps.c.listed_ahead,
            steps.c.marked,
            steps.c.conversation,
            steps.c.seq,
            steps.c.position,
            running.c.id.label("run"),
            running.c.turn_started_at,
            running.c.repo,
            running.c.started,
            running.c.timed,
            *_NO_TIMING,
        ).select_from(steps.outerjoin(running, running.c.id == steps.c.work_id)),
        _last(own, own.c.repo, last),
        _last(every, None, last),
    ).subquery("rows")
    run_rows: dict[uuid.UUID, Row[Any]] = {}
    lists: dict[uuid.UUID, list[_Step]] = {}
    listings: dict[str, dict[str, bool]] = {}
    found: dict[_Read, list[tuple[datetime, int, _Timing]]] = {}
    for row in db.execute(
        select(rows)
        .order_by(rows.c.seq, rows.c.work_id, rows.c.position)
        .execution_options(max_statement_length=_READ_LENGTH)
    ):
        if row.read_kind is not None:
            # Each read stands once with no timing found for a listing.
            of_read = found.setdefault(
                _Read(row.read_kind, row.read_repo, row.read_as_of), []
            )
            if row.timing_id is not None:
                of_read.append(
                    (
                        row.timing_ended_at,
                        row.timing_id,
                        _Timing(row.duration, row.timing_listed),
                    )
                )
            continue
        step = _Step(
            row.code,
            row.state_code,
            row.kind_code,
            row.started_at,
            row.listed_ahead,
            row.marked,
        )
        if row.run is not None:
            run_rows.setdefault(row.run, row)
            lists.setdefault(row.run, []).append(step)
        else:
            # Another work item's, by its conversation, the earliest first.
            assert row.conversation is not None and row.listed_ahead is not None
            listings.setdefault(row.conversation, {}).setdefault(
                row.code, row.listed_ahead
            )
    runs = [
        _Run(
            work_id,
            row.turn_started_at,
            row.repo,
            tuple(lists[work_id]),
            started=row.started,
            timed=row.timed,
            listings=(
                {} if row.conversation is None else listings.get(row.conversation, {})
            ),
        )
        for work_id, row in run_rows.items()
    ]
    timings = {
        read: tuple(
            timing
            for *_, timing in sorted(
                of_read, key=lambda each: (each[0], each[1]), reverse=True
            )
        )
        for read, of_read in found.items()
    }
    return [run for run in runs if run.left], timings


_NO_TIMING = tuple(
    null().label(name)
    for name in (
        "read_kind",
        "read_repo",
        "read_as_of",
        "timing_id",
        "timing_ended_at",
        "duration",
        "timing_listed",
    )
)
"""A step's row's columns of a timing's."""


def _last(
    reads: Subquery, repo: ColumnElement[str] | None, last: int
) -> Select[*tuple[Any, ...]]:
    """The rows of the last timings of each of `reads`, kinds as they stood at
    an `as_of` or as they stand, in the repo `repo` names, or in all repos
    where it is none: the `last` that were listed ahead and the `last` that
    were not, and each read once with none for a listing with none.

    A kind's listed and unlisted timings are read apart, so that each read
    ends at its `last` rows of an index, however long the kind's history
    and however few of them the repo's, of one listing or ended by its
    `as_of`.
    """
    began = values(column("listed", Boolean), name="began").data([(True,), (False,)])
    of_kind = (
        select(
            StepTiming.ended_at,
            StepTiming.id,
            StepTiming.duration,
            StepTiming.listed_ahead,
        )
        .where(
            StepTiming.kind_code == reads.c.kind,
            StepTiming.listed_ahead == began.c.listed,
            # A timing that ended at the instant a step began had ended when
            # it began: one publication ends a step and begins the next.
            StepTiming.ended_at
            <= func.coalesce(reads.c.as_of, literal_column("'infinity'")),
        )
        .order_by(StepTiming.ended_at.desc(), StepTiming.id.desc())
        .limit(last)
    )
    if repo is not None:
        of_kind = of_kind.where(StepTiming.repo == repo)
    timings = of_kind.lateral("timings")
    return (
        select(
            *_NO_STEP,
            reads.c.kind.label("read_kind"),
            (null() if repo is None else repo).label("read_repo"),
            reads.c.as_of.label("read_as_of"),
            timings.c.id.label("timing_id"),
            timings.c.ended_at.label("timing_ended_at"),
            timings.c.duration,
            timings.c.listed_ahead.label("timing_listed"),
        )
        .select_from(reads)
        .join(began, true())
        .outerjoin(timings, true())
    )


_NO_STEP = tuple(
    null().label(name)
    for name in (
        "work_id",
        "code",
        "state_code",
        "kind_code",
        "started_at",
        "listed_ahead",
        "marked",
        "conversation",
        "seq",
        "position",
        "run",
        "turn_started_at",
        "repo",
        "started",
        "timed",
    )
)
"""A timing's row's columns of a step's and its run's."""


def _estimate(
    run: _Run,
    figures: _Figures,
    *,
    now: datetime,
    window: int,
    running: int,
    slow_factor: float,
) -> WorkEstimate | None:
    active = run.active
    seconds, outrun = _left(run, figures, now=now, window=window, running=running)
    marked = any(step.marked for step in active)
    longer = None
    if outrun:
        longer = LongerThanUsual.OUTRUN
    elif marked:
        longer = LongerThanUsual.MARKED
    if seconds is None and longer is None:
        return None
    return WorkEstimate(
        work_id=run.id,
        seconds=seconds,
        longer_than_usual=longer,
        marked=marked,
        kind=active[0].kind_code if active else None,
        ran_seconds=int(run.so_far(now)),
        step_figures=tuple(
            row
            for step in active
            if (row := _row(run, step, figures, now=now, running=running)) is not None
        ),
        run_figures=_run_row(
            run, figures, now=now, window=window, slow_factor=slow_factor
        ),
    )


def _run_row(
    run: _Run,
    figures: _Figures,
    *,
    now: datetime,
    window: int,
    slow_factor: float,
) -> RunFigures | None:
    """The run's row of the figures; none where it prices no list, or no
    step on it was listed ahead, or a kind it prices had no price at the
    run's start."""
    kinds = run.priced
    if not kinds:
        return None
    normal = 0.0
    for kind in kinds:
        of_kind = figures[_Read(kind, run.repo, run.started)]
        price = None if of_kind is None else of_kind.price(window)
        if price is None:
            return None
        normal += price[0]
    return RunFigures(
        so_far_seconds=run.so_far(now),
        normal_seconds=normal,
        slow_seconds=normal * slow_factor,
    )


def _against(
    run: _Run, step: _Step, figures: _Figures, running: int
) -> tuple[_Timing, ...] | None:
    """The timings the running `step` is read against, of those of its kind
    that had ended when it began; none where its kind had fewer than `FEW`
    in all repos then, or it has none."""
    began = run.began(step)
    of_kind = None if began is None else figures[began]
    return None if of_kind is None else of_kind.against(step.listed_ahead, running)


def _row(
    run: _Run, step: _Step, figures: _Figures, *, now: datetime, running: int
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
    """The seconds a run still takes, none where it has no estimate or a
    running step has outrun every timing it is read against; and whether a
    running step shows outrun: any that has where the run has an estimate
    but for the outrun, a marked one alone where it has none (D250). A
    running step whose kind had fewer than `FEW` timings in all repos when
    it began leaves no estimate."""
    still: dict[_Step, list[float]] = {}
    outrun: list[_Step] = []
    unread = False
    for step in run.active:
        longer = _longer(run, step, figures, now=now, running=running)
        if longer is None:
            unread = True
        elif longer:
            still[step] = longer
        else:
            outrun.append(step)
    priced = _prices(run, figures, window)
    if priced is None or unread:
        return None, any(step.marked for step in outrun)
    if outrun:
        return None, True
    seconds = 0.0
    for step in run.left:
        assert step.kind_code is not None
        if step.state_code == ProgressState.PENDING:
            seconds += priced[step.kind_code][0]
        else:
            seconds += median(still[step])
    for kind in run.owing:
        seconds += priced[kind][1]
    return seconds, False


def _longer(
    run: _Run, step: _Step, figures: _Figures, *, now: datetime, running: int
) -> list[float] | None:
    """What each timing the running `step` is read against that ran at least
    as long as it has still took; none where it is read against nothing,
    empty where it has outrun every one."""
    against = _against(run, step, figures, running)
    if against is None:
        return None
    ran = run.ran(step, now)
    return [timing.duration - ran for timing in against if timing.duration >= ran]


def _prices(
    run: _Run, figures: _Figures, window: int
) -> dict[str, tuple[float, float]] | None:
    """The price and the repeats' share of each kind the run's time left
    reads, as its timings stand; none where a step left to do has no kind
    or a kind has no price."""
    kinds = run.kinds
    if kinds is None:
        return None
    priced: dict[str, tuple[float, float]] = {}
    for kind in kinds:
        timings = figures[_Read(kind, run.repo, None)]
        price = None if timings is None else timings.price(window)
        if price is None:
            return None
        priced[kind] = price
    return priced
