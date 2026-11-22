"""The planner (F154.1): a checked state's window, scope, measures and what
its statements leave; and the query it means, as the file of states holds
it."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import Catalogue
from app.dashboard.planner import (
    Condition,
    Plan,
    Planned,
    PlannedRatio,
    described,
    plan,
    window,
)
from app.dashboard.reading import read
from app.dashboard.state import Between, Preset, RatioKey, Simple, Weeks
from app.services.quota_week_service import Period
from tests.support.dashboard import catalogue

THIS = datetime(2026, 11, 19, 10, tzinfo=UTC)
LAST = THIS - timedelta(days=7)
BEFORE = LAST - timedelta(days=7)
WEEKS = (
    Period(BEFORE, LAST),
    Period(LAST, THIS),
    Period(THIS, THIS + timedelta(days=7)),
)
NOW = datetime(2026, 11, 22, 23, 30, tzinfo=UTC)
"""Monday 23 November 2026, half past midnight in Europe/Amsterdam."""

PROJECT = "5b0e6a4c-2f4a-4d7e-9b1e-0c3f0c7c1a2b"


@pytest.fixture
def held(session: DbSession) -> Catalogue:
    return catalogue(session)


def _plan(held: Catalogue, written: str) -> Plan:
    return plan(read(written, held, WEEKS).state, held, WEEKS, NOW)


class TestWindow:
    def test_all_time_is_none(self, held: Catalogue) -> None:
        assert window(Preset("all"), held, WEEKS, NOW) is None

    def test_a_range_of_days_is_its_days_in_the_zone(self, held: Catalogue) -> None:
        assert window(Preset("d2"), held, WEEKS, NOW) == (
            (
                datetime(2026, 11, 21, 23, tzinfo=UTC),
                datetime(2026, 11, 23, 23, tzinfo=UTC),
            ),
        )

    def test_this_quota_week_is_the_latest_the_record_holds(
        self, held: Catalogue
    ) -> None:
        assert window(Preset("qw"), held, WEEKS, NOW) == (
            (THIS, THIS + timedelta(days=7)),
        )

    def test_weeks_that_follow_each_other_are_one_span(self, held: Catalogue) -> None:
        assert window(Preset("l4"), held, WEEKS, NOW) == (
            (BEFORE, THIS + timedelta(days=7)),
        )

    def test_weeks_apart_are_a_span_each(self, held: Catalogue) -> None:
        assert window(Weeks((BEFORE, THIS)), held, WEEKS, NOW) == (
            (BEFORE, LAST),
            (THIS, THIS + timedelta(days=7)),
        )

    def test_weeks_the_record_does_not_reach_are_none_of_it(
        self, held: Catalogue
    ) -> None:
        assert window(Preset("lqw"), held, WEEKS[-1:], NOW) == ()

    def test_a_range_between_a_time_of_day_and_a_date_in_the_zone(
        self, held: Catalogue
    ) -> None:
        between = Between(datetime(2026, 11, 1, 8, 30), datetime(2026, 11, 7).date())

        assert window(between, held, WEEKS, NOW) == (
            (
                datetime(2026, 11, 1, 7, 30, tzinfo=UTC),
                datetime(2026, 11, 7, 23, tzinfo=UTC),
            ),
        )

    def test_a_range_open_at_a_side(self, held: Catalogue) -> None:
        assert window(
            Between(datetime(2026, 11, 1).date(), None), held, WEEKS, NOW
        ) == ((datetime(2026, 10, 31, 23, tzinfo=UTC), None),)


class TestPlan:
    def test_its_scope_is_the_drill_and_the_chips_on_values(
        self, held: Catalogue
    ) -> None:
        found = _plan(
            held,
            f"dr=project:{PROJECT}@project&dr=psession:~&c=!source:chat,pilot"
            "&c=effort:high,~",
        )

        assert [condition.written() for condition in found.scope] == [
            f"project:{PROJECT}",
            "psession:~",
            "!source:chat,pilot",
            "effort:high,~",
        ]
        assert found.after == ()

    def test_an_order_dimensions_chip_is_its_parts(self, held: Catalogue) -> None:
        found = _plan(held, f"c=session_start:{PROJECT}")

        assert found.scope[0].dimension == "psession"

    def test_it_leaves_what_its_statements_do_not_apply(self, held: Catalogue) -> None:
        found = _plan(
            held,
            "c=~miss:1&c=@rows,gt,100,cost.sum&c=!@items,ge,1.5,cost.sum&c=@outliers",
        )

        assert found.scope == ()
        assert found.after == (
            "~miss:1",
            "@rows,gt,100,cost.sum",
            "!@items,ge,1.5,cost.sum",
            "@outliers",
        )

    def test_a_measure_is_its_figures_fact_at_its_grain(self, held: Catalogue) -> None:
        found = _plan(held, "m=cost.median.conversation&m=turns.count&m=events.count")

        assert found.measures == (
            Planned(Simple("cost", "median", "conversation"), "call", "conversation"),
            Planned(Simple("turns", "count"), "turn", None),
            Planned(Simple("events", "count"), "event", None),
        )

    def test_one_whose_fact_has_no_by_is_refused_with_why(
        self, held: Catalogue
    ) -> None:
        found = _plan(held, "by=model&m=turns.count")

        assert found.measures[0] == Planned(
            Simple("turns", "count"),
            "turn",
            None,
            "turns is a figure of Pilot turns, which have no model",
        )

    def test_a_ratio_by_its_key_has_the_catalogues_sides(self, held: Catalogue) -> None:
        found = _plan(held, "m=r:per_call")

        assert found.measures[0] == PlannedRatio(
            RatioKey("per_call"),
            Planned(Simple("cost", "sum"), "call", None),
            Planned(Simple("calls", "count"), "call", None),
        )

    def test_its_simples_are_each_measure_once_a_ratios_sides_among_them(
        self, held: Catalogue
    ) -> None:
        found = _plan(held, "m=cost.sum&m=r:per_call&m=r:Share:miss_cost.sum/cost.sum")

        assert [one.measure for one in found.simples] == [
            Simple("cost", "sum"),
            Simple("calls", "count"),
            Simple("miss_cost", "sum"),
        ]

    def test_it_carries_the_by_the_color_and_the_focus(self, held: Catalogue) -> None:
        found = _plan(held, f"by=psession&col=model&f=project:{PROJECT}")

        assert (found.by, found.color) == ("psession", "model")
        assert found.focus is not None
        assert str(found.focus.key) == PROJECT


class TestDescribed:
    def test_a_range_by_its_key_and_another_by_its_spans(self, held: Catalogue) -> None:
        by_key = described(_plan(held, "t=qw"), [])
        by_spans = described(_plan(held, "t=c,2026-11-01,"), [])

        assert by_key["time"] == "qw"
        assert by_spans["time"] == [["2026-10-31T23:00:00Z", None]]

    def test_each_part_the_query_reads(self, held: Catalogue) -> None:
        found = _plan(
            held,
            f"by=model&m=turns.count&m=r:per_call&m=cost.p90.conversation"
            f"&c=!source:work&c=~miss:1&f=project:{PROJECT}&col=effort",
        )

        assert described(found, [{"fact": "call"}]) == {
            "time": "qw",
            "by": "model",
            "color": "effort",
            "focus": f"project:{PROJECT}",
            "scope": ["!source:work"],
            "measures": [
                {
                    "measure": "turns.count",
                    "fact": "turn",
                    "refused": "turns is a figure of Pilot turns, which have no model",
                },
                {
                    "measure": "r:per_call",
                    "over": [
                        {"measure": "cost.sum", "fact": "call"},
                        {"measure": "calls.count", "fact": "call"},
                    ],
                },
                {
                    "measure": "cost.p90.conversation",
                    "fact": "call",
                    "items": "conversation",
                },
            ],
            "statements": [{"fact": "call"}],
            "after": ["~miss:1"],
        }

    def test_a_condition_writes_none_as_a_state_does(self) -> None:
        assert Condition("effort", ("high", None), True).written() == "!effort:high,~"
