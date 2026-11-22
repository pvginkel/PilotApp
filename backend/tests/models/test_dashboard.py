"""Saved View, View Star, Dimension Favourite, Quick Filter and Custom Ratio:
what a row of what the dashboard stores must hold (DB §2.10; 600 to 603)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    CustomRatio,
    DimensionFavourite,
    QuickFilter,
    SavedView,
    User,
    ViewStar,
)
from app.models.reference import FavouriteMenu, Origin, UserKind
from tests.support.database import violated_constraint

SAVED_AT = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)
STATE = "t=qw&by=project&m=cost.sum&col=none"


def _view(
    db: DbSession, origin: Origin, name: str, key: str | None = None
) -> SavedView:
    view = SavedView(
        origin_code=origin, key=key, name=name, state=STATE, saved_at=SAVED_AT
    )
    db.add(view)
    db.flush()
    return view


def _ratio(db: DbSession, origin: Origin, key: str, name: str) -> CustomRatio:
    ratio = CustomRatio(
        origin_code=origin,
        key=key,
        name=name,
        numerator="cost.sum",
        denominator="calls.count",
        saved_at=SAVED_AT,
    )
    db.add(ratio)
    db.flush()
    return ratio


def _quick_filter(db: DbSession, code: str, condition: str = "model:x") -> None:
    db.add(
        QuickFilter(
            code=code,
            label="Market day",
            condition=condition,
            marks=False,
            saved_at=SAVED_AT,
        )
    )


@pytest.fixture
def other(session: DbSession) -> User:
    """A second person who has signed in."""
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture(autouse=True)
def nothing_stored(session: DbSession) -> None:
    """No saved view but the test's own: the suite's database holds Pilot's
    own system views from its deploy step."""
    session.execute(delete(SavedView))


class TestSavedView:
    def test_a_system_view_is_one_whose_origin_is_managed(
        self, session: DbSession
    ) -> None:
        views = [
            _view(session, Origin.PILOT, "Projects", "projects"),
            _view(session, Origin.WORKFLOW, "Drift", "drift"),
            _view(session, Origin.PERSON, "Writers on Fable"),
        ]
        session.expire_all()

        assert [view.system for view in views] == [True, True, False]

    def test_a_name_may_stand_once_among_the_system_views_and_once_among_the_others(
        self, session: DbSession
    ) -> None:
        """DB 602."""
        _view(session, Origin.WORKFLOW, "Drift", "drift")
        _view(session, Origin.PERSON, "Drift")

        assert session.scalar(select(func.count()).select_from(SavedView)) == 2

    def test_two_system_views_may_not_share_a_name(self, session: DbSession) -> None:
        _view(session, Origin.PILOT, "Projects", "projects")
        session.add(
            SavedView(
                origin_code=Origin.WORKFLOW,
                key="projects",
                name="Projects",
                state=STATE,
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "saved_views_system_name_key"

    def test_two_of_a_persons_views_may_not_share_a_name(
        self, session: DbSession
    ) -> None:
        _view(session, Origin.PERSON, "Writers on Fable")
        session.add(
            SavedView(
                origin_code=Origin.PERSON,
                name="Writers on Fable",
                state=STATE,
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "saved_views_system_name_key"

    def test_a_system_view_has_a_key(self, session: DbSession) -> None:
        """DB 603."""
        session.add(
            SavedView(
                origin_code=Origin.WORKFLOW,
                name="Drift",
                state=STATE,
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "ck_saved_views_key"

    def test_one_a_person_saved_has_none(self, session: DbSession) -> None:
        session.add(
            SavedView(
                origin_code=Origin.PERSON,
                key="writers",
                name="Writers on Fable",
                state=STATE,
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "ck_saved_views_key"

    def test_a_key_is_unique_within_its_origin(self, session: DbSession) -> None:
        _view(session, Origin.PILOT, "Projects", "projects")
        _view(session, Origin.WORKFLOW, "The workflow's projects", "projects")
        session.add(
            SavedView(
                origin_code=Origin.WORKFLOW,
                key="projects",
                name="Projects again",
                state=STATE,
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "saved_views_origin_code_key_key"


class TestViewStar:
    def test_a_person_stars_a_view_once(self, session: DbSession, person: User) -> None:
        view = _view(session, Origin.PILOT, "Projects", "projects")
        session.add(
            ViewStar(user_id=person.id, saved_view_id=view.id, starred_at=SAVED_AT)
        )
        session.flush()
        session.expunge_all()
        session.add(
            ViewStar(user_id=person.id, saved_view_id=view.id, starred_at=SAVED_AT)
        )

        assert violated_constraint(session) == "view_stars_pkey"

    def test_the_stars_go_with_their_view(
        self, session: DbSession, person: User, other: User
    ) -> None:
        """DB 604: a view a load drops takes its stars with it."""
        view = _view(session, Origin.WORKFLOW, "Drift", "drift")
        kept = _view(session, Origin.WORKFLOW, "Rework", "rework")
        session.add_all(
            [
                ViewStar(user_id=person.id, saved_view_id=view.id, starred_at=SAVED_AT),
                ViewStar(user_id=other.id, saved_view_id=view.id, starred_at=SAVED_AT),
                ViewStar(user_id=other.id, saved_view_id=kept.id, starred_at=SAVED_AT),
            ]
        )
        session.flush()

        session.execute(delete(SavedView).where(SavedView.id == view.id))

        assert session.scalars(select(ViewStar.saved_view_id)).all() == [kept.id]

    def test_a_star_is_a_users(self, session: DbSession) -> None:
        view = _view(session, Origin.PILOT, "Projects", "projects")
        session.add(
            ViewStar(
                user_id=view.id,  # no User's id
                saved_view_id=view.id,
                starred_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "view_stars_user_id_fkey"


class TestDimensionFavourite:
    def test_a_dimension_may_be_a_favourite_in_both_lists(
        self, session: DbSession, person: User
    ) -> None:
        session.add_all(
            DimensionFavourite(user_id=person.id, menu_code=menu, dimension="model")
            for menu in FavouriteMenu
        )
        session.flush()

        assert session.scalars(
            select(DimensionFavourite.menu_code).order_by(DimensionFavourite.menu_code)
        ).all() == [FavouriteMenu.BY, FavouriteMenu.COLOR]

    def test_once_in_one_list(self, session: DbSession, person: User) -> None:
        session.add(
            DimensionFavourite(
                user_id=person.id, menu_code=FavouriteMenu.BY, dimension="model"
            )
        )
        session.flush()
        session.expunge_all()
        session.add(
            DimensionFavourite(
                user_id=person.id, menu_code=FavouriteMenu.BY, dimension="model"
            )
        )

        assert violated_constraint(session) == "dimension_favourites_pkey"


class TestQuickFilter:
    def test_its_code_is_unique(self, session: DbSession) -> None:
        _quick_filter(session, "market_day")
        session.flush()
        _quick_filter(session, "market_day")

        assert violated_constraint(session) == "quick_filters_code_key"

    def test_its_condition_carries_no_mark_of_its_own(self, session: DbSession) -> None:
        """Whether it marks is `marks`, fixed when it is made."""
        _quick_filter(session, "market_day", "~weekday:6")

        assert violated_constraint(session) == "ck_quick_filters_condition"


class TestCustomRatio:
    def test_one_loaded_and_a_persons_carry_system_from_their_origin(
        self, session: DbSession
    ) -> None:
        ratios = [
            _ratio(session, Origin.WORKFLOW, "per_step", "Cost per step"),
            _ratio(session, Origin.PERSON, "person_per_step", "Cost per step"),
        ]
        session.expire_all()

        assert [ratio.system for ratio in ratios] == [True, False]

    def test_none_is_pilots_own(self, session: DbSession) -> None:
        """DB 600: Pilot's own ratios are the catalogue's and no rows."""
        session.add(
            CustomRatio(
                origin_code=Origin.PILOT,
                key="per_step",
                name="Cost per step",
                numerator="cost.sum",
                denominator="calls.count",
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "ck_custom_ratios_origin"

    def test_its_key_is_unique_among_all(self, session: DbSession) -> None:
        """DB 602."""
        _ratio(session, Origin.PERSON, "person_per_step", "Cost per step")
        session.add(
            CustomRatio(
                origin_code=Origin.PERSON,
                key="person_per_step",
                name="My cost per step",
                numerator="cost.sum",
                denominator="calls.count",
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "custom_ratios_key_key"

    @pytest.mark.parametrize("key", ["Per_step", "per step", "per:step", "1st"])
    def test_its_key_is_a_word_a_state_writes_as_it_stands(
        self, session: DbSession, key: str
    ) -> None:
        session.add(
            CustomRatio(
                origin_code=Origin.WORKFLOW,
                key=key,
                name="Cost per step",
                numerator="cost.sum",
                denominator="calls.count",
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "ck_custom_ratios_key"

    @pytest.mark.parametrize(
        ("origin", "key"),
        [(Origin.PERSON, "per_step"), (Origin.WORKFLOW, "person_per_step")],
    )
    def test_a_persons_key_and_none_but_a_persons_is_in_their_space(
        self, session: DbSession, origin: Origin, key: str
    ) -> None:
        """DB 602: a person's key from a space no loaded ratio's is in."""
        session.add(
            CustomRatio(
                origin_code=origin,
                key=key,
                name="Cost per step",
                numerator="cost.sum",
                denominator="calls.count",
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "ck_custom_ratios_key_space"

    def test_two_of_a_persons_ratios_may_not_share_a_name(
        self, session: DbSession
    ) -> None:
        _ratio(session, Origin.PERSON, "person_per_step", "Cost per step")
        session.add(
            CustomRatio(
                origin_code=Origin.PERSON,
                key="person_per_step_2",
                name="Cost per step",
                numerator="cost.sum",
                denominator="calls.count",
                saved_at=SAVED_AT,
            )
        )

        assert violated_constraint(session) == "custom_ratios_system_name_key"
