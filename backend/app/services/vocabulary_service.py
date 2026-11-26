"""The labeller's vocabularies, as a collector declares them (F152.6; DB
decisions 79.12 and 79.40, assertion 585): Pilot holds every list a label
takes its value from as the labeller declares it, and its code names none of
the values."""

import logging
from collections import Counter
from typing import Any

from pilot_collection.vocabularies import VocabulariesSchema
from sqlalchemy import ColumnElement, delete, exists, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.dashboard.assembly import CatalogueService
from app.exceptions import VocabulariesInvalidException
from app.extensions import db
from app.models import (
    AskCategory,
    AvoidableKind,
    BuildResult,
    CallClass,
    CommandClass,
    ContextPartKind,
    EventKind,
    FileClass,
    ReworkKind,
    Rule,
    SegmentKind,
    ToolEffectKind,
    UnitMeasure,
    UnitOutcome,
    WaitCause,
    WorkUnitKind,
    WorkUnitKindNesting,
)
from app.models.call import RECORDED_ELSEWHERE
from app.utils.after_commit import after_commit

logger = logging.getLogger(__name__)

LISTS: dict[str, type[Any]] = {
    "work_unit_kind": WorkUnitKind,
    "unit_outcome": UnitOutcome,
    "rework_kind": ReworkKind,
    "unit_measure": UnitMeasure,
    "segment_kind": SegmentKind,
    "wait_cause": WaitCause,
    "call_class": CallClass,
    "avoidable_kind": AvoidableKind,
    "command_class": CommandClass,
    "build_result": BuildResult,
    "file_class": FileClass,
    "tool_effect_kind": ToolEffectKind,
    "rule": Rule,
    "ask_category": AskCategory,
    "event_kind": EventKind,
    "context_part_kind": ContextPartKind,
}
"""The reference entity each list of a declaration fills, by the list's name
in the call."""

BESIDE: tuple[type[Any], ...] = (EventKind, ContextPartKind)
"""The entities whose values are the collector's too: of these, a value the
labeller declared is one that holds a `description`."""

_Pair = tuple[str, str]


def _faults(vocabularies: VocabulariesSchema) -> list[str]:
    """Each way the declaration contradicts itself, in the call's order."""
    found: list[str] = []
    for name in LISTS:
        values = getattr(vocabularies.lists, name)
        for code, count in Counter(value.code for value in values).items():
            if count > 1:
                found.append(f"`{name}`: the code `{code}` is declared {count} times")
        for place, count in Counter(value.position for value in values).items():
            if count > 1:
                found.append(f"`{name}`: the position {place} is given {count} times")
    found.extend(
        f"`event_kind`: `{value.code}` is a kind another entity records, and no Event's"
        for value in vocabularies.lists.event_kind
        if value.code in RECORDED_ELSEWHERE
    )
    kinds = {value.code for value in vocabularies.lists.work_unit_kind}
    pairs = Counter((pair.inner, pair.outer) for pair in vocabularies.nesting)
    for (inner, outer), count in pairs.items():
        named = f"the nesting of `{inner}` in `{outer}`"
        if count > 1:
            found.append(f"{named} is given {count} times")
        found.extend(
            f"{named}: `{kind}` is no Work Unit Kind the call declares"
            for kind in dict.fromkeys((inner, outer))
            if kind not in kinds
        )
    return found


def _unnamed(entity: type[Any]) -> list[ColumnElement[bool]]:
    """A condition per foreign key of the record that references the
    entity's table: that no row of the key's table names the row."""
    referred = entity.__table__
    return [
        ~exists().where(*(element.parent == element.column for element in key.elements))
        for table in db.metadata.tables.values()
        for key in table.foreign_key_constraints
        if key.referred_table is referred
    ]


class VocabularyService:
    """Writes the labeller's vocabularies into the record on the caller's
    transaction."""

    def __init__(self, db: Session, catalogue_service: CatalogueService) -> None:
        """
        Args:
            catalogue_service: The dashboard's catalogue, which holds the
                reference entities' rows and is dropped where a call writes
                one
        """
        self.db = db
        self.catalogue_service = catalogue_service

    def declare(self, vocabularies: VocabulariesSchema) -> None:
        """Hold the labeller's vocabularies as the call declares them.

        A value is written where Pilot holds it otherwise, or not at all:
        its name, its line, its place and the fact about its category. A
        value the labeller no longer declares is removed where no row names
        it, and kept with no place where one does; of Event Kind and Context
        Part Kind those are the labeller's alone, the values with a line, and
        the collector's stand as they are. The nestings are the call's, one
        it no longer declares removed by the same rule. Where a row was
        written the catalogue's copy is dropped once the transaction has
        committed. The labeller's version is logged with what was written.

        Raises:
            VocabulariesInvalidException: the call has faults; nothing is
                written.
        """
        found = _faults(vocabularies)
        if found:
            raise VocabulariesInvalidException(vocabularies.version, found)
        gone: dict[type[Any], list[str]] = {}
        written = 0
        for name, entity in LISTS.items():
            values = getattr(vocabularies.lists, name)
            declared = [value.model_dump() for value in values]
            written += self._write(entity, declared)
            gone[entity] = self._gone(entity, {value.code for value in values})
        pairs = {(pair.inner, pair.outer) for pair in vocabularies.nesting}
        nestings = self._nest(pairs)
        removed = unplaced = 0
        for entity, codes in gone.items():
            taken, kept = self._remove(entity, codes)
            removed += taken
            unplaced += kept
        if written or nestings or removed or unplaced:
            after_commit(self.catalogue_service.drop)
        logger.info(
            "Took the vocabularies of the labeller %s: %d values written, %d"
            " nestings written or removed, %d values removed and %d kept with no"
            " place, no longer declared",
            vocabularies.version,
            written,
            nestings,
            removed,
            unplaced,
        )

    def _write(self, entity: type[Any], declared: list[dict[str, Any]]) -> int:
        """Write each declared value Pilot holds otherwise or not at all;
        returned is their number."""
        columns = entity.__table__.columns
        held = {
            row["code"]: dict(row)
            for row in self.db.execute(
                select(*columns).where(entity.code.in_([v["code"] for v in declared]))
            ).mappings()
        }
        changed = [value for value in declared if held.get(value["code"]) != value]
        if changed:
            insert = pg_insert(entity).values(changed)
            self.db.execute(
                insert.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        column.key: insert.excluded[column.key]
                        for column in columns
                        if column.key != "code"
                    },
                )
            )
        return len(changed)

    def _gone(self, entity: type[Any], declared: set[str]) -> list[str]:
        """The labeller's values of the entity that the call no longer
        declares."""
        held = select(entity.code).where(entity.code.not_in(declared))
        if entity in BESIDE:
            held = held.where(entity.description.is_not(None))
        return list(self.db.scalars(held))

    def _nest(self, declared: set[_Pair]) -> int:
        """Hold the nestings the call declares, and remove the others no row
        names; returned is the number of rows written or removed."""
        held: set[_Pair] = {
            (inner, outer)
            for inner, outer in self.db.execute(
                select(WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code)
            )
        }
        new = sorted(declared - held)
        if new:
            self.db.execute(
                pg_insert(WorkUnitKindNesting),
                [{"inner_code": inner, "outer_code": outer} for inner, outer in new],
            )
        removed = 0
        old = sorted(held - declared)
        if old:
            removed = len(
                self.db.execute(
                    delete(WorkUnitKindNesting)
                    .where(
                        tuple_(
                            WorkUnitKindNesting.inner_code,
                            WorkUnitKindNesting.outer_code,
                        ).in_(old),
                        *_unnamed(WorkUnitKindNesting),
                    )
                    .returning(WorkUnitKindNesting.inner_code)
                ).all()
            )
        return len(new) + removed

    def _remove(self, entity: type[Any], codes: list[str]) -> tuple[int, int]:
        """Remove each of those values no row names, and take its place from
        each other one; returned are the two numbers."""
        if not codes:
            return 0, 0
        removed: set[str] = set(
            self.db.scalars(
                delete(entity)
                .where(entity.code.in_(codes), *_unnamed(entity))
                .returning(entity.code)
            )
        )
        kept = [code for code in codes if code not in removed]
        unplaced = 0
        if kept:
            unplaced = len(
                self.db.scalars(
                    update(entity)
                    .where(entity.code.in_(kept), entity.position.is_not(None))
                    .values(position=None)
                    .returning(entity.code)
                ).all()
            )
        return len(removed), unplaced
