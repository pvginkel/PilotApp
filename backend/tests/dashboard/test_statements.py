"""The statements of a view's rows: one grouped scan per fact, a statement
per fact and grain for the measures over a part's items, which measures
stack, and each statement as the file of states holds it."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import Catalogue
from app.dashboard.planner import Plan, Planned, plan
from app.dashboard.reading import read
from app.dashboard.state import Simple
from app.dashboard.statements import Items, Scan, described, stacks, statements
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

    def test_an_items_statement_groups_by_its_items(self, held: Catalogue) -> None:
        found = statements(_plan(held, "m=cost.max.conversation"), held)[1]

        assert isinstance(found, Items)
        compiled = str(found.select.compile())
        assert "GROUPING SETS((r.b, r.item), (r.item))" in compiled
        assert "DISTINCT" not in compiled


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
