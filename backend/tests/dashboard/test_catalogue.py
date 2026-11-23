"""The catalogue's shapes (F154.4): a row's paths and joins, what a fact
offers, and the grains and aggregates read from its entries."""

from datetime import timedelta

import pytest
from sqlalchemy import Integer, column, select, table
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import (
    COUNT,
    Aggregate,
    Catalogue,
    Dimension,
    Fact,
    Figure,
    Join,
    Marker,
    QuickFilter,
    Ratio,
    TimeRange,
    Unreachable,
)

_stalls = table("stalls", column("id", Integer), column("market_id", Integer))
_markets = table("markets", column("id", Integer), column("town_id", Integer))
_towns = table("towns", column("id", Integer), column("name"))

SALE = Fact(
    key="sale",
    label="Sales",
    one="sale",
    many="sales",
    source=table("sales", column("stall_id", Integer), column("at")),
    counts="sales",
)
VISIT = Fact(
    key="visit",
    label="Visits",
    one="visit",
    many="visits",
    source=table("visits", column("market_id", Integer), column("at")),
    counts="visits",
    part="visit",
    shows=("town",),
)
JOINS = (
    Join("stall", _stalls, lambda row: _stalls.c.id == row["stall_id"]),
    Join(
        "market",
        _markets,
        lambda row: (
            _markets.c.id
            == (row.to("stall").c.market_id if row.fact is SALE else row["market_id"])
        ),
    ),
    Join("town", _towns, lambda row: _towns.c.id == row.to("market").c.town_id),
)
NEW_STALL = Marker("stall", "New stall", "Where a stall was first seen", "stall")

TOWN = Dimension(
    key="town",
    label="Town",
    group="attribute",
    line="The town the market stands in",
    path=lambda row: row.to("town").c.id,
    name=lambda row: row.to("town").c.name,
)
STALL = Dimension(
    key="stall",
    label="Stall",
    group="part",
    line="One stall",
    path=lambda row: row["stall_id"],
    one="stall",
    many="stalls",
    figures=("sales",),
)
VISITED = Dimension(
    key="visit",
    label="Visit",
    group="part",
    line="One visit",
    path=lambda row: row["at"],
    one="visit",
    many="visits",
)
SALES = Figure(
    key="sales",
    label="Sales",
    fact="sale",
    line="The sales",
    format="count",
    path=lambda row: row["stall_id"],
    aggregate=COUNT,
)
TAKINGS = Figure(
    key="takings",
    label="Takings",
    fact="sale",
    line="What the sales took",
    format="usd",
    path=lambda row: row["at"],
)
AGGREGATES = (Aggregate("sum", "Sum", "Added up"), Aggregate(COUNT, "Count", "Counted"))


MARKET_DAY = QuickFilter("market_day", "Market day", "weekday:6")


def _catalogue(**entries: object) -> Catalogue:
    values: dict[str, object] = {
        "zone": "Europe/Amsterdam",
        "sitting_gap": timedelta(hours=4),
        "facts": (SALE, VISIT),
        "joins": JOINS,
        "dimensions": (TOWN, STALL, VISITED),
        "figures": (SALES, TAKINGS),
        "aggregates": AGGREGATES,
        "ratios": (
            Ratio("each", "Each", "Per sale", "usd", "takings.sum", "sales.count"),
        ),
        "ranges": (TimeRange("all", "All time", "Everything"),),
    }
    return Catalogue(**(values | entries))  # type: ignore[arg-type]


class TestRow:
    def test_a_path_reads_the_facts_own_column(self) -> None:
        row = _catalogue().row(SALE)

        assert row["stall_id"] is SALE.source.c.stall_id
        assert row.taken == ()

    def test_a_column_the_fact_has_not_is_unreachable(self) -> None:
        row = _catalogue().row(VISIT)

        with pytest.raises(Unreachable, match="The fact visit has no column stall_id"):
            row["stall_id"]

    def test_reading_a_join_takes_the_joins_it_starts_from_first(self) -> None:
        row = _catalogue().row(SALE)

        assert row.to("town") is _towns
        assert row.taken == ("stall", "market", "town")

    def test_a_join_is_taken_once(self) -> None:
        row = _catalogue().row(SALE)

        row.to("market")
        row.to("town")
        row.to("market")

        assert row.taken == ("stall", "market", "town")

    def test_the_source_keeps_a_row_a_join_reaches_nothing_from(
        self, session: DbSession
    ) -> None:
        row = _catalogue().row(SALE)
        town = TOWN.path(row)

        statement = str(select(town).select_from(row.source()))

        assert statement == (
            "SELECT towns.id \n"
            "FROM sales LEFT OUTER JOIN stalls ON stalls.id = sales.stall_id"
            " LEFT OUTER JOIN markets ON markets.id = stalls.market_id"
            " LEFT OUTER JOIN towns ON towns.id = markets.town_id"
        )

    def test_a_row_with_no_join_read_is_the_facts_source(self) -> None:
        assert _catalogue().row(VISIT).source() is VISIT.source


class TestCatalogue:
    def test_a_fact_offers_the_dimensions_its_rows_reach(self) -> None:
        catalogue = _catalogue()

        assert catalogue.offered("town") == ("sale", "visit")
        assert catalogue.offered("stall") == ("sale",)

    def test_an_entry_is_found_by_its_key(self) -> None:
        catalogue = _catalogue()

        assert catalogue.fact("visit") is VISIT
        assert catalogue.dimension("town") is TOWN
        assert catalogue.figure("takings") is TAKINGS
        assert catalogue.ratio("each").denominator == "sales.count"
        with pytest.raises(KeyError):
            catalogue.dimension("village")

    @pytest.mark.parametrize(
        ("entries", "twice"),
        [
            ({"facts": (SALE, SALE)}, "fact sale"),
            ({"joins": (*JOINS, JOINS[0])}, "join stall"),
            ({"dimensions": (TOWN, STALL, TOWN)}, "dimension town"),
            ({"figures": (SALES, SALES)}, "figure sales"),
            ({"aggregates": (*AGGREGATES, AGGREGATES[0])}, "aggregate sum"),
            ({"quick_filters": (MARKET_DAY, MARKET_DAY)}, "quick filter market_day"),
            ({"markers": (NEW_STALL, NEW_STALL)}, "marker stall"),
        ],
    )
    def test_a_key_stands_once_among_its_kind(
        self, entries: dict[str, object], twice: str
    ) -> None:
        with pytest.raises(ValueError, match=f"holds the {twice} twice"):
            _catalogue(**entries)

    def test_a_figure_and_a_dimension_may_share_a_key(self) -> None:
        shared = Dimension(
            key="sales",
            label="Sold",
            group="attribute",
            line="Whether it sold",
            path=lambda row: row["at"],
        )

        assert _catalogue(dimensions=(TOWN, shared)).dimension("sales") is shared

    def test_only_a_facts_counting_figure_takes_the_count(self) -> None:
        catalogue = _catalogue()

        assert catalogue.aggregates_of(SALES) == ("sum", COUNT)
        assert catalogue.aggregates_of(TAKINGS) == ("sum",)

    def test_a_grain_is_any_part_and_the_own_row_of_a_fact_that_is_none(self) -> None:
        grains = _catalogue().grains

        assert [(grain.key, grain.one, grain.many) for grain in grains] == [
            ("stall", "stall", "stalls"),
            ("visit", "visit", "visits"),
            ("sale", "sale", "sales"),
        ]
        assert grains[0].figures == ("sales",)
        # The Visit fact's row is the part `visit`: no grain of its own.
        assert [grain.key for grain in grains].count("visit") == 1
