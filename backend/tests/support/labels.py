"""Rows of what an invented labeller gave, for tests of what the record holds
of its labels: its declared values, its Work Units under the kitchen's Work
Unit Kinds, a Test Suite and a CI Build. Each helper adds its row and
flushes, so the row has its id."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import CIBuild, TestSuite, WorkUnit, WorkUnitKind, WorkUnitKindNesting
from tests.support.transcripts import STARTED

MENU, COURSE, DISH = "menu", "course", "dish"
"""The invented Work Unit Kinds, each sitting in the one before it."""


def declared[Row](db: DbSession, entity: type[Row], code: str, **facts: Any) -> Row:
    """The labeller's value `code` of the entity, at the next place in its
    list, written where the test has not met it yet."""
    row = db.get(entity, code)
    if row is None:
        place = (db.scalar(select(func.max(entity.position))) or 0) + 1  # type: ignore[attr-defined]
        row = entity(
            code=code,
            name=code.replace("_", " ").capitalize(),
            description=f"The {code.replace('_', ' ')}.",
            position=place,
            **facts,
        )
        db.add(row)
        db.flush()
    return row


def kinds(db: DbSession) -> None:
    """The kitchen's Work Unit Kinds and their nestings: a course in a menu,
    a dish in a course."""
    for kind in (MENU, COURSE, DISH):
        declared(db, WorkUnitKind, kind)
    for inner, outer in ((COURSE, MENU), (DISH, COURSE)):
        if db.get(WorkUnitKindNesting, (inner, outer)) is None:
            db.add(WorkUnitKindNesting(inner_code=inner, outer_code=outer))
    db.flush()


def work_unit(
    db: DbSession,
    key: str,
    kind: str = MENU,
    part_of: WorkUnit | None = None,
    **overrides: Any,
) -> WorkUnit:
    """The Work Unit of `key`, of the kind, sitting in `part_of`."""
    kinds(db)
    values: dict[str, Any] = {
        "key": key,
        "kind_code": kind,
        "title": key.rsplit("|", 1)[-1],
        "started_at": STARTED,
    }
    if part_of is not None:
        values |= {"part_of_id": part_of.id, "part_of_kind_code": part_of.kind_code}
    values.update(overrides)
    row = WorkUnit(**values)
    db.add(row)
    db.flush()
    return row


def suite(db: DbSession, code: str = "RecipeBox/backend/test") -> TestSuite:
    row = TestSuite(code=code, name=code.replace("/", " "))
    db.add(row)
    db.flush()
    return row


def ci_build(
    db: DbSession, job: str = "RecipeBox/Build-Main", number: int = 812, **facts: Any
) -> CIBuild:
    row = CIBuild(job=job, number=number, **facts)
    db.add(row)
    db.flush()
    return row
