"""A view's address (F159): `#dash/<state>`, a state read and checked
(`reading`) and written back in its normal form, the one a chat links; an
entry's focus filled in from the record; and its time range fixed on
request, "this quota week" written as the week's own key and "the last 7
days" as its two dates, so that a link shows the time an answer was about.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard.assembly import CatalogueService
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import Catalogue
from app.dashboard.reading import WEEK, Checked, is_entry, read
from app.dashboard.state import (
    PREFIX,
    Between,
    Level,
    Preset,
    Simple,
    State,
    Time,
    Weeks,
    look,
    write,
)
from app.services.quota_week_service import Period, quota_weeks

ENTRY_MEASURES = (Simple("cost", "sum"), Simple("misses", "sum"))
"""An entry's measures, cost and the cache misses, one set for every kind
of focus (F166.1)."""

_ENTRY_LENGTH = 3_000
"""The bound of the entry's read, which carries the Call fact's source as
SQL text: some 2,400 characters for Pilot's own foci."""


@dataclass(frozen=True)
class Address:
    """A state read and checked: its meaning, its address in its normal
    form, its look-only parts as that form writes them, and a note for each
    part dropped."""

    state: State
    address: str
    look: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class View:
    """A state's address, with the catalogue and the quota weeks it was
    read under, and the deadline of the answer's reads: the engine's timeout
    from the state's check, which an entry's read took its time of."""

    address: Address
    catalogue: Catalogue
    weeks: tuple[Period, ...]
    deadline: float


class AddressService:
    """A view's state checked against the catalogue and the record, and
    written back as its address."""

    def __init__(
        self, db: Session, catalogue_service: CatalogueService, bounds: Bounds
    ) -> None:
        self.db = db
        self.catalogue_service = catalogue_service
        self.bounds = bounds

    def address(
        self, written: str, fix_time: bool = False, now: datetime | None = None
    ) -> Address:
        """The address of the state `written`, an entry's filled in from the
        record; with `fix_time`, its time range as it stands at `now`.
        `StateRefusedException` where the state has a fault."""
        return self.view(written, fix_time, now).address

    def view(
        self, written: str, fix_time: bool = False, now: datetime | None = None
    ) -> View:
        """The address of the state `written`, as `address` gives it, with
        the catalogue and the quota weeks it was read under, and the
        deadline its answer's reads take."""
        deadline = self.bounds.deadline()
        catalogue = self.catalogue_service.catalogue(self.db)
        weeks = self.weeks()
        checked = read(written, catalogue, weeks)
        if is_entry(written):
            checked = self.entry(catalogue, checked, deadline)
        state = checked.state
        if fix_time:
            state = replace(
                state,
                time=fixed(state.time, catalogue, weeks, now or datetime.now(UTC)),
            )
        return View(
            Address(state, PREFIX + write(state), look(state), checked.notes),
            catalogue,
            weeks,
            deadline,
        )

    def weeks(self) -> tuple[Period, ...]:
        """The quota weeks the record holds, in the order they start."""
        return quota_weeks(self.db)

    def entry(self, catalogue: Catalogue, checked: Checked, deadline: float) -> Checked:
        """An entry's state: its focus's path as the drill stack, each level
        as if drilled from By its own part; By the focus's parts in rows;
        cost and the cache misses; the quota weeks its Calls fall in, all
        time where it has none (F166.1). Its read runs under the engine's
        bounds, before `deadline`."""
        focus = checked.state.focus
        assert focus is not None
        dimension = catalogue.dimension(focus.dimension)
        above = parents(catalogue, dimension.key)
        row = catalogue.row(catalogue.fact(catalogue.figure("cost").fact))
        columns = [
            catalogue.dimension(WEEK).path(row),
            *(catalogue.dimension(key).path(row) for key in above),
        ]
        named = dimension.path(row) == focus.key
        with self.bounds.read(self.db, deadline) as db:
            found = db.execute(
                select(*columns)
                .select_from(row.source())
                .where(named)
                .distinct()
                .execution_options(max_statement_length=_ENTRY_LENGTH)
            ).all()
        starts = sorted(
            {found_row[0] for found_row in found if found_row[0] is not None}
        )
        levels = [
            Level(key, value, key)
            for place, key in enumerate(above, start=1)
            if (
                value := next(
                    (one[place] for one in found if one[place] is not None), None
                )
            )
            is not None
        ]
        notes = checked.notes
        if not found:
            notes += (
                f"f={focus.dimension}: the record holds nothing of it yet, so the "
                "view takes all time.",
            )
        whole = next(
            time_range.key for time_range in catalogue.ranges if time_range.unit is None
        )
        return Checked(
            State(
                time=Weeks(tuple(starts)) if starts else Preset(whole),
                by=dimension.next or dimension.key,
                measures=ENTRY_MEASURES,
                levels=(*levels, Level(dimension.key, focus.key, dimension.key)),
                focus=focus,
            ),
            notes,
        )


def parents(catalogue: Catalogue, part: str) -> list[str]:
    """The parts above `part`, outermost first: each the one part whose next
    level down is the one under it."""
    chain: list[str] = []
    while True:
        above = [
            dimension.key
            for dimension in catalogue.dimensions
            if dimension.group == "part" and dimension.next == part
        ]
        if len(above) != 1 or above[0] in chain:
            return chain
        part = above[0]
        chain.insert(0, part)


def fixed(
    time: Time, catalogue: Catalogue, weeks: Sequence[Period], now: datetime
) -> Time:
    """A time range as it stands at `now`: a range of days as its two dates
    in the catalogue's zone, a range of quota weeks as their keys, the
    running week the latest the record holds; all time, and a range already
    fixed, as written."""
    if not isinstance(time, Preset):
        return time
    named = next(one for one in catalogue.ranges if one.key == time.key)
    if named.unit == "day":
        last = now.astimezone(ZoneInfo(catalogue.zone)).date() - timedelta(
            days=named.back
        )
        return Between(last - timedelta(days=named.count - 1), last)
    if named.unit == "quota_week":
        end = len(weeks) - named.back
        chosen = weeks[max(0, end - named.count) : max(0, end)]
        return Weeks(tuple(week.starts_at for week in chosen)) if chosen else time
    return time
