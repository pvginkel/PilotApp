"""The time a running work item still takes (F156.4 to F156.7): the price,
the running step and the timings it is read against, the repeats owed, no
estimate, longer than usual and the run's mark, the running step's and the
run's figures (F156.13, F156.14) and the project's pick."""

import itertools
import uuid
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy.orm import Session as DbSession

from app import models
from app.extensions import db
from app.models import (
    Environment,
    Item,
    ProgressStep,
    Project,
    StepKind,
    StepTiming,
    Turn,
    Work,
)
from app.models.reference import ProgressState, SessionState, TurnCause
from app.schemas.timeline import LongerThanUsual
from app.services.container import ServiceContainer
from app.services.step_estimate import (
    RunFigures,
    StepEstimates,
    StepFigures,
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
    conversation: str | None = None,
) -> uuid.UUID:
    """A worker's run of `project`, placed in `repo`, on `conversation`,
    whose Session and its first turn began `began` minutes ago and its
    running turn `turn` minutes ago; its id."""
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
                conversation_id=conversation,
                started_at=_ago(began),
                turn_started_at=_ago(turn),
            ),
        ]
    )
    db.flush()
    db.add(
        Turn(
            session_id=work_id,
            seq=1,
            message="Fix the client for v4.",
            started_at=_ago(began),
            cause_code=TurnCause.BRIEF,
        )
    )
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


def _timed_at(
    db: DbSession,
    work_id: uuid.UUID,
    kind: str,
    minutes: Sequence[float],
    *,
    ended: float,
    listed: bool | None = True,
    repo: str | None = REPO,
) -> None:
    """Timings of `kind` on the Work, one per figure of `minutes`, every one
    ended `ended` minutes ago."""
    _kinds(db, {kind})
    db.add_all(
        StepTiming(
            work_id=work_id,
            kind_code=kind,
            ended_at=_ago(ended),
            duration=round(each * MINUTE),
            listed_ahead=listed,
            code=f"timed-{next(_numbers)}",
            repo=repo,
        )
        for each in minutes
    )
    db.flush()


def _estimates(
    db: DbSession,
    work_ids: Sequence[uuid.UUID],
    *,
    window: int = 20,
    running: int = 60,
    slow_factor: float = 1.6,
) -> dict[uuid.UUID, WorkEstimate]:
    return work_estimates(
        db,
        work_ids,
        now=NOW,
        window=window,
        running=running,
        slow_factor=slow_factor,
    )


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

    def test_a_done_work_item_has_none(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """A done line shows nothing, its marked step neither, though its
        Session runs on."""
        _timed(session, past, "write", [20] * 10)
        _list(session, run, [_active("write", 5, marked=True)])
        assert list(_estimates(session, [run])) == [run]
        item = session.get_one(Item, run)
        item.done_at, item.done_cause_code = NOW, "turn_ended"
        session.flush()

        assert _estimates(session, [run]) == {}

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

    def test_the_repos_ten_and_the_five_are_counted_whatever_the_settings(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Settings under ten cut neither count: the repo's ten listed ahead
        give an estimate under settings of 4, and price the step under
        settings of 5 though another repo's are newer."""
        _timed(session, past, "write", [10] * 10, age=20)
        _list(session, run, [_pending("write")])

        assert _minutes(
            _estimates(session, [run], window=4, running=4)[run]
        ) == pytest.approx(10)

        _timed(session, past, "write", [10] * 2, age=30)
        _timed(session, past, "write", [40] * 12, repo=OTHER_REPO)

        assert _minutes(
            _estimates(session, [run], window=5, running=5)[run]
        ) == pytest.approx(10)

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

    def test_a_begun_step_of_its_kind_of_a_listing_unknown_releases_nothing(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """Begun after the listed `write`, the second is no unlisted step:
        the first owes until the `ship` not begun is done."""
        left = self._left(
            session,
            run,
            [
                _done("write", 60),
                _active("write", 10, listed=None),
                _pending("ship"),
            ],
        )

        assert left == pytest.approx(5 + 10 + 2.5)

    def test_a_step_not_begun_is_the_next_listed_step_on_the_list(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """A list done out of order: the `ship` not begun stands between the
        `write` and the `review` done after it, so the `write` owes until the
        `ship` is done, and the `review`, with nothing listed after it, while
        a step is left."""
        left = self._left(
            session,
            run,
            [_done("write", 60), _pending("ship"), _done("review", 40)],
        )

        assert left == pytest.approx(5 + 2.5 + 1)

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
        assert (estimate.longer_than_usual, estimate.marked) == (
            LongerThanUsual.OUTRUN,
            False,
        )
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

        assert (estimate.longer_than_usual, estimate.marked) == (
            LongerThanUsual.MARKED,
            True,
        )
        assert _minutes(estimate) == pytest.approx(15 + 8)
        assert estimate.minutes == 25

    def test_a_marked_step_that_outran_its_60_gives_no_time_left_and_keeps_its_mark(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """The badge's em dash, and the sentence that its run marks it: a
        step its run marks keeps the marked sentence once it has outrun too
        (F156.14)."""
        _list(session, run, [_active("write", 46, marked=True)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual, estimate.marked) == (
            None,
            LongerThanUsual.OUTRUN,
            True,
        )

    def test_a_mark_on_one_running_step_with_another_outrun_is_the_runs_mark(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("review", 2, marked=True), _active("write", 46)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.longer_than_usual, estimate.marked) == (
            LongerThanUsual.OUTRUN,
            True,
        )

    @pytest.mark.parametrize("kind", ["sweep", None])
    def test_a_marked_step_on_a_work_item_with_no_estimate_stands_alone(
        self, session: DbSession, run: uuid.UUID, kind: str | None
    ) -> None:
        """A kind with no timing, or a step with no kind."""
        _list(session, run, [_active("write", 5, marked=True), _pending(kind)])

        estimate = _estimates(session, [run])[run]

        assert (
            estimate.seconds,
            estimate.longer_than_usual,
            estimate.marked,
            estimate.kind,
        ) == (None, LongerThanUsual.MARKED, True, "write")

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

        estimate = _estimates(session, [run])[run]

        assert (estimate.longer_than_usual, estimate.marked) == (None, False)


class TestWorkEstimatesAsTheStepBegan:
    """A running step is read against the timings of its kind that had
    ended when it began, so that they hold still while it runs (F156.5); a
    step not begun and the repeats owed read the window as it stands
    (F156.4)."""

    def test_a_timing_ended_since_it_began_moves_neither_its_time_left_nor_its_row(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 9 + [45])
        _list(session, run, [_active("write", 30)])
        before = _estimates(session, [run])[run]

        _timed_at(session, past, "write", [100] * 10, ended=10)
        after = _estimates(session, [run])[run]

        assert after == before
        assert _minutes(after) == pytest.approx(15)

    def test_a_timing_ended_since_it_began_does_not_keep_its_estimate(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 9 + [45])
        _list(session, run, [_active("write", 46)])
        _timed_at(session, past, "write", [100], ended=1)

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual) == (
            None,
            LongerThanUsual.OUTRUN,
        )

    def test_a_timing_ended_at_the_instant_it_began_had_ended_when_it_began(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """One publication ends a step and begins the next at one instant."""
        _timed(session, past, "write", [20] * 9)
        _timed_at(session, past, "write", [45], ended=30)
        _list(session, run, [_active("write", 30)])

        estimate = _estimates(session, [run])[run]

        assert estimate.longer_than_usual is None
        assert _minutes(estimate) == pytest.approx(15)
        assert [row.timings for row in estimate.step_figures] == [10]

    def test_the_repos_ten_are_counted_among_the_timings_ended_when_it_began(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Nine of the repo's own when it began, and ten in another repo: it
        is read against all repos', 35 more, though the repo's tenth has
        ended since and its own would leave 5."""
        _timed(session, past, "write", [10] * 9)
        _timed(session, past, "write", [40] * 10, repo=OTHER_REPO)
        _list(session, run, [_active("write", 5)])
        _timed_at(session, past, "write", [10], ended=1)

        estimate = _estimates(session, [run])[run]

        assert _minutes(estimate) == pytest.approx(35)
        assert [row.timings for row in estimate.step_figures] == [19]

    def test_the_five_that_began_as_it_did_are_counted_among_those_ended_when_it_began(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Four unlisted when it began: the kind's last taken whole, 10
        more, though a fifth has ended since and they alone would leave 90."""
        _timed(session, past, "write", [20] * 6)
        _timed(session, past, "write", [100] * 4, listed=False, age=1.5)
        _list(session, run, [_active("write", 10, listed=False)])
        _timed_at(session, past, "write", [100], listed=False, ended=1)

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(10)

    def test_a_kind_with_fewer_than_five_timings_when_it_began_leaves_none(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """However many have ended since; a mark stands alone, with no
        row."""
        _timed(session, past, "write", [20] * 4)
        _list(session, run, [_active("write", 5)])
        _timed_at(session, past, "write", [20] * 6, ended=1)

        assert _estimates(session, [run]) == {}

        _list_again(session, run, [_active("write", 5, marked=True)])
        estimate = _estimates(session, [run])[run]

        assert (
            estimate.seconds,
            estimate.longer_than_usual,
            estimate.step_figures,
        ) == (None, LongerThanUsual.MARKED, ())

    def test_a_step_not_begun_and_the_repeats_owed_read_the_window_as_it_stands(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Ten listed and five unlisted of 40 minutes ended since the step
        began, before five of the ten listed of 20 that had ended then: the
        window prices a `write` at 700 / 15 minutes, 200 / 15 of them its
        repeats' share; the running step is read against the ten of 20, 15
        more."""
        _timed(session, past, "write", [20] * 10)
        _list(session, run, [_active("write", 5), _pending("write")])
        _timed_at(session, past, "write", [40] * 10, ended=1)
        _timed_at(session, past, "write", [40] * 5, listed=False, ended=1)

        assert _minutes(_estimates(session, [run])[run]) == pytest.approx(
            15 + 700 / 15 + 200 / 15
        )


class TestWorkEstimatesStepFigures:
    """A running step's row of the figures on hover or press (F156.13), of
    the timings it is read against."""

    def test_its_row_is_its_time_run_and_the_median_the_90th_percentile_and_the_longest(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The 90th percentile between the ninth and the tenth of ten: 26
        and a tenth of the 34 minutes to 60."""
        _timed(session, past, "write", [10, 12, 14, 16, 18, 20, 22, 24, 26, 60])
        _list(session, run, [_active("write", 7), _pending("write")])

        [row] = _estimates(session, [run])[run].step_figures

        assert (row.kind, row.so_far_seconds, row.longest_seconds, row.timings) == (
            "write",
            7 * MINUTE,
            60 * MINUTE,
            10,
        )
        assert row.normal_seconds == pytest.approx(19 * MINUTE)
        assert row.slow_seconds == pytest.approx(29.4 * MINUTE)
        assert (
            row.so_far_minutes,
            row.normal_minutes,
            row.slow_minutes,
            row.longest_minutes,
        ) == (7, 19, 29, 60)

    def test_it_reads_the_timings_the_time_left_reads(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Those that began as it did where five did, under the running
        step's setting."""
        _timed(session, past, "write", [20] * 6)
        _timed(session, past, "write", [40, 60, 80, 100, 120], listed=False, age=1.5)
        _list(session, run, [_active("write", 10, listed=False)])

        [row] = _estimates(session, [run])[run].step_figures
        [fewer] = _estimates(session, [run], running=3)[run].step_figures

        assert (row.normal_seconds, row.longest_seconds, row.timings) == (
            80 * MINUTE,
            120 * MINUTE,
            5,
        )
        assert (fewer.normal_seconds, fewer.longest_seconds, fewer.timings) == (
            60 * MINUTE,
            80 * MINUTE,
            3,
        )

    def test_several_running_steps_have_a_row_each_in_the_lists_order(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [30] * 10)
        _timed(session, past, "review", [8] * 10)
        _list(session, run, [_active("review", 2), _active("write", 10)])

        rows = _estimates(session, [run])[run].step_figures

        assert [(row.kind, row.so_far_minutes, row.normal_minutes) for row in rows] == [
            ("review", 2, 8),
            ("write", 10, 30),
        ]

    def test_a_step_with_no_kind_or_too_few_timings_has_no_row_and_the_rest_stand(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """A work item with no estimate whose marked step's alert stands
        alone keeps that step's row."""
        _timed(session, past, "write", [20] * 10)
        _timed(session, past, "sweep", [5] * 4)
        _list(
            session,
            run,
            [
                _active("sweep", 3),
                _active("write", 5, marked=True),
                _active(None, 2),
            ],
        )

        estimate = _estimates(session, [run])[run]

        assert (estimate.seconds, estimate.longer_than_usual) == (
            None,
            LongerThanUsual.MARKED,
        )
        assert [row.kind for row in estimate.step_figures] == ["write"]

    def test_a_step_that_outran_its_60_keeps_its_row(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _timed(session, past, "write", [20] * 9 + [45])
        _list(session, run, [_active("write", 46)])

        estimate = _estimates(session, [run])[run]

        assert estimate.longer_than_usual is LongerThanUsual.OUTRUN
        assert [
            (row.so_far_minutes, row.longest_minutes) for row in estimate.step_figures
        ] == [(46, 45)]

    def test_its_time_run_counts_from_the_later_of_its_start_and_the_turns(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        resumed = _run(session, project, project_session, turn=4)
        _timed(session, past, "write", [30] * 10)
        _list(session, resumed, [_active("write", 10)])

        [row] = _estimates(session, [resumed])[resumed].step_figures

        assert row.so_far_seconds == 4 * MINUTE


def _row(seconds: float) -> StepFigures:
    return StepFigures(
        kind="write",
        so_far_seconds=seconds,
        normal_seconds=seconds,
        slow_seconds=seconds,
        longest_seconds=round(seconds),
        timings=60,
    )


class TestStepFiguresMinutes:
    @pytest.mark.parametrize(
        ("seconds", "words"),
        [
            (0, 0),
            (29, 0),
            (30, 1),
            (18 * MINUTE + 29, 18),
            (18 * MINUTE + 30, 19),
            (59 * MINUTE + 40, 60),
            (130 * MINUTE + 20, 130),
            (132 * MINUTE + 31, 133),
        ],
    )
    def test_a_time_run_and_the_longest_are_to_the_nearest_minute(
        self, seconds: float, words: int
    ) -> None:
        row = _row(seconds)

        assert (row.so_far_minutes, row.longest_minutes) == (words, words)

    @pytest.mark.parametrize(
        ("minutes", "words"),
        [
            (0.4, 0),
            (19.4, 19),
            (19.5, 20),
            (59.4, 59),
            (59.5, 60),
            (62.4, 60),
            (62.5, 65),
            (130.4, 130),
            (132.4, 130),
            (132.5, 135),
            (627, 625),
        ],
    )
    def test_normal_and_slow_are_to_the_nearest_minute_under_an_hour_and_five_from_one(
        self, minutes: float, words: int
    ) -> None:
        row = _row(minutes * MINUTE)

        assert (row.normal_minutes, row.slow_minutes) == (words, words)


class TestWorkEstimatesRunFigures:
    """The run's row of the figures on hover or press (F156.13): its time so
    far, which the alert's sentence says too (F156.14), its list at its
    kinds' prices as the timings stood at its start, and its slow, its
    normal times the factor."""

    @pytest.fixture(autouse=True)
    def _history(self, session: DbSession, past: uuid.UUID) -> None:
        _timed(session, past, "write", [20] * 10)
        _timed(session, past, "review", [8] * 10)

    def test_its_row_is_its_so_far_its_list_at_its_kinds_prices_and_its_slow(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """A done step's 30 minutes and the running one's 6 so far; 20, 8
        and 20 normal; and 1.6 times that slow, 76.8 minutes, to the nearest
        five."""
        _timed_at(session, run, "write", [30], ended=49)
        _list(
            session,
            run,
            [_done("write", 50), _active("review", 6), _pending("write")],
        )

        estimate = _estimates(session, [run])[run]

        figures = estimate.run_figures
        assert figures is not None
        assert figures.so_far_seconds == 36 * MINUTE
        assert figures.normal_seconds == pytest.approx(48 * MINUTE)
        assert figures.slow_seconds == pytest.approx(76.8 * MINUTE)
        assert (
            figures.so_far_minutes,
            figures.normal_minutes,
            figures.slow_minutes,
        ) == (36, 48, 75)
        assert estimate.ran_seconds == 36 * MINUTE

    def test_a_list_of_one_step_has_none_and_its_so_far_still_stands(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """A timing of a step its list no longer holds counts in it."""
        _timed_at(session, run, "review", [8], ended=20)
        _list(session, run, [_active("write", 12)])

        estimate = _estimates(session, [run])[run]

        assert (estimate.run_figures, estimate.ran_seconds) == (None, 20 * MINUTE)

    def test_a_step_not_listed_ahead_adds_nothing_to_its_normal(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(
            session,
            run,
            [
                _done("review", 50, listed=False),
                _active("write", 5),
                _pending("review"),
            ],
        )

        figures = _estimates(session, [run])[run].run_figures

        assert figures is not None
        assert figures.normal_seconds == pytest.approx((20 + 8) * MINUTE)

    def test_a_list_with_no_step_listed_ahead_has_none_and_its_so_far_still_stands(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """Every step first seen as it began: its normal would price nothing,
        a row of zeros beside its time so far."""
        _timed_at(session, run, "review", [8], ended=20)
        _list(
            session,
            run,
            [_done("review", 20, listed=False), _active("write", 12, listed=False)],
        )

        estimate = _estimates(session, [run])[run]

        assert (estimate.run_figures, estimate.ran_seconds) == (None, 20 * MINUTE)

    def test_its_prices_are_the_timings_as_they_stood_at_its_start(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """A `write` ended since the run began is not among them, a `review`
        ended at the instant it began is: 20 and 110 over 11."""
        _timed_at(session, past, "write", [200], ended=239)
        _timed_at(session, past, "review", [30], ended=240)
        _list(session, run, [_active("review", 5), _pending("write")])

        figures = _estimates(session, [run])[run].run_figures

        assert figures is not None
        assert figures.normal_seconds == pytest.approx((10 + 20) * MINUTE)

    def test_its_normal_grows_only_as_its_list_gains_a_step(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 5), _pending("review")])
        before = _estimates(session, [run])[run].run_figures
        _timed_at(session, past, "write", [200], ended=2)
        moved = _estimates(session, [run])[run].run_figures
        _list_again(
            session,
            run,
            [_active("write", 5), _pending("review"), _pending("write")],
        )
        grown = _estimates(session, [run])[run].run_figures

        assert before is not None and moved is not None and grown is not None
        assert [each.normal_seconds for each in (before, moved, grown)] == [
            pytest.approx(28 * MINUTE),
            pytest.approx(28 * MINUTE),
            pytest.approx(48 * MINUTE),
        ]

    def test_a_kind_with_no_price_at_its_start_leaves_no_row(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """Ten timings of a kind, every one ended since the run began: the
        time left prices it, the run's normal could not."""
        _timed_at(session, past, "ship", [10] * 10, ended=60)
        _list(session, run, [_active("write", 5), _pending("ship")])

        estimate = _estimates(session, [run])[run]

        assert estimate.seconds is not None
        assert estimate.run_figures is None

    @pytest.mark.parametrize(("listed", "stands"), [(True, False), (False, True)])
    def test_a_step_with_no_kind_listed_ahead_leaves_no_row(
        self, session: DbSession, run: uuid.UUID, listed: bool, stands: bool
    ) -> None:
        """A done step with no kind is no matter to the time left; to the
        run's normal it is unless it was not listed ahead."""
        _list(
            session,
            run,
            [_done(None, 30, listed=listed), _active("write", 5), _pending("write")],
        )

        estimate = _estimates(session, [run])[run]

        assert estimate.seconds is not None
        assert (estimate.run_figures is not None) is stands

    def test_its_slow_factor_is_a_setting(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _list(session, run, [_active("write", 5), _pending("write")])

        figures = _estimates(session, [run], slow_factor=2.5)[run].run_figures

        assert figures is not None
        assert (figures.normal_seconds, figures.slow_seconds) == (
            pytest.approx(40 * MINUTE),
            pytest.approx(100 * MINUTE),
        )


class TestWorkEstimatesTheRun:
    """The run is the work items on the running one's conversation, the
    running one alone where it has none; its start its first work item's
    first turn (F156.13)."""

    @pytest.fixture(autouse=True)
    def _history(self, session: DbSession, past: uuid.UUID) -> None:
        _timed(session, past, "write", [20] * 10)

    def _on(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        conversation: str | None,
        *,
        began: float,
        state: SessionState = SessionState.ENDED,
    ) -> uuid.UUID:
        return _run(
            session,
            project,
            project_session,
            state=state,
            began=began,
            turn=began,
            conversation=conversation,
        )

    def test_its_so_far_counts_every_work_item_on_its_conversation_and_no_other(
        self, session: DbSession, project: Project, project_session: models.Session
    ) -> None:
        """Not another conversation's, nor one with none, `past`."""
        earlier = self._on(session, project, project_session, "run-1", began=300)
        _timed_at(session, earlier, "write", [25], ended=280)
        other = self._on(session, project, project_session, "run-2", began=200)
        _timed_at(session, other, "write", [50], ended=100)
        current = self._on(
            session,
            project,
            project_session,
            "run-1",
            began=100,
            state=SessionState.RUNNING,
        )
        _timed_at(session, current, "write", [15], ended=60)
        _list(
            session,
            current,
            [_done("write", 75, listed=None), _active("write", 10)],
        )

        estimate = _estimates(session, [current])[current]

        assert estimate.ran_seconds == (25 + 15 + 10) * MINUTE
        assert estimate.run_figures is not None
        assert estimate.run_figures.so_far_seconds == (25 + 15 + 10) * MINUTE

    def test_its_start_is_its_first_work_items_first_turn(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """A timing ended after the first work item's first turn and before
        the running one's is not among its prices."""
        self._on(session, project, project_session, "run-1", began=300)
        current = self._on(
            session,
            project,
            project_session,
            "run-1",
            began=100,
            state=SessionState.RUNNING,
        )
        _timed_at(session, past, "write", [200], ended=200)
        _list(session, current, [_active("write", 10), _pending("write")])

        figures = _estimates(session, [current])[current].run_figures

        assert figures is not None
        assert figures.normal_seconds == pytest.approx(40 * MINUTE)

    def test_a_resume_restarts_neither_its_start_nor_its_so_far(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The Session's clock, which a Resume restarts, is not the run's:
        its done step's timing stays in its so far, its running step counts
        from the resumed turn, and its prices stay its first turn's."""
        _timed_at(session, run, "write", [40], ended=60)
        _timed_at(session, past, "write", [200], ended=10)
        resumed = session.get_one(models.Session, run)
        resumed.started_at = resumed.turn_started_at = _ago(2)
        session.add(
            Turn(
                session_id=run,
                seq=2,
                message="Go on.",
                started_at=_ago(2),
                cause_code=TurnCause.RESUME,
            )
        )
        _list(
            session,
            run,
            [_done("write", 61), _active("write", 30), _pending("write")],
        )

        estimate = _estimates(session, [run])[run]

        assert estimate.ran_seconds == (40 + 2) * MINUTE
        assert estimate.run_figures is not None
        assert estimate.run_figures.normal_seconds == pytest.approx(60 * MINUTE)

    @pytest.mark.parametrize(("known", "normal"), [(True, 60), (False, 40), (None, 60)])
    def test_a_step_its_list_brings_begun_counts_as_the_run_listed_it(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        known: bool | None,
        normal: float,
    ) -> None:
        """A continuation's first list brings the run's done steps begun,
        their listing unknown: as the work item that ran them listed them,
        listed where none knows."""
        earlier = self._on(session, project, project_session, "run-1", began=300)
        _list(session, earlier, [_done("write", 290, listed=known), _pending("write")])
        current = self._on(
            session,
            project,
            project_session,
            "run-1",
            began=100,
            state=SessionState.RUNNING,
        )
        _list(
            session,
            current,
            [
                _done("write", 290, listed=None),
                _active("write", 10, listed=None),
                _pending("write"),
            ],
        )

        figures = _estimates(session, [current])[current].run_figures

        assert figures is not None
        assert figures.normal_seconds == pytest.approx(normal * MINUTE)

    def test_another_conversations_listing_is_not_the_runs(
        self, session: DbSession, project: Project, project_session: models.Session
    ) -> None:
        other = self._on(session, project, project_session, "run-2", began=300)
        _list(session, other, [_done("write", 290, listed=False)])
        current = self._on(
            session,
            project,
            project_session,
            "run-1",
            began=100,
            state=SessionState.RUNNING,
        )
        _list(
            session,
            current,
            [_done("write", 90, listed=None), _active("write", 10)],
        )

        figures = _estimates(session, [current])[current].run_figures

        assert figures is not None
        assert figures.normal_seconds == pytest.approx(40 * MINUTE)

    def test_a_work_item_with_no_conversation_is_a_run_of_its_own(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """Another with none counts in neither its so far nor its start: a
        `write` of 200 ended between the other's first turn and its own is
        among its prices, with the other's of 50."""
        other = self._on(session, project, project_session, None, began=600)
        _timed_at(session, other, "write", [50], ended=500)
        _timed_at(session, past, "write", [200], ended=300)
        current = self._on(
            session,
            project,
            project_session,
            None,
            began=240,
            state=SessionState.RUNNING,
        )
        _list(session, current, [_active("write", 10), _pending("write")])

        estimate = _estimates(session, [current])[current]

        assert estimate.ran_seconds == 10 * MINUTE
        assert estimate.run_figures is not None
        assert estimate.run_figures.normal_seconds == pytest.approx(
            2 * (200 + 200 + 50) / 12 * MINUTE
        )

    def test_a_seeded_timing_on_its_work_item_is_not_the_runs(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """A seed's timings hang on the work item that ran the seed."""
        session.add(
            StepTiming(
                work_id=run,
                kind_code="write",
                ended_at=_ago(60),
                duration=30 * MINUTE,
                listed_ahead=True,
                key="seeded-1",
                repo=REPO,
            )
        )
        session.flush()
        _list(session, run, [_active("write", 10)])

        assert _estimates(session, [run])[run].ran_seconds == 10 * MINUTE


def _run_row(seconds: float) -> RunFigures:
    return RunFigures(
        so_far_seconds=seconds, normal_seconds=seconds, slow_seconds=seconds
    )


class TestRunFiguresMinutes:
    @pytest.mark.parametrize(
        ("seconds", "words"),
        [(29, 0), (30, 1), (18 * MINUTE + 30, 19), (132 * MINUTE + 31, 133)],
    )
    def test_its_so_far_is_to_the_nearest_minute(
        self, seconds: float, words: int
    ) -> None:
        assert _run_row(seconds).so_far_minutes == words

    @pytest.mark.parametrize(
        ("minutes", "words"),
        [(19.4, 19), (59.5, 60), (62.4, 60), (62.5, 65), (132.5, 135)],
    )
    def test_its_normal_and_slow_are_to_the_nearest_minute_under_an_hour_and_five_from_one(
        self, minutes: float, words: int
    ) -> None:
        row = _run_row(minutes * MINUTE)

        assert (row.normal_minutes, row.slow_minutes) == (words, words)


class TestWorkEstimatesRead:
    def test_the_estimates_stand_in_the_order_asked_with_the_time_each_has_run(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        first = _run(session, project, project_session)
        second = _run(session, project, project_session)
        _timed(session, past, "write", [30] * 10)
        _list(session, first, [_active("write", 12.5)])
        _list(session, second, [_active("write", 20)])

        estimates = _estimates(session, [second, uuid.uuid4(), first])

        assert [
            (estimate.work_id, estimate.ran_seconds) for estimate in estimates.values()
        ] == [(second, 20 * MINUTE), (first, 750)]
        assert list(estimates) == [second, first]

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
        """The running Sessions with their runs' starts and timings, their
        lists with their runs' other listings, their repos' own timings and
        all repos', as they stand, as they stood when each running step
        began and as they stood when each run began; the runs here on a
        conversation of two, three and none."""
        works = []
        for number, repo in enumerate((REPO, OTHER_REPO, None)):
            conversation = None if repo is None else f"conversation-{number}"
            for _earlier in range(number + 1):
                earlier = _run(
                    session,
                    project,
                    project_session,
                    repo=repo,
                    state=SessionState.ENDED,
                    began=300,
                    conversation=conversation,
                )
                _list(session, earlier, [_done("write", 290), _pending("review")])
                _timed_at(session, earlier, "sweep", [10], ended=280, repo=repo)
            works.append(
                _run(
                    session,
                    project,
                    project_session,
                    repo=repo,
                    conversation=conversation,
                )
            )
        for kind in ("write", "review", "ship"):
            _timed(session, past, kind, [20] * 10)
        for began, work_id in enumerate(works, start=5):
            _list(
                session,
                work_id,
                [
                    _done("write", 290, listed=None),
                    _active("write", began),
                    _active("review", 2),
                    _pending("ship"),
                ],
            )

        with sent(session) as statements:
            estimates = _estimates(session, works)

        assert list(estimates) == works
        assert [len(each.step_figures) for each in estimates.values()] == [2, 2, 2]
        assert [
            (each.run_figures.normal_minutes, each.ran_seconds // MINUTE)
            for each in estimates.values()
            if each.run_figures is not None
        ] == [(80, 10 + 5 + 2), (80, 20 + 6 + 2), (80, 7 + 2)]
        assert len(statements.texts) == 4


class TestWorkEstimatesPlans:
    """The plans of the estimates' reads, on a database of their own: at this
    size the planner weighs a repo's read of a kind's last timings on the
    repo's index and on the kind's alike, and breaks the tie on their files'
    sizes and the table's, which the rows a test before rolled back on the
    worker's database leave grown."""

    @pytest.fixture
    def session(self, committed_app: Flask) -> Generator[DbSession]:
        """The test's session, on a clone of the run's template, rolled back
        at teardown."""
        with committed_app.app_context():
            engine = db.engine
        with DbSession(engine, expire_on_commit=False) as fresh:
            yield fresh

    def test_each_read_of_a_kinds_last_timings_ends_on_an_index(
        self,
        session: DbSession,
        project: Project,
        project_session: models.Session,
        past: uuid.UUID,
    ) -> None:
        """In a repo's own and in all repos', as they stand and as they
        stood when a step began, with no sort and no walk of the kind's other
        listing, another repo's timings or those ended since: the plan the
        planner has once a table this small is not read whole, on statistics
        in which a repo holds an eighth of its kind's timings."""
        works = [
            _run(session, project, project_session, repo=repo)
            for repo in (REPO, OTHER_REPO)
        ]
        for repo in (REPO, *(f"example/Repo{number}" for number in range(7))):
            _timed(session, past, "write", [20] * 10, repo=repo)
        for work_id in works:
            _list(session, work_id, [_active("write", 5), _pending("write")])
        connection = session.connection()
        # The pick between the kind's index and the repo's reads the table's
        # statistics, which are otherwise whatever autovacuum last left; on
        # statistics of a single repo the kind's index with a filter costs less.
        connection.exec_driver_sql("ANALYZE step_timings")
        with sent(session) as statements:
            _estimates(session, works)
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


class TestStepEstimates:
    def test_it_reads_under_its_settings(
        self, session: DbSession, run: uuid.UUID, past: uuid.UUID
    ) -> None:
        """The window of 2 prices the step not begun at 40 minutes, where 5
        would at 22; the running step's 5 leave it 5 more, where 2 would
        35; the run's slow is twice its normal of 80 minutes."""
        _timed(session, past, "write", [40] * 2 + [10] * 8)
        _list(session, run, [_active("write", 5), _pending("write")])

        estimates = StepEstimates(window=2, running=5, slow_factor=2).of(
            session, [run], NOW
        )

        assert _minutes(estimates[run]) == pytest.approx(40 + 5)
        assert estimates[run].run_figures == RunFigures(
            so_far_seconds=5 * MINUTE,
            normal_seconds=80 * MINUTE,
            slow_seconds=160 * MINUTE,
        )
        assert estimates == _estimates(
            session, [run], window=2, running=5, slow_factor=2
        )

    def test_the_container_hands_it_the_window_the_60_and_the_slow_factor(
        self,
        container: ServiceContainer,
        session: DbSession,
        run: uuid.UUID,
        past: uuid.UUID,
    ) -> None:
        """Twenty timings of 10 minutes, the newest, before forty of 40: the
        window of 20 prices the step not begun at 10 minutes, where 60 would
        at 30; the running step's 60 leave it 35 more, where 20 would 5; the
        run's normal of 20 minutes is 32 slow."""
        _timed(session, past, "write", [10] * 20 + [40] * 40)
        _list(session, run, [_active("write", 5), _pending("write")])

        estimates = container.step_estimates().of(session, [run], NOW)

        assert _minutes(estimates[run]) == pytest.approx(35 + 10)
        run_figures = estimates[run].run_figures
        assert run_figures is not None
        assert run_figures.normal_seconds == pytest.approx(20 * MINUTE)
        assert run_figures.slow_seconds == pytest.approx(32 * MINUTE)


def _shown(
    seconds: float | None, longer: LongerThanUsual | None = None
) -> WorkEstimate:
    return WorkEstimate(
        work_id=uuid.uuid4(),
        seconds=seconds,
        longer_than_usual=longer,
        marked=longer is LongerThanUsual.MARKED,
        kind="write",
        ran_seconds=600,
        step_figures=(),
        run_figures=None,
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
