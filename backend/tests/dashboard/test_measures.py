"""The figures, the aggregates, the built-in ratios and the time ranges
Pilot's code declares (F154.4, F155.3), the figures read on the record."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.catalogue import COUNT
from app.dashboard.facts import FACTS
from app.dashboard.measures import AGGREGATES, FIGURES, RANGES, RATIOS, TOKEN_KINDS
from app.models import Project, User
from tests.support.dashboard import Record, catalogue, read, record


@pytest.fixture
def held(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


def _figure(session: DbSession, key: str) -> list[object]:
    """The figure on each row of its fact, in the rows' order."""
    index = catalogue(session)
    figure = index.figure(key)
    return [
        value
        for (value,) in read(
            session, index, figure.fact, figure.path, by=lambda row: row["at"]
        )
    ]


class TestFigures:
    def test_every_figure_is_of_a_fact_pilots_code_declares(self) -> None:
        facts = {fact.key: fact for fact in FACTS}

        assert {figure.fact for figure in FIGURES} == set(facts)
        for fact in facts.values():
            counting = [figure for figure in FIGURES if figure.key == fact.counts]
            assert [figure.fact for figure in counting] == [fact.key]
            assert counting[0].aggregate == COUNT

    def test_a_calls_cost_tokens_and_context(
        self, session: DbSession, held: Record
    ) -> None:
        assert _figure(session, "cost") == [
            Decimal("0.50"),
            Decimal("0.25"),
            Decimal("0.10"),
            Decimal("1.00"),
            Decimal("0.75"),
            Decimal("0.05"),
        ]
        a_call = 1_204 + 3_310 + 48_112 + 2_870
        assert _figure(session, "tokens") == [a_call] * 4 + [32_500, a_call]
        context = 1_204 + 3_310 + 48_112
        assert _figure(session, "ctx") == [context] * 4 + [None, context]
        assert _figure(session, "calls") == [1] * 6

    def test_the_tokens_split_by_the_kinds_within_none(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        tokens = index.figure("tokens")
        assert tokens.kinds is not None
        assert (
            tuple(tokens.kinds)
            == TOKEN_KINDS
            == (
                "input",
                "cache_write",
                "cache_read",
                "output",
            )
        )

        rows = read(
            session, index, "call", *tokens.kinds.values(), by=lambda row: row["at"]
        )

        assert rows[0] == (1_204, 3_310, 48_112, 2_870)
        assert rows[4] == (100, 2_000, 30_000, 400)
        assert [figure.key for figure in FIGURES if figure.kinds] == ["tokens"]

    def test_the_misses_the_rewinds_the_compactions_and_the_waits(
        self, session: DbSession, held: Record
    ) -> None:
        assert _figure(session, "misses") == [0, 0, 0, 1, 0, 0]
        assert _figure(session, "miss_cost") == [
            None,
            None,
            None,
            Decimal("1.00"),
            None,
            None,
        ]
        assert _figure(session, "rewinds") == [0, 1, 0, 0, 0, 0]
        assert _figure(session, "past_ttl") == [0, 1, 0, 0, 0, 0]
        assert _figure(session, "compactions") == [0, 0, 0, 1, 0, 0]

    def test_waited_is_the_records_and_took_from_sending_to_completion(
        self, session: DbSession, held: Record
    ) -> None:
        assert _figure(session, "waited") == [None, 30.0, None, None, None, None]
        # Only the second Call has a sending time, 30 s before it completed.
        assert _figure(session, "took") == [None, Decimal(30), None, None, None, None]

    def test_a_turns_figures_with_its_reported_cost(
        self, session: DbSession, held: Record
    ) -> None:
        assert _figure(session, "turns") == [1, 1]
        assert _figure(session, "turn_time") == [600.0, 180.0]
        assert _figure(session, "failed_turns") == [0, 1]
        assert _figure(session, "reported_cost") == [Decimal("2.50"), Decimal("0.75")]

    def test_the_events_and_those_that_are_errors(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        row = index.row(index.fact("event"))

        events, errors = session.execute(
            select(
                func.sum(index.figure("events").path(row)),
                func.sum(index.figure("error_events").path(row)),
            ).select_from(row.source())
        ).one()

        # The API error, the fallback, the cut-off response and the hook.
        assert (events, errors) == (10, 4)

    def test_only_the_peak_context_is_an_items_largest(self) -> None:
        largest = [figure.key for figure in FIGURES if figure.within == "max"]

        assert largest == ["ctx"]
        assert [figure.key for figure in FIGURES if not figure.stacks] == ["ctx"]


class TestAggregates:
    def test_the_aggregates_a_measure_takes(self, session: DbSession) -> None:
        index = catalogue(session)

        assert [aggregate.key for aggregate in AGGREGATES] == [
            "sum",
            "median",
            "mean",
            "max",
            "p90",
            "count",
        ]
        assert index.aggregates_of(index.figure("cost")) == (
            "sum",
            "median",
            "mean",
            "max",
            "p90",
        )
        assert COUNT in index.aggregates_of(index.figure("calls"))
        for figure in FIGURES:
            assert figure.aggregate in index.aggregates_of(figure)


class TestRatios:
    def test_the_built_in_ratios_name_nothing_of_a_workflow(self) -> None:
        assert [
            (ratio.key, ratio.numerator, ratio.denominator, ratio.format)
            for ratio in RATIOS
        ] == [
            (
                "overhead",
                "cost.sum(source=chat|pilot)",
                "cost.sum(source=work)",
                "share",
            ),
            ("miss_share", "miss_cost.sum", "cost.sum", "share"),
            ("per_call", "cost.sum", "calls.count", "usd"),
        ]

    def test_each_side_names_a_figure_an_aggregate_it_takes_and_values_it_has(
        self, session: DbSession
    ) -> None:
        index = catalogue(session)

        for ratio in RATIOS:
            for side in (ratio.numerator, ratio.denominator):
                measure, _, condition = side.partition("(")
                figure, aggregate = measure.split(".")
                assert aggregate in index.aggregates_of(index.figure(figure))
                if condition:
                    dimension, values = condition.rstrip(")").split("=")
                    held = index.dimension(dimension)
                    assert held.values is not None
                    assert set(values.split("|")) <= {v.code for v in held.values}
                    assert index.figure(figure).fact in index.offered(dimension)


class TestRanges:
    def test_the_ranges_a_state_names(self) -> None:
        assert [
            (range_.key, range_.unit, range_.count, range_.back) for range_ in RANGES
        ] == [
            ("today", "day", 1, 0),
            ("d2", "day", 2, 0),
            ("d7", "day", 7, 0),
            ("qw", "quota_week", 1, 0),
            ("lqw", "quota_week", 1, 1),
            ("l2", "quota_week", 2, 0),
            ("l4", "quota_week", 4, 0),
            ("l8", "quota_week", 8, 0),
            ("all", None, 1, 0),
        ]
