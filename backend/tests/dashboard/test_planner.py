"""The planner (F154.1): a checked state's window, scope, measures, marks,
thresholds and outlier rows, the quick filters' chips and a refused
measure's stand-in; and the query it means, as the file of states holds
it."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import Catalogue, QuickFilter
from app.dashboard.planner import (
    Condition,
    Plan,
    Planned,
    PlannedRatio,
    Threshold,
    asked,
    described,
    plan,
    series_plan,
    window,
)
from app.dashboard.reading import read
from app.dashboard.state import (
    Between,
    Filter,
    OnItems,
    Preset,
    RatioKey,
    Simple,
    Weeks,
)
from app.exceptions import StateRefusedException
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
        assert (found.marks, found.thresholds, found.outliers) == ((), (), None)
        assert not found.judges

    def test_an_order_dimensions_chip_is_its_parts(self, held: Catalogue) -> None:
        found = _plan(held, f"c=session_start:{PROJECT}")

        assert isinstance(found.scope[0], Condition)
        assert found.scope[0].dimension == "psession"

    def test_a_condition_on_each_item_keeps_or_marks_rows(
        self, held: Catalogue
    ) -> None:
        found = _plan(
            held, "c=!@items,ge,1.5,cost.sum.conversation&c=~@items,gt,1,cost.sum"
        )

        assert found.scope == (
            OnItems("ge", 1.5, Simple("cost", "sum", "conversation"), negated=True),
        )
        assert found.marks == (OnItems("gt", 1, Simple("cost", "sum")),)

    def test_a_marked_chip_on_values_marks(self, held: Catalogue) -> None:
        found = _plan(held, "c=~!miss:1&c=effort:high")

        assert found.scope == (Condition("effort", ("high",)),)
        assert found.marks == (Condition("miss", (1,), negated=True),)

    def test_a_threshold_on_the_bys_rows_is_its_measure_planned(
        self, held: Catalogue
    ) -> None:
        found = _plan(
            held, "by=model&c=@rows,gt,100,turns.count&c=~@rows,le,0.5,r:per_call"
        )

        assert found.thresholds == (
            Threshold(
                Planned(
                    Simple("turns", "count"),
                    "turn",
                    None,
                    "turns is a figure of Pilot turns, which have no model",
                ),
                "gt",
                100,
            ),
            Threshold(
                PlannedRatio(
                    RatioKey("per_call"),
                    Planned(Simple("cost", "sum"), "call", None),
                    Planned(Simple("calls", "count"), "call", None),
                ),
                "le",
                0.5,
                marked=True,
            ),
        )
        assert found.judges

    def test_its_simples_take_the_thresholds_after_the_views(
        self, held: Catalogue
    ) -> None:
        found = _plan(held, "m=miss_cost.sum&c=@rows,gt,1,r:per_call")

        assert [one.measure for one in found.simples] == [
            Simple("miss_cost", "sum"),
            Simple("cost", "sum"),
            Simple("calls", "count"),
        ]

    @pytest.mark.parametrize(
        ("written", "judged"),
        [
            ("c=@outliers", "keep"),
            ("c=~@outliers", "mark"),
            ("c=~@outliers&c=@outliers", "keep"),
            ("c=@outliers&c=~@outliers", "keep"),
        ],
    )
    def test_the_outlier_rows_chip_keeps_where_any_keeps(
        self, held: Catalogue, written: str, judged: str
    ) -> None:
        found = _plan(held, written)

        assert found.outliers == judged
        assert found.judges

    def test_a_quick_filter_that_is_on_is_its_chip(self, held: Catalogue) -> None:
        found = _plan(held, "b=misses,expensive,outliers")

        assert found.scope == (
            OnItems("gt", 1, Simple("cost", "sum")),
            Condition("miss", (1,)),
        )
        assert found.outliers == "keep"

    def test_a_quick_filter_that_marks_marks(self, held: Catalogue) -> None:
        marking = replace(
            held,
            quick_filters=(
                QuickFilter("marked_misses", "Misses", "miss:1", marks=True),
                QuickFilter("marked_outliers", "Outliers", "@outliers", marks=True),
            ),
        )

        found = _plan(marking, "b=marked_misses,marked_outliers")

        assert found.scope == ()
        assert found.marks == (Condition("miss", (1,)),)
        assert found.outliers == "mark"

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

    def test_one_refused_is_answered_by_its_stand_in(self, held: Catalogue) -> None:
        standing = _standing(held, "cost", "reported_cost")

        found = _plan(
            standing,
            "by=model&m=reported_cost.sum(source=chat)&m=reported_cost.median.psession",
        )

        why = "reported_cost is a figure of Pilot turns, which have no model"
        chats = (Filter("source", ("chat",)),)
        assert found.measures == (
            Planned(
                Simple("reported_cost", "sum", filters=chats),
                "call",
                None,
                why,
                Simple("cost", "sum", filters=chats),
            ),
            Planned(
                Simple("reported_cost", "median", "psession"),
                "call",
                "psession",
                why,
                Simple("cost", "median", "psession"),
            ),
        )
        assert all(planned.answers for planned in found.simples)
        assert found.simples[0].answered.figure == "cost"

    @pytest.mark.parametrize(
        ("standing", "stands_for", "written"),
        [
            ("cost", "reported_cost", "by=model&m=turns.count"),
            ("cost", "reported_cost", "by=event_kind&m=reported_cost.sum"),
            ("cost", "turns", "by=model&m=turns.count"),
        ],
        ids=["no figure stands for it", "on a fact with no By", "no such aggregate"],
    )
    def test_one_with_no_stand_in_is_refused_alone(
        self, held: Catalogue, standing: str, stands_for: str, written: str
    ) -> None:
        found = _plan(_standing(held, standing, stands_for), written)

        refused = found.simples[0]
        assert refused.refused is not None
        assert refused.stand_in is None
        assert not refused.answers

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


def _standing(held: Catalogue, standing: str, stands_for: str) -> Catalogue:
    """The catalogue with the figure `standing` standing for `stands_for`."""
    return replace(
        held,
        figures=tuple(
            replace(figure, stands_for=stands_for) if figure.key == standing else figure
            for figure in held.figures
        ),
    )


class TestSeriesPlan:
    @pytest.mark.parametrize(
        ("written", "by"),
        [
            ("p=time,hod", "hod"),
            ("by=psession&p=order", "session_start"),
            ("by=pturn&p=order,turn_seq", "turn_seq"),
            ("by=psession", "psession"),
        ],
    )
    def test_the_dimension_a_view_asks(
        self, held: Catalogue, written: str, by: str
    ) -> None:
        assert asked(read(written, held, WEEKS).state, held) == by

    def test_its_rows_are_by_the_dimension_asked(self, held: Catalogue) -> None:
        state = read("dr=project:" + PROJECT + "&p=time,day", held, WEEKS).state

        found = series_plan(state, held, WEEKS, NOW)

        assert found.by == "day"
        assert found.scope == (Condition("project", (uuid.UUID(PROJECT),)),)

    @pytest.mark.parametrize("written", ["by=project", "by=call&p=lanes", "p=table"])
    def test_a_view_with_no_series_is_refused(
        self, held: Catalogue, written: str
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            series_plan(read(written, held, WEEKS).state, held, WEEKS, NOW)

        assert refused.value.faults[0].kind == "p"


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
            f"&c=!source:work&c=~miss:1&c=@items,gt,1,cost.sum.psession"
            f"&c=@rows,gt,2,cost.sum&c=~@rows,lt,0.5,r:per_call&c=~@outliers"
            f"&f=project:{PROJECT}&col=effort",
        )

        assert described(found, [{"fact": "call"}]) == {
            "time": "qw",
            "by": "model",
            "color": "effort",
            "focus": f"project:{PROJECT}",
            "scope": ["!source:work", "@items,gt,1,cost.sum.psession"],
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
            "marks": ["miss:1"],
            "thresholds": [
                {"keeps": "gt,2", "measure": {"measure": "cost.sum", "fact": "call"}},
                {
                    "marks": "lt,0.5",
                    "measure": {
                        "measure": "r:per_call",
                        "over": [
                            {"measure": "cost.sum", "fact": "call"},
                            {"measure": "calls.count", "fact": "call"},
                        ],
                    },
                },
            ],
            "outliers": "mark",
        }

    def test_a_stand_in_beside_the_measure_it_stands_in_for(
        self, held: Catalogue
    ) -> None:
        found = _plan(
            _standing(held, "cost", "reported_cost"), "by=model&m=reported_cost.sum"
        )

        assert described(found, [])["measures"] == [
            {
                "measure": "reported_cost.sum",
                "fact": "call",
                "refused": (
                    "reported_cost is a figure of Pilot turns, which have no model"
                ),
                "stand_in": "cost.sum",
            }
        ]

    def test_a_condition_writes_none_as_a_state_does(self) -> None:
        assert Condition("effort", ("high", None), True).written() == "!effort:high,~"
