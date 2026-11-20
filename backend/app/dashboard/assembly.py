"""The catalogue's assembly (F154.4): Pilot's code's entries, with what the
record's rows give — a vocabulary's rows as a dimension's values, and a
version dimension per Component — and the process's copy of it, kept until a
publication writes a vocabulary's row."""

import threading
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard.catalogue import Catalogue, Value
from app.dashboard.dimensions import (
    own_dimensions,
    version_dimension,
    version_keys,
    with_values,
)
from app.dashboard.facts import FACTS, OCCURRENCES, own_joins, version_joins
from app.dashboard.measures import AGGREGATES, FIGURES, RANGES, RATIOS
from app.models import (
    CompactionTrigger,
    Component,
    EventKind,
    MissCause,
    Model,
    SessionKind,
    StopReason,
)

_VOCABULARIES: dict[str, type[Any]] = {
    "session_kind": SessionKind,
    "model": Model,
    "stop_reason": StopReason,
    "miss_cause": MissCause,
    "compact_trigger": CompactionTrigger,
}
"""The reference entity whose rows are a dimension's values, by the
dimension's key."""

EVENT_KIND = "event_kind"
"""The dimension whose values are the Event Kinds: the record's rows, and
the kinds whose occurrences other entities record."""


def _rows(db: Session, entity: type[Any]) -> tuple[Value, ...]:
    rows = db.execute(
        select(entity.code, entity.name).order_by(entity.name, entity.code)
    )
    return tuple(Value(str(code), str(name)) for code, name in rows)


def _event_kinds(db: Session) -> tuple[Value, ...]:
    stored = [
        Value(kind.code, kind.name, is_error=kind.is_error)
        for kind in db.scalars(select(EventKind))
    ]
    recorded = [
        Value(kind.code, kind.name, is_error=kind.is_error) for kind in OCCURRENCES
    ]
    return tuple(sorted(stored + recorded, key=lambda kind: (kind.name, kind.code)))


def assemble(db: Session, zone: str, sitting_gap: timedelta) -> Catalogue:
    """The catalogue as the record stands: the local time derived in `zone`,
    a sitting ended by a gap of `sitting_gap`."""
    components: Sequence[Component] = db.scalars(
        select(Component).order_by(Component.code)
    ).all()
    keys = version_keys(components)
    values = {key: _rows(db, entity) for key, entity in _VOCABULARIES.items()}
    values[EVENT_KIND] = _event_kinds(db)
    return Catalogue(
        zone=zone,
        sitting_gap=sitting_gap,
        facts=FACTS,
        joins=own_joins(sitting_gap)
        + tuple(join for component in components for join in version_joins(component)),
        dimensions=tuple(
            with_values(dimension, values[dimension.key])
            if dimension.key in values
            else dimension
            for dimension in own_dimensions(zone)
        )
        + tuple(
            version_dimension(component, keys[component.code])
            for component in components
        ),
        figures=FIGURES,
        aggregates=AGGREGATES,
        ratios=RATIOS,
        ranges=RANGES,
    )


class CatalogueService:
    """The process's catalogue: assembled at its first read and kept until
    `drop`, which the publication that wrote a vocabulary's row calls once
    its transaction has committed."""

    def __init__(self, zone: str, sitting_gap_seconds: float) -> None:
        self.zone = zone
        self.sitting_gap = timedelta(seconds=sitting_gap_seconds)
        self._lock = threading.Lock()
        self._held: Catalogue | None = None
        self._drops = 0

    def catalogue(self, db: Session) -> Catalogue:
        """The catalogue, assembled on `db` where the process holds none."""
        with self._lock:
            held, drops = self._held, self._drops
        if held is not None:
            return held
        assembled = assemble(db, self.zone, self.sitting_gap)
        with self._lock:
            # One dropped while it was assembled may have read the record
            # before the row that dropped it.
            if self._drops == drops:
                self._held = assembled
        return assembled

    def drop(self) -> None:
        """Forget the catalogue held: the next read assembles it anew."""
        with self._lock:
            self._held = None
            self._drops += 1
