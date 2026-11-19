"""The time a running work item still takes (F156.4 to F156.7): the price,
the running step, the repeats owed, no estimate, longer than usual and the
project's pick."""

import itertools
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Environment,
    Item,
    ProgressStep,
    Project,
    StepKind,
    StepTiming,
    Work,
)
from app.models.reference import ProgressState, SessionState
from app.services.step_estimate import (
    LongerThanUsual,
    WorkEstimate,
    project_estimate,
    work_estimates,
)
from tests.support.statements import sent

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
REPO = "example/Example"
OTHER_REPO = "example/Other"
MINUTE = 60

_numbers = itertools.count(1)


def _ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def _run(
    db: DbSession,
    project: Project,
    creator: models.Session,
    *,
    repo: str | None = REPO,
    environment: Environment | None = None,
    state: SessionState = SessionState.RUNNING,
    began: float = 240,
    turn: float = 240,
) -> uuid.UUID:
    """A worker's run of `project`, placed in `repo`, whose Session began
    `began` minutes ago and its turn `turn` minutes ago; its id."""
    work_id = uuid.uuid4()
    db.add_all(
        [
            Item(
                id=work_id,
                project_id=project.id,
                seq=1000 + next(_numbers),
                kind_code="work",
                title="Fixing the client for v4",
                created_by_session_id=creator.id,
            ),
            models.Session(
                id=work_id,
                project_id=project.id,
                environment_id=environment.id if environment else None,
                kind_code="work",
                cwd="/work/Example",
                token_hash=uuid.uuid4().hex * 2,
                state_code=state,
                started_at=_ago(began),
                turn_started_at=_ago(turn),
            ),
        ]
    )
    db.flush()
    db.add(
        Work(
            id=work_id,
            project_id=project.id,
            session_kind_code="work",
            autopilot=False,
            repo=repo,
        )
    )
    db.flush()
    return work_id


@dataclass(frozen=True)
class _Step:
    """A step of a list: `began` and `ended` in minutes before now."""

    kind: str | None
    state: ProgressState
    listed: bool | None = None
    began: float | None = None
    ended: float | None = None
    marked: bool | None = None


def _pending(kind: str | None) -> _Step:
    return _Step(kind, ProgressState.PENDING)


def _active(
    kind: str | None,
    ran: float,
    *,
    listed: bool | None = True,
    marked: bool | None = None,
) -> _Step:
    return _Step(kind, ProgressState.ACTIVE, listed, ran, marked=marked)


def _done(
    kind: str | None,
    began: float,
    *,
    listed: bool | None = True,
    marked: bool | None = None,
) -> _Step:
    return _Step(kind, ProgressState.DONE, listed, began, began - 1, marked)


def _kinds(db: DbSession, kinds: set[str]) -> None:
    for kind in kinds:
        if db.get(StepKind, kind) is None:
            db.add(StepKind(code=kind, name=kind))
    db.flush()


def _list(db: DbSession, work_id: uuid.UUID, steps: Sequence[_Step]) -> None:
    """`steps` as the Work's list, in order."""
    _kinds(db, {step.kind for step in steps if step.kind is not None})
    db.add_all(
        ProgressStep(
            work_id=work_id,
            code=f"step-{position}",
            label=f"Step {position}",
            position=position,
            state_code=step.state,
            started_at=None if step.began is None else _ago(step.began),
            ended_at=None if step.ended is None else _ago(step.ended),
            kind_code=step.kind,
            listed_ahead=step.listed,
            marked=step.marked,
        )
        for position, step in enumerate(steps, start=1)
    )
    db.flush()


def _timed(
    db: DbSession,
    work_id: uuid.UUID,
    kind: str,
    minutes: Sequence[float],
    *,
    listed: bool | None = True,
    repo: str | None = REPO,
    age: float = 1,
) -> None:
    """Timings of `kind` on the Work, one per figure of `minutes`: the first
    ended `age` days ago and each next a day before the one before it."""
    _kinds(db, {kind})
    db.add_all(
        StepTiming(
            work_id=work_id,
            kind_code=kind,
            ended_at=NOW - timedelta(days=age + older),
            duration=round(each * MINUTE),
            listed_ahead=listed,
            code=f"timed-{next(_numbers)}",
            repo=repo,
        )
        for older, each in enumerate(minutes)
    )
    db.flush()


def _estimates(
    db: DbSession,
    work_ids: Sequence[uuid.UUID],
    *,
    window: int = 20,
    running: int = 60,
) -> dict[uuid.UUID, WorkEstimate]:
    return work_estimates(db, work_ids, now=NOW, window=window, running=running)


def _minutes(estimate: WorkEstimate) -> float:
    assert estimate.seconds is not None
    return estimate.seconds / MINUTE


@pytest.fixture
def run(
    session: DbSession, project: Project, project_session: models.Session
) -> uuid.UUID:
    """A running work item placed in `REPO`, with no list yet."""
    return _run(session, project, project_session)


@pytest.fixture
def past(
    session: DbSession, project: Project, project_session: models.Session
) -> uuid.UUID:
    """A work item no test estimates, which the timings hang on."""
    return _run(session, project, project_session, state=SessionState.ENDED)


class TestWorkEstimates:
    def test_the_records_worked_example_comes_out_at_118_minutes(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Nine steps listed ahead, the first phase's two done, the second
        phase's `code-writer` running for 10 minutes and six not begun: 100
        minutes of steps not begun, 14 of the running step and 4 of repeats
        owed, the running `code-writer`'s 3 and the first review's 1."""
        # Each kind's window of 20: its listed timings, then its unlisted.
        for kind, listed, unlisted in (
            ("review", [7] * 16, [4] * 4),
            ("sweep", [7] * 12, [7.5] * 8),
            ("consult", [3] * 15, [3] * 5),
            ("test", [33] * 18, [18] * 2),
            ("docs", [16] * 20, []),
            ("wrap-up", [25] * 20, []),
        ):
            _timed(session, past, kind, listed)
            _timed(session, past, kind, unlisted, listed=False, age=1.5)
        _timed(session, past, "code-writer", [22] * 16)
        _timed(session, past, "code-writer", [12] * 4, listed=False, age=1.5)
        # Before the window: with its 16, the last 60 that were listed
        # ahead, 40 of them longer than 10 minutes.
        _timed(session, past, "code-writer", [24] * 8 + [30] * 16 + [8] * 20, age=30)
        _list(
            session,
            run,
            [
                _done("code-writer", 70),
                _done("review", 20),
                _active("code-writer", 10),
                _pending("review"),
                _pending("sweep"),
                _pending("consult"),
                _pending("test"),
                _pending("docs"),
                _pending("wrap-up"),
            ],
        )

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx(118)
        assert estimate.minutes == 120
        assert (estimate.longer_than_usual, estimate.kind) == (None, "code-writer")

    @pytest.mark.parametrize(
        "state",
        [state for state in SessionState if state is not SessionState.RUNNING],
    )
    def test_a_work_item_that_does_not_run_has_none(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
        state: SessionState,
    ) -> None:
        """Its marked step shows nothing either."""
        work_id = _run(session, project, project_session, state=state)
        _timed(session, past, "write", [20] * 10)
        _list(session, work_id, [_active("write", 5, marked=True)])

        assert _estimates(session, [work_id]) == {}

    def test_a_list_with_no_step_or_every_step_done_has_none(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        run: uuid.UUID,
        past: uuid.UUID,
    ) -> None:
        done = _run(session, project, project_session)
        _timed(session, past, "write", [20] * 10)
        _list(session, done, [_done("write", 30), _done("write", 20)])

        assert _estimates(session, [run, done]) == {}

    def test_a_step_left_to_do_with_no_kind_leaves_none(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 10)
        _list(session, run, [_active("write", 5), _pending(None)])

        assert _estimates(session, [run]) == {}

    def test_a_done_step_with_no_kind_is_no_matter(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 10)
        _list(session, run, [_done(None, 30), _pending("write")])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(20)

    def test_a_kind_with_fewer_than_five_timings_in_all_repos_leaves_none(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 10)
        _timed(session, past, "review", [8] * 2)
        _timed(session, past, "review", [8] * 2, repo=OTHER_REPO)
        _list(session, run, [_active("write", 5), _pending("review")])

        assert _estimates(session, [run]) == {}

        _timed(session, past, "review", [8], repo=None)

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(15 + 8)

    def test_a_window_with_no_listed_timing_leaves_none(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The listed timings before the window do not price the kind."""
        _timed(session, past, "write", [20] * 20, listed=False)
        _timed(session, past, "write", [20] * 20, age=40)
        _list(session, run, [_pending("write")])

        assert _estimates(session, [run]) == {}
        assert _estimates(session, [run], window=21) != {}

    def test_a_timing_whose_listing_is_unknown_counts_in_nothing(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Not among a kind's five, not in its window and not among those a
        running step is read against."""
        _timed(session, past, "review", [8] * 4)
        _timed(session, past, "review", [90] * 30, listed=None)
        _list(session, run, [_pending("review")])

        assert _estimates(session, [run]) == {}

        _timed(session, past, "review", [8], age=0.5)
        _timed(session, past, "write", [20] * 10)
        _timed(session, past, "write", [300] * 30, listed=None, age=0.5)
        _list_again(session, run, [_active("write", 5), _pending("review")])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(15 + 8)

    def test_a_step_not_begun_counts_at_the_windows_total_over_its_listed_timings(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The mean with the unlisted repeats in it, of the last 20 by their
        end and no timing before them."""
        _timed(session, past, "write", [20] * 16)
        _timed(session, past, "write", [10] * 4, listed=False, age=1.5)
        _timed(session, past, "write", [500] * 10, age=40)
        _timed(session, past, "write", [500] * 10, listed=False, age=40)
        _list(session, run, [_pending("write"), _pending("write")])

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx(2 * (16 * 20 + 4 * 10) / 16)
        assert estimate.kind is None

    def test_the_window_is_a_setting_counted_in_steps(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [10] * 5 + [40] * 5)
        _list(session, run, [_pending("write")])

        assert _minutes(_estimates(session, [run], window=5)[run]) == pytest.approx(10)
        assert _minutes(_estimates(session, [run], window=10)[run]) == pytest.approx(25)

    def test_two_timings_of_one_instant_stand_in_the_order_they_were_written(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The later written is the later of the two."""
        _timed(session, past, "write", [10] * 5 + [40] * 5)
        _timed(session, past, "write", [70])
        _list(session, run, [_pending("write")])

        assert _minutes(_estimates(session, [run], window=1)[run]) == pytest.approx(70)

    def test_a_repos_own_timings_count_once_it_has_ten_of_the_kind(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """All repos' until then, a timing of no repo among them; the tenth
        of its own leaves every other repo's out."""
        _timed(session, past, "write", [10] * 9)
        _timed(session, past, "write", [40] * 6, repo=OTHER_REPO, age=20)
        _timed(session, past, "write", [70] * 3, repo=None, age=30)
        _list(session, run, [_pending("write")])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(
            (9 * 10 + 6 * 40 + 3 * 70) / 18
        )

        _timed(session, past, "write", [10], age=0.5)

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(10)

    def test_the_repos_ten_count_no_timing_of_an_unknown_listing(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [10] * 9)
        _timed(session, past, "write", [10] * 5, listed=None)
        _timed(session, past, "write", [40] * 9, repo=OTHER_REPO)
        _list(session, run, [_pending("write")])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(25)

    def test_a_work_item_in_no_repo_reads_all_repos(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        work_id = _run(session, project, project_session, repo=None)
        _timed(session, past, "write", [10] * 10)
        _timed(session, past, "write", [40] * 10, repo=None)
        _list(session, work_id, [_pending("write")])

        assert _minutes(_estimates(session, [work_id])[work_id]) == pytest.approx(25)

    def test_a_work_item_with_no_repo_label_is_of_its_environments_repo(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        placed = Environment(
            id="example-other-1",
            name="Other-1",
            exempt=False,
            server_created_at=NOW,
            repo=OTHER_REPO,
        )
        session.add(placed)
        session.flush()
        work_id = _run(session, project, project_session, repo=None, environment=placed)
        _timed(session, past, "write", [10] * 10)
        _timed(session, past, "write", [40] * 10, repo=OTHER_REPO)
        _list(session, work_id, [_pending("write")])

        assert _minutes(_estimates(session, [work_id])[work_id]) == pytest.approx(40)

    def test_a_running_step_counts_at_the_median_of_what_longer_steps_still_took(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Of those that began as it did, those that ran no longer than it
        has left out, each less the time it has run."""
        _timed(session, past, "write", [5, 10, 14, 20, 30, 50])
        _timed(session, past, "write", [100] * 6, listed=False)
        _list(session, run, [_active("write", 10, listed=False)])

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx(90)
        assert estimate.kind == "write"

        _list_again(session, run, [_active("write", 12)])
        # The price's repeats' share, which a listed running step owes.
        share = (6 * 100 + sum([5, 10, 14, 20, 30, 50])) / 6 - 129 / 6

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx((8 + 18) / 2 + share)

    def test_a_timing_as_long_as_the_step_has_run_still_took_nothing(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [10] * 5)
        _list(session, run, [_active("write", 10)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual) == (0, None)
        assert estimate.minutes == 5

    @pytest.mark.parametrize("listed", [False, None])
    def test_fewer_than_five_that_began_as_it_did_or_a_listing_unknown_reads_them_whole(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID, listed: bool | None
    ) -> None:
        _timed(session, past, "write", [20] * 6)
        _timed(session, past, "write", [100] * 4, listed=False, age=1.5)
        _list(session, run, [_active("write", 10, listed=listed)])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(10)

    def test_five_that_began_as_it_did_are_read_alone(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 6)
        _timed(session, past, "write", [100] * 5, listed=False, age=1.5)
        _list(session, run, [_active("write", 10, listed=False)])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(90)

    def test_the_time_run_counts_from_the_later_of_the_steps_start_and_the_turns(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """A step resumed after a stop does not count the time it stood."""
        resumed = _run(session, project, project_session, turn=4)
        straight = _run(session, project, project_session, turn=100)
        _timed(session, past, "write", [30] * 10, listed=False)
        _timed(session, past, "write", [30] * 10, age=1.5)
        for work_id in (resumed, straight):
            _list(session, work_id, [_active("write", 10, listed=False)])

        estimates = _estimates(session, [resumed, straight])

        assert _minutes(estimates[resumed]) == pytest.approx(26)
        assert _minutes(estimates[straight]) == pytest.approx(20)

    def test_several_running_steps_add_up_and_the_first_on_the_list_names_the_kind(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [30] * 10, listed=False)
        _timed(session, past, "write", [30] * 10, age=1.5)
        _timed(session, past, "review", [8] * 10, listed=False)
        _timed(session, past, "review", [8] * 10, age=1.5)
        _list(
            session,
            run,
            [
                _active("review", 2, listed=False),
                _active("write", 10, listed=False),
            ],
        )

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx(6 + 20)
        assert estimate.kind == "review"

    def test_the_running_steps_60_are_a_setting_counted_in_steps(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 5 + [50] * 5, listed=False)
        _timed(session, past, "write", [20] * 10, age=20)
        _list(session, run, [_active("write", 10, listed=False)])

        assert _minutes(_estimates(session, [run], running=5)[run]) == pytest.approx(10)
        assert _minutes(_estimates(session, [run], running=10)[run]) == pytest.approx(
            25
        )


def _list_again(db: DbSession, work_id: uuid.UUID, steps: Sequence[_Step]) -> None:
    """`steps` in place of the Work's list."""
    for step in db.query(ProgressStep).filter_by(work_id=work_id):
        db.delete(step)
    db.flush()
    _list(db, work_id, steps)


class TestWorkEstimatesRepeatsOwed:
    """A `write` is priced at 22.5 minutes, 2.5 of them its repeats' share,
    and a `review` at 9, 1 of it its share."""

    @pytest.fixture(autouse=True)
    def _history(self, session: DbSession, past: uuid.UUID) -> None:
        _timed(session, past, "write", [20] * 8)
        _timed(session, past, "write", [10] * 2, listed=False, age=1.5)
        _timed(session, past, "review", [8] * 8)
        _timed(session, past, "review", [4] * 2, listed=False, age=1.5)
        _timed(session, past, "ship", [5] * 10)

    def _left(
        self, session: DbSession, run: uuid.UUID, steps: Sequence[_Step]
    ) -> float:
        _list(session, run, steps)
        return _minutes(_estimates(session, [run])[run])

    def test_a_listed_step_owes_its_share_while_it_runs(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        assert self._left(session, run, [_active("write", 10)]) == pytest.approx(
            10 + 2.5
        )

    def test_an_unlisted_step_or_one_of_a_listing_unknown_owes_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        left = self._left(
            session,
            run,
            [_active("write", 10, listed=False), _active("write", 10, listed=None)],
        )

        assert left == pytest.approx(10 + 10)

    def test_done_it_owes_until_the_next_listed_step_on_the_list_is_done(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """An unlisted step between the two releases nothing: the first
        `write` is released by the done `review`, which owes for the `ship`
        not begun."""
        left = self._left(
            session,
            run,
            [
                _done("write", 60),
                _done("ship", 50, listed=False),
                _done("review", 40),
                _pending("ship"),
            ],
        )

        assert left == pytest.approx(5 + 1)

    def test_done_it_owes_while_the_next_listed_step_runs(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        left = self._left(session, run, [_done("review", 40), _active("ship", 1)])

        assert left == pytest.approx(4 + 1)

    def test_an_unlisted_step_of_its_kind_begun_after_it_releases_it(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """The next listed step, the `ship`, has not begun: the second
        `write` alone releases the first."""
        left = self._left(
            session,
            run,
            [
                _done("write", 60),
                _active("write", 10, listed=False),
                _pending("ship"),
            ],
        )

        assert left == pytest.approx(5 + 10)

    def test_an_unlisted_step_of_another_kind_releases_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """The second `write` began after the `review`, which owes until the
        `ship` is done."""
        left = self._left(
            session,
            run,
            [
                _done("write", 60),
                _done("review", 40),
                _active("write", 10, listed=False),
                _pending("ship"),
            ],
        )

        assert left == pytest.approx(5 + 10 + 1)

    def test_an_unlisted_step_of_its_kind_begun_before_it_releases_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        left = self._left(
            session,
            run,
            [_done("write", 70, listed=False), _done("write", 60), _pending("ship")],
        )

        assert left == pytest.approx(5 + 2.5)

    def test_with_no_listed_step_after_it_it_owes_while_a_step_is_left(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        left = self._left(
            session,
            run,
            [_done("write", 60), _active("ship", 1, listed=False)],
        )

        assert left == pytest.approx(4 + 2.5)

    def test_a_done_step_of_a_listing_unknown_owes_nothing_and_releases_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """A continuation's first list: its done steps and its running one
        are of a listing unknown, and the listed `write` before them owes
        until the `ship` not begun is done."""
        left = self._left(
            session,
            run,
            [
                _done("write", 60),
                _done("review", 40, listed=None),
                _active("ship", 1, listed=None),
                _pending("ship"),
            ],
        )

        assert left == pytest.approx(4 + 5 + 2.5)

    def test_a_kind_owed_alone_is_a_kind_the_estimate_needs(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "sweep", [7] * 4)
        _list(session, run, [_done("sweep", 30), _pending("ship")])

        assert _estimates(session, [run]) == {}

        _timed(session, past, "sweep", [7])

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(5)


class TestWorkEstimatesLongerThanUsual:
    @pytest.fixture(autouse=True)
    def _history(self, session: DbSession, past: uuid.UUID) -> None:
        _timed(session, past, "write", [20] * 9 + [45])
        _timed(session, past, "review", [8] * 10)

    def test_a_step_that_outran_every_one_of_its_60_gives_no_time_left(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 46), _pending("review")])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.minutes) == (None, None)
        assert estimate.longer_than_usual is LongerThanUsual.OUTRUN
        assert estimate.kind == "write"

    def test_a_step_one_of_its_60_ran_as_long_as_keeps_its_estimate(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 45), _pending("review")])

        estimate = _estimates(session, [run])[run]

        assert estimate.longer_than_usual is None
        assert _minutes(estimate) == pytest.approx(8)

    def test_a_timing_before_its_60_does_not_keep_the_estimate(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 30)])

        assert _estimates(session, [run], running=9)[run].longer_than_usual is (
            LongerThanUsual.OUTRUN
        )
        assert _estimates(session, [run], running=10)[run].longer_than_usual is None

    def test_one_of_several_running_steps_outrun_gives_no_time_left(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("review", 2), _active("write", 46)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual, estimate.kind) == (
            None,
            LongerThanUsual.OUTRUN,
            "review",
        )

    def test_a_marked_step_within_its_60_keeps_the_time_left(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 5, marked=True), _pending("review")])

        estimate = _estimates(session, [run])[run]

        assert estimate.longer_than_usual is LongerThanUsual.MARKED
        assert _minutes(estimate) == pytest.approx(15 + 8)
        assert estimate.minutes == 25

    def test_a_marked_step_that_outran_its_60_gives_no_time_left(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 46, marked=True)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual) == (
            None,
            LongerThanUsual.OUTRUN,
        )

    @pytest.mark.parametrize("kind", ["sweep", None])
    def test_a_marked_step_on_a_work_item_with_no_estimate_stands_alone(
        self, session: DbSession, run: uuid.UUID, kind: str | None
    ) -> None:
        """A kind with no timing, or a step with no kind."""
        _list(session, run, [_active("write", 5, marked=True), _pending(kind)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual, estimate.kind) == (
            None,
            LongerThanUsual.MARKED,
            "write",
        )

    def test_a_step_outrun_on_a_work_item_with_no_estimate_shows_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 46), _pending("sweep")])

        assert _estimates(session, [run]) == {}

    def test_a_mark_on_a_step_that_does_not_run_is_no_alert(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(
            session,
            run,
            [
                _done("write", 30, marked=True),
                _active("write", 5, marked=False),
                _Step("review", ProgressState.PENDING, marked=True),
            ],
        )

        assert _estimates(session, [run])[run].longer_than_usual is None


class TestWorkEstimatesRead:
    def test_the_estimates_stand_in_the_order_asked_with_the_time_each_has_run(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        first = _run(session, project, project_session, began=12.5)
        second = _run(session, project, project_session, began=200)
        _timed(session, past, "write", [20] * 10)
        for work_id in (first, second):
            _list(session, work_id, [_pending("write")])

        estimates = _estimates(session, [second, uuid.uuid4(), first])

        assert [
            (estimate.work_id, estimate.ran_seconds) for estimate in estimates.values()
        ] == [(second, 200 * MINUTE), (first, 750)]
        assert list(estimates) == [second, first]

    def test_a_session_with_no_start_has_run_no_time(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        session.get_one(models.Session, run).started_at = None
        _timed(session, past, "write", [20] * 10)
        _list(session, run, [_pending("write")])

        assert _estimates(session, [run])[run].ran_seconds is None

    def test_no_work_item_asked_reads_nothing(self, session: DbSession) -> None:
        with sent(session) as statements:
            assert _estimates(session, []) == {}

        assert statements.texts == []

    def test_any_number_of_work_items_and_kinds_is_four_statements(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """The running Sessions, their lists, their repos' own timings and
        all repos'."""
        works = [
            _run(session, project, project_session, repo=repo)
            for repo in (REPO, OTHER_REPO, None)
        ]
        for kind in ("write", "review", "ship"):
            _timed(session, past, kind, [20] * 10)
        for work_id in works:
            _list(
                session,
                work_id,
                [_active("write", 5), _pending("review"), _pending("ship")],
            )

        with sent(session) as statements:
            estimates = _estimates(session, works)

        assert list(estimates) == works
        assert len(statements.texts) == 4

    def test_each_read_of_a_kinds_last_timings_ends_on_an_index(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """In a repo's own and in all repos', with no sort and no walk of
        the kind's other listing or another repo's timings: the plan the
        planner has once a table this small is not read whole."""
        works = [
            _run(session, project, project_session, repo=repo)
            for repo in (REPO, OTHER_REPO)
        ]
        _timed(session, past, "write", [20] * 10)
        for work_id in works:
            _list(session, work_id, [_pending("write")])
        with sent(session) as statements:
            _estimates(session, works)
        connection = session.connection()
        for path in ("seqscan", "bitmapscan", "sort"):
            connection.exec_driver_sql(f"SET LOCAL enable_{path} = off")

        plans = []
        for statement in statements.built[2:]:
            compiled = statement.compile(connection)
            rows = connection.exec_driver_sql(
                f"EXPLAIN {compiled.string}", compiled.params
            )
            plans.append("\n".join(row[0] for row in rows))

        own, every = plans
        assert (
            "Index Scan Backward using"
            " ix_step_timings_repo_kind_code_listed_ahead_ended_at" in own
        )
        assert (
            "Index Scan Backward using ix_step_timings_kind_code_listed_ahead_ended_at"
            in every
        )
        assert "Sort" not in own + every
        assert "Filter" not in own + every


def _shown(
    seconds: float | None, longer: LongerThanUsual | None = None
) -> WorkEstimate:
    return WorkEstimate(
        work_id=uuid.uuid4(),
        seconds=seconds,
        longer_than_usual=longer,
        kind="write",
        ran_seconds=600,
    )


class TestWorkEstimateMinutes:
    @pytest.mark.parametrize(
        ("minutes", "rounded"),
        [
            (0, 5),
            (2.4, 5),
            (7.4, 5),
            (7.5, 10),
            (12.5, 15),
            (25, 25),
            (52.4, 50),
            (52.5, 55),
            (54.9, 55),
            (55, 60),
            (89.9, 60),
            (90, 120),
            (118, 120),
            (149.9, 120),
            (150, 180),
            (600, 600),
        ],
    )
    def test_the_time_left_is_rounded_as_the_badge_words_it(
        self, minutes: float, rounded: int
    ) -> None:
        assert _shown(minutes * MINUTE).minutes == rounded

    def test_no_time_left_rounds_to_none(self) -> None:
        assert _shown(None, LongerThanUsual.OUTRUN).minutes is None


class TestProjectEstimate:
    def test_no_estimate_among_its_work_items_is_none(self) -> None:
        assert project_estimate([]) is None

    def test_it_is_the_work_item_with_the_most_time_left(self) -> None:
        most = _shown(3000)

        assert project_estimate([_shown(600), most, _shown(2999)]) is most

    def test_of_two_alike_it_is_the_first(self) -> None:
        first = _shown(600)

        assert project_estimate([first, _shown(600)]) is first

    def test_one_longer_than_usual_stands_before_any_time_left(self) -> None:
        marked = _shown(300, LongerThanUsual.MARKED)

        assert project_estimate([_shown(9000), marked]) is marked

    def test_a_step_outrun_stands_before_a_step_marked(self) -> None:
        outrun = _shown(None, LongerThanUsual.OUTRUN)

        assert (
            project_estimate(
                [_shown(9000), _shown(4000, LongerThanUsual.MARKED), outrun]
            )
            is outrun
        )

    def test_of_the_marked_it_is_the_one_with_the_most_time_left(self) -> None:
        most = _shown(4000, LongerThanUsual.MARKED)

        assert (
            project_estimate(
                [
                    _shown(None, LongerThanUsual.MARKED),
                    _shown(300, LongerThanUsual.MARKED),
                    most,
                    _shown(9000),
                ]
            )
            is most
        )

    def test_a_marked_one_with_no_estimate_stands_where_no_marked_one_has_any(
        self,
    ) -> None:
        alone = _shown(None, LongerThanUsual.MARKED)

        assert project_estimate([_shown(9000), alone]) is alone
