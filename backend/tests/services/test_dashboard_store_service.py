"""What the dashboard stores (F155): Pilot's own system views made what the
release holds, a load of an Origin's system views by key (F155.3; DB 601 to
604), and the saved views as they are listed."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.views import VIEWS, SystemView
from app.models import SavedView, User, ViewStar
from app.models.reference import Origin
from app.services.container import ServiceContainer
from app.services.dashboard_store_service import DashboardStoreService, Loaded

EARLIER = datetime(2026, 11, 1, 9, tzinfo=UTC)
NOW = datetime(2026, 11, 22, 9, tzinfo=UTC)
STATE = "t=qw&by=project&m=cost.sum&col=none"
OTHER_STATE = "t=d7&by=model&m=cost.sum&col=none"

PANTRY = SystemView("pantry", "Pantry", STATE, "What the pantry's runs cost")
LARDER = SystemView("larder", "Larder", OTHER_STATE)


def _row(db: DbSession, origin: Origin, key: str) -> SavedView:
    return db.scalars(
        select(SavedView).where(SavedView.origin_code == origin, SavedView.key == key)
    ).one()


def _rows(db: DbSession, origin: Origin) -> list[tuple[str | None, str, str]]:
    return [
        (row.key, row.name, row.state)
        for row in db.scalars(
            select(SavedView)
            .where(SavedView.origin_code == origin)
            .order_by(SavedView.key)
        )
    ]


def _star(db: DbSession, user: User, view: SavedView) -> None:
    db.add(ViewStar(user_id=user.id, saved_view_id=view.id, starred_at=EARLIER))
    db.flush()


def _stars(db: DbSession) -> list[tuple[str | None, str]]:
    return [
        (key, name)
        for key, name in db.execute(
            select(SavedView.key, SavedView.name)
            .join(ViewStar, ViewStar.saved_view_id == SavedView.id)
            .order_by(SavedView.key)
        )
    ]


@pytest.fixture
def service(container: ServiceContainer) -> DashboardStoreService:
    return container.dashboard_store_service()


@pytest.fixture
def stored(session: DbSession, service: DashboardStoreService) -> None:
    """No saved view but the workflow's two, loaded earlier."""
    session.execute(delete(SavedView))
    service.load_views(Origin.WORKFLOW, (PANTRY, LARDER), EARLIER)


class TestShip:
    def test_it_adds_pilots_own_views_where_none_is_stored(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        session.execute(delete(SavedView))

        assert service.ship(NOW) == Loaded(added=3, changed=0, removed=0)
        assert _rows(session, Origin.PILOT) == sorted(
            (view.key, view.name, view.state) for view in VIEWS
        )
        assert {row.saved_at for row in session.scalars(select(SavedView))} == {NOW}

    def test_views_that_are_the_releases_are_left_as_they_were(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """The suite's database holds them from its deploy step."""
        before = {
            row.id: row.saved_at
            for row in session.scalars(
                select(SavedView).where(SavedView.origin_code == Origin.PILOT)
            )
        }

        assert service.ship(NOW) == Loaded(added=0, changed=0, removed=0)
        assert {
            row.id: row.saved_at
            for row in session.scalars(
                select(SavedView).where(SavedView.origin_code == Origin.PILOT)
            )
        } == before

    def test_one_another_release_left_is_made_this_releases_in_place(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        view = _row(session, Origin.PILOT, "projects")
        view.name, view.state, view.note = "Old projects", STATE, None
        _star(session, person, view)

        assert service.ship(NOW) == Loaded(added=0, changed=1, removed=0)
        session.refresh(view)
        assert (view.name, view.state, view.note, view.saved_at) == (
            VIEWS[0].name,
            VIEWS[0].state,
            VIEWS[0].note,
            NOW,
        )
        assert _stars(session) == [("projects", "Projects")]

    def test_one_the_release_no_longer_holds_is_removed_its_stars_with_it(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        gone = SavedView(
            origin_code=Origin.PILOT,
            key="gone",
            name="Gone",
            state=STATE,
            saved_at=EARLIER,
        )
        session.add(gone)
        session.flush()
        _star(session, person, gone)

        assert service.ship(NOW) == Loaded(added=0, changed=0, removed=1)
        assert "gone" not in {key for key, _, _ in _rows(session, Origin.PILOT)}
        assert _stars(session) == []

    def test_a_person_s_view_under_a_system_views_name_stands_beside_it(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """DB 602: one name once among the system views and once among the
        others."""
        session.execute(delete(SavedView))
        session.add(
            SavedView(
                origin_code=Origin.PERSON,
                name="Projects",
                state=STATE,
                saved_at=EARLIER,
            )
        )
        session.flush()

        service.ship(NOW)

        assert [(view.system, view.name) for view in service.saved_views()] == [
            (True, "Projects"),
            (True, "Where the week went"),
            (True, "Work types"),
            (False, "Projects"),
        ]


@pytest.mark.usefixtures("stored")
class TestLoadViews:
    def test_it_leaves_the_origins_views_the_entries_it_is_given(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        moved = SystemView("cellar", "Cellar", OTHER_STATE)

        loaded = service.load_views(Origin.WORKFLOW, (PANTRY, moved), NOW)

        assert loaded == Loaded(added=1, changed=0, removed=1)
        assert _rows(session, Origin.WORKFLOW) == [
            ("cellar", "Cellar", OTHER_STATE),
            ("pantry", "Pantry", STATE),
        ]

    def test_an_entry_is_matched_by_its_key_so_a_renamed_one_keeps_its_row_and_stars(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        """DB 603 and 604."""
        pantry = _row(session, Origin.WORKFLOW, "pantry")
        _star(session, person, pantry)

        service.load_views(
            Origin.WORKFLOW,
            (SystemView("pantry", "The pantry", OTHER_STATE), LARDER),
            NOW,
        )

        assert _row(session, Origin.WORKFLOW, "pantry").id == pantry.id
        assert _stars(session) == [("pantry", "The pantry")]

    def test_an_entry_changed_is_saved_at_the_load_and_one_unchanged_keeps_its_time(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        service.load_views(
            Origin.WORKFLOW, (PANTRY, SystemView("larder", "Larder", STATE)), NOW
        )

        assert [
            (row.key, row.saved_at)
            for row in session.scalars(select(SavedView).order_by(SavedView.key))
        ] == [("larder", NOW), ("pantry", EARLIER)]

    def test_a_name_a_removed_view_held_is_free_for_an_entry(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        service.load_views(
            Origin.WORKFLOW, (SystemView("cellar", "Pantry", STATE), LARDER), NOW
        )

        assert _rows(session, Origin.WORKFLOW) == [
            ("cellar", "Pantry", STATE),
            ("larder", "Larder", OTHER_STATE),
        ]

    def test_it_leaves_the_other_origins_views_alone(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        session.add(
            SavedView(
                origin_code=Origin.PERSON, name="Mine", state=STATE, saved_at=EARLIER
            )
        )
        service.ship(NOW)

        service.load_views(Origin.WORKFLOW, (), NOW)

        assert _rows(session, Origin.WORKFLOW) == []
        assert len(_rows(session, Origin.PILOT)) == len(VIEWS)
        assert _rows(session, Origin.PERSON) == [(None, "Mine", STATE)]


class TestSavedViews:
    @pytest.mark.usefixtures("stored")
    def test_the_system_views_come_first_and_each_list_by_name(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        session.add_all(
            SavedView(
                origin_code=Origin.PERSON, name=name, state=STATE, saved_at=EARLIER
            )
            for name in ("Writers", "Apples")
        )
        session.flush()

        assert [view.name for view in service.saved_views()] == [
            "Larder",
            "Pantry",
            "Apples",
            "Writers",
        ]
