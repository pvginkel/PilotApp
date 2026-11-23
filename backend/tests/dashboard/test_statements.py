"""The statements of a view's rows: one grouped scan per fact, a statement
per fact and grain for the measures over a part's items, a marks statement
per fact where a chip marks, which measures add up and stack, a stand-in's
fact, the By's values a plan is narrowed to, and each statement as the file
of states holds it."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import Catalogue
from app.dashboard.planner import Plan, Planned, plan
from app.dashboard.reading import read
from app.dashboard.state import Simple
from app.dashboard.statements import (
    Items,
    Marked,
    Scan,
    adds,
    described,
    ordered,
    stacks,
    statements,
)
from tests.support.dashboard import catalogue

NOW = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.fixture
def held(session: DbSession) -> Catalogue:
    return catalogue(session)


def _plan(held: Catalogue, written: str) -> Plan:
    return plan(read(written, held, ()).state, held, (), NOW)


class TestStacks:
    @pytest.mark.parametrize(
        ("measure", "color", "stacked"),
        [
            (Simple("cost", "sum"), "model", True),
            (Simple("cost", "sum", "conversation"), "model", True),
            (Simple("calls", "count"), "model", True),
            (Simple("calls", "count", "conversation"), "model", False),
            (Simple("cost", "median"), "model", False),
            (Simple("ctx", "max"), "model", False),
            (Simple("tokens", "sum"), "token_kind", True),
            (Simple("cost", "sum"), "token_kind", False),
            (Simple("cost", "sum"), None, False),
        ],
    )
    def test_a_sum_or_a_count_of_rows_of_a_figure_that_stacks(
        self, held: Catalogue, measure: Simple, color: str | None, stacked: bool
    ) -> None:
        planned = Planned(measure, "call", measure.grain)

        assert stacks(planned, color, held) is stacked

    def test_not_where_its_fact_lacks_the_color(self, held: Catalogue) -> None:
        assert (
            stacks(Planned(Simple("turns", "count"), "turn", None), "model", held)
            is False
        )

    def test_not_where_it_is_refused(self, held: Catalogue) -> None:
        planned = Planned(Simple("cost", "sum"), "call", None, "refused")

        assert stacks(planned, "model", held) is False

    def test_as_its_stand_in_where_one_stands_in(self, held: Catalogue) -> None:
        planned = Planned(
            Simple("reported_cost", "sum"),
            "call",
            None,
            "refused",
            Simple("cost", "sum"),
        )

        assert stacks(planned, "model", held) is True


class TestAdds:
    @pytest.mark.parametrize(
        ("measure", "added"),
        [
            (Simple("cost", "sum"), True),
            (Simple("cost", "sum", "conversation"), True),
            (Simple("calls", "count"), True),
            (Simple("calls", "count", "conversation"), False),
            (Simple("cost", "median"), False),
            (Simple("ctx", "sum"), False),
        ],
    )
    def test_a_sum_or_a_count_of_rows_of_a_figure_that_stacks(
        self, held: Catalogue, measure: Simple, added: bool
    ) -> None:
        assert adds(Planned(measure, "call", measure.grain), held) is added

    def test_not_where_it_is_refused(self, held: Catalogue) -> None:
        planned = Planned(Simple("turns", "count"), "turn", None, "refused")

        assert adds(planned, held) is False


class TestStatements:
    def test_a_scan_per_fact_then_a_statement_per_fact_and_grain(
        self, held: Catalogue
    ) -> None:
        found = statements(
            _plan(
                held,
                "m=cost.sum&m=turns.count&m=cost.median.conversation"
                "&m=calls.count.conversation&m=cost.median&m=cost.p90",
            ),
            held,
        )

        assert [
            (type(one).__name__, one.fact, getattr(one, "grain", None), one.measures)
            for one in found
        ] == [
            ("Scan", "call", None, (0,)),
            ("Scan", "turn", None, (1,)),
            ("Items", "call", "conversation", (2, 3)),
            ("Items", "call", None, (4, 5)),
        ]

    def test_a_fact_scanned_for_its_rows_whatever_its_measures(
        self, held: Catalogue
    ) -> None:
        found = statements(_plan(held, "m=cost.median.conversation"), held)

        assert [(type(one).__name__, one.measures) for one in found] == [
            ("Scan", ()),
            ("Items", (0,)),
        ]

    def test_a_scan_splits_what_stacks_by_the_color(self, held: Catalogue) -> None:
        scan = statements(_plan(held, "m=cost.sum.conversation&col=model"), held)[0]

        assert isinstance(scan, Scan)
        assert (scan.measures, scan.splits, scan.colored) == ((), (0,), True)

    def test_a_scan_splits_by_the_token_kinds_with_no_grouping_of_its_own(
        self, held: Catalogue
    ) -> None:
        scan = statements(_plan(held, "m=tokens.sum&col=token_kind"), held)[0]

        assert isinstance(scan, Scan)
        assert (scan.splits, scan.kinds, scan.colored) == ((0,), (0,), False)

    def test_a_fact_whose_measures_are_all_refused_has_none(
        self, held: Catalogue
    ) -> None:
        assert statements(_plan(held, "by=model&m=turns.count"), held) == ()

    def test_a_marks_statement_per_fact_the_views_measures_read(
        self, held: Catalogue
    ) -> None:
        found = statements(
            _plan(
                held,
                "m=cost.sum&m=cost.median&m=turns.count&c=~miss:1"
                "&c=@rows,gt,1,events.count",
            ),
            held,
        )

        marked = [one for one in found if isinstance(one, Marked)]
        assert [(one.fact, one.measures) for one in marked] == [
            ("call", (0,)),
            ("turn", (2,)),
        ]
        assert [type(one).__name__ for one in found[-2:]] == ["Marked", "Marked"]

    def test_none_with_no_chip_that_marks(self, held: Catalogue) -> None:
        found = statements(_plan(held, "c=~@rows,gt,1,cost.sum&c=~@outliers"), held)

        assert not any(isinstance(one, Marked) for one in found)

    def test_a_stand_in_is_answered_by_its_own_fact(self, held: Catalogue) -> None:
        standing = replace(
            held,
            figures=tuple(
                replace(figure, stands_for="reported_cost")
                if figure.key == "cost"
                else figure
                for figure in held.figures
            ),
        )

        found = statements(_plan(standing, "by=model&m=reported_cost.sum"), standing)

        assert [(type(one).__name__, one.fact, one.measures) for one in found] == [
            ("Scan", "call", (0,)),
        ]

    def test_the_bys_values_it_is_narrowed_to_are_one_array(
        self, held: Catalogue
    ) -> None:
        kept = (*(uuid.uuid4() for _ in range(3_000)), None)
        narrowed = replace(_plan(held, "t=all&by=psession"), rows=kept)

        scan = statements(narrowed, held)[0]
        compiled = scan.select.compile()

        assert "= ANY (" in str(compiled)
        assert "IS NULL" in str(compiled)
        assert [
            list(value) for value in compiled.params.values() if isinstance(value, list)
        ] == [list(kept[:-1])]

    def test_an_items_statement_groups_by_its_items(self, held: Catalogue) -> None:
        found = statements(_plan(held, "m=cost.max.conversation"), held)[1]

        assert isinstance(found, Items)
        compiled = str(found.select.compile())
        assert "GROUPING SETS((r.b, r.item), (r.item))" in compiled
        assert "DISTINCT" not in compiled


class TestOrdered:
    def test_an_order_is_its_own_and_a_part_lies_along_its_first(
        self, held: Catalogue
    ) -> None:
        start = held.dimension("session_start")

        assert ordered(held, start) is start
        assert ordered(held, held.dimension("psession")) is start
        assert ordered(held, held.dimension("project")) is None


class TestDescribed:
    def test_each_with_its_groupings_and_its_joins(self, held: Catalogue) -> None:
        found = _plan(
            held, "m=cost.sum&m=cost.median.conversation&col=model&c=event_kind:denied"
        )

        assert described(found, held) == [
            {
                "fact": "call",
                "grouping": [["project"], [], ["project", "model"]],
                "joins": ["session", "thread", "main", "project"],
                "through": {"event_kind": "event"},
            },
            {
                "fact": "call",
                "items": "conversation",
                "grouping": [["project"], []],
                "joins": ["session", "thread", "main", "project"],
                "through": {"event_kind": "event"},
            },
        ]

    def test_a_marks_statement_and_an_item_condition_through_conversations(
        self, held: Catalogue
    ) -> None:
        found = _plan(held, "m=turns.count&c=~@items,gt,1,cost.sum")

        assert described(found, held)[-1] == {
            "fact": "turn",
            "marks": True,
            "grouping": [["project"]],
            "joins": ["session", "thread", "main", "project"],
            "through": {"@items,gt,1,cost.sum": "call"},
        }
