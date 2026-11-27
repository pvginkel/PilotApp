"""The four rules over work units (F154.4): where the prototype coded the
workflow, one rule for every kind, naming none — the units of one parent in
the order of their start, a marker a change in a role's configuration as it
ran, outliers judged among the items of one role, and work done again a
unit with any rework kind.

Each rule is pinned on invented units in the kitchen's words
(`tests.support.labels`), each unit carried out by a thread of its own with
one Call, and on the scenario's units as the stub labeller gives them, its
run records given the roles, the round and the rework kind the scenario's
lack.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pilot_scenario import SCENARIO
from pilot_scenario import builder as builder_module
from pilot_scenario.builder import Builder
from pilot_scenario.scenario import GEARS
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.assembly import assemble
from app.dashboard.series import (
    Configuration,
    Series,
    SeriesService,
    Shift,
    described,
)
from app.models import (
    Call,
    ComponentVersion,
    Model,
    Project,
    ReworkKind,
    Transcript,
    WorkUnit,
    WorkUnitKind,
)
from app.services.container import ServiceContainer
from tests.support import transcripts
from tests.support.dashboard import GAP, ZONE
from tests.support.labels import COURSE, declared, work_unit
from tests.support.transcripts import HAIKU, OPUS, SONNET

NOW = datetime(2026, 11, 20, tzinfo=UTC)
DAY = datetime(2026, 10, 1, 8, tzinfo=UTC)


def _day(number: int) -> datetime:
    return DAY + timedelta(days=number)


@pytest.fixture
def menu(session: DbSession) -> WorkUnit:
    return work_unit(session, "kitchen|Dinner")


@pytest.fixture
def series(container: ServiceContainer) -> Callable[[str], Series]:
    service: SeriesService = container.series_service()
    return lambda written: service.series(written, now=NOW)


def course(
    db: DbSession,
    menu: WorkUnit,
    title: str,
    started_at: datetime | None,
    **facts: Any,
) -> WorkUnit:
    """A course of the menu, started at `started_at`."""
    return work_unit(
        db, f"{menu.key}|{title}", COURSE, part_of=menu, started_at=started_at, **facts
    )


def carried(
    db: DbSession,
    unit: WorkUnit,
    at: datetime,
    cost: str = "1",
    model: str = OPUS,
    effort: str | None = "high",
    agent_id: str | None = None,
) -> Transcript:
    """A thread of its own whose one Launch carried out `unit`, with one Call
    at `at`: a main thread, or a sub-agent's where `agent_id` names one."""
    transcripts.reference(db, Model, model)
    read_under = db.scalar(
        select(ComponentVersion).where(ComponentVersion.component_code == "collector")
    )
    thread = transcripts.transcript(
        db,
        read_under or transcripts.component_version(db),
        session_id=str(uuid.uuid4()),
        agent_id=agent_id,
        first_call_at=at,
        last_call_at=at,
    )
    start = transcripts.launch(db, thread, started_at=at, work_unit_id=unit.id)
    transcripts.call(
        db,
        thread,
        1,
        launch_id=start.id,
        completed_at=at,
        cost=Decimal(cost),
        model_code=model,
        effort=effort,
        rewind=False,
        cache_miss=False,
        past_ttl=False,
    )
    return thread


def later_call(
    db: DbSession, thread: Transcript, at: datetime, model: str, effort: str | None
) -> None:
    """A second Call of the thread, in its first Launch."""
    first = db.scalars(select(Call).where(Call.transcript_id == thread.id)).one()
    transcripts.reference(db, Model, model)
    transcripts.call(
        db,
        thread,
        2,
        launch_id=first.launch_id,
        completed_at=at,
        cost=Decimal("1"),
        model_code=model,
        effort=effort,
        rewind=False,
        cache_miss=False,
        past_ttl=False,
    )


class TestTheUnitsOfOneParentInTheOrderOfTheirStart:
    def test_each_kind_lies_along_its_order(self, session: DbSession) -> None:
        declared(session, WorkUnitKind, "menu")
        declared(session, WorkUnitKind, "menu_start")

        catalogue = assemble(session, ZONE, GAP)

        along = {
            dimension.base: dimension
            for dimension in catalogue.dimensions
            if dimension.group == "order"
        }
        assert along["menu"].key == "menu_start_2"
        assert along["menu_start"].key == "menu_start_start"
        menu = along["menu"]
        assert (menu.label, menu.line) == (
            "Menu, in the order started",
            "Each Menu by when its work began, else by its first moment",
        )
        assert (menu.next, menu.null) == (
            catalogue.dimension("menu").next,
            "(No Menu)",
        )

    def test_a_kinds_units_stand_by_their_start_else_by_their_first_moment(
        self,
        session: DbSession,
        menu: WorkUnit,
        series: Callable[[str], Series],
    ) -> None:
        # The keys, the titles and the ids run against the starts.
        third = course(session, menu, "A soup", _day(2))
        unstarted = course(session, menu, "B salad", None)
        first = course(session, menu, "C bread", _day(0))
        second = course(session, menu, "D fish", _day(1))
        for unit, day in ((third, 2), (first, 0), (second, 1)):
            carried(session, unit, _day(day) + timedelta(hours=1))
        carried(session, unstarted, _day(1) + timedelta(hours=2))

        found = series("t=all&by=course&p=order")

        assert found.by.key == "course_start"
        assert [point.label for point in found.points] == [
            "C bread",
            "D fish",
            "B salad",
            "A soup",
        ]
        assert [point.axis for point in found.points] == [
            _day(0),
            _day(1),
            _day(1) + timedelta(hours=2),
            _day(2),
        ]


class TestAMarkerWhereARolesConfigurationChanged:
    @pytest.fixture
    def cooked(self, session: DbSession, menu: WorkUnit) -> list[WorkUnit]:
        """Five courses, a day apart, of the role cook but the fourth's, a
        taster's; the first two on Opus at high, the third on Sonnet at
        high, its sub-agent on Haiku, the fourth on Haiku, the fifth on
        Sonnet with no effort, the second turning to Sonnet in its second
        Call; and a sixth cook's, carried out by a sub-agent alone, on
        Haiku."""
        units = [
            course(
                session,
                menu,
                f"Course {number}",
                _day(number),
                role="taster" if number == 3 else "cook",
            )
            for number in range(5)
        ]
        configurations = [
            (OPUS, "high"),
            (OPUS, "high"),
            (SONNET, "high"),
            (HAIKU, "high"),
            (SONNET, None),
        ]
        threads = [
            carried(session, unit, _day(number), model=model, effort=effort)
            for number, (unit, (model, effort)) in enumerate(
                zip(units, configurations, strict=True)
            )
        ]
        later_call(session, threads[1], _day(1) + timedelta(hours=1), SONNET, "high")
        carried(
            session,
            units[2],
            _day(2) + timedelta(minutes=1),
            model=HAIKU,
            agent_id="a1b2c3d4e5f60718",
        )
        alone = course(session, menu, "Course 5", _day(5), role="cook")
        carried(session, alone, _day(5), model=HAIKU, agent_id="b2c3d4e5f6071829")
        return units

    def test_each_change_with_the_configuration_before_it(
        self, cooked: list[WorkUnit], series: Callable[[str], Series]
    ) -> None:
        found = series("t=all&by=course&p=order")

        assert [marker for marker in found.markers if isinstance(marker, Shift)] == [
            Shift(
                "model",
                "cook",
                Configuration(SONNET, "high"),
                Configuration(OPUS, "high"),
                _day(2),
            ),
            Shift(
                "model",
                "cook",
                Configuration(SONNET, None),
                Configuration(SONNET, "high"),
                _day(4),
            ),
        ]

    def test_the_configuration_before_the_axis_is_read_and_a_change_off_it_left_out(
        self, cooked: list[WorkUnit], series: Callable[[str], Series]
    ) -> None:
        found = series("t=c,2026-10-04,2026-10-05&by=course&p=order")

        assert [point.label for point in found.points] == ["Course 3", "Course 4"]
        assert found.markers == (
            Shift(
                "model",
                "cook",
                Configuration(SONNET, None),
                Configuration(SONNET, "high"),
                _day(4),
            ),
        )

    def test_a_series_states_list_it_with_the_fact_it_reads(
        self, container: ServiceContainer, cooked: list[WorkUnit]
    ) -> None:
        view = container.address_service().view("t=all&by=course&p=order")
        entry = described(view, NOW)

        assert entry is not None
        configuration = next(
            marker for marker in entry["markers"] if marker["kind"] == "model"
        )
        assert configuration["fact"] == "call"


class TestOutliersAmongTheItemsOfOneRole:
    @pytest.fixture
    def costed(self, session: DbSession, menu: WorkUnit) -> list[WorkUnit]:
        """Six cooks' courses costing 1 but the last, 9, and five tasters'
        costing 10, a day apart, the tasters' between the cooks'."""
        costs = [("cook", "1")] * 5 + [("cook", "9")] + [("taster", "10")] * 5
        order = [0, 6, 1, 7, 2, 8, 3, 9, 4, 10, 5]
        units = []
        for day, at in enumerate(order):
            role, cost = costs[at]
            unit = course(session, menu, f"Course {day}", _day(day), role=role)
            carried(session, unit, _day(day), cost=cost)
            units.append(unit)
        return units

    def test_a_points_are_judged_among_their_roles(
        self, costed: list[WorkUnit], series: Callable[[str], Series]
    ) -> None:
        found = series("t=all&by=course&p=order&m=cost.sum")

        # Among all eleven together the cooks' 9 lies inside the fence.
        assert [point.label for point in found.points][10] == "Course 10"
        assert found.panels[0].outliers == (10,)

    def test_a_panels_dots_are_judged_among_their_roles(
        self, costed: list[WorkUnit], series: Callable[[str], Series]
    ) -> None:
        found = series("t=all&p=time,day&m=cost.median.course")

        panel = found.panels[0]
        assert panel.kind == "items"
        assert panel.dots is not None
        assert [panel.dots[place].label for place in panel.outliers] == ["Course 10"]

    def test_items_that_share_no_role_are_judged_together(
        self, session: DbSession, menu: WorkUnit, series: Callable[[str], Series]
    ) -> None:
        costs = ["1", "10", "1", "10", "1", "10", "1", "10", "1", "10", "9"]
        for day, cost in enumerate(costs):
            unit = course(session, menu, f"Course {day}", _day(day))
            carried(session, unit, _day(day), cost=cost)

        found = series("t=all&by=course&p=order&m=cost.sum")

        assert found.panels[0].outliers == ()


class TestWorkDoneAgain:
    @pytest.fixture
    def recooked(self, session: DbSession, menu: WorkUnit) -> tuple[WorkUnit, WorkUnit]:
        """A course cooked again at a cost of 3, and one cooked once at 1."""
        again = course(
            session,
            menu,
            "Soup",
            _day(0),
            rework_kind_code=declared(session, ReworkKind, "recooked").code,
        )
        once = course(session, menu, "Bread", _day(1))
        carried(session, again, _day(0), cost="3")
        carried(session, once, _day(1), cost="1")
        return again, once

    def test_a_unit_with_any_rework_kind_is_rework(
        self,
        container: ServiceContainer,
        recooked: tuple[WorkUnit, WorkUnit],
    ) -> None:
        found = container.rows_service().rows(
            "t=all&by=rework&m=cost.sum&m=units.count", now=NOW
        )

        assert {row.key: row.values for row in found.rows} == {
            1: (3.0, 1.0),
            0: (1.0, 2.0),
        }

    def test_the_rework_share_is_its_cost_over_all(
        self,
        container: ServiceContainer,
        recooked: tuple[WorkUnit, WorkUnit],
    ) -> None:
        found = container.rows_service().rows(
            "t=all&by=menu&m=cost.sum&m=r:rework_share", now=NOW
        )

        assert [(row.label, row.values) for row in found.rows] == [
            ("Dinner", (4.0, 0.75))
        ]


@pytest.mark.usefixtures("service_user")
class TestTheScenariosUnits:
    """The scenario's run records with the roles they lack: both legs of
    the errand a cook's, the dumplings' cooked again in a second round, and
    carried out by the gears' conversation, which starts after the
    halving's."""

    @pytest.fixture
    def loaded(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Transcript:
        records = Builder.records

        def given(built: Builder) -> dict[str, Any]:
            written = records(built)
            for unit in written["units"]:
                if unit["kind"] == "leg":
                    unit["role"] = "cook"
                if unit["title"] == "Halve the dumplings":
                    unit |= {
                        "round": 2,
                        "rework_kind": "recooked",
                        "started_at": built.time(300),
                    }
                    written["ran"][built.conversation(GEARS)] = unit["key"]
            return written

        monkeypatch.setattr(builder_module.Builder, "records", given)
        container.scenario_service().load({"recipe-box": project.id})
        return session.scalars(
            select(Transcript).where(
                Transcript.session_id == Builder(SCENARIO, NOW).conversation(GEARS),
                Transcript.agent_id.is_(None),
            )
        ).one()

    def test_the_errands_legs_stand_in_the_order_of_their_start(
        self, loaded: Transcript, container: ServiceContainer
    ) -> None:
        found = container.series_service().series("t=all&by=leg&p=order")

        assert found.by.key == "leg_start"
        assert [point.label for point in found.points] == [
            "Halve the stew",
            "Halve the dumplings",
        ]

    def test_the_cooks_configuration_changed_with_the_dumplings(
        self, session: DbSession, loaded: Transcript, container: ServiceContainer
    ) -> None:
        started = session.scalar(
            select(WorkUnit.started_at).where(WorkUnit.title == "Halve the dumplings")
        )
        assert started is not None

        found = container.series_service().series("t=all&by=leg&p=order")

        assert [marker for marker in found.markers if isinstance(marker, Shift)] == [
            Shift(
                "model",
                "cook",
                Configuration(OPUS, None),
                Configuration(OPUS, "high"),
                started,
            )
        ]

    def test_the_dumplings_are_the_errands_rework(
        self, session: DbSession, loaded: Transcript, container: ServiceContainer
    ) -> None:
        again = session.scalar(
            select(func.sum(Call.cost)).where(Call.transcript_id == loaded.id)
        )

        found = container.rows_service().rows(
            "t=all&by=errand&m=cost.sum&m=r:rework_share", now=datetime.now(UTC)
        )

        errand = next(row for row in found.rows if row.label == "Scale the recipes")
        cost, share = errand.values
        assert again is not None and cost is not None
        assert share == pytest.approx(float(again) / cost)
