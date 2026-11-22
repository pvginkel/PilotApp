"""The catalogue's assembly (F154.4): Pilot's code's entries, with what the
record's rows give — a vocabulary's rows as a dimension's values, a version
dimension per Component, and from the stored configuration the custom
ratios and the quick filters — and the process's copy of it, kept until a
publication writes a vocabulary's row or a person writes a quick filter or a
ratio.

A stored ratio or quick filter is offered where what it names reads under
the rest of the catalogue: a ratio's two measures, a quick filter's chip and
its amount's figure; and a ratio where its key is no built-in ratio's. One
that does not is left out, so that a state naming it drops it with a note
(`reading`), as it does one that is gone.
"""

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.dashboard.catalogue import (
    Catalogue,
    Format,
    QuickFilter,
    Ratio,
    RatioOrigin,
    Value,
)
from app.dashboard.dimensions import (
    own_dimensions,
    version_dimension,
    version_keys,
    with_values,
)
from app.dashboard.facts import FACTS, OCCURRENCES, own_joins, version_joins
from app.dashboard.measures import AGGREGATES, FIGURES, RANGES, RATIOS
from app.dashboard.reading import read_chip, read_simple
from app.dashboard.state import Simple
from app.exceptions import StateRefusedException
from app.models import (
    CompactionTrigger,
    Component,
    EventKind,
    MissCause,
    Model,
    SessionKind,
    StopReason,
)
from app.services.quota_week_service import Period, quota_weeks

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


def ratio_format(
    catalogue: Catalogue, numerator: Simple, denominator: Simple
) -> Format:
    """A stored ratio's format: a share of two measures of one format, else
    its numerator's."""
    above = catalogue.figure(numerator.figure).format
    below = catalogue.figure(denominator.figure).format
    return "share" if above == below else above


def _ratios(
    db: Session, catalogue: Catalogue, weeks: Sequence[Period]
) -> tuple[Ratio, ...]:
    built_in = {ratio.key for ratio in catalogue.ratios}
    ratios = []
    for row in db.scalars(
        select(models.CustomRatio).order_by(
            models.CustomRatio.system.desc(), models.CustomRatio.name
        )
    ):
        if row.key in built_in:
            continue
        try:
            numerator = read_simple(row.numerator, catalogue, weeks)
            denominator = read_simple(row.denominator, catalogue, weeks)
        except StateRefusedException:
            continue
        ratios.append(
            Ratio(
                key=row.key,
                label=row.name,
                line=row.note,
                format=ratio_format(catalogue, numerator, denominator),
                numerator=row.numerator,
                denominator=row.denominator,
                origin=cast(RatioOrigin, row.origin_code.value),
            )
        )
    return tuple(ratios)


def _quick_filters(
    db: Session, catalogue: Catalogue, weeks: Sequence[Period]
) -> tuple[QuickFilter, ...]:
    figures = {figure.key for figure in catalogue.figures}
    quick_filters = []
    for row in db.scalars(
        select(models.QuickFilter).order_by(
            models.QuickFilter.saved_at, models.QuickFilter.code
        )
    ):
        if row.amount_figure is not None and row.amount_figure not in figures:
            continue
        try:
            read_chip(row.condition, catalogue, weeks)
        except StateRefusedException:
            continue
        quick_filters.append(
            QuickFilter(
                key=row.code,
                label=row.label,
                condition=row.condition,
                marks=row.marks,
                amount=row.amount_figure,
                note=row.note,
            )
        )
    return tuple(quick_filters)


def assemble(db: Session, zone: str, sitting_gap: timedelta) -> Catalogue:
    """The catalogue as the record stands: the local time derived in `zone`,
    a sitting ended by a gap of `sitting_gap`."""
    own = _own(db, zone, sitting_gap)
    weeks = quota_weeks(db)
    return replace(
        own,
        ratios=own.ratios + _ratios(db, own, weeks),
        quick_filters=_quick_filters(db, own, weeks),
    )


def _own(db: Session, zone: str, sitting_gap: timedelta) -> Catalogue:
    """Pilot's code's entries with the record's vocabularies."""
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
    `drop`, which the publication that wrote a vocabulary's row, and a write
    of a quick filter or a custom ratio, calls once its transaction has
    committed."""

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
