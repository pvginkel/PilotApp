"""Revision 0054: what the dashboard stores, with the five quick filters it
ships with written once, and its downgrade, which takes all of it."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.dashboard.assembly import assemble
from app.dashboard.reading import read_chip
from app.dashboard.state import OnItems, Outliers, Pin, Simple
from app.models import QuickFilter
from app.services.quota_week_service import quota_weeks
from tests.support.dashboard import GAP, ZONE
from tests.support.revisions import run_revision

TABLES = (
    "saved_views",
    "view_stars",
    "dimension_favourites",
    "quick_filters",
    "custom_ratios",
)


def _quick_filters(db: DbSession) -> list[tuple[str, str, str, bool, str | None]]:
    return [
        (row.code, row.label, row.condition, row.marks, row.amount_figure)
        for row in db.scalars(select(QuickFilter).order_by(QuickFilter.label))
    ]


SHIPPED = [
    ("misses", "Cache misses", "miss:1", False, "miss_cost"),
    ("compactions", "Compactions", "compaction:1", False, None),
    ("expensive", "Expensive calls", "@items,gt,1,cost.sum", False, "cost"),
    ("outliers", "Outlier rows", "@outliers", False, None),
    ("past_ttl", "Waits past the cache TTL", "past_ttl:1", False, "miss_cost"),
]


class TestTheUpgrade:
    def test_it_writes_the_five_quick_filters_the_dashboard_ships_with(
        self, session: DbSession
    ) -> None:
        assert _quick_filters(session) == SHIPPED

    def test_each_quick_filters_condition_is_a_chip_the_engine_reads(
        self, session: DbSession
    ) -> None:
        catalogue = assemble(session, ZONE, GAP)
        weeks = quota_weeks(session)

        chips = {
            row.code: read_chip(row.condition, catalogue, weeks)
            for row in session.scalars(select(QuickFilter))
        }

        assert chips == {
            "past_ttl": Pin("past_ttl", (1,)),
            "misses": Pin("miss", (1,)),
            "compactions": Pin("compaction", (1,)),
            "outliers": Outliers(),
            "expensive": OnItems("gt", 1.0, Simple("cost", "sum")),
        }

    def test_each_has_a_line_of_explanation(self, session: DbSession) -> None:
        assert all(session.scalars(select(QuickFilter.note)))


class TestTheDowngrade:
    def test_everything_the_dashboard_stores_goes_with_its_tables_and_types(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0054", "downgrade")

        assert [
            session.scalar(text(f"SELECT to_regclass('{table}')")) for table in TABLES
        ] == [None] * len(TABLES)
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM pg_type"
                    " WHERE typname IN ('origin', 'favourite_menu')"
                )
            )
            == 0
        )

    def test_the_upgrade_after_it_writes_the_quick_filters_again(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0054", "downgrade")
        run_revision(session, "0054", "upgrade")

        assert _quick_filters(session) == SHIPPED
