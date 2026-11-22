"""What the dashboard stores (F155; DB §2.10): the saved views, the quick
filters and the custom ratios everyone shares, and a person's favourites.

The system views are the system's: no User changes one but by its star (DB
601). Pilot's own name nothing of a workflow and are what this release's code
holds (`app/dashboard/views.py`): each deploy loads them after the revisions
(`post_migration_hook`), as does the load of the invented record. The
workflow's views and its loaded ratios are what the entries of its file make
them, which the service user hands the route of their load (F155.3), every
entry checked before any is written. A load of an Origin's rows leaves them
the entries it is given, matched by key: an entry a row has changes that row
in place, its stars kept; one no row has is added; a row whose key the
entries no longer hold is removed, its stars with it (DB 604).

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
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.dashboard.address import AddressService
from app.dashboard.assembly import CatalogueService, ratio_format
from app.dashboard.catalogue import Catalogue, Ratio
from app.dashboard.reading import read, read_chip, read_simple
from app.dashboard.refusal import (
    ENTRY,
    Fault,
    in_entry,
    listed,
    nearest,
    quoted,
    refused,
    refused_load,
)
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
    """What a load of system views or loaded ratios wrote: the rows it
    added, changed and removed."""

    added: int
    changed: int
    removed: int


@dataclass(frozen=True)
class RatioEntry:
    """A ratio as the workflow's file names it: `key` matches it to its
    loaded row, and is what a view's state names it by after `r:`."""

    key: str
    name: str
    numerator: str
    denominator: str
    note: str | None = None


@dataclass(frozen=True)
class WorkflowLoaded:
    """What a load of the workflow's views and ratios wrote, and a note for
    each part of a view's state dropped, named with its view."""

    views: Loaded
    ratios: Loaded
    notes: tuple[str, ...]


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
        return self._load(SavedView, origin, views, _VIEW_FIELDS, now)

    def load_workflow(
        self,
        views: Sequence[SystemView],
        ratios: Sequence[RatioEntry],
        now: datetime | None = None,
    ) -> WorkflowLoaded:
        """The workflow's system views and loaded ratios made the entries of
        its file, each by its key (F155.3; DB 604): a view's state and a
        ratio's two sides kept in their normal form, a view's read under the
        ratios the load leaves, so that it may name one the same load holds.

        Raises:
            StateRefusedException: an entry has a fault, every fault of every
                entry named with its entry, and nothing is written
        """
        catalogue = self.catalogue_service.catalogue(self.db)
        weeks = quota_weeks(self.db)
        built_in = {ratio.key for ratio in catalogue.ratios if ratio.origin is None}
        ratio_faults = _repeated("ratio", ratios)
        kept: list[RatioEntry] = []
        offered: list[Ratio] = []
        for ratio in ratios:
            place = f'ratio "{ratio.key}"'
            key_fault = _key_fault(place, ratio.key, built_in)
            if key_fault is not None:
                ratio_faults.append(key_fault)
            sides = []
            for written in (ratio.numerator, ratio.denominator):
                try:
                    sides.append(read_simple(written, catalogue, weeks))
                except StateRefusedException as refusal:
                    ratio_faults.extend(
                        in_entry(place, fault) for fault in refusal.faults
                    )
            if len(sides) < 2:
                continue
            above, below = sides
            kept.append(
                replace(
                    ratio, numerator=simple_key(above), denominator=simple_key(below)
                )
            )
            if key_fault is None and all(one.key != ratio.key for one in offered):
                offered.append(
                    Ratio(
                        key=ratio.key,
                        label=ratio.name,
                        line=ratio.note,
                        format=ratio_format(catalogue, above, below),
                        numerator=simple_key(above),
                        denominator=simple_key(below),
                        origin="workflow",
                    )
                )
        leaves = replace(
            catalogue,
            ratios=(
                *(one for one in catalogue.ratios if one.origin != "workflow"),
                *offered,
            ),
        )
        pilots = set(
            self.db.scalars(
                select(SavedView.name).where(SavedView.origin_code == Origin.PILOT)
            )
        )
        view_faults = _repeated("view", views)
        normal: list[SystemView] = []
        notes: list[str] = []
        for view in views:
            place = f'view "{view.key}"'
            if view.name in pilots:
                view_faults.append(
                    Fault(
                        f'{place}, name "{view.name}"',
                        ENTRY,
                        "one of Pilot's own system views has the name, and a name "
                        "stands once among the system views",
                    )
                )
            try:
                checked = read(view.state, leaves, weeks)
            except StateRefusedException as refusal:
                view_faults.extend(in_entry(place, fault) for fault in refusal.faults)
                continue
            normal.append(replace(view, state=write(checked.state)))
            notes.extend(f"{place}, {note}" for note in checked.notes)
        if view_faults or ratio_faults:
            raise refused_load([*view_faults, *ratio_faults])
        saved_at = now or datetime.now(UTC)
        loaded = WorkflowLoaded(
            self.load_views(Origin.WORKFLOW, normal, saved_at),
            self._load(CustomRatio, Origin.WORKFLOW, kept, _RATIO_FIELDS, saved_at),
            tuple(notes),
        )
        after_commit(self.catalogue_service.drop)
        return loaded

    def _load(
        self,
        model: type[SavedView] | type[CustomRatio],
        origin: Origin,
        entries: Sequence[SystemView | RatioEntry],
        fields: tuple[str, ...],
        now: datetime,
    ) -> Loaded:
        """The rows of `model` of `origin` made `entries`, one per key, by
        key, each entry's `fields` its row's; a row added or changed saved
        at `now`."""
        rows: list[Any] = list(
            self.db.scalars(select(model).where(model.origin_code == origin))
        )
        held = {row.key: row for row in rows}
        keys = {entry.key for entry in entries}
        gone = [row.id for key, row in held.items() if key not in keys]
        if gone:
            # Before the others are written, so that a name a removed row
            # held is free for one of them.
            self.db.execute(delete(model).where(model.id.in_(gone)))
        renamed = [
            held[entry.key]
            for entry in entries
            if entry.key in held and held[entry.key].name != entry.name
        ]
        if renamed:
            # A name stands once in its list at every row's write, so a name
            # one row takes from another is freed first, under a stand-in a
            # line break leads: no name of one line is one.
            for row in renamed:
                row.name = f"\n{row.id}"
            self.db.flush()
        added = changed = 0
        for entry in entries:
            values = {field: getattr(entry, field) for field in fields}
            row = held.get(entry.key)
            if row is None:
                self.db.add(
                    model(origin_code=origin, key=entry.key, saved_at=now, **values)
                )
                added += 1
            elif any(getattr(row, field) != value for field, value in values.items()):
                for field, value in values.items():
                    setattr(row, field, value)
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


_VIEW_FIELDS = ("name", "state", "note")
_RATIO_FIELDS = ("name", "numerator", "denominator", "note")


def _repeated(kind: str, entries: Sequence[SystemView | RatioEntry]) -> list[Fault]:
    """A fault for each key that stands on more than one entry, and for each
    entry whose name one before it has."""
    faults = []
    keys = [entry.key for entry in entries]
    for key in dict.fromkeys(keys):
        if (count := keys.count(key)) > 1:
            faults.append(
                Fault(
                    f'{kind} "{key}"',
                    ENTRY,
                    f"the key stands on {count} entries, and a load takes one "
                    "entry a key",
                )
            )
    named: dict[str, str] = {}
    for entry in entries:
        first = named.setdefault(entry.name, entry.key)
        if first != entry.key:
            faults.append(
                Fault(
                    f'{kind} "{entry.key}", name "{entry.name}"',
                    ENTRY,
                    f'the {kind} "{first}" has the name too, and a name stands '
                    f"once among the loaded {kind}s",
                )
            )
    return faults


def _key_fault(place: str, key: str, built_in: set[str]) -> Fault | None:
    """The fault of a loaded ratio's key: one in the space of a person's
    keys (DB 602), or a built-in ratio's."""
    if key.startswith(PERSON_KEYS):
        return Fault(
            f"{place}, key",
            ENTRY,
            f'a key that begins "{PERSON_KEYS}" is a ratio a person made, and a '
            "loaded ratio's key is outside that space",
        )
    if key in built_in:
        return Fault(
            f"{place}, key",
            ENTRY,
            "a ratio built into the dashboard has the key, and a loaded ratio's "
            "key is no built-in one's",
        )
    return None


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
