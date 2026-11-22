"""What the dashboard stores (F155; DB §2.10): the saved views, the quick
filters and the custom ratios everyone shares, and a person's favourites.

The system views are the system's: no User changes one but by its star (DB
601). Pilot's own name nothing of a workflow and are what this release's code
holds (`app/dashboard/views.py`): each deploy loads them after the revisions
(`post_migration_hook`), as does the load of the invented record. A load of
an Origin's views leaves them the entries it is given, matched by key: an
entry a row has changes that row in place, its stars kept; one no row has is
added; a row whose key the entries no longer hold is removed, its stars with
it (DB 604).

A view one person saved is anyone's to replace, rename and remove; a quick
filter anyone's to make and remove, never to change; a ratio a person made
anyone's to make, change and remove, a loaded one nobody's (F155.1, F155.3).
A stored expression is kept in the normal form a view's state writes (F155.4).
A write of a quick filter or a ratio drops the process's catalogue once it
has committed, so that the next read offers what it wrote.
"""

import re
import secrets
import string
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.dashboard.address import AddressService
from app.dashboard.assembly import CatalogueService
from app.dashboard.catalogue import Catalogue
from app.dashboard.reading import read_chip, read_simple
from app.dashboard.refusal import Fault, listed, nearest, quoted, refused
from app.dashboard.state import TOKEN_KIND, chip_key, simple_key, write
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
from app.models.dashboard import PERSON_KEYS
from app.models.reference import FavouriteMenu, Origin
from app.services.quota_week_service import quota_weeks
from app.utils.after_commit import after_commit

KEY_LENGTH = 24
"""The most letters of a ratio's name its key takes, after `PERSON_KEYS`: its
words that fit, or the first word cut."""

CODE_LENGTH = 4
"""The letters of a quick filter's code a person made: a letter, then
letters or digits."""

_CODE_LETTERS = string.ascii_lowercase + string.digits


@dataclass(frozen=True)
class Loaded:
    """What a load of system views wrote: the views it added, changed and
    removed."""

    added: int
    changed: int
    removed: int


@dataclass(frozen=True)
class Saved:
    """A view saved: its row, whether the save made it rather than replaced
    one of its name, and a note for each part of its state dropped."""

    view: SavedView
    made: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Favourites:
    """A person's favourites: the views they starred, by their ids in the
    order starred, and the dimensions in By's list and in Color's, each by
    its key, those the catalogue offers there."""

    views: list[uuid.UUID]
    by: list[str]
    color: list[str]


class DashboardStoreService:
    """The rows of what the dashboard stores."""

    def __init__(
        self,
        db: Session,
        catalogue_service: CatalogueService,
        address_service: AddressService,
    ) -> None:
        self.db = db
        self.catalogue_service = catalogue_service
        self.address_service = address_service

    # ------------------------------------------------------- system views

    def ship(self, now: datetime | None = None) -> Loaded:
        """Pilot's own system views made what this release holds."""
        return self.load_views(Origin.PILOT, VIEWS, now or datetime.now(UTC))

    def load_views(
        self, origin: Origin, views: Sequence[SystemView], now: datetime
    ) -> Loaded:
        """The system views of `origin` made `views`, one per key, by key; a
        view added or changed saved at `now`."""
        held = {
            row.key: row
            for row in self.db.scalars(
                select(SavedView).where(SavedView.origin_code == origin)
            )
        }
        keys = {view.key for view in views}
        gone = [row.id for key, row in held.items() if key not in keys]
        if gone:
            # Before the others are written, so that a name a removed view
            # held is free for one of them.
            self.db.execute(delete(SavedView).where(SavedView.id.in_(gone)))
        added = changed = 0
        for view in views:
            row = held.get(view.key)
            if row is None:
                self.db.add(
                    SavedView(
                        origin_code=origin,
                        key=view.key,
                        name=view.name,
                        state=view.state,
                        note=view.note,
                        saved_at=now,
                    )
                )
                added += 1
            elif (row.name, row.state, row.note) != (view.name, view.state, view.note):
                row.name, row.state, row.note = view.name, view.state, view.note
                row.saved_at = now
                changed += 1
        self.db.flush()
        return Loaded(added, changed, len(gone))

    # -------------------------------------------------------- saved views

    def saved_views(self) -> list[SavedView]:
        """Every Saved View, the system views before those a person saved,
        each list by name."""
        return list(
            self.db.scalars(
                select(SavedView).order_by(
                    SavedView.system.desc(), SavedView.name, SavedView.id
                )
            )
        )

    def saved_view(self, view_id: uuid.UUID) -> SavedView:
        """The Saved View of `view_id`.

        Raises:
            RecordNotFoundException: no Saved View has the id
        """
        view = self.db.get(SavedView, view_id)
        if view is None:
            raise RecordNotFoundException("Saved view", str(view_id))
        return view

    def save_view(
        self, name: str, state: str, note: str | None, now: datetime | None = None
    ) -> Saved:
        """A view's whole state saved for everyone under `name`, in its
        normal form, an entry's filled in: the one a person saved under that
        name replaced in place, its stars kept. A system view of the name is
        in the other list and stays (DB 602).

        Raises:
            StateRefusedException: the state has a fault
        """
        found = self.address_service.address(state)
        normal = write(found.state)
        saved_at = now or datetime.now(UTC)
        made = uuid.uuid4()
        view_id = self.db.scalars(
            insert(SavedView)
            .values(
                id=made,
                origin_code=Origin.PERSON,
                name=name,
                state=normal,
                note=note,
                saved_at=saved_at,
            )
            .on_conflict_do_update(
                constraint="saved_views_system_name_key",
                set_={"state": normal, "note": note, "saved_at": saved_at},
            )
            .returning(SavedView.id)
        ).one()
        view = self.db.scalars(
            select(SavedView)
            .where(SavedView.id == view_id)
            .execution_options(populate_existing=True)
        ).one()
        return Saved(view, view_id == made, found.notes)

    def rename_view(self, view_id: uuid.UUID, name: str) -> SavedView:
        """A view a person saved under the name `name`.

        Raises:
            RecordNotFoundException: no Saved View has the id
            InvalidOperationException: the view is a system view
            ResourceConflictException: another view a person saved has the name
        """
        view = self.saved_view(view_id)
        _persons_view(view, "rename")
        if view.name != name:
            taken = self.db.scalar(
                select(SavedView.id).where(
                    SavedView.system.is_(False), SavedView.name == name
                )
            )
            if taken is not None:
                raise ResourceConflictException("saved view", f'the name "{name}"')
            view.name = name
            self.db.flush()
        return view

    def remove_view(self, view_id: uuid.UUID) -> None:
        """A view a person saved removed, the stars on it with it.

        Raises:
            RecordNotFoundException: no Saved View has the id
            InvalidOperationException: the view is a system view
        """
        view = self.saved_view(view_id)
        _persons_view(view, "remove")
        self.db.delete(view)
        self.db.flush()

    # --------------------------------------------------------- favourites

    def star(
        self, person: User, view_id: uuid.UUID, now: datetime | None = None
    ) -> None:
        """`person`'s star on a view, a system view's or a saved one's; one
        they have keeps its place among their stars.

        Raises:
            RecordNotFoundException: no Saved View has the id
        """
        self.saved_view(view_id)
        self.db.execute(
            insert(ViewStar)
            .values(
                user_id=person.id,
                saved_view_id=view_id,
                starred_at=now or datetime.now(UTC),
            )
            .on_conflict_do_nothing()
        )

    def unstar(self, person: User, view_id: uuid.UUID) -> None:
        """`person`'s star on a view taken off, where they have one.

        Raises:
            RecordNotFoundException: no Saved View has the id
        """
        self.saved_view(view_id)
        self.db.execute(
            delete(ViewStar).where(
                ViewStar.user_id == person.id, ViewStar.saved_view_id == view_id
            )
        )

    def favourites(self, person: User) -> Favourites:
        """`person`'s stars and favourite dimensions; a dimension the
        catalogue no longer offers in its list left out."""
        views = list(
            self.db.scalars(
                select(ViewStar.saved_view_id)
                .where(ViewStar.user_id == person.id)
                .order_by(ViewStar.starred_at, ViewStar.saved_view_id)
            )
        )
        catalogue = self.catalogue_service.catalogue(self.db)
        held = self.db.execute(
            select(DimensionFavourite.menu_code, DimensionFavourite.dimension)
            .where(DimensionFavourite.user_id == person.id)
            .order_by(DimensionFavourite.dimension)
        ).all()
        listed_in = {menu: _offered(catalogue, menu) for menu in FavouriteMenu}
        kept = {
            menu: [
                dimension
                for held_menu, dimension in held
                if held_menu is menu and dimension in listed_in[menu]
            ]
            for menu in FavouriteMenu
        }
        return Favourites(views, kept[FavouriteMenu.BY], kept[FavouriteMenu.COLOR])

    def favour(self, person: User, menu: FavouriteMenu, dimension: str) -> None:
        """`dimension` a favourite of `person`'s in `menu`'s list.

        Raises:
            ValidationException: the catalogue offers no such dimension there
        """
        offered = _offered(self.catalogue_service.catalogue(self.db), menu)
        if dimension not in offered:
            near = nearest(dimension, offered)
            raise ValidationException(
                f'Cannot mark "{dimension}" a favourite in {_LISTS[menu]} because '
                f"{_ALLOWED[menu]}."
                + (f" Did you mean {listed(quoted(near), 'or')}?" if near else "")
            )
        self.db.execute(
            insert(DimensionFavourite)
            .values(user_id=person.id, menu_code=menu, dimension=dimension)
            .on_conflict_do_nothing()
        )

    def unfavour(self, person: User, menu: FavouriteMenu, dimension: str) -> None:
        """`dimension` no favourite of `person`'s in `menu`'s list."""
        self.db.execute(
            delete(DimensionFavourite).where(
                DimensionFavourite.user_id == person.id,
                DimensionFavourite.menu_code == menu,
                DimensionFavourite.dimension == dimension,
            )
        )

    # ------------------------------------------------------ quick filters

    def quick_filters(self) -> list[QuickFilter]:
        """Every Quick Filter, in the order they were made, the catalogue's
        order of them."""
        return list(
            self.db.scalars(
                select(QuickFilter).order_by(QuickFilter.saved_at, QuickFilter.code)
            )
        )

    def add_quick_filter(
        self,
        label: str,
        chip: str,
        amount: str | None,
        note: str | None,
        now: datetime | None = None,
    ) -> QuickFilter:
        """A quick filter for everyone under a code of its own: `chip` as a
        state writes it, one that marks if the chip does, and `amount` the
        figure whose sum shows beside its count, or none.

        Raises:
            StateRefusedException: the chip has a fault
            ValidationException: the catalogue has no figure `amount`
        """
        catalogue = self.catalogue_service.catalogue(self.db)
        condition = read_chip(chip, catalogue, quota_weeks(self.db))
        figures = [figure.key for figure in catalogue.figures]
        if amount is not None and amount not in figures:
            near = nearest(amount, figures)
            raise ValidationException(
                f'Cannot add the quick filter "{label}" because no figure has the '
                f'key "{amount}".'
                + (f" Did you mean {listed(quoted(near), 'or')}?" if near else "")
            )
        quick_filter = QuickFilter(
            code=self._code(),
            label=label,
            condition=chip_key(replace(condition, marked=False)),
            marks=condition.marked,
            amount_figure=amount,
            note=note,
            saved_at=now or datetime.now(UTC),
        )
        self.db.add(quick_filter)
        self.db.flush()
        after_commit(self.catalogue_service.drop)
        return quick_filter

    def remove_quick_filter(self, quick_filter_id: uuid.UUID) -> None:
        """A quick filter removed, one the dashboard shipped with too, which
        nothing writes again.

        Raises:
            RecordNotFoundException: no Quick Filter has the id
        """
        quick_filter = self.db.get(QuickFilter, quick_filter_id)
        if quick_filter is None:
            raise RecordNotFoundException("Quick filter", str(quick_filter_id))
        self.db.delete(quick_filter)
        self.db.flush()
        after_commit(self.catalogue_service.drop)

    def _code(self) -> str:
        taken = set(self.db.scalars(select(QuickFilter.code)))
        while True:
            code = secrets.choice(string.ascii_lowercase) + "".join(
                secrets.choice(_CODE_LETTERS) for _ in range(CODE_LENGTH - 1)
            )
            if code not in taken:
                return code

    # ------------------------------------------------------ custom ratios

    def custom_ratios(self) -> list[CustomRatio]:
        """Every Custom Ratio, the loaded ones before a person's, each list by
        name."""
        return list(
            self.db.scalars(
                select(CustomRatio).order_by(
                    CustomRatio.system.desc(), CustomRatio.name, CustomRatio.id
                )
            )
        )

    def custom_ratio(self, ratio_id: uuid.UUID) -> CustomRatio:
        """The Custom Ratio of `ratio_id`.

        Raises:
            RecordNotFoundException: no Custom Ratio has the id
        """
        ratio = self.db.get(CustomRatio, ratio_id)
        if ratio is None:
            raise RecordNotFoundException("Custom ratio", str(ratio_id))
        return ratio

    def add_ratio(
        self,
        name: str,
        numerator: str,
        denominator: str,
        note: str | None,
        now: datetime | None = None,
    ) -> CustomRatio:
        """A ratio for everyone under `name`, its key made from the name in
        the space of a person's keys and kept, its two sides measures as a
        state writes them.

        Raises:
            StateRefusedException: a side has a fault, every fault of both
                named
            ResourceConflictException: a ratio a person made has the name
        """
        above, below = self._sides(numerator, denominator)
        self._name_free(name, None)
        ratio = CustomRatio(
            origin_code=Origin.PERSON,
            key=self._key(name),
            name=name,
            numerator=above,
            denominator=below,
            note=note,
            saved_at=now or datetime.now(UTC),
        )
        self.db.add(ratio)
        self.db.flush()
        after_commit(self.catalogue_service.drop)
        return ratio

    def edit_ratio(
        self,
        ratio_id: uuid.UUID,
        name: str,
        numerator: str,
        denominator: str,
        note: str | None,
        now: datetime | None = None,
    ) -> CustomRatio:
        """A ratio a person made changed in place under its key.

        Raises:
            RecordNotFoundException: no Custom Ratio has the id
            InvalidOperationException: the ratio is a loaded one
            StateRefusedException: a side has a fault, every fault of both
                named
            ResourceConflictException: another ratio a person made has the name
        """
        ratio = self.custom_ratio(ratio_id)
        _persons_ratio(ratio, "change")
        above, below = self._sides(numerator, denominator)
        self._name_free(name, ratio.id)
        ratio.name, ratio.numerator, ratio.denominator = name, above, below
        ratio.note = note
        ratio.saved_at = now or datetime.now(UTC)
        self.db.flush()
        after_commit(self.catalogue_service.drop)
        return ratio

    def remove_ratio(self, ratio_id: uuid.UUID) -> None:
        """A ratio a person made removed.

        Raises:
            RecordNotFoundException: no Custom Ratio has the id
            InvalidOperationException: the ratio is a loaded one
        """
        ratio = self.custom_ratio(ratio_id)
        _persons_ratio(ratio, "remove")
        self.db.delete(ratio)
        self.db.flush()
        after_commit(self.catalogue_service.drop)

    def _sides(self, numerator: str, denominator: str) -> tuple[str, str]:
        catalogue = self.catalogue_service.catalogue(self.db)
        weeks = quota_weeks(self.db)
        faults: list[Fault] = []
        sides = []
        for written in (numerator, denominator):
            try:
                sides.append(simple_key(read_simple(written, catalogue, weeks)))
            except StateRefusedException as refusal:
                faults.extend(refusal.faults)
        if faults:
            raise refused(faults)
        return sides[0], sides[1]

    def _name_free(self, name: str, own: uuid.UUID | None) -> None:
        same = select(CustomRatio.id).where(
            CustomRatio.system.is_(False), CustomRatio.name == name
        )
        if own is not None:
            same = same.where(CustomRatio.id != own)
        if self.db.scalar(same) is not None:
            raise ResourceConflictException("custom ratio", f'the name "{name}"')

    def _key(self, name: str) -> str:
        ascii_name = (
            unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        )
        word = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
        if len(word) > KEY_LENGTH:
            cut = word[: KEY_LENGTH + 1]
            word = cut.rsplit("_", 1)[0] if "_" in cut else word[:KEY_LENGTH]
        base = PERSON_KEYS + (word or "ratio")
        taken = set(
            self.db.scalars(
                select(CustomRatio.key).where(
                    CustomRatio.key.startswith(base, autoescape=True)
                )
            )
        )
        key, number = base, 2
        while key in taken:
            key, number = f"{base}_{number}", number + 1
        return key


_LISTS = {FavouriteMenu.BY: "By's list", FavouriteMenu.COLOR: "Color's list"}

_ALLOWED = {
    FavouriteMenu.BY: "it is no dimension of the catalogue's",
    FavouriteMenu.COLOR: "a color is a part, an attribute or token_kind",
}


def _offered(catalogue: Catalogue, menu: FavouriteMenu) -> list[str]:
    """What a person may mark a favourite in `menu`'s list: By any
    dimension, Color a part, an attribute or the token kind."""
    if menu is FavouriteMenu.BY:
        return [dimension.key for dimension in catalogue.dimensions]
    return [
        *(
            dimension.key
            for dimension in catalogue.dimensions
            if dimension.group in ("part", "attribute")
        ),
        TOKEN_KIND,
    ]


def _persons_view(view: SavedView, operation: str) -> None:
    if view.system:
        raise InvalidOperationException(
            f'{operation} the view "{view.name}"',
            "it is a system view, which the system manages: a star is all a "
            "person changes of it",
        )


def _persons_ratio(ratio: CustomRatio, operation: str) -> None:
    if ratio.system:
        raise InvalidOperationException(
            f'{operation} the ratio "{ratio.name}"',
            "it was loaded with the workflow's views, and nobody changes or "
            "removes a loaded ratio",
        )
