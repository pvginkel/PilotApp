"""The catalogue's assembly (F154.4): Pilot's code's entries, with what the
record's rows give — a vocabulary's rows as a dimension's values, a version
dimension per Component and the marker of its versions; from the labeller's
declared rows a part per Work Unit Kind in the drill's order its nestings
give, each along its order by its units' start, a figure per Unit Measure,
and each value with its line and its place;
and from the stored configuration the custom ratios and the quick filters —
and the process's copy of it, kept until a publication writes a
vocabulary's row, a collector's declaration writes one of the labeller's, or
a person writes a quick filter or a ratio.

A key the labeller's code takes is its code where Pilot's code has not
taken it (`dimensions.declared_keys`), so that a code the labeller declares
never displaces an entry of Pilot's.

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
    Dimension,
    Format,
    QuickFilter,
    Ratio,
    RatioOrigin,
    Value,
)
from app.dashboard.dimensions import (
    configuration_marker,
    declared_keys,
    kind_dimension,
    kind_order,
    own_dimensions,
    reaches,
    version_dimension,
    version_keys,
    version_marker,
    with_values,
)
from app.dashboard.facts import (
    FACTS,
    OCCURRENCES,
    own_joins,
    unit_joins,
    unit_measure_join,
    version_joins,
)
from app.dashboard.measures import (
    AGGREGATES,
    FIGURES,
    RANGES,
    RATIOS,
    measure_figure,
)
from app.dashboard.reading import read_chip, read_simple
from app.dashboard.state import Simple
from app.exceptions import StateRefusedException
from app.models import (
    AvoidableKind,
    CallClass,
    CompactionTrigger,
    Component,
    EventKind,
    MissCause,
    Model,
    ReworkKind,
    SegmentKind,
    SessionKind,
    StopReason,
    UnitMeasure,
    UnitOutcome,
    WaitCause,
    WorkUnitKind,
    WorkUnitKindNesting,
)
from app.services.quota_week_service import Period, quota_weeks

_VOCABULARIES: dict[str, type[Any]] = {
    "session_kind": SessionKind,
    "model": Model,
    "stop_reason": StopReason,
    "miss_cause": MissCause,
    "compact_trigger": CompactionTrigger,
}
"""The reference entity of Pilot's or the collector's whose rows are a
dimension's values, by the dimension's key."""

_DECLARED: dict[str, type[Any]] = {
    "call_class": CallClass,
    "avoidable_kind": AvoidableKind,
    "wait_cause": WaitCause,
    "segment_kind": SegmentKind,
    "outcome": UnitOutcome,
    "rework_kind": ReworkKind,
}
"""The list of the labeller's whose values are a dimension's values, by the
dimension's key."""

CONVERSATION = "conversation"
"""The part a Work Unit Kind's row drills to where no kind sits in it."""

EVENT_KIND = "event_kind"
"""The dimension whose values are the Event Kinds: the record's rows, and
the kinds whose occurrences other entities record."""


def _rows(db: Session, entity: type[Any]) -> tuple[Value, ...]:
    rows = db.execute(
        select(entity.code, entity.name).order_by(entity.name, entity.code)
    )
    return tuple(Value(str(code), str(name)) for code, name in rows)


def _in_place(entity: Any) -> tuple[Any, ...]:
    """The order of the labeller's values: their place in their list, a
    value no longer declared after them by its name."""
    return (entity.position.asc().nulls_last(), entity.name, entity.code)


def _declared(db: Session, entity: type[Any]) -> tuple[Value, ...]:
    """The labeller's values of a list, each with its line and its place."""
    rows: Sequence[Any] = db.scalars(select(entity).order_by(*_in_place(entity))).all()
    return tuple(
        Value(row.code, row.name, line=row.description, position=row.position)
        for row in rows
    )


def _event_kinds(db: Session) -> tuple[Value, ...]:
    stored = [
        Value(
            kind.code,
            kind.name,
            line=kind.description,
            position=kind.position,
            is_error=kind.is_error,
        )
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
    with_ratios = replace(own, ratios=own.ratios + _ratios(db, own, weeks))
    return replace(with_ratios, quick_filters=_quick_filters(db, with_ratios, weeks))


def _own(db: Session, zone: str, sitting_gap: timedelta) -> Catalogue:
    """Pilot's code's entries with the record's vocabularies and the
    labeller's declared rows."""
    components: Sequence[Component] = db.scalars(
        select(Component).order_by(Component.code)
    ).all()
    keys = version_keys(components)
    values = {key: _rows(db, entity) for key, entity in _VOCABULARIES.items()}
    values |= {key: _declared(db, entity) for key, entity in _DECLARED.items()}
    values[EVENT_KIND] = _event_kinds(db)
    own = tuple(
        with_values(dimension, values[dimension.key])
        if dimension.key in values
        else dimension
        for dimension in own_dimensions(zone)
    )
    taken = {
        *(dimension.key for dimension in own),
        *keys.values(),
        *(fact.key for fact in FACTS),
    }
    hops, kinds = _kinds(db, taken)
    measures: Sequence[UnitMeasure] = db.scalars(
        select(UnitMeasure).order_by(*_in_place(UnitMeasure))
    ).all()
    figure_keys = declared_keys(
        [measure.code for measure in measures], {figure.key for figure in FIGURES}
    )
    return Catalogue(
        zone=zone,
        sitting_gap=sitting_gap,
        facts=FACTS,
        joins=own_joins(sitting_gap)
        + unit_joins(hops)
        + tuple(unit_measure_join(measure.code) for measure in measures)
        + tuple(join for component in components for join in version_joins(component)),
        dimensions=own
        + kinds
        + tuple(
            version_dimension(component, keys[component.code])
            for component in components
        ),
        figures=FIGURES
        + tuple(
            measure_figure(measure, figure_keys[measure.code]) for measure in measures
        ),
        aggregates=AGGREGATES,
        ratios=RATIOS,
        ranges=RANGES,
        markers=tuple(
            version_marker(component, keys[component.code]) for component in components
        )
        + (configuration_marker(),),
    )


def _kinds(db: Session, taken: set[str]) -> tuple[int, tuple[Dimension, ...]]:
    """A part per Work Unit Kind, in their places, then each kind along its
    order, each under a key none of `taken` holds; and the most steps up from
    a Work Unit any of them reads. A kind's row drills to the first kind by
    its place that sits in it, and one that none sits in to the
    conversation."""
    kinds: Sequence[WorkUnitKind] = db.scalars(
        select(WorkUnitKind).order_by(*_in_place(WorkUnitKind))
    ).all()
    nestings = [
        (inner, outer)
        for inner, outer in db.execute(
            select(WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code)
        )
    ]
    keys = declared_keys([kind.code for kind in kinds], taken)
    reach = reaches(nestings)
    placed = {kind.code: place for place, kind in enumerate(kinds)}
    below: dict[str, str] = {}
    for inner, outer in sorted(nestings, key=lambda pair: placed[pair[0]]):
        below.setdefault(outer, inner)
    parts = tuple(
        kind_dimension(
            kind,
            keys[kind.code],
            keys[below[kind.code]] if kind.code in below else CONVERSATION,
            reach.get(kind.code, 0),
        )
        for kind in kinds
    )
    orders = declared_keys(
        [f"{keys[kind.code]}_start" for kind in kinds], taken | set(keys.values())
    )
    along = tuple(
        kind_order(kind, orders[f"{part.key}_start"], part, reach.get(kind.code, 0))
        for kind, part in zip(kinds, parts, strict=True)
    )
    return max(reach.values(), default=0), parts + along


class CatalogueService:
    """The process's catalogue: assembled at its first read and kept until
    `drop`, which the publication that wrote a vocabulary's row, the
    declaration of the labeller's vocabularies that wrote one, and a write
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
