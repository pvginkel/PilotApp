"""The labeller's reference entities and Work Unit Kind Nesting: what a row
must hold (DB §2.8, §2.11; decision 79.40, assertion 585)."""

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

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
from tests.support.database import violated_constraint

OWN: dict[type[Any], dict[str, Any]] = {
    WorkUnitKind: {},
    UnitOutcome: {},
    ReworkKind: {},
    UnitMeasure: {"unit": "dishes"},
    SegmentKind: {},
    WaitCause: {},
    CallClass: {},
    AvoidableKind: {},
    CommandClass: {},
    BuildResult: {},
    FileClass: {"counted": True},
    ToolEffectKind: {},
    Rule: {"home": "/kitchen/RULES.md"},
    AskCategory: {},
}
"""The labeller's own reference entities, each with the fact about its
category it holds."""

BESIDE: dict[type[Any], dict[str, Any]] = {
    EventKind: {"is_error": False},
    ContextPartKind: {},
}
"""The collector's reference entities that hold the labeller's values too."""

EVERY = OWN | BESIDE


def _value(entity: type[Any], code: str, position: int | None, **overrides: Any) -> Any:
    facts: dict[str, Any] = {
        "code": code,
        "name": code.capitalize(),
        "description": f"The {code}.",
        "position": position,
    }
    return entity(**(facts | EVERY[entity] | overrides))


def _violated_at_commit(session: DbSession) -> str:
    """Flush, check the deferred constraints as a commit does, and return the
    name of the one violated."""
    session.flush()
    with pytest.raises(IntegrityError) as raised:
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return raised.value.orig.diag.constraint_name


@pytest.mark.parametrize("entity", list(EVERY), ids=lambda e: e.__tablename__)
class TestADeclaredValue:
    def test_it_holds_its_line_its_place_and_its_fact(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        session.add(_value(entity, "simmer", 1))
        session.flush()
        session.expunge_all()

        held = session.get(entity, "simmer")
        assert held is not None
        assert (held.name, held.description, held.position) == (
            "Simmer",
            "The simmer.",
            1,
        )
        for fact, given in EVERY[entity].items():
            assert getattr(held, fact) == given

    def test_no_two_hold_one_place_in_the_list(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        session.add_all([_value(entity, "simmer", 1), _value(entity, "sear", 1)])

        assert _violated_at_commit(session) == f"uq_{entity.__tablename__}_position"

    def test_two_values_swap_places_in_one_transaction(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        """The places' uniqueness is checked at the commit, so a declaration
        that reorders a list moves its values through a repeated place."""
        first, second = _value(entity, "simmer", 1), _value(entity, "sear", 2)
        session.add_all([first, second])
        session.flush()
        first.position = 2
        session.flush()
        second.position = 1
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        places = session.execute(
            select(entity.code, entity.position).order_by(entity.position)
        ).all()
        assert places == [("sear", 1), ("simmer", 2)]

    def test_values_no_longer_declared_hold_no_place(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        session.add_all([_value(entity, "simmer", None), _value(entity, "sear", None)])
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        assert session.scalars(select(entity.position)).all() == [None, None]

    def test_its_place_is_from_one(self, session: DbSession, entity: type[Any]) -> None:
        session.add(_value(entity, "simmer", 0))

        assert violated_constraint(session) == f"ck_{entity.__tablename__}_position"


@pytest.mark.parametrize("entity", list(OWN), ids=lambda e: e.__tablename__)
class TestTheLabellersOwnValue:
    def test_it_names_its_line(self, session: DbSession, entity: type[Any]) -> None:
        session.add(_value(entity, "simmer", 1, description=None))

        with pytest.raises(IntegrityError) as raised:
            session.flush()

        assert raised.value.orig.diag.column_name == "description"


@pytest.mark.parametrize("entity", list(BESIDE), ids=lambda e: e.__tablename__)
class TestAValueBesideTheCollectors:
    def test_the_collectors_holds_no_line_and_no_place(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        session.add(_value(entity, "spill", None, description=None))
        session.flush()
        session.expunge_all()

        held = session.get(entity, "spill")
        assert held is not None
        assert (held.description, held.position) == (None, None)

    def test_one_with_a_place_names_its_line(
        self, session: DbSession, entity: type[Any]
    ) -> None:
        """DB 585: a value the labeller declares has a line and a place."""
        session.add(_value(entity, "simmer", 1, description=None))

        assert violated_constraint(session) == f"ck_{entity.__tablename__}_described"


class TestWorkUnitKindNesting:
    def test_a_kind_sits_in_others_and_takes_others_in(
        self, session: DbSession
    ) -> None:
        for place, code in enumerate(("menu", "course", "dish", "garnish"), start=1):
            session.add(_value(WorkUnitKind, code, place))
        session.flush()
        session.add_all(
            [
                WorkUnitKindNesting(inner_code="course", outer_code="menu"),
                WorkUnitKindNesting(inner_code="dish", outer_code="course"),
                WorkUnitKindNesting(inner_code="garnish", outer_code="course"),
                WorkUnitKindNesting(inner_code="garnish", outer_code="dish"),
            ]
        )
        session.flush()

        pairs = session.execute(
            select(
                WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code
            ).order_by(WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code)
        ).all()
        assert pairs == [
            ("course", "menu"),
            ("dish", "course"),
            ("garnish", "course"),
            ("garnish", "dish"),
        ]

    def test_a_pairing_is_held_once(self, session: DbSession) -> None:
        session.add_all(
            [_value(WorkUnitKind, "menu", 1), _value(WorkUnitKind, "dish", 2)]
        )
        session.flush()
        session.add(WorkUnitKindNesting(inner_code="dish", outer_code="menu"))
        session.flush()
        session.expunge_all()
        session.add(WorkUnitKindNesting(inner_code="dish", outer_code="menu"))

        assert violated_constraint(session) == "work_unit_kind_nestings_pkey"

    @pytest.mark.parametrize(
        ("inner", "outer", "key"),
        [
            ("pudding", "menu", "work_unit_kind_nestings_inner_code_fkey"),
            ("menu", "pudding", "work_unit_kind_nestings_outer_code_fkey"),
        ],
    )
    def test_it_pairs_two_kinds_pilot_holds(
        self, session: DbSession, inner: str, outer: str, key: str
    ) -> None:
        session.add(_value(WorkUnitKind, "menu", 1))
        session.flush()
        session.add(WorkUnitKindNesting(inner_code=inner, outer_code=outer))

        assert violated_constraint(session) == key
