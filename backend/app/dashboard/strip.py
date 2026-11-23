"""A series' events strip (F164.6): the events in each of a series' points,
by their kind, from a route of its own, so that it never holds the chart up.

- A **bucket** is a value of the dimension the series asks (`asked`): its
  events in the window under the scope, by kind, and how many of them count
  as errors. A threshold on the By's rows and the outlier rows' chip drop
  whole points, which the page matches by key, so the strip reads the scope
  alone, and no mark.
- An event counts as an error by the Event fact's `is_error`: its Event
  Kind's for a stored Event, the catalogue's for an occurrence another
  entity records.
- The **kinds** are those the buckets hold, each with its label, whether it
  counts as an error and its count over them all: the errors first, then the
  rest, each group by its count, the largest first.
- A dimension the events lack is answered with no bucket, the strip saying
  why.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.dashboard.address import Address, AddressService
from app.dashboard.assembly import EVENT_KIND
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import Catalogue, Dimension
from app.dashboard.planner import Plan, Window, series_plan
from app.dashboard.state import Value
from app.dashboard.statements import Read, counted

EVENT_ERROR = "event_error"
"""The dimension that says whether an event's kind counts as an error."""


@dataclass(frozen=True)
class SeenKind:
    """A kind of event the strip holds, with its count over every bucket."""

    key: str
    label: str
    is_error: bool
    total: int


@dataclass(frozen=True)
class Bucket:
    """A point's events: `counts` each kind's, in the order of the strip's
    kinds, and `errors` those that count as errors."""

    key: Value
    counts: tuple[int, ...]
    errors: int


@dataclass(frozen=True)
class Strip:
    """A series' events strip, `refused` why where the events lack the
    dimension the series asks."""

    address: Address
    zone: str
    window: Window
    by: Dimension
    kinds: tuple[SeenKind, ...]
    buckets: tuple[Bucket, ...]
    refused: str | None = None


def strip_read(found: Plan, catalogue: Catalogue) -> Read | str:
    """The statement of the strip of a series' plan, or why the events lack
    its dimension."""
    fact = catalogue.fact(catalogue.offered(EVENT_KIND)[0])
    if fact.key not in catalogue.offered(found.by):
        return f"The strip counts {fact.many}, which have no {found.by}"
    return counted(found, catalogue, EVENT_KIND, EVENT_ERROR)


class StripService:
    """A series' events strip, from its view's state as the URL writes it."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def strip(self, written: str, now: datetime | None = None) -> Strip:
        """The events strip of the state `written`, its time as it stands at
        `now`.

        Raises:
            StateRefusedException: the state has a fault, or is not in order
                or over time
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        catalogue = view.catalogue
        found = series_plan(
            view.address.state, catalogue, view.weeks, now or datetime.now(UTC)
        )
        by = catalogue.dimension(found.by)
        read = strip_read(found, catalogue)
        if isinstance(read, str):
            return Strip(
                view.address, catalogue.zone, found.window, by, (), (), refused=read
            )
        with self.bounds.read(self.db) as db:
            rows = db.execute(read.select).all()
        names = {
            value.code: value.name
            for value in catalogue.dimension(EVENT_KIND).values or ()
        }
        totals: dict[str, int] = {}
        errors: set[str] = set()
        held: dict[Value, dict[str, int]] = {}
        for row in rows:
            totals[row.kind] = totals.get(row.kind, 0) + row.n
            if row.error:
                errors.add(row.kind)
            held.setdefault(row.b, {})[row.kind] = row.n
        kinds = tuple(
            SeenKind(kind, names.get(kind, kind), kind in errors, totals[kind])
            for kind in sorted(
                totals, key=lambda kind: (kind not in errors, -totals[kind], kind)
            )
        )
        return Strip(
            address=view.address,
            zone=catalogue.zone,
            window=found.window,
            by=by,
            kinds=kinds,
            buckets=tuple(
                Bucket(
                    key,
                    tuple(held[key].get(kind.key, 0) for kind in kinds),
                    sum(n for kind, n in held[key].items() if kind in errors),
                )
                for key in sorted(held, key=_order)
            ),
        )


def _order(value: Value) -> tuple[bool, str]:
    return (value is None, "" if value is None else str(value))
