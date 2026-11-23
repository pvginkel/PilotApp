"""A view's series (F154.1, F163.3, F164.2): in order or over time, its points
along the axis with each measure as a panel draws it, the rolling band over
the length the state names, the outliers by the screen's one rule, the
markers where a version was first seen, and the chips as the rows take them.

The record is `tests.support.dashboard.record`'s, on 12 November 2026 in
Amsterdam, a Thursday, its loose thread's Call a day later; `members` adds
work items' Sessions, each made on a day of its own with one Turn standing
in for its Calls.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard import series as series_module
from app.dashboard.planner import Measured, series_plan
from app.dashboard.series import (
    Band,
    Series,
    SeriesService,
    kind,
    rolling,
    start_of,
)
from app.dashboard.state import Roll
from app.exceptions import StateRefusedException
from app.models import LaunchComponent, Project, User
from app.models.reference import SessionState, TurnCause
from app.services.container import ServiceContainer
from tests.support import transcripts
from tests.support.dashboard import Record, record
from tests.support.transcripts import STARTED

NOW = datetime(2026, 11, 20, tzinfo=UTC)
FIRST_DAY = datetime(2026, 10, 1, 8, tzinfo=UTC)


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> SeriesService:
    return container.series_service()


def _series(service: SeriesService, written: str) -> Series:
    return service.series(written, now=NOW)


def _values(found: Series, at: int = 0) -> list[float | None]:
    return [
        None if (value := point.values[at]) is None else round(value, 6)
        for point in found.points
    ]


def members(
    db: DbSession, project: Project, costs: Sequence[str]
) -> list[models.Session]:
    """A work item's Session for each cost, made a day after the one before
    from 1 October 2026, with one Turn of that cost on its day."""
    made = []
    for day, cost in enumerate(costs):
        created = FIRST_DAY + timedelta(days=day)
        run = models.Session(
            project_id=project.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash=f"{day + 10:064d}",
            state_code=SessionState.IDLE,
            created_at=created,
        )
        db.add(run)
        db.flush()
        db.add(
            models.Turn(
                session_id=run.id,
                seq=1,
                message="Scale the recipe.",
                started_at=created + timedelta(minutes=5),
                ended_at=created + timedelta(minutes=10),
                cost=Decimal(cost),
                cause_code=TurnCause.BRIEF,
            )
        )
        made.append(run)
    db.flush()
    return made


class TestRolling:
    def test_it_reads_the_previous_values_and_draws_from_its_length_on(
        self,
    ) -> None:
        assert rolling([1.0, 2.0, 3.0, 4.0], Roll(2, 2)) == (
            None,
            None,
            Band(1.25, 1.5, 1.75),
            Band(2.25, 2.5, 2.75),
        )

    def test_the_values_before_the_range_come_first(self) -> None:
        assert rolling([5.0], Roll(3, 2), before=[1.0, 2.0]) == (Band(1.25, 1.5, 1.75),)

    def test_a_point_with_none_is_no_value_read(self) -> None:
        assert rolling([1.0, None, 3.0], Roll(1, 1)) == (
            None,
            Band(1.0, 1.0, 1.0),
            Band(1.0, 1.0, 1.0),
        )


class TestStartOf:
    def test_the_earliest_span(self) -> None:
        later = datetime(2026, 11, 12, tzinfo=UTC)
        earlier = datetime(2026, 11, 5, tzinfo=UTC)

        assert start_of(((later, None), (earlier, later))) == earlier

    def test_none_for_all_time_none_of_it_and_an_open_start(self) -> None:
        assert start_of(None) is None
        assert start_of(()) is None
        assert start_of(((None, NOW),)) is None


@pytest.mark.usefixtures("worked")
class TestOverTime:
    def test_by_day_its_points_are_the_zones_days_each_with_its_span(
        self, service: SeriesService
    ) -> None:
        found = _series(service, "t=all&p=time,day&m=cost.sum&m=calls.count")

        assert found.presentation == "time"
        assert found.by.key == "day"
        assert [point.key for point in found.points] == [
            date(2026, 11, 12),
            date(2026, 11, 13),
        ]
        assert _values(found) == [2.6, 0.05]
        assert [(point.starts_at, point.ends_at) for point in found.points] == [
            (
                datetime(2026, 11, 11, 23, tzinfo=UTC),
                datetime(2026, 11, 12, 23, tzinfo=UTC),
            ),
            (
                datetime(2026, 11, 12, 23, tzinfo=UTC),
                datetime(2026, 11, 13, 23, tzinfo=UTC),
            ),
        ]
        assert [panel.kind for panel in found.panels] == ["column", "column"]
        assert [panel.band for panel in found.panels] == [None, None]
        assert found.total_points == 2
        assert found.off_axis is None

    def test_by_the_quota_week_each_point_is_its_week(
        self, service: SeriesService
    ) -> None:
        found = _series(service, "t=all&p=time,qweek")

        week = datetime(2026, 11, 12, 10, tzinfo=UTC)
        assert [point.key for point in found.points] == [week - timedelta(7), week]
        assert _values(found) == [1.85, 0.8]
        assert [(point.starts_at, point.ends_at) for point in found.points] == [
            (week - timedelta(7), week),
            (week, week + timedelta(7)),
        ]

    def test_by_the_hour_its_points_come_round_with_no_span_and_no_marker(
        self, service: SeriesService, session: DbSession, worked: Record
    ) -> None:
        _a_later_version(session, worked)

        found = _series(service, "t=all&p=time,hod")

        assert [point.key for point in found.points] == [10, 11, 12]
        assert _values(found) == [1.9, 0.2, 0.75]
        assert {point.starts_at for point in found.points} == {None}
        assert found.markers == ()

    def test_the_by_plays_no_part(self, service: SeriesService) -> None:
        found = _series(service, "t=all&by=psession&p=time,day")

        assert _values(found) == [2.6, 0.05]

    def test_the_color_stacks_the_event_kind_among_them(
        self, service: SeriesService
    ) -> None:
        found = _series(service, "t=all&p=time,day&m=events.count&col=event_kind")

        assert found.color is not None
        assert found.color.key == "event_kind"
        kinds = [value.key for value in found.color.values]
        assert "api_error" in kinds
        first = found.points[0]
        assert first.split is not None and first.split[0] is not None
        assert sum(first.split[0]) == first.values[0]
        assert found.panels[0].measure.stacks

    def test_a_measure_over_a_parts_items_draws_their_dots(
        self, service: SeriesService, worked: Record
    ) -> None:
        found = _series(service, "t=all&p=time,day&m=cost.max.conversation")

        panel = found.panels[0]
        assert panel.kind == "items"
        assert panel.dots is not None
        assert [(dot.point, dot.key, round(dot.value, 6)) for dot in panel.dots] == [
            (0, worked.thread.id, 1.75),
            (0, worked.sub_agent.id, 0.1),
            (1, worked.loose.id, 0.05),
        ]
        assert [dot.at for dot in panel.dots] == [
            STARTED + timedelta(minutes=1),
            STARTED + timedelta(minutes=2, seconds=30),
            STARTED + timedelta(days=1),
        ]
        assert panel.band == (None, None, None)
        assert panel.measure.median == 0.1
        assert not panel.cut

    def test_a_parts_dot_has_its_name(
        self, service: SeriesService, worked: Record
    ) -> None:
        found = _series(service, "t=all&p=time,qweek&m=cost.max.project")

        dots = found.panels[0].dots
        assert dots is not None
        assert [(dot.key, dot.label) for dot in dots] == [
            (worked.project.id, "Recipe box"),
            (worked.project.id, "Recipe box"),
        ]

    def test_a_threshold_keeps_its_points_and_their_dots(
        self, service: SeriesService, worked: Record
    ) -> None:
        found = _series(
            service,
            "t=all&p=time,day&m=cost.sum&m=cost.max.conversation&c=@rows,gt,1,cost.sum",
        )

        assert [point.key for point in found.points] == [date(2026, 11, 12)]
        assert found.all.values[0] == pytest.approx(2.6)
        dots = found.panels[1].dots
        assert dots is not None
        assert {dot.key for dot in dots} == {worked.thread.id, worked.sub_agent.id}

    def test_a_marked_chip_marks_its_points(self, service: SeriesService) -> None:
        found = _series(service, "t=all&p=time,day&c=~miss:1")

        assert [point.marked for point in found.points] == [True, False]
        assert [point.marks for point in found.points] == [(1.0,), (0.0,)]

    def test_a_marker_where_a_version_was_first_seen(
        self, service: SeriesService, session: DbSession, worked: Record
    ) -> None:
        later = _a_later_version(session, worked)

        found = _series(service, "t=all&p=time,day")

        assert [
            (marker.kind, marker.value, marker.before, marker.at)
            for marker in found.markers
        ] == [("claude_code_version", "2.1.318", "2.1.317", later)]

    def test_a_marker_outside_the_axis_is_left_out(
        self, service: SeriesService, session: DbSession, worked: Record
    ) -> None:
        _a_later_version(session, worked)

        found = _series(service, "t=c,2026-11-12,2026-11-12&p=time,day")

        assert found.markers == ()


class TestInOrder:
    def test_its_points_are_the_members_by_their_place_with_the_band(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        runs = members(session, project, ["1", "2", "3", "4", "5", "6"])

        found = _series(service, "t=all&by=psession&p=order&roll=2,2")

        assert found.presentation == "order"
        assert found.by.key == "session_start"
        assert [point.key for point in found.points] == [run.id for run in runs]
        assert [point.axis for point in found.points] == [
            run.created_at for run in runs
        ]
        assert _values(found) == [1, 2, 3, 4, 5, 6]
        panel = found.panels[0]
        assert panel.kind == "column"
        assert panel.band == (
            None,
            None,
            Band(1.25, 1.5, 1.75),
            Band(2.25, 2.5, 2.75),
            Band(3.25, 3.5, 3.75),
            Band(4.25, 4.5, 4.75),
        )
        assert panel.before == 0

    def test_the_band_reads_the_members_before_the_range_first(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        runs = members(session, project, ["1", "2", "3", "4", "5", "6"])

        found = _series(
            service, "t=c,2026-10-05,2026-10-06&by=psession&p=order&roll=2,3"
        )

        assert [point.key for point in found.points] == [runs[4].id, runs[5].id]
        panel = found.panels[0]
        assert panel.before == 3
        assert panel.band == (Band(3.25, 3.5, 3.75), Band(4.25, 4.5, 4.75))

    def test_a_member_in_the_range_is_not_read_before_it(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        runs = members(session, project, ["1", "2", "3", "4", "5", "6"])
        _a_later_turn(session, runs[2], datetime(2026, 10, 5, 12, tzinfo=UTC), "7")

        found = _series(
            service, "t=c,2026-10-05,2026-10-06&by=psession&p=order&roll=2,3"
        )

        assert [point.key for point in found.points] == [
            runs[2].id,
            runs[4].id,
            runs[5].id,
        ]
        assert _values(found) == [7, 5, 6]
        panel = found.panels[0]
        assert panel.before == 3
        assert panel.band == (
            Band(2.5, 3.0, 3.5),
            Band(4.75, 5.5, 6.25),
            Band(5.5, 6.0, 6.5),
        )

    def test_its_outliers_by_the_screens_one_rule(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        members(session, project, ["1", "1", "1", "1", "1", "9"])

        found = _series(service, "t=all&by=psession&p=order")

        assert found.panels[0].outliers == (5,)

    def test_the_row_with_none_is_answered_beside_the_points(
        self, service: SeriesService, worked: Record
    ) -> None:
        found = _series(service, "t=all&by=psession&p=order&m=cost.sum")

        assert None not in [point.key for point in found.points]
        assert found.off_axis is not None
        assert found.off_axis.values == (pytest.approx(0.05),)
        assert found.total_points == 2

    def test_an_items_own_figure_is_a_point(self, service: SeriesService) -> None:
        found = _series(service, "t=all&by=psession&p=order&m=cost.max.psession")

        assert found.panels[0].kind == "point"
        assert found.panels[0].dots is None

    def test_the_focus_is_left_out_of_the_median(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        runs = members(session, project, ["1", "2", "9"])

        found = _series(service, f"t=all&by=psession&p=order&f=psession:{runs[2].id}")

        assert [point.focus for point in found.points] == [False, False, True]
        assert found.panels[0].measure.median == 1.5


class TestItemsBeforeTheRange:
    def test_the_dots_band_reads_the_items_that_started_before_the_range_first(
        self, service: SeriesService, session: DbSession, project: Project
    ) -> None:
        runs = members(session, project, ["1", "2", "3", "4", "5", "6"])
        _a_later_turn(session, runs[2], datetime(2026, 10, 5, 12, tzinfo=UTC), "7")

        found = _series(
            service, "t=c,2026-10-05,2026-10-06&p=time,day&m=cost.max.psession&roll=2,3"
        )

        panel = found.panels[0]
        assert panel.kind == "items"
        assert panel.dots is not None
        assert [(dot.point, dot.key, dot.value) for dot in panel.dots] == [
            (0, runs[4].id, 5),
            (0, runs[2].id, 7),
            (1, runs[5].id, 6),
        ]
        assert panel.before == 3
        assert panel.band == (
            Band(2.5, 3.0, 3.5),
            Band(4.25, 4.5, 4.75),
            Band(5.5, 6.0, 6.5),
        )


@pytest.mark.usefixtures("worked")
class TestCaps:
    def test_at_most_its_points_with_the_count_of_all(
        self, service: SeriesService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(series_module, "ROWS", 1)

        found = _series(service, "t=all&p=time,day")

        assert [point.key for point in found.points] == [date(2026, 11, 12)]
        assert found.total_points == 2

    def test_at_most_its_dots_saying_more_were_left_out(
        self, service: SeriesService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(series_module, "DOTS", 2)

        found = _series(service, "t=all&p=time,day&m=cost.max.conversation")

        assert found.panels[0].dots is not None
        assert len(found.panels[0].dots) == 2
        assert found.panels[0].cut

    def test_at_most_its_markers_of_a_kind_the_latest(
        self,
        service: SeriesService,
        session: DbSession,
        worked: Record,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(series_module, "MARKERS", 1)
        _a_later_version(session, worked)
        latest = _a_later_version(
            session, worked, "2.1.319", datetime(2026, 11, 13, 12, tzinfo=UTC)
        )

        assert [
            (marker.value, marker.before, marker.at)
            for marker in _series(service, "t=all&p=time,day").markers
        ] == [("2.1.319", "2.1.318", latest)]


class TestKind:
    @pytest.mark.parametrize(
        ("written", "drawn"),
        [
            ("t=all&p=time,day&m=cost.sum", "column"),
            ("t=all&p=time,day&m=calls.count.conversation", "column"),
            ("t=all&p=time,day&m=cost.median", "point"),
            ("t=all&p=time,day&m=r:overhead", "point"),
            ("t=all&p=time,day&m=cost.median.conversation", "items"),
            ("t=all&by=psession&p=order&m=cost.median.psession", "point"),
            ("t=all&by=psession&p=order&m=cost.median.conversation", "items"),
        ],
    )
    def test_how_a_series_draws_a_measure(
        self, service: SeriesService, written: str, drawn: str
    ) -> None:
        found = _series(service, written)

        assert [panel.kind for panel in found.panels] == [drawn]
        view = service.address_service.view(written)
        assert (
            kind(_planned(service, written)[0], view.catalogue.dimension(found.by.key))
            == drawn
        )


class TestRefused:
    def test_a_view_in_rows_has_no_series(self, service: SeriesService) -> None:
        with pytest.raises(StateRefusedException) as refused:
            _series(service, "t=all&by=project")

        assert refused.value.message.splitlines() == [
            "Cannot read the view because its state has 1 fault.",
            "- p=rows: the view draws rows, and only a view in order or over time "
            "has a series. A series takes p=order[,<order dimension>] or "
            "p=time,<grain>.",
            "A presentation reads p=order[,<order dimension>], p=time,<grain>, "
            "p=lanes or p=table, as in p=time,day.",
        ]

    def test_a_state_with_faults_is_refused_whole(self, service: SeriesService) -> None:
        with pytest.raises(StateRefusedException):
            _series(service, "p=time,minute")


def _planned(service: SeriesService, written: str) -> tuple[Measured, ...]:
    view = service.address_service.view(written)
    found = series_plan(view.address.state, view.catalogue, view.weeks, NOW)
    return found.measures


def _a_later_turn(db: DbSession, run: models.Session, at: datetime, cost: str) -> None:
    """A second Turn of `run`'s, started at `at`, of `cost`."""
    db.add(
        models.Turn(
            session_id=run.id,
            seq=2,
            message="Halve the recipe.",
            started_at=at,
            ended_at=at + timedelta(minutes=5),
            cost=Decimal(cost),
            cause_code=TurnCause.BRIEF,
        )
    )
    db.flush()


def _a_later_version(
    db: DbSession,
    worked: Record,
    version: str = "2.1.318",
    at: datetime = datetime(2026, 11, 13, 10, tzinfo=UTC),
) -> datetime:
    """A thread of the work item's whose Launch ran Claude Code `version`,
    its one Call of 0.20 at `at`, by default 11:00 in Amsterdam the day after
    the record's; that Call's time."""
    later = transcripts.component_version(db, "claude-code", version)
    read_under = db.get(models.ComponentVersion, worked.thread.read_under_id)
    assert read_under is not None
    thread = transcripts.transcript(db, read_under, session_id=str(uuid.uuid4()))
    start = transcripts.launch(db, thread, session_id=worked.work.id, turn_seq=1)
    db.add(
        LaunchComponent(
            launch_id=start.id,
            component_version_id=later.id,
            component_code="claude-code",
        )
    )
    transcripts.call(
        db,
        thread,
        1,
        completed_at=at,
        launch_id=start.id,
        cost=Decimal("0.20"),
        rewind=False,
        cache_miss=False,
        past_ttl=False,
    )
    db.flush()
    return at
