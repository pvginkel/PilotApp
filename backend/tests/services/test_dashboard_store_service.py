"""What the dashboard stores (F155): Pilot's own system views made what the
release holds, a load of an Origin's system views by key, and the load of the
workflow's views and ratios from its file, on an invented one, every entry
checked before any is written (F155.3; DB 601 to 604); the saved views saved, renamed and removed by anyone, a system view by
no one (F155.1, DB 601); a person's stars and favourite dimensions (F155.2);
the quick filters made and removed; and the ratios a person made, made,
changed and removed, a loaded one by no one (F155.3), each in the normal form
a view's state writes (F155.4)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.views import VIEWS, SystemView
from app.exceptions import (
    InvalidOperationException,
    RecordNotFoundException,
    ResourceConflictException,
    StateRefusedException,
    ValidationException,
)
from app.models import (
    CustomRatio,
    DimensionFavourite,
    QuickFilter,
    SavedView,
    User,
    ViewStar,
)
from app.models.reference import FavouriteMenu, Origin, UserKind
from app.services.container import ServiceContainer
from app.services.dashboard_store_service import (
    DashboardStoreService,
    Favourites,
    Loaded,
    RatioEntry,
    WorkflowLoaded,
)
from app.utils.after_commit import run_after_commit_callbacks
from tests.support import workflow_views

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

    def test_two_views_that_swap_their_names_in_one_call_are_loaded(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        swapped = (
            SystemView("pantry", "Larder", STATE),
            SystemView("larder", "Pantry", OTHER_STATE),
        )

        loaded = service.load_views(Origin.WORKFLOW, swapped, NOW)

        assert loaded == Loaded(added=0, changed=2, removed=0)
        assert _rows(session, Origin.WORKFLOW) == [
            ("larder", "Pantry", OTHER_STATE),
            ("pantry", "Larder", STATE),
        ]


ERRANDS = "t=l8&by=project&m=cost.sum&m=r:per_serving&col=model"
LEGS = "t=qw&by=conversation&m=cost.median&col=none&roll=5,5"
RIDES = "t=d7&by=project&p=time,day&m=cost.sum&m=r:per_ride&col=source"


def _ratios(db: DbSession, origin: Origin) -> list[tuple[str, str, str, str]]:
    return [
        (row.key, row.name, row.numerator, row.denominator)
        for row in db.scalars(
            select(CustomRatio)
            .where(CustomRatio.origin_code == origin)
            .order_by(CustomRatio.key)
        )
    ]


@pytest.fixture
def from_the_file(service: DashboardStoreService) -> None:
    """The invented file loaded, earlier."""
    service.load_workflow(*workflow_views.entries(), EARLIER)


class TestLoadWorkflow:
    def test_the_file_is_loaded_each_entry_in_its_normal_form(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        loaded = service.load_workflow(*workflow_views.entries(), NOW)

        assert loaded == WorkflowLoaded(
            views=Loaded(added=3, changed=0, removed=0),
            ratios=Loaded(added=2, changed=0, removed=0),
            notes=(),
        )
        assert _rows(session, Origin.WORKFLOW) == [
            ("errands", "Errands", ERRANDS),
            ("legs", "Legs", LEGS),
            ("rides", "Rides", RIDES),
        ]
        assert _ratios(session, Origin.WORKFLOW) == [
            ("per_ride", "Cost per ride", "cost.sum", "turns.count"),
            ("per_serving", "Cost per serving", "cost.sum", "calls.count"),
        ]
        assert _row(session, Origin.WORKFLOW, "errands").note == (
            "What each project's errands cost over the last eight quota weeks, "
            "and per serving"
        )

    def test_a_view_by_a_unit_keeps_the_band_its_state_sets(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """F154.1: the length is the view's, the load setting none by a
        kind's name; a view that sets none takes ten and fifteen."""
        service.load_workflow(*workflow_views.entries(), NOW)

        assert _row(session, Origin.WORKFLOW, "legs").state.endswith("&roll=5,5")
        assert "roll=" not in _row(session, Origin.WORKFLOW, "rides").state

    @pytest.mark.usefixtures("from_the_file")
    def test_a_load_again_changes_by_key_adds_and_removes_the_stars_going_with_a_view(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        """DB 604."""
        errands = _row(session, Origin.WORKFLOW, "errands")
        _star(session, person, errands)
        _star(session, person, _row(session, Origin.WORKFLOW, "rides"))
        views = (
            SystemView("errands", "Errands by week", ERRANDS),
            SystemView("legs", "Legs", LEGS),
            SystemView("suppers", "Suppers", "t=qw&by=project&m=cost.sum&col=none"),
        )
        ratios = (
            RatioEntry("per_serving", "Cost per serving", "cost.sum", "turns.count"),
            RatioEntry("per_supper", "Cost per supper", "cost.sum", "calls.count"),
        )

        loaded = service.load_workflow(views, ratios, NOW)

        assert loaded == WorkflowLoaded(
            views=Loaded(added=1, changed=1, removed=1),
            ratios=Loaded(added=1, changed=1, removed=1),
            notes=(),
        )
        assert _row(session, Origin.WORKFLOW, "errands").id == errands.id
        assert _stars(session) == [("errands", "Errands by week")]
        assert _ratios(session, Origin.WORKFLOW) == [
            ("per_serving", "Cost per serving", "cost.sum", "turns.count"),
            ("per_supper", "Cost per supper", "cost.sum", "calls.count"),
        ]

    @pytest.mark.usefixtures("from_the_file")
    def test_the_same_file_again_changes_nothing_and_keeps_its_times(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        loaded = service.load_workflow(*workflow_views.entries(), NOW)

        assert loaded == WorkflowLoaded(
            views=Loaded(added=0, changed=0, removed=0),
            ratios=Loaded(added=0, changed=0, removed=0),
            notes=(),
        )
        loaded_at = select(SavedView.saved_at).where(
            SavedView.origin_code == Origin.WORKFLOW
        )
        assert set(session.scalars(loaded_at)) == {EARLIER}
        assert set(session.scalars(select(CustomRatio.saved_at))) == {EARLIER}

    @pytest.mark.usefixtures("from_the_file")
    def test_names_swapped_in_one_load_are_loaded(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        views = (
            SystemView("errands", "Rides", ERRANDS),
            SystemView("legs", "Legs", LEGS),
            SystemView("rides", "Errands", RIDES),
        )
        ratios = (
            RatioEntry("per_serving", "Cost per ride", "cost.sum", "calls.count"),
            RatioEntry("per_ride", "Cost per serving", "cost.sum", "turns.count"),
        )

        loaded = service.load_workflow(views, ratios, NOW)

        assert (loaded.views, loaded.ratios) == (
            Loaded(added=0, changed=2, removed=0),
            Loaded(added=0, changed=2, removed=0),
        )
        assert [name for _, name, _ in _rows(session, Origin.WORKFLOW)] == [
            "Rides",
            "Legs",
            "Errands",
        ]
        assert [name for _, name, _, _ in _ratios(session, Origin.WORKFLOW)] == [
            "Cost per serving",
            "Cost per ride",
        ]

    @pytest.mark.usefixtures("from_the_file")
    def test_every_fault_of_every_entry_is_named_with_its_entry_and_nothing_written(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        views = (
            SystemView("errands", "Errands", "t=l8&by=servings&m=cost.sum"),
            SystemView("legs", "Projects", LEGS),
            SystemView("legs", "Legs", LEGS),
            SystemView("rides", "Errands", RIDES),
        )
        ratios = (
            RatioEntry("per_serving", "Cost per serving", "cots.sum", "calls.count"),
            RatioEntry("person_rides", "Cost per ride", "cost.sum", "turns.count"),
            RatioEntry("overhead", "Cost per serving", "cost.sum", "turns.count"),
        )

        with pytest.raises(StateRefusedException) as refused:
            service.load_workflow(views, ratios, NOW)

        assert [fault.part for fault in refused.value.faults] == [
            'view "legs"',
            'view "rides", name "Errands"',
            'view "errands", by=servings',
            'view "legs", name "Projects"',
            'ratio "overhead", name "Cost per serving"',
            'ratio "per_serving", m=cots.sum',
            'ratio "person_rides", key',
            'ratio "overhead", key',
        ]
        assert refused.value.message == (
            "Cannot load the views and ratios because their entries have 8 faults.\n"
            '- view "legs": the key stands on 2 entries, and a load takes one entry '
            "a key.\n"
            '- view "rides", name "Errands": the view "errands" has the name too, '
            "and a name stands once among the loaded views.\n"
            '- view "errands", by=servings: "servings" is no dimension. By takes a '
            "part or an attribute; the catalogue's dimensions list them.\n"
            '- view "legs", name "Projects": one of Pilot\'s own system views has '
            "the name, and a name stands once among the system views.\n"
            '- ratio "overhead", name "Cost per serving": the ratio "per_serving" '
            "has the name too, and a name stands once among the loaded ratios.\n"
            '- ratio "per_serving", m=cots.sum: "cots" is no figure. Did you mean '
            '"cost"? The catalogue\'s measures list the figures.\n'
            '- ratio "person_rides", key: a key that begins "person_" is a ratio a '
            "person made, and a loaded ratio's key is outside that space.\n"
            '- ratio "overhead", key: a ratio built into the dashboard has the key, '
            "and a loaded ratio's key is no built-in one's.\n"
            "A By reads by=<dimension>, as in by=project.\n"
            "A measure reads m=<figure>.<aggregate>[.<grain>][(<filter>;…)], "
            "m=r:<ratio> or m=r:<name>:<measure>/<measure>, as in "
            "m=cost.median.conversation or m=cost.sum(miss=1)."
        )
        assert _rows(session, Origin.WORKFLOW) == [
            ("errands", "Errands", ERRANDS),
            ("legs", "Legs", LEGS),
            ("rides", "Rides", RIDES),
        ]
        assert [key for key, _, _, _ in _ratios(session, Origin.WORKFLOW)] == [
            "per_ride",
            "per_serving",
        ]

    @pytest.mark.usefixtures("from_the_file")
    def test_a_ratios_key_on_two_entries_is_a_fault_named_with_its_entry(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        views, _ = workflow_views.entries()
        ratios = (
            RatioEntry("per_serving", "Cost per serving", "cost.sum", "calls.count"),
            RatioEntry("per_serving", "Cost per supper", "cost.sum", "turns.count"),
        )

        with pytest.raises(StateRefusedException) as refused:
            service.load_workflow(views, ratios, NOW)

        assert refused.value.message == (
            "Cannot load the views and ratios because their entries have 1 fault.\n"
            '- ratio "per_serving": the key stands on 2 entries, and a load takes '
            "one entry a key."
        )
        assert [key for key, _, _, _ in _ratios(session, Origin.WORKFLOW)] == [
            "per_ride",
            "per_serving",
        ]

    def test_a_part_dropped_is_a_note_named_with_its_view(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """A quick filter that is gone, and a ratio the load does not hold,
        as a state's read drops them (F154.2)."""
        views = (
            SystemView("errands", "Errands", f"{ERRANDS}&b=pantry"),
            SystemView("rides", "Rides", RIDES),
        )
        ratios = (
            RatioEntry("per_serving", "Cost per serving", "cost.sum", "calls.count"),
        )

        loaded = service.load_workflow(views, ratios, NOW)

        assert loaded.notes == (
            'view "errands", b=pantry: no quick filter has the key "pantry", so it '
            "is dropped.",
            'view "rides", m=r:per_ride: no ratio has the key "per_ride", so the '
            "measure is dropped.",
        )
        assert _rows(session, Origin.WORKFLOW) == [
            ("errands", "Errands", ERRANDS),
            ("rides", "Rides", "t=d7&by=project&p=time,day&m=cost.sum&col=source"),
        ]

    @pytest.mark.usefixtures("from_the_file")
    def test_a_ratio_the_load_removes_is_dropped_from_its_views_with_a_note(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """The views are read under the ratios the load leaves, not those
        held before it: per_ride, held from the file, is gone with it."""
        run_after_commit_callbacks()
        views, ratios = workflow_views.entries()

        loaded = service.load_workflow(
            views, [ratio for ratio in ratios if ratio.key != "per_ride"], NOW
        )

        assert loaded.notes == (
            'view "rides", m=r:per_ride: no ratio has the key "per_ride", so the '
            "measure is dropped.",
        )
        assert "per_ride" not in _row(session, Origin.WORKFLOW, "rides").state

    def test_it_leaves_pilots_own_views_and_what_a_person_made_alone(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        service.save_view("Mine", STATE, None, EARLIER)
        mine = service.add_ratio("Cost per turn", "cost.sum", "turns.count", None)

        service.load_workflow(*workflow_views.entries(), NOW)
        service.load_workflow([], [], NOW)

        assert _rows(session, Origin.WORKFLOW) == []
        assert _ratios(session, Origin.WORKFLOW) == []
        assert [name for _, name, _ in _rows(session, Origin.PILOT)] == [
            view.name for view in sorted(VIEWS, key=lambda view: view.key)
        ]
        assert _rows(session, Origin.PERSON) == [(None, "Mine", STATE)]
        assert service.custom_ratios() == [mine]

    def test_the_catalogue_offers_its_ratios_once_the_load_has_committed(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue_service = container.catalogue_service()
        catalogue_service.catalogue(session)

        container.dashboard_store_service().load_workflow(
            *workflow_views.entries(), NOW
        )
        run_after_commit_callbacks()

        assert [
            (ratio.key, ratio.label, ratio.origin)
            for ratio in catalogue_service.catalogue(session).ratios
            if ratio.origin is not None
        ] == [
            ("per_ride", "Cost per ride", "workflow"),
            ("per_serving", "Cost per serving", "workflow"),
        ]


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


def _bea(db: DbSession) -> User:
    bea = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    db.add(bea)
    db.flush()
    return bea


def _system(db: DbSession, name: str = "Projects") -> SavedView:
    return db.scalars(
        select(SavedView).where(SavedView.system.is_(True), SavedView.name == name)
    ).one()


def _persons(db: DbSession, name: str) -> SavedView:
    return db.scalars(
        select(SavedView).where(SavedView.system.is_(False), SavedView.name == name)
    ).one()


def _loaded_ratio(db: DbSession) -> CustomRatio:
    ratio = CustomRatio(
        origin_code=Origin.WORKFLOW,
        key="per_crate",
        name="Cost per crate",
        numerator="cost.sum",
        denominator="calls.count",
        saved_at=EARLIER,
    )
    db.add(ratio)
    db.flush()
    return ratio


class TestSaveView:
    def test_it_saves_the_state_in_its_normal_form_for_everyone(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        saved = service.save_view("Opus", "#dash/m=cost.sum&by=model&t=d7", None, NOW)

        assert saved.made
        assert saved.notes == ()
        assert (saved.view.origin_code, saved.view.key) == (Origin.PERSON, None)
        assert (saved.view.name, saved.view.state) == (
            "Opus",
            "t=d7&by=model&m=cost.sum&col=none",
        )
        assert saved.view.saved_at == NOW
        assert not saved.view.system

    def test_the_bands_length_is_saved_with_it(
        self, service: DashboardStoreService
    ) -> None:
        saved = service.save_view("Short band", "by=model&roll=5,5", None, NOW)

        assert saved.view.state == "t=qw&by=model&m=cost.sum&col=none&roll=5,5"

    def test_a_save_under_a_saved_views_name_replaces_it_its_stars_kept(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        first = service.save_view("Opus", STATE, "The first", EARLIER).view
        _star(session, person, first)

        saved = service.save_view("Opus", OTHER_STATE, None, NOW)

        assert not saved.made
        assert saved.view.id == first.id
        assert (saved.view.state, saved.view.note, saved.view.saved_at) == (
            OTHER_STATE,
            None,
            NOW,
        )
        assert _stars(session) == [(None, "Opus")]

    def test_a_system_views_name_saves_a_view_beside_it(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """F155.1: a system view may have the same name."""
        shipped = _system(session)

        saved = service.save_view("Projects", OTHER_STATE, None, NOW)

        assert saved.made
        assert saved.view.id != shipped.id
        assert _system(session).state == shipped.state

    def test_a_quick_filter_that_is_gone_is_dropped_with_a_note(
        self, service: DashboardStoreService
    ) -> None:
        saved = service.save_view("Gone", "by=model&b=misses,shelf", None, NOW)

        assert saved.view.state == "t=qw&by=model&m=cost.sum&b=misses&col=none"
        assert saved.notes == (
            'b=misses,shelf: no quick filter has the key "shelf", so it is dropped.',
        )

    def test_a_state_with_faults_is_refused_and_nothing_saved(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        before = len(service.saved_views())

        with pytest.raises(StateRefusedException) as refused:
            service.save_view("Broken", "by=projet&t=d8", None, NOW)

        assert [fault.part for fault in refused.value.faults] == ["by=projet", "t=d8"]
        assert len(service.saved_views()) == before


class TestRenameView:
    def test_a_saved_view_is_renamed_its_stars_kept(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        view = service.save_view("Opus", STATE, None, EARLIER).view
        _star(session, person, view)

        renamed = service.rename_view(view.id, "Opus this week")

        assert (renamed.id, renamed.name, renamed.saved_at) == (
            view.id,
            "Opus this week",
            EARLIER,
        )
        assert _stars(session) == [(None, "Opus this week")]

    def test_it_may_take_a_system_views_name(
        self, service: DashboardStoreService
    ) -> None:
        view = service.save_view("Opus", STATE, None, NOW).view

        assert service.rename_view(view.id, "Projects").name == "Projects"

    def test_its_own_name_changes_nothing(self, service: DashboardStoreService) -> None:
        view = service.save_view("Opus", STATE, None, NOW).view

        assert service.rename_view(view.id, "Opus").name == "Opus"

    def test_another_saved_views_name_is_refused(
        self, service: DashboardStoreService
    ) -> None:
        view = service.save_view("Opus", STATE, None, NOW).view
        service.save_view("Fable", OTHER_STATE, None, NOW)

        with pytest.raises(ResourceConflictException) as refused:
            service.rename_view(view.id, "Fable")

        assert refused.value.message == (
            'A saved view with the name "Fable" already exists'
        )

    def test_a_system_view_is_refused(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """DB 601."""
        with pytest.raises(InvalidOperationException) as refused:
            service.rename_view(_system(session).id, "Mine")

        assert refused.value.message == (
            'Cannot rename the view "Projects" because it is a system view, which '
            "the system manages: a star is all a person changes of it"
        )
        assert _system(session).name == "Projects"

    def test_no_view_is_refused(self, service: DashboardStoreService) -> None:
        with pytest.raises(RecordNotFoundException):
            service.rename_view(uuid.uuid4(), "Mine")


class TestRemoveView:
    def test_a_saved_view_is_removed_the_stars_on_it_with_it(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        view = service.save_view("Opus", STATE, None, NOW).view
        _star(session, person, view)

        service.remove_view(view.id)

        assert session.get(SavedView, view.id) is None
        assert _stars(session) == []

    def test_a_system_view_is_refused(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            service.remove_view(_system(session).id)

        assert refused.value.message.startswith(
            'Cannot remove the view "Projects" because it is a system view'
        )

    def test_no_view_is_refused(self, service: DashboardStoreService) -> None:
        with pytest.raises(RecordNotFoundException):
            service.remove_view(uuid.uuid4())


class TestStars:
    def test_a_person_stars_a_system_view_and_a_saved_one_listed_as_starred(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        saved = service.save_view("Opus", STATE, None, NOW).view
        shipped = _system(session)

        service.star(person, saved.id, EARLIER)
        service.star(person, shipped.id, NOW)

        assert service.favourites(person).views == [saved.id, shipped.id]

    def test_a_star_again_keeps_its_place(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        first, second = _system(session), _system(session, "Work types")
        service.star(person, first.id, EARLIER)
        service.star(person, second.id, NOW)

        service.star(person, first.id, NOW + timedelta(hours=1))

        assert service.favourites(person).views == [first.id, second.id]

    def test_the_stars_are_each_persons_own(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        shipped = _system(session)
        service.star(person, shipped.id, NOW)

        assert service.favourites(_bea(session)).views == []

    def test_a_star_taken_off(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        shipped = _system(session)
        service.star(person, shipped.id, NOW)

        service.unstar(person, shipped.id)
        service.unstar(person, shipped.id)

        assert service.favourites(person).views == []
        assert _system(session).name == "Projects"

    def test_no_view_is_refused(
        self, service: DashboardStoreService, person: User
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            service.star(person, uuid.uuid4())
        with pytest.raises(RecordNotFoundException):
            service.unstar(person, uuid.uuid4())


class TestFavourites:
    def test_a_dimension_in_bys_list_and_a_color_in_colors(
        self, service: DashboardStoreService, person: User
    ) -> None:
        for menu, dimension in (
            (FavouriteMenu.BY, "project"),
            (FavouriteMenu.BY, "day"),
            (FavouriteMenu.COLOR, "work_type"),
            (FavouriteMenu.COLOR, "token_kind"),
            (FavouriteMenu.BY, "project"),
        ):
            service.favour(person, menu, dimension)

        assert service.favourites(person) == Favourites(
            views=[], by=["day", "project"], color=["token_kind", "work_type"]
        )

    def test_a_favourite_taken_off(
        self, service: DashboardStoreService, person: User
    ) -> None:
        service.favour(person, FavouriteMenu.BY, "project")
        service.favour(person, FavouriteMenu.COLOR, "project")

        service.unfavour(person, FavouriteMenu.BY, "project")
        service.unfavour(person, FavouriteMenu.BY, "model")

        assert service.favourites(person) == Favourites(
            views=[], by=[], color=["project"]
        )

    def test_one_the_catalogue_no_longer_offers_is_left_out(
        self, session: DbSession, service: DashboardStoreService, person: User
    ) -> None:
        session.add(
            DimensionFavourite(
                user_id=person.id, menu_code=FavouriteMenu.BY, dimension="shelf"
            )
        )
        session.flush()

        assert service.favourites(person).by == []

    def test_a_dimension_the_catalogue_does_not_offer_is_refused(
        self, service: DashboardStoreService, person: User
    ) -> None:
        with pytest.raises(ValidationException) as refused:
            service.favour(person, FavouriteMenu.BY, "projet")

        assert refused.value.message == (
            'Cannot mark "projet" a favourite in By\'s list because it is no '
            'dimension of the catalogue\'s. Did you mean "project"?'
        )

    def test_a_color_is_a_part_an_attribute_or_the_token_kind(
        self, service: DashboardStoreService, person: User
    ) -> None:
        with pytest.raises(ValidationException) as refused:
            service.favour(person, FavouriteMenu.COLOR, "day")

        assert refused.value.message == (
            'Cannot mark "day" a favourite in Color\'s list because a color is a '
            "part, an attribute or token_kind."
        )


class TestQuickFilters:
    def test_one_is_made_for_everyone_under_a_code_of_its_own(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        now = datetime.now(UTC)
        made = service.add_quick_filter(
            "Opus only", "model:claude-opus-5-5", "cost", "The big model", now
        )

        assert re.fullmatch("[a-z][a-z0-9]{3}", made.code)
        assert (made.label, made.condition, made.marks) == (
            "Opus only",
            "model:claude-opus-5-5",
            False,
        )
        assert (made.amount_figure, made.note, made.saved_at) == (
            "cost",
            "The big model",
            now,
        )
        assert service.quick_filters()[-1].id == made.id

    def test_a_chip_that_marks_makes_one_that_marks(
        self, service: DashboardStoreService
    ) -> None:
        made = service.add_quick_filter("Marked misses", "~miss:1", None, None, NOW)

        assert (made.condition, made.marks) == ("miss:1", True)

    def test_its_chip_is_kept_in_its_normal_form(
        self, service: DashboardStoreService
    ) -> None:
        made = service.add_quick_filter(
            "Dear", "@items,gt,1.50,cost.sum", None, None, NOW
        )

        assert made.condition == "@items,gt,1.5,cost.sum"

    def test_the_catalogue_offers_it_once_its_write_has_committed(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue_service = container.catalogue_service()
        catalogue_service.catalogue(session)
        made = container.dashboard_store_service().add_quick_filter(
            "Opus only", "model:claude-opus-5-5", None, None
        )

        run_after_commit_callbacks()

        keys = [one.key for one in catalogue_service.catalogue(session).quick_filters]
        assert keys[-1] == made.code

    def test_the_catalogue_drops_it_once_its_removal_has_committed(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue_service = container.catalogue_service()
        store = container.dashboard_store_service()
        made = store.add_quick_filter("Opus only", "model:claude-opus-5-5", None, None)
        run_after_commit_callbacks()
        catalogue_service.catalogue(session)

        store.remove_quick_filter(made.id)
        run_after_commit_callbacks()

        keys = [one.key for one in catalogue_service.catalogue(session).quick_filters]
        assert made.code not in keys

    def test_a_chip_with_faults_is_refused(
        self, service: DashboardStoreService
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            service.add_quick_filter("Broken", "modle:x", None, None, NOW)

        assert [fault.part for fault in refused.value.faults] == ["c=modle:x"]

    def test_an_amount_no_figure_has_is_refused(
        self, service: DashboardStoreService
    ) -> None:
        with pytest.raises(ValidationException) as refused:
            service.add_quick_filter("Opus", "model:claude-opus-5-5", "cots", None, NOW)

        assert refused.value.message == (
            'Cannot add the quick filter "Opus" because no figure has the key '
            '"cots". Did you mean "cost"?'
        )

    def test_one_is_removed_one_the_dashboard_shipped_with_too(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        shipped = session.scalars(
            select(QuickFilter).where(QuickFilter.code == "misses")
        ).one()

        service.remove_quick_filter(shipped.id)

        assert "misses" not in [row.code for row in service.quick_filters()]

    def test_no_quick_filter_is_refused(self, service: DashboardStoreService) -> None:
        with pytest.raises(RecordNotFoundException):
            service.remove_quick_filter(uuid.uuid4())


class TestCustomRatios:
    def test_one_is_made_under_a_key_from_its_name_in_a_persons_space(
        self, service: DashboardStoreService
    ) -> None:
        made = service.add_ratio(
            "Cost per turn", "reported_cost.sum", "turns.count", None, NOW
        )

        assert (made.origin_code, made.key, made.name) == (
            Origin.PERSON,
            "person_cost_per_turn",
            "Cost per turn",
        )
        assert (made.numerator, made.denominator) == (
            "reported_cost.sum",
            "turns.count",
        )
        assert not made.system

    def test_its_sides_are_kept_in_their_normal_form(
        self, service: DashboardStoreService
    ) -> None:
        made = service.add_ratio("Waits", "waited", "calls.count", None, NOW)

        assert (made.numerator, made.denominator) == ("waited.sum", "calls.count")

    @pytest.mark.parametrize(
        ("name", "key"),
        [
            ("Kosten über Zeit!", "person_kosten_uber_zeit"),
            ("€", "person_ratio"),
            ("A very long name for a ratio of costs", "person_a_very_long_name_for_a"),
        ],
    )
    def test_its_key_is_a_word_of_its_name(
        self, service: DashboardStoreService, name: str, key: str
    ) -> None:
        assert service.add_ratio(name, "cost.sum", "calls.count", None, NOW).key == key

    def test_a_key_taken_is_numbered(self, service: DashboardStoreService) -> None:
        first = service.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)
        service.edit_ratio(first.id, "Turn cost", "cost.sum", "turns.count", None, NOW)

        again = service.add_ratio("Cost per turn", "cost.sum", "calls.count", None, NOW)
        third = service.add_ratio(
            "Cost  per turn", "cost.sum", "calls.count", None, NOW
        )

        assert [first.key, again.key, third.key] == [
            "person_cost_per_turn",
            "person_cost_per_turn_2",
            "person_cost_per_turn_3",
        ]

    def test_a_loaded_ratios_name_may_stand_among_a_persons(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        _loaded_ratio(session)

        made = service.add_ratio("Cost per crate", "cost.sum", "calls.count", None, NOW)

        assert made.name == "Cost per crate"
        assert [ratio.system for ratio in service.custom_ratios()] == [True, False]

    def test_a_persons_name_taken_is_refused(
        self, service: DashboardStoreService
    ) -> None:
        service.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)

        with pytest.raises(ResourceConflictException) as refused:
            service.add_ratio("Cost per turn", "cost.sum", "calls.count", None, NOW)

        assert refused.value.message == (
            'A custom ratio with the name "Cost per turn" already exists'
        )

    def test_every_fault_of_both_sides_is_named(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            service.add_ratio("Broken", "cots.sum", "calls.cuont", None, NOW)

        assert [fault.part for fault in refused.value.faults] == [
            "m=cots.sum",
            "m=calls.cuont",
        ]
        assert refused.value.message.startswith(
            "Cannot read the view because its state has 2 faults."
        )
        assert service.custom_ratios() == []

    def test_one_is_changed_under_its_key(self, service: DashboardStoreService) -> None:
        made = service.add_ratio("Cost per turn", "cost.sum", "turns.count", "A", NOW)
        later = NOW + timedelta(hours=1)

        changed = service.edit_ratio(
            made.id, "Turn cost", "reported_cost.sum", "turns.count", None, later
        )

        assert (changed.id, changed.key, changed.name) == (
            made.id,
            "person_cost_per_turn",
            "Turn cost",
        )
        assert (changed.numerator, changed.note, changed.saved_at) == (
            "reported_cost.sum",
            None,
            later,
        )

    def test_a_change_may_keep_its_name_and_not_take_anothers(
        self, service: DashboardStoreService
    ) -> None:
        made = service.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)
        service.add_ratio("Cost per call", "cost.sum", "calls.count", None, NOW)

        service.edit_ratio(
            made.id, "Cost per turn", "cost.sum", "turns.count", "B", NOW
        )
        with pytest.raises(ResourceConflictException):
            service.edit_ratio(
                made.id, "Cost per call", "cost.sum", "turns.count", None, NOW
            )

    def test_one_is_removed(self, service: DashboardStoreService) -> None:
        made = service.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)

        service.remove_ratio(made.id)

        assert service.custom_ratios() == []

    def test_a_loaded_one_is_neither_changed_nor_removed(
        self, session: DbSession, service: DashboardStoreService
    ) -> None:
        """DB 601."""
        loaded = _loaded_ratio(session)

        with pytest.raises(InvalidOperationException) as changed:
            service.edit_ratio(loaded.id, "Mine", "cost.sum", "turns.count", None, NOW)
        with pytest.raises(InvalidOperationException) as removed:
            service.remove_ratio(loaded.id)

        assert changed.value.message == (
            'Cannot change the ratio "Cost per crate" because it was loaded with '
            "the workflow's views, and nobody changes or removes a loaded ratio"
        )
        assert removed.value.message.startswith(
            'Cannot remove the ratio "Cost per crate" because'
        )
        assert [ratio.name for ratio in service.custom_ratios()] == ["Cost per crate"]

    def test_the_catalogue_offers_one_once_its_write_has_committed(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue_service = container.catalogue_service()
        store = container.dashboard_store_service()
        catalogue_service.catalogue(session)
        made = store.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)
        run_after_commit_callbacks()

        assert catalogue_service.catalogue(session).ratios[-1].key == made.key

        store.remove_ratio(made.id)
        run_after_commit_callbacks()

        assert made.key not in [
            ratio.key for ratio in catalogue_service.catalogue(session).ratios
        ]

    def test_the_catalogue_reads_an_edit_once_it_has_committed(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        catalogue_service = container.catalogue_service()
        store = container.dashboard_store_service()
        made = store.add_ratio("Cost per turn", "cost.sum", "turns.count", None, NOW)
        run_after_commit_callbacks()
        catalogue_service.catalogue(session)

        store.edit_ratio(made.id, "Turn cost", "reported_cost.sum", "turns.count", None)
        run_after_commit_callbacks()

        (edited,) = [
            ratio
            for ratio in catalogue_service.catalogue(session).ratios
            if ratio.key == made.key
        ]
        assert (edited.label, edited.numerator) == ("Turn cost", "reported_cost.sum")

    def test_no_ratio_is_refused(self, service: DashboardStoreService) -> None:
        with pytest.raises(RecordNotFoundException):
            service.edit_ratio(uuid.uuid4(), "Mine", "cost.sum", "calls.count", None)
        with pytest.raises(RecordNotFoundException):
            service.remove_ratio(uuid.uuid4())
